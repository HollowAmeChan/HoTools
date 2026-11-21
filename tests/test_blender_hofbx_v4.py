"""Actual HoFBX operator v4/v3 sidecars and normal undo restoration.

Uses only disposable synthetic scenes. Optional -- ABSOLUTE_OUTPUT_DIRECTORY
keeps the generated FBX/HoFBX files for Unity interoperability checks.
"""

from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

# Match existing exporter integration tests without importing all addon UI/GPU
# modules into a background Blender process.
for name, directory in (("HoTools", ROOT), ("HoTools.ShapekeyTools", ROOT / "ShapekeyTools")):
    module = types.ModuleType(name)
    module.__path__ = [str(directory)]
    sys.modules.setdefault(name, module)
from BoneTools import register as register_bones, unregister as unregister_bones
from BoneTools.auxBone.boneFan import BoneFanCore
from BoneTools.auxBone.boneTwist import TwistBoneCore
from BoneTools.auxBone.copyRotation import CopyRotationCore
from BoneTools.boneProperty import register_existing_aim_pair
from Exporter import FbxExporter
from RigConstraints.source import capture_armature
from RigConstraints.codec import loads
from _fbx_dt_testkit import mesh_state

ApplyModifiers = importlib.import_module("HoTools.ShapekeyTools.operators").OP_ApplyArmatureModifiersKeepShapekeys


def activate(objects, active):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active


def flat(matrix):
    return [float(value) for row in matrix for value in row]


def state(rig_name, mesh_name):
    rig, mesh = bpy.data.objects[rig_name], bpy.data.objects[mesh_name]
    document = capture_armature(rig)
    document.pop("exportTime", None)
    document.pop("inputFingerprint", None)
    return {
        "document": document,
        "mesh": mesh_state(mesh),
        "world": flat(rig.matrix_world),
        "pose": [(bone.name, flat(bone.matrix_basis)) for bone in rig.pose.bones],
        "posePosition": rig.data.pose_position,
        "selection": sorted(obj.name for obj in bpy.context.selected_objects),
        "active": bpy.context.view_layer.objects.active.name,
        "mode": rig.mode,
        "parents": [(bone.name, bone.parent.name if bone.parent else "") for bone in rig.data.bones],
    }


def build(name, *, empty=False, muted=False):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    data = bpy.data.armatures.new(name + "Data")
    rig = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(rig)
    activate([rig], rig)
    bpy.ops.object.mode_set(mode="EDIT")

    def bone(label, head, tail, parent="", roll=0):
        value = data.edit_bones.new(label)
        value.head, value.tail, value.roll = head, tail, roll
        if parent:
            value.parent = data.edit_bones[parent]
        return value

    bone("Root", (0, 0, 0), (0, 0, .6))
    bone("Main", (0, 0, .6), (.2, .12, 1.2), "Root", .34)
    bone("Lower", (.2, .12, 1.2), (.55, .4, 1.45), "Main", -.2)
    bone("CopyOwner", (.4, -.2, .7), (.65, .15, .25), "Root", -1.1)
    bone("AimOwner", (-.4, -.1, .7), (-.35, .1, .3), "Root")
    bone("Up", (-.1, .6, 1), (-.1, .8, 1.2), "Root")
    bone("RawOwner", (.6, -.2, .8), (.8, -.2, 1.1), "Root")
    fan_names, twist_names = [], []
    if not empty:
        fan_names = BoneFanCore._create_fan_bones(rig, ["Main", "Lower"], "out", count=2,
            length_factor=.35, pin_length_factor=.25, name_prefix="V4_")
        twist = TwistBoneCore.create_twist_chain(rig, "Main", 3, keep_head_end_weight=True)
        twist_names = twist["created_names"]
    bpy.ops.object.mode_set(mode="OBJECT")
    if not empty:
        TwistBoneCore.add_copy_rotation_to_twist_bones(bpy.context, rig, ["Main"], twist_names,
            manual_target="Lower", top_influence=.2, bottom_influence=.8)
        CopyRotationCore.configure(rig, ["CopyOwner"], "Main", influence=.3)
        owner = rig.pose.bones["AimOwner"]
        a = owner.constraints.new("DAMPED_TRACK")
        a.name, a.target, a.subtarget, a.track_axis = "AimDirection", rig, "Main", "TRACK_X"
        u = owner.constraints.new("LOCKED_TRACK")
        u.name, u.target, u.subtarget = "AimUp", rig, "Up"
        u.track_axis, u.lock_axis = "TRACK_NEGATIVE_Z", "LOCK_X"
        register_existing_aim_pair(owner)
        raw = rig.pose.bones["RawOwner"].constraints.new("COPY_ROTATION")
        raw.name, raw.target, raw.subtarget = "UserRawCopyRotation", rig, "Main"
        if muted:
            for pose in rig.pose.bones:
                for constraint in pose.constraints:
                    constraint.mute = True
        data.bones["Main"].hotools_boneprops.generateMCH = True
    mesh = bpy.data.meshes.new(name + "MeshData")
    mesh.from_pydata([(0, 0, .7), (.3, 0, .7), (0, .3, .7)], [], [(0, 1, 2)])
    skin = bpy.data.objects.new(name + "Mesh", mesh)
    bpy.context.scene.collection.objects.link(skin)
    skin.parent = rig
    group = skin.vertex_groups.new(name="Main")
    group.add([0, 1, 2], 1, "REPLACE")
    modifier = skin.modifiers.new("Armature", "ARMATURE")
    modifier.object = rig
    activate([rig, skin], rig)
    bpy.context.view_layer.update()
    return rig.name, skin.name, fan_names, twist_names


def run_case(directory, label, *, version=None, empty=False, muted=False, apply_pose=False, allow_approximate=False):
    rig_name, mesh_name, fans, twists = build("HoFbx_" + label, empty=empty, muted=muted)
    before = state(rig_name, mesh_name)
    authored = deepcopy(before["document"])
    path = directory / (label + ".fbx")
    version_options = {} if version is None else {"rigConstraintIRVersion": version}
    result = bpy.ops.ho.final_fbx_export("EXEC_DEFAULT", filepath=str(path),
        **version_options, generateMCHBones=not empty,
        exportUnityMetadata=True, addLeafBones=False, applyArmaturePose=apply_pose,
        fixObjectTransform=True, applyExportConstraints=False,
        allowNativeConstraintApproximation=allow_approximate,
        exportBsCorrective=False, exportHumanoidMapping=False)
    assert result == {"FINISHED"}, (label, result)
    assert path.is_file() and path.stat().st_size > 1000
    after = state(rig_name, mesh_name)
    assert after == before, (label, "HoFBX normal undo did not restore authoring state")
    files = list((directory / "HoFBX").glob(label + "_*_constraint.json"))
    assert len(files) == 1, (label, files)
    manifest = json.loads((directory / "HoFBX" / (label + "_unity.json")).read_text(encoding="utf-8"))
    assert any(entry["kind"] == "rigConstraintIR" and entry["file"] == files[0].name for entry in manifest["files"])
    if version == "3":
        doc = json.loads(files[0].read_text(encoding="utf-8"))
        assert doc["schemaVersion"] == 3 and "knownConstraints" in doc
        assert doc["mchBindings"]
        assert any(row["auxType"] == "TWIST" for row in doc["auxBones"])
        print("HOFBX_CASE_OK", label, "v3")
        return
    doc = loads(files[0].read_text(encoding="utf-8"))
    assert doc["schemaVersion"] == 4 and doc["captureStage"] == "AUTHORING"
    assert doc["sourceContext"] == authored["sourceContext"]
    assert doc["bindings"]["captureStage"] == "POSTPROCESS"
    assert doc["bindings"]["bindingContext"]["fbxBoneAxes"] == "Y_X"
    assert doc["sources"][:len(authored["sources"])] == authored["sources"]
    assert doc["importPolicy"] == {"allowNativeApproximation": allow_approximate}
    for binding in doc["implementationBindings"]:
        if binding["implementationId"].endswith(".legacy"):
            expected_policy = "ALLOW_LEGACY"
        else:
            expected_policy = "ALLOW_APPROXIMATE" if allow_approximate and binding["backendId"] in {"Standard", "Vrc"} else "EXACT_ONLY"
        assert binding["fallbackPolicy"] == expected_policy
    if empty:
        assert not doc["sources"] and not doc["semantics"] and not doc["bindings"]["boneMap"]
    else:
        assert doc["bindings"]["boneMap"] == [{"sourceBone": "Main", "exportBone": "MCH_Main"}]
        generated = [row for row in doc["sources"] if row["captureStage"] == "EXPORT_GENERATED"]
        assert len(generated) == 1 and generated[0]["constraint"]["targetBoneName"] == "Main"
        copy = next(row for row in doc["sources"] if row["constraint"]["name"] == CopyRotationCore.CONSTRAINT_NAME)
        assert copy["constraint"]["targetBoneName"] == "Main"
        overlay = next(row for row in doc["bindings"]["constraintMap"] if row["sourceId"] == copy["sourceId"])
        assert overlay["targetBoneName"] == "MCH_Main"
        semantic = next(row for row in doc["semantics"] if row["ownerBone"] == "CopyOwner")
        assert semantic["semanticType"] == "COPY_ROTATION" and semantic["parameters"]["sourceBones"] == ["Main"]
        assert not semantic["parameters"]["ownsBone"]
        assert any(row["semanticType"] == "FAN" and row["ownerBone"] in fans for row in doc["semantics"])
        assert any(row["semanticType"] == "TWIST" and row["ownerBone"] in twists for row in doc["semantics"])
        assert any(row["semanticType"] == "AIM" for row in doc["semantics"])
        raw = next(row for row in doc["sources"] if row["constraint"]["name"] == "UserRawCopyRotation")
        assert not any(raw["sourceId"] in row["sourceIds"] for row in doc["semantics"])
        assert any(raw["sourceId"] in row["sourceIds"] and row["status"] == "UNKNOWN" for row in doc["diagnostics"])
        if muted:
            assert all(row["constraint"]["parameters"]["mute"] for row in doc["sources"] if row["captureStage"] == "AUTHORING")
    print("HOFBX_CASE_OK", label, "v4", len(doc["sources"]), len(doc["semantics"]))


register_bones()
bpy.utils.register_class(ApplyModifiers)
bpy.utils.register_class(FbxExporter.OP_FinalFBXExport)
assert bpy.ops.ho.final_fbx_export.get_rna_type().properties["rigConstraintIRVersion"].default == "4"
try:
    context = tempfile.TemporaryDirectory(prefix="hotools_hofbx_v4_")
    try:
        output = Path(sys.argv[sys.argv.index("--") + 1]).resolve() if "--" in sys.argv else Path(context.name)
        output.mkdir(parents=True, exist_ok=True)
        for label, options in (("ordinary_v4", {}), ("muted_v4", {"muted": True}),
                               ("apply_pose_v4", {"apply_pose": True}),
                               ("approximate_v4", {"allow_approximate": True}),
                               ("compat_v3", {"version": "3"}), ("empty_v4", {"empty": True})):
            run_case(output, label, **options)
        if "--" in sys.argv:
            print("HOFBX_V4_FIXTURE", output)
    finally:
        context.cleanup()
finally:
    bpy.utils.unregister_class(FbxExporter.OP_FinalFBXExport)
    bpy.utils.unregister_class(ApplyModifiers)
    unregister_bones()
print("HOFBX_V4_OK", bpy.app.version_string)
