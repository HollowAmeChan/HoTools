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
    / "test" / "fixtures" / "tier_a" / "particle_step_baseline_pose_001.json"
)


def _axis_angle(value):
    if value is None:
        return np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    axis = np.asarray(value["axis"], dtype=np.float32)
    half_angle = np.float32(np.radians(value["degrees"]) * 0.5)
    return np.asarray(
        tuple(axis * np.sin(half_angle)) + (np.cos(half_angle),),
        dtype=np.float32,
    )


def _update_center(context, values, *, frame_interpolation=1.0):
    identity = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    zero = np.zeros(3, dtype=np.float32)
    initial_scale = np.asarray(values["initial_scale"], dtype=np.float32)
    hotools_native.mc2_context_v0_update_center_dynamic(
        context,
        zero,
        zero,
        identity,
        identity,
        initial_scale * np.float32(values["scale_ratio"]),
        initial_scale * np.float32(values["scale_ratio"]),
        zero,
        identity,
        initial_scale,
        np.asarray(values["negative_scale_direction"], dtype=np.float32),
        1.0,
        frame_interpolation,
        1.0,
    )


def test_baseline_step_pose_matches_fixed_oracle():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    values = fixture["input"]
    expected = fixture["expected"]
    count = len(values["attributes"])
    context = hotools_native.mc2_context_v0_create(0, count)
    try:
        positions = np.zeros((count, 3), dtype=np.float32)
        normals = np.zeros((count, 3), dtype=np.float32)
        normals[:, 2] = 1.0
        tangents = np.zeros((count, 3), dtype=np.float32)
        tangents[:, 0] = 1.0
        hotools_native.mc2_context_v0_update_proxy_static(
            context,
            positions,
            normals,
            tangents,
            np.zeros((count, 2), dtype=np.float32),
            np.asarray(values["attributes"], dtype=np.uint8),
            np.empty((0, 2), dtype=np.int32),
            np.empty((0, 3), dtype=np.int32),
        )
        local_rotations = np.asarray(
            [_axis_angle(value) for value in values["vertex_local_rotation_axis_angles"]],
            dtype=np.float32,
        )
        hotools_native.mc2_context_v0_update_baseline_static(
            context,
            np.asarray(values["parent_indices"], dtype=np.int32),
            np.asarray(((0, 1), (1, 1), (2, 0), (2, 0)), dtype=np.int32),
            np.asarray((1, 2), dtype=np.int32),
            np.asarray((0,), dtype=np.uint8),
            np.asarray(values["baseline_ranges"], dtype=np.int32),
            np.asarray(values["baseline_data"], dtype=np.int32),
            np.asarray((0, 0, 0, 3), dtype=np.int32),
            np.asarray((0.0, 0.5, 1.0, 0.0), dtype=np.float32),
            np.asarray(values["vertex_local_positions"], dtype=np.float32),
            local_rotations,
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
            np.asarray((0,), dtype=np.int32),
            np.zeros(3, dtype=np.float32),
            np.asarray((0.0, -1.0, 0.0), dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_parameters(
            context,
            np.zeros(47, dtype=np.float32),
            np.zeros(11, dtype=np.int32),
            np.zeros((9, 16), dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_team_options(
            context, values["animation_pose_ratio"]
        )
        base_positions = np.asarray(values["base_positions"], dtype=np.float32)
        base_rotations = np.asarray(
            [_axis_angle(value) for value in values["base_rotation_axis_angles"]],
            dtype=np.float32,
        )
        hotools_native.mc2_context_v0_update_dynamic(
            context,
            1,
            0,
            base_positions,
            base_rotations,
            1.0,
            1.0,
            values["scale_ratio"],
            1.0,
            1.0,
        )
        hotools_native.mc2_context_v0_reset(context)
        _update_center(context, values)
        hotools_native.mc2_context_v0_step(context, 1.0 / 60.0, 1.0, 1.0)
        step_positions = np.empty_like(base_positions)
        step_rotations = np.empty_like(base_rotations)
        hotools_native.mc2_context_v0_read_step_basic(
            context, step_positions, step_rotations
        )
        np.testing.assert_allclose(
            step_positions,
            expected["step_basic_positions"],
            rtol=1.0e-6,
            atol=1.0e-6,
        )
        expected_rotations = np.asarray(
            expected["step_basic_rotations_xyzw"], dtype=np.float32
        )
        for index in range(count):
            if np.dot(step_rotations[index], expected_rotations[index]) < 0.0:
                step_rotations[index] *= -1.0
        np.testing.assert_allclose(
            step_rotations, expected_rotations, rtol=1.0e-6, atol=1.0e-6
        )
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["baseline_pose_rebuild_count"] == 1
        assert info["team_options_revision"] == 1
        assert info["animation_pose_ratio"] == values["animation_pose_ratio"]

        shifted_positions = base_positions + np.asarray(
            (4.0, 0.0, 0.0), dtype=np.float32
        )
        hotools_native.mc2_context_v0_update_dynamic(
            context, 2, 0, shifted_positions, base_rotations, 1.0, 0.25,
            values["scale_ratio"], 1.0, 1.0
        )
        _update_center(context, values, frame_interpolation=0.25)
        hotools_native.mc2_context_v0_step(context, 1.0 / 60.0, 1.0, 1.0)
        hotools_native.mc2_context_v0_read_step_basic(
            context, step_positions, step_rotations
        )
        interpolated_expected = np.asarray(
            expected["step_basic_positions"], dtype=np.float32
        ) + np.asarray((1.0, 0.0, 0.0), dtype=np.float32)
        np.testing.assert_allclose(
            step_positions, interpolated_expected, rtol=1.0e-6, atol=1.0e-6
        )
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["baseline_pose_rebuild_count"] == 2

        hotools_native.mc2_context_v0_update_team_options(context, 1.0)
        hotools_native.mc2_context_v0_update_dynamic(
            context, 3, 0, shifted_positions, base_rotations, 1.0, 1.0,
            values["scale_ratio"], 1.0, 1.0
        )
        _update_center(context, values)
        hotools_native.mc2_context_v0_step(context, 1.0 / 60.0, 1.0, 1.0)
        hotools_native.mc2_context_v0_read_step_basic(
            context, step_positions, step_rotations
        )
        np.testing.assert_allclose(step_positions, shifted_positions, atol=1.0e-6)
        for index in range(count):
            if np.dot(step_rotations[index], base_rotations[index]) < 0.0:
                step_rotations[index] *= -1.0
        np.testing.assert_allclose(step_rotations, base_rotations, atol=1.0e-6)
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["baseline_pose_rebuild_count"] == 2
        assert info["team_options_revision"] == 2
    finally:
        hotools_native.mc2_context_v0_free(context)


if __name__ == "__main__":
    test_baseline_step_pose_matches_fixed_oracle()
    print("PASS MC2 native baseline step pose")
