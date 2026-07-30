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


def activate(obj):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def make_mesh(name, vertex_count=5):
    data = bpy.data.meshes.new(f"{name}Data")
    data.from_pydata([(float(index), 0.0, 0.0) for index in range(vertex_count)], [], [])
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    activate(obj)
    return obj


def positions(key):
    return np.array([point.co[:] for point in key.data], dtype=np.float32)


def assert_position(key, index, expected):
    actual = np.array(key.data[index].co[:], dtype=np.float32)
    assert np.allclose(actual, expected, atol=1e-6), (key.name, index, actual, expected)


# 柔化遮罩先按位移幅度混合，再应用全局保护强度；过渡宽度为零时，
# 仍然使用严格的移动/未移动二值遮罩。
delta = np.array(
    [
        (0.0, 0.0, 0.0),
        (0.5, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (2.0, 0.0, 0.0),
    ],
    dtype=np.float32,
)
mask = module._shape_key_rebase_mask(delta, 0.0, 0.5, 0.5)
assert np.allclose(mask, (0.0, 0.25, 0.5, 0.5), atol=1e-6)
binary_mask = module._shape_key_rebase_mask(delta, 0.5, 0.0, 1.0)
assert np.allclose(binary_mask, (0.0, 0.0, 1.0, 1.0), atol=1e-6)

# FBSF 自动权重按左右半脸分别比较目标表情与捏脸 delta。
# 同向位移得到 1，正交位移得到 0；左右过渡只在分数确实不同时启用。
fbsf_basis = np.array(
    [(-1.0, 0.0, 0.0), (-0.05, 0.0, 0.0),
     (0.05, 0.0, 0.0), (1.0, 0.0, 0.0)],
    dtype=np.float32,
)
fbsf_edit = np.array([(0.0, 1.0, 0.0)] * 4, dtype=np.float32)
fbsf_target = np.array(
    [(0.0, 1.0, 0.0), (0.0, 1.0, 0.0),
     (0.0, 0.0, 1.0), (0.0, 0.0, 1.0)],
    dtype=np.float32,
)
hard_weights, left_score, right_score, split_sides = module._fbsf_rebase_weights(
    fbsf_target, fbsf_edit, fbsf_basis, 0.0, 1.0)
assert left_score == 1.0
assert right_score == 0.0
assert split_sides
assert np.allclose(hard_weights, (1.0, 1.0, 0.0, 0.0), atol=1e-6)

smooth_weights, _left, _right, _split = module._fbsf_rebase_weights(
    fbsf_target, fbsf_edit, fbsf_basis, 0.1, 1.0)
assert np.allclose(smooth_weights, (1.0, 0.75, 0.25, 0.0), atol=1e-6)

# 原实现把反向内积按一半强度计入相似度，这个看似特殊的行为也必须保持。
opposite_weights, left_score, right_score, split_sides = module._fbsf_rebase_weights(
    -fbsf_edit, fbsf_edit, fbsf_basis, 0.0, 1.0)
assert left_score == 0.5
assert right_score == 0.5
assert not split_sides
assert np.allclose(opposite_weights, 0.5, atol=1e-6)
assert module._fbsf_threshold_map(0.05) == 0.0
assert module._fbsf_threshold_map(0.95) == 1.0
assert module.OP_ShapekeyTools_RebaseFBSF.bl_label == "全键局部变基-FBSF"
assert module.OP_ShapekeyTools_RebasePreserveExpressions.bl_label == "全键局部变基-HO"
assert (
    module.OP_ShapekeyTools_RebasePreserveExpressions.bl_idname
    == "ho.rebase_shapekeys_preserve_expressions"
)

registered = (
    module.OP_ShapekeyTools_Apply_ActiveShapekey2Basis,
    module.OP_ShapekeyTools_RebaseFBSF,
    module.OP_ShapekeyTools_RebasePreserveExpressions,
)
for operator in registered:
    bpy.utils.register_class(operator)

try:
    obj = make_mesh("LocalRebase")
    basis = obj.shape_key_add(name="Basis", from_mix=False)
    sculpt = obj.shape_key_add(name="FaceSculpt", from_mix=False)
    for point in sculpt.data:
        point.co.y += 1.0

    expression = obj.shape_key_add(name="Expression", from_mix=False)
    expression.data[0].co.z += 1.0
    expression.data[2].co.z += 0.05
    expression.data[3].co.z += 2.0

    nested = obj.shape_key_add(name="Nested", from_mix=False)
    nested.relative_key = expression
    for index, point in enumerate(nested.data):
        point.co = expression.data[index].co.copy()
    nested.data[1].co.x += 0.5

    active_child = obj.shape_key_add(name="RelativeToSculpt", from_mix=False)
    active_child.relative_key = sculpt
    for index, point in enumerate(active_child.data):
        point.co = sculpt.data[index].co.copy()
    active_child.data[4].co.z += 0.5

    obj.active_shape_key_index = obj.data.shape_keys.key_blocks.find(sculpt.name)
    result = bpy.ops.ho.rebase_shapekeys_preserve_expressions(
        "EXEC_DEFAULT",
        factor=0.5,
        movement_threshold=0.1,
        falloff_ratio=0.0,
        protection_strength=1.0,
    )
    assert result == {'FINISHED'}

    keys = obj.data.shape_keys.key_blocks
    assert keys.get("FaceSculpt") is None
    basis = keys[0]
    expression = keys["Expression"]
    nested = keys["Nested"]
    active_child = keys["RelativeToSculpt"]
    assert nested.relative_key == expression
    assert active_child.relative_key == basis

    for index in range(5):
        assert_position(basis, index, (float(index), 0.5, 0.0))

    # 超过阈值的表情顶点保持原来的绝对目标位置。
    assert_position(expression, 0, (0.0, 0.0, 1.0))
    assert_position(expression, 1, (1.0, 0.5, 0.0))
    assert_position(expression, 2, (2.0, 0.5, 0.05))
    assert_position(expression, 3, (3.0, 0.0, 2.0))
    assert_position(expression, 4, (4.0, 0.5, 0.0))

    # 嵌套键在自身局部位移为零的位置跟随重写后的相对键。
    assert_position(nested, 0, (0.0, 0.0, 1.0))
    assert_position(nested, 1, (1.5, 0.0, 0.0))
    assert_position(nested, 2, (2.0, 0.5, 0.05))

    # 被删除捏脸键的子键会安全地改为相对新 Basis。
    assert_position(active_child, 0, (0.0, 0.5, 0.0))
    assert_position(active_child, 4, (4.0, 1.0, 0.5))

    # 前置检查会拒绝不安全状态，并且不改变已经保存的坐标。
    guarded = make_mesh("GuardedRebase", vertex_count=2)
    guarded_basis = guarded.shape_key_add(name="Basis", from_mix=False)
    guarded_sculpt = guarded.shape_key_add(name="Sculpt", from_mix=False)
    guarded_expression = guarded.shape_key_add(name="Expression", from_mix=False)
    guarded_sculpt.data[0].co.y += 1.0
    guarded.active_shape_key_index = 1
    original_basis = positions(guarded_basis)
    guarded_expression.value = 0.25
    result = bpy.ops.ho.rebase_shapekeys_preserve_expressions("EXEC_DEFAULT")
    assert result == {'CANCELLED'}
    assert np.allclose(positions(guarded_basis), original_basis)
    assert guarded.data.shape_keys.key_blocks.get("Sculpt") is not None

    guarded_expression.value = 0.0
    guarded.data.shape_keys.use_relative = False
    result = bpy.ops.ho.rebase_shapekeys_preserve_expressions("EXEC_DEFAULT")
    assert result == {'CANCELLED'}
    assert np.allclose(positions(guarded_basis), original_basis)

    # FBSF 与 HO 是两个独立算子。左侧表情与捏脸同向，因此反向抵消；
    # 右侧表情与捏脸正交，因此保持普通全局变基产生的整体位移。
    fbsf = make_mesh("FBSFRebase", vertex_count=4)
    x_positions = (-1.0, -0.5, 0.5, 1.0)
    for index, x in enumerate(x_positions):
        fbsf.data.vertices[index].co.x = x
    fbsf_basis_key = fbsf.shape_key_add(name="Basis", from_mix=False)
    fbsf_sculpt = fbsf.shape_key_add(name="FaceSculpt", from_mix=False)
    for point in fbsf_sculpt.data:
        point.co.y += 1.0

    fbsf_expression = fbsf.shape_key_add(name="Expression", from_mix=False)
    for index in (0, 1):
        fbsf_expression.data[index].co.y += 1.0
    for index in (2, 3):
        fbsf_expression.data[index].co.z += 1.0

    fbsf_child = fbsf.shape_key_add(name="RelativeToSculpt", from_mix=False)
    fbsf_child.relative_key = fbsf_sculpt
    for index, point in enumerate(fbsf_child.data):
        point.co = fbsf_sculpt.data[index].co.copy()
        point.co.z += 0.25

    fbsf.active_shape_key_index = fbsf.data.shape_keys.key_blocks.find(
        fbsf_sculpt.name)
    result = bpy.ops.ho.rebase_shapekeys_fbsf(
        "EXEC_DEFAULT",
        factor=0.5,
        correction_strength=1.0,
        side_smooth_width=0.0,
    )
    assert result == {'FINISHED'}

    fbsf_keys = fbsf.data.shape_keys.key_blocks
    assert fbsf_keys.get("FaceSculpt") is None
    fbsf_basis_key = fbsf_keys[0]
    fbsf_expression = fbsf_keys["Expression"]
    fbsf_child = fbsf_keys["RelativeToSculpt"]
    assert fbsf_child.relative_key == fbsf_basis_key
    for index, x in enumerate(x_positions):
        assert_position(fbsf_basis_key, index, (x, 0.5, 0.0))
    for index in (0, 1):
        assert_position(fbsf_expression, index, (x_positions[index], 1.0, 0.0))
    for index in (2, 3):
        assert_position(fbsf_expression, index, (x_positions[index], 0.5, 1.0))
    for index, x in enumerate(x_positions):
        assert_position(fbsf_child, index, (x, 0.5, 0.25))

    # 原有全键变基算子保持独立并维持原行为。
    legacy = make_mesh("FullRebase", vertex_count=2)
    legacy_basis = legacy.shape_key_add(name="Basis", from_mix=False)
    legacy_source = legacy.shape_key_add(name="Source", from_mix=False)
    legacy_expression = legacy.shape_key_add(name="Expression", from_mix=False)
    for point in legacy_source.data:
        point.co.y += 1.0
    legacy_expression.data[0].co.z += 1.0
    legacy_source.value = 0.5
    legacy.active_shape_key_index = 1

    result = bpy.ops.ho.apply_active_shapekey_to_basis("EXEC_DEFAULT")
    assert result == {'FINISHED'}
    legacy_keys = legacy.data.shape_keys.key_blocks
    assert legacy_keys.get("Source") is None
    assert_position(legacy_keys[0], 0, (0.0, 0.5, 0.0))
    assert_position(legacy_keys[0], 1, (1.0, 0.5, 0.0))
    assert_position(legacy_keys["Expression"], 0, (0.0, 0.5, 1.0))
    assert_position(legacy_keys["Expression"], 1, (1.0, 0.5, 0.0))
finally:
    for operator in reversed(registered):
        bpy.utils.unregister_class(operator)


# 覆盖正式注册列表，确保两个独立命名的算子都能通过插件正常注册。
module.register()
try:
    assert hasattr(bpy.ops.ho, "apply_active_shapekey_to_basis")
    assert hasattr(bpy.ops.ho, "rebase_shapekeys_fbsf")
    assert hasattr(bpy.ops.ho, "rebase_shapekeys_preserve_expressions")
finally:
    module.unregister()


print("SHAPEKEY_REBASE_OK", bpy.app.version_string)
