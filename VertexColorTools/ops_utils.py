import bpy
from bpy.props import FloatProperty
from bpy.types import Operator
from mathutils import Color

from .bake_normal import HO_OT_bake_normal_to_vertex_color
from .properties import get_scene_settings
from .utils import get_active_corner_color_data, get_color_data_value
from ..i18n import tr


class HO_OT_choose_same_vertex_color_mesh(Operator):
    bl_idname = "ho.choosesamevertexcolormesh"
    bl_label = "选择相同顶点色面"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties):
        return tr("选择相同顶点色面")

    threshold: FloatProperty(
        name="容差",
        description="选择同顶点色时使用的容差",
        default=0.01,
        min=0.0,
        max=1.0,
    )  # type: ignore

    def execute(self, context):
        obj = context.object
        if obj is None or obj.type != "MESH":
            self.report({"WARNING"}, tr("请先选择一个网格物体"))
            return {"CANCELLED"}

        bpy.ops.object.mode_set(mode="OBJECT")

        colors = get_active_corner_color_data(obj.data, create_if_missing=False)
        if colors is None:
            self.report({"WARNING"}, tr("当前没有可用的顶点色层"))
            bpy.ops.object.editmode_toggle()
            return {"CANCELLED"}

        selected_polygons = [polygon for polygon in obj.data.polygons if polygon.select]
        if not selected_polygons:
            bpy.ops.object.editmode_toggle()
            return {"FINISHED"}

        target_polygon = selected_polygons[0]
        target_color = self.average_polygon_color(target_polygon, colors)

        for polygon in obj.data.polygons:
            source_color = self.average_polygon_color(polygon, colors)
            if (
                abs(source_color.r - target_color.r) < self.threshold
                and abs(source_color.g - target_color.g) < self.threshold
                and abs(source_color.b - target_color.b) < self.threshold
            ):
                polygon.select = True

        bpy.ops.object.editmode_toggle()
        return {"FINISHED"}

    @staticmethod
    def average_polygon_color(polygon, colors):
        red = green = blue = 0.0
        for loop_index in polygon.loop_indices:
            color = get_color_data_value(colors[loop_index])
            red += color[0]
            green += color[1]
            blue += color[2]

        divisor = max(1, polygon.loop_total)
        return Color((red / divisor, green / divisor, blue / divisor))


class HO_OT_vertex_weight_to_vertex_color(Operator):
    bl_idname = "ho.vertexweight2vertexcolor"
    bl_label = "权重转顶点色"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties):
        return tr("权重转顶点色")

    def execute(self, context):
        bpy.ops.paint.vertex_paint_toggle()
        bpy.ops.paint.vertex_color_from_weight()
        bpy.ops.object.mode_set(mode="OBJECT")
        return {"FINISHED"}


def draw_utils_panel(context, layout):
    settings = get_scene_settings(context.scene)
    section = layout.column(align=True)

    row = section.row(align=True)
    row.prop(settings, "choose_same_threshold", text=tr("容差"))
    op = row.operator(
        HO_OT_choose_same_vertex_color_mesh.bl_idname,
        text=tr("选择同顶点色面"),
        icon="RADIOBUT_ON",
    )
    op.threshold = settings.choose_same_threshold

    section.operator(
        HO_OT_vertex_weight_to_vertex_color.bl_idname,
        text=tr("权重转顶点色"),
    )
    section.operator(
        HO_OT_bake_normal_to_vertex_color.bl_idname,
        text=tr("烘焙顶点法线到顶点色"),
    )


CLASSES = (
    HO_OT_choose_same_vertex_color_mesh,
    HO_OT_vertex_weight_to_vertex_color,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
