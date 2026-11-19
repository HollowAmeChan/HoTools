"""Background Blender checks for optional animation pack operators and timers."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

import bpy
from bpy_restrict_state import RestrictBlend


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import BoneTools
from BoneTools import HumanoidDebug as debug
from BoneTools.HumanoidDebug import animation_pack as pack, pack_ui as ui

spec = importlib.util.spec_from_file_location("pack_ui_build", ROOT / "tools/build_animation_zip.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class Layout:
    def __init__(self):
        self.events = []

    def box(self):
        return self

    def row(self, **kwargs):
        return self

    def label(self, **kwargs):
        self.events.append(("label", kwargs.get("text")))

    def operator(self, name, **kwargs):
        self.events.append(("operator", name))
        return type("Button", (), {})()

    def progress(self, **kwargs):
        self.events.append(("progress", kwargs["type"]))


def finish_job():
    job = ui._JOB
    assert job is not None
    job["thread"].join(timeout=5)
    assert not job["thread"].is_alive()
    if bpy.app.timers.is_registered(ui._poll_job):
        bpy.app.timers.unregister(ui._poll_job)
    assert ui._poll_job() is None
    assert ui._JOB is None


original_directory = debug.ANIMATION_DIRECTORY
with tempfile.TemporaryDirectory(prefix="hotools-pack-ui-") as temp:
    root = Path(temp)
    debug.ANIMATION_DIRECTORY = root / "installed/animations"
    with RestrictBlend():
        BoneTools.register()
    bpy.app.timers.unregister(debug._initialize_scene_settings)
    debug._initialize_scene_settings()
    assert not debug._clip_list()
    layout = Layout()
    debug.draw_preferences(layout, bpy.context)
    for operator in ("ho.humanoid_pack_download", "ho.humanoid_pack_import", "ho.humanoid_pack_remove"):
        assert ("operator", operator) in layout.events

    source = root / "source/BoneTools/HumanoidDebug/animations/VRM/Test.anim"
    source.parent.mkdir(parents=True)
    source.write_text(
        "AnimationClip:\n  m_Name: Test\n  m_SampleRate: 60\n"
        "  m_AnimationClipSettings:\n    m_StopTime: 0.1\n  m_EditorCurves:\n"
        "  m_EulerEditorCurves: []\n", encoding="utf-8",
    )
    archive = root / "HoTools-Humanoid-Animations-test.zip"
    builder.build_animation_zip(root / "source", archive, "test")
    actions_before = tuple(bpy.data.actions)
    assert bpy.ops.ho.humanoid_pack_import(filepath=str(archive)) == {"FINISHED"}
    finish_job()
    assert ui._MESSAGE == "已安装 1 条官方动画", ui._MESSAGE
    assert not ui._ERROR
    assert len(debug._clip_list()) == 1
    assert bpy.context.scene.ho_humanoid_debug_clip == "VRM/Test"
    assert bpy.context.scene.ho_humanoid_debug_frame_count == 7
    assert tuple(bpy.data.actions) == actions_before

    # Both old exact and old float32-rounded enum IDs migrate after relocation.
    from zlib import crc32
    from struct import pack as float_pack, unpack
    checksum = crc32(b"Test")
    for old_value in (
        checksum & debug._MAX_ENUM_VALUE or 1,
        int(unpack("f", float_pack("f", checksum & 0x7fffffff or 1))[0]),
    ):
        bpy.context.scene["ho_humanoid_debug_clip"] = old_value
        debug._repair_clip_selection(bpy.context.scene)
        assert bpy.context.scene.ho_humanoid_debug_clip == "VRM/Test"

    entered = threading.Event()

    def wait_for_cancel(_library, *, progress, cancel):
        progress("等待取消", 0.5)
        entered.set()
        assert cancel.wait(timeout=5)
        raise pack.CancelledError()

    ui._start_job(wait_for_cancel, lambda _result: "unexpected success")
    assert entered.wait(timeout=5)
    assert ui._poll_job() == 0.1
    layout = Layout()
    ui.draw_preferences(layout, bpy.context)
    assert ("progress", "BAR") in layout.events
    assert ("operator", "ho.humanoid_pack_cancel") in layout.events
    assert bpy.ops.ho.humanoid_pack_cancel() == {"FINISHED"}
    finish_job()
    assert ui._MESSAGE == "已取消"
    assert pack.installed_info(debug.ANIMATION_DIRECTORY)["complete"]

    def fail_download(_library, **kwargs):
        raise OSError("simulated network error")

    ui._start_job(fail_download, lambda _result: "")
    finish_job()
    assert ui._ERROR and "simulated network error" in ui._MESSAGE
    assert pack.installed_info(debug.ANIMATION_DIRECTORY)["complete"]

    custom = debug.ANIMATION_DIRECTORY / "User.anim"
    custom.write_bytes(source.read_bytes().replace(b"m_Name: Test", b"m_Name: User"))
    assert bpy.ops.ho.humanoid_pack_remove() == {"FINISHED"}
    finish_job()
    assert custom.is_file()
    assert len(debug._clip_list()) == 1
    assert debug._clip_list()[0].identifier == "User"

    # Disabling with work pending cancels the worker and removes its timer.
    entered.clear()
    ui._start_job(wait_for_cancel, lambda _result: "")
    assert entered.wait(timeout=5)
    thread = ui._JOB["thread"]
    BoneTools.unregister()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert ui._JOB is None
    assert not bpy.app.timers.is_registered(ui._poll_job)
    debug.ANIMATION_DIRECTORY = original_directory
print("HUMANOID_ANIMATION_PACK_UI_OK")
