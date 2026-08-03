"""End-to-end Blender regression test for generated Aux/MCH constraint ownership."""

import json
import sys
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from BoneTools.auxBone.boneFan import BoneFanCore
from BoneTools.auxBone.boneTwist import TwistBoneCore
from Exporter.ConstraintIRExporter import ConstraintIRExporter
from Exporter.FbxExporter import FBXExporter


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


bpy.utils.register_class(TestBoneRef)
bpy.utils.register_class(TestAuxInfo)
bpy.utils.register_class(TestBoneProps)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=TestBoneProps)


def _set_constraint_target(constraint, armature, bone_name):
    constraint.target = armature
    constraint.subtarget = bone_name


def _constraint_keys(armature):
    return {
        (pose_bone.name, stack_index)
        for pose_bone in armature.pose.bones
        for stack_index, _constraint in enumerate(pose_bone.constraints)
    }


data = bpy.data.armatures.new("RigConstraintE2EData")
armature = bpy.data.objects.new("RigConstraintE2E", data)
bpy.context.scene.collection.objects.link(armature)
bpy.ops.object.select_all(action="DESELECT")
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")

# A bent, connected chain gives both Twist and Fan a non-degenerate frame.
root = data.edit_bones.new("Root")
root.head = (0.0, 0.0, 0.0)
root.tail = (0.0, 1.0, 0.0)

upper = data.edit_bones.new("Upper")
upper.head = root.tail
upper.tail = (0.35, 2.0, 0.65)
upper.parent = root

forearm = data.edit_bones.new("Forearm")
forearm.head = upper.tail
forearm.tail = (1.1, 2.65, 0.8)
forearm.parent = upper

hand = data.edit_bones.new("Hand")
hand.head = forearm.tail
hand.tail = (1.45, 3.25, 1.25)
hand.parent = forearm

palm = data.edit_bones.new("Palm")
palm.head = hand.tail
palm.tail = (1.7, 3.8, 1.4)
palm.parent = hand

finger_01 = data.edit_bones.new("Finger_01")
finger_01.head = palm.tail
finger_01.tail = (1.9, 4.25, 1.55)
finger_01.parent = palm

finger_02 = data.edit_bones.new("Finger_02")
finger_02.head = finger_01.tail
finger_02.tail = (2.05, 4.65, 1.65)
finger_02.parent = finger_01

finger_03 = data.edit_bones.new("Finger_03")
finger_03.head = finger_02.tail
finger_03.tail = (2.15, 5.0, 1.7)
finger_03.parent = finger_02

finger_04 = data.edit_bones.new("Finger_04")
finger_04.head = finger_03.tail
finger_04.tail = (2.2, 5.3, 1.72)
finger_04.parent = finger_03

# The generators are designed to be called from Edit mode.
twist_result = TwistBoneCore.create_twist_chain(
    armature,
    "Upper",
    count=3,
    twist_length_factor=0.2,
    keep_head_end_weight=False,
)
twist_names = twist_result["created_names"]
assert len(twist_names) == 3, twist_result
twist_count, twist_targets = TwistBoneCore.add_copy_rotation_to_twist_bones(
    bpy.context,
    armature,
    ["Upper"],
    twist_names,
    manual_target="Forearm",
    top_influence=0.2,
    bottom_influence=0.8,
)
assert twist_count == 3
assert twist_targets == {"Upper": "Forearm"}

fan_names = BoneFanCore._create_fan_bones(
    armature,
    ["Forearm", "Hand"],
    "out",
    count=2,
    length_factor=0.35,
    pin_length_factor=0.25,
    bone_collection_name="RigConstraintE2EFan",
    influence_scale=1.0,
    name_prefix="E2E_",
)
assert len(fan_names) == 2, fan_names

# All generator methods restore Edit mode. Add user constraints in Object mode
# after generated ownership has been recorded, so the exporter must classify them
# as unknown without relying on their names or target types.
bpy.ops.object.mode_set(mode="OBJECT")
for bone_name in ("Upper", "Forearm"):
    data.bones[bone_name].hotools_boneprops.generateMCH = True

twist_owner = armature.pose.bones[twist_names[0]]
user_twist = twist_owner.constraints.new("COPY_LOCATION")
user_twist.name = "User_Twist_Interference"
_set_constraint_target(user_twist, armature, "Hand")

user_main = armature.pose.bones["Forearm"].constraints.new("COPY_LOCATION")
user_main.name = "User_Main_Interference"
_set_constraint_target(user_main, armature, "Upper")

# Same display name as a generated Fan constraint, but on a different owner.
# Name lookup must remain owner-local.
user_same_name = armature.pose.bones["Hand"].constraints.new("COPY_ROTATION")
user_same_name.name = "HoTools_FAN_CopyRotation"
_set_constraint_target(user_same_name, armature, "Upper")

# MCH preprocessing must happen after Aux generation. It moves references to
# generated MCH bones, then creates and registers the temporary Parent bindings.
name_maps = FBXExporter.clear_armatures_bone_rotation(
    [armature],
    [armature],
    armature,
)
assert name_maps == {armature.name: {"Upper": "MCH_Upper", "Forearm": "MCH_Forearm"}}

constraint_data = json.loads(
    ConstraintIRExporter.export_to_json(
        armature,
        export_time="2026-08-03T00:00:00Z",
    )
)

assert constraint_data["mchEnabledBones"] == ["Forearm", "Upper"]
binding_map = {item["sourceBone"]: item for item in constraint_data["mchBindings"]}
assert set(binding_map) == {"Upper", "Forearm"}
for source_name in ("Upper", "Forearm"):
    binding = binding_map[source_name]
    assert binding["mchBone"] == f"MCH_{source_name}"
    assert binding["constraint"]["constraintType"] == "CHILD_OF"
    assert binding["constraint"]["targetObjectName"] == armature.name
    assert binding["constraint"]["targetBoneName"] == source_name

aux_map = {item["boneName"]: item for item in constraint_data["auxBones"]}
assert set(twist_names).issubset(aux_map)
assert set(fan_names).issubset(aux_map)
assert {"MCH_Upper", "MCH_Forearm"}.issubset(aux_map)

for twist_name in twist_names:
    twist = aux_map[twist_name]
    assert twist["auxType"] == "TWIST"
    assert twist["sourceBones"] == ["Upper"]
    assert twist["constraintNames"] == [
        "HoTools_TWIST_CopyRotation",
        "HoTools_TWIST_StretchTo",
    ]
    assert [item["constraintType"] for item in twist["constraints"]] == [
        "COPY_ROTATION",
        "STRETCH_TO",
    ]
    assert all(
        item["targetBoneName"] == "MCH_Forearm"
        for item in twist["constraints"]
    )
    assert twist["involvedBones"]

for fan_name in fan_names:
    fan = aux_map[fan_name]
    assert fan["auxType"] == "FAN"
    assert fan["sourceBones"] == ["Forearm", "Hand"]
    assert fan["constraintNames"] == ["HoTools_FAN_CopyRotation"]
    assert [item["constraintType"] for item in fan["constraints"]] == [
        "COPY_ROTATION"
    ]

for mch_name, source_name in (
    ("MCH_Upper", "Upper"),
    ("MCH_Forearm", "Forearm"),
):
    mch = aux_map[mch_name]
    assert mch["auxType"] == "MCH"
    assert mch["sourceBones"] == [source_name]
    assert mch["constraintNames"] == [FBXExporter.MCH_PARENT_CONSTRAINT_NAME]
    assert mch["constraints"] == []

unknown = {
    (item["ownerBone"], item["constraint"]["name"]): item
    for item in constraint_data["unknownConstraints"]
}
assert (twist_names[0], "User_Twist_Interference") in unknown
assert ("Forearm", "User_Main_Interference") in unknown
assert ("Hand", "HoTools_FAN_CopyRotation") in unknown
assert unknown[("Forearm", "User_Main_Interference")]["constraint"][
    "targetBoneName"
] == "MCH_Upper"

known_keys = {
    (item["ownerBone"], item["constraint"]["stackIndex"])
    for item in constraint_data["knownConstraints"]
}
unknown_keys = {
    (item["ownerBone"], item["constraint"]["stackIndex"])
    for item in constraint_data["unknownConstraints"]
}
all_keys = _constraint_keys(armature)
assert known_keys.isdisjoint(unknown_keys)
assert len(known_keys) == len(constraint_data["knownConstraints"])
assert len(unknown_keys) == len(constraint_data["unknownConstraints"])
assert known_keys | unknown_keys == all_keys

print("RIG_CONSTRAINT_E2E_OK", bpy.app.version_string)
