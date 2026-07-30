import importlib.util
import os
import sys

import bpy


PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGE_DIR = os.path.join(PLUGIN_ROOT, "_Lib", "py311", "HotoolsPackage")
if PACKAGE_DIR not in sys.path:
    sys.path.insert(0, PACKAGE_DIR)

module_path = os.path.join(PLUGIN_ROOT, "MeshTools", "boolean.py")
spec = importlib.util.spec_from_file_location("hotools_boolean_operator_test", module_path)
boolean_operator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boolean_operator)


def cube(origin, size=1.0, vertex_base=0):
    ox, oy, oz = origin
    vertices = [
        (ox, oy, oz),
        (ox + size, oy, oz),
        (ox + size, oy + size, oz),
        (ox, oy + size, oz),
        (ox, oy, oz + size),
        (ox + size, oy, oz + size),
        (ox + size, oy + size, oz + size),
        (ox, oy + size, oz + size),
    ]
    polygons = [
        [0, 3, 2, 1],
        [4, 5, 6, 7],
        [0, 1, 5, 4],
        [1, 2, 6, 5],
        [2, 3, 7, 6],
        [3, 0, 4, 7],
    ]
    return vertices, [[index + vertex_base for index in face] for face in polygons]


bpy.ops.wm.read_factory_settings(use_empty=True)
vertices, polygons = cube((0.0, 0.0, 0.0))
mesh = bpy.data.meshes.new("BooleanInput")
mesh.from_pydata(vertices, [], polygons)
obj = bpy.data.objects.new("BooleanInput", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)

boolean_operator.register()
try:
    status = bpy.ops.ho.boolean_union_reconstruction()
    assert status == {'FINISHED'}, status
    assert len(obj.data.polygons) == 6
    assert all(len(polygon.vertices) == 4 for polygon in obj.data.polygons)
finally:
    boolean_operator.unregister()

first_vertices, first_polygons = cube((0.0, 0.0, 0.0))
second_vertices, second_polygons = cube((0.5, 0.5, 0.5), vertex_base=8)
mesh = bpy.data.meshes.new("IntersectingInput")
mesh.from_pydata(first_vertices + second_vertices, [], first_polygons + second_polygons)
result = boolean_operator._load_native_boolean().outer_hull(
    *boolean_operator._mesh_arrays(mesh)
)
output = boolean_operator._build_mesh(mesh, result)
assert result["restored_polygons"] > 0
assert result["seam_triangles"] > 0
assert any(len(polygon.vertices) == 4 for polygon in output.polygons)
assert any(len(polygon.vertices) == 3 for polygon in output.polygons)

print(
    "BOOLEAN_BLENDER_OK",
    len(output.vertices),
    len(output.polygons),
    result["restored_polygons"],
    result["seam_triangles"],
)
