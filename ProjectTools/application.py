"""Blender-session level operations."""

import os
import subprocess

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator


def _detached_creationflags() -> int:
    if os.name != "nt":
        return 0
    return (
        getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
    )


def _launch_detached(args):
    kwargs = {
        "close_fds": True,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        try:
            subprocess.Popen(args, creationflags=_detached_creationflags(), **kwargs)
            return
        except OSError:
            fallback = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
            )
            subprocess.Popen(args, creationflags=fallback, **kwargs)
            return
    subprocess.Popen(args, start_new_session=True, **kwargs)


def _quit_after_operator():
    try:
        bpy.ops.wm.quit_blender()
    except Exception:
        pass
    return None


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
    startup_script: StringProperty(options={"HIDDEN"})
    startup_script_config: StringProperty(options={"HIDDEN"})

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "confirm_restart")

    def execute(self, context):
        if not self.confirm_restart:
            self.report({'WARNING'}, "请确认重启 Blender")
            return {'CANCELLED'}
        args = [bpy.app.binary_path]
        if self.startup_script:
            args.extend((
                "--background",
                "--factory-startup",
                "--python",
                self.startup_script,
            ))
            if self.startup_script_config:
                args.extend(("--", self.startup_script_config))
        elif bpy.data.filepath:
            args.append(bpy.data.filepath)
        _launch_detached(args)
        bpy.app.timers.register(_quit_after_operator, first_interval=0.15)
        return {"FINISHED"}


# def draw_in_TOPBAR_MT_editor_menus(self, context):
#     """顶部重启按钮"""
#     layout = self.layout
#     layout.alert = True
#     layout.operator(OP_RestartBlender.bl_idname, icon="QUIT", text="")
#     layout.alert = False


__all__ = ["OP_RestartBlender", "draw_in_TOPBAR_MT_editor_menus"]
