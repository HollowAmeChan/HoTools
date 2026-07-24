"""Shared declarative viewport primitives and the single HoAux draw handler."""

from dataclasses import dataclass, field
from math import cos, pi, sin

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector


Color = tuple[float, float, float, float]


@dataclass(frozen=True)
class LineStyle:
    color: Color
    width: float = 2.0


@dataclass(frozen=True)
class PointStyle:
    color: Color
    size: float = 6.0


ROLE_LINE_STYLES = {
    "TRK": LineStyle((0.2, 0.75, 1.0, 0.9), 2.0),
    "DEF": LineStyle((0.25, 1.0, 0.45, 0.95), 3.0),
    "DIR": LineStyle((1.0, 0.7, 0.2, 1.0), 4.0),
    "GUIDE": LineStyle((0.85, 0.85, 0.85, 0.65), 1.0),
}
JOINT_POINT_STYLE = PointStyle((1.0, 0.45, 0.2, 1.0), 7.0)


@dataclass
class PreviewScene:
    object_name: str
    lines: list[tuple[Vector, Vector, LineStyle]] = field(default_factory=list)
    points: list[tuple[Vector, PointStyle]] = field(default_factory=list)

    def add_segment(self, start, end, style):
        self.lines.append((Vector(start), Vector(end), style))

    def add_polyline(self, points, style, *, closed=False):
        points = [Vector(point) for point in points]
        for start, end in zip(points, points[1:]):
            self.add_segment(start, end, style)
        if closed and len(points) > 2:
            self.add_segment(points[-1], points[0], style)

    def add_circle(self, center, normal, radius, style, *, segments=32):
        normal = Vector(normal).normalized()
        tangent = normal.orthogonal().normalized()
        bitangent = normal.cross(tangent).normalized()
        center = Vector(center)
        points = [
            center
            + radius
            * (tangent * cos(index * 2.0 * pi / segments)
               + bitangent * sin(index * 2.0 * pi / segments))
            for index in range(segments)
        ]
        self.add_polyline(points, style, closed=True)

    def add_point(self, position, style=JOINT_POINT_STYLE):
        self.points.append((Vector(position), style))

    def add_planned_bones(self, plans):
        for plan in plans:
            self.add_segment(
                plan.head,
                plan.tail,
                ROLE_LINE_STYLES.get(plan.role_tag, ROLE_LINE_STYLES["GUIDE"]),
            )


class ViewportPreview:
    _handler = None
    _owner_key = None
    _scene = None

    @classmethod
    def is_visible(cls, owner_key=None):
        visible = cls._handler is not None and cls._scene is not None
        return visible and (owner_key is None or cls._owner_key == owner_key)

    @classmethod
    def show(cls, owner_key, scene):
        cls._owner_key = owner_key
        cls._scene = scene
        if cls._handler is None:
            cls._handler = bpy.types.SpaceView3D.draw_handler_add(
                cls._draw, (), "WINDOW", "POST_VIEW"
            )
        cls.tag_redraw()

    @classmethod
    def clear(cls, owner_key=None):
        if owner_key is not None and owner_key != cls._owner_key:
            return
        cls._scene = None
        cls._owner_key = None
        if cls._handler is not None:
            bpy.types.SpaceView3D.draw_handler_remove(cls._handler, "WINDOW")
            cls._handler = None
        cls.tag_redraw()

    @staticmethod
    def tag_redraw():
        window_manager = getattr(bpy.context, "window_manager", None)
        if window_manager is None:
            return
        for window in window_manager.windows:
            if window.screen is None:
                continue
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

    @staticmethod
    def _draw_group(shader, primitive_type, coordinates, color, size):
        if not coordinates:
            return
        if primitive_type == "LINES":
            gpu.state.line_width_set(size)
        else:
            gpu.state.point_size_set(size)
        shader.bind()
        shader.uniform_float("color", color)
        batch_for_shader(shader, primitive_type, {"pos": coordinates}).draw(shader)

    @classmethod
    def _draw(cls):
        scene = cls._scene
        if scene is None:
            return
        obj = bpy.data.objects.get(scene.object_name)
        if obj is None:
            return

        line_groups = {}
        for start, end, style in scene.lines:
            coordinates = line_groups.setdefault(style, [])
            coordinates.extend((tuple(obj.matrix_world @ start), tuple(obj.matrix_world @ end)))
        point_groups = {}
        for position, style in scene.points:
            point_groups.setdefault(style, []).append(tuple(obj.matrix_world @ position))

        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("LESS_EQUAL")
        try:
            for style, coordinates in line_groups.items():
                cls._draw_group(shader, "LINES", coordinates, style.color, style.width)
            for style, coordinates in point_groups.items():
                cls._draw_group(shader, "POINTS", coordinates, style.color, style.size)
        finally:
            gpu.state.line_width_set(1.0)
            gpu.state.point_size_set(1.0)
            gpu.state.depth_test_set("LESS_EQUAL")
            gpu.state.blend_set("NONE")
