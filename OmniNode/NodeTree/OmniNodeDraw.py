import bpy
import blf
import textwrap


_HANDLES = {}
_PAYLOADS = {}


def _overlay_id(node):
    return f"omni_error::{node.id_data.name_full}::{node.name}"


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


def _get_text_location(node, text, scale, align='UP'):
    x, y = _absolute_location(node)
    gap = 10

    try:
        dx, dy = node.dimensions
    except (TypeError, ValueError):
        dx, dy = 1, 1

    if align == "RIGHT":
        x, y = int(x + dx + gap), int(y)
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


def callback_disable(overlay_id):
    handle = _HANDLES.pop(overlay_id, None)
    payload = _PAYLOADS.pop(overlay_id, None)
    if handle is not None:
        bpy.types.SpaceNodeEditor.draw_handler_remove(handle, 'WINDOW')
    if payload is not None:
        _tag_node_editors(payload["tree_name"])


def draw_text(node, text, color=(1.0, 0.35, 0.35, 1.0), scale=1.3, align="UP"):
    overlay_id = _overlay_id(node)
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


def sync_bug_text(node):
    if getattr(node, "is_bug", False) and getattr(node, "bug_text", ""):
        wrapped = "\n".join(textwrap.wrap(node.bug_text, width=36)) or node.bug_text
        draw_text(node, wrapped)
    else:
        callback_disable(_overlay_id(node))


def clear_tree(tree):
    prefix = f"omni_error::{tree.name_full}::"
    for overlay_id in list(_HANDLES.keys()):
        if overlay_id.startswith(prefix):
            callback_disable(overlay_id)


def register():
    return None


def unregister():
    for overlay_id in list(_HANDLES.keys()):
        callback_disable(overlay_id)
