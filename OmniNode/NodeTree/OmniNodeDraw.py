import bpy
import blf
import colorsys
import gpu
import math
import textwrap
import time
from gpu_extras.batch import batch_for_shader

from ...PropertyCurve import PropertyCurveDraw


_HANDLES = {}
_PAYLOADS = {}
_WARNED = set()
_RUNTIME_TIMING_TREES = {}
_COMPILE_FLOW_TREES = {}
_RIGHT_OVERLAY_GAP_X = 12


def _compile_flow_sequence_position(elapsed, cycle_seconds, node_count):
    node_count = max(int(node_count), 1)
    cycle_seconds = max(float(cycle_seconds), 0.25)
    units = float(node_count * 2)
    return (max(float(elapsed), 0.0) % cycle_seconds) / cycle_seconds * units


def _compile_flow_node_pulse(position, node_index, node_count, width=0.85):
    node_count = max(int(node_count), 1)
    total = float(node_count * 2)
    center = float(int(node_index) * 2)
    distance = abs(float(position) - center) % total
    distance = min(distance, total - distance)
    width = max(float(width), 0.001)
    if distance >= width:
        return 0.0
    return 0.5 + 0.5 * math.cos(math.pi * distance / width)


def _compile_flow_link_progress(position, target_index, node_count):
    node_count = max(int(node_count), 1)
    total = float(node_count * 2)
    start = (float(int(target_index) * 2) - 1.0) % total
    local = (float(position) - start) % total
    if local > 1.0:
        return None
    return local * local * (3.0 - 2.0 * local)


def _compile_flow_muted_pulse(progress, path_index, path_count):
    if progress is None or path_count <= 0:
        return 0.0
    center = (int(path_index) + 1.0) / (int(path_count) + 1.0)
    width = min(0.22, 0.72 / (int(path_count) + 1.0))
    distance = abs(float(progress) - center)
    if distance >= width:
        return 0.0
    return 0.5 + 0.5 * math.cos(math.pi * distance / width)


def _warn_once(key, message):
    if key in _WARNED:
        return
    _WARNED.add(key)
    print(message)


def _overlay_id(node, kind):
    return f"omni_{kind}::{node.id_data.name_full}::{node.name}"


def _tree_draw_key(tree):
    try:
        return int(tree.as_pointer())
    except Exception:
        return id(tree)


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
    def draw_preview(payload, rect, title=""):
        PropertyCurveDraw.draw_preview(DrawSocketView, payload, rect, title=title)

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
            if getattr(node, "omni_view_preview", False):
                yield node

    @staticmethod
    def blocks_for_node(node):
        blocks = []
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


class DrawRuntimeTiming:
    """Draw the latest sampled execution time above each node."""

    GLOBAL_OVERLAY_ID = "omni_runtime_timing::global"
    FAST_SECONDS = 0.001
    SLOW_SECONDS = 0.008
    FAST_COLOR = (0.32, 0.88, 0.45, 1.0)
    MEDIUM_COLOR = (1.0, 0.72, 0.18, 1.0)
    SLOW_COLOR = (1.0, 0.28, 0.22, 1.0)

    @staticmethod
    def format_seconds(seconds):
        seconds = max(float(seconds), 0.0)
        if seconds < 0.001:
            return f"{seconds * 1_000_000.0:.0f} us"
        if seconds < 0.1:
            return f"{seconds * 1000.0:.2f} ms"
        return f"{seconds * 1000.0:.1f} ms"

    @staticmethod
    def color(seconds):
        seconds = max(float(seconds), 0.0)
        if seconds <= DrawRuntimeTiming.FAST_SECONDS:
            return DrawRuntimeTiming.FAST_COLOR
        if seconds < DrawRuntimeTiming.SLOW_SECONDS:
            return DrawRuntimeTiming.MEDIUM_COLOR
        return DrawRuntimeTiming.SLOW_COLOR

    @staticmethod
    def draw_label(node, seconds):
        text = DrawRuntimeTiming.format_seconds(seconds)
        x, y = _absolute_location(node)
        width = _get_node_width(node)
        ui_scale = bpy.context.preferences.system.ui_scale
        x = (x + width * 0.5) * ui_scale
        y = (y + 12.0) * ui_scale

        font_id = 0
        blf.size(font_id, _get_text_height(0.9))
        text_width, _ = blf.dimensions(font_id, text)
        blf.position(font_id, x - text_width * 0.5, y, 0)
        blf.color(font_id, *DrawRuntimeTiming.color(seconds))
        blf.enable(font_id, blf.SHADOW)
        blf.shadow(font_id, 3, 0.0, 0.0, 0.0, 0.5)
        blf.shadow_offset(font_id, 1, -1)
        blf.draw(font_id, text)
        blf.disable(font_id, blf.SHADOW)

    @staticmethod
    def handler():
        editor = getattr(bpy.context, "space_data", None)
        if editor is None or editor.type != 'NODE_EDITOR':
            return
        tree = getattr(editor, "edit_tree", None) or getattr(editor, "node_tree", None)
        if tree is None or not getattr(tree, "show_runtime_timing", False):
            return
        payload = _RUNTIME_TIMING_TREES.get(_tree_draw_key(tree))
        if not payload:
            return

        for node_name, seconds in payload.items():
            node = tree.nodes.get(node_name)
            if node is None:
                continue
            try:
                DrawRuntimeTiming.draw_label(node, seconds)
            except Exception as exc:
                _warn_once(
                    "runtime_timing_handler",
                    f"OmniNode runtime timing draw failed: {exc}",
                )

    @staticmethod
    def ensure_handler():
        if DrawRuntimeTiming.GLOBAL_OVERLAY_ID in _HANDLES:
            return
        _PAYLOADS[DrawRuntimeTiming.GLOBAL_OVERLAY_ID] = {"tree_name": None}
        _HANDLES[DrawRuntimeTiming.GLOBAL_OVERLAY_ID] = bpy.types.SpaceNodeEditor.draw_handler_add(
            DrawRuntimeTiming.handler,
            (),
            'WINDOW',
            'POST_VIEW',
        )

    @staticmethod
    def update_tree(tree, node_timings):
        _RUNTIME_TIMING_TREES[_tree_draw_key(tree)] = {
            node_name: float(seconds)
            for node_name, seconds in node_timings.items()
        }
        DrawRuntimeTiming.ensure_handler()
        DrawRuntimeTiming.tag_tree(tree)

    @staticmethod
    def tag_tree(tree):
        _tag_node_editors(getattr(tree, "name_full", None))

    @staticmethod
    def clear_tree(tree):
        _RUNTIME_TIMING_TREES.pop(_tree_draw_key(tree), None)
        DrawRuntimeTiming.tag_tree(tree)


class DrawCompileFlow:
    """Animate the compiled node order and register-transfer links."""

    GLOBAL_OVERLAY_ID = "omni_compile_flow::global"
    TIMER_INTERVAL = 1.0 / 24.0
    REGULAR_COLOR = (0.18, 0.78, 1.0)
    MUTED_LINK_COLOR = (1.0, 0.55, 0.12)
    MUTED_NODE_COLOR = (1.0, 0.55, 0.12)
    _timer_running = False

    @staticmethod
    def _node_bounds(node):
        left, top = _absolute_location(node)
        try:
            width, height = map(float, node.dimensions)
        except (TypeError, ValueError):
            width, height = _get_node_width(node, 140.0), 80.0
        width = max(_get_node_width(node, width), 24.0)
        height = max(height, 24.0)
        return left, top - height, left + width, top

    @staticmethod
    def _socket_anchor(node, identifier, is_output):
        left, bottom, right, top = DrawCompileFlow._node_bounds(node)
        if getattr(node, "hide", False):
            return (right if is_output else left), (top + bottom) * 0.5

        sockets = getattr(node, "outputs" if is_output else "inputs", ())
        visible = [sock for sock in sockets if not getattr(sock, "hide", False)]
        index = 0
        for socket_index, sock in enumerate(visible):
            if getattr(sock, "identifier", None) == identifier:
                index = socket_index
                break
        available = max((top - bottom) - 38.0, 16.0)
        spacing = min(22.0, max(14.0, available / max(len(visible), 1)))
        y = top - 34.0 - index * spacing
        return (right if is_output else left), max(bottom + 8.0, y)

    @staticmethod
    def _node_side_anchor(node, is_output):
        left, bottom, right, top = DrawCompileFlow._node_bounds(node)
        return (right if is_output else left), (top + bottom) * 0.5

    @staticmethod
    def _bezier_points(start, end, count=32):
        count = max(int(count), 2)
        x0, y0 = start
        x3, y3 = end
        handle = max(abs(x3 - x0) * 0.5, 36.0)
        x1, y1 = x0 + handle, y0
        x2, y2 = x3 - handle, y3
        points = []
        for index in range(count):
            t = index / float(count - 1)
            u = 1.0 - t
            points.append((
                u * u * u * x0 + 3.0 * u * u * t * x1 + 3.0 * u * t * t * x2 + t * t * t * x3,
                u * u * u * y0 + 3.0 * u * u * t * y1 + 3.0 * u * t * t * y2 + t * t * t * y3,
            ))
        return points

    @staticmethod
    def _draw_colored_polyline(points, colors, width=2.0):
        if len(points) < 2 or len(points) != len(colors):
            return
        vertices = []
        vertex_colors = []
        for index in range(len(points) - 1):
            vertices.extend(((*points[index], 0.0), (*points[index + 1], 0.0)))
            vertex_colors.extend((colors[index], colors[index + 1]))
        try:
            gpu.state.blend_set('ALPHA')
            gpu.state.line_width_set(float(width))
            shader = gpu.shader.from_builtin('SMOOTH_COLOR')
            batch = batch_for_shader(shader, 'LINES', {"pos": vertices, "color": vertex_colors})
            shader.bind()
            batch.draw(shader)
        finally:
            gpu.state.line_width_set(1.0)
            gpu.state.blend_set('NONE')

    @staticmethod
    def _always_color(elapsed, index):
        hue = (float(elapsed) * 0.16 + int(index) * 0.13) % 1.0
        return colorsys.hsv_to_rgb(hue, 0.78, 1.0)

    @staticmethod
    def _draw_node(node, index, count, position, elapsed, always_run):
        pulse = _compile_flow_node_pulse(position, index, count)
        color = (
            DrawCompileFlow._always_color(elapsed, index)
            if always_run else DrawCompileFlow.REGULAR_COLOR
        )
        left, bottom, right, top = DrawCompileFlow._node_bounds(node)
        rect = [(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)]
        DrawSocketView.draw_polyline(rect, (*color, 0.16 + pulse * 0.24), width=6.0)
        DrawSocketView.draw_polyline(rect, (*color, 0.34 + pulse * 0.66), width=2.0)
        DrawSocketView.draw_label(
            f"{index + 1:02d}",
            left + 7.0,
            top + 8.0,
            (*color, 0.45 + pulse * 0.55),
            size=9,
            align="LEFT",
        )

    @staticmethod
    def _draw_link(tree, link, target_index, count, position, elapsed, always_nodes):
        from_name, from_socket, to_name, to_socket, reg, muted_path = link
        source = tree.nodes.get(from_name)
        target = tree.nodes.get(to_name)
        if source is None or target is None:
            return
        anchors = [DrawCompileFlow._socket_anchor(source, from_socket, True)]
        for muted_name in reversed(muted_path):
            muted_node = tree.nodes.get(muted_name)
            if muted_node is None:
                continue
            anchors.append(DrawCompileFlow._node_side_anchor(muted_node, False))
            anchors.append(DrawCompileFlow._node_side_anchor(muted_node, True))
        anchors.append(DrawCompileFlow._socket_anchor(target, to_socket, False))
        points = []
        for index in range(len(anchors) - 1):
            segment = DrawCompileFlow._bezier_points(anchors[index], anchors[index + 1], count=16)
            points.extend(segment if not points else segment[1:])
        if muted_path:
            color = DrawCompileFlow.MUTED_LINK_COLOR
        elif from_name in always_nodes:
            color = DrawCompileFlow._always_color(elapsed, target_index)
        else:
            color = DrawCompileFlow.REGULAR_COLOR
        DrawSocketView.draw_polyline(points, (*color, 0.12), width=2.0)

        progress = _compile_flow_link_progress(position, target_index, count)
        if progress is None:
            return None
        colors = []
        tail_length = 0.34
        for index in range(len(points)):
            t = index / float(len(points) - 1)
            distance = progress - t
            if distance < 0.0 or distance > tail_length:
                alpha = 0.04
            else:
                alpha = 0.18 + 0.82 * (1.0 - distance / tail_length) ** 2
            colors.append((*color, alpha))
        DrawCompileFlow._draw_colored_polyline(points, colors, width=4.0)
        head_index = min(int(progress * (len(points) - 1)), len(points) - 1)
        head_x, head_y = points[head_index]
        DrawSocketView.draw_label(
            f"r{reg}",
            head_x,
            head_y + 9.0,
            (*color, 0.92),
            size=8,
            align="CENTER",
        )
        return progress

    @staticmethod
    def _draw_muted_node(node, pulse):
        left, bottom, right, top = DrawCompileFlow._node_bounds(node)
        rect = [(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)]
        color = DrawCompileFlow.MUTED_NODE_COLOR
        DrawSocketView.draw_polyline(rect, (*color, 0.08 + pulse * 0.12), width=6.0)
        DrawSocketView.draw_polyline(rect, (*color, 0.22 + pulse * 0.34), width=2.0)

    @staticmethod
    def handler():
        editor = getattr(bpy.context, "space_data", None)
        if editor is None or editor.type != 'NODE_EDITOR':
            return
        tree = getattr(editor, "edit_tree", None) or getattr(editor, "node_tree", None)
        if tree is None or not getattr(tree, "show_compile_flow", False):
            return
        payload = _COMPILE_FLOW_TREES.get(_tree_draw_key(tree))
        if not payload:
            return

        flow = payload["flow"]
        nodes = flow.get("nodes", ())
        if not nodes:
            return
        elapsed = time.perf_counter() - payload["started_at"]
        cycle = max(float(getattr(tree, "compile_flow_cycle_duration", 4.0)), 1.0)
        position = _compile_flow_sequence_position(elapsed, cycle, len(nodes))
        node_indices = {record[0]: index for index, record in enumerate(nodes)}
        always_nodes = {record[0] for record in nodes if record[2]}
        muted_pulses = {}

        try:
            for link in flow.get("links", ()):
                target_index = node_indices.get(link[2])
                if target_index is not None:
                    progress = DrawCompileFlow._draw_link(
                        tree, link, target_index, len(nodes), position, elapsed, always_nodes
                    )
                    muted_path = tuple(reversed(link[5]))
                    for path_index, muted_name in enumerate(muted_path):
                        pulse = _compile_flow_muted_pulse(
                            progress, path_index, len(muted_path)
                        )
                        muted_pulses[muted_name] = max(
                            muted_pulses.get(muted_name, 0.0), pulse
                        )
            for muted_name in flow.get("muted_nodes", ()):
                muted_node = tree.nodes.get(muted_name)
                if muted_node is not None:
                    DrawCompileFlow._draw_muted_node(
                        muted_node,
                        muted_pulses.get(muted_name, 0.0),
                    )
            for index, (node_name, _node_type, always_run) in enumerate(nodes):
                node = tree.nodes.get(node_name)
                if node is not None:
                    DrawCompileFlow._draw_node(
                        node, index, len(nodes), position, elapsed, bool(always_run)
                    )
        except Exception as exc:
            _warn_once("compile_flow_handler", f"OmniNode compile flow draw failed: {exc}")

    @staticmethod
    def animation_timer():
        if not _COMPILE_FLOW_TREES:
            DrawCompileFlow._timer_running = False
            return None
        wm = getattr(bpy.context, "window_manager", None)
        if wm is not None:
            for window in wm.windows:
                for area in window.screen.areas:
                    if area.type != 'NODE_EDITOR':
                        continue
                    space = area.spaces.active
                    tree = getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)
                    if tree is not None and _tree_draw_key(tree) in _COMPILE_FLOW_TREES:
                        area.tag_redraw()
        return DrawCompileFlow.TIMER_INTERVAL

    @staticmethod
    def ensure_handler():
        if DrawCompileFlow.GLOBAL_OVERLAY_ID not in _HANDLES:
            _PAYLOADS[DrawCompileFlow.GLOBAL_OVERLAY_ID] = {"tree_name": None}
            _HANDLES[DrawCompileFlow.GLOBAL_OVERLAY_ID] = bpy.types.SpaceNodeEditor.draw_handler_add(
                DrawCompileFlow.handler,
                (),
                'WINDOW',
                'POST_VIEW',
            )
        if not DrawCompileFlow._timer_running:
            bpy.app.timers.register(DrawCompileFlow.animation_timer, first_interval=0.0)
            DrawCompileFlow._timer_running = True

    @staticmethod
    def stop_timer():
        try:
            if bpy.app.timers.is_registered(DrawCompileFlow.animation_timer):
                bpy.app.timers.unregister(DrawCompileFlow.animation_timer)
        except Exception:
            pass
        DrawCompileFlow._timer_running = False

    @staticmethod
    def update_tree(tree, flow):
        if not flow or not flow.get("nodes"):
            DrawCompileFlow.clear_tree(tree)
            return
        _COMPILE_FLOW_TREES[_tree_draw_key(tree)] = {
            "flow": flow,
            "started_at": time.perf_counter(),
        }
        DrawCompileFlow.ensure_handler()
        DrawCompileFlow.tag_tree(tree)

    @staticmethod
    def tag_tree(tree):
        _tag_node_editors(getattr(tree, "name_full", None))

    @staticmethod
    def clear_tree(tree):
        _COMPILE_FLOW_TREES.pop(_tree_draw_key(tree), None)
        DrawCompileFlow.tag_tree(tree)
        if not _COMPILE_FLOW_TREES:
            DrawCompileFlow.stop_timer()


def clear_tree(tree):
    DrawDescription.clear_tree(tree)
    DrawBug.clear_tree(tree)
    DrawRuntimeTiming.clear_tree(tree)
    DrawCompileFlow.clear_tree(tree)


def register():
    DrawSidePanel.ensure_handler()
    DrawRuntimeTiming.ensure_handler()


def unregister():
    _RUNTIME_TIMING_TREES.clear()
    _COMPILE_FLOW_TREES.clear()
    DrawCompileFlow.stop_timer()
    overlay_ids = set(_HANDLES.keys()) | set(_PAYLOADS.keys())
    for overlay_id in list(overlay_ids):
        _clear_overlay(overlay_id)
