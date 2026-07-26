"""统一物理世界使用的纯数学/数值 helper。"""

from __future__ import annotations

import math

import numpy as np


DEFAULT_EPSILON = 1.0e-8


def clamp_int(value, minimum: int, maximum: int, fallback: int = 0) -> int:
    """把任意输入钳制到整数区间。"""
    try:
        number = int(value)
    except Exception:
        number = int(fallback)
    return max(int(minimum), min(int(maximum), number))


def numpy_vec3(value, dtype=np.float32) -> np.ndarray | None:
    """把三维向量输入转成 numpy vec3；非法输入返回 None。"""
    if value is None:
        return None
    try:
        return np.asarray((float(value[0]), float(value[1]), float(value[2])), dtype=dtype)
    except Exception:
        return None


def vec3_length(value) -> float:
    """返回三维向量长度；非法输入按 0 处理。"""
    try:
        x = float(value[0])
        y = float(value[1])
        z = float(value[2])
    except Exception:
        return 0.0
    return math.sqrt(x * x + y * y + z * z)


def matrix_scale_radius(matrix) -> float:
    """从矩阵缩放中取最大绝对轴缩放，作为球/胶囊半径缩放因子。"""
    try:
        scale = matrix.to_scale()
        return max(abs(float(scale.x)), abs(float(scale.y)), abs(float(scale.z)))
    except Exception:
        return 1.0


def signed_third_axis_length(axis_x, axis_y, axis_z, epsilon: float = DEFAULT_EPSILON) -> float | None:
    """
    返回第三轴长度，并用 axis_x x axis_y 与 axis_z 的方向关系保留手性符号。

    SpringBone native ABI 用 X/Y 半轴加一个带符号 Z 半轴长度表示有向盒体；
    这个函数只负责纯数学转换，不关心调用者的 collider 语义。
    """
    x = numpy_vec3(axis_x)
    y = numpy_vec3(axis_y)
    z = numpy_vec3(axis_z)
    if x is None or y is None or z is None:
        return None
    z_length = vec3_length(z)
    if vec3_length(x) <= epsilon or vec3_length(y) <= epsilon or z_length <= epsilon:
        return None
    sign = 1.0 if float(np.dot(np.cross(x, y), z)) >= 0.0 else -1.0
    return z_length * sign
