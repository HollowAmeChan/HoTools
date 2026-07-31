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


def make_eye_and_mouth_mesh(name):
    # 两片有真实三角面的眼睑条带，加一个空间上分离的嘴部面片。
    vertices = [
        (-1.0, 0.0, 0.8), (0.0, 0.0, 0.8), (1.0, 0.0, 0.8),
        (-1.0, 0.0, 0.5), (0.0, 0.0, 0.5), (1.0, 0.0, 0.5),
        (-1.0, 0.0, -0.5), (0.0, 0.0, -0.5), (1.0, 0.0, -0.5),
        (-1.0, 0.0, -0.8), (0.0, 0.0, -0.8), (1.0, 0.0, -0.8),
        (-0.5, -3.0, 0.25), (0.5, -3.0, 0.25),
        (-0.5, -3.0, -0.25), (0.5, -3.0, -0.25),
    ]
    faces = [
        (0, 1, 4, 3), (1, 2, 5, 4),
        (6, 7, 10, 9), (7, 8, 11, 10),
        (12, 13, 15, 14),
    ]
    data = bpy.data.meshes.new(f"{name}Data")
    data.from_pydata(vertices, [], faces)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    activate(obj)
    return obj


def add_closure_shape_keys(obj):
    basis = obj.shape_key_add(name="Basis", from_mix=False)
    ordinary_sculpt = obj.shape_key_add(name="OrdinarySculpt", from_mix=False)
    for point in ordinary_sculpt.data:
        point.co.y += 2.0

    eye_sculpt = obj.shape_key_add(name="EyeSculpt", from_mix=False)
    for index, point in enumerate(eye_sculpt.data):
        if index < 12:
            point.co.z *= 1.4

    blink = obj.shape_key_add(name="Blink", from_mix=False)
    for index in (0, 1, 2):
        blink.data[index].co.z -= 0.15
    for index in (3, 4, 5):
        blink.data[index].co.z -= 0.45
    for index in (6, 7, 8):
        blink.data[index].co.z += 0.45
    for index in (9, 10, 11):
        blink.data[index].co.z += 0.15

    mouth_open = obj.shape_key_add(name="MouthOpen", from_mix=False)
    for index in (14, 15):
        mouth_open.data[index].co.z -= 0.4
    return basis, ordinary_sculpt, eye_sculpt, blink, mouth_open


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
assert "eye_vertex_group" not in (
    module.OP_ShapekeyTools_RebasePreserveExpressions.__annotations__)
assert "factor" not in (
    module.OP_ShapekeyTools_RebasePreserveExpressions.__annotations__)
assert {
    "ordinary_shape_key", "eye_shape_key", "blink_reference_key",
}.issubset(module.OP_ShapekeyTools_RebasePreserveExpressions.__annotations__)
assert (
    module.OP_ShapekeyTools_RebasePreserveExpressions.bl_idname
    == "ho.rebase_shapekeys_preserve_expressions"
)

# 局部变形必须由新相对键的坐标架承载。旧表情沿局部 X 拉伸两倍；新眼眶旋转
# 九十度后，目标边也必须沿旋转后的局部 X 拉伸，而不能继续指向旧世界 X。
local_rest = np.array(
    [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
    dtype=np.float32,
)
local_key = np.array(
    [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
    dtype=np.float32,
)
local_new = np.array(
    [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)],
    dtype=np.float32,
)
_first, _second, local_targets, _weights = (
    module._ho_triangle_transfer_constraints(
        local_rest,
        local_key,
        local_new,
        np.array([(0, 1, 2)], dtype=np.int32),
        np.ones(3, dtype=np.float32),
        1.0,
    )
)
assert np.allclose(local_targets[0], (0.0, 2.0, 0.0), atol=1e-6)
assert np.allclose(local_targets[1], (-1.0, 0.0, 0.0), atol=1e-6)

# 局部 FBSF 只能保留形状差分，不能把左右眼的整体捏脸平移拉回旧位置。
uniform_shift = np.tile((0.0, 2.0, 0.0), (4, 1)).astype(np.float32)
uniform_global = fbsf_basis + uniform_shift
centered_baseline = module._ho_local_fbsf_baseline(
    uniform_global,
    uniform_shift,
    np.ones(4, dtype=np.float32),
    np.ones(4, dtype=np.float32),
    fbsf_basis,
    1.0,
)
assert np.allclose(centered_baseline, uniform_global, atol=1e-6)

registered = (
    module.OP_ShapekeyTools_Apply_ActiveShapekey2Basis,
    module.OP_ShapekeyTools_RebaseFBSF,
    module.OP_ShapekeyTools_RebasePreserveExpressions,
)
for operator in registered:
    bpy.utils.register_class(operator)

try:
    obj = make_eye_and_mouth_mesh("LocalRebase")
    basis, ordinary_sculpt, eye_sculpt, expression, mouth_open = (
        add_closure_shape_keys(obj))

    nested = obj.shape_key_add(name="Nested", from_mix=False)
    nested.relative_key = expression
    for index, point in enumerate(nested.data):
        point.co = expression.data[index].co.copy()
        point.co.y += 0.2

    eye_child = obj.shape_key_add(name="RelativeToEyeSculpt", from_mix=False)
    eye_child.relative_key = eye_sculpt
    for index, point in enumerate(eye_child.data):
        point.co = eye_sculpt.data[index].co.copy()
        point.co.x += 0.15

    old_basis = positions(basis)
    old_expression = positions(expression)
    old_mouth_open = positions(mouth_open)
    old_nested = positions(nested)
    topology = module._ho_rebase_topology(obj.data, old_basis)
    default_pairs = module._ho_reference_pairs(
        old_basis, old_expression, topology, 1.5, 0.35)
    wide_pairs = module._ho_reference_pairs(
        old_basis, old_expression, topology, 6.0, 0.35)
    assert len(default_pairs) == 3
    # 搜索半径只扩大闭眼参考的候选范围，不能反向排除已经找到的眼睑关系。
    assert len(wide_pairs) == len(default_pairs)
    automatic_weights = module._ho_automatic_eye_weights(
        old_basis, old_expression, default_pairs, topology, 2)
    assert np.all(automatic_weights[:12] > 0.0)
    assert np.allclose(automatic_weights[12:], 0.0)

    # 单侧运动不能误配到另一个独立网格岛上的静止表面。
    one_sided = old_basis.copy()
    one_sided[3:6, 2] -= 0.9
    assert not module._ho_reference_pairs(
        old_basis, one_sided, topology, 1.5, 0.35)

    # 任一后续键求解失败时，规划阶段不得提前写入已经处理过的键。
    obj.active_shape_key_index = obj.data.shape_keys.key_blocks.find(
        ordinary_sculpt.name)
    before_transaction = {
        key.name: positions(key).copy()
        for key in obj.data.shape_keys.key_blocks
    }
    calls = [0]

    def fail_after_first(
            _key, old_key, old_relative, new_relative,
            _old_basis, _old_active, _new_basis):
        calls[0] += 1
        if calls[0] > 1:
            raise RuntimeError("planned failure")
        return old_key + (new_relative - old_relative)

    try:
        module._rewrite_rebased_shape_key_tree(obj, 0.5, fail_after_first)
    except RuntimeError as exc:
        assert str(exc) == "planned failure"
    else:
        raise AssertionError("规划阶段异常未向上传递")
    for key in obj.data.shape_keys.key_blocks:
        assert np.array_equal(positions(key), before_transaction[key.name])
    assert obj.data.shape_keys.key_blocks.get("OrdinarySculpt") is not None
    assert obj.data.shape_keys.key_blocks.get("EyeSculpt") is not None

    calls[0] = 0
    try:
        module._rewrite_ho_dual_shape_key_tree(
            obj,
            obj.data.shape_keys,
            basis,
            ordinary_sculpt,
            eye_sculpt,
            fail_after_first,
        )
    except RuntimeError as exc:
        assert str(exc) == "planned failure"
    else:
        raise AssertionError("双键规划阶段异常未向上传递")
    for key in obj.data.shape_keys.key_blocks:
        assert np.array_equal(positions(key), before_transaction[key.name])
    assert obj.data.shape_keys.key_blocks.get("OrdinarySculpt") is not None
    assert obj.data.shape_keys.key_blocks.get("EyeSculpt") is not None

    ordinary_sculpt.value = 1.0
    eye_sculpt.value = 1.0
    obj.active_shape_key_index = obj.data.shape_keys.key_blocks.find(
        eye_sculpt.name)
    result = bpy.ops.ho.rebase_shapekeys_preserve_expressions(
        "EXEC_DEFAULT",
        ordinary_shape_key="OrdinarySculpt",
        eye_shape_key="EyeSculpt",
        blink_reference_key="Blink",
        transfer_strength=1.0,
        closure_strength=1.0,
        contact_radius_factor=1.5,
        max_gap_ratio=0.35,
        smooth_rings=2,
    )
    assert result == {'FINISHED'}

    keys = obj.data.shape_keys.key_blocks
    assert keys.get("OrdinarySculpt") is None
    assert keys.get("EyeSculpt") is None
    basis = keys[0]
    expression = keys["Blink"]
    mouth_open = keys["MouthOpen"]
    nested = keys["Nested"]
    eye_child = keys["RelativeToEyeSculpt"]
    assert nested.relative_key == expression
    assert eye_child.relative_key == basis

    # Basis 完整采用捏脸结果；闭眼键不是旧坐标透传，而是在扩大后的新眼眶上
    # 重新应用局部变形和跨眼睑闭合关系。
    for index in range(12):
        expected = old_basis[index].copy()
        expected[1] += 2.0
        expected[2] *= 1.4
        assert_position(basis, index, expected)
    for upper, lower in zip((3, 4, 5), (6, 7, 8)):
        global_gap = abs(
            (old_expression[upper, 2] + basis.data[upper].co.z - old_basis[upper, 2])
            - (old_expression[lower, 2] + basis.data[lower].co.z - old_basis[lower, 2])
        )
        new_gap = abs(expression.data[upper].co.z - expression.data[lower].co.z)
        assert new_gap < global_gap * 0.75, (new_gap, global_gap)
        old_gap = abs(old_expression[upper, 2] - old_expression[lower, 2])
        assert new_gap <= old_gap + 1e-4, (new_gap, old_gap)
    for index in range(12):
        assert abs(expression.data[index].co.y - 2.0) < 1e-4

    # 眼部组之外必须逐顶点等于普通全局变基，张嘴不能再发生 FBSF 式回弹。
    new_basis_positions = positions(basis)
    expected_mouth = old_mouth_open + (new_basis_positions - old_basis)
    assert np.allclose(positions(mouth_open)[12:], expected_mouth[12:], atol=1e-6)

    # 嵌套键仍沿修正后的父键迁移，统一平移不会被眼部局部求解吞掉。
    for index in range(len(old_nested)):
        assert_position(nested, index, (
            expression.data[index].co.x,
            expression.data[index].co.y + 0.2,
            expression.data[index].co.z,
        ))
    for index in range(len(old_basis)):
        assert_position(eye_child, index, (
            basis.data[index].co.x + 0.15,
            basis.data[index].co.y,
            basis.data[index].co.z,
        ))

    # 前置检查会拒绝不安全状态，并且不改变已经保存的坐标。
    guarded = make_mesh("GuardedRebase", vertex_count=2)
    guarded_basis = guarded.shape_key_add(name="Basis", from_mix=False)
    guarded_ordinary = guarded.shape_key_add(name="Ordinary", from_mix=False)
    guarded_eye = guarded.shape_key_add(name="Eye", from_mix=False)
    guarded_blink = guarded.shape_key_add(name="Blink", from_mix=False)
    guarded_expression = guarded.shape_key_add(name="Expression", from_mix=False)
    guarded_ordinary.data[0].co.y += 1.0
    guarded_eye.data[0].co.z += 1.0
    guarded_ordinary.value = 1.0
    guarded_eye.value = 0.5
    guarded.active_shape_key_index = 1
    original_basis = positions(guarded_basis)
    result = bpy.ops.ho.rebase_shapekeys_preserve_expressions(
        "EXEC_DEFAULT",
        ordinary_shape_key="Ordinary",
        eye_shape_key="Eye",
        blink_reference_key="Blink",
    )
    assert result == {'CANCELLED'}
    assert np.allclose(positions(guarded_basis), original_basis)
    assert guarded.data.shape_keys.key_blocks.get("Ordinary") is not None
    assert guarded.data.shape_keys.key_blocks.get("Eye") is not None

    guarded_eye.value = 1.0
    guarded_expression.value = 0.25
    result = bpy.ops.ho.rebase_shapekeys_preserve_expressions(
        "EXEC_DEFAULT",
        ordinary_shape_key="Ordinary",
        eye_shape_key="Eye",
        blink_reference_key="Blink",
    )
    assert result == {'CANCELLED'}
    assert np.allclose(positions(guarded_basis), original_basis)

    guarded_expression.value = 0.0
    guarded.data.shape_keys.use_relative = False
    result = bpy.ops.ho.rebase_shapekeys_preserve_expressions(
        "EXEC_DEFAULT",
        ordinary_shape_key="Ordinary",
        eye_shape_key="Eye",
        blink_reference_key="Blink",
    )
    assert result == {'CANCELLED'}
    assert np.allclose(positions(guarded_basis), original_basis)

    guarded.data.shape_keys.use_relative = True
    result = bpy.ops.ho.rebase_shapekeys_preserve_expressions(
        "EXEC_DEFAULT",
        ordinary_shape_key="Ordinary",
        eye_shape_key="Eye",
        blink_reference_key="Missing",
    )
    assert result == {'CANCELLED'}
    assert np.allclose(positions(guarded_basis), original_basis)
    assert guarded.data.shape_keys.key_blocks.get("Ordinary") is not None
    assert guarded.data.shape_keys.key_blocks.get("Eye") is not None

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
