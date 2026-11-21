"""Preserve grouping Empty frames through HoFBX correction and undo.

Run in Blender with --background --factory-startup --python-exit-code 1.
The expected frame/geometry comes from the authored REST scene, independently
of exporter correction and FBX import. Only disposable scenes are created.
"""

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import bpy
from mathutils import Euler, Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from Exporter.FbxExporter import OP_FinalFBXExport

TOLERANCE = 2e-5
OBSERVED, RESULTS = {}, []
ORIGINAL_PARAMS = OP_FinalFBXExport.getParams


def trs(location, angles, scale=1):
    return Matrix.Translation(Vector(location)) @ Euler(angles).to_matrix().to_4x4() @ Matrix.Scale(scale, 4)


def flat(matrix):
    return [float(value) for row in matrix for value in row]


def points(obj):
    bpy.context.view_layer.update()
    return [tuple(obj.matrix_world @ vertex.co) for vertex in obj.data.vertices]


def matrix_error(actual, expected):
    return max(abs(a - b) for a, b in zip(actual, expected))


def point_error(actual, expected):
    assert len(actual) == len(expected)
    return max(max(min((Vector(a) - Vector(b)).length for b in expected) for a in actual),
               max(min((Vector(a) - Vector(b)).length for b in actual) for a in expected))


def snapshot():
    empty = bpy.data.objects["BoneGroup"]
    return {"emptyWorld": flat(empty.matrix_world), "meshPoints": points(bpy.data.objects["RigidMesh"]),
            "parentInverse": flat(empty.matrix_parent_inverse), "basis": flat(empty.matrix_basis),
            "parent": empty.parent.name, "parentType": empty.parent_type, "parentBone": empty.parent_bone,
            "selected": sorted(obj.name for obj in bpy.context.selected_objects),
            "active": bpy.context.active_object.name}


def build(parent_type):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    data = bpy.data.armatures.new("RigData")
    rig = bpy.data.objects.new("Rig", data)
    bpy.context.scene.collection.objects.link(rig)
    rig.matrix_world = trs((.7, -.3, .25), (.2, -.35, .5), 1.2)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    bone = data.edit_bones.new("Anchor")
    bone.head, bone.tail, bone.roll = (.3, .1, .8), (.6, -.2, 1.8), .45
    bpy.ops.object.mode_set(mode="OBJECT")
    pose = rig.pose.bones["Anchor"]
    pose.rotation_mode = "XYZ"
    pose.rotation_euler, pose.location = (.25, -.18, .12), (.03, -.02, .01)
    empty = bpy.data.objects.new("BoneGroup", None)
    bpy.context.scene.collection.objects.link(empty)
    empty.parent, empty.parent_type = rig, parent_type
    empty.parent_bone = "Anchor" if parent_type == "BONE" else ""
    empty.matrix_parent_inverse = trs((.1, -.08, .03), (.15, .25, -.2))
    empty.matrix_basis = trs((.16, .07, -.05), (.3, -.25, .4), .9)
    mesh = bpy.data.meshes.new("Triangle")
    mesh.from_pydata([(0, 0, 0), (.3, .05, 0), (.02, .1, .2)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new("RigidMesh", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = empty
    obj.matrix_parent_inverse = trs((-.03, .02, .04), (.1, -.15, .2))
    obj.matrix_basis = trs((.07, .02, -.04), (-.2, .1, .3), .85)
    for value in (rig, empty, obj):
        value.select_set(True)
    data.pose_position = "REST"
    bpy.context.view_layer.update()
    expected = snapshot()
    data.pose_position = "POSE"
    bpy.context.view_layer.update()
    return expected, snapshot()


def observe_writer(self, context, report_errors=True):
    # getParams runs after all correction and immediately before backend export.
    OBSERVED[Path(self.filepath).stem] = snapshot()
    return ORIGINAL_PARAMS(self, context, report_errors=report_errors)


def run_case(directory, parent_type, fix):
    expected, authored = build(parent_type)
    label = parent_type.lower() + "_fix_" + str(fix).lower()
    path = directory / (label + ".fbx")
    assert bpy.ops.ho.final_fbx_export("EXEC_DEFAULT", filepath=str(path),
        exportUnityMetadata=False, exportBoneConstraint=False, exportBoneCollection=False,
        exportHumanoidMapping=False, exportBsCorrective=False, addLeafBones=False,
        generateMCHBones=False, applyArmaturePose=False, fixObjectTransform=fix,
        applyExportConstraints=False) == {"FINISHED"}
    writer, restored = OBSERVED[label], snapshot()
    frame_error = matrix_error(writer["emptyWorld"], expected["emptyWorld"])
    geometry_error = point_error(writer["meshPoints"], expected["meshPoints"])
    assert frame_error < TOLERANCE, (label, "Empty world frame changed", frame_error)
    assert geometry_error < TOLERANCE, (label, "writer geometry changed", geometry_error)
    for key in ("parent", "parentType", "parentBone"):
        assert writer[key] == expected[key], (label, "writer parent changed", key)
    for key in ("emptyWorld", "parentInverse", "basis"):
        assert matrix_error(restored[key], authored[key]) == 0, (label, "undo matrix", key)
    assert point_error(restored["meshPoints"], authored["meshPoints"]) == 0, (label, "undo geometry")
    for key in ("parent", "parentType", "parentBone", "selected", "active"):
        assert restored[key] == authored[key], (label, "undo identity/selection", key)
    assert bpy.data.objects["Rig"].data.pose_position == "POSE"
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(path), use_anim=False)
    assert bpy.data.objects.get("BoneGroup") is not None, (label, "Empty missing from FBX")
    roundtrip_error = point_error(points(bpy.data.objects["RigidMesh"]), expected["meshPoints"])
    assert roundtrip_error < TOLERANCE, (label, "roundtrip geometry", roundtrip_error)
    RESULTS.append({"case": label, "writerFrameError": frame_error,
                    "writerGeometryError": geometry_error, "roundtripError": roundtrip_error})


bpy.utils.register_class(OP_FinalFBXExport)
OP_FinalFBXExport.getParams = observe_writer
try:
    with TemporaryDirectory(prefix="hotools_empty_frames_") as directory:
        for parent_type in ("BONE", "OBJECT"):
            for fix in (False, True):
                run_case(Path(directory), parent_type, fix)
finally:
    OP_FinalFBXExport.getParams = ORIGINAL_PARAMS
    bpy.utils.unregister_class(OP_FinalFBXExport)

print("FBX_EMPTY_FRAME_RESULTS", json.dumps(RESULTS, sort_keys=True))
print("FBX_EMPTY_FRAMES_OK", bpy.app.version_string, len(RESULTS))
