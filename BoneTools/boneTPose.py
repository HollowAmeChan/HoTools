"""Humanoid T-Pose reference-pose authoring and preview."""

import bpy
from bpy.app.handlers import persistent
from bpy.types import Operator
from mathutils import Matrix, Vector
from Exporter.HumanoidMappingExporter import HumanoidMappingExporter


_PREVIEW_STATES = {}
_IDENTITY_MATRIX = Matrix.Identity(4)
_IDENTITY_VALUES = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)
_ARM_SLOTS = ("shoulder", "upper_arm", "lower_arm", "hand")


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


def _mapping_to_bone(armature):
    result = {}
    layout_slots = {
        "Hips": "hips",
        "Spine": "spine",
        "Chest": "chest",
        "UpperChest": "upperchest",
        "Neck": "neck",
        "Head": "head",
        "LeftShoulder": "shoulder.L",
        "RightShoulder": "shoulder.R",
        "LeftUpperArm": "upper_arm.L",
        "RightUpperArm": "upper_arm.R",
        "LeftLowerArm": "lower_arm.L",
        "RightLowerArm": "lower_arm.R",
        "LeftHand": "hand.L",
        "RightHand": "hand.R",
    }
    for bone in armature.data.bones:
        props = getattr(bone, "hotools_boneprops", None)
        mapping = getattr(props, "humanoidMapping", "").strip() if props else ""
        if not mapping:
            continue
        human_name = HumanoidMappingExporter.to_unity_human_name(mapping)
        slot = layout_slots.get(human_name, mapping)
        if slot not in result:
            result[slot] = bone.name
    return result


def _project_to_plane(vector, normal):
    return vector - normal * vector.dot(normal)


def _normalised(vector):
    return vector.normalized() if vector.length > 1e-6 else None


def _auto_arm_directions(armature):
    mapping = _mapping_to_bone(armature)
    data_bones = armature.data.bones

    def bone_for(slot):
        name = mapping.get(slot)
        return data_bones.get(name) if name else None

    hips = bone_for("hips")
    head = bone_for("head")
    chest = bone_for("chest")
    spine = bone_for("spine")
    if hips is not None:
        body_center = hips.head_local.copy()
    elif chest is not None:
        body_center = chest.head_local.copy()
    else:
        body_center = Vector((0.0, 0.0, 0.0))

    up = None
    if hips is not None and head is not None:
        up = _normalised(head.head_local - hips.head_local)
    if up is None and hips is not None and chest is not None:
        up = _normalised(chest.head_local - hips.head_local)
    if up is None and spine is not None:
        up = _normalised(spine.tail_local - spine.head_local)
    if up is None and hips is not None:
        up = _normalised(hips.tail_local - hips.head_local)
    if up is None:
        up = Vector((0.0, 0.0, 1.0))

    left_anchor = bone_for("shoulder.L")
    right_anchor = bone_for("shoulder.R")
    if left_anchor is None:
        left_anchor = bone_for("upper_arm.L")
    if right_anchor is None:
        right_anchor = bone_for("upper_arm.R")
    lateral = None
    if left_anchor is not None and right_anchor is not None:
        lateral = _normalised(_project_to_plane(
            right_anchor.head_local - left_anchor.head_local,
            up,
        ))

    directions = {}
    for side in ("L", "R"):
        if lateral is not None:
            outward = -lateral if side == "L" else lateral
        else:
            anchor = bone_for(f"shoulder.{side}")
            if anchor is None:
                anchor = bone_for(f"upper_arm.{side}")
            outward = None
            if anchor is not None:
                outward = _normalised(_project_to_plane(
                    anchor.head_local - body_center,
                    up,
                ))

        if outward is None:
            upper_arm = bone_for(f"upper_arm.{side}")
            if upper_arm is not None:
                outward = _normalised(_project_to_plane(
                    upper_arm.tail_local - upper_arm.head_local,
                    up,
                ))
        if outward is None:
            continue

        for slot in _ARM_SLOTS:
            name = mapping.get(f"{slot}.{side}")
            if name and name in armature.pose.bones:
                directions[name] = outward.copy()

    return directions


def _align_bone_to_direction(pose_bone, target):
    head = pose_bone.head.copy()
    direction = pose_bone.tail - head
    current = _normalised(direction)
    if current is None:
        return False
    delta = current.rotation_difference(target)
    pivot = Matrix.Translation(head)
    desired = (
        pivot
        @ delta.to_matrix().to_4x4()
        @ Matrix.Translation(-head)
        @ pose_bone.matrix.copy()
    )
    pose_bone.matrix = desired
    bpy.context.view_layer.update()
    return True


def _generate_auto_tpose(armature, directions):
    if not directions:
        raise ValueError("没有可用于自动 T-Pose 的 Humanoid 手臂映射")
    mapping = _mapping_to_bone(armature)
    _clear_pose_channels(armature)
    for slot in _ARM_SLOTS:
        for side in ("L", "R"):
            name = mapping.get(f"{slot}.{side}")
            pose_bone = armature.pose.bones.get(name) if name else None
            if pose_bone is None:
                continue
            target = directions.get(name)
            if target is not None:
                _align_bone_to_direction(pose_bone, target)


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
    bl_description = "按 Humanoid 映射将肩、上臂、前臂和手水平外展；结果进入预览，可微调后保存"

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def execute(self, context):
        armature = _armature(context)
        directions = _auto_arm_directions(armature)
        if not directions:
            self.report({"ERROR"}, "需要至少一侧有效的 Humanoid 手臂映射")
            return {"CANCELLED"}
        try:
            _begin_preview(armature)
            _generate_auto_tpose(armature, directions)
        except Exception as error:
            if is_previewing(armature):
                _restore_preview(armature)
            self.report({"ERROR"}, f"自动 T-Pose 失败：{error}")
            return {"CANCELLED"}
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


def draw_tpose_row(layout, armature):
    row = layout.row(align=True)
    row.label(text="T-Pose")
    previewing = is_previewing(armature)
    row.operator(
        OT_HumanoidTPosePreview.bl_idname,
        text="",
        icon="PAUSE" if previewing else "PLAY",
        depress=previewing,
    )
    row.operator(OT_HumanoidTPoseSave.bl_idname, text="", icon="FILE_TICK")
    row.operator(OT_HumanoidTPoseAuto.bl_idname, text="", icon="ARMATURE_DATA")
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
