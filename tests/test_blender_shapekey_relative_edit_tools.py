import importlib
import sys
import types
from pathlib import Path

import bpy
import numpy as np


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))
package = types.ModuleType("HoTools")
package.__path__ = [str(ADDON_DIR)]
sys.modules.setdefault("HoTools", package)
shapekey_package = types.ModuleType("HoTools.ShapekeyTools")
shapekey_package.__path__ = [str(ADDON_DIR / "ShapekeyTools")]
sys.modules.setdefault("HoTools.ShapekeyTools", shapekey_package)

module = importlib.import_module("HoTools.ShapekeyTools.operators")


def positions(key):
    return np.array([point.co[:] for point in key.data], dtype=np.float32)


def activate_key(obj, key):
    if obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    obj.active_shape_key_index = obj.data.shape_keys.key_blocks.find(key.name)


def select_vertices(obj, indices):
    if obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    selected = set(indices)
    for vertex in obj.data.vertices:
        vertex.select = vertex.index in selected
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_mode(type='VERT')


mesh = bpy.data.meshes.new("RelativeEditToolsData")
mesh.from_pydata(
    [(0.0, 0.0, 0.0), (0.1, 0.0, 0.0),
     (0.2, 0.0, 0.0), (10.0, 0.0, 0.0)],
    [],
    [],
)
obj = bpy.data.objects.new("RelativeEditTools", mesh)
bpy.context.scene.collection.objects.link(obj)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj

basis = obj.shape_key_add(name="Basis", from_mix=False)
parent = obj.shape_key_add(name="Parent", from_mix=False)
parent.relative_key = basis
parent.data[1].co.z += 1.0

child = obj.shape_key_add(name="Child", from_mix=False)
child.relative_key = parent
for index, point in enumerate(child.data):
    point.co = parent.data[index].co.copy()
child.data[1].co.y += 0.5
child.data[2].co.y -= 0.25

source = obj.shape_key_add(name="Source", from_mix=False)
source.data[2].co = (0.2, 2.0, 3.0)

registered = (
    module.OP_SelectShapekeyOffsetedVerticex,
    module.OP_RemoveSelectedVerticesInActiveShapekey,
    module.OP_ClearSelectedVerticesInActiveShapekey,
    module.OP_SmoothShapekey,
)
props_registered = False
for operator in registered:
    bpy.utils.register_class(operator)

try:
    module.reg_props()
    props_registered = True
    assert not hasattr(
        bpy.types.Scene, "hoShapekeyTools_selectedBaseShapekey")
    assert "shape_key" in (
        module.OP_RemoveSelectedVerticesInActiveShapekey.__annotations__)
    assert "algorithm" in (
        module.OP_RemoveSelectedVerticesInActiveShapekey.__annotations__)
    algorithm_prop = (
        bpy.ops.ho.remove_selected_vertices_in_activeshapekey
        .get_rna_type().properties["algorithm"])
    assert str(algorithm_prop.default) == 'REPLACE'
    assert [
        (item.identifier, item.name) for item in algorithm_prop.enum_items
    ] == [
        ('REPLACE', "替换"), ('ADD', "加"), ('SUBTRACT', "减"),
    ]
    blend_prop = (
        bpy.ops.ho.remove_selected_vertices_in_activeshapekey
        .get_rna_type().properties["blend"])
    assert abs(blend_prop.default - 1.0) < 1e-6

    # 嵌套键只选择相对 Parent 发生位移的点；Parent 自身相对 Basis 的位移不能混入。
    activate_key(obj, child)
    select_vertices(obj, ())
    bpy.ops.object.mode_set(mode='OBJECT')
    assert bpy.ops.ho.select_positive_offset_vertices() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert {v.index for v in obj.data.vertices if v.select} == {1, 2}

    # 清除选中点与 Shift/对象模式全清除都必须回到 Child 的 Parent，而不是 Basis。
    child_vertex_two = child.data[2].co.copy()
    select_vertices(obj, (1,))
    assert bpy.ops.ho.clear_selected_vertices_in_activeshapekey(
        "EXEC_DEFAULT") == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert np.allclose(child.data[1].co[:], parent.data[1].co[:], atol=1e-6)
    assert np.allclose(child.data[2].co[:], child_vertex_two[:], atol=1e-6)

    child.data[1].co.y += 0.5
    assert bpy.ops.ho.clear_selected_vertices_in_activeshapekey(
        "EXEC_DEFAULT", clear_whole_key=True) == {'FINISHED'}
    assert np.allclose(positions(child), positions(parent), atol=1e-6)

    # “替换”仍接受任意来源键，但来源键现在属于算子弹窗，不再占据面板常驻输入。
    child.data[2].co.y -= 0.25
    select_vertices(obj, (2,))
    assert bpy.ops.ho.remove_selected_vertices_in_activeshapekey(
        "EXEC_DEFAULT", shape_key="Source") == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert np.allclose(child.data[2].co[:], source.data[2].co[:], atol=1e-6)

    # 加/减模式：以来源键相对其自身相对键的位移为基准，且只影响选中点。
    # NestedSource 相对 Parent 的位移是 (0, 2, 5)，相对 Basis 则是 (0, 2, 6)，
    # 因此结果可以区分“来源键的相对键”与“基型”两种基准。
    nested_source = obj.shape_key_add(name="NestedSource", from_mix=False)
    nested_source.relative_key = parent
    nested_source.data[1].co = (0.1, 2.0, 6.0)

    child.data[1].co = basis.data[1].co.copy()
    select_vertices(obj, (1,))
    assert bpy.ops.ho.remove_selected_vertices_in_activeshapekey(
        "EXEC_DEFAULT", shape_key="NestedSource",
        algorithm='ADD') == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert np.allclose(child.data[1].co[:], (0.1, 2.0, 5.0), atol=1e-6)
    # 未选中的点不受影响。
    assert np.allclose(child.data[2].co[:], source.data[2].co[:], atol=1e-6)

    select_vertices(obj, (1,))
    assert bpy.ops.ho.remove_selected_vertices_in_activeshapekey(
        "EXEC_DEFAULT", shape_key="NestedSource",
        algorithm='SUBTRACT') == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert np.allclose(child.data[1].co[:], basis.data[1].co[:], atol=1e-6)

    # 混合强度：替换按比例向来源键插值，加/减按倍数叠加位移，强度 0 保持不动。
    child.data[1].co = basis.data[1].co.copy()
    select_vertices(obj, (1,))
    assert bpy.ops.ho.remove_selected_vertices_in_activeshapekey(
        "EXEC_DEFAULT", shape_key="NestedSource", algorithm='ADD',
        blend=0.5) == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    # (0.1, 0, 0) + 0.5 * (0, 2, 5)
    assert np.allclose(child.data[1].co[:], (0.1, 1.0, 2.5), atol=1e-6)

    select_vertices(obj, (1,))
    assert bpy.ops.ho.remove_selected_vertices_in_activeshapekey(
        "EXEC_DEFAULT", shape_key="NestedSource", algorithm='ADD',
        blend=0.0) == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert np.allclose(child.data[1].co[:], (0.1, 1.0, 2.5), atol=1e-6)

    child.data[2].co = (0.2, -0.25, 0.0)
    select_vertices(obj, (2,))
    assert bpy.ops.ho.remove_selected_vertices_in_activeshapekey(
        "EXEC_DEFAULT", shape_key="Source", algorithm='REPLACE',
        blend=0.25) == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    # (0.2, -0.25, 0) + 0.25 * ((0.2, 2, 3) - (0.2, -0.25, 0))
    assert np.allclose(child.data[2].co[:], (0.2, 0.3125, 0.75), atol=1e-6)

    # 零相对位移经过平滑后仍应严格等于 Parent；若错误使用 Basis，此处会改坏 Parent 形状。
    smooth = obj.shape_key_add(name="Smooth", from_mix=False)
    smooth.relative_key = parent
    for index, point in enumerate(smooth.data):
        point.co = parent.data[index].co.copy()
    activate_key(obj, smooth)
    select_vertices(obj, range(len(obj.data.vertices)))
    assert bpy.ops.ho.smooth_shapekey("EXEC_DEFAULT") == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert np.allclose(positions(smooth), positions(parent), atol=1e-6)
finally:
    if obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    if props_registered:
        module.ureg_props()
    for operator in reversed(registered):
        bpy.utils.unregister_class(operator)

print("SHAPEKEY_RELATIVE_EDIT_TOOLS_OK", bpy.app.version_string)
