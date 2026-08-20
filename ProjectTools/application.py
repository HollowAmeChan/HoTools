"""Blender-session level operations."""

import subprocess

import bpy
from bpy.types import Operator


class OP_RestartBlender(Operator):
    bl_idname = "ho.restart_blender"
    bl_label = "快速重启"
    bl_description = "不保存并重启 Blender"
    bl_options = {"REGISTER"}

    def execute(self, context):
        args = [bpy.app.binary_path]
        if bpy.data.filepath:
            args.append(bpy.data.filepath)
        subprocess.Popen(args)
        bpy.ops.wm.quit_blender()
        return {"FINISHED"}

__all__ = ["OP_RestartBlender"]
