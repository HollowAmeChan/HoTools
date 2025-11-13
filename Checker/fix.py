import bpy
from bpy.types import Operator,Panel,Menu
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, FloatProperty, IntProperty, EnumProperty,FloatVectorProperty
import bmesh
from bpy_extras.io_utils import ExportHelper, ImportHelper

# region 变量
def reg_props():
    return


def ureg_props():
    return
# endregion

class OP_Checker_selectFace(Operator):
    bl_idname = "ho.checker_select_face"
    bl_label = "选中面"
    bl_options = {'REGISTER', 'UNDO'}

    input: bpy.props.StringProperty(default="") # type: ignore

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "请选中一个网格物体")
            return {'CANCELLED'}

        mesh = obj.data
        # 进入编辑模式才可以修改选中状态
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='FACE')

        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()  # 刷新索引表

        for f in bm.faces:
            f.select = False
        for idx in eval(self.input):
            bm.faces[idx].select = True

        bmesh.update_edit_mesh(mesh)
        
        return {'FINISHED'}

class OP_Checker_selectVerts(Operator):
    bl_idname = "ho.checker_select_verts"
    bl_label = "选中点"
    bl_options = {'REGISTER', 'UNDO'}

    input: bpy.props.StringProperty(default="")  # type: ignore # 输入顶点索引列表，例如 "[0, 5, 12]"


    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "请选中一个网格物体")
            return {'CANCELLED'}

        mesh = obj.data
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='VERT')
        bm = bmesh.from_edit_mesh(mesh)
        bm.verts.ensure_lookup_table()  # 刷新顶点索引表

        for v in bm.verts:
            v.select = False
        try:
            for idx in eval(self.input):
                bm.verts[idx].select = True
        except Exception as e:
            self.report({'ERROR'}, f"输入错误: {e}")
            return {'CANCELLED'}

        bmesh.update_edit_mesh(mesh)
        return {'FINISHED'}

class OP_Checker_selectEdges(Operator):
    bl_idname = "ho.checker_select_edges"
    bl_label = "选中边"
    bl_options = {'REGISTER', 'UNDO'}

    input: bpy.props.StringProperty(default="")  # type: ignore # 输入边索引列表，例如 "[0, 5, 12]"

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "请选中一个网格物体")
            return {'CANCELLED'}

        mesh = obj.data
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='EDGE')
        bm = bmesh.from_edit_mesh(mesh)
        bm.edges.ensure_lookup_table()  # 刷新边索引表

        for e in bm.edges:
            e.select = False
        try:
            for idx in eval(self.input):
                bm.edges[idx].select = True
        except Exception as e:
            self.report({'ERROR'}, f"输入错误: {e}")
            return {'CANCELLED'}

        bmesh.update_edit_mesh(mesh)
        return {'FINISHED'}

class OP_Checker_selectBones(Operator):
    bl_idname = "ho.checker_select_bones"
    bl_label = "选中骨骼"
    bl_options = {'REGISTER', 'UNDO'}

    input: bpy.props.StringProperty(default="")  # type: ignore # 例如 '["Bone", "Bone.001"]'

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请选中一个骨骼对象")
            return {'CANCELLED'}

        # 进入POSE模式
        bpy.ops.object.mode_set(mode='POSE')

        # 显示所有骨骼组（Blender 4.0后，已弃用bone groups，但保留此逻辑用于自定义筛选）
        for bone in obj.data.bones:
            bone.hide = False
        for pbone in obj.pose.bones:
            pbone.bone.hide = False

        # 取消所有骨骼的选择
        for pbone in obj.pose.bones:
            pbone.bone.select = False

        try:
            bone_names = eval(self.input)
            for name in bone_names:
                if name in obj.pose.bones:
                    pbone = obj.pose.bones[name]
                    pbone.bone.select = True
                    obj.data.bones.active = pbone.bone  # 设置活动骨骼
                else:
                    self.report({'WARNING'}, f"未找到骨骼: {name}")
        except Exception as e:
            self.report({'ERROR'}, f"输入错误: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}


cls = [OP_Checker_selectFace,OP_Checker_selectVerts,OP_Checker_selectEdges,OP_Checker_selectBones
       ]


def register():
    for i in cls:
        bpy.utils.register_class(i)

    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    
    ureg_props()
