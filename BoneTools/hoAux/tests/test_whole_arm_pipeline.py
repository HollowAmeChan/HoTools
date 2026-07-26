import sys
from pathlib import Path

import bpy
from bpy.props import PointerProperty
from bpy.types import PropertyGroup


ADDON_DIR = Path(__file__).resolve().parents[3]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from BoneTools import hoAux
from BoneTools.hoAux.generation import find_collection, iter_hoaux_bones
from BoneTools.hoAux.module_base import WHOLE_ARM_PIPELINE_TYPES
from BoneTools.hoAux.preview import PIPELINE_PREVIEW_OWNER, ViewportPreview
from BoneTools.hoAux.properties import PG_HoAuxBoneInfo


class _TestBoneProps(PropertyGroup):
    hoAux: PointerProperty(type=PG_HoAuxBoneInfo)


hoAux.register()
bpy.utils.register_class(_TestBoneProps)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=_TestBoneProps)

armature = bpy.data.armatures.new("WholeArmPipelineArmature")
obj = bpy.data.objects.new("WholeArmPipeline", armature)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
for side, sign in (("L", 1.0), ("R", -1.0)):
    shoulder = armature.edit_bones.new(f"Shoulder_{side}")
    shoulder.head = (sign * 0.05, -0.35, 0.5)
    shoulder.tail = (sign * 0.45, -0.1, 0.65)
    shoulder.roll = sign * 0.18
    upper = armature.edit_bones.new(f"UpperArm_{side}")
    upper.head = shoulder.tail
    upper.tail = (sign * 1.35, 0.35, 0.15)
    upper.roll = sign * -0.31
    upper.parent = shoulder
    lower = armature.edit_bones.new(f"LowerArm_{side}")
    lower.head = upper.tail
    lower.tail = (sign * 1.9, 1.25, 0.45)
    lower.roll = sign * 0.27
    lower.parent = upper
    hand = armature.edit_bones.new(f"Hand_{side}")
    hand.head = lower.tail
    hand.tail = (sign * 2.15, 1.75, 0.3)
    hand.roll = sign * -0.22
    hand.parent = lower
bpy.ops.object.mode_set(mode="OBJECT")

root = bpy.context.scene.hoaux_settings
root.shoulderBone = "Shoulder_L"
root.upperArmBone = "UpperArm_L"
root.lowerArmBone = "LowerArm_L"
root.handBone = "Hand_L"
root.processSymmetry = True
root.pipelinePreviewEnabled = True
assert ViewportPreview.active_owner() == PIPELINE_PREVIEW_OWNER
assert ViewportPreview._scene is not None
assert len(ViewportPreview._scene.lines) > 100

bpy.ops.object.mode_set(mode="POSE")
assert bpy.ops.hoaux.generate_pipeline() == {"FINISHED"}
assert obj.mode == "POSE"
assert not root.pipelinePreviewEnabled

generated = list(iter_hoaux_bones(armature))
assert len(generated) == 88
assert sum(bone.hotools_boneprops.hoAux.roleTag == "DEF" for bone in generated) == 44
assert sum(bone.hotools_boneprops.hoAux.roleTag == "TRK" for bone in generated) == 38
assert sum(bone.hotools_boneprops.hoAux.roleTag == "DIR" for bone in generated) == 6
assert sum(bone.use_deform for bone in generated) == 44
assert sum(len(obj.pose.bones[bone.name].constraints) for bone in generated) == 116
assert len(obj.animation_data.drivers) == 44
assert {
    bone.hotools_boneprops.hoAux.moduleType
    for bone in generated
    if bone.hotools_boneprops.hoAux.moduleType != "ROTATION_HALF"
} == set(WHOLE_ARM_PIPELINE_TYPES)

assert bpy.ops.hoaux.generate_pipeline() == {"FINISHED"}
assert len(list(iter_hoaux_bones(armature))) == 88
assert obj.mode == "POSE"

assert bpy.ops.hoaux.remove_pipeline() == {"FINISHED"}
assert obj.mode == "POSE"
assert not list(iter_hoaux_bones(armature))
assert find_collection(armature, "HOAUX:ROOT") is not None
assert find_collection(armature, "HOAUX:TAG:DEF") is not None
assert find_collection(armature, "HOAUX:TAG:TRK") is not None
assert find_collection(armature, "HOAUX:TAG:DIR") is not None
print("HOAUX_PIPELINE_OK bones=88 constraints=116 drivers=44 mode=POSE")
