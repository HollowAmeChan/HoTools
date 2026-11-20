"""Humanoid T-Pose reference-pose authoring and preview."""

import bpy
from bpy.app.handlers import persistent
from bpy.types import Operator
from mathutils import Matrix
from . import humanoid_tpose_solver


_PREVIEW_STATES = {}
_IDENTITY_MATRIX = Matrix.Identity(4)
_IDENTITY_VALUES = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


def _armature(context):
    obj = getattr(context, "active_object", None)
    return obj if obj is not None and obj.type == "ARMATURE" else None


def _preview_key(armature):
    return armature.as_pointer()


def is_previewing(armature):
    return armature is not None and _preview_key(armature) in _PREVIEW_STATES


def _matrix_values(matrix):
    return tuple(float(matrix[row][column]) for row in range(4) for column in range(4))


def _matrix_from_values(values):
    return Matrix(tuple(
        tuple(float(values[row * 4 + column]) for column in range(4))
        for row in range(4)
    ))


def _bone_props(pose_bone):
    return getattr(getattr(pose_bone, "bone", None), "hotools_boneprops", None)


def cached_bone_count(armature):
    if armature is None or armature.type != "ARMATURE":
        return 0
    return sum(
        bool(getattr(_bone_props(pose_bone), "humanoidTPoseCached", False))
        for pose_bone in armature.pose.bones
    )


def _capture_preview_state(armature):
    animation_data = armature.animation_data
    return {
        "object": armature,
        "pose_position": armature.data.pose_position,
        "basis": {
            pose_bone.name: pose_bone.matrix_basis.copy()
            for pose_bone in armature.pose.bones
        },
        "constraints": [
            (constraint, bool(constraint.mute))
            for pose_bone in armature.pose.bones
            for constraint in pose_bone.constraints
        ],
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
    }


def _suspend_pose_inputs(armature, state):
    animation_data = state["animation_data"]
    if animation_data is not None:
        if state["action"] is not None:
            animation_data.action = None
        if state["use_nla"] is not None:
            animation_data.use_nla = False
        for track, _was_muted in state["nla_tracks"]:
            track.mute = True
        for driver, _was_muted in state["drivers"]:
            driver.mute = True
    for constraint, _was_muted in state["constraints"]:
        constraint.mute = True
    bpy.context.view_layer.update()


def _restore_preview(armature):
    key = _preview_key(armature)
    state = _PREVIEW_STATES.pop(key, None)
    if state is None:
        return False

    animation_data = state["animation_data"]
    if animation_data is not None:
        try:
            animation_data.action = state["action"]
            action_slot = state["action_slot"]
            if action_slot is not None and hasattr(animation_data, "action_slot"):
                animation_data.action_slot = action_slot
            if state["use_nla"] is not None:
                animation_data.use_nla = state["use_nla"]
        except (AttributeError, ReferenceError, TypeError, ValueError, RuntimeError):
            pass
        for track, was_muted in state["nla_tracks"]:
            try:
                track.mute = was_muted
            except (ReferenceError, RuntimeError):
                pass
        for driver, was_muted in state["drivers"]:
            try:
                driver.mute = was_muted
            except (ReferenceError, RuntimeError):
                pass
    for constraint, was_muted in state["constraints"]:
        try:
            constraint.mute = was_muted
        except (ReferenceError, RuntimeError):
            pass

    for pose_bone in armature.pose.bones:
        basis = state["basis"].get(pose_bone.name)
        if basis is not None:
            pose_bone.matrix_basis = basis
    armature.data.pose_position = state["pose_position"]
    bpy.context.view_layer.update()
    return True


def _begin_preview(armature):
    key = _preview_key(armature)
    if key in _PREVIEW_STATES:
        return False
    state = _capture_preview_state(armature)
    _PREVIEW_STATES[key] = state
    try:
        _suspend_pose_inputs(armature, state)
        armature.data.pose_position = "POSE"
        bpy.context.view_layer.update()
    except Exception:
        _restore_preview(armature)
        raise
    return True


def _clear_pose_channels(armature):
    for pose_bone in armature.pose.bones:
        pose_bone.matrix_basis = _IDENTITY_MATRIX
    bpy.context.view_layer.update()


def _apply_cached_pose(armature):
    count = 0
    _clear_pose_channels(armature)
    for pose_bone in armature.pose.bones:
        props = _bone_props(pose_bone)
        if props is None or not props.humanoidTPoseCached:
            continue
        pose_bone.matrix_basis = _matrix_from_values(props.humanoidTPoseMatrixBasis)
        count += 1
    bpy.context.view_layer.update()
    return count


def _save_current_pose(armature):
    bpy.context.view_layer.update()
    pose_matrices = {
        pose_bone.name: pose_bone.matrix.copy()
        for pose_bone in armature.pose.bones
    }
    count = 0
    for pose_bone in armature.pose.bones:
        props = _bone_props(pose_bone)
        if props is None:
            continue
        parent = pose_bone.parent
        matrix_basis = pose_bone.bone.convert_local_to_pose(
            matrix=pose_matrices[pose_bone.name],
            matrix_local=pose_bone.bone.matrix_local,
            parent_matrix=pose_matrices[parent.name] if parent else Matrix.Identity(4),
            parent_matrix_local=parent.bone.matrix_local if parent else Matrix.Identity(4),
            invert=True,
        )
        props.humanoidTPoseMatrixBasis = _matrix_values(matrix_basis)
        props.humanoidTPoseCached = True
        count += 1
    return count


def _clear_calibration(armature):
    count = 0
    for pose_bone in armature.pose.bones:
        props = _bone_props(pose_bone)
        if props is None or not props.humanoidTPoseCached:
            continue
        props.humanoidTPoseCached = False
        props.humanoidTPoseMatrixBasis = _IDENTITY_VALUES
        count += 1
    return count


def _generate_auto_tpose(armature):
    _clear_pose_channels(armature)
    return humanoid_tpose_solver.generate(armature)


class OT_HumanoidTPosePreview(Operator):
    bl_idname = "ho.humanoid_tpose_preview"
    bl_label = "预览 T-Pose"
    bl_description = "切换已保存的 T-Pose 预览；关闭时恢复进入预览前的姿态和动画状态"

    @classmethod
    def poll(cls, context):
        armature = _armature(context)
        return armature is not None and (
            is_previewing(armature) or cached_bone_count(armature) > 0
        )

    def execute(self, context):
        armature = _armature(context)
        if is_previewing(armature):
            _restore_preview(armature)
            return {"FINISHED"}

        try:
            _begin_preview(armature)
            count = _apply_cached_pose(armature)
            if count == 0:
                _restore_preview(armature)
                self.report({"ERROR"}, "当前骨架没有已保存的 T-Pose 标定")
                return {"CANCELLED"}
        except Exception as error:
            if is_previewing(armature):
                _restore_preview(armature)
            self.report({"ERROR"}, f"T-Pose 预览失败：{error}")
            return {"CANCELLED"}
        return {"FINISHED"}


class OT_HumanoidTPoseSave(Operator):
    bl_idname = "ho.humanoid_tpose_save"
    bl_label = "保存当前为 T-Pose"
    bl_description = "将当前骨架所有骨骼的姿态变换保存为 T-Pose 标定"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def execute(self, context):
        count = _save_current_pose(_armature(context))
        self.report({"INFO"}, f"已保存 {count} 根骨骼的 T-Pose 标定")
        return {"FINISHED"}


class OT_HumanoidTPoseAuto(Operator):
    bl_idname = "ho.humanoid_tpose_auto"
    bl_label = "自动生成 T-Pose"
    bl_description = "按 Unity Humanoid 的方向与容差校正全身、手掌和手指；结果进入预览，可微调后保存"

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def execute(self, context):
        armature = _armature(context)
        if not humanoid_tpose_solver.mapped_bones(armature):
            self.report({"ERROR"}, "需要有效的 Humanoid 骨骼映射")
            return {"CANCELLED"}
        try:
            _begin_preview(armature)
            errors = _generate_auto_tpose(armature)
        except Exception as error:
            if is_previewing(armature):
                _restore_preview(armature)
            self.report({"ERROR"}, f"自动 T-Pose 失败：{error}")
            return {"CANCELLED"}
        if errors["total"] > .01:
            names = "、".join(errors["bones"])
            if errors["position"] > .01:
                names = (names + "、" if names else "") + "骨盆位置"
            self.report({"WARNING"}, "已生成 T-Pose 候选，仍需检查：" + names)
        else:
            self.report({"INFO"}, "已生成 T-Pose 候选；可微调后保存当前姿态")
        return {"FINISHED"}


class OT_HumanoidTPoseClearPose(Operator):
    bl_idname = "ho.humanoid_tpose_clear_pose"
    bl_label = "清除当前姿态"
    bl_description = "退出 T-Pose 预览（如正在预览），然后将当前骨架所有姿态变换重置为静置姿态"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def execute(self, context):
        armature = _armature(context)
        if is_previewing(armature):
            _restore_preview(armature)
        _clear_pose_channels(armature)
        self.report({"INFO"}, "已重置当前姿态；T-Pose 标定已保留")
        return {"FINISHED"}


class OT_HumanoidTPoseClearCalibration(Operator):
    bl_idname = "ho.humanoid_tpose_clear_calibration"
    bl_label = "清除 T-Pose 标定"
    bl_description = "退出预览（如正在预览），并删除已保存的 T-Pose 标定"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def execute(self, context):
        armature = _armature(context)
        if is_previewing(armature):
            _restore_preview(armature)
        count = _clear_calibration(armature)
        self.report({"INFO"}, f"已清除 {count} 根骨骼的 T-Pose 标定")
        return {"FINISHED"}


_CLASSES = (
    OT_HumanoidTPosePreview,
    OT_HumanoidTPoseSave,
    OT_HumanoidTPoseAuto,
    OT_HumanoidTPoseClearPose,
    OT_HumanoidTPoseClearCalibration,
)


def draw_tpose_row(layout:bpy.types.UILayout, armature):
    row = layout.row(align=True)
    previewing = is_previewing(armature)
    row.operator(
        OT_HumanoidTPosePreview.bl_idname,
        text="预览Tpose",
        icon="PAUSE" if previewing else "PLAY",
        depress=previewing,
    )
    row.operator(OT_HumanoidTPoseSave.bl_idname, text="保存Tpose", icon="FILE_TICK")
    row.operator(OT_HumanoidTPoseAuto.bl_idname, text="自动Tpose", icon="ARMATURE_DATA")
    row.operator(
        OT_HumanoidTPoseClearPose.bl_idname,
        text="",
        icon="LOOP_BACK",
    )
    row.operator(
        OT_HumanoidTPoseClearCalibration.bl_idname,
        text="",
        icon="TRASH",
    )
    row.enabled = armature is not None and armature.type == "ARMATURE"


@persistent
def _restore_previews_before_file_change(_unused):
    for state in list(_PREVIEW_STATES.values()):
        try:
            _restore_preview(state["object"])
        except (ReferenceError, RuntimeError):
            pass


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    if _restore_previews_before_file_change not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_restore_previews_before_file_change)
    if _restore_previews_before_file_change not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_restore_previews_before_file_change)
    if _restore_previews_before_file_change not in bpy.app.handlers.undo_pre:
        bpy.app.handlers.undo_pre.append(_restore_previews_before_file_change)
    if _restore_previews_before_file_change not in bpy.app.handlers.redo_pre:
        bpy.app.handlers.redo_pre.append(_restore_previews_before_file_change)


def unregister():
    _restore_previews_before_file_change(None)
    if _restore_previews_before_file_change in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(_restore_previews_before_file_change)
    if _restore_previews_before_file_change in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_restore_previews_before_file_change)
    if _restore_previews_before_file_change in bpy.app.handlers.undo_pre:
        bpy.app.handlers.undo_pre.remove(_restore_previews_before_file_change)
    if _restore_previews_before_file_change in bpy.app.handlers.redo_pre:
        bpy.app.handlers.redo_pre.remove(_restore_previews_before_file_change)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
