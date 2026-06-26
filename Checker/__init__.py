import bpy
from bpy.types import Panel

from . import meshMirrorChecker, objectChecker, overlayPreview


def reg_props():
    enum_items = [
        ("PANEL_CHECKER_MIRRORCHECKER", "网格镜像", ""),
        ("PANEL_CHECKER_OBJECTCHECKER", "物体检查", ""),
    ]
    bpy.types.Scene.ho_CheckerToolsPanel_Mod = bpy.props.EnumProperty(
        name="CheckerToolsPanelMod",
        items=enum_items,
    )


def ureg_props():
    if hasattr(bpy.types.Scene, "ho_CheckerToolsPanel_Mod"):
        del bpy.types.Scene.ho_CheckerToolsPanel_Mod


class PL_ObjectChecker(Panel):
    bl_idname = "VIEW_PT_Hollow_ObjectChecker"
    bl_label = "检查"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HoTools"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        row = layout.row(align=True)
        row.label(text="检查")
        row.prop(scene, "ho_CheckerToolsPanel_Mod", expand=True)

        if scene.ho_CheckerToolsPanel_Mod == "PANEL_CHECKER_MIRRORCHECKER":
            meshMirrorChecker.drawMeshMirrorCheckerPanel(layout, context)
        elif scene.ho_CheckerToolsPanel_Mod == "PANEL_CHECKER_OBJECTCHECKER":
            objectChecker.drawObjectCheckerPanel(layout, context)


cls = [PL_ObjectChecker]


def register():
    objectChecker.register()
    meshMirrorChecker.register()
    overlayPreview.register()
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    overlayPreview.unregister()
    meshMirrorChecker.unregister()
    objectChecker.unregister()
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
