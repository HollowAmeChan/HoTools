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


# 本地 FBSF 近似权重按左右半脸分别比较目标表情与捏脸 delta。
# 同向位移得到 1，正交位移得到 0；左右过渡只在分数确实不同时启用。
fbsf_basis = np.array(
    [(-1.0, 0.0, 0.0), (-0.05, 0.0, 0.0),
     (0.05, 0.0, 0.0), (1.0, 0.0, 0.0)],
    dtype=np.float32,
)
fbsf_edit = np.array([(0.0, 1.0, 0.0)] * 4, dtype=np.float32)
fbsf_target = np.array(
    [(0.0, 0.0, 1.0), (0.0, 0.0, 1.0),
     (0.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
    dtype=np.float32,
)
hard_weights, left_score, right_score, split_sides = module._fbsf_rebase_weights(
    fbsf_target, fbsf_edit, fbsf_basis, 0.0, 1.0)
assert left_score == 1.0
assert right_score == 0.0
assert split_sides
assert np.allclose(hard_weights, (0.0, 0.0, 1.0, 1.0), atol=1e-6)

smooth_weights, _left, _right, _split = module._fbsf_rebase_weights(
    fbsf_target, fbsf_edit, fbsf_basis, 0.1, 1.0)
assert np.allclose(smooth_weights, (0.0, 0.25, 0.75, 1.0), atol=1e-6)

# 本地早期实现把反向内积按一半强度计入相似度，这个行为必须保持兼容。
opposite_weights, left_score, right_score, split_sides = module._fbsf_rebase_weights(
    -fbsf_edit, fbsf_edit, fbsf_basis, 0.0, 1.0)
assert left_score == 0.5
assert right_score == 0.5
assert not split_sides
assert np.allclose(opposite_weights, 0.5, atol=1e-6)
assert module._fbsf_threshold_map(0.05) == 0.0
assert module._fbsf_threshold_map(0.95) == 1.0
assert module._fbsf_auto_function_tag("@vrc.blink.001") == 'BOTH_EYES'
assert module._fbsf_auto_function_tag("eyeBlinkLeft") == 'LEFT_EYE'
assert module._fbsf_auto_function_tag("eyeBlinkRight.001") == 'RIGHT_EYE'
assert module._fbsf_auto_function_tag("眼眶Left") == 'LEFT_EYE'
assert module._fbsf_auto_function_tag("眼眶Right") == 'RIGHT_EYE'
assert module._fbsf_auto_function_tag("左眼眶") == 'LEFT_EYE'
assert module._fbsf_auto_function_tag("右眼眶.001") == 'RIGHT_EYE'
assert module._fbsf_auto_function_tag("vrc.v_aa") == 'MOUTH'
assert module._fbsf_auto_function_tag("MouthOpen") == 'MOUTH'
assert module._fbsf_auto_function_tag("CheekPuff") == 'OTHERS'

fbsf_references = (
    ('BOTH_EYES', fbsf_target),
    ('MOUTH', np.array([(0.0, 0.0, 1.0)] * 4, dtype=np.float32)),
)
eye_definition = module._fbsf_source_definition(
    fbsf_edit, fbsf_references, fbsf_basis)
assert eye_definition == (1.0, 0.0, 0.0)
assert module._fbsf_infer_left_is_positive(
    (('LEFT_EYE', fbsf_target),), fbsf_basis)
mirrored_left_target = np.array(
    [(0.0, 1.0, 0.0), (0.0, 1.0, 0.0),
     (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)],
    dtype=np.float32,
)
assert not module._fbsf_infer_left_is_positive(
    (('LEFT_EYE', mirrored_left_target),), fbsf_basis)
left_only_weights, left_score, right_score, split_sides = (
    module._fbsf_definition_weights(
        'LEFT_EYE', eye_definition, fbsf_basis, 0.0, 1.0))
assert (left_score, right_score, split_sides) == (1.0, 0.0, True)
assert np.allclose(left_only_weights, (0.0, 0.0, 1.0, 1.0))
legacy_left_weights, *_legacy_details = module._fbsf_definition_weights(
    'LEFT_EYE', eye_definition, fbsf_basis, 0.0, 1.0, False)
assert np.allclose(legacy_left_weights, (1.0, 1.0, 0.0, 0.0))
other_weights, left_score, right_score, split_sides = (
    module._fbsf_definition_weights(
        'OTHERS', eye_definition, fbsf_basis, 0.0, 1.0))
assert (left_score, right_score, split_sides) == (0.0, 0.0, False)
assert not np.any(other_weights)
assert module.OP_ShapekeyTools_RebaseFBSF.bl_label == "全键局部变基-FBSF"
assert "function_tag" in module.PG_ShapekeyTools_FBSFSource.__annotations__
assert "merge" in module.PG_ShapekeyTools_FBSFSource.__annotations__
assert "mergeable" in module.PG_ShapekeyTools_FBSFSource.__annotations__
assert "enabled" not in module.PG_ShapekeyTools_FBSFSource.__annotations__
assert 'SOURCE' not in module.FBSF_FUNCTION_TAGS
assert "factor" not in module.OP_ShapekeyTools_RebaseFBSF.__annotations__
assert {
    "sources", "source_index", "correction_strength", "side_smooth_width",
}.issubset(module.OP_ShapekeyTools_RebaseFBSF.__annotations__)
assert not hasattr(module, "OP_ShapekeyTools_RebasePreserveExpressions")

registered = (
    module.PG_ShapekeyTools_FBSFSource,
    module.HO_UL_ShapekeyTools_FBSFSources,
    module.OP_ShapekeyTools_Apply_ActiveShapekey2Basis,
    module.OP_ShapekeyTools_RebaseFBSF,
)
for operator in registered:
    bpy.utils.register_class(operator)

try:
    # 任一后续键求解失败时，规划阶段不得提前写入已经处理过的键。
    obj = make_mesh("AtomicRebase", vertex_count=3)
    basis = obj.shape_key_add(name="Basis", from_mix=False)
    source = obj.shape_key_add(name="Source", from_mix=False)
    first_target = obj.shape_key_add(name="FirstTarget", from_mix=False)
    second_target = obj.shape_key_add(name="SecondTarget", from_mix=False)
    source.data[0].co.y += 1.0
    first_target.data[1].co.z += 1.0
    second_target.data[2].co.x += 1.0
    obj.active_shape_key_index = obj.data.shape_keys.key_blocks.find(source.name)
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
    assert obj.data.shape_keys.key_blocks.get("Source") is not None

    # 两个非零捏脸键会作为 FBSF 来源列表一起烘焙，并按左右权能修正。
    fbsf = make_mesh("FBSFRebase", vertex_count=4)
    x_positions = (-1.0, -0.5, 0.5, 1.0)
    for index, x in enumerate(x_positions):
        fbsf.data.vertices[index].co.x = x
    fbsf_basis_key = fbsf.shape_key_add(name="Basis", from_mix=False)
    fbsf_sculpt = fbsf.shape_key_add(name="EyeSculptLeft", from_mix=False)
    for index in (2, 3):
        fbsf_sculpt.data[index].co.z += 1.0

    fbsf_sculpt_z = fbsf.shape_key_add(name="EyeSculptRight", from_mix=False)
    for index in (0, 1):
        fbsf_sculpt_z.data[index].co.y += 1.0

    fbsf_expression = fbsf.shape_key_add(name="Blink", from_mix=False)
    for index in (0, 1):
        fbsf_expression.data[index].co.y += 1.0
    for index in (2, 3):
        fbsf_expression.data[index].co.z += 1.0

    fbsf_mouth = fbsf.shape_key_add(name="MouthOpen", from_mix=False)
    for point in fbsf_mouth.data:
        point.co.z += 1.0

    fbsf_other = fbsf.shape_key_add(name="CheekPuff", from_mix=False)
    for point in fbsf_other.data:
        point.co.x += 0.1

    fbsf_child = fbsf.shape_key_add(name="RelativeToSculpt", from_mix=False)
    fbsf_child.relative_key = fbsf_sculpt
    for index, point in enumerate(fbsf_child.data):
        point.co = fbsf_sculpt.data[index].co.copy()
        point.co.x += 0.25

    fbsf_sculpt.value = 0.5
    fbsf_sculpt_z.value = 0.25
    fbsf.active_shape_key_index = fbsf.data.shape_keys.key_blocks.find(
        fbsf_sculpt.name)
    result = bpy.ops.ho.rebase_shapekeys_fbsf(
        "EXEC_DEFAULT",
        correction_strength=1.0,
        side_smooth_width=0.0,
    )
    assert result == {'FINISHED'}

    fbsf_keys = fbsf.data.shape_keys.key_blocks
    assert fbsf_keys.get("EyeSculptLeft") is None
    assert fbsf_keys.get("EyeSculptRight") is None
    fbsf_basis_key = fbsf_keys[0]
    fbsf_expression = fbsf_keys["Blink"]
    fbsf_mouth = fbsf_keys["MouthOpen"]
    fbsf_other = fbsf_keys["CheekPuff"]
    fbsf_child = fbsf_keys["RelativeToSculpt"]
    assert fbsf_child.relative_key == fbsf_basis_key
    for index in (0, 1):
        assert_position(fbsf_basis_key, index, (x_positions[index], 0.25, 0.0))
    for index in (2, 3):
        assert_position(fbsf_basis_key, index, (x_positions[index], 0.0, 0.5))
    for index in (0, 1):
        assert_position(fbsf_expression, index, (x_positions[index], 1.0, 0.0))
    for index in (2, 3):
        assert_position(fbsf_expression, index, (x_positions[index], 0.0, 1.0))
    for index in (0, 1):
        assert_position(fbsf_mouth, index, (x_positions[index], 0.25, 1.0))
    for index in (2, 3):
        assert_position(fbsf_mouth, index, (x_positions[index], 0.0, 1.5))
    for index in (0, 1):
        assert_position(fbsf_other, index, (x_positions[index] + 0.1, 0.25, 0.0))
    for index in (2, 3):
        assert_position(fbsf_other, index, (x_positions[index] + 0.1, 0.0, 0.5))
    for index in (0, 1):
        assert_position(fbsf_child, index, (x_positions[index] + 0.25, 0.25, 0.0))
    for index in (2, 3):
        assert_position(fbsf_child, index, (x_positions[index] + 0.25, 0.0, 0.5))

    # 未知名称可以通过弹窗的手工功能标签进入眼睛流程。
    manual = make_mesh("FBSFManualTag", vertex_count=2)
    manual.data.vertices[0].co.x = -1.0
    manual.data.vertices[1].co.x = 1.0
    manual_basis = manual.shape_key_add(name="Basis", from_mix=False)
    manual_source = manual.shape_key_add(name="Sculpt", from_mix=False)
    manual_target = manual.shape_key_add(name="CustomExpression", from_mix=False)
    for point in manual_source.data:
        point.co.y += 1.0
    for point in manual_target.data:
        point.co.y += 1.0
    module._rebase_shape_keys_fbsf(
        manual,
        ((manual_source.name, 1.0, 'BOTH_EYES'),),
        1.0,
        0.0,
        ((manual_target.name, 'BOTH_EYES'),),
    )
    for index, x in enumerate((-1.0, 1.0)):
        assert_position(
            manual.data.shape_keys.key_blocks["CustomExpression"],
            index,
            (x, 1.0, 0.0),
        )

    # “合并”与“功能”相互独立：未选键必须保留；其他来源只做全局变基，
    # 即使它与眼睛目标位移完全同向，也不能触发 FBSF 回弹。
    roles = make_mesh("FBSFSourceRoles", vertex_count=2)
    roles.data.vertices[0].co.x = -1.0
    roles.data.vertices[1].co.x = 1.0
    roles_basis = roles.shape_key_add(name="Basis", from_mix=False)
    roles_global = roles.shape_key_add(name="FaceSculpt", from_mix=False)
    roles_unchecked = roles.shape_key_add(name="EyeSculptLeft", from_mix=False)
    roles_blink = roles.shape_key_add(name="Blink", from_mix=False)
    for point in roles_global.data:
        point.co.y += 1.0
    for point in roles_unchecked.data:
        point.co.z += 1.0
    for point in roles_blink.data:
        point.co.y += 1.0
    source_names, *_details = module._rebase_shape_keys_fbsf(
        roles,
        ((roles_global.name, 0.5, 'OTHERS'),),
        1.0,
        0.0,
        (
            (roles_unchecked.name, 'LEFT_EYE'),
            (roles_blink.name, 'BOTH_EYES'),
        ),
    )
    roles_keys = roles.data.shape_keys.key_blocks
    assert source_names == ("FaceSculpt",)
    assert roles_keys.get("FaceSculpt") is None
    assert roles_keys.get("EyeSculptLeft") is not None
    for index, x in enumerate((-1.0, 1.0)):
        assert_position(roles_keys[0], index, (x, 0.5, 0.0))
        assert_position(roles_keys["Blink"], index, (x, 1.5, 0.0))
        assert_position(roles_keys["EyeSculptLeft"], index, (x, 0.5, 1.0))

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


# 覆盖正式注册列表，确保保留 FBSF 并且不再暴露旧 HO 算子。
module.register()
try:
    assert hasattr(bpy.ops.ho, "apply_active_shapekey_to_basis")
    assert hasattr(bpy.ops.ho, "rebase_shapekeys_fbsf")
    assert "rebase_shapekeys_preserve_expressions" not in dir(bpy.ops.ho)
finally:
    module.unregister()


print("SHAPEKEY_REBASE_OK", bpy.app.version_string)
