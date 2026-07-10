"""Fixed constraint visualization."""

from __future__ import annotations

from ...utils.debug_draw import add_line
from .common import append_anchor_pair, append_frame_axes


def append_lines(groups: dict[str, list], spec, context) -> None:
    base = groups["base"]
    append_anchor_pair(base, context)
    axis_size = context.size * 0.35
    append_frame_axes(base, context.frame_a, axis_size)
    append_frame_axes(base, context.frame_b, axis_size)

    # Corresponding frame axes are locked together: these three bridges make
    # orientation mismatch visible instead of showing only the anchor points.
    for axis_a, axis_b in (
        (context.frame_a.axis_x, context.frame_b.axis_x),
        (context.frame_a.axis_y, context.frame_b.axis_y),
        (context.frame_a.axis_z, context.frame_b.axis_z),
    ):
        add_line(
            base,
            context.frame_a.position + axis_a * axis_size,
            context.frame_b.position + axis_b * axis_size,
        )
