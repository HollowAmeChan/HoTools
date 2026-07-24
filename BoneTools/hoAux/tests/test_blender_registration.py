import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[3]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

import BoneTools


BoneTools.register()

items = bpy.types.Scene.bl_rna.properties["ho_BoneToolsPanel_Mod"].enum_items
assert "PANEL_BONE_HOAUX" in {item.identifier for item in items}

armature = bpy.data.armatures.new("HoAuxRegistrationArmature")
obj = bpy.data.objects.new("HoAuxRegistration", armature)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
bone = armature.edit_bones.new("RegistrationBone")
bone.head = (0.0, 0.0, 0.0)
bone.tail = (0.0, 1.0, 0.0)
bpy.ops.object.mode_set(mode="OBJECT")

info = armature.bones["RegistrationBone"].hotools_boneprops.hoAux
assert info.isHoAuxBone is False
info.isHoAuxBone = True
info.nameKey = "TEST.REGISTRATION.BONE"
assert info.nameKey == "TEST.REGISTRATION.BONE"
assert hasattr(bpy.context.scene, "hoaux_shoulder_volume_settings")
assert hasattr(bpy.context.scene, "hoaux_elbow_volume_settings")

BoneTools.unregister()
print("HOAUX_REGISTRATION_OK")
