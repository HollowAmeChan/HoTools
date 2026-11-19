"""Run with Blender --background --factory-startup --python this_file."""

from pathlib import Path
from struct import pack, unpack
import sys
import tempfile
import time
from zlib import crc32

import bpy
from bpy_restrict_state import RestrictBlend
from mathutils import Matrix


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import BoneTools
from BoneTools.HumanoidDebug import anim_parser, rig
from BoneTools import HumanoidDebug as humanoid_debug, boneTPose


def _curve(name, first, last):
    return f"""  - serializedVersion: 2
    curve:
      serializedVersion: 2
      m_Curve:
      - serializedVersion: 3
        time: 0
        value: {first}
        inSlope: 0
        outSlope: 0
        inWeight: 0.33333334
        outWeight: 0.33333334
      - serializedVersion: 3
        time: 0.016666668
        value: {last}
        inSlope: 0
        outSlope: 0
        inWeight: 0.33333334
        outWeight: 0.33333334
      m_PreInfinity: 2
      m_PostInfinity: 2
      m_RotationOrder: 4
    attribute: {name}
    path:
    classID: 95
    script: {{fileID: 0}}
    flags: 0
"""


def _make_clip(path, name="PreviewTest", last_value=0.5):
    content = (
        "%YAML 1.1\n"
        "%TAG !u! tag:unity3d.com,2011:\n"
        "--- !u!74 &7400000\n"
        "AnimationClip:\n"
        f"  m_Name: {name}\n"
        "  m_SampleRate: 60\n"
        "  m_AnimationClipSettings:\n"
        "    m_StartTime: 0\n"
        "    m_StopTime: 0.016666668\n"
        "  m_EditorCurves:\n"
        + _curve("RootT.x", 0, 0.1)
        + _curve("Spine Front-Back", 0, last_value)
        + "  m_EulerEditorCurves: []\n"
    )
    path.write_text(content, encoding="utf-8")


def _create_armature():
    specs = (
        ("Hips", (0.0, 0.0, 0.0), (0.0, 0.0, 0.2), "hips"),
        ("Spine", (0.0, 0.0, 0.2), (0.0, 0.0, 0.55), "spine"),
        ("Head", (0.0, 0.0, 0.9), (0.0, 0.0, 1.15), "head"),
        ("Shoulder.L", (0.25, 0.0, 0.75), (0.4, 0.0, 0.75), "shoulder.L"),
        ("Shoulder.R", (-0.25, 0.0, 0.75), (-0.4, 0.0, 0.75), "shoulder.R"),
        ("UpperArm.L", (0.4, 0.0, 0.75), (0.65, 0.0, 0.75), "upper_arm.L"),
        ("UpperArm.R", (-0.4, 0.0, 0.75), (-0.65, 0.0, 0.75), "upper_arm.R"),
        ("LowerArm.L", (0.65, 0.0, 0.75), (0.9, 0.0, 0.75), "lower_arm.L"),
        ("LowerArm.R", (-0.65, 0.0, 0.75), (-0.9, 0.0, 0.75), "lower_arm.R"),
        ("Hand.L", (0.9, 0.0, 0.75), (1.0, 0.0, 0.75), "hand.L"),
        ("Hand.R", (-0.9, 0.0, 0.75), (-1.0, 0.0, 0.75), "hand.R"),
    )
    data = bpy.data.armatures.new("HumanoidDebugTestData")
    armature = bpy.data.objects.new("HumanoidDebugTest", data)
    bpy.context.scene.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for name, head, tail, _mapping in specs:
        bone = data.edit_bones.new(name)
        bone.head, bone.tail = head, tail
    bpy.ops.object.mode_set(mode="OBJECT")

    for name, _head, _tail, mapping in specs:
        bone = data.bones[name]
        props = bone.hotools_boneprops
        props.humanoidMapping = mapping
        props.humanoidTPoseCached = True
        props.humanoidTPoseMatrixBasis = tuple(
            value for row in Matrix.Identity(4) for value in row
        )
    return armature


class LayoutRecorder:
    def __init__(self):
        self.events = []
        self.enabled = True
        self.operator_context = "INVOKE_DEFAULT"

    def box(self):
        return self

    def panel(self, _identifier, *, default_closed):
        assert default_closed
        return self, self

    def row(self, **_kwargs):
        return self

    def column(self, **_kwargs):
        return self

    def label(self, **kwargs):
        self.events.append(("label", kwargs.get("text")))

    def operator(self, operator, **_kwargs):
        self.events.append(("operator", operator))
        return type("OperatorButton", (), {})()

    def prop(self, _data, property_name, **_kwargs):
        self.events.append(("prop", property_name))

    def separator(self, **_kwargs):
        pass

    def popover(self, **kwargs):
        self.events.append(("popover", kwargs.get("panel")))


scene = bpy.context.scene
original = {
    "frame_start": scene.frame_start,
    "frame_end": scene.frame_end,
    "frame_current": scene.frame_current,
    "fps": scene.render.fps,
    "fps_base": scene.render.fps_base,
}

with tempfile.TemporaryDirectory(prefix="hotools-humanoid-debug-") as temp_dir:
    builtin_directory = humanoid_debug.ANIMATION_DIRECTORY
    assert builtin_directory == ROOT / "BoneTools" / "HumanoidDebug" / "animations"
    animation_directory = Path(temp_dir) / "animations"
    animation_directory.mkdir()
    clip_path = animation_directory / "PreviewTest.anim"
    _make_clip(clip_path)
    humanoid_debug.ANIMATION_DIRECTORY = animation_directory
    # Match addon_utils.enable(): Blender blocks bpy.data/bpy.context scene
    # access throughout add-on registration. Direct register() tests missed
    # the startup failure that hid the entire BoneTools panel.
    with RestrictBlend():
        BoneTools.register()
    assert bpy.app.timers.is_registered(humanoid_debug._initialize_scene_settings)
    bpy.app.timers.unregister(humanoid_debug._initialize_scene_settings)
    humanoid_debug._initialize_scene_settings()
    assert not hasattr(bpy.types.Scene, "ho_humanoid_debug_archive_path")
    clips = anim_parser.list_clips(animation_directory)
    assert len(clips) == 1
    assert clips[0].path == clip_path
    clip = anim_parser.load_clip(clips[0])
    assert clip.info.frame_count(60) == 2
    assert len(clip.curves["Spine Front-Back"].times) == 2
    assert abs(clip.curves["Spine Front-Back"].evaluate(clip.info.duration) - 0.5) < 1e-6

    armature = _create_armature()
    spine = armature.pose.bones["Spine"]
    spine.rotation_mode = "XYZ"
    spine.rotation_euler = (0.1, 0.2, 0.3)
    original_basis = {
        pose_bone.name: pose_bone.matrix_basis.copy()
        for pose_bone in armature.pose.bones
    }
    action = bpy.data.actions.new("HumanoidDebugRestoreAction")
    armature.animation_data_create().action = action
    action_pointers = {item.as_pointer() for item in bpy.data.actions}

    scene.frame_start = 1
    scene.frame_end = 250
    scene.frame_set(11)
    scene.render.fps = 24
    scene.render.fps_base = 1.0
    scene.ho_humanoid_debug_fps = 60
    scene.ho_humanoid_debug_muscle_scale = 1.0
    scene.ho_humanoid_debug_clip = "PreviewTest"
    assert scene.ho_humanoid_debug_auto_frame_count
    assert scene.ho_humanoid_debug_frame_count == 2

    armature.animation_data.action = action
    assert rig.clip_readiness(armature)[0]
    assert humanoid_debug._selected_clip_info(scene).name == "PreviewTest"
    assert bpy.ops.ho.humanoid_tpose_preview() == {"FINISHED"}
    assert boneTPose.is_previewing(armature)
    assert bpy.ops.ho.humanoid_debug_play() == {"FINISHED"}
    assert not boneTPose.is_previewing(armature)
    assert bpy.ops.ho.humanoid_debug_pause() == {"FINISHED"}
    assert scene.render.fps == 60
    assert scene.frame_start == 11
    assert scene.frame_end == 12
    assert armature.animation_data.action is None
    hips = armature.pose.bones["Hips"]
    hips_head_at_start = hips.head.copy()
    reference_state = humanoid_debug._RUNTIME["reference"]
    scene.ho_humanoid_debug_progress = 100
    assert scene.ho_humanoid_debug_frame == 1
    assert scene.frame_current == scene.frame_end
    assert scene.ho_humanoid_debug_progress == 100
    scene.ho_humanoid_debug_progress = 0
    assert scene.frame_current == scene.frame_start

    runtime = humanoid_debug._RUNTIME
    runtime["playing"] = True
    runtime["last_tick"] = time.perf_counter() - (1.0 / 60.0) - 0.002
    assert humanoid_debug._playback_timer() is not None
    assert scene.frame_current == 12
    runtime["playing"] = True
    runtime["last_tick"] = time.perf_counter() - (1.0 / 60.0) - 0.002
    assert humanoid_debug._playback_timer() is not None
    assert scene.frame_current == 11

    scene.ho_humanoid_debug_loop = False
    scene.frame_set(12)
    runtime["playing"] = True
    runtime["last_tick"] = time.perf_counter() - (1.0 / 60.0) - 0.002
    assert humanoid_debug._playback_timer() is None
    assert scene.frame_current == 12
    assert not runtime["playing"]
    scene.ho_humanoid_debug_loop = True

    scene.ho_humanoid_debug_auto_frame_count = False
    scene.ho_humanoid_debug_frame_count = 1
    assert scene.frame_end == 11
    scene.ho_humanoid_debug_frame_count = 2
    assert scene.frame_end == 12
    scene.ho_humanoid_debug_auto_frame_count = True

    scene.frame_set(12)
    animated_basis = spine.matrix_basis.copy()
    assert max(
        abs(animated_basis[row][column] - Matrix.Identity(4)[row][column])
        for row in range(4)
        for column in range(4)
    ) > 1e-4
    expected_root_offset = (
        reference_state["axes"]["right"] * 0.1 * reference_state["rig_scale"]
    )
    assert (hips.head - hips_head_at_start - expected_root_offset).length < 1e-5
    assert armature.animation_data.action is None

    scene.ho_humanoid_debug_frame = 0
    assert scene.frame_current == 11
    assert bpy.ops.ho.humanoid_debug_step(direction=1) == {"FINISHED"}
    assert scene.frame_current == 12
    assert bpy.ops.ho.humanoid_debug_step(direction=-1) == {"FINISHED"}
    assert scene.frame_current == 11
    assert bpy.ops.ho.humanoid_debug_stop() == {"FINISHED"}
    assert scene.frame_start == original["frame_start"] or scene.frame_start == 1
    assert scene.frame_end == 250
    assert scene.frame_current == 11
    assert scene.render.fps == 24
    assert scene.render.fps_base == 1.0
    assert armature.animation_data.action is action
    assert {item.as_pointer() for item in bpy.data.actions} == action_pointers
    for pose_bone in armature.pose.bones:
        expected = original_basis[pose_bone.name]
        actual = pose_bone.matrix_basis
        assert all(
            abs(actual[row][column] - expected[row][column]) < 1e-5
            for row in range(4)
            for column in range(4)
        ), pose_bone.name

    assert bpy.ops.ho.humanoid_debug_play() == {"FINISHED"}
    assert bpy.ops.ho.humanoid_debug_pause() == {"FINISHED"}
    scene.frame_set(12)
    humanoid_debug._save_pre_handler(None)
    assert not humanoid_debug._active_runtime_for_scene(scene)
    assert scene.frame_start == 1
    assert scene.frame_end == 250
    assert scene.frame_current == 11
    assert scene.render.fps == 24
    assert armature.animation_data.action is action
    assert {item.as_pointer() for item in bpy.data.actions} == action_pointers

    layout = LayoutRecorder()
    humanoid_debug.draw_panel(layout, bpy.context)
    assert ("label", "人型动画调试") in layout.events
    assert ("operator", "ho.humanoid_debug_refresh") in layout.events
    assert ("operator", "ho.humanoid_debug_open_folder") in layout.events
    assert ("prop", "ho_humanoid_debug_clip") in layout.events
    assert ("prop", "ho_humanoid_debug_progress") in layout.events
    assert ("popover", "VIEW3D_PT_hotools_humanoid_debug_settings") in layout.events
    assert ("prop", "ho_humanoid_debug_fps") not in layout.events
    assert ("prop", "ho_humanoid_debug_frame_count") not in layout.events
    assert not any(event[0] == "label" and event[1] and
                   ("帧数对齐" in event[1] or "Humanoid 映射" in event[1])
                   for event in layout.events)
    assert ("prop", "ho_humanoid_debug_archive_path") not in layout.events
    settings_layout = LayoutRecorder()
    humanoid_debug.VIEW3D_PT_HumanoidDebugSettings.draw(
        type("SettingsPanel", (), {"layout": settings_layout})(), bpy.context,
    )
    assert ("prop", "ho_humanoid_debug_fps") in settings_layout.events
    assert ("prop", "ho_humanoid_debug_frame_count") in settings_layout.events
    assert ("prop", "ho_humanoid_debug_muscle_scale") in settings_layout.events

    # Dropping files into a subfolder only needs a refresh. Stable enum IDs
    # preserve selection when an earlier filename is inserted.
    other_scene = bpy.data.scenes.new("HumanoidDebugLibraryScene")
    other_scene.ho_humanoid_debug_clip = "PreviewTest"
    nested_directory = animation_directory / "custom"
    nested_directory.mkdir()
    _make_clip(nested_directory / "PreviewTest.ANIM", name="CustomPreview")
    _make_clip(animation_directory / "AAA.anim", name="EarlierClip")
    assert len(humanoid_debug._clip_list()) == 1
    assert bpy.ops.ho.humanoid_debug_refresh() == {"FINISHED"}
    refreshed_clips = humanoid_debug._clip_list()
    assert {info.identifier for info in refreshed_clips} == {
        "AAA", "PreviewTest", "custom/PreviewTest",
    }
    assert scene.ho_humanoid_debug_clip == "PreviewTest"
    assert other_scene.ho_humanoid_debug_clip == "PreviewTest"
    # A real enum button stores its selection through float32. The old
    # 31-bit checksums silently became invalid values and previewed item 1.
    values = [item[4] for item in humanoid_debug._clip_items(scene, bpy.context)]
    assert len(set(values)) == len(values)
    for identifier, _name, _description, _icon, number in humanoid_debug._clip_items(scene, bpy.context):
        assert number == int(unpack("f", pack("f", number))[0])
        scene["ho_humanoid_debug_clip"] = int(unpack("f", pack("f", number))[0])
        humanoid_debug._on_clip_changed(scene, bpy.context)
        assert scene.ho_humanoid_debug_clip == identifier
        assert humanoid_debug._selected_clip_info(scene).identifier == identifier
        assert bpy.ops.ho.humanoid_debug_play() == {"FINISHED"}
        assert humanoid_debug._RUNTIME["clip"].info.identifier == identifier
        assert bpy.ops.ho.humanoid_debug_stop() == {"FINISHED"}

    # Repair both saved old IDs and IDs rounded by the old UI controls.
    legacy = crc32("custom/PreviewTest".encode("utf-8")) & 0x7fffffff or 1
    for raw in (legacy, int(unpack("f", pack("f", legacy))[0])):
        scene["ho_humanoid_debug_clip"] = raw
        humanoid_debug._load_post_handler(None)
        assert scene.ho_humanoid_debug_clip == "custom/PreviewTest"
    scene.ho_humanoid_debug_clip = "custom/PreviewTest"
    assert humanoid_debug._selected_clip_info(scene).name == "CustomPreview"
    assert anim_parser.load_clip(
        humanoid_debug._selected_clip_info(scene)
    ).info.identifier == "custom/PreviewTest"

    # Refresh invalidates samples after replacing an existing animation.
    _make_clip(clip_path, last_value=0.25)
    assert bpy.ops.ho.humanoid_debug_refresh() == {"FINISHED"}
    changed_info = next(
        info for info in humanoid_debug._clip_list()
        if info.identifier == "PreviewTest"
    )
    changed_clip = anim_parser.load_clip(changed_info)
    assert changed_clip is not clip
    assert abs(changed_clip.curves["Spine Front-Back"].values[-1] - 0.25) < 1e-6
    assert scene.ho_humanoid_debug_clip == "custom/PreviewTest"

    # Removed selections fall back to a valid item for every scene.
    (nested_directory / "PreviewTest.ANIM").unlink()
    assert bpy.ops.ho.humanoid_debug_refresh() == {"FINISHED"}
    assert scene.ho_humanoid_debug_clip == "AAA"
    assert other_scene.ho_humanoid_debug_clip == "PreviewTest"
    (animation_directory / "AAA.anim").unlink()
    clip_path.unlink()
    assert bpy.ops.ho.humanoid_debug_refresh() == {"FINISHED"}
    assert not humanoid_debug._clip_list()
    assert scene.ho_humanoid_debug_clip == "_NONE"
    assert other_scene.ho_humanoid_debug_clip == "_NONE"
    _make_clip(clip_path)
    assert bpy.ops.ho.humanoid_debug_refresh() == {"FINISHED"}
    assert scene.ho_humanoid_debug_clip == "PreviewTest"
    assert other_scene.ho_humanoid_debug_clip == "PreviewTest"
    bpy.data.scenes.remove(other_scene)

    # Blender clears non-persistent handlers when opening another .blend.
    # Reproduce that lifecycle, then check actual frame-driven deformation.
    reload_path = Path(temp_dir) / "handler-reload.blend"
    armature.data.pose_position = "REST"
    legacy = crc32("PreviewTest".encode("utf-8")) & 0x7fffffff or 1
    scene["ho_humanoid_debug_clip"] = int(unpack("f", pack("f", legacy))[0])
    bpy.ops.wm.save_as_mainfile(filepath=str(reload_path))
    bpy.ops.wm.open_mainfile(filepath=str(reload_path))
    scene = bpy.context.scene
    armature = bpy.data.objects["HumanoidDebugTest"]
    action = bpy.data.actions["HumanoidDebugRestoreAction"]
    bpy.context.view_layer.objects.active = armature
    assert humanoid_debug._on_frame_change in bpy.app.handlers.frame_change_post
    assert humanoid_debug._load_post_handler in bpy.app.handlers.load_post
    assert scene.ho_humanoid_debug_clip == "PreviewTest"
    assert bpy.ops.ho.humanoid_debug_play() == {"FINISHED"}
    assert armature.data.pose_position == "POSE"
    assert bpy.ops.ho.humanoid_debug_pause() == {"FINISHED"}
    start_basis = armature.pose.bones["Spine"].matrix_basis.copy()
    scene.frame_set(scene.frame_end)
    assert any(
        abs(armature.pose.bones["Spine"].matrix_basis[row][column] - start_basis[row][column]) > 1e-5
        for row in range(3) for column in range(3)
    )
    assert bpy.ops.ho.humanoid_debug_stop() == {"FINISHED"}
    assert armature.data.pose_position == "REST"
    print(
        "HUMANOID_DEBUG_OK",
        bpy.app.version_string,
        "curves",
        len(clip.curves),
    )

    bpy.data.objects.remove(armature, do_unlink=True)
    bpy.data.actions.remove(action)

BoneTools.unregister()
humanoid_debug.ANIMATION_DIRECTORY = builtin_directory
