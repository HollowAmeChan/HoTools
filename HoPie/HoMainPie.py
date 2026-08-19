"""HoMainPie：编辑模式下的主工作饼菜单。"""

from bpy.props import BoolProperty
from bpy.types import Menu, Operator

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


def _draw_view_options(layout: LayoutBuilder, context):
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


def _draw_edge_display(layout: LayoutBuilder, context):
    """直接绘制网格边缘显示选项。"""
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
    row.item().operator(
        HO_OT_HoMainPieSetEdgeOverlays.bl_idname,
        text="全开",
        icon="CHECKMARK",
        enabled=True,
        props={"enabled": True},
    )
    row.item().operator(
        HO_OT_HoMainPieSetEdgeOverlays.bl_idname,
        text="全关",
        icon="X",
        enabled=True,
        props={"enabled": False},
    )

def _draw_quick_modifiers(layout: LayoutBuilder, context):
    """直接绘制 ModifierTools 的快速修改器按钮。"""
    buttons = (
        ("SUBSURF_SIMPLE", "纯细分"),
        ("SUBSURF", "细分"),
        ("SOLIDIFY", "实体化"),
        ("MIRROR", "镜像"),
        ("TRIANGULATE", "三角化"),
        ("BOOLEAN", "布尔"),
        ("SHRINKWRAP", "缩裹"),
        ("DATA_TRANSFER", "数据传递"),
    )
    for start in (0, 4):
        row = layout.row(align=True)
        for modifier_type, label in buttons[start:start + 4]:
            row.item().operator(
                "ho.modifier_add_quick",
                text=label,
                icon="MODIFIER_ON",
                modifier_type=modifier_type,
            )


class HO_MT_HoMainPieMesh(Menu):
    """PME 中的网格工具子饼。"""

    bl_idname = "HO_MT_HoMainPieMesh"
    bl_label = "网格工具"

    def draw(self, context):
        pie = HoPie(self.layout, context)
        pie.top.expand(_draw_edge_display)
        pie.top_right.expand(_draw_quick_modifiers)
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
        draw_prop(pie.top, overlay, "show_overlays", "叠加层", icon="OVERLAY")
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
