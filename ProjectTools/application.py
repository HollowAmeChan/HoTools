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

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "confirm_restart")

    def execute(self, context):
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
