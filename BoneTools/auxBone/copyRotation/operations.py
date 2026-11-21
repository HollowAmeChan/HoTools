"""Undoable copyR commands for currently selected owner bones."""

import bpy
from bpy.types import Operator

from Utils.bone_selection import selected_bone_names
from .core import CopyRotationCore


def _poll(context):
    armature = context.active_object
    return armature is not None and armature.type == "ARMATURE" and armature.mode in {"POSE", "EDIT"} and bool(selected_bone_names(context, armature))


class OP_CopyRGenerate(Operator):
    bl_idname = "ho.copyr_generate"
    bl_label = "创建／更新 copyR"
    bl_description = "让所选已有骨复制指定目标的旋转，立即登记 copyR；保留原骨、静置朝向和权重"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def execute(self, context):
        armature = context.active_object
        names = selected_bone_names(context, armature)
        settings = context.scene.ho_copyr_settings
        old_mode = armature.mode
        try:
            if old_mode == "EDIT":
                bpy.ops.object.mode_set(mode="OBJECT")
            constraints = CopyRotationCore.configure(armature, names, settings.target_bone,
                influence=settings.influence, target_space=settings.target_space, owner_space=settings.owner_space)
        except (ValueError, RuntimeError, TypeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        finally:
            if old_mode == "EDIT" and armature.mode != "EDIT":
                bpy.ops.object.mode_set(mode="EDIT")
        self.report({"INFO"}, "已创建／更新 {} 个 copyR".format(len(constraints)))
        return {"FINISHED"}


class OP_CopyRRemove(Operator):
    bl_idname = "ho.copyr_remove"
    bl_label = "移除 copyR"
    bl_description = "仅移除所选骨的已登记 copyR 约束和身份，保留原骨及权重"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll(context)

    def execute(self, context):
        armature = context.active_object
        names = selected_bone_names(context, armature)
        old_mode = armature.mode
        try:
            if old_mode == "EDIT":
                bpy.ops.object.mode_set(mode="OBJECT")
            count = CopyRotationCore.remove(armature, names)
        except (ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        finally:
            if old_mode == "EDIT" and armature.mode != "EDIT":
                bpy.ops.object.mode_set(mode="EDIT")
        self.report({"INFO"}, "已移除 {} 个 copyR".format(count))
        return {"FINISHED"}
