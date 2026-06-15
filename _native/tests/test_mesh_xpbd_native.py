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


def collision_group_enabled(mask, group):
    group = int(group)
    if group < 1 or group > 16:
        return False
    return bool(int(mask) & (1 << (group - 1)))


def safe_normal(delta, fallback):
    length = float(np.linalg.norm(delta))
    if length > EPSILON:
        return delta / length

    fallback_length = float(np.linalg.norm(fallback))
    if fallback_length > EPSILON:
        return fallback / fallback_length

    return np.array([0.0, 0.0, 1.0], dtype=np.float32)


def closest_point_on_segment(point, segment_a, segment_b):
    segment = segment_b - segment_a
    denom = float(np.dot(segment, segment))
    if denom <= EPSILON:
        return segment_a.copy()

    t = float(np.dot(point - segment_a, segment)) / denom
    return segment_a + segment * max(0.0, min(1.0, t))


def project_collisions(
    positions,
    rest_positions,
    inv_masses,
    collision_radii,
    collided_by_groups,
    collider_types,
    collider_groups,
    collider_centers,
    collider_segment_a,
    collider_segment_b,
    collider_radii,
):
    if not int(collided_by_groups) or len(collider_types) == 0:
        return

    for vertex_index in range(len(positions)):
        if float(inv_masses[vertex_index]) <= EPSILON:
            continue

        hit_radius = float(collision_radii[vertex_index])
        if hit_radius <= EPSILON:
            continue

        projected = positions[vertex_index].copy()
        fallback = projected - rest_positions[vertex_index]
        for collider_index in range(len(collider_types)):
            if not collision_group_enabled(collided_by_groups, collider_groups[collider_index]):
                continue

            radius = max(float(collider_radii[collider_index]), 0.0) + hit_radius
            if radius <= EPSILON:
                continue

            if int(collider_types[collider_index]) == 1:
                center = closest_point_on_segment(
                    projected,
                    collider_segment_a[collider_index],
                    collider_segment_b[collider_index],
                )
            else:
                center = collider_centers[collider_index]

            delta = projected - center
            if float(np.dot(delta, delta)) >= radius * radius:
                continue

            projected = center + safe_normal(delta, fallback) * radius

        positions[vertex_index] = projected


def empty_collision_args(vertex_count):
    return (
        np.zeros(vertex_count, dtype=np.float32),
        0,
        np.empty(0, dtype=np.int32),
        np.empty(0, dtype=np.int32),
        np.empty((0, 3), dtype=np.float32),
        np.empty((0, 3), dtype=np.float32),
        np.empty((0, 3), dtype=np.float32),
        np.empty(0, dtype=np.float32),
    )


def run_native(
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
    collision_args,
):
    hotools_native.solve_mesh_shape_key_xpbd(
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
        *collision_args,
    )
    return positions, prev_positions


def assert_native_matches_reference(
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
    collision_args,
):
    expected_pos, expected_prev = solve_reference(
        positions.copy(),
        prev_positions.copy(),
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
        *collision_args,
    )

    actual_pos, actual_prev = run_native(
        positions.copy(),
        prev_positions.copy(),
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
        collision_args,
    )

    np.testing.assert_allclose(actual_pos, expected_pos, rtol=1e-5, atol=1e-5)
    np.testing.assert_allclose(actual_prev, expected_prev, rtol=1e-5, atol=1e-5)
    return actual_pos, actual_prev


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
    collision_radii,
    collided_by_groups,
    collider_types,
    collider_groups,
    collider_centers,
    collider_segment_a,
    collider_segment_b,
    collider_radii,
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

        project_collisions(
            positions,
            rest_positions,
            inv_masses,
            collision_radii,
            collided_by_groups,
            collider_types,
            collider_groups,
            collider_centers,
            collider_segment_a,
            collider_segment_b,
            collider_radii,
        )

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

            project_collisions(
                positions,
                rest_positions,
                inv_masses,
                collision_radii,
                collided_by_groups,
                collider_types,
                collider_groups,
                collider_centers,
                collider_segment_a,
                collider_segment_b,
                collider_radii,
            )

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

    assert_native_matches_reference(
        positions,
        prev_positions,
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
        empty_collision_args(len(rest)),
    )

    collision_rest = np.array([[0.2, 0.0, 0.0]], dtype=np.float32)
    collision_pos = collision_rest.copy()
    collision_prev = collision_rest.copy()
    no_i = np.empty(0, dtype=np.int32)
    no_rest = np.empty(0, dtype=np.float32)
    collision_args = (
        np.array([0.25], dtype=np.float32),
        1,
        np.array([0], dtype=np.int32),
        np.array([1], dtype=np.int32),
        np.array([[0.0, 0.0, 0.0]], dtype=np.float32),
        np.array([[0.0, 0.0, 0.0]], dtype=np.float32),
        np.array([[0.0, 0.0, 0.0]], dtype=np.float32),
        np.array([0.5], dtype=np.float32),
    )
    actual_collision_pos, _actual_collision_prev = assert_native_matches_reference(
        collision_pos,
        collision_prev,
        collision_rest,
        np.array([1.0], dtype=np.float32),
        no_i,
        no_i,
        no_rest,
        no_i,
        no_i,
        no_rest,
        np.zeros(3, dtype=np.float32),
        1.0 / 30.0,
        0.0,
        1,
        0,
        0.0,
        0.0,
        collision_args,
    )
    np.testing.assert_allclose(actual_collision_pos, np.array([[0.75, 0.0, 0.0]], dtype=np.float32))

    capsule_args = (
        np.array([0.25], dtype=np.float32),
        1,
        np.array([1], dtype=np.int32),
        np.array([1], dtype=np.int32),
        np.array([[0.0, 0.0, 0.0]], dtype=np.float32),
        np.array([[0.0, -1.0, 0.0]], dtype=np.float32),
        np.array([[0.0, 1.0, 0.0]], dtype=np.float32),
        np.array([0.5], dtype=np.float32),
    )
    capsule_pos, _capsule_prev = assert_native_matches_reference(
        np.array([[0.2, 0.3, 0.0]], dtype=np.float32),
        np.array([[0.2, 0.3, 0.0]], dtype=np.float32),
        np.array([[0.2, 0.3, 0.0]], dtype=np.float32),
        np.array([1.0], dtype=np.float32),
        no_i,
        no_i,
        no_rest,
        no_i,
        no_i,
        no_rest,
        np.zeros(3, dtype=np.float32),
        1.0 / 30.0,
        0.0,
        1,
        0,
        0.0,
        0.0,
        capsule_args,
    )
    np.testing.assert_allclose(capsule_pos, np.array([[0.75, 0.3, 0.0]], dtype=np.float32), atol=1e-6)

    group_filtered_args = (
        np.array([0.25], dtype=np.float32),
        1,
        np.array([0], dtype=np.int32),
        np.array([2], dtype=np.int32),
        np.array([[0.0, 0.0, 0.0]], dtype=np.float32),
        np.array([[0.0, 0.0, 0.0]], dtype=np.float32),
        np.array([[0.0, 0.0, 0.0]], dtype=np.float32),
        np.array([0.5], dtype=np.float32),
    )
    group_filtered_pos, _group_filtered_prev = assert_native_matches_reference(
        collision_pos,
        collision_prev,
        collision_rest,
        np.array([1.0], dtype=np.float32),
        no_i,
        no_i,
        no_rest,
        no_i,
        no_i,
        no_rest,
        np.zeros(3, dtype=np.float32),
        1.0 / 30.0,
        0.0,
        1,
        0,
        0.0,
        0.0,
        group_filtered_args,
    )
    np.testing.assert_allclose(group_filtered_pos, collision_pos, atol=1e-6)

    pinned_pos, _pinned_prev = assert_native_matches_reference(
        collision_pos,
        collision_prev,
        collision_rest,
        np.array([0.0], dtype=np.float32),
        no_i,
        no_i,
        no_rest,
        no_i,
        no_i,
        no_rest,
        np.zeros(3, dtype=np.float32),
        1.0 / 30.0,
        0.0,
        1,
        0,
        0.0,
        0.0,
        collision_args,
    )
    np.testing.assert_allclose(pinned_pos, collision_rest, atol=1e-6)

    dynamic_expected_pos = np.array([[1.5, 0.0, 0.0]], dtype=np.float32)
    dynamic_expected_prev = dynamic_expected_pos.copy()
    dynamic_actual_pos = dynamic_expected_pos.copy()
    dynamic_actual_prev = dynamic_expected_pos.copy()
    for center_x in (3.0, 1.2):
        dynamic_args = (
            np.array([0.25], dtype=np.float32),
            1,
            np.array([0], dtype=np.int32),
            np.array([1], dtype=np.int32),
            np.array([[center_x, 0.0, 0.0]], dtype=np.float32),
            np.array([[center_x, 0.0, 0.0]], dtype=np.float32),
            np.array([[center_x, 0.0, 0.0]], dtype=np.float32),
            np.array([0.5], dtype=np.float32),
        )
        dynamic_expected_pos, dynamic_expected_prev = solve_reference(
            dynamic_expected_pos,
            dynamic_expected_prev,
            np.array([[1.5, 0.0, 0.0]], dtype=np.float32),
            np.array([1.0], dtype=np.float32),
            no_i,
            no_i,
            no_rest,
            no_i,
            no_i,
            no_rest,
            np.zeros(3, dtype=np.float32),
            1.0 / 30.0,
            0.0,
            1,
            0,
            0.0,
            0.0,
            *dynamic_args,
        )
        dynamic_actual_pos, dynamic_actual_prev = run_native(
            dynamic_actual_pos,
            dynamic_actual_prev,
            np.array([[1.5, 0.0, 0.0]], dtype=np.float32),
            np.array([1.0], dtype=np.float32),
            no_i,
            no_i,
            no_rest,
            no_i,
            no_i,
            no_rest,
            np.zeros(3, dtype=np.float32),
            1.0 / 30.0,
            0.0,
            1,
            0,
            0.0,
            0.0,
            dynamic_args,
        )
    np.testing.assert_allclose(dynamic_actual_pos, dynamic_expected_pos, rtol=1e-5, atol=1e-5)
    np.testing.assert_allclose(dynamic_actual_prev, dynamic_expected_prev, rtol=1e-5, atol=1e-5)
    np.testing.assert_allclose(dynamic_actual_pos, np.array([[1.95, 0.0, 0.0]], dtype=np.float32), atol=1e-6)

    try:
        hotools_native.solve_mesh_shape_key_xpbd(
            positions.copy(),
            prev_positions.copy(),
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
            *empty_collision_args(len(rest)),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("out-of-range constraint index did not raise ValueError")

    print("mesh_xpbd_native smoke test passed")


if __name__ == "__main__":
    main()
