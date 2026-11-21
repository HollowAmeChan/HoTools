"""Synthetic direct v4 numerical oracle through the actual HoFBX operator.

blender --background --factory-startup --disable-autoexec --python-exit-code 1
        --python tests/export_direct_v4_fixture.py -- ABSOLUTE_OUTPUT_DIRECTORY

Only disposable generated bones are used. Blender evaluates all expected poses;
this producer does not implement the Unity algorithms or claim merge coverage.
"""

import json
import random
import sys
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, PointerProperty
from bpy.types import PropertyGroup
from mathutils import Euler, Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from BoneTools.boneProperty import PG_Hotools_BoneRef, PG_Hotools_AuxBoneInfo, register_existing_aim_pair
from BoneTools.auxBone.copyRotation import CopyRotationCore
from Exporter.FbxExporter import OP_FinalFBXExport
from RigConstraints import codec
from RigConstraints.blender.properties import PROPERTY_CLASSES, PG_RigConstraintGroup
from RigConstraints.source import capture_armature


class FixtureProps(PropertyGroup):
    generateMCH: BoolProperty(default=False)
    auxBone: PointerProperty(type=PG_Hotools_AuxBoneInfo)
    constraintGroups: CollectionProperty(type=PG_RigConstraintGroup)


for cls in (PG_Hotools_BoneRef, PG_Hotools_AuxBoneInfo, *PROPERTY_CLASSES, FixtureProps):
    bpy.utils.register_class(cls)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=FixtureProps)
out = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
out.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
data = bpy.data.armatures.new("DirectData")
rig = bpy.data.objects.new("DirectRig", data)
bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")


def bone(name, head, direction=(.07, .3, .13), parent="Root", roll=0):
    value = data.edit_bones.new(name)
    value.head, value.tail = head, tuple(a + b for a, b in zip(head, direction))
    value.roll = roll
    if parent:
        value.parent = data.edit_bones[parent]
    return value


bone("Root", (0, 0, 0), (0, .3, 0), parent="")
bone("TargetA", (.7, .2, 1.0), (.1, .27, -.13), roll=.41)
bone("TargetB", (-.6, .3, .85), (-.13, .18, .16), roll=-.62)
bone("AimTarget", (.8, -.1, 1.1), (.2, .3, .1))
bone("UpTarget", (-.25, .9, 1.4), (.1, .2, .1))
inputs = ["Root", "TargetA", "TargetB", "AimTarget", "UpTarget"]
owners = []
for index, influence in enumerate((0, .3, 1)):
    for prefix, x in (("Location", .3), ("Rotation", -.3)):
        name = prefix + str(index)
        bone(name, (x + index * .04, -.3, .6 + index * .12), (.15, .1, -.27), roll=-.7 + index * .22)
        owners.append(name)
bone("Weighted", (.15, -.2, 1.1), (.1, .25, -.1), roll=.23)
bone("Aim", (-.4, -.2, .9), (.1, .3, -.15), roll=-.3)
owners += ["Weighted", "Aim"]
bpy.ops.object.mode_set(mode="OBJECT")
for index, influence in enumerate((0, .3, 1)):
    owner = rig.pose.bones["Location" + str(index)]
    value = owner.constraints.new("COPY_LOCATION")
    value.name, value.target, value.subtarget = "WorldPosition", rig, "TargetA"
    value.owner_space = value.target_space = "WORLD"
    value.influence = influence
    CopyRotationCore.configure(rig, ["Rotation" + str(index)], "TargetB", influence=influence,
                               owner_space="WORLD", target_space="WORLD")
weighted = rig.pose.bones["Weighted"].constraints.new("ARMATURE")
weighted.name = "TwoSourceRigidLbs"
for name, weight in (("TargetA", .65), ("TargetB", .35)):
    value = weighted.targets.new()
    value.target, value.subtarget, value.weight = rig, name, weight
weighted.use_deform_preserve_volume = False
weighted.use_bone_envelopes = False
weighted.use_current_location = False
owner = rig.pose.bones["Aim"]
direction = owner.constraints.new("DAMPED_TRACK")
direction.name, direction.target, direction.subtarget, direction.track_axis = "Direction", rig, "AimTarget", "TRACK_X"
up = owner.constraints.new("LOCKED_TRACK")
up.name, up.target, up.subtarget, up.track_axis, up.lock_axis = "Up", rig, "UpTarget", "TRACK_NEGATIVE_Z", "LOCK_X"
register_existing_aim_pair(owner)
bpy.context.view_layer.update()


def flat(matrix):
    return [float(value) for row in matrix for value in row]


def apply(motions):
    for pose in rig.pose.bones:
        pose.matrix_basis = Matrix.Identity(4)
    for name in inputs:
        angles, location = motions.get(name, ((0, 0, 0), (0, 0, 0)))
        rig.pose.bones[name].matrix_basis = Matrix.Translation(Vector(location)) @ Euler(angles, "XYZ").to_matrix().to_4x4()
    bpy.context.view_layer.update()


rng = random.Random(20261121)
cases = [("rest", {})]
for index in range(24):
    motions = {}
    for name in inputs:
        magnitude = .3 if name == "Root" else .6
        angles = tuple(rng.uniform(-magnitude, magnitude) for _ in range(3))
        location = tuple(rng.uniform(-.08, .08) for _ in range(3))
        motions[name] = angles, location
    cases.append(("pose_{:02d}".format(index), motions))
rests = [{"name": value.name, "matrix": flat(value.matrix_local)} for value in data.bones]
samples = []
for label, motions in cases:
    apply(motions)
    expected = [{"name": pose.name, "matrix": flat(pose.matrix)} for pose in rig.pose.bones]
    samples.append({"name": label,
                    "inputs": [{"name": name, "matrix": flat(rig.pose.bones[name].matrix)} for name in inputs],
                    "expected": expected})
apply({})
author = capture_armature(rig)
bpy.utils.register_class(OP_FinalFBXExport)
try:
    assert "rigConstraintIRVersion" not in bpy.ops.ho.final_fbx_export.get_rna_type().properties
    assert bpy.ops.ho.final_fbx_export("EXEC_DEFAULT", filepath=str(out / "Direct.fbx"),
        exportUnityMetadata=False, exportBoneConstraint=True, exportBoneCollection=False,
        exportHumanoidMapping=False, exportBsCorrective=False, addLeafBones=False,
        generateMCHBones=False, applyArmaturePose=False, fixObjectTransform=False,
        applyExportConstraints=False, allowNativeConstraintApproximation=True) == {"FINISHED"}
finally:
    bpy.utils.unregister_class(OP_FinalFBXExport)
sidecars = list((out / "HoFBX").glob("Direct_*_constraint.json"))
assert len(sidecars) == 1, sidecars
exported = codec.loads(sidecars[0].read_text(encoding="utf-8"))
assert exported["schemaVersion"] == 4 and exported["sources"] == author["sources"]
assert not exported["diagnostics"], exported["diagnostics"]
assert {row["semanticType"] for row in exported["semantics"]} == {"COPY_LOCATION", "COPY_ROTATION", "ARMATURE", "AIM"}
assert len(exported["semantics"]) == 8
assert exported["importPolicy"] == {"allowNativeApproximation": True}
(out / "Direct_v4.json").write_text(codec.dumps(exported), encoding="utf-8")
fixture = {"variant": "Direct", "blenderVersion": bpy.app.version_string,
           "bones": rests, "ownerNames": owners, "inputNames": inputs, "samples": samples,
           "exportRoute": "ACTUAL_HOFBX_OPERATOR", "sampleSpace": "BLENDER_ARMATURE",
           "coverage": ["Copy Location", "world copyR", "two-source Armature", "explicit Aim", "dynamic source and common parent"]}
(out / "Direct_samples.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
assert (out / "Direct.fbx").stat().st_size > 1000
print("DIRECT_V4_FIXTURE_OK", bpy.app.version_string, len(owners), len(samples), out)
