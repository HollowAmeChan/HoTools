import json
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


FIXTURE = (
    ROOT / "OmniNode" / "NodeTree" / "Function" / "physicsWorld" / "mc2"
    / "test" / "fixtures" / "tier_a" / "center_frame_shift_skip_count_001.json"
)


def _read_center(context):
    now_position = np.empty(3, dtype=np.float32)
    now_rotation = np.empty(4, dtype=np.float32)
    step_vector = np.empty(3, dtype=np.float32)
    step_rotation = np.empty(4, dtype=np.float32)
    inertia_vector = np.empty(3, dtype=np.float32)
    inertia_rotation = np.empty(4, dtype=np.float32)
    rotation_axis = np.empty(3, dtype=np.float32)
    values = hotools_native.mc2_context_v0_read_center_step(
        context,
        now_position,
        now_rotation,
        step_vector,
        step_rotation,
        inertia_vector,
        inertia_rotation,
        rotation_axis,
    )
    return now_position.copy(), step_vector.copy(), values


def test_step_interpolation_reuses_one_center_frame():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    values = fixture["input"]
    ratios = fixture["expected"]["step_frame_interpolations"]
    context = hotools_native.mc2_context_v0_create(0, 1)
    identity = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    zero = np.zeros(3, dtype=np.float32)
    one = np.ones(3, dtype=np.float32)
    try:
        hotools_native.mc2_context_v0_update_proxy_static(
            context,
            np.zeros((1, 3), dtype=np.float32),
            np.asarray(((0.0, 0.0, 1.0),), dtype=np.float32),
            np.asarray(((1.0, 0.0, 0.0),), dtype=np.float32),
            np.zeros((1, 2), dtype=np.float32),
            np.asarray((1,), dtype=np.uint8),
            np.empty((0, 2), dtype=np.int32),
            np.empty((0, 3), dtype=np.int32),
        )
        hotools_native.mc2_context_v0_update_baseline_static(
            context,
            np.asarray((-1,), dtype=np.int32),
            np.asarray(((0, 0),), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.uint8),
            np.empty((0, 2), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
            np.asarray((0,), dtype=np.int32),
            np.asarray((0.0,), dtype=np.float32),
            np.zeros((1, 3), dtype=np.float32),
            identity.reshape((1, 4)),
        )
        hotools_native.mc2_context_v0_update_distance_static(
            context,
            np.asarray(((0, 0),), dtype=np.int32),
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
            np.asarray((0,), dtype=np.int32),
            zero,
            np.asarray((0.0, -1.0, 0.0), dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_parameters(
            context,
            np.zeros(47, dtype=np.float32),
            np.zeros(11, dtype=np.int32),
            np.zeros((9, 16), dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_team_options(context, 1.0)
        start_positions = np.zeros((1, 3), dtype=np.float32)
        rotations = identity.reshape((1, 4))
        hotools_native.mc2_context_v0_update_dynamic(
            context, 1, 0, start_positions, rotations,
            1.0, 1.0, 1.0, 1.0, 1.0
        )
        hotools_native.mc2_context_v0_reset(context)
        end_positions = np.asarray(((9.0, 0.0, 0.0),), dtype=np.float32)
        hotools_native.mc2_context_v0_update_dynamic(
            context, 2, 0, end_positions, rotations,
            1.0, 1.0, 1.0, 1.0, 1.0
        )
        try:
            hotools_native.mc2_context_v0_update_step_interpolation(
                context, ratios[0]
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("step interpolation reused a stale Center frame")

        first_position = np.asarray((9.0, 0.0, 0.0), dtype=np.float32)
        hotools_native.mc2_context_v0_update_center_dynamic(
            context,
            zero,
            first_position,
            identity,
            identity,
            one,
            one,
            zero,
            identity,
            one,
            one,
            1.0,
            ratios[0],
            1.0,
        )
        step_positions = np.empty((1, 3), dtype=np.float32)
        step_rotations = np.empty((1, 4), dtype=np.float32)
        for index, ratio in enumerate(ratios):
            if index > 0:
                hotools_native.mc2_context_v0_update_step_interpolation(
                    context, ratio
                )
            hotools_native.mc2_context_v0_step(
                context,
                values["simulation_delta_time"],
                1.0,
                1.0,
            )
            hotools_native.mc2_context_v0_read_step_basic(
                context, step_positions, step_rotations
            )
            expected_position = np.asarray(
                (9.0 * ratio, 0.0, 0.0), dtype=np.float32
            )
            np.testing.assert_allclose(
                step_positions[0], expected_position, rtol=1.0e-6, atol=1.0e-6
            )
            center_position, step_vector, scalar = _read_center(context)
            np.testing.assert_allclose(
                center_position, expected_position, rtol=1.0e-6, atol=1.0e-6
            )
            np.testing.assert_allclose(
                step_vector, (3.0, 0.0, 0.0), rtol=1.0e-6, atol=1.0e-6
            )
            np.testing.assert_allclose(
                scalar["frame_interpolation"], ratio, rtol=1.0e-6, atol=1.0e-6
            )

        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["center_dynamic_revision"] == 1
        assert info["step_interpolation_revision"] == 2
        assert info["center_step_count"] == 3
        assert info["step_count"] == 3
        assert info["center_frame_ready"] is True
    finally:
        hotools_native.mc2_context_v0_free(context)


if __name__ == "__main__":
    test_step_interpolation_reuses_one_center_frame()
    print("PASS MC2 native step interpolation")
