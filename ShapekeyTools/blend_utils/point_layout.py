"""混合矩阵的坐标点位排布工具（纯计算，只依赖 ``math``）。

- :func:`grid_coordinates`：把 N 个点位铺成居中的行列矩阵；
- :func:`assign_grid`：把铺开结果写回调试矩阵的点位；
- :func:`duplicate_coordinate_groups`：找出坐标完全重合的点位，供界面提示。

坐标映射本身在 ``blend_space_math``，这里只负责“怎么摆”。
"""

from __future__ import annotations

import math

__all__ = (
    "assign_grid",
    "duplicate_coordinate_groups",
    "grid_coordinates",
)


def grid_coordinates(count: int, *, span: float = 1.0) -> list[tuple[float, float]]:
    """把 ``count`` 个坐标点铺成居中的行列矩阵，范围 ``[-span, span]``。

    单点直接落在原点；其余情况按接近正方形的行列数铺开，行优先（先左右后上下），
    这样“嘴巴上下 / 左右”这类二维表能直接从键的顺序读出来。
    """
    if count <= 0:
        return []
    if count == 1:
        return [(0.0, 0.0)]
    columns = max(2, math.ceil(math.sqrt(count)))
    rows = math.ceil(count / columns)
    coordinates = []
    for index in range(count):
        row, column = divmod(index, columns)
        u = (column / (columns - 1) * 2.0 - 1.0) * span if columns > 1 else 0.0
        v = (1.0 - row / (rows - 1) * 2.0) * span if rows > 1 else 0.0
        coordinates.append((round(u, 4), round(v, 4)))
    return coordinates


def assign_grid(item) -> None:
    """按当前点位数量重排全部坐标（就地改写）。"""
    if item is None:
        return
    for point, (u, v) in zip(item.points, grid_coordinates(len(item.points))):
        point.u = u
        point.v = v


def duplicate_coordinate_groups(item):
    """返回坐标完全重合的点位下标组，供 UI 提示。"""
    if item is None:
        return []
    groups = {}
    for index, point in enumerate(item.points):
        key = (round(point.u, 6), round(point.v, 6))
        groups.setdefault(key, []).append(index)
    return [indexes for indexes in groups.values() if len(indexes) > 1]
