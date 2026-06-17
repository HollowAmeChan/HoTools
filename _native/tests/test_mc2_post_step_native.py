import sys
import os
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, os.environ.get("HOTOOLS_NATIVE_TEST_DIR", str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage")))

import hotools_native  # noqa: E402


EPSILON = 0.00000001
FRICTION_DAMPING_RATE = 0.6
STATIC_FRICTION_INCREASE = 0.04
STATIC_FRICTION_DECAY = 0.05
STATIC_FRICTION_VELOCITY_WIDTH = 0.2


def safe_normal(delta):
    length = float(np.linalg.norm(delta))
    if length > EPSILON:
        return delta / length
    return np.asarray((0.0, 0.0, 1.0), dtype=np.float32)


def clamp_vector(vector, max_length):
    limit = max(float(max_length), 0.0)
    if limit <= EPSILON:
        return np.zeros_like(vector, dtype=np.float32)
    length = float(np.linalg.norm(vector))
    if length <= limit or length <= EPSILON:
        return np.ascontiguousarray(vector, dtype=np.float32)
    return np.ascontiguousarray(vector * (limit / length), dtype=np.float32)


def project_on_plane(vector, normal):
    n = safe_normal(normal)
    return np.ascontiguousarray(vector - n * float(np.dot(vector, n)), dtype=np.float32)


def apply_post_step_reference(
    positions,
    old_positions,
    velocity_positions,
    velocities,
    real_velocities,
    friction,
    static_friction,
    collision_normals,
    inv_masses,
    step_dt,
    dynamic_friction,
    static_friction_speed,
    particle_speed_limit,
):
    if step_dt <= EPSILON:
        return

    dynamic_friction = max(0.0, min(1.0, float(dynamic_friction)))
    static_friction_speed = max(float(static_friction_speed), 0.0)

    for vertex_index in range(len(positions)):
        next_position = positions[vertex_index].copy()
        old_position = old_positions[vertex_index].copy()

        if float(inv_masses[vertex_index]) > EPSILON:
            velocity_old_position = velocity_positions[vertex_index].copy()
            contact_normal = collision_normals[vertex_index]
            contact_friction = float(friction[vertex_index])
            has_collision = float(np.dot(contact_normal, contact_normal)) > EPSILON and contact_friction > EPSILON

            static_value = float(static_friction[vertex_index])
            if has_collision and static_friction_speed > 0.0:
                normal = safe_normal(contact_normal)
                tangent_delta = project_on_plane(next_position - old_position, normal)
                tangent_velocity = float(np.linalg.norm(tangent_delta)) / step_dt
                if tangent_velocity < static_friction_speed:
                    static_value = min(1.0, static_value + STATIC_FRICTION_INCREASE)
                else:
                    excess = tangent_velocity - static_friction_speed
                    decay = max(excess / STATIC_FRICTION_VELOCITY_WIDTH, 0.05)
                    static_value = max(0.0, static_value - decay)
                tangent_delta *= static_value
                next_position -= tangent_delta
                velocity_old_position -= tangent_delta
                positions[vertex_index] = next_position
            else:
                static_value = max(0.0, static_value - STATIC_FRICTION_DECAY)
            static_friction[vertex_index] = static_value

            velocity = (next_position - velocity_old_position) / step_dt
            speed_sq = float(np.dot(velocity, velocity))
            if has_collision and dynamic_friction > 0.0 and speed_sq >= EPSILON:
                normal = safe_normal(contact_normal)
                velocity_normal = velocity / max(float(np.sqrt(speed_sq)), EPSILON)
                dot = 0.5 + 0.5 * float(np.dot(normal, velocity_normal))
                dot = dot * dot
                attenuation = (1.0 - dot) * max(0.0, min(1.0, contact_friction * dynamic_friction))
                velocity -= velocity * attenuation

            if particle_speed_limit >= 0.0 and particle_speed_limit > EPSILON:
                velocity = clamp_vector(velocity, particle_speed_limit)
            velocities[vertex_index] = velocity
            friction[vertex_index] = contact_friction * FRICTION_DAMPING_RATE
        else:
            velocities[vertex_index] = np.zeros(3, dtype=np.float32)
            static_friction[vertex_index] = 0.0
            friction[vertex_index] = 0.0

        real_velocities[vertex_index] = (positions[vertex_index] - old_position) / step_dt
        old_positions[vertex_index] = positions[vertex_index]
        velocity_positions[vertex_index] = positions[vertex_index]


def assert_native_matches_reference():
    positions = np.array(
        [
            [0.2, 0.05, 0.0],
            [0.7, 0.0, 0.0],
            [0.1, 0.1, 0.0],
            [0.0, 0.0, 0.2],
        ],
        dtype=np.float32,
    )
    old_positions = np.array(
        [
            [0.0, 0.0, 0.0],
            [0.2, 0.0, 0.0],
            [0.1, 0.1, 0.0],
            [0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    velocity_positions = np.array(
        [
            [-0.1, 0.0, 0.0],
            [0.1, 0.0, 0.0],
            [0.1, 0.1, 0.0],
            [0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    velocities = np.zeros_like(positions)
    real_velocities = np.zeros_like(positions)
    friction = np.array([0.8, 0.5, 0.0, 1.0], dtype=np.float32)
    static_friction = np.array([0.2, 0.4, 0.3, 0.6], dtype=np.float32)
    collision_normals = np.array(
        [
            [0.0, 0.0, 1.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )
    inv_masses = np.array([1.0, 1.0, 1.0, 0.0], dtype=np.float32)

    expected = [array.copy() for array in (
        positions,
        old_positions,
        velocity_positions,
        velocities,
        real_velocities,
        friction,
        static_friction,
    )]
    actual = [array.copy() for array in (
        positions,
        old_positions,
        velocity_positions,
        velocities,
        real_velocities,
        friction,
        static_friction,
    )]

    apply_post_step_reference(
        expected[0],
        expected[1],
        expected[2],
        expected[3],
        expected[4],
        expected[5],
        expected[6],
        collision_normals,
        inv_masses,
        0.05,
        0.7,
        2.0,
        3.0,
    )

    hotools_native.apply_post_step_mc2(
        actual[0],
        actual[1],
        actual[2],
        actual[3],
        actual[4],
        actual[5],
        actual[6],
        collision_normals,
        inv_masses,
        0.05,
        0.7,
        2.0,
        3.0,
    )

    for actual_array, expected_array in zip(actual, expected):
        np.testing.assert_allclose(actual_array, expected_array, rtol=1e-6, atol=1e-6)


def main():
    assert_native_matches_reference()
    print("mc2 post step native smoke test passed")


if __name__ == "__main__":
    main()
