"""MC2 Python 后端的数学和 numpy 工具。"""

import hashlib

import mathutils
import numpy as np

from .constants import MC2SystemConstants


def vector3(value, fallback: mathutils.Vector) -> mathutils.Vector:
    if value is None or value == "":
        return fallback.copy()
    try:
        vec = mathutils.Vector(value)
    except Exception:
        return fallback.copy()
    if len(vec) == 0:
        return fallback.copy()
    if len(vec) == 1:
        return mathutils.Vector((vec[0], fallback[1], fallback[2]))
    if len(vec) == 2:
        return mathutils.Vector((vec[0], vec[1], fallback[2]))
    return vec.to_3d()


def matrix_to_numpy(matrix: mathutils.Matrix) -> np.ndarray:
    return np.asarray(
        [[float(matrix[row][col]) for col in range(4)] for row in range(4)],
        dtype=np.float32,
    )


def transform_positions(matrix: np.ndarray, positions: np.ndarray) -> np.ndarray:
    values = np.ascontiguousarray(positions, dtype=np.float32)
    return np.ascontiguousarray(values @ matrix[:3, :3].T + matrix[:3, 3], dtype=np.float32)


def transform_directions(matrix: np.ndarray, directions: np.ndarray) -> np.ndarray:
    values = np.ascontiguousarray(directions, dtype=np.float32)
    transformed = values @ matrix[:3, :3].T
    lengths = np.linalg.norm(transformed, axis=1)
    valid = lengths > MC2SystemConstants.EPSILON
    result = np.zeros_like(transformed, dtype=np.float32)
    result[valid] = transformed[valid] / lengths[valid, None]
    return np.ascontiguousarray(result, dtype=np.float32)


def matrix_world_key(obj) -> tuple:
    matrix = obj.matrix_world
    return tuple(round(float(matrix[row][col]), 8) for row in range(4) for col in range(4))


def matrix_world_3x3_key(obj) -> tuple:
    matrix = obj.matrix_world
    return tuple(round(float(matrix[row][col]), 8) for row in range(3) for col in range(3))


def matrix_scale_radius(matrix: mathutils.Matrix) -> float:
    try:
        scale = matrix.to_scale()
        return max(abs(float(scale.x)), abs(float(scale.y)), abs(float(scale.z)))
    except Exception:
        return 1.0


def array_hash(values: np.ndarray) -> str:
    return hashlib.sha1(np.ascontiguousarray(values).tobytes()).hexdigest()


def clamp_group_mask(value) -> int:
    try:
        return max(0, min(0xFFFF, int(value)))
    except Exception:
        return 0


def collision_group_bit(group) -> int:
    try:
        group_index = max(1, min(16, int(group)))
    except Exception:
        group_index = 1
    return 1 << (group_index - 1)


def vector_to_numpy(value) -> np.ndarray | None:
    if value is None:
        return None
    if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "z"):
        return np.asarray((float(value.x), float(value.y), float(value.z)), dtype=np.float32)
    try:
        array = np.asarray(value, dtype=np.float32).reshape(-1)
    except Exception:
        return None
    if array.size < 3:
        return None
    return np.ascontiguousarray(array[:3], dtype=np.float32)


def closest_point_on_segment_np(point: np.ndarray, segment_a, segment_b) -> np.ndarray | None:
    a = vector_to_numpy(segment_a)
    b = vector_to_numpy(segment_b)
    if a is None or b is None:
        return None

    segment = b - a
    denom = float(np.dot(segment, segment))
    if denom <= MC2SystemConstants.EPSILON:
        return a

    t = float(np.dot(point - a, segment) / denom)
    t = max(0.0, min(1.0, t))
    return a + segment * t


def safe_normal_np(delta: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(delta))
    if length > MC2SystemConstants.EPSILON:
        return delta / length

    fallback_length = float(np.linalg.norm(fallback))
    if fallback_length > MC2SystemConstants.EPSILON:
        return fallback / fallback_length

    return np.asarray((0.0, 0.0, 1.0), dtype=np.float32)


def project_on_plane(vector: np.ndarray, normal: np.ndarray) -> np.ndarray:
    n = safe_normal_np(normal, np.asarray((0.0, 0.0, 1.0), dtype=np.float32))
    return np.ascontiguousarray(vector - n * float(np.dot(vector, n)), dtype=np.float32)


def clamp_vector(vector: np.ndarray, max_length: float) -> np.ndarray:
    limit = max(float(max_length), 0.0)
    if limit <= MC2SystemConstants.EPSILON:
        return np.zeros_like(vector, dtype=np.float32)
    length = float(np.linalg.norm(vector))
    if length <= limit or length <= MC2SystemConstants.EPSILON:
        return np.ascontiguousarray(vector, dtype=np.float32)
    return np.ascontiguousarray(vector * (limit / length), dtype=np.float32)


def world_gravity(gravity_dir) -> np.ndarray:
    gravity = vector3(gravity_dir, mathutils.Vector((0.0, 0.0, -1.0)))
    if gravity.length <= MC2SystemConstants.EPSILON:
        return np.zeros(3, dtype=np.float32)

    gravity.normalize()
    return np.asarray((gravity.x, gravity.y, gravity.z), dtype=np.float32)
