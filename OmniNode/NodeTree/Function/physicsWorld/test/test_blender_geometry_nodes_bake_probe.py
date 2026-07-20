# -*- coding: utf-8 -*-
"""Geometry Nodes Bake feasibility probe for Physics World mesh output.

Usage:
    blender.exe --factory-startup --background --python test_blender_geometry_nodes_bake_probe.py

The test intentionally stays independent from production helpers. It proves the
Blender 4.5 host behavior required before adding a Bake node to the shared
Physics World post-displacement node group.
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
OBJECT_NAME = "PhysicsGNBakeProbe"
MODIFIER_NAME = "HoTools 物理网格缓存"
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


def _make_mesh_object():
    mesh = bpy.data.meshes.new(f"{OBJECT_NAME}Mesh")
    mesh.from_pydata(
        [(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)],
        [],
        [(0, 1, 2)],
    )
    obj = bpy.data.objects.new(OBJECT_NAME, mesh)
    bpy.context.scene.collection.objects.link(obj)
    attribute = mesh.attributes.new(ATTRIBUTE_NAME, "FLOAT_VECTOR", "POINT")
    zeros = np.zeros(len(mesh.vertices) * 3, dtype=np.float32)
    attribute.data.foreach_set("vector", zeros)
    return obj


def _write_frame_offset(obj, frame: int) -> None:
    attribute = obj.data.attributes[ATTRIBUTE_NAME]
    values = np.zeros((len(obj.data.vertices), 3), dtype=np.float32)
    values[:, 2] = np.float32(frame)
    attribute.data.foreach_set("vector", values.reshape(-1))
    obj.data.update()
    obj.update_tag()


def _evaluated_positions(obj, frame: int) -> np.ndarray:
    bpy.context.scene.frame_set(int(frame))
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


def _expected_positions(frame: int) -> np.ndarray:
    return np.asarray(
        [(-1.0, 0.0, float(frame)), (1.0, 0.0, float(frame)), (0.0, 0.0, 1.0 + float(frame))],
        dtype=np.float32,
    )


def _select_only(obj) -> None:
    for candidate in bpy.context.selected_objects:
        candidate.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _disk_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def test_geometry_nodes_bake_post_displacement() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="hotools_gn_bake_probe_"))
    blend_path = temp_root / "probe.blend"
    bake_dir = temp_root / "bake"
    bake_dir.mkdir(parents=True, exist_ok=True)
    frame_events: list[int] = []

    try:
        obj = _make_mesh_object()
        _attribute, _live_modifier = gn_offset.ensure_gn_offset_output(obj)
        _select_only(obj)
        bpy.context.view_layer.update()
        modifier, entry = gn_offset.configure_gn_offset_disk_bake(
            obj,
            str(bake_dir),
            FRAME_START,
            FRAME_END,
        )
        bake_node = gn_offset.get_gn_offset_bake_node(modifier.node_group)

        assert entry.node == bake_node
        assert modifier.name == MODIFIER_NAME
        assert entry.bake_id > 0
        assert bake_node.bake_items[0].socket_type == "GEOMETRY"
        assert bake_node.inputs["Geometry"].is_linked
        assert bake_node.outputs["Geometry"].is_linked
        assert gn_offset.is_gn_offset_cache_enabled(obj) is False

        def write_offset_on_frame(scene, depsgraph=None):
            del depsgraph
            live_obj = bpy.data.objects.get(OBJECT_NAME)
            if live_obj is None:
                return
            frame = int(scene.frame_current)
            frame_events.append(frame)
            _write_frame_offset(live_obj, frame)

        bpy.app.handlers.frame_change_post.append(write_offset_on_frame)
        bpy.context.scene.frame_start = FRAME_START
        bpy.context.scene.frame_end = FRAME_END
        bpy.context.scene.frame_set(FRAME_START)
        _write_frame_offset(obj, FRAME_START)

        # Blender requires a saved blend file before Geometry Nodes can bake.
        result = bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)
        assert result == {"FINISHED"}

        # Make the targeted Bake branch part of the evaluated modifier while
        # Blender owns the bake, then keep it enabled for playback.
        gn_offset.set_gn_offset_cache_enabled(obj, True)
        frame_events.clear()
        result = bpy.ops.object.geometry_node_bake_single(
            session_uid=int(obj.session_uid),
            modifier_name=modifier.name,
            bake_id=int(entry.bake_id),
        )
        assert result == {"FINISHED"}, result
        assert {FRAME_START, FRAME_START + 1, FRAME_END}.issubset(set(frame_events)), frame_events
        distinct_events = [
            frame
            for index, frame in enumerate(frame_events)
            if index == 0 or frame != frame_events[index - 1]
        ]
        assert distinct_events == list(range(FRAME_START, FRAME_END + 1)), frame_events
        assert int(bpy.context.scene.frame_current) == FRAME_START

        files = _disk_files(bake_dir)
        assert files, f"Geometry Nodes Bake created no files in {bake_dir}"
        assert sum(path.stat().st_size for path in files) > 0
        print(
            "Geometry Nodes Bake events:",
            frame_events,
            "files:",
            [(path.name, path.stat().st_size) for path in files],
        )

        # Once baked, changing the live attribute must not change evaluated output.
        _write_frame_offset(obj, 100)
        cached_positions = {
            frame: _evaluated_positions(obj, frame)
            for frame in range(FRAME_START, FRAME_END + 1)
        }
        print(
            "Geometry Nodes switched cache Z:",
            {frame: values[:, 2].tolist() for frame, values in cached_positions.items()},
        )
        for frame in range(FRAME_START, FRAME_END + 1):
            actual = cached_positions[frame]
            np.testing.assert_allclose(actual, _expected_positions(frame), rtol=0.0, atol=1.0e-6)

        bpy.app.handlers.frame_change_post.remove(write_offset_on_frame)
        file_state = [(path, path.stat().st_size, path.stat().st_mtime_ns) for path in files]

        # Playback is per modifier: disabling it restores live geometry while
        # retaining every cache file, then enabling it restores the same bake.
        gn_offset.set_gn_offset_cache_enabled(obj, False)
        _write_frame_offset(obj, 20)
        for frame in range(FRAME_START, FRAME_END + 1):
            actual = _evaluated_positions(obj, frame)
            np.testing.assert_allclose(actual, _expected_positions(20), rtol=0.0, atol=1.0e-6)
        assert file_state == [
            (path, path.stat().st_size, path.stat().st_mtime_ns)
            for path in files
        ]

        gn_offset.set_gn_offset_cache_enabled(obj, True)
        for frame in range(FRAME_START, FRAME_END + 1):
            actual = _evaluated_positions(obj, frame)
            np.testing.assert_allclose(actual, _expected_positions(frame), rtol=0.0, atol=1.0e-6)
        result = bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)
        assert result == {"FINISHED"}

        # The baked node must keep reading disk data after reopening the blend.
        result = bpy.ops.wm.open_mainfile(filepath=str(blend_path), load_ui=False)
        assert result == {"FINISHED"}
        obj = bpy.data.objects[OBJECT_NAME]
        modifier = obj.modifiers[MODIFIER_NAME]
        entry = modifier.bakes[0]
        assert gn_offset.is_gn_offset_cache_enabled(obj) is True
        for frame in range(FRAME_START, FRAME_END + 1):
            actual = _evaluated_positions(obj, frame)
            np.testing.assert_allclose(actual, _expected_positions(frame), rtol=0.0, atol=1.0e-6)

        # Deleting the Bake must restore the live post-displacement path.
        _select_only(obj)
        _write_frame_offset(obj, 20)
        result = bpy.ops.object.geometry_node_bake_delete_single(
            session_uid=int(obj.session_uid),
            modifier_name=modifier.name,
            bake_id=int(entry.bake_id),
        )
        assert result == {"FINISHED"}, result
        gn_offset.set_gn_offset_cache_enabled(obj, False)
        actual = _evaluated_positions(obj, FRAME_START + 1)
        np.testing.assert_allclose(actual, _expected_positions(20), rtol=0.0, atol=1.0e-6)
        assert not _disk_files(bake_dir), "deleting the Bake left owned disk files behind"
    finally:
        for handler in list(bpy.app.handlers.frame_change_post):
            if getattr(handler, "__name__", "") == "write_offset_on_frame":
                bpy.app.handlers.frame_change_post.remove(handler)
        # The probe owns the entire unique temp directory.
        shutil.rmtree(temp_root, ignore_errors=True)


def main() -> None:
    test_geometry_nodes_bake_post_displacement()
    print("Physics World Geometry Nodes Bake probe: PASS")


if __name__ == "__main__":
    main()
