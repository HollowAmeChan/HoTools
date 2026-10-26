"""Hidden modifiers must be excluded before HoFBX bakes data-transfer chains.

Run with Blender --background --factory-startup --python <this file>.
Verify actual FBX readback, shape keys, and restoration of the authored scene.
"""

import sys
import tempfile
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON_DIR))
from Exporter import FbxExporter


def make_quad(name, uv_value):
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata([(1, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0)], [], [(0, 1, 2, 3)])
    uv = mesh.uv_layers.new(name="UVMap")
    for item in uv.data:
        item.uv = (uv_value, uv_value)
    ob = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def modifier_state(ob):
    return [(mod.name, mod.type, mod.show_viewport, mod.show_render) for mod in ob.modifiers]


def run_case(out_dir, case, with_shape_keys, remove_hidden=True):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    source = make_quad("Source", 0.8)
    target = make_quad("Target", 0.2)
    if with_shape_keys:
        target.shape_key_add(name="Basis")
        wide = target.shape_key_add(name="Wide")
        wide.data[1].co.x += 0.5

    if case in {"hidden_prefix", "hidden_source"}:
        owner = target if case == "hidden_prefix" else source
        mirror = owner.modifiers.new("HiddenMirror", "MIRROR")
        mirror.show_viewport = False
        mirror.show_render = True

    transfer = target.modifiers.new("TransferUV", "DATA_TRANSFER")
    transfer.object = source
    transfer.use_loop_data = True
    transfer.data_types_loops = {'UV'}
    transfer.loop_mapping = 'TOPOLOGY'
    transfer.layers_uv_select_src = 'ALL'
    transfer.layers_uv_select_dst = 'NAME'
    if case == "hidden_transfer":
        transfer.show_viewport = False
        transfer.show_render = True

    bpy.context.view_layer.update()
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    expected_modifiers = {ob.name: modifier_state(ob) for ob in (source, target)}
    filepath = out_dir / f"{case}_{with_shape_keys}_{remove_hidden}.fbx"
    result = bpy.ops.ho.final_fbx_export(
        "EXEC_DEFAULT", filepath=str(filepath),
        removeHiddenModifiers=remove_hidden,
        applyArmaturePose=False, fixObjectTransform=False,
        addLeafBones=False, generateMCHBones=False,
        exportUnityMetadata=False, exportBoneConstraint=False,
        exportBoneCollection=False, exportHumanoidMapping=False,
    )
    assert result == {'FINISHED'}, (case, result)
    for name, state in expected_modifiers.items():
        assert modifier_state(bpy.data.objects[name]) == state, (case, name, "modifiers not restored")
    restored = bpy.data.objects["Target"]
    assert len(restored.data.vertices) == 4
    assert abs(restored.data.uv_layers.active.data[0].uv.x - 0.2) < 1e-5
    if with_shape_keys:
        assert restored.data.shape_keys.key_blocks["Wide"].data[1].co.x == 2.5

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(filepath))
    imported = bpy.data.objects["Target"]
    assert len(imported.data.vertices) == 4, (case, "hidden mirror baked into FBX")
    expected_uv = 0.2 if case == "hidden_transfer" and remove_hidden else 0.8
    for item in imported.data.uv_layers.active.data:
        assert abs(item.uv.x - expected_uv) < 1e-4, (case, with_shape_keys, item.uv[:], expected_uv)
    if with_shape_keys:
        keys = imported.data.shape_keys.key_blocks
        assert [key.name for key in keys] == ["Basis", "Wide"]
        assert max((a.co - b.co).length for a, b in zip(keys["Basis"].data, keys["Wide"].data)) > 0.1
    print(f"PASS: {case}, shape_keys={with_shape_keys}, remove_hidden={remove_hidden}", flush=True)


bpy.utils.register_class(FbxExporter.OP_FinalFBXExport)
try:
    with tempfile.TemporaryDirectory(prefix="hotools_hidden_modifiers_") as directory:
        for with_shape_keys in (False, True):
            for case in ("hidden_transfer", "hidden_prefix", "hidden_source"):
                run_case(Path(directory), case, with_shape_keys)
            # Explicitly disabling removal retains render-only transfer support.
            run_case(Path(directory), "hidden_transfer", with_shape_keys, remove_hidden=False)
finally:
    bpy.utils.unregister_class(FbxExporter.OP_FinalFBXExport)

print("HoFBX hidden modifier regression tests passed.", flush=True)
