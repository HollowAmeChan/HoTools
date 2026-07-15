"""Blender-independent float32 vector, quaternion, and matrix math."""

from __future__ import annotations

import math

import numpy as np


IDENTITY_QUATERNION_F32 = (0.0, 0.0, 0.0, 1.0)


def normalize_vector_f32(value: np.ndarray) -> np.ndarray:
    length = np.float32(np.linalg.norm(value))
    if length <= np.float32(0.0):
        raise ValueError("cannot normalize a zero vector")
    return np.asarray(value / length, dtype=np.float32)


def normalize_quaternion_f32(
    value: np.ndarray,
    *,
    zero_epsilon=0.0,
    zero_message="cannot normalize a zero quaternion",
) -> np.ndarray:
    length = np.float32(np.linalg.norm(value))
    if length <= np.float32(zero_epsilon):
        raise ValueError(zero_message)
    return np.asarray(value / length, dtype=np.float32)


def quaternion_multiply_f32(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    lx, ly, lz, lw = (np.float32(value) for value in left)
    rx, ry, rz, rw = (np.float32(value) for value in right)
    return np.asarray((
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    ), dtype=np.float32)


def quaternion_inverse_f32(value: np.ndarray) -> np.ndarray:
    conjugate = np.asarray(
        (-value[0], -value[1], -value[2], value[3]),
        dtype=np.float32,
    )
    return normalize_quaternion_f32(conjugate)


def quaternion_conjugate_f32(value: np.ndarray) -> np.ndarray:
    return np.asarray(
        (-value[0], -value[1], -value[2], value[3]),
        dtype=np.float32,
    )


def rotate_vector_f32(rotation: np.ndarray, vector: np.ndarray) -> np.ndarray:
    quaternion = normalize_quaternion_f32(rotation)
    pure = np.asarray((vector[0], vector[1], vector[2], 0.0), dtype=np.float32)
    return quaternion_multiply_f32(
        quaternion_multiply_f32(quaternion, pure),
        quaternion_inverse_f32(quaternion),
    )[:3]


def rotate_vector_unit_quaternion_f32(
    rotation: np.ndarray,
    vector: np.ndarray,
) -> np.ndarray:
    xyz = rotation[:3]
    twice_cross = np.float32(2.0) * np.cross(xyz, vector)
    return np.asarray(
        vector + rotation[3] * twice_cross + np.cross(xyz, twice_cross),
        dtype=np.float32,
    )


def quaternion_slerp_f32(
    first: np.ndarray,
    second: np.ndarray,
    ratio,
) -> np.ndarray:
    ratio = np.float32(ratio)
    first = normalize_quaternion_f32(first)
    target = normalize_quaternion_f32(second)
    dot = np.float32(np.dot(first, target))
    if dot < np.float32(0.0):
        target = -target
        dot = -dot
    dot = np.clip(dot, np.float32(-1.0), np.float32(1.0))
    if dot > np.float32(0.9995):
        return normalize_quaternion_f32(first + (target - first) * ratio)
    theta = np.float32(np.arccos(dot))
    sin_theta = np.float32(np.sin(theta))
    first_weight = np.float32(
        np.sin((np.float32(1.0) - ratio) * theta) / sin_theta
    )
    second_weight = np.float32(np.sin(ratio * theta) / sin_theta)
    return normalize_quaternion_f32(
        first * first_weight + target * second_weight
    )


def quaternion_slerp_unit_f32(
    first: np.ndarray,
    second: np.ndarray,
    ratio,
    *,
    zero_epsilon=0.0,
    zero_message="cannot normalize a zero quaternion",
) -> np.ndarray:
    ratio = np.float32(ratio)
    target = second.copy()
    cosine = np.float32(np.dot(first, target))
    if cosine < np.float32(0.0):
        target = -target
        cosine = -cosine
    if cosine > np.float32(0.9995):
        result = first + (target - first) * ratio
    else:
        angle = np.float32(np.arccos(np.clip(cosine, -1.0, 1.0)))
        sine = np.float32(np.sin(angle))
        first_weight = np.float32(
            np.sin((np.float32(1.0) - ratio) * angle) / sine
        )
        second_weight = np.float32(np.sin(ratio * angle) / sine)
        result = first * first_weight + target * second_weight
    return normalize_quaternion_f32(
        result,
        zero_epsilon=zero_epsilon,
        zero_message=zero_message,
    )


def quaternion_from_to_f32(
    first: np.ndarray,
    second: np.ndarray,
    ratio=1.0,
) -> np.ndarray:
    first = normalize_vector_f32(first)
    second = normalize_vector_f32(second)
    cosine = np.clip(
        np.float32(np.dot(first, second)),
        np.float32(-1.0),
        np.float32(1.0),
    )
    angle = np.float32(np.arccos(cosine))
    axis = np.asarray(np.cross(first, second), dtype=np.float32)
    if abs(np.float32(1.0) + cosine) < np.float32(1.0e-6):
        angle = np.float32(math.pi)
        if first[0] > first[1] and first[0] > first[2]:
            axis = np.asarray(np.cross(first, (0.0, 1.0, 0.0)), dtype=np.float32)
        else:
            axis = np.asarray(np.cross(first, (1.0, 0.0, 0.0)), dtype=np.float32)
    elif abs(np.float32(1.0) - cosine) < np.float32(1.0e-6):
        return np.asarray(IDENTITY_QUATERNION_F32, dtype=np.float32)
    axis = normalize_vector_f32(axis)
    half_angle = np.float32(angle * np.float32(ratio) * np.float32(0.5))
    sine = np.float32(np.sin(half_angle))
    return normalize_quaternion_f32(np.asarray((
        axis[0] * sine,
        axis[1] * sine,
        axis[2] * sine,
        np.float32(np.cos(half_angle)),
    ), dtype=np.float32))


def matrix3_to_quaternion_f32(matrix: np.ndarray) -> np.ndarray:
    m00, m01, m02 = matrix[0]
    m10, m11, m12 = matrix[1]
    m20, m21, m22 = matrix[2]
    trace = np.float32(m00 + m11 + m22)
    if trace > np.float32(0.0):
        scale = np.float32(np.sqrt(trace + np.float32(1.0)) * np.float32(2.0))
        result = (m21 - m12, m02 - m20, m10 - m01, np.float32(0.25) * scale)
        result = (result[0] / scale, result[1] / scale, result[2] / scale, result[3])
    elif m00 > m11 and m00 > m22:
        scale = np.float32(
            np.sqrt(np.float32(1.0) + m00 - m11 - m22) * np.float32(2.0)
        )
        result = (
            np.float32(0.25) * scale,
            (m01 + m10) / scale,
            (m02 + m20) / scale,
            (m21 - m12) / scale,
        )
    elif m11 > m22:
        scale = np.float32(
            np.sqrt(np.float32(1.0) + m11 - m00 - m22) * np.float32(2.0)
        )
        result = (
            (m01 + m10) / scale,
            np.float32(0.25) * scale,
            (m12 + m21) / scale,
            (m02 - m20) / scale,
        )
    else:
        scale = np.float32(
            np.sqrt(np.float32(1.0) + m22 - m00 - m11) * np.float32(2.0)
        )
        result = (
            (m02 + m20) / scale,
            (m12 + m21) / scale,
            np.float32(0.25) * scale,
            (m10 - m01) / scale,
        )
    return normalize_quaternion_f32(np.asarray(result, dtype=np.float32))


def look_rotation_f32(forward: np.ndarray, up: np.ndarray) -> np.ndarray:
    forward = normalize_vector_f32(forward)
    right = normalize_vector_f32(
        np.asarray(np.cross(up, forward), dtype=np.float32)
    )
    corrected_up = np.asarray(np.cross(forward, right), dtype=np.float32)
    matrix = np.column_stack((right, corrected_up, forward)).astype(np.float32)
    return matrix3_to_quaternion_f32(matrix)


def quaternion_matrix_unit_f32(rotation: np.ndarray) -> np.ndarray:
    x, y, z, w = rotation
    two = np.float32(2.0)
    return np.asarray(
        (
            (1.0 - two * (y * y + z * z), two * (x * y - z * w), two * (x * z + y * w)),
            (two * (x * y + z * w), 1.0 - two * (x * x + z * z), two * (y * z - x * w)),
            (two * (x * z - y * w), two * (y * z + x * w), 1.0 - two * (x * x + y * y)),
        ),
        dtype=np.float32,
    )


def transform_point_matrix_f32(position: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    value = np.empty(4, dtype=np.float32)
    value[:3] = position
    value[3] = np.float32(1.0)
    return np.asarray(matrix @ value, dtype=np.float32)[:3]


def transform_vector_matrix_f32(vector: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return np.asarray(matrix[:3, :3] @ vector, dtype=np.float32)
