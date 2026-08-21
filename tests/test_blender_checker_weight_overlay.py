"""Background-Blender coverage for weight modes in overlayPreview."""

import importlib
import sys
import types
from pathlib import Path

import bpy
import gpu


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))
package = types.ModuleType("HoTools")
package.__path__ = [str(ADDON_DIR)]
sys.modules.setdefault("HoTools", package)

original_shader_from_builtin = gpu.shader.from_builtin
gpu.shader.from_builtin = lambda _name: None
try:
    checker = importlib.import_module("HoTools.Checker")
    vertex_group_operators = importlib.import_module(
        "HoTools.VertexGroupTools.vertexGroupOperators"
    )
finally:
    gpu.shader.from_builtin = original_shader_from_builtin


checker.register()
vertex_group_operators.register()
try:
    overlay_preview = checker.overlayPreview
    for mode_id, label in (
        ("WEIGHT_COLOR", "权重-彩色"),
        ("WEIGHT_NO_BONE", "权重-无骨控制"),
        ("WEIGHT_GROUP_COUNT", "权重-组数量"),
        ("WEIGHT_NORMALIZED", "权重-归一化"),
    ):
        assert overlay_preview.CheckerOverlayPreview.MODE_SPECS[mode_id]["label"] == label

    assert not hasattr(bpy.types.Scene, "ho_checker_weight_debug_group_limit")
    assert not hasattr(bpy.types.Scene, "hoVertexGroupTools_DebugBoneWeightGroup_open_menu")
    assert not hasattr(bpy.types.Scene, "hoVertexGroupTools_debug_groupnum_limit")
    assert hasattr(bpy.types.Scene, "ho_checker_overlay_weight_group_limit")
    assert hasattr(bpy.types.Scene, "ho_checker_overlay_weight_check_zero")
    assert hasattr(bpy.types.Scene, "hoVertexGroupTools_view_activevertex_weight")

    scene = bpy.context.scene
    scene.ho_checker_overlay_check_mode = "WEIGHT_NORMALIZED"
    scene.ho_checker_overlay_weight_check_zero = True
    checker.refresh_all(bpy.context)
    weight_preview = overlay_preview.WeightOverlayPreview
    assert weight_preview.DRAW_unnormalizedBoneWeightGroup({0: 1.0, 1: 0.0}) == (0, 1, 0, 0.6)
    assert weight_preview.DRAW_strictUnnormalizedBoneWeightGroup({0: 1.0, 1: 0.0}) == (1, 0, 0, 0.6)

    # A mesh without any vertex groups has no edit-mode deform layer. The
    # overlay must still classify it as an empty-weight mesh without raising.
    mesh = bpy.data.meshes.new("weight_overlay_empty_mesh")
    mesh.from_pydata(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), (), ((0, 1, 2),))
    obj = bpy.data.objects.new("weight_overlay_empty_object", mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    overlay_preview.WeightOverlayPreview.build_data(obj, mode="NONE")
    bpy.ops.object.mode_set(mode="EDIT")
    overlay_preview.WeightOverlayPreview.build_data(obj, mode="NONE")
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.meshes.remove(mesh)
finally:
    vertex_group_operators.unregister()
    checker.unregister()

print("test_blender_checker_weight_overlay: PASS")
