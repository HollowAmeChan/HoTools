# -*- coding: utf-8 -*-
"""Physics Bake OmniNode Bone Action regression."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types

import bpy
from mathutils import Matrix


TEST_DIR = Path(__file__).resolve().parent
PW_ROOT = TEST_DIR.parent
FUNCTION = PW_ROOT.parent
NODETREE = FUNCTION.parent
OMNINODE = NODETREE.parent
HOTOOLS = OMNINODE.parent

for path in (str(HOTOOLS), str(HOTOOLS.parent)):
    if path not in sys.path:
        sys.path.insert(0, path)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PW_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [str(package_path)]
    module.__package__ = package_name
    sys.modules[package_name] = module

world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)
commands = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.writeback_commands"
)
physics_nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.nodes"
)
node_core = importlib.import_module(
    "HoTools.OmniNode.NodeTree.FunctionNodeCore"
)


def _make_armature():
    data = bpy.data.armatures.new("PhysicsBakeBoneData")
    obj = bpy.data.objects.new("PhysicsBakeRig", data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for index, name in enumerate(("PhysicalQuat", "PhysicalAxis", "Untouched")):
        bone = data.edit_bones.new(name)
        bone.head = (float(index), 0.0, 0.0)
        bone.tail = (float(index), 0.0, 1.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    obj.pose.bones["PhysicalQuat"].rotation_mode = "QUATERNION"
    obj.pose.bones["PhysicalAxis"].rotation_mode = "AXIS_ANGLE"
    obj.pose.bones["Untouched"].rotation_mode = "XYZ"
    return obj


def _publish(world, armature, frame: int) -> None:
    world.clear_results("bone_transform")
    world.frame_context.frame = int(frame)
    world.frame_context.same_frame = False
    world.frame_context.restart_required = False
    matrices = {
        "PhysicalQuat": Matrix.Translation((0.1 * frame, 0.0, 0.0))
        @ Matrix.Rotation(0.15 * frame, 4, "Z"),
        "PhysicalAxis": Matrix.Translation((0.0, 0.2 * frame, 0.0))
        @ Matrix.Rotation(-0.1 * frame, 4, "X"),
    }
    for bone_name, matrix_basis in matrices.items():
        commands.publish_bone_transform_writeback(
            world,
            solver="bone-node-test",
            slot_id=f"bone-node-test:{bone_name}",
            armature_ptr=int(armature.as_pointer()),
            armature_data_ptr=int(armature.data.as_pointer()),
            frame=frame,
            generation=int(world.generation),
            bone_name=bone_name,
            matrix_basis=matrix_basis,
        )
    returned_world, count = physics_nodes.physicsWriteback(world)
    assert returned_world is world and count == 2


def _publish_batch(world, armature, frame: int) -> None:
    world.clear_results("bone_transform")
    world.frame_context.frame = int(frame)
    world.frame_context.same_frame = False
    world.frame_context.restart_required = False
    slot_id = "bone-node-test:batch"
    slot = world.ensure_solver_slot(slot_id, "bone-node-test")
    pose_bones = armature.pose.bones
    names = ("PhysicalQuat", "PhysicalAxis")
    matrices = (
        Matrix.Translation((0.1 * frame, 0.0, 0.0))
        @ Matrix.Rotation(0.15 * frame, 4, "Z"),
        Matrix.Translation((0.0, 0.2 * frame, 0.0))
        @ Matrix.Rotation(-0.1 * frame, 4, "X"),
    )
    slot.data["writeback_plan"] = {
        "armature": armature,
        "batches": [
            {
                "records": [
                    {
                        "bone_name": name,
                        "pose_bone": pose_bones[name],
                        "pose_index": pose_bones.find(name),
                    }
                    for name in names
                ],
                "matrix_bases": list(matrices),
                "target_pose_matrices": [],
                "current_tails": [],
                "source_kind": "test",
                "source_root": "",
            }
        ],
    }
    commands.publish_bone_transform_batch_writeback(
        world,
        solver="bone-node-test",
        slot_id=slot_id,
        armature_ptr=int(armature.as_pointer()),
        armature_data_ptr=int(armature.data.as_pointer()),
        frame=frame,
        generation=int(world.generation),
        bone_count=2,
        plan_schema="test",
    )
    returned_world, count = physics_nodes.physicsWriteback(world)
    assert returned_world is world and count == 2


def _paths(action) -> set[str]:
    return {curve.data_path for curve in action.fcurves}


def _key_frames(action, data_path: str) -> set[int]:
    frames = set()
    for curve in action.fcurves:
        if curve.data_path != data_path:
            continue
        frames.update(int(round(point.co.x)) for point in curve.keyframe_points)
    return frames


def _curve_value(action, data_path: str, array_index: int, frame: int) -> float:
    for curve in action.fcurves:
        if curve.data_path == data_path and curve.array_index == array_index:
            return float(curve.evaluate(frame))
    raise AssertionError((data_path, array_index, frame))


def test_physics_bake_bones() -> None:
    _, input_meta, _, defaults, _, settings = node_core.CheckMetaInfo(
        physics_nodes.clearPhysicsBake
    )
    for identifier, kind in (
        ("animation_clear_mode", "ANIMATION"),
        ("mesh_cache_policy", "MESH"),
        ("finalize_cache_policy", "FINALIZE"),
    ):
        assert input_meta[identifier]["type"] == "OmniNodeSocketPhysicsBakePolicy"
        assert settings[identifier]["policy_kind"] == kind
    assert defaults["animation_clear_mode"] == "SESSION_ALL"
    assert defaults["mesh_cache_policy"] == "KEEP"
    assert defaults["finalize_cache_policy"] == "KEEP"

    temp_root = Path(tempfile.mkdtemp(prefix="hotools_physics_bake_bones_"))
    armature = _make_armature()
    untouched = armature.pose.bones["Untouched"]
    untouched.rotation_euler.z = 0.35
    untouched.keyframe_insert(data_path="rotation_euler", frame=1)
    source_action = armature.animation_data.action
    source_action.name = "UserSourceAction"
    source_paths_before = _paths(source_action)
    world = world_types.PhysicsWorldCache()
    world.generation = 8

    try:
        _publish(world, armature, 1)
        returned, bone_count, mesh_count, status = physics_nodes.physicsBake(
            world=world,
            cache_directory=str(temp_root),
            file_prefix="BoneBake",
            frame_start=1,
            frame_end=10,
            bake_bones=True,
            bake_mesh=False,
            use_mesh_cache=False,
            enabled=True,
        )
        assert returned is world
        assert bone_count == 2 and mesh_count == 0
        assert "Bone Bake：2" in status
        bake_action = armature.animation_data.action
        assert bake_action != source_action
        assert bake_action.name.startswith("BoneBake_PhysicsBakeRig_PhysicsBake_")
        assert _paths(source_action) == source_paths_before

        bake_paths = _paths(bake_action)
        assert 'pose.bones["PhysicalQuat"].location' in bake_paths
        assert 'pose.bones["PhysicalQuat"].rotation_quaternion' in bake_paths
        assert 'pose.bones["PhysicalQuat"].scale' in bake_paths
        assert 'pose.bones["PhysicalAxis"].rotation_axis_angle' in bake_paths
        untouched_paths = {
            path for path in bake_paths
            if path.startswith('pose.bones["Untouched"]')
        }
        assert untouched_paths == {'pose.bones["Untouched"].rotation_euler'}

        _publish_batch(world, armature, 2)
        _, bone_count, _, _ = physics_nodes.physicsBake(
            world=world,
            cache_directory=str(temp_root),
            file_prefix="BoneBake",
            bake_bones=True,
            bake_mesh=False,
            use_mesh_cache=False,
        )
        assert bone_count == 2
        assert armature.animation_data.action == bake_action
        assert _key_frames(
            bake_action,
            'pose.bones["PhysicalQuat"].rotation_quaternion',
        ) == {1, 2}
        assert _key_frames(
            bake_action,
            'pose.bones["PhysicalAxis"].rotation_axis_angle',
        ) == {1, 2}
        assert abs(_curve_value(
            bake_action,
            'pose.bones["PhysicalQuat"].location',
            0,
            1,
        ) - 0.1) <= 1.0e-6
        assert abs(_curve_value(
            bake_action,
            'pose.bones["PhysicalQuat"].location',
            0,
            2,
        ) - 0.2) <= 1.0e-6

        before_counts = {
            (curve.data_path, curve.array_index): len(curve.keyframe_points)
            for curve in bake_action.fcurves
        }
        world.frame_context.same_frame = True
        _, bone_count, _, status = physics_nodes.physicsBake(
            world=world,
            cache_directory=str(temp_root),
            file_prefix="BoneBake",
            bake_bones=True,
            bake_mesh=False,
            use_mesh_cache=False,
        )
        assert bone_count == 0 and "同帧重复" in status
        assert before_counts == {
            (curve.data_path, curve.array_index): len(curve.keyframe_points)
            for curve in bake_action.fcurves
        }

        world.frame_context.same_frame = False
        bpy.context.scene.frame_set(5)
        _, removed, _, status = physics_nodes.clearPhysicsBake(
            world=world,
            cache_directory=str(temp_root),
            file_prefix="BoneBake",
            clear_frame=1,
            animation_clear_mode="TRIGGER_FRAME_ONLY",
            mesh_cache_policy="KEEP",
            finalize_cache_policy="KEEP",
            clear_live_output=True,
            pause_timeline=False,
        )
        assert removed == 0 and "等待清理帧" in status
        assert _key_frames(
            bake_action,
            'pose.bones["PhysicalQuat"].rotation_quaternion',
        ) == {1, 2}

        bpy.context.scene.frame_set(1)
        _publish(world, armature, 1)
        _, removed, mesh_count, status = physics_nodes.clearPhysicsBake(
            world=world,
            cache_directory=str(temp_root),
            file_prefix="BoneBake",
            clear_frame=1,
            animation_clear_mode="TRIGGER_FRAME_ONLY",
            mesh_cache_policy="KEEP",
            finalize_cache_policy="KEEP",
            clear_live_output=True,
            pause_timeline=False,
        )
        assert removed > 0 and mesh_count == 0 and "Clear 完成" in status
        assert _key_frames(
            bake_action,
            'pose.bones["PhysicalQuat"].rotation_quaternion',
        ) == {2}
        assert _key_frames(
            bake_action,
            'pose.bones["PhysicalAxis"].rotation_axis_angle',
        ) == {2}
        assert _paths(source_action) == source_paths_before
        for bone_name in ("PhysicalQuat", "PhysicalAxis"):
            matrix = armature.pose.bones[bone_name].matrix_basis
            difference = max(
                abs(float(matrix[row][column]) - float(row == column))
                for row in range(4)
                for column in range(4)
            )
            assert difference <= 1.0e-6, (bone_name, difference, matrix)

        manifest_path = temp_root / "BoneBake.hotools-bake.json"
        first_clear_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        first_revision = first_clear_manifest["boundary_baseline_revision"]
        _, repeated_removed, _, _ = physics_nodes.clearPhysicsBake(
            world=world,
            cache_directory=str(temp_root),
            file_prefix="BoneBake",
            clear_frame=1,
            animation_clear_mode=0,
            mesh_cache_policy=0,
            finalize_cache_policy=0,
            clear_live_output=True,
            pause_timeline=False,
        )
        repeated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert repeated_removed == 0
        assert repeated_manifest["boundary_baseline_revision"] == first_revision

        bpy.context.scene.frame_set(2)
        _publish_batch(world, armature, 2)
        _, bone_count, _, _ = physics_nodes.physicsBake(
            world=world,
            cache_directory=str(temp_root),
            file_prefix="BoneBake",
            bake_bones=True,
            bake_mesh=False,
            use_mesh_cache=False,
        )
        assert bone_count == 2
        assert _key_frames(
            bake_action,
            'pose.bones["PhysicalQuat"].rotation_quaternion',
        ) == {1, 2}
        assert _key_frames(
            bake_action,
            'pose.bones["PhysicalAxis"].rotation_axis_angle',
        ) == {1, 2}
        assert abs(_curve_value(
            bake_action,
            'pose.bones["PhysicalQuat"].location',
            0,
            1,
        )) <= 1.0e-6
        assert abs(_curve_value(
            bake_action,
            'pose.bones["PhysicalQuat"].location',
            0,
            2,
        ) - 0.2) <= 1.0e-6

        bpy.context.scene.frame_set(3)
        _publish_batch(world, armature, 3)
        physics_nodes.physicsBake(
            world=world,
            cache_directory=str(temp_root),
            file_prefix="BoneBake",
            bake_bones=True,
            bake_mesh=False,
            use_mesh_cache=False,
        )
        assert _key_frames(
            bake_action,
            'pose.bones["PhysicalQuat"].rotation_quaternion',
        ) == {1, 2, 3}
        bpy.context.scene.frame_set(2)
        _publish_batch(world, armature, 2)
        _, removed_from_frame, _, _ = physics_nodes.clearPhysicsBake(
            world=world,
            cache_directory=str(temp_root),
            file_prefix="BoneBake",
            clear_frame=2,
            animation_clear_mode="FROM_CLEAR_FRAME",
            mesh_cache_policy="KEEP",
            finalize_cache_policy="KEEP",
            clear_live_output=True,
            pause_timeline=False,
        )
        assert removed_from_frame > 0
        assert _key_frames(
            bake_action,
            'pose.bones["PhysicalQuat"].rotation_quaternion',
        ) == {1}
        assert armature.animation_data.action == source_action

        bpy.context.scene.frame_set(1)
        _publish(world, armature, 1)
        bake_action_name = bake_action.name
        shared_data = bpy.data.armatures.new("UnexpectedSharedBakeData")
        shared_object = bpy.data.objects.new("UnexpectedSharedBakeUser", shared_data)
        bpy.context.scene.collection.objects.link(shared_object)
        shared_object.animation_data_create().action = bake_action
        _, blocked_count, _, blocked_status = physics_nodes.clearPhysicsBake(
            world=world,
            cache_directory=str(temp_root),
            file_prefix="BoneBake",
            clear_frame=1,
            animation_clear_mode="SESSION_ALL",
            mesh_cache_policy="KEEP",
            finalize_cache_policy="KEEP",
            clear_live_output=True,
            pause_timeline=False,
        )
        assert blocked_count == 0 and "被其他对象共享" in blocked_status
        assert bake_action_name in bpy.data.actions
        shared_object.animation_data.action = None
        bpy.data.objects.remove(shared_object, do_unlink=True)
        bpy.data.armatures.remove(shared_data)
        _, removed, _, _ = physics_nodes.clearPhysicsBake(
            world=world,
            cache_directory=str(temp_root),
            file_prefix="BoneBake",
            clear_frame=1,
            animation_clear_mode=2,
            mesh_cache_policy=0,
            finalize_cache_policy=0,
            clear_live_output=True,
            pause_timeline=False,
        )
        assert removed > 0
        assert armature.animation_data.action == source_action
        assert bake_action_name not in bpy.data.actions
        assert _paths(source_action) == source_paths_before

        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        actions = manifest["bones"]["actions"]
        assert len(actions) == 1
        action_record = next(iter(actions.values()))
        assert action_record["bone_names"] == ["PhysicalAxis", "PhysicalQuat"]
        assert action_record["status"] == "CLEARED"
        assert action_record["frame_end"] == 3
        assert "Untouched" not in action_record["bone_names"]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def main() -> None:
    test_physics_bake_bones()
    print("Physics Bake OmniNode Bone Action: PASS")


if __name__ == "__main__":
    main()
