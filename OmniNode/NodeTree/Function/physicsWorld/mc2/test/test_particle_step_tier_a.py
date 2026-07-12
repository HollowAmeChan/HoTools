import json
from pathlib import Path

import numpy as np


FIXTURE = Path(__file__).parent / "fixtures" / "tier_a" / "particle_step_gravity_damping_001.json"
EXPECTED_COMMIT = "418f89ff31a45bb4b2336641ad5907a1110eabea"


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


if __name__ == "__main__":
    test_particle_prediction_matches_fixed_mc2_oracle()
    print("PASS MC2 particle-step Tier A oracle")
