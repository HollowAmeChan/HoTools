import bpy
from bpy.types import UILayout, Context, Operator
from bpy.props import BoolProperty, IntProperty
from .humanoid_auto_mapping import auto_map_source_names_to_humanoid,TARGET_LAYOUT
from . import arpAssembly

from math import acos, atan2, cos, degrees, radians, sin
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from bpy_extras import view3d_utils
from Utils.bone_selection import selected_bone_names


def reg_props():
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
    bpy.types.Scene.bone_humanoid_check_precise_limb_ik = BoolProperty(
        name="精确四肢IK检查",
        description="检查四肢骨X轴是否垂直于弯曲平面（对齐ARP Auto IK Roll的目标）；开启后并入检查预览",
        default=False,
    )
    bpy.types.Scene.bone_humanoid_check_twist = BoolProperty(
        name="扭转检查",
        description="检查各Humanoid骨骼轴向偏转（axis_direction模式），关闭后不显示轴向扭转错误",
        default=True,
    )
    bpy.types.Scene.bone_humanoid_check_ik_bend = BoolProperty(
        name="IK朝向",
        description="检查四肢IK弯曲朝向是否符合预期（ik_bend_direction模式），关闭后不显示IK朝向错误",
        default=True,
    )
    bpy.types.Scene.bone_humanoid_check_connection = BoolProperty(
        name="相连项",
        description="检查特定Humanoid骨骼的相连项（use_connect）是否关闭，关闭后不显示相连警告",
        default=True,
    )
    bpy.types.Scene.bone_humanoid_preview_font_size = IntProperty(
        name="文字大小",
        default=30,
        min=12,
        max=64,
    )

def ureg_props():
    del bpy.types.Scene.bone_humanoid_preview_show_names
    del bpy.types.Scene.bone_humanoid_preview_show_missing
    del bpy.types.Scene.bone_humanoid_preview_show_check_details
    del bpy.types.Scene.bone_humanoid_check_precise_limb_ik
    del bpy.types.Scene.bone_humanoid_check_twist
    del bpy.types.Scene.bone_humanoid_check_ik_bend
    del bpy.types.Scene.bone_humanoid_check_connection
    del bpy.types.Scene.bone_humanoid_preview_font_size


class OP_Humanoid_FixLimbIkRoll(Operator):
    bl_idname = "ho.humanoid_fix_limb_ik_roll"
    bl_label = "修复四肢IK滚转"
    bl_description = (
        "把四肢骨(upper/lower arm/leg)的滚转对齐到各自的弯曲平面法线，"
        "匹配ARP Auto IK Roll的目标，避免Match to Rig时参考骨扭转被自动改写。"
        "执行前会弹框列出将修复的骨与缺失的Humanoid骨"
    )
    bl_options = {'REGISTER', 'UNDO'}

    # 四肢链定义：(显示名, 上肢mapping, 下肢mapping)。上下肢共用同一条弯曲平面。
    _LIMB_CHAINS = (
        ("左臂", "upper_arm.L", "lower_arm.L"),
        ("右臂", "upper_arm.R", "lower_arm.R"),
        ("左腿", "upper_leg.L", "lower_leg.L"),
        ("右腿", "upper_leg.R", "lower_leg.R"),
    )

    # invoke 阶段扫描结果，供 draw 复用（instance 属性，dialog 期间同一实例）
    _fixable_bones = []
    _missing_mappings = []
    _degenerate_limbs = []

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'ARMATURE'

    def _build_mapping_to_bone(self, obj):
        # mapping 名 -> 骨名（同名 mapping 取第一根）
        result = {}
        for bone in obj.data.bones:
            props = getattr(bone, "hotools_boneprops", None)
            if props is None:
                continue

            mapping = props.humanoidMapping.strip()
            if not mapping:
                continue

            if mapping not in result:
                result[mapping] = bone.name

        return result

    def _compute_targets(self, obj):
        """扫描四肢链，返回 (targets, missing, degenerate)。

        targets: [(bone_name, mapping, normal_world)]，弯曲平面法线在世界空间。
        missing: [缺失的 mapping 名]
        degenerate: [直肢(三关节共线)的肢体显示名]
        必须在 OBJECT/POSE 模式调用（依赖 data.bones 的静置坐标）。
        """
        world = obj.matrix_world
        mapping_to_bone = self._build_mapping_to_bone(obj)

        targets = []
        missing = []
        degenerate = []
        seen = set()

        for limb_label, upper_map, lower_map in self._LIMB_CHAINS:
            upper_name = mapping_to_bone.get(upper_map)
            lower_name = mapping_to_bone.get(lower_map)

            local_missing = []
            if upper_name is None:
                local_missing.append(upper_map)
            if lower_name is None:
                local_missing.append(lower_map)

            if local_missing:
                missing.extend(local_missing)
                continue

            upper_bone = obj.data.bones.get(upper_name)
            lower_bone = obj.data.bones.get(lower_name)

            if upper_bone is None or lower_bone is None:
                if upper_bone is None:
                    missing.append(upper_map)
                if lower_bone is None:
                    missing.append(lower_map)
                continue

            root_point = world @ upper_bone.head_local
            middle_point = (
                world @ upper_bone.tail_local
                + world @ lower_bone.head_local
            ) * 0.5
            end_point = world @ lower_bone.tail_local

            normal = _safe_normalized_vector(
                (middle_point - root_point).cross(end_point - root_point)
            )

            # 直臂/直腿三点共线，无法定义弯曲平面
            if normal is None:
                degenerate.append(limb_label)
                continue

            for bone_name, mapping in (
                (upper_name, upper_map),
                (lower_name, lower_map),
            ):
                if bone_name in seen:
                    continue

                seen.add(bone_name)
                targets.append((bone_name, mapping, normal.copy()))

        return targets, missing, degenerate

    def invoke(self, context, event):
        obj = context.object

        targets, missing, degenerate = self._compute_targets(obj)
        self._fixable_bones = [
            (bone_name, mapping)
            for bone_name, mapping, _ in targets
        ]
        self._missing_mappings = missing
        self._degenerate_limbs = degenerate

        if not targets and not missing and not degenerate:
            self.report(
                {'WARNING'},
                "未找到任何四肢Humanoid映射（upper/lower arm/leg）",
            )
            return {'CANCELLED'}

        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        layout = self.layout

        if self._fixable_bones:
            box = layout.box()
            box.label(
                text=f"将修复 {len(self._fixable_bones)} 根四肢骨的滚转：",
                icon='CON_KINEMATIC',
            )
            col = box.column(align=True)
            for bone_name, mapping in self._fixable_bones:
                col.label(text=f"{mapping}  ({bone_name})")
        else:
            layout.label(text="没有可修复的四肢骨", icon='INFO')

        if self._missing_mappings:
            box = layout.box()
            box.alert = True
            box.label(
                text=f"缺失的Humanoid四肢骨 {len(self._missing_mappings)}：",
                icon='ERROR',
            )
            col = box.column(align=True)
            for mapping in self._missing_mappings:
                col.label(text=f"✕ {mapping}")

        if self._degenerate_limbs:
            box = layout.box()
            box.label(
                text="直肢跳过（三关节共线，无弯曲平面）：",
                icon='INFO',
            )
            col = box.column(align=True)
            for limb_label in self._degenerate_limbs:
                col.label(text=f"- {limb_label}")

    def execute(self, context):
        obj = context.object

        if obj is None or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择一个Armature")
            return {'CANCELLED'}

        prev_active = context.view_layer.objects.active
        prev_mode = obj.mode

        # 先回到物体模式，保证 data.bones 静置坐标有效，再计算目标法线
        bpy.ops.object.mode_set(mode='OBJECT')
        context.view_layer.objects.active = obj
        obj.select_set(True)

        targets, missing, degenerate = self._compute_targets(obj)

        bpy.ops.object.mode_set(mode='EDIT')

        rot_inv = obj.matrix_world.inverted().to_3x3()

        fixed_count = 0
        skipped_parallel = 0

        for bone_name, mapping, normal_world in targets:
            eb = obj.data.edit_bones.get(bone_name)
            if eb is None:
                continue

            bone_y_axis = eb.tail - eb.head
            if bone_y_axis.length < 1e-6:
                continue
            bone_y_axis.normalize()

            # 法线转到骨架局部空间，再投影到滚转平面（⊥骨骼Y轴）
            normal_local = rot_inv @ normal_world
            normal_proj = normal_local - bone_y_axis * normal_local.dot(bone_y_axis)

            # 法线平行于骨轴时 roll 无法修正，跳过
            if normal_proj.length < 1e-6:
                skipped_parallel += 1
                continue
            normal_proj.normalize()

            # 取与当前 Z 轴同侧的法线方向，保证最小旋转、不翻180°
            sign = 1.0 if eb.z_axis.dot(normal_proj) >= 0.0 else -1.0
            desired_z_axis = normal_proj * sign

            # align_roll 直接把骨骼 Z 轴对到给定向量（= 弯曲平面法线 = 滚转/铰链轴）
            before_roll = eb.roll
            eb.align_roll(desired_z_axis)
            fixed_count += 1

            print(
                f"[Fix Limb IK Roll] {bone_name} mapping={mapping} "
                f"roll {before_roll:.6f} -> {eb.roll:.6f}"
            )

        # 恢复进入前的模式与活动物体
        bpy.ops.object.mode_set(mode='OBJECT')

        if prev_active is not None:
            context.view_layer.objects.active = prev_active

        try:
            if prev_mode == 'POSE':
                bpy.ops.object.mode_set(mode='POSE')
            elif prev_mode == 'EDIT':
                bpy.ops.object.mode_set(mode='EDIT')
            else:
                bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass

        msg = f"四肢IK滚转修复完成：修复 {fixed_count}"

        if skipped_parallel:
            msg += f"，跳过(法线平行骨轴) {skipped_parallel}"

        if degenerate:
            msg += f"，直肢跳过 {len(degenerate)}"

        if missing:
            msg += f"，缺失 {len(missing)}"

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

    def _collect_selected_visible_bones(self, context, obj):
        armature = obj.data
        selected_names = set(selected_bone_names(context, obj))

        selected = []
        hidden_selected_count = 0

        for bone in armature.bones:
            if bone.name not in selected_names:
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

        bones, hidden_selected_count = self._collect_selected_visible_bones(context, obj)

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
        selected_names = set(selected_bone_names(context, obj)) if self.only_selected else set()

        for bone in bones:
            if self.only_selected and bone.name not in selected_names:
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


# 精确四肢IK检查阈值（度）。四肢骨Z轴偏离弯曲平面法线超过此值即报错。
# ARP Auto IK Roll 会把四肢骨精确对到弯曲平面，所以这里用一个较小的阈值。
_LIMB_IK_ROLL_THRESHOLD_DEG = 5.0


class HumanoidLimbIkRollMode(HumanoidTwistCheckMode):
    """精确四肢IK滚转检查。

    刻画 ARP Auto IK Roll 的不变量：每根四肢骨的局部 Z 轴平行于弯曲平面法线
    （即滚转/铰链轴 = 由上肢head、肘(膝)、下肢tail 三关节确定的平面法线，
    等价于骨骼 X 轴落在弯曲平面内）。ARP 用 calculate_roll(NEG_Z/POS_Z) 就是
    把 Z 对到这条法线，右侧再 -180°。

    - 检查本骨世界 Z 轴（投影到滚转平面）与平面法线的锐角，超阈值即报错；
      对 ±法线取最近，锐角判定与符号无关，左右臂腿共用同一套几何，不需要
      处理 ARP 里 NEG_Z/POS_Z/右侧-180° 的符号差异。
    - 直臂/直腿（三关节共线）法线退化为 0，无法定义弯曲平面，跳过不报。
    """

    idname = "limb_ik_roll"

    def __init__(
        self,
        upper_mapping_name,
        lower_mapping_name,
        threshold_deg=_LIMB_IK_ROLL_THRESHOLD_DEG,
    ):
        self.upper_mapping_name = upper_mapping_name
        self.lower_mapping_name = lower_mapping_name
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

        plane_normal = _safe_normalized_vector(
            (middle_point - root_point).cross(end_point - root_point)
        )
        # 三关节共线（直臂/直腿）无法定义弯曲平面，跳过
        if plane_normal is None:
            return None

        bone_z_axis = context.axis("+Z")
        bone_y_axis = context.axis("+Y")

        if bone_z_axis is None or bone_y_axis is None:
            return None

        # 投影到滚转平面（⊥骨骼Y轴）。roll 只能绕 Y 旋转，法线里平行于 Y 的分量
        # 无论如何都消不掉，投影后只度量 roll 能控制的偏差，保证修复后必过检查。
        actual_axis = context.project_to_roll_plane(bone_z_axis, bone_y_axis)
        target_axis = context.project_to_roll_plane(plane_normal, bone_y_axis)

        if actual_axis is None or target_axis is None:
            return None

        # 取与当前 Z 轴同侧的法线方向，度量最小锐角（符号无关，等同于修复不翻180°）
        if actual_axis.dot(target_axis) < 0.0:
            target_axis = -target_axis

        angle_deg = context.angle_between_degrees(actual_axis, target_axis)

        if angle_deg <= self.threshold_deg:
            return None

        # 可视化贴到这根骨自己的中心和尺度上。upper/lower 是两条独立规则，
        # 若都用整条链中点(肘部)会重叠堆在一起、且不贴合骨骼，看起来像画错位。
        if context.center_world is not None:
            visual_origin = context.center_world
        else:
            visual_origin = (root_point + end_point) * 0.5

        if context.head_world is not None and context.tail_world is not None:
            bone_length = (context.tail_world - context.head_world).length
        else:
            bone_length = (end_point - root_point).length

        visual_length = max(bone_length * 0.5, 0.08)
        fan_axis = _safe_normalized_vector(target_axis.cross(actual_axis))
        if fan_axis is None:
            fan_axis = bone_y_axis

        return {
            "rule_name": rule.name,
            "mode": self.idname,
            "mapping_name": context.mapping_name,
            "axis_label": "IK滚转",
            "target_label": "弯曲平面法线",
            "angle_deg": angle_deg,
            "threshold_deg": self.threshold_deg,
            "actual_axis_world": actual_axis,
            "target_axis_world": target_axis,
            "bone_axis_world": bone_y_axis,
            "fan_axis_world": fan_axis,
            "visual_origin_world": visual_origin,
            "visual_axis_length": visual_length,
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
# 精确四肢IK检查规则独立成表，通过场景开关按需并入检查结果（默认关闭）
HUMANOID_LIMB_IK_RULES = HumanoidTwistRuleRegistry()

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


def _register_limb_ik_roll_rule(
    mapping_name,
    upper_mapping_name,
    lower_mapping_name,
    threshold_deg=_LIMB_IK_ROLL_THRESHOLD_DEG,
):
    return HUMANOID_LIMB_IK_RULES.register(HumanoidTwistRule(
        name=f"{mapping_name}: IK滚转 -> 弯曲平面法线",
        mapping_names=(mapping_name,),
        mode=HumanoidLimbIkRollMode(
            upper_mapping_name=upper_mapping_name,
            lower_mapping_name=lower_mapping_name,
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


# 精确四肢IK检查规则注册区（默认关闭，由场景开关并入）。
# 每根四肢骨检查自身 Z 轴是否平行于所在肢体的弯曲平面法线（Z ∥ 法线 = 滚转/铰链轴）。
# 因取锐角、对 ±法线取最近，通过/失败与左右无关，上下肢共用同一条弯曲平面。
_register_limb_ik_roll_rule(
    mapping_name="upper_arm.L",
    upper_mapping_name="upper_arm.L",
    lower_mapping_name="lower_arm.L",
)
_register_limb_ik_roll_rule(
    mapping_name="lower_arm.L",
    upper_mapping_name="upper_arm.L",
    lower_mapping_name="lower_arm.L",
)
_register_limb_ik_roll_rule(
    mapping_name="upper_arm.R",
    upper_mapping_name="upper_arm.R",
    lower_mapping_name="lower_arm.R",
)
_register_limb_ik_roll_rule(
    mapping_name="lower_arm.R",
    upper_mapping_name="upper_arm.R",
    lower_mapping_name="lower_arm.R",
)
_register_limb_ik_roll_rule(
    mapping_name="upper_leg.L",
    upper_mapping_name="upper_leg.L",
    lower_mapping_name="lower_leg.L",
)
_register_limb_ik_roll_rule(
    mapping_name="lower_leg.L",
    upper_mapping_name="upper_leg.L",
    lower_mapping_name="lower_leg.L",
)
_register_limb_ik_roll_rule(
    mapping_name="upper_leg.R",
    upper_mapping_name="upper_leg.R",
    lower_mapping_name="lower_leg.R",
)
_register_limb_ik_roll_rule(
    mapping_name="lower_leg.R",
    upper_mapping_name="upper_leg.R",
    lower_mapping_name="lower_leg.R",
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
    def _check_precise_limb_ik(cls):
        return bool(cls._scene_setting(
            "bone_humanoid_check_precise_limb_ik",
            False,
        ))

    @classmethod
    def _check_twist(cls):
        return bool(cls._scene_setting("bone_humanoid_check_twist", True))

    @classmethod
    def _check_ik_bend(cls):
        return bool(cls._scene_setting("bone_humanoid_check_ik_bend", True))

    @classmethod
    def _check_connection(cls):
        return bool(cls._scene_setting("bone_humanoid_check_connection", True))

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

        issues = list(HUMANOID_TWIST_RULES.evaluate(context))

        # 按检查项开关过滤：扭转检查 / IK朝向检查
        check_twist = cls._check_twist()
        check_ik_bend = cls._check_ik_bend()
        if not check_twist or not check_ik_bend:
            filtered = []
            for issue in issues:
                mode = issue.get("mode")
                if mode == "axis_direction" and not check_twist:
                    continue
                if mode == "ik_bend_direction" and not check_ik_bend:
                    continue
                filtered.append(issue)
            issues = filtered

        # 精确四肢IK检查为可选项，开启后并入同一份结果，渲染/文字复用现有逻辑
        if cls._check_precise_limb_ik():
            issues.extend(HUMANOID_LIMB_IK_RULES.evaluate(context))

        return issues

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
        # 相连项检查开关关闭时直接短路
        if not cls._check_connection():
            return []

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
        font_size = cls._font_size_value()
        twist_font_size = cls._twist_font_size_value()

        for index, item in enumerate(cls._items):
            bone_name = item["bone_name"]
            mapping_name = cls._get_bone_mapping_name(bone_name)
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

            if show_names:
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

    # ── 骨骼处理 ──────────────────────────────────────────
    mapping_box = layout.box()
    mapping_box.label(text="骨骼处理", icon="ARMATURE_DATA")

    row = mapping_box.row(align=True)
    row.operator(OP_Mapping_WriteHumanoidBoneProps.bl_idname, text="自动映射")
    row.operator(OP_Mapping_ClearHumanoidBoneProps.bl_idname, text="", icon="TRASH")

    # ── Humanoid 检查预览 ──────────────────────────────────
    layout.separator(factor=0.8)
    preview_box = layout.box()

    # 标题行：名称 + 开关按钮
    header = preview_box.row(align=True)
    header.label(text="Humanoid检查预览", icon="HIDE_OFF")
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

    # 显示选项
    display_col = preview_box.column(align=True)
    display_col.label(text="显示选项：")
    row = display_col.row(align=True)
    row.prop(scene, "bone_humanoid_preview_show_names", toggle=True)
    row.prop(scene, "bone_humanoid_preview_show_missing", toggle=True)

    row = display_col.row(align=True)
    row.prop(scene, "bone_humanoid_preview_show_check_details", toggle=True)
    row.prop(scene, "bone_humanoid_preview_font_size")

    preview_box.separator(factor=0.4)

    # 检查项开关
    check_col = preview_box.column(align=True)
    check_col.label(text="检查项：")
    row = check_col.row(align=True)
    row.prop(scene, "bone_humanoid_check_twist", toggle=True)
    row.prop(scene, "bone_humanoid_check_ik_bend", toggle=True)
    row.prop(scene, "bone_humanoid_check_connection", toggle=True)

    row = check_col.row(align=True)
    row.prop(scene, "bone_humanoid_check_precise_limb_ik", toggle=True)
    row.operator(
        OP_Humanoid_FixLimbIkRoll.bl_idname,
        text="修复四肢IK滚转",
        icon="CON_KINEMATIC",
    )

    layout.separator(factor=0.8)
    arpAssembly.draw_panel(layout, context)

cls = [
    OP_Mapping_WriteHumanoidBoneProps,
    OP_Mapping_ClearHumanoidBoneProps,
    OP_HumanoidMappingPreview_Show,
    OP_HumanoidMappingPreview_Clear,
    OP_Humanoid_FixLimbIkRoll,
]

def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()
    arpAssembly.register()


def unregister():
    HumanoidMappingPreviewHUD.clear()
    arpAssembly.unregister()
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
