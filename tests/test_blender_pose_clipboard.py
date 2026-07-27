import math
import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from Utils import bone_utils


armature_data = bpy.data.armatures.new("PoseClipboardData")
armature = bpy.data.objects.new("PoseClipboard", armature_data)
bpy.context.scene.collection.objects.link(armature)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")

for index, name in enumerate(("CopiedBone", "UncopiedBone")):
    bone = armature_data.edit_bones.new(name)
    bone.head = (index * 0.25, 0.0, 0.0)
    bone.tail = (index * 0.25, 1.0, 0.0)

bpy.ops.object.mode_set(mode="POSE")
copied_bone = armature.pose.bones["CopiedBone"]
uncopied_bone = armature.pose.bones["UncopiedBone"]

copied_bone.location = (0.25, -0.5, 0.75)
copied_bone.rotation_mode = "XYZ"
copied_bone.rotation_euler = (
    math.radians(10.0),
    math.radians(20.0),
    math.radians(30.0),
)
copied_bone.scale = (1.1, 1.2, 1.3)
uncopied_bone.location.x = 2.0

expected_location = copied_bone.location.copy()
expected_rotation = copied_bone.rotation_euler.copy()
expected_scale = copied_bone.scale.copy()

# 复制时只记录选中骨骼。
bone_utils.select_bones(armature, ["CopiedBone"])
assert bpy.ops.pose.copy() == {"FINISHED"}

copied_bone.location = (0.0, 0.0, 0.0)
copied_bone.rotation_euler = (0.0, 0.0, 0.0)
copied_bone.scale = (1.0, 1.0, 1.0)
uncopied_bone.location = (0.0, 0.0, 0.0)

# 粘贴按骨骼名称生效，不受当前选择限制。
bone_utils.select_bones(armature, ["UncopiedBone"])
assert bpy.ops.pose.paste(flipped=False, selected_mask=False) == {"FINISHED"}
assert copied_bone.location == expected_location
assert copied_bone.rotation_euler == expected_rotation
assert copied_bone.scale == expected_scale
assert tuple(uncopied_bone.location) == (0.0, 0.0, 0.0)

print("POSE_CLIPBOARD_OK", bpy.app.version_string)
