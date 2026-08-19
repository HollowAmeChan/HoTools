"""HoMainPie：编辑模式下的主工作饼菜单。"""

import bpy
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Menu, Operator

from .HoPieCore import (
    HoPie,
    draw_prop,
    ensure_layout,
    find_space,
)


class HO_OT_HoMainPieToggleOverlay(Operator):
    """切换三维视图的总叠加层。"""

    bl_idname = "ho.main_pie_toggle_overlay"
    bl_label = "叠加层"
    bl_description = "显示或隐藏三维视图叠加层"

    @classmethod
    def poll(cls, context):
        return find_space(context, "VIEW_3D") is not None

    def execute(self, context):
        space = find_space(context, "VIEW_3D")
        overlay = getattr(space, "overlay", None)
        if overlay is None:
            return {"CANCELLED"}
        overlay.show_overlays = not overlay.show_overlays
        return {"FINISHED"}


class HO_OT_HoMainPieSetColorMode(Operator):
    """设置视图光照的颜色来源。"""

    bl_idname = "ho.main_pie_set_color_mode"
    bl_label = "设置视图颜色"
    bl_options = {"REGISTER", "UNDO"}

    color_mode: EnumProperty(
        name="颜色模式",
        items=(
            ("MATERIAL", "材质", "使用材质颜色"),
            ("RANDOM", "随机", "使用随机颜色"),
        ),
        options={"HIDDEN"},
    )

    @classmethod
    def poll(cls, context):
        return find_space(context, "VIEW_3D") is not None

    def execute(self, context):
        space = find_space(context, "VIEW_3D")
        shading = getattr(space, "shading", None)
        if shading is None or not hasattr(shading, "color_type"):
            return {"CANCELLED"}

        # 切回材质颜色时关闭 HoTools 自己的顶点色预览，保持两个入口状态一致。
        if self.color_mode == "MATERIAL":
            settings = getattr(getattr(context, "scene", None), "ho_vertex_color_tools", None)
            if settings is not None and hasattr(settings, "view_mode") and settings.view_mode:
                settings.view_mode = False
        shading.color_type = self.color_mode
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


def _draw_view_options(layout, context):
    """集中绘制主饼左上角的视图选项和叠加层开关。"""
    layout = ensure_layout(layout, context)
    space = find_space(context, "VIEW_3D")
    overlay = getattr(space, "overlay", None)
    scene = getattr(context, "scene", None)

    row = layout.row()
    row.item().operator("view3d.view_persportho",text="开关正交",icon="VIEW_ORTHO")
    row.item().popover(panel="OBJECT_PT_display", text="视图显示", icon="VIEW3D")

    row = layout.row(align=True)
    draw_prop(row, overlay, "show_weight", "权重", icon="COLOR")
    draw_prop(row, overlay, "show_face_orientation", "朝向", icon="AXIS_FRONT")
    draw_prop(row, overlay, "show_wireframes", "线框", icon="SHADING_WIRE")
    draw_prop(row, overlay, "show_gizmo_object_translate", "轴", icon="GIZMO")

    row = layout.row(align=True)
    settings = getattr(scene, "ho_vertex_color_tools", None)
    draw_prop(row, settings, "view_mode", "顶点色", icon="COLOR")
    draw_prop(row, scene, "ho_checker_overlay_show", "Checker", icon="CHECKMARK")

    if scene is not None and hasattr(scene, "ho_checker_overlay_realtime_refresh"):
        checker_row = layout.row(align=True)
        checker_row.raw_layout.enabled = bool(getattr(scene, "ho_checker_overlay_show", False))
        # draw_prop(checker_row,scene,"ho_checker_overlay_realtime_refresh","实时刷新",icon="FILE_REFRESH")

    row = layout.row(align=True)
    row.item().operator(HO_OT_HoMainPieSetColorMode.bl_idname,text="材质",icon="MATERIAL",).color_mode = "MATERIAL"
    row.item().operator(HO_OT_HoMainPieSetColorMode.bl_idname,text="随机",icon="COLOR",).color_mode = "RANDOM"
    if overlay is not None:
        draw_prop(row, overlay, "show_text", "文本", icon="TEXT")
    uv_editor = getattr(space, "uv_editor", None)
    if uv_editor is not None:
        draw_prop(row, uv_editor, "show_stretch", "UV 拉伸", icon="UV")


class HO_MT_HoMainPieEdgeDisplay(Menu):
    """网格显示操作，直接读取当前三维视图叠加层属性。"""

    bl_idname = "HO_MT_HoMainPieEdgeDisplay"
    bl_label = "网格显示操作"

    def draw(self, context):
        layout = self.layout
        space = find_space(context, "VIEW_3D")
        overlay = getattr(space, "overlay", None)

        row = layout.row(align=True)
        draw_prop(row, overlay, "show_edge_crease", "折痕")
        draw_prop(row, overlay, "show_edge_sharp", "锐边")
        row = layout.row(align=True)
        draw_prop(row, overlay, "show_edge_bevel_weight", "倒角")
        draw_prop(row, overlay, "show_edge_seams", "缝合")

        layout.separator()
        row = layout.row(align=True)
        enable = row.operator(
            HO_OT_HoMainPieSetEdgeOverlays.bl_idname,
            text="全开",
            icon="CHECKMARK",
        )
        enable.enabled = True
        disable = row.operator(
            HO_OT_HoMainPieSetEdgeOverlays.bl_idname,
            text="全关",
            icon="X",
        )
        disable.enabled = False


class HO_MT_HoMainPieSelection(Menu):
    """点、线、面选择工具的轻量入口。"""

    bl_idname = "HO_MT_HoMainPieSelection"
    bl_label = "点线面工具合集"

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.operator("mesh.select_mode", text="点").type = "VERT"
        row.operator("mesh.select_mode", text="边").type = "EDGE"
        row.operator("mesh.select_mode", text="面").type = "FACE"
        layout.separator()
        layout.operator("mesh.select_all", text="全选").action = "SELECT"
        layout.operator("mesh.select_all", text="取消全选").action = "DESELECT"


class HO_MT_HoMainPieQuickModifiers(Menu):
    """快速网格修改器，调用 ModifierTools 的现有操作。"""

    bl_idname = "HO_MT_HoMainPieQuickModifiers"
    bl_label = "快速网格"

    _BUTTONS = (
        ("SUBSURF_SIMPLE", "纯细分"),
        ("SUBSURF", "细分"),
        ("SOLIDIFY", "实体化"),
        ("MIRROR", "镜像"),
        ("TRIANGULATE", "三角化"),
        ("BOOLEAN", "布尔"),
        ("SHRINKWRAP", "缩裹"),
        ("DATA_TRANSFER", "数据传递"),
    )

    def draw(self, context):
        layout = self.layout
        for start in (0, 4):
            row = layout.row(align=True)
            for modifier_type, label in self._BUTTONS[start:start + 4]:
                button = row.operator(
                    "ho.modifier_add_quick",
                    text=label,
                    icon="MODIFIER_ON",
                )
                button.modifier_type = modifier_type


class HO_MT_HoMainPieMesh(Menu):
    """PME 中的网格工具子饼。"""

    bl_idname = "HO_MT_HoMainPieMesh"
    bl_label = "网格工具"

    def draw(self, context):
        pie = HoPie(self.layout, context)
        pie.bottom.menu(
            HO_MT_HoMainPieEdgeDisplay.bl_idname,
            text="网格显示操作",
            icon="FUND",
        )
        pie.top.menu(
            HO_MT_HoMainPieSelection.bl_idname,
            text="点线面工具合集",
            icon="VIEW_PAN",
        )
        pie.top_left.menu(
            HO_MT_HoMainPieQuickModifiers.bl_idname,
            text="快速网格",
            icon="MODIFIER_ON",
        )
        pie.finish()


class HO_MT_HoMainPie(Menu):
    """HoTools 的编辑模式主工作饼。"""

    bl_idname = "HO_MT_HoMainPie"
    bl_label = "HoMainPie"

    def draw(self, context):
        pie = HoPie(self.layout, context)
        # 槽位顺序与 PME 一致，但写代码时直接使用方向名，不再手数分隔符。
        pie.left.pie(
            HO_MT_HoMainPieMesh.bl_idname,
            text="网格工具",
            icon="MESH_DATA",
        )
        pie.top.operator(
            HO_OT_HoMainPieToggleOverlay.bl_idname,
            text="叠加层",
            icon="OVERLAY",
        )
        pie.top_left.expand(_draw_view_options)
        pie.finish()


HO_MAIN_PIE_CLASSES = (
    HO_OT_HoMainPieToggleOverlay,
    HO_OT_HoMainPieSetColorMode,
    HO_OT_HoMainPieSetEdgeOverlays,
    HO_MT_HoMainPieEdgeDisplay,
    HO_MT_HoMainPieSelection,
    HO_MT_HoMainPieQuickModifiers,
    HO_MT_HoMainPieMesh,
    HO_MT_HoMainPie,
)


__all__ = ["HO_MAIN_PIE_CLASSES"]
