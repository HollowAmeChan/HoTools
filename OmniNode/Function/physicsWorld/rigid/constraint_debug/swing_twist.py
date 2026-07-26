"""SwingTwist 约束的语义调试绘制。"""

from __future__ import annotations

import math

from mathutils import Quaternion, Vector

from ...utils.debug_draw import add_line
from .common import append_anchor_pair, append_axis_line


def append_lines(groups: dict[str, list], spec, context) -> None:
    """绘制局部 Z 扭转轴、椭圆摆动边界和扭转角边界。"""
    append_anchor_pair(groups["base"], context)
    frame = context.frame_a
    length = context.size * 0.75
    normal_angle = max(0.0, min(
        float(getattr(spec, "swing_normal_half_angle", math.pi * 0.25)), math.pi,
    ))
    plane_angle = max(0.0, min(
        float(getattr(spec, "swing_plane_half_angle", math.pi * 0.25)), math.pi,
    ))
    append_axis_line(groups["base"], frame.position, frame.axis_z, context.size * 0.2, length)

    swing_type = str(getattr(spec, "swing_type", "CONE") or "CONE").upper()
    if swing_type == "PYRAMID":
        def pyramid_direction(swing_y: float, swing_z: float):
            """复现 Jolt ClampSwingTwist 使用的无扭转金字塔边界方向。"""
            half_y = 0.5 * swing_y
            half_z = 0.5 * swing_z
            quat_y = math.sin(half_y) * math.cos(half_z)
            quat_z = math.cos(half_y) * math.sin(half_z)
            quat_w = math.cos(half_y) * math.cos(half_z)
            inverse_length = 1.0 / math.sqrt(
                quat_y * quat_y + quat_z * quat_z + quat_w * quat_w
            )
            quat_y *= inverse_length
            quat_z *= inverse_length
            quat_w *= inverse_length
            along_twist = 1.0 - 2.0 * (quat_y * quat_y + quat_z * quat_z)
            along_plane = 2.0 * quat_w * quat_z
            along_normal = -2.0 * quat_w * quat_y
            return (
                along_twist * frame.axis_z
                + along_plane * frame.axis_x
                + along_normal * frame.axis_y
            )

        samples = []
        segments = 16
        for index in range(segments):
            ratio = index / segments
            samples.append((-plane_angle, normal_angle * (1.0 - 2.0 * ratio)))
        for index in range(segments):
            ratio = index / segments
            samples.append((plane_angle * (-1.0 + 2.0 * ratio), -normal_angle))
        for index in range(segments):
            ratio = index / segments
            samples.append((plane_angle, normal_angle * (-1.0 + 2.0 * ratio)))
        for index in range(segments):
            ratio = index / segments
            samples.append((plane_angle * (1.0 - 2.0 * ratio), normal_angle))
        points = [
            frame.position + pyramid_direction(swing_y, swing_z) * length
            for swing_y, swing_z in samples
        ]
        for index, point in enumerate(points):
            add_line(groups["limits"], point, points[(index + 1) % len(points)])
            if index % segments == 0:
                add_line(groups["limits"], frame.position, point)
    else:
        points = []
        for index in range(24):
            angle = math.tau * index / 24
            radial = (
                math.cos(angle) * math.sin(plane_angle) * frame.axis_x
                + math.sin(angle) * math.sin(normal_angle) * frame.axis_y
            )
            axial = math.sqrt(max(0.0, 1.0 - min(radial.length_squared, 1.0)))
            points.append(frame.position + (radial + axial * frame.axis_z) * length)
        for index, point in enumerate(points):
            add_line(groups["limits"], point, points[(index + 1) % len(points)])
            if index % 4 == 0:
                add_line(groups["limits"], frame.position, point)

    twist_min = max(-math.pi, min(
        float(getattr(spec, "twist_min_angle", -math.pi * 0.25)), math.pi,
    ))
    twist_max = max(-math.pi, min(
        float(getattr(spec, "twist_max_angle", math.pi * 0.25)), math.pi,
    ))
    radius = context.size * 0.3
    for twist in (twist_min, twist_max):
        direction = math.cos(twist) * frame.axis_x + math.sin(twist) * frame.axis_y
        add_line(groups["limits"], frame.position, frame.position + direction * radius)

    swing_motor_state = str(getattr(spec, "swing_motor_state", "OFF") or "OFF").upper()
    twist_motor_state = str(getattr(spec, "twist_motor_state", "OFF") or "OFF").upper()
    motor_states = {swing_motor_state, twist_motor_state}
    if "POSITION" in motor_states:
        target_wxyz = tuple(getattr(
            spec, "swing_twist_target_orientation_wxyz", (1.0, 0.0, 0.0, 0.0),
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
    if "VELOCITY" in motor_states:
        target_velocity = tuple(getattr(
            spec, "swing_twist_target_angular_velocity", (0.0, 0.0, 0.0),
        ))
        if len(target_velocity) == 3:
            velocity_world = (
                float(target_velocity[0]) * frame.axis_x
                + float(target_velocity[1]) * frame.axis_y
                + float(target_velocity[2]) * frame.axis_z
            )
            if velocity_world.length_squared > 1.0e-12:
                add_line(
                    groups["motor"], frame.position,
                    frame.position + velocity_world.normalized() * context.size * 0.55,
                )
