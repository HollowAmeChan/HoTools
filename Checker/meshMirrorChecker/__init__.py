import bpy
from bpy.types import Panel,Operator,UIList,PropertyGroup
from bpy.props import StringProperty,IntProperty,CollectionProperty,BoolProperty,FloatProperty

from . import fixOperator

def reg_props():
    enum_items = [
        ('X', "X", "-x~+x"),
        ('Y', "Y", "-y~+y"),
        ('Z', "Z", "-z~+z"),
    ]
    bpy.types.Scene.ho_MirrorCheckerAxis = bpy.props.EnumProperty(
        name="ho操作对称轴", items=enum_items)
    
    bpy.types.Scene.ho_mirrorchecker_base_vertex_index = IntProperty(description="需要进行对称的顶点")
    bpy.types.Scene.ho_mirrorchecker_target_vertex_index = IntProperty(description="参考的顶点")

    bpy.types.Scene.ho_mirrorchecker_isonlyselect = BoolProperty(description="仅检查选中",default=True)
    bpy.types.Scene.ho_mirrorchecker_checkuv_tolerance = FloatProperty(description="UV容差,推荐低于1e-6",default=0.00000001,max=0.001,min=0)
    bpy.types.Scene.ho_mirrorchecker_topu_ischeck = BoolProperty(description="检查拓补,计算较快但会误判一些网格",default=False)
    bpy.types.Scene.ho_mirrorchecker_mirroruv_ischeck = BoolProperty(description="检查镜像UV",default=True)
    bpy.types.Scene.ho_mirrorchecker_stackuv_ischeck = BoolProperty(description="检查重叠UV",default=False)
    bpy.types.Scene.ho_mirrorchecker_swapsign = BoolProperty(description="翻转正负轴",default=False)
    return


def ureg_props():
    del bpy.types.Scene.ho_MirrorCheckerAxis
    del bpy.types.Scene.ho_mirrorchecker_base_vertex_index
    del bpy.types.Scene.ho_mirrorchecker_target_vertex_index
    return


def drawMeshMirrorCheckerPanel(layout:bpy.types.UILayout,context:bpy.types.Context):
    scene = context.scene

    row = layout.row(align=True)
    row.label(text="视图显示")
    space = context.space_data
    row.label(text="",icon="MOD_MIRROR")
    row.prop(context.object,"use_mesh_mirror_x",toggle=True)
    row.prop(context.object,"use_mesh_mirror_y",toggle=True)
    row.prop(context.object,"use_mesh_mirror_z",toggle=True)

    if hasattr(space, "overlay"):
        row.prop(space.overlay, "show_text", text="",toggle=True,icon="LINENUMBERS_OFF")
    if hasattr(space, "overlay"):
        row.prop(space.overlay, "show_extra_indices", text="",toggle=True,icon="LINENUMBERS_ON")
 
    layout.label(text="自动修复")
    row = layout.row(align=True)
    row.scale_y = 2.0
    row1 = row.row(align=True)
    row1.scale_x = 0.5
    row1.prop(scene,"ho_MirrorCheckerAxis",text="")
    op = row.operator(fixOperator.OP_Checker_AutoForceVertexMirror.bl_idname,text="自动修复对称",icon="MODIFIER_ON")
    op.isonlyselect = scene.ho_mirrorchecker_isonlyselect
    op.checkuv_tolerance = scene.ho_mirrorchecker_checkuv_tolerance
    op.topu_ischeck = scene.ho_mirrorchecker_topu_ischeck
    op.mirroruv_ischeck = scene.ho_mirrorchecker_mirroruv_ischeck
    op.stackuv_ischeck = scene.ho_mirrorchecker_stackuv_ischeck
    op.swapsign = scene.ho_mirrorchecker_swapsign
    row1 = row.row(align=True)
    row1.scale_x = 1
    row1.prop(scene,"ho_mirrorchecker_swapsign",text="",icon="AREA_SWAP")
    
    row = layout.row(align=True)
    row.prop(scene,"ho_mirrorchecker_isonlyselect",toggle=True,icon_only=True,icon="RESTRICT_SELECT_OFF",text="仅选中")
    row.prop(scene,"ho_mirrorchecker_checkuv_tolerance",text="UV容差")
    row = layout.row(align=True)
    row.prop(scene,"ho_mirrorchecker_topu_ischeck",toggle=True,icon_only=True,icon="MOD_EDGESPLIT",text="检查拓补")
    row.prop(scene,"ho_mirrorchecker_mirroruv_ischeck",toggle=True,icon_only=True,icon="UV_VERTEXSEL",text="检查镜像UV")
    row.prop(scene,"ho_mirrorchecker_stackuv_ischeck",toggle=True,icon_only=True,icon="MOD_MESHDEFORM",text="检查重叠UV")

    layout.label(text="手动修复")
    row = layout.row(align=True)
    row1 = row.row(align=True)
    op = row1.operator(fixOperator.OP_Checker_getActiveVertexIndex.bl_idname,text="",icon="EYEDROPPER")
    op.is_target=False
    row1.prop(scene,"ho_mirrorchecker_base_vertex_index",text="")
    row.operator(fixOperator.OP_Checker_forceVertexMirror.bl_idname,text="",icon="MODIFIER_ON")
    row2 = row.row(align=True)
    row2.prop(scene,"ho_mirrorchecker_target_vertex_index",text="")
    op = row2.operator(fixOperator.OP_Checker_getActiveVertexIndex.bl_idname,text="",icon="EYEDROPPER")
    op.is_target=True
    row.operator(fixOperator.OP_Checker_swapMirrorVertexIndex.bl_idname,text="",icon="AREA_SWAP")

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