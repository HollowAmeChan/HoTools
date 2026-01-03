import bpy
import sys
import os
import json
import subprocess
import random
import numpy as np

if sys.version_info >= (3, 11):
    from ._Lib.py311.PIL import Image, ImageDraw ,ImageFilter
else:
    from ._Lib.py310.PIL import Image, ImageDraw, ImageFilter

import bmesh
import math
from bpy.types import Operator,Panel,Menu
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, FloatProperty, IntProperty, EnumProperty,FloatVectorProperty
import bmesh

from mathutils import Vector, Matrix,Euler
from bpy_extras.io_utils import ExportHelper, ImportHelper

def reg_props():
    return


def ureg_props():
    return


class OP_select_inside_face_loop(bpy.types.Operator):
    bl_idname = "ho.select_inside_face_loop"
    bl_label = "填充选择"
    bl_options = {'REGISTER', 'UNDO'}

    event: bpy.types.Event
    location: tuple[int, int]

    @classmethod
    def poll(cls, context):
        # 确保操作在网格对象的编辑模式下执行
        return context.active_object and context.active_object.type == 'MESH' and context.mode == 'EDIT_MESH'

    def execute(self, context):
        ops = bpy.ops
        mesh = ops.mesh

        mesh.hide()
        ops.view3d.select(location=self.location)
        mesh.select_linked()
        mesh.reveal()
        return {'FINISHED'}

    def invoke(self, context, event):
        self.event = event
        self.location = (event.mouse_region_x, event.mouse_region_y)
        return self.execute(context)

class OP_RestartBlender(Operator):
    bl_idname = "ho.restart_blender"
    bl_label = "快速重启"
    bl_description = "不保存重启"
    bl_options = {'REGISTER'}

    def execute(self, context):
        py = os.path.join(os.path.dirname(__file__), "console_toggle.py")
        filepath = bpy.data.filepath
        if (filepath != ""):
            subprocess.Popen([sys.argv[0], filepath, '-P', py])
        else:
            subprocess.Popen([sys.argv[0], '-P', py])
        bpy.ops.wm.quit_blender()
        return {'FINISHED'}

class OP_sync_render_visibility(Operator):
    bl_idname = "ho.sync_render_visibility"
    bl_label = "同步渲染/视图层显示"
    bl_description = "将所有启用物体的渲染与视图层显示同步"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        view_layer = context.view_layer

        # 遍历视图层中的所有集合
        for collection in view_layer.layer_collection.children:
            collection: bpy.types.LayerCollection
            if not collection.exclude:  # 只处理没有被排除的集合（本属性数据api与大纲绘制值相反，原因是指代不同
                # 遍历集合中的所有物体
                collection.collection.hide_render = collection.hide_viewport
        for obj in context.scene.objects:
            obj.hide_render = obj.hide_get()

        return {'FINISHED'}

class OP_CopyALL_modifiers_to_selected(Operator):
    bl_idname = "ho.copyall_modifiers_to_selected"
    bl_label = "复制全部修改器到所选"
    bl_description = "按顺序复制全部修改器到所选物体"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # 获取活动物体和选中物体列表
        active_obj = context.active_object
        selected_objs = context.selected_objects

        if not active_obj:
            self.report({'ERROR'}, "没有活动物体")
            return {'CANCELLED'}
            
        if len(selected_objs) < 2:
            self.report({'ERROR'}, "需要选择至少两个物体（源物体+目标物体）")
            return {'CANCELLED'}

        modifiers = active_obj.modifiers
        if not modifiers:
            self.report({'INFO'}, "活动物体没有修改器")
            return {'FINISHED'}

        try:
            for m in modifiers:
                bpy.ops.object.modifier_copy_to_selected(
                    modifier=m.name
                )
        except RuntimeError as e:
            self.report({'ERROR'}, f"复制失败: {str(e)}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"成功复制 {len(modifiers)} 个修改器")
        return {'FINISHED'}

class OP_PlaceObjectBottom(Operator):
    bl_idname = "ho.placeobjectbottom"
    bl_label = "选择底面放置"
    bl_description = "使用选择的面作为底面，旋转物体使底面贴合水平面摆放"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj and obj.type == 'MESH' and context.mode == "EDIT_MESH"

    def execute(self, context):
        bpy.ops.object.mode_set(mode='OBJECT')
        obj = context.active_object
        mesh = obj.data
        mat_world = obj.matrix_world

        # 计算选中面法线平均向量
        normal_sum = Vector((0, 0, 0))
        for poly in mesh.polygons:
            if poly.select:
                normal_sum += (mat_world.to_3x3() @ poly.normal)
        if normal_sum.length == 0:
            self.report({'ERROR'}, "未选择任何面")
            return {'CANCELLED'}
        avg_normal = normal_sum.normalized()

        target_normal = Vector((0, 0, -1))  # 目标朝下

        axis = avg_normal.cross(target_normal)
        angle = avg_normal.angle(target_normal)

        if axis.length < 1e-6:
            # 平行或反向
            if avg_normal.dot(target_normal) < 0:
                # 180度旋转，任选垂直轴
                axis = Vector((1, 0, 0))
                angle = math.pi
            else:
                axis = Vector((0, 0, 1))
                angle = 0
        else:
            axis.normalize()

        # 转换旋转到物体本地坐标系
        local_axis = obj.matrix_world.to_3x3().inverted() @ axis
        # 叠加到物体的欧拉旋转（先确保是欧拉旋转模式）
        if obj.rotation_mode != 'XYZ':
            obj.rotation_mode = 'XYZ'

        # 通过轴角转换为欧拉角增量
        delta_rot = Euler(local_axis * angle, 'XYZ')

        # 叠加旋转（通过矩阵乘法）
        rot_mat = obj.rotation_euler.to_matrix().to_4x4()
        delta_mat = delta_rot.to_matrix().to_4x4()
        new_rot_mat = delta_mat @ rot_mat
        obj.rotation_euler = new_rot_mat.to_euler('XYZ')

        # 刷新依赖，更新变换
        context.view_layer.update()

        # 重新计算选中面旋转后顶点的最低点Z
        new_verts_z = []
        for poly in mesh.polygons:
            if poly.select:
                for idx in poly.vertices:
                    v_world = obj.matrix_world @ mesh.vertices[idx].co
                    new_verts_z.append(v_world.z)

        if not new_verts_z:
            self.report({'ERROR'}, "旋转后无法计算高度")
            return {'CANCELLED'}

        min_z = min(new_verts_z)
        obj.location.z -= min_z

        return {'FINISHED'}

class OP_AlignViewToAvgNormal(Operator):
    bl_idname = "ho.align_to_avg_normal"
    bl_label = "视图对准面"
    bl_description = "根据当前选中面的平均法向，将视图对准法向的负方向"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # 只能在 3D 视图且编辑网格模式下启用
        return (context.area.type == 'VIEW_3D' and
                context.object is not None and
                context.object.type == 'MESH' and
                context.mode == 'EDIT_MESH')

    def execute(self, context):
        obj = context.object
        mesh = obj.data

        # 切换到 OBJECT 模式以便读取世界坐标下的法线
        bpy.ops.object.mode_set(mode='OBJECT')
        mat_world = obj.matrix_world

        # 计算选中面法线的世界空间平均向量
        normal_sum = Vector((0.0, 0.0, 0.0))
        for poly in mesh.polygons:
            if poly.select:
                normal_sum += mat_world.to_3x3() @ poly.normal

        if normal_sum.length == 0.0:
            self.report({'ERROR'}, "未选择任何面")
            bpy.ops.object.mode_set(mode='EDIT')
            return {'CANCELLED'}

        avg_normal = normal_sum.normalized()
        # 我们希望视图沿 avg_normal 的反方向（法向朝向视点）
        view_dir = -avg_normal

        # 获取 3D 视图的 Region3D，设置为正交并对准法向
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                region_3d = area.spaces.active.region_3d
                # # 切换到正交视图
                # region_3d.view_perspective = 'ORTHO'
                # 计算旋转四元数：将本地 -Z 轴（视图朝向）对齐到 view_dir
                rot_quat = view_dir.to_track_quat('-Z', 'Y')
                region_3d.view_rotation = rot_quat
                # 可选：调整缩放或距离，以便更好地查看
                # region_3d.view_distance = max(mesh.dimensions) * 2.0
                break

        # 切回编辑模式
        bpy.ops.object.mode_set(mode='EDIT')

        return {'FINISHED'}

class OP_BooleanUnionReconstruction(Operator):
    bl_idname = "ho.boolean_union_reconstruction"
    bl_label = "布尔并集重构"
    bl_description = "使用布尔并集，消除网格内的内部交叉区域，保留其他区域的布线"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'MESH'
    def execute(self, context):
        obj = context.object

        # 创建一个空的 mesh 对象作为布尔对象
        mesh_data = bpy.data.meshes.new(name="EmptyMesh")
        bool_obj = bpy.data.objects.new("BooleanUnionHelper", mesh_data)
        context.collection.objects.link(bool_obj)

        # 设置布尔修改器
        bool_mod = obj.modifiers.new(name="Boolean_Union_Reconstruct", type='BOOLEAN')
        bool_mod.operation = 'UNION'
        bool_mod.solver = 'EXACT'  # 使用准确模式
        bool_mod.use_self = True   # 启用自身交集
        bool_mod.object = bool_obj

        # 切换到对象模式以应用修改器
        bpy.ops.object.mode_set(mode='OBJECT')

        # 应用所有 viewport 中显示的修改器
        for mod in [m for m in obj.modifiers if m.show_viewport]:
            try:
                bpy.ops.object.modifier_apply(modifier=mod.name)
            except:
                self.report({'WARNING'}, f"无法应用修改器: {mod.name}")

        # 删除临时对象
        bpy.data.objects.remove(bool_obj, do_unlink=True)
        return {'FINISHED'}

class OP_CustomSplitNormals_Export(Operator, ExportHelper):
    bl_idname = "ho.custom_splitnormal_export"
    bl_label = "导出自定义拆边法向为文件"
    bl_description = "如果没有添加自定义法线则跳过"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'MESH'

    def execute(self, context):
        obj = context.object
        mesh = obj.data

        if not mesh.has_custom_normals:
            self.report({'WARNING'}, "当前网格没有自定义法线")
            return {'CANCELLED'}

        # 确保在对象模式，否则 loop.normal 访问不正常
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # 提取 loop normals
        normals = [list(loop.normal) for loop in mesh.loops]

        # 保存为 JSON
        import json
        try:
            with open(self.filepath, 'w') as f:
                json.dump(normals, f)
        except Exception as e:
            self.report({'ERROR'}, f"导出失败: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"已导出 {len(normals)} 个自定义法线")
        return {'FINISHED'}

class OP_CustomSplitNormals_Import(Operator, ImportHelper):
    bl_idname = "ho.custom_splitnormal_import"
    bl_label = "导入自定义拆边法向文件"
    bl_description = "覆盖当前的自定义法向"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'MESH'

    def execute(self, context):
        obj = context.object
        mesh = obj.data

        try:
            with open(self.filepath, 'r') as f:
                normal_data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"读取文件失败: {e}")
            return {'CANCELLED'}

        if len(normal_data) != len(mesh.loops):
            self.report({'ERROR'}, f"法线数量不匹配 ({len(normal_data)} vs {len(mesh.loops)})")
            return {'CANCELLED'}

        # 转换为 Vector 列表
        from mathutils import Vector
        split_normals = [Vector(n).normalized() for n in normal_data]

        # mesh.use_auto_smooth = True
        mesh.normals_split_custom_set(split_normals)
        self.report({'INFO'}, f"成功导入并应用 {len(split_normals)} 个法线")
        return {'FINISHED'}


class OP_Replace_MeshDataBlock2selectedObj(Operator):
    bl_idname = "ho.replace"
    bl_label = "复制活动物体网格数据到所选物体"
    bl_description = "会使选择物体全部关联到活动物体"
    bl_options = {'REGISTER', 'UNDO'}

    confirm: bpy.props.BoolProperty(default=False) # type: ignore

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'MESH'

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_confirm(self, event)

    def execute(self, context):
        active_obj = context.object
        mesh = active_obj.data

        for obj in context.selected_objects:
            if obj != active_obj and obj.type == 'MESH':
                obj.data = mesh

        self.report({'INFO'}, "已将网格数据复制到选中物体")
        return {'FINISHED'}


def get_first_image_from_material(obj):
    if not obj.data.materials:
        return None
    mat = obj.data.materials[0]
    if not mat or not mat.use_nodes:
        return None
    for n in mat.node_tree.nodes:
        if n.type == 'TEX_IMAGE' and n.image:
            return n.image
    return None

class OP_MeshToImageEmpty(Operator):
    bl_idname = "ho.mesh_to_image_empty"
    bl_label = "面片转参考图"
    bl_description = "逆向操作为bl自带的转化"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "请选择 Mesh")
            return {'CANCELLED'}

        image = get_first_image_from_material(obj)
        if not image:
            self.report({'ERROR'}, "未找到图片材质")
            return {'CANCELLED'}

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        faces = [f for f in bm.faces if f.select]

        if len(faces) != 1 or len(faces[0].verts) != 4:
            self.report({'ERROR'}, "请选择一个四边面")
            bm.free()
            return {'CANCELLED'}

        f = faces[0]
        verts = [obj.matrix_world @ v.co for v in f.verts]

        # 计算面片两条相邻边长度
        e1 = verts[1] - verts[0]
        e2 = verts[2] - verts[1]

        width  = e1.length
        height = e2.length

        # 构建局部坐标系
        x_axis = e1.normalized()
        z_axis = (obj.matrix_world.to_3x3() @ f.normal).normalized()
        y_axis = z_axis.cross(x_axis)
        rot = Matrix((x_axis, y_axis, z_axis)).transposed().to_euler()
        center = sum(verts, Vector()) / 4.0

        # 创建 Image Empty
        empty = bpy.data.objects.new(f"REF_{image.name}", None)
        empty.empty_display_type = 'IMAGE'
        empty.data = image

        # -------------------------
        # 修正缩放逻辑：等比缩放
        # -------------------------
        img_w, img_h = image.size
        aspect = img_w / img_h if img_h else 1.0

        # 使用面片高度为基准，Image Empty 会根据图片比例自动撑开宽度
        empty.empty_display_size = height
        empty.scale = (1, 1, 1)  # 关键：等比缩放

        empty.location = center
        empty.rotation_euler = rot

        context.collection.objects.link(empty)
        context.view_layer.objects.active = empty

        bm.free()
        # -------------------------
        # 删除原面片
        # -------------------------
        bpy.data.objects.remove(obj, do_unlink=True)
        
        return {'FINISHED'}


def draw_in_OUTLINER_MT_context_menu(self, context: bpy.types.Context):
    """大纲视图右键菜单"""
    layout: bpy.types.UILayout = self.layout
    layout.operator(OP_sync_render_visibility.bl_idname,
                    icon="RESTRICT_RENDER_OFF")
def draw_in_DATA_PT_modifiers(self,context: bpy.types.Context):
    """修改器顶上"""
    layout: bpy.types.UILayout = self.layout
    layout.use_property_decorate = False  # 禁用关键帧动画

    obj = context.object

    if not obj:
        return  # 未选物体不显示
    if not obj.modifiers:
        return  # 物体没有修改器不显示
    if obj.type != "MESH":
        return  # 不是网格的不显示

    row = layout.row(align=True)
    row.operator(OP_CopyALL_modifiers_to_selected.bl_idname,
                 text="复制全部到所选") 
def draw_in_DATA_PT_customdata(self,context: bpy.types.Context):
    """几何数据属性下"""
    layout: bpy.types.UILayout = self.layout
    row = layout.row(align=True)
    row.operator(OP_CustomSplitNormals_Export.bl_idname)
    row.operator(OP_CustomSplitNormals_Import.bl_idname)

def draw_in_VIEW3D_MT_object_convert(self,context: bpy.types.Context):
    """物体转换菜单下"""
    layout: bpy.types.UILayout = self.layout
    row = layout.row(align=True)
    row.operator(OP_MeshToImageEmpty.bl_idname)


class VIEW3D_MT_edit_mesh_hotools(Menu):
    """编辑模式右键时的菜单追加"""
    bl_label = "Hotools"

    def draw(self, context):
        layout = self.layout
        layout.operator(OP_PlaceObjectBottom.bl_idname, icon='TRIA_DOWN')
        layout.operator(OP_AlignViewToAvgNormal.bl_idname,icon="RESTRICT_RENDER_OFF")

def draw_in_VIEW3D_MT_edit_mesh_context_menu(self, context):
    """编辑模式右键时的菜单追加"""
    self.layout.menu("VIEW3D_MT_edit_mesh_hotools") 

def draw_in_DATA_PT_remesh(self, context):
    """重构网格面板添加"""
    layout: bpy.types.UILayout = self.layout
    layout.operator(OP_BooleanUnionReconstruction.bl_idname)

def draw_in_DATA_PT_context_mesh(self, context):
    """数据顶"""
    layout: bpy.types.UILayout = self.layout
    layout.operator(OP_Replace_MeshDataBlock2selectedObj.bl_idname)


def draw_in_TOPBAR_MT_editor_menus(self, context):
    # TODO 不知道要不要加,顶部的快速重启bl按键
    layout: bpy.types.UILayout = self.layout
    layout.alert = True
    layout.operator(OP_RestartBlender.bl_idname, icon="QUIT", text="")
    layout.alert = False


cls = [OP_select_inside_face_loop, OP_RestartBlender,
       OP_sync_render_visibility,
       OP_CopyALL_modifiers_to_selected,OP_PlaceObjectBottom,
       OP_BooleanUnionReconstruction,
       VIEW3D_MT_edit_mesh_hotools,
       OP_AlignViewToAvgNormal,
       OP_CustomSplitNormals_Import,OP_CustomSplitNormals_Export,
       OP_Replace_MeshDataBlock2selectedObj,
       OP_MeshToImageEmpty,
       ]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    bpy.types.OUTLINER_MT_context_menu.append(draw_in_OUTLINER_MT_context_menu)
    bpy.types.DATA_PT_modifiers.append(draw_in_DATA_PT_modifiers)
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.prepend(draw_in_VIEW3D_MT_edit_mesh_context_menu)
    bpy.types.DATA_PT_remesh.append(draw_in_DATA_PT_remesh)
    bpy.types.DATA_PT_customdata.append(draw_in_DATA_PT_customdata)
    bpy.types.DATA_PT_context_mesh.append(draw_in_DATA_PT_context_mesh)
    bpy.types.VIEW3D_MT_object_convert.append(draw_in_VIEW3D_MT_object_convert)
    # bpy.types.TOPBAR_MT_editor_menus.append(draw_in_TOPBAR_MT_editor_menus)

    # 默认绑定 Ctrl + Shift + 右键
    # 此设置可以被preference保存，不用担心注册阶段写死
    wm = bpy.context.window_manager
    km = wm.keyconfigs.addon.keymaps.new(
        name="Window", space_type="EMPTY", region_type="WINDOW")
    kmi = km.keymap_items.new(OP_select_inside_face_loop.bl_idname,
                              type='RIGHTMOUSE', value='PRESS', ctrl=True, shift=True)
    kmi.active = True

    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    bpy.types.OUTLINER_MT_context_menu.remove(draw_in_OUTLINER_MT_context_menu)
    bpy.types.DATA_PT_modifiers.remove(draw_in_DATA_PT_modifiers)
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(draw_in_VIEW3D_MT_edit_mesh_context_menu)
    bpy.types.DATA_PT_remesh.remove(draw_in_DATA_PT_remesh)
    bpy.types.DATA_PT_customdata.remove(draw_in_DATA_PT_customdata)
    bpy.types.DATA_PT_context_mesh.remove(draw_in_DATA_PT_context_mesh)

    # bpy.types.TOPBAR_MT_editor_menus.remove(draw_in_TOPBAR_MT_editor_menus)

    ureg_props()
