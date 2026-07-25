"""Single active HoAux preview, following the ordinary aux preview lifecycle."""

from dataclasses import dataclass, field
from math import cos, pi, sin

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector

from .module_base import definitions, get_definition

try:
    from ..previewUtils import AuxPreviewUtils
except ImportError:
    from previewUtils import AuxPreviewUtils


Color = tuple[float, float, float, float]


@dataclass(frozen=True)
class LineStyle:
    color: Color
    width: float = 2.0


@dataclass(frozen=True)
class PointStyle:
    color: Color
    size: float = 8.0


@dataclass(frozen=True)
class LabelStyle:
    color: Color = (0.95, 0.95, 0.95, 1.0)
    size: int = 14


ROLE_LINE_STYLES = {
    "TRK": LineStyle((1.0, 0.72, 0.2, 0.95), 2.0),
    "DEF": LineStyle((0.35, 0.95, 0.55, 0.95), 3.0),
    "DIR": LineStyle((1.0, 0.3, 0.9, 0.95), 3.0),
    "GUIDE": LineStyle((0.95, 0.95, 0.95, 0.85), 1.5),
}
JOINT_POINT_STYLE = PointStyle((1.0, 0.65, 0.15, 1.0), 8.0)


@dataclass
class PreviewScene:
    object_name: str
    title: str = "HoAux"
    message: str = ""
    lines: list[tuple[Vector, Vector, LineStyle]] = field(default_factory=list)
    points: list[tuple[Vector, PointStyle]] = field(default_factory=list)
    labels: list[tuple[Vector, str, LabelStyle]] = field(default_factory=list)

    def add_segment(self, start, end, style):
        self.lines.append((Vector(start), Vector(end), style))

    def add_polyline(self, points, style, *, closed=False):
        points = [Vector(point) for point in points]
        for start, end in zip(points, points[1:]):
            self.add_segment(start, end, style)
        if closed and len(points) > 2:
            self.add_segment(points[-1], points[0], style)

    def add_circle(self, center, normal, radius, style, *, segments=48):
        normal = Vector(normal).normalized()
        tangent = normal.orthogonal().normalized()
        bitangent = normal.cross(tangent).normalized()
        center = Vector(center)
        points = [
            center
            + radius
            * (
                tangent * cos(index * 2.0 * pi / segments)
                + bitangent * sin(index * 2.0 * pi / segments)
            )
            for index in range(segments)
        ]
        self.add_polyline(points, style, closed=True)

    def add_point(self, position, style=JOINT_POINT_STYLE):
        self.points.append((Vector(position), style))

    def add_label(self, position, text, style=LabelStyle()):
        self.labels.append((Vector(position), text, style))

    def add_planned_bones(self, plans, *, labels=False):
        for plan in plans:
            self.add_segment(
                plan.head,
                plan.tail,
                ROLE_LINE_STYLES.get(plan.role_tag, ROLE_LINE_STYLES["GUIDE"]),
            )
            if labels:
                self.add_label(plan.tail, plan.preferred_name)


class ViewportPreview:
    _handler_3d = None
    _handler_2d = None
    _owner_key = None
    _scene = None

    @classmethod
    def is_visible(cls, owner_key=None):
        visible = cls._scene is not None
        return visible and (owner_key is None or cls._owner_key == owner_key)

    @classmethod
    def active_owner(cls):
        return cls._owner_key if cls._scene is not None else None

    @classmethod
    def show(cls, owner_key, scene):
        AuxPreviewUtils.ensure_handlers(cls, cls._draw_3d, cls._draw_2d)
        cls._owner_key = owner_key
        cls._scene = scene
        AuxPreviewUtils.tag_redraw()

    @classmethod
    def clear(cls, owner_key=None):
        if owner_key is not None and owner_key != cls._owner_key:
            return
        cls._scene = None
        cls._owner_key = None
        AuxPreviewUtils.tag_redraw()

    @classmethod
    def shutdown(cls):
        cls.clear()
        AuxPreviewUtils.remove_handlers(cls)

    @classmethod
    def _draw_3d(cls):
        scene = cls._scene
        if scene is None or scene.message:
            return
        obj = bpy.data.objects.get(scene.object_name)
        if obj is None:
            return

        line_groups = {}
        for start, end, style in scene.lines:
            coordinates = line_groups.setdefault(style, [])
            coordinates.extend(
                (tuple(obj.matrix_world @ start), tuple(obj.matrix_world @ end))
            )
        point_groups = {}
        for position, style in scene.points:
            point_groups.setdefault(style, []).append(
                tuple(obj.matrix_world @ position)
            )

        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        try:
            for style, coordinates in line_groups.items():
                gpu.state.line_width_set(style.width)
                AuxPreviewUtils.draw_lines(shader, coordinates, style.color)
            for style, coordinates in point_groups.items():
                AuxPreviewUtils.draw_points(shader, coordinates, style.color, style.size)
        finally:
            gpu.state.line_width_set(1.0)
            gpu.state.depth_test_set("LESS_EQUAL")
            gpu.state.blend_set("NONE")

    @classmethod
    def _draw_2d(cls):
        scene = cls._scene
        if scene is None:
            return
        font_id = 0
        if scene.message:
            AuxPreviewUtils.draw_label(
                font_id,
                f"{scene.title} 预览: {scene.message}",
                (20.0, 40.0),
                (1.0, 0.85, 0.2, 1.0),
                14,
            )
            return

        obj = bpy.data.objects.get(scene.object_name)
        region = bpy.context.region
        region_data = bpy.context.region_data
        if obj is None or region is None or region_data is None:
            return

        line_shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        gpu.state.blend_set("ALPHA")
        gpu.state.line_width_set(1.5)
        try:
            for index, (position, label, style) in enumerate(scene.labels):
                screen = location_3d_to_region_2d(
                    region,
                    region_data,
                    obj.matrix_world @ position,
                )
                if screen is None:
                    continue
                direction = 1.0 if index % 2 == 0 else -1.0
                elbow = (screen.x + direction * 24.0, screen.y + 12.0)
                end = (elbow[0] + direction * 30.0, elbow[1])
                AuxPreviewUtils.draw_lines(
                    line_shader,
                    (tuple(screen), elbow, elbow, end),
                    (*style.color[:3], 0.7),
                )
                text_x = end[0] + (5.0 if direction > 0 else -5.0)
                if direction < 0:
                    blf.size(font_id, style.size)
                    text_x -= blf.dimensions(font_id, label)[0]
                AuxPreviewUtils.draw_label(
                    font_id,
                    label,
                    (text_x, end[1] - style.size * 0.35),
                    style.color,
                    style.size,
                )
        finally:
            gpu.state.line_width_set(1.0)
            gpu.state.blend_set("NONE")


_timer_running = False
_toggle_guard = False
_timer_interval = 0.08


def _settings(definition, scene):
    return definition.settings(scene)


def _start_timer():
    global _timer_running
    if not _timer_running:
        _timer_running = True
        bpy.app.timers.register(_timer)


def _show(context, module_type):
    definition = get_definition(module_type)
    try:
        scene = definition.build_preview_scene(context)
    except (KeyError, TypeError, ValueError, ReferenceError) as exc:
        obj = context.object
        scene = PreviewScene(
            obj.name if obj is not None else "",
            title=definition.label,
            message=str(exc),
        )
    ViewportPreview.show(module_type, scene)
    _start_timer()


def set_module_preview_enabled(context, module_type, enabled):
    global _toggle_guard
    if _toggle_guard:
        return
    _toggle_guard = True
    try:
        if enabled:
            for definition in definitions():
                if definition.type_id == module_type:
                    continue
                settings = _settings(definition, context.scene)
                if settings.preview_enabled:
                    settings.preview_enabled = False
            _show(context, module_type)
        else:
            ViewportPreview.clear(module_type)
    finally:
        _toggle_guard = False


def refresh_active_preview(context):
    module_type = ViewportPreview.active_owner()
    if module_type is None:
        return
    definition = get_definition(module_type)
    if not _settings(definition, context.scene).preview_enabled:
        ViewportPreview.clear(module_type)
        return
    _show(context, module_type)


def _timer():
    global _timer_running
    if ViewportPreview.active_owner() is None:
        _timer_running = False
        return None
    try:
        refresh_active_preview(bpy.context)
    except (AttributeError, KeyError, ReferenceError, RuntimeError, ValueError):
        ViewportPreview.clear()
        _timer_running = False
        return None
    return _timer_interval


def shutdown():
    global _timer_running
    _timer_running = False
    ViewportPreview.shutdown()
