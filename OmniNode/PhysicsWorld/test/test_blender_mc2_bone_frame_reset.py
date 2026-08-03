"""Regression test for MC2 restart input after unified PoseBone writeback reset."""

from __future__ import annotations

import os
import sys
import types

import bpy
from mathutils import Matrix


HOTOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", os.path.join(HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.Function", os.path.join(HOTOOLS, "OmniNode", "Function")),
    ("HoTools.OmniNode.PhysicsWorld", os.path.join(HOTOOLS, "OmniNode", "PhysicsWorld")),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module

from HoTools.OmniNode.PhysicsWorld.mc2.setups.bone_frame_input import (
    _resolve_mc2_bone_source_basis,
)


def _is_identity(matrix) -> bool:
    identity = Matrix.Identity(4)
    return all(abs(matrix[row][column] - identity[row][column]) < 1e-6
               for row in range(4) for column in range(4))


def test_restart_rebuilds_from_matrix_basis() -> None:
    armature_data = bpy.data.armatures.new("MC2RestartTestData")
    armature = bpy.data.objects.new("MC2RestartTestArmature", armature_data)
    bpy.context.scene.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    root = armature_data.edit_bones.new("Root")
    root.head = (0, 0, 0)
    root.tail = (0, 1, 0)
    child = armature_data.edit_bones.new("Child")
    child.head = (0, 1, 0)
    child.tail = (0, 2, 0)
    child.parent = root
    bpy.ops.object.mode_set(mode="POSE")

    pose_bone = armature.pose.bones["Child"]
    pose_bone.matrix_basis = Matrix.Rotation(0.5, 4, "Z")
    world = types.SimpleNamespace(
        backend_resources={},
        frame_context=types.SimpleNamespace(restart_required=True),
        generation=1,
    )
    result = _resolve_mc2_bone_source_basis(
        world, armature.as_pointer(), pose_bone
    )
    assert result is not None and _is_identity(result)

    state = world.backend_resources["mc2.bone.frame_state"]
    entry = state["bones"][(armature.as_pointer(), "Child")]
    entry["source_basis"] = Matrix.Translation((2, 0, 0))
    entry["expected_writeback_basis"] = Matrix.Rotation(0.75, 4, "Z")
    pose_bone.matrix_basis = Matrix.Identity(4)
    result = _resolve_mc2_bone_source_basis(
        world, armature.as_pointer(), pose_bone
    )
    assert _is_identity(result)
    print("PASS test_restart_rebuilds_from_matrix_basis")


test_restart_rebuilds_from_matrix_basis()
