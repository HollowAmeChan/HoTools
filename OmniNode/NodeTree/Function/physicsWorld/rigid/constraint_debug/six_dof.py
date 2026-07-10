"""SixDOF 约束的六轴语义调试绘制。"""

from __future__ import annotations

import math

from mathutils import Quaternion, Vector

from ...utils.debug_draw import add_line
from .common import append_anchor_pair, append_arc, append_frame_axes


def append_lines(groups: dict[str, list], spec, context) -> None:
    """按 HoTools XYZ frame 绘制平移范围和旋转范围。"""
    append_anchor_pair(groups["base"], context)
    frame = context.frame_a
    append_frame_axes(groups["base"], frame, context.size * 0.35)
    axes = (frame.axis_x, frame.axis_y, frame.axis_z)
    rotation_bases = (
        (frame.axis_y, frame.axis_z),
        (frame.axis_z, frame.axis_x),
        (frame.axis_x, frame.axis_y),
    )
    modes = tuple(getattr(spec, "six_dof_axis_modes", ("FIXED",) * 6))
    minimum = tuple(getattr(
        spec, "six_dof_limit_min", (-1.0, -1.0, -1.0, -math.pi, -math.pi, -math.pi),
    ))
    maximum = tuple(getattr(
        spec, "six_dof_limit_max", (1.0, 1.0, 1.0, math.pi, math.pi, math.pi),
    ))
    if len(modes) != 6 or len(minimum) != 6 or len(maximum) != 6:
        return

    for index, axis in enumerate(axes):
        mode = str(modes[index] or "FIXED").upper()
        if mode == "LIMITED":
            add_line(
                groups["limits"],
                frame.position + axis * float(minimum[index]),
                frame.position + axis * float(maximum[index]),
            )
        elif mode == "FREE":
            extent = context.size * 0.65
            add_line(
                groups["base"], frame.position - axis * extent,
                frame.position + axis * extent,
            )

    radius = context.size * 0.48
    for local_index, (axis_x, axis_y) in enumerate(rotation_bases):
        index = local_index + 3
        mode = str(modes[index] or "FIXED").upper()
        if mode == "LIMITED":
            append_arc(
                groups["limits"], frame.position, axis_x, axis_y, radius,
                float(minimum[index]), float(maximum[index]),
            )
        elif mode == "FREE":
            append_arc(
                groups["base"], frame.position, axis_x, axis_y, radius,
                -math.pi, math.pi,
            )

    motor_states = tuple(getattr(spec, "six_dof_motor_states", ("OFF",) * 6))
    if len(motor_states) != 6:
        return

    target_position = tuple(getattr(
        spec, "six_dof_target_position", (0.0, 0.0, 0.0),
    ))
    if len(target_position) == 3:
        local_target = Vector(tuple(
            float(target_position[index])
            if str(motor_states[index] or "OFF").upper() == "POSITION"
            else 0.0
            for index in range(3)
        ))
        if local_target.length_squared > 1.0e-12:
            world_target = (
                local_target.x * frame.axis_x
                + local_target.y * frame.axis_y
                + local_target.z * frame.axis_z
            )
            add_line(
                groups["motor"], frame.position,
                frame.position + world_target,
            )

    target_velocity = tuple(getattr(
        spec, "six_dof_target_velocity", (0.0, 0.0, 0.0),
    ))
    if len(target_velocity) == 3:
        local_velocity = Vector(tuple(
            float(target_velocity[index])
            if str(motor_states[index] or "OFF").upper() == "VELOCITY"
            else 0.0
            for index in range(3)
        ))
        if local_velocity.length_squared > 1.0e-12:
            world_velocity = (
                local_velocity.x * frame.axis_x
                + local_velocity.y * frame.axis_y
                + local_velocity.z * frame.axis_z
            ).normalized()
            add_line(
                groups["motor"], frame.position,
                frame.position + world_velocity * context.size * 0.55,
            )

    rotation_states = {
        str(state or "OFF").upper() for state in motor_states[3:]
    }
    if "POSITION" in rotation_states:
        target_wxyz = tuple(getattr(
            spec, "six_dof_target_orientation_wxyz", (1.0, 0.0, 0.0, 0.0),
        ))
        if len(target_wxyz) == 4:
            target_local = Quaternion(target_wxyz) @ Vector((0.0, 0.0, 1.0))
            target_world = (
                target_local.x * frame.axis_x
                + target_local.y * frame.axis_y
                + target_local.z * frame.axis_z
            )
            add_line(
                groups["motor"], frame.position,
                frame.position + target_world * context.size * 0.65,
            )

    target_angular_velocity = tuple(getattr(
        spec, "six_dof_target_angular_velocity", (0.0, 0.0, 0.0),
    ))
    if len(target_angular_velocity) == 3:
        local_angular_velocity = Vector(tuple(
            float(target_angular_velocity[index])
            if str(motor_states[index + 3] or "OFF").upper() == "VELOCITY"
            else 0.0
            for index in range(3)
        ))
        if local_angular_velocity.length_squared > 1.0e-12:
            world_angular_velocity = (
                local_angular_velocity.x * frame.axis_x
                + local_angular_velocity.y * frame.axis_y
                + local_angular_velocity.z * frame.axis_z
            ).normalized()
            add_line(
                groups["motor"], frame.position,
                frame.position + world_angular_velocity * context.size * 0.48,
            )
