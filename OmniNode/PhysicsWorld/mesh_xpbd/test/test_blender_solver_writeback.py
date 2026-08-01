"""Mesh XPBD native step 到公共 GN writeback 的 Blender 4.5 闭环。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
import numpy as np


MESH_XPBD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD = os.path.dirname(MESH_XPBD_ROOT)
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

authoring = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mesh_xpbd.authoring"
)
object_spec = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mesh_xpbd.object_spec"
)
results = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mesh_xpbd.results"
)
solver = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mesh_xpbd.solver"
)
world_names = importlib.import_module("HoTools.OmniNode.PhysicsWorld.names")
world_types = importlib.import_module("HoTools.OmniNode.PhysicsWorld.types")
writeback = importlib.import_module("HoTools.OmniNode.PhysicsWorld.writeback")


def _offset_values(obj) -> np.ndarray:
    attribute = obj.data.attributes.get(world_names.GN_OFFSET_ATTRIBUTE_NAME)
    assert attribute is not None
    values = np.empty((len(obj.data.vertices) * 3,), dtype=np.float32)
    attribute.data.foreach_get("vector", values)
    return values.reshape((-1, 3))


def _set_frame(world, frame: int, *, restart: bool) -> None:
    context = world.frame_context
    context.previous_frame = frame - 1 if frame > 1 else None
    context.frame = frame
    context.continuous = frame > 1
    context.same_frame = False
    context.restart_required = restart
    context.raw_dt = 1.0 / 24.0
    context.dt = 1.0 / 24.0
    context.substeps = 2
    context.generation = world.generation


def test_native_solver_publishes_and_common_writeback_applies_offsets():
    mesh = bpy.data.meshes.new("MeshXpbdWorldWritebackMesh")
    mesh.from_pydata(
        ((0, 0, 0), (1, 0, 0), (0, 1, 0)),
        (),
        ((0, 1, 2),),
    )
    mesh.update()
    source = bpy.data.objects.new("MeshXpbdWorldWriteback", mesh)
    bpy.context.scene.collection.objects.link(source)
    world = world_types.PhysicsWorldCache()
    try:
        pin = source.vertex_groups.new(name="Pin")
        pin.add((0,), 1.0, "REPLACE")
        xpbd_object = object_spec.make_mesh_xpbd_custom_object(
            source,
            pin_enabled=True,
            pin_vertex_group=pin.name,
        )
        tasks = authoring.make_mesh_xpbd_tasks(
            [xpbd_object],
            gravity_power=9.8,
            damping=0.0,
            iterations=8,
        )

        _set_frame(world, 1, restart=False)
        writeback_count, _elapsed = solver.step_mesh_xpbd(
            world, tasks, debug_capture=True
        )
        assert writeback_count == 1
        first_stats = results.get_mesh_xpbd_stats_result(world)
        assert first_stats["reset_slot_count"] == 1
        assert first_stats["stepped_slot_count"] == 0

        _set_frame(world, 2, restart=False)
        writeback_count, _elapsed = solver.step_mesh_xpbd(
            world, tasks, debug_capture=True
        )
        assert writeback_count == 1
        commands = world.consume_results(
            world_names.GN_ATTRIBUTE_CHANNEL,
            solver="mesh_xpbd",
        )
        assert len(commands) == 1
        offsets = commands[0]["local_offsets"]
        np.testing.assert_allclose(offsets[0], (0.0, 0.0, 0.0), atol=1.0e-6)
        assert float(np.linalg.norm(offsets[1:])) > 1.0e-5

        assert writeback.writeback_gn_attributes(world) == 1
        np.testing.assert_allclose(_offset_values(source), offsets, atol=1.0e-6)
        modifier = source.modifiers.get(world_names.GN_OFFSET_MODIFIER_NAME)
        assert modifier is not None and modifier.type == "NODES"

        stats = results.get_mesh_xpbd_stats_result(world)
        assert stats["stepped_slot_count"] == 1
        assert stats["reset_slot_count"] == 0
        assert stats["collider_count"] == 0
        slot = world.solver_slots[tasks[0].slot_id]
        assert slot.debug_snapshot()["summary"]["decision"] == "step"
    finally:
        world.omni_cache_dispose("test_complete")
        bpy.data.objects.remove(source, do_unlink=True)
        bpy.data.meshes.remove(mesh)


if __name__ == "__main__":
    test_native_solver_publishes_and_common_writeback_applies_offsets()
    print("PASS test_native_solver_publishes_and_common_writeback_applies_offsets")
