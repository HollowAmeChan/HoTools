"""Cone constraint visualization."""

from __future__ import annotations

import math

from ...utils.debug_draw import add_circle_lines, add_line
from .common import append_anchor_pair, append_axis_line


def append_lines(groups: dict[str, list], spec, context) -> None:
    append_anchor_pair(groups["base"], context)
    frame = context.frame_a
    length = context.size * 0.75
    half_angle = max(0.0, min(float(getattr(spec, "cone_half_angle", 0.0) or 0.0), math.pi))

    append_axis_line(
        groups["base"],
        frame.position,
        frame.axis_z,
        context.size * 0.20,
        length,
    )
    if half_angle <= 1.0e-7:
        return

    # Jolt's ConeConstraint limits the angle between the two twist axes.  The
    # boundary is therefore a real angular cone, while twist around Z remains
    # free and is shown by the ring.
    axial = math.cos(half_angle) * length
    radial = abs(math.sin(half_angle) * length)
    ring_center = frame.position + frame.axis_z * axial
    add_circle_lines(groups["limits"], ring_center, frame.axis_x, frame.axis_y, radial)
    for index in range(8):
        angle = math.tau * index / 8
        rim = ring_center + (
            math.cos(angle) * frame.axis_x + math.sin(angle) * frame.axis_y
        ) * radial
        add_line(groups["limits"], frame.position, rim)
    add_circle_lines(
        groups["base"],
        frame.position + frame.axis_z * (context.size * 0.18),
        frame.axis_x,
        frame.axis_y,
        context.size * 0.12,
    )
