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
    ROOT
    / "OmniNode"
    / "NodeTree"
    / "Function"
    / "physicsWorld"
    / "mc2"
    / "test"
    / "fixtures"
    / "tier_a"
    / "particle_step_constraints_post_001.json"
)

# The JSON remains the MC2 source oracle. OmniMC2 intentionally uses
# 1 - depth^1.5 for particle inertia instead of the source 1 - depth^2.
OMNI_PRODUCT_POSITIONS_AFTER_POST = np.asarray((
    (
        (0.1, 1.05, -0.05),
        (1.35724556, 0.06563706, -1.15565562),
        (1.26957369, 0.84595281, -0.65183097),
        (2.26655579, 0.87751120, -1.25101995),
    ),
    (
        (0.2, 1.1, -0.1),
        (2.08661151, 0.88325435, -0.84887791),
        (1.96295857, 1.26717103, -0.84934980),
        (3.08432388, 1.91037393, -1.62652421),
    ),
), dtype=np.float32)


def _parameters(values):
    floats = np.zeros(47, dtype=np.float32)
    ints = np.zeros(11, dtype=np.int32)
    curves = np.zeros((9, 16), dtype=np.float32)
    floats[0] = values["gravity"]
    floats[1:4] = values["gravity_direction"]
    floats[4] = values["gravity_falloff"]
    floats[5] = values["stabilization_time_after_reset"]
    floats[6] = values["blend_weight"]
    floats[16] = values["local_inertia"]
    floats[17] = values["local_movement_speed_limit"]
    floats[18] = values["local_rotation_speed_limit"]
    floats[19] = values["depth_inertia"]
    floats[21] = -1.0
    floats[26] = values["distance_velocity_attenuation"]
    floats[27] = values["bending_stiffness"]
    ints[3] = 2
    curves[0, :] = values["damping"]
    curves[2, :] = values["distance_stiffness"]
    return floats, ints, curves


def _axis_angle_y(value):
    half = np.float32(np.radians(value["degrees"]) * 0.5)
    return np.asarray((0.0, np.sin(half), 0.0, np.cos(half)), dtype=np.float32)


def _read_center(context):
    outputs = (
        np.empty(3, dtype=np.float32),
        np.empty(4, dtype=np.float32),
        np.empty(3, dtype=np.float32),
        np.empty(4, dtype=np.float32),
        np.empty(3, dtype=np.float32),
        np.empty(4, dtype=np.float32),
        np.empty(3, dtype=np.float32),
    )
    scalars = hotools_native.mc2_context_v0_read_center_step(context, *outputs)
    return scalars, outputs


def test_particle_frame_matches_omni_product_contract():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    values = fixture["input"]
    expected = fixture["expected"]
    count = len(values["attributes"])
    context = hotools_native.mc2_context_v0_create(0, count)
    try:
        proxy_positions = np.asarray(
            values["initial_particle_positions"], dtype=np.float32
        )
        normals = np.zeros((count, 3), dtype=np.float32)
        normals[:, 2] = 1.0
        tangents = np.zeros((count, 3), dtype=np.float32)
        tangents[:, 0] = 1.0
        uvs = np.zeros((count, 2), dtype=np.float32)
        attributes = np.asarray(values["attributes"], dtype=np.uint8)
        edges = np.asarray(
            ((0, 1), (0, 2), (0, 3), (1, 2), (2, 3)), dtype=np.int32
        )
        triangles = np.asarray(((0, 2, 1), (0, 3, 2)), dtype=np.int32)
        hotools_native.mc2_context_v0_update_proxy_static(
            context,
            proxy_positions,
            normals,
            tangents,
            uvs,
            attributes,
            edges,
            triangles,
        )

        parents = np.asarray((-1, 0, 0, 2), dtype=np.int32)
        child_ranges = np.asarray(((0, 2), (2, 0), (2, 1), (3, 0)), dtype=np.int32)
        child_data = np.asarray((1, 2, 3), dtype=np.int32)
        baseline_flags = np.asarray((0,), dtype=np.uint8)
        baseline_ranges = np.asarray(((0, 4),), dtype=np.int32)
        baseline_data = np.asarray((0, 1, 2, 3), dtype=np.int32)
        roots = np.zeros(count, dtype=np.int32)
        depths = np.asarray(values["depths"], dtype=np.float32)
        local_positions = np.zeros((count, 3), dtype=np.float32)
        local_rotations = np.zeros((count, 4), dtype=np.float32)
        local_rotations[:, 3] = 1.0
        hotools_native.mc2_context_v0_update_baseline_static(
            context,
            parents,
            child_ranges,
            child_data,
            baseline_flags,
            baseline_ranges,
            baseline_data,
            roots,
            depths,
            local_positions,
            local_rotations,
        )
        hotools_native.mc2_context_v0_update_distance_static(
            context,
            np.asarray(values["distance_ranges"], dtype=np.int32),
            np.asarray(values["distance_targets"], dtype=np.int32),
            np.asarray(values["distance_rest_signed"], dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_bending_static(
            context,
            np.asarray(values["bending_ordered_quads"], dtype=np.int32),
            np.asarray(values["bending_rest_angle_or_volume"], dtype=np.float32),
            np.asarray(values["bending_sign_or_volume"], dtype=np.int8),
        )
        hotools_native.mc2_context_v0_update_center_static(
            context,
            np.asarray((0,), dtype=np.int32),
            proxy_positions[0].copy(),
            np.asarray(values["gravity_direction"], dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_parameters(
            context, *_parameters(values)
        )
        hotools_native.mc2_context_v0_update_team_options(context, 1.0)

        rotations = np.zeros((count, 4), dtype=np.float32)
        rotations[:, 3] = 1.0
        old_animated = np.asarray(values["old_animated_positions"], dtype=np.float32)
        current_animated = np.asarray(values["animated_positions"], dtype=np.float32)
        hotools_native.mc2_context_v0_update_dynamic(
            context, 1, 0, old_animated, rotations,
            values["velocity_weight_before_steps"], 1.0, 1.0, 1.0, 0.0,
        )
        hotools_native.mc2_context_v0_reset(context)
        hotools_native.mc2_context_v0_update_dynamic(
            context, 2, 0, current_animated, rotations,
            values["velocity_weight_before_steps"], 1.0, 1.0, 1.0,
            expected["center_frame_interpolations"][0],
        )
        old_rotation = np.asarray(
            values["old_frame_world_rotation_xyzw"], dtype=np.float32
        )
        frame_rotation = _axis_angle_y(values["frame_world_rotation_axis_angle"])
        hotools_native.mc2_context_v0_update_center_dynamic(
            context,
            np.asarray(values["old_frame_world_position"], dtype=np.float32),
            np.asarray(values["frame_world_position"], dtype=np.float32),
            old_rotation,
            frame_rotation,
            np.asarray(values["old_frame_world_scale"], dtype=np.float32),
            np.asarray(values["frame_world_scale"], dtype=np.float32),
            np.asarray(values["old_frame_world_position"], dtype=np.float32),
            old_rotation,
            np.ones(3, dtype=np.float32),
            np.ones(3, dtype=np.float32),
            values["distance_weight"],
            expected["center_frame_interpolations"][0],
            values["velocity_weight_before_steps"],
        )

        out_positions = np.empty((count, 3), dtype=np.float32)
        out_rotations = np.empty((count, 4), dtype=np.float32)
        for step_index in range(values["update_count"]):
            if step_index > 0:
                hotools_native.mc2_context_v0_update_step_interpolation(
                    context, expected["center_frame_interpolations"][step_index]
                )
            hotools_native.mc2_context_v0_step(
                context,
                values["simulation_delta_time"],
                values["simulation_power"][1],
                values["simulation_power"][2],
            )
            hotools_native.mc2_context_v0_read(
                context, out_positions, out_rotations
            )
            source_positions = np.asarray(
                expected["positions_after_post"][step_index], dtype=np.float32
            )
            np.testing.assert_allclose(
                out_positions,
                OMNI_PRODUCT_POSITIONS_AFTER_POST[step_index],
                rtol=1.0e-6,
                atol=2.0e-5,
            )
            np.testing.assert_allclose(
                out_positions[0], source_positions[0], rtol=1.0e-6, atol=2.0e-5
            )
            assert not np.allclose(
                out_positions[1:], source_positions[1:], rtol=1.0e-6, atol=2.0e-5
            )
            scalars, center_outputs = _read_center(context)
            np.testing.assert_allclose(
                scalars["frame_interpolation"],
                expected["center_frame_interpolations"][step_index],
                atol=1.0e-6,
            )
            np.testing.assert_allclose(
                center_outputs[0],
                expected["center_now_world_positions"][step_index],
                rtol=1.0e-6,
                atol=1.0e-6,
            )
            np.testing.assert_allclose(
                center_outputs[4],
                expected["center_inertia_vectors"][step_index],
                rtol=1.0e-6,
                atol=1.0e-6,
            )

        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["step_count"] == 2
        assert info["center_step_count"] == 2
        assert info["particle_prediction_count"] == 2
        assert info["particle_inertia_count"] == 6
        assert info["distance_solve_count"] == 4
        assert info["bending_solve_count"] == 2
    finally:
        hotools_native.mc2_context_v0_free(context)


if __name__ == "__main__":
    test_particle_frame_matches_omni_product_contract()
    print("PASS MC2 native complete particle frame")
