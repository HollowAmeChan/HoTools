"""物理调试绘制的通用线段/GPU/几何辅助。"""

from __future__ import annotations

import math

import gpu
import mathutils
from gpu_extras.batch import batch_for_shader


_SEGMENTS = 24
_UNIT_CIRCLE = [
    (math.cos(math.tau * i / _SEGMENTS), math.sin(math.tau * i / _SEGMENTS))
    for i in range(_SEGMENTS + 1)
]


def draw_line_batches(batch_specs) -> None:
    """绘制 [(lines, color, width), ...]；lines 必须是纯 tuple 坐标列表。"""
    specs = list(batch_specs or ())
    if not any(lines for lines, _, _ in specs):
        return
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    gpu.state.depth_mask_set(False)
    try:
        for lines, color, line_width in specs:
            if not lines:
                continue
            batch = batch_for_shader(shader, "LINES", {"pos": lines})
            shader.bind()
            shader.uniform_float("color", color)
            gpu.state.line_width_set(float(line_width))
            batch.draw(shader)
    finally:
        gpu.state.line_width_set(1.0)
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.blend_set("NONE")


def vector3(value, fallback=(0.0, 0.0, 0.0)) -> mathutils.Vector:
    try:
        return mathutils.Vector(value).to_3d()
    except Exception:
        return mathutils.Vector(fallback).to_3d()


def tuple3(value) -> tuple[float, float, float]:
    vec = vector3(value)
    return (float(vec.x), float(vec.y), float(vec.z))


def float_value(value, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(fallback)


def half_extents(value, fallback=(0.5, 0.5, 0.5)) -> tuple[float, float, float]:
    try:
        items = tuple(max(float(v), 0.0) for v in value)
        if len(items) == 3:
            return items
    except Exception:
        pass
    return tuple(float(v) for v in fallback)


def matrix_from_position_rotation(position, rotation_wxyz) -> mathutils.Matrix | None:
    try:
        loc = vector3(position)
        rot = mathutils.Quaternion(rotation_wxyz)
        return mathutils.Matrix.Translation(loc) @ rot.to_matrix().to_4x4()
    except Exception:
        return None


def axis_from_matrix(mat: mathutils.Matrix, index: int, fallback) -> mathutils.Vector:
    try:
        vec = mathutils.Vector(mat.col[index][:3]).to_3d()
        if vec.length > 1e-7:
            vec.normalize()
            return vec
    except Exception:
        pass
    return vector3(fallback)


def object_location(obj) -> mathutils.Vector:
    try:
        return obj.matrix_world.translation.copy()
    except Exception:
        return mathutils.Vector((0.0, 0.0, 0.0))


def add_line(lines: list, a, b) -> None:
    lines.append(tuple3(a))
    lines.append(tuple3(b))


def add_cross_lines(lines: list, center, radius: float) -> None:
    c = vector3(center)
    r = float(radius)
    add_line(lines, c + mathutils.Vector((-r, 0, 0)), c + mathutils.Vector((r, 0, 0)))
    add_line(lines, c + mathutils.Vector((0, -r, 0)), c + mathutils.Vector((0, r, 0)))
    add_line(lines, c + mathutils.Vector((0, 0, -r)), c + mathutils.Vector((0, 0, r)))


def add_circle_lines(lines: list, center, axis_a, axis_b, radius: float) -> None:
    if radius <= 1e-7:
        return
    a = axis_a * radius
    b = axis_b * radius
    points = [center + c * a + s * b for c, s in _UNIT_CIRCLE]
    for index in range(len(points) - 1):
        add_line(lines, points[index], points[index + 1])


def add_sphere_lines(lines: list, center, axis_x, axis_y, axis_z, radius: float) -> None:
    add_circle_lines(lines, center, axis_x, axis_y, radius)
    add_circle_lines(lines, center, axis_x, axis_z, radius)
    add_circle_lines(lines, center, axis_y, axis_z, radius)


def add_capsule_lines(lines: list, segment_a, segment_b, radius: float) -> None:
    segment_a = vector3(segment_a)
    segment_b = vector3(segment_b)
    radius = float(radius)
    if radius <= 1e-7:
        return

    axis = segment_b - segment_a
    if axis.length <= 1e-7:
        add_sphere_lines(
            lines,
            segment_a,
            mathutils.Vector((1, 0, 0)),
            mathutils.Vector((0, 1, 0)),
            mathutils.Vector((0, 0, 1)),
            radius,
        )
        return
    axis.normalize()
    ref = mathutils.Vector((1, 0, 0)) if abs(axis.dot(mathutils.Vector((0, 0, 1)))) > 0.9 else mathutils.Vector((0, 0, 1))
    axis_a = axis.cross(ref).normalized()
    axis_b = axis.cross(axis_a).normalized()
    add_circle_lines(lines, segment_a, axis_a, axis_b, radius)
    add_circle_lines(lines, segment_b, axis_a, axis_b, radius)
    for side in (axis_a, -axis_a, axis_b, -axis_b):
        add_line(lines, segment_a + side * radius, segment_b + side * radius)
    for side in (axis_a, axis_b):
        _add_capsule_cap_arc_lines(lines, segment_a, side, -axis, radius)
        _add_capsule_cap_arc_lines(lines, segment_b, side, axis, radius)


def _add_capsule_cap_arc_lines(lines: list, center, side, pole_axis, radius: float) -> None:
    points = [
        center + math.cos(math.pi * index / _SEGMENTS) * side * radius
        + math.sin(math.pi * index / _SEGMENTS) * pole_axis * radius
        for index in range(_SEGMENTS + 1)
    ]
    for index in range(len(points) - 1):
        add_line(lines, points[index], points[index + 1])


def add_plane_lines(lines: list, center, axis_x, axis_y, normal) -> None:
    corners = [
        center - axis_x - axis_y,
        center + axis_x - axis_y,
        center + axis_x + axis_y,
        center - axis_x + axis_y,
    ]
    for index, corner in enumerate(corners):
        add_line(lines, corner, corners[(index + 1) % len(corners)])
    ray = normal.normalized() * max(axis_x.length, axis_y.length, 0.5)
    for corner in corners:
        add_line(lines, corner, corner - ray)


def add_box_lines(lines: list, center, axis_x, axis_y, axis_z) -> None:
    corners = [
        center + sx * axis_x + sy * axis_y + sz * axis_z
        for sx, sy, sz in (
            (-1.0, -1.0, -1.0),
            (1.0, -1.0, -1.0),
            (1.0, 1.0, -1.0),
            (-1.0, 1.0, -1.0),
            (-1.0, -1.0, 1.0),
            (1.0, -1.0, 1.0),
            (1.0, 1.0, 1.0),
            (-1.0, 1.0, 1.0),
        )
    ]
    for start, end in (
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ):
        add_line(lines, corners[start], corners[end])
