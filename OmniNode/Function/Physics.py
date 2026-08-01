OMNI_NODE_REGISTRATION = {
    "category": {"id": "PHYSICS", "label": "物理", "order": 160},
}

from ..OmniNodeSocketMapping import _OmniBone
from ..FunctionNodeCore import omni
from ..config import nodeColors

import bpy


class _PoseBoneValues:
    @staticmethod
    def require_armature(obj, label: str) -> bpy.types.Object:
        if obj is None or not isinstance(obj, bpy.types.Object) or obj.type != "ARMATURE":
            raise ValueError(f"{label} is not an armature object")
        return obj

    @staticmethod
    def bone_socket_value(armature_obj: bpy.types.Object, bone_name: str) -> dict:
        return {
            "armature": armature_obj,
            "bone": bone_name,
        }

    @classmethod
    def resolve(cls, value) -> tuple[bpy.types.Object, str]:
        if not isinstance(value, dict):
            raise ValueError("bone input is empty")
        armature_obj = cls.require_armature(value.get("armature"), "armature")
        bone_name = str(value.get("bone") or "").strip()
        if not bone_name:
            raise ValueError("bone name is empty")
        return armature_obj, bone_name

    @classmethod
    def flatten(cls, values) -> list[dict]:
        result = []
        if values is None:
            return result
        pending = list(values) if isinstance(values, (list, tuple)) else [values]
        while pending:
            value = pending.pop(0)
            if isinstance(value, (list, tuple)):
                pending[0:0] = list(value)
                continue
            try:
                armature_obj, bone_name = cls.resolve(value)
            except Exception:
                continue
            result.append(cls.bone_socket_value(armature_obj, bone_name))
        return result


@omni(
    enable=True,
    always_run=True,
    bl_label="骨骼姿态K帧",
    base_color=nodeColors.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["骨骼", "启用"],
    _OUTPUT_NAME=["骨骼", "写入数量"],
    omni_description="""
    给输入 Bone 集合中的 PoseBone 在当前帧插入姿态关键帧。

    接法：
    1. 把需要记录姿态的 Bone 集合接到本节点“骨骼”输入。
    2. 本节点的“骨骼”输入是多重输入，可以接一条或多条骨链。
    3. 启用为 False 时只透传骨骼列表，不写关键帧。

    写入内容：
    对每根 PoseBone 插入 location、rotation、scale。
    rotation 会根据当前 rotation_mode 选择 rotation_quaternion、rotation_axis_angle 或 rotation_euler。

    注意：
    本节点只负责把当前已经写入 PoseBone 的姿态 K 到当前帧。
    bake 时建议用稳定的逐帧播放/运行流程，不要在同一帧手动反复执行。
    """,
    mute_passthrough={"_OUTPUT0": "bones"},
)
def keyframePoseBones(
    bones: list[_OmniBone],
    enabled: bool = True,
) -> tuple[list[_OmniBone], int]:
    bone_values = _PoseBoneValues.flatten(bones)
    if not enabled:
        return bone_values, 0

    frame = bpy.context.scene.frame_current
    inserted = 0
    for value in bone_values:
        try:
            armature_obj, bone_name = _PoseBoneValues.resolve(value)
        except Exception:
            continue

        pose_bone = armature_obj.pose.bones.get(bone_name)
        if pose_bone is None:
            continue

        pose_bone.keyframe_insert(data_path="location", frame=frame)
        if pose_bone.rotation_mode == "QUATERNION":
            pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
        elif pose_bone.rotation_mode == "AXIS_ANGLE":
            pose_bone.keyframe_insert(data_path="rotation_axis_angle", frame=frame)
        else:
            pose_bone.keyframe_insert(data_path="rotation_euler", frame=frame)
        pose_bone.keyframe_insert(data_path="scale", frame=frame)
        inserted += 1

    return bone_values, inserted
