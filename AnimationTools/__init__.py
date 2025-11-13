import bpy
from bpy.types import Panel
from . import rigidBodyPhysics


# region 变量
def reg_props():
    return


def ureg_props():
    return
# endregion


# TODO
class PL_AnimationTools(Panel):
    bl_idname = "VIEW_PT_Hollow_AnimationTools"
    bl_label = "动画工具"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HoTools"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.label(text="刚体物理相关")
        row.operator(
            rigidBodyPhysics.OP_SetViewPortShadingMode.bl_idname, text="刚体预览")

        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(context.scene.rigidbody_world, "enabled", text="刚体世界")
        if context.scene.rigidbody_world.enabled:
            # 使用指向 frame_end 属性的路径来绘制属性
            row.prop(context.scene.rigidbody_world.point_cache,
                     "frame_end", text="End Frame")
        col.operator(
            rigidBodyPhysics.OP_CopyRigidBodySettings.bl_idname, text="复制刚体约束到所选")
        col.operator("rigidbody.object_settings_copy", text="复制刚体到所选")
        col.operator(
            rigidBodyPhysics.OP_AssignColorsByCollisionGroupCombination.bl_idname, text="刚体组颜色刷新")


cls = []


def register():
    rigidBodyPhysics.register()

    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    rigidBodyPhysics.unregister()

    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
