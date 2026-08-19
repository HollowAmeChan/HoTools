"""HoMainPie：模式无关的主工作饼菜单。"""
import bpy
from bpy.props import BoolProperty
from bpy.types import Menu, Operator

from ..ModifierTools import _draw_quick_modifier_buttons

from .HoPieCore import (
    HoPie,
    LayoutBuilder,
    draw_prop,
    find_space,
)


_RANDOM_PREVIEW_RESTORE = "MATERIAL"


class HO_OT_HoMainPieToggleRandomPreview(Operator):
    """切换随机颜色预览，并记住切换前的颜色模式。"""

    bl_idname = "ho.main_pie_toggle_random_preview"
    bl_label = "随机预览"
    bl_description = "切换随机颜色预览，并恢复之前的颜色模式"
    bl_options = {"REGISTER", "UNDO"}

    @staticmethod
    def _remember(color_type):
        """记住开启随机预览前的颜色模式。"""
        global _RANDOM_PREVIEW_RESTORE
        if isinstance(color_type, str) and color_type != "RANDOM":
            _RANDOM_PREVIEW_RESTORE = color_type

    @staticmethod
    def _restore():
        """读取需要恢复的颜色模式。"""
        if (not isinstance(_RANDOM_PREVIEW_RESTORE, str)
                or _RANDOM_PREVIEW_RESTORE == "RANDOM"):
            return "MATERIAL"
        return _RANDOM_PREVIEW_RESTORE

    @staticmethod
    def _disable_vertex_color_preview(context):
        """回到材质颜色时关闭 HoTools 的顶点色预览。"""
        settings = getattr(getattr(context, "scene", None), "ho_vertex_color_tools", None)
        if settings is None or not hasattr(settings, "view_mode"):
            return
        try:
            settings.view_mode = False
        except (AttributeError, TypeError, ValueError, RuntimeError):
            pass

    @classmethod
    def poll(cls, context):
        space = find_space(context, "VIEW_3D")
        shading = getattr(space, "shading", None)
        return shading is not None and hasattr(shading, "color_type")

    def execute(self, context):
        space = find_space(context, "VIEW_3D")
        shading = getattr(space, "shading", None)
        if shading is None or not hasattr(shading, "color_type"):
            return {"CANCELLED"}

        current = getattr(shading, "color_type", None)
        if current == "RANDOM":
            color_type = self._restore()
            try:
                shading.color_type = color_type
            except (AttributeError, TypeError, ValueError, RuntimeError):
                return {"CANCELLED"}
            if color_type == "MATERIAL":
                self._disable_vertex_color_preview(context)
            return {"FINISHED"}

        try:
            shading.color_type = "RANDOM"
        except (AttributeError, TypeError, ValueError, RuntimeError):
            return {"CANCELLED"}
        self._remember(current)
        return {"FINISHED"}


class HO_OT_HoMainPieSetEdgeOverlays(Operator):
    """一次打开或关闭网格边缘辅助显示。"""

    bl_idname = "ho.main_pie_set_edge_overlays"
    bl_label = "网格边缘显示"
    bl_options = {"REGISTER", "UNDO"}

    enabled: BoolProperty(name="启用", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return find_space(context, "VIEW_3D") is not None

    def execute(self, context):
        space = find_space(context, "VIEW_3D")
        overlay = getattr(space, "overlay", None)
        if overlay is None:
            return {"CANCELLED"}
        for prop_name in (
            "show_edge_crease",
            "show_edge_sharp",
            "show_edge_bevel_weight",
            "show_edge_seams",
        ):
            if hasattr(overlay, prop_name):
                setattr(overlay, prop_name, self.enabled)
        return {"FINISHED"}


def _draw_view_options(layout: bpy.types.UILayout, context):
    """主饼左上角的视图选项和叠加层开关。"""
    space = find_space(context, "VIEW_3D")
    overlay = getattr(space, "overlay", None)
    scene = getattr(context, "scene", None)

    row = layout.row()
    row.item().operator("view3d.view_persportho",text="开关正交",icon="VIEW_ORTHO")
    row.item().popover(panel="OBJECT_PT_display", text="视图显示", icon="VIEW3D")

    row = layout.row(align=True)
    draw_prop(row, overlay, "show_weight", "权重", icon="STRIP_COLOR_01")
    draw_prop(row, overlay, "show_face_orientation", "朝向", icon="STRIP_COLOR_05")
    draw_prop(row, overlay, "show_wireframes", "线框", icon="STRIP_COLOR_09")
    draw_prop(row, overlay, "show_gizmo_object_translate", "轴", icon="STRIP_COLOR_03")

    row = layout.row(align=True)
    settings = getattr(scene, "ho_vertex_color_tools", None)
    draw_prop(row, settings, "view_mode", "顶点色", icon="COLORSET_06_VEC")
    draw_prop(row, scene, "ho_checker_overlay_show", "棋盘格", icon="TEXTURE_DATA")

    if scene is not None and hasattr(scene, "ho_checker_overlay_realtime_refresh"):
        checker_row = layout.row(align=True)
        checker_row.raw_layout.enabled = bool(getattr(scene, "ho_checker_overlay_show", False))
        # draw_prop(checker_row,scene,"ho_checker_overlay_realtime_refresh","实时刷新",icon="FILE_REFRESH")

    row = layout.row(align=True)
    shading = getattr(space, "shading", None)
    random_active = getattr(shading, "color_type", None) == "RANDOM"
    row.item().operator(HO_OT_HoMainPieToggleRandomPreview.bl_idname,
        text="随机预览",icon="COLORSET_05_VEC",depress=random_active,)
    if overlay is not None:
        draw_prop(row, overlay, "show_text", "文本", icon="COLORSET_10_VEC")
    draw_prop(row, getattr(space, "uv_editor", None), "show_stretch", "UV 拉伸", icon="COLORSET_04_VEC")


def _draw_quick_edge_tools(layout: LayoutBuilder, context):
    """绘制快速清除/标记缝合边、锐边和折痕，以及 UV 同步开关。"""
    col = layout.column(align=True)
    col.scale_y = 2
    col.scale_x = 2

    buttons = (
        ("mesh.mark_seam", "COLLECTION_COLOR_01", {"clear": True}),
        ("mesh.mark_sharp", "COLLECTION_COLOR_05", {"clear": True}),
        ("transform.edge_crease", "COLLECTION_COLOR_07",
         {"value": -1.0, "release_confirm": True}),
        ("mesh.mark_seam", "STRIP_COLOR_01", {"clear": False}),
        ("mesh.mark_sharp", "STRIP_COLOR_05", {"clear": False}),
        ("transform.edge_crease", "STRIP_COLOR_07",
         {"value": 1.0, "release_confirm": True}),
    )
    for operator_id, icon, properties in buttons:
        col.operator(operator_id, text="", icon=icon, props=properties)

    tool_settings = getattr(getattr(context, "scene", None), "tool_settings", None)
    if tool_settings is not None and hasattr(tool_settings, "use_uv_select_sync"):
        col.separator()
        col.prop(
            tool_settings,
            "use_uv_select_sync",
            text="",
            icon="UV_SYNC_SELECT",
        )


def _draw_mesh_selection_tools(layout: LayoutBuilder, context):
    """绘制常用的网格关联选择操作。"""
    col = layout.column(align=True)
    col.scale_x = 1.25
    col.scale_y = 1.35

    col.operator("mesh.faces_select_linked_flat",
        text="相邻平展",icon="VIEW_PERSPECTIVE",props={"sharpness": 0.2617993950843811},)
    col.operator("mesh.loop_to_region",
        text="循环线内",icon="VIEW_ORTHO",)
    col.operator("mesh.region_to_loop",
        text="边界循环",icon="SELECT_SET",)

    row = col.row(align=True)
    row.operator("mesh.select_linked",
        text="关联缝合",icon="STRIP_COLOR_01",props={"delimit": {"SEAM"}},)
    row.operator("mesh.select_linked",
        text="关联锐边",icon="STRIP_COLOR_05",props={"delimit": {"SHARP"}},)


def _draw_mesh_left_tools(layout: LayoutBuilder, context):
    """把选择列放在快速边属性列左侧，保持主饼原来的空间关系。"""
    row = layout.row(align=True)
    _draw_mesh_selection_tools(row.column(align=True), context)
    _draw_quick_edge_tools(row.column(align=True), context)


def _draw_edge_display(layout: bpy.types.UILayout, context):
    """绘制线属性显示选项。"""
    space = find_space(context, "VIEW_3D")
    overlay = getattr(space, "overlay", None)

    grid = layout.grid_flow(row_major=True,columns=2, even_columns=True, even_rows=True, align=True)
    draw_prop(grid, overlay, "show_edge_crease", "折痕",icon="STRIP_COLOR_07")
    draw_prop(grid, overlay, "show_edge_sharp", "锐边",icon="STRIP_COLOR_05")
    draw_prop(grid, overlay, "show_edge_bevel_weight", "倒角",icon="LAYERGROUP_COLOR_05")
    draw_prop(grid, overlay, "show_edge_seams", "缝合",icon="STRIP_COLOR_01")

    grid.operator(HO_OT_HoMainPieSetEdgeOverlays.bl_idname,text="",icon="CHECKMARK").enabled = True
    grid.operator(HO_OT_HoMainPieSetEdgeOverlays.bl_idname,text="",icon="X").enabled = False


class HO_MT_HoMainPieMesh(Menu):
    """PME 中的网格工具子饼。"""

    bl_idname = "HO_MT_HoMainPieMesh"
    bl_label = "网格工具"

    def draw(self, context):
        pie = HoPie(self.layout, context)
        pie.left.expand(_draw_mesh_left_tools)
        pie.top.expand(_draw_edge_display,
            height=1.5)
        # 快速修改器函数内部使用固定四列网格，普通面板和饼菜单展开保持一致。
        pie.top_right.expand(_draw_quick_modifier_buttons)
        pie.finish()


class HO_MT_HoMainPie(Menu):
    """HoTools 的编辑模式主工作饼。"""

    bl_idname = "HO_MT_HoMainPie"
    bl_label = "HoMainPie"

    def draw(self, context):
        pie = HoPie(self.layout, context)
        pie.left.pie(HO_MT_HoMainPieMesh.bl_idname,
            text="网格工具",icon="MESH_DATA",)

        space = find_space(context, "VIEW_3D")
        overlay = getattr(space, "overlay", None)
        if overlay is not None:
            pie.top.expression(
                "C.space_data.overlay.show_overlays = not C.space_data.overlay.show_overlays",
                text="叠加层",icon="OVERLAY",depress=bool(getattr(overlay, "show_overlays", False)),)

        pie.top_left.expand(_draw_view_options,
            width=1.5,height=1.5,height_offset=5.0,)
        pie.finish()


HO_MAIN_PIE_CLASSES = (
    HO_OT_HoMainPieToggleRandomPreview,
    HO_OT_HoMainPieSetEdgeOverlays,
    HO_MT_HoMainPieMesh,
    HO_MT_HoMainPie,
)


__all__ = ["HO_MAIN_PIE_CLASSES"]
