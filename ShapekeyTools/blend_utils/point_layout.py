"""混合矩阵的格点划分工具（纯计算，只依赖 ``math``）。

矩阵格点由**矩阵大小属性**（行/列格子数）强制划分：

- :func:`matrix_grid`：按行列数给出格点坐标（左上起、行优先）；
- :func:`matrix_unit`：单个格子的步长（用于微调与吸附）；
- :func:`snap_to_grid`：把一个坐标吸附到最近的格点上；
- :func:`duplicate_coordinate_groups`：找出坐标完全重合的点位，供界面提示。

坐标到像素的映射在 ``blend_space_math``，这里只负责“格点在哪”。
"""

from __future__ import annotations

import math

__all__ = (
    "MAX_MATRIX_SIZE",
    "MIN_MATRIX_SIZE",
    "duplicate_coordinate_groups",
    "matrix_grid",
    "matrix_grid_index",
    "matrix_unit",
    "snap_to_grid",
)

MIN_MATRIX_SIZE = 1
MAX_MATRIX_SIZE = 16


def matrix_unit(count: int, *, span: float = 1.0) -> float:
    """单格步长：``count`` 个格子铺满 ``[-span, span]`` 时的间距。

    只有一个格子（或更少）时返回 ``2 * span``，这样“往右挪一格”会夹到边界，
    等价于“已经在边上、挪不动”。
    """
    count = max(MIN_MATRIX_SIZE, int(count))
    if count <= 1:
        return 2.0 * span
    return 2.0 * span / (count - 1)


def matrix_grid(columns: int, rows: int, *, span: float = 1.0):
    """按矩阵大小给出格点坐标，**从左到右、从上到下**（行优先）。

    返回 ``[(-1, 1), (0, 1), (1, 1), (-1, 0), ...]`` 这样的列表，长度 ``columns*rows``。
    """
    columns = max(MIN_MATRIX_SIZE, int(columns))
    rows = max(MIN_MATRIX_SIZE, int(rows))
    step_u = matrix_unit(columns, span=span)
    step_v = matrix_unit(rows, span=span)
    coordinates = []
    for row in range(rows):
        for column in range(columns):
            u = -span + column * step_u if columns > 1 else 0.0
            v = span - row * step_v if rows > 1 else 0.0
            coordinates.append((round(u, 4), round(v, 4)))
    return coordinates


def matrix_grid_index(u, v, columns, rows, *, span: float = 1.0):
    """把一个坐标映射到最近的格点 ``(列, 行)`` 下标（不含合法性判断）。"""
    columns = max(MIN_MATRIX_SIZE, int(columns))
    rows = max(MIN_MATRIX_SIZE, int(rows))
    step_u = matrix_unit(columns, span=span)
    step_v = matrix_unit(rows, span=span)
    column = 0 if columns <= 1 else int(round((float(u) + span) / step_u))
    row = 0 if rows <= 1 else int(round((span - float(v)) / step_v))
    return (
        max(0, min(column, columns - 1)),
        max(0, min(row, rows - 1)),
    )


def snap_to_grid(u, v, columns, rows, *, span: float = 1.0):
    """把坐标吸附到最近的格点，返回 ``(u, v)``。"""
    column, row = matrix_grid_index(u, v, columns, rows, span=span)
    step_u = matrix_unit(columns, span=span)
    step_v = matrix_unit(rows, span=span)
    snapped_u = 0.0 if columns <= 1 else -span + column * step_u
    snapped_v = 0.0 if rows <= 1 else span - row * step_v
    return round(snapped_u, 4), round(snapped_v, 4)


def duplicate_coordinate_groups(item):
    """返回坐标完全重合的点位下标组，供 UI 提示。"""
    if item is None:
        return []
    groups = {}
    for index, point in enumerate(item.points):
        key = (round(point.u, 6), round(point.v, 6))
        groups.setdefault(key, []).append(index)
    return [indexes for indexes in groups.values() if len(indexes) > 1]
