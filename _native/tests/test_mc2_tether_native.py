import json
import os
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, os.environ.get("HOTOOLS_NATIVE_TEST_DIR", str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage")))

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
    / "tether_runtime_001.json"
)

EPSILON = 0.00000001
TETHER_STIFFNESS_WIDTH = 0.3
TETHER_COMPRESSION_STIFFNESS = 1.0
TETHER_STRETCH_STIFFNESS = 1.0
TETHER_COMPRESSION_VELOCITY_ATTENUATION = 0.7
TETHER_STRETCH_VELOCITY_ATTENUATION = 0.7


def project_tether_reference(
    positions,
    inv_masses,
    root_indices,
    root_rest_lengths,
    velocity_positions,
    stiffness,
    compression,
    stretch,
):
    stiffness = max(0.0, min(1.0, float(stiffness)))
    if stiffness <= EPSILON:
        return

    compression_limit = 1.0 - max(0.0, min(1.0, float(compression)))
    stretch_limit = 1.0 + max(0.0, float(stretch))
    stiffness_width = max(TETHER_STIFFNESS_WIDTH, EPSILON)

    for vertex_index in range(len(positions)):
        if float(inv_masses[vertex_index]) <= EPSILON:
            continue
        root_index = int(root_indices[vertex_index])
        if root_index < 0:
            continue
        rest_length = float(root_rest_lengths[vertex_index])
        if rest_length <= EPSILON:
            continue

        delta = positions[root_index] - positions[vertex_index]
        distance = float(np.linalg.norm(delta))
        if distance <= EPSILON:
            continue

        ratio = distance / rest_length
        dist = 0.0
        solve_stiffness = 0.0
        velocity_attenuation = 0.0
        if ratio < compression_limit:
            dist = distance - compression_limit * rest_length
            fade = max(0.0, min(1.0, (compression_limit - ratio) / stiffness_width))
            solve_stiffness = stiffness * TETHER_COMPRESSION_STIFFNESS * fade
            velocity_attenuation = TETHER_COMPRESSION_VELOCITY_ATTENUATION
        elif ratio > stretch_limit:
            dist = distance - stretch_limit * rest_length
            fade = max(0.0, min(1.0, (ratio - stretch_limit) / stiffness_width))
            solve_stiffness = stiffness * TETHER_STRETCH_STIFFNESS * fade
            velocity_attenuation = TETHER_STRETCH_VELOCITY_ATTENUATION

        if solve_stiffness <= EPSILON:
            continue

        add = (delta / distance) * (dist * solve_stiffness)
        positions[vertex_index] += add
        velocity_positions[vertex_index] += add * velocity_attenuation


def assert_native_matches_reference():
    positions = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.35, 0.0, 0.0],
            [0.25, 0.0, 0.0],
            [0.5, 0.5, 0.0],
            [1.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    inv_masses = np.array([0.0, 1.0, 1.0, 0.0, 1.0], dtype=np.float32)
    root_indices = np.array([-1, 0, 0, 0, -1], dtype=np.int32)
    root_rest_lengths = np.array([0.0, 1.0, 1.0, 1.0, 1.0], dtype=np.float32)

    expected_positions = positions.copy()
    expected_velocity_positions = positions.copy()
    actual_positions = positions.copy()
    actual_velocity_positions = positions.copy()

    project_tether_reference(
        expected_positions,
        inv_masses,
        root_indices,
        root_rest_lengths,
        expected_velocity_positions,
        1.0,
        0.4,
        0.03,
    )

    hotools_native.project_tether_mc2(
        actual_positions,
        inv_masses,
        root_indices,
        root_rest_lengths,
        actual_velocity_positions,
        1.0,
        0.4,
        0.03,
    )

    np.testing.assert_allclose(actual_positions, expected_positions, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(actual_velocity_positions, expected_velocity_positions, rtol=1e-6, atol=1e-6)


def assert_native_matches_tier_a_oracle():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["oracle_tier"] == "A"
    assert fixture["mc2_commit"] == "418f89ff31a45bb4b2336641ad5907a1110eabea"
    values = fixture["input"]
    expected = fixture["expected"]

    attributes = np.asarray(values["attributes"], dtype=np.uint8)
    positions = np.asarray(values["next_positions"], dtype=np.float32)
    velocity_positions = np.asarray(values["velocity_positions"], dtype=np.float32)
    root_indices = np.asarray(values["root_indices"], dtype=np.int32)
    step_basic_positions = np.asarray(values["step_basic_positions"], dtype=np.float32)
    inv_masses = np.asarray((attributes & 0x02) != 0, dtype=np.float32)
    root_rest_lengths = np.zeros(len(positions), dtype=np.float32)
    for vertex, root in enumerate(root_indices):
        if root >= 0:
            root_rest_lengths[vertex] = np.linalg.norm(
                step_basic_positions[root] - step_basic_positions[vertex]
            )

    hotools_native.project_tether_mc2(
        positions,
        inv_masses,
        root_indices,
        root_rest_lengths,
        velocity_positions,
        1.0,
        values["compression_limit"],
        values["stretch_limit"],
    )

    np.testing.assert_allclose(
        positions,
        np.asarray(expected["next_positions"], dtype=np.float32),
        rtol=1e-6,
        atol=1e-6,
    )
    np.testing.assert_allclose(
        velocity_positions,
        np.asarray(expected["velocity_positions"], dtype=np.float32),
        rtol=1e-6,
        atol=1e-6,
    )


def main():
    assert_native_matches_reference()
    assert_native_matches_tier_a_oracle()
    print("mc2 tether native smoke test passed")


if __name__ == "__main__":
    main()
