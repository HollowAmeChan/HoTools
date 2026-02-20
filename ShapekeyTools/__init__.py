import bpy
import bmesh
from bpy.types import Panel

from . import operators, transfer, manager,multiObjectFlow


def reg_props():
    # 功能区开关
    enum_items = [
        ('PANEL_SHAPEKEYTOOLS_MANAGER', "管理", ""),
        ('PANEL_SHAPEKEYTOOLS_TRANSFER', "传递", ""),
    ]
    bpy.types.Scene.ho_ShapekeyToolsPanel_Mod = bpy.props.EnumProperty(
        name="ShapekeyToolsPanelMod", items=enum_items)


def ureg_props():
    del bpy.types.Scene.ho_ShapekeyToolsPanel_Mod


# region 面板


class ShapekeyTools(Panel):
    bl_idname = "VIEW_PT_Hollow_ShapekeyTool"
    bl_label = "形态键工具"
    # bl_space_type = "VIEW_3D"
    # bl_region_type = "UI"
    # bl_category = "HoTools"
    # bl_options = {'DEFAULT_CLOSED'}
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_parent_id = "PT_Main_HotoolsMainPanel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.label(text="形态键工具")
        row.prop(context.scene, "ho_ShapekeyToolsPanel_Mod", expand=True,)
        layout.separator()
        if context.scene.ho_ShapekeyToolsPanel_Mod == "PANEL_SHAPEKEYTOOLS_TRANSFER":
            transfer.drawShapekeyTransferPanel(self.layout, context)
        if context.scene.ho_ShapekeyToolsPanel_Mod == "PANEL_SHAPEKEYTOOLS_MANAGER":
            manager.drawShapekeyManagerPanel(self.layout, context)

cls = [ShapekeyTools]
# endregion


def register():
    transfer.register()
    operators.register()
    manager.register()
    multiObjectFlow.register()

    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    transfer.unregister()
    operators.unregister()
    manager.unregister()
    multiObjectFlow.unregister()

    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
