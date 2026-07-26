"""Hinge constraint visualization."""

from __future__ import annotations

import math

from .common import (
    append_angle_spoke,
    append_arc,
    append_anchor_pair,
    append_axis_line,
    append_circle,
    current_value,
)


def append_lines(groups: dict[str, list], spec, context) -> None:
    append_anchor_pair(groups["base"], context)
    radius = context.size * 0.45
    append_axis_line(
        groups["base"],
        context.frame_a.position,
        context.frame_a.axis_z,
        context.size * 0.55,
        context.size * 0.55,
    )
    append_angle_spoke(groups["base"], context.frame_a, radius, 0.0)

    if bool(getattr(spec, "limit_enabled", False)):
        minimum = max(-math.pi, min(float(getattr(spec, "angular_limit_min", -math.pi)), 0.0))
        maximum = min(math.pi, max(float(getattr(spec, "angular_limit_max", math.pi)), 0.0))
        append_arc(
            groups["limits"],
            context.frame_a.position,
            context.frame_a.axis_x,
            context.frame_a.axis_y,
            radius,
            minimum,
            maximum,
        )
        append_angle_spoke(groups["limits"], context.frame_a, radius, minimum)
        append_angle_spoke(groups["limits"], context.frame_a, radius, maximum)
    else:
        append_circle(groups["base"], context.frame_a, radius)

    value = current_value(context, "angle")
    if value is not None:
        append_angle_spoke(groups["state"], context.frame_a, radius * 1.10, value)

    motor_state = str(getattr(spec, "motor_state", "OFF") or "OFF").upper()
    if motor_state == "POSITION":
        append_angle_spoke(
            groups["motor"],
            context.frame_a,
            radius * 1.20,
            float(getattr(spec, "motor_target_angle", 0.0) or 0.0),
        )
    elif motor_state == "VELOCITY":
        direction = 1.0 if float(getattr(spec, "motor_target_angular_velocity", 0.0) or 0.0) >= 0.0 else -1.0
        append_arc(
            groups["motor"],
            context.frame_a.position,
            context.frame_a.axis_x,
            context.frame_a.axis_y,
            radius * 1.20,
            0.0 if direction > 0.0 else -math.pi * 0.75,
            math.pi * 0.75 if direction > 0.0 else 0.0,
            segments=12,
        )
