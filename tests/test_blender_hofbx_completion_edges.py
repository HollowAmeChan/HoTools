"""Completion audit: final binding matrices and posed authoring preservation."""

import importlib
import json
from pathlib import Path
import sys
import tempfile
import types

import bpy
from mathutils import Euler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for name, directory in (("HoTools", ROOT), ("HoTools.ShapekeyTools", ROOT / "ShapekeyTools")):
    module = types.ModuleType(name)
    module.__path__ = [str(directory)]
    sys.modules.setdefault(name, module)
from BoneTools import register as register_bones, unregister as unregister_bones
from BoneTools.auxBone.copyRotation import CopyRotationCore
from Exporter import FbxExporter
from Exporter.ConstraintIRExporter import ConstraintIRExporter
from RigConstraints.source import capture_armature
from RigConstraints.codec import loads

ApplyModifiers = importlib.import_module("HoTools.ShapekeyTools.operators").OP_ApplyArmatureModifiersKeepShapekeys
actual_contexts = {}
original_get_params = FbxExporter.OP_FinalFBXExport.getParams


def traced_params(self, context, report_errors=True):
    # This point is after every final export transform correction and immediately
    # before bpy's FBX writer. Read matrices only; never change production logic.
    rigs = [obj for obj in context.selected_objects if obj.type == "ARMATURE"]
    if rigs:
        rig = rigs[0]
        actual_contexts[Path(self.filepath).stem] = ConstraintIRExporter._binding_context(rig, list(rig.data.bones))
    return original_get_params(self, context, report_errors)


FbxExporter.OP_FinalFBXExport.getParams = traced_params
register_bones()
bpy.utils.register_class(ApplyModifiers)
bpy.utils.register_class(FbxExporter.OP_FinalFBXExport)
results = {}
try:
    with tempfile.TemporaryDirectory(prefix="hotools_completion_edges_") as directory:
        for apply_pose in (False, True):
            bpy.ops.wm.read_factory_settings(use_empty=True)
            data = bpy.data.armatures.new("CompletionData")
            rig = bpy.data.objects.new("CompletionRig", data)
            bpy.context.scene.collection.objects.link(rig)
            bpy.context.view_layer.objects.active = rig
            rig.select_set(True)
            bpy.ops.object.mode_set(mode="EDIT")
            for name, head, tail, parent in (
                ("Root", (0, 0, 0), (0, 0, .5), ""),
                ("Main", (0, 0, .5), (.2, .1, 1), "Root"),
                ("Owner", (.4, -.2, .6), (.7, -.1, .2), "Root"),
                ("Probe", (-.3, .4, .6), (-.1, .5, .9), "Root"),
            ):
                bone = data.edit_bones.new(name)
                bone.head, bone.tail = head, tail
                if parent:
                    bone.parent = data.edit_bones[parent]
            bpy.ops.object.mode_set(mode="OBJECT")
            rig.location, rig.rotation_euler, rig.scale = (.7, -.3, .2), (.3, -.4, .7), (1.3, 1.3, 1.3)
            for name, angles in (("Main", (.2, -.1, .3)), ("Owner", (-.1, .2, .1))):
                pose = rig.pose.bones[name]
                pose.rotation_mode = "QUATERNION"
                pose.rotation_quaternion = Euler(angles).to_quaternion()
            CopyRotationCore.configure(rig, ["Owner"], "Main", influence=.3)
            rig.data.bones["Main"].hotools_boneprops.generateMCH = True
            mesh = bpy.data.meshes.new("CompletionMesh")
            mesh.from_pydata([(0,0,.6), (.2,0,.6), (0,.2,.6)], [], [(0,1,2)])
            skin = bpy.data.objects.new("CompletionSkin", mesh)
            bpy.context.scene.collection.objects.link(skin)
            skin.parent = rig
            weights = skin.vertex_groups.new(name="Main")
            weights.add([0,1,2], 1.0, "REPLACE")
            skin.modifiers.new("Armature", "ARMATURE").object = rig
            skin.select_set(True)
            bpy.context.view_layer.update()
            author = capture_armature(rig)
            label = "posed" if apply_pose else "unposed"
            path = Path(directory) / (label + ".fbx")
            assert bpy.ops.ho.final_fbx_export("EXEC_DEFAULT", filepath=str(path),
                rigConstraintIRVersion="4", generateMCHBones=True, exportUnityMetadata=True,
                addLeafBones=False, applyArmaturePose=apply_pose, fixObjectTransform=True,
                exportBsCorrective=False) == {"FINISHED"}
            sidecar = next((path.parent / "HoFBX").glob(label + "_*_constraint.json"))
            exported = loads(sidecar.read_text(encoding="utf-8"))
            binding = exported["bindings"]["bindingContext"]
            actual = actual_contexts[label]
            object_error = max(abs(a-b) for a, b in zip(binding["objectMatrix"], actual["objectMatrix"]))
            actual_bones = {bone["boneName"]: bone for bone in actual["bones"]}
            rest_error = max(abs(a-b) for bone in binding["bones"]
                             for a, b in zip(bone["restMatrix"], actual_bones[bone["boneName"]]["restMatrix"]))
            results[label + "_final_bind_matrices"] = object_error < 1e-5 and rest_error < 1e-5
            results[label + "_author_inputs_preserved"] = exported["sources"][:len(author["sources"])] == author["sources"] and exported["sourceContext"] == author["sourceContext"]
            if apply_pose:
                owner = next(bone for bone in actual["bones"] if bone["boneName"] == "Owner")
                identity = [1.0 if row == column else 0.0 for row in range(4) for column in range(4)]
                results["apply_pose_resets_final_owner_input"] = max(abs(a-b) for a,b in zip(owner["poseBasis"], identity)) < 1e-6
            print("COMPLETION_BIND_MATRIX_ERRORS", label, object_error, rest_error)
finally:
    bpy.utils.unregister_class(FbxExporter.OP_FinalFBXExport)
    bpy.utils.unregister_class(ApplyModifiers)
    unregister_bones()
    FbxExporter.OP_FinalFBXExport.getParams = original_get_params
print("COMPLETION_EDGE_RESULTS", json.dumps(results, sort_keys=True))
assert all(results.values()), "Completion gaps: " + ", ".join(name for name, passed in results.items() if not passed)
print("HOFBX_COMPLETION_EDGES_OK", bpy.app.version_string)
