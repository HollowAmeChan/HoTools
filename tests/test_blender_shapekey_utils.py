import sys
from pathlib import Path

import bpy
import numpy as np


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from Utils import shapekey_utils


def assert_raises(error_type, function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except error_type:
        return
    raise AssertionError(f"{function.__name__} 未抛出 {error_type.__name__}")


def make_mesh(name, vertices, faces=()):
    mesh = bpy.data.meshes.new(f"{name}Data")
    mesh.from_pydata(vertices, [], faces)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


obj = make_mesh(
    "ShapeKeyUtilsContract",
    [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
     (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
    [(0, 1, 2, 3)],
)

# Basis 创建必须幂等，并始终返回 Blender 记录的真实参考键。
basis = shapekey_utils.ensure_basis_shape_key(obj)
assert shapekey_utils.ensure_basis_shape_key(obj) == basis
assert shapekey_utils.require_shape_keys(obj).reference_key == basis
assert_raises(
    shapekey_utils.ShapeKeyUtilsError,
    shapekey_utils.require_shape_keys,
    bpy.data.objects.new("NotMesh", None),
)

# 坐标批量读写必须保持形状、数值与数据所有权。
smile = obj.shape_key_add(name="Smile", from_mix=False)
smile_positions = shapekey_utils.read_shape_key_positions(smile)
smile_positions[:, 2] = (0.0, 0.25, 0.5, 0.75)
assert shapekey_utils.write_shape_key_positions(smile, smile_positions) == 4
round_trip = shapekey_utils.read_shape_key_positions(smile)
assert np.allclose(round_trip, smile_positions, atol=1e-6)
round_trip[0, 0] = 99.0
assert smile.data[0].co.x != 99.0

assert_raises(
    shapekey_utils.ShapeKeyUtilsError,
    shapekey_utils.write_shape_key_positions,
    smile,
    np.zeros((3, 3), dtype=np.float32),
)
invalid_positions = smile_positions.copy()
invalid_positions[0, 0] = np.nan
assert_raises(
    shapekey_utils.ShapeKeyUtilsError,
    shapekey_utils.write_shape_key_positions,
    smile,
    invalid_positions,
)

# 坐标与设置复制走同一条公共路径；同一 Key 数据块才能复制 relative_key。
child = obj.shape_key_add(name="Child", from_mix=False)
child.relative_key = smile
child.slider_min = -2.0
child.slider_max = 3.0
child.value = 2.5
child.mute = True
child.lock_shape = True
child.vertex_group = "Face"
child.interpolation = 'KEY_LINEAR'
child_positions = smile_positions + (0.1, -0.2, 0.3)
shapekey_utils.write_shape_key_positions(child, child_positions)
obj.active_shape_key_index = obj.data.shape_keys.key_blocks.find("Child")
assert shapekey_utils.active_relative_shape_key(obj) == smile
obj.active_shape_key_index = 0
assert shapekey_utils.active_relative_shape_key(obj) is None
obj.active_shape_key_index = obj.data.shape_keys.key_blocks.find("Child")

duplicate = obj.shape_key_add(name="Duplicate", from_mix=False)
assert shapekey_utils.copy_shape_key_positions(child, duplicate) == 4
copied_settings = shapekey_utils.copy_shape_key_settings(child, duplicate)
assert np.allclose(
    shapekey_utils.read_shape_key_positions(duplicate), child_positions, atol=1e-6)
assert duplicate.relative_key == smile
assert duplicate.slider_min == -2.0
assert duplicate.slider_max == 3.0
assert duplicate.value == 2.5
assert duplicate.mute is True
assert duplicate.lock_shape is True
assert duplicate.vertex_group == "Face"
assert duplicate.interpolation == 'KEY_LINEAR'
assert "relative_key" in copied_settings

other = make_mesh(
    "ShapeKeyUtilsOther",
    [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
     (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
)
other_basis = shapekey_utils.ensure_basis_shape_key(other)
other_key = other.shape_key_add(name="Other", from_mix=False)
shapekey_utils.copy_shape_key_settings(child, other_key)
assert other_key.relative_key == other_basis

short_obj = make_mesh("ShapeKeyUtilsShort", [(0.0, 0.0, 0.0)])
short_basis = shapekey_utils.ensure_basis_shape_key(short_obj)
assert_raises(
    shapekey_utils.ShapeKeyUtilsError,
    shapekey_utils.copy_shape_key_positions,
    child,
    short_basis,
)

# 重排会先校验完整名称集合，失败时不得改变已有顺序。
for selected in bpy.context.selected_objects:
    selected.select_set(False)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
obj.active_shape_key_index = obj.data.shape_keys.key_blocks.find("Child")
requested_order = ["Basis", "Duplicate", "Smile", "Child"]
shapekey_utils.reorder_shape_keys(obj, requested_order)
assert [key.name for key in obj.data.shape_keys.key_blocks] == requested_order
assert obj.active_shape_key.name == "Child"

before_invalid_order = [key.name for key in obj.data.shape_keys.key_blocks]
assert_raises(
    shapekey_utils.ShapeKeyUtilsError,
    shapekey_utils.reorder_shape_keys,
    obj,
    ["Smile", "Basis", "Duplicate", "Child"],
)
assert [key.name for key in obj.data.shape_keys.key_blocks] == before_invalid_order

assert shapekey_utils.move_shape_key_to_index(obj, "Smile", 3)
assert obj.active_shape_key.name == "Smile"
assert [key.name for key in obj.data.shape_keys.key_blocks] == [
    "Basis", "Duplicate", "Child", "Smile"]
assert not shapekey_utils.move_shape_key_to_index(obj, "Missing", 1)
assert_raises(
    shapekey_utils.ShapeKeyUtilsError,
    shapekey_utils.move_shape_key_to_index,
    obj,
    "Smile",
    0,
)

# 依赖排序不受列表显示顺序影响，父相对键必须先于子键。
duplicate.relative_key = child
dependency_order = shapekey_utils.relative_shape_key_order(obj.data.shape_keys)
dependency_names = [key.name for key in dependency_order]
assert dependency_names.index("Smile") < dependency_names.index("Child")
assert dependency_names.index("Child") < dependency_names.index("Duplicate")
assert [key.name for key in shapekey_utils.relative_shape_key_order(
    obj.data.shape_keys, excluded=(child,))] == ["Duplicate", "Smile"]

smile.relative_key = child
child.relative_key = smile
assert_raises(
    shapekey_utils.ShapeKeyDependencyError,
    shapekey_utils.relative_shape_key_order,
    obj.data.shape_keys,
)
smile.relative_key = basis
child.relative_key = smile

assert shapekey_utils.validate_shape_key_vertex_counts(obj.data.shape_keys) == 4
triangles = shapekey_utils.mesh_triangle_indices(obj.data)
assert triangles.shape == (2, 3)
assert set(triangles.reshape(-1)) == {0, 1, 2, 3}

print("SHAPEKEY_UTILS_CONTRACT_OK", bpy.app.version_string)
