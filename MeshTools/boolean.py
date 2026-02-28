import bpy
from bpy.types import Operator

def reg_props():
    return

def ureg_props():
    return

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


def draw_in_DATA_PT_remesh(self, context):
    """重构网格面板添加"""
    layout: bpy.types.UILayout = self.layout
    layout.operator(OP_BooleanUnionReconstruction.bl_idname)
    


cls = [OP_BooleanUnionReconstruction]

def register():
    for i in cls:
        bpy.utils.register_class(i)

    bpy.types.DATA_PT_remesh.append(draw_in_DATA_PT_remesh)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)

    bpy.types.DATA_PT_remesh.remove(draw_in_DATA_PT_remesh)
    ureg_props()
