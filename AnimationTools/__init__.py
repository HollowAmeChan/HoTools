import bpy
from bpy.types import Panel
from . import rigidBodyPhysics,actionProcess


# region 变量
def reg_props():
    # 功能区开关
    enum_items = [
        ('PANEL_ANIMATIONTOOLS_ACTIONPROCESS', "动画处理", ""),
        ('PANEL_ANIMATIONTOOLS_RIGIDBODYPHYSICS', "刚体物理", ""),
    ]
    bpy.types.Scene.ho_AnimationToolsPanel_Mod = bpy.props.EnumProperty(
        name="AnimationToolsPanelMod", items=enum_items)
    return


def ureg_props():
    return
# endregion


# TODO
class PL_AnimationTools(Panel):
    bl_idname = "VIEW_PT_Hollow_AnimationTools"
    bl_label = "动画工具"
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
        row.label(text="动画工具")
        row.prop(context.scene, "ho_AnimationToolsPanel_Mod", expand=True,)
        layout.separator()
        if context.scene.ho_AnimationToolsPanel_Mod == "PANEL_ANIMATIONTOOLS_ACTIONPROCESS":
            actionProcess.drawActionProcessPanel(self.layout, context)
        if context.scene.ho_AnimationToolsPanel_Mod == "PANEL_ANIMATIONTOOLS_RIGIDBODYPHYSICS":
            rigidBodyPhysics.drawRigidBodyPhysicsPanel(self.layout, context)



        


cls = [PL_AnimationTools]


def register():
    rigidBodyPhysics.register()
    actionProcess.register()

    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    rigidBodyPhysics.unregister()
    actionProcess.unregister()

    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
