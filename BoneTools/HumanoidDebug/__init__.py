"""Temporary Unity Humanoid animation preview for mapped Blender armatures."""

import time
from pathlib import Path
from struct import pack, unpack
from zlib import crc32

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from bpy.types import Operator, Panel

from . import anim_parser, rig


_RUNTIME = None
_UPDATING_FRAME_PROPERTY = False
_UPDATING_FRAME_COUNT = False
_FRAME_HANDLER = None
_SAVE_HANDLER = None
_LOAD_HANDLER = None
_LOAD_POST_HANDLER = None
_RENDER_HANDLER = None
_UNDO_HANDLER = None
ANIMATION_DIRECTORY = Path(__file__).resolve().parent / "animations"
_CLIP_LIST_CACHE = None
_CLIP_ENUM_ITEMS = []
_CLIP_ENUM_VALUES = {}
_CLIP_LEGACY_VALUES = {}
_MAX_ENUM_VALUE = (1 << 24) - 1
_MAX_PLAYBACK_FPS = 120
_MAX_PREVIEW_FRAMES = 6000
_TIMER_INTERVAL = 1.0 / 60.0


def _clip_list():
    global _CLIP_LIST_CACHE, _CLIP_ENUM_ITEMS
    if _CLIP_LIST_CACHE is None:
        _CLIP_LIST_CACHE = anim_parser.list_clips(ANIMATION_DIRECTORY)
        _CLIP_ENUM_VALUES.clear()
        _CLIP_LEGACY_VALUES.clear()
        items = []
        used_values = set()
        for info in _CLIP_LIST_CACHE:
            checksum = crc32(info.identifier.encode("utf-8"))
            # Enum menu buttons pass their value through a float32. Larger
            # integers round to a different, invalid enum on an actual click.
            number = checksum & _MAX_ENUM_VALUE or 1
            while number in used_values:
                number = number % _MAX_ENUM_VALUE + 1
            used_values.add(number)
            _CLIP_ENUM_VALUES[info.identifier] = number
            legacy = checksum & 0x7fffffff or 1
            for value in (legacy, int(unpack("f", pack("f", legacy))[0])):
                _CLIP_LEGACY_VALUES.setdefault(value, info.identifier)
            items.append((
                info.identifier,
                info.name,
                f"{info.duration:.2f} 秒 · {info.sample_rate:g} FPS · "
                f"{info.path.relative_to(ANIMATION_DIRECTORY).as_posix()}",
                0,
                number,
            ))
        _CLIP_ENUM_ITEMS = items or [
            ("_NONE", "没有可用动画", "将 Unity Humanoid .anim 放入动画文件夹后刷新", 0, 0),
        ]
    return _CLIP_LIST_CACHE


def _clip_items(_scene, _context):
    _clip_list()
    # Blender retains references to dynamic enum strings.
    return _CLIP_ENUM_ITEMS


def _selected_clip_info(scene):
    clips = _clip_list()
    if not clips:
        return None
    identifier = scene.ho_humanoid_debug_clip
    return next(
        (info for info in clips if info.identifier == identifier),
        None,
    )


def _repair_clip_selection(scene):
    clips = _clip_list()
    raw = scene.get("ho_humanoid_debug_clip")
    if raw is None or raw in _CLIP_ENUM_VALUES.values():
        return
    identifier = _CLIP_LEGACY_VALUES.get(raw)
    scene.ho_humanoid_debug_clip = (
        identifier or (clips[0].identifier if clips else "_NONE")
    )


def _effective_frame_count(scene, info):
    if scene.ho_humanoid_debug_auto_frame_count:
        return info.frame_count(scene.ho_humanoid_debug_fps)
    return max(1, min(_MAX_PREVIEW_FRAMES, scene.ho_humanoid_debug_frame_count))


def _refresh_frame_count(scene):
    global _UPDATING_FRAME_COUNT
    info = _selected_clip_info(scene)
    frame_count = (
        info.frame_count(scene.ho_humanoid_debug_fps)
        if info is not None
        else 1
    )
    _UPDATING_FRAME_COUNT = True
    try:
        scene.ho_humanoid_debug_frame_count = frame_count
    finally:
        _UPDATING_FRAME_COUNT = False
    return frame_count


def _active_runtime_for_scene(scene):
    return _RUNTIME is not None and _RUNTIME["scene"] == scene


def _tag_redraw():
    window_manager = bpy.context.window_manager
    if window_manager is None:
        return
    for window in window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D" or area.type == "DOPESHEET_EDITOR":
                area.tag_redraw()


def _matrix_basis_snapshot(armature):
    return {
        pose_bone.name: pose_bone.matrix_basis.copy()
        for pose_bone in armature.pose.bones
    }


def _capture_state(scene, armature):
    animation_data = armature.animation_data
    return {
        "scene": scene,
        "armature": armature,
        "pose_position": armature.data.pose_position,
        "basis": _matrix_basis_snapshot(armature),
        "animation_data": animation_data,
        "action": getattr(animation_data, "action", None),
        "action_slot": getattr(animation_data, "action_slot", None),
        "use_nla": getattr(animation_data, "use_nla", None),
        "nla_tracks": [
            (track, bool(track.mute))
            for track in getattr(animation_data, "nla_tracks", ())
        ],
        "drivers": [
            (driver, bool(driver.mute))
            for driver in getattr(animation_data, "drivers", ())
        ],
        "constraints": [
            (constraint, bool(constraint.mute))
            for pose_bone in armature.pose.bones
            for constraint in pose_bone.constraints
        ],
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "frame_current": scene.frame_current,
        "fps": scene.render.fps,
        "fps_base": scene.render.fps_base,
    }


def _suspend_pose_inputs(state):
    state["armature"].data.pose_position = "POSE"
    animation_data = state["animation_data"]
    if animation_data is not None:
        if state["action"] is not None:
            animation_data.action = None
        if state["use_nla"] is not None:
            animation_data.use_nla = False
        for track, _muted in state["nla_tracks"]:
            track.mute = True
        for driver, _muted in state["drivers"]:
            driver.mute = True
    for constraint, _muted in state["constraints"]:
        constraint.mute = True
    bpy.context.view_layer.update()


def _restore_state(state):
    scene = state.get("scene")
    armature = state.get("armature")
    try:
        if armature is None or armature.type != "ARMATURE":
            return
    except ReferenceError:
        return

    animation_data = state["animation_data"]
    if animation_data is not None:
        try:
            animation_data.action = state["action"]
            action_slot = state["action_slot"]
            if action_slot is not None and hasattr(animation_data, "action_slot"):
                try:
                    animation_data.action_slot = action_slot
                except (AttributeError, TypeError, ValueError, RuntimeError):
                    pass
            if state["use_nla"] is not None:
                animation_data.use_nla = state["use_nla"]
            for track, muted in state["nla_tracks"]:
                track.mute = muted
            for driver, muted in state["drivers"]:
                driver.mute = muted
        except ReferenceError:
            pass
    for constraint, muted in state["constraints"]:
        try:
            constraint.mute = muted
        except ReferenceError:
            pass

    for pose_bone in armature.pose.bones:
        basis = state["basis"].get(pose_bone.name)
        if basis is not None:
            pose_bone.matrix_basis = basis
    armature.data.pose_position = state["pose_position"]

    if scene is not None:
        try:
            scene.frame_start = state["frame_start"]
            scene.frame_end = state["frame_end"]
            scene.render.fps = state["fps"]
            scene.render.fps_base = state["fps_base"]
        except ReferenceError:
            scene = None

    try:
        bpy.context.view_layer.update()
    except (ReferenceError, RuntimeError):
        pass

    if scene is not None:
        try:
            scene.frame_set(state["frame_current"])
        except (ReferenceError, RuntimeError):
            pass


def _stop_preview():
    global _RUNTIME
    state = _RUNTIME
    if state is None:
        return False
    _RUNTIME = None
    if bpy.app.timers.is_registered(_playback_timer):
        bpy.app.timers.unregister(_playback_timer)
    _restore_state(state)
    _tag_redraw()
    return True


def _apply_preview_frame(scene, frame):
    if not _active_runtime_for_scene(scene):
        return
    state = _RUNTIME
    total = _effective_frame_count(scene, state["clip"].info)
    offset = max(0, min(total - 1, frame - state["start_frame"]))
    frame_rate = scene.ho_humanoid_debug_fps
    sample = state["clip"].sample(offset / frame_rate)
    rig.apply_sample(
        state["armature"],
        state["reference"],
        sample,
        scene.ho_humanoid_debug_muscle_scale,
    )

    global _UPDATING_FRAME_PROPERTY
    if scene.ho_humanoid_debug_frame != offset:
        _UPDATING_FRAME_PROPERTY = True
        try:
            scene.ho_humanoid_debug_frame = offset
        finally:
            _UPDATING_FRAME_PROPERTY = False
    _tag_redraw()


@persistent
def _on_frame_change(scene, _depsgraph=None):
    if _active_runtime_for_scene(scene):
        _apply_preview_frame(scene, scene.frame_current)


def _playback_timer():
    if _RUNTIME is None or not _RUNTIME["playing"]:
        return None
    state = _RUNTIME
    scene = state["scene"]
    try:
        now = time.perf_counter()
        fps = max(1, scene.ho_humanoid_debug_fps)
        elapsed = now - state["last_tick"]
        steps = int(elapsed * fps)
        if steps <= 0:
            return min(_TIMER_INTERVAL, 1.0 / fps)
        state["last_tick"] += steps / fps

        total = _effective_frame_count(scene, state["clip"].info)
        offset = scene.frame_current - state["start_frame"] + steps
        if offset >= total:
            if scene.ho_humanoid_debug_loop:
                offset %= total
            else:
                offset = total - 1
                state["playing"] = False
        scene.frame_set(state["start_frame"] + offset)
        return min(_TIMER_INTERVAL, 1.0 / fps) if state["playing"] else None
    except (ReferenceError, RuntimeError, TypeError):
        _stop_preview()
        return None


def _set_preview_rate(scene, frame_rate):
    if not _active_runtime_for_scene(scene):
        return
    state = _RUNTIME
    frame_rate = max(1, min(_MAX_PLAYBACK_FPS, int(frame_rate)))
    scene.render.fps = frame_rate
    scene.render.fps_base = 1.0
    total = _effective_frame_count(scene, state["clip"].info)
    scene.frame_end = state["start_frame"] + total - 1
    offset = max(0, min(total - 1, scene.frame_current - state["start_frame"]))
    if scene.frame_current != state["start_frame"] + offset:
        scene.frame_set(state["start_frame"] + offset)
    else:
        _apply_preview_frame(scene, scene.frame_current)


def _on_clip_changed(scene, _context):
    if _active_runtime_for_scene(scene):
        _stop_preview()
    scene.ho_humanoid_debug_frame = 0
    _refresh_frame_count(scene)


def _on_frame_property_changed(scene, _context):
    if _UPDATING_FRAME_PROPERTY or not _active_runtime_for_scene(scene):
        return
    state = _RUNTIME
    total = _effective_frame_count(scene, state["clip"].info)
    offset = max(0, min(total - 1, scene.ho_humanoid_debug_frame))
    target_frame = state["start_frame"] + offset
    if scene.frame_current != target_frame:
        scene.frame_set(target_frame)
    else:
        _apply_preview_frame(scene, target_frame)


def _get_progress(scene):
    info = _selected_clip_info(scene)
    if info is None:
        return 0.0
    last = _effective_frame_count(scene, info) - 1
    return min(100.0, scene.ho_humanoid_debug_frame * 100.0 / last) if last else 0.0


def _set_progress(scene, value):
    if not _active_runtime_for_scene(scene):
        return
    total = _effective_frame_count(scene, _RUNTIME["clip"].info)
    scene.ho_humanoid_debug_frame = round(value * 0.01 * (total - 1))
    _RUNTIME["last_tick"] = time.perf_counter()


def _on_fps_changed(scene, _context):
    if scene.ho_humanoid_debug_auto_frame_count:
        _refresh_frame_count(scene)
    if _active_runtime_for_scene(scene):
        _set_preview_rate(scene, scene.ho_humanoid_debug_fps)


def _on_auto_frame_count_changed(scene, _context):
    if scene.ho_humanoid_debug_auto_frame_count:
        _refresh_frame_count(scene)
    if _active_runtime_for_scene(scene):
        _set_preview_rate(scene, scene.ho_humanoid_debug_fps)


def _on_frame_count_changed(scene, _context):
    if _UPDATING_FRAME_COUNT or not _active_runtime_for_scene(scene):
        return
    _set_preview_rate(scene, scene.ho_humanoid_debug_fps)


def _on_muscle_scale_changed(scene, _context):
    if _active_runtime_for_scene(scene):
        _apply_preview_frame(scene, scene.frame_current)


def _begin_preview(scene, armature):
    global _RUNTIME
    if _RUNTIME is not None:
        _stop_preview()

    info = _selected_clip_info(scene)
    if info is None:
        raise ValueError("请将 Unity Humanoid .anim 放入动画文件夹后刷新")
    clip = anim_parser.load_clip(info)
    ready, message, _mapping_count, _calibrated_count = rig.clip_readiness(armature)
    if not ready:
        raise ValueError(message)
    if not rig.has_supported_curves(armature, clip):
        raise ValueError("此动画没有可映射到当前骨架的 Humanoid 曲线")

    if bpy.context.active_object != armature:
        raise ValueError("请将目标人型骨架设为活动对象")
    from .. import boneTPose
    if boneTPose.is_previewing(armature):
        boneTPose._restore_preview(armature)

    state = _capture_state(scene, armature)
    try:
        _suspend_pose_inputs(state)
        reference = rig.build_reference_state(armature, clip)
        frame_rate = max(1, min(_MAX_PLAYBACK_FPS, scene.ho_humanoid_debug_fps))
        frame_start = scene.frame_current
        total = _effective_frame_count(scene, clip.info)
        _RUNTIME = {
            **state,
            "clip": clip,
            "reference": reference,
            "start_frame": frame_start,
            "playing": False,
            "last_tick": 0.0,
        }
        scene.render.fps = frame_rate
        scene.render.fps_base = 1.0
        scene.frame_start = frame_start
        scene.frame_end = frame_start + total - 1
        scene.ho_humanoid_debug_frame = 0
        scene.frame_set(frame_start)
        _apply_preview_frame(scene, frame_start)
    except Exception:
        _RUNTIME = None
        _restore_state(state)
        raise


class OT_HumanoidDebugRefresh(Operator):
    bl_idname = "ho.humanoid_debug_refresh"
    bl_label = "刷新动画"
    bl_description = "重新扫描动画文件夹及子文件夹，读取新增或修改的 .anim 文件"

    def execute(self, _context):
        global _CLIP_LIST_CACHE
        selected = {
            scene: scene.ho_humanoid_debug_clip for scene in bpy.data.scenes
        }
        _stop_preview()
        anim_parser.clear_clip_cache()
        _CLIP_LIST_CACHE = None
        clips = _clip_list()
        identifiers = {info.identifier for info in clips}
        fallback = clips[0].identifier if clips else "_NONE"
        for scene, identifier in selected.items():
            scene.ho_humanoid_debug_clip = (
                identifier if identifier in identifiers else fallback
            )
        _tag_redraw()
        self.report({"INFO"}, f"已刷新 {len(clips)} 条人型动画")
        return {"FINISHED"}


class OT_HumanoidDebugOpenFolder(Operator):
    bl_idname = "ho.humanoid_debug_open_folder"
    bl_label = "打开动画文件夹"
    bl_description = "打开内置动画文件夹；将 Unity Humanoid .anim 放入此处后点击刷新"

    def execute(self, _context):
        try:
            ANIMATION_DIRECTORY.mkdir(parents=True, exist_ok=True)
            return bpy.ops.wm.path_open(filepath=str(ANIMATION_DIRECTORY))
        except (OSError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class OT_HumanoidDebugPlay(Operator):
    bl_idname = "ho.humanoid_debug_play"
    bl_label = "播放 Humanoid 动画"
    bl_description = "临时计算并播放当前 Unity Humanoid 动画"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "ARMATURE"

    def execute(self, context):
        armature = context.active_object
        try:
            if (
                _RUNTIME is None
                or _RUNTIME["armature"] != armature
                or _RUNTIME["scene"] != context.scene
            ):
                _begin_preview(context.scene, armature)
            state = _RUNTIME
            if not state["playing"]:
                total = _effective_frame_count(context.scene, state["clip"].info)
                if context.scene.frame_current >= state["start_frame"] + total - 1:
                    context.scene.frame_set(state["start_frame"])
                state["playing"] = True
                state["last_tick"] = time.perf_counter()
                if not bpy.app.timers.is_registered(_playback_timer):
                    bpy.app.timers.register(
                        _playback_timer,
                        first_interval=_TIMER_INTERVAL,
                        persistent=False,
                    )
            _tag_redraw()
            return {"FINISHED"}
        except (OSError, ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class OT_HumanoidDebugPause(Operator):
    bl_idname = "ho.humanoid_debug_pause"
    bl_label = "暂停 Humanoid 动画"
    bl_description = "暂停播放并保留当前姿态，便于逐帧检查"

    @classmethod
    def poll(cls, _context):
        return _RUNTIME is not None and _RUNTIME["playing"]

    def execute(self, _context):
        _RUNTIME["playing"] = False
        if bpy.app.timers.is_registered(_playback_timer):
            bpy.app.timers.unregister(_playback_timer)
        _tag_redraw()
        return {"FINISHED"}


class OT_HumanoidDebugStop(Operator):
    bl_idname = "ho.humanoid_debug_stop"
    bl_label = "停止 Humanoid 动画"
    bl_description = "退出临时预览并恢复姿态、动画输入和 Blender 时间轴"

    @classmethod
    def poll(cls, _context):
        return _RUNTIME is not None

    def execute(self, _context):
        _stop_preview()
        return {"FINISHED"}


class OT_HumanoidDebugStep(Operator):
    bl_idname = "ho.humanoid_debug_step"
    bl_label = "逐帧查看"
    bl_description = "将临时动画预览移动一帧"
    direction: IntProperty(default=1, min=-1, max=1)

    @classmethod
    def poll(cls, context):
        return (
            _RUNTIME is not None
            and not _RUNTIME["playing"]
            and _RUNTIME["scene"] == context.scene
        )

    def execute(self, context):
        scene = context.scene
        total = _effective_frame_count(scene, _RUNTIME["clip"].info)
        offset = scene.frame_current - _RUNTIME["start_frame"] + self.direction
        offset = max(0, min(total - 1, offset))
        scene.frame_set(_RUNTIME["start_frame"] + offset)
        return {"FINISHED"}


class VIEW3D_PT_HumanoidDebugSettings(Panel):
    bl_idname = "VIEW3D_PT_hotools_humanoid_debug_settings"
    bl_label = "播放设置"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 13

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(scene, "ho_humanoid_debug_fps", text="帧率")
        row = layout.row(align=True)
        row.prop(scene, "ho_humanoid_debug_auto_frame_count", text="自动帧数")
        row = layout.row()
        row.enabled = not scene.ho_humanoid_debug_auto_frame_count
        row.prop(scene, "ho_humanoid_debug_frame_count", text="总帧数")
        layout.prop(scene, "ho_humanoid_debug_muscle_scale", text="动作幅度")
        frame = layout.row()
        frame.enabled = _active_runtime_for_scene(scene)
        frame.prop(scene, "ho_humanoid_debug_frame", text="当前帧")
        info = _selected_clip_info(scene)
        if info is not None:
            layout.separator()
            layout.label(text=f"{info.duration:.2f} 秒 · 源 {info.sample_rate:g} FPS")
            total = _effective_frame_count(scene, info)
            duration = (total - 1) / scene.ho_humanoid_debug_fps
            if abs(duration - info.duration) > 0.5 / scene.ho_humanoid_debug_fps:
                layout.label(text=f"时长 {duration:.2f} 秒（未对齐）", icon="ERROR")


def draw_panel(layout, context):
    scene = context.scene
    armature = context.active_object
    header, box = layout.panel("hotools_bone_humanoid_debug", default_closed=True)
    header.label(text="人型动画调试", icon="ARMATURE_DATA")
    if box is None:
        return

    _clip_list()
    clip_row = box.row(align=True)
    clip_row.prop(scene, "ho_humanoid_debug_clip", text="")
    clip_row.operator(OT_HumanoidDebugRefresh.bl_idname, text="", icon="FILE_REFRESH")
    clip_row.operator(
        OT_HumanoidDebugOpenFolder.bl_idname, text="", icon="FILE_FOLDER"
    )

    info = _selected_clip_info(scene)
    active = _active_runtime_for_scene(scene) and _RUNTIME["armature"] == armature
    ready, reason, _mapped_count, _calibrated_count = rig.clip_readiness(armature)
    has_clip = info is not None
    controls_ready = ready and has_clip

    controls = box.row(align=True)
    transport = controls.row(align=True)
    step = transport.row(align=True)
    step.enabled = active and not _RUNTIME["playing"]
    previous = step.operator(
        OT_HumanoidDebugStep.bl_idname,
        text="",
        icon="PREV_KEYFRAME",
    )
    previous.direction = -1
    play = transport.row(align=True)
    play.enabled = controls_ready or active
    if active and _RUNTIME["playing"]:
        play.operator(
            OT_HumanoidDebugPause.bl_idname,
            text="",
            icon="PAUSE",
        )
    else:
        play.operator(
            OT_HumanoidDebugPlay.bl_idname,
            text="",
            icon="PLAY",
            depress=active,
        )
    stop = transport.row(align=True)
    stop.enabled = _RUNTIME is not None
    stop.operator(OT_HumanoidDebugStop.bl_idname, text="", icon="CANCEL")
    step = transport.row(align=True)
    step.enabled = active and not _RUNTIME["playing"]
    following = step.operator(
        OT_HumanoidDebugStep.bl_idname,
        text="",
        icon="NEXT_KEYFRAME",
    )
    following.direction = 1
    controls.prop(scene, "ho_humanoid_debug_loop", text="循环", toggle=True)
    controls.popover(panel=VIEW3D_PT_HumanoidDebugSettings.bl_idname, text="", icon="PREFERENCES")

    if info is not None:
        frame_count = _effective_frame_count(scene, info)
        progress = box.row(align=True)
        slider = progress.row()
        slider.enabled = active
        slider.prop(scene, "ho_humanoid_debug_progress", text="", slider=True)
        offset = min(scene.ho_humanoid_debug_frame, frame_count - 1) if active else 0
        progress.label(text=f"{offset + 1} / {frame_count}")
    if not ready:
        box.label(text=reason, icon="INFO")
    elif not has_clip:
        box.label(text="将 .anim 放入动画文件夹后刷新", icon="INFO")


_CLASSES = (
    OT_HumanoidDebugRefresh,
    OT_HumanoidDebugOpenFolder,
    OT_HumanoidDebugPlay,
    OT_HumanoidDebugPause,
    OT_HumanoidDebugStop,
    OT_HumanoidDebugStep,
    VIEW3D_PT_HumanoidDebugSettings,
)


@persistent
def _save_pre_handler(_dummy):
    _stop_preview()


@persistent
def _load_pre_handler(_dummy):
    _stop_preview()


@persistent
def _load_post_handler(_dummy):
    _initialize_scene_settings()


def _initialize_scene_settings():
    """Initialize scene values after Blender leaves its restricted register phase."""
    for scene in bpy.data.scenes:
        _repair_clip_selection(scene)
        if scene.ho_humanoid_debug_auto_frame_count:
            _refresh_frame_count(scene)
    _tag_redraw()


@persistent
def _render_pre_handler(_dummy):
    _stop_preview()


@persistent
def _undo_pre_handler(_dummy):
    _stop_preview()


def register():
    global _FRAME_HANDLER, _SAVE_HANDLER, _LOAD_HANDLER, _RENDER_HANDLER, _UNDO_HANDLER
    global _LOAD_POST_HANDLER
    _clip_list()
    bpy.types.Scene.ho_humanoid_debug_clip = EnumProperty(
        name="动作",
        description="Unity Humanoid 动画",
        items=_clip_items,
        default=_CLIP_ENUM_ITEMS[0][4],
        update=_on_clip_changed,
    )
    bpy.types.Scene.ho_humanoid_debug_frame = IntProperty(
        name="预览帧",
        description="当前 Unity 动画预览帧，不会创建关键帧",
        default=0,
        min=0,
        max=_MAX_PREVIEW_FRAMES,
        update=_on_frame_property_changed,
    )
    bpy.types.Scene.ho_humanoid_debug_progress = FloatProperty(
        name="播放进度",
        description="拖动以逐帧查看当前动作",
        min=0.0,
        max=100.0,
        subtype="PERCENTAGE",
        precision=0,
        get=_get_progress,
        set=_set_progress,
        options={"SKIP_SAVE"},
    )
    bpy.types.Scene.ho_humanoid_debug_fps = IntProperty(
        name="预览帧率",
        description="播放期间临时同步到 Blender 场景帧率",
        default=60,
        min=1,
        max=_MAX_PLAYBACK_FPS,
        update=_on_fps_changed,
    )
    bpy.types.Scene.ho_humanoid_debug_auto_frame_count = BoolProperty(
        name="自动对齐帧数",
        description="按动作时长和预览帧率计算总帧数",
        default=True,
        update=_on_auto_frame_count_changed,
    )
    bpy.types.Scene.ho_humanoid_debug_frame_count = IntProperty(
        name="帧数",
        description="自动对齐关闭时使用的播放帧数",
        default=1,
        min=1,
        max=_MAX_PREVIEW_FRAMES,
        update=_on_frame_count_changed,
    )
    bpy.types.Scene.ho_humanoid_debug_loop = BoolProperty(
        name="循环",
        description="动画到达末帧后从首帧继续播放",
        default=True,
    )
    bpy.types.Scene.ho_humanoid_debug_muscle_scale = FloatProperty(
        name="肌肉幅度",
        description=(
            "以保存的 T-Pose 为基准调整预览姿态幅度；"
            "1 为 Unity 默认肌肉角度范围，0 为标定的肢体姿态"
        ),
        default=1.0,
        min=0.0,
        max=2.0,
        soft_max=1.5,
        update=_on_muscle_scale_changed,
    )
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    _FRAME_HANDLER = _on_frame_change
    _SAVE_HANDLER = _save_pre_handler
    _LOAD_HANDLER = _load_pre_handler
    _LOAD_POST_HANDLER = _load_post_handler
    _RENDER_HANDLER = _render_pre_handler
    _UNDO_HANDLER = _undo_pre_handler
    bpy.app.handlers.frame_change_post.append(_FRAME_HANDLER)
    bpy.app.handlers.save_pre.append(_SAVE_HANDLER)
    bpy.app.handlers.load_pre.append(_LOAD_HANDLER)
    bpy.app.handlers.load_post.append(_LOAD_POST_HANDLER)
    bpy.app.handlers.render_pre.append(_RENDER_HANDLER)
    bpy.app.handlers.undo_pre.append(_UNDO_HANDLER)
    # addon_utils.enable() uses RestrictBlend: bpy.data.scenes is unavailable
    # here. Scene migration must run after registration or after file loading.
    bpy.app.timers.register(_initialize_scene_settings, first_interval=0.0)


def unregister():
    global _FRAME_HANDLER, _SAVE_HANDLER, _LOAD_HANDLER, _RENDER_HANDLER, _UNDO_HANDLER
    global _LOAD_POST_HANDLER
    global _CLIP_LIST_CACHE, _CLIP_ENUM_ITEMS
    _stop_preview()
    if bpy.app.timers.is_registered(_initialize_scene_settings):
        bpy.app.timers.unregister(_initialize_scene_settings)
    for handlers, callback in (
        (bpy.app.handlers.frame_change_post, _FRAME_HANDLER),
        (bpy.app.handlers.save_pre, _SAVE_HANDLER),
        (bpy.app.handlers.load_pre, _LOAD_HANDLER),
        (bpy.app.handlers.load_post, _LOAD_POST_HANDLER),
        (bpy.app.handlers.render_pre, _RENDER_HANDLER),
        (bpy.app.handlers.undo_pre, _UNDO_HANDLER),
    ):
        if callback is not None and callback in handlers:
            handlers.remove(callback)
    _FRAME_HANDLER = _SAVE_HANDLER = _LOAD_HANDLER = _LOAD_POST_HANDLER = None
    _RENDER_HANDLER = _UNDO_HANDLER = None
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    for name in (
        "ho_humanoid_debug_clip",
        "ho_humanoid_debug_frame",
        "ho_humanoid_debug_progress",
        "ho_humanoid_debug_fps",
        "ho_humanoid_debug_auto_frame_count",
        "ho_humanoid_debug_frame_count",
        "ho_humanoid_debug_loop",
        "ho_humanoid_debug_muscle_scale",
    ):
        delattr(bpy.types.Scene, name)
    _CLIP_LIST_CACHE = None
    _CLIP_ENUM_ITEMS = []
    _CLIP_ENUM_VALUES.clear()
    _CLIP_LEGACY_VALUES.clear()
    anim_parser.clear_clip_cache()
