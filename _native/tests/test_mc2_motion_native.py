import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage"))

import hotools_native  # noqa: E402


EPSILON = 0.00000001
MOTION_VELOCITY_ATTENUATION = 0.95


def safe_normal(delta):
    length = float(np.linalg.norm(delta))
    if length > EPSILON:
        return delta / length
    return np.asarray((0.0, 0.0, 1.0), dtype=np.float32)


def project_motion_reference(
    positions,
    base_positions,
    base_normals,
    inv_masses,
    max_distances,
    stiffness_values,
    backstop_radii,
    backstop_distances,
    velocity_positions,
):
    use_max_distance = bool(np.any(max_distances > EPSILON))
    use_backstop = bool(np.any(backstop_radii > EPSILON))
    if not use_max_distance and not use_backstop:
        return
    if not bool(np.any(stiffness_values > EPSILON)):
        return

    for vertex_index in range(len(positions)):
        if float(inv_masses[vertex_index]) <= EPSILON:
            continue
        stiffness = float(stiffness_values[vertex_index])
        if stiffness <= EPSILON:
            continue
        limit = float(max_distances[vertex_index])
        backstop_radius = max(float(backstop_radii[vertex_index]), 0.0)
        if limit <= EPSILON and backstop_radius <= EPSILON:
            continue
        original_position = positions[vertex_index].copy()
        constrained = original_position.copy()

        if use_max_distance and limit > EPSILON:
            delta = constrained - base_positions[vertex_index]
            distance = float(np.linalg.norm(delta))
            if distance > limit and distance > EPSILON:
                constrained = base_positions[vertex_index] + (delta / distance) * limit

        if use_backstop and backstop_radius > EPSILON:
            normal = safe_normal(base_normals[vertex_index])
            backstop_distance = max(float(backstop_distances[vertex_index]), 0.0)
            center = base_positions[vertex_index] - normal * (backstop_distance + backstop_radius)
            delta = constrained - center
            distance = float(np.linalg.norm(delta))
            if EPSILON < distance < backstop_radius:
                constrained = center + (delta / distance) * backstop_radius

        next_position = original_position * (1.0 - stiffness) + constrained * stiffness
        add = next_position - original_position
        positions[vertex_index] = next_position
        velocity_positions[vertex_index] += add * MOTION_VELOCITY_ATTENUATION


def assert_native_matches_reference():
    positions = np.array(
        [
            [1.5, 0.0, 0.0],
            [0.0, 0.0, -0.15],
            [0.5, 0.2, -0.4],
            [2.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    base_positions = np.array(
        [
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    base_normals = np.array(
        [
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    inv_masses = np.array([1.0, 1.0, 1.0, 0.0], dtype=np.float32)
    max_distances = np.array([1.0, 0.0, 0.6, 0.5], dtype=np.float32)
    stiffness_values = np.array([1.0, 0.75, 0.5, 1.0], dtype=np.float32)
    backstop_radii = np.array([0.0, 0.3, 0.5, 0.0], dtype=np.float32)
    backstop_distances = np.array([0.0, 0.0, 0.2, 0.0], dtype=np.float32)

    expected_positions = positions.copy()
    expected_velocity_positions = positions.copy()
    actual_positions = positions.copy()
    actual_velocity_positions = positions.copy()

    project_motion_reference(
        expected_positions,
        base_positions,
        base_normals,
        inv_masses,
        max_distances,
        stiffness_values,
        backstop_radii,
        backstop_distances,
        expected_velocity_positions,
    )

    hotools_native.project_motion_constraints_mc2(
        actual_positions,
        base_positions,
        base_normals,
        inv_masses,
        max_distances,
        stiffness_values,
        backstop_radii,
        backstop_distances,
        actual_velocity_positions,
    )

    np.testing.assert_allclose(actual_positions, expected_positions, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(actual_velocity_positions, expected_velocity_positions, rtol=1e-6, atol=1e-6)


def main():
    assert_native_matches_reference()
    print("mc2 motion native smoke test passed")


if __name__ == "__main__":
    main()
