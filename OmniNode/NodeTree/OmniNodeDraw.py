import bpy
import blf
import textwrap
import gpu
from gpu_extras.batch import batch_for_shader

from .OmniCurve import resolve_color_curve, resolve_float_curve


_HANDLES = {}
_PAYLOADS = {}
_WARNED = set()
_RIGHT_OVERLAY_GAP_X = 12


def _warn_once(key, message):
    if key in _WARNED:
        return
    _WARNED.add(key)
    print(message)


def _overlay_id(node, kind="error"):
    return f"omni_{kind}::{node.id_data.name_full}::{node.name}"


def _wrap_text(text, width=40):
    wrapped_lines = []
    for line in str(text or "").strip().splitlines():
        line = line.strip()
        if not line:
            wrapped_lines.append("")
            continue
        wrapped_lines.extend(textwrap.wrap(line, width=width) or [line])
    return "\n".join(wrapped_lines)


def _absolute_location(node):
    loc = getattr(node, "absolute_location", None)
    if loc is not None:
        return float(loc[0]), float(loc[1])

    loc = getattr(node, "location_absolute", None)
    if loc is not None:
        return float(loc[0]), float(loc[1])

    x, y = node.location
    parent = node.parent
    while parent is not None:
        x += parent.location[0]
        y += parent.location[1]
        parent = parent.parent
    return float(x), float(y)


def _view_to_region(x, y):
    region = getattr(bpy.context, "region", None)
    if region is None:
        return None
    view2d = getattr(region, "view2d", None)
    if view2d is None:
        return None
    try:
        return view2d.view_to_region(float(x), float(y), clip=False)
    except Exception:
        return None


def _tag_node_editors(tree_name=None):
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return

    for window in wm.windows:
        for area in window.screen.areas:
            if area.type != 'NODE_EDITOR':
                continue
            space = area.spaces.active
            tree = getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)
            if tree_name is not None and getattr(tree, "name_full", None) != tree_name:
                continue
            area.tag_redraw()


def _get_line_height(scale=1.0):
    ui_scale = bpy.context.preferences.system.ui_scale
    return int(18 * scale * ui_scale)


def _get_text_height(scale=1.0):
    ui_scale = bpy.context.preferences.system.ui_scale
    return int(15 * scale * ui_scale)


def _get_node_width(node, fallback=1.0):
    if getattr(node, "hide", False):
        width_hidden = getattr(node, "width_hidden", None)
        if width_hidden is not None:
            return float(width_hidden)

    width = getattr(node, "width", None)
    if width is not None:
        return float(width)

    return float(fallback)


def _get_text_location(node, text, scale, align='UP'):
    x, y = _absolute_location(node)
    gap = 10

    try:
        dx, dy = node.dimensions
    except (TypeError, ValueError):
        dx, dy = 1, 1

    if align == "RIGHT":
        x, y = int(x + _get_node_width(node, dx) + _RIGHT_OVERLAY_GAP_X), int(y)
    elif align == "UP":
        if getattr(node, "hide", False):
            visible_inputs = len([s for s in node.inputs if not s.hide])
            visible_outputs = len([s for s in node.outputs if not s.hide])
            max_sock_num = max(visible_inputs, visible_outputs)
            gap += (max_sock_num * 0.3) * max_sock_num
        line_height = _get_line_height(scale)
        n = len(text.split('\n'))
        x, y = int(x), int(y + (n - 1) * line_height + gap)
    elif align == "DOWN":
        line_height = _get_line_height(scale)
        x, y = int(x), int(y - dy - line_height)
    else:
        x, y = int(x), int(y)
    return x, y


def _draw_text_handler(overlay_id):
    payload = _PAYLOADS.get(overlay_id)
    if payload is None:
        return

    editor = bpy.context.space_data
    if editor is None or editor.type != 'NODE_EDITOR':
        return

    edit_tree = getattr(editor, "edit_tree", None) or getattr(editor, "node_tree", None)
    if edit_tree is None or getattr(edit_tree, "name_full", None) != payload["tree_name"]:
        return

    node = edit_tree.nodes.get(payload["node_name"])
    if node is None:
        return

    x, y = _get_text_location(node, payload["text"], payload["scale"], payload["align"])

    ui_scale = bpy.context.preferences.system.ui_scale
    x, y = x * ui_scale, y * ui_scale

    font_id = 0
    text_height = _get_text_height(payload["scale"])
    line_height = _get_line_height(payload["scale"])

    blf.size(font_id, text_height)
    blf.color(font_id, *payload["color"])
    blf.enable(font_id, blf.SHADOW)
    blf.shadow(font_id, 3, 0.0, 0.0, 0.0, 0.35)
    blf.shadow_offset(font_id, 1, -1)

    for line in payload["text"].split('\n'):
        blf.position(font_id, x, y, 0)
        blf.draw(font_id, line)
        y -= line_height

    blf.disable(font_id, blf.SHADOW)


class DrawCurveSocket:
    """曲线 socket 的只读预览绘制。"""

    GLOBAL_OVERLAY_ID = "omni_curve_preview::global"
    SOCKET_TYPES = {"OmniNodeSocketFloatCurve", "OmniNodeSocketColorCurve"}

    @staticmethod
    def overlay_id(sock, kind="curve_preview"):
        node = sock.node
        direction = "OUT" if sock in node.outputs[:] else "IN"
        return f"omni_{kind}::{node.id_data.name_full}::{node.name}::{direction}::{sock.identifier}"

    @staticmethod
    def draw_batch(kind, points, color, width=1.0):
        if not points:
            return

        points_2d = [(float(point[0]), float(point[1])) for point in points]
        points_3d = [(point[0], point[1], 0.0) for point in points_2d]
        attempts = (
            ("UNIFORM_COLOR", points_3d),
            ("2D_UNIFORM_COLOR", points_2d),
        )
        last_error = None
        for shader_name, shader_points in attempts:
            try:
                gpu.state.blend_set('ALPHA')
                gpu.state.line_width_set(width)
                shader = gpu.shader.from_builtin(shader_name)
                batch = batch_for_shader(shader, kind, {"pos": shader_points})
                shader.bind()
                shader.uniform_float("color", color)
                batch.draw(shader)
                return
            except Exception as exc:
                last_error = exc
            finally:
                try:
                    gpu.state.line_width_set(1.0)
                    gpu.state.blend_set('NONE')
                except Exception:
                    pass

        _warn_once(
            "curve_preview_draw_batch",
            f"OmniNode 曲线预览绘制失败：{last_error}",
        )

    @staticmethod
    def draw_rect(left, bottom, right, top, color):
        points = [
            (left, bottom),
            (right, bottom),
            (right, top),
            (left, bottom),
            (right, top),
            (left, top),
        ]
        DrawCurveSocket.draw_batch('TRIS', points, color)

    @staticmethod
    def draw_polyline(points, color, width=1.0):
        if len(points) < 2:
            return
        segments = []
        for index in range(len(points) - 1):
            segments.append(points[index])
            segments.append(points[index + 1])
        DrawCurveSocket.draw_batch('LINES', segments, color, width=width)

    @staticmethod
    def draw_label(text, x, y, color=(0.88, 0.92, 1.0, 1.0), size=11, align="CENTER"):
        if text is None:
            return
        font_id = 0
        ui_scale = bpy.context.preferences.system.ui_scale
        blf.size(font_id, int(size * ui_scale))
        label = str(text)
        try:
            width, _height = blf.dimensions(font_id, label)
        except Exception:
            width = 0
        if align == "CENTER":
            x -= width * 0.5
        elif align == "RIGHT":
            x -= width
        blf.color(font_id, *color)
        blf.position(font_id, x, y, 0)
        blf.draw(font_id, label)

    @staticmethod
    def format_axis_value(value):
        value = float(value)
        if abs(value) < 0.000001:
            return "0"
        if abs(value - round(value)) < 0.000001 and abs(value) <= 9:
            return str(int(round(value)))
        return f"{value:.2g}"

    @staticmethod
    def curve_from_payload(payload):
        if not isinstance(payload, dict):
            return None, None
        kind = str(payload.get("kind", ""))
        if kind == "float_curve":
            return resolve_float_curve(payload), "float"
        if kind == "color_curve":
            return resolve_color_curve(payload), "color"
        return None, None

    @staticmethod
    def socket_from_payload(node, payload):
        sockets = node.outputs if payload.get("socket_is_output") else node.inputs
        socket_name = payload.get("socket_name")
        socket_identifier = payload.get("socket_identifier")
        socket_index = payload.get("socket_index")

        if socket_name:
            sock = sockets.get(socket_name)
            if sock is not None:
                return sock

        if socket_identifier:
            sock = sockets.get(socket_identifier)
            if sock is not None:
                return sock
            for item in sockets:
                if getattr(item, "identifier", None) == socket_identifier:
                    return item

        if socket_index is not None:
            try:
                return sockets[int(socket_index)]
            except Exception:
                pass

        return None

    @staticmethod
    def stack_index(node, sock):
        get_index = getattr(node, "omni_curve_preview_index", None)
        if callable(get_index):
            return max(0, int(get_index(sock, DrawCurveSocket.SOCKET_TYPES)))

        visible = DrawCurveSocket.preview_sockets_for_node(node)
        try:
            return max(0, visible.index(sock))
        except ValueError:
            return 0

    @staticmethod
    def node_rect(node, sock):
        x, y = _get_text_location(node, "", 1.0, align="RIGHT")
        ui_scale = bpy.context.preferences.system.ui_scale
        x *= ui_scale
        y *= ui_scale

        preview_width = 210
        preview_height = 145
        stack_gap = 14
        stack_index = DrawCurveSocket.stack_index(node, sock)
        left = float(x)
        top = float(y) - stack_index * (preview_height + stack_gap)
        return left, top, left + preview_width, top - preview_height

    @staticmethod
    def region_rect(node, sock):
        left, top, right, bottom = DrawCurveSocket.node_rect(node, sock)
        return min(left, right), min(bottom, top), max(left, right), max(bottom, top)

    @staticmethod
    def axis_values(minimum, maximum):
        values = [float(minimum), float(maximum)]
        for value in (-1.0, 0.0, 1.0):
            if minimum <= value <= maximum:
                values.append(value)
        result = []
        for value in values:
            if not any(abs(value - item) < 0.0001 for item in result):
                result.append(value)
        return sorted(result)

    @staticmethod
    def draw_preview(payload, rect, title=""):
        curve, curve_type = DrawCurveSocket.curve_from_payload(payload)
        if curve is None:
            return

        left, bottom, right, top = rect
        if right - left < 12 or top - bottom < 12:
            return

        DrawCurveSocket.draw_rect(left, bottom, right, top, (0.045, 0.052, 0.065, 0.88))
        DrawCurveSocket.draw_polyline(
            [(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)],
            (0.35, 0.42, 0.52, 0.95),
            width=1.0,
        )

        pad_left = 34
        pad_right = 12
        pad_top = 22
        pad_bottom = 24
        plot_left = left + pad_left
        plot_right = right - pad_right
        plot_top = top - pad_top
        plot_bottom = bottom + pad_bottom

        sample_count = 96
        xs = [index / float(sample_count - 1) for index in range(sample_count)]
        if curve_type == "color":
            y_min, y_max = 0.0, 1.0
        else:
            sample_values = [curve.sample(x) for x in xs]
            point_values = [point["y"] for point in curve.points]
            y_min = min(sample_values + point_values)
            y_max = max(sample_values + point_values)
            if abs(y_max - y_min) < 0.000001:
                padding = max(abs(y_max) * 0.2, 1.0)
                y_min -= padding
                y_max += padding
            else:
                padding = (y_max - y_min) * 0.08
                y_min -= padding
                y_max += padding

        def sx(value):
            return plot_left + float(value) * (plot_right - plot_left)

        def sy(value):
            if abs(y_max - y_min) < 0.000001:
                return (plot_bottom + plot_top) * 0.5
            return plot_bottom + (float(value) - y_min) / (y_max - y_min) * (plot_top - plot_bottom)

        grid_color = (0.25, 0.31, 0.39, 0.65)
        axis_color = (0.62, 0.68, 0.76, 0.9)
        for x_value in (0.0, 1.0):
            x = sx(x_value)
            DrawCurveSocket.draw_polyline([(x, plot_bottom), (x, plot_top)], axis_color, width=1.0)
            DrawCurveSocket.draw_label(
                DrawCurveSocket.format_axis_value(x_value),
                x,
                bottom + 7,
                (0.72, 0.78, 0.86, 1.0),
                size=9,
            )

        for y_value in DrawCurveSocket.axis_values(y_min, y_max):
            y = sy(y_value)
            color = axis_color if abs(y_value) < 0.000001 else grid_color
            DrawCurveSocket.draw_polyline([(plot_left, y), (plot_right, y)], color, width=1.0)
            DrawCurveSocket.draw_label(
                DrawCurveSocket.format_axis_value(y_value),
                plot_left - 5,
                y - 4,
                (0.72, 0.78, 0.86, 1.0),
                size=9,
                align="RIGHT",
            )

        if curve_type == "color":
            channels = [
                (0, (1.0, 0.25, 0.22, 1.0), "R"),
                (1, (0.3, 0.95, 0.42, 1.0), "G"),
                (2, (0.32, 0.55, 1.0, 1.0), "B"),
            ]
            for channel, color, _label in channels:
                points = [(sx(x), sy(curve.sample(x)[channel])) for x in xs]
                DrawCurveSocket.draw_polyline(points, color, width=1.8)
            DrawCurveSocket.draw_label("R", right - 39, top - 16, (1.0, 0.25, 0.22, 1.0), size=9)
            DrawCurveSocket.draw_label("G", right - 26, top - 16, (0.3, 0.95, 0.42, 1.0), size=9)
            DrawCurveSocket.draw_label("B", right - 13, top - 16, (0.32, 0.55, 1.0, 1.0), size=9)
        else:
            points = [(sx(x), sy(curve.sample(x))) for x in xs]
            DrawCurveSocket.draw_polyline(points, (0.38, 0.86, 1.0, 1.0), width=2.0)

        preview_title = str(title or "曲线")
        DrawCurveSocket.draw_label(preview_title, left + 8, top - 15, (0.88, 0.93, 1.0, 1.0), size=10, align="LEFT")

    @staticmethod
    def iter_preview_sockets(tree):
        for node in getattr(tree, "nodes", ()):
            for sock in DrawCurveSocket.preview_sockets_for_node(node):
                yield node, sock

    @staticmethod
    def preview_sockets_for_node(node):
        get_sockets = getattr(node, "omni_curve_preview_sockets", None)
        if callable(get_sockets):
            return list(get_sockets(DrawCurveSocket.SOCKET_TYPES))

        sockets = list(getattr(node, "inputs", ())) + list(getattr(node, "outputs", ()))
        visible = [
            item for item in sockets
            if getattr(item, "preview_curve", False)
            and getattr(item, "bl_idname", "") in DrawCurveSocket.SOCKET_TYPES
        ]
        return visible

    @staticmethod
    def handler(*_args):
        editor = bpy.context.space_data
        if editor is None or editor.type != 'NODE_EDITOR':
            return

        edit_tree = getattr(editor, "edit_tree", None) or getattr(editor, "node_tree", None)
        if edit_tree is None:
            return

        for node, sock in DrawCurveSocket.iter_preview_sockets(edit_tree):
            try:
                curve_payload = sock.default_value
                rect = DrawCurveSocket.region_rect(node, sock)
                if rect is None:
                    continue
                DrawCurveSocket.draw_preview(curve_payload, rect, title=sock.name)
            except Exception as exc:
                _warn_once(
                    "curve_preview_handler",
                    f"OmniNode 曲线预览回调失败：{exc}",
                )

    @staticmethod
    def ensure_handler():
        if DrawCurveSocket.GLOBAL_OVERLAY_ID in _HANDLES:
            return
        _PAYLOADS[DrawCurveSocket.GLOBAL_OVERLAY_ID] = {"tree_name": None}
        _HANDLES[DrawCurveSocket.GLOBAL_OVERLAY_ID] = bpy.types.SpaceNodeEditor.draw_handler_add(
            DrawCurveSocket.handler,
            (),
            'WINDOW',
            'POST_VIEW',
        )

    @staticmethod
    def clear(sock):
        _tag_node_editors(sock.node.id_data.name_full)

    @staticmethod
    def is_visible(sock):
        return bool(getattr(sock, "preview_curve", False))

    @staticmethod
    def draw(sock):
        DrawCurveSocket.ensure_handler()
        _tag_node_editors(sock.node.id_data.name_full)

    @staticmethod
    def sync(sock):
        if getattr(sock, "preview_curve", False):
            DrawCurveSocket.draw(sock)
        else:
            DrawCurveSocket.clear(sock)


def callback_disable(overlay_id):
    handle = _HANDLES.pop(overlay_id, None)
    payload = _PAYLOADS.pop(overlay_id, None)
    if handle is not None:
        bpy.types.SpaceNodeEditor.draw_handler_remove(handle, 'WINDOW')
    if payload is not None:
        _tag_node_editors(payload["tree_name"])


def draw_text(node, text, color=(1.0, 0.35, 0.35, 1.0), scale=1.3, align="UP", kind="error"):
    overlay_id = _overlay_id(node, kind)
    callback_disable(overlay_id)
    _PAYLOADS[overlay_id] = {
        "tree_name": node.id_data.name_full,
        "node_name": node.name,
        "text": text,
        "color": color,
        "scale": scale,
        "align": align,
    }
    _HANDLES[overlay_id] = bpy.types.SpaceNodeEditor.draw_handler_add(
        _draw_text_handler,
        (overlay_id,),
        'WINDOW',
        'POST_VIEW',
    )
    _tag_node_editors(node.id_data.name_full)


def clear_description(node):
    callback_disable(_overlay_id(node, "description"))


def is_description_visible(node):
    return _overlay_id(node, "description") in _PAYLOADS


def description_text(node):
    text = str(getattr(node, "omni_description", "") or "").strip()
    if not text or text == "No description":
        return ""
    return text


def draw_description(node):
    text = description_text(node)
    if not text:
        clear_description(node)
        return False

    wrapped = _wrap_text(text, width=48) or text
    draw_text(
        node,
        wrapped,
        color=(0.62, 0.82, 1.0, 1.0),
        scale=1.05,
        align="RIGHT",
        kind="description",
    )
    return True


def sync_bug_text(node):
    if getattr(node, "is_bug", False) and getattr(node, "bug_text", ""):
        clear_description(node)
        wrapped = _wrap_text(node.bug_text, width=36) or node.bug_text
        draw_text(node, wrapped, kind="error")
    else:
        callback_disable(_overlay_id(node, "error"))


def clear_tree(tree):
    prefix = f"omni_error::{tree.name_full}::"
    for overlay_id in list(_HANDLES.keys()):
        if overlay_id.startswith(prefix):
            callback_disable(overlay_id)


def register():
    DrawCurveSocket.ensure_handler()


def unregister():
    for overlay_id in list(_HANDLES.keys()):
        callback_disable(overlay_id)
