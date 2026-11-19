"""Blender controls for the optional animation library."""

import queue
import threading
import time
from pathlib import Path

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from . import animation_pack, anim_parser


_JOB = None
_MESSAGE = ""
_PROGRESS = 0.0
_ERROR = False
_JOB_LOCK = threading.Lock()


def _library():
    from . import ANIMATION_DIRECTORY
    return ANIMATION_DIRECTORY


def _redraw():
    manager = bpy.context.window_manager
    if manager:
        for window in manager.windows:
            for area in window.screen.areas:
                if area.type in {"PREFERENCES", "VIEW_3D"}:
                    area.tag_redraw()


def _poll_job():
    global _JOB, _MESSAGE, _PROGRESS, _ERROR
    job = _JOB
    if job is None:
        return None
    finished = False
    clips = None
    succeeded = False
    while True:
        try:
            kind, message, factor, preloaded = job["events"].get_nowait()
        except queue.Empty:
            break
        _MESSAGE, _PROGRESS = message, factor
        if kind in {"done", "cancelled", "error"}:
            _ERROR = kind == "error"
            finished = True
            succeeded = kind == "done"
            clips = preloaded
    if finished:
        _JOB = None
        if succeeded:
            from . import refresh_library
            refresh_library(clips)
    _redraw()
    return None if finished else 0.1


def _start_job(work, success):
    global _JOB, _MESSAGE, _PROGRESS, _ERROR
    if _JOB is not None:
        raise ValueError("动画包任务正在进行")
    from . import _stop_preview
    _stop_preview()
    events = queue.SimpleQueue()
    cancel = threading.Event()
    library = Path(_library())
    _MESSAGE, _PROGRESS, _ERROR = "准备动画包", 0.0, False

    def worker():
        last_update = 0.0

        def progress(message, factor):
            nonlocal last_update
            now = time.monotonic()
            if now - last_update >= 0.1 or factor >= 1.0:
                events.put(("progress", message, factor, None))
                last_update = now

        try:
            # A cancelled worker can still be waiting for a network timeout
            # when the add-on is re-enabled. Serialize file operations.
            with _JOB_LOCK:
                if cancel.is_set():
                    raise animation_pack.CancelledError("已取消")
                result = work(library, progress=progress, cancel=cancel)
                progress("读取动画列表", 1.0)
                # Scanning these large Unity YAML headers can take seconds.
                # Keep that work off Blender's main thread as well.
                clips = anim_parser.list_clips(library)
            events.put(("done", success(result), 1.0, clips))
        except animation_pack.CancelledError:
            events.put(("cancelled", "已取消", 0.0, None))
        except Exception as error:
            events.put(("error", f"操作失败：{error}", 0.0, None))

    thread = threading.Thread(target=worker, name="HoToolsAnimationPack", daemon=True)
    _JOB = {"thread": thread, "cancel": cancel, "events": events}
    try:
        bpy.app.timers.register(_poll_job, first_interval=0.1, persistent=True)
        thread.start()
    except BaseException:
        _JOB = None
        if bpy.app.timers.is_registered(_poll_job):
            bpy.app.timers.unregister(_poll_job)
        raise
    _redraw()


class OT_HumanoidPackDownload(Operator):
    bl_idname = "ho.humanoid_pack_download"
    bl_label = "下载动画包"
    bl_description = "从对应 GitHub Release 下载官方动画包，解压后自动刷新动作列表"

    @classmethod
    def poll(cls, _context):
        return _JOB is None

    def execute(self, _context):
        if not getattr(bpy.app, "online_access", True):
            self.report({"ERROR"}, "请先在 Blender 偏好设置中启用“允许联网”，或从本地 ZIP 安装")
            return {"CANCELLED"}
        metadata = animation_pack.read_metadata()
        try:
            _start_job(
                lambda library, **kwargs: animation_pack.download_and_install(
                    library, metadata=metadata, **kwargs
                ),
                lambda result: f"已安装 {len(result['files'])} 条官方动画",
            )
        except (OSError, ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class OT_HumanoidPackImport(Operator, ImportHelper):
    bl_idname = "ho.humanoid_pack_import"
    bl_label = "从 ZIP 安装动画包"
    bl_description = "安装从 HoTools Release 下载的独立动画 ZIP"
    filename_ext = ".zip"
    filter_glob: StringProperty(default="*.zip", options={"HIDDEN"})

    @classmethod
    def poll(cls, _context):
        return _JOB is None

    def execute(self, _context):
        archive = Path(self.filepath)
        try:
            _start_job(
                lambda library, **kwargs: animation_pack.install_archive(
                    archive, library, **kwargs
                ),
                lambda result: f"已安装 {len(result['files'])} 条官方动画",
            )
        except (OSError, ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class OT_HumanoidPackRemove(Operator):
    bl_idname = "ho.humanoid_pack_remove"
    bl_label = "移除动画包"
    bl_description = "移除下载的官方动画，保留用户自己添加或修改的动画"

    @classmethod
    def poll(cls, _context):
        return _JOB is None and animation_pack.installed_info(_library())["managed"]

    def execute(self, _context):
        try:
            _start_job(
                animation_pack.uninstall,
                lambda result: f"已移除 {result['removed']} 条官方动画"
                + (f"，保留 {result['preserved']} 条修改过的动画" if result["preserved"] else ""),
            )
        except (OSError, ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class OT_HumanoidPackCancel(Operator):
    bl_idname = "ho.humanoid_pack_cancel"
    bl_label = "取消下载"
    bl_description = "取消当前动画包操作，保留先前安装的动画"

    @classmethod
    def poll(cls, _context):
        return _JOB is not None

    def execute(self, _context):
        _JOB["cancel"].set()
        return {"FINISHED"}


def draw_preferences(layout, _context):
    box = layout.box()
    box.label(text="人型调试动画（可选）", icon="ARMATURE_DATA")
    info = animation_pack.installed_info(_library())
    if _JOB is not None:
        row = box.row(align=True)
        row.progress(factor=_PROGRESS, type="BAR", text=_MESSAGE)
        row.operator(OT_HumanoidPackCancel.bl_idname, text="", icon="CANCEL")
        return
    if info["count"]:
        status = (
            f"已安装 · {info['count']} 条动画" if info["managed"]
            else f"本地动画 · {info['count']} 条"
        )
        if not info["complete"]:
            status = "动画包不完整，请重新下载"
        box.label(text=status, icon="CHECKMARK" if info["complete"] else "ERROR")
    else:
        box.label(text="未安装", icon="INFO")
    row = box.row(align=True)
    row.operator(
        OT_HumanoidPackDownload.bl_idname,
        text="重新下载" if info["managed"] else "下载动画包",
        icon="IMPORT",
    )
    row.operator(OT_HumanoidPackImport.bl_idname, text="", icon="FILE_FOLDER")
    remove = row.row(align=True)
    remove.enabled = info["managed"]
    remove.operator(OT_HumanoidPackRemove.bl_idname, text="", icon="TRASH")
    if _MESSAGE:
        message = box.row()
        message.alert = _ERROR
        message.label(text=_MESSAGE, icon="ERROR" if _ERROR else "INFO")


CLASSES = (
    OT_HumanoidPackDownload, OT_HumanoidPackImport,
    OT_HumanoidPackRemove, OT_HumanoidPackCancel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    global _JOB, _MESSAGE, _ERROR
    if _JOB:
        _JOB["cancel"].set()
        # The worker only handles Python data and files; it never touches bpy.
        _JOB = None
    if bpy.app.timers.is_registered(_poll_job):
        bpy.app.timers.unregister(_poll_job)
    _MESSAGE, _ERROR = "", False
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
