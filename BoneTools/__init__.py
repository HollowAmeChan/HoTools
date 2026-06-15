import bpy
from bpy.types import Panel,Menu
from . import boneHumanoid,boneOperators,boneProperty,boneRename,boneSplit,boneDissolve


# region 变量
def reg_props():
    # 功能区开关
    enum_items = [
        ('PANEL_BONE_HUMANOID', "Humanoid", ""),
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
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HoTools"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.label(text="骨骼操作")
        row.prop(context.scene, "ho_BoneToolsPanel_Mod", expand=True,)
        if context.scene.ho_BoneToolsPanel_Mod == "PANEL_BONE_HUMANOID":
            boneHumanoid.drawBoneHumanoidPanel(self.layout, context)
        if context.scene.ho_BoneToolsPanel_Mod == "PANEL_BONE_OPERATORS":
            boneOperators.drawBoneOperatorsPanel(self.layout, context)
        if context.scene.ho_BoneToolsPanel_Mod == "PANEL_BONE_RENAME":
            boneRename.drawBoneRenamePanel(self.layout, context)


class VIEW3D_MT_armature_context_menu_hotools(Menu):
    """骨骼编辑模式下的右键菜单"""
    bl_label = "Hotools"

    def draw(self, context):
        layout = self.layout
        layout.operator(boneOperators.OP_RelaxBoneChain.bl_idname)
        layout.operator(boneOperators.OP_AddEndBone.bl_idname)
        layout.operator(boneOperators.OP_ForceClearBoneRotation.bl_idname)
        layout.operator(boneOperators.OP_Fix_EmptyRotate_Bone.bl_idname)

def drawIn_VIEW3D_MT_armature_context_menu(self, context):
    self.layout.menu("VIEW3D_MT_armature_context_menu_hotools") 

class VIEW3D_MT_pose_context_menu_hotools(Menu):
    """骨骼姿态模式下的右键菜单"""
    bl_label = "Hotools"

    def draw(self, context):
        layout = self.layout
        layout.operator(boneOperators.OP_SelectBoneBy_by_KeepRotation.bl_idname)
        layout.operator(boneOperators.OP_SelectBone_by_Nochild.bl_idname)
        layout.operator(boneOperators.OP_SelectBone_by_endBone.bl_idname)
        if context.active_object and context.active_object.type == 'ARMATURE':
            layout.operator(boneOperators.OP_ApplyRestPose.bl_idname)
        layout.operator(boneOperators.OP_FastCreatPoseAsset.bl_idname)

def drawIn_VIEW3D_MT_pose_context_menu(self, context):
    self.layout.menu("VIEW3D_MT_pose_context_menu_hotools") 



cls = [
    PL_BoneTools,
    VIEW3D_MT_armature_context_menu_hotools,
    VIEW3D_MT_pose_context_menu_hotools,
    ]


def register():
    boneProperty.register()
    boneOperators.register()
    boneRename.register()
    boneSplit.register()
    boneDissolve.register()
    boneHumanoid.register()

    for i in cls:
        bpy.utils.register_class(i)

    bpy.types.VIEW3D_MT_armature_context_menu.append(drawIn_VIEW3D_MT_armature_context_menu)
    bpy.types.VIEW3D_MT_pose_context_menu.append(drawIn_VIEW3D_MT_pose_context_menu)
    reg_props()


def unregister():
    boneOperators.unregister()
    boneRename.unregister()
    boneSplit.unregister()
    boneDissolve.unregister()
    boneHumanoid.unregister()
    boneProperty.unregister()

    for i in cls:
        bpy.utils.unregister_class(i)

    bpy.types.VIEW3D_MT_armature_context_menu.remove(drawIn_VIEW3D_MT_armature_context_menu)
    bpy.types.VIEW3D_MT_pose_context_menu.remove(drawIn_VIEW3D_MT_pose_context_menu)
    ureg_props()
