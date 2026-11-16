"""Exercise HoFBX with two selected rigs, their descendants, and an unrelated rig.

Run in a disposable Blender process with --background --factory-startup
--python-exit-code 1 --python tests/test_blender_fbx_multiple_armatures.py.
"""

import io
import importlib
import json
import sys
import tempfile
import traceback
import types
from contextlib import redirect_stdout
from pathlib import Path

import bpy
from mathutils import Vector

ADDON_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON_DIR))
from BoneTools import register as register_bones, unregister as unregister_bones
from Exporter import FbxExporter

# Load the operator in its package namespace without registering unrelated UI.
for package_name, package_path in (("HoTools", ADDON_DIR),
                                   ("HoTools.ShapekeyTools", ADDON_DIR / "ShapekeyTools")):
    package = types.ModuleType(package_name)
    package.__path__ = [str(package_path)]
    sys.modules.setdefault(package_name, package)
OP_ApplyArmatureModifiersKeepShapekeys = importlib.import_module(
    "HoTools.ShapekeyTools.operators"
).OP_ApplyArmatureModifiersKeepShapekeys


def activate(objects, active):
    bpy.ops.object.select_all(action="DESELECT")
    for ob in objects:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = active


def vector(value):
    return tuple(round(float(component), 5) for component in value)


def matrix(value):
    return tuple(vector(row) for row in value)


def mesh_points(ob):
    bpy.context.view_layer.update()
    evaluated = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return sorted(vector(evaluated.matrix_world @ vertex.co) for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def assert_points(actual, expected, label):
    assert len(actual) == len(expected), (label, len(actual), len(expected))
    error = max((Vector(a) - Vector(b)).length for a, b in zip(actual, expected))
    assert error < 3e-4, (label, "world geometry mismatch", error, actual, expected)


def snapshot():
    bpy.context.view_layer.update()
    objects = {}
    for ob in bpy.data.objects:
        state = {
            "type": ob.type, "parent": ob.parent.name if ob.parent else None,
            "parent_type": ob.parent_type, "parent_bone": ob.parent_bone,
            "world": matrix(ob.matrix_world), "hidden": ob.hide_get(),
            "modifiers": [(mod.name, mod.type, mod.show_viewport, mod.show_render,
                           getattr(getattr(mod, "object", None), "name", None)) for mod in ob.modifiers],
        }
        if ob.type == "MESH":
            state["vertices"] = [vector(vertex.co) for vertex in ob.data.vertices]
            state["weights"] = [[(group.group, round(group.weight, 5)) for group in vertex.groups]
                                for vertex in ob.data.vertices]
            state["keys"] = [(key.name, round(key.value, 5), [vector(v.co) for v in key.data])
                             for key in ob.data.shape_keys.key_blocks] if ob.data.shape_keys else []
        elif ob.type == "ARMATURE":
            state["bones"] = [(bone.name, bone.parent.name if bone.parent else None,
                               matrix(bone.matrix_local)) for bone in ob.data.bones]
            state["pose"] = [(bone.name, matrix(bone.matrix_basis)) for bone in ob.pose.bones]
            state["display"] = ob.data.pose_position
            state["collections"] = [(col.name, col.is_visible) for col in ob.data.collections_all]
        objects[ob.name] = state
    return objects, sorted(ob.name for ob in bpy.context.selected_objects), bpy.context.active_object.name


def build_rig(name, location, with_meshes=True):
    rig = bpy.data.objects.new(name, bpy.data.armatures.new(name + "Data"))
    bpy.context.scene.collection.objects.link(rig)
    rig.location = location
    rig.rotation_euler.z = 0.13 if name == "Rig_A" else -0.22
    activate([rig], rig)
    bpy.ops.object.mode_set(mode="EDIT")
    root = rig.data.edit_bones.new("Root")
    root.head, root.tail = (0, 0, 0), (0, 0, 1)
    tip = rig.data.edit_bones.new("Tip")
    tip.head, tip.tail, tip.parent = (0, 0, 1), (0.2, 0, 2), root
    bpy.ops.object.mode_set(mode="OBJECT")
    rig.data.bones["Tip"].hotools_boneprops.generateMCH = True
    rig.data.bones["Root"].hotools_boneprops.humanoidMapping = "hips"
    rig.data.bones["Tip"].hotools_boneprops.humanoidMapping = "spine"
    collection = rig.data.collections.new(name + "_Bones")
    for bone in rig.data.bones:
        collection.assign(bone)
    rig.pose.bones["Root"].rotation_mode = "XYZ"
    rig.pose.bones["Root"].rotation_euler.y = 0.27 if name == "Rig_A" else -0.35
    rig.pose.bones["Tip"].rotation_mode = "XYZ"
    rig.pose.bones["Tip"].rotation_euler.x = 0.18 if name == "Rig_A" else -0.23
    meshes = []
    if with_meshes:
        group = bpy.data.objects.new(name + "_Group", None)
        bpy.context.scene.collection.objects.link(group)
        group.parent = rig
        for index in range(2):
            mesh = bpy.data.meshes.new(f"{name}_Mesh{index}Data")
            mesh.from_pydata([(-0.3, index * 0.4, 0.2), (0.3, index * 0.4, 0.2),
                              (0.3, index * 0.4, 1.8), (-0.3, index * 0.4, 1.8)], [], [(0, 1, 2, 3)])
            ob = bpy.data.objects.new(f"{name}_Mesh{index}", mesh)
            bpy.context.scene.collection.objects.link(ob)
            ob.parent = rig if index == 0 else group
            ob.vertex_groups.new(name="Root").add([0, 1], 1.0, "REPLACE")
            ob.vertex_groups.new(name="Tip").add([2, 3], 1.0, "REPLACE")
            modifier = ob.modifiers.new("Armature", "ARMATURE")
            modifier.object = rig
            if index == 1:
                ob.shape_key_add(name="Basis")
                wide = ob.shape_key_add(name="Wide")
                wide.data[2].co.x += 0.4
                wide.value = 0.35
            meshes.append(ob)
    return rig, meshes


def check_metadata(filepath):
    metadata = filepath.parent / "HoFBX"
    manifest = json.loads((metadata / f"{filepath.stem}_unity.json").read_text(encoding="utf-8"))
    assert "Rig_Unselected" not in json.dumps(manifest)
    humanoid = json.loads((metadata / f"{filepath.stem}_humanoid.json").read_text(encoding="utf-8"))
    assert {rig["armatureName"] for rig in humanoid["armatures"]} == {"Rig_A", "Rig_B"}
    for name in ("Rig_A", "Rig_B"):
        ir = json.loads((metadata / f"{filepath.stem}_{name}_constraint.json").read_text(encoding="utf-8"))
        assert ir["armatureName"] == name
        collections = json.loads((metadata / f"{filepath.stem}_{name}_collection.json").read_text(encoding="utf-8"))
        assert collections["armatureName"] == name + "Data"


def run_case(directory, name, *, rigs_only=False, active_mesh=False, apply_pose=True, mch=True):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    rig_a, meshes_a = build_rig("Rig_A", (-2, 0, 0))
    rig_b, meshes_b = build_rig("Rig_B", (3, 1, 0.5))
    build_rig("Rig_Unselected", (8, 0, 0))
    meshes = meshes_a + meshes_b
    selection = [rig_a, rig_b] if rigs_only else [rig_a, rig_b, *meshes]
    activate(selection, meshes_b[-1] if active_mesh else rig_a)
    before = snapshot()
    pose_state = [rig.data.pose_position for rig in (rig_a, rig_b)]
    if not apply_pose:
        for rig in (rig_a, rig_b):
            rig.data.pose_position = "REST"
    expected = {ob.name: mesh_points(ob) for ob in meshes}
    for rig, state in zip((rig_a, rig_b), pose_state):
        rig.data.pose_position = state
    filepath = directory / (name + ".fbx")
    output = io.StringIO()
    with redirect_stdout(output):
        result = bpy.ops.ho.final_fbx_export("EXEC_DEFAULT", filepath=str(filepath),
                                            applyArmaturePose=apply_pose, generateMCHBones=mch)
    print(output.getvalue(), flush=True)
    assert result == {'FINISHED'}, (name, result)
    assert snapshot() == before, (name, "authored scene/selection was not restored")
    assert "失败" not in output.getvalue() and "脱离" not in output.getvalue(), (name, output.getvalue())
    if mch:
        check_metadata(filepath)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(filepath))
    assert {ob.name for ob in bpy.data.objects if ob.type == "ARMATURE"} == {"Rig_A", "Rig_B"}
    for rig_name in ("Rig_A", "Rig_B"):
        bones = bpy.data.objects[rig_name].data.bones
        assert {"Root", "Tip", "Tip_end"}.issubset(bones.keys()), (name, rig_name, bones.keys())
        assert ("MCH_Tip" in bones) == mch, (name, rig_name, "incorrect MCH bones")
    imported_meshes = {ob.name for ob in bpy.data.objects if ob.type == "MESH"}
    expected_names = set() if rigs_only else set(expected)
    assert imported_meshes == expected_names, (name, imported_meshes, expected_names)
    for mesh_name in imported_meshes:
        ob = bpy.data.objects[mesh_name]
        owner = mesh_name.split("_Mesh")[0]
        modifiers = [mod for mod in ob.modifiers if mod.type == "ARMATURE"]
        assert len(modifiers) == 1 and modifiers[0].object.name == owner, (name, mesh_name, "wrong skin")
        assert_points(mesh_points(ob), expected[mesh_name], (name, mesh_name))
        if mesh_name.endswith("Mesh1"):
            keys = ob.data.shape_keys.key_blocks
            assert [key.name for key in keys] == ["Basis", "Wide"]
            assert abs(keys["Wide"].value - 0.35) < 1e-5
            assert max((a.co - b.co).length for a, b in zip(keys["Basis"].data, keys["Wide"].data)) > 0.1
    # Moving one imported rig must move only its own meshes, despite identical bone names.
    original = {mesh_name: mesh_points(bpy.data.objects[mesh_name]) for mesh_name in imported_meshes}
    bpy.data.objects["Rig_A"].location.x += 0.7
    for mesh_name in imported_meshes:
        delta = Vector((0.7, 0, 0)) if mesh_name.startswith("Rig_A_") else Vector((0, 0, 0))
        assert_points(mesh_points(bpy.data.objects[mesh_name]),
                      [tuple(Vector(point) + delta) for point in original[mesh_name]], (name, mesh_name, "independence"))
    # Exercise skin deformation too, rather than checking only object parenting.
    original = {mesh_name: mesh_points(bpy.data.objects[mesh_name]) for mesh_name in imported_meshes}
    rig = bpy.data.objects["Rig_A"]
    root = rig.pose.bones["Root"]
    delta = rig.matrix_world.to_3x3() @ root.bone.matrix_local.to_3x3() @ Vector((0.2, 0, 0))
    root.location.x += 0.2
    for mesh_name in imported_meshes:
        displacement = delta if mesh_name.startswith("Rig_A_") else Vector((0, 0, 0))
        assert_points(mesh_points(bpy.data.objects[mesh_name]),
                      [tuple(Vector(point) + displacement) for point in original[mesh_name]],
                      (name, mesh_name, "skin independence"))
    print(f"PASS: {name}: two armatures, {len(imported_meshes)} meshes", flush=True)


register_bones()
bpy.utils.register_class(OP_ApplyArmatureModifiersKeepShapekeys)
bpy.utils.register_class(FbxExporter.OP_FinalFBXExport)
failures = []
try:
    with tempfile.TemporaryDirectory(prefix="hotools_multiple_armatures_") as directory:
        for name, options in (
            ("defaults", {}),
            ("active_child_mesh", {"active_mesh": True}),
            ("without_mch", {"mch": False}),
            ("without_apply_pose", {"apply_pose": False}),
            ("only_rigs_selected", {"rigs_only": True}),
        ):
            try:
                run_case(Path(directory), name, **options)
            except Exception:
                failures.append(name)
                traceback.print_exc()
finally:
    bpy.utils.unregister_class(FbxExporter.OP_FinalFBXExport)
    bpy.utils.unregister_class(OP_ApplyArmatureModifiersKeepShapekeys)
    unregister_bones()

assert not failures, failures
print("FBX_MULTIPLE_ARMATURES_OK", bpy.app.version_string, flush=True)
