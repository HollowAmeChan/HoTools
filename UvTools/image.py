import blf
import bmesh
import math

import bpy
import gpu
import numpy as np
from bpy.props import BoolProperty, FloatVectorProperty, IntProperty
from bpy.types import Context, Operator, UILayout
from gpu_extras.batch import batch_for_shader


DEFAULT_SELECTION_WIDTH = 2048
DEFAULT_SELECTION_HEIGHT = 2048
DEFAULT_BRUSH_RADIUS = 48
MIN_BRUSH_RADIUS = 1
MAX_BRUSH_RADIUS = 2048
BRUSH_RADIUS_SCROLL_STEP = 8

_RECT_SHADER = None
_RECT_SHADER_NAME = None


MODE_LABELS = {
    "SET": "替换",
    "ADD": "加选",
    "SUB": "减选",
}

MODE_COLORS = {
    "SET": ((0.2, 0.55, 1.0, 0.18), (0.2, 0.55, 1.0, 1.0)),
    "ADD": ((0.2, 0.9, 0.35, 0.16), (0.2, 0.9, 0.35, 1.0)),
    "SUB": ((1.0, 0.18, 0.12, 0.14), (1.0, 0.18, 0.12, 1.0)),
}

VIEW_NAVIGATION_EVENTS = {
    "WHEELUPMOUSE",
    "WHEELDOWNMOUSE",
    "WHEELINMOUSE",
    "WHEELOUTMOUSE",
    "TRACKPADPAN",
    "TRACKPADZOOM",
    "MOUSEPAN",
    "MOUSEZOOM",
}


class ImageSelection:
    def __init__(self, width=DEFAULT_SELECTION_WIDTH, height=DEFAULT_SELECTION_HEIGHT):
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.mask = np.zeros((self.height, self.width), dtype=np.uint8)
        self.selected_pixels = 0
        self.operation_count = 0
        self.last_rect_px = (0, 0, 0, 0)
        self.last_mode = "SET"
        self._overlay_rects = []
        self._overlay_dirty = True

    def ensure_size(self, width, height):
        width = max(1, int(width))
        height = max(1, int(height))
        if self.width == width and self.height == height:
            return

        self.mask = _resize_mask_nearest(self.mask, width, height)
        self.width = width
        self.height = height
        self.selected_pixels = int(np.count_nonzero(self.mask))
        self.operation_count = 0
        self.last_rect_px = (0, 0, 0, 0)
        self.last_mode = "SET"
        self._overlay_rects = []
        self._overlay_dirty = True

    def apply_rect(self, rect_px, mode):
        x0, y0, x1, y1 = _clamp_pixel_rect(rect_px, self.width, self.height)

        if mode == "SET":
            self.mask.fill(0)

        if x0 < x1 and y0 < y1:
            region = self.mask[y0:y1, x0:x1]
            if mode in {"SET", "ADD"}:
                region[:] = 1
            elif mode == "SUB":
                region[:] = 0

        self.last_rect_px = (x0, y0, x1, y1)
        self.last_mode = mode
        self._commit_change()
        return x0 < x1 and y0 < y1

    def apply_brush(self, center_px, radius_px, mode):
        cx, cy = center_px
        radius = max(1.0, float(radius_px))
        x0 = max(0, int(math.floor(cx - radius)))
        x1 = min(self.width, int(math.ceil(cx + radius)) + 1)
        y0 = max(0, int(math.floor(cy - radius)))
        y1 = min(self.height, int(math.ceil(cy + radius)) + 1)
        if x0 >= x1 or y0 >= y1:
            return False

        xs = np.arange(x0, x1, dtype=np.float64) + 0.5
        ys = np.arange(y0, y1, dtype=np.float64) + 0.5
        grid_x, grid_y = np.meshgrid(xs, ys)
        circle = (grid_x - cx) ** 2 + (grid_y - cy) ** 2 <= radius ** 2
        if not np.any(circle):
            return False

        value = 0 if mode == "SUB" else 1
        region = self.mask[y0:y1, x0:x1]
        if not np.any(region[circle] != value):
            return False

        region[circle] = value
        self.last_rect_px = (x0, y0, x1, y1)
        self.last_mode = mode
        self._commit_change()
        return True

    def apply_polygon(self, points, mode):
        points = np.asarray(points, dtype=np.float64)
        if points.shape[0] < 3:
            return False

        x0 = max(0, int(math.floor(float(points[:, 0].min()) * self.width)))
        x1 = min(self.width, int(math.ceil(float(points[:, 0].max()) * self.width)))
        y0 = max(0, int(math.floor(float(points[:, 1].min()) * self.height)))
        y1 = min(self.height, int(math.ceil(float(points[:, 1].max()) * self.height)))

        changed = False
        if mode == "SET":
            changed = bool(np.any(self.mask))
            self.mask.fill(0)

        if x0 < x1 and y0 < y1:
            xs = (np.arange(x0, x1, dtype=np.float64) + 0.5) / self.width
            ys = (np.arange(y0, y1, dtype=np.float64) + 0.5) / self.height
            grid_x, grid_y = np.meshgrid(xs, ys)
            polygon = _points_in_polygon(grid_x, grid_y, points)
            if np.any(polygon):
                value = 0 if mode == "SUB" else 1
                region = self.mask[y0:y1, x0:x1]
                if np.any(region[polygon] != value):
                    region[polygon] = value
                    changed = True

        if not changed:
            return False

        self.last_rect_px = (x0, y0, x1, y1)
        self.last_mode = mode
        self._commit_change()
        return True

    def invert(self):
        np.bitwise_xor(self.mask, 1, out=self.mask)
        self.last_mode = "INV"
        self._commit_change()

    def clear(self):
        self.mask.fill(0)
        self.last_mode = "CLEAR"
        self._commit_change()

    def replace_mask(self, mask, mode):
        self.mask = mask.astype(np.uint8, copy=True)
        self.last_mode = mode
        self.last_rect_px = (0, 0, self.width, self.height)
        self._commit_change()

    def _commit_change(self):
        self.selected_pixels = int(np.count_nonzero(self.mask))
        self.operation_count += 1
        self._overlay_dirty = True

    def overlay_rects(self):
        if self._overlay_dirty:
            self._overlay_rects = _mask_to_pixel_rects(self.mask)
            self._overlay_dirty = False
        return self._overlay_rects


class SelectionOverlay:
    selection = None
    draw_handle = None

    @classmethod
    def get_selection(cls, context=None):
        if cls.selection is None:
            width, height = cls._target_size(context)
            cls.selection = ImageSelection(width, height)
        return cls.selection

    @classmethod
    def current_selection(cls):
        return cls.selection

    @classmethod
    def needs_canvas_refresh(cls, scene):
        selection = cls.selection
        if selection is None:
            return False

        return (
            selection.width != int(scene.ho_uvtools_image_selection_width)
            or selection.height != int(scene.ho_uvtools_image_selection_height)
        )

    @classmethod
    def draw(cls):
        scene = getattr(bpy.context, "scene", None)
        if scene is None or not getattr(scene, "ho_uvtools_image_selection_show", False):
            return

        if cls.selection is not None:
            _draw_selection_mask(cls.selection)
        _draw_image_border()

    @classmethod
    def ensure_draw_handler(cls):
        if cls.draw_handle is None:
            cls.draw_handle = bpy.types.SpaceImageEditor.draw_handler_add(
                cls.draw, (), "WINDOW", "POST_VIEW"
            )

    @classmethod
    def remove_draw_handler(cls):
        if cls.draw_handle is not None:
            bpy.types.SpaceImageEditor.draw_handler_remove(cls.draw_handle, "WINDOW")
            cls.draw_handle = None

    @classmethod
    def sync_visibility(cls, context):
        scene = getattr(context, "scene", None)
        if scene is not None and scene.ho_uvtools_image_selection_show:
            cls.ensure_draw_handler()
        else:
            cls.remove_draw_handler()
        _tag_image_editors_redraw(context)

    @classmethod
    def force_visible(cls, context):
        scene = getattr(context, "scene", None)
        if scene is not None and not scene.ho_uvtools_image_selection_show:
            scene.ho_uvtools_image_selection_show = True
        cls.ensure_draw_handler()
        _tag_image_editors_redraw(context)

    @classmethod
    def refresh(cls, context):
        scene = getattr(context, "scene", None)
        if scene is not None and scene.ho_uvtools_image_selection_show:
            cls.ensure_draw_handler()
        _tag_image_editors_redraw(context)

    @classmethod
    def reset(cls):
        cls.remove_draw_handler()
        cls.selection = None

    @staticmethod
    def _target_size(context):
        scene = getattr(context, "scene", None) if context is not None else None
        if scene is not None and hasattr(scene, "ho_uvtools_image_selection_width"):
            return scene.ho_uvtools_image_selection_width, scene.ho_uvtools_image_selection_height
        return DEFAULT_SELECTION_WIDTH, DEFAULT_SELECTION_HEIGHT


def _resize_mask_nearest(mask, width, height):
    if mask.size == 0:
        return np.zeros((height, width), dtype=np.uint8)

    old_height, old_width = mask.shape
    if old_width == width and old_height == height:
        return mask

    x_idx = (np.arange(width, dtype=np.int64) * old_width) // width
    y_idx = (np.arange(height, dtype=np.int64) * old_height) // height
    x_idx = np.minimum(x_idx, old_width - 1)
    y_idx = np.minimum(y_idx, old_height - 1)
    return mask[y_idx[:, None], x_idx[None, :]].astype(np.uint8, copy=True)


def get_current_selection():
    return SelectionOverlay.current_selection()


def _get_active_image(context):
    space = context.space_data
    if space is None or not hasattr(space, "image"):
        return None
    return space.image


def _active_image_name(context):
    image = _get_active_image(context)
    return image.name if image is not None else "无活动图像"


def _active_image_size(context):
    image = _get_active_image(context)
    if image is None:
        return None

    width, height = image.size
    width = int(width)
    height = int(height)
    if width < 1 or height < 1:
        return None

    return width, height


def _get_window_region(area):
    if area is None:
        return None
    for region in area.regions:
        if region.type == "WINDOW":
            return region
    return None


def _event_to_region_xy(area, event):
    region = _get_window_region(area)
    if region is None:
        return None

    x = event.mouse_x - region.x
    y = event.mouse_y - region.y
    return x, y, region


def _is_in_window_region(area, event):
    data = _event_to_region_xy(area, event)
    if data is None:
        return False

    x, y, region = data
    return 0 <= x <= region.width and 0 <= y <= region.height


def _event_to_view_xy(area, event):
    data = _event_to_region_xy(area, event)
    if data is None:
        return None

    x, y, region = data
    return region.view2d.region_to_view(x, y)


def _event_select_mode(event):
    if event.shift:
        return "ADD"
    if event.ctrl:
        return "SUB"
    return "SET"


def _view_rect_to_pixel_rect(rect, width, height):
    x0, y0, x1, y1 = rect
    min_x = min(x0, x1)
    max_x = max(x0, x1)
    min_y = min(y0, y1)
    max_y = max(y0, y1)

    px0 = math.floor(min_x * width)
    px1 = math.ceil(max_x * width)
    py0 = math.floor(min_y * height)
    py1 = math.ceil(max_y * height)
    return _clamp_pixel_rect((px0, py0, px1, py1), width, height)


def _view_xy_to_pixel_xy(view_xy, selection):
    return view_xy[0] * selection.width, view_xy[1] * selection.height


def _clamp_pixel_rect(rect, width, height):
    x0, y0, x1, y1 = rect
    x0 = max(0, min(width, int(x0)))
    x1 = max(0, min(width, int(x1)))
    y0 = max(0, min(height, int(y0)))
    y1 = max(0, min(height, int(y1)))
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _mask_to_pixel_rects(mask):
    height, _width = mask.shape
    rects = []
    active = {}

    for y in range(height):
        row = mask[y]
        padded = np.empty(row.size + 2, dtype=np.int16)
        padded[0] = 0
        padded[-1] = 0
        padded[1:-1] = row
        changes = np.diff(padded)
        starts = np.flatnonzero(changes == 1)
        ends = np.flatnonzero(changes == -1)
        current = set()

        for x0, x1 in zip(starts, ends):
            key = (int(x0), int(x1))
            current.add(key)
            if key in active:
                active[key][3] = y + 1
            else:
                active[key] = [int(x0), y, int(x1), y + 1]

        for key in list(active.keys()):
            if key not in current:
                rects.append(tuple(active.pop(key)))

    rects.extend(tuple(rect) for rect in active.values())
    return rects


def _editable_mesh_objects(context):
    objects = getattr(context, "objects_in_mode_unique_data", None)
    if objects:
        return [obj for obj in objects if obj.type == "MESH" and obj.mode == "EDIT"]

    obj = context.edit_object or context.object
    if obj is not None and obj.type == "MESH" and obj.mode == "EDIT":
        return [obj]

    return []


def _require_uv_face_mode(context):
    objects = _editable_mesh_objects(context)
    if not objects:
        return None, "需要在 Mesh 编辑模式下执行"

    tool_settings = context.tool_settings
    if not tool_settings.use_uv_select_sync:
        return None, "操作需要开启 UV 同步模式"
    if tuple(tool_settings.mesh_select_mode) != (False, False, True):
        return None, "需要切换到面选择模式"

    if not any(obj.data.uv_layers.active for obj in objects):
        return None, "当前物体没有活动 UV 层"

    return objects, None


def _selected_uv_polygons_from_edit_mesh(context, objects):
    polygons = []

    for obj in objects:
        polygons.extend(_selected_uv_polygons_from_object(obj))

    return polygons


def _selected_uv_polygons_from_object(obj):
    mesh = obj.data
    bm = bmesh.from_edit_mesh(mesh)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()

    active_uv = mesh.uv_layers.active
    uv_layer = bm.loops.layers.uv.get(active_uv.name) if active_uv is not None else None
    if uv_layer is None:
        uv_layer = bm.loops.layers.uv.active
    if uv_layer is None:
        return []

    polygons = []
    for face in bm.faces:
        if face.hide:
            continue
        uv_loops = [loop[uv_layer] for loop in face.loops]
        selected = _mesh_face_selected(face)
        if not selected or len(face.loops) < 3:
            continue

        polygons.append([(uv_loop.uv.x, uv_loop.uv.y) for uv_loop in uv_loops])
    return polygons


def _mesh_face_selected(face):
    if face.select:
        return True
    return all(loop.vert.select for loop in face.loops)


def _points_in_polygon(x, y, points):
    inside = np.zeros_like(x, dtype=bool)
    x_prev, y_prev = points[-1]
    for x_curr, y_curr in points:
        crosses = (y_curr > y) != (y_prev > y)
        x_at_y = (x_prev - x_curr) * (y - y_curr) / (y_prev - y_curr + 1e-12) + x_curr
        inside ^= crosses & (x < x_at_y)
        x_prev, y_prev = x_curr, y_curr
    return inside


def _fill_uv_polygon_mask(mask, polygon):
    height, width = mask.shape
    points = np.asarray(polygon, dtype=np.float64)
    if points.shape[0] < 3:
        return

    x0 = max(0, int(math.floor(float(points[:, 0].min()) * width)))
    x1 = min(width, int(math.ceil(float(points[:, 0].max()) * width)))
    y0 = max(0, int(math.floor(float(points[:, 1].min()) * height)))
    y1 = min(height, int(math.ceil(float(points[:, 1].max()) * height)))
    if x0 >= x1 or y0 >= y1:
        return

    xs = (np.arange(x0, x1, dtype=np.float64) + 0.5) / width
    ys = (np.arange(y0, y1, dtype=np.float64) + 0.5) / height
    grid_x, grid_y = np.meshgrid(xs, ys)
    mask[y0:y1, x0:x1][_points_in_polygon(grid_x, grid_y, points)] = 1


def _uv_polygons_to_mask(polygons, width, height):
    mask = np.zeros((height, width), dtype=np.uint8)
    for polygon in polygons:
        _fill_uv_polygon_mask(mask, polygon)
    return mask


def _get_rect_shader():
    global _RECT_SHADER, _RECT_SHADER_NAME

    if _RECT_SHADER is not None:
        return _RECT_SHADER, _RECT_SHADER_NAME

    for name in ("UNIFORM_COLOR", "2D_UNIFORM_COLOR"):
        try:
            _RECT_SHADER = gpu.shader.from_builtin(name)
            _RECT_SHADER_NAME = name
            return _RECT_SHADER, _RECT_SHADER_NAME
        except Exception:
            pass

    return None, None


def _shader_coords(coords, shader_name):
    if shader_name and shader_name.startswith("2D_"):
        return coords
    return [(x, y, 0.0) for x, y in coords]


def _rect_fill_line_coords(rect):
    x0, y0, x1, y1 = rect
    fill_coords = [
        (x0, y0),
        (x0, y1),
        (x1, y1),
        (x0, y0),
        (x1, y1),
        (x1, y0),
    ]
    line_coords = [
        (x0, y0),
        (x0, y1),
        (x0, y1),
        (x1, y1),
        (x1, y1),
        (x1, y0),
        (x1, y0),
        (x0, y0),
    ]
    return fill_coords, line_coords


def _pixel_rect_to_view_rect(rect, selection):
    x0, y0, x1, y1 = rect
    return (
        x0 / selection.width,
        y0 / selection.height,
        x1 / selection.width,
        y1 / selection.height,
    )


def _draw_view_rect(rect, mode, active=True):
    shader, shader_name = _get_rect_shader()
    if shader is None:
        return

    fill_coords, line_coords = _rect_fill_line_coords(rect)
    fill_batch = batch_for_shader(shader, "TRIS", {"pos": _shader_coords(fill_coords, shader_name)})
    line_batch = batch_for_shader(shader, "LINES", {"pos": _shader_coords(line_coords, shader_name)})
    fill_color, line_color = MODE_COLORS.get(mode, MODE_COLORS["SET"])

    gpu.state.blend_set("ALPHA")
    shader.bind()
    shader.uniform_float("color", fill_color)
    fill_batch.draw(shader)

    gpu.state.line_width_set(2.0 if active else 1.0)
    shader.uniform_float("color", line_color)
    line_batch.draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set("NONE")


def _circle_line_coords(center, radius_x, radius_y, segments=72):
    cx, cy = center
    coords = []
    previous = (cx + radius_x, cy)
    for i in range(1, segments + 1):
        angle = math.tau * i / segments
        current = (cx + math.cos(angle) * radius_x, cy + math.sin(angle) * radius_y)
        coords.extend((previous, current))
        previous = current
    return coords


def _draw_brush_circle(center, selection, radius_px, mode):
    shader, shader_name = _get_rect_shader()
    if shader is None or selection is None:
        return

    radius_x = max(1.0, float(radius_px)) / selection.width
    radius_y = max(1.0, float(radius_px)) / selection.height
    coords = _circle_line_coords(center, radius_x, radius_y)
    batch = batch_for_shader(shader, "LINES", {"pos": _shader_coords(coords, shader_name)})
    _fill_color, line_color = MODE_COLORS.get(mode, MODE_COLORS["ADD"])

    gpu.state.blend_set("ALPHA")
    gpu.state.line_width_set(2.0)
    shader.bind()
    shader.uniform_float("color", line_color)
    batch.draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set("NONE")


def _draw_selection_mask(selection):
    rects = selection.overlay_rects()
    if not rects:
        return

    shader, shader_name = _get_rect_shader()
    if shader is None:
        return

    coords = []
    for rect_px in rects:
        coords.extend(_rect_fill_line_coords(_pixel_rect_to_view_rect(rect_px, selection))[0])

    batch = batch_for_shader(shader, "TRIS", {"pos": _shader_coords(coords, shader_name)})
    gpu.state.blend_set("ALPHA")
    shader.bind()
    shader.uniform_float("color", (0.2, 0.55, 1.0, 0.24))
    batch.draw(shader)
    gpu.state.blend_set("NONE")


def _draw_image_border():
    shader, shader_name = _get_rect_shader()
    if shader is None:
        return

    _fill_coords, line_coords = _rect_fill_line_coords((0.0, 0.0, 1.0, 1.0))
    batch = batch_for_shader(shader, "LINES", {"pos": _shader_coords(line_coords, shader_name)})
    gpu.state.blend_set("ALPHA")
    gpu.state.line_width_set(3.0)
    shader.bind()
    shader.uniform_float("color", (1.0, 0.48, 0.05, 0.95))
    batch.draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set("NONE")


def _draw_edit_overlay(operator):
    if getattr(operator, "edit_mode", "BOX") == "BRUSH":
        if operator.mouse_view_xy is not None:
            mode = operator.brush_mode or "ADD"
            _draw_brush_circle(operator.mouse_view_xy, operator.selection, operator.brush_radius, mode)
        return

    if operator.start_view_xy is None or operator.end_view_xy is None:
        return

    x0, y0 = operator.start_view_xy
    x1, y1 = operator.end_view_xy
    _draw_view_rect((x0, y0, x1, y1), operator.select_mode, active=True)


def _tag_image_editors_redraw(context):
    screen = getattr(context, "screen", None)
    if screen is None:
        return

    for area in screen.areas:
        if area.type == "IMAGE_EDITOR":
            area.tag_redraw()


def _update_selection_show(self, context):
    SelectionOverlay.sync_visibility(context)


def _draw_hud_line(font_id, x, y, key_text, value_text, value_color=(1.0, 1.0, 1.0, 1.0)):
    blf.color(font_id, 1.0, 0.85, 0.2, 1.0)
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, key_text)
    key_width, _ = blf.dimensions(font_id, key_text)

    blf.color(font_id, *value_color)
    blf.position(font_id, x + key_width, y, 0)
    blf.draw(font_id, value_text)


def _draw_hud(operator):
    font_id = 0
    blf.size(font_id, 16)

    x, y = operator.mouse_region_xy
    x += 20
    y += 20

    blf.enable(font_id, blf.SHADOW)
    blf.shadow(font_id, 3, 0.0, 0.0, 0.0, 0.6)
    blf.shadow_offset(font_id, 1, -1)

    if operator.edit_mode == "BRUSH":
        if operator.brush_active:
            mode_label = "清空" if operator.brush_mode == "SUB" else "添加"
            _draw_hud_line(font_id, x, y + 88, "状态:", "涂抹中", (0.35, 1.0, 0.35, 1.0))
            _draw_hud_line(font_id, x, y + 66, "模式:", mode_label)
        else:
            _draw_hud_line(font_id, x, y + 88, "状态:", "画笔待命", (1.0, 0.65, 0.18, 1.0))
            _draw_hud_line(font_id, x, y + 66, "左键/Shift+左键:", "添加 / 清空")

        _draw_hud_line(font_id, x, y + 44, "大小:", str(int(operator.brush_radius)))
        _draw_hud_line(font_id, x, y + 22, "Shift+滚轮:", "调整大小")
        _draw_hud_line(font_id, x, y, "E:", "切到框选")
    else:
        if operator.waiting_start:
            _draw_hud_line(font_id, x, y + 88, "状态:", "等待框选", (1.0, 0.65, 0.18, 1.0))
            _draw_hud_line(font_id, x, y + 66, "左键:", "拖拽创建区域")
        else:
            mode_label = MODE_LABELS.get(operator.select_mode, operator.select_mode)
            _draw_hud_line(font_id, x, y + 88, "状态:", "拖拽中", (0.35, 1.0, 0.35, 1.0))
            _draw_hud_line(font_id, x, y + 66, "模式:", mode_label)

        _draw_hud_line(font_id, x, y + 44, "Shift/Ctrl:", "加选 / 减选")
        _draw_hud_line(font_id, x, y + 22, "Ctrl+I:", "反选")
        _draw_hud_line(font_id, x, y, "E:", "切到画笔")

    _draw_hud_line(font_id, x, y - 22, "Esc/右键:", "退出")

    blf.disable(font_id, blf.SHADOW)


class OP_UVTools_ImageBoxSelect(Operator):
    bl_idname = "ho.uvtools_image_box_select"
    bl_label = "编辑图像选区"
    bl_description = "在图像编辑器中用框选或画笔编辑 HoTools 固定分辨率硬选区"
    bl_options = {"REGISTER"}

    draw_handle_view = None
    draw_handle_hud = None
    area = None
    selection = None
    edit_mode = "BOX"
    waiting_start = False
    ignore_until_release = False
    view_navigation_active = False
    select_mode = "SET"
    brush_active = False
    brush_mode = "ADD"
    brush_radius = DEFAULT_BRUSH_RADIUS
    mouse_region_xy = (20, 20)
    mouse_view_xy = None
    start_view_xy = None
    end_view_xy = None

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "IMAGE_EDITOR"

    def _tag_redraw(self):
        if self.area is not None:
            self.area.tag_redraw()

    def _clear_draw_handlers(self):
        if self.draw_handle_view is not None:
            bpy.types.SpaceImageEditor.draw_handler_remove(self.draw_handle_view, "WINDOW")
            self.draw_handle_view = None
        if self.draw_handle_hud is not None:
            bpy.types.SpaceImageEditor.draw_handler_remove(self.draw_handle_hud, "WINDOW")
            self.draw_handle_hud = None

    def _update_mouse(self, event):
        data = _event_to_region_xy(self.area, event)
        if data is None:
            return False

        x, y, region = data
        self.mouse_region_xy = (x, y)
        self.mouse_view_xy = region.view2d.region_to_view(x, y)
        return True

    def _reset_box_state(self):
        self.waiting_start = True
        self.ignore_until_release = False
        self.select_mode = "SET"
        self.start_view_xy = None
        self.end_view_xy = None

    def _reset_brush_state(self):
        self.brush_active = False
        self.brush_mode = "ADD"

    def _toggle_edit_mode(self, event):
        self._reset_box_state()
        self._reset_brush_state()
        self.edit_mode = "BRUSH" if self.edit_mode == "BOX" else "BOX"
        self._update_mouse(event)
        self._tag_redraw()

    def _begin_drag(self, event):
        view_xy = _event_to_view_xy(self.area, event)
        if view_xy is None:
            return False

        self.start_view_xy = view_xy
        self.end_view_xy = view_xy
        self.select_mode = _event_select_mode(event)
        self.waiting_start = False
        self._tag_redraw()
        return True

    def _update_drag(self, event):
        view_xy = _event_to_view_xy(self.area, event)
        if view_xy is None:
            return

        self.end_view_xy = view_xy
        self._update_mouse(event)
        self._tag_redraw()

    def _commit_box(self, context):
        if self.selection is None or self.start_view_xy is None or self.end_view_xy is None:
            self.waiting_start = True
            self._tag_redraw()
            return {"RUNNING_MODAL"}

        x0, y0 = self.start_view_xy
        x1, y1 = self.end_view_xy
        view_rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        rect_px = _view_rect_to_pixel_rect(view_rect, self.selection.width, self.selection.height)
        self.selection.apply_rect(rect_px, self.select_mode)

        context.scene.ho_uvtools_image_box_select_rect = view_rect
        context.scene.ho_uvtools_image_box_select_has_rect = True

        SelectionOverlay.refresh(context)

        self.waiting_start = True
        self.ignore_until_release = False
        self.start_view_xy = None
        self.end_view_xy = None
        self._tag_redraw()
        return {"RUNNING_MODAL"}

    def _invert_selection(self, context):
        if self.selection is None:
            return

        self.selection.invert()
        SelectionOverlay.refresh(context)

    def _paint(self, context, event):
        if self.selection is None or not self._update_mouse(event):
            return

        center_px = _view_xy_to_pixel_xy(self.mouse_view_xy, self.selection)
        if self.selection.apply_brush(center_px, self.brush_radius, self.brush_mode):
            SelectionOverlay.refresh(context)
        self._tag_redraw()

    def _set_brush_radius(self, context, value):
        self.brush_radius = int(max(MIN_BRUSH_RADIUS, min(MAX_BRUSH_RADIUS, value)))
        context.scene.ho_uvtools_image_brush_radius = self.brush_radius
        self._tag_redraw()

    def _adjust_brush_radius(self, context, event):
        direction = 1 if event.type in {"WHEELUPMOUSE", "WHEELINMOUSE"} else -1
        self._set_brush_radius(context, self.brush_radius + direction * BRUSH_RADIUS_SCROLL_STEP)
        self._update_mouse(event)
        self._tag_redraw()

    def _cancel(self):
        self._clear_draw_handlers()
        self._tag_redraw()
        return {"CANCELLED"}

    def _pass_through_view_navigation(self, event):
        if event.type == "MIDDLEMOUSE":
            self._update_mouse(event)
            self._tag_redraw()
            self.view_navigation_active = event.value != "RELEASE"
            return True

        if self.view_navigation_active and event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            self._update_mouse(event)
            self._tag_redraw()
            return True

        if event.type in VIEW_NAVIGATION_EVENTS:
            self._update_mouse(event)
            self._tag_redraw()
            return True

        return False

    def invoke(self, context, event):
        self.area = context.area
        self.selection = SelectionOverlay.get_selection(context)
        SelectionOverlay.force_visible(context)

        self.edit_mode = "BOX"
        self._reset_box_state()
        self._reset_brush_state()
        self.ignore_until_release = event.type == "LEFTMOUSE" and event.value != "RELEASE"
        self.view_navigation_active = False
        self.brush_radius = int(context.scene.ho_uvtools_image_brush_radius)
        self.mouse_region_xy = (20, 20)
        self.mouse_view_xy = None
        self.start_view_xy = None
        self.end_view_xy = None
        self._update_mouse(event)

        self.draw_handle_view = bpy.types.SpaceImageEditor.draw_handler_add(
            _draw_edit_overlay, (self,), "WINDOW", "POST_VIEW"
        )
        self.draw_handle_hud = bpy.types.SpaceImageEditor.draw_handler_add(
            _draw_hud, (self,), "WINDOW", "POST_PIXEL"
        )

        context.window_manager.modal_handler_add(self)
        self._tag_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            return self._cancel()

        if event.type == "E" and event.value == "PRESS":
            self._toggle_edit_mode(event)
            return {"RUNNING_MODAL"}

        if event.type == "I" and event.value == "PRESS" and event.ctrl:
            self._invert_selection(context)
            return {"RUNNING_MODAL"}

        if (
            self.edit_mode == "BRUSH"
            and event.shift
            and event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE", "WHEELINMOUSE", "WHEELOUTMOUSE"}
        ):
            self._adjust_brush_radius(context, event)
            return {"RUNNING_MODAL"}

        if self._pass_through_view_navigation(event):
            return {"PASS_THROUGH"}

        if self.edit_mode == "BRUSH":
            if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
                if self.brush_active:
                    self.brush_mode = "SUB" if event.shift else "ADD"
                    self._paint(context, event)
                else:
                    self._update_mouse(event)
                    self._tag_redraw()
                return {"RUNNING_MODAL"}

            if event.type == "LEFTMOUSE":
                if event.value == "PRESS" and _is_in_window_region(self.area, event):
                    self.brush_active = True
                    self.brush_mode = "SUB" if event.shift else "ADD"
                    self._paint(context, event)
                    return {"RUNNING_MODAL"}

                if event.value == "RELEASE":
                    if self.brush_active:
                        self.brush_mode = "SUB" if event.shift else "ADD"
                        self._paint(context, event)
                    else:
                        self._update_mouse(event)
                    self.brush_active = False
                    self._tag_redraw()
                    return {"RUNNING_MODAL"}

            return {"RUNNING_MODAL"}

        if self.waiting_start:
            if self.ignore_until_release:
                if event.type == "LEFTMOUSE" and event.value == "RELEASE":
                    self.ignore_until_release = False
                return {"RUNNING_MODAL"}

            if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
                self._update_mouse(event)
                self._tag_redraw()
                return {"RUNNING_MODAL"}

            if event.type == "LEFTMOUSE" and event.value == "PRESS" and _is_in_window_region(self.area, event):
                self._update_mouse(event)
                self._begin_drag(event)
                return {"RUNNING_MODAL"}

            return {"RUNNING_MODAL"}

        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            self._update_mouse(event)
            self._update_drag(event)
            self._tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            self._update_drag(event)
            return self._commit_box(context)

        return {"RUNNING_MODAL"}


class OP_UVTools_ImageRefreshSelectionCanvas(Operator):
    bl_idname = "ho.uvtools_image_refresh_selection_canvas"
    bl_label = "刷新选区画布"
    bl_description = "按当前画布宽高重采样 HoTools 硬选区"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selection = SelectionOverlay.get_selection(context)
        selection.ensure_size(
            context.scene.ho_uvtools_image_selection_width,
            context.scene.ho_uvtools_image_selection_height,
        )

        SelectionOverlay.refresh(context)
        return {"FINISHED"}


class OP_UVTools_ImageClearSelection(Operator):
    bl_idname = "ho.uvtools_image_clear_selection"
    bl_label = "清空选区"
    bl_description = "清空 HoTools 当前硬选区"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selection = SelectionOverlay.get_selection(context)
        selection.clear()

        SelectionOverlay.refresh(context)
        return {"FINISHED"}


class OP_UVTools_ImageFillSelectionFromSelectedUv(Operator):
    bl_idname = "ho.uvtools_image_fill_selection_from_selected_uv"
    bl_label = "从选中UV填充遮罩"
    bl_description = "用当前选中的 UV 面填充 HoTools 当前硬选区遮罩"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objects, error = _require_uv_face_mode(context)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        polygons = _selected_uv_polygons_from_edit_mesh(context, objects)
        if not polygons:
            self.report({"WARNING"}, "没有选中的 UV 面")
            return {"CANCELLED"}

        selection = SelectionOverlay.get_selection(context)
        mask = _uv_polygons_to_mask(polygons, selection.width, selection.height)
        if not np.any(mask):
            self.report({"WARNING"}, "选中的 UV 面没有覆盖当前选区画布")
            return {"CANCELLED"}

        selection.replace_mask(mask, "UV")
        SelectionOverlay.refresh(context)
        self.report({"INFO"}, f"已从 {len(polygons)} 个 UV 面填充遮罩")
        return {"FINISHED"}


class OP_UVTools_ImageSetSelectionCanvasDefault(Operator):
    bl_idname = "ho.uvtools_image_set_selection_canvas_default"
    bl_label = "默认选区画布"
    bl_description = "将目标选区画布尺寸设为 2048 x 2048"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context.scene.ho_uvtools_image_selection_width = DEFAULT_SELECTION_WIDTH
        context.scene.ho_uvtools_image_selection_height = DEFAULT_SELECTION_HEIGHT
        _tag_image_editors_redraw(context)
        return {"FINISHED"}


class OP_UVTools_ImageSetSelectionCanvasFromImage(Operator):
    bl_idname = "ho.uvtools_image_set_selection_canvas_from_image"
    bl_label = "使用当前图像尺寸"
    bl_description = "将目标选区画布尺寸设为当前 Image Editor 图像尺寸"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        size = _active_image_size(context)
        if size is None:
            self.report({"WARNING"}, "当前 Image Editor 没有有效图像尺寸")
            return {"CANCELLED"}

        width, height = size
        context.scene.ho_uvtools_image_selection_width = width
        context.scene.ho_uvtools_image_selection_height = height
        _tag_image_editors_redraw(context)
        return {"FINISHED"}


def reg_props():
    bpy.types.Scene.ho_uvtools_image_selection_show = BoolProperty(
        name="显示选区",
        description="在图像编辑器中持续显示 HoTools 硬选区",
        default=False,
        update=_update_selection_show,
    )
    bpy.types.Scene.ho_uvtools_image_selection_width = IntProperty(
        name="选区宽度",
        default=DEFAULT_SELECTION_WIDTH,
        min=1,
    )
    bpy.types.Scene.ho_uvtools_image_selection_height = IntProperty(
        name="选区高度",
        default=DEFAULT_SELECTION_HEIGHT,
        min=1,
    )
    bpy.types.Scene.ho_uvtools_image_brush_radius = IntProperty(
        name="画笔大小",
        default=DEFAULT_BRUSH_RADIUS,
        min=MIN_BRUSH_RADIUS,
        max=MAX_BRUSH_RADIUS,
    )
    bpy.types.Scene.ho_uvtools_image_box_select_has_rect = BoolProperty(
        name="有图像选区",
        default=False,
    )
    bpy.types.Scene.ho_uvtools_image_box_select_rect = FloatVectorProperty(
        name="图像选区",
        description="图像编辑器视图坐标中的最后一次矩形选区: min_x, min_y, max_x, max_y",
        size=4,
        default=(0.0, 0.0, 0.0, 0.0),
    )


def ureg_props():
    SelectionOverlay.reset()
    if hasattr(bpy.types.Scene, "ho_uvtools_image_box_select_rect"):
        del bpy.types.Scene.ho_uvtools_image_box_select_rect
    if hasattr(bpy.types.Scene, "ho_uvtools_image_box_select_has_rect"):
        del bpy.types.Scene.ho_uvtools_image_box_select_has_rect
    if hasattr(bpy.types.Scene, "ho_uvtools_image_brush_radius"):
        del bpy.types.Scene.ho_uvtools_image_brush_radius
    if hasattr(bpy.types.Scene, "ho_uvtools_image_selection_height"):
        del bpy.types.Scene.ho_uvtools_image_selection_height
    if hasattr(bpy.types.Scene, "ho_uvtools_image_selection_width"):
        del bpy.types.Scene.ho_uvtools_image_selection_width
    if hasattr(bpy.types.Scene, "ho_uvtools_image_selection_show"):
        del bpy.types.Scene.ho_uvtools_image_selection_show


def drawImagePanel(layout: UILayout, context: Context):
    scene = context.scene
    
    box = layout.box()
    box.label(text=f"{_active_image_name(context)}")
    col = box.column(align=True)
    row = col.row(align=True)
    row.alert = SelectionOverlay.needs_canvas_refresh(scene)
    row.operator(OP_UVTools_ImageRefreshSelectionCanvas.bl_idname, text="", icon="FILE_REFRESH")
    row.alert = False
    row.prop(scene, "ho_uvtools_image_selection_width", text="")
    row.prop(scene, "ho_uvtools_image_selection_height", text="")
    row.operator(OP_UVTools_ImageSetSelectionCanvasDefault.bl_idname, text="", icon="RECOVER_LAST")
    image_size_row = row.row(align=True)
    image_size_row.enabled = _active_image_size(context) is not None
    image_size_row.operator(OP_UVTools_ImageSetSelectionCanvasFromImage.bl_idname, text="", icon="IMAGE_DATA")

    box = layout.box()
    row = box.row(align=True)
    row.scale_y = 2
    row.prop(scene, "ho_uvtools_image_selection_show", text="", toggle=True, icon="OVERLAY")
    row.operator(OP_UVTools_ImageBoxSelect.bl_idname, text="编辑选区", icon="SELECT_SET")
    row.operator(OP_UVTools_ImageClearSelection.bl_idname, text="", icon="TRASH")

    row = box.row(align=True)
    row.operator(OP_UVTools_ImageFillSelectionFromSelectedUv.bl_idname, text="选中UV填充遮罩",)


cls = [
    OP_UVTools_ImageBoxSelect,
    OP_UVTools_ImageRefreshSelectionCanvas,
    OP_UVTools_ImageClearSelection,
    OP_UVTools_ImageFillSelectionFromSelectedUv,
    OP_UVTools_ImageSetSelectionCanvasDefault,
    OP_UVTools_ImageSetSelectionCanvasFromImage,
]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    ureg_props()
    for i in reversed(cls):
        bpy.utils.unregister_class(i)
