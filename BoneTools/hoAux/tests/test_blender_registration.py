import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[3]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

import BoneTools
from Utils import bone_utils


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
assert hasattr(bpy.context.scene, "hoaux_forearm_twist_settings")
assert hasattr(bpy.context.scene, "hoaux_upper_arm_twist_settings")
shoulder_settings = bpy.context.scene.hoaux_shoulder_volume_settings
elbow_settings = bpy.context.scene.hoaux_elbow_volume_settings
twist_settings = bpy.context.scene.hoaux_forearm_twist_settings
assert shoulder_settings.bl_rna.properties["track_length"].name == "TRK长度"
assert elbow_settings.bl_rna.properties["twist_offset"].name == "扭转偏移"
assert twist_settings.bl_rna.properties["segment_count"].name == "分段数"
assert {prop.identifier for prop in shoulder_settings.bl_rna.properties} == {
    "rna_type",
    "name",
    "ui_expanded",
    "preview_enabled",
    "track_length",
    "deform_length",
    "x0_angle",
    "twist_offset",
}
assert {prop.identifier for prop in elbow_settings.bl_rna.properties} == {
    "rna_type",
    "name",
    "ui_expanded",
    "preview_enabled",
    "track_length",
    "deform_length",
    "twist_offset",
}
assert {prop.identifier for prop in twist_settings.bl_rna.properties} == {
    "rna_type",
    "name",
    "ui_expanded",
    "preview_enabled",
    "segment_count",
    "influence_start",
    "influence_end",
}
assert "side" not in bpy.context.scene.hoaux_settings.bl_rna.properties
assert bone_utils.require_same_side("UpperArm_L", "LowerArm.L") == "L"
try:
    bone_utils.require_same_side("UpperArm_L", "LowerArm_R")
except ValueError:
    pass
else:
    raise AssertionError("mixed role sides were accepted")

BoneTools.unregister()
print("HOAUX_REGISTRATION_OK")
