"""HoFBX 曲线网格化整链路回归；使用 Blender 后台运行。"""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import bpy

ADDON_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON_DIR))
from Exporter import FbxExporter


def activate(objects, active):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active


def build_curve(name, mirror=False, with_profile=False):
    data = bpy.data.curves.new(name + "Data", "CURVE")
    data.dimensions = "3D"
    data.bevel_depth = 0.1
    data.bevel_resolution = 2
    spline = data.splines.new("BEZIER")
    spline.bezier_points.add(1)
    for point, co in zip(spline.bezier_points, [(1, 0, 0), (2, 1, 1)]):
        point.co = co
        point.handle_left_type = point.handle_right_type = "AUTO"
    profile = None
    if with_profile:
        profile_data = bpy.data.curves.new("ProfileData", "CURVE")
        profile_data.dimensions = "2D"
        spline = profile_data.splines.new("POLY")
        spline.points.add(3)
        for point, co in zip(spline.points, [(-0.1, -0.1, 0, 1), (0.1, -0.1, 0, 1),
                                             (0.1, 0.1, 0, 1), (-0.1, 0.1, 0, 1)]):
            point.co = co
        spline.use_cyclic_u = True
        profile = bpy.data.objects.new("Profile", profile_data)
        bpy.context.scene.collection.objects.link(profile)
        data.bevel_mode = "OBJECT"
        data.bevel_object = profile
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    if mirror:
        obj.modifiers.new("Mirror", "MIRROR")
    bpy.context.view_layer.update()
    return obj, profile


bpy.utils.register_class(FbxExporter.OP_FinalFBXExport)
try:
    with TemporaryDirectory(prefix="hotools_fbx_curves_") as output_dir:
        for mirror, with_profile in (
            (False, False), (True, False), (True, True),
        ):
            bpy.ops.wm.read_factory_settings(use_empty=True)
            obj, profile = build_curve("Curve", mirror=mirror, with_profile=with_profile)
            selected = [profile, obj] if profile else [obj]
            activate(selected, obj)
            evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            expected_vertices, expected_faces = len(mesh.vertices), len(mesh.polygons)
            evaluated.to_mesh_clear()
            assert expected_faces > 0, "测试曲线必须有实际的面"
            filepath = str(Path(output_dir) / f"curve_{mirror}_{with_profile}.fbx")
            assert bpy.ops.ho.final_fbx_export(
                "EXEC_DEFAULT", filepath=filepath, meshifyCurves=True,
                exportUnityMetadata=False, exportBoneConstraint=False,
                exportBoneCollection=False, exportHumanoidMapping=False,
            ) == {"FINISHED"}
            restored = bpy.data.objects["Curve"]
            assert restored.type == "CURVE", "导出后应恢复为曲线"
            assert [mod.type for mod in restored.modifiers] == (["MIRROR"] if mirror else [])
            if profile:
                assert bpy.data.objects["Profile"].type == "CURVE"
                assert restored.data.bevel_object == bpy.data.objects["Profile"]
            bpy.ops.wm.read_factory_settings(use_empty=True)
            bpy.ops.import_scene.fbx(filepath=filepath)
            imported = bpy.data.objects.get("Curve")
            assert imported is not None and imported.type == "MESH", "曲线没有转成网格导出"
            assert len(imported.data.vertices) == expected_vertices
            assert len(imported.data.polygons) == expected_faces, (
                f"截面先网格化时丢失曲面：{len(imported.data.polygons)} != {expected_faces}"
            )
finally:
    bpy.utils.unregister_class(FbxExporter.OP_FinalFBXExport)

print("FBX_CURVES_OK", bpy.app.version_string)
