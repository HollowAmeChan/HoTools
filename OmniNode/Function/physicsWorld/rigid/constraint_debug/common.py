"""Constraint debug draw primitives shared by the per-type renderers.

This module only converts a :class:`ConstraintSpec` plus an optional result
snapshot into plain line coordinates.  It never reads a Jolt handle and never
submits GPU work.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import mathutils

from ...utils.debug_draw import (
    add_circle_lines,
    add_cross_lines,
    add_line,
    add_sphere_lines,
    float_value,
    vector3,
)


_EPSILON = 1.0e-7
_ARC_SEGMENTS = 24


@dataclass(frozen=True)
class ConstraintFrame:
    position: mathutils.Vector
    axis_x: mathutils.Vector
    axis_y: mathutils.Vector
    axis_z: mathutils.Vector


@dataclass(frozen=True)
class ConstraintDrawContext:
    constraint_type: str
    frame_a: ConstraintFrame
    frame_b: ConstraintFrame
    size: float
    state: dict


def make_context(spec, state: dict | None = None) -> ConstraintDrawContext:
    return ConstraintDrawContext(
        constraint_type=str(getattr(spec, "constraint_type", "FIXED") or "FIXED").upper(),
        frame_a=_frame_from_spec(spec, "a"),
        frame_b=_frame_from_spec(spec, "b"),
        size=max(float_value(getattr(spec, "draw_constraint_size", 1.0), 1.0), 0.05),
        state=dict(state or {}),
    )


def append_anchor_pair(lines: list, context: ConstraintDrawContext) -> None:
    """Draw the two Jolt point frames and their current separation."""
    radius = context.size * 0.10
    add_cross_lines(lines, context.frame_a.position, radius)
    if (context.frame_b.position - context.frame_a.position).length_squared > _EPSILON:
        add_cross_lines(lines, context.frame_b.position, radius)
        add_line(lines, context.frame_a.position, context.frame_b.position)


def append_frame_axes(lines: list, frame: ConstraintFrame, size: float) -> None:
    """Draw the authored X/Y/Z frame; Jolt mappings use Z as hinge/slider axis."""
    length = max(float(size), 0.01)
    add_line(lines, frame.position, frame.position + frame.axis_x * length)
    add_line(lines, frame.position, frame.position + frame.axis_y * length * 0.8)
    add_line(lines, frame.position, frame.position + frame.axis_z * length * 1.2)


def append_axis_line(
    lines: list,
    center,
    axis,
    negative_length: float,
    positive_length: float,
) -> None:
    center = vector3(center)
    axis = _normalized(axis, (0.0, 0.0, 1.0))
    add_line(lines, center - axis * max(float(negative_length), 0.0), center + axis * max(float(positive_length), 0.0))


def append_tick(lines: list, point, axis, normal, size: float) -> None:
    point = vector3(point)
    axis = _normalized(axis, (0.0, 0.0, 1.0))
    normal = vector3(normal) - axis * vector3(normal).dot(axis)
    normal = _normalized(normal, (1.0, 0.0, 0.0))
    half = max(float(size), 0.005) * 0.5
    add_line(lines, point - normal * half, point + normal * half)


def append_arrow(lines: list, start, end, side_hint, head_size: float) -> None:
    start = vector3(start)
    end = vector3(end)
    add_line(lines, start, end)
    direction = end - start
    if direction.length <= _EPSILON:
        return
    direction.normalize()
    side = vector3(side_hint) - direction * vector3(side_hint).dot(direction)
    side = _normalized(side, (1.0, 0.0, 0.0))
    head = max(float(head_size), 0.01)
    add_line(lines, end, end - direction * head + side * head * 0.45)
    add_line(lines, end, end - direction * head - side * head * 0.45)


def append_arc(
    lines: list,
    center,
    axis_x,
    axis_y,
    radius: float,
    start_angle: float,
    end_angle: float,
    segments: int = _ARC_SEGMENTS,
) -> None:
    radius = max(float(radius), 0.0)
    if radius <= _EPSILON:
        return
    start_angle = float(start_angle)
    end_angle = float(end_angle)
    if end_angle < start_angle:
        start_angle, end_angle = end_angle, start_angle
    span = end_angle - start_angle
    segment_count = max(2, int(math.ceil(max(span, 0.05) / math.tau * max(int(segments), 4))))
    center = vector3(center)
    axis_x = _normalized(axis_x, (1.0, 0.0, 0.0))
    axis_y = _normalized(axis_y, (0.0, 1.0, 0.0))
    points = []
    for index in range(segment_count + 1):
        angle = start_angle + span * index / segment_count
        points.append(center + (math.cos(angle) * axis_x + math.sin(angle) * axis_y) * radius)
    for index in range(len(points) - 1):
        add_line(lines, points[index], points[index + 1])


def append_angle_spoke(lines: list, frame: ConstraintFrame, radius: float, angle: float) -> None:
    end = frame.position + (
        math.cos(float(angle)) * frame.axis_x + math.sin(float(angle)) * frame.axis_y
    ) * max(float(radius), 0.0)
    add_line(lines, frame.position, end)


def append_free_rotation_sphere(lines: list, frame: ConstraintFrame, radius: float) -> None:
    add_sphere_lines(
        lines,
        frame.position,
        frame.axis_x,
        frame.axis_y,
        frame.axis_z,
        max(float(radius), 0.0),
    )


def append_unbounded_axis(lines: list, frame: ConstraintFrame, extent: float) -> None:
    extent = max(float(extent), 0.05)
    append_arrow(
        lines,
        frame.position,
        frame.position + frame.axis_z * extent,
        frame.axis_x,
        extent * 0.20,
    )
    append_arrow(
        lines,
        frame.position,
        frame.position - frame.axis_z * extent,
        frame.axis_x,
        extent * 0.20,
    )


def append_circle(lines: list, frame: ConstraintFrame, radius: float) -> None:
    add_circle_lines(lines, frame.position, frame.axis_x, frame.axis_y, max(float(radius), 0.0))


def current_value(context: ConstraintDrawContext, expected_kind: str) -> float | None:
    if str(context.state.get("current_value_kind", "none")) != expected_kind:
        return None
    try:
        return float(context.state.get("current_value", 0.0))
    except Exception:
        return None


def _frame_from_spec(spec, side: str) -> ConstraintFrame:
    suffix = "a" if side.lower() == "a" else "b"
    fallback_position = getattr(spec, "anchor_position", (0.0, 0.0, 0.0))
    fallback_rotation = getattr(spec, "anchor_rotation_wxyz", (1.0, 0.0, 0.0, 0.0))
    position = vector3(getattr(spec, f"anchor_position_{suffix}", fallback_position))
    try:
        rotation = mathutils.Quaternion(
            getattr(spec, f"anchor_rotation_wxyz_{suffix}", fallback_rotation)
        )
        rotation.normalize()
    except Exception:
        rotation = mathutils.Quaternion((1.0, 0.0, 0.0, 0.0))
    return ConstraintFrame(
        position=position,
        axis_x=_normalized(rotation @ mathutils.Vector((1.0, 0.0, 0.0)), (1.0, 0.0, 0.0)),
        axis_y=_normalized(rotation @ mathutils.Vector((0.0, 1.0, 0.0)), (0.0, 1.0, 0.0)),
        axis_z=_normalized(rotation @ mathutils.Vector((0.0, 0.0, 1.0)), (0.0, 0.0, 1.0)),
    )


def _normalized(value, fallback) -> mathutils.Vector:
    result = vector3(value, fallback)
    if result.length <= _EPSILON:
        result = vector3(fallback)
    result.normalize()
    return result
