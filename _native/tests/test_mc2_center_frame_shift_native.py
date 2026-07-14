import os
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


if __name__ == "__main__":
    test_center_frame_shift_transforms_particle_history_and_velocity()
    print("PASS MC2 native Center frame shift")
