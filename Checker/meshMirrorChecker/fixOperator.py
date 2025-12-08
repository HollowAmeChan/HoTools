import bpy
from bpy.types import Operator,Panel,Menu
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, FloatProperty, IntProperty, EnumProperty,FloatVectorProperty
import bmesh


def reg_props():

    return


def ureg_props():
    return

class OP_Checker_getActiveVertexIndex(Operator):
    bl_idname = "ho.checker_get_activevertex_index"
    bl_label = "选择点"
    bl_description = "填入活动顶点index"
    bl_options = {'REGISTER', 'UNDO'}

    is_target:BoolProperty(default=False) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        bm = bmesh.from_edit_mesh(obj.data)
        if self.is_target:
            context.scene.ho_mirrorchecker_target_vertex_index = bm.select_history.active.index
        else:
            context.scene.ho_mirrorchecker_base_vertex_index = bm.select_history.active.index
        return {'FINISHED'}

cls = [OP_Checker_getActiveVertexIndex
       ]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()