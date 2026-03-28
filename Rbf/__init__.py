import bpy
import bmesh
from bpy.types import Panel

from  . import transfer

def reg_props():
    # 功能区开关
    enum_items = [
        ('PANEL_RBF_TRANSFER', "传递", ""),
    ]
    bpy.types.Scene.ho_RbfPanel_Mod = bpy.props.EnumProperty(
        name="RbfPanelMod", items=enum_items)
    return

def ureg_props():
    del bpy.types.Scene.ho_RbfPanel_Mod
    return

class PL_Rbf(Panel):
    bl_idname = "VIEW_PT_Hollow_Rbf"
    bl_label = "Rbf"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HoTools"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.label(text="RBF")
        row.prop(context.scene, "ho_RbfPanel_Mod", expand=True,)
        if context.scene.ho_RbfPanel_Mod == "PANEL_RBF_TRANSFER":
            transfer.drawRbfTransferPanel(self.layout, context)
        return



cls = [PL_Rbf]

def register():
    transfer.register()
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    transfer.unregister()
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
