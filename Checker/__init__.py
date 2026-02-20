import bpy
from bpy.types import Panel

from  . import objectChecker,meshMirrorChecker

def reg_props():
    # 功能区开关
    enum_items = [
        ('PANEL_CHECKER_MIRRORCHECKER', "网格镜像", ""),
        ('PANEL_CHECKER_OBJECTCHECKER', "物体检查", ""),
    ]
    bpy.types.Scene.ho_CheckerToolsPanel_Mod = bpy.props.EnumProperty(
        name="CheckerToolsPanelMod", items=enum_items)
    return

def ureg_props():
    del bpy.types.Scene.ho_CheckerToolsPanel_Mod
    return


class PL_ObjectChecker(Panel):
    bl_idname = "VIEW_PT_Hollow_ObjectChecker"
    bl_label = "检查"
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
        row.label(text="检查")
        row.prop(context.scene, "ho_CheckerToolsPanel_Mod", expand=True,)
        if context.scene.ho_CheckerToolsPanel_Mod == "PANEL_CHECKER_MIRRORCHECKER":
            meshMirrorChecker.drawMeshMirrorCheckerPanel(self.layout, context)
        if context.scene.ho_CheckerToolsPanel_Mod == "PANEL_CHECKER_OBJECTCHECKER":
            objectChecker.drawObjectCheckerPanel(self.layout, context)

        return



cls = [PL_ObjectChecker]



def register():
    objectChecker.register()
    meshMirrorChecker.register()
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    objectChecker.unregister()
    meshMirrorChecker.unregister()
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
