import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from BoneTools import boneOperators
from Utils import bone_utils


bpy.utils.register_class(boneOperators.OP_AddSelectMirroredBones)

armature_data = bpy.data.armatures.new("AddSelectMirroredBonesData")
armature = bpy.data.objects.new("AddSelectMirroredBones", armature_data)
bpy.context.scene.collection.objects.link(armature)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")

names = (
    "arm.L",
    "arm.R",
    "LeftHand",
    "RightHand",
    "leg_L",
    "leg_R",
    "missing_L",
    "spine",
)
for index, name in enumerate(names):
    bone = armature_data.edit_bones.new(name)
    bone.head = (index * 0.2, 0.0, 0.0)
    bone.tail = (index * 0.2, 1.0, 0.0)

# 编辑模式：保留原选择，并按多种命名规则加选存在的对侧骨。
bone_utils.select_bones(armature, ["arm.L", "LeftHand", "missing_L", "spine"])
assert boneOperators.OP_AddSelectMirroredBones.poll(bpy.context)
assert bpy.ops.ho.add_select_mirrored_bones() == {"FINISHED"}
assert set(bone_utils.selected_bone_names(bpy.context, armature)) == {
    "arm.L",
    "arm.R",
    "LeftHand",
    "RightHand",
    "missing_L",
    "spine",
}

# 姿态模式使用相同规则。
bpy.ops.object.mode_set(mode="POSE")
bone_utils.select_bones(armature, ["leg_R"])
assert bpy.ops.ho.add_select_mirrored_bones() == {"FINISHED"}
assert set(bone_utils.selected_bone_names(bpy.context, armature)) == {
    "leg_L",
    "leg_R",
}

# 对侧已经选中时不重复处理，也不改变选择。
assert bpy.ops.ho.add_select_mirrored_bones() == {"CANCELLED"}
assert set(bone_utils.selected_bone_names(bpy.context, armature)) == {
    "leg_L",
    "leg_R",
}

print("ADD_SELECT_MIRRORED_BONES_OK", bpy.app.version_string)
