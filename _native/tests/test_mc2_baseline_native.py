import os
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, os.environ.get("HOTOOLS_NATIVE_TEST_DIR", str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage")))

import hotools_native  # noqa: E402


EPSILON = 0.00000001


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


def quat_rotate(quat, vector):
    q = quat_normalize(np.asarray(quat, dtype=np.float32))
    v = np.asarray(vector, dtype=np.float32)
    uv = np.cross(q[:3], v)
    uuv = np.cross(q[:3], uv)
    return np.ascontiguousarray(v + 2.0 * (q[3] * uv + uuv), dtype=np.float32)


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


def axis_angle_quat(axis, angle_rad):
    axis = np.asarray(axis, dtype=np.float32)
    length = float(np.linalg.norm(axis))
    if length <= EPSILON:
        axis = np.asarray((0.0, 0.0, 1.0), dtype=np.float32)
    else:
        axis = axis / length
    half = float(angle_rad) * 0.5
    s = float(np.sin(half))
    return np.asarray((axis[0] * s, axis[1] * s, axis[2] * s, float(np.cos(half))), dtype=np.float32)


def update_step_basic_reference(
    base_positions,
    base_rotations,
    parents,
    baseline_start,
    baseline_count,
    baseline_data,
    vertex_local_positions,
    vertex_local_rotations,
    animation_pose_ratio=0.0,
):
    step_positions = np.ascontiguousarray(base_positions, dtype=np.float32).copy()
    step_rotations = np.ascontiguousarray(base_rotations, dtype=np.float32).copy()
    ratio = max(0.0, min(1.0, float(animation_pose_ratio)))
    if ratio > 0.99 or len(baseline_data) == 0:
        return step_positions, step_rotations

    for line_index in range(len(baseline_start)):
        start = int(baseline_start[line_index])
        count = int(baseline_count[line_index])
        for data_offset in range(count):
            data_index = start + data_offset
            if data_index < 0 or data_index >= len(baseline_data):
                continue
            vertex_index = int(baseline_data[data_index])
            if vertex_index < 0 or vertex_index >= len(step_positions):
                continue
            parent = int(parents[vertex_index])
            if 0 <= parent < len(step_positions):
                parent_pos = step_positions[parent]
                parent_rot = step_rotations[parent]
                step_positions[vertex_index] = parent_pos + quat_rotate(
                    parent_rot,
                    vertex_local_positions[vertex_index],
                )
                step_rotations[vertex_index] = quat_mul(parent_rot, vertex_local_rotations[vertex_index])
        if ratio > EPSILON:
            for data_offset in range(count):
                data_index = start + data_offset
                if data_index < 0 or data_index >= len(baseline_data):
                    continue
                vertex_index = int(baseline_data[data_index])
                step_positions[vertex_index] = (
                    step_positions[vertex_index] * (1.0 - ratio)
                    + base_positions[vertex_index] * ratio
                )
                step_rotations[vertex_index] = quat_slerp(
                    step_rotations[vertex_index],
                    base_rotations[vertex_index],
                    ratio,
                )
    return np.ascontiguousarray(step_positions, dtype=np.float32), np.ascontiguousarray(step_rotations, dtype=np.float32)


def assert_native_matches_reference(animation_pose_ratio):
    base_positions = np.asarray(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (2.0, 0.2, 0.0),
            (1.0, 1.0, 0.0),
            (-1.0, 0.0, 0.0),
            (-1.0, 1.0, 0.0),
        ),
        dtype=np.float32,
    )
    base_rotations = np.asarray(
        (
            axis_angle_quat((0.0, 0.0, 1.0), 0.1),
            axis_angle_quat((0.0, 1.0, 0.0), 0.2),
            axis_angle_quat((1.0, 0.0, 0.0), -0.25),
            axis_angle_quat((0.0, 0.0, 1.0), 0.5),
            axis_angle_quat((1.0, 0.0, 0.0), 0.3),
            axis_angle_quat((0.0, 1.0, 0.0), -0.4),
        ),
        dtype=np.float32,
    )
    parents = np.asarray((-1, 0, 1, 1, -1, 4), dtype=np.int32)
    baseline_start = np.asarray((0, 4), dtype=np.int32)
    baseline_count = np.asarray((4, 2), dtype=np.int32)
    baseline_data = np.asarray((0, 1, 2, 3, 4, 5), dtype=np.int32)
    vertex_local_positions = np.asarray(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.1, 0.0),
            (1.0, 0.2, 0.3),
            (0.0, 1.0, 0.1),
            (0.0, 0.0, 0.0),
            (0.2, 1.0, 0.0),
        ),
        dtype=np.float32,
    )
    vertex_local_rotations = np.asarray(
        (
            (0.0, 0.0, 0.0, 1.0),
            axis_angle_quat((0.0, 0.0, 1.0), 0.15),
            axis_angle_quat((0.0, 1.0, 0.0), -0.35),
            axis_angle_quat((1.0, 0.0, 0.0), 0.25),
            (0.0, 0.0, 0.0, 1.0),
            axis_angle_quat((0.0, 0.0, 1.0), -0.45),
        ),
        dtype=np.float32,
    )

    expected_positions, expected_rotations = update_step_basic_reference(
        base_positions,
        base_rotations,
        parents,
        baseline_start,
        baseline_count,
        baseline_data,
        vertex_local_positions,
        vertex_local_rotations,
        animation_pose_ratio,
    )
    actual_positions = np.zeros_like(base_positions)
    actual_rotations = np.zeros_like(base_rotations)
    hotools_native.update_step_basic_pose_mc2(
        base_positions,
        base_rotations,
        parents,
        baseline_start,
        baseline_count,
        baseline_data,
        vertex_local_positions,
        vertex_local_rotations,
        actual_positions,
        actual_rotations,
        animation_pose_ratio,
    )
    np.testing.assert_allclose(actual_positions, expected_positions, rtol=2e-5, atol=2e-5)
    np.testing.assert_allclose(actual_rotations, expected_rotations, rtol=2e-5, atol=2e-5)


def main():
    assert_native_matches_reference(0.0)
    assert_native_matches_reference(0.35)
    assert_native_matches_reference(1.0)
    print("mc2 baseline native smoke test passed")


if __name__ == "__main__":
    main()
