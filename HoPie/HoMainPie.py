"""HoMainPie：模式无关的主工作饼菜单。"""
import bpy
from bpy.types import Menu, Operator

try:
    from ..ModifierTools import _draw_quick_modifier_buttons
except ImportError:
    try:
        from ModifierTools import _draw_quick_modifier_buttons
    except ImportError:
        # Standalone HoPie test loaders do not have the parent HoTools package.
        def _draw_quick_modifier_buttons(*args, **kwargs):
            return None

from ._Core import (
    HoPie,
    LayoutBuilder,
    draw_prop,
    find_space,
)

from ..MeshTools.parallel_manifold_subdivide import OP_ParallelManifoldSubdivide


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


class HO_OT_HoMainPieSeparateLoose(Operator):
    """把当前网格物体按松散块拆成多个物体。"""

    bl_idname = "ho.main_pie_separate_loose"
    bl_label = "分离松散块"
    bl_description = "将当前网格物体的互不连接部分分离为独立物体"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """只允许在物体模式下处理活动网格物体。"""
        obj = getattr(context, "active_object", None)
        return (
            getattr(context, "mode", None) == "OBJECT"
            and getattr(obj, "type", None) == "MESH"
        )

    def execute(self, context):
        """临时进入编辑模式调用 Blender 的松散块分离操作。"""
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            result = bpy.ops.mesh.separate(type="LOOSE")
            bpy.ops.object.mode_set(mode="OBJECT")
        except (RuntimeError, TypeError, ValueError) as error:
            if getattr(context, "mode", None) == "EDIT_MESH":
                try:
                    bpy.ops.object.mode_set(mode="OBJECT")
                except RuntimeError:
                    pass
            self.report({"WARNING"}, f"分离松散块失败：{error}")
            return {"CANCELLED"}
        return result


class HO_OT_HoMainPieSetEdgeCrease(Operator):
    """Directly assign the crease value of the selected mesh edges."""

    bl_idname = "ho.main_pie_set_edge_crease"
    bl_label = "Set Edge Crease"
    bl_options = {"REGISTER", "UNDO"}

    value: bpy.props.FloatProperty(default=0.0, min=0.0, max=1.0) # type: ignore

    @classmethod
    def poll(cls, context):
        return getattr(context, "mode", None) == "EDIT_MESH" and getattr(
            getattr(context, "edit_object", None), "type", None
        ) == "MESH"

    def execute(self, context):
        obj = getattr(context, "edit_object", None)
        if getattr(obj, "type", None) != "MESH":
            return {"CANCELLED"}

        try:
            import bmesh

            bm = bmesh.from_edit_mesh(obj.data)
            crease_layer = bm.edges.layers.float.get("crease_edge")
            if crease_layer is None:
                crease_layer = bm.edges.layers.float.new("crease_edge")
            for edge in bm.edges:
                if edge.select:
                    edge[crease_layer] = self.value
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return {"CANCELLED"}
        return {"FINISHED"}


class HO_OT_HoMainPieSelectHalf(Operator):
    """Select the vertices on one side of the mesh's local X axis."""

    bl_idname = "ho.vertexgrouptools_select_oneside"
    bl_label = "选择一半"
    bl_description = "编辑模式下，选择物体局部 X 轴一侧的顶点"
    bl_options = {"REGISTER", "UNDO"}

    reverse: bpy.props.BoolProperty(
        default=False,
        name="选择左半",
    ) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "active_object", None)
        return getattr(obj, "type", None) == "MESH" and obj.mode == "EDIT"

    def execute(self, context):
        import bmesh

        obj = context.active_object
        bpy.ops.mesh.select_mode(
            use_extend=False,
            use_expand=False,
            type="VERT",
        )

        mesh = bmesh.from_edit_mesh(obj.data)
        mesh.verts.ensure_lookup_table()
        for vert in mesh.verts:
            vert.select_set(False)

        if self.reverse:
            for vert in mesh.verts:
                if vert.co.x < -0.0001:
                    vert.select_set(True)
        else:
            for vert in mesh.verts:
                if vert.co.x > 0.0001:
                    vert.select_set(True)

        mesh.select_flush_mode()
        bmesh.update_edit_mesh(obj.data)
        obj.update_from_editmode()
        if _object_has_local_rotation(obj):
            self.report(
                {"WARNING"},
                "当前物体有旋转，已选择本地 X 轴一侧",
            )
        return {"FINISHED"}


class HO_OT_HoMainPieSelectMirror(Operator):
    """Replace the selection with its mirror, or extend it while Shift is held."""

    bl_idname = "ho.vertexgrouptools_select_mirror"
    bl_label = "选择镜像"
    bl_description = "编辑模式下选择镜像；按住 Shift 点击时加选镜像"
    bl_options = {"REGISTER", "UNDO"}

    extend: bpy.props.BoolProperty(
        name="加选",
        default=False,
    ) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "active_object", None)
        return getattr(obj, "type", None) == "MESH" and obj.mode == "EDIT"

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        bpy.ops.mesh.select_mirror("EXEC_DEFAULT", extend=self.extend)
        if _object_has_local_rotation(context.active_object):
            self.report(
                {"WARNING"},
                "当前物体有旋转，已按本地 X 轴镜像选择",
            )
        return {"FINISHED"}


def _object_has_local_rotation(obj, tolerance=1e-6):
    """Return whether the object's local rotation transform is non-identity."""
    if obj is None:
        return False

    rotation_mode = getattr(obj, "rotation_mode", "XYZ")
    if rotation_mode == "QUATERNION":
        rotation = getattr(obj, "rotation_quaternion", None)
        if rotation is None:
            return False
        return (
            abs(abs(float(rotation[0])) - 1.0) > tolerance
            or any(abs(float(value)) > tolerance for value in rotation[1:])
        )
    if rotation_mode == "AXIS_ANGLE":
        rotation = getattr(obj, "rotation_axis_angle", None)
        return rotation is not None and abs(float(rotation[0])) > tolerance

    rotation = getattr(obj, "rotation_euler", None)
    return rotation is not None and any(
        abs(float(value)) > tolerance for value in rotation
    )


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


def _draw_main_top_right(layout: LayoutBuilder, context):
    """绘制主饼右上角的界面和时间轴快捷项。"""
    space = find_space(context, "VIEW_3D")
    screen = getattr(context, "screen", None)
    preferences = getattr(context, "preferences", None)
    view_preferences = getattr(preferences, "view", None)
    scene = getattr(context, "scene", None)
    render = getattr(scene, "render", None)

    # 第一行：界面显示开关。
    row = layout.row(align=True)
    draw_prop(row, view_preferences, "use_translate_interface", "中/英",icon="BLENDER")
    if (space is not None and screen is not None
            and hasattr(space, "show_region_header")
            and hasattr(screen, "show_statusbar")):
        row.expression(
            "space.show_region_header = not space.show_region_header; "
            "screen.show_statusbar = not screen.show_statusbar",
            text="标题/状态",
            depress=lambda current: bool(
                getattr(getattr(current, "space_data", None),
                        "show_region_header", False)
            ) and bool(
                getattr(getattr(current, "screen", None),
                        "show_statusbar", False)
            ),
        )

    # 第二行：播放控制和场景帧率。
    row = layout.row(align=True)
    draw_prop(row, render, "fps", "帧率", icon="TIME")
    row = layout.row(align=True)
    row.scale_y = 2
    row.scale_x = 4
    is_playing = bool(getattr(screen, "is_animation_playing", False))
    row.operator("screen.animation_play",
        text="",icon="PAUSE" if is_playing else "PLAY",depress=is_playing,)
    row.operator("screen.frame_jump",
        text="",icon="REW",props={"end": False},)


def _draw_quick_edge_tools(layout: LayoutBuilder, context):
    """绘制快速清除/标记缝合边、锐边和折痕，以及 UV 同步开关。"""
    col = layout.column(align=True)
    col.scale_y = 2
    col.scale_x = 2

    buttons = (
        ("mesh.mark_seam", "COLLECTION_COLOR_01", {"clear": True}),
        ("mesh.mark_sharp", "COLLECTION_COLOR_05", {"clear": True}),
    )
    for operator_id, icon, properties in buttons:
        col.operator(operator_id, text="", icon=icon, props=properties)

    col.operator(
        HO_OT_HoMainPieSetEdgeCrease.bl_idname,
        text="",
        icon="COLLECTION_COLOR_07",
        props={"value": 0.0},
    )

    for operator_id, icon, properties in (
        ("mesh.mark_seam", "STRIP_COLOR_01", {"clear": False}),
        ("mesh.mark_sharp", "STRIP_COLOR_05", {"clear": False}),
    ):
        col.operator(operator_id, text="", icon=icon, props=properties)

    col.operator(
        HO_OT_HoMainPieSetEdgeCrease.bl_idname,
        text="",
        icon="STRIP_COLOR_07",
        props={"value": 1.0},
    )

    tool_settings = getattr(getattr(context, "scene", None), "tool_settings", None)
    if tool_settings is not None and hasattr(tool_settings, "use_uv_select_sync"):
        col.separator()
        col.prop(tool_settings,"use_uv_select_sync",text="",icon="UV_SYNC_SELECT",)
        col.operator("uv.pin",text="",icon="PINNED",props={"clear": False},)
        col.operator("uv.pin",text="",icon="UNPINNED",props={"clear": True},)


def _draw_mesh_selection_tools(layout: LayoutBuilder, context):
    """绘制常用的网格关联选择操作。"""
    col = layout.column(align=True)
    col.scale_x = 1.25
    col.scale_y = 1.25

    row = col.row(align=True)
    row.scale_y = 2
    row.operator("mesh.region_to_loop",
        text="边界",icon="SELECT_SET",)
    row.operator("mesh.loop_to_region",
        text="边界内",icon="VIEW_ORTHO",)
    row.operator("mesh.select_linked",
        text="拓补关联",icon="UV_FACESEL",props={"delimit": {"NORMAL"}},)

    row = col.row(align=True)
    row.operator("mesh.select_linked",
        text="选择UV岛",icon="STRIP_COLOR_01",props={"delimit": {"SEAM"}},)
    row.operator("mesh.select_linked",
        text="选择光滑组",icon="STRIP_COLOR_05",props={"delimit": {"SHARP"}},)

    row = col.row(align=True)
    row.operator("mesh.edges_select_sharp",
        text="锐利边缘",icon="STRIP_COLOR_05",)
    row.operator("mesh.select_nth",
        text="间隔性弃选",icon="SELECT_SUBTRACT",props={"skip": 1, "nth": 1, "offset": 0},)

    row = col.row(align=True)
    row.operator("mesh.select_face_by_sides",
        text="选择Ngon",icon="FACESEL",props={"number": 4, "type": "GREATER"},)
    row.operator("mesh.select_by_pole_count",
        text="选择极点",icon="VERTEXSEL",props={"pole_count": 4, "type": "GREATER"},)

    row = col.row(align=True)
    row.operator("mesh.faces_select_linked_flat",
        text="相邻平展",icon="VIEW_PERSPECTIVE",props={"sharpness": 0.25},)
    row.operator("ho.lselect", 
        text="L选", icon="FILE_VOLUME")

    row = col.row(align=True)
    row.scale_y = 2
    row.operator("mesh.loop_multi_select",
        text="选择循环",icon="FILE_VOLUME",props={"ring": False},)
    row.operator("mesh.loop_multi_select",
        text="选择并排",icon="ALIGN_JUSTIFY",props={"ring": True},)

    row = col.row(align=True)
    row.scale_y = 2
    row.operator("ho.vertexgrouptools_select_oneside",
        text="左半",props={"reverse": True},icon="TRIA_LEFT",)
    row.operator("ho.vertexgrouptools_select_oneside",
        text="右半",props={"reverse": False},icon="TRIA_RIGHT",)
    row.operator("ho.vertexgrouptools_select_mirror",
        text="选择镜像",icon="ARROW_LEFTRIGHT",)


def _draw_mesh_left_tools(layout: LayoutBuilder, context):
    """把选择列放在快速边属性列左侧，保持主饼原来的空间关系。"""
    row = layout.row(align=True)
    _draw_mesh_selection_tools(row.column(align=True), context)
    _draw_quick_edge_tools(row.column(align=True), context)


def _draw_edge_flow_tools(layout: LayoutBuilder, context):
    """绘制 Mesh 子饼正右侧的 EdgeFlow 工具区。"""
    col = layout.column(align=True)
    col.scale_y = 1.35
    col.operator("ho.set_edge_flow", text="loop设流",icon="SPHERECURVE")
    col.operator("ho.parallel_manifold_subdivide", text="并排流形细分", icon="MOD_SUBSURF")
    col.operator("ho.slide_edge_loop_cut", text="滑边环切", icon="EDGESEL")
    row = col.row(align=True)
    row.operator("ho.set_edge_curve", text="并排设流",icon="MOD_WAVE")
    row.operator("ho.set_edge_linear", text="并排设直",icon="FILE_VOLUME")
    row = col.row(align=True)
    row.operator("ho.mesh_flatten", text="压平", icon="NOCURVE")
    row.operator("ho.mesh_relax", text="保边松弛", icon="MOD_SMOOTH")
    row = col.row(align=True)
    row.operator("ho.mesh_circle_even", text="均匀圆化", icon="MESH_CIRCLE")


def _draw_edge_display(layout: LayoutBuilder, context):
    """绘制线属性显示选项。"""
    space = find_space(context, "VIEW_3D")
    overlay = getattr(space, "overlay", None)

    grid = layout.grid_flow(row_major=True,columns=2, even_columns=True, even_rows=True, align=True)
    draw_prop(grid, overlay, "show_edge_crease", "折痕",icon="STRIP_COLOR_07")
    draw_prop(grid, overlay, "show_edge_sharp", "锐边",icon="STRIP_COLOR_05")
    draw_prop(grid, overlay, "show_edge_bevel_weight", "倒角",icon="LAYERGROUP_COLOR_05")
    draw_prop(grid, overlay, "show_edge_seams", "缝合",icon="STRIP_COLOR_01")

    if overlay is not None:
        grid_builder = LayoutBuilder(grid, context)
        grid_builder.expression(
            "o=C.space_data.overlay; "
            "o.show_edge_crease=True; "
            "o.show_edge_sharp=True; "
            "o.show_edge_bevel_weight=True; "
            "o.show_edge_seams=True",
            text="", icon="CHECKMARK",
        )
        grid_builder.expression(
            "o=C.space_data.overlay; "
            "o.show_edge_crease=False; "
            "o.show_edge_sharp=False; "
            "o.show_edge_bevel_weight=False; "
            "o.show_edge_seams=False",
            text="", icon="X",
        )


def _draw_object_export_panel(layout: LayoutBuilder, context):
    """绘制物体子饼正右侧的导出面板。"""
    # 导出操作需要文件路径，保持 Blender 文件选择器的默认调用方式。
    layout.operator_context = "INVOKE_DEFAULT"
    layout.enabled = (
        getattr(context, "mode", None) == "OBJECT"
        and getattr(context, "active_object", None) is not None
    )

    col = layout.column(align=True)
    col.scale_x = 1.25
    col.scale_y = 1.5

    row = col.row(align=True)
    row.operator("export_scene.fbx",
        text="FBX导出",icon="EXPORT",)
    row.operator("ho.final_fbx_export",
        text="HoFBX导出",icon="EXPORT",)

    row = col.row(align=True)
    row.operator("wm.obj_export",
        text="OBJ导出",icon="EXPORT",)
    row.operator("wm.stl_export",
        text="STL导出",icon="EXPORT",)


def _draw_object_quick_panel(layout: LayoutBuilder, context):
    """绘制物体子饼左侧的快速操作面板。"""
    obj = getattr(context, "active_object", None)

    col = layout.column(align=True)
    col.scale_x = 1
    col.scale_y = 1.5

    row = col.row(align=True)
    draw_prop(row, obj, "display_type", "显示方式", icon="SHADING_WIRE")
    draw_prop(row, obj, "show_in_front", "最前显示", icon="XRAY")

    col.operator(HO_OT_HoMainPieSeparateLoose.bl_idname,
        text="分离松散块",icon="UNLINKED",)

def _draw_mesh_down_tools(layout: LayoutBuilder, context):
    """绘制网格子饼下方的工具面板。"""
    col = layout.column(align=True)
    col.scale_x = 1.25
    col.scale_y = 1.25

    row = col.row(align=True)
    row.operator(OP_ParallelManifoldSubdivide.bl_idname,
            text="并排流形细分",icon="FILE_VOLUME",)

class HO_MT_HoMainPieMesh(Menu):
    """PME 中的网格工具子饼。"""

    bl_idname = "HO_MT_HoMainPieMesh"
    bl_label = "网格工具"

    def draw(self, context):
        pie = HoPie(self.layout, context)
        pie.left.expand(_draw_mesh_left_tools)
        pie.right.expand(_draw_edge_flow_tools,
            height=1.5,)
        pie.top.expand(_draw_edge_display,
            height=1.5)
        pie.top_right.expand(_draw_quick_modifier_buttons,
            height_offset=30.0)
        pie.bottom.expand(_draw_mesh_down_tools,
            height=1.5)
        pie.finish()


class HO_MT_HoMainPieObject(Menu):
    """主饼右侧的物体工具子饼。"""

    bl_idname = "HO_MT_HoMainPieObject"
    bl_label = "物体面板"

    def draw(self, context):
        pie = HoPie(self.layout, context)
        pie.left.expand(_draw_object_quick_panel, height=1)
        pie.right.expand(_draw_object_export_panel, height=1)
        pie.finish()


class HO_MT_HoMainPie(Menu):
    """HoTools 的编辑模式主工作饼。"""

    bl_idname = "HO_MT_HoMainPie"
    bl_label = "HoMainPie"

    def draw(self, context):
        pie = HoPie(self.layout, context)
        pie.left.pie(HO_MT_HoMainPieMesh.bl_idname,
            text="网格工具",icon="MESH_DATA",)
        pie.right.pie(HO_MT_HoMainPieObject.bl_idname,
            text="物体面板",icon="OBJECT_DATA",)



        space = find_space(context, "VIEW_3D")
        overlay = getattr(space, "overlay", None)
        if overlay is not None:
            pie.top.expression(
                "C.space_data.overlay.show_overlays = not C.space_data.overlay.show_overlays",
                text="叠加层",icon="OVERLAY",depress=bool(getattr(overlay, "show_overlays", False)),)

        pie.top_left.expand(_draw_view_options,
            width=1.5,height=1.5,height_offset=5.0,)
        pie.top_right.expand(_draw_main_top_right,
            height_offset=5.0,)
        pie.finish()


HO_MAIN_PIE_CLASSES = (
    HO_OT_HoMainPieToggleRandomPreview,
    HO_OT_HoMainPieSeparateLoose,
    HO_OT_HoMainPieSetEdgeCrease,
    HO_OT_HoMainPieSelectHalf,
    HO_OT_HoMainPieSelectMirror,
    HO_MT_HoMainPieMesh,
    HO_MT_HoMainPieObject,
    HO_MT_HoMainPie,
)


__all__ = ["HO_MAIN_PIE_CLASSES"]
