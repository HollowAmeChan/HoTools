import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage"))

import hotools_native  # noqa: E402


EPSILON = 0.00000001
DISTANCE_HORIZONTAL_STIFFNESS = 0.5
DISTANCE_FIXED_INVERSE_MASS = 1.0 / 50.0
DISTANCE_VELOCITY_ATTENUATION = 0.3


def project_neighbor_reference(
    positions,
    inv_masses,
    starts,
    counts,
    neighbors,
    rest_lengths,
    stiffness_values,
    velocity_positions,
):
    if len(neighbors) == 0 or not bool(np.any(stiffness_values > EPSILON)):
        return

    for vertex_index in range(len(positions)):
        wi = float(inv_masses[vertex_index])
        if wi <= EPSILON:
            continue
        local_stiffness = float(np.clip(stiffness_values[vertex_index], 0.0, 1.0))
        if local_stiffness <= EPSILON:
            continue

        start = int(starts[vertex_index])
        count = int(counts[vertex_index])
        if count <= 0:
            continue

        add = np.zeros(3, dtype=np.float32)
        add_count = 0
        current = positions[vertex_index].copy()
        for offset in range(count):
            data_index = start + offset
            neighbor_index = int(neighbors[data_index])
            rest_dist = float(rest_lengths[data_index])
            rest = abs(rest_dist)
            final_stiffness = local_stiffness
            if rest_dist < 0.0:
                final_stiffness = float(np.clip(final_stiffness * DISTANCE_HORIZONTAL_STIFFNESS, 0.0, 1.0))

            raw_wj = float(inv_masses[neighbor_index])
            wj = raw_wj if raw_wj > EPSILON else DISTANCE_FIXED_INVERSE_MASS
            wsum = wi + wj
            if wsum <= EPSILON:
                continue

            delta = positions[neighbor_index] - current
            distance = float(np.linalg.norm(delta))
            if rest <= EPSILON:
                add += delta * 0.5
                add_count += 1
                continue
            if distance <= EPSILON:
                continue

            correction = ((distance - rest) * final_stiffness / wsum) * wi * (delta / distance)
            add += correction
            add_count += 1

        if add_count > 0:
            add_pos = add / float(add_count)
            positions[vertex_index] = current + add_pos
            velocity_positions[vertex_index] += add_pos * DISTANCE_VELOCITY_ATTENUATION


def assert_native_matches_reference():
    positions = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.25, 0.0, 0.0],
            [0.0, 1.1, 0.0],
            [1.15, 1.25, 0.2],
        ],
        dtype=np.float32,
    )
    inv_masses = np.array([0.0, 1.0, 0.7, 1.2], dtype=np.float32)
    starts = np.array([0, 2, 5, 7], dtype=np.int32)
    counts = np.array([2, 3, 2, 1], dtype=np.int32)
    neighbors = np.array([1, 2, 0, 3, 2, 0, 1, 1], dtype=np.int32)
    rest_lengths = np.array([1.0, 1.0, 1.0, 1.0, -1.4142135, 1.0, -1.4142135, 1.0], dtype=np.float32)
    stiffness = np.array([1.0, 0.8, 0.5, 1.0], dtype=np.float32)

    expected_positions = positions.copy()
    expected_velocity_positions = positions.copy()
    actual_positions = positions.copy()
    actual_velocity_positions = positions.copy()

    project_neighbor_reference(
        expected_positions,
        inv_masses,
        starts,
        counts,
        neighbors,
        rest_lengths,
        stiffness,
        expected_velocity_positions,
    )

    hotools_native.project_neighbor_constraints_mc2(
        actual_positions,
        inv_masses,
        starts,
        counts,
        neighbors,
        rest_lengths,
        stiffness,
        actual_velocity_positions,
        DISTANCE_VELOCITY_ATTENUATION,
    )

    np.testing.assert_allclose(actual_positions, expected_positions, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(actual_velocity_positions, expected_velocity_positions, rtol=1e-6, atol=1e-6)


def main():
    assert_native_matches_reference()
    print("mc2 neighbor native smoke test passed")


if __name__ == "__main__":
    main()
