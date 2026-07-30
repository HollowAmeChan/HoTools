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


def make_closure_mesh(name):
    # 两条拓扑上分离、空间上可接触的条带，模拟上下眼睑或上下唇。
    vertices = [
        (-1.0, 0.0, 0.5), (0.0, 0.0, 0.5), (1.0, 0.0, 0.5),
        (-1.0, 0.0, -0.5), (0.0, 0.0, -0.5), (1.0, 0.0, -0.5),
    ]
    edges = [(0, 1), (1, 2), (3, 4), (4, 5)]
    data = bpy.data.meshes.new(f"{name}Data")
    data.from_pydata(vertices, edges, [])
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    activate(obj)
    return obj


def add_closure_shape_keys(obj):
    basis = obj.shape_key_add(name="Basis", from_mix=False)
    sculpt = obj.shape_key_add(name="FaceSculpt", from_mix=False)
    for index, point in enumerate(sculpt.data):
        point.co.y += 2.0
        point.co.z += 0.3 if index < 3 else -0.1

    expression = obj.shape_key_add(name="Blink", from_mix=False)
    for index, point in enumerate(expression.data):
        point.co.z += -0.45 if index < 3 else 0.45
    return basis, sculpt, expression


def positions(key):
    return np.array([point.co[:] for point in key.data], dtype=np.float32)


def assert_position(key, index, expected):
    actual = np.array(key.data[index].co[:], dtype=np.float32)
    assert np.allclose(actual, expected, atol=1e-6), (key.name, index, actual, expected)


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
    obj = make_closure_mesh("LocalRebase")
    basis, sculpt, expression = add_closure_shape_keys(obj)

    nested = obj.shape_key_add(name="Nested", from_mix=False)
    nested.relative_key = expression
    for index, point in enumerate(nested.data):
        point.co = expression.data[index].co.copy()
        point.co.y += 0.2

    old_basis = positions(basis)
    old_sculpt = positions(sculpt)
    old_expression = positions(expression)
    old_nested = positions(nested)
    topology = module._ho_rebase_topology(obj.data, old_basis)
    default_pairs = module._ho_convergence_pairs(
        old_basis, old_expression, topology, 0.75, 0.35)
    wide_pairs = module._ho_convergence_pairs(
        old_basis, old_expression, topology, 3.0, 0.35)
    assert len(default_pairs) == 3
    # 搜索半径只能扩大候选范围，不能反过来提高旧基型间距门槛。
    assert len(wide_pairs) == len(default_pairs)

    obj.active_shape_key_index = obj.data.shape_keys.key_blocks.find(sculpt.name)
    result = bpy.ops.ho.rebase_shapekeys_preserve_expressions(
        "EXEC_DEFAULT",
        factor=0.5,
        correction_strength=1.0,
        contact_radius_factor=0.75,
        max_gap_ratio=0.35,
        smooth_rings=2,
    )
    assert result == {'FINISHED'}

    keys = obj.data.shape_keys.key_blocks
    assert keys.get("FaceSculpt") is None
    basis = keys[0]
    expression = keys["Blink"]
    nested = keys["Nested"]
    assert nested.relative_key == expression

    # HO 以 FBSF 为保底，并把上下条带恢复到原表情的绝对闭合间距；即使新眼眶
    # 间距增大，旧闭眼缝也不能按比例被放大，同时整体仍处于捏脸后的 y 位置。
    for index in range(3):
        assert_position(basis, index, ((-1.0, 0.0, 1.0)[index], 1.0, 0.65))
    for index in range(3, 6):
        x = (-1.0, 0.0, 1.0)[index - 3]
        assert_position(basis, index, (x, 1.0, -0.55))
    for index in range(3):
        old_gap = abs(old_expression[index, 2] - old_expression[index + 3, 2])
        new_gap = abs(expression.data[index].co.z - expression.data[index + 3].co.z)
        assert new_gap <= old_gap + 1e-5
        assert abs(expression.data[index].co.y - 1.0) < 1e-4
    # 同一条带的修正应保持连续，不能形成旧 HO 那种阈值褶纹。
    assert abs((expression.data[1].co.z - expression.data[0].co.z)) < 1e-4
    assert abs((expression.data[2].co.z - expression.data[1].co.z)) < 1e-4
    assert abs((expression.data[4].co.z - expression.data[3].co.z)) < 1e-4
    assert abs((expression.data[5].co.z - expression.data[4].co.z)) < 1e-4
    nested_weights, _left, _right, _split = module._fbsf_rebase_weights(
        old_nested - old_expression,
        old_sculpt - old_basis,
        old_basis,
        0.0,
        1.0,
    )
    expression_shift = positions(expression) - old_expression
    expected_nested = (
        old_nested + expression_shift
        - expression_shift * nested_weights[:, None]
    )
    assert np.allclose(positions(nested), expected_nested, atol=1e-6)

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
