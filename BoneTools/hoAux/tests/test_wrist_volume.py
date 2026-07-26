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

armature = bpy.data.armatures.new("WristVolumeArmature")
obj = bpy.data.objects.new("WristVolume", armature)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
for side, sign in (("L", 1.0), ("R", -1.0)):
    lower = armature.edit_bones.new(f"LowerArm_{side}")
    lower.head = (sign * 1.3, -0.7, 0.4)
    lower.tail = (sign * 0.35, 0.1, 0.0)
    lower.roll = sign * 0.31
    hand = armature.edit_bones.new(f"Hand_{side}")
    hand.head = lower.tail
    hand.tail = (sign * 0.05, 0.65, 0.2)
    hand.roll = sign * -0.24
    hand.parent = lower
bpy.ops.object.mode_set(mode="OBJECT")

root = bpy.context.scene.hoaux_settings
root.lowerArmBone = "LowerArm_L"
root.handBone = "Hand_L"
root.processSymmetry = True
definition = get_definition("WRIST_VOLUME")
preview = definition.build_preview_scene(bpy.context)
assert len(preview.lines) == 20
assert len(preview.points) == 2
assert len(preview.labels) == 20

bpy.ops.object.mode_set(mode="POSE")
operator_result = bpy.ops.hoaux.generate_module(module_type="WRIST_VOLUME")
assert operator_result == {"FINISHED"}
assert obj.mode == "POSE"

generated = list(iter_hoaux_bones(armature))
assert len(generated) == 20
assert sum(bone.hotools_boneprops.hoAux.roleTag == "DEF" for bone in generated) == 8
assert sum(bone.hotools_boneprops.hoAux.roleTag == "TRK" for bone in generated) == 10
assert sum(bone.hotools_boneprops.hoAux.roleTag == "DIR" for bone in generated) == 2
assert sum(bone.use_deform for bone in generated) == 8
assert sum(len(obj.pose.bones[bone.name].constraints) for bone in generated) == 32
assert len(obj.animation_data.drivers) == 12
assert all(
    target.rotation_mode == "QUATERNION"
    for fcurve in obj.animation_data.drivers
    for variable in fcurve.driver.variables
    for target in variable.targets
)

hand_pose = obj.pose.bones["Hand_L"]
hand_pose.rotation_mode = "XYZ"
hand_pose.rotation_euler.x = math.radians(45.0)
bpy.context.view_layer.update()

def bone_with(role, marker, side="L"):
    return next(
        bone
        for bone in generated
        if bone.hotools_boneprops.hoAux.roleTag == role
        and bone.hotools_boneprops.hoAux.marker == marker
        and bone.hotools_boneprops.hoAux.side == side
    )


x1_pose = obj.pose.bones[bone_with("DEF", "X1").name]
x1_location = next(
    constraint
    for constraint in x1_pose.constraints
    if constraint.type == "COPY_LOCATION"
)
assert abs(x1_location.influence - 0.25) < 1e-4, x1_location.influence

x0_pose = obj.pose.bones[bone_with("DEF", "X0").name]
x0_locations = [
    constraint
    for constraint in x0_pose.constraints
    if constraint.type == "COPY_LOCATION"
]
assert len(x0_locations) == 2
assert abs(x0_locations[0].influence) < 1e-6
assert abs(x0_locations[1].influence - 0.5) < 1e-4

removed = remove_scope(obj)
assert removed["bones"] == 20
assert "LowerArm_L" in armature.bones
assert "Hand_L" in armature.bones
print("HOAUX_WRIST_OK bones=20 constraints=32 drivers=12 mode=POSE")
