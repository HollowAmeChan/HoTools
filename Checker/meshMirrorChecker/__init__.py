import bpy
from bpy.types import Panel,Operator,UIList,PropertyGroup
from bpy.props import StringProperty,IntProperty,CollectionProperty

from . import fixOperator

def reg_props():
    bpy.types.Scene.ho_mirrorchecker_base_vertex_index = IntProperty(description="需要进行对称的顶点")
    bpy.types.Scene.ho_mirrorchecker_target_vertex_index = IntProperty(description="参考的顶点")
    return


def ureg_props():
    del bpy.types.Scene.ho_mirrorchecker_base_vertex_index
    del bpy.types.Scene.ho_mirrorchecker_target_vertex_index
    return


def drawMeshMirrorCheckerPanel(layout:bpy.types.UILayout,context:bpy.types.Context):
    scene = context.scene
    row = layout.row(align=True)

    space = context.space_data
    if hasattr(space, "overlay"):
        row.prop(space.overlay, "show_text", text="显示文本",toggle=True,icon="LINENUMBERS_OFF")
    if hasattr(space, "overlay"):
        row.prop(space.overlay, "show_extra_indices", text="显示编号",toggle=True,icon="LINENUMBERS_ON")


    row = layout.row(align=True)
    row1 = row.row(align=True)
    op = row1.operator(fixOperator.OP_Checker_getActiveVertexIndex.bl_idname,text="",icon="EYEDROPPER")
    op.is_target=False
    row1.prop(scene,"ho_mirrorchecker_base_vertex_index",text="")
    # row.operator()
    row2 = row.row(align=True)
    op = row2.operator(fixOperator.OP_Checker_getActiveVertexIndex.bl_idname,text="",icon="EYEDROPPER")
    op.is_target=True
    row2.prop(scene,"ho_mirrorchecker_target_vertex_index",text="")

    return



cls = [
       ]


def register():
    fixOperator.register()
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    fixOperator.unregister()
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()