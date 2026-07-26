import math
import sys
from pathlib import Path

import bpy
from bpy.props import PointerProperty
from bpy.types import PropertyGroup


ADDON_DIR = Path(__file__).resolve().parents[3]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from BoneTools import hoAux
from BoneTools.hoAux.generation import iter_hoaux_bones
from BoneTools.hoAux.module_base import get_definition
from BoneTools.hoAux.operations import remove_scope
from BoneTools.hoAux.properties import PG_HoAuxBoneInfo


class _TestBoneProps(PropertyGroup):
    hoAux: PointerProperty(type=PG_HoAuxBoneInfo)


hoAux.register()
bpy.utils.register_class(_TestBoneProps)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=_TestBoneProps)

armature = bpy.data.armatures.new("UpperArmSlideArmature")
obj = bpy.data.objects.new("UpperArmSlide", armature)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
for side, sign in (("L", 1.0), ("R", -1.0)):
    upper = armature.edit_bones.new(f"UpperArm_{side}")
    upper.head = (sign * 0.15, -0.3, 0.25)
    upper.tail = (sign * 1.2, 0.2, -0.05)
    upper.roll = sign * 0.34
    lower = armature.edit_bones.new(f"LowerArm_{side}")
    lower.head = upper.tail
    lower.tail = (sign * 1.75, 1.15, 0.3)
    lower.roll = sign * -0.29
    lower.parent = upper
bpy.ops.object.mode_set(mode="OBJECT")

root = bpy.context.scene.hoaux_settings
root.upperArmBone = "UpperArm_L"
root.lowerArmBone = "LowerArm_L"
root.processSymmetry = True
definition = get_definition("UPPER_ARM_MUSCLE_SLIDE")
preview = definition.build_preview_scene(bpy.context)
assert len(preview.lines) == 14
assert len(preview.points) == 4
assert len(preview.labels) == 14

bpy.ops.object.mode_set(mode="POSE")
assert bpy.ops.hoaux.generate_module(
    module_type="UPPER_ARM_MUSCLE_SLIDE"
) == {"FINISHED"}
assert obj.mode == "POSE"

generated = list(iter_hoaux_bones(armature))
assert len(generated) == 14
assert sum(bone.hotools_boneprops.hoAux.roleTag == "DEF" for bone in generated) == 4
assert sum(bone.hotools_boneprops.hoAux.roleTag == "TRK" for bone in generated) == 8
assert sum(bone.hotools_boneprops.hoAux.roleTag == "DIR" for bone in generated) == 2
assert sum(bone.use_deform for bone in generated) == 4
assert sum(len(obj.pose.bones[bone.name].constraints) for bone in generated) == 14
assert len(obj.animation_data.drivers) == 12
assert all(
    target.rotation_mode == "QUATERNION"
    for fcurve in obj.animation_data.drivers
    for variable in fcurve.driver.variables
    for target in variable.targets
)

def slide_def(marker):
    return next(
        bone
        for bone in generated
        if bone.hotools_boneprops.hoAux.moduleType == "UPPER_ARM_MUSCLE_SLIDE"
        and bone.hotools_boneprops.hoAux.roleTag == "DEF"
        and bone.hotools_boneprops.hoAux.marker == marker
        and bone.hotools_boneprops.hoAux.side == "L"
    )


lower_pose = obj.pose.bones["LowerArm_L"]
lower_pose.rotation_mode = "XYZ"
lower_pose.rotation_euler.z = math.radians(45.0)
bpy.context.view_layer.update()
out_pose = obj.pose.bones[slide_def("OUT").name]
out_locations = [
    constraint
    for constraint in out_pose.constraints
    if constraint.type == "COPY_LOCATION"
]
assert len(out_locations) == 2
assert abs(out_locations[0].influence - 0.25) < 1e-4
assert abs(out_locations[1].influence) < 1e-6

lower_pose.rotation_euler.z = math.radians(135.0)
bpy.context.view_layer.update()
assert abs(out_locations[0].influence - 0.75) < 1e-4
assert abs(out_locations[1].influence - 0.5) < 1e-4

removed = remove_scope(obj)
assert removed["bones"] == 14
assert "UpperArm_L" in armature.bones
assert "LowerArm_L" in armature.bones
print("HOAUX_SLIDE_OK bones=14 constraints=14 drivers=12 responses=.75/.5")
