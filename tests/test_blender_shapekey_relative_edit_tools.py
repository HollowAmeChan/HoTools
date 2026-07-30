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
