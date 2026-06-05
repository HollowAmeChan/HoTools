import bpy
from bpy.types import Operator


def reg_props():
    return


def ureg_props():
    return


class OT_UVTools_RTBake(Operator):
    """RT烘焙入口，具体功能后续接入"""
    bl_idname = "ho.uvtools_rt_bake"
    bl_label = "RT烘焙"
    bl_description = "RT烘焙入口"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        self.report({'WARNING'}, "RT烘焙功能待实现")
        return {'CANCELLED'}


def drawRTBakePanel(layout: bpy.types.UILayout, context):
    box = layout.box()

    col = box.column(align=True)
    row = col.row(align=True)
    row.operator(OT_UVTools_RTBake.bl_idname, text="RT烘焙", icon="RENDER_RESULT")
    return


cls = [
    OT_UVTools_RTBake,
]


def register():
    for i in cls:
        bpy.utils.register_class(i)

    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)

    ureg_props()
