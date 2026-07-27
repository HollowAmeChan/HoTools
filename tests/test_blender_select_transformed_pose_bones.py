import math
import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from BoneTools import boneOperators
from Utils import bone_utils


bpy.utils.register_class(boneOperators.OP_SelectTransformedPoseBones)

armature_data = bpy.data.armatures.new("SelectTransformedPoseBonesData")
armature = bpy.data.objects.new("SelectTransformedPoseBones", armature_data)
bpy.context.scene.collection.objects.link(armature)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")

for index, name in enumerate(
    ("rest", "location", "euler", "quaternion", "axis_angle", "scale")
):
    bone = armature_data.edit_bones.new(name)
    bone.head = (index * 0.2, 0.0, 0.0)
    bone.tail = (index * 0.2, 1.0, 0.0)

bpy.ops.object.mode_set(mode="POSE")
armature.pose.bones["location"].location.x = 0.25

euler_bone = armature.pose.bones["euler"]
euler_bone.rotation_mode = "XYZ"
euler_bone.rotation_euler.z = math.radians(15.0)

quaternion_bone = armature.pose.bones["quaternion"]
quaternion_bone.rotation_mode = "QUATERNION"
quaternion_bone.rotation_quaternion.x = 0.25

axis_angle_bone = armature.pose.bones["axis_angle"]
axis_angle_bone.rotation_mode = "AXIS_ANGLE"
axis_angle_bone.rotation_axis_angle[0] = math.radians(20.0)

armature.pose.bones["scale"].scale.y = 1.5

# 现有选择必须被替换，而不是扩展。
bone_utils.select_bones(armature, ["rest"])
assert boneOperators.OP_SelectTransformedPoseBones.poll(bpy.context)
assert bpy.ops.ho.select_transformed_pose_bones() == {"FINISHED"}
assert set(bone_utils.selected_bone_names(bpy.context, armature)) == {
    "location",
    "euler",
    "quaternion",
    "axis_angle",
    "scale",
}

# 所有姿态复位后，操作应清空选择。
for pose_bone in armature.pose.bones:
    pose_bone.location = (0.0, 0.0, 0.0)
    pose_bone.rotation_euler = (0.0, 0.0, 0.0)
    pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    pose_bone.rotation_axis_angle[0] = 0.0
    pose_bone.scale = (1.0, 1.0, 1.0)

assert bpy.ops.ho.select_transformed_pose_bones() == {"FINISHED"}
assert bone_utils.selected_bone_names(bpy.context, armature) == []

print("SELECT_TRANSFORMED_POSE_BONES_OK", bpy.app.version_string)
