import json
from pathlib import Path

import numpy as np


FIXTURE = Path(__file__).parent / "fixtures" / "tier_a" / "particle_step_gravity_damping_001.json"
INERTIA_FIXTURE = Path(__file__).parent / "fixtures" / "tier_a" / "particle_step_inertia_001.json"
FRAME_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "tier_a"
    / "particle_step_constraints_post_001.json"
)
BASELINE_FIXTURES = tuple(
    Path(__file__).parent / "fixtures" / "tier_a" / name
    for name in (
        "particle_step_baseline_pose_001.json",
        "particle_step_baseline_pose_negative_scale_x_001.json",
    )
)
EXPECTED_COMMIT = "418f89ff31a45bb4b2336641ad5907a1110eabea"


def _normalize_quaternion(value: np.ndarray) -> np.ndarray:
    return np.asarray(value / np.float32(np.linalg.norm(value)), dtype=np.float32)


def _slerp(first: np.ndarray, second: np.ndarray, ratio: np.float32) -> np.ndarray:
    target = second.copy()
    cosine = np.float32(np.dot(first, target))
    if cosine < 0.0:
        target = -target
        cosine = -cosine
    if cosine > np.float32(0.9995):
        return _normalize_quaternion(first + (target - first) * ratio)
    angle = np.float32(np.arccos(np.clip(cosine, -1.0, 1.0)))
    sine = np.float32(np.sin(angle))
    first_weight = np.float32(np.sin((np.float32(1.0) - ratio) * angle) / sine)
    second_weight = np.float32(np.sin(ratio * angle) / sine)
    return _normalize_quaternion(first * first_weight + target * second_weight)


def _z_rotation(degrees: float) -> np.ndarray:
    half_angle = np.float32(np.radians(np.float32(degrees)) * np.float32(0.5))
    return np.asarray((0.0, 0.0, np.sin(half_angle), np.cos(half_angle)), dtype=np.float32)


def _axis_angle(value) -> np.ndarray:
    if value is None:
        return np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    axis = np.asarray(value["axis"], dtype=np.float32)
    half_angle = np.float32(np.radians(np.float32(value["degrees"])) * np.float32(0.5))
    return np.asarray(
        tuple(axis * np.sin(half_angle)) + (np.cos(half_angle),),
        dtype=np.float32,
    )


def _multiply(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return np.asarray(
        (
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
            lw * rw - lx * rx - ly * ry - lz * rz,
        ),
        dtype=np.float32,
    )


def _rotate(rotation: np.ndarray, vector: np.ndarray) -> np.ndarray:
    twice_cross = np.float32(2.0) * np.cross(rotation[:3], vector)
    return np.asarray(
        vector + rotation[3] * twice_cross + np.cross(rotation[:3], twice_cross),
        dtype=np.float32,
    )


def test_particle_prediction_matches_fixed_mc2_oracle() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = fixture["source"]
    assert source["commit"] == EXPECTED_COMMIT
    assert source["oracle_tier"] == "A"
    assert source["producer"] == [
        "Runtime/Manager/Simulation/SimulationManagerNormal.cs::SimulationStepUpdateParticles"
    ]

    values = fixture["input"]
    expected = fixture["expected"]
    velocity = np.asarray(values["velocities"][0], dtype=np.float32)
    velocity *= np.float32(values["velocity_weight"])
    damping = np.float32(values["damping_samples"][8])
    damping_factor = np.clip(
        np.float32(1.0) - damping * np.float32(values["simulation_power"][2]),
        np.float32(0.0),
        np.float32(1.0),
    )
    velocity *= damping_factor
    gravity = (
        np.asarray(values["gravity_direction"], dtype=np.float32)
        * np.float32(values["gravity"])
        * np.float32(values["gravity_ratio"])
        * np.float32(values["scale_ratio"])
    )
    dt = np.float32(values["simulation_delta_time"])
    velocity += gravity * dt
    next_position = np.asarray(values["old_positions"][0], dtype=np.float32) + velocity * dt

    np.testing.assert_allclose(next_position, expected["next_positions"][0], rtol=0.0, atol=1.0e-6)
    np.testing.assert_array_equal(expected["base_positions"], values["animated_positions"])
    np.testing.assert_array_equal(expected["next_positions"][1], values["animated_positions"][1])
    np.testing.assert_array_equal(expected["velocity_positions"][0], values["old_positions"][0])
    np.testing.assert_array_equal(expected["velocity_positions"][1], values["animated_positions"][1])
    assert expected["temp_vector_a"] == [[0, 0, 0], [0, 0, 0]]
    assert expected["temp_vector_b"] == [[0, 0, 0], [0, 0, 0]]
    assert expected["temp_counts"] == [0, 0]
    assert expected["temp_floats"] == [0, 0]


def test_particle_center_inertia_matches_fixed_mc2_oracle() -> None:
    fixture = json.loads(INERTIA_FIXTURE.read_text(encoding="utf-8"))
    source = fixture["source"]
    assert fixture["oracle_tier"] == source["oracle_tier"] == "A"
    assert fixture["mc2_commit"] == source["commit"] == EXPECTED_COMMIT
    assert source["producer"] == [
        "Runtime/Manager/Simulation/SimulationManagerNormal.cs::SimulationStepUpdateParticles"
    ]

    values = fixture["input"]
    expected = fixture["expected"]
    depth = np.float32(values["depth"])
    inertia_depth = np.float32(values["depth_inertia"]) * (
        np.float32(1.0) - depth * depth
    )
    inertia_vector = np.asarray(values["inertia_vector"], dtype=np.float32)
    step_vector = np.asarray(values["step_vector"], dtype=np.float32)
    effective_vector = inertia_vector + (step_vector - inertia_vector) * inertia_depth
    effective_rotation = _slerp(
        _z_rotation(values["inertia_rotation_axis_angle"]["degrees"]),
        _z_rotation(values["step_rotation_axis_angle"]["degrees"]),
        inertia_depth,
    )
    old_world = np.asarray(values["old_world_position"], dtype=np.float32)
    old_position = np.asarray(values["old_position"], dtype=np.float32)
    world_position = (
        old_world + _rotate(effective_rotation, old_position - old_world) + effective_vector
    )
    velocity = _rotate(
        effective_rotation, np.asarray(values["velocity"], dtype=np.float32)
    )
    velocity *= np.float32(values["velocity_weight"])
    next_position = world_position + velocity * np.float32(values["simulation_delta_time"])

    np.testing.assert_allclose(
        world_position, expected["velocity_positions"][0], rtol=0.0, atol=1.0e-6
    )
    np.testing.assert_allclose(
        next_position, expected["next_positions"][0], rtol=0.0, atol=1.0e-6
    )
    np.testing.assert_array_equal(expected["base_positions"][0], values["animated_position"])
    np.testing.assert_array_equal(
        expected["step_basic_positions"][0], values["animated_position"]
    )
    np.testing.assert_array_equal(expected["base_rotations_xyzw"][0], (0, 0, 0, 1))
    np.testing.assert_array_equal(expected["step_basic_rotations_xyzw"][0], (0, 0, 0, 1))


def _assert_baseline_step_pose_fixture(path: Path) -> None:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    source = fixture["source"]
    assert fixture["oracle_tier"] == source["oracle_tier"] == "A"
    assert fixture["mc2_commit"] == source["commit"] == EXPECTED_COMMIT
    assert source["producer"] == [
        "Runtime/Manager/Simulation/SimulationManagerNormal.cs::SimulationStepUpdateBaseLinePose"
    ]
    values = fixture["input"]
    expected = fixture["expected"]
    base_positions = np.asarray(values["base_positions"], dtype=np.float32)
    base_rotations = np.asarray(
        [_axis_angle(value) for value in values["base_rotation_axis_angles"]],
        dtype=np.float32,
    )
    local_positions = np.asarray(values["vertex_local_positions"], dtype=np.float32)
    local_rotations = np.asarray(
        [_axis_angle(value) for value in values["vertex_local_rotation_axis_angles"]],
        dtype=np.float32,
    )
    step_positions = base_positions.copy()
    step_rotations = base_rotations.copy()
    direction = np.asarray(values["negative_scale_direction"], dtype=np.float32)
    quaternion_value = np.asarray(
        values["negative_scale_quaternion_value"], dtype=np.float32
    )
    scale = np.asarray(values["initial_scale"], dtype=np.float32) * np.float32(
        values["scale_ratio"]
    )
    for start, count in values["baseline_ranges"]:
        for vertex in values["baseline_data"][start : start + count]:
            parent = values["parent_indices"][vertex]
            if values["attributes"][vertex] == 2 and parent >= 0:
                local_position = local_positions[vertex] * direction * scale
                local_rotation = local_rotations[vertex] * quaternion_value
                step_positions[vertex] = (
                    step_positions[parent]
                    + _rotate(step_rotations[parent], local_position)
                )
                step_rotations[vertex] = _normalize_quaternion(
                    _multiply(step_rotations[parent], local_rotation)
                )
    blend = np.float32(values["animation_pose_ratio"])
    for start, count in values["baseline_ranges"]:
        for vertex in values["baseline_data"][start : start + count]:
            step_positions[vertex] += (
                base_positions[vertex] - step_positions[vertex]
            ) * blend
            step_rotations[vertex] = _slerp(
                step_rotations[vertex], base_rotations[vertex], blend
            )
    np.testing.assert_allclose(
        step_positions, expected["step_basic_positions"], rtol=1.0e-6, atol=1.0e-6
    )
    expected_rotations = np.asarray(
        expected["step_basic_rotations_xyzw"], dtype=np.float32
    )
    for index in range(len(step_rotations)):
        if np.dot(step_rotations[index], expected_rotations[index]) < 0.0:
            step_rotations[index] *= -1.0
    np.testing.assert_allclose(
        step_rotations, expected_rotations, rtol=1.0e-6, atol=1.0e-6
    )


def test_baseline_step_pose_matches_fixed_mc2_oracle() -> None:
    for path in BASELINE_FIXTURES:
        _assert_baseline_step_pose_fixture(path)


def test_particle_frame_constraints_and_post_match_fixed_mc2_oracle() -> None:
    fixture = json.loads(FRAME_FIXTURE.read_text(encoding="utf-8"))
    values = fixture["input"]
    expected = fixture["expected"]
    assert fixture["oracle_tier"] == "A"
    assert fixture["mc2_commit"] == EXPECTED_COMMIT
    dt = np.float32(values["simulation_delta_time"])
    simulation_power_z = np.float32(values["simulation_power"][2])
    damping_factor = np.float32(
        1.0 - np.float32(values["damping"]) * simulation_power_z
    )
    depths = np.asarray(values["depths"], dtype=np.float32)
    attributes = np.asarray(values["attributes"], dtype=np.uint8)
    animated = np.asarray(values["animated_positions"], dtype=np.float32)
    old_animated = np.asarray(values["old_animated_positions"], dtype=np.float32)
    previous_positions = np.asarray(
        values["initial_particle_positions"], dtype=np.float32
    )
    previous_velocities = np.asarray(values["initial_velocities"], dtype=np.float32)
    gravity_direction = np.asarray(values["gravity_direction"], dtype=np.float32)
    prediction_stages = np.asarray(
        expected["positions_after_prediction"], dtype=np.float32
    )
    post_positions = np.asarray(expected["positions_after_post"], dtype=np.float32)
    post_velocities = np.asarray(expected["velocities_after_post"], dtype=np.float32)
    real_velocities = np.asarray(
        expected["real_velocities_after_post"], dtype=np.float32
    )
    velocity_references = np.asarray(
        expected["velocity_references_after_second_distance"], dtype=np.float32
    )
    center_now = np.asarray(expected["center_now_world_positions"], dtype=np.float32)
    center_step_vectors = np.asarray(expected["center_step_vectors"], dtype=np.float32)
    center_step_rotations = np.asarray(
        expected["center_step_rotations_xyzw"], dtype=np.float32
    )
    center_inertia_vectors = np.asarray(
        expected["center_inertia_vectors"], dtype=np.float32
    )
    center_inertia_rotations = np.asarray(
        expected["center_inertia_rotations_xyzw"], dtype=np.float32
    )
    center_weights = np.asarray(expected["center_velocity_weights"], dtype=np.float32)
    center_gravity = np.asarray(expected["center_gravity_ratios"], dtype=np.float32)
    center_scales = np.asarray(expected["center_scale_ratios"], dtype=np.float32)
    frame_interpolations = np.asarray(
        expected["center_frame_interpolations"], dtype=np.float32
    )

    for step_index in range(int(values["update_count"])):
        expected_prediction = np.empty_like(previous_positions)
        expected_prediction[0] = (
            old_animated[0]
            + (animated[0] - old_animated[0]) * frame_interpolations[step_index]
        )
        old_world = (
            np.zeros(3, dtype=np.float32)
            if step_index == 0
            else center_now[step_index - 1]
        )
        for vertex in range(1, len(previous_positions)):
            assert attributes[vertex] == 2
            inertia_depth = np.float32(values["depth_inertia"]) * (
                np.float32(1.0) - depths[vertex] * depths[vertex]
            )
            inertia_vector = (
                center_inertia_vectors[step_index] * (np.float32(1.0) - inertia_depth)
                + center_step_vectors[step_index] * inertia_depth
            )
            inertia_rotation = _slerp(
                center_inertia_rotations[step_index],
                center_step_rotations[step_index],
                inertia_depth,
            )
            world_position = old_world + _rotate(
                inertia_rotation,
                previous_positions[vertex] - old_world,
            ) + inertia_vector
            velocity = _rotate(inertia_rotation, previous_velocities[vertex])
            velocity *= center_weights[step_index] * damping_factor
            velocity += (
                gravity_direction
                * np.float32(values["gravity"])
                * center_gravity[step_index]
                * center_scales[step_index]
                * dt
            )
            expected_prediction[vertex] = world_position + velocity * dt
        np.testing.assert_allclose(
            prediction_stages[step_index],
            expected_prediction,
            rtol=1.0e-6,
            atol=2.0e-6,
        )

        expected_velocity = (
            post_positions[step_index] - velocity_references[step_index]
        ) / dt * center_weights[step_index]
        expected_velocity[attributes == 1] = 0.0
        np.testing.assert_allclose(
            post_velocities[step_index],
            expected_velocity,
            rtol=1.0e-6,
            atol=2.0e-6,
        )
        np.testing.assert_allclose(
            real_velocities[step_index],
            (post_positions[step_index] - previous_positions) / dt,
            rtol=1.0e-6,
            atol=2.0e-6,
        )
        previous_positions = post_positions[step_index]
        previous_velocities = post_velocities[step_index]

    np.testing.assert_allclose(
        expected["positions_after_post"],
        expected["positions_after_second_distance"],
        rtol=0.0,
        atol=0.0,
    )
    np.testing.assert_allclose(
        expected["post_old_component_world_position"],
        values["component_world_position"],
        atol=1.0e-6,
    )
    np.testing.assert_allclose(
        expected["post_old_frame_world_position"],
        values["frame_world_position"],
        atol=1.0e-6,
    )


if __name__ == "__main__":
    test_particle_prediction_matches_fixed_mc2_oracle()
    test_particle_center_inertia_matches_fixed_mc2_oracle()
    test_baseline_step_pose_matches_fixed_mc2_oracle()
    test_particle_frame_constraints_and_post_match_fixed_mc2_oracle()
    print("PASS MC2 particle-step Tier A oracle")
