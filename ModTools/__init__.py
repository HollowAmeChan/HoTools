import bpy
from bpy.types import Panel

from . import texpacker, weight

def reg_props():
    bpy.types.Scene.ho_ModToolsPanel_Mod = bpy.props.EnumProperty(
        name="ModToolsPanelMod",
        items=[
            ('PANEL_MODTOOLS_TEXPACKER', "贴图打包", ""),
            ('PANEL_MODTOOLS_WEIGHT', "权重", ""),
        ]
    )
    return

def ureg_props():
    del bpy.types.Scene.ho_ModToolsPanel_Mod
    return

class ModTools(Panel):
    bl_idname = "VIEW_PT_Hollow_ModTool"
    bl_label = "Mod工具"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HoTools"
    bl_options = {'DEFAULT_CLOSED'}


    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.label(text="Mod工具")
        row.prop(context.scene, "ho_ModToolsPanel_Mod", expand=True,)
        layout.separator()
        if context.scene.ho_ModToolsPanel_Mod == "PANEL_MODTOOLS_TEXPACKER":
            texpacker.drawTexPackerPanel(self.layout, context)
        if context.scene.ho_ModToolsPanel_Mod == "PANEL_MODTOOLS_WEIGHT":
            weight.drawWeightPanel(self.layout, context)



cls = [ModTools]

def register():
    texpacker.register()
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in reversed(cls):
        bpy.utils.unregister_class(i)
    ureg_props()
    texpacker.unregister()
