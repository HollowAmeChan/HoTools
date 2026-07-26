"""Rack-and-pinion constraint visualization."""

from __future__ import annotations

from ...utils.debug_draw import add_line
from .common import append_axis_line, append_circle, append_unbounded_axis


def append_lines(groups: dict[str, list], spec, context) -> None:
    append_axis_line(
        groups["base"], context.frame_a.position, context.frame_a.axis_z,
        context.size * 0.45, context.size * 0.45,
    )
    append_circle(groups["base"], context.frame_a, context.size * 0.35)
    append_unbounded_axis(groups["base"], context.frame_b, context.size * 0.85)
    add_line(groups["base"], context.frame_a.position, context.frame_b.position)
