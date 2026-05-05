import bpy
from bpy.props import EnumProperty, IntProperty
from bpy.types import Operator

from .properties import get_scene_settings


DEFAULT_COLOR_GROUPS = {
    1: [
        (1, 0, 0),
        (0, 1, 0),
        (0, 0, 1),
        (1, 1, 0),
        (1, 0, 1),
        (0, 1, 1),
        (1, 0.5, 0),
        (0, 1, 0.5),
        (0.5, 0, 1),
        (0.25, 0.75, 0.5),
        (0.5, 0.25, 0.75),
        (0.75, 0.5, 0.25),
    ],
    2: [
        (0.051269, 0.025187, 0.025187),
        (0.21586, 0.095307, 0.095307),
        (1.0, 0.417885, 0.417885),
        (1.0, 0.672443, 0.376262),
        (0.98225, 1.0, 0.467784),
        (0.590618, 1.0, 0.520996),
        (0.327777, 0.921581, 1.0),
        (0.351532, 0.552011, 1.0),
        (0.508881, 0.445201, 1.0),
        (1.0, 0.564711, 1.0),
        (1.0, 0.76815, 1.0),
        (1.0, 0.879622, 1.0),
    ],
    3: [
        (0, 0.005182, 0.008568),
        (0.0, 0.014444, 0.027321),
        (0.0, 0.049707, 0.107023),
        (0.025187, 0.064803, 0.177888),
        (0.254152, 0.08022, 0.274677),
        (0.502886, 0.08022, 0.278894),
        (1.0, 0.124771, 0.119538),
        (1.0, 0.23455, 0.030714),
        (1.0, 0.381326, 0.0),
        (1.0, 0.651405, 0.215861),
        (1.0, 0.814846, 0.527115),
        (1.0, 0.90466, 0.745404),
    ],
}


def get_default_color_group(group_index):
    return DEFAULT_COLOR_GROUPS.get(group_index, DEFAULT_COLOR_GROUPS[1])


def replace_color_collection(collection, colors):
    collection.clear()
    for color in colors:
        item = collection.add()
        item.color = color


class HO_OT_default_vertex_color_palette(Operator):
    bl_idname = "ho.default_vertex_color_palette"
    bl_label = "管理预设颜色"
    bl_options = {"REGISTER", "UNDO"}

    action: EnumProperty(
        items=[
            ("LOAD_GROUP", "Load Group", ""),
            ("RESET_ITEM", "Reset Item", ""),
            ("CLEAR", "Clear", ""),
        ],
        default="LOAD_GROUP",
    )  # type: ignore
    group_index: IntProperty(default=1, min=1, max=3)  # type: ignore
    index: IntProperty(default=-1)  # type: ignore

    def execute(self, context):
        settings = get_scene_settings(context.scene)

        if self.action == "CLEAR":
            settings.default_group_index = 0
            settings.default_colors.clear()
            return {"FINISHED"}

        if self.action == "LOAD_GROUP":
            settings.default_group_index = self.group_index
            replace_color_collection(
                settings.default_colors,
                get_default_color_group(self.group_index),
            )
            return {"FINISHED"}

        if self.action == "RESET_ITEM":
            if not (0 <= self.index < len(settings.default_colors)):
                return {"CANCELLED"}
            group_index = settings.default_group_index or 1
            group = get_default_color_group(group_index)
            settings.default_colors[self.index].color = group[self.index % len(group)]

        return {"FINISHED"}


def draw_template_panel(context, layout, set_color_operator_idname):
    settings = get_scene_settings(context.scene)
    section = layout.column(align=True)

    row = section.row(align=True)
    row.alignment = "LEFT"
    row.label(text="预设组")
    row.alignment = "RIGHT"
    op = row.operator(HO_OT_default_vertex_color_palette.bl_idname, text="", icon="EVENT_A")
    op.action = "LOAD_GROUP"
    op.group_index = 1
    op = row.operator(HO_OT_default_vertex_color_palette.bl_idname, text="", icon="EVENT_B")
    op.action = "LOAD_GROUP"
    op.group_index = 2
    op = row.operator(HO_OT_default_vertex_color_palette.bl_idname, text="", icon="EVENT_C")
    op.action = "LOAD_GROUP"
    op.group_index = 3
    op = row.operator(HO_OT_default_vertex_color_palette.bl_idname, text="", icon="TRASH")
    op.action = "CLEAR"

    if settings.default_colors:
        for index, item in enumerate(settings.default_colors):
            row = section.row(align=True)
            op = row.operator(set_color_operator_idname, text="", icon="GREASEPENCIL")
            op.color = item.color
            row.prop(item, "color", icon_only=True)
            op = row.operator(HO_OT_default_vertex_color_palette.bl_idname, text="", icon="FILE_REFRESH")
            op.action = "RESET_ITEM"
            op.index = index


CLASSES = (HO_OT_default_vertex_color_palette,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
