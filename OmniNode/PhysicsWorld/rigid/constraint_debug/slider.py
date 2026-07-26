"""Slider (prismatic) constraint visualization."""

from __future__ import annotations

from .common import (
    append_anchor_pair,
    append_arrow,
    append_tick,
    append_unbounded_axis,
    current_value,
)


def append_lines(groups: dict[str, list], spec, context) -> None:
    append_anchor_pair(groups["base"], context)
    frame = context.frame_a
    extent = context.size * 0.85

    if bool(getattr(spec, "limit_enabled", False)):
        minimum = float(getattr(spec, "linear_limit_min", -1.0) or 0.0)
        maximum = float(getattr(spec, "linear_limit_max", 1.0) or 0.0)
        if minimum > maximum:
            minimum, maximum = maximum, minimum
        start = frame.position + frame.axis_z * minimum
        end = frame.position + frame.axis_z * maximum
        append_arrow(groups["limits"], start, end, frame.axis_x, context.size * 0.15)
        append_tick(groups["limits"], start, frame.axis_z, frame.axis_x, context.size * 0.32)
        append_tick(groups["limits"], end, frame.axis_z, frame.axis_x, context.size * 0.32)
    else:
        append_unbounded_axis(groups["base"], frame, extent)

    value = current_value(context, "position")
    if value is not None:
        point = frame.position + frame.axis_z * value
        append_tick(groups["state"], point, frame.axis_z, frame.axis_x, context.size * 0.42)

    motor_state = str(getattr(spec, "motor_state", "OFF") or "OFF").upper()
    if motor_state == "POSITION":
        target = frame.position + frame.axis_z * float(
            getattr(spec, "motor_target_position", 0.0) or 0.0
        )
        append_tick(groups["motor"], target, frame.axis_z, frame.axis_y, context.size * 0.52)
    elif motor_state == "VELOCITY":
        velocity = float(getattr(spec, "motor_target_velocity", 0.0) or 0.0)
        direction = 1.0 if velocity >= 0.0 else -1.0
        append_arrow(
            groups["motor"],
            frame.position,
            frame.position + frame.axis_z * direction * extent,
            frame.axis_y,
            context.size * 0.18,
        )
