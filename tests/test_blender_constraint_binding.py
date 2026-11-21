"""Authoring facts stay immutable across real MCH export preprocessing.

Optional -- ABSOLUTE_OUTPUT_DIRECTORY writes a disposable interoperability
fixture (authoring.v4.json, exported.v4.json and matching FBX). No user file is
loaded or saved; the default test writes no files.
"""

from copy import deepcopy
import json
from pathlib import Path
import sys

import bpy
from bpy.props import BoolProperty, CollectionProperty, PointerProperty
from bpy.types import PropertyGroup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from BoneTools.boneProperty import PG_Hotools_AuxBoneInfo, PG_Hotools_BoneRef, register_existing_aim_pair
from BoneTools.auxBone.copyRotation import CopyRotationCore
from Exporter.FbxExporter import FBXExporter
from RigConstraints.binding import build_export_document
from RigConstraints.blender.metadata import _replace_aux_constraints
from RigConstraints.blender.properties import PROPERTY_CLASSES, PG_RigConstraintGroup
from RigConstraints.codec import dumps, loads, fingerprint
from RigConstraints.source import capture_armature


class BindingProps(PropertyGroup):
    generateMCH: BoolProperty(default=False)
    auxBone: PointerProperty(type=PG_Hotools_AuxBoneInfo)
    constraintGroups: CollectionProperty(type=PG_RigConstraintGroup)


for cls in (PG_Hotools_BoneRef, PG_Hotools_AuxBoneInfo, *PROPERTY_CLASSES, BindingProps):
    bpy.utils.register_class(cls)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=BindingProps)
rig = bpy.data.objects.new("ConstraintBindingRig", bpy.data.armatures.new("ConstraintBindingData"))
bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
for index, name in enumerate(("Root", "Main", "Up", "CopyR", "Aim", "Twist", "Raw", "Weighted")):
    bone = rig.data.edit_bones.new(name)
    bone.head = (index * .2, (index % 3) * .15, .8)
    bone.tail = (index * .2 + .12, (index % 3) * .15 + .25, .1)
    bone.roll = .13 * index
    if name != "Root":
        bone.parent = rig.data.edit_bones["Root"]
bpy.ops.object.mode_set(mode="OBJECT")


def add(owner, kind, name, target="Main"):
    obj = rig if owner == "@object" else rig.pose.bones[owner]
    constraint = obj.constraints.new(kind)
    constraint.name = name
    if hasattr(constraint, "target"):
        constraint.target, constraint.subtarget = rig, target
    return constraint


CopyRotationCore.configure(rig, ["CopyR"], "Main", influence=.3)
raw = add("Raw", "COPY_ROTATION", "UserCopyRotation")
limit = add("Raw", "LIMIT_ROTATION", "UnimplementedLimit")
object_copy = add("@object", "COPY_LOCATION", "ObjectCopyLocation")
external = bpy.data.objects.new("ObjectConstraintTarget", None)
bpy.context.scene.collection.objects.link(external)
object_copy.target, object_copy.subtarget = external, ""
weighted = add("Weighted", "ARMATURE", "WeightedTargets")
for name, weight in (("Main", .7), ("Up", .3)):
    target = weighted.targets.new()
    target.target, target.subtarget, target.weight = rig, name, weight
aim_a = add("Aim", "DAMPED_TRACK", "AimDirection")
aim_a.track_axis = "TRACK_X"
aim_u = add("Aim", "LOCKED_TRACK", "AimUp", "Up")
aim_u.track_axis, aim_u.lock_axis = "TRACK_NEGATIVE_Z", "LOCK_X"
register_existing_aim_pair(rig.pose.bones["Aim"])
aux = rig.data.bones["Twist"].hotools_boneprops.auxBone
aux.isAuxBone, aux.auxType = True, "TWIST"
aux.sourceBones.add().name = "Main"
twist_r = add("Twist", "COPY_ROTATION", "TwistRotation")
twist_r.owner_space, twist_r.target_space = "LOCAL", "LOCAL_OWNER_ORIENT"
twist_s = add("Twist", "STRETCH_TO", "TwistStretch")
twist_s.volume, twist_s.keep_axis = "NO_VOLUME", "SWING_Y"
_replace_aux_constraints(rig.pose.bones["Twist"], [twist_r, twist_s])
rig.data.bones["Main"].hotools_boneprops.generateMCH = True
bpy.context.view_layer.update()
author = capture_armature(rig)
author["extension"] = {"future": [1, 2.5, "保留"]}
author["sources"][0]["constraint"]["parameters"]["future_parameter"] = {"preserve": True}
author["inputFingerprint"] = fingerprint(author)
saved_author = deepcopy(author)

# Binding without preprocessing preserves the same source set and stages.
plain = build_export_document(author, rig)
assert plain["sources"] == author["sources"]
assert plain["captureStage"] == "AUTHORING" and plain["bindings"]["captureStage"] == "POSTPROCESS"
assert plain["bindings"]["boneMap"] == []
assert author == saved_author

# Run actual MCH preprocessing. The original target names and rest matrices
# remain in authoring sources/context; final references belong to the overlay.
mch_map = FBXExporter.clear_armatures_bone_rotation([rig], [rig], rig)[rig.name]
assert mch_map == {"Main": "MCH_Main"}
rig.pose.bones["Raw"].constraints.move(1, 0)  # Name matching, never stack guesses.
before_final = capture_armature(rig, capture_stage="POSTPROCESS")
exported = build_export_document(author, rig, mch_map=mch_map)
after_final = capture_armature(rig, capture_stage="POSTPROCESS")
for snapshot in (before_final, after_final):
    snapshot.pop("exportTime", None)
    snapshot.pop("inputFingerprint", None)
assert before_final == after_final
assert author == saved_author
assert exported["sourceContext"] == author["sourceContext"]
assert exported["sources"][:len(author["sources"])] == author["sources"]
assert exported["extension"] == author["extension"]
assert exported["captureStage"] == "AUTHORING"
assert exported["bindings"]["captureStage"] == "POSTPROCESS"
assert exported["bindings"]["bindingContext"]["fbxBoneAxes"] == "Y_X"
assert exported["bindings"]["bindingContext"]["space"] == "BLENDER_ARMATURE"
assert any(row["boneName"] == "MCH_Main" for row in exported["bindings"]["bindingContext"]["bones"])
assert not any(row["boneName"] == "MCH_Main" for row in exported["sourceContext"]["bones"])
assert exported["bindings"]["boneMap"] == [{"sourceBone": "Main", "exportBone": "MCH_Main"}]
overlay = {row["sourceId"]: row for row in exported["bindings"]["constraintMap"]}
assert len(overlay) == len(exported["sources"])
by_name = {source["constraint"]["name"]: source for source in exported["sources"]}
copy_source = by_name[CopyRotationCore.CONSTRAINT_NAME]
assert copy_source["constraint"]["targetBoneName"] == "Main"
assert overlay[copy_source["sourceId"]]["targetBoneName"] == "MCH_Main"
object_source = by_name[object_copy.name]
assert object_source["ownerKind"] == "OBJECT"
assert overlay[object_source["sourceId"]]["targetObjectName"] == external.name
assert overlay[object_source["sourceId"]]["targetBoneName"] == ""
assert not any(object_source["sourceId"] in semantic["sourceIds"] for semantic in exported["semantics"])
raw_source = by_name[raw.name]
assert raw_source["constraint"]["stackIndex"] == 0
assert overlay[raw_source["sourceId"]]["stackIndex"] == 1
assert not any(raw_source["sourceId"] in semantic["sourceIds"] for semantic in exported["semantics"])
assert any(row["sourceIds"] == [raw_source["sourceId"]] and row["status"] == "UNKNOWN" for row in exported["diagnostics"])
weighted_source = by_name[weighted.name]
assert weighted_source["constraint"]["references"]["targets"][0]["properties"]["subtarget"] == "Main"
assert overlay[weighted_source["sourceId"]]["references"]["targets"][0]["properties"]["subtarget"] == "MCH_Main"
generated = [source for source in exported["sources"] if source["captureStage"] == "EXPORT_GENERATED"]
assert len(generated) == 1 and generated[0]["ownerBone"] == "MCH_Main"
assert generated[0]["constraint"]["constraintType"] == "CHILD_OF"
assert generated[0]["constraint"]["targetBoneName"] == "Main"
assert overlay[generated[0]["sourceId"]]["targetBoneName"] == "Main"  # Never map MCH's source into self.
mch_semantic = next(semantic for semantic in exported["semantics"] if semantic["semanticType"] == "MCH")
assert mch_semantic["sourceIds"] == [generated[0]["sourceId"]]
assert mch_semantic["parameters"]["sourceBones"] == ["Main"]
aim_semantic = next(semantic for semantic in exported["semantics"] if semantic["semanticType"] == "AIM")
assert aim_semantic["parameters"]["sourceBones"] == ["Main", "Up"]
assert aim_semantic["parameters"]["targetBone"] == "Main"
assert not exported["diagnostics"] or all(row["status"] == "UNKNOWN" for row in exported["diagnostics"]), exported["diagnostics"]
assert loads(dumps(exported))["sources"] == exported["sources"]


def rejects(action, expected):
    try:
        action()
    except ValueError as error:
        assert expected in str(error), str(error)
    else:
        raise AssertionError("Expected binding rejection: " + expected)


# Same stack/type is not enough after a rename; same name is not enough after a
# type change. Neither failure may alter the saved authoring input.
raw.name = "UserRenamedAfterCapture"
rejects(lambda: build_export_document(author, rig, mch_map=mch_map), "缺失或改名")
raw.name = "UserCopyRotation"
rig.pose.bones["Raw"].constraints.remove(raw)
wrong = add("Raw", "COPY_LOCATION", "UserCopyRotation")
rejects(lambda: build_export_document(author, rig, mch_map=mch_map), "类型改变")
rig.pose.bones["Raw"].constraints.remove(wrong)
raw = add("Raw", "COPY_ROTATION", "UserCopyRotation")
raw.subtarget = "MCH_Main"
unknown_added = add("Raw", "COPY_SCALE", "UnexpectedExportConstraint")
rejects(lambda: build_export_document(author, rig, mch_map=mch_map), "未声明的新约束")
rig.pose.bones["Raw"].constraints.remove(unknown_added)
rejects(lambda: build_export_document(author, rig, mch_map={"Main": "Main"}), "骨映射")
rejects(lambda: build_export_document({**author, "captureStage": "POSTPROCESS"}, rig, mch_map=mch_map), "AUTHORING")
assert author == saved_author

# A mapped generated bone without its generated relationship must never be
# accepted as a complete binding merely because all authored facts still match.
saved_mch_names = [constraint.name for constraint in rig.pose.bones["MCH_Main"].constraints]
for constraint in list(rig.pose.bones["MCH_Main"].constraints):
    rig.pose.bones["MCH_Main"].constraints.remove(constraint)
rig.data.bones["MCH_Main"].hotools_boneprops.constraintGroups.clear()
rig.data.bones["MCH_Main"].hotools_boneprops.auxBone.constraintNames.clear()
rejects(lambda: build_export_document(author, rig, mch_map=mch_map), "缺少完整语义")
FBXExporter.add_mch_parent_constraints(rig, mch_map)
assert [constraint.name for constraint in rig.pose.bones["MCH_Main"].constraints] == saved_mch_names

if "--" in sys.argv:
    output = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "authoring.v4.json").write_text(dumps(author) + "\n", encoding="utf-8")
    # Capture the actual current order again for the emitted matching FBX.
    current = build_export_document(author, rig, mch_map=mch_map)
    (output / "exported.v4.json").write_text(dumps(current) + "\n", encoding="utf-8")
    (output / "fixture-summary.json").write_text(json.dumps({
        "blender": bpy.app.version_string, "mchMap": mch_map,
        "sourceCount": len(current["sources"]), "semanticCount": len(current["semantics"]),
        "generatedSourceId": generated[0]["sourceId"],
    }, indent=2) + "\n", encoding="utf-8")
    # Mirror the production endpoint: the sidecar owns constraints, while FBX
    # exports un-constrained bind transforms, not an evaluated constrained pose.
    FBXExporter.clear_exported_constraints([rig])
    assert bpy.ops.export_scene.fbx(filepath=str(output / "constraint-binding.fbx"),
        use_selection=True, object_types={"ARMATURE"}, add_leaf_bones=False,
        primary_bone_axis="Y", secondary_bone_axis="X", bake_anim=False,
        axis_forward="-Z", axis_up="Y") == {"FINISHED"}
    print("CONSTRAINT_BINDING_FIXTURE", output)

print("CONSTRAINT_BINDING_OK", bpy.app.version_string)
