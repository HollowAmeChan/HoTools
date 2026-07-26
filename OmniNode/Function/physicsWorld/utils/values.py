"""物理世界 result/spec 使用的基础数值格式化函数。"""

from __future__ import annotations


def float3(value, fallback=None) -> tuple[float, float, float]:
    if value is None:
        value = fallback if fallback is not None else (0.0, 0.0, 0.0)
    return (float(value[0]), float(value[1]), float(value[2]))


def matrix16(value) -> tuple[float, ...]:
    if len(value) == 16:
        return tuple(float(value[index]) for index in range(16))
    if len(value) == 4 and all(len(value[row]) == 4 for row in range(4)):
        return (
            float(value[0][0]), float(value[0][1]), float(value[0][2]), float(value[0][3]),
            float(value[1][0]), float(value[1][1]), float(value[1][2]), float(value[1][3]),
            float(value[2][0]), float(value[2][1]), float(value[2][2]), float(value[2][3]),
            float(value[3][0]), float(value[3][1]), float(value[3][2]), float(value[3][3]),
        )
    raise ValueError("matrix payload 必须包含 16 个数值")


def matrix_from_16(value):
    import mathutils

    values = matrix16(value)
    return mathutils.Matrix((
        (values[0], values[1], values[2], values[3]),
        (values[4], values[5], values[6], values[7]),
        (values[8], values[9], values[10], values[11]),
        (values[12], values[13], values[14], values[15]),
    ))
