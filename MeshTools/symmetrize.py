"""Mesh-only symmetrize operator and its flick-direction interaction."""

import blf
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty
from bpy_extras.view3d_utils import (
    location_3d_to_region_2d,
    region_2d_to_location_3d,
    region_2d_to_origin_3d,
    region_2d_to_vector_3d,
)
from mathutils import Vector

from Utils.symmetrize import symmetrize
from Utils.hud import begin_hud, end_hud, draw_mouse_hud_rows
from Utils.viewport_draw import draw_circle, draw_point, draw_vector


AXIS_COLORS = {
    "X": (1.0, 0.25, 0.25),
    "Y": (0.3, 1.0, 0.3),
    "Z": (0.3, 0.6, 1.0),
}
_ACTIVE_DRAWS = bpy.app.driver_namespace.setdefault("hotools_symmetrize_draws", {})


def cleanup_symmetrize_huds():
    """Remove previews left by an interrupted modal, reload or disable."""
    for handle, area in list(_ACTIVE_DRAWS.items()):
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
        except (ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        _ACTIVE_DRAWS.pop(handle, None)
        try:
            area.header_text_set(None)
            area.tag_redraw()
        except (ReferenceError, RuntimeError):
            pass


def _direction_label(direction, axis, remove=False):
    source, target = ("+", "-") if direction == "POSITIVE" else ("-", "+")
    if remove:
        return f"保留 {source}{axis}，删除 {target}{axis}"
    return f"{source}{axis} → {target}{axis}"


AXIS_ITEMS = (
    ("X", "X", "Symmetrize along the X axis"),
    ("Y", "Y", "Symmetrize along the Y axis"),
    ("Z", "Z", "Symmetrize along the Z axis"),
)
DIRECTION_ITEMS = (
    ("POSITIVE", "Positive", "Keep the positive side"),
    ("NEGATIVE", "Negative", "Keep the negative side"),
)


def _flick_direction(operator, context):
    """Return the object axis closest to the current mouse flick."""
    origin_2d = location_3d_to_region_2d(
        context.region,
        context.region_data,
        operator.init_mouse_3d,
        default=Vector((context.region.width / 2, context.region.height / 2)),
    )
    projected_axes = {}
    for direction, axis in operator.axes.items():
        axis_2d = location_3d_to_region_2d(
            context.region,
            context.region_data,
            operator.init_mouse_3d + axis,
            default=origin_2d,
        )
        delta = axis_2d - origin_2d
        if delta.length > 1e-6:
            projected_axes[direction] = delta.normalized()
    if not projected_axes or operator.flick_vector.length < 1e-6:
        return "NEGATIVE_X"
    return min(
        (
            (direction, abs(operator.flick_vector.xy.angle_signed(axis)))
            for direction, axis in projected_axes.items()
        ),
        key=lambda item: item[1],
    )[0]


def _symmetrize_direction(flick_direction):
    direction, axis = flick_direction.split("_")
    return ("NEGATIVE" if direction == "POSITIVE" else "POSITIVE", axis)


def _object_axes(matrix):
    basis = matrix.to_quaternion()
    return {
        "POSITIVE_X": basis @ Vector((1, 0, 0)),
        "NEGATIVE_X": basis @ Vector((-1, 0, 0)),
        "POSITIVE_Y": basis @ Vector((0, 1, 0)),
        "NEGATIVE_Y": basis @ Vector((0, -1, 0)),
        "POSITIVE_Z": basis @ Vector((0, 0, 1)),
        "NEGATIVE_Z": basis @ Vector((0, 0, -1)),
    }


class OP_Symmetrize(bpy.types.Operator):
    """Mirror mesh geometry across an object-local axis."""

    bl_idname = "ho.symmetrize"
    bl_label = "Symmetrize Mesh"
    bl_description = "Use Alt-X to symmetrize the active mesh"
    bl_options = {"REGISTER", "UNDO"}

    objmode: BoolProperty(name="Object Mode", default=False)  # type: ignore
    flick: BoolProperty(name="Flick Direction", default=True)  # type: ignore
    axis: EnumProperty(name="Axis", items=AXIS_ITEMS, default="X")  # type: ignore
    direction: EnumProperty(  # type: ignore
        name="Direction",
        items=DIRECTION_ITEMS,
        default="POSITIVE",
    )
    threshold: FloatProperty(  # type: ignore
        name="Threshold",
        default=0.0001,
        min=0.0,
    )
    partial: BoolProperty(name="Selected Only", default=False)  # type: ignore
    remove: BoolProperty(name="Remove Other Side", default=False)  # type: ignore
    remove_redundant_center: BoolProperty(  # type: ignore
        name="Remove Redundant Center",
        default=True,
    )
    is_custom_normal: BoolProperty(default=False, options={"HIDDEN"})  # type: ignore
    mirror_custom_normals: BoolProperty(  # type: ignore
        name="Mirror Custom Normals",
        default=True,
    )
    custom_normal_method: EnumProperty(  # type: ignore
        name="Custom Normal Matching",
        items=(
            ("INDEX", "Index", "Match normals by vertex index"),
            ("LOCATION", "Location", "Match normals by vertex location"),
        ),
        default="INDEX",
    )
    fix_center: BoolProperty(name="Fix Center Seam", default=False)  # type: ignore
    fix_center_method: EnumProperty(  # type: ignore
        name="Center Seam Method",
        items=(
            ("CLEAR", "Clear", "Clear center seam normals"),
            ("TRANSFER", "Transfer", "Transfer center seam normals"),
        ),
        default="CLEAR",
    )
    clear_sharps: BoolProperty(name="Clear Center Sharps", default=True)  # type: ignore

    def _draw_context(self):
        context = bpy.context
        if (context.area != self.area or context.region != self.region
                or self.passthrough):
            return None
        return context

    def draw_HUD(self):
        context = self._draw_context()
        if context is None:
            return
        color = (1.0, 0.25, 0.25) if self.remove else AXIS_COLORS[self.axis]
        draw_circle(self.init_mouse, self.flick_distance, color=color, alpha=0.35)
        draw_vector(
            Vector((*self.flick_vector, 0.0)),
            origin=Vector((*self.init_mouse, 0.0)), color=color, width=2,
            screen=True,
        )
        font = begin_hud(size=round(13 * self.scale))
        try:
            # Labels use the same world vectors as flick picking, including
            # the object's rotation; they remain aligned while orbiting.
            for direction, axis in self.axes.items():
                point = location_3d_to_region_2d(
                    context.region, context.region_data,
                    self.init_mouse_3d + axis * self.axis_length * 1.2,
                )
                if point is None:
                    continue
                sign, axis_name = direction.split("_")
                label = ("+" if sign == "POSITIVE" else "-") + axis_name
                selected = direction == self.flick_direction
                blf.color(font, *AXIS_COLORS[axis_name], 1.0 if selected else 0.65)
                width, height = blf.dimensions(font, label)
                blf.position(font, point.x - width / 2, point.y - height / 2, 0)
                blf.draw(font, label)
        finally:
            end_hud(font)
        rows = [
            (0, "模式: ", "删除另一侧" if self.remove else "强制对称", color),
            (-23, "方向: ", _direction_label(self.direction, self.axis, self.remove), color),
            (-46, "范围: ", "仅选中" if self.partial else "全部（含隐藏）"),
            (-73, "移动鼠标: ", "选择轴向，越过圆圈执行"),
            (-96, "左键 / 空格: ", "确认    右键 / Esc: 取消"),
            (-119, "S / P: ", "切换范围    X / D: 切换模式"),
        ]
        rows = [(round(offset * self.scale), *rest) for offset, *rest in rows]
        draw_mouse_hud_rows(
            (self.init_mouse.x + self.flick_distance, self.init_mouse.y + self.flick_distance),
            rows, offset=round(22 * self.scale), size=round(14 * self.scale),
        )

    def draw_VIEW3D(self):
        if self._draw_context() is None:
            return
        for direction, axis in self.axes.items():
            positive = direction.startswith("POSITIVE")
            selected = direction == self.flick_direction
            draw_vector(
                axis * self.axis_length, origin=self.init_mouse_3d,
                color=AXIS_COLORS[direction[-1]],
                width=3 if selected else (2 if positive else 1),
                alpha=1.0 if selected else (0.65 if positive else 0.3),
            )
        draw_point(
            self.init_mouse_3d + self.axes[self.flick_direction] * self.axis_length,
            color=AXIS_COLORS[self.axis], size=8 * self.scale,
        )

    def _update_header(self):
        mode = "删除另一侧" if self.remove else "强制对称"
        scope = "仅选中" if self.partial else "全部（含隐藏）"
        self.area.header_text_set(
            f"{mode}  |  {_direction_label(self.direction, self.axis, self.remove)}  |  {scope}"
            "  |  移动鼠标选轴 · 左键确认 · Esc取消 · S范围 · X模式"
        )

    def _set_flick_origin(self, context):
        view_origin = region_2d_to_origin_3d(context.region, context.region_data, self.mousepos)
        view_dir = region_2d_to_vector_3d(context.region, context.region_data, self.mousepos)
        self.origin = view_origin + view_dir * 10.0
        self.init_mouse = self.mousepos.copy()
        self.init_mouse_3d = region_2d_to_location_3d(
            context.region, context.region_data, self.init_mouse, self.origin,
        )
        offset = region_2d_to_location_3d(
            context.region, context.region_data,
            self.init_mouse + Vector((self.flick_distance * 0.65, 0)), self.origin,
        )
        self.axis_length = (offset - self.init_mouse_3d).length
        self.flick_vector = Vector((0.0, 0.0))

    def finish(self):
        for name in ("HUD", "VIEW3D"):
            handle = getattr(self, name, None)
            if handle is not None:
                try:
                    bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
                except (ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
                _ACTIVE_DRAWS.pop(handle, None)
                setattr(self, name, None)
        area = getattr(self, "area", None)
        if area is not None:
            try:
                area.header_text_set(None)
                area.tag_redraw()
            except (ReferenceError, RuntimeError):
                pass

    def cancel(self, context):
        self.finish()

    @classmethod
    def poll(cls, context):
        active = context.active_object
        return bool(
            active
            and context.area is not None
            and context.area.type == "VIEW_3D"
            and active.type == "MESH"
            and context.mode in {"EDIT_MESH", "OBJECT"}
        )

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.prop(self, "partial", text="Selected Only", toggle=True)
        row.prop(
            self,
            "remove",
            text="Remove" if self.remove else "Symmetrize",
            toggle=True,
        )
        row = layout.row(align=True)
        row.prop(self, "axis", expand=True)
        row.prop(self, "direction", expand=True)
        layout.prop(self, "threshold")
        if self.remove or self.partial:
            return
        if self.is_custom_normal:
            layout.prop(self, "mirror_custom_normals")
            if self.mirror_custom_normals:
                layout.prop(self, "custom_normal_method", expand=True)
                layout.prop(self, "fix_center")
                if self.fix_center:
                    layout.prop(self, "fix_center_method", expand=True)
                    layout.prop(self, "clear_sharps")
        else:
            layout.prop(self, "remove_redundant_center")

    def modal(self, context, event):
        if context.area != self.area or self.area.type != "VIEW_3D":
            self.finish()
            return {"CANCELLED"}
        context.area.tag_redraw()
        self.mousepos = Vector((event.mouse_region_x, event.mouse_region_y))

        if event.type == "MIDDLEMOUSE" or (
            event.alt and event.type in {"LEFTMOUSE", "RIGHTMOUSE"}
        ) or event.type.startswith("NDOF"):
            self.passthrough = True
            return {"PASS_THROUGH"}

        if event.type == "MOUSEMOVE":
            if self.passthrough:
                self._set_flick_origin(context)
            self.passthrough = False
            self.flick_vector = self.mousepos - self.init_mouse
            if self.flick_vector.length:
                self.flick_direction = _flick_direction(self, context)
                self.direction, self.axis = _symmetrize_direction(
                    self.flick_direction
                )
            if self.flick_vector.length > self.flick_distance:
                return self.execute(context)
        elif event.type in {"X", "D"} and event.value == "PRESS":
            self.remove = not self.remove
        elif event.type in {"S", "P"} and event.value == "PRESS":
            self.partial = not self.partial
        elif event.type in {"LEFTMOUSE", "SPACE"} and event.value == "PRESS":
            self.direction, self.axis = _symmetrize_direction(self.flick_direction)
            return self.execute(context)
        elif event.type in {"RIGHTMOUSE", "ESC"}:
            self.finish()
            return {"CANCELLED"}

        self._update_header()
        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if not self.flick:
            return self.execute(context)

        active = context.active_object
        self.scale = context.preferences.system.ui_scale
        self.flick_distance = 75.0 * self.scale
        self.mousepos = Vector((event.mouse_region_x, event.mouse_region_y))
        self._set_flick_origin(context)
        self.flick_direction = "NEGATIVE_X"
        self.direction, self.axis = _symmetrize_direction(self.flick_direction)
        self.axes = _object_axes(active.matrix_world)
        self.passthrough = False
        self.area, self.region = context.area, context.region
        cleanup_symmetrize_huds()
        try:
            self.HUD = bpy.types.SpaceView3D.draw_handler_add(
                self.draw_HUD, (), "WINDOW", "POST_PIXEL",
            )
            _ACTIVE_DRAWS[self.HUD] = self.area
            self.VIEW3D = bpy.types.SpaceView3D.draw_handler_add(
                self.draw_VIEW3D, (), "WINDOW", "POST_VIEW",
            )
            _ACTIVE_DRAWS[self.VIEW3D] = self.area
            self._update_header()
            context.window_manager.modal_handler_add(self)
        except Exception:
            self.finish()
            raise
        self.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def execute(self, context):
        self.finish()
        active = context.active_object
        self.is_custom_normal = bool(
            getattr(active.data, "has_custom_normals", False)
        )
        was_object_mode = context.mode == "OBJECT"
        if was_object_mode:
            bpy.ops.object.mode_set(mode="EDIT")
        self.result = symmetrize(
            active,
            direction=f"{self.direction}_{self.axis}",
            threshold=self.threshold,
            partial=self.partial,
            remove=self.remove,
            remove_redundant_center=self.remove_redundant_center,
            mirror_custom_normals=self.mirror_custom_normals,
            custom_normal_method=self.custom_normal_method,
            fix_center=self.fix_center,
            fix_center_method=self.fix_center_method,
            clear_sharps=self.clear_sharps,
        )
        if was_object_mode:
            bpy.ops.object.mode_set(mode="OBJECT")
        scope = "仅选中" if self.partial else "全部网格"
        mode = "已删除另一侧" if self.remove else "对称完成"
        self.report({"INFO"}, f"{mode}：{_direction_label(self.direction, self.axis, self.remove)}（{scope}）")
        return {"FINISHED"}
