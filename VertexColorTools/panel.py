import bpy

from .ops_base import HO_OT_set_mesh_vertex_color, draw_base_panel
from .ops_templates import draw_template_panel
from .ops_utils import draw_utils_panel
from .properties import get_scene_settings


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
