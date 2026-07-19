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
    / "angle_runtime_001.json"
)

EPSILON = 0.00000001
ANGLE_LIMIT_ITERATION = 3
ANGLE_LIMIT_ATTENUATION = 0.9
ANGLE_RESTORATION_VELOCITY_ATTENUATION = 0.8
ANGLE_RESTORATION_GRAVITY_FALLOFF = 0.0
ANGLE_LIMIT_STIFFNESS = 1.0


def safe_normal(vector, fallback):
    length = float(np.linalg.norm(vector))
    if length > EPSILON:
        return np.asarray(vector / length, dtype=np.float32)
    fallback_length = float(np.linalg.norm(fallback))
    if fallback_length > EPSILON:
        return np.asarray(fallback / fallback_length, dtype=np.float32)
    return np.asarray((0.0, 0.0, 1.0), dtype=np.float32)


def quat_normalize(quat):
    length = float(np.linalg.norm(quat))
    if length <= EPSILON:
        return np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    return np.asarray(quat / length, dtype=np.float32)


def quat_mul(a, b):
    ax, ay, az, aw = (float(a[0]), float(a[1]), float(a[2]), float(a[3]))
    bx, by, bz, bw = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
    return quat_normalize(
        np.asarray(
            (
                aw * bx + ax * bw + ay * bz - az * by,
                aw * by - ax * bz + ay * bw + az * bx,
                aw * bz + ax * by - ay * bx + az * bw,
                aw * bw - ax * bx - ay * by - az * bz,
            ),
            dtype=np.float32,
        )
    )


def quat_inverse(quat):
    q = quat_normalize(np.asarray(quat, dtype=np.float32))
    return np.asarray((-q[0], -q[1], -q[2], q[3]), dtype=np.float32)


def quat_rotate(quat, vector):
    q = quat_normalize(np.asarray(quat, dtype=np.float32))
    v = np.asarray(vector, dtype=np.float32)
    qv = q[:3]
    uv = np.cross(qv, v)
    uuv = np.cross(qv, uv)
    return np.ascontiguousarray(v + 2.0 * (q[3] * uv + uuv), dtype=np.float32)


def from_to_rotation(source, target, ratio=1.0):
    ratio = max(0.0, min(1.0, float(ratio)))
    src = safe_normal(source, np.asarray((0.0, 0.0, 1.0), dtype=np.float32))
    dst = safe_normal(target, src)
    dot = max(-1.0, min(1.0, float(np.dot(src, dst))))
    if dot > 1.0 - EPSILON or ratio <= EPSILON:
        return np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    if dot < -1.0 + EPSILON:
        helper = (
            np.asarray((0.0, 1.0, 0.0), dtype=np.float32)
            if float(src[0]) > float(src[1]) and float(src[0]) > float(src[2])
            else np.asarray((1.0, 0.0, 0.0), dtype=np.float32)
        )
        axis = safe_normal(np.cross(src, helper), np.asarray((0.0, 0.0, 1.0), dtype=np.float32))
        angle = np.pi * ratio
    else:
        axis = safe_normal(np.cross(src, dst), np.asarray((0.0, 0.0, 1.0), dtype=np.float32))
        angle = float(np.arccos(dot)) * ratio
    half = angle * 0.5
    s = float(np.sin(half))
    return np.asarray((axis[0] * s, axis[1] * s, axis[2] * s, float(np.cos(half))), dtype=np.float32)


def clamp_vector_angle(vector, target, angle_rad):
    length = float(np.linalg.norm(vector))
    if length <= EPSILON:
        return np.ascontiguousarray(vector, dtype=np.float32)
    target_length = float(np.linalg.norm(target))
    if target_length <= EPSILON:
        return np.ascontiguousarray(vector, dtype=np.float32)
    v_dir = vector / length
    t_dir = target / target_length
    dot = max(-1.0, min(1.0, float(np.dot(v_dir, t_dir))))
    current_angle = float(np.arccos(dot))
    if current_angle <= angle_rad:
        return np.ascontiguousarray(vector, dtype=np.float32)
    q = from_to_rotation(t_dir, v_dir, max(float(angle_rad), 0.0) / max(current_angle, EPSILON))
    return np.ascontiguousarray(quat_rotate(q, t_dir) * length, dtype=np.float32)


def project_angle_reference(
    positions,
    inv_masses,
    parent_indices,
    baseline_start,
    baseline_count,
    baseline_data,
    step_basic_positions,
    step_basic_rotations,
    restoration_values,
    limit_values,
    velocity_positions,
):
    if len(baseline_data) == 0:
        return

    restoration_values = np.clip(restoration_values, 0.0, 1.0)
    use_limit = len(limit_values) == len(positions) and bool(np.any(limit_values > EPSILON))
    use_restoration = bool(np.any(restoration_values > EPSILON))
    if not use_restoration and not use_limit:
        return

    gravity_falloff = max(0.0, min(1.0, 1.0 - ANGLE_RESTORATION_GRAVITY_FALLOFF))
    restoration_attenuation = max(0.0, min(1.0, ANGLE_RESTORATION_VELOCITY_ATTENUATION))
    limit_stiffness = max(0.0, min(1.0, ANGLE_LIMIT_STIFFNESS))

    length_buffer = np.zeros(len(positions), dtype=np.float32)
    local_pos_buffer = np.zeros((len(positions), 3), dtype=np.float32)
    local_rot_buffer = np.zeros((len(positions), 4), dtype=np.float32)
    rotation_buffer = np.ascontiguousarray(step_basic_rotations, dtype=np.float32).copy()
    restoration_vector_buffer = np.zeros((len(positions), 3), dtype=np.float32)

    for line_index in range(len(baseline_start)):
        start = int(baseline_start[line_index])
        count = int(baseline_count[line_index])
        if count <= 1:
            continue

        for offset in range(count):
            data_index = start + offset
            vertex_index = int(baseline_data[data_index])
            rotation_buffer[vertex_index] = step_basic_rotations[vertex_index]
            if offset <= 0:
                continue
            parent_index = int(parent_indices[vertex_index])
            base_vector = step_basic_positions[vertex_index] - step_basic_positions[parent_index]
            if use_limit:
                current_vector = positions[vertex_index] - positions[parent_index]
                current_length = float(np.linalg.norm(current_vector))
                base_length = float(np.linalg.norm(base_vector))
                if current_length > EPSILON and base_length > EPSILON:
                    parent_rot_inv = quat_inverse(step_basic_rotations[parent_index])
                    length_buffer[vertex_index] = current_length
                    local_pos_buffer[vertex_index] = quat_rotate(parent_rot_inv, base_vector / base_length)
                    local_rot_buffer[vertex_index] = quat_mul(parent_rot_inv, step_basic_rotations[vertex_index])
                else:
                    length_buffer[vertex_index] = 0.0
                    local_pos_buffer[vertex_index] = 0.0
                    local_rot_buffer[vertex_index] = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
            if use_restoration:
                restoration_vector_buffer[vertex_index] = base_vector

        for iteration in range(ANGLE_LIMIT_ITERATION):
            iteration_den = max(ANGLE_LIMIT_ITERATION - 1, 1)
            iteration_ratio = float(iteration) / float(iteration_den)
            limit_rot_ratio = 0.4
            restoration_rot_ratio = 0.1 + (0.5 - 0.1) * iteration_ratio

            for offset in range(1, count):
                data_index = start + offset
                child_index = int(baseline_data[data_index])
                parent_index = int(parent_indices[child_index])
                child_inv_mass = float(inv_masses[child_index])
                parent_inv_mass = float(inv_masses[parent_index])
                if child_inv_mass <= EPSILON:
                    continue

                child_pos = positions[child_index].copy()
                parent_pos = positions[parent_index].copy()

                if use_limit:
                    parent_rot = rotation_buffer[parent_index]
                    local_pos = local_pos_buffer[child_index]
                    local_rot = local_rot_buffer[child_index]
                    vector = child_pos - parent_pos
                    vector_len = float(np.linalg.norm(vector))
                    target_vector = quat_rotate(parent_rot, local_pos)
                    target_len = float(np.linalg.norm(target_vector))
                    if vector_len > EPSILON and target_len <= EPSILON:
                        add = parent_pos - child_pos
                        child_pos = parent_pos.copy()
                        positions[child_index] = child_pos
                        velocity_positions[child_index] += add
                        rotation_buffer[child_index] = quat_mul(parent_rot, local_rot)
                        vector = None
                    elif vector_len > EPSILON and target_len > EPSILON:
                        vector_dir = vector / vector_len
                        target_dir = target_vector / target_len
                        blend_len = vector_len * 0.5 + float(length_buffer[child_index]) * 0.5
                        vector = vector_dir * blend_len if blend_len > EPSILON else None
                    else:
                        vector = None

                    if vector is not None:
                        max_angle_rad = np.deg2rad(max(0.0, float(limit_values[child_index])))
                        angle = float(np.arccos(max(-1.0, min(1.0, float(np.dot(vector_dir, target_dir))))))
                        result_vector = vector
                        if angle > max_angle_rad:
                            recovery_angle = angle * (1.0 - limit_stiffness) + max_angle_rad * limit_stiffness
                            result_vector = clamp_vector_angle(vector, target_vector, recovery_angle)

                        rot_pos = parent_pos + vector * limit_rot_ratio
                        parent_final = rot_pos - result_vector * limit_rot_ratio
                        child_final = rot_pos + result_vector * (1.0 - limit_rot_ratio)
                        parent_add = (parent_final - parent_pos) * parent_inv_mass
                        child_add = (child_final - child_pos) * child_inv_mass

                        child_pos += child_add
                        positions[child_index] = child_pos
                        velocity_positions[child_index] += child_add * ANGLE_LIMIT_ATTENUATION
                        if parent_inv_mass > EPSILON:
                            parent_pos += parent_add
                            positions[parent_index] = parent_pos
                            velocity_positions[parent_index] += parent_add * ANGLE_LIMIT_ATTENUATION

                        corrected_vector = child_pos - parent_pos
                        corrected_len = float(np.linalg.norm(corrected_vector))
                        if corrected_len > EPSILON:
                            next_rot = quat_mul(parent_rot, local_rot)
                            q = from_to_rotation(
                                target_vector / max(target_len, EPSILON),
                                corrected_vector / corrected_len,
                            )
                            rotation_buffer[child_index] = quat_mul(q, next_rot)

                if not use_restoration:
                    continue
                restoration_stiffness_value = float(restoration_values[child_index]) * gravity_falloff
                if restoration_stiffness_value <= EPSILON:
                    continue

                child_pos = positions[child_index].copy()
                parent_pos = positions[parent_index].copy()
                target_vector = restoration_vector_buffer[child_index]
                target_len = float(np.linalg.norm(target_vector))
                vector = child_pos - parent_pos
                vector_len = float(np.linalg.norm(vector))
                if target_len <= EPSILON:
                    add = parent_pos - child_pos
                    positions[child_index] = parent_pos
                    velocity_positions[child_index] += add
                    continue
                if vector_len <= EPSILON:
                    continue

                q = from_to_rotation(vector / vector_len, target_vector / target_len, restoration_stiffness_value)
                result_vector = quat_rotate(q, vector)
                rot_pos = parent_pos + vector * restoration_rot_ratio
                parent_final = rot_pos - result_vector * restoration_rot_ratio
                child_final = rot_pos + result_vector * (1.0 - restoration_rot_ratio)
                parent_add = (parent_final - parent_pos) * parent_inv_mass
                child_add = (child_final - child_pos) * child_inv_mass

                child_pos += child_add
                positions[child_index] = child_pos
                velocity_positions[child_index] += child_add * restoration_attenuation
                if parent_inv_mass > EPSILON:
                    parent_pos += parent_add
                    positions[parent_index] = parent_pos
                    velocity_positions[parent_index] += parent_add * restoration_attenuation


def assert_native_matches_reference():
    positions = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.05, 0.15, 0.0],
            [2.05, 0.75, 0.15],
            [3.05, 1.35, -0.1],
            [0.0, 1.0, 0.0],
            [0.95, 1.15, 0.2],
            [1.8, 1.35, 0.55],
        ],
        dtype=np.float32,
    )
    inv_masses = np.array([0.0, 1.0, 0.9, 1.1, 0.0, 1.0, 0.8], dtype=np.float32)
    parent_indices = np.array([-1, 0, 1, 2, -1, 4, 5], dtype=np.int32)
    baseline_start = np.array([0, 4], dtype=np.int32)
    baseline_count = np.array([4, 3], dtype=np.int32)
    baseline_data = np.array([0, 1, 2, 3, 4, 5, 6], dtype=np.int32)
    step_basic_positions = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [3.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
            [2.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    step_basic_rotations = np.zeros((7, 4), dtype=np.float32)
    step_basic_rotations[:, 3] = 1.0
    restoration_values = np.array([0.0, 0.8, 0.7, 0.6, 0.0, 0.9, 0.75], dtype=np.float32)
    limit_values = np.array([0.0, 35.0, 25.0, 20.0, 0.0, 30.0, 18.0], dtype=np.float32)

    expected_positions = positions.copy()
    expected_velocity_positions = positions.copy()
    actual_positions = positions.copy()
    actual_velocity_positions = positions.copy()

    project_angle_reference(
        expected_positions,
        inv_masses,
        parent_indices,
        baseline_start,
        baseline_count,
        baseline_data,
        step_basic_positions,
        step_basic_rotations,
        restoration_values,
        limit_values,
        expected_velocity_positions,
    )

    hotools_native.project_angle_constraints_mc2(
        actual_positions,
        inv_masses,
        parent_indices,
        baseline_start,
        baseline_count,
        baseline_data,
        step_basic_positions,
        step_basic_rotations,
        restoration_values,
        limit_values,
        actual_velocity_positions,
        ANGLE_RESTORATION_VELOCITY_ATTENUATION,
        ANGLE_RESTORATION_GRAVITY_FALLOFF,
        ANGLE_LIMIT_STIFFNESS,
    )

    np.testing.assert_allclose(actual_positions, expected_positions, rtol=1e-5, atol=1e-5)
    np.testing.assert_allclose(actual_velocity_positions, expected_velocity_positions, rtol=1e-5, atol=1e-5)


def assert_native_matches_tier_a_oracle():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["oracle_tier"] == "A"
    assert fixture["mc2_commit"] == "418f89ff31a45bb4b2336641ad5907a1110eabea"
    values = fixture["input"]
    expected = fixture["expected"]

    attributes = np.asarray(values["attributes"], dtype=np.uint8)
    positions = np.asarray(values["next_positions"], dtype=np.float32)
    velocity_positions = np.asarray(values["velocity_positions"], dtype=np.float32)
    depths = np.asarray(values["depths"], dtype=np.float32)
    inv_masses = np.asarray((attributes & 0x02) != 0, dtype=np.float32)
    restoration_values = np.full(
        len(positions),
        values["restoration_stiffness"] * values["simulation_power"][3],
        dtype=np.float32,
    )
    limit_values = np.full(
        len(positions), values["limit_angle_degrees"], dtype=np.float32
    )

    hotools_native.project_angle_constraints_mc2(
        positions,
        inv_masses,
        np.asarray(values["parent_indices"], dtype=np.int32),
        np.asarray(values["baseline_start"], dtype=np.int32),
        np.asarray(values["baseline_count"], dtype=np.int32),
        np.asarray(values["baseline_data"], dtype=np.int32),
        np.asarray(values["step_basic_positions"], dtype=np.float32),
        np.asarray(values["step_basic_rotations_xyzw"], dtype=np.float32),
        restoration_values,
        limit_values,
        velocity_positions,
        values["restoration_velocity_attenuation"],
        values["restoration_gravity_falloff"],
        values["limit_stiffness"],
    )

    np.testing.assert_allclose(
        positions,
        np.asarray(expected["next_positions"], dtype=np.float32),
        rtol=1e-5,
        atol=1e-5,
    )
    np.testing.assert_allclose(
        velocity_positions,
        np.asarray(expected["velocity_positions"], dtype=np.float32),
        rtol=1e-5,
        atol=1e-5,
    )
    np.testing.assert_allclose(
        np.asarray(expected["length_scratch_after"], dtype=np.float32),
        np.zeros(len(depths), dtype=np.float32),
        rtol=0.0,
        atol=0.0,
    )
    np.testing.assert_allclose(
        np.asarray(expected["local_position_scratch_after"], dtype=np.float32),
        np.zeros((len(depths), 3), dtype=np.float32),
        rtol=0.0,
        atol=0.0,
    )
    np.testing.assert_allclose(
        np.asarray(expected["restoration_scratch_after"], dtype=np.float32),
        np.zeros((len(depths), 3), dtype=np.float32),
        rtol=0.0,
        atol=0.0,
    )


def test_angle_restoration_identity_is_exact_noop():
    positions = np.asarray((
        (0.17, 0.23, -0.11),
        (0.20, 0.50, 0.03),
        (0.31, 0.74, 0.19),
        (0.47, 0.91, 0.38),
    ), dtype=np.float32)
    initial_positions = positions.copy()
    velocity_positions = np.asarray((
        (0.01, -0.02, 0.03),
        (0.04, 0.05, -0.06),
        (-0.07, 0.08, 0.09),
        (0.10, -0.11, 0.12),
    ), dtype=np.float32)
    initial_velocity_positions = velocity_positions.copy()
    rotations = np.zeros((len(positions), 4), dtype=np.float32)
    rotations[:, 3] = 1.0
    restoration = np.asarray((0.0, 0.85, 0.85, 0.85), dtype=np.float32)
    limit = np.zeros((len(positions),), dtype=np.float32)
    for _ in range(10000):
        hotools_native.project_angle_constraints_mc2(
            positions,
            np.asarray((0.0, 1.0, 1.0, 1.0), dtype=np.float32),
            np.asarray((-1, 0, 1, 2), dtype=np.int32),
            np.asarray((0,), dtype=np.int32),
            np.asarray((4,), dtype=np.int32),
            np.asarray((0, 1, 2, 3), dtype=np.int32),
            initial_positions,
            rotations,
            restoration,
            limit,
            velocity_positions,
            0.25,
            0.0,
            1.0,
        )
    np.testing.assert_array_equal(positions, initial_positions)
    np.testing.assert_array_equal(velocity_positions, initial_velocity_positions)


def main():
    assert_native_matches_reference()
    assert_native_matches_tier_a_oracle()
    print("mc2 angle native smoke test passed")


if __name__ == "__main__":
    main()
