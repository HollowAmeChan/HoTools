"""Blender integration test for explicit Aux bone/constraint ownership."""

import sys
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup


ADDON_ROOT = Path(__file__).resolve().parents[1]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from BoneTools.auxBone.boneFan import BoneFanCore
from BoneTools.auxBone.boneFanSide import BoneFanSideCore
from BoneTools.auxBone.boneFanSingle import BoneFanSingleCore
from BoneTools.auxBone.boneTwist import TwistBoneCore
from BoneTools.boneProperty import _replace_aux_constraints
from Exporter.ConstraintIRExporter import ConstraintIRExporter
from Utils import bone_utils


class TestBoneRef(PropertyGroup):
    name: StringProperty(default="")


class TestAuxInfo(PropertyGroup):
    isAuxBone: BoolProperty(default=False)
    auxType: StringProperty(default="NONE")
    sourceBones: CollectionProperty(type=TestBoneRef)
    constraintNames: CollectionProperty(type=TestBoneRef)


class TestBoneProps(PropertyGroup):
    generateMCH: BoolProperty(default=False)
    auxBone: PointerProperty(type=TestAuxInfo)


def tag_aux(data_bone, aux_type, sources):
    aux = data_bone.hotools_boneprops.auxBone
    aux.isAuxBone = True
    aux.auxType = aux_type
    aux.sourceBones.clear()
    aux.constraintNames.clear()
    for source in sources:
        item = aux.sourceBones.add()
        item.name = source


def add_manual_name_collision(pose_bone, constraint_type, name):
    constraint = pose_bone.constraints.new(constraint_type)
    constraint.name = name
    return constraint


for cls in (TestBoneRef, TestAuxInfo, TestBoneProps):
    bpy.utils.register_class(cls)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=TestBoneProps)

data = bpy.data.armatures.new("AuxOwnershipData")
armature = bpy.data.objects.new("AuxOwnership", data)
bpy.context.scene.collection.objects.link(armature)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")

root = data.edit_bones.new("Root")
root.head = (0.0, 0.0, 0.0)
root.tail = (0.0, 1.0, 0.0)
main = data.edit_bones.new("Main")
main.head = root.tail
main.tail = (0.0, 2.0, 0.25)
main.parent = root
target = data.edit_bones.new("Target")
target.head = main.tail
target.tail = (0.0, 3.0, 0.5)
target.parent = main

collision_name = TwistBoneCore._twist_name("Main", 3, 2)
user_collision = data.edit_bones.new(collision_name)
user_collision.head = (2.0, 0.0, 0.0)
user_collision.tail = (2.0, 1.0, 0.0)

fan_types = (
    ("FanAux", "FAN", BoneFanCore),
    ("FanSingleAux", "FAN_SINGLE", BoneFanSingleCore),
    ("FanSideAux", "FAN_SIDE", BoneFanSideCore),
)
for bone_name, _aux_type, _core in fan_types:
    bone = data.edit_bones.new(bone_name)
    bone.head = (1.0, 1.0, 0.0)
    bone.tail = (1.0, 2.0, 0.0)
    bone.parent = main

bpy.ops.object.mode_set(mode="OBJECT")
for bone_name, aux_type, _core in fan_types:
    tag_aux(data.bones[bone_name], aux_type, ["Main", "Target"])

# A preferred-name collision is user data. Generation must report it before
# deleting or creating any Twist bone.
try:
    TwistBoneCore.create_twist_chain(
        armature,
        "Main",
        3,
        keep_head_end_weight=True,
    )
except RuntimeError as error:
    assert collision_name in str(error)
else:
    raise AssertionError("Twist generation must stop on a user bone-name collision")
assert data.bones.get(collision_name) is not None
assert not data.bones[collision_name].hotools_boneprops.auxBone.isAuxBone

# Remove only the test collision, then create the valid chain.
bpy.ops.object.mode_set(mode="EDIT")
data.edit_bones.remove(data.edit_bones[collision_name])
bpy.ops.object.mode_set(mode="OBJECT")
first = TwistBoneCore.create_twist_chain(
    armature,
    "Main",
    3,
    keep_head_end_weight=True,
)
assert collision_name in first["created_names"]
assert len(first["created_names"]) == 2
for bone_name in first["created_names"]:
    aux = data.bones[bone_name].hotools_boneprops.auxBone
    assert aux.isAuxBone
    assert aux.auxType == "TWIST"
    assert [item.name for item in aux.sourceBones] == ["Main"]

second = TwistBoneCore.create_twist_chain(
    armature,
    "Main",
    3,
    keep_head_end_weight=True,
)
assert set(second["replaced_names"]) == set(first["created_names"])
assert len(second["created_names"]) == 2

copy_name = bone_utils.aux_constraint_name("TWIST", "CopyRotation")
stretch_name = bone_utils.aux_constraint_name("TWIST", "StretchTo")
manual_constraints = []
for bone_name in second["created_names"]:
    pose_bone = armature.pose.bones[bone_name]
    manual_constraints.extend(
        (
            add_manual_name_collision(pose_bone, "COPY_ROTATION", copy_name),
            add_manual_name_collision(pose_bone, "STRETCH_TO", stretch_name),
        )
    )

# The preferred constraint names are also owned resources. An unregistered
# user constraint with either name must abort the whole operation.
try:
    TwistBoneCore.add_copy_rotation_to_twist_bones(
        bpy.context,
        armature,
        ["Main"],
        second["created_names"],
        manual_target="Target",
    )
except RuntimeError as error:
    assert copy_name in str(error) or stretch_name in str(error)
else:
    raise AssertionError("Twist constraints must stop on a preferred-name collision")

for bone_name in second["created_names"]:
    pose_bone = armature.pose.bones[bone_name]
    for constraint in list(pose_bone.constraints):
        if constraint in manual_constraints:
            pose_bone.constraints.remove(constraint)
manual_constraints.clear()

count, target_map = TwistBoneCore.add_copy_rotation_to_twist_bones(
    bpy.context,
    armature,
    ["Main"],
    second["created_names"],
    manual_target="Target",
)
assert count == 2
assert target_map == {"Main": "Target"}

for bone_name in second["created_names"]:
    pose_bone = armature.pose.bones[bone_name]
    aux = data.bones[bone_name].hotools_boneprops.auxBone
    registered = [item.name for item in aux.constraintNames]
    assert len(registered) == 2
    assert set(registered) == {copy_name, stretch_name}

for bone_name, aux_type, core in fan_types:
    pose_bone = armature.pose.bones[bone_name]
    preferred_name = bone_utils.aux_constraint_name(aux_type, "CopyRotation")
    manual = add_manual_name_collision(pose_bone, "COPY_ROTATION", preferred_name)
    try:
        core._ensure_copy_rotation_constraint(
            pose_bone,
            armature,
            "Target",
            0.5,
        )
    except RuntimeError as error:
        assert preferred_name in str(error)
    else:
        raise AssertionError(f"{aux_type} must stop on a preferred-name collision")
    pose_bone.constraints.remove(manual)
    generated = core._ensure_copy_rotation_constraint(
        pose_bone,
        armature,
        "Target",
        0.5,
    )
    _replace_aux_constraints(pose_bone, [generated])
    assert generated.name == preferred_name
    assert [item.name for item in data.bones[bone_name].hotools_boneprops.auxBone.constraintNames] == [
        generated.name
    ]

constraint_data = ConstraintIRExporter.export_to_dict(
    armature,
    export_time="test",
)
known = constraint_data["knownConstraints"]
unknown = constraint_data["unknownConstraints"]
known_keys = {
    (item["ownerBone"], item["constraint"]["stackIndex"])
    for item in known
}
unknown_keys = {
    (item["ownerBone"], item["constraint"]["stackIndex"])
    for item in unknown
}
all_keys = {
    (pose_bone.name, stack_index)
    for pose_bone in armature.pose.bones
    for stack_index, _constraint in enumerate(pose_bone.constraints)
}
assert len(known_keys) == len(known) == 7
assert len(unknown_keys) == len(unknown) == 0
assert known_keys.isdisjoint(unknown_keys)
assert known_keys | unknown_keys == all_keys
assert {item["relationType"] for item in known} == {"AUX_CONSTRAINT"}
assert {item["auxType"] for item in known} == {
    "TWIST",
    "FAN",
    "FAN_SINGLE",
    "FAN_SIDE",
}

print("AUX_CONSTRAINT_OWNERSHIP_OK", bpy.app.version_string)
