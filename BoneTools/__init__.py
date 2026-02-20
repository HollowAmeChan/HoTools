import bpy
from bpy.types import Panel
from . import boneRename,boneOperators,boneSplit,boneDissolve


# region 变量
def reg_props():
    # 功能区开关
    enum_items = [
        ('PANEL_BONE_OPERATORS', "操作", ""),
        ('PANEL_BONE_RENAME', "命名", ""),
    ]
    bpy.types.Scene.ho_BoneToolsPanel_Mod = bpy.props.EnumProperty(
        name="BoneToolsPanelMod", items=enum_items)
    return


def ureg_props():
    del bpy.types.Scene.ho_BoneToolsPanel_Mod
    return
# endregion


class PL_BoneTools(Panel):
    bl_idname = "VIEW_PT_Hollow_BoneTools"
    bl_label = "骨骼工具"
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
        row.label(text="骨骼操作")
        row.prop(context.scene, "ho_BoneToolsPanel_Mod", expand=True,)
        if context.scene.ho_BoneToolsPanel_Mod == "PANEL_BONE_OPERATORS":
            boneOperators.drawBoneOperatorsPanel(self.layout, context)
        if context.scene.ho_BoneToolsPanel_Mod == "PANEL_BONE_RENAME":
            boneRename.drawBoneRenamePanel(self.layout, context)


cls = [PL_BoneTools]


def register():
    boneOperators.register()
    boneRename.register()
    boneSplit.register()
    boneDissolve.register()

    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    boneOperators.unregister()
    boneRename.unregister()
    boneSplit.unregister()
    boneDissolve.unregister()


    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
