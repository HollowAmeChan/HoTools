"""MC2 Python 后端的数学和 numpy 工具。"""

import hashlib
import math

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


def transform_vectors(matrix: np.ndarray, vectors: np.ndarray) -> np.ndarray:
    values = np.ascontiguousarray(vectors, dtype=np.float32)
    return np.ascontiguousarray(values @ matrix[:3, :3].T, dtype=np.float32)


def matrix_world_key(obj) -> tuple:
    matrix = obj.matrix_world
    return tuple(round(float(matrix[row][col]), 8) for row in range(4) for col in range(4))


def matrix_world_3x3_key(obj) -> tuple:
    matrix = obj.matrix_world
    return tuple(round(float(matrix[row][col]), 8) for row in range(3) for col in range(3))


def matrix_scale_radius(matrix: mathutils.Matrix) -> float:
    try:
        values = matrix_to_numpy(matrix)[:3, :3]
        axis_lengths = np.linalg.norm(values, axis=0)
        return float(np.max(axis_lengths))
    except Exception:
        return 1.0


def matrix_scale_ratio(matrix: mathutils.Matrix, init_scale_radius: float) -> float:
    base = max(abs(float(init_scale_radius)), MC2SystemConstants.EPSILON)
    return max(matrix_scale_radius(matrix) / base, MC2SystemConstants.EPSILON)


def matrix_negative_scale_sign(matrix: mathutils.Matrix) -> int:
    try:
        return -1 if float(matrix.to_3x3().determinant()) < 0.0 else 1
    except Exception:
        return 1


def object_negative_scale_sign(obj) -> int:
    direction = object_negative_scale_direction(obj)
    return -1 if np.any(direction < 0.0) else 1


def object_negative_scale_direction(obj) -> np.ndarray:
    direction = np.ones(3, dtype=np.float32)
    current = obj
    while current is not None:
        scale = getattr(current, "scale", None)
        if scale is not None:
            direction *= np.asarray(
                (
                    -1.0 if float(scale.x) < 0.0 else 1.0,
                    -1.0 if float(scale.y) < 0.0 else 1.0,
                    -1.0 if float(scale.z) < 0.0 else 1.0,
                ),
                dtype=np.float32,
            )
        current = getattr(current, "parent", None)
    if np.all(direction > 0.0) and matrix_negative_scale_sign(obj.matrix_world) < 0:
        direction[0] = -1.0
    return np.ascontiguousarray(direction, dtype=np.float32)


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


# ---------------------------------------------------------------------------
# 四元数工具（供 baseline.py / inertia.py 共享）
# 约定：quat = (x, y, z, w)，float32，形状 (4,)
# ---------------------------------------------------------------------------

_IDENTITY_QUAT = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)


def quat_normalize(quat: np.ndarray) -> np.ndarray:
    """归一化四元数；零向量时返回单位四元数。"""
    length = float(np.linalg.norm(quat))
    if length <= MC2SystemConstants.EPSILON:
        return _IDENTITY_QUAT.copy()
    return np.asarray(quat / length, dtype=np.float32)


def quat_from_matrix(matrix: np.ndarray) -> np.ndarray:
    """从 3×3 旋转矩阵构造四元数（Shepperd 方法）。"""
    m = np.asarray(matrix, dtype=np.float32)
    trace = float(m[0, 0] + m[1, 1] + m[2, 2])
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        return quat_normalize(np.asarray(
            ((m[2, 1] - m[1, 2]) / s,
             (m[0, 2] - m[2, 0]) / s,
             (m[1, 0] - m[0, 1]) / s,
             0.25 * s),
            dtype=np.float32,
        ))
    if m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
        return quat_normalize(np.asarray(
            (0.25 * s,
             (m[0, 1] + m[1, 0]) / s,
             (m[0, 2] + m[2, 0]) / s,
             (m[2, 1] - m[1, 2]) / s),
            dtype=np.float32,
        ))
    if m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
        return quat_normalize(np.asarray(
            ((m[0, 1] + m[1, 0]) / s,
             0.25 * s,
             (m[1, 2] + m[2, 1]) / s,
             (m[0, 2] - m[2, 0]) / s),
            dtype=np.float32,
        ))
    s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
    return quat_normalize(np.asarray(
        ((m[0, 2] + m[2, 0]) / s,
         (m[1, 2] + m[2, 1]) / s,
         0.25 * s,
         (m[1, 0] - m[0, 1]) / s),
        dtype=np.float32,
    ))


def quat_dot_abs(a: np.ndarray, b: np.ndarray) -> float:
    """两个四元数归一化后点积的绝对值（用于角度比较，忽略符号）。"""
    return abs(float(np.dot(quat_normalize(a), quat_normalize(b))))


def identity_quat() -> np.ndarray:
    """返回单位四元数 (x=0, y=0, z=0, w=1) 的副本。"""
    return _IDENTITY_QUAT.copy()


def quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """四元数乘法 a * b，结果归一化。约定 (x, y, z, w)。"""
    ax, ay, az, aw = float(a[0]), float(a[1]), float(a[2]), float(a[3])
    bx, by, bz, bw = float(b[0]), float(b[1]), float(b[2]), float(b[3])
    return quat_normalize(np.asarray(
        (aw * bx + ax * bw + ay * bz - az * by,
         aw * by - ax * bz + ay * bw + az * bx,
         aw * bz + ax * by - ay * bx + az * bw,
         aw * bw - ax * bx - ay * by - az * bz),
        dtype=np.float32,
    ))


def quat_inverse(quat: np.ndarray) -> np.ndarray:
    """归一化四元数的逆（共轭）。"""
    q = quat_normalize(np.asarray(quat, dtype=np.float32))
    return np.asarray((-q[0], -q[1], -q[2], q[3]), dtype=np.float32)


def quat_rotate(quat: np.ndarray, vector: np.ndarray) -> np.ndarray:
    """用四元数旋转三维向量（Rodrigues 公式）。"""
    q = quat_normalize(np.asarray(quat, dtype=np.float32))
    v = np.asarray(vector, dtype=np.float32)
    qv = q[:3]
    uv = np.cross(qv, v)
    uuv = np.cross(qv, uv)
    return np.ascontiguousarray(v + 2.0 * (q[3] * uv + uuv), dtype=np.float32)


def quat_slerp(a: np.ndarray, b: np.ndarray, ratio: float) -> np.ndarray:
    """球面线性插值：ratio=0 返回 a，ratio=1 返回 b。"""
    t = max(0.0, min(1.0, float(ratio)))
    qa = quat_normalize(a)
    qb = quat_normalize(b)
    dot = float(np.dot(qa, qb))
    if dot < 0.0:
        qb = -qb
        dot = -dot
    if dot > 0.9995:
        return quat_normalize(qa + (qb - qa) * t)
    theta0 = math.acos(max(-1.0, min(1.0, dot)))
    theta = theta0 * t
    sin_theta0 = math.sin(theta0)
    s0 = math.cos(theta) - dot * math.sin(theta) / sin_theta0
    s1 = math.sin(theta) / sin_theta0
    return quat_normalize((s0 * qa) + (s1 * qb))


def quat_angle(a: np.ndarray, b: np.ndarray) -> float:
    """两个四元数表示的旋转之间的夹角（弧度）。"""
    dot = max(-1.0, min(1.0, quat_dot_abs(a, b)))
    return float(2.0 * math.acos(dot))


def quat_from_to(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """从旋转 a 到旋转 b 的差四元数：b * a⁻¹。"""
    return quat_mul(quat_normalize(b), quat_inverse(quat_normalize(a)))


def quat_to_axis_angle(quat: np.ndarray) -> tuple[np.ndarray, float]:
    """四元数转轴角。返回 (axis, angle_radians)，零旋转时 axis=(0,0,0), angle=0。"""
    q = quat_normalize(quat)
    w = max(-1.0, min(1.0, float(q[3])))
    angle = float(2.0 * math.acos(w))
    s = math.sqrt(max(1.0 - w * w, 0.0))
    if s <= MC2SystemConstants.EPSILON:
        return np.asarray((0.0, 0.0, 0.0), dtype=np.float32), 0.0
    return np.asarray(q[:3] / s, dtype=np.float32), angle


# ---------------------------------------------------------------------------
# 矩阵 / 变换工具
# ---------------------------------------------------------------------------

def matrix_translation(matrix: np.ndarray) -> np.ndarray:
    """从 4×4 矩阵提取平移向量（第4列前三分量）。"""
    return np.ascontiguousarray(matrix[:3, 3], dtype=np.float32)


def matrix_rotation_quat(matrix: np.ndarray) -> np.ndarray:
    """从 4×4 变换矩阵提取旋转四元数（Gram-Schmidt 正交化后调用 quat_from_matrix）。"""
    basis = np.asarray(matrix[:3, :3], dtype=np.float32)
    x = safe_normal_np(basis[:, 0], np.asarray((1.0, 0.0, 0.0), dtype=np.float32))
    y = basis[:, 1] - x * float(np.dot(basis[:, 1], x))
    y = safe_normal_np(y, np.asarray((0.0, 1.0, 0.0), dtype=np.float32))
    z = safe_normal_np(np.cross(x, y), np.asarray((0.0, 0.0, 1.0), dtype=np.float32))
    y = safe_normal_np(np.cross(z, x), y)
    rot = np.asarray(
        ((x[0], y[0], z[0]),
         (x[1], y[1], z[1]),
         (x[2], y[2], z[2])),
        dtype=np.float32,
    )
    return quat_from_matrix(rot)


def shift_position(
    position: np.ndarray,
    pivot: np.ndarray,
    shift_vector: np.ndarray,
    shift_rotation: np.ndarray,
) -> np.ndarray:
    """将 position 绕 pivot 旋转 shift_rotation，再平移 shift_vector。"""
    local = np.asarray(position, dtype=np.float32) - pivot
    return np.ascontiguousarray(
        pivot + quat_rotate(shift_rotation, local) + shift_vector,
        dtype=np.float32,
    )


def transform_point(
    local_position: np.ndarray,
    origin: np.ndarray,
    rotation: np.ndarray,
) -> np.ndarray:
    """将局部坐标 local_position 变换到世界坐标（先旋转再平移）。"""
    return np.ascontiguousarray(
        np.asarray(origin, dtype=np.float32) + quat_rotate(rotation, local_position),
        dtype=np.float32,
    )


def inverse_transform_point(
    position: np.ndarray,
    origin: np.ndarray,
    rotation: np.ndarray,
) -> np.ndarray:
    """将世界坐标 position 变换回局部坐标（先减平移再逆旋转）。"""
    local = np.asarray(position, dtype=np.float32) - np.asarray(origin, dtype=np.float32)
    return np.ascontiguousarray(quat_rotate(quat_inverse(rotation), local), dtype=np.float32)
