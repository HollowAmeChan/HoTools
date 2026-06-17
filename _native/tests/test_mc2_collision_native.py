import sys
import os
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, os.environ.get("HOTOOLS_NATIVE_TEST_DIR", str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage")))

import hotools_native  # noqa: E402


EPSILON = 0.00000001


def safe_normal(delta, fallback):
    length = float(np.linalg.norm(delta))
    if length > EPSILON:
        return delta / length
    fallback_length = float(np.linalg.norm(fallback))
    if fallback_length > EPSILON:
        return fallback / fallback_length
    return np.asarray((0.0, 0.0, 1.0), dtype=np.float32)


def closest_point_on_segment(point, a, b):
    segment = b - a
    denom = float(np.dot(segment, segment))
    if denom <= EPSILON:
        return a
    t = float(np.dot(point - a, segment) / denom)
    t = max(0.0, min(1.0, t))
    return a + segment * t


def closest_point_ratio(point, a, b):
    segment = b - a
    denom = float(np.dot(segment, segment))
    if denom <= EPSILON:
        return 0.0
    t = float(np.dot(point - a, segment) / denom)
    return max(0.0, min(1.0, t))


def project_collisions_reference(
    positions,
    base_positions,
    inv_masses,
    collision_radii,
    collided_by_groups,
    collider_types,
    collider_group_bits,
    collider_centers,
    collider_segment_a,
    collider_segment_b,
    collider_radii,
    collision_normals,
    friction,
    collider_old_centers=None,
    collider_old_segment_a=None,
    collider_old_segment_b=None,
):
    if len(collider_types) == 0 or not collided_by_groups:
        return

    for vertex_index in range(len(positions)):
        if float(inv_masses[vertex_index]) <= EPSILON:
            continue
        hit_radius = float(collision_radii[vertex_index])
        if hit_radius <= EPSILON:
            continue

        origin = positions[vertex_index].copy()
        fallback = origin - base_positions[vertex_index]
        add_position = np.zeros(3, dtype=np.float32)
        add_normal = np.zeros(3, dtype=np.float32)
        add_count = 0
        friction_normal = np.zeros(3, dtype=np.float32)
        friction_value = 0.0
        friction_range = max(hit_radius, EPSILON)

        for collider_index in range(len(collider_types)):
            if not collided_by_groups & int(collider_group_bits[collider_index]):
                continue

            radius = hit_radius + max(float(collider_radii[collider_index]), 0.0)
            if radius <= EPSILON:
                continue

            if int(collider_types[collider_index]) == 1:
                old_a = (
                    collider_old_segment_a[collider_index]
                    if collider_old_segment_a is not None
                    else collider_segment_a[collider_index]
                )
                old_b = (
                    collider_old_segment_b[collider_index]
                    if collider_old_segment_b is not None
                    else collider_segment_b[collider_index]
                )
                ratio = closest_point_ratio(origin, old_a, old_b)
                old_center = old_a + (old_b - old_a) * ratio
                center = collider_segment_a[collider_index] + (
                    collider_segment_b[collider_index] - collider_segment_a[collider_index]
                ) * ratio
            else:
                center = collider_centers[collider_index]
                old_center = (
                    collider_old_centers[collider_index]
                    if collider_old_centers is not None
                    else center
                )

            delta = origin - old_center
            normal = safe_normal(delta, fallback)
            surface_point = center + normal * radius
            surface_distance = float(np.dot(origin - surface_point, normal))
            if surface_distance <= friction_range:
                collider_distance = max(surface_distance, 0.0)
                near_friction = 1.0 - max(0.0, min(1.0, collider_distance / friction_range))
                if near_friction > friction_value:
                    friction_value = near_friction
                friction_normal += normal
            if surface_distance >= 0.0:
                continue

            add_position += -normal * surface_distance
            add_normal += normal
            add_count += 1

        if add_count <= 0:
            friction_length = float(np.linalg.norm(friction_normal))
            if friction_length <= EPSILON:
                collision_normals[vertex_index] = 0.0
                continue
            collision_normals[vertex_index] = friction_normal / friction_length
            if friction_value > float(friction[vertex_index]):
                friction[vertex_index] = float(friction_value)
            continue

        add_normal /= float(add_count)
        normal_length = float(np.linalg.norm(add_normal))
        if normal_length <= EPSILON:
            collision_normals[vertex_index] = 0.0
            if friction_value > float(friction[vertex_index]):
                friction[vertex_index] = float(friction_value)
            continue

        blend = min(normal_length, 1.0)
        positions[vertex_index] = origin + (add_position / float(add_count)) * blend
        collision_normals[vertex_index] = add_normal / normal_length
        if 1.0 > float(friction[vertex_index]):
            friction[vertex_index] = 1.0


def assert_native_matches_reference():
    positions = np.array(
        [
            [0.4, 0.0, 0.0],
            [0.0, 0.5, 0.0],
            [1.15, 0.0, 0.0],
            [0.2, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    base_positions = np.zeros_like(positions)
    inv_masses = np.array([1.0, 1.0, 1.0, 0.0], dtype=np.float32)
    collision_radii = np.array([0.25, 0.2, 0.25, 0.3], dtype=np.float32)
    collider_types = np.array([0, 1, 0], dtype=np.int32)
    collider_group_bits = np.array([1, 1, 2], dtype=np.int32)
    collider_centers = np.array(
        [
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [0.9, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    collider_segment_a = np.array(
        [
            [0.0, 0.0, 0.0],
            [0.0, -0.25, 0.0],
            [0.9, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    collider_segment_b = np.array(
        [
            [0.0, 0.0, 0.0],
            [0.0, 0.25, 0.0],
            [0.9, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    collider_radii = np.array([0.35, 0.35, 0.5], dtype=np.float32)

    expected_positions = positions.copy()
    expected_normals = np.zeros_like(positions)
    expected_friction = np.zeros(len(positions), dtype=np.float32)
    actual_positions = positions.copy()
    actual_normals = np.zeros_like(positions)
    actual_friction = np.zeros(len(positions), dtype=np.float32)

    args = (
        base_positions,
        inv_masses,
        collision_radii,
        1,
        collider_types,
        collider_group_bits,
        collider_centers,
        collider_segment_a,
        collider_segment_b,
        collider_radii,
    )
    project_collisions_reference(
        expected_positions,
        *args[:3],
        args[3],
        *args[4:],
        expected_normals,
        expected_friction,
    )

    hotools_native.project_collisions_mc2(
        actual_positions,
        base_positions,
        inv_masses,
        collision_radii,
        actual_normals,
        actual_friction,
        1,
        collider_types,
        collider_group_bits,
        collider_centers,
        collider_segment_a,
        collider_segment_b,
        collider_radii,
    )

    np.testing.assert_allclose(actual_positions, expected_positions, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(actual_normals, expected_normals, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(actual_friction, expected_friction, rtol=1e-6, atol=1e-6)


def assert_native_matches_moving_collider_reference():
    positions = np.asarray(((0.0, 0.4, 0.0),), dtype=np.float32)
    base_positions = np.zeros_like(positions)
    inv_masses = np.asarray((1.0,), dtype=np.float32)
    collision_radii = np.asarray((0.25,), dtype=np.float32)
    collider_types = np.asarray((0,), dtype=np.int32)
    collider_group_bits = np.asarray((1,), dtype=np.int32)
    collider_centers = np.asarray(((0.4, 0.0, 0.0),), dtype=np.float32)
    collider_segment_a = collider_centers.copy()
    collider_segment_b = collider_centers.copy()
    collider_old_centers = np.asarray(((0.0, 0.0, 0.0),), dtype=np.float32)
    collider_old_segment_a = collider_old_centers.copy()
    collider_old_segment_b = collider_old_centers.copy()
    collider_radii = np.asarray((0.35,), dtype=np.float32)

    expected_positions = positions.copy()
    expected_normals = np.zeros_like(positions)
    expected_friction = np.zeros(len(positions), dtype=np.float32)
    actual_positions = positions.copy()
    actual_normals = np.zeros_like(positions)
    actual_friction = np.zeros(len(positions), dtype=np.float32)

    project_collisions_reference(
        expected_positions,
        base_positions,
        inv_masses,
        collision_radii,
        1,
        collider_types,
        collider_group_bits,
        collider_centers,
        collider_segment_a,
        collider_segment_b,
        collider_radii,
        expected_normals,
        expected_friction,
        collider_old_centers,
        collider_old_segment_a,
        collider_old_segment_b,
    )
    hotools_native.project_collisions_mc2(
        actual_positions,
        base_positions,
        inv_masses,
        collision_radii,
        actual_normals,
        actual_friction,
        1,
        collider_types,
        collider_group_bits,
        collider_centers,
        collider_segment_a,
        collider_segment_b,
        collider_old_centers,
        collider_old_segment_a,
        collider_old_segment_b,
        collider_radii,
    )

    np.testing.assert_allclose(actual_positions, expected_positions, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(actual_normals, expected_normals, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(actual_friction, expected_friction, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(actual_positions[0], np.asarray((0.0, 0.6, 0.0), dtype=np.float32), atol=1e-6)


def main():
    assert_native_matches_reference()
    assert_native_matches_moving_collider_reference()
    print("mc2 collision native smoke test passed")


if __name__ == "__main__":
    main()
