import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from BoneTools import boneOperators
from Utils import bone_utils


bpy.utils.register_class(boneOperators.OP_DeleteSelectedBoneCurrentFrameKeyframes)

armature_data = bpy.data.armatures.new("DeleteBonePoseKeysData")
armature = bpy.data.objects.new("DeleteBonePoseKeys", armature_data)
bpy.context.scene.collection.objects.link(armature)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")

for index, name in enumerate(("DeleteBone", "KeepBone")):
    bone = armature_data.edit_bones.new(name)
    bone.head = (index * 0.25, 0.0, 0.0)
    bone.tail = (index * 0.25, 1.0, 0.0)

bpy.ops.object.mode_set(mode="POSE")
delete_bone = armature.pose.bones["DeleteBone"]
keep_bone = armature.pose.bones["KeepBone"]
delete_bone["pose_value"] = 0.0

for frame in (1.0, 8.0):
    bpy.context.scene.frame_set(int(frame))
    delete_bone.location.x = frame
    delete_bone["pose_value"] = frame
    keep_bone.rotation_euler.z = frame * 0.1
    armature.location.y = frame * 0.2
    delete_bone.keyframe_insert("location", frame=frame)
    delete_bone.keyframe_insert('["pose_value"]', frame=frame)
    keep_bone.keyframe_insert("rotation_euler", frame=frame)
    armature.keyframe_insert("location", frame=frame)

bpy.context.scene.frame_set(1)
delete_bone.scale.x = 1.5
delete_bone.keyframe_insert("scale", frame=1.0)

animation_data = armature.animation_data
assert animation_data is not None
assert animation_data.action is not None

owners = boneOperators._active_action_curve_owners(animation_data)
assert owners
paths_before = {
    fcurve.data_path
    for owner in owners
    for fcurve in owner.fcurves
}
delete_root = delete_bone.path_from_id()
keep_root = keep_bone.path_from_id()
assert any(path.startswith(delete_root) for path in paths_before)
assert any(path.startswith(keep_root) for path in paths_before)
assert "location" in paths_before

bone_utils.select_bones(armature, ["DeleteBone"])
assert boneOperators.OP_DeleteSelectedBoneCurrentFrameKeyframes.poll(bpy.context)
assert bpy.ops.ho.delete_selected_bone_current_frame_keyframes() == {"FINISHED"}

paths_after = {
    fcurve.data_path
    for owner in boneOperators._active_action_curve_owners(animation_data)
    for fcurve in owner.fcurves
}
delete_curves = [
    fcurve
    for owner in boneOperators._active_action_curve_owners(animation_data)
    for fcurve in owner.fcurves
    if fcurve.data_path.startswith(delete_root)
]
assert delete_curves
assert all(
    [key.co.x for key in fcurve.keyframe_points] == [8.0]
    for fcurve in delete_curves
)
assert not any(fcurve.data_path.endswith(".scale") for fcurve in delete_curves)
assert any(path.startswith(keep_root) for path in paths_after)
assert "location" in paths_after

assert bpy.ops.ho.delete_selected_bone_current_frame_keyframes() == {"CANCELLED"}

print("DELETE_BONE_POSE_KEYFRAMES_OK", bpy.app.version_string)
