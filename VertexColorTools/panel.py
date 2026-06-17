import bpy
import bmesh

from .ops_base import HO_OT_set_mesh_vertex_color, draw_base_panel
from .ops_templates import draw_template_panel
from .ops_utils import draw_utils_panel
from .properties import get_scene_settings
from .utils import get_active_corner_color_attribute


def _draw_rgba_column(layout, color):
    for channel_name, value in zip(("R", "G", "B", "A"), color):
        row = layout.row(align=True)
        row.label(text=channel_name, translate=False)
        row.label(text=f"{value:.4f}", translate=False)


def _draw_active_vertex_color_warning(layout):
    warn = layout.row()
    warn.alert = True
    warn.label(text="警告：此面板会实时读取编辑模式顶点色，受 Blender 内部问题影响容易崩溃，请不要常开。", icon="ERROR")


def _get_single_selected_vertex(bm):
    selected_vert = None
    for vert in bm.verts:
        if not vert.select:
            continue
        if selected_vert is not None:
            return False
        selected_vert = vert

    return selected_vert


def _get_active_bmesh_color_layer(bm, color_name):
    color_layer = bm.loops.layers.color.get(color_name)
    if color_layer is None:
        color_layer = bm.loops.layers.float_color.get(color_name)
    return color_layer


def _draw_active_vertex_color(layout, context):
    obj = context.active_object
    if obj is None or obj.type != "MESH" or obj.mode != "EDIT":
        return

    mesh = obj.data
    try:
        active_color = get_active_corner_color_attribute(mesh, create_if_missing=False)
    except RuntimeError:
        return
    if active_color is None:
        return

    try:
        bm = bmesh.from_edit_mesh(mesh)
    except RuntimeError:
        return

    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    color_layer = _get_active_bmesh_color_layer(bm, active_color.name)
    selected_vert = _get_single_selected_vertex(bm)

    box = layout.box()
    _draw_active_vertex_color_warning(box)
    if selected_vert is None:
        box.label(text="请选择一个顶点")
        return
    if selected_vert is False:
        box.label(text="只能选择一个顶点")
        return
    if color_layer is None:
        box.label(text="当前活动颜色层没有可读数据")
        return

    color_rows = []
    for loop in selected_vert.link_loops:
        rgba = tuple(loop[color_layer])
        if rgba not in color_rows:
            color_rows.append(rgba)

    if not color_rows:
        box.label(text="当前顶点没有可读颜色")
        return

    for index, rgba in enumerate(color_rows):
        col = box.column(align=True)
        if len(color_rows) > 1:
            col.label(text=f"Corner {index + 1}", translate=False)
        else:
            col.label(text="RGBA", translate=False)
        _draw_rgba_column(col, rgba)


def draw_in_DATA_PT_vertex_colors(self, context):
    obj = context.active_object
    if obj is None or obj.type != "MESH":
        return

    settings = get_scene_settings(context.scene)
    layout = self.layout
    layout.use_property_decorate = False

    row = layout.row(align=True)
    row_left = row.row(align=True)
    row_left.alignment = "LEFT"
    row_left.prop(settings, "show_base_tools", text="", icon="EVENT_H", toggle=True)
    row_left.prop(settings, "show_active_vertex_color", text="", icon="OUTLINER_DATA_MESH", toggle=True)
    row_left.prop(settings, "show_template_tools", text="", icon="OUTLINER_COLLECTION", toggle=True)
    row_left.prop(settings, "show_utils_tools", text="", icon="PROPERTIES", toggle=True)

    row_right = row.row(align=True)
    row_right.alignment = "RIGHT"
    row_right.prop(settings, "view_mode", text="", icon="OVERLAY", toggle=True)
    row_right.prop(
        context.scene,
        "hoVertexColorTools_control_color_attribute_listener",
        text="",
        icon="UV_SYNC_SELECT",
        toggle=True,
    )

    if settings.show_active_vertex_color:
        _draw_active_vertex_color(layout, context)
    if settings.show_base_tools:
        draw_base_panel(context, layout)
    if settings.show_template_tools:
        draw_template_panel(context, layout, HO_OT_set_mesh_vertex_color.bl_idname)
    if settings.show_utils_tools:
        draw_utils_panel(context, layout)


def register():
    try:
        bpy.types.DATA_PT_vertex_colors.remove(draw_in_DATA_PT_vertex_colors)
    except Exception:
        pass
    bpy.types.DATA_PT_vertex_colors.append(draw_in_DATA_PT_vertex_colors)


def unregister():
    try:
        bpy.types.DATA_PT_vertex_colors.remove(draw_in_DATA_PT_vertex_colors)
    except Exception:
        pass
