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


def test_physics_bake_bones() -> None:
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

        manifest = json.loads(
            (temp_root / "BoneBake.hotools-bake.json").read_text(encoding="utf-8")
        )
        actions = manifest["bones"]["actions"]
        assert len(actions) == 1
        action_record = next(iter(actions.values()))
        assert action_record["bone_names"] == ["PhysicalAxis", "PhysicalQuat"]
        assert action_record["frame_start"] == 1
        assert action_record["frame_end"] == 2
        assert "Untouched" not in action_record["bone_names"]
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def main() -> None:
    test_physics_bake_bones()
    print("Physics Bake OmniNode Bone Action: PASS")


if __name__ == "__main__":
    main()
