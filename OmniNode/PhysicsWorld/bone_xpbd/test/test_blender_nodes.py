"""Bone XPBD 节点 socket 与运行调试生命周期的 Blender 4.5 验收。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
import numpy as np


BONE_XPBD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD = os.path.dirname(BONE_XPBD_ROOT)
OMNINODE = os.path.dirname(PHYSICS_WORLD)
HOTOOLS = os.path.dirname(OMNINODE)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.Function", os.path.join(OMNINODE, "Function")),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)


registry = importlib.import_module("HoTools.OmniNode.PhysicsWorld.registry")
nodes = importlib.import_module("HoTools.OmniNode.PhysicsWorld.bone_xpbd.nodes")
node_core = importlib.import_module("HoTools.OmniNode.FunctionNodeCore")
world_types = importlib.import_module("HoTools.OmniNode.PhysicsWorld.types")
xpbd_names = importlib.import_module("HoTools.OmniNode.PhysicsWorld.bone_xpbd.names")
xpbd_debug_draw = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.bone_xpbd.debug_draw"
)


def _socket_types(metadata: dict) -> dict[str, str]:
    return {
        identifier: str(value["type"])
        for identifier, value in metadata.items()
    }


def _socket_multi(metadata: dict, flags: dict) -> dict[str, bool]:
    return {
        identifier: bool(flags[identifier])
        for identifier in metadata
    }


def _debug_world(name: str, slot_id: str):
    world = world_types.PhysicsWorldCache()
    world.frame_context.frame = 12
    slot = world.ensure_solver_slot(slot_id, xpbd_names.BONE_XPBD_SLOT_KIND)
    slot.data["source_name"] = name
    slot.data["debug_summary"] = {
        "decision": "step",
        "tail_follow": True,
    }
    slot.data["debug_capture"] = {
        "world_positions": np.asarray(
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.2, 0.0), (3.0, 0.0, 0.0)),
            dtype=np.float32,
        ),
        "inverse_masses": np.asarray((0.0, 1.0, 1.0, 0.0), dtype=np.float32),
        "endpoint_particles": np.asarray(((0, 1), (1, 2), (2, 3)), dtype=np.int32),
        "bend_indices": np.asarray(((0, 2), (1, 3)), dtype=np.int32),
    }
    return world, slot


def test_node_socket_annotations_and_tail_follow_default():
    _, inputs, outputs, defaults, multi, _ = node_core.CheckMetaInfo(
        nodes.physicsBoneXpbdObject
    )
    assert _socket_types(inputs) == {"bones": "OmniNodeSocketBone"}
    assert _socket_multi(inputs, multi) == {"bones": True}
    assert _socket_types(outputs) == {
        "_OUTPUT0": "OmniNodeSocketAny",
        "_OUTPUT1": "NodeSocketInt",
    }
    assert _socket_multi(outputs, multi) == {"_OUTPUT0": True, "_OUTPUT1": False}

    _, inputs, outputs, defaults, multi, _ = node_core.CheckMetaInfo(
        nodes.physicsBoneXpbdCustomObject
    )
    assert _socket_types(inputs) == {
        "bones": "OmniNodeSocketBone",
        "pin_enabled": "NodeSocketBool",
    }
    assert _socket_multi(inputs, multi) == {"bones": True, "pin_enabled": False}
    assert defaults["pin_enabled"] is False
    assert _socket_types(outputs) == {
        "_OUTPUT0": "OmniNodeSocketAny",
        "_OUTPUT1": "NodeSocketInt",
    }
    assert _socket_multi(outputs, multi) == {"_OUTPUT0": True, "_OUTPUT1": False}

    _, inputs, outputs, defaults, multi, _ = node_core.CheckMetaInfo(
        nodes.physicsBoneXpbdTask
    )
    assert _socket_types(inputs) == {
        "bone_objects": "OmniNodeSocketAny",
        "tail_follow": "NodeSocketBool",
        "collision_enabled": "NodeSocketBool",
        "particle_radius": "NodeSocketFloat",
        "collided_by_groups": "OmniNodeSocketBitMask",
        "damping": "NodeSocketFloat",
        "stretch_compliance": "NodeSocketFloat",
        "bend_compliance": "NodeSocketFloat",
        "iterations": "NodeSocketInt",
        "gravity_direction": "NodeSocketVector",
        "gravity_power": "NodeSocketFloat",
    }
    assert _socket_multi(inputs, multi) == {
        identifier: identifier == "bone_objects"
        for identifier in inputs
    }
    assert defaults["tail_follow"] is True
    assert _socket_types(outputs) == {
        "_OUTPUT0": "OmniNodeSocketAny",
        "_OUTPUT1": "NodeSocketInt",
    }
    assert _socket_multi(outputs, multi) == {"_OUTPUT0": True, "_OUTPUT1": False}

    _, inputs, outputs, defaults, multi, _ = node_core.CheckMetaInfo(
        nodes.physicsBoneXpbdDebugDraw
    )
    assert _socket_types(inputs) == {
        "world": "OmniNodeSocketAny",
        "max_items": "NodeSocketInt",
        "show_particles": "NodeSocketBool",
        "show_segments": "NodeSocketBool",
        "show_bend": "NodeSocketBool",
    }
    assert _socket_multi(inputs, multi) == {
        identifier: False
        for identifier in inputs
    }
    assert _socket_types(outputs) == {
        "_OUTPUT0": "OmniNodeSocketAny",
        "_OUTPUT1": "NodeSocketString",
    }
    assert _socket_multi(outputs, multi) == {"_OUTPUT0": False, "_OUTPUT1": False}


def test_debug_node_requests_capture_and_clears_when_disabled():
    xpbd_debug_draw.clear_bone_xpbd_debug_draw_store()
    world, slot = _debug_world("DebugBoneChain", "bone_xpbd:test:debug")
    key = str(id(world))
    try:
        returned_world, status = nodes.physicsBoneXpbdDebugDraw(
            world,
            show_particles=True,
            show_segments=True,
            show_bend=True,
        )
        assert returned_world is world
        assert "DebugBoneChain" in status
        assert "Tail吸附=开" in status
        assert slot.data["_debug_requested"] is True
        stored = xpbd_debug_draw._STORE[key]
        assert len(stored["line_batches"]) == 2
        assert len(stored["point_batches"]) == 2

        returned_world, status = nodes.physicsBoneXpbdDebugDraw(world)
        assert returned_world is world
        assert status == "Bone XPBD调试未选择视图。"
        assert slot.data["_debug_requested"] is False
        assert "debug_capture" not in slot.data
        assert key not in xpbd_debug_draw._STORE
        assert xpbd_debug_draw._DRAW_HANDLE is None
    finally:
        xpbd_debug_draw.clear_bone_xpbd_debug_draw_store()


def test_world_dispose_handler_clears_only_owned_debug_store():
    xpbd_debug_draw.clear_bone_xpbd_debug_draw_store()
    first_world, _first_slot = _debug_world(
        "FirstDebugBoneChain",
        "bone_xpbd:test:dispose:first",
    )
    second_world, _second_slot = _debug_world(
        "SecondDebugBoneChain",
        "bone_xpbd:test:dispose:second",
    )
    first_key = str(id(first_world))
    second_key = str(id(second_world))
    try:
        nodes.physicsBoneXpbdDebugDraw(first_world, show_particles=True)
        nodes.physicsBoneXpbdDebugDraw(second_world, show_particles=True)
        assert first_key in xpbd_debug_draw._STORE
        assert second_key in xpbd_debug_draw._STORE

        handlers = tuple(
            entry
            for entry in registry.iter_world_dispose_handlers()
            if entry["domain"] == "bone_xpbd"
        )
        assert len(handlers) == 1
        assert handlers[0]["hook_ref"] == (
            ".debug_draw:dispose_bone_xpbd_debug_draw_for_world"
        )
        handlers[0]["hook"](first_world, "test_world_dispose")
        assert first_key not in xpbd_debug_draw._STORE
        assert second_key in xpbd_debug_draw._STORE

        handlers[0]["hook"](second_world, "test_world_dispose")
        assert second_key not in xpbd_debug_draw._STORE
        assert xpbd_debug_draw._DRAW_HANDLE is None
    finally:
        xpbd_debug_draw.clear_bone_xpbd_debug_draw_store()


if __name__ == "__main__":
    test_node_socket_annotations_and_tail_follow_default()
    test_debug_node_requests_capture_and_clears_when_disabled()
    test_world_dispose_handler_clears_only_owned_debug_store()
    print("Bone XPBD Blender nodes/debug lifecycle: PASS")
