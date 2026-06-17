import os
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, os.environ.get("HOTOOLS_NATIVE_TEST_DIR", str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage")))

import hotools_native  # noqa: E402


EPSILON = 0.00000001


def safe_normal(vector, fallback):
    length = float(np.linalg.norm(vector))
    if length > EPSILON:
        return np.asarray(vector / length, dtype=np.float32)
    fallback_length = float(np.linalg.norm(fallback))
    if fallback_length > EPSILON:
        return np.asarray(fallback / fallback_length, dtype=np.float32)
    return np.asarray((0.0, 0.0, 1.0), dtype=np.float32)


def project_on_plane(vector, normal):
    n = safe_normal(normal, np.asarray((0.0, 0.0, 1.0), dtype=np.float32))
    return np.ascontiguousarray(vector - n * float(np.dot(vector, n)), dtype=np.float32)


def quat_normalize(quat):
    length = float(np.linalg.norm(quat))
    if length <= EPSILON:
        return np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    return np.asarray(quat / length, dtype=np.float32)


def quat_slerp(a, b, ratio):
    t = max(0.0, min(1.0, float(ratio)))
    qa = quat_normalize(np.asarray(a, dtype=np.float32))
    qb = quat_normalize(np.asarray(b, dtype=np.float32))
    dot = float(np.dot(qa, qb))
    if dot < 0.0:
        qb = -qb
        dot = -dot
    if dot > 0.9995:
        return quat_normalize(qa + (qb - qa) * t)
    theta0 = float(np.arccos(max(-1.0, min(1.0, dot))))
    theta = theta0 * t
    sin_theta = float(np.sin(theta))
    sin_theta0 = float(np.sin(theta0))
    s0 = float(np.cos(theta)) - dot * sin_theta / sin_theta0
    s1 = sin_theta / sin_theta0
    return quat_normalize(s0 * qa + s1 * qb)


def quat_rotate(quat, vector):
    q = quat_normalize(np.asarray(quat, dtype=np.float32))
    v = np.asarray(vector, dtype=np.float32)
    uv = np.cross(q[:3], v)
    uuv = np.cross(q[:3], uv)
    return np.ascontiguousarray(v + 2.0 * (q[3] * uv + uuv), dtype=np.float32)


def axis_angle_quat(axis, angle_rad):
    n = safe_normal(np.asarray(axis, dtype=np.float32), np.asarray((0.0, 0.0, 1.0), dtype=np.float32))
    half = float(angle_rad) * 0.5
    s = float(np.sin(half))
    return np.asarray((n[0] * s, n[1] * s, n[2] * s, float(np.cos(half))), dtype=np.float32)


def apply_substep_inertia_reference(
    old_positions,
    velocities,
    depths,
    inv_masses,
    old_world_position,
    step_vector,
    step_rotation,
    inertia_vector,
    inertia_rotation,
    depth_inertia,
):
    depth_inertia = max(0.0, min(1.0, float(depth_inertia)))
    for vertex_index in range(len(old_positions)):
        if float(inv_masses[vertex_index]) <= EPSILON:
            continue
        depth = max(0.0, min(1.0, float(depths[vertex_index])))
        ratio = depth_inertia * (1.0 - depth * depth)
        vector = inertia_vector * (1.0 - ratio) + step_vector * ratio
        rotation = quat_slerp(inertia_rotation, step_rotation, ratio)
        local = old_positions[vertex_index] - old_world_position
        old_positions[vertex_index] = old_world_position + quat_rotate(rotation, local) + vector
        velocities[vertex_index] = quat_rotate(rotation, velocities[vertex_index])


def apply_centrifugal_velocity_reference(
    positions,
    velocities,
    depths,
    inv_masses,
    now_world_position,
    rotation_axis,
    angular_velocity,
    centrifugal,
):
    centrifugal = max(0.0, min(1.0, float(centrifugal)))
    if centrifugal <= EPSILON or float(angular_velocity) <= EPSILON:
        return
    if float(np.linalg.norm(rotation_axis)) <= EPSILON:
        return
    axis = safe_normal(rotation_axis, np.asarray((0.0, 1.0, 0.0), dtype=np.float32))
    for vertex_index in range(len(positions)):
        if float(inv_masses[vertex_index]) <= EPSILON:
            continue
        velocity = velocities[vertex_index]
        speed = float(np.linalg.norm(velocity))
        if speed <= EPSILON:
            continue
        local = positions[vertex_index] - now_world_position
        radial = project_on_plane(local, axis)
        radius = float(np.linalg.norm(radial))
        if radius <= EPSILON:
            continue
        n = radial / radius
        tangent = safe_normal(np.cross(axis, n), np.zeros(3, dtype=np.float32))
        forward = velocity / speed
        strength = max(0.0, float(np.dot(forward, tangent)))
        depth = max(0.0, min(1.0, float(depths[vertex_index])))
        mass = 1.0 + (1.0 - depth)
        force = mass * float(angular_velocity) * float(angular_velocity) * radius
        velocities[vertex_index] = velocity + n * (force * centrifugal * 0.02 * strength)


def assert_substep_inertia_matches_reference():
    old_positions = np.asarray(
        (
            (1.0, 0.0, 0.0),
            (0.0, 2.0, 0.0),
            (-1.0, 0.5, 0.0),
            (0.2, -0.3, 1.4),
        ),
        dtype=np.float32,
    )
    velocities = np.asarray(
        (
            (0.0, 1.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0),
            (0.6, -0.2, 0.3),
        ),
        dtype=np.float32,
    )
    depths = np.asarray((0.0, 0.5, 1.0, 0.25), dtype=np.float32)
    inv_masses = np.asarray((1.0, 0.0, 0.7, 0.2), dtype=np.float32)
    old_world_position = np.asarray((0.25, -0.25, 0.1), dtype=np.float32)
    step_vector = np.asarray((0.1, 0.2, -0.05), dtype=np.float32)
    step_rotation = axis_angle_quat((0.0, 0.0, 1.0), np.deg2rad(70.0))
    inertia_vector = np.asarray((-0.03, 0.02, 0.01), dtype=np.float32)
    inertia_rotation = axis_angle_quat((1.0, 0.0, 0.0), np.deg2rad(-20.0))

    expected_positions = old_positions.copy()
    expected_velocities = velocities.copy()
    actual_positions = old_positions.copy()
    actual_velocities = velocities.copy()

    apply_substep_inertia_reference(
        expected_positions,
        expected_velocities,
        depths,
        inv_masses,
        old_world_position,
        step_vector,
        step_rotation,
        inertia_vector,
        inertia_rotation,
        0.8,
    )
    hotools_native.apply_substep_inertia_mc2(
        actual_positions,
        actual_velocities,
        depths,
        inv_masses,
        old_world_position,
        step_vector,
        step_rotation,
        inertia_vector,
        inertia_rotation,
        0.8,
    )

    np.testing.assert_allclose(actual_positions, expected_positions, rtol=2e-5, atol=2e-5)
    np.testing.assert_allclose(actual_velocities, expected_velocities, rtol=2e-5, atol=2e-5)


def assert_centrifugal_matches_reference():
    positions = np.asarray(
        (
            (2.0, 0.0, 0.0),
            (0.0, 2.0, 0.0),
            (0.0, 0.0, 3.0),
            (1.0, 1.0, 0.0),
            (-2.0, 0.0, 0.0),
        ),
        dtype=np.float32,
    )
    velocities = np.asarray(
        (
            (0.0, 2.0, 0.0),
            (-2.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, -1.0, 0.0),
        ),
        dtype=np.float32,
    )
    depths = np.asarray((0.0, 0.5, 1.0, 0.2, 0.4), dtype=np.float32)
    inv_masses = np.asarray((1.0, 1.0, 1.0, 0.0, 1.0), dtype=np.float32)
    now_world_position = np.zeros(3, dtype=np.float32)
    rotation_axis = np.asarray((0.0, 0.0, 2.0), dtype=np.float32)

    expected = velocities.copy()
    actual = velocities.copy()
    apply_centrifugal_velocity_reference(
        positions,
        expected,
        depths,
        inv_masses,
        now_world_position,
        rotation_axis,
        3.0,
        0.7,
    )
    hotools_native.apply_centrifugal_velocity_mc2(
        positions,
        actual,
        depths,
        inv_masses,
        now_world_position,
        rotation_axis,
        3.0,
        0.7,
    )
    np.testing.assert_allclose(actual, expected, rtol=2e-5, atol=2e-5)

    zero_axis_actual = velocities.copy()
    hotools_native.apply_centrifugal_velocity_mc2(
        positions,
        zero_axis_actual,
        depths,
        inv_masses,
        now_world_position,
        np.zeros(3, dtype=np.float32),
        3.0,
        0.7,
    )
    np.testing.assert_allclose(zero_axis_actual, velocities, rtol=0.0, atol=0.0)


def main():
    assert_substep_inertia_matches_reference()
    assert_centrifugal_matches_reference()
    print("mc2 inertia native smoke test passed")


if __name__ == "__main__":
    main()
