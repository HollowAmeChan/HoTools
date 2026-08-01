"""在外部生产 .blend 当前场景中执行 Mesh XPBD 长帧生命周期验收。"""

from __future__ import annotations

import importlib
import json
import os
import sys
import time
import types

import bpy
import numpy as np


HOTOOLS = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)
    ))))
)
OMNINODE = os.path.join(HOTOOLS, "OmniNode")
PHYSICS_WORLD = os.path.join(OMNINODE, "PhysicsWorld")
NATIVE_PACKAGE = os.path.join(HOTOOLS, "_Lib", "py311", "HotoolsPackage")

for module_name in tuple(sys.modules):
    if module_name == "hotools_native" or module_name == "HoTools" or module_name.startswith("HoTools."):
        sys.modules.pop(module_name, None)
for path in reversed((NATIVE_PACKAGE, HOTOOLS, os.path.dirname(HOTOOLS))):
    if path not in sys.path:
        sys.path.insert(0, path)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.Function", os.path.join(OMNINODE, "Function")),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module

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


def _world_positions(source) -> np.ndarray:
    local = np.empty((len(source.data.vertices), 3), dtype=np.float64)
    source.data.vertices.foreach_get("co", local.reshape(-1))
    matrix = np.asarray(source.matrix_world, dtype=np.float64)
    return local @ matrix[:3, :3].T + matrix[:3, 3]


def _set_frame(world, frame: int, *, same_frame=False, paused=False, restart=False):
    context = world.frame_context
    context.previous_frame = frame if same_frame else frame - 1
    context.frame = frame
    context.continuous = not same_frame and not restart
    context.same_frame = bool(same_frame)
    context.restart_required = bool(restart)
    context.raw_dt = 1.0 / 24.0
    context.dt = 0.0 if paused else 1.0 / 24.0
    context.substeps = 2
    context.generation = world.generation


def test_current_production_blend_soak():
    if not bpy.data.filepath:
        raise AssertionError("production soak 必须从一个已加载的 .blend 运行")
    source = bpy.data.objects.get("Cube")
    if source is None or source.type != "MESH":
        raise AssertionError("production soak 需要场景中的 Cube Mesh")
    if len(source.data.vertices) < 3:
        raise AssertionError("production Cube 顶点数不足")

    world = world_types.PhysicsWorldCache()
    original_matrix = source.matrix_world.copy()
    started = time.perf_counter()
    try:
        initial_world = _world_positions(source)
        pin_index = int(np.argmax(initial_world[:, 2]))
        pin = source.vertex_groups.new(name="__MeshXpbdProductionPin")
        pin.add((pin_index,), 1.0, "REPLACE")
        plane_z = float(np.min(initial_world[:, 2]) - 0.5)
        collider_owner = next(
            (obj for obj in bpy.context.scene.objects if obj is not source),
            None,
        )
        world.collider_snapshot = {
            "frame": 1,
            "source_key": "mesh_xpbd_production_plane_v1",
            "source_count": 1,
            "colliders": [{
                "key": "production:plane",
                "owner": collider_owner,
                "owner_type": "OBJECT",
                "type": "PLANE",
                "center": (0.0, 0.0, plane_z),
                "normal": (0.0, 0.0, 1.0),
                "primary_group": 1,
            }],
        }
        xpbd_object = object_spec.make_mesh_xpbd_custom_object(
            source,
            pin_enabled=True,
            pin_vertex_group=pin.name,
            collided_by_groups=1,
        )

        task_values = {"iterations": 8}
        owner = None
        for frame in range(1, 181):
            if frame == 60:
                source.matrix_world.translation.x += 0.25
            elif frame == 120:
                source.matrix_world = original_matrix.copy()
            if frame == 150:
                task_values["iterations"] = 10
            tasks = authoring.make_mesh_xpbd_tasks(
                [xpbd_object],
                collision_enabled=True,
                collision_radius=0.05,
                damping=0.02,
                stretch_compliance=0.0,
                bend_compliance=0.001,
                gravity_power=9.8,
                **task_values,
            )
            _set_frame(
                world,
                frame,
                paused=frame == 100,
                restart=frame in {1, 130},
            )
            count, _elapsed = solver.step_mesh_xpbd(
                world,
                tasks,
                debug_capture=frame == 180,
            )
            assert count == 1
            assert writeback.writeback_gn_attributes(world) == 1
            slot = world.solver_slots[tasks[0].slot_id]
            current_owner = slot.data["native_context"]
            if owner is None:
                owner = current_owner
            assert current_owner is owner

            if frame == 90:
                before = owner.stats()["step_count"]
                _set_frame(world, frame, same_frame=True)
                solver.step_mesh_xpbd(world, tasks)
                assert owner.stats()["step_count"] == before
                assert writeback.writeback_gn_attributes(world) == 1

        commands = world.consume_results(
            world_names.GN_ATTRIBUTE_CHANNEL,
            solver="mesh_xpbd",
        )
        assert len(commands) == 1
        offsets = commands[0]["local_offsets"]
        assert offsets.shape == (len(source.data.vertices), 3)
        assert np.isfinite(offsets).all()
        assert float(np.max(np.linalg.norm(offsets, axis=1))) < 100.0
        stats = results.get_mesh_xpbd_stats_result(world)
        assert stats["status"] == "ok"
        assert stats["slot_count"] == 1
        assert stats["collider_count"] == 1
        assert len(world.solver_slots) == 1
        native_stats = owner.stats()
        assert native_stats["step_count"] >= 175
        attribute = source.data.attributes.get(world_names.GN_OFFSET_ATTRIBUTE_NAME)
        assert attribute is not None and len(attribute.data) == len(source.data.vertices)
        print("MESH_XPBD_PRODUCTION_SOAK " + json.dumps({
            "blend": bpy.data.filepath,
            "object": source.name,
            "particles": len(source.data.vertices),
            "frames": 180,
            "native_steps": native_stats["step_count"],
            "native_resets": native_stats["reset_count"],
            "max_local_offset": float(np.max(np.linalg.norm(offsets, axis=1))),
            "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        }, ensure_ascii=False))
    finally:
        source.matrix_world = original_matrix
        world.omni_cache_dispose("production_soak_complete")


if __name__ == "__main__":
    test_current_production_blend_soak()
    print("PASS test_current_production_blend_soak")
