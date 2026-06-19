import os
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, os.environ.get("HOTOOLS_NATIVE_TEST_DIR", str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage")))

import hotools_native  # noqa: E402


EPSILON = 0.00000001
MC2_ATTR_FIXED = 1 << 1
MC2_ATTR_MOVE = 1 << 2
MC2_ATTR_MOTION = 1 << 3
DISTANCE_VELOCITY_ATTENUATION = 0.3
ANGLE_RESTORATION_VELOCITY_ATTENUATION = 0.8
ANGLE_RESTORATION_GRAVITY_FALLOFF = 0.0
MAX_DISTANCE_RATIO_FUTURE_PREDICTION = 1.3


def calc_inv_masses(attributes, depths, friction):
    dep = np.clip(np.ascontiguousarray(depths, dtype=np.float32), 0.0, 1.0)
    fr = np.ascontiguousarray(friction, dtype=np.float32)
    mass = 1.0 + fr * 3.0 + ((1.0 - dep) ** 2) * 5.0
    inv = np.ascontiguousarray(1.0 / np.maximum(mass, EPSILON), dtype=np.float32)
    inv[(np.ascontiguousarray(attributes, dtype=np.uint8) & MC2_ATTR_MOVE) == 0] = 0.0
    return inv


def pin_fixed(state, reset_dynamics):
    fixed = state["inv_masses"] <= EPSILON
    if not bool(np.any(fixed)):
        return
    state["positions"][fixed] = state["base_positions"][fixed]
    state["velocity_positions"][fixed] = state["base_positions"][fixed]
    if reset_dynamics:
        state["old_positions"][fixed] = state["base_positions"][fixed]
        state["velocity"][fixed] = 0.0
        state["real_velocity"][fixed] = 0.0
        state["friction"][fixed] = 0.0
        state["static_friction"][fixed] = 0.0


def run_reference(state, params):
    for substep in range(params["substeps"]):
        hotools_native.update_step_basic_pose_mc2(
            state["base_positions"],
            state["base_rotations"],
            state["parent_indices"],
            state["baseline_start"],
            state["baseline_count"],
            state["baseline_data"],
            state["vertex_local_positions"],
            state["vertex_local_rotations"],
            state["step_basic_positions"],
            state["step_basic_rotations"],
            params["animation_pose_ratio"],
        )
        state["inv_masses"][:] = calc_inv_masses(state["attributes"], state["depths"], state["friction"])
        state["collision_normals"].fill(0.0)
        hotools_native.apply_substep_inertia_mc2(
            state["old_positions"],
            state["velocity"],
            state["depths"],
            state["inv_masses"],
            params["substep_old_world_positions"][substep],
            params["substep_step_vectors"][substep],
            params["substep_step_rotations"][substep],
            params["substep_inertia_vectors"][substep],
            params["substep_inertia_rotations"][substep],
            params["depth_inertia"],
        )
        state["velocity_positions"][:] = state["old_positions"]
        if params["step_dt"] > EPSILON:
            movable = state["inv_masses"] > EPSILON
            state["velocity"][movable] *= (1.0 - params["substep_damping_values"][movable])[:, None]
            state["velocity"][movable] += params["gravity"] * params["step_dt"]
            state["positions"][movable] = state["old_positions"][movable] + state["velocity"][movable] * params["step_dt"]
        pin_fixed(state, False)

        if params.get("use_tether", True):
            hotools_native.project_tether_mc2(
                state["positions"],
                state["inv_masses"],
                state["root_indices"],
                state["tether_rest_lengths"],
                state["velocity_positions"],
                1.0,
                params["tether_compression"],
                params["tether_stretch"],
            )

        for _ in range(params["iterations"]):
            hotools_native.project_neighbor_constraints_mc2(
                state["positions"],
                state["inv_masses"],
                state["distance_start"],
                state["distance_count"],
                state["distance_data"],
                state["distance_rest"],
                params["distance_stiffness_values"],
                state["velocity_positions"],
                DISTANCE_VELOCITY_ATTENUATION,
            )
            hotools_native.project_angle_constraints_mc2(
                state["positions"],
                state["inv_masses"],
                state["parent_indices"],
                state["baseline_start"],
                state["baseline_count"],
                state["baseline_data"],
                state["step_basic_positions"],
                state["step_basic_rotations"],
                params["angle_restoration_values"],
                params["angle_limit_values"],
                state["velocity_positions"],
                params["angle_restoration_velocity_attenuation"],
                params["angle_restoration_gravity_falloff"],
                params["angle_limit_stiffness"],
            )
            hotools_native.project_collisions_mc2(
                state["positions"],
                state["base_positions"],
                state["inv_masses"],
                state["collision_radii"],
                state["collision_normals"],
                state["friction"],
                params["collided_by_groups"],
                params["collider_types"],
                params["collider_group_bits"],
                params["collider_centers"],
                params["collider_segment_a"],
                params["collider_segment_b"],
                params["collider_old_centers"],
                params["collider_old_segment_a"],
                params["collider_old_segment_b"],
                params["collider_radii"],
            )
            state["inv_masses"][:] = calc_inv_masses(state["attributes"], state["depths"], state["friction"])
            hotools_native.project_neighbor_constraints_mc2(
                state["positions"],
                state["inv_masses"],
                state["distance_start"],
                state["distance_count"],
                state["distance_data"],
                state["distance_rest"],
                params["distance_stiffness_values"],
                state["velocity_positions"],
                DISTANCE_VELOCITY_ATTENUATION,
            )
            pin_fixed(state, False)

        hotools_native.project_motion_constraints_mc2(
            state["positions"],
            state["base_positions"],
            state["base_rotations"],
            state["inv_masses"],
            params["max_distances"],
            params["motion_stiffness_values"],
            params["backstop_radii"],
            params["backstop_distances"],
            state["velocity_positions"],
            params["normal_axis"],
        )
        hotools_native.apply_post_step_mc2(
            state["positions"],
            state["old_positions"],
            state["velocity_positions"],
            state["velocity"],
            state["real_velocity"],
            state["friction"],
            state["static_friction"],
            state["collision_normals"],
            state["inv_masses"],
            params["step_dt"],
            params["dynamic_friction"],
            params["static_friction_speed"],
            params["particle_speed_limit"],
        )
        hotools_native.apply_centrifugal_velocity_mc2(
            state["positions"],
            state["velocity"],
            state["depths"],
            state["inv_masses"],
            params["substep_now_world_positions"][substep],
            params["substep_rotation_axes"][substep],
            float(params["substep_angular_velocities"][substep]),
            params["centrifugal"],
        )
        pin_fixed(state, True)

    hotools_native.calculate_display_positions_mc2(
        state["positions"],
        state["real_velocity"],
        state["root_indices"],
        state["display_positions"],
        params["frame_dt"],
        MAX_DISTANCE_RATIO_FUTURE_PREDICTION,
    )


def solve_args(state, params):
    empty_i32_quad = np.empty((0, 4), dtype=np.int32)
    empty_f32 = np.empty(0, dtype=np.float32)
    return (
        state["positions"],
        state["old_positions"],
        state["velocity_positions"],
        state["velocity"],
        state["real_velocity"],
        state["friction"],
        state["static_friction"],
        state["collision_normals"],
        state["inv_masses"],
        state["step_basic_positions"],
        state["step_basic_rotations"],
        state["display_positions"],
        state["base_positions"],
        state["base_normals"],
        state["base_rotations"],
        state["attributes"],
        state["depths"],
        state["root_indices"],
        state["tether_rest_lengths"],
        state["parent_indices"],
        state["baseline_start"],
        state["baseline_count"],
        state["baseline_data"],
        state["vertex_local_positions"],
        state["vertex_local_rotations"],
        state["distance_start"],
        state["distance_count"],
        state["distance_data"],
        state["distance_rest"],
        params["distance_stiffness_values"],
        state["bend_distance_start"],
        state["bend_distance_count"],
        state["bend_distance_data"],
        state["bend_distance_neighbor_rest"],
        params["bend_stiffness_values"],
        empty_i32_quad,
        empty_f32,
        np.empty(0, dtype=np.int32),
        empty_i32_quad,
        empty_f32,
        params["angle_restoration_values"],
        params["angle_restoration_velocity_attenuation_values"],
        params["angle_restoration_gravity_falloff_values"],
        params["angle_limit_values"],
        params["substep_damping_values"],
        params["max_distances"],
        params["motion_stiffness_values"],
        params["backstop_radii"],
        params["backstop_distances"],
        state["edges"],
        state["collision_radii"],
        params["collider_types"],
        params["collider_group_bits"],
        params["collider_centers"],
        params["collider_segment_a"],
        params["collider_segment_b"],
        params["collider_old_centers"],
        params["collider_old_segment_a"],
        params["collider_old_segment_b"],
        params["collider_radii"],
        params["substep_old_world_positions"],
        params["substep_step_vectors"],
        params["substep_step_rotations"],
        params["substep_inertia_vectors"],
        params["substep_inertia_rotations"],
        params["substep_now_world_positions"],
        params["substep_rotation_axes"],
        params["substep_angular_velocities"],
        params["frame_dt"],
        params["step_dt"],
        params["substeps"],
        params["iterations"],
        params["gravity"],
        params["depth_inertia"],
        params["centrifugal"],
        params.get("use_tether", True),
        params["tether_compression"],
        params["tether_stretch"],
        params["dynamic_friction"],
        params["static_friction_speed"],
        params["particle_speed_limit"],
        params["angle_limit_stiffness"],
        params["normal_axis"],
        params["collided_by_groups"],
        params.get("collider_collision_mode", 1),
        MAX_DISTANCE_RATIO_FUTURE_PREDICTION,
        params["animation_pose_ratio"],
    )


def make_state_and_params():
    identity = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    base_positions = np.asarray(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
        ),
        dtype=np.float32,
    )
    state = {
        "positions": base_positions.copy(),
        "old_positions": base_positions.copy(),
        "velocity_positions": base_positions.copy(),
        "velocity": np.asarray(((0.0, 0.0, 0.0), (0.2, 0.0, 0.0), (0.0, 0.4, 0.0)), dtype=np.float32),
        "real_velocity": np.zeros((3, 3), dtype=np.float32),
        "friction": np.zeros(3, dtype=np.float32),
        "static_friction": np.zeros(3, dtype=np.float32),
        "collision_normals": np.zeros((3, 3), dtype=np.float32),
        "inv_masses": np.zeros(3, dtype=np.float32),
        "step_basic_positions": base_positions.copy(),
        "step_basic_rotations": np.repeat(identity.reshape(1, 4), 3, axis=0).copy(),
        "display_positions": base_positions.copy(),
        "base_positions": base_positions,
        "base_normals": np.asarray(((0.0, 1.0, 0.0),) * 3, dtype=np.float32),
        "base_rotations": np.repeat(identity.reshape(1, 4), 3, axis=0).copy(),
        "attributes": np.asarray((MC2_ATTR_FIXED, MC2_ATTR_MOVE | MC2_ATTR_MOTION, MC2_ATTR_MOVE | MC2_ATTR_MOTION), dtype=np.uint8),
        "depths": np.asarray((1.0, 0.55, 0.2), dtype=np.float32),
        "root_indices": np.asarray((-1, 0, 0), dtype=np.int32),
        "tether_rest_lengths": np.asarray((0.0, 1.0, 2.0), dtype=np.float32),
        "parent_indices": np.asarray((-1, 0, 1), dtype=np.int32),
        "baseline_start": np.asarray((0,), dtype=np.int32),
        "baseline_count": np.asarray((3,), dtype=np.int32),
        "baseline_data": np.asarray((0, 1, 2), dtype=np.int32),
        "vertex_local_positions": np.asarray(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 0.0)), dtype=np.float32),
        "vertex_local_rotations": np.repeat(identity.reshape(1, 4), 3, axis=0).copy(),
        "distance_start": np.asarray((0, 1, 3), dtype=np.int32),
        "distance_count": np.asarray((1, 2, 1), dtype=np.int32),
        "distance_data": np.asarray((1, 0, 2, 1), dtype=np.int32),
        "distance_rest": np.asarray((1.0, 1.0, 1.0, 1.0), dtype=np.float32),
        "bend_distance_start": np.zeros(3, dtype=np.int32),
        "bend_distance_count": np.zeros(3, dtype=np.int32),
        "bend_distance_data": np.empty(0, dtype=np.int32),
        "bend_distance_neighbor_rest": np.empty(0, dtype=np.float32),
        "edges": np.asarray(((0, 1), (1, 2)), dtype=np.int32),
        "collision_radii": np.asarray((0.0, 0.18, 0.18), dtype=np.float32),
    }
    frame_dt = np.float32(1.0 / 30.0)
    substeps = 2
    params = {
        "frame_dt": float(frame_dt),
        "step_dt": float(frame_dt / substeps),
        "substeps": substeps,
        "iterations": 2,
        "gravity": np.asarray((0.0, -2.0, 0.0), dtype=np.float32),
        "substep_damping_values": np.full(3, 0.04, dtype=np.float32),
        "depth_inertia": 0.2,
        "centrifugal": 0.0,
        "use_tether": True,
        "tether_compression": 0.4,
        "tether_stretch": 0.03,
        "dynamic_friction": 0.35,
        "static_friction_speed": 0.2,
        "particle_speed_limit": 4.0,
        "angle_limit_stiffness": 0.75,
        "normal_axis": 1,
        "collided_by_groups": 1,
        "collider_collision_mode": 1,
        "animation_pose_ratio": 0.0,
        "distance_stiffness_values": np.asarray((1.0, 0.8, 0.65), dtype=np.float32),
        "bend_stiffness_values": np.zeros(3, dtype=np.float32),
        "angle_restoration_values": np.asarray((0.0, 0.15, 0.1), dtype=np.float32),
        "angle_restoration_velocity_attenuation": ANGLE_RESTORATION_VELOCITY_ATTENUATION,
        "angle_restoration_gravity_falloff": ANGLE_RESTORATION_GRAVITY_FALLOFF,
        "angle_restoration_velocity_attenuation_values": np.full(
            3,
            ANGLE_RESTORATION_VELOCITY_ATTENUATION,
            dtype=np.float32,
        ),
        "angle_restoration_gravity_falloff_values": np.full(
            3,
            ANGLE_RESTORATION_GRAVITY_FALLOFF,
            dtype=np.float32,
        ),
        "angle_limit_values": np.asarray((0.0, 80.0, 70.0), dtype=np.float32),
        "max_distances": np.asarray((0.0, 1.2, 1.4), dtype=np.float32),
        "motion_stiffness_values": np.ones(3, dtype=np.float32),
        "backstop_radii": np.zeros(3, dtype=np.float32),
        "backstop_distances": np.zeros(3, dtype=np.float32),
        "collider_types": np.asarray((0,), dtype=np.int32),
        "collider_group_bits": np.asarray((1,), dtype=np.int32),
        "collider_centers": np.asarray(((1.0, -0.05, 0.0),), dtype=np.float32),
        "collider_segment_a": np.zeros((1, 3), dtype=np.float32),
        "collider_segment_b": np.zeros((1, 3), dtype=np.float32),
        "collider_old_centers": np.asarray(((0.92, -0.05, 0.0),), dtype=np.float32),
        "collider_old_segment_a": np.asarray(((0.92, -0.05, 0.0),), dtype=np.float32),
        "collider_old_segment_b": np.asarray(((0.92, -0.05, 0.0),), dtype=np.float32),
        "collider_radii": np.asarray((0.1,), dtype=np.float32),
        "substep_old_world_positions": np.asarray(((0.0, 0.0, 0.0), (0.005, 0.0, 0.0)), dtype=np.float32),
        "substep_step_vectors": np.asarray(((0.005, 0.0, 0.0), (0.005, 0.0, 0.0)), dtype=np.float32),
        "substep_step_rotations": np.repeat(identity.reshape(1, 4), substeps, axis=0).copy(),
        "substep_inertia_vectors": np.asarray(((0.0025, 0.0, 0.0), (0.0025, 0.0, 0.0)), dtype=np.float32),
        "substep_inertia_rotations": np.repeat(identity.reshape(1, 4), substeps, axis=0).copy(),
        "substep_now_world_positions": np.asarray(((0.005, 0.0, 0.0), (0.01, 0.0, 0.0)), dtype=np.float32),
        "substep_rotation_axes": np.zeros((substeps, 3), dtype=np.float32),
        "substep_angular_velocities": np.zeros(substeps, dtype=np.float32),
    }
    return state, params


def assert_native_solver_matches_scheduled_reference():
    reference_state, params = make_state_and_params()
    native_state = {key: value.copy() if isinstance(value, np.ndarray) else value for key, value in reference_state.items()}
    run_reference(reference_state, params)
    hotools_native.solve_meshcloth_mc2(*solve_args(native_state, params))

    for key in (
        "positions",
        "old_positions",
        "velocity_positions",
        "velocity",
        "real_velocity",
        "friction",
        "static_friction",
        "collision_normals",
        "inv_masses",
        "step_basic_positions",
        "step_basic_rotations",
        "display_positions",
    ):
        np.testing.assert_allclose(native_state[key], reference_state[key], rtol=2e-5, atol=2e-5, err_msg=key)


def main():
    assert_native_solver_matches_scheduled_reference()
    print("mc2 solver core native smoke test passed")


if __name__ == "__main__":
    main()
