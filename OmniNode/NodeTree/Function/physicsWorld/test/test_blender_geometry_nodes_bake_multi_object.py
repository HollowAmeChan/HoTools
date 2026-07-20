# -*- coding: utf-8 -*-
"""Multi-object Geometry Nodes Bake probe for the shared physics output group.

Usage:
    blender.exe --factory-startup --background --python test_blender_geometry_nodes_bake_multi_object.py
"""

from __future__ import annotations

import importlib
from pathlib import Path
import shutil
import sys
import tempfile
import types

import bpy
import numpy as np


ATTRIBUTE_NAME = "hotools_physics_offset"
FRAME_START = 1
FRAME_END = 3

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

gn_offset = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.gn_offset"
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


def _write_offset(obj, value: float) -> None:
    attribute = obj.data.attributes[ATTRIBUTE_NAME]
    values = np.zeros((len(obj.data.vertices), 3), dtype=np.float32)
    values[:, 2] = np.float32(value)
    attribute.data.foreach_set("vector", values.reshape(-1))
    obj.data.update()
    obj.update_tag()


def _positions(obj, frame: int) -> np.ndarray:
    bpy.context.scene.frame_set(frame)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    if mesh is None:
        raise AssertionError("evaluated mesh is missing")
    try:
        values = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", values)
        return values.reshape((-1, 3)).copy()
    finally:
        evaluated.to_mesh_clear()


def _expected(obj, z_offset: float) -> np.ndarray:
    base = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
    obj.data.vertices.foreach_get("co", base)
    result = base.reshape((-1, 3)).copy()
    result[:, 2] += np.float32(z_offset)
    return result


def _files(path: Path) -> list[Path]:
    return sorted(item for item in path.rglob("*") if item.is_file())


def _select_objects(objects) -> None:
    for candidate in bpy.context.selected_objects:
        candidate.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def test_multi_object_bake_with_separate_owned_caches() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="hotools_gn_bake_multi_"))
    blend_path = temp_root / "multi.blend"
    objects = (
        _make_object("PhysicsBakeA", 0.0),
        _make_object("PhysicsBakeB", 4.0),
    )
    object_offsets = {
        objects[0].name: 0.0,
        objects[1].name: 10.0,
    }
    bake_dirs = {
        obj.name: temp_root / "bake" / obj.name
        for obj in objects
    }
    frame_events: list[int] = []
    bake_events: dict[str, list[int]] = {}

    def write_all_offsets(scene, depsgraph=None):
        del depsgraph
        frame = int(scene.frame_current)
        frame_events.append(frame)
        for name, base_offset in object_offsets.items():
            obj = bpy.data.objects.get(name)
            if obj is not None:
                _write_offset(obj, base_offset + frame)

    try:
        for obj in objects:
            directory = bake_dirs[obj.name]
            directory.mkdir(parents=True, exist_ok=True)
            modifier, entry = gn_offset.configure_gn_offset_disk_bake(
                obj,
                str(directory),
                FRAME_START,
                FRAME_END,
            )
            assert entry.node == gn_offset.get_gn_offset_bake_node(modifier.node_group)
            live_modifier = obj.modifiers.get("HoTools 物理后置位移")
            assert obj.modifiers.find(live_modifier.name) + 1 == obj.modifiers.find(modifier.name)
            assert gn_offset.is_gn_offset_cache_enabled(obj) is False
            gn_offset.set_gn_offset_cache_enabled(obj, True)
            assert int(entry.bake_id) > 0

        _select_objects(objects)
        bpy.context.scene.frame_start = FRAME_START
        bpy.context.scene.frame_end = FRAME_END
        bpy.context.scene.frame_set(FRAME_START)
        for obj in objects:
            _write_offset(obj, object_offsets[obj.name] + FRAME_START)
        bpy.app.handlers.frame_change_post.append(write_all_offsets)

        result = bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)
        assert result == {"FINISHED"}
        frame_events.clear()
        # Blender's public API bakes ordinary Bake nodes one modifier at a time.
        # The similarly named simulation_nodes_cache_bake operator only handles
        # Simulation Zones and intentionally does not cover GeometryNodeBake.
        for obj in objects:
            frame_events.clear()
            modifier = obj.modifiers["HoTools 物理网格缓存"]
            entry = gn_offset.get_gn_offset_bake_entry(modifier)
            modifier_name, bake_id = modifier.name, int(entry.bake_id)
            result = bpy.ops.object.geometry_node_bake_single(
                session_uid=int(obj.session_uid),
                modifier_name=modifier_name,
                bake_id=bake_id,
            )
            print("Geometry Nodes Bake target:", obj.name, modifier_name, bake_id, result)
            assert result == {"FINISHED"}, result
            distinct_events = [
                frame
                for index, frame in enumerate(frame_events)
                if index == 0 or frame != frame_events[index - 1]
            ]
            assert distinct_events == list(range(FRAME_START, FRAME_END + 1)), frame_events
            bake_events[obj.name] = distinct_events
            assert int(bpy.context.scene.frame_current) == FRAME_START

        for obj in objects:
            files = _files(bake_dirs[obj.name])
            assert files, f"{obj.name} has no disk bake"
            assert all(str(path).startswith(str(bake_dirs[obj.name])) for path in files)

        # Both modifiers must ignore later live writes while using their own baked geometry.
        for obj in objects:
            _write_offset(obj, 100.0 + object_offsets[obj.name])
        for frame in range(FRAME_START, FRAME_END + 1):
            for obj in objects:
                np.testing.assert_allclose(
                    _positions(obj, frame),
                    _expected(obj, object_offsets[obj.name] + frame),
                    rtol=0.0,
                    atol=1.0e-6,
                )

        bpy.app.handlers.frame_change_post.remove(write_all_offsets)

        # Cache playback is independent per object and does not mutate files.
        first, second = objects
        first_files = [(path, path.stat().st_size) for path in _files(bake_dirs[first.name])]
        gn_offset.set_gn_offset_cache_enabled(first, False)
        _write_offset(first, 50.0)
        np.testing.assert_allclose(
            _positions(first, FRAME_START),
            _expected(first, 50.0),
            rtol=0.0,
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            _positions(second, FRAME_START),
            _expected(second, object_offsets[second.name] + FRAME_START),
            rtol=0.0,
            atol=1.0e-6,
        )
        assert first_files == [(path, path.stat().st_size) for path in _files(bake_dirs[first.name])]
        gn_offset.set_gn_offset_cache_enabled(first, True)
        np.testing.assert_allclose(
            _positions(first, FRAME_START),
            _expected(first, FRAME_START),
            rtol=0.0,
            atol=1.0e-6,
        )

        for index, obj in enumerate(objects):
            modifier = obj.modifiers["HoTools 物理网格缓存"]
            entry = gn_offset.get_gn_offset_bake_entry(modifier)
            modifier_name, bake_id = modifier.name, int(entry.bake_id)
            result = bpy.ops.object.geometry_node_bake_delete_single(
                session_uid=int(obj.session_uid),
                modifier_name=modifier_name,
                bake_id=bake_id,
            )
            assert result == {"FINISHED"}, result
            gn_offset.set_gn_offset_cache_enabled(obj, False)
            assert not _files(bake_dirs[obj.name])
            for untouched in objects[index + 1 :]:
                assert _files(bake_dirs[untouched.name]), (
                    f"deleting {obj.name} also deleted {untouched.name}'s cache"
                )

            _write_offset(obj, 50.0 + object_offsets[obj.name])
            np.testing.assert_allclose(
                _positions(obj, FRAME_START),
                _expected(obj, 50.0 + object_offsets[obj.name]),
                rtol=0.0,
                atol=1.0e-6,
            )

        print(
            "Geometry Nodes per-object Bake events:",
            bake_events,
            "directories:",
            [str(path) for path in bake_dirs.values()],
        )
    finally:
        if write_all_offsets in bpy.app.handlers.frame_change_post:
            bpy.app.handlers.frame_change_post.remove(write_all_offsets)
        shutil.rmtree(temp_root, ignore_errors=True)


def main() -> None:
    test_multi_object_bake_with_separate_owned_caches()
    print("Physics World Geometry Nodes multi-object Bake probe: PASS")


if __name__ == "__main__":
    main()
