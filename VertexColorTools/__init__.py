import mathutils
import bpy
from bpy.types import Operator, Panel, PropertyGroup
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

    # 默认组赋色的布尔开关，以及组赋色的index
    bpy.types.Scene.ho_isGroupPaintMode = bpy.props.BoolProperty(
        default=True)
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

    del bpy.types.Scene.ho_isGroupPaintMode
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


class set1DefaultVertexCol(Operator):
    """
    创建预设一
    """
    bl_idname = "ho.set1defaultvertexcol"
    bl_label = "清除预设颜色"
    bl_options = {'REGISTER', 'UNDO'}

    color_list: bpy.props.FloatVectorProperty()  # type: ignore

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        context.scene.ho_GroupPaintDefaultIndex = 1
        context.scene.ho_VertexColorCol.clear()
        for i in DEFAULT_COLOR_GROUP1:
            vtx_color = context.scene.ho_VertexColorCol.add()
            vtx_color.color = i

        return {'FINISHED'}


class set2DefaultVertexCol(Operator):
    """
    创建预设二
    """
    bl_idname = "ho.set2defaultvertexcol"
    bl_label = "清除预设颜色"
    bl_options = {'REGISTER', 'UNDO'}

    color_list: bpy.props.FloatVectorProperty()  # type: ignore

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        context.scene.ho_GroupPaintDefaultIndex = 2
        context.scene.ho_VertexColorCol.clear()
        for i in DEFAULT_COLOR_GROUP2:
            vtx_color = context.scene.ho_VertexColorCol.add()
            vtx_color.color = i

        return {'FINISHED'}


class set3DefaultVertexCol(Operator):
    """
    创建预设三
    """
    bl_idname = "ho.set3defaultvertexcol"
    bl_label = "清除预设颜色"
    bl_options = {'REGISTER', 'UNDO'}

    color_list: bpy.props.FloatVectorProperty()  # type: ignore

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        context.scene.ho_GroupPaintDefaultIndex = 3
        context.scene.ho_VertexColorCol.clear()
        for i in DEFAULT_COLOR_GROUP3:
            vtx_color = context.scene.ho_VertexColorCol.add()
            vtx_color.color = i

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
        return True

    def execute(self, context):
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
                            bpy.ops.paint.vertex_paint_toggle()
                            context.object.data.use_paint_mask = True
                            context.tool_settings.vertex_paint.brush = bpy.data.brushes['Draw']
                            #UI绘制的颜色存进去的颜色不一样，存进去的颜色使用属性预览的跟出去烘的是一致的，所以需要修正的部分在这个指定的步骤
                            bpy.data.brushes["Draw"].color = linear_to_srgb(self.color[:3])
                            bpy.ops.paint.vertex_color_set()
                            bpy.ops.object.editmode_toggle()
                        break
                break
        else:
            self.report({'WARNING'}, "找不到 3D 视图区")
            return {'CANCELLED'}
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

        colors = obj.data.vertex_colors.active.data
        selected_polygons = list(filter(lambda p: p.select, obj.data.polygons))

        if len(selected_polygons):
            p = selected_polygons[0]
            r = g = b = 0
            for i in p.loop_indices:
                c = colors[i].color
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
                    c = colors[i].color
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


class vertexGroup2RandomVertexColor(Operator):
    """
    给顶点组赋随机的顶点色
    """
    bl_idname = "ho.vertexgroup2randomvertexcolor"
    bl_label = "给顶点组赋随机的顶点色，只能为面组"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        obj = bpy.context.active_object
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
                            # 获取所有顶点组
                            vgroups = obj.vertex_groups
                            bpy.ops.object.editmode_toggle()
                            for i in range(len(vgroups)):
                                selected_vgroup = vgroups[i]

                                # 检查顶点组是否存在
                                if selected_vgroup is not None:
                                    # 获取网格数据
                                    mesh = obj.data

                                    # 选择指定名称的顶点组所属的网格
                                    bpy.ops.object.mode_set(mode='OBJECT')
                                    bpy.ops.object.select_all(action='DESELECT')
                                    obj.select_set(True)
                                    bpy.context.view_layer.objects.active = obj
                                    bpy.ops.object.mode_set(mode='EDIT')
                                    bpy.ops.mesh.select_all(action='DESELECT')
                                    bpy.ops.object.vertex_group_set_active(
                                        group=selected_vgroup.name)
                                    bpy.ops.object.vertex_group_select()
                                    bpy.ops.object.mode_set(mode='OBJECT')
                                    # 赋予颜色
                                    bpy.ops.paint.vertex_paint_toggle()
                                    bpy.context.object.data.use_paint_mask = True
                                    context.tool_settings.vertex_paint.brush = bpy.data.brushes['Draw']
                                    bpy.data.brushes["Draw"].color = (
                                        random.random(), random.random(), random.random())
                                    bpy.ops.paint.vertex_color_set()
                                    bpy.ops.object.editmode_toggle()
                                    return {'FINISHED'}
                        break
                break
        else:
            self.report({'WARNING'}, "找不到 3D 视图区")
            return {'CANCELLED'}

        
        return {'FINISHED'}


class vertexGroup2DefaultVertexColor(Operator):
    """
    给顶点组赋指定组内的的颜色
    """
    bl_idname = "ho.vertexgroup2defaultvertexcolor"
    bl_label = "给顶点组赋指定组内的的颜色，只能为面组"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        obj = bpy.context.active_object
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
                            # 获取所有顶点组
                            vgroups = obj.vertex_groups

                            index = context.scene.ho_GroupPaintDefaultIndex
                            mode = context.scene.ho_isGroupPaintMode

                            if obj == None:
                                return
                            if mode == False:
                                default_color = [
                                    i.color for i in context.scene.ho_TempVertexColor[:]]
                            elif mode != False and index == 1:
                                default_color = DEFAULT_COLOR_GROUP1
                            elif mode != False and index == 2:
                                default_color = DEFAULT_COLOR_GROUP2
                            elif mode != False and index == 3:
                                default_color = DEFAULT_COLOR_GROUP3
                            else:
                                default_color = DEFAULT_COLOR_GROUP1

                            # 首先刷白此物体全部顶点色
                            bpy.ops.object.mode_set(mode='EDIT')
                            bpy.ops.mesh.select_all(action='SELECT')
                            bpy.ops.paint.vertex_paint_toggle()
                            bpy.context.object.data.use_paint_mask = True
                            context.tool_settings.vertex_paint.brush = bpy.data.brushes['Draw']
                            bpy.data.brushes["Draw"].color = (1, 1, 1)
                            bpy.ops.paint.vertex_color_set()
                            bpy.ops.object.editmode_toggle()
                            # 逐顶点组操作
                            bpy.ops.object.editmode_toggle()
                            for i in range(len(vgroups)):
                                selected_vgroup = vgroups[i]

                                # 检查顶点组是否存在,颜色组是否存在
                                if selected_vgroup is None:
                                    return {'FINISHED'}
                                if len(default_color) == 0:
                                    return {'FINISHED'}
                                # 选择指定名称的顶点组所属的网格
                                bpy.ops.object.mode_set(mode='OBJECT')
                                bpy.ops.object.select_all(action='DESELECT')
                                obj.select_set(True)
                                bpy.context.view_layer.objects.active = obj
                                bpy.ops.object.mode_set(mode='EDIT')
                                bpy.ops.mesh.select_all(action='DESELECT')
                                bpy.ops.object.vertex_group_set_active(
                                    group=selected_vgroup.name)
                                bpy.ops.object.vertex_group_select()
                                bpy.ops.object.mode_set(mode='OBJECT')

                                bpy.ops.paint.vertex_paint_toggle()
                                bpy.context.object.data.use_paint_mask = True
                                context.tool_settings.vertex_paint.brush = bpy.data.brushes['Draw']
                                bpy.data.brushes["Draw"].color = default_color[i %
                                                                            len(default_color)]
                                bpy.ops.paint.vertex_color_set()
                                bpy.ops.object.editmode_toggle()
                            return {'FINISHED'}
                        break
                break
        else:
            self.report({'WARNING'}, "找不到 3D 视图区")
            return {'CANCELLED'}
        


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

    def bake_normal(self,obj, src):
        obj.data.calc_tangents()
        src.data.calc_tangents()

        if not obj.data.vertex_colors:
            obj.data.vertex_colors.new()

        for polygon in obj.data.polygons:
            for loop_index in polygon.loop_indices:
                obj_loop = obj.data.loops[loop_index]

                obj_tangent = obj_loop.tangent
                obj_bitangent = obj_loop.bitangent
                obj_normal = obj_loop.normal

                src_loop = src.data.loops[loop_index]
                src_normal = src_loop.normal

                obj.data.vertex_colors.active.data[loop_index].color = (
                    mathutils.Vector.dot(src_normal, obj_tangent) * 0.5 + 0.5,
                    mathutils.Vector.dot(src_normal, obj_bitangent) * 0.5 + 0.5,
                    mathutils.Vector.dot(src_normal, obj_normal) * 0.5 + 0.5,
                    1.0
                )

    def execute(self, context):
        obj0 = context.object
        mesh0 = obj0.data
        if not mesh0.has_custom_normals:
            self.report({'WARNING'}, "当前网格没有自定义法线")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # 提取源原本网格的loop normals，然后清除
        normals = [list(loop.normal) for loop in mesh0.loops]
        bpy.ops.mesh.customdata_custom_splitnormals_clear()

        # 复制空法线数据对象（包括 mesh 数据）
        obj1 = obj0.copy()
        obj1.data = obj0.data.copy()
        obj1.name = obj0.name + "_copy"
        bpy.context.collection.objects.link(obj1)

        #导回源原本网格的loop normals
        mesh0.normals_split_custom_set(normals)
        
        #进行切线空间法线计算
        if bpy.context.active_object == obj0:
            try:
                self.bake_normal(obj0, obj1)
            except:
                return {'CANCELLED'}

        else:
            try:
             self.bake_normal(obj1, obj0)
            except:
                return {'CANCELLED'}
        # 删除备份物体
        bpy.data.objects.remove(obj1, do_unlink=True)

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
        single.operator(set1DefaultVertexCol.bl_idname,
                        text="", icon="EVENT_A")
        single.operator(set2DefaultVertexCol.bl_idname,
                        text="", icon="EVENT_B")
        single.operator(set3DefaultVertexCol.bl_idname,
                        text="", icon="EVENT_C")

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
        row.prop(context.scene, "ho_isGroupPaintMode",
                    text="使用预设组", toggle=True)
        row.operator(
            vertexGroup2DefaultVertexColor.bl_idname, text="顶点组赋颜色组", icon="FUND")
        row = layout.row(align=True)

        row.prop(context.scene,
                    "ho_chooseSameVertexColorMeshThreshold", text="容差")
        o = row.operator(
            chooseSameVertexColorMesh.bl_idname, text="选择同顶点色面", icon="SEQUENCE_COLOR_01")
        o.threshold = context.scene.ho_chooseSameVertexColorMeshThreshold

        layout.operator(
            vertexGroup2RandomVertexColor.bl_idname, text="顶点组赋随机色")
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
       set1DefaultVertexCol,
       set2DefaultVertexCol,
       set3DefaultVertexCol,
       enterVertexColorView, quitVertexColorView,
       setMeshVertexColor, chooseSameVertexColorMesh,
       vertexGroup2RandomVertexColor, vertexGroup2DefaultVertexColor, vertexWeight2vertexColor,
       vertexColorChannelCombine,bakeNormal2VertexColor

       ]
# endregion


def register():
    print("VertexColorTools reging")
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()
    bpy.types.DATA_PT_vertex_colors.append(draw_in_DATA_PT_vertex_colors)


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
    bpy.types.DATA_PT_vertex_colors.remove(draw_in_DATA_PT_vertex_colors)
