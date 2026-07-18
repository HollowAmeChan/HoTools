"""物理调试绘制的通用线段/GPU/几何辅助。"""

from __future__ import annotations

import math

import gpu
import mathutils
from gpu_extras.batch import batch_for_shader


_SEGMENTS = 24
_ROUND_POINT_SHADER = None

_ROUND_POINT_VERTEX_SHADER = """
uniform mat4 ModelViewProjectionMatrix;
in vec3 pos;

void main()
{
    gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);
}
"""

_ROUND_POINT_FRAGMENT_SHADER = """
uniform vec4 color;
out vec4 fragColor;

void main()
{
    vec2 centered = gl_PointCoord - vec2(0.5);
    float radius = length(centered);
    float edge = max(fwidth(radius), 0.001);
    float coverage = 1.0 - smoothstep(0.5 - edge, 0.5, radius);
    if (coverage <= 0.0) {
        discard;
    }
    fragColor = vec4(color.rgb, color.a * coverage);
}
"""


def _round_point_shader():
    global _ROUND_POINT_SHADER
    if _ROUND_POINT_SHADER is None:
        _ROUND_POINT_SHADER = gpu.types.GPUShader(
            _ROUND_POINT_VERTEX_SHADER,
            _ROUND_POINT_FRAGMENT_SHADER,
        )
    return _ROUND_POINT_SHADER


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


def draw_point_batches(batch_specs) -> None:
    """绘制 [(points, color, size), ...]；size 是屏幕像素。"""
    specs = list(batch_specs or ())
    if not any(points for points, _, _ in specs):
        return
    shader = _round_point_shader()
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    gpu.state.depth_mask_set(False)
    try:
        for points, color, point_size in specs:
            if not points:
                continue
            batch = batch_for_shader(shader, "POINTS", {"pos": points})
            shader.bind()
            shader.uniform_float(
                "ModelViewProjectionMatrix",
                gpu.matrix.get_projection_matrix()
                @ gpu.matrix.get_model_view_matrix(),
            )
            shader.uniform_float("color", color)
            gpu.state.point_size_set(float(point_size))
            batch.draw(shader)
    finally:
        gpu.state.point_size_set(1.0)
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


def add_point(points: list, position) -> None:
    points.append(tuple3(position))


def _perpendicular_axes(direction: mathutils.Vector):
    reference = (
        mathutils.Vector((1.0, 0.0, 0.0))
        if abs(direction.z) > 0.9
        else mathutils.Vector((0.0, 0.0, 1.0))
    )
    first = direction.cross(reference).normalized()
    return first, direction.cross(first).normalized()


def add_arrow_lines(
    lines: list,
    start,
    end,
    *,
    head_length: float | None = None,
    head_width: float | None = None,
) -> None:
    """添加world-space向量箭头；短向量会按长度自动缩小箭头。"""
    start = vector3(start)
    end = vector3(end)
    delta = end - start
    length = delta.length
    if length <= 1.0e-7:
        return
    direction = delta / length
    size = min(
        max(float(head_length) if head_length is not None else length * 0.2, 1.0e-5),
        length * 0.45,
    )
    width = max(
        float(head_width) if head_width is not None else size * 0.45,
        1.0e-5,
    )
    axis_a, axis_b = _perpendicular_axes(direction)
    head_center = end - direction * size
    add_line(lines, start, end)
    for side in (axis_a, -axis_a, axis_b, -axis_b):
        add_line(lines, end, head_center + side * width)


def add_arc_lines(
    lines: list,
    center,
    axis_a,
    axis_b,
    radius: float,
    start_angle: float,
    end_angle: float,
    *,
    segments: int | None = None,
) -> None:
    """在给定二维基底中添加角度弧，适合角限制和旋转差debug。"""
    radius = float(radius)
    if radius <= 1.0e-7:
        return
    center = vector3(center)
    axis_a = vector3(axis_a)
    axis_b = vector3(axis_b)
    if axis_a.length <= 1.0e-7 or axis_b.length <= 1.0e-7:
        return
    axis_a.normalize()
    axis_b.normalize()
    span = float(end_angle) - float(start_angle)
    count = max(
        1,
        int(segments)
        if segments is not None
        else int(math.ceil(abs(span) / math.tau * _SEGMENTS)),
    )
    points = [
        center
        + math.cos(float(start_angle) + span * index / count) * axis_a * radius
        + math.sin(float(start_angle) + span * index / count) * axis_b * radius
        for index in range(count + 1)
    ]
    for index in range(count):
        add_line(lines, points[index], points[index + 1])


def add_spring_lines(
    lines: list,
    start,
    end,
    *,
    radius: float = 0.02,
    turns: int = 6,
    segments_per_turn: int = 4,
) -> None:
    """添加沿约束轴展开的弹簧线；端部保留直线以便读取锚点。"""
    start = vector3(start)
    end = vector3(end)
    delta = end - start
    length = delta.length
    if length <= 1.0e-7:
        return
    direction = delta / length
    axis_a, axis_b = _perpendicular_axes(direction)
    lead = min(length * 0.15, max(float(radius), 0.0) * 2.0)
    coil_start = start + direction * lead
    coil_end = end - direction * lead
    add_line(lines, start, coil_start)
    count = max(2, int(turns) * max(2, int(segments_per_turn)))
    coil_length = max((coil_end - coil_start).length, 0.0)
    points = []
    for index in range(count + 1):
        ratio = index / count
        envelope = min(ratio * count, (1.0 - ratio) * count, 1.0)
        angle = math.tau * max(1, int(turns)) * ratio
        radial = (
            math.cos(angle) * axis_a + math.sin(angle) * axis_b
        ) * max(float(radius), 0.0) * envelope
        points.append(coil_start + direction * coil_length * ratio + radial)
    for index in range(count):
        add_line(lines, points[index], points[index + 1])
    add_line(lines, coil_end, end)


def add_basis_lines(lines: list, center, rotation, scale: float = 0.1) -> None:
    """添加真实旋转基底；rotation使用Blender Quaternion(wxyz)语义。"""
    center = vector3(center)
    try:
        quaternion = rotation if isinstance(rotation, mathutils.Quaternion) else mathutils.Quaternion(rotation)
    except Exception:
        return
    for axis in (
        mathutils.Vector((1.0, 0.0, 0.0)),
        mathutils.Vector((0.0, 1.0, 0.0)),
        mathutils.Vector((0.0, 0.0, 1.0)),
    ):
        add_line(lines, center, center + quaternion @ axis * float(scale))


def add_cross_lines(lines: list, center, radius: float) -> None:
    c = vector3(center)
    r = float(radius)
    add_line(lines, c + mathutils.Vector((-r, 0, 0)), c + mathutils.Vector((r, 0, 0)))
    add_line(lines, c + mathutils.Vector((0, -r, 0)), c + mathutils.Vector((0, r, 0)))
    add_line(lines, c + mathutils.Vector((0, 0, -r)), c + mathutils.Vector((0, 0, r)))


def add_circle_lines(lines: list, center, axis_a, axis_b, radius: float) -> None:
    add_arc_lines(lines, center, axis_a, axis_b, radius, 0.0, math.tau, segments=_SEGMENTS)


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


def add_tapered_capsule_lines(
    lines: list,
    segment_a,
    segment_b,
    radius_a: float,
    radius_b: float,
) -> None:
    """Draw a segment whose collision radius interpolates between its endpoints."""
    segment_a = vector3(segment_a)
    segment_b = vector3(segment_b)
    radius_a = max(float(radius_a), 0.0)
    radius_b = max(float(radius_b), 0.0)
    if max(radius_a, radius_b) <= 1.0e-7:
        return

    axis = segment_b - segment_a
    if axis.length <= 1.0e-7:
        add_sphere_lines(
            lines,
            segment_a,
            mathutils.Vector((1, 0, 0)),
            mathutils.Vector((0, 1, 0)),
            mathutils.Vector((0, 0, 1)),
            max(radius_a, radius_b),
        )
        return
    axis.normalize()
    axis_a, axis_b = _perpendicular_axes(axis)
    if radius_a > 1.0e-7:
        add_circle_lines(lines, segment_a, axis_a, axis_b, radius_a)
    if radius_b > 1.0e-7:
        add_circle_lines(lines, segment_b, axis_a, axis_b, radius_b)
    for side in (axis_a, -axis_a, axis_b, -axis_b):
        add_line(
            lines,
            segment_a + side * radius_a,
            segment_b + side * radius_b,
        )
    for side in (axis_a, axis_b):
        if radius_a > 1.0e-7:
            _add_capsule_cap_arc_lines(lines, segment_a, side, -axis, radius_a)
        if radius_b > 1.0e-7:
            _add_capsule_cap_arc_lines(lines, segment_b, side, axis, radius_b)


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
