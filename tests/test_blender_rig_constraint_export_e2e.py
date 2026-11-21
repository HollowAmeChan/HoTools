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
from RigConstraints.source import capture_armature
from RigConstraints.semantics import translate
from RigConstraints.blender.properties import PROPERTY_CLASSES, PG_RigConstraintGroup
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
    constraintGroups: CollectionProperty(type=PG_RigConstraintGroup)


bpy.utils.register_class(TestBoneRef)
bpy.utils.register_class(TestAuxInfo)
for cls in PROPERTY_CLASSES:
    bpy.utils.register_class(cls)
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

constraint_data = translate(capture_armature(armature))
assert constraint_data["schemaVersion"] == 4
assert sorted(constraint_data["mchPlans"]) == ["Forearm", "Upper"]
declarations = {row["ownerBone"]: row for row in constraint_data["declarations"]}
sources = {row["sourceId"]: row for row in constraint_data["sources"]}
assert set(twist_names + fan_names + ["MCH_Upper", "MCH_Forearm"]) == set(declarations)
for name in twist_names:
    group = declarations[name]
    assert group["semanticType"] == "TWIST" and group["sourceBones"] == ["Upper"]
    members = [sources[sid]["constraint"] for sid in group["memberSourceIds"]]
    assert [row["constraintType"] for row in members] == ["COPY_ROTATION", "STRETCH_TO"]
    assert all(row["targetBoneName"] == "MCH_Forearm" for row in members)
for name in fan_names:
    group = declarations[name]
    assert group["semanticType"] == "FAN" and group["sourceBones"] == ["Forearm", "Hand"]
    assert [sources[sid]["constraint"]["constraintType"] for sid in group["memberSourceIds"]] == ["COPY_ROTATION"]
for source_name in ("Upper", "Forearm"):
    group = declarations["MCH_" + source_name]
    assert group["semanticType"] == "MCH" and group["sourceBones"] == [source_name]
    assert group["ownsBone"]
    raw = sources[group["memberSourceIds"][0]]["constraint"]
    assert raw["name"] == FBXExporter.MCH_PARENT_CONSTRAINT_NAME
    assert raw["constraintType"] == "CHILD_OF" and raw["targetBoneName"] == source_name

raw_by_key = {(row["ownerBone"], row["constraint"]["name"]): row for row in sources.values()}
manual = [(twist_names[0], "User_Twist_Interference"), ("Forearm", "User_Main_Interference"), ("Hand", "HoTools_FAN_CopyRotation")]
claimed = {sid for group in declarations.values() for sid in group["memberSourceIds"]}
assert all(raw_by_key[key]["sourceId"] not in claimed for key in manual)
assert raw_by_key[("Forearm", "User_Main_Interference")]["constraint"]["targetBoneName"] == "MCH_Upper"
unknown_copy = raw_by_key[("Hand", "HoTools_FAN_CopyRotation")]["sourceId"]
assert any(row["status"] == "UNKNOWN" and unknown_copy in row["sourceIds"] for row in constraint_data["diagnostics"])
keys = [(row["ownerBone"], row["constraint"]["stackIndex"]) for row in sources.values()]
assert len(keys) == len(set(keys)) and set(keys) == _constraint_keys(armature)
assert {row["semanticType"] for row in constraint_data["semantics"]} >= {"TWIST", "FAN", "MCH"}

print("RIG_CONSTRAINT_E2E_OK", bpy.app.version_string)
