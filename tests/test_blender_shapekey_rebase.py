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


def make_triangle_mesh(name):
    data = bpy.data.meshes.new(f"{name}Data")
    data.from_pydata(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        [],
        [(0, 1, 2)],
    )
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    activate(obj)
    return obj


def positions(key):
    return np.array([point.co[:] for point in key.data], dtype=np.float32)


def assert_position(key, index, expected):
    actual = np.array(key.data[index].co[:], dtype=np.float32)
    assert np.allclose(actual, expected, atol=1e-6), (key.name, index, actual, expected)


# The smooth mask blends by displacement magnitude, then applies the global
# protection strength. A zero-width falloff remains a strict moved/unmoved mask.
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

# Gradient mode combines normalized motion with a per-triangle polar
# decomposition. Pure translation is retained by motion, while rotation also
# protects a stationary pivot vertex through its incident triangle.
triangle_positions = np.array(
    [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
    dtype=np.float32,
)
triangles = np.array([(0, 1, 2)], dtype=np.int32)
translated_positions = triangle_positions + (2.0, -1.0, 0.5)
translation_activity = module._shape_key_deformation_activity(
    triangle_positions, translated_positions, triangles, 1e-6)
assert np.allclose(translation_activity, 1.0, atol=1e-6)

angle = np.deg2rad(30.0)
rotation = np.array(
    [
        (np.cos(angle), -np.sin(angle), 0.0),
        (np.sin(angle), np.cos(angle), 0.0),
        (0.0, 0.0, 1.0),
    ],
    dtype=np.float32,
)
rotated_positions = triangle_positions @ rotation.T
rotation_activity = module._shape_key_deformation_activity(
    triangle_positions, rotated_positions, triangles, 1e-6)
assert np.allclose(rotation_activity, 1.0, atol=1e-5)
stretched_positions = triangle_positions.copy()
stretched_positions[:, 0] *= 1.5
stretch_activity = module._shape_key_deformation_activity(
    triangle_positions, stretched_positions, triangles, 1e-6)
assert np.allclose(stretch_activity, 1.0, atol=1e-5)
scaled_rotation_activity = module._shape_key_deformation_activity(
    triangle_positions * 100.0, rotated_positions * 100.0, triangles, 1e-4)
assert np.allclose(rotation_activity, scaled_rotation_activity, atol=1e-5)

unchanged_mask = module._shape_key_gradient_rebase_mask(
    triangle_positions, triangle_positions, triangles,
    1e-6, 0.1, 0.2, 1.0)
assert np.allclose(unchanged_mask, 0.0, atol=1e-6)

degenerate_positions = np.array(
    [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
    dtype=np.float32,
)
degenerate_key = degenerate_positions.copy()
degenerate_key[1, 1] = 0.5
degenerate_activity = module._shape_key_deformation_activity(
    degenerate_positions, degenerate_key, triangles, 1e-6)
assert np.all(np.isfinite(degenerate_activity))


registered = (
    module.OP_ShapekeyTools_Apply_ActiveShapekey2Basis,
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

    # Expression vertices above the threshold retain their old absolute target.
    assert_position(expression, 0, (0.0, 0.0, 1.0))
    assert_position(expression, 1, (1.0, 0.5, 0.0))
    assert_position(expression, 2, (2.0, 0.5, 0.05))
    assert_position(expression, 3, (3.0, 0.0, 2.0))
    assert_position(expression, 4, (4.0, 0.5, 0.0))

    # A nested key follows its rewritten relative key where its own local delta is zero.
    assert_position(nested, 0, (0.0, 0.0, 1.0))
    assert_position(nested, 1, (1.5, 0.0, 0.0))
    assert_position(nested, 2, (2.0, 0.5, 0.05))

    # Children of the removed sculpt key are safely re-parented to the new Basis.
    assert_position(active_child, 0, (0.0, 0.5, 0.0))
    assert_position(active_child, 4, (4.0, 1.0, 0.5))

    # A zero-displacement rotation pivot is protected by the incident face's
    # polar rotation instead of following the newly raised Basis.
    gradient_obj = make_triangle_mesh("GradientLocalRebase")
    gradient_basis = gradient_obj.shape_key_add(name="Basis", from_mix=False)
    gradient_sculpt = gradient_obj.shape_key_add(name="FaceSculpt", from_mix=False)
    for point in gradient_sculpt.data:
        point.co.z += 1.0
    gradient_expression = gradient_obj.shape_key_add(name="RotatedExpression", from_mix=False)
    for index, point in enumerate(gradient_expression.data):
        point.co = rotated_positions[index]

    gradient_obj.active_shape_key_index = 1
    result = bpy.ops.ho.rebase_shapekeys_preserve_expressions(
        "EXEC_DEFAULT",
        factor=1.0,
        movement_threshold=1e-6,
        protection_strength=1.0,
        use_gradient_rebase=True,
        gradient_threshold=0.1,
        gradient_softness=0.2,
    )
    assert result == {'FINISHED'}
    gradient_keys = gradient_obj.data.shape_keys.key_blocks
    assert_position(gradient_keys[0], 0, (0.0, 0.0, 1.0))
    assert_position(gradient_keys["RotatedExpression"], 0, (0.0, 0.0, 0.0))

    # Preconditions reject unsafe state without changing stored coordinates.
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

    # The pre-existing operator remains independent and keeps its original behavior.
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


# Exercise the production registration list so both independently named operators
# stay available through normal add-on registration.
module.register()
try:
    assert hasattr(bpy.ops.ho, "apply_active_shapekey_to_basis")
    assert hasattr(bpy.ops.ho, "rebase_shapekeys_preserve_expressions")
finally:
    module.unregister()


print("SHAPEKEY_REBASE_OK", bpy.app.version_string)
