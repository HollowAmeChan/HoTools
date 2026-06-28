import bpy
from bpy.types import Context, Operator, UILayout
from bpy.props import FloatProperty, IntProperty
from math import acos, cos, radians, sin
from mathutils import Vector

from .boneSplit import BoneSplitCore
from .boneTwist import TwistBoneCore


EPS = 1e-6


def reg_props():
    return


def ureg_props():
    return


def _safe_normalized_vector(vector):
    if vector.length < EPS:
        return None
    return vector.normalized()


def _clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def drawBoneFanPanel(layout: UILayout, context: Context):
    fan_box = layout.box()

    row = fan_box.row(align=True)
    row.operator(OP_FanInBone.bl_idname, text="fanIn添加")
    row.operator(OP_FanOutBone.bl_idname, text="fanOut添加")

    row = fan_box.row(align=True)
    row.operator(OP_RemoveFanBone.bl_idname, text="清除Fan骨")


class BoneFanCore:
    @staticmethod
    def _fan_name(base_name: str, fan_kind: str, index: int, padding: int) -> str:
        stem, side_suffix = TwistBoneCore._split_side_suffix(base_name)
        marker = "_fan_in_" if fan_kind == "in" else "_fan_out_"
        return f"{stem}{marker}{index:0{padding}d}{side_suffix}"

    @staticmethod
    def _parse_fan_name(name: str):
        stem, side_suffix = TwistBoneCore._split_side_suffix(name)
        for fan_kind, marker in (("in", "_fan_in_"), ("out", "_fan_out_")):
            marker_index = stem.rfind(marker)
            if marker_index < 0:
                continue

            index_text = stem[marker_index + len(marker):]
            if not index_text.isdigit():
                continue

            base_stem = stem[:marker_index]
            if not base_stem:
                continue

            return {
                "base_name": f"{base_stem}{side_suffix}",
                "fan_kind": fan_kind,
                "index": int(index_text),
            }

        return None

    @staticmethod
    def _rotate_vector_around_axis(vector, axis, angle_rad):
        axis = _safe_normalized_vector(axis)
        if axis is None:
            return None

        return (
            vector * cos(angle_rad)
            + axis.cross(vector) * sin(angle_rad)
            + axis * axis.dot(vector) * (1.0 - cos(angle_rad))
        )

    @staticmethod
    def _selected_bone_names(context: Context, armature: bpy.types.Object) -> list[str]:
        if armature.mode == "POSE":
            return [bone.name for bone in context.selected_pose_bones]
        if armature.mode == "EDIT":
            return [bone.name for bone in armature.data.edit_bones if bone.select]
        return []

    @staticmethod
    def _resolve_joint_geometry(bone_a, bone_b):
        if (bone_a.tail - bone_b.head).length <= 1e-4:
            parent_bone = bone_a
            child_bone = bone_b
            joint = (bone_a.tail + bone_b.head) * 0.5
        elif (bone_b.tail - bone_a.head).length <= 1e-4:
            parent_bone = bone_b
            child_bone = bone_a
            joint = (bone_b.tail + bone_a.head) * 0.5
        else:
            return None, "两根骨必须首尾相接并形成关节"

        parent_dir = _safe_normalized_vector(parent_bone.head - joint)
        child_dir = _safe_normalized_vector(child_bone.tail - joint)
        if parent_dir is None or child_dir is None:
            return None, "关节两侧骨长过短，无法生成 fan 骨"

        dot = _clamp(parent_dir.dot(child_dir), -1.0, 1.0)
        angle_rad = acos(dot)
        if angle_rad <= radians(1.0) or angle_rad >= radians(179.0):
            return None, "两根骨的夹角过小或过直，无法生成 fan 骨"

        plane_normal = _safe_normalized_vector(parent_dir.cross(child_dir))
        if plane_normal is None:
            return None, "无法计算工作平面法线"

        fan_in_axis = _safe_normalized_vector(parent_dir + child_dir)
        if fan_in_axis is None:
            return None, "无法计算 fan 中心线"

        parent_length = (parent_bone.head - joint).length
        child_length = (child_bone.tail - joint).length

        return {
            "parent_bone": parent_bone,
            "child_bone": child_bone,
            "joint": joint,
            "parent_dir": parent_dir,
            "child_dir": child_dir,
            "plane_normal": plane_normal,
            "fan_in_axis": fan_in_axis,
            "base_length": min(parent_length, child_length),
        }, None

    @staticmethod
    def _build_angles(count: int, spread_deg: float) -> list[float]:
        if count <= 1:
            return [0.0]

        if spread_deg <= 0.0:
            return [0.0 for _ in range(count)]

        half = spread_deg * 0.5
        step = spread_deg / (count - 1)
        return [-half + i * step for i in range(count)]

    @staticmethod
    def _choose_parent_bone(direction, a_bone, a_dir, b_bone, b_dir):
        score_a = direction.dot(a_dir)
        score_b = direction.dot(b_dir)
        if abs(score_a - score_b) < 1e-6:
            return a_bone
        return a_bone if score_a > score_b else b_bone

    @staticmethod
    def _apply_hotools_bone_props(armature: bpy.types.Object, bone_names: list[str]) -> None:
        #设置hotools属性
        for bone_name in bone_names:
            bone = armature.data.bones.get(bone_name)
            props = getattr(bone, "hotools_boneprops", None) if bone else None
            if props and hasattr(props, "keepRotation"):
                props.keepRotation = False
            if props and hasattr(props, "humanoidMapping"):
                props.humanoidMapping = bone_name

    @classmethod
    def _create_fan_bones(
        cls,
        armature: bpy.types.Object,
        selected_names: list[str],
        fan_kind: str,
        count: int,
        length_factor: float,
        spread_deg: float,
    ) -> list[str]:
        if len(selected_names) != 2:
            raise Exception("请先选择两根骨骼")

        edit_bones = armature.data.edit_bones
        bone_a = edit_bones.get(selected_names[0])
        bone_b = edit_bones.get(selected_names[1])
        if bone_a is None or bone_b is None:
            raise Exception("未找到已选择的骨骼")

        frame, error = cls._resolve_joint_geometry(bone_a, bone_b)
        if error:
            raise Exception(error)

        parent_bone = frame["parent_bone"]
        child_bone = frame["child_bone"]
        joint = frame["joint"]
        parent_dir = frame["parent_dir"]
        child_dir = frame["child_dir"]
        plane_normal = frame["plane_normal"]
        center_axis = frame["fan_in_axis"]
        if fan_kind == "out":
            center_axis = -center_axis
        base_length = frame["base_length"]

        padding = max(2, len(str(count)))
        fan_length = max(base_length * length_factor, EPS)
        angles = cls._build_angles(count, spread_deg)

        existed = []
        for i in range(count):
            new_name = cls._fan_name(parent_bone.name, fan_kind, i + 1, padding)
            if edit_bones.get(new_name) is not None:
                existed.append(new_name)

        if existed:
            raise Exception("Fan骨名称已存在: " + ", ".join(existed))

        created_names = []
        for i, angle_deg in enumerate(angles, start=1):
            new_name = cls._fan_name(parent_bone.name, fan_kind, i, padding)
            direction = cls._rotate_vector_around_axis(
                center_axis,
                plane_normal,
                radians(angle_deg),
            )
            if direction is None:
                raise Exception(f"无法生成 {new_name} 的方向")

            direction = _safe_normalized_vector(direction)
            if direction is None:
                raise Exception(f"{new_name} 方向长度为 0")

            new_bone = edit_bones.new(new_name)
            new_bone.head = joint.copy()
            new_bone.tail = joint + direction * fan_length
            new_bone.use_connect = False
            new_bone.use_deform = True
            new_bone.parent = cls._choose_parent_bone(
                direction,
                parent_bone,
                parent_dir,
                child_bone,
                child_dir,
            )

            try:
                new_bone.align_roll(plane_normal)
            except Exception:
                new_bone.roll = 0.0

            created_names.append(new_name)

        bpy.context.view_layer.objects.active = armature
        try:
            BoneSplitCore.set_object_mode(armature, "OBJECT")
            cls._apply_hotools_bone_props(armature, created_names)
        finally:
            if armature.mode != "EDIT":
                try:
                    BoneSplitCore.set_object_mode(armature, "EDIT")
                except Exception:
                    pass

        return created_names

    @classmethod
    def _collect_fan_bone_names(cls, armature: bpy.types.Object, selected_names: list[str]) -> list[str]:
        edit_bones = armature.data.edit_bones
        removal = set()
        selected_set = set(selected_names)

        if not selected_names:
            for bone in edit_bones:
                if cls._parse_fan_name(bone.name) is not None:
                    removal.add(bone.name)
            return sorted(removal)

        for name in selected_names:
            if cls._parse_fan_name(name) is not None:
                removal.add(name)

        for bone in edit_bones:
            parsed = cls._parse_fan_name(bone.name)
            if parsed is None:
                continue
            if parsed["base_name"] in selected_set:
                removal.add(bone.name)

        return sorted(removal)

    @classmethod
    def _remove_fan_bones(cls, armature: bpy.types.Object, selected_names: list[str]) -> int:
        edit_bones = armature.data.edit_bones
        removed = 0

        for bone_name in cls._collect_fan_bone_names(armature, selected_names):
            bone = edit_bones.get(bone_name)
            if bone is None:
                continue
            edit_bones.remove(bone)
            removed += 1

        return removed


class OP_FanBase(Operator):
    bl_options = {"REGISTER", "UNDO"}

    count: IntProperty(
        name="数量",
        description="生成的 fan 骨数量",
        default=2,
        min=1,
    )  # type: ignore
    length_factor: FloatProperty(
        name="长度系数",
        description="fan 骨长度相对于关节两侧骨长度的比例",
        default=0.2,
        min=0.01,
        soft_max=1.0,
    )  # type: ignore
    spread_deg: FloatProperty(
        name="扇面角度",
        description="fan 骨围绕中心线的总展开角度",
        default=30.0,
        min=0.0,
        soft_max=90.0,
    )  # type: ignore

    fan_kind = "in"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "ARMATURE":
            return False

        if obj.mode == "POSE":
            return len(context.selected_pose_bones) == 2

        if obj.mode == "EDIT":
            return len([bone for bone in obj.data.edit_bones if bone.select]) == 2

        return False

    def execute(self, context):
        armature = context.active_object
        original_mode = armature.mode
        old_active = bpy.context.view_layer.objects.active
        was_hidden = armature.hide_viewport

        selected_names = BoneFanCore._selected_bone_names(context, armature)
        if len(selected_names) != 2:
            self.report({"ERROR"}, "请先选择两根骨骼")
            return {"CANCELLED"}

        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()

        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

        try:
            if original_mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, "EDIT")

            created_names = BoneFanCore._create_fan_bones(
                armature,
                selected_names,
                self.fan_kind,
                self.count,
                self.length_factor,
                self.spread_deg,
            )

            if original_mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, original_mode)

            self.report({"INFO"}, f"已生成 {len(created_names)} 根 {self.bl_label}")
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        finally:
            if armature.mode == "EDIT" and original_mode != "EDIT":
                try:
                    BoneSplitCore.set_object_mode(armature, original_mode)
                except Exception:
                    pass

            if old_active is not None:
                try:
                    bpy.context.view_layer.objects.active = old_active
                except Exception:
                    pass

            if was_hidden:
                armature.hide_set(True)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "count")
        layout.prop(self, "length_factor")
        layout.prop(self, "spread_deg")


class OP_FanInBone(OP_FanBase):
    bl_idname = "ho.fan_in_bone"
    bl_label = "fanIn添加"
    bl_description = "在关节内侧生成 fan 骨"
    fan_kind = "in"


class OP_FanOutBone(OP_FanBase):
    bl_idname = "ho.fan_out_bone"
    bl_label = "fanOut添加"
    bl_description = "在关节外侧生成 fan 骨"
    fan_kind = "out"


class OP_RemoveFanBone(Operator):
    bl_idname = "ho.remove_fan_bone"
    bl_label = "清除Fan骨"
    bl_description = "清除选中骨对应的 fan 骨；若未选择骨骼，则清空全部 fan 骨"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        armature = context.active_object
        original_mode = armature.mode
        old_active = bpy.context.view_layer.objects.active
        was_hidden = armature.hide_viewport

        selected_names = BoneFanCore._selected_bone_names(context, armature)

        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()

        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

        try:
            if original_mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, "EDIT")

            removed = BoneFanCore._remove_fan_bones(armature, selected_names)

            if original_mode != "EDIT":
                BoneSplitCore.set_object_mode(armature, original_mode)

            self.report({"INFO"}, f"已清除 {removed} 根 fan 骨")
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        finally:
            if armature.mode == "EDIT" and original_mode != "EDIT":
                try:
                    BoneSplitCore.set_object_mode(armature, original_mode)
                except Exception:
                    pass

            if old_active is not None:
                try:
                    bpy.context.view_layer.objects.active = old_active
                except Exception:
                    pass

            if was_hidden:
                armature.hide_set(True)


cls = [
    OP_FanInBone,
    OP_FanOutBone,
    OP_RemoveFanBone,
]


def register():
    for item in cls:
        bpy.utils.register_class(item)
    reg_props()


def unregister():
    for item in cls:
        bpy.utils.unregister_class(item)
    ureg_props()
