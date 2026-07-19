import os
import json
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(
    0,
    os.environ.get(
        "HOTOOLS_NATIVE_TEST_DIR",
        str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage"),
    ),
)

import hotools_native  # noqa: E402


def _proxy_static():
    return (
        np.zeros((1, 3), dtype=np.float32),
        np.array([[0.0, 0.0, 1.0]], dtype=np.float32),
        np.array([[1.0, 0.0, 0.0]], dtype=np.float32),
        np.zeros((1, 2), dtype=np.float32),
        np.array([2], dtype=np.uint8),
        np.empty((0, 2), dtype=np.int32),
        np.empty((0, 3), dtype=np.int32),
    )


def _baseline_static():
    return (
        np.array([-1], dtype=np.int32),
        np.array([[0, 0]], dtype=np.int32),
        np.empty((0,), dtype=np.int32),
        np.array([0], dtype=np.uint8),
        np.array([[0, 1]], dtype=np.int32),
        np.array([0], dtype=np.int32),
        np.array([0], dtype=np.int32),
        np.array([0.5], dtype=np.float32),
        np.zeros((1, 3), dtype=np.float32),
        np.array([[0.0, 0.0, 0.0, 1.0]], dtype=np.float32),
    )


def _update_dynamic(context, frame, positions, rotations):
    hotools_native.mc2_context_v0_update_dynamic(
        context,
        frame,
        0,
        positions,
        rotations,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
    )


def _read(context):
    positions = np.empty((1, 3), dtype=np.float32)
    rotations = np.empty((1, 4), dtype=np.float32)
    hotools_native.mc2_context_v0_read(context, positions, rotations)
    return positions, rotations


def _read_many(context, count):
    positions = np.empty((count, 3), dtype=np.float32)
    rotations = np.empty((count, 4), dtype=np.float32)
    hotools_native.mc2_context_v0_read(context, positions, rotations)
    return positions, rotations


def _particle_context(
    count, *, mode, distance=0.5, rotation=180.0, gravity=0.0,
    fixed_indices=(0,),
):
    context = hotools_native.mc2_context_v0_create(0, count)
    positions, normals, tangents, uvs, attributes, _edges, _triangles = _proxy_static()
    proxy_attributes = np.repeat(attributes, count, axis=0)
    if fixed_indices:
        proxy_attributes[np.asarray(fixed_indices, dtype=np.intp)] = np.uint8(1)
    hotools_native.mc2_context_v0_update_proxy_static(
        context,
        np.repeat(positions, count, axis=0),
        np.repeat(normals, count, axis=0),
        np.repeat(tangents, count, axis=0),
        np.repeat(uvs, count, axis=0),
        proxy_attributes,
        np.empty((0, 2), dtype=np.int32),
        np.empty((0, 3), dtype=np.int32),
    )
    hotools_native.mc2_context_v0_update_baseline_static(
        context,
        np.arange(-1, count - 1, dtype=np.int32),
        np.array(
            [[index, 1 if index + 1 < count else 0] for index in range(count)],
            dtype=np.int32,
        ),
        np.arange(1, count, dtype=np.int32),
        np.array([0], dtype=np.uint8),
        np.array([[0, count]], dtype=np.int32),
        np.arange(count, dtype=np.int32),
        np.zeros(count, dtype=np.int32),
        np.linspace(0.0, 1.0, count, dtype=np.float32),
        np.zeros((count, 3), dtype=np.float32),
        np.repeat(
            np.array([[0.0, 0.0, 0.0, 1.0]], dtype=np.float32),
            count,
            axis=0,
        ),
    )
    hotools_native.mc2_context_v0_update_distance_static(
        context,
        np.zeros((count, 2), dtype=np.int32),
        np.empty((0,), dtype=np.int32),
        np.empty((0,), dtype=np.float32),
    )
    hotools_native.mc2_context_v0_update_bending_static(
        context,
        np.empty((0, 4), dtype=np.int32),
        np.empty((0,), dtype=np.float32),
        np.empty((0,), dtype=np.int8),
    )
    hotools_native.mc2_context_v0_update_center_static(
        context,
        np.asarray(fixed_indices, dtype=np.int32),
        np.zeros(3, dtype=np.float32),
        np.asarray((0.0, -1.0, 0.0), dtype=np.float32),
    )
    floats = np.zeros(47, dtype=np.float32)
    floats[0] = gravity
    floats[2] = 1.0
    floats[22] = distance
    floats[23] = rotation
    ints = np.zeros(11, dtype=np.int32)
    ints[2] = mode
    hotools_native.mc2_context_v0_update_parameters(
        context,
        floats,
        ints,
        np.zeros((9, 16), dtype=np.float32),
    )
    return context


def _bone_particle_context(*, mode):
    count = 5
    context = hotools_native.mc2_context_v0_create(0, count)
    hotools_native.mc2_context_v0_set_setup_kind(context, 1)
    positions, normals, tangents, uvs, _attributes, _edges, _triangles = (
        _proxy_static()
    )
    hotools_native.mc2_context_v0_update_proxy_static(
        context,
        np.repeat(positions, count, axis=0),
        np.repeat(normals, count, axis=0),
        np.repeat(tangents, count, axis=0),
        np.repeat(uvs, count, axis=0),
        np.array([1, 2, 2, 1, 2], dtype=np.uint8),
        np.empty((0, 2), dtype=np.int32),
        np.empty((0, 3), dtype=np.int32),
    )
    hotools_native.mc2_context_v0_update_baseline_static(
        context,
        np.array([-1, 0, 1, -1, 3], dtype=np.int32),
        np.zeros((count, 2), dtype=np.int32),
        np.empty((0,), dtype=np.int32),
        np.empty((0,), dtype=np.uint8),
        np.empty((0, 2), dtype=np.int32),
        np.empty((0,), dtype=np.int32),
        np.array([-1, 0, 0, -1, 3], dtype=np.int32),
        np.zeros((count,), dtype=np.float32),
        np.zeros((count, 3), dtype=np.float32),
        np.repeat(
            np.array([[0.0, 0.0, 0.0, 1.0]], dtype=np.float32),
            count,
            axis=0,
        ),
    )
    floats = np.zeros(47, dtype=np.float32)
    floats[22] = 0.5
    floats[23] = 180.0
    ints = np.zeros(11, dtype=np.int32)
    ints[2] = mode
    hotools_native.mc2_context_v0_update_parameters(
        context,
        floats,
        ints,
        np.zeros((9, 16), dtype=np.float32),
    )
    hotools_native.mc2_context_v0_update_center_static(
        context,
        np.asarray((0, 3), dtype=np.int32),
        np.zeros(3, dtype=np.float32),
        np.asarray((0.0, -1.0, 0.0), dtype=np.float32),
    )
    return context


def _axis_angle(value):
    axis = np.asarray(value["axis"], dtype=np.float32)
    half_angle = np.float32(np.radians(value["degrees"]) * 0.5)
    return np.concatenate((
        axis * np.sin(half_angle),
        np.asarray((np.cos(half_angle),), dtype=np.float32),
    )).astype(np.float32)


def test_center_frame_shift_transforms_particle_history_and_velocity():
    context = hotools_native.mc2_context_v0_create(0, 1)
    try:
        hotools_native.mc2_context_v0_update_proxy_static(context, *_proxy_static())
        hotools_native.mc2_context_v0_update_baseline_static(context, *_baseline_static())
        floats = np.zeros(47, dtype=np.float32)
        floats[0] = 1.0
        floats[1] = 1.0
        curves = np.zeros((9, 16), dtype=np.float32)
        hotools_native.mc2_context_v0_update_parameters(
            context,
            floats,
            np.zeros(11, dtype=np.int32),
            curves,
        )
        positions = np.zeros((1, 3), dtype=np.float32)
        rotations = np.array([[0.0, 0.0, 0.0, 1.0]], dtype=np.float32)
        _update_dynamic(context, 1, positions, rotations)
        hotools_native.mc2_context_v0_reset(context)
        hotools_native.mc2_context_v0_step(context, 1.0, 1.0, 1.0)
        np.testing.assert_allclose(_read(context)[0], [[1.0, 0.0, 0.0]], atol=1.0e-6)

        half_angle = np.float32(np.pi * 0.25)
        shift_rotation = np.array(
            [0.0, np.sin(half_angle), 0.0, np.cos(half_angle)],
            dtype=np.float32,
        )
        bad_rotation = np.zeros(4, dtype=np.float32)
        before = _read(context)
        try:
            hotools_native.mc2_context_v0_apply_center_frame_shift(
                context,
                np.zeros(3, dtype=np.float32),
                np.zeros(3, dtype=np.float32),
                bad_rotation,
            )
        except ValueError as exc:
            assert "unit quaternion" in str(exc)
        else:
            raise AssertionError("invalid Center shift rotation was accepted")
        after_bad = _read(context)
        np.testing.assert_array_equal(after_bad[0], before[0])
        np.testing.assert_array_equal(after_bad[1], before[1])

        hotools_native.mc2_context_v0_apply_center_frame_shift(
            context,
            np.zeros(3, dtype=np.float32),
            np.zeros(3, dtype=np.float32),
            shift_rotation,
        )
        shifted_positions, shifted_rotations = _read(context)
        np.testing.assert_allclose(shifted_positions, [[0.0, 0.0, -1.0]], atol=1.0e-6)
        np.testing.assert_allclose(shifted_rotations, [shift_rotation], atol=1.0e-6)
        assert hotools_native.mc2_context_v0_inspect(context)["center_frame_shift_count"] == 1

        floats[0:4] = 0.0
        hotools_native.mc2_context_v0_update_parameters(
            context,
            floats,
            np.zeros(11, dtype=np.int32),
            curves,
        )
        _update_dynamic(context, 2, positions, rotations)
        hotools_native.mc2_context_v0_step(context, 1.0, 1.0, 1.0)
        final_positions, _final_rotations = _read(context)
        np.testing.assert_allclose(final_positions, [[0.0, 0.0, -2.0]], atol=1.0e-6)
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_negative_scale_teleport_matches_center_oracle():
    fixture_path = (
        ROOT
        / "OmniNode" / "NodeTree" / "Function" / "physicsWorld" / "mc2"
        / "test" / "fixtures" / "tier_a"
        / "center_frame_shift_negative_scale_x_001.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    values = fixture["input"]
    expected = fixture["expected"]
    matrix = np.asarray(
        expected["negative_scale_matrix_columns"], dtype=np.float32
    ).T.copy()
    initial_position = np.asarray(values["old_position"], dtype=np.float32)
    initial_velocity = np.asarray(values["velocity"], dtype=np.float32)
    initial_rotation = _axis_angle(values["old_rotation_axis_angle"])

    context = hotools_native.mc2_context_v0_create(0, 1)
    try:
        hotools_native.mc2_context_v0_update_proxy_static(context, *_proxy_static())
        hotools_native.mc2_context_v0_update_baseline_static(context, *_baseline_static())
        floats = np.zeros(47, dtype=np.float32)
        floats[0] = 1.0
        floats[1:4] = initial_velocity
        curves = np.zeros((9, 16), dtype=np.float32)
        hotools_native.mc2_context_v0_update_parameters(
            context, floats, np.zeros(11, dtype=np.int32), curves
        )
        positions = np.asarray(
            [initial_position - initial_velocity], dtype=np.float32
        )
        rotations = np.asarray([initial_rotation], dtype=np.float32)
        _update_dynamic(context, 1, positions, rotations)
        hotools_native.mc2_context_v0_reset(context)
        hotools_native.mc2_context_v0_step(context, 1.0, 1.0, 1.0)
        np.testing.assert_allclose(_read(context)[0], [initial_position], atol=1.0e-6)

        hotools_native.mc2_context_v0_apply_center_negative_scale_teleport(
            context, matrix
        )
        teleported_position, teleported_rotation = _read(context)
        np.testing.assert_allclose(
            teleported_position, [expected["old_position"]], rtol=1.0e-6, atol=1.0e-6
        )
        expected_rotation = np.asarray(expected["old_rotation_xyzw"], dtype=np.float32)
        if np.dot(teleported_rotation[0], expected_rotation) < 0.0:
            teleported_rotation[0] *= -1.0
        np.testing.assert_allclose(
            teleported_rotation, [expected_rotation], rtol=1.0e-6, atol=1.0e-6
        )
        assert hotools_native.mc2_context_v0_inspect(context)[
            "center_negative_scale_teleport_count"
        ] == 1

        floats[0:4] = 0.0
        hotools_native.mc2_context_v0_update_parameters(
            context, floats, np.zeros(11, dtype=np.int32), curves
        )
        _update_dynamic(context, 2, positions, rotations)
        hotools_native.mc2_context_v0_step(context, 1.0, 1.0, 1.0)
        final_position, _ = _read(context)
        np.testing.assert_allclose(
            final_position,
            [
                np.asarray(expected["old_position"], dtype=np.float32)
                + np.asarray(expected["velocity"], dtype=np.float32)
            ],
            rtol=1.0e-6,
            atol=2.0e-6,
        )
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_task_keep_uses_first_fixed_and_transforms_every_particle():
    count = 3
    context = _particle_context(count, mode=2, gravity=1.0)
    identity = np.repeat(
        np.array([[0.0, 0.0, 0.0, 1.0]], dtype=np.float32),
        count,
        axis=0,
    )
    initial = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
        dtype=np.float32,
    )
    try:
        _update_dynamic(context, 1, initial, identity)
        hotools_native.mc2_context_v0_reset(context)
        hotools_native.mc2_context_v0_apply_center_frame_shift(
            context,
            np.zeros(3, dtype=np.float32),
            np.array([0.0, 0.25, 0.0], dtype=np.float32),
            np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32),
        )
        before_positions, _before_rotations = _read_many(context, count)
        current = initial.copy()
        current[0, 0] += 2.0
        current[1, 0] -= 5.0
        current[2, 0] += 0.1
        _update_dynamic(context, 2, current, identity)
        result = hotools_native.mc2_context_v0_apply_task_teleport(context)
        assert result["mode"] == 2
        assert result["trigger_count"] == count
        assert result["particle_count"] == count
        assert result["applied"] is True
        assert result["reference_kind"] == "first_fixed"
        assert result["reference_index"] == 0
        assert result["measured_distance"] == 2.0
        assert result["measured_rotation_degrees"] == 0.0
        positions, rotations = _read_many(context, count)
        expected_positions = before_positions + np.array([2.0, 0.0, 0.0], dtype=np.float32)
        np.testing.assert_allclose(positions, expected_positions, atol=1.0e-6)
        np.testing.assert_array_equal(rotations, identity)
        repeated = hotools_native.mc2_context_v0_apply_task_teleport(context)
        assert repeated == result
        assert hotools_native.mc2_context_v0_inspect(context)[
            "particle_teleport_apply_count"
        ] == 1
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_task_reset_uses_first_fixed_rotation_and_resets_every_particle():
    count = 2
    context = _particle_context(count, mode=1, distance=10.0, rotation=30.0)
    identity = np.repeat(
        np.array([[0.0, 0.0, 0.0, 1.0]], dtype=np.float32),
        count,
        axis=0,
    )
    initial = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32
    )
    try:
        _update_dynamic(context, 1, initial, identity)
        hotools_native.mc2_context_v0_reset(context)
        hotools_native.mc2_context_v0_apply_center_frame_shift(
            context,
            np.zeros(3, dtype=np.float32),
            np.array([0.0, 0.5, 0.0], dtype=np.float32),
            np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32),
        )
        current_rotations = identity.copy()
        half_angle = np.float32(np.pi * 0.25)
        current_rotations[0] = (
            0.0,
            0.0,
            np.sin(half_angle),
            np.cos(half_angle),
        )
        _update_dynamic(context, 2, initial, current_rotations)
        result = hotools_native.mc2_context_v0_apply_task_teleport(context)
        assert result["mode"] == 1
        assert result["trigger_count"] == count
        assert result["applied"] is True
        assert result["reference_kind"] == "first_fixed"
        assert result["reference_index"] == 0
        assert abs(result["measured_rotation_degrees"] - 90.0) <= 1.0e-4
        positions_before_reset, _ = _read_many(context, count)
        np.testing.assert_allclose(
            positions_before_reset,
            [[0.0, 0.5, 0.0], [1.0, 0.5, 0.0]],
            atol=1.0e-6,
        )
        hotools_native.mc2_context_v0_reset(context)
        positions, rotations = _read_many(context, count)
        np.testing.assert_allclose(
            positions,
            initial,
            atol=1.0e-6,
        )
        np.testing.assert_allclose(rotations[0], current_rotations[0], atol=1.0e-6)
        np.testing.assert_allclose(rotations[1], identity[1], atol=1.0e-6)
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["particle_teleport_trigger_count"] == 1
        assert info["particle_teleport_mode"] == 1
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_bone_task_teleport_uses_first_fixed_not_other_branches():
    count = 5
    identity = np.repeat(
        np.array([[0.0, 0.0, 0.0, 1.0]], dtype=np.float32),
        count,
        axis=0,
    )
    initial = np.array(
        [
            [0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 2.0, 0.0],
            [10.0, 0.0, 0.0],
            [10.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    context = _bone_particle_context(mode=2)
    try:
        _update_dynamic(context, 1, initial, identity)
        hotools_native.mc2_context_v0_reset(context)
        other_branch = initial.copy()
        other_branch[3:, 0] += 3.0
        _update_dynamic(context, 2, other_branch, identity)
        ignored = hotools_native.mc2_context_v0_apply_task_teleport(context)
        assert ignored["reference_kind"] == "first_fixed"
        assert ignored["reference_index"] == 0
        assert ignored["applied"] is False

        before, _ = _read_many(context, count)
        current = other_branch.copy()
        current[:3, 0] += 2.0
        _update_dynamic(context, 3, current, identity)
        result = hotools_native.mc2_context_v0_apply_task_teleport(context)
        assert result["applied"] is True
        assert result["trigger_count"] == count
        positions, _ = _read_many(context, count)
        np.testing.assert_allclose(
            positions,
            before + np.array([2.0, 0.0, 0.0], dtype=np.float32),
            atol=1.0e-6,
        )
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_task_teleport_returns_one_reference_without_particle_debug_arrays():
    count = 2
    context = _particle_context(count, mode=1)
    identity = np.repeat(
        np.array([[0.0, 0.0, 0.0, 1.0]], dtype=np.float32),
        count,
        axis=0,
    )
    initial = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32
    )
    try:
        _update_dynamic(context, 1, initial, identity)
        hotools_native.mc2_context_v0_reset(context)
        current = initial.copy()
        current[0, 0] += 2.0
        _update_dynamic(context, 2, current, identity)
        result = hotools_native.mc2_context_v0_apply_task_teleport(context)
        assert result["trigger_count"] == count
        assert result["reference_kind"] == "first_fixed"
        assert result["reference_index"] == 0
        np.testing.assert_allclose(result["old_reference_position"], initial[0])
        np.testing.assert_allclose(result["reference_position"], current[0])
        assert hotools_native.mc2_context_v0_inspect(context)[
            "particle_teleport_apply_count"
        ] == 1
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_task_teleport_falls_back_to_object_origin_without_fixed_particles():
    count = 2
    context = _particle_context(count, mode=1, fixed_indices=())
    positions = np.asarray(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)), dtype=np.float32
    )
    rotations = np.repeat(
        np.asarray(((0.0, 0.0, 0.0, 1.0),), dtype=np.float32),
        count,
        axis=0,
    )
    component_rotation = np.asarray(
        ((0.0, 0.0, 0.0, 1.0),), dtype=np.float32
    )
    component_scale = np.ones(3, dtype=np.float32)
    try:
        _update_dynamic(context, 1, positions, rotations)
        hotools_native.mc2_context_v0_derive_center_pose_raw(
            context,
            np.zeros(3, dtype=np.float32),
            component_rotation,
            component_scale,
        )
        hotools_native.mc2_context_v0_reset(context)
        _update_dynamic(context, 2, positions, rotations)
        hotools_native.mc2_context_v0_derive_center_pose_raw(
            context,
            np.asarray((2.0, 0.0, 0.0), dtype=np.float32),
            component_rotation,
            component_scale,
        )
        result = hotools_native.mc2_context_v0_apply_task_teleport(context)
        assert result["applied"] is True
        assert result["reference_kind"] == "object_origin"
        assert result["reference_index"] == -1
        assert result["measured_distance"] == 2.0
    finally:
        hotools_native.mc2_context_v0_free(context)


if __name__ == "__main__":
    test_center_frame_shift_transforms_particle_history_and_velocity()
    test_negative_scale_teleport_matches_center_oracle()
    test_task_keep_uses_first_fixed_and_transforms_every_particle()
    test_task_reset_uses_first_fixed_rotation_and_resets_every_particle()
    test_bone_task_teleport_uses_first_fixed_not_other_branches()
    test_task_teleport_returns_one_reference_without_particle_debug_arrays()
    test_task_teleport_falls_back_to_object_origin_without_fixed_particles()
    print("PASS MC2 native Center frame shift")
