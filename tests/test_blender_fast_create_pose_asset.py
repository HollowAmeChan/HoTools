import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from BoneTools import boneOperators
from Utils import bone_utils


bpy.utils.register_class(boneOperators.OP_FastCreatPoseAsset)

armature_data = bpy.data.armatures.new("FastPoseAssetData")
armature = bpy.data.objects.new("FastPoseAsset", armature_data)
bpy.context.scene.collection.objects.link(armature)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")

bone = armature_data.edit_bones.new("PoseBone")
bone.head = (0.0, 0.0, 0.0)
bone.tail = (0.0, 1.0, 0.0)

bpy.ops.object.mode_set(mode="POSE")
bone_utils.select_bones(armature, ["PoseBone"])
armature.pose.bones["PoseBone"].rotation_euler.z = 0.5
source_action = bpy.data.actions.new("Source Action")
armature.animation_data_create().action = source_action

pose_name = "HoTools Fast Pose Test"
assert boneOperators.OP_FastCreatPoseAsset.poll(bpy.context)
assert bpy.ops.ho.fast_create_pose_asset(pose_name=pose_name) == {"FINISHED"}

pose_action = bpy.data.actions.get(pose_name)
assert pose_action is not None
assert pose_action.asset_data is not None
assert armature.animation_data.action is source_action

bone_utils.select_bones(armature, [])
assert not boneOperators.OP_FastCreatPoseAsset.poll(bpy.context)

print("FAST_CREATE_POSE_ASSET_OK", bpy.app.version_string)
