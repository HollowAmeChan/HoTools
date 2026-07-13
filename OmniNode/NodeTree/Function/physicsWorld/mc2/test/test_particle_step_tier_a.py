import json
from pathlib import Path

import numpy as np


FIXTURE = Path(__file__).parent / "fixtures" / "tier_a" / "particle_step_gravity_damping_001.json"
INERTIA_FIXTURE = Path(__file__).parent / "fixtures" / "tier_a" / "particle_step_inertia_001.json"
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


if __name__ == "__main__":
    test_particle_prediction_matches_fixed_mc2_oracle()
    test_particle_center_inertia_matches_fixed_mc2_oracle()
    print("PASS MC2 particle-step Tier A oracle")
