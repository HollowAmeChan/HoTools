import random

import bmesh
import bpy
from bpy.props import EnumProperty, FloatVectorProperty, IntProperty
from bpy.types import Operator

from .properties import get_scene_settings
from .utils import get_active_corner_color_attribute, linear_to_srgb
from ..i18n import tr


def apply_vertex_color_view(context, enable):
    window = context.window
    screen = context.screen
    if window is None or screen is None:
        raise RuntimeError(tr("当前上下文没有可用窗口"))

    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        for region in area.regions:
            if region.type != "WINDOW":
                continue

            override = {
                "window": window,
                "screen": screen,
                "area": area,
                "region": region,
            }
            with context.temp_override(**override):
                shading = context.space_data.shading
                context.scene.view_settings.view_transform = "Standard"
                if enable:
                    shading.color_type = "VERTEX"
                    shading.background_type = "VIEWPORT"
                    shading.light = "FLAT"
                else:
                    context.space_data.overlay.show_overlays = True
                    shading.color_type = "MATERIAL"
                    shading.background_type = "THEME"
                    shading.light = "STUDIO"
            return

    raise RuntimeError(tr("找不到 3D 视图区域"))


class HO_OT_temp_vertex_color_palette(Operator):
    bl_idname = "ho.temp_vertex_color_palette"
    bl_label = "管理缓存颜色"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties):
        return tr("管理缓存颜色")

    action: EnumProperty(
        items=[
            ("ADD", "Add", ""),
            ("REMOVE", "Remove", ""),
            ("CLEAR", "Clear", ""),
            ("SET_ACTIVE", "Set Active", ""),
        ],
        default="ADD",
    )  # type: ignore
    index: IntProperty(default=-1)  # type: ignore
    color: FloatVectorProperty(
        size=3,
        subtype="COLOR",
        default=(1.0, 0.0, 0.0),
        min=0.0,
        max=1.0,
    )  # type: ignore

    def execute(self, context):
        settings = get_scene_settings(context.scene)

        if self.action == "ADD":
            item = settings.temp_colors.add()
            item.color = settings.paint_color
        elif self.action == "REMOVE":
            if 0 <= self.index < len(settings.temp_colors):
                settings.temp_colors.remove(self.index)
        elif self.action == "CLEAR":
            settings.temp_colors.clear()
        elif self.action == "SET_ACTIVE":
            settings.paint_color = self.color

        return {"FINISHED"}


class HO_OT_enter_vertex_color_view(Operator):
    bl_idname = "ho.entervertexcolorview"
    bl_label = "进入顶点色预览"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties):
        return tr("进入顶点色预览")

    def execute(self, context):
        try:
            apply_vertex_color_view(context, True)
        except RuntimeError as exc:
            self.report({"WARNING"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class HO_OT_quit_vertex_color_view(Operator):
    bl_idname = "ho.quitvertexcolorview"
    bl_label = "退出顶点色预览"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties):
        return tr("退出顶点色预览")

    def execute(self, context):
        try:
            apply_vertex_color_view(context, False)
        except RuntimeError as exc:
            self.report({"WARNING"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class HO_OT_set_mesh_vertex_color(Operator):
    bl_idname = "ho.setmeshvertexcolor"
    bl_label = "写入顶点色"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties):
        return tr("写入顶点色")

    color: FloatVectorProperty(size=3, subtype="COLOR", min=0.0, max=1.0)  # type: ignore

    @classmethod
    def poll(cls, context):
        return (
            context.object is not None
            and context.object.type == "MESH"
            and context.mode == "EDIT_MESH"
        )

    def execute(self, context):
        obj = context.object
        if obj is None or obj.type != "MESH":
            self.report({"WARNING"}, tr("当前对象不是网格"))
            return {"CANCELLED"}

        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        active_color = get_active_corner_color_attribute(mesh)

        color_layer = bm.loops.layers.color.get(active_color.name)
        if color_layer is None:
            color_layer = bm.loops.layers.float_color.get(active_color.name)
        if color_layer is None:
            if active_color.data_type == "FLOAT_COLOR":
                color_layer = bm.loops.layers.float_color.new(active_color.name)
            else:
                color_layer = bm.loops.layers.color.new(active_color.name)

        selected_faces = [face for face in bm.faces if face.select]
        if not selected_faces:
            self.report({"WARNING"}, tr("当前没有选中任何面"))
            return {"CANCELLED"}

        color = (*linear_to_srgb(self.color[:3]), 1.0)
        for face in selected_faces:
            for loop in face.loops:
                loop[color_layer] = color

        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        return {"FINISHED"}


def draw_base_panel(context, layout):
    settings = get_scene_settings(context.scene)
    section = layout.column(align=True)

    row = section.row(align=True)
    op = row.operator(HO_OT_set_mesh_vertex_color.bl_idname, text="", icon="GREASEPENCIL")
    op.color = settings.paint_color
    op = row.operator(HO_OT_set_mesh_vertex_color.bl_idname, text="", icon="KEY_EMPTY1_FILLED")
    op.color = (1.0, 1.0, 1.0)
    op = row.operator(HO_OT_set_mesh_vertex_color.bl_idname, text="", icon="KEY_EMPTY1")
    row.prop(settings, "paint_color", icon_only=True)
    op.color = (0.0, 0.0, 0.0)
    op = row.operator(HO_OT_temp_vertex_color_palette.bl_idname, text="", icon="EVENT_R")
    op.action = "SET_ACTIVE"
    op.color = (
        random.random(),
        random.random(),
        random.random(),
    )
    op = row.operator(HO_OT_temp_vertex_color_palette.bl_idname, text="", icon="ADD")
    op.action = "ADD"

    if settings.temp_colors:
        section.separator()
        row = section.row(align=True)
        row.label(text=tr("缓存颜色"))
        op = row.operator(HO_OT_temp_vertex_color_palette.bl_idname, text="", icon="TRASH")
        op.action = "CLEAR"

        for index, item in enumerate(settings.temp_colors):
            row = section.row(align=True)
            op = row.operator(HO_OT_set_mesh_vertex_color.bl_idname, text="", icon="GREASEPENCIL")
            op.color = item.color
            row.prop(item, "color", icon_only=True)
            op = row.operator(HO_OT_temp_vertex_color_palette.bl_idname, text="", icon="TRASH")
            op.action = "REMOVE"
            op.index = index


CLASSES = (
    HO_OT_temp_vertex_color_palette,
    HO_OT_enter_vertex_color_view,
    HO_OT_quit_vertex_color_view,
    HO_OT_set_mesh_vertex_color,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
