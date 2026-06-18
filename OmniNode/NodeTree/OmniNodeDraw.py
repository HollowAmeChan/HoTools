import bpy
import blf
import gpu
import textwrap
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


def _overlay_id(node, kind):
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
        line_count = len(text.split('\n'))
        x, y = int(x), int(y + (line_count - 1) * line_height + gap)
    elif align == "DOWN":
        line_height = _get_line_height(scale)
        x, y = int(x), int(y - dy - line_height)
    else:
        x, y = int(x), int(y)
    return x, y


def _draw_text_overlay_handler(overlay_id):
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


def _clear_overlay(overlay_id):
    handle = _HANDLES.pop(overlay_id, None)
    payload = _PAYLOADS.pop(overlay_id, None)
    if handle is not None:
        bpy.types.SpaceNodeEditor.draw_handler_remove(handle, 'WINDOW')
    if payload is not None:
        _tag_node_editors(payload.get("tree_name"))


def _draw_text_overlay(node, text, color=(1.0, 0.35, 0.35, 1.0), scale=1.3, align="UP", kind="error"):
    overlay_id = _overlay_id(node, kind)
    _clear_overlay(overlay_id)
    _PAYLOADS[overlay_id] = {
        "tree_name": node.id_data.name_full,
        "node_name": node.name,
        "text": text,
        "color": color,
        "scale": scale,
        "align": align,
    }
    _HANDLES[overlay_id] = bpy.types.SpaceNodeEditor.draw_handler_add(
        _draw_text_overlay_handler,
        (overlay_id,),
        'WINDOW',
        'POST_VIEW',
    )
    _tag_node_editors(node.id_data.name_full)


def _clear_text_tree(tree, kinds):
    prefixes = tuple(f"omni_{kind}::{tree.name_full}::" for kind in kinds)
    overlay_ids = set(_HANDLES.keys()) | set(_PAYLOADS.keys())
    for overlay_id in list(overlay_ids):
        if overlay_id.startswith(prefixes):
            _clear_overlay(overlay_id)


class DrawBug:
    """绘制节点 Bug 信息。"""

    KIND = "error"
    COLOR = (1.0, 0.35, 0.35, 1.0)

    @staticmethod
    def text(node):
        if not getattr(node, "is_bug", False):
            return ""
        return str(getattr(node, "bug_text", "") or "").strip()

    @staticmethod
    def clear(node):
        _clear_overlay(_overlay_id(node, DrawBug.KIND))

    @staticmethod
    def draw(node):
        text = DrawBug.text(node)
        if not text:
            DrawBug.clear(node)
            return False

        wrapped = _wrap_text(text, width=36) or text
        _draw_text_overlay(node, wrapped, color=DrawBug.COLOR, kind=DrawBug.KIND)
        return True

    @staticmethod
    def sync(node):
        return DrawBug.draw(node)

    @staticmethod
    def clear_tree(tree):
        _clear_text_tree(tree, (DrawBug.KIND,))

    @staticmethod
    def side_panel_block(node):
        text = DrawBug.text(node)
        if not text:
            return None
        return {
            "kind": "text",
            "title": "错误",
            "text": text,
            "height": 115,
            "color": DrawBug.COLOR,
        }


class DrawDescription:
    """绘制节点说明。"""

    KIND = "description"
    COLOR = (0.62, 0.82, 1.0, 1.0)

    @staticmethod
    def text(node):
        text = str(getattr(node, "omni_description", "") or "").strip()
        if not text or text == "No description":
            return ""
        return text

    @staticmethod
    def clear(node):
        _clear_overlay(_overlay_id(node, DrawDescription.KIND))

    @staticmethod
    def is_visible(node):
        return _overlay_id(node, DrawDescription.KIND) in _PAYLOADS

    @staticmethod
    def draw(node):
        text = DrawDescription.text(node)
        if not text:
            DrawDescription.clear(node)
            return False

        wrapped = _wrap_text(text, width=120) or text
        _draw_text_overlay(
            node,
            wrapped,
            color=DrawDescription.COLOR,
            scale=1.05,
            align="RIGHT",
            kind=DrawDescription.KIND,
        )
        return True

    @staticmethod
    def clear_tree(tree):
        _clear_text_tree(tree, (DrawDescription.KIND,))


class DrawSocketView:
    """绘制节点侧栏 socket 预览。"""

    SOCKET_TYPES = {"OmniNodeSocketFloatCurve", "OmniNodeSocketColorCurve"}

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
            "socket_view_draw_batch",
            f"OmniNode 侧栏预览绘制失败：{last_error}",
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
        DrawSocketView.draw_batch('TRIS', points, color)

    @staticmethod
    def draw_polyline(points, color, width=1.0):
        if len(points) < 2:
            return
        segments = []
        for index in range(len(points) - 1):
            segments.append(points[index])
            segments.append(points[index + 1])
        DrawSocketView.draw_batch('LINES', segments, color, width=width)

    @staticmethod
    def draw_square(cx, cy, size, color):
        half = size * 0.5
        DrawSocketView.draw_rect(cx - half, cy - half, cx + half, cy + half, color)

    @staticmethod
    def draw_curve_segment(curve, index, sx, sy, channel=None, color=(1.0, 1.0, 1.0, 1.0), width=1.0):
        points = curve.points
        if index < 0 or index >= len(points) - 1:
            return
        left = points[index]
        right = points[index + 1]
        x0 = float(left["x"])
        x1 = float(right["x"])
        if x1 < x0:
            return

        segment_interpolation = curve.segment_interpolation(index)
        if channel is None:
            y0 = float(left["y"])
            y1 = float(right["y"])
            sample_value = lambda x: curve.sample(x)
        else:
            y0 = float(left["color"][channel])
            y1 = float(right["color"][channel])
            sample_value = lambda x: curve.sample(x)[channel]

        if segment_interpolation == "CONSTANT":
            DrawSocketView.draw_polyline([(sx(x0), sy(y0)), (sx(x1), sy(y0))], color, width=width)
            DrawSocketView.draw_polyline([(sx(x1), sy(y0)), (sx(x1), sy(y1))], color, width=1.0)
            return

        if segment_interpolation == "LINEAR" or abs(x1 - x0) < 0.000001:
            DrawSocketView.draw_polyline([(sx(x0), sy(y0)), (sx(x1), sy(y1))], color, width=width)
            return

        sample_count = 24
        segment_points = []
        for sample_index in range(sample_count):
            factor = sample_index / float(sample_count - 1)
            x = x0 * (1.0 - factor) + x1 * factor
            segment_points.append((sx(x), sy(sample_value(x))))
        DrawSocketView.draw_polyline(segment_points, color, width=width)

    @staticmethod
    def draw_curve_handles(curve, sx, sy, channel=None, color=(0.75, 0.82, 0.92, 0.72)):
        points = curve.points
        for index in range(max(0, len(points) - 1)):
            if curve.segment_interpolation(index) != "BEZIER":
                continue

            if channel is None:
                left_value = float(points[index]["y"])
                right_value = float(points[index + 1]["y"])
                handles = curve.segment_handles(index)
            else:
                left_value = float(points[index]["color"][channel])
                right_value = float(points[index + 1]["color"][channel])
                handles = curve.segment_handles(index, channel)
            if not handles:
                continue

            left_handle, right_handle = handles
            left_point = (sx(points[index]["x"]), sy(left_value))
            right_point = (sx(points[index + 1]["x"]), sy(right_value))
            left_handle_point = (sx(left_handle["x"]), sy(left_handle["y"]))
            right_handle_point = (sx(right_handle["x"]), sy(right_handle["y"]))

            DrawSocketView.draw_polyline([left_point, left_handle_point], color, width=1.0)
            DrawSocketView.draw_polyline([right_point, right_handle_point], color, width=1.0)
            DrawSocketView.draw_square(left_handle_point[0], left_handle_point[1], 4, color)
            DrawSocketView.draw_square(right_handle_point[0], right_handle_point[1], 4, color)

    @staticmethod
    def draw_curve_points(curve, sx, sy, channel=None, color=(1.0, 1.0, 1.0, 1.0)):
        for point in curve.points:
            if channel is None:
                value = point["y"]
            else:
                value = point["color"][channel]
            x = sx(point["x"])
            y = sy(value)
            DrawSocketView.draw_square(x, y, 7, (0.02, 0.025, 0.032, 0.9))
            DrawSocketView.draw_square(x, y, 5, color)

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
        curve, curve_type = DrawSocketView.curve_from_payload(payload)
        if curve is None:
            return

        left, bottom, right, top = rect
        if right - left < 12 or top - bottom < 12:
            return

        DrawSocketView.draw_rect(left, bottom, right, top, (0.045, 0.052, 0.065, 0.88))
        DrawSocketView.draw_polyline(
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
            DrawSocketView.draw_polyline([(x, plot_bottom), (x, plot_top)], axis_color, width=1.0)
            DrawSocketView.draw_label(
                DrawSocketView.format_axis_value(x_value),
                x,
                bottom + 7,
                (0.72, 0.78, 0.86, 1.0),
                size=9,
            )

        for y_value in DrawSocketView.axis_values(y_min, y_max):
            y = sy(y_value)
            color = axis_color if abs(y_value) < 0.000001 else grid_color
            DrawSocketView.draw_polyline([(plot_left, y), (plot_right, y)], color, width=1.0)
            DrawSocketView.draw_label(
                DrawSocketView.format_axis_value(y_value),
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
                handle_color = (color[0], color[1], color[2], 0.45)
                DrawSocketView.draw_curve_handles(curve, sx, sy, channel=channel, color=handle_color)
                for point_index in range(len(curve.points) - 1):
                    DrawSocketView.draw_curve_segment(
                        curve,
                        point_index,
                        sx,
                        sy,
                        channel=channel,
                        color=color,
                        width=1.8,
                    )
                DrawSocketView.draw_curve_points(curve, sx, sy, channel=channel, color=color)
            DrawSocketView.draw_label("R", right - 39, top - 16, (1.0, 0.25, 0.22, 1.0), size=9)
            DrawSocketView.draw_label("G", right - 26, top - 16, (0.3, 0.95, 0.42, 1.0), size=9)
            DrawSocketView.draw_label("B", right - 13, top - 16, (0.32, 0.55, 1.0, 1.0), size=9)
        else:
            curve_color = (0.38, 0.86, 1.0, 1.0)
            DrawSocketView.draw_curve_handles(curve, sx, sy, color=(0.68, 0.84, 0.96, 0.72))
            for point_index in range(len(curve.points) - 1):
                DrawSocketView.draw_curve_segment(
                    curve,
                    point_index,
                    sx,
                    sy,
                    color=curve_color,
                    width=2.0,
                )
            DrawSocketView.draw_curve_points(curve, sx, sy, color=curve_color)

        preview_title = str(title or "曲线")
        DrawSocketView.draw_label(preview_title, left + 8, top - 15, (0.88, 0.93, 1.0, 1.0), size=10, align="LEFT")

    def preview_sockets_for_node(node):
        get_sockets = getattr(node, "omni_curve_preview_sockets", None)
        if callable(get_sockets):
            return list(get_sockets(DrawSocketView.SOCKET_TYPES))

        return [
            item for item in getattr(node, "inputs", ())
            if getattr(item, "bl_idname", "") in DrawSocketView.SOCKET_TYPES
        ]

    @staticmethod
    def side_panel_blocks(node):
        return [
            {
                "kind": "curve",
                "title": sock.name,
                "socket": sock,
                "height": 145,
            }
            for sock in DrawSocketView.preview_sockets_for_node(node)
        ]

    @staticmethod
    def draw_block(block, rect):
        sock = block["socket"]
        DrawSocketView.draw_preview(sock.default_value, rect, title=block["title"])


class DrawSidePanel:
    """统一管理节点侧栏区块排列。"""

    GLOBAL_OVERLAY_ID = "omni_node_side_panel::global"
    WIDTH = 210
    STACK_GAP = 14

    @staticmethod
    def node_anchor(node):
        x, y = _get_text_location(node, "", 1.0, align="RIGHT")
        ui_scale = bpy.context.preferences.system.ui_scale
        return float(x * ui_scale), float(y * ui_scale)

    @staticmethod
    def item_rect(node, index, item_height, item_width=None):
        x, y = DrawSidePanel.node_anchor(node)
        left = float(x)
        top = float(y) - index * (item_height + DrawSidePanel.STACK_GAP)
        width = float(item_width or DrawSidePanel.WIDTH)
        return left, top, left + width, top - item_height

    @staticmethod
    def region_rect(node, index, block):
        left, top, right, bottom = DrawSidePanel.item_rect(
            node,
            index,
            block["height"],
            block.get("width"),
        )
        return min(left, right), min(bottom, top), max(left, right), max(bottom, top)

    @staticmethod
    def iter_nodes(tree):
        for node in getattr(tree, "nodes", ()):
            if (
                getattr(node, "omni_view_preview", False)
                or bool(DrawBug.text(node))
            ):
                yield node

    @staticmethod
    def blocks_for_node(node):
        blocks = []
        for block in (DrawBug.side_panel_block(node),):
            if block:
                blocks.append(block)
        if getattr(node, "omni_view_preview", False):
            blocks.extend(DrawSocketView.side_panel_blocks(node))
        return blocks

    @staticmethod
    def draw_text_panel(text, rect, title="说明", color=(0.62, 0.82, 1.0, 1.0)):
        left, bottom, right, top = rect
        DrawSocketView.draw_rect(left, bottom, right, top, (0.045, 0.052, 0.065, 0.88))
        DrawSocketView.draw_polyline(
            [(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)],
            (0.35, 0.42, 0.52, 0.95),
            width=1.0,
        )
        DrawSocketView.draw_label(title, left + 8, top - 15, color, size=10, align="LEFT")

        wrap_width = max(22, int((right - left - 20) / 7.0))
        wrapped = _wrap_text(text, width=wrap_width)
        y = top - 34
        max_lines = max(1, int((top - bottom - 44) / 16))
        for line in wrapped.splitlines()[:max_lines]:
            DrawSocketView.draw_label(line, left + 10, y, (0.78, 0.86, 0.96, 1.0), size=9, align="LEFT")
            y -= 16

    @staticmethod
    def draw_text_block(block, rect):
        DrawSidePanel.draw_text_panel(
            block["text"],
            rect,
            title=block["title"],
            color=block["color"],
        )

    @staticmethod
    def draw_block(block, rect):
        if block["kind"] == "curve":
            DrawSocketView.draw_block(block, rect)
        elif block["kind"] == "text":
            DrawSidePanel.draw_text_block(block, rect)

    @staticmethod
    def handler(*_args):
        editor = bpy.context.space_data
        if editor is None or editor.type != 'NODE_EDITOR':
            return

        edit_tree = getattr(editor, "edit_tree", None) or getattr(editor, "node_tree", None)
        if edit_tree is None:
            return

        for node in DrawSidePanel.iter_nodes(edit_tree):
            blocks = DrawSidePanel.blocks_for_node(node)
            if not blocks:
                continue

            for index, block in enumerate(blocks):
                rect = DrawSidePanel.region_rect(node, index, block)
                if rect is None:
                    continue

                try:
                    DrawSidePanel.draw_block(block, rect)
                except Exception as exc:
                    _warn_once(
                        "side_panel_handler",
                        f"OmniNode 侧栏绘制回调失败：{exc}",
                    )

    @staticmethod
    def ensure_handler():
        if DrawSidePanel.GLOBAL_OVERLAY_ID in _HANDLES:
            return
        _PAYLOADS[DrawSidePanel.GLOBAL_OVERLAY_ID] = {"tree_name": None}
        _HANDLES[DrawSidePanel.GLOBAL_OVERLAY_ID] = bpy.types.SpaceNodeEditor.draw_handler_add(
            DrawSidePanel.handler,
            (),
            'WINDOW',
            'POST_VIEW',
        )

    @staticmethod
    def clear_node(node):
        _tag_node_editors(node.id_data.name_full)

    @staticmethod
    def is_visible(node):
        return bool(getattr(node, "omni_view_preview", False))

    @staticmethod
    def draw_node(node):
        DrawSidePanel.ensure_handler()
        _tag_node_editors(node.id_data.name_full)

    @staticmethod
    def sync_node(node):
        if getattr(node, "omni_view_preview", False):
            DrawSidePanel.draw_node(node)
        else:
            DrawSidePanel.clear_node(node)


def clear_tree(tree):
    DrawDescription.clear_tree(tree)
    DrawBug.clear_tree(tree)


def register():
    DrawSidePanel.ensure_handler()


def unregister():
    overlay_ids = set(_HANDLES.keys()) | set(_PAYLOADS.keys())
    for overlay_id in list(overlay_ids):
        _clear_overlay(overlay_id)
