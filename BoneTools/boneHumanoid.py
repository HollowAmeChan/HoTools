# TODO:目前很难用，还很容易不小心把骨架搞坏，OP_Humanoid_ForceAlign对于扭转的识别很奇怪。arp的ref与deform骨命名很恶心奇怪，自动处理要做好很hack。以及用户需要首先把ref吸到自己的骨架上（需要自动map一次），然后生成对齐的deform层，然后自己的骨架又要使用约束吸到rig骨架上（这里用的交换运动骨架物体，然后使用deform层的map，所以ref的map要删掉重新给deformmap，这很傻逼），这整个流程中ref强制吸附+约束吸附可以完全整合成一整个无脑操作
import bpy
from bpy.types import Panel, UILayout, Context, Operator
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty,IntProperty,EnumProperty
from .humanoid_auto_mapping import auto_map_source_names_to_humanoid,TARGET_LAYOUT

import blf
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from bpy_extras import view3d_utils
from ..i18n import tr

def PF_armature_filter(self, obj):
    return obj.type == 'ARMATURE'

def reg_props():
    bpy.types.Scene.bone_constraint_resting_armature = PointerProperty(
        type=bpy.types.Object, poll=PF_armature_filter)
    bpy.types.Scene.bone_constraint_moving_armature = PointerProperty(
        type=bpy.types.Object, poll=PF_armature_filter)

def ureg_props():
    del bpy.types.Scene.bone_constraint_resting_armature
    del bpy.types.Scene.bone_constraint_moving_armature

class OP_SwapBoneConstraintArmatures(Operator):
    bl_idname = "ho.swap_bone_constraint_armatures"
    bl_label = "交换骨架"
    bl_description = "交换当前设置的Resting和Moving骨架"
    
    @classmethod
    def description(cls, context, properties):
        return tr("交换当前设置的Resting和Moving骨架")

    def execute(self, context):
        scene = context.scene
        resting = scene.bone_constraint_resting_armature
        moving = scene.bone_constraint_moving_armature

        if resting is None and moving is None:
            self.report({'WARNING'}, tr("没有设置骨架"))
            return {'CANCELLED'}

        scene.bone_constraint_resting_armature = moving
        scene.bone_constraint_moving_armature = resting

        self.report({'INFO'}, tr("已交换骨架"))
        return {'FINISHED'}

class OP_SameNameBone_addConstraint(Operator):
    bl_idname = "ho.samenamebone_addconstraint"
    bl_label = "按映射添加约束"
    bl_description = "根据humanoid映射，确定对应的pair，添加约束"
    
    @classmethod
    def description(cls, context, properties):
        return tr("根据humanoid映射，确定对应的pair，添加约束")
    bl_options = {'REGISTER', 'UNDO'}

    constraint_type: bpy.props.StringProperty(
        name="Constraint Type",
        default="COPY_LOCATION",
    )  # type: ignore

    def execute(self, context):
        scene = context.scene
        resting_armature = scene.bone_constraint_resting_armature
        moving_armature = scene.bone_constraint_moving_armature

        if not (resting_armature and moving_armature):
            self.report({'WARNING'}, tr("需要指定两个骨架"))
            return {'CANCELLED'}

        if resting_armature.type != 'ARMATURE' or moving_armature.type != 'ARMATURE':
            self.report({'WARNING'}, tr("指定对象必须都是Armature"))
            return {'CANCELLED'}

        # humanoidMapping -> resting pose bone
        resting_mapping_map = {}
        duplicate_resting_mappings = set()

        for resting_bone in resting_armature.pose.bones:
            props = getattr(resting_bone.bone, "hotools_boneprops", None)
            if props is None:
                continue

            mapping_name = props.humanoidMapping.strip()
            if not mapping_name:
                continue

            if mapping_name in resting_mapping_map:
                duplicate_resting_mappings.add(mapping_name)
                continue

            resting_mapping_map[mapping_name] = resting_bone

        added_count = 0
        existed_count = 0
        fallback_count = 0
        missing_count = 0
        skipped_no_mapping_count = 0

        for moving_bone in moving_armature.pose.bones:
            resting_bone = None

            props = getattr(moving_bone.bone, "hotools_boneprops", None)
            mapping_name = ""

            if props is not None:
                mapping_name = props.humanoidMapping.strip()

            if mapping_name:
                resting_bone = resting_mapping_map.get(mapping_name)
            else:
                skipped_no_mapping_count += 1

            # fallback：如果映射找不到，则尝试同名骨骼
            if resting_bone is None:
                resting_bone = resting_armature.pose.bones.get(moving_bone.name)
                if resting_bone is not None:
                    fallback_count += 1

            if resting_bone is None:
                missing_count += 1
                print(
                    f"[Bone Constraint] 未找到对应骨骼: "
                    f"moving={moving_bone.name}, mapping={mapping_name or '<EMPTY>'}"
                )
                continue

            existing_constraints = [
                c for c in moving_bone.constraints
                if (
                    c.type == self.constraint_type
                    and c.target == resting_armature
                    and c.subtarget == resting_bone.name
                )
            ]

            if existing_constraints:
                existed_count += 1
                print(
                    f"[Bone Constraint] 已存在: "
                    f"{moving_bone.name} -> {resting_bone.name} "
                    f"{self.constraint_type}"
                )
                continue

            constraint = moving_bone.constraints.new(self.constraint_type)
            constraint.name = f"{self.constraint_type}_{resting_bone.name}"
            constraint.target = resting_armature
            constraint.subtarget = resting_bone.name

            added_count += 1

            print(
                f"[Bone Constraint] 添加: "
                f"{moving_bone.name} -> {resting_bone.name} "
                f"mapping={mapping_name or '<SAME_NAME>'} "
                f"type={self.constraint_type}"
            )

        if duplicate_resting_mappings:
            print("[Bone Constraint] resting骨架存在重复humanoidMapping:")
            for name in sorted(duplicate_resting_mappings):
                print(f"  {name}")

        msg = (
            f"添加约束完成："
            f"新增 {added_count}，"
            f"已存在 {existed_count}，"
            f"同名回退 {fallback_count}，"
            f"未找到 {missing_count}"
        )

        if skipped_no_mapping_count:
            msg += f"，moving无映射 {skipped_no_mapping_count}"

        if duplicate_resting_mappings:
            msg += f"，resting重复映射 {len(duplicate_resting_mappings)}"

        self.report({'INFO'}, msg)
        return {'FINISHED'}

class OP_BoneApplyConstraint(Operator):
    bl_idname = "ho.bone_apply_constraint"
    bl_label = "应用约束到骨骼"
    bl_description = "将选中骨骼的约束结果应用为当前姿态，并移除约束"
    
    @classmethod
    def description(cls, context, properties):
        return tr("将选中骨骼的约束结果应用为当前姿态，并移除约束")
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
            self.report({'WARNING'}, tr("未选择任何骨骼"))
            return {'CANCELLED'}

        # 确保在 Pose 模式
        bpy.ops.object.mode_set(mode='POSE')

        # 1. 应用视觉变换（约束结果）
        bpy.ops.pose.visual_transform_apply()

        # 2. 移除约束
        for pb in pose_bones:
            for c in reversed(pb.constraints):
                pb.constraints.remove(c)


        self.report({'INFO'}, tr("已应用 {0} 根骨骼的约束").format(len(pose_bones)))
        return {'FINISHED'}
    
class OP_movingArmture_clear_constraint(Operator):
    bl_idname = "ho.movingarmture_clear_constraint"
    bl_label = "清空移动骨架中的所有约束"
    bl_description = "清空移动骨架中的所有约束"
    
    @classmethod
    def description(cls, context, properties):
        return tr("清空移动骨架中的所有约束")

    def execute(self, context):
        scene = context.scene
        moving_armature = scene.bone_constraint_moving_armature
        if not moving_armature:
            self.report({'WARNING'}, tr("需要指定移动骨架"))
            return {'CANCELLED'}

        # 遍历目标骨架的每个骨骼，并删除所有指定类型的约束
        for moving_bone in moving_armature.pose.bones:
            # 直接删除目标骨骼上的所有指定类型的约束
            constraints_to_remove = [c for c in moving_bone.constraints]
            for constraint in constraints_to_remove:
                moving_bone.constraints.remove(constraint)
        return {'FINISHED'}

class OP_BoneRemoveConstraints(Operator):
    bl_idname = "ho.bone_remove_constraints"
    bl_label = "移除骨骼约束"
    bl_description = "移除选中骨骼上的全部约束"
    
    @classmethod
    def description(cls, context, properties):
        return tr("移除选中骨骼上的全部约束")
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
            self.report({'WARNING'}, tr("未选择任何骨骼"))
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='POSE')

        for pb in pose_bones:
            if not pb.constraints:
                continue

            # 逐个移除约束（倒序，防炸）
            for c in reversed(pb.constraints):
                pb.constraints.remove(c)

        self.report({'INFO'}, tr("已移除选中骨骼的全部约束"))
        return {'FINISHED'}

class OP_Humanoid_ForceAlign(Operator):
    bl_idname = "ho.humanoid_force_align"
    bl_label = "强制Humanoid对齐"
    bl_description = "根据Humanoid映射直接修改moving骨架的EditBone Rest Pose"
    
    @classmethod
    def description(cls, context, properties):
        return tr("根据Humanoid映射直接修改moving骨架的EditBone Rest Pose")
    bl_options = {'REGISTER', 'UNDO'}

    align_roll: BoolProperty(name="对齐Roll", default=True)  # type: ignore
    align_tail: BoolProperty(name="对齐Tail", default=True)  # type: ignore
    keep_length: BoolProperty(name="保持原长度", default=False)  # type: ignore
    only_selected: BoolProperty(name="仅处理选中骨骼", default=True)  # type: ignore

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

    def execute(self, context):
        scene = context.scene
        resting_obj = scene.bone_constraint_resting_armature
        moving_obj = scene.bone_constraint_moving_armature

        if resting_obj == moving_obj:
            self.report({'ERROR'}, tr("不能对同一个骨架执行"))
            return {'CANCELLED'}

        prev_active = context.view_layer.objects.active
        prev_mode = context.mode

        aligned_count = 0
        missing_count = 0
        skipped_count = 0
        roll_failed_count = 0

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
            z_axis_world = (resting_rot @ eb.z_axis).normalized()

            if mapping not in resting_data:
                resting_data[mapping] = {
                    "name": str(eb.name),
                    "head_world": head_world.copy(),
                    "tail_world": tail_world.copy(),
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
                try:
                    roll_axis_local = (
                        moving_rot_inv @ source["z_axis_world"]
                    ).normalized()

                    moving_eb.align_roll(roll_axis_local)

                except Exception as e:
                    roll_failed_count += 1
                    print(
                        f"[Humanoid Force Align] roll align failed: "
                        f"{moving_eb.name}, mapping={mapping}, error={e}"
                    )

            aligned_count += 1

            print(
                "[Humanoid Force Align] "
                f"{moving_eb.name} <- {source['name']} "
                f"mapping={mapping}"
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

        self.report({'INFO'}, msg)
        return {'FINISHED'}    
    
class OP_Mapping_WriteHumanoidBoneProps(Operator):
    bl_idname = "ho.mapping_write_humanoid_boneprops"
    bl_label = "自动计算选中骨骼的Humanoid映射"
    bl_description = "只检测当前选中的可见骨骼；按住Shift点击会先清空选中骨骼的旧映射"
    
    @classmethod
    def description(cls, context, properties):
        return tr("只检测当前选中的可见骨骼；按住Shift点击会先清空选中骨骼的旧映射")
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
            self.report({'ERROR'}, tr("请选择一个Armature"))
            return {'CANCELLED'}

        bones, hidden_selected_count = self._collect_selected_visible_bones(obj)

        if not bones:
            if hidden_selected_count:
                self.report({'WARNING'}, tr("选中的骨骼都不可见或所在骨骼集合隐藏：{0}").format(hidden_selected_count))
            else:
                self.report({'WARNING'}, tr("请先选中需要参与Humanoid映射的骨骼"))
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
            self.report({'ERROR'}, tr("自动Humanoid映射失败: {0}").format(e))
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

class OP_Mapping_ClearHumanoidBoneProps(Operator):
    bl_idname = "ho.mapping_clear_humanoid_boneprops"
    bl_label = "清空骨架Humanoid映射"
    bl_description = "清空当前活动骨架中所有骨骼的Humanoid映射"
    
    @classmethod
    def description(cls, context, properties):
        return tr("清空当前活动骨架中所有骨骼的Humanoid映射")
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

    @staticmethod
    def no_i18n(name: str) -> str:
        return "\u200B".join(name)

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
    def _refresh_mapping_cache(cls):
        armature = cls._get_armature()
        if armature is None:
            cls._items = []
            cls._missing_targets = []
            return

        target_names = [item[0] for item in TARGET_LAYOUT]

        mapped_targets = set()
        items = []

        for pb in armature.pose.bones:
            mapping_name = cls._get_bone_mapping_name(pb.name)
            if not mapping_name:
                continue

            mapped_targets.add(mapping_name)
            items.append({
                "bone_name": pb.name,
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

        return True, (
            f"Humanoid预览已生成："
            f"映射骨骼 {len(cls._items)}，"
            f"缺失 {len(cls._missing_targets)}"
        )

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

    @classmethod
    def _draw_3d(cls):
        if not cls._items:
            return

        region = bpy.context.region
        if region is None:
            return

        coords = []
        points = []

        for item in cls._items:
            result = cls._get_pose_bone_world_points(item["bone_name"])
            if result is None:
                continue

            head, tail, center = result
            coords.extend([head, tail])
            points.extend([head, tail])

        if not coords:
            return

        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')

        shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINES', {
            "pos": coords,
        })

        shader.bind()
        shader.uniform_float("viewportSize", (region.width, region.height))
        shader.uniform_float("lineWidth", cls._line_width)
        shader.uniform_float("color", (0.1, 0.85, 1.0, 0.95))
        batch.draw(shader)

        if points:
            point_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            point_batch = batch_for_shader(point_shader, 'POINTS', {
                "pos": points,
            })

            gpu.state.point_size_set(cls._point_size)
            point_shader.bind()
            point_shader.uniform_float("color", (1.0, 0.9, 0.15, 0.95))
            point_batch.draw(point_shader)
            gpu.state.point_size_set(1.0)

        gpu.state.blend_set('NONE')
        gpu.state.depth_test_set('LESS_EQUAL')

    @classmethod
    def _draw_2d(cls):
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

        for index, item in enumerate(cls._items):
            bone_name = item["bone_name"]
            mapping_name = cls._get_bone_mapping_name(bone_name)
            if not mapping_name:
                continue

            result = cls._get_pose_bone_world_points(bone_name)
            if result is None:
                continue

            head, tail, center = result

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

            line_shader.bind()
            line_shader.uniform_float("color", (0.1, 0.85, 1.0, 0.85))
            batch.draw(line_shader)

            label = f'{mapping_name}  ({bone_name})'
            label = cls.no_i18n(label)

            blf.size(font_id, cls._font_size)
            blf.enable(font_id, blf.SHADOW)
            blf.shadow(font_id, 3, 0, 0, 0, 0.75)
            blf.shadow_offset(font_id, 1, -1)

            blf.color(font_id, 0.75, 0.95, 1.0, 1.0)
            blf.position(font_id, label_x, label_y, 0)
            blf.draw(font_id, label)

            blf.disable(font_id, blf.SHADOW)

        if cls._missing_targets:
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

                blf.size(font_id, cls._missing_font_size + 2)
                blf.enable(font_id, blf.SHADOW)
                blf.shadow(font_id, 5, 0, 0, 0, 0.85)
                blf.shadow_offset(font_id, 1, -1)

                blf.color(font_id, 1.0, 0.2, 0.15, 1.0)
                blf.position(font_id, x, y, 0)
                blf.draw(
                    font_id,
                    cls.no_i18n(f"缺失Humanoid骨骼: {len(cls._missing_targets)}")
                )

                blf.size(font_id, cls._missing_font_size)

                max_show = cls._missing_max_show

                for i, name in enumerate(cls._missing_targets[:max_show]):
                    line_y = y - 24 - i * cls._missing_line_height

                    blf.position(font_id, x + 20, line_y, 0)
                    blf.draw(font_id, cls.no_i18n(f"✕ {name}"))

                remain = len(cls._missing_targets) - max_show
                if remain > 0:
                    line_y = y - 24 - max_show * cls._missing_line_height

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
    
    @classmethod
    def description(cls, context, properties):
        return tr("清除Humanoid映射绘制预览")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        HumanoidMappingPreviewHUD.clear()
        self.report({'INFO'}, tr("Humanoid映射预览已清除"))
        return {'FINISHED'}


def drawBoneHumanoidPanel(layout: UILayout, context: Context):
    scene = context.scene

    box = layout.box()
    box.label(text=tr("Humanoid映射"))

    row = box.row(align=True)

    if HumanoidMappingPreviewHUD.is_running():
        row.alert = True
        row.operator(OP_HumanoidMappingPreview_Clear.bl_idname,text="",icon="PANEL_CLOSE",)
        row.alert = False
    else:
        row.operator(OP_HumanoidMappingPreview_Show.bl_idname,text="",icon="OVERLAY",)

    row.operator(OP_Mapping_WriteHumanoidBoneProps.bl_idname,text=tr("自动映射"),)
    row.operator(OP_Mapping_ClearHumanoidBoneProps.bl_idname,text="",icon="TRASH",)


    row = box.row(align=True)
    row.prop_search(scene, "bone_constraint_resting_armature",scene,"objects",text=tr("固定"),icon="ARMATURE_DATA",)
    row.operator(OP_SwapBoneConstraintArmatures.bl_idname,text="",icon="ARROW_LEFTRIGHT",)
    row.prop_search(scene,"bone_constraint_moving_armature",scene,"objects",text=tr("移动"),icon="ARMATURE_DATA",)

    col = box.column(align=True)
    row = col.row(align=True)
    row.operator(OP_Humanoid_ForceAlign.bl_idname,text=tr("强制Humanoid对齐"),icon="CON_ARMATURE",)

    row = col.row(align=True)
    
    row.operator(OP_SameNameBone_addConstraint.bl_idname,text=tr("约束-复制位置"),).constraint_type = 'COPY_LOCATION'
    row.operator(OP_SameNameBone_addConstraint.bl_idname,text=tr("约束-复制旋转"),).constraint_type = 'COPY_ROTATION'
    row.operator(OP_movingArmture_clear_constraint.bl_idname,text="",icon="TRASH",)

    row = box.row(align=True)
    row.operator(OP_BoneApplyConstraint.bl_idname,text=tr("应用约束到骨骼"),)
    row.operator(OP_BoneRemoveConstraints.bl_idname,text=tr("移除骨骼约束"),)

cls = [
    OP_SwapBoneConstraintArmatures,
    OP_SameNameBone_addConstraint,
    OP_BoneApplyConstraint,
    OP_movingArmture_clear_constraint,
    OP_BoneRemoveConstraints,
    OP_Mapping_WriteHumanoidBoneProps,
    OP_Mapping_ClearHumanoidBoneProps,
    OP_HumanoidMappingPreview_Show,
    OP_HumanoidMappingPreview_Clear,
    OP_Humanoid_ForceAlign,
]

def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()

