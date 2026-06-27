import bpy
from bpy.types import Panel, UILayout, Context, Operator
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty,IntProperty,FloatProperty,EnumProperty
from .humanoid_auto_mapping import auto_map_source_names_to_humanoid,TARGET_LAYOUT
from . import humanoidCorrectionBones

import csv
from math import acos, atan2, cos, degrees, radians, sin
import os
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from bpy_extras import view3d_utils

def PF_armature_filter(self, obj):
    return obj.type == 'ARMATURE'

class HumanoidDeformTagPresetRegistry:
    preset_dir = os.path.join(
        os.path.dirname(__file__),
        "deform_tag_presets",
    )
    no_preset_id = "__NONE__"

    @staticmethod
    def format_name(preset_id):
        return preset_id.strip()

    @classmethod
    def load_file(cls, path):
        tags = {}

        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)

                for row in reader:
                    if len(row) < 2:
                        continue

                    humanoid_name = row[0].strip()
                    deform_name = row[1].strip()

                    if not humanoid_name or humanoid_name.startswith("#"):
                        continue

                    if not deform_name:
                        continue

                    tags[humanoid_name] = deform_name
        except Exception as e:
            print(f"[DeformTag Preset] failed to read {path}: {e}")
            return None

        if not tags:
            return None

        preset_id = os.path.splitext(os.path.basename(path))[0]
        return {
            "id": preset_id,
            "name": cls.format_name(preset_id),
            "path": path,
            "tags": tags,
        }

    @classmethod
    def load_all(cls):
        presets = {}

        if not os.path.isdir(cls.preset_dir):
            return presets

        for filename in sorted(os.listdir(cls.preset_dir)):
            if not filename.endswith(".csv") or filename.startswith("_"):
                continue

            preset = cls.load_file(
                os.path.join(cls.preset_dir, filename),
            )
            if preset is None:
                continue

            presets[preset["id"]] = preset

        return presets

    @staticmethod
    def enum_items(_self, _context):
        presets = HumanoidDeformTagPresetRegistry.load_all()

        if not presets:
            return [(
                HumanoidDeformTagPresetRegistry.no_preset_id,
                "无DeformTag预设",
                "没有找到可用的DeformTag预设",
            )]

        return [
            (
                preset_id,
                preset["name"],
                preset["path"],
            )
            for preset_id, preset in sorted(
                presets.items(),
                key=lambda item: item[1]["name"].lower(),
            )
        ]

    @classmethod
    def selected(cls, scene):
        preset_id = getattr(
            scene,
            "bone_humanoid_deform_tag_preset",
            cls.no_preset_id,
        )

        if preset_id == cls.no_preset_id:
            return None

        return cls.load_all().get(preset_id)

    @classmethod
    def get(cls, preset_id):
        if not preset_id or preset_id == cls.no_preset_id:
            return None

        return cls.load_all().get(preset_id)


def reg_props():
    bpy.types.Scene.bone_constraint_resting_armature = PointerProperty(
        type=bpy.types.Object, poll=PF_armature_filter)
    bpy.types.Scene.bone_constraint_moving_armature = PointerProperty(
        type=bpy.types.Object, poll=PF_armature_filter)
    bpy.types.Scene.bone_humanoid_deform_tag_preset = EnumProperty(
        name="DeformTag预设",
        items=HumanoidDeformTagPresetRegistry.enum_items,
    )
    bpy.types.Scene.bone_humanoid_preview_show_names = BoolProperty(
        name="显示名称",
        default=True,
    )
    bpy.types.Scene.bone_humanoid_preview_show_missing = BoolProperty(
        name="显示缺失骨骼",
        default=True,
    )
    bpy.types.Scene.bone_humanoid_preview_show_check_details = BoolProperty(
        name="显示检查内容",
        default=True,
    )
    bpy.types.Scene.bone_humanoid_preview_show_deform_tags = BoolProperty(
        name="显示DeformTag",
        default=True,
    )
    bpy.types.Scene.bone_humanoid_preview_font_size = IntProperty(
        name="文字大小",
        default=30,
        min=12,
        max=64,
    )

def ureg_props():
    del bpy.types.Scene.bone_constraint_resting_armature
    del bpy.types.Scene.bone_constraint_moving_armature
    del bpy.types.Scene.bone_humanoid_deform_tag_preset
    del bpy.types.Scene.bone_humanoid_preview_show_names
    del bpy.types.Scene.bone_humanoid_preview_show_missing
    del bpy.types.Scene.bone_humanoid_preview_show_check_details
    del bpy.types.Scene.bone_humanoid_preview_show_deform_tags
    del bpy.types.Scene.bone_humanoid_preview_font_size

class OP_SwapBoneConstraintArmatures(Operator):
    bl_idname = "ho.swap_bone_constraint_armatures"
    bl_label = "交换骨架"
    bl_description = "交换当前设置的Resting和Moving骨架"

    def execute(self, context):
        scene = context.scene
        resting = scene.bone_constraint_resting_armature
        moving = scene.bone_constraint_moving_armature

        if resting is None and moving is None:
            self.report({'WARNING'}, "没有设置骨架")
            return {'CANCELLED'}

        scene.bone_constraint_resting_armature = moving
        scene.bone_constraint_moving_armature = resting

        self.report({'INFO'}, "已交换骨架")
        return {'FINISHED'}

class OP_DeformTag_addConstraint(Operator):
    bl_idname = "ho.deformtag_addconstraint"
    bl_label = "按DeformTag添加复制位置旋转约束"
    bl_description = "读取固定骨架骨骼的DeformMappingTag，在移动骨架中按骨名查找形变骨并添加约束；HumanoidMapping 名称包含 twist 的骨只添加复制旋转约束"
    bl_options = {'REGISTER', 'UNDO'}

    """
    关于 ARP deform 骨约束的当前结论：

    之前尝试过在添加约束时检测 fixed/base 骨和 target/deform 骨的 rest 轴向差异，
    然后对轴向变化较大的骨切换 COPY_ROTATION 的坐标空间。这个做法已经确认会引入
    更多不可控问题，所以这里不再做按骨骼轴向差异切换空间的 hack。

    现在这个操作只负责一件事：根据 DeformMappingTag 找到目标 deform 骨，并添加复制位置 /
    复制旋转约束。默认空间保持 Pose Space -> Pose Space，这样约束行为可预期，也方便
    后续定位真正的问题。

    真正需要处理的是 ARP 生成控制器时会自动修正参考骨 / deform 骨本身：
    - 优先方向是检查输入骨架，尽量在生成前发现会触发 ARP 自动修正的骨骼问题；
    - 检查项应该放到 Humanoid 映射检查 / 骨骼规范检查里，而不是塞进约束添加逻辑；
    - 对不可避免的 ARP 修正，需要在预览和检查里明确提示，让用户知道哪些骨可能被修正；
    - 约束流程要容忍修正后的 deform 骨存在，但不要为了个别修正再引入隐式坐标系分支。

    hips 仍然保留两个明确兼容项：
    - COPY_LOCATION head_tail=1.0，用来处理 ARP hips deform 骨头尾方向；
    - COPY_ROTATION 使用 Local With Parent -> Local Space (Owner Orientation)，这是当前实测
      能处理 hips 旋转基准不一致的必要特例。
    这两个特例都只绑定到 hips，不恢复按轴向阈值给任意骨切换坐标系的旧逻辑。

    HumanoidMapping 命中 arm_twist / leg_twist 的骨只添加 COPY_ROTATION:
    - leg_twist 使用 Local Space -> Local Space (Owner Orientation)；
    - arm_twist 使用 Local With Parent -> Local Space (Owner Orientation)。
    如果已经存在同目标的 COPY_LOCATION，会在本操作中移除，避免 twist 骨被位置约束拉动。
    """

    @staticmethod
    def _is_hips_mapping(fixed_bone, props):
        humanoid_mapping = getattr(props, "humanoidMapping", "").strip()
        return humanoid_mapping == "hips" or fixed_bone.name == "hips"

    @staticmethod
    def _is_arm_twist_mapping(props):
        humanoid_mapping = getattr(props, "humanoidMapping", "").strip().lower()
        return "arm" in humanoid_mapping and "twist" in humanoid_mapping

    @staticmethod
    def _is_leg_twist_mapping(props):
        humanoid_mapping = getattr(props, "humanoidMapping", "").strip().lower()
        return "leg" in humanoid_mapping and "twist" in humanoid_mapping

    @classmethod
    def _configure_constraint(
        cls,
        constraint,
        constraint_type,
        target_armature,
        target_bone,
        is_hips_mapping,
        is_arm_twist_mapping,
        is_leg_twist_mapping,
    ):
        constraint.target = target_armature
        constraint.subtarget = target_bone.name

        if constraint_type == 'COPY_ROTATION' and is_arm_twist_mapping:
            constraint.owner_space = 'LOCAL_WITH_PARENT'
            constraint.target_space = 'LOCAL_OWNER_ORIENT'
        elif constraint_type == 'COPY_ROTATION' and is_leg_twist_mapping:
            constraint.owner_space = 'LOCAL'
            constraint.target_space = 'LOCAL_OWNER_ORIENT'
        elif constraint_type == 'COPY_ROTATION' and is_hips_mapping:
            constraint.owner_space = 'LOCAL_WITH_PARENT'
            constraint.target_space = 'LOCAL_OWNER_ORIENT'
        else:
            constraint.owner_space = 'POSE'
            constraint.target_space = 'POSE'

        if constraint_type == 'COPY_LOCATION' and hasattr(constraint, "head_tail"):
            constraint.head_tail = 1.0 if is_hips_mapping else 0.0

        if hasattr(constraint, "mix_mode"):
            constraint.mix_mode = 'REPLACE'

    def execute(self, context):
        scene = context.scene
        fixed_armature = scene.bone_constraint_resting_armature
        target_armature = scene.bone_constraint_moving_armature
        constraint_types = ('COPY_LOCATION', 'COPY_ROTATION')

        if not (fixed_armature and target_armature):
            self.report({'WARNING'}, "需要指定两个骨架")
            return {'CANCELLED'}

        if fixed_armature.type != 'ARMATURE' or target_armature.type != 'ARMATURE':
            self.report({'WARNING'}, "指定对象必须都是Armature")
            return {'CANCELLED'}

        added_count = 0
        existed_count = 0
        replaced_count = 0
        deform_tag_count = 0
        missing_count = 0
        skipped_no_props_count = 0
        skipped_no_deform_tag_count = 0
        configured_existing_count = 0
        hips_head_tail_count = 0
        twist_rotation_only_count = 0
        arm_twist_count = 0
        leg_twist_count = 0
        removed_twist_location_count = 0

        for fixed_bone in fixed_armature.pose.bones:
            props = getattr(fixed_bone.bone, "hotools_boneprops", None)
            if props is None:
                skipped_no_props_count += 1
                continue

            deform_mapping_tag = getattr(
                props,
                "deformMappingTag",
                "",
            ).strip()

            if not deform_mapping_tag:
                skipped_no_deform_tag_count += 1
                continue

            target_bone = target_armature.pose.bones.get(deform_mapping_tag)
            if target_bone is None:
                missing_count += 1
                print(
                    f"[Bone Constraint] DeformMappingTag target missing: "
                    f"fixed={fixed_bone.name}, tag={deform_mapping_tag}"
                )
                continue

            deform_tag_count += 1
            is_hips_mapping = self._is_hips_mapping(fixed_bone, props)
            is_arm_twist_mapping = self._is_arm_twist_mapping(props)
            is_leg_twist_mapping = self._is_leg_twist_mapping(props)
            is_twist_mapping = is_arm_twist_mapping or is_leg_twist_mapping
            bone_constraint_types = (
                ('COPY_ROTATION',)
                if is_twist_mapping
                else constraint_types
            )


            if is_hips_mapping:
                hips_head_tail_count += 1

            if is_twist_mapping:
                twist_rotation_only_count += 1
                if is_arm_twist_mapping:
                    arm_twist_count += 1
                if is_leg_twist_mapping:
                    leg_twist_count += 1

                old_copy_location_constraints = [
                    c for c in fixed_bone.constraints
                    if (
                        c.type == 'COPY_LOCATION'
                        and c.target == target_armature
                        and c.subtarget == target_bone.name
                    )
                ]

                for old_constraint in old_copy_location_constraints:
                    fixed_bone.constraints.remove(old_constraint)
                    removed_twist_location_count += 1

            old_copy_transforms_constraints = [
                c for c in fixed_bone.constraints
                if (
                    c.type == 'COPY_TRANSFORMS'
                    and c.target == target_armature
                    and c.subtarget == target_bone.name
                    and c.name == f"COPY_TRANSFORMS_{target_bone.name}"
                )
            ]

            for old_constraint in old_copy_transforms_constraints:
                fixed_bone.constraints.remove(old_constraint)
                replaced_count += 1

            for constraint_type in bone_constraint_types:
                existing_constraints = [
                    c for c in fixed_bone.constraints
                    if (
                        c.type == constraint_type
                        and c.target == target_armature
                        and c.subtarget == target_bone.name
                    )
                ]

                if existing_constraints:
                    existed_count += 1
                    for existing_constraint in existing_constraints:
                        self._configure_constraint(
                            existing_constraint,
                            constraint_type,
                            target_armature,
                            target_bone,
                            is_hips_mapping,
                            is_arm_twist_mapping,
                            is_leg_twist_mapping,
                        )
                        configured_existing_count += 1

                    continue

                constraint = fixed_bone.constraints.new(constraint_type)
                constraint.name = f"{constraint_type}_{target_bone.name}"
                self._configure_constraint(
                    constraint,
                    constraint_type,
                    target_armature,
                    target_bone,
                    is_hips_mapping,
                    is_arm_twist_mapping,
                    is_leg_twist_mapping,
                )

                added_count += 1


        msg = (
            f"添加约束完成："
            f"新增 {added_count}，"
            f"已存在 {existed_count}，"
            f"未找到 {missing_count}"
        )

        if deform_tag_count:
            msg += f"，DeformTag {deform_tag_count}"

        if replaced_count:
            msg += f"，替换复制变换 {replaced_count}"

        if configured_existing_count:
            msg += f", reconfigured existing {configured_existing_count}"


        if hips_head_tail_count:
            msg += f", hips head_tail=1 {hips_head_tail_count}"

        if twist_rotation_only_count:
            msg += f"，Twist仅旋转 {twist_rotation_only_count}"

        if arm_twist_count:
            msg += f"，ArmTwist {arm_twist_count}"

        if leg_twist_count:
            msg += f"，LegTwist {leg_twist_count}"

        if removed_twist_location_count:
            msg += f"，移除Twist位置约束 {removed_twist_location_count}"

        if skipped_no_deform_tag_count:
            msg += f"，无DeformTag {skipped_no_deform_tag_count}"

        if skipped_no_props_count:
            msg += f"，无属性 {skipped_no_props_count}"

        self.report({'INFO'}, msg)
        return {'FINISHED'}

class OP_BoneApplyConstraint(Operator):
    bl_idname = "ho.bone_apply_constraint"
    bl_label = "应用约束到骨骼"
    bl_description = "将选中骨骼的约束结果应用为当前姿态，并移除约束"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'ARMATURE' and
            context.mode == 'POSE'
        )

    def execute(self, context):
        obj = context.active_object
        pose_bones = context.selected_pose_bones

        if not pose_bones:
            self.report({'WARNING'}, "未选择任何骨骼")
            return {'CANCELLED'}

        # 确保在 Pose 模式
        bpy.ops.object.mode_set(mode='POSE')

        # 1. 应用视觉变换（约束结果）
        bpy.ops.pose.visual_transform_apply()

        # 2. 移除约束
        for pb in pose_bones:
            for c in reversed(pb.constraints):
                pb.constraints.remove(c)


        self.report({'INFO'}, f"已应用 {len(pose_bones)} 根骨骼的约束")
        return {'FINISHED'}
    
class OP_FixedArmature_ClearConstraint(Operator):
    bl_idname = "ho.fixedarmature_clear_constraint"
    bl_label = "清空固定骨架中的所有约束"
    bl_description = "清空固定骨架中的所有约束"

    def execute(self, context):
        scene = context.scene
        fixed_armature = scene.bone_constraint_resting_armature
        if not fixed_armature:
            self.report({'WARNING'}, "需要指定固定骨架")
            return {'CANCELLED'}

        for fixed_bone in fixed_armature.pose.bones:
            constraints_to_remove = [c for c in fixed_bone.constraints]
            for constraint in constraints_to_remove:
                fixed_bone.constraints.remove(constraint)
        return {'FINISHED'}

class OP_BoneRemoveConstraints(Operator):
    bl_idname = "ho.bone_remove_constraints"
    bl_label = "移除骨骼约束"
    bl_description = "移除选中骨骼上的全部约束"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'ARMATURE' and
            context.mode == 'POSE'
        )

    def execute(self, context):
        obj = context.active_object
        pose_bones = context.selected_pose_bones

        if not pose_bones:
            self.report({'WARNING'}, "未选择任何骨骼")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='POSE')

        for pb in pose_bones:
            if not pb.constraints:
                continue

            # 逐个移除约束（倒序，防炸）
            for c in reversed(pb.constraints):
                pb.constraints.remove(c)

        self.report({'INFO'}, "已移除选中骨骼的全部约束")
        return {'FINISHED'}

# TODO ARP 在生成 rig 时会主动修正参考骨 / deform 骨。后续重点不再是给约束添加逻辑堆坐标系 hack，
# 而是把可触发 ARP 修正的骨骼问题前置到检查规则里，并在必须容忍修正结果时给出明确提示。
class OP_Humanoid_ForceAlign(Operator):
    bl_idname = "ho.humanoid_force_align"
    bl_label = "强制Humanoid对齐"
    bl_description = "根据Humanoid映射直接修改moving骨架的EditBone Rest Pose"
    bl_options = {'REGISTER', 'UNDO'}

    align_roll: BoolProperty(name="对齐Roll", default=True)  # type: ignore
    align_tail: BoolProperty(name="对齐Tail", default=True)  # type: ignore
    keep_length: BoolProperty(name="保持原长度", default=False)  # type: ignore
    only_selected: BoolProperty(name="仅处理选中骨骼", default=False)  # type: ignore

    @classmethod
    def poll(cls, context):
        scene = context.scene
        resting = scene.bone_constraint_resting_armature
        moving = scene.bone_constraint_moving_armature

        return (
            resting is not None
            and moving is not None
            and resting.type == 'ARMATURE'
            and moving.type == 'ARMATURE'
        )

    def _edit_bone_depth(self, eb):
        depth = 0
        parent = eb.parent
        while parent:
            depth += 1
            parent = parent.parent
        return depth

    @staticmethod
    def _axis_label_parts(axis_label):
        sign = -1.0 if axis_label.startswith("-") else 1.0
        axis_name = axis_label[-1].upper()

        return sign, axis_name

    @classmethod
    def _actual_axis_from_label(cls, edit_bone, axis_label):
        sign, axis_name = cls._axis_label_parts(axis_label)

        if axis_name == "X":
            return edit_bone.x_axis.normalized() * sign

        if axis_name == "Z":
            return edit_bone.z_axis.normalized() * sign

        if axis_name == "Y":
            return edit_bone.y_axis.normalized() * sign

        return None

    @classmethod
    def _add_axis_direction_roll_candidate(
        cls,
        candidates,
        label,
        checked_axis_label,
        target_axis_local,
        bone_axis_local,
    ):
        sign, axis_name = cls._axis_label_parts(checked_axis_label)
        projected_axis = (
            target_axis_local
            - bone_axis_local * target_axis_local.dot(bone_axis_local)
        )

        score = projected_axis.length
        if score < 1e-6:
            return

        desired_checked_axis = projected_axis.normalized()

        if axis_name == "Z":
            roll_axis_local = desired_checked_axis * sign
        elif axis_name == "X":
            desired_x_axis = desired_checked_axis * sign
            roll_axis_local = desired_x_axis.cross(bone_axis_local)

            if roll_axis_local.length < 1e-6:
                return

            roll_axis_local.normalize()
        else:
            return

        candidates.append({
            "label": label,
            "roll_axis_local": roll_axis_local,
            "score": score,
            "checked_axis_label": checked_axis_label,
            "desired_checked_axis": desired_checked_axis,
        })

    @classmethod
    def _build_source_axis_roll_candidates(
        cls,
        source,
        bone_axis_local,
        moving_rot_inv,
    ):
        candidates = []

        source_z_local = moving_rot_inv @ source["z_axis_world"]
        cls._add_axis_direction_roll_candidate(
            candidates,
            "SOURCE:Z",
            "+Z",
            source_z_local,
            bone_axis_local,
        )

        source_x_local = moving_rot_inv @ source["x_axis_world"]
        cls._add_axis_direction_roll_candidate(
            candidates,
            "SOURCE:X",
            "+X",
            source_x_local,
            bone_axis_local,
        )

        return candidates

    def execute(self, context):
        scene = context.scene
        resting_obj = scene.bone_constraint_resting_armature
        moving_obj = scene.bone_constraint_moving_armature

        if resting_obj == moving_obj:
            self.report({'ERROR'}, "不能对同一个骨架执行")
            return {'CANCELLED'}

        prev_active = context.view_layer.objects.active
        prev_mode = context.mode

        aligned_count = 0
        missing_count = 0
        skipped_count = 0
        roll_aligned_count = 0
        roll_failed_count = 0
        roll_skipped_count = 0
        roll_x_fallback_count = 0
        roll_items = []

        # --------------------------------------------------
        # 1. 读取 resting 骨架数据
        # --------------------------------------------------
        bpy.ops.object.mode_set(mode='OBJECT')
        context.view_layer.objects.active = resting_obj
        resting_obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')

        resting_data = {}

        resting_world = resting_obj.matrix_world.copy()
        resting_rot = resting_world.to_3x3()

        for eb in resting_obj.data.edit_bones:
            bone = resting_obj.data.bones.get(eb.name)
            if bone is None:
                continue

            props = getattr(bone, "hotools_boneprops", None)
            if props is None:
                continue

            mapping = props.humanoidMapping.strip()
            if not mapping:
                continue

            head_world = resting_world @ eb.head
            tail_world = resting_world @ eb.tail
            x_axis_world = (resting_rot @ eb.x_axis).normalized()
            z_axis_world = (resting_rot @ eb.z_axis).normalized()

            if mapping not in resting_data:
                resting_data[mapping] = {
                    "name": str(eb.name),
                    "head_world": head_world.copy(),
                    "tail_world": tail_world.copy(),
                    "x_axis_world": x_axis_world.copy(),
                    "z_axis_world": z_axis_world.copy(),
                }

        # --------------------------------------------------
        # 2. 修改 moving 骨架
        # --------------------------------------------------
        bpy.ops.object.mode_set(mode='OBJECT')
        context.view_layer.objects.active = moving_obj
        moving_obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')

        moving_world_inv = moving_obj.matrix_world.inverted()
        moving_rot_inv = moving_world_inv.to_3x3()

        # 关键：全部断开连接，避免小腿/前臂/手指 head 被父骨 tail 拉回去
        disconnected_count = 0
        for eb in moving_obj.data.edit_bones:
            if eb.use_connect:
                eb.use_connect = False
                disconnected_count += 1

        moving_edit_bones = sorted(
            list(moving_obj.data.edit_bones),
            key=self._edit_bone_depth,
        )

        for moving_eb in moving_edit_bones:
            bone = moving_obj.data.bones.get(moving_eb.name)
            if bone is None:
                skipped_count += 1
                continue

            if self.only_selected and not bone.select:
                continue

            if hasattr(bone, "visible") and not bone.visible:
                continue

            props = getattr(bone, "hotools_boneprops", None)
            if props is None:
                skipped_count += 1
                continue

            mapping = props.humanoidMapping.strip()
            if not mapping:
                continue

            source = resting_data.get(mapping)
            if source is None:
                missing_count += 1
                print(f"[Humanoid Force Align] missing mapping: {mapping}")
                continue

            original_length = moving_eb.length

            head_local = moving_world_inv @ source["head_world"]
            tail_local = moving_world_inv @ source["tail_world"]

            if (tail_local - head_local).length < 1e-6:
                skipped_count += 1
                print(
                    f"[Humanoid Force Align] skipped zero length: "
                    f"{moving_eb.name}"
                )
                continue

            moving_eb.head = head_local

            if self.align_tail:
                moving_eb.tail = tail_local
            else:
                direction = (moving_eb.tail - moving_eb.head).normalized()
                moving_eb.tail = moving_eb.head + direction * original_length

            if self.keep_length:
                direction = (moving_eb.tail - moving_eb.head).normalized()
                moving_eb.tail = moving_eb.head + direction * original_length

            if self.align_roll:
                roll_items.append((moving_eb, mapping, source))

            aligned_count += 1

            print(
                "[Humanoid Force Align] "
                f"{moving_eb.name} <- {source['name']} "
                f"mapping={mapping}"
            )

        if self.align_roll:
            for moving_eb, mapping, source in roll_items:
                try:
                    bone_axis_local = moving_eb.tail - moving_eb.head
                    if bone_axis_local.length < 1e-6:
                        roll_skipped_count += 1
                        print(
                            f"[Humanoid Force Align] roll skipped zero length: "
                            f"{moving_eb.name}, mapping={mapping}"
                        )
                        continue

                    bone_axis_local.normalize()
                    roll_candidates = self._build_source_axis_roll_candidates(
                        source,
                        bone_axis_local,
                        moving_rot_inv,
                    )

                    if not roll_candidates:
                        roll_skipped_count += 1
                        print(
                            f"[Humanoid Force Align] roll skipped parallel: "
                            f"{moving_eb.name}, mapping={mapping}"
                        )
                        continue

                    candidate = max(
                        roll_candidates,
                        key=lambda item: item["score"],
                    )
                    before_roll = moving_eb.roll

                    moving_eb.align_roll(candidate["roll_axis_local"])

                    actual_axis = self._actual_axis_from_label(
                        moving_eb,
                        candidate["checked_axis_label"],
                    )
                    desired_axis = candidate["desired_checked_axis"]

                    if actual_axis is not None and desired_axis.length >= 1e-6:
                        desired_axis = desired_axis.normalized()
                        roll_error_deg = degrees(acos(max(
                            -1.0,
                            min(1.0, actual_axis.dot(desired_axis)),
                        )))
                    else:
                        roll_error_deg = None

                    roll_aligned_count += 1
                    if candidate["checked_axis_label"].endswith("X"):
                        roll_x_fallback_count += 1

                    error_text = (
                        f"{roll_error_deg:.3f}deg"
                        if roll_error_deg is not None
                        else "unknown"
                    )
                    print(
                        f"[Humanoid Force Align] roll: "
                        f"{moving_eb.name}, mapping={mapping}, "
                        f"axis={candidate['label']}, "
                        f"{before_roll:.6f} -> {moving_eb.roll:.6f}, "
                        f"error={error_text}"
                    )

                except Exception as e:
                    roll_failed_count += 1
                    print(
                        f"[Humanoid Force Align] roll align failed: "
                        f"{moving_eb.name}, mapping={mapping}, error={e}"
                    )

        bpy.ops.object.mode_set(mode='OBJECT')

        if prev_active:
            context.view_layer.objects.active = prev_active

        try:
            if prev_mode == 'POSE':
                bpy.ops.object.mode_set(mode='POSE')
            elif prev_mode == 'EDIT_ARMATURE':
                bpy.ops.object.mode_set(mode='EDIT')
            else:
                bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass

        msg = (
            f"Humanoid强制对齐完成："
            f"对齐 {aligned_count}，"
            f"缺失 {missing_count}，"
            f"跳过 {skipped_count}，"
            f"断开连接 {disconnected_count}"
        )

        if roll_failed_count:
            msg += f"，Roll失败 {roll_failed_count}"

        if self.align_roll:
            msg += f"，Roll对齐 {roll_aligned_count}"
            if roll_skipped_count:
                msg += f"，Roll跳过 {roll_skipped_count}"
            if roll_x_fallback_count:
                msg += f"，Roll使用X轴 {roll_x_fallback_count}"

        self.report({'INFO'}, msg)
        return {'FINISHED'}    
    
class OP_Mapping_WriteHumanoidBoneProps(Operator):
    bl_idname = "ho.mapping_write_humanoid_boneprops"
    bl_label = "自动计算选中骨骼的Humanoid映射"
    bl_description = "只检测当前选中的可见骨骼；按住Shift点击会先清空选中骨骼的旧映射"
    bl_options = {'REGISTER', 'UNDO'}

    use_shift: BoolProperty(default=False, options={'HIDDEN'})  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'ARMATURE'

    def invoke(self, context, event):
        self.use_shift = event.shift
        return self.execute(context)

    def _is_bone_visible(self, bone):
        # Blender 4.x: bone.visible 会综合 bone.hide、bone collection 可见性等
        if hasattr(bone, "visible"):
            return bone.visible

        # fallback
        if getattr(bone, "hide", False):
            return False

        return True

    def _collect_selected_visible_bones(self, obj):
        armature = obj.data

        selected = []
        hidden_selected_count = 0

        for bone in armature.bones:
            if not bone.select:
                continue

            if not self._is_bone_visible(bone):
                hidden_selected_count += 1
                continue

            selected.append(bone)

        return selected, hidden_selected_count

    def execute(self, context):
        obj = context.object

        if obj is None or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择一个Armature")
            return {'CANCELLED'}

        bones, hidden_selected_count = self._collect_selected_visible_bones(obj)

        if not bones:
            if hidden_selected_count:
                self.report({'WARNING'}, f"选中的骨骼都不可见或所在骨骼集合隐藏：{hidden_selected_count}")
            else:
                self.report({'WARNING'}, "请先选中需要参与Humanoid映射的骨骼")
            return {'CANCELLED'}

        cleared_count = 0
        skipped_count = 0

        # Shift点击：只清空选中可见骨骼的旧映射
        if self.use_shift:
            for bone in bones:
                props = getattr(bone, "hotools_boneprops", None)
                if props is None:
                    skipped_count += 1
                    continue

                if props.humanoidMapping:
                    props.humanoidMapping = ""
                    cleared_count += 1

        source_names = [bone.name for bone in bones]

        try:
            result = auto_map_source_names_to_humanoid(source_names)
        except Exception as e:
            self.report({'ERROR'}, f"自动Humanoid映射失败: {e}")
            return {'CANCELLED'}

        source_to_target = {
            match.source_name: match.target_name
            for match in result.matches
        }

        written_count = 0

        for bone in bones:
            props = getattr(bone, "hotools_boneprops", None)

            if props is None:
                skipped_count += 1
                continue

            target_name = source_to_target.get(bone.name)

            if target_name:
                props.humanoidMapping = target_name
                written_count += 1

        unmatched_count = len(result.unmatched_sources)
        low_confidence_count = len(result.low_confidence_matches)

        msg = (
            f"选中骨骼Humanoid映射完成："
            f"参与 {len(bones)}，"
            f"写入 {written_count}，"
            f"未匹配 {unmatched_count}，"
            f"低置信度 {low_confidence_count}"
        )

        if self.use_shift:
            msg += f"，清空旧映射 {cleared_count}"

        if hidden_selected_count:
            msg += f"，忽略隐藏选中 {hidden_selected_count}"

        if skipped_count:
            msg += f"，跳过无属性 {skipped_count}"

        self.report({'INFO'}, msg)

        print("[Humanoid Auto Mapping Selected Bones]")
        print(f"Armature: {obj.name}")
        print(f"Selected visible bones: {len(bones)}")
        print(f"Hidden selected ignored: {hidden_selected_count}")
        print(f"Shift clear old mapping: {self.use_shift}")
        print(f"Cleared: {cleared_count}")
        print(f"Written: {written_count}")
        print(f"Unmatched sources: {unmatched_count}")
        print(f"Low confidence: {low_confidence_count}")

        if result.low_confidence_matches:
            print("Low confidence matches:")
            for match in result.low_confidence_matches:
                print(
                    f"  {match.source_name} -> {match.target_name} "
                    f"score={match.score:.1f} "
                    f"reason={match.reason}"
                )

        if result.unmatched_sources:
            print("Unmatched sources:")
            for name in result.unmatched_sources:
                print(f"  {name}")
        
        #刷新预览
        if HumanoidMappingPreviewHUD.is_running():
            bpy.ops.ho.humanoid_mapping_preview_clear()
            bpy.ops.ho.humanoid_mapping_preview_show()

        return {'FINISHED'}


class OP_Mapping_WriteDeformTagsFromHumanoid(Operator):
    bl_idname = "ho.mapping_write_deform_tags_from_humanoid"
    bl_label = "按Humanoid填DeformTag"
    bl_description = "根据当前骨骼的Humanoid映射和选中的DeformTag预设，写入DeformMappingTag"
    bl_options = {'REGISTER', 'UNDO'}

    preset_id: EnumProperty(
        name="DeformTag预设",
        items=HumanoidDeformTagPresetRegistry.enum_items,
    )  # type: ignore

    only_selected: BoolProperty(
        name="仅处理选中骨骼",
        default=False,
    )  # type: ignore

    overwrite_existing: BoolProperty(
        name="覆盖已有DeformTag",
        default=True,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        obj = context.object
        scene = context.scene

        preset = HumanoidDeformTagPresetRegistry.get(self.preset_id)
        if preset is None:
            preset = HumanoidDeformTagPresetRegistry.selected(scene)

        if preset is None:
            self.report({'ERROR'}, "没有可用的DeformTag预设")
            return {'CANCELLED'}

        try:
            scene.bone_humanoid_deform_tag_preset = preset["id"]
        except Exception:
            pass

        tags = preset["tags"]
        processed_count = 0
        written_count = 0
        unchanged_count = 0
        skipped_existing_count = 0
        skipped_no_props_count = 0
        skipped_no_humanoid_count = 0
        missing_preset_count = 0

        for bone in obj.data.bones:
            if self.only_selected and not bone.select:
                continue

            processed_count += 1
            props = getattr(bone, "hotools_boneprops", None)

            if props is None:
                skipped_no_props_count += 1
                continue

            humanoid_name = props.humanoidMapping.strip()
            if not humanoid_name:
                skipped_no_humanoid_count += 1
                continue

            deform_tag = tags.get(humanoid_name)
            if not deform_tag:
                missing_preset_count += 1
                print(
                    f"[DeformTag Preset] missing humanoid entry: "
                    f"bone={bone.name}, humanoid={humanoid_name}, "
                    f"preset={preset['id']}"
                )
                continue

            current_tag = getattr(props, "deformMappingTag", "").strip()
            if current_tag and not self.overwrite_existing:
                skipped_existing_count += 1
                continue

            if current_tag == deform_tag:
                unchanged_count += 1
                continue

            props.deformMappingTag = deform_tag
            written_count += 1

            print(
                f"[DeformTag Preset] write: "
                f"{bone.name}, humanoid={humanoid_name}, "
                f"deformTag={deform_tag}, preset={preset['id']}"
            )

        msg = (
            f"DeformTag填入完成："
            f"预设 {preset['name']}，"
            f"处理 {processed_count}，"
            f"写入 {written_count}，"
            f"未变化 {unchanged_count}"
        )

        if skipped_existing_count:
            msg += f"，保留已有 {skipped_existing_count}"

        if skipped_no_humanoid_count:
            msg += f"，无Humanoid {skipped_no_humanoid_count}"

        if missing_preset_count:
            msg += f"，预设缺失 {missing_preset_count}"

        if skipped_no_props_count:
            msg += f"，无属性 {skipped_no_props_count}"

        if HumanoidMappingPreviewHUD.is_running():
            bpy.ops.ho.humanoid_mapping_preview_clear()
            bpy.ops.ho.humanoid_mapping_preview_show()

        self.report({'INFO'}, msg)
        return {'FINISHED'}


class OP_Mapping_ClearHumanoidBoneProps(Operator):
    bl_idname = "ho.mapping_clear_humanoid_boneprops"
    bl_label = "清空骨架Humanoid映射"
    bl_description = "清空当前活动骨架中所有骨骼的Humanoid映射"
    bl_options = {'REGISTER', 'UNDO'}

    only_selected: BoolProperty(
        name="仅清空选中骨骼",
        default=False,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        obj = context.object
        bones = obj.data.bones

        cleared_count = 0
        skipped_count = 0

        for bone in bones:
            if self.only_selected and not bone.select:
                continue

            props = getattr(bone, "hotools_boneprops", None)
            if props is None:
                skipped_count += 1
                continue

            if props.humanoidMapping:
                props.humanoidMapping = ""
                cleared_count += 1

        msg = f"已清空Humanoid映射：{cleared_count}"
        if skipped_count:
            msg += f"，跳过无属性 {skipped_count}"
        
        #刷新预览
        if HumanoidMappingPreviewHUD.is_running():
            bpy.ops.ho.humanoid_mapping_preview_clear()
            bpy.ops.ho.humanoid_mapping_preview_show()

        self.report({'INFO'}, msg)
        return {'FINISHED'}

def _safe_normalized_vector(vector):
    if vector.length < 1e-6:
        return None

    return vector.normalized()


class HumanoidBoneSample:
    def __init__(
        self,
        bone_name,
        mapping_name,
        head_world,
        tail_world,
        axes_world,
        bone=None,
        pose_bone=None,
        edit_bone=None,
    ):
        self.bone_name = bone_name
        self.mapping_name = mapping_name
        self.head_world = head_world
        self.tail_world = tail_world
        self.center_world = (head_world + tail_world) * 0.5
        self.axes_world = axes_world
        self.bone = bone
        self.pose_bone = pose_bone
        self.edit_bone = edit_bone

    def points(self):
        return self.head_world, self.tail_world, self.center_world


class HumanoidTwistCheckContext:
    _axis_indices = {
        "X": 0,
        "Y": 1,
        "Z": 2,
    }

    def __init__(
        self,
        bone_name,
        mapping_name,
        axes,
        armature=None,
        bone=None,
        pose_bone=None,
        head_world=None,
        tail_world=None,
        center_world=None,
        mapping_to_bone_name=None,
        mapping_to_sample=None,
        bone_name_to_sample=None,
    ):
        self.bone_name = bone_name
        self.mapping_name = mapping_name
        self.axes = axes
        self.armature = armature
        self.bone = bone
        self.pose_bone = pose_bone
        self.head_world = head_world
        self.tail_world = tail_world
        self.center_world = center_world
        self.mapping_to_bone_name = mapping_to_bone_name or {}
        self.mapping_to_sample = mapping_to_sample or {}
        self.bone_name_to_sample = bone_name_to_sample or {}

    def axis(self, axis_label):
        sign = -1.0 if axis_label.startswith("-") else 1.0
        axis_name = axis_label[-1].upper()
        index = self._axis_indices.get(axis_name)

        if index is None:
            return None

        return self.axes[index] * sign

    @staticmethod
    def project_to_roll_plane(direction, bone_axis):
        projected = direction - bone_axis * direction.dot(bone_axis)
        return _safe_normalized_vector(projected)

    @staticmethod
    def angle_between_degrees(a, b):
        dot = max(-1.0, min(1.0, a.dot(b)))
        return degrees(acos(dot))

    def bone_name_for_mapping(self, mapping_name):
        sample = self.sample_for_mapping(mapping_name)
        if sample is not None:
            return sample.bone_name

        return self.mapping_to_bone_name.get(mapping_name)

    def sample_for_mapping(self, mapping_name):
        return self.mapping_to_sample.get(mapping_name)

    def sample_for_bone_name(self, bone_name):
        return self.bone_name_to_sample.get(bone_name)

    def pose_points_for_bone_name(self, bone_name):
        sample = self.sample_for_bone_name(bone_name)
        if sample is not None:
            return sample.points()

        if self.armature is None:
            return None

        pb = self.armature.pose.bones.get(bone_name)
        if pb is None:
            return None

        head = self.armature.matrix_world @ pb.head
        tail = self.armature.matrix_world @ pb.tail
        center = (head + tail) * 0.5

        return head, tail, center

    def pose_points_for_mapping(self, mapping_name):
        sample = self.sample_for_mapping(mapping_name)
        if sample is not None:
            return sample.points()

        bone_name = self.bone_name_for_mapping(mapping_name)
        if not bone_name:
            return None

        return self.pose_points_for_bone_name(bone_name)


class HumanoidTwistCheckMode:
    idname = "base"

    def evaluate(self, rule, context):
        raise NotImplementedError


class HumanoidAxisDirectionTwistMode(HumanoidTwistCheckMode):
    idname = "axis_direction"

    def __init__(
        self,
        checked_axis,
        target_world,
        target_label,
        roll_axis="+Y",
        threshold_deg=30.0,
    ):
        self.checked_axis = checked_axis
        self.target_world = Vector(target_world)
        self.target_label = target_label
        self.roll_axis = roll_axis
        self.threshold_deg = threshold_deg

    def evaluate(self, rule, context):
        actual_axis_world = context.axis(self.checked_axis)
        bone_axis_world = context.axis(self.roll_axis)

        if actual_axis_world is None or bone_axis_world is None:
            return None

        actual_axis = context.project_to_roll_plane(
            actual_axis_world,
            bone_axis_world,
        )
        target_axis = context.project_to_roll_plane(
            self.target_world,
            bone_axis_world,
        )

        if actual_axis is None or target_axis is None:
            return None

        angle_deg = context.angle_between_degrees(actual_axis, target_axis)

        if angle_deg <= self.threshold_deg:
            return None

        return {
            "rule_name": rule.name,
            "mode": self.idname,
            "mapping_name": context.mapping_name,
            "axis_label": self.checked_axis,
            "target_label": self.target_label,
            "angle_deg": angle_deg,
            "threshold_deg": self.threshold_deg,
            "actual_axis_world": actual_axis,
            "target_axis_world": target_axis,
            "bone_axis_world": bone_axis_world,
        }


class HumanoidIkBendDirectionTwistMode(HumanoidTwistCheckMode):
    idname = "ik_bend_direction"

    def __init__(
        self,
        upper_mapping_name,
        lower_mapping_name,
        target_world=(0.0, 1.0, 0.0),
        target_label="世界+Y",
        threshold_deg=30.0,
    ):
        self.upper_mapping_name = upper_mapping_name
        self.lower_mapping_name = lower_mapping_name
        self.target_world = Vector(target_world)
        self.target_label = target_label
        self.threshold_deg = threshold_deg

    def evaluate(self, rule, context):
        upper_points = context.pose_points_for_mapping(self.upper_mapping_name)
        lower_points = context.pose_points_for_mapping(self.lower_mapping_name)

        if upper_points is None or lower_points is None:
            return None

        upper_head, upper_tail, _ = upper_points
        lower_head, lower_tail, _ = lower_points

        root_point = upper_head
        middle_point = (upper_tail + lower_head) * 0.5
        end_point = lower_tail

        triangle_normal = _safe_normalized_vector(
            (middle_point - root_point).cross(end_point - root_point)
        )
        if triangle_normal is None:
            return None

        chain_vector = end_point - root_point
        chain_axis = _safe_normalized_vector(chain_vector)
        if chain_axis is None:
            return None

        projection_point = (
            root_point
            + chain_axis * (middle_point - root_point).dot(chain_axis)
        )
        ik_direction = _safe_normalized_vector(middle_point - projection_point)
        target_axis = _safe_normalized_vector(self.target_world)

        if ik_direction is None or target_axis is None:
            return None

        angle_deg = context.angle_between_degrees(ik_direction, target_axis)

        if angle_deg <= self.threshold_deg:
            return None

        visual_length = max(
            (end_point - root_point).length * 0.35,
            0.08,
        )
        fan_axis = _safe_normalized_vector(target_axis.cross(ik_direction))
        if fan_axis is None:
            fan_axis = triangle_normal

        return {
            "rule_name": rule.name,
            "mode": self.idname,
            "mapping_name": context.mapping_name,
            "axis_label": "IK弯曲",
            "target_label": self.target_label,
            "angle_deg": angle_deg,
            "threshold_deg": self.threshold_deg,
            "actual_axis_world": ik_direction,
            "target_axis_world": target_axis,
            "bone_axis_world": chain_axis,
            "fan_axis_world": fan_axis,
            "visual_origin_world": middle_point,
            "visual_axis_length": visual_length,
            "ik_projection_world": projection_point,
            "ik_middle_world": middle_point,
            "ik_direction_end_world": middle_point + ik_direction * visual_length,
            "ik_triangle_points_world": (root_point, middle_point, end_point),
            "ik_triangle_normal_world": triangle_normal,
        }


class HumanoidTwistRule:
    def __init__(self, name, mapping_names, mode):
        self.name = name
        self.mapping_names = set(mapping_names)
        self.mode = mode

    def matches(self, mapping_name):
        return mapping_name in self.mapping_names

    def evaluate(self, context):
        if not self.matches(context.mapping_name):
            return None

        return self.mode.evaluate(self, context)


class HumanoidTwistRuleRegistry:
    def __init__(self):
        self._rules = []

    def register(self, rule):
        self._rules.append(rule)
        return rule

    def evaluate(self, context):
        issues = []

        for rule in self._rules:
            issue = rule.evaluate(context)
            if issue is not None:
                issues.append(issue)

        return issues

    def rules(self):
        return tuple(self._rules)


class HumanoidWarningCheckContext:
    def __init__(
        self,
        bone_name,
        mapping_name,
        bone=None,
        edit_bone=None,
    ):
        self.bone_name = bone_name
        self.mapping_name = mapping_name
        self.bone = bone
        self.edit_bone = edit_bone

    def source_bone(self):
        if self.edit_bone is not None:
            return self.edit_bone

        return self.bone


class HumanoidWarningCheckMode:
    idname = "base"

    def evaluate(self, rule, context):
        raise NotImplementedError


class HumanoidDisconnectedBoneWarningMode(HumanoidWarningCheckMode):
    idname = "disconnected_bone"

    def __init__(
        self,
        expected_connected=False,
        message="相连项未关闭",
    ):
        self.expected_connected = expected_connected
        self.message = message

    def evaluate(self, rule, context):
        source_bone = context.source_bone()
        if source_bone is None:
            return None

        actual_connected = bool(getattr(source_bone, "use_connect", False))
        if actual_connected == self.expected_connected:
            return None

        return {
            "rule_name": rule.name,
            "mode": self.idname,
            "mapping_name": context.mapping_name,
            "message": self.message,
            "actual_connected": actual_connected,
            "expected_connected": self.expected_connected,
        }


class HumanoidWarningRule:
    def __init__(self, name, mapping_names, mode):
        self.name = name
        self.mapping_names = set(mapping_names)
        self.mode = mode

    def matches(self, mapping_name):
        return mapping_name in self.mapping_names

    def evaluate(self, context):
        if not self.matches(context.mapping_name):
            return None

        return self.mode.evaluate(self, context)


class HumanoidWarningRuleRegistry:
    def __init__(self):
        self._rules = []

    def register(self, rule):
        self._rules.append(rule)
        return rule

    def evaluate(self, context):
        warnings = []

        for rule in self._rules:
            warning = rule.evaluate(context)
            if warning is not None:
                warnings.append(warning)

        return warnings

    def rules(self):
        return tuple(self._rules)


HUMANOID_TWIST_RULES = HumanoidTwistRuleRegistry()
HUMANOID_WARNING_RULES = HumanoidWarningRuleRegistry()

_WORLD_NEG_Y = (0.0, -1.0, 0.0)
_WORLD_POS_X = (1.0, 0.0, 0.0)


def _register_axis_direction_twist_rule(
    mapping_name,
    checked_axis,
    target_world,
    target_label,
    roll_axis="+Y",
    threshold_deg=30.0,
):
    return HUMANOID_TWIST_RULES.register(HumanoidTwistRule(
        name=f"{mapping_name}: {checked_axis} -> {target_label}",
        mapping_names=(mapping_name,),
        mode=HumanoidAxisDirectionTwistMode(
            checked_axis=checked_axis,
            target_world=target_world,
            target_label=target_label,
            roll_axis=roll_axis,
            threshold_deg=threshold_deg,
        ),
    ))


def _register_ik_bend_direction_twist_rule(
    mapping_name,
    upper_mapping_name,
    lower_mapping_name,
    target_world=(0.0, 1.0, 0.0),
    target_label="世界+Y",
    threshold_deg=30.0,
):
    return HUMANOID_TWIST_RULES.register(HumanoidTwistRule(
        name=f"{mapping_name}: IK弯曲 -> {target_label}",
        mapping_names=(mapping_name,),
        mode=HumanoidIkBendDirectionTwistMode(
            upper_mapping_name=upper_mapping_name,
            lower_mapping_name=lower_mapping_name,
            target_world=target_world,
            target_label=target_label,
            threshold_deg=threshold_deg,
        ),
    ))


def _register_disconnected_bone_warning_rule(
    mapping_name,
    expected_connected=False,
    message="相连项未关闭",
):
    return HUMANOID_WARNING_RULES.register(HumanoidWarningRule(
        name=f"{mapping_name}: 相连项关闭建议",
        mapping_names=(mapping_name,),
        mode=HumanoidDisconnectedBoneWarningMode(
            expected_connected=expected_connected,
            message=message,
        ),
    ))


# 黄色警告规则注册区：每条规则独立注册，方便后续针对具体骨骼调整。
_register_disconnected_bone_warning_rule(
    mapping_name="hips",
)
_register_disconnected_bone_warning_rule(
    mapping_name="spine",
)
_register_disconnected_bone_warning_rule(
    mapping_name="chest",
)
_register_disconnected_bone_warning_rule(
    mapping_name="neck",
)
_register_disconnected_bone_warning_rule(
    mapping_name="head",
)


# 扭转规则注册区：每条规则独立注册，方便后续单独改阈值或替换判定模式。
_register_axis_direction_twist_rule(
    mapping_name="shoulder.L",
    checked_axis="+X",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)
_register_axis_direction_twist_rule(
    mapping_name="upper_arm.L",
    checked_axis="+X",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)
_register_axis_direction_twist_rule(
    mapping_name="lower_arm.L",
    checked_axis="+X",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)
_register_axis_direction_twist_rule(
    mapping_name="hand.L",
    checked_axis="+X",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)
_register_axis_direction_twist_rule(
    mapping_name="upper_leg.L",
    checked_axis="+X",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)
_register_axis_direction_twist_rule(
    mapping_name="lower_leg.L",
    checked_axis="+X",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)

_register_axis_direction_twist_rule(
    mapping_name="shoulder.R",
    checked_axis="-X",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)
_register_axis_direction_twist_rule(
    mapping_name="upper_arm.R",
    checked_axis="-X",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)
_register_axis_direction_twist_rule(
    mapping_name="lower_arm.R",
    checked_axis="-X",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)
_register_axis_direction_twist_rule(
    mapping_name="hand.R",
    checked_axis="-X",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)
_register_axis_direction_twist_rule(
    mapping_name="upper_leg.R",
    checked_axis="-X",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)
_register_axis_direction_twist_rule(
    mapping_name="lower_leg.R",
    checked_axis="-X",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)

_register_axis_direction_twist_rule(
    mapping_name="hips",
    checked_axis="+Z",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)
_register_axis_direction_twist_rule(
    mapping_name="hips",
    checked_axis="+X",
    target_world=_WORLD_POS_X,
    target_label="世界+X",
)
_register_axis_direction_twist_rule(
    mapping_name="spine",
    checked_axis="+Z",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)
_register_axis_direction_twist_rule(
    mapping_name="spine",
    checked_axis="+X",
    target_world=_WORLD_POS_X,
    target_label="世界+X",
)
_register_axis_direction_twist_rule(
    mapping_name="chest",
    checked_axis="+Z",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)
_register_axis_direction_twist_rule(
    mapping_name="chest",
    checked_axis="+X",
    target_world=_WORLD_POS_X,
    target_label="世界+X",
)
_register_axis_direction_twist_rule(
    mapping_name="neck",
    checked_axis="+Z",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)
_register_axis_direction_twist_rule(
    mapping_name="neck",
    checked_axis="+X",
    target_world=_WORLD_POS_X,
    target_label="世界+X",
)
_register_axis_direction_twist_rule(
    mapping_name="head",
    checked_axis="+Z",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)
_register_axis_direction_twist_rule(
    mapping_name="head",
    checked_axis="+X",
    target_world=_WORLD_POS_X,
    target_label="世界+X",
)

_register_ik_bend_direction_twist_rule(
    mapping_name="lower_arm.L",
    upper_mapping_name="upper_arm.L",
    lower_mapping_name="lower_arm.L",
)
_register_ik_bend_direction_twist_rule(
    mapping_name="lower_arm.R",
    upper_mapping_name="upper_arm.R",
    lower_mapping_name="lower_arm.R",
)
_register_ik_bend_direction_twist_rule(
    mapping_name="lower_leg.L",
    upper_mapping_name="upper_leg.L",
    lower_mapping_name="lower_leg.L",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)
_register_ik_bend_direction_twist_rule(
    mapping_name="lower_leg.R",
    upper_mapping_name="upper_leg.R",
    lower_mapping_name="lower_leg.R",
    target_world=_WORLD_NEG_Y,
    target_label="世界-Y",
)


class HumanoidMappingPreviewHUD:
    _handler_3d = None
    _handler_2d = None
    _timer_running = False

    _timer_interval = 1.0  # 固定低频刷新，避免属性面板卡顿

    _armature = None
    _armature_name = ""
    _items = []
    _missing_targets = []

    _line_width = 7.0
    _point_size = 8.0

    _font_size = 30
    _line_length_x = 60
    _line_length_y = 22

    _line_end_offset_x = 18
    _line_end_offset_y = 16
    _label_stagger = 12

    _missing_font_size = 30
    _missing_line_height = 30
    _missing_origin_offset_x = -40
    _missing_origin_offset_y = -40
    _missing_max_show = 40

    _twist_axis_length_factor = 0.36
    _twist_axis_min_length = 0.08
    _twist_line_width = 4.0
    _twist_fan_segments = 18
    _twist_font_size = 24
    _twist_warning_offset_y = 30

    @staticmethod
    def no_i18n(name: str) -> str:
        return "\u200B".join(name)

    @staticmethod
    def _scene_setting(name, default):
        scene = getattr(bpy.context, "scene", None)
        if scene is None:
            return default

        return getattr(scene, name, default)

    @classmethod
    def _show_names(cls):
        return bool(cls._scene_setting(
            "bone_humanoid_preview_show_names",
            True,
        ))

    @classmethod
    def _show_missing_targets(cls):
        return bool(cls._scene_setting(
            "bone_humanoid_preview_show_missing",
            True,
        ))

    @classmethod
    def _show_check_details(cls):
        return bool(cls._scene_setting(
            "bone_humanoid_preview_show_check_details",
            True,
        ))

    @classmethod
    def _show_deform_tags(cls):
        return bool(cls._scene_setting(
            "bone_humanoid_preview_show_deform_tags",
            True,
        ))

    @classmethod
    def _font_size_value(cls):
        return int(cls._scene_setting(
            "bone_humanoid_preview_font_size",
            cls._font_size,
        ))

    @classmethod
    def _twist_font_size_value(cls):
        return max(12, int(cls._font_size_value() * 0.8))

    @classmethod
    def _missing_font_size_value(cls):
        return cls._font_size_value()

    @classmethod
    def _missing_line_height_value(cls):
        return max(18, int(cls._missing_font_size_value() * 1.0))

    @classmethod
    def is_running(cls):
        return cls._handler_2d is not None or cls._handler_3d is not None

    @classmethod
    def _get_armature(cls):
        if cls._armature is not None:
            try:
                if cls._armature.name in bpy.data.objects:
                    return cls._armature
            except ReferenceError:
                pass

        if cls._armature_name:
            obj = bpy.data.objects.get(cls._armature_name)
            if obj and obj.type == 'ARMATURE':
                cls._armature = obj
                return obj

        return None

    @classmethod
    def _get_bone_mapping_name(cls, bone_name: str) -> str:
        armature = cls._get_armature()
        if armature is None:
            return ""

        bone = armature.data.bones.get(bone_name)
        if bone is None:
            return ""

        props = getattr(bone, "hotools_boneprops", None)
        if props is None:
            return ""

        return props.humanoidMapping.strip()

    @classmethod
    def _get_bone_deform_mapping_tag(cls, bone_name: str) -> str:
        armature = cls._get_armature()
        if armature is None:
            return ""

        bone = armature.data.bones.get(bone_name)
        if bone is None:
            return ""

        props = getattr(bone, "hotools_boneprops", None)
        if props is None:
            return ""

        return getattr(props, "deformMappingTag", "").strip()

    @staticmethod
    def _is_editing_armature(armature):
        context = bpy.context

        return (
            context.mode == 'EDIT_ARMATURE'
            and getattr(context, "edit_object", None) == armature
        )

    @classmethod
    def _make_axes_from_matrix(cls, matrix):
        x_axis = _safe_normalized_vector(matrix @ Vector((1.0, 0.0, 0.0)))
        y_axis = _safe_normalized_vector(matrix @ Vector((0.0, 1.0, 0.0)))
        z_axis = _safe_normalized_vector(matrix @ Vector((0.0, 0.0, 1.0)))

        if x_axis is None or y_axis is None or z_axis is None:
            return None

        return x_axis, y_axis, z_axis

    @classmethod
    def _make_axes_from_edit_bone(cls, armature, edit_bone):
        rot_world = armature.matrix_world.to_3x3()

        x_axis = _safe_normalized_vector(rot_world @ edit_bone.x_axis)
        y_axis = _safe_normalized_vector(rot_world @ edit_bone.y_axis)
        z_axis = _safe_normalized_vector(rot_world @ edit_bone.z_axis)

        if x_axis is None or y_axis is None or z_axis is None:
            return None

        return x_axis, y_axis, z_axis

    @classmethod
    def _get_bone_world_rest_axes(cls, bone_name: str):
        armature = cls._get_armature()
        if armature is None:
            return None

        bone = armature.data.bones.get(bone_name)
        if bone is None:
            return None

        rest_rot_world = (
            armature.matrix_world.to_3x3()
            @ bone.matrix_local.to_3x3()
        )

        return cls._make_axes_from_matrix(rest_rot_world)

    @classmethod
    def _build_bone_samples(cls):
        armature = cls._get_armature()
        if armature is None:
            return []

        world = armature.matrix_world
        samples = []

        if cls._is_editing_armature(armature):
            for eb in armature.data.edit_bones:
                mapping_name = cls._get_bone_mapping_name(eb.name)
                if not mapping_name:
                    continue

                axes = cls._make_axes_from_edit_bone(armature, eb)
                if axes is None:
                    continue

                bone = armature.data.bones.get(eb.name)
                samples.append(HumanoidBoneSample(
                    bone_name=eb.name,
                    mapping_name=mapping_name,
                    head_world=world @ eb.head,
                    tail_world=world @ eb.tail,
                    axes_world=axes,
                    bone=bone,
                    edit_bone=eb,
                ))

            return samples

        for pb in armature.pose.bones:
            mapping_name = cls._get_bone_mapping_name(pb.name)
            if not mapping_name:
                continue

            axes = cls._get_bone_world_rest_axes(pb.name)
            if axes is None:
                continue

            samples.append(HumanoidBoneSample(
                bone_name=pb.name,
                mapping_name=mapping_name,
                head_world=world @ pb.head,
                tail_world=world @ pb.tail,
                axes_world=axes,
                bone=pb.bone,
                pose_bone=pb,
            ))

        return samples

    @classmethod
    def _get_twist_issues(
        cls,
        sample,
        mapping_to_bone_name=None,
        mapping_to_sample=None,
        bone_name_to_sample=None,
    ):
        if sample is None or sample.axes_world is None:
            return []

        armature = cls._get_armature()

        context = HumanoidTwistCheckContext(
            bone_name=sample.bone_name,
            mapping_name=sample.mapping_name,
            axes=sample.axes_world,
            armature=armature,
            bone=sample.bone,
            pose_bone=sample.pose_bone,
            head_world=sample.head_world,
            tail_world=sample.tail_world,
            center_world=sample.center_world,
            mapping_to_bone_name=mapping_to_bone_name,
            mapping_to_sample=mapping_to_sample,
            bone_name_to_sample=bone_name_to_sample,
        )

        return HUMANOID_TWIST_RULES.evaluate(context)

    @classmethod
    def _format_twist_issues(cls, issues):
        parts = []

        for issue in issues:
            parts.append(
                f"{issue['axis_label']}->{issue['target_label']} "
                f"{issue['angle_deg']:.0f}°>{issue['threshold_deg']:.0f}°"
            )

        return " / ".join(parts)

    @classmethod
    def _get_connection_warnings(cls, sample):
        if sample is None:
            return []

        context = HumanoidWarningCheckContext(
            bone_name=sample.bone_name,
            mapping_name=sample.mapping_name,
            bone=sample.bone,
            edit_bone=sample.edit_bone,
        )

        return HUMANOID_WARNING_RULES.evaluate(context)

    @classmethod
    def _format_connection_warnings(cls, warnings):
        return " / ".join(
            warning["message"]
            for warning in warnings
        )

    @classmethod
    def _refresh_mapping_cache(cls):
        armature = cls._get_armature()
        if armature is None:
            cls._items = []
            cls._missing_targets = []
            return

        target_names = [item[0] for item in TARGET_LAYOUT]

        mapped_targets = set()
        items = []
        samples = cls._build_bone_samples()
        mapping_to_bone_name = {}
        mapping_to_sample = {}
        bone_name_to_sample = {}

        for sample in samples:
            mapping_name = sample.mapping_name
            if not mapping_name:
                continue

            mapped_targets.add(mapping_name)
            bone_name_to_sample[sample.bone_name] = sample

            if mapping_name not in mapping_to_bone_name:
                mapping_to_bone_name[mapping_name] = sample.bone_name
                mapping_to_sample[mapping_name] = sample

        for sample in samples:
            if not sample.mapping_name:
                continue

            items.append({
                "bone_name": sample.bone_name,
                "sample": sample,
                "twist_issues": cls._get_twist_issues(
                    sample,
                    mapping_to_bone_name=mapping_to_bone_name,
                    mapping_to_sample=mapping_to_sample,
                    bone_name_to_sample=bone_name_to_sample,
                ),
                "connection_warnings": cls._get_connection_warnings(sample),
            })

        cls._items = items
        cls._missing_targets = [
            name for name in target_names
            if name not in mapped_targets
        ]

    @classmethod
    def show(cls, context: Context, armature_obj: bpy.types.Object):
        cls.clear()

        if armature_obj is None or armature_obj.type != 'ARMATURE':
            return False, "请选择Armature"

        cls._armature = armature_obj
        cls._armature_name = armature_obj.name

        cls._refresh_mapping_cache()

        cls._handler_3d = bpy.types.SpaceView3D.draw_handler_add(
            cls._draw_3d,
            (),
            'WINDOW',
            'POST_VIEW',
        )

        cls._handler_2d = bpy.types.SpaceView3D.draw_handler_add(
            cls._draw_2d,
            (),
            'WINDOW',
            'POST_PIXEL',
        )

        if not cls._timer_running:
            cls._timer_running = True
            bpy.app.timers.register(cls._timer)

        cls._tag_redraw()

        twist_error_bone_count = sum(
            1 for item in cls._items
            if item.get("twist_issues")
        )
        connection_warning_bone_count = sum(
            1 for item in cls._items
            if item.get("connection_warnings")
        )
        msg = (
            f"Humanoid预览已生成："
            f"映射骨骼 {len(cls._items)}，"
            f"缺失 {len(cls._missing_targets)}"
        )

        if twist_error_bone_count:
            msg += f"，扭转错误 {twist_error_bone_count}"

        if connection_warning_bone_count:
            msg += f"，相连警告 {connection_warning_bone_count}"

        return True, msg

    @classmethod
    def clear(cls):
        if cls._handler_3d is not None:
            bpy.types.SpaceView3D.draw_handler_remove(
                cls._handler_3d,
                'WINDOW',
            )

        if cls._handler_2d is not None:
            bpy.types.SpaceView3D.draw_handler_remove(
                cls._handler_2d,
                'WINDOW',
            )

        cls._handler_3d = None
        cls._handler_2d = None
        cls._timer_running = False

        cls._armature = None
        cls._armature_name = ""
        cls._items = []
        cls._missing_targets = []

        cls._tag_redraw()

    @classmethod
    def _get_pose_bone_world_points(cls, bone_name: str):
        armature = cls._get_armature()
        if armature is None:
            return None

        pb = armature.pose.bones.get(bone_name)
        if pb is None:
            return None

        head = armature.matrix_world @ pb.head
        tail = armature.matrix_world @ pb.tail
        center = (head + tail) * 0.5

        return head, tail, center

    @classmethod
    def _get_item_world_points(cls, item):
        sample = item.get("sample")
        if sample is not None:
            return sample.points()

        return cls._get_pose_bone_world_points(item["bone_name"])

    @classmethod
    def _refresh_live_edit_cache_if_needed(cls):
        armature = cls._get_armature()
        if armature is None:
            return

        if cls._is_editing_armature(armature):
            cls._refresh_mapping_cache()

    @classmethod
    def _timer(cls):
        if cls._handler_3d is None and cls._handler_2d is None:
            cls._timer_running = False
            return None

        cls._refresh_mapping_cache()
        cls._tag_redraw()

        return cls._timer_interval

    @staticmethod
    def _tag_redraw():
        wm = bpy.context.window_manager
        if wm is None:
            return

        for window in wm.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

    @staticmethod
    def _rotate_vector_around_axis(vector, axis, angle_rad):
        axis = axis.normalized()

        return (
            vector * cos(angle_rad)
            + axis.cross(vector) * sin(angle_rad)
            + axis * axis.dot(vector) * (1.0 - cos(angle_rad))
        )

    @classmethod
    def _append_fan_geometry(
        cls,
        triangles,
        borders,
        origin,
        base_axis,
        fan_axis,
        radius,
        signed_angle,
    ):
        if abs(signed_angle) < 1e-6:
            return

        fan_points = []
        for i in range(cls._twist_fan_segments + 1):
            factor = i / cls._twist_fan_segments
            angle = signed_angle * factor
            fan_direction = cls._rotate_vector_around_axis(
                base_axis,
                fan_axis,
                angle,
            )
            fan_points.append(origin + fan_direction * radius)

        for i in range(len(fan_points) - 1):
            triangles.extend([
                origin,
                fan_points[i],
                fan_points[i + 1],
            ])

        borders.extend([
            origin,
            fan_points[0],
            origin,
            fan_points[-1],
        ])

        for i in range(len(fan_points) - 1):
            borders.extend([
                fan_points[i],
                fan_points[i + 1],
            ])

    @classmethod
    def _draw_3d(cls):
        cls._refresh_live_edit_cache_if_needed()

        if not cls._items:
            return

        region = bpy.context.region
        if region is None:
            return

        normal_coords = []
        warning_coords = []
        error_coords = []
        normal_points = []
        warning_points = []
        error_points = []
        actual_axis_coords = []
        target_axis_coords = []
        ik_triangle_triangles = []
        ik_triangle_edges = []
        angle_fan_triangles = []
        angle_fan_border_coords = []
        threshold_fan_triangles = []
        threshold_fan_border_coords = []
        show_check_details = cls._show_check_details()

        for item in cls._items:
            result = cls._get_item_world_points(item)
            if result is None:
                continue

            head, tail, center = result
            twist_issues = item.get("twist_issues") or []
            connection_warnings = item.get("connection_warnings") or []

            if twist_issues:
                error_coords.extend([head, tail])
                error_points.extend([head, tail])

                bone_length = max((tail - head).length, cls._twist_axis_min_length)
                axis_length = max(
                    bone_length * cls._twist_axis_length_factor,
                    cls._twist_axis_min_length,
                )

                for issue in twist_issues:
                    if not show_check_details:
                        continue

                    actual_axis = issue["actual_axis_world"]
                    target_axis = issue["target_axis_world"]
                    bone_axis = issue["bone_axis_world"]
                    fan_axis_world = issue.get("fan_axis_world", bone_axis)
                    visual_origin = issue.get("visual_origin_world", center)
                    visual_axis_length = issue.get(
                        "visual_axis_length",
                        axis_length,
                    )
                    actual_axis_coords.extend([
                        visual_origin,
                        visual_origin + actual_axis * visual_axis_length,
                    ])
                    target_axis_coords.extend([
                        visual_origin,
                        visual_origin + target_axis * visual_axis_length,
                    ])

                    if issue.get("mode") == "ik_bend_direction":
                        triangle_points = issue.get("ik_triangle_points_world")
                        if triangle_points and len(triangle_points) == 3:
                            root_point, middle_point, end_point = triangle_points
                            ik_triangle_triangles.extend([
                                root_point,
                                middle_point,
                                end_point,
                            ])
                            ik_triangle_edges.extend([
                                root_point,
                                middle_point,
                                middle_point,
                                end_point,
                                end_point,
                                root_point,
                            ])

                    fan_axis = _safe_normalized_vector(fan_axis_world)
                    if fan_axis is not None:
                        signed_angle = atan2(
                            fan_axis.dot(target_axis.cross(actual_axis)),
                            max(-1.0, min(1.0, target_axis.dot(actual_axis))),
                        )
                        threshold_rad = radians(issue["threshold_deg"])
                        threshold_angle = (
                            1.0 if signed_angle >= 0.0 else -1.0
                        ) * min(abs(signed_angle), threshold_rad)

                        cls._append_fan_geometry(
                            angle_fan_triangles,
                            angle_fan_border_coords,
                            visual_origin,
                            target_axis,
                            fan_axis,
                            visual_axis_length,
                            signed_angle,
                        )
                        cls._append_fan_geometry(
                            threshold_fan_triangles,
                            threshold_fan_border_coords,
                            visual_origin,
                            target_axis,
                            fan_axis,
                            visual_axis_length,
                            threshold_angle,
                        )
            elif connection_warnings:
                warning_coords.extend([head, tail])
                warning_points.extend([head, tail])
            else:
                normal_coords.extend([head, tail])
                normal_points.extend([head, tail])

        if not normal_coords and not warning_coords and not error_coords:
            return

        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')

        line_shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')

        def draw_lines(coords, color, width):
            if not coords:
                return

            batch = batch_for_shader(line_shader, 'LINES', {
                "pos": coords,
            })

            line_shader.bind()
            line_shader.uniform_float(
                "viewportSize",
                (region.width, region.height),
            )
            line_shader.uniform_float("lineWidth", width)
            line_shader.uniform_float("color", color)
            batch.draw(line_shader)

        if ik_triangle_triangles:
            triangle_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            triangle_batch = batch_for_shader(triangle_shader, 'TRIS', {
                "pos": ik_triangle_triangles,
            })

            triangle_shader.bind()
            triangle_shader.uniform_float("color", (1.0, 0.76, 0.05, 0.12))
            triangle_batch.draw(triangle_shader)

        if angle_fan_triangles:
            fan_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            fan_batch = batch_for_shader(fan_shader, 'TRIS', {
                "pos": angle_fan_triangles,
            })

            fan_shader.bind()
            fan_shader.uniform_float("color", (1.0, 0.42, 0.05, 0.18))
            fan_batch.draw(fan_shader)

        if threshold_fan_triangles:
            threshold_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            threshold_batch = batch_for_shader(threshold_shader, 'TRIS', {
                "pos": threshold_fan_triangles,
            })

            threshold_shader.bind()
            threshold_shader.uniform_float("color", (0.45, 1.0, 0.45, 0.22))
            threshold_batch.draw(threshold_shader)

        draw_lines(normal_coords, (0.1, 0.85, 1.0, 0.95), cls._line_width)
        draw_lines(warning_coords, (1.0, 0.82, 0.08, 0.98), cls._line_width)
        draw_lines(error_coords, (1.0, 0.08, 0.04, 0.98), cls._line_width)
        draw_lines(ik_triangle_edges, (1.0, 0.78, 0.1, 0.92), 3.0)
        draw_lines(angle_fan_border_coords, (1.0, 0.62, 0.05, 0.72), 2.0)
        draw_lines(threshold_fan_border_coords, (0.55, 1.0, 0.55, 0.82), 2.0)
        draw_lines(target_axis_coords, (0.25, 1.0, 0.25, 0.95), cls._twist_line_width)
        draw_lines(actual_axis_coords, (1.0, 0.08, 0.04, 0.98), cls._twist_line_width)

        if normal_points or warning_points or error_points:
            point_shader = gpu.shader.from_builtin('UNIFORM_COLOR')

            gpu.state.point_size_set(cls._point_size)

            if normal_points:
                point_batch = batch_for_shader(point_shader, 'POINTS', {
                    "pos": normal_points,
                })

                point_shader.bind()
                point_shader.uniform_float("color", (1.0, 0.9, 0.15, 0.95))
                point_batch.draw(point_shader)

            if warning_points:
                point_batch = batch_for_shader(point_shader, 'POINTS', {
                    "pos": warning_points,
                })

                point_shader.bind()
                point_shader.uniform_float("color", (1.0, 0.82, 0.08, 0.98))
                point_batch.draw(point_shader)

            if error_points:
                point_batch = batch_for_shader(point_shader, 'POINTS', {
                    "pos": error_points,
                })

                point_shader.bind()
                point_shader.uniform_float("color", (1.0, 0.08, 0.04, 0.98))
                point_batch.draw(point_shader)

            gpu.state.point_size_set(1.0)

        gpu.state.blend_set('NONE')
        gpu.state.depth_test_set('LESS_EQUAL')

    @classmethod
    def _draw_2d(cls):
        cls._refresh_live_edit_cache_if_needed()

        armature = cls._get_armature()
        if armature is None:
            return

        context = bpy.context
        region = context.region
        rv3d = context.region_data

        if region is None or rv3d is None:
            return

        font_id = 0

        line_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        show_names = cls._show_names()
        show_check_details = cls._show_check_details()
        show_deform_tags = cls._show_deform_tags()
        font_size = cls._font_size_value()
        twist_font_size = cls._twist_font_size_value()

        for index, item in enumerate(cls._items):
            bone_name = item["bone_name"]
            mapping_name = cls._get_bone_mapping_name(bone_name)
            deform_mapping_tag = cls._get_bone_deform_mapping_tag(bone_name)
            if not mapping_name:
                continue

            result = cls._get_item_world_points(item)
            if result is None:
                continue

            head, tail, center = result
            twist_issues = item.get("twist_issues") or []
            connection_warnings = item.get("connection_warnings") or []
            if (
                not show_names
                and not show_deform_tags
                and not (
                    show_check_details
                    and (twist_issues or connection_warnings)
                )
            ):
                continue

            pos_2d = view3d_utils.location_3d_to_region_2d(
                region,
                rv3d,
                center,
            )

            if pos_2d is None:
                continue

            x, y = pos_2d

            label_x = x + cls._line_length_x
            label_y = (
                y
                + cls._line_length_y
                + (index % 3) * cls._label_stagger
            )

            coords = [
                (x, y),
                (
                    label_x - cls._line_end_offset_x,
                    label_y + cls._line_end_offset_y,
                ),
            ]

            batch = batch_for_shader(line_shader, 'LINES', {
                "pos": coords,
            })

            line_color = (
                (1.0, 0.08, 0.04, 0.92)
                if twist_issues
                else (
                    (1.0, 0.82, 0.08, 0.92)
                    if connection_warnings
                    else (0.1, 0.85, 1.0, 0.85)
                )
            )

            line_shader.bind()
            line_shader.uniform_float("color", line_color)
            batch.draw(line_shader)

            if show_names or show_deform_tags:
                if show_names and show_deform_tags:
                    deform_label = (
                        deform_mapping_tag
                        if deform_mapping_tag
                        else "<NO_DEFORM_TAG>"
                    )
                    label = f'{mapping_name} -> {deform_label}  ({bone_name})'
                elif show_deform_tags:
                    deform_label = (
                        deform_mapping_tag
                        if deform_mapping_tag
                        else "<NO_DEFORM_TAG>"
                    )
                    label = f'DeformTag: {deform_label}'
                else:
                    label = f'{mapping_name}  ({bone_name})'

                label = cls.no_i18n(label)

                blf.size(font_id, font_size)
                blf.enable(font_id, blf.SHADOW)
                blf.shadow(font_id, 3, 0, 0, 0, 0.75)
                blf.shadow_offset(font_id, 1, -1)

                if twist_issues:
                    blf.color(font_id, 1.0, 0.16, 0.1, 1.0)
                elif connection_warnings:
                    blf.color(font_id, 1.0, 0.82, 0.08, 1.0)
                else:
                    blf.color(font_id, 0.75, 0.95, 1.0, 1.0)

                blf.position(font_id, label_x, label_y, 0)
                blf.draw(font_id, label)

            if show_check_details and (twist_issues or connection_warnings):
                blf.size(font_id, twist_font_size)
                blf.enable(font_id, blf.SHADOW)
                blf.shadow(font_id, 3, 0, 0, 0, 0.75)
                blf.shadow_offset(font_id, 1, -1)

                detail_y = label_y - max(
                    cls._twist_warning_offset_y,
                    twist_font_size,
                )
                detail_step = max(18, twist_font_size)

                if twist_issues:
                    warning_label = (
                        f"扭转错误: {cls._format_twist_issues(twist_issues)}"
                    )
                    blf.color(font_id, 1.0, 0.46, 0.25, 1.0)
                    blf.position(font_id, label_x, detail_y, 0)
                    blf.draw(font_id, cls.no_i18n(warning_label))
                    detail_y -= detail_step

                if connection_warnings:
                    warning_label = (
                        "相连警告: "
                        f"{cls._format_connection_warnings(connection_warnings)}"
                    )
                    blf.color(font_id, 1.0, 0.82, 0.08, 1.0)
                    blf.position(font_id, label_x, detail_y, 0)
                    blf.draw(font_id, cls.no_i18n(warning_label))

            blf.disable(font_id, blf.SHADOW)

        if cls._missing_targets and cls._show_missing_targets():
            origin_2d = view3d_utils.location_3d_to_region_2d(
                region,
                rv3d,
                armature.matrix_world.translation,
            )

            if origin_2d is not None:
                ox, oy = origin_2d

                x = ox + cls._missing_origin_offset_x
                y = oy + cls._missing_origin_offset_y

                coords = [
                    (ox, oy),
                    (x - 8, y + 6),
                ]

                batch = batch_for_shader(line_shader, 'LINES', {
                    "pos": coords,
                })

                line_shader.bind()
                line_shader.uniform_float("color", (1.0, 0.15, 0.1, 0.9))
                batch.draw(line_shader)

                missing_font_size = cls._missing_font_size_value()
                missing_line_height = cls._missing_line_height_value()

                blf.size(font_id, missing_font_size + 2)
                blf.enable(font_id, blf.SHADOW)
                blf.shadow(font_id, 5, 0, 0, 0, 0.85)
                blf.shadow_offset(font_id, 1, -1)

                blf.color(font_id, 1.0, 0.2, 0.15, 1.0)
                blf.position(font_id, x, y, 0)
                blf.draw(
                    font_id,
                    cls.no_i18n(f"缺失Humanoid骨骼: {len(cls._missing_targets)}")
                )

                blf.size(font_id, missing_font_size)

                max_show = cls._missing_max_show

                for i, name in enumerate(cls._missing_targets[:max_show]):
                    line_y = y - 24 - i * missing_line_height

                    blf.position(font_id, x + 20, line_y, 0)
                    blf.draw(font_id, cls.no_i18n(f"✕ {name}"))

                remain = len(cls._missing_targets) - max_show
                if remain > 0:
                    line_y = y - 24 - max_show * missing_line_height

                    blf.position(font_id, x + 20, line_y, 0)
                    blf.draw(font_id, cls.no_i18n(f"... 还有 {remain} 个"))

                blf.disable(font_id, blf.SHADOW)

        gpu.state.blend_set('NONE')

class OP_HumanoidMappingPreview_Show(Operator):
    bl_idname = "ho.humanoid_mapping_preview_show"
    bl_label = "预览Humanoid映射"
    bl_description = """使用活动骨架物体的Humanoid映射绘制预览，如果已有预览则先清除"""

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        obj = context.object

        ok, msg = HumanoidMappingPreviewHUD.show(context, obj)

        if not ok:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        self.report({'INFO'}, msg)
        return {'FINISHED'}

class OP_HumanoidMappingPreview_Clear(Operator):
    bl_idname = "ho.humanoid_mapping_preview_clear"
    bl_label = "清除Humanoid映射预览"
    bl_description = "清除Humanoid映射绘制预览"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        HumanoidMappingPreviewHUD.clear()
        self.report({'INFO'}, "Humanoid映射预览已清除")
        return {'FINISHED'}


def drawBoneHumanoidPanel(layout: UILayout, context: Context):
    scene = context.scene

    mapping_box = layout.box()
    mapping_box.label(text="骨骼处理")

    row = mapping_box.row(align=True)
    row.operator(OP_Mapping_WriteHumanoidBoneProps.bl_idname,text="自动映射",)
    row.operator(OP_Mapping_ClearHumanoidBoneProps.bl_idname,text="",icon="TRASH",)

    humanoidCorrectionBones.correctionBones.drawHumanoidCorrectionBonesPanel(
        mapping_box,
        context,
    )

    row = mapping_box.row(align=True)
    row.prop(
        scene,
        "bone_humanoid_deform_tag_preset",
        text="",
    )
    op = row.operator(
        OP_Mapping_WriteDeformTagsFromHumanoid.bl_idname,
        text="填入DeformTag",
        icon="PRESET",
    )
    op.preset_id = scene.bone_humanoid_deform_tag_preset

    layout.separator(factor=1)
    preview_box = layout.box()
    header = preview_box.row(align=True)
    header.label(text="Humanoid检查预览")

    if HumanoidMappingPreviewHUD.is_running():
        header.alert = True
        header.operator(
            OP_HumanoidMappingPreview_Clear.bl_idname,
            text="关闭预览",
            icon="PANEL_CLOSE",
        )
        header.alert = False
    else:
        header.operator(
            OP_HumanoidMappingPreview_Show.bl_idname,
            text="开启预览",
            icon="HIDE_OFF",
        )

    col = preview_box.column(align=True)
    row = col.row(align=True)
    row.prop(
        scene,
        "bone_humanoid_preview_show_names",
        toggle=True,
    )
    row.prop(
        scene,
        "bone_humanoid_preview_show_missing",
        toggle=True,
    )
    row.prop(
        scene,
        "bone_humanoid_preview_show_deform_tags",
        toggle=True,
    )

    row = col.row(align=True)
    row.prop(
        scene,
        "bone_humanoid_preview_show_check_details",
        toggle=True,
    )
    row.prop(scene, "bone_humanoid_preview_font_size")


    layout.separator(factor=1)
    box = layout.box()
    box.label(text="Humanoid映射")

    row = box.row(align=True)
    row.prop_search(scene, "bone_constraint_resting_armature",scene,"objects",text="固定",icon="ARMATURE_DATA",)
    row.operator(OP_SwapBoneConstraintArmatures.bl_idname,text="",icon="ARROW_LEFTRIGHT",)
    row.prop_search(scene,"bone_constraint_moving_armature",scene,"objects",text="移动",icon="ARMATURE_DATA",)

    col = box.column(align=True)
    row = col.row(align=True)
    row.operator(OP_Humanoid_ForceAlign.bl_idname,text="强制Humanoid对齐",icon="CON_ARMATURE",)

    row = col.row(align=True)
    
    row.operator(OP_DeformTag_addConstraint.bl_idname,text="约束-位置旋转",)
    row.operator(OP_FixedArmature_ClearConstraint.bl_idname,text="",icon="TRASH",)

    row = box.row(align=True)
    row.operator(OP_BoneApplyConstraint.bl_idname,text="应用约束到骨骼",)
    row.operator(OP_BoneRemoveConstraints.bl_idname,text="移除骨骼约束",)

cls = [
    OP_SwapBoneConstraintArmatures,
    OP_DeformTag_addConstraint,
    OP_BoneApplyConstraint,
    OP_FixedArmature_ClearConstraint,
    OP_BoneRemoveConstraints,
    OP_Mapping_WriteHumanoidBoneProps,
    OP_Mapping_WriteDeformTagsFromHumanoid,
    OP_Mapping_ClearHumanoidBoneProps,
    OP_HumanoidMappingPreview_Show,
    OP_HumanoidMappingPreview_Clear,
    OP_Humanoid_ForceAlign,
]

def register():
    for i in cls:
        bpy.utils.register_class(i)
    humanoidCorrectionBones.register()
    reg_props()


def unregister():
    humanoidCorrectionBones.unregister()
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
