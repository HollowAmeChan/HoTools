"""Rollback support for HoAux generation transactions."""

import bpy

from .collection_registry import prune_empty_system_collections


def restore_armature_mode(obj, desired_mode):
    if obj.mode == desired_mode:
        return
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    if obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    if desired_mode != "OBJECT":
        bpy.ops.object.mode_set(mode=desired_mode)


class GenerationTransaction:
    def __init__(self, armature_object):
        self.armature_object = armature_object
        self.original_mode = armature_object.mode
        self.created_bones = []
        self.created_constraints = []
        self.created_drivers = []
        self._committed = False

    def track_bone(self, bone_name):
        self.created_bones.append(bone_name)

    def track_constraint(self, owner_name, constraint):
        self.created_constraints.append((owner_name, constraint))

    def track_driver(self, fcurve):
        self.created_drivers.append(fcurve)

    def commit(self):
        self._committed = True

    def rollback(self):
        obj = self.armature_object
        animation_data = obj.animation_data
        if animation_data is not None:
            for fcurve in reversed(self.created_drivers):
                try:
                    animation_data.drivers.remove(fcurve)
                except (ReferenceError, RuntimeError):
                    pass

        for owner_name, constraint in reversed(self.created_constraints):
            pose_bone = obj.pose.bones.get(owner_name)
            if pose_bone is None:
                continue
            try:
                pose_bone.constraints.remove(constraint)
            except (ReferenceError, RuntimeError):
                pass

        if self.created_bones:
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            if obj.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="EDIT")
            try:
                for bone_name in reversed(self.created_bones):
                    edit_bone = obj.data.edit_bones.get(bone_name)
                    if edit_bone is not None:
                        obj.data.edit_bones.remove(edit_bone)
            finally:
                bpy.ops.object.mode_set(mode="OBJECT")
        prune_empty_system_collections(obj.data)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if not self._committed:
                self.rollback()
        finally:
            self.restore_original_mode()
        return False

    def restore_original_mode(self):
        restore_armature_mode(self.armature_object, self.original_mode)
