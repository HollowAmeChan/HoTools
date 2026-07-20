# -*- coding: utf-8 -*-
"""End-to-end Physics Bake OmniNode mesh stage regression."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types

import bpy
import numpy as np


FRAME_START = 1
FRAME_END = 3
PREFIX = "NodeBake"

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
gn_offset = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.gn_offset"
)
physics_bake = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.bake"
)
physics_nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.nodes"
)


def _make_object(name: str, x_offset: float):
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(
        [
            (-1.0 + x_offset, 0.0, 0.0),
            (1.0 + x_offset, 0.0, 0.0),
            (x_offset, 0.0, 1.0),
        ],
        [],
        [(0, 1, 2)],
    )
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    gn_offset.ensure_gn_offset_output(obj)
    return obj


def _publish_frame(world, objects, offsets, frame: int) -> None:
    world.clear_results("gn_attribute")
    world.frame_context.frame = int(frame)
    world.frame_context.same_frame = False
    world.frame_context.restart_required = False
    for obj in objects:
        values = np.zeros((len(obj.data.vertices), 3), dtype=np.float32)
        values[:, 2] = np.float32(offsets[obj.name] + frame)
        commands.publish_gn_offset_writeback(
            world,
            solver="node-test",
            slot_id=f"node-test:{obj.name}",
            object_ptr=int(obj.as_pointer()),
            object_data_ptr=int(obj.data.as_pointer()),
            frame=frame,
            generation=int(world.generation),
            local_offsets=values,
        )
    returned_world, count = physics_nodes.physicsWriteback(world)
    assert returned_world is world and count == len(objects)


def _positions(obj, frame: int) -> np.ndarray:
    bpy.context.scene.frame_set(frame)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        values = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", values)
        return values.reshape((-1, 3)).copy()
    finally:
        evaluated.to_mesh_clear()


def _expected(obj, z_offset: float) -> np.ndarray:
    values = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
    obj.data.vertices.foreach_get("co", values)
    result = values.reshape((-1, 3)).copy()
    result[:, 2] += np.float32(z_offset)
    return result


def _files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def test_physics_bake_node_mesh_stage() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="hotools_physics_bake_node_"))
    blend_path = temp_root / "node.blend"
    cache_root = temp_root / "cache"
    objects = (
        _make_object("NodeBakeA", 0.0),
        _make_object("NodeBakeB", 4.0),
    )
    offsets = {objects[0].name: 0.0, objects[1].name: 10.0}
    world = world_types.PhysicsWorldCache()
    world.generation = 5
    frame_events = []
    nested_statuses = []
    action_recording_flags = []

    def execute_tree_on_frame(scene, depsgraph=None):
        del depsgraph
        frame = int(scene.frame_current)
        frame_events.append(frame)
        action_recording_flags.append(
            physics_bake.geometry_bake_should_record_actions()
        )
        _publish_frame(world, objects, offsets, frame)
        nested_statuses.append(
            physics_nodes.physicsBake(
                world=world,
                cache_directory=str(cache_root),
                file_prefix=PREFIX,
                frame_start=FRAME_START,
                frame_end=FRAME_END,
                bake_bones=False,
                bake_mesh=True,
                use_mesh_cache=True,
                enabled=True,
            )[3]
        )

    try:
        physics_bake.reset_geometry_bake_runtime_for_tests()
        bpy.context.scene.frame_start = FRAME_START
        bpy.context.scene.frame_end = FRAME_END
        bpy.context.scene.frame_set(FRAME_START)
        _publish_frame(world, objects, offsets, FRAME_START)

        _, _, count, status = physics_nodes.physicsBake(
            world=world,
            cache_directory="//physics_bake",
            file_prefix=PREFIX,
            frame_start=FRAME_START,
            frame_end=FRAME_END,
            bake_bones=False,
            bake_mesh=True,
            use_mesh_cache=True,
        )
        assert count == 0 and "必须先保存" in status
        _, _, count, status = physics_nodes.physicsBake(
            world=world,
            cache_directory=str(cache_root),
            file_prefix=PREFIX,
            frame_start=FRAME_START,
            frame_end=FRAME_END,
            bake_bones=False,
            bake_mesh=False,
            use_mesh_cache=True,
        )
        assert count == 0 and "尚未完成" in status

        assert bpy.ops.wm.save_as_mainfile(
            filepath=str(blend_path),
            check_existing=False,
        ) == {"FINISHED"}

        returned_world, bone_count, target_count, status = physics_nodes.physicsBake(
            world=world,
            cache_directory=str(cache_root),
            file_prefix=PREFIX,
            frame_start=FRAME_START,
            frame_end=FRAME_END,
            bake_bones=False,
            bake_mesh=True,
            use_mesh_cache=True,
        )
        assert returned_world is world
        assert bone_count == 0
        assert target_count == 2
        assert "已排队" in status
        _, _, duplicate_count, duplicate_status = physics_nodes.physicsBake(
            world=world,
            cache_directory=str(cache_root),
            file_prefix=PREFIX,
            frame_start=FRAME_START,
            frame_end=FRAME_END,
            bake_bones=False,
            bake_mesh=True,
            use_mesh_cache=True,
        )
        assert duplicate_count == 2 and "已排队" in duplicate_status
        _, cleared_animations, cleared_meshes, clear_status = physics_nodes.clearPhysicsBake(
            world=world,
            cache_directory=str(cache_root),
            file_prefix=PREFIX,
            clear_frame=FRAME_START,
            animation_clear_mode=2,
            mesh_cache_policy=0,
            finalize_cache_policy=0,
            clear_live_output=False,
            pause_timeline=False,
        )
        assert cleared_animations == 0 and cleared_meshes == 0
        assert "Clear 完成" in clear_status
        assert physics_bake.run_pending_geometry_bake() is False
        _, _, target_count, status = physics_nodes.physicsBake(
            world=world,
            cache_directory=str(cache_root),
            file_prefix=PREFIX,
            frame_start=FRAME_START,
            frame_end=FRAME_END,
            bake_bones=False,
            bake_mesh=True,
            use_mesh_cache=True,
        )
        assert target_count == 2 and "已排队" in status
        bpy.app.handlers.frame_change_post.append(execute_tree_on_frame)
        assert physics_bake.run_pending_geometry_bake() is True
        assert physics_bake.geometry_bake_is_active() is False
        assert any("正在运行" in status for status in nested_statuses), nested_statuses
        assert all(
            "正在运行" in status or "完成" in status
            for status in nested_statuses
        ), nested_statuses
        assert [
            frame
            for index, frame in enumerate(frame_events)
            if index == 0 or frame != frame_events[index - 1]
        ] == [1, 2, 3, 1, 2, 3, 1]
        assert action_recording_flags[:3] == [True, True, True]
        assert action_recording_flags[3:6] == [False, False, False]

        manifest_path = cache_root / f"{PREFIX}.hotools-bake.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "COMPLETE"
        assert manifest["boundary_frame"] == FRAME_START
        assert manifest["boundary_baseline_revision"] == 1
        assert len(manifest["targets"]) == 2
        assert all(record["status"] == "COMPLETE" for record in manifest["targets"].values())
        files_before = [
            (path, path.stat().st_size, path.stat().st_mtime_ns)
            for path in _files(cache_root)
        ]

        bpy.app.handlers.frame_change_post.remove(execute_tree_on_frame)
        assert bpy.ops.wm.save_as_mainfile(
            filepath=str(blend_path),
            check_existing=False,
        ) == {"FINISHED"}
        object_names = tuple(obj.name for obj in objects)
        assert bpy.ops.wm.open_mainfile(filepath=str(blend_path), load_ui=False) == {"FINISHED"}
        objects = tuple(bpy.data.objects[name] for name in object_names)
        assert all(gn_offset.is_gn_offset_cache_enabled(obj) for obj in objects)

        for obj in objects:
            values = np.zeros((len(obj.data.vertices), 3), dtype=np.float32)
            values[:, 2] = 100.0
            gn_offset.write_gn_local_offsets(obj, values)
        for frame in range(FRAME_START, FRAME_END + 1):
            for obj in objects:
                np.testing.assert_allclose(
                    _positions(obj, frame),
                    _expected(obj, offsets[obj.name] + frame),
                    rtol=0.0,
                    atol=1.0e-6,
                )

        # False rearms the trigger and disables playback without touching files.
        _, _, disabled_count, status = physics_nodes.physicsBake(
            world=world,
            cache_directory=str(cache_root),
            file_prefix=PREFIX,
            frame_start=FRAME_START,
            frame_end=FRAME_END,
            bake_bones=False,
            bake_mesh=False,
            use_mesh_cache=False,
        )
        assert disabled_count == 2 and "实时模式" in status
        assert all(not gn_offset.is_gn_offset_cache_enabled(obj) for obj in objects)
        assert files_before == [
            (path, path.stat().st_size, path.stat().st_mtime_ns)
            for path in _files(cache_root)
        ]

        _, _, enabled_count, status = physics_nodes.physicsBake(
            world=world,
            cache_directory=str(cache_root),
            file_prefix=PREFIX,
            frame_start=FRAME_START,
            frame_end=FRAME_END,
            bake_bones=False,
            bake_mesh=False,
            use_mesh_cache=True,
        )
        assert enabled_count == 2 and "正在使用" in status
        assert all(gn_offset.is_gn_offset_cache_enabled(obj) for obj in objects)

        bpy.context.scene.frame_set(FRAME_START)
        payload_files = [path for path in _files(cache_root) if path != manifest_path]
        payload_snapshot = [
            (path, path.stat().st_size, path.stat().st_mtime_ns)
            for path in payload_files
        ]
        _, animation_count, mesh_count, status = physics_nodes.clearPhysicsBake(
            world=world,
            cache_directory=str(cache_root),
            file_prefix=PREFIX,
            clear_frame=FRAME_START,
            animation_clear_mode=2,
            mesh_cache_policy=0,
            finalize_cache_policy=0,
            clear_live_output=False,
            pause_timeline=False,
        )
        assert animation_count == 0 and mesh_count == 0 and "Clear 完成" in status
        assert all(gn_offset.is_gn_offset_cache_enabled(obj) for obj in objects)
        assert payload_snapshot == [
            (path, path.stat().st_size, path.stat().st_mtime_ns)
            for path in payload_files
        ]

        _, _, mesh_count, status = physics_nodes.clearPhysicsBake(
            world=world,
            cache_directory=str(cache_root),
            file_prefix=PREFIX,
            clear_frame=FRAME_START,
            animation_clear_mode=2,
            mesh_cache_policy=1,
            finalize_cache_policy=0,
            clear_live_output=False,
            pause_timeline=False,
        )
        assert mesh_count == 2 and "Mesh 2" in status
        assert all(not gn_offset.is_gn_offset_cache_enabled(obj) for obj in objects)
        assert payload_snapshot == [
            (path, path.stat().st_size, path.stat().st_mtime_ns)
            for path in payload_files
        ]
        stale_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert stale_manifest["status"] == "STALE"
        assert all(
            record["status"] == "STALE"
            and record["stale_from_frame"] == FRAME_START
            for record in stale_manifest["targets"].values()
        )
        _, _, repeated_count, _ = physics_nodes.clearPhysicsBake(
            world=world,
            cache_directory=str(cache_root),
            file_prefix=PREFIX,
            clear_frame=FRAME_START,
            animation_clear_mode=2,
            mesh_cache_policy=1,
            finalize_cache_policy=0,
            clear_live_output=False,
            pause_timeline=False,
        )
        assert repeated_count == 0

        _, _, deleted_count, status = physics_nodes.clearPhysicsBake(
            world=world,
            cache_directory=str(cache_root),
            file_prefix=PREFIX,
            clear_frame=FRAME_START,
            animation_clear_mode=2,
            mesh_cache_policy=2,
            finalize_cache_policy=0,
            clear_live_output=False,
            pause_timeline=False,
        )
        assert deleted_count == 2 and "Mesh 2" in status
        assert not [path for path in _files(cache_root) if path != manifest_path]
        deleted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert deleted_manifest["status"] == "CLEARED"
        assert all(
            record["status"] == "DELETED"
            for record in deleted_manifest["targets"].values()
        )
        _, _, repeated_delete_count, _ = physics_nodes.clearPhysicsBake(
            world=world,
            cache_directory=str(cache_root),
            file_prefix=PREFIX,
            clear_frame=FRAME_START,
            animation_clear_mode=2,
            mesh_cache_policy=2,
            finalize_cache_policy=0,
            clear_live_output=False,
            pause_timeline=False,
        )
        assert repeated_delete_count == 0
    finally:
        if execute_tree_on_frame in bpy.app.handlers.frame_change_post:
            bpy.app.handlers.frame_change_post.remove(execute_tree_on_frame)
        physics_bake.reset_geometry_bake_runtime_for_tests()
        shutil.rmtree(temp_root, ignore_errors=True)


def main() -> None:
    test_physics_bake_node_mesh_stage()
    print("Physics Bake OmniNode mesh stage: PASS")


if __name__ == "__main__":
    main()
