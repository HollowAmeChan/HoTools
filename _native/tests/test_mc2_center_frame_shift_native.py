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


if __name__ == "__main__":
    test_center_frame_shift_transforms_particle_history_and_velocity()
    test_negative_scale_teleport_matches_center_oracle()
    print("PASS MC2 native Center frame shift")
