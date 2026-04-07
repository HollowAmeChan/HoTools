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
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HoTools"
    bl_options = {'DEFAULT_CLOSED'}


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
def draw_in_DATA_PT_shape_keys(self, context: bpy.types.Context):
    layout: bpy.types.UILayout = self.layout
    layout.use_property_decorate = False  # 禁用关键帧动画


    row = layout.row(align=True)
    row1 = row.row(align=True)
    row1.alignment = 'LEFT'
    row1.prop(context.scene,"hoShapekeyTools_open_menu",text="",icon="EVENT_H",toggle=True)
    row1.prop(context.scene,"hoShapekeyTools_enable_multi",text="",icon="OUTLINER_COLLECTION",toggle=True)
    
    row2 = row.row(align=True)
    row2.alignment= 'RIGHT'
    row2.prop(context.scene,"hoShapekeyTools_control_shape_key_listener",text="",toggle=True,icon="UV_SYNC_SELECT")


    if context.scene.hoShapekeyTools_open_menu:
        operators._draw_sk_operators(context=context,layout=layout)
    if context.scene.hoShapekeyTools_enable_multi:
        multiObjectFlow._draw_sk_multiobj(context=context,layout=layout)




def register():
    transfer.register()
    operators.register()
    manager.register()
    multiObjectFlow.register()

    for i in cls:
        bpy.utils.register_class(i)
    reg_props()
    bpy.types.DATA_PT_shape_keys.append(draw_in_DATA_PT_shape_keys)


def unregister():
    transfer.unregister()
    operators.unregister()
    manager.unregister()
    multiObjectFlow.unregister()

    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
    bpy.types.DATA_PT_shape_keys.remove(draw_in_DATA_PT_shape_keys)
