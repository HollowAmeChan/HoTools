import mathutils
import bpy
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import EnumProperty
import random
import time
import bmesh
from mathutils import Vector,Matrix

# region 全局变量


DEFAULT_COLOR_GROUP1 = [
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
    (0.75, 0.5, 0.25)]
DEFAULT_COLOR_GROUP2 = [
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
    (1.0, 0.879622, 1.0)]
DEFAULT_COLOR_GROUP3 = [
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
]
# endregion

# region 变量


class PG_VertexColorCol(PropertyGroup):
    index: bpy.props.IntProperty()  # type: ignore
    color: bpy.props.FloatVectorProperty(
        name="VertexColor", size=3, subtype='COLOR', default=(0, 0, 0), min=0, max=1)  # type: ignore


def reg_props():

    # 通道合并相关属性
    bpy.types.Mesh.ho_vertex_color_combine_0 = bpy.props.StringProperty(
        name='R')
    bpy.types.Mesh.ho_vertex_color_combine_1 = bpy.props.StringProperty(
        name='G')
    bpy.types.Mesh.ho_vertex_color_combine_2 = bpy.props.StringProperty(
        name='B')
    bpy.types.Mesh.ho_vertex_color_combine_3 = bpy.props.StringProperty(
        name='A')
    bpy.types.Mesh.ho_vertex_color_combine_tgt = bpy.props.StringProperty(
        name='Target')

    # 预设顶点色集合
    bpy.types.Scene.ho_VertexColorCol = bpy.props.CollectionProperty(
        type=PG_VertexColorCol)
    # 自建缓存顶点色集合
    bpy.types.Scene.ho_TempVertexColor = bpy.props.CollectionProperty(
        type=PG_VertexColorCol)
    # 功能区开关
    bpy.types.Scene.ho_VertexColorPannel_BaseTools = bpy.props.BoolProperty(
        default=True)
    bpy.types.Scene.ho_VertexColorPannel_TemplateTools = bpy.props.BoolProperty(
        default=False)
    bpy.types.Scene.ho_VertexColorPannel_Utils = bpy.props.BoolProperty(
        default=False)
    bpy.types.Scene.ho_VertexColorPannel_Others = bpy.props.BoolProperty(
        default=False)

    # 顶点色预览布尔开关
    def changeViewMode(self, context):
        if context.scene.ho_VertexColorViewMode:
            bpy.ops.ho.entervertexcolorview()
        else:
            bpy.ops.ho.quitvertexcolorview()
    bpy.types.Scene.ho_VertexColorViewMode = bpy.props.BoolProperty(
        default=False, description="!!!注意!!!预览模式是原生blender的预览,颜色不正常没有经过伽马矫正,请去材质中使用顶点色并连接伽马节点,参数为1/2.2≈0.455",
        update=changeViewMode)

    # 吸色模式布尔开关
    def changeGetColorMode(self, context):
        if context.scene.ho_GetVertexColorViewMode:
            bpy.ops.ho.entergetvertexcolorview()
        else:
            bpy.ops.ho.quitgetvertexcolorview()
    bpy.types.Scene.ho_GetVertexColorViewMode = bpy.props.BoolProperty(
        default=False, update=changeGetColorMode)

    # 缓存色，前景色，背景色
    bpy.types.Scene.ho_PaintTempVertexColor = bpy.props.FloatVectorProperty(
        name="缓存颜色", size=3, subtype="COLOR", default=(1, 0, 0), min=0, max=1)
    bpy.types.Scene.ho_FrontTempVertexColor = bpy.props.FloatVectorProperty(
        name="前景颜色", size=3, subtype="COLOR", default=(1, 1, 1), min=0, max=1)
    bpy.types.Scene.ho_BackTempVertexColor = bpy.props.FloatVectorProperty(
        name="背景颜色", size=3, subtype="COLOR", default=(0, 0, 0), min=0, max=1)

    bpy.types.Scene.ho_GroupPaintDefaultIndex = bpy.props.IntProperty(
        default=1)

    # 选择同顶点色的容差
    bpy.types.Scene.ho_chooseSameVertexColorMeshThreshold = bpy.props.FloatProperty(
        name="容差", description="选择同顶点色时的容差(通道共用容差)", default=0.01, max=1, min=0, step=0.01)


def ureg_props():
    del bpy.types.Mesh.ho_vertex_color_combine_0
    del bpy.types.Mesh.ho_vertex_color_combine_1
    del bpy.types.Mesh.ho_vertex_color_combine_2
    del bpy.types.Mesh.ho_vertex_color_combine_3
    del bpy.types.Mesh.ho_vertex_color_combine_tgt


    del bpy.types.Scene.ho_VertexColorCol
    del bpy.types.Scene.ho_TempVertexColor 

    del bpy.types.Scene.ho_VertexColorPannel_BaseTools
    del bpy.types.Scene.ho_VertexColorPannel_TemplateTools
    del bpy.types.Scene.ho_VertexColorPannel_Utils
    del bpy.types.Scene.ho_VertexColorPannel_Others

    del bpy.types.Scene.ho_VertexColorViewMode
    del bpy.types.Scene.ho_GetVertexColorViewMode


    del bpy.types.Scene.ho_PaintTempVertexColor
    del bpy.types.Scene.ho_FrontTempVertexColor
    del bpy.types.Scene.ho_BackTempVertexColor

    del bpy.types.Scene.ho_GroupPaintDefaultIndex

    del bpy.types.Scene.ho_chooseSameVertexColorMeshThreshold

# endregion

# region 操作


class addTempVertexCol(Operator):
    """
    添加缓存颜色
    """
    bl_idname = "ho.addtempvertexcol"
    bl_label = "添加缓存颜色"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        color = context.scene.ho_PaintTempVertexColor
        vtx_color = context.scene.ho_TempVertexColor.add()
        vtx_color.color = color
        return {'FINISHED'}


class removeTempVertexCol(Operator):
    """
    删除缓存颜色
    """
    bl_idname = "ho.removetempvertexcol"
    bl_label = "删除缓存颜色"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty()  # type: ignore

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        col = context.scene.ho_TempVertexColor
        col.remove(self.index)
        return {'FINISHED'}


class clearTempVertexCol(Operator):
    """
    清空缓冲颜色
    """
    bl_idname = "ho.cleartempvertexcol"
    bl_label = "清除缓冲颜色"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        context.scene.ho_TempVertexColor.clear()
        return {'FINISHED'}


class changeTempVertexCol(Operator):
    """
    改变缓存颜色
    """
    bl_idname = "ho.changetempvertexcol"
    bl_label = "改变缓存颜色"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty()  # type: ignore
    color: bpy.props.FloatVectorProperty(size=3)  # type: ignore

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        context.scene.ho_PaintTempVertexColor = self.color
        return {'FINISHED'}


class changeFBVertexCol(Operator):
    """
    对前背景颜色进行操作
    """
    bl_idname = "ho.changefbvertexcol"
    bl_label = "对前背景颜色进行操作"
    bl_options = {'REGISTER', 'UNDO'}

    switch: bpy.props.BoolProperty(default=False)  # type: ignore
    refresh: bpy.props.BoolProperty(default=False)  # type: ignore

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):

        if self.switch:
            temp = context.scene.ho_FrontTempVertexColor.copy()
            context.scene.ho_FrontTempVertexColor = context.scene.ho_BackTempVertexColor.copy()
            context.scene.ho_BackTempVertexColor = temp
            return {'FINISHED'}

        if self.refresh:
            context.scene.ho_FrontTempVertexColor = (1, 1, 1)
            context.scene.ho_BackTempVertexColor = (0, 0, 0)
            return {'FINISHED'}

        return {'FINISHED'}

# 预设顶点色组相关


class clearDefaultVertexCol(Operator):
    """
    清空预设颜色
    """
    bl_idname = "ho.cleardefaultvertexcol"
    bl_label = "清除预设颜色"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        context.scene.ho_GroupPaintDefaultIndex = 0
        context.scene.ho_VertexColorCol.clear()
        return {'FINISHED'}


class changeDefaultVertexCol(Operator):
    """
    改变预设颜色
    """
    bl_idname = "ho.changedefaultvertexcol"
    bl_label = "改变预设颜色"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty()  # type: ignore
    color: bpy.props.FloatVectorProperty()  # type: ignore

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        context.scene.ho_VertexColorCol[self.index].color = self.color
        return {'FINISHED'}


class setDefaultVertexCol(Operator):
    """
    创建预设颜色组
    """
    bl_idname = "ho.setdefaultvertexcol"
    bl_label = "设置预设颜色"
    bl_options = {'REGISTER', 'UNDO'}

    group_index: bpy.props.IntProperty(default=1, min=1, max=3)  # type: ignore

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        default_groups = {
            1: DEFAULT_COLOR_GROUP1,
            2: DEFAULT_COLOR_GROUP2,
            3: DEFAULT_COLOR_GROUP3,
        }
        color_group = default_groups.get(self.group_index)
        if color_group is None:
            self.report({'WARNING'}, "无效的预设组")
            return {'CANCELLED'}

        context.scene.ho_GroupPaintDefaultIndex = self.group_index
        context.scene.ho_VertexColorCol.clear()
        for color in color_group:
            vtx_color = context.scene.ho_VertexColorCol.add()
            vtx_color.color = color

        return {'FINISHED'}

# 视图模式相关


class enterVertexColorView(Operator):
    """
    进入顶点色预览模式
    """
    bl_idname = "ho.entervertexcolorview"
    bl_label = "进入预览模式"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        # 强制寻找 VIEW_3D 区域
        for area in bpy.context.window.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        override = {
                            'window': bpy.context.window,
                            'screen': bpy.context.screen,
                            'area': area,
                            'region': region,
                        }
                        with bpy.context.temp_override(**override):
                            context.scene.view_settings.view_transform = 'Standard'
                            context.space_data.shading.color_type = 'VERTEX'
                            context.space_data.shading.background_type = 'VIEWPORT'
                            context.space_data.shading.light = 'FLAT'
                        break
                break
        else:
            self.report({'WARNING'}, "找不到 3D 视图区")
            return {'CANCELLED'}
        return {'FINISHED'}


class quitVertexColorView(Operator):
    """
    退出顶点色预览模式
    """
    bl_idname = "ho.quitvertexcolorview"
    bl_label = "从预览模式中退出"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        # 强制寻找 VIEW_3D 区域
        for area in bpy.context.window.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        override = {
                            'window': bpy.context.window,
                            'screen': bpy.context.screen,
                            'area': area,
                            'region': region,
                        }
                        with bpy.context.temp_override(**override):
                            context.scene.ho_GetVertexColorViewMode = 0
                            context.scene.view_settings.view_transform = 'Standard'
                            context.space_data.overlay.show_overlays = True
                            context.space_data.shading.light = 'STUDIO'
                            context.space_data.shading.color_type = 'MATERIAL'
                            context.space_data.shading.background_type = 'THEME'
                            break
                break
        else:
            self.report({'WARNING'}, "找不到 3D 视图区")
            return {'CANCELLED'}
        return {'FINISHED'}

# 工具操作
def linear_channel_to_srgb(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * pow(c, 1.0 / 2.4) - 0.055

def linear_to_srgb(color):
    return [linear_channel_to_srgb(c) for c in color]

def get_active_corner_color_attribute(mesh, create_if_missing=True):
    if len(mesh.color_attributes) == 0:
        if not create_if_missing:
            return None
        color_attr = mesh.color_attributes.new(
            name="Col", type='BYTE_COLOR', domain='CORNER')
        mesh.color_attributes.active_color_index = len(mesh.color_attributes) - 1
        return color_attr

    color_index = mesh.color_attributes.active_color_index
    color_attr = mesh.color_attributes[color_index]
    if color_attr.domain != 'CORNER':
        raise RuntimeError("当前激活的顶点色层不是 Face Corner 类型")

    return color_attr

def get_active_corner_color_data(mesh, create_if_missing=True):
    color_attr = get_active_corner_color_attribute(mesh, create_if_missing)
    if color_attr is None:
        return None
    return color_attr.data

def get_color_data_value(color_data):
    if hasattr(color_data, "color_srgb"):
        return color_data.color_srgb
    return color_data.color

class setMeshVertexColor(Operator):
    """
    给选中网格指定顶点色
    """
    bl_idname = "ho.setmeshvertexcolor"
    bl_label = "给选中网格指定顶点色"
    bl_options = {'REGISTER', 'UNDO'}

    color: bpy.props.FloatVectorProperty()  # type: ignore

    @classmethod
    def poll(cls, context):
        return (context.object is not None and context.object.type == 'MESH'
                and context.mode == 'EDIT_MESH')

    def execute(self, context):
        obj = context.object
        if obj is None or obj.type != 'MESH':
            self.report({'WARNING'}, "当前对象不是网格")
            return {'CANCELLED'}

        if context.mode != 'EDIT_MESH':
            self.report({'WARNING'}, "请在编辑模式下使用此操作")
            return {'CANCELLED'}

        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)

        active_color = get_active_corner_color_attribute(mesh)
        color_layer = bm.loops.layers.color.get(active_color.name)
        if color_layer is None:
            color_layer = bm.loops.layers.color.new(active_color.name)

        color = (*linear_to_srgb(self.color[:3]), 1.0)
        selected_faces = [face for face in bm.faces if face.select]
        if not selected_faces:
            self.report({'WARNING'}, "当前没有选中任何面")
            return {'CANCELLED'}

        for face in selected_faces:
            for loop in face.loops:
                loop[color_layer] = color

        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        return {'FINISHED'}

class chooseSameVertexColorMesh(Operator):
    """
    选择同种顶点色的网格
    """
    bl_idname = "ho.choosesamevertexcolormesh"
    bl_label = "选择同种顶点色的网格"
    bl_options = {'REGISTER', 'UNDO'}

    threshold: bpy.props.FloatProperty(
        name="容差", description="选择同顶点色时的容差(通道共用容差)", default=0.01, max=1, min=0, step=0.01)  # type: ignore

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        threshold = self.threshold
        obj = bpy.context.object

        bpy.ops.object.mode_set(mode="OBJECT")

        colors = get_active_corner_color_data(obj.data, create_if_missing=False)
        if colors is None:
            self.report({'WARNING'}, "当前没有可用的顶点色层")
            bpy.ops.object.editmode_toggle()
            return {'CANCELLED'}
        selected_polygons = list(filter(lambda p: p.select, obj.data.polygons))

        if len(selected_polygons):
            p = selected_polygons[0]
            r = g = b = 0
            for i in p.loop_indices:
                c = get_color_data_value(colors[i])
                r += c[0]
                g += c[1]
                b += c[2]
            r /= p.loop_total
            g /= p.loop_total
            b /= p.loop_total
            target = mathutils.Color((r, g, b))

            for p in obj.data.polygons:
                r = g = b = 0
                for i in p.loop_indices:
                    c = get_color_data_value(colors[i])
                    r += c[0]
                    g += c[1]
                    b += c[2]
                r /= p.loop_total
                g /= p.loop_total
                b /= p.loop_total
                source = mathutils.Color((r, g, b))

                print(target, source)

                if (abs(source.r - target.r) < threshold and
                    abs(source.g - target.g) < threshold and
                        abs(source.b - target.b) < threshold):

                    p.select = True

        bpy.ops.object.editmode_toggle()
        return {'FINISHED'}     


class vertexWeight2vertexColor(Operator):
    """
    使用顶点权重绘制到顶点色
    """
    bl_idname = "ho.vertexweight2vertexcolor"
    bl_label = "使用选中的顶点组的权重，绘制到顶点色"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        bpy.ops.paint.vertex_paint_toggle()
        bpy.ops.paint.vertex_color_from_weight()
        bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}


class vertexColorChannelCombine(Operator):
    """
    合并四个顶点色层到另一个顶点色层
    """
    bl_idname = "ho.vertexcolorchannelcombine"
    bl_label = "合并四个顶点色层到另一个顶点色层"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        bpy.ops.object.mode_set(mode='OBJECT')
        mesh = bpy.context.active_object.data
        self.combine_vertexcolor_channel(
            mesh.ho_vertex_color_combine_0,
            mesh.ho_vertex_color_combine_1,
            mesh.ho_vertex_color_combine_2,
            mesh.ho_vertex_color_combine_3,
            mesh.ho_vertex_color_combine_tgt,
        )
        return {'FINISHED'}

    def combine_vertexcolor_channel(self, layerR, layerG, layerB, layerA, target):
        r = 0.0
        g = 0.0
        b = 0.0
        a = 1.0
        if layerR:
            atrR = bpy.context.active_object.data.color_attributes[layerR]
            itemsR = atrR.data.items()[:]
        if layerG:
            atrG = bpy.context.active_object.data.color_attributes[layerG]
            itemsG = atrG.data.items()[:]
        if layerB:
            atrB = bpy.context.active_object.data.color_attributes[layerB]
            itemsB = atrB.data.items()[:]
        if layerA:
            atrA = bpy.context.active_object.data.color_attributes[layerA]
            itemsA = atrA.data.items()[:]
        if target:
            atrTgt = bpy.context.active_object.data.color_attributes[target]
            itemsTgt = atrTgt.data.items()[:]
        if not target:
            return

        mesh = bpy.context.active_object.data
        for poly in mesh.polygons:
            for loop_index in poly.loop_indices:
                if layerR:
                    r = itemsR[loop_index][1].color_srgb[0]
                if layerG:
                    g = itemsG[loop_index][1].color_srgb[0]
                if layerB:
                    b = itemsB[loop_index][1].color_srgb[0]
                if layerA:
                    a = itemsA[loop_index][1].color_srgb[0]
                combined_color = (r, g, b, a)
                itemsTgt[loop_index][1].color_srgb = combined_color


class bakeNormal2VertexColor(Operator):
    bl_idname = "ho.bake_custom_normal_to_vertex_color"
    bl_label = "烘焙自定义法线到顶点色"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="法线空间转换",
        items=[
            (
                'CUSTOM2RAW',
                "custom → raw",
                "将自定义（平滑）法线编码到原始TBN空间"
            ),
            (
                'RAW2CUSTOM',
                "raw → custom（liltoon）",
                "将原始法线编码到当前（自定义/平滑）TBN空间，用于修复 liltoon 描边方向"
            ),
            (
                'OBJECT2SMOOTH',
                "other smooth → active smooth",
                "将另一个物体的平滑法线编码到当前物体的平滑TBN空间"
            ),
        ],
        default='CUSTOM2RAW'
    )  # type: ignore

    def get_active_corner_color_attribute(self, mesh):
        return get_active_corner_color_attribute(mesh)

    def write_color_data(self, color_data, color):
        if hasattr(color_data, "color_srgb"):
            color_data.color_srgb = color
        else:
            color_data.color = color

    def get_source_normal(self, normal_mesh, loop_index, use_vertex_normal=False):
        if use_vertex_normal:
            vertex_index = normal_mesh.loops[loop_index].vertex_index
            return normal_mesh.vertices[vertex_index].normal.normalized()
        return normal_mesh.loops[loop_index].normal

    def get_other_selected_mesh_object(self, context, active_obj):
        other_mesh_objects = [
            obj for obj in context.selected_objects
            if obj.type == 'MESH' and obj != active_obj
        ]
        if len(other_mesh_objects) != 1:
            raise RuntimeError("该模式需要额外选择且仅选择一个参考网格物体")
        return other_mesh_objects[0]

    def ensure_same_topology(self, mesh_a, mesh_b):
        if len(mesh_a.vertices) != len(mesh_b.vertices):
            raise RuntimeError("两个物体的顶点数量不一致")
        if len(mesh_a.edges) != len(mesh_b.edges):
            raise RuntimeError("两个物体的边数量不一致")
        if len(mesh_a.loops) != len(mesh_b.loops):
            raise RuntimeError("两个物体的面角数量不一致")
        if len(mesh_a.polygons) != len(mesh_b.polygons):
            raise RuntimeError("两个物体的面数量不一致")

        for poly_index, (poly_a, poly_b) in enumerate(zip(mesh_a.polygons, mesh_b.polygons)):
            if poly_a.loop_total != poly_b.loop_total:
                raise RuntimeError(f"第 {poly_index} 个面的边数不一致")

            verts_a = [mesh_a.loops[li].vertex_index for li in poly_a.loop_indices]
            verts_b = [mesh_b.loops[li].vertex_index for li in poly_b.loop_indices]
            if verts_a != verts_b:
                raise RuntimeError(f"第 {poly_index} 个面的拓扑顺序不一致")

    def create_raw_reference_object(self, context, obj):
        mesh = obj.data
        custom_normals = [loop.normal.copy() for loop in mesh.loops]

        bpy.ops.mesh.customdata_custom_splitnormals_clear()

        obj_raw = obj.copy()
        obj_raw.data = obj.data.copy()
        obj_raw.name = obj.name + "_raw"
        context.collection.objects.link(obj_raw)

        mesh.normals_split_custom_set(custom_normals)
        return obj_raw

    def bake_normal(self, dst_obj, tbn_obj, normal_obj, use_vertex_normal=False):
        dst_mesh = dst_obj.data
        tbn_mesh = tbn_obj.data
        normal_mesh = normal_obj.data

        dst_mesh.calc_tangents()
        tbn_mesh.calc_tangents()
        normal_mesh.calc_tangents()

        color_attr = self.get_active_corner_color_attribute(dst_mesh)
        color_layer = color_attr.data

        for poly in dst_mesh.polygons:
            for li in poly.loop_indices:

                tbn_loop = tbn_mesh.loops[li]
                t = tbn_loop.tangent
                b = tbn_loop.bitangent
                n = tbn_loop.normal

                src_n = self.get_source_normal(
                    normal_mesh, li, use_vertex_normal)

                encoded_normal = (
                    src_n.dot(t) * 0.5 + 0.5,
                    src_n.dot(b) * 0.5 + 0.5,
                    src_n.dot(n) * 0.5 + 0.5,
                    1.0
                )
                self.write_color_data(color_layer[li], encoded_normal)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "mode", expand=True)
        if self.mode == 'OBJECT2SMOOTH':
            layout.label(text="额外选择一个拓扑一致的参考网格")

    def execute(self, context):
        obj0 = context.object
        if obj0 is None or obj0.type != 'MESH':
            self.report({'WARNING'}, "请先选择一个网格物体")
            return {'CANCELLED'}
        mesh0 = obj0.data

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        obj_raw = None

        try:
            if self.mode == 'RAW2CUSTOM':
                if not mesh0.has_custom_normals:
                    self.report({'WARNING'}, "当前网格没有自定义法线")
                    return {'CANCELLED'}

                obj_raw = self.create_raw_reference_object(context, obj0)
                self.bake_normal(
                    dst_obj=obj0,
                    tbn_obj=obj0,
                    normal_obj=obj_raw,
                    use_vertex_normal=True
                )

            elif self.mode == 'CUSTOM2RAW':
                if not mesh0.has_custom_normals:
                    self.report({'WARNING'}, "当前网格没有自定义法线")
                    return {'CANCELLED'}

                obj_raw = self.create_raw_reference_object(context, obj0)
                self.bake_normal(
                    dst_obj=obj0,
                    tbn_obj=obj_raw,
                    normal_obj=obj0,
                    use_vertex_normal=False
                )

            else:
                src_obj = self.get_other_selected_mesh_object(context, obj0)
                self.ensure_same_topology(mesh0, src_obj.data)

                obj_raw = self.create_raw_reference_object(context, obj0)
                self.bake_normal(
                    dst_obj=obj0,
                    tbn_obj=obj_raw,
                    normal_obj=src_obj,
                    use_vertex_normal=True
                )

        except Exception as e:
            self.report({'ERROR'}, str(e))
            if obj_raw is not None:
                bpy.data.objects.remove(obj_raw, do_unlink=True)
            return {'CANCELLED'}

        if obj_raw is not None:
            bpy.data.objects.remove(obj_raw, do_unlink=True)

        return {"FINISHED"}


# endregion

# region 面板

    

def draw_in_DATA_PT_vertex_colors(self, context: bpy.types.Context):
    if context.active_object.type != "MESH":
        return
    layout = self.layout
    row = layout.row(align=True)
    row.prop(context.scene, "ho_VertexColorViewMode",
                text="", icon="OVERLAY", toggle=True)
    row.prop(context.scene, "ho_VertexColorPannel_BaseTools",
                text="基础", toggle=True)
    row.prop(context.scene, "ho_VertexColorPannel_TemplateTools",
                text="模板", toggle=True)
    row.prop(context.scene, "ho_VertexColorPannel_Utils",
                text="实用", toggle=True)
    row.prop(context.scene, "ho_VertexColorPannel_Others",
                text="其他", toggle=True)

    # # ----始终显示顶点色层面板----
    # row = layout.row()
    # col = row.column()
    # col.template_list(
    #     "MESH_UL_color_attributes",
    #     "color_attributes",
    #     context.active_object.data,
    #     "color_attributes",
    #     context.object.data.color_attributes,
    #     "active_color_index",
    #     rows=3,
    # )

    # col = row.column(align=True)
    # col.operator("geometry.color_attribute_add", icon='ADD', text="")
    # col.operator("geometry.color_attribute_remove", icon='REMOVE', text="")
    # col.separator()
    # col.menu("MESH_MT_color_attribute_context_menu",
    #             icon='DOWNARROW_HLT', text="")

    # 基础工具
    if context.scene.ho_VertexColorPannel_BaseTools:
        layout = self.layout.column(align=True)
        # 缓冲颜色绘制
        single = layout.row(align=True)

        change = single.operator(
            setMeshVertexColor.bl_idname, text="", icon="GREASEPENCIL")
        change.color = context.scene.ho_PaintTempVertexColor  # 绘制缓冲色到面

        single.prop(context.scene, "ho_PaintTempVertexColor",
                    icon_only=True)  # 缓冲色

        single = layout.row(align=True)
        single.alignment = ("CENTER")
        change = single.operator(
            changeTempVertexCol.bl_idname, text="", icon="EVENT_F")
        change.color = context.scene.ho_FrontTempVertexColor  # 切换为前景颜色

        change = single.operator(
            changeTempVertexCol.bl_idname, text="", icon="EVENT_B")
        change.color = context.scene.ho_BackTempVertexColor  # 切换为背景颜色

        change = single.operator(
            changeTempVertexCol.bl_idname, text="", icon="EVENT_R")
        seed = int(time.time()*10)
        random.seed(seed)  # 切换为随机颜色
        change.color = (random.random(), random.random(), random.random())

        single.operator(addTempVertexCol.bl_idname,
                        text="", icon="ADD")  # 添加到缓存

        # 前后景色设置
        single = layout.row(align=True)

        single.prop(context.scene, "ho_FrontTempVertexColor",
                    icon_only=True)
        single.prop(context.scene, "ho_BackTempVertexColor",
                    icon_only=True)

        single = layout.row(align=True)
        single.alignment = ("CENTER")

        change = single.operator(
            setMeshVertexColor.bl_idname, text="", icon="GREASEPENCIL")
        change.color = context.scene.ho_FrontTempVertexColor
        change = single.operator(
            setMeshVertexColor.bl_idname, text="", icon="OUTLINER_DATA_GP_LAYER")
        change.color = context.scene.ho_BackTempVertexColor

        change = single.operator(
            changeFBVertexCol.bl_idname, text="", icon="ARROW_LEFTRIGHT")
        change.switch = True
        change.refresh = False  # 交换前背景

        change = single.operator(
            changeFBVertexCol.bl_idname, text="", icon="FILE_REFRESH")
        change.switch = False
        change.refresh = True  # 刷新前背景

        layout.separator()

        # 缓冲自设颜色
        vc = context.scene.ho_TempVertexColor
        if vc:
            layout.label(text="颜色组")
            col = layout.column(align=True)
            col.operator(clearTempVertexCol.bl_idname,
                            text="", icon="TRASH")
            for i in range(len(vc[:])):
                # 每一行
                if not vc[i]:
                    break
                single = col.row(align=True)
                # 应用颜色到顶点色的按钮
                change = single.operator(
                    setMeshVertexColor.bl_idname, text="", icon="GREASEPENCIL")
                change.color = vc[i].color

                # 颜色属性的按钮
                single.prop(data=vc[i], property="color", icon_only=True)

                # 删除颜色的按钮
                change = single.operator(
                    removeTempVertexCol.bl_idname, text="", icon="TRASH")
                change.index = i
    # 模板工具
    if context.scene.ho_VertexColorPannel_TemplateTools:
        layout = self.layout.column(align=True)
        layout.label(text="模板工具")
        single = layout.row(align=True)
        single.operator(clearDefaultVertexCol.bl_idname,
                        text="", icon="TRASH")
        o = single.operator(setDefaultVertexCol.bl_idname,
                        text="", icon="EVENT_A")
        o.group_index = 1
        o = single.operator(setDefaultVertexCol.bl_idname,
                        text="", icon="EVENT_B")
        o.group_index = 2
        o = single.operator(setDefaultVertexCol.bl_idname,
                        text="", icon="EVENT_C")
        o.group_index = 3

        # 预设顶点颜色
        vc = context.scene.ho_VertexColorCol
        if vc:
            layout.label(text="预设组")
            layout = self.layout.column(align=True)
            col = layout.column(align=True)
            for i in range(len(vc[:])):
                # 每一行
                if not vc[i]:
                    break
                single = col.row(align=True)
                # 应用颜色到顶点色的按钮
                change = single.operator(
                    setMeshVertexColor.bl_idname, text="", icon="GREASEPENCIL")
                change.color = vc[i].color

                # 颜色属性的按钮
                single.prop(data=vc[i], property="color", icon_only=True)

                # 刷新颜色的按钮
                change = single.operator(
                    changeDefaultVertexCol.bl_idname, text="", icon="FILE_REFRESH")
                change.index = i
                change.color = DEFAULT_COLOR_GROUP1[
                    i % len(DEFAULT_COLOR_GROUP1)]
    # 实用工具
    if context.scene.ho_VertexColorPannel_Utils:
        layout = self.layout.column(align=True)
        layout.label(text="实用工具")
        
        row = layout.row(align=True)
        row.prop(context.scene,
                    "ho_chooseSameVertexColorMeshThreshold", text="容差")
        o = row.operator(
            chooseSameVertexColorMesh.bl_idname, text="选择同顶点色面", icon="RADIOBUT_ON")
        o.threshold = context.scene.ho_chooseSameVertexColorMeshThreshold

        layout.operator(vertexWeight2vertexColor.bl_idname,
                        text="权重到顶点色")
        layout.operator(bakeNormal2VertexColor.bl_idname,
                        text="烘焙顶点法线到顶点色")

        
    # 其它工具
    if context.scene.ho_VertexColorPannel_Others:
        # ----层工具----
        self.layout.label(text='合并通道')

        def draw_color_override(key):
            value = getattr(context.object.data, key)
            layout = self.layout
            if value in context.object.data.color_attributes and context.object.data.color_attributes[value].domain != 'CORNER':
                layout = self.layout.box()
                layout.label(
                    text='Only Face Corner attributes are supported', icon='ERROR')
            layout.prop_search(context.object.data, key,
                                context.object.data, 'color_attributes')

        draw_color_override('ho_vertex_color_combine_0')
        draw_color_override('ho_vertex_color_combine_1')
        draw_color_override('ho_vertex_color_combine_2')
        draw_color_override('ho_vertex_color_combine_3')
        draw_color_override('ho_vertex_color_combine_tgt')

        layout = self.layout
        layout.operator(
            vertexColorChannelCombine.bl_idname, text="合并到目标层")



cls = [PG_VertexColorCol,
    addTempVertexCol, removeTempVertexCol,
    changeTempVertexCol, changeFBVertexCol,
    clearDefaultVertexCol, changeDefaultVertexCol,
    clearTempVertexCol,
    setDefaultVertexCol,
    enterVertexColorView, quitVertexColorView,
    setMeshVertexColor, chooseSameVertexColorMesh,
    vertexWeight2vertexColor,
    vertexColorChannelCombine,bakeNormal2VertexColor

       ]
# endregion


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()
    bpy.types.DATA_PT_vertex_colors.append(draw_in_DATA_PT_vertex_colors)


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
    bpy.types.DATA_PT_vertex_colors.remove(draw_in_DATA_PT_vertex_colors)
