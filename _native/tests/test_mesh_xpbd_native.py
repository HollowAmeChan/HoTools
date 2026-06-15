import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage"))

import hotools_native  # noqa: E402


EPSILON = 0.000001


def project_distance_constraints(
    positions,
    inv_masses,
    index_i,
    index_j,
    rest_lengths,
    compliance,
    dt,
):
    alpha = max(float(compliance), 0.0) / (dt * dt) if dt > EPSILON else 0.0
    for constraint_index in range(len(index_i)):
        i = int(index_i[constraint_index])
        j = int(index_j[constraint_index])
        wi = float(inv_masses[i])
        wj = float(inv_masses[j])
        wsum = wi + wj
        if wsum <= EPSILON:
            continue

        delta = positions[i] - positions[j]
        length = float(np.linalg.norm(delta))
        if length <= EPSILON:
            continue

        c = length - float(rest_lengths[constraint_index])
        dlambda = -c / (wsum + alpha)
        normal = delta / length
        if wi > 0.0:
            positions[i] += wi * dlambda * normal
        if wj > 0.0:
            positions[j] -= wj * dlambda * normal


def solve_reference(
    positions,
    prev_positions,
    rest_positions,
    inv_masses,
    edge_i,
    edge_j,
    edge_rest,
    bend_i,
    bend_j,
    bend_rest,
    gravity,
    dt,
    damping,
    substeps,
    iterations,
    stretch_compliance,
    bend_compliance,
):
    pinned = inv_masses <= EPSILON
    has_pinned = bool(np.any(pinned))
    substep_count = max(1, min(16, int(substeps)))
    iteration_count = max(0, min(64, int(iterations)))
    step_dt = dt / substep_count if substep_count > 0 else dt
    damping = max(0.0, min(1.0, float(damping)))

    for _ in range(substep_count):
        old_positions = positions.copy()
        inertia = (positions - prev_positions) * (1.0 - damping)
        positions += inertia + gravity * (step_dt * step_dt)
        prev_positions = old_positions

        if has_pinned:
            positions[pinned] = rest_positions[pinned]
            prev_positions[pinned] = rest_positions[pinned]

        for _iteration in range(iteration_count):
            project_distance_constraints(
                positions,
                inv_masses,
                edge_i,
                edge_j,
                edge_rest,
                stretch_compliance,
                step_dt,
            )
            project_distance_constraints(
                positions,
                inv_masses,
                bend_i,
                bend_j,
                bend_rest,
                bend_compliance,
                step_dt,
            )

            if has_pinned:
                positions[pinned] = rest_positions[pinned]
                prev_positions[pinned] = rest_positions[pinned]

    return positions, prev_positions


def main():
    rest = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    positions = rest.copy()
    positions[:, 2] = np.array([0.0, 0.1, -0.05, 0.2], dtype=np.float32)
    prev_positions = rest.copy()
    inv_masses = np.array([0.0, 1.0, 1.0, 1.0], dtype=np.float32)
    edge_i = np.array([0, 1, 2, 0, 1], dtype=np.int32)
    edge_j = np.array([1, 3, 3, 2, 2], dtype=np.int32)
    edge_rest = np.linalg.norm(rest[edge_i] - rest[edge_j], axis=1).astype(np.float32)
    bend_i = np.array([0], dtype=np.int32)
    bend_j = np.array([3], dtype=np.int32)
    bend_rest = np.linalg.norm(rest[bend_i] - rest[bend_j], axis=1).astype(np.float32)
    gravity = np.array([0.0, 0.0, -9.8], dtype=np.float32)

    expected_pos, expected_prev = solve_reference(
        positions.copy(),
        prev_positions.copy(),
        rest,
        inv_masses,
        edge_i,
        edge_j,
        edge_rest,
        bend_i,
        bend_j,
        bend_rest,
        gravity,
        1.0 / 30.0,
        0.02,
        2,
        6,
        0.0,
        0.001,
    )

    actual_pos = positions.copy()
    actual_prev = prev_positions.copy()
    hotools_native.solve_mesh_shape_key_xpbd(
        actual_pos,
        actual_prev,
        rest,
        inv_masses,
        edge_i,
        edge_j,
        edge_rest,
        bend_i,
        bend_j,
        bend_rest,
        gravity,
        1.0 / 30.0,
        0.02,
        2,
        6,
        0.0,
        0.001,
    )

    np.testing.assert_allclose(actual_pos, expected_pos, rtol=1e-5, atol=1e-5)
    np.testing.assert_allclose(actual_prev, expected_prev, rtol=1e-5, atol=1e-5)

    try:
        hotools_native.solve_mesh_shape_key_xpbd(
            actual_pos.copy(),
            actual_prev.copy(),
            rest,
            inv_masses,
            np.array([0, len(rest)], dtype=np.int32),
            np.array([1, 2], dtype=np.int32),
            np.array([1.0, 1.0], dtype=np.float32),
            bend_i,
            bend_j,
            bend_rest,
            gravity,
            1.0 / 30.0,
            0.02,
            1,
            1,
            0.0,
            0.001,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("out-of-range constraint index did not raise ValueError")

    print("mesh_xpbd_native smoke test passed")


if __name__ == "__main__":
    main()
