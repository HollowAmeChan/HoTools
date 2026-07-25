import sys
from pathlib import Path

import bpy


BONE_TOOLS_DIR = Path(__file__).resolve().parents[2]
if str(BONE_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(BONE_TOOLS_DIR))

import hoAux
from hoAux.preview import ViewportPreview


hoAux.register()
armature = bpy.data.armatures.new("HoAuxPreviewArmature")
obj = bpy.data.objects.new("HoAuxPreview", armature)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
shoulder = armature.edit_bones.new("Shoulder_L")
shoulder.head = (0.0, 0.0, 0.0)
shoulder.tail = (0.0, 0.5, 0.0)
upper = armature.edit_bones.new("UpperArm_L")
upper.head = shoulder.tail
upper.tail = (0.0, 1.5, 0.0)
upper.parent = shoulder
lower = armature.edit_bones.new("LowerArm_L")
lower.head = upper.tail
lower.tail = (0.8, 2.1, 0.2)
lower.parent = upper
bpy.ops.object.mode_set(mode="OBJECT")

root = bpy.context.scene.hoaux_settings
root.shoulderBone = "Shoulder_L"
root.upperArmBone = "UpperArm_L"
root.lowerArmBone = "LowerArm_L"
shoulder_settings = bpy.context.scene.hoaux_shoulder_volume_settings
elbow_settings = bpy.context.scene.hoaux_elbow_volume_settings

shoulder_settings.preview_enabled = True
assert ViewportPreview.active_owner() == "SHOULDER_VOLUME"
assert shoulder_settings.preview_enabled
assert ViewportPreview._handler_3d is not None
assert ViewportPreview._handler_2d is not None

elbow_settings.preview_enabled = True
assert ViewportPreview.active_owner() == "ELBOW_VOLUME"
assert not shoulder_settings.preview_enabled
assert elbow_settings.preview_enabled

elbow_settings.track_length = 0.42
assert ViewportPreview.active_owner() == "ELBOW_VOLUME"
assert ViewportPreview._scene is not None
elbow_settings.preview_enabled = False
assert ViewportPreview.active_owner() is None
assert ViewportPreview._handler_3d is not None
assert ViewportPreview._handler_2d is not None

hoAux.unregister()
assert ViewportPreview._handler_3d is None
assert ViewportPreview._handler_2d is None
print("HOAUX_PREVIEW_LIFECYCLE_OK")
