"""HoAux module state and no-weight deletion operations."""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from .ir.blender_reader import bone_name_from_path
from .generation import iter_hoaux_bones


class HoAuxRemovalBlockedError(RuntimeError):
    pass


def scope_bones(armature_data, pipeline_id="", module_id=""):
    result = []
    for bone in iter_hoaux_bones(armature_data):
        info = bone.hotools_boneprops.hoAux
        if pipeline_id and info.pipelineId != pipeline_id:
            continue
        if module_id and info.moduleId != module_id:
            continue
        result.append(bone)
    return result


def _scope_fcurves(armature_object, bone_names):
    animation_data = armature_object.animation_data
    if animation_data is None:
        return []
    return [
        fcurve
        for fcurve in animation_data.drivers
        if bone_name_from_path(fcurve.data_path) in bone_names
    ]


def set_scope_enabled(armature_object, pipeline_id, module_id, enabled):
    bones = scope_bones(armature_object.data, pipeline_id, module_id)
    bone_names = {bone.name for bone in bones}
    constraint_count = 0
    for bone_name in bone_names:
        pose_bone = armature_object.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        for constraint in pose_bone.constraints:
            constraint.mute = not enabled
            constraint_count += 1
    fcurves = _scope_fcurves(armature_object, bone_names)
    for fcurve in fcurves:
        fcurve.mute = not enabled
    return {
        "bones": len(bones),
        "constraints": constraint_count,
        "drivers": len(fcurves),
    }


def scope_is_enabled(armature_object, pipeline_id, module_id):
    bones = scope_bones(armature_object.data, pipeline_id, module_id)
    bone_names = {bone.name for bone in bones}
    states = []
    for bone_name in bone_names:
        pose_bone = armature_object.pose.bones.get(bone_name)
        if pose_bone is not None:
            states.extend(not constraint.mute for constraint in pose_bone.constraints)
    states.extend(not fcurve.mute for fcurve in _scope_fcurves(armature_object, bone_names))
    return any(states) if states else True


def _external_children(bones, deleting_names):
    result = []
    for bone in bones:
        for child in bone.children:
            if child.name not in deleting_names:
                result.append((bone.name, child.name))
    return result


def _referencing_owners(armature_object, target_names, excluded_owner_names):
    result = []
    for pose_bone in armature_object.pose.bones:
        if pose_bone.name in excluded_owner_names:
            continue
        for constraint in pose_bone.constraints:
            if getattr(constraint, "target", None) == armature_object:
                if getattr(constraint, "subtarget", "") in target_names:
                    result.append(f"{pose_bone.name}:{constraint.name}")
    animation_data = armature_object.animation_data
    if animation_data is not None:
        for fcurve in animation_data.drivers:
            owner_name = bone_name_from_path(fcurve.data_path)
            if owner_name in excluded_owner_names:
                continue
            for variable in fcurve.driver.variables:
                for target in variable.targets:
                    if getattr(target, "id", None) == armature_object:
                        if getattr(target, "bone_target", "") in target_names:
                            result.append(f"{fcurve.data_path}:{variable.name}")
    return result


def _referenced_dir_names(armature_object, owner_names):
    result = set()
    for owner_name in owner_names:
        pose_bone = armature_object.pose.bones.get(owner_name)
        if pose_bone is None:
            continue
        for constraint in pose_bone.constraints:
            if getattr(constraint, "target", None) != armature_object:
                continue
            target_name = getattr(constraint, "subtarget", "")
            target_bone = armature_object.data.bones.get(target_name)
            if target_bone is None:
                continue
            info = getattr(target_bone.hotools_boneprops, "hoAux", None)
            if info is not None and info.isHoAuxBone and info.roleTag == "DIR":
                result.add(target_name)
    for fcurve in _scope_fcurves(armature_object, owner_names):
        for variable in fcurve.driver.variables:
            for target in variable.targets:
                target_name = getattr(target, "bone_target", "")
                target_bone = armature_object.data.bones.get(target_name)
                if target_bone is None:
                    continue
                info = getattr(target_bone.hotools_boneprops, "hoAux", None)
                if info is not None and info.isHoAuxBone and info.roleTag == "DIR":
                    result.add(target_name)
    return result


def _remove_edit_bones(armature_object, bone_names):
    if not bone_names:
        return 0
    armature_data = armature_object.data
    bpy.context.view_layer.objects.active = armature_object
    armature_object.select_set(True)
    if armature_object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.mode_set(mode="EDIT")
    removed = 0
    try:
        for bone_name in bone_names:
            edit_bone = armature_data.edit_bones.get(bone_name)
            if edit_bone is not None:
                armature_data.edit_bones.remove(edit_bone)
                removed += 1
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    return removed


def remove_scope(armature_object, pipeline_id="", module_id=""):
    if armature_object is None or armature_object.type != "ARMATURE":
        raise TypeError("remove_scope requires an Armature object")
    armature_data = armature_object.data
    bones = scope_bones(armature_data, pipeline_id, module_id)
    deleting_names = {bone.name for bone in bones}
    if not deleting_names:
        return {"bones": 0, "drivers": 0, "collections": 0}

    blocked = _external_children(bones, deleting_names)
    if blocked:
        detail = ", ".join(f"{parent}->{child}" for parent, child in blocked)
        raise HoAuxRemovalBlockedError(f"HoAux 骨下存在非删除范围子骨：{detail}")

    references = _referencing_owners(
        armature_object, deleting_names, deleting_names
    )
    if references:
        detail = ", ".join(references)
        raise HoAuxRemovalBlockedError(f"删除范围仍被其他资源使用：{detail}")

    candidate_dirs = _referenced_dir_names(armature_object, deleting_names)

    drivers = _scope_fcurves(armature_object, deleting_names)
    animation_data = armature_object.animation_data
    if animation_data is not None:
        for fcurve in drivers:
            animation_data.drivers.remove(fcurve)

    removed_bones = _remove_edit_bones(armature_object, deleting_names)

    orphan_dirs = {
        bone_name
        for bone_name in candidate_dirs
        if bone_name in armature_data.bones
        and not _referencing_owners(armature_object, {bone_name}, set())
    }
    orphan_bones = [armature_data.bones[name] for name in orphan_dirs]
    blocked_dir_names = {
        parent_name
        for parent_name, _child_name in _external_children(orphan_bones, orphan_dirs)
    }
    orphan_dirs = {
        name
        for name in orphan_dirs
        if name not in blocked_dir_names
    }
    removed_bones += _remove_edit_bones(armature_object, orphan_dirs)

    return {
        "bones": removed_bones,
        "drivers": len(drivers),
        "collections": 0,
    }


class OT_HoAuxToggleModule(Operator):
    bl_idname = "hoaux.toggle_module"
    bl_label = "启用/禁用 HoAux 模块"
    bl_options = {"REGISTER", "UNDO"}

    pipeline_id: StringProperty(default="")  # type: ignore
    module_id: StringProperty(default="")  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        enabled = not scope_is_enabled(context.object, self.pipeline_id, self.module_id)
        result = set_scope_enabled(
            context.object, self.pipeline_id, self.module_id, enabled
        )
        state = "启用" if enabled else "禁用"
        self.report({"INFO"}, f"已{state} {result['bones']} 根骨")
        return {"FINISHED"}


class OT_HoAuxRemoveModule(Operator):
    bl_idname = "hoaux.remove_module"
    bl_label = "删除 HoAux 模块"
    bl_options = {"REGISTER", "UNDO"}

    pipeline_id: StringProperty(default="")  # type: ignore
    module_id: StringProperty(default="")  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        try:
            result = remove_scope(context.object, self.pipeline_id, self.module_id)
        except HoAuxRemovalBlockedError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"已删除 {result['bones']} 根 HoAux 骨")
        return {"FINISHED"}


class OT_HoAuxRemoveAll(Operator):
    bl_idname = "hoaux.remove_all"
    bl_label = "删除全部 HoAux"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "ARMATURE"

    def execute(self, context):
        try:
            result = remove_scope(context.object)
        except HoAuxRemovalBlockedError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"已删除 {result['bones']} 根 HoAux 骨")
        return {"FINISHED"}


CLASSES = (OT_HoAuxToggleModule, OT_HoAuxRemoveModule, OT_HoAuxRemoveAll)
