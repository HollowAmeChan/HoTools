# -*- coding: utf-8 -*-
"""End-to-end Physics Bake incremental PC2 mesh cache regression."""

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
PREFIX = "NodeBakePC2"

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
pc2 = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.bake.pc2"
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
    bpy.context.scene.frame_set(frame)
    world.clear_results("gn_attribute")
    world.frame_context.frame = int(frame)
    world.frame_context.same_frame = False
    world.frame_context.restart_required = False
    for obj in objects:
        values = np.zeros((len(obj.data.vertices), 3), dtype=np.float32)
        values[:, 2] = np.float32(offsets[obj.name] + frame)
        commands.publish_gn_offset_writeback(
            world,
            solver="pc2-node-test",
            slot_id=f"pc2-node-test:{obj.name}",
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
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
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


def _payload_snapshot(paths) -> list[tuple[Path, int, int]]:
    return [(path, path.stat().st_size, path.stat().st_mtime_ns) for path in paths]


def _bake_frame(world, cache_root: Path, objects, offsets, frame: int):
    _publish_frame(world, objects, offsets, frame)
    return physics_nodes.physicsBake(
        world=world,
        cache_directory=str(cache_root),
        file_prefix=PREFIX,
        frame_start=FRAME_START,
        frame_end=FRAME_END,
        bake_bones=False,
        bake_mesh=True,
        use_mesh_cache=True,
    )


def test_physics_bake_node_mesh_stage() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="hotools_physics_pc2_"))
    blend_path = temp_root / "pc2.blend"
    cache_root = temp_root / "cache"
    objects = (
        _make_object("PC2BakeA", 0.0),
        _make_object("PC2BakeB", 4.0),
    )
    offsets = {objects[0].name: 0.0, objects[1].name: 10.0}
    world = world_types.PhysicsWorldCache()
    world.generation = 7

    try:
        physics_bake.reset_geometry_bake_runtime_for_tests()
        for frame in range(FRAME_START, FRAME_END + 1):
            result = _bake_frame(world, cache_root, objects, offsets, frame)
            assert result[0] is world
            assert result[1] == str(cache_root) and result[2] == PREFIX
            assert result[3] == 0 and result[4] == len(objects), result
            for obj in objects:
                modifier = obj.modifiers.get(pc2.PC2_MODIFIER_NAME)
                assert modifier is not None and modifier.type == "MESH_CACHE"
                assert obj.modifiers[-1] == modifier
                assert modifier.cache_format == "PC2"
                assert modifier.forward_axis == "POS_Y" and modifier.up_axis == "POS_Z"
                assert modifier.show_viewport is (frame == FRAME_END)

        assert physics_bake.run_pending_geometry_bake() is False
        assert physics_bake.geometry_bake_is_active() is False
        manifest_path = cache_root / f"{PREFIX}.hotools-bake.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["schema"] == "hotools_physics_bake_v2"
        assert manifest["backend"] == "PC2" and manifest["status"] == "COMPLETE"
        assert len(manifest["targets"]) == len(objects)
        payload_files = sorted(cache_root.glob("*.pc2"))
        assert len(payload_files) == len(objects)
        assert sorted(path.suffix for path in cache_root.iterdir()) == [".json", ".pc2", ".pc2"]
        for record in manifest["targets"].values():
            path = Path(record["file"])
            header = pc2.read_pc2_header(path)
            assert header.vertex_count == 3
            assert header.start_frame == FRAME_START and header.sample_rate == 1.0
            assert header.sample_count == FRAME_END - FRAME_START + 1
            assert path.stat().st_size == pc2.PC2_HEADER.size + 3 * 3 * 12
            assert record["written_frames"] == [1, 2, 3]

        # The completed PC2 modifier must override later live GN values and preserve XYZ.
        for obj in objects:
            gn_offset.write_gn_local_offsets(
                obj,
                np.full((len(obj.data.vertices), 3), 100.0, dtype=np.float32),
            )
        for frame in range(FRAME_START, FRAME_END + 1):
            for obj in objects:
                np.testing.assert_allclose(
                    _positions(obj, frame),
                    _expected(obj, offsets[obj.name] + frame),
                    rtol=0.0,
                    atol=1.0e-6,
                )

        payload_before = _payload_snapshot(payload_files)
        disabled = physics_nodes.physicsBake(
            world, str(cache_root), PREFIX, FRAME_START, FRAME_END,
            False, False, False, True,
        )
        assert disabled[4] == len(objects)
        assert all(not obj.modifiers[pc2.PC2_MODIFIER_NAME].show_viewport for obj in objects)
        assert _payload_snapshot(payload_files) == payload_before

        missing_path = payload_files[-1].with_suffix(".missing")
        payload_files[-1].rename(missing_path)
        failed_enable = physics_nodes.physicsBake(
            world, str(cache_root), PREFIX, FRAME_START, FRAME_END,
            False, False, True, True,
        )
        assert failed_enable[4] == 0
        assert all(not obj.modifiers[pc2.PC2_MODIFIER_NAME].show_viewport for obj in objects)
        missing_path.rename(payload_files[-1])

        enabled = physics_nodes.physicsBake(
            world, str(cache_root), PREFIX, FRAME_START, FRAME_END,
            False, False, True, True,
        )
        assert enabled[4] == len(objects)
        assert all(obj.modifiers[pc2.PC2_MODIFIER_NAME].show_viewport for obj in objects)

        # KEEP preserves both files and playback state.
        bpy.context.scene.frame_set(FRAME_START)
        kept = physics_nodes.clearPhysicsBake(
            world, str(cache_root), PREFIX, FRAME_START, 2, 0, 0, False, False, True
        )
        assert kept[1] == 0 and kept[2] == 0
        assert _payload_snapshot(payload_files) == payload_before
        assert all(obj.modifiers[pc2.PC2_MODIFIER_NAME].show_viewport for obj in objects)

        # Invalidate at frame 2 keeps only frame 1 and disables playback.
        bpy.context.scene.frame_set(2)
        invalidated = physics_nodes.clearPhysicsBake(
            world, str(cache_root), PREFIX, 2, 2, 1, 0, False, False, True
        )
        assert invalidated[2] == len(objects)
        for path in payload_files:
            header = pc2.read_pc2_header(path)
            assert header.sample_count == 1
            assert path.stat().st_size == pc2.PC2_HEADER.size + 3 * 12
        stale = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert stale["status"] == "STALE"
        assert all(
            record["status"] == "STALE"
            and record["written_frames"] == [1]
            and record["stale_from_frame"] == 2
            for record in stale["targets"].values()
        )
        assert all(not obj.modifiers[pc2.PC2_MODIFIER_NAME].show_viewport for obj in objects)

        # Continue from the truncation boundary without rebuilding frame 1.
        for frame in (2, 3):
            result = _bake_frame(world, cache_root, objects, offsets, frame)
            assert result[4] == len(objects)
        resumed = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert resumed["status"] == "COMPLETE"
        assert all(record["written_frames"] == [1, 2, 3] for record in resumed["targets"].values())

        # Absolute PC2 paths and owned modifiers survive a .blend save/reopen.
        assert bpy.ops.wm.save_as_mainfile(
            filepath=str(blend_path), check_existing=False
        ) == {"FINISHED"}
        object_names = tuple(obj.name for obj in objects)
        assert bpy.ops.wm.open_mainfile(filepath=str(blend_path), load_ui=False) == {"FINISHED"}
        objects = tuple(bpy.data.objects[name] for name in object_names)
        for frame in range(FRAME_START, FRAME_END + 1):
            for obj in objects:
                np.testing.assert_allclose(
                    _positions(obj, frame),
                    _expected(obj, offsets[obj.name] + frame),
                    rtol=0.0,
                    atol=1.0e-6,
                )

        # DELETE removes only manifest-owned PC2 files and owned modifiers.
        bpy.context.scene.frame_set(FRAME_START)
        deleted = physics_nodes.clearPhysicsBake(
            world, str(cache_root), PREFIX, FRAME_START, 2, 2, 0, False, False, True
        )
        assert deleted[2] == len(objects)
        assert not list(cache_root.glob("*.pc2"))
        assert all(obj.modifiers.get(pc2.PC2_MODIFIER_NAME) is None for obj in objects)
        repeated = physics_nodes.clearPhysicsBake(
            world, str(cache_root), PREFIX, FRAME_START, 2, 2, 0, False, False, True
        )
        assert repeated[2] == 0
    finally:
        physics_bake.reset_geometry_bake_runtime_for_tests()
        shutil.rmtree(temp_root, ignore_errors=True)


def main() -> None:
    test_physics_bake_node_mesh_stage()
    print("Physics Bake incremental PC2 mesh stage: PASS")


if __name__ == "__main__":
    main()
