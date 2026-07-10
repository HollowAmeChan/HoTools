"""Gear constraint visualization."""

from __future__ import annotations

from ...utils.debug_draw import add_line
from .common import append_axis_line, append_circle


def append_lines(groups: dict[str, list], spec, context) -> None:
    ratio = max(float(getattr(spec, "gear_ratio", 1.0) or 1.0), 1.0e-4)
    radius_a = context.size * 0.35
    radius_b = context.size * 0.35 * min(max(1.0 / ratio, 0.35), 2.5)
    append_axis_line(
        groups["base"], context.frame_a.position, context.frame_a.axis_z,
        context.size * 0.45, context.size * 0.45,
    )
    append_axis_line(
        groups["base"], context.frame_b.position, context.frame_b.axis_z,
        context.size * 0.45, context.size * 0.45,
    )
    append_circle(groups["base"], context.frame_a, radius_a)
    append_circle(groups["base"], context.frame_b, radius_b)
    add_line(groups["base"], context.frame_a.position, context.frame_b.position)
