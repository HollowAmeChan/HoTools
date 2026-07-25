import math
import sys
from pathlib import Path

import bpy
from bpy.props import PointerProperty
from bpy.types import PropertyGroup


BONE_TOOLS_DIR = Path(__file__).resolve().parents[2]
if str(BONE_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(BONE_TOOLS_DIR))

import hoAux
from hoAux.generation import iter_hoaux_bones
from hoAux.module_base import get_definition
from hoAux.operations import remove_scope
from hoAux.properties import PG_HoAuxBoneInfo


class _TestBoneProps(PropertyGroup):
    hoAux: PointerProperty(type=PG_HoAuxBoneInfo)


hoAux.register()
bpy.utils.register_class(_TestBoneProps)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=_TestBoneProps)

armature = bpy.data.armatures.new("LimbBulgeArmature")
obj = bpy.data.objects.new("LimbBulge", armature)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
for side, sign in (("L", 1.0), ("R", -1.0)):
    upper = armature.edit_bones.new(f"UpperArm_{side}")
    upper.head = (sign * 0.2, -0.4, 0.3)
    upper.tail = (sign * 1.15, 0.25, 0.0)
    upper.roll = sign * 0.32
    lower = armature.edit_bones.new(f"LowerArm_{side}")
    lower.head = upper.tail
    lower.tail = (sign * 1.8, 1.1, 0.35)
    lower.roll = sign * -0.27
    lower.parent = upper
bpy.ops.object.mode_set(mode="OBJECT")

root = bpy.context.scene.hoaux_settings
root.upperArmBone = "UpperArm_L"
root.lowerArmBone = "LowerArm_L"
root.processSymmetry = True

forearm_definition = get_definition("FOREARM_BULGE")
forearm_preview = forearm_definition.build_preview_scene(bpy.context)
assert len(forearm_preview.lines) == 10
assert len(forearm_preview.points) == 4
assert len(forearm_preview.labels) == 10

bpy.ops.object.mode_set(mode="EDIT")
assert bpy.ops.hoaux.generate_module(module_type="FOREARM_BULGE") == {"FINISHED"}
assert obj.mode == "EDIT"

upper_definition = get_definition("UPPER_ARM_LONGITUDINAL_BULGE")
upper_preview = upper_definition.build_preview_scene(bpy.context)
assert len(upper_preview.lines) == 10
bpy.ops.object.mode_set(mode="POSE")
assert bpy.ops.hoaux.generate_module(
    module_type="UPPER_ARM_LONGITUDINAL_BULGE"
) == {"FINISHED"}
assert obj.mode == "POSE"

generated = list(iter_hoaux_bones(armature))
assert len(generated) == 18
assert sum(bone.hotools_boneprops.hoAux.roleTag == "DEF" for bone in generated) == 8
assert sum(bone.hotools_boneprops.hoAux.roleTag == "TRK" for bone in generated) == 8
assert sum(bone.hotools_boneprops.hoAux.roleTag == "DIR" for bone in generated) == 2
assert sum(bone.use_deform for bone in generated) == 8
assert sum(len(obj.pose.bones[bone.name].constraints) for bone in generated) == 10
assert len(obj.animation_data.drivers) == 8
assert all(
    target.rotation_mode == "QUATERNION"
    for fcurve in obj.animation_data.drivers
    for variable in fcurve.driver.variables
    for target in variable.targets
)

lower_pose = obj.pose.bones["LowerArm_L"]
lower_pose.rotation_mode = "XYZ"
lower_pose.rotation_euler.z = math.radians(135.0)
bpy.context.view_layer.update()
forearm_up = next(
    bone
    for bone in generated
    if bone.hotools_boneprops.hoAux.moduleType == "FOREARM_BULGE"
    and bone.hotools_boneprops.hoAux.roleTag == "DEF"
    and bone.hotools_boneprops.hoAux.marker == "UP"
    and bone.hotools_boneprops.hoAux.side == "L"
)
influence = next(
    constraint.influence
    for constraint in obj.pose.bones[forearm_up.name].constraints
    if constraint.type == "COPY_LOCATION"
)
assert abs(influence - 0.5) < 1e-4, influence

removed = remove_scope(obj)
assert removed["bones"] == 18
assert "UpperArm_L" in armature.bones
assert "LowerArm_L" in armature.bones
print("HOAUX_BULGE_OK bones=18 constraints=10 drivers=8 influence=0.5")
