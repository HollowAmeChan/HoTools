"""Pulley 约束的绳路语义调试绘制。"""

from __future__ import annotations

from ...utils.debug_draw import add_cross_lines, add_line, vector3
from .common import append_anchor_pair


def append_lines(groups: dict[str, list], spec, context) -> None:
    """绘制两个刚体连接点、世界固定点和完整绳路。"""
    append_anchor_pair(groups["base"], context)
    fixed_a = vector3(getattr(spec, "pulley_fixed_point_a", (-1.0, 2.0, 0.0)))
    fixed_b = vector3(getattr(spec, "pulley_fixed_point_b", (1.0, 2.0, 0.0)))
    radius = context.size * 0.1
    add_cross_lines(groups["base"], fixed_a, radius)
    add_cross_lines(groups["base"], fixed_b, radius)
    add_line(groups["base"], context.frame_a.position, fixed_a)
    add_line(groups["base"], fixed_a, fixed_b)
    add_line(groups["base"], fixed_b, context.frame_b.position)
