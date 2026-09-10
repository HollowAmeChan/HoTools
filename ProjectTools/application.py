"""Blender-session level operations."""

import subprocess

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator


class OP_RestartBlender(Operator):
    bl_idname = "ho.restart_blender"
    bl_label = "快速重启"
    bl_description = "不保存并重启 Blender"
    bl_options = {"REGISTER"}

    confirm_restart: BoolProperty(
        name="确认重启",
        description="重启不会自动保存当前未保存的内容",
        default=True,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "confirm_restart")

    def execute(self, context):
        if not self.confirm_restart:
            self.report({'WARNING'}, "请确认重启 Blender")
            return {'CANCELLED'}
        args = [bpy.app.binary_path]
        if bpy.data.filepath:
            args.append(bpy.data.filepath)
        subprocess.Popen(args)
        bpy.ops.wm.quit_blender()
        return {"FINISHED"}


# def draw_in_TOPBAR_MT_editor_menus(self, context):
#     """顶部重启按钮"""
#     layout = self.layout
#     layout.alert = True
#     layout.operator(OP_RestartBlender.bl_idname, icon="QUIT", text="")
#     layout.alert = False


__all__ = ["OP_RestartBlender", "draw_in_TOPBAR_MT_editor_menus"]
