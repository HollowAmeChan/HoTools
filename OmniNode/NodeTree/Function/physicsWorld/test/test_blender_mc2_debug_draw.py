"""Blender acceptance for implicit, request-driven MC2 debug snapshots."""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
import numpy as np


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
NODETREE = os.path.join(HOTOOLS, "OmniNode", "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(FUNCTION, "physicsWorld")

for path in (HOTOOLS, os.path.dirname(HOTOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", os.path.join(HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PW_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module


parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs"
)
topology_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology"
)
frame_state = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.frame_state"
)
center_state = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.center_state"
)
native_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.native_context"
)
debug_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.debug"
)
debug_draw = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.debug_draw"
)
solver_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.solver"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)
physics_blender = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender"
)


def _grid(name: str, z: float, *, size: int = 4, spacing: float = 0.02):
    vertices = [(x * spacing, y * spacing, z) for y in range(size) for x in range(size)]
    faces = []
    for y in range(size - 1):
        for x in range(size - 1):
            a = y * size + x
            b = a + 1
            c = a + size
            d = c + 1
            faces.extend(((a, b, d), (a, d, c)))
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(vertices, (), faces)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    extent = max((size - 1) * spacing, 1.0e-6)
    for loop in mesh.loops:
        x, y, _z = vertices[loop.vertex_index]
        uv_layer.data[loop.index].uv = (x / extent, y / extent)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _task(obj):
    profile = parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=0.0,
        stabilization_time_after_reset=0.0,
        radius=0.02,
        max_distance_enabled=True,
        max_distance=0.05,
        backstop_enabled=True,
        backstop_radius=0.01,
        backstop_distance=0.01,
        teleport_mode=2,
        teleport_distance=0.1,
        teleport_rotation=30.0,
        self_collision_mode=2,
        self_collision_sync_mode=2,
    )
    return specs.make_mc2_task_spec(
        "mesh_cloth",
        [obj],
        profile=profile,
        setup_options=parameters.make_mc2_setup_options(
            "mesh_cloth", self_collision_radius_model="derived_radius"
        ),
    )


def _frame_input(task, frame):
    topology = topology_module.build_mc2_topology_spec(task)
    positions = np.asarray([tuple(vertex.co) for vertex in task.sources[0].data.vertices], dtype=np.float32)
    rotations = np.zeros((len(positions), 4), dtype=np.float32)
    rotations[:, 3] = 1.0
    component_position = (1.0, 0.0, 0.0) if frame >= 3 else (0.0, 0.0, 0.0)
    component_scale = (-1.0, 1.0, 1.0) if frame >= 3 else (1.0, 1.0, 1.0)
    source_world_linear = np.diag(component_scale).astype(np.float32)
    center_pose = center_state.MC2CenterFramePoseSpec(
        frame=frame,
        generation=1,
        component_identity=task.task_id,
        component_world_position=component_position,
        component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
        component_world_scale=component_scale,
        anchor_identity=f"anchor:{task.task_id}",
        anchor_world_position=(0.0, 0.0, 0.0),
        anchor_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
    )
    return frame_state.make_mc2_frame_input(
        task_id=task.task_id,
        topology_signature=topology.topology_signature,
        frame=frame,
        generation=1,
        world_positions=positions,
        world_rotations_xyzw=rotations,
        source_world_linear=source_world_linear,
        center_frame_pose=center_pose,
    )


def _world_frame(world, frame, previous):
    context = world.frame_context
    context.previous_frame = previous
    context.frame = frame
    context.same_frame = previous == frame
    context.continuous = previous is not None and frame == previous + 1
    context.raw_dt = 1.0 / 90.0
    context.dt = 1.0 / 90.0
    context.generation = 1
    world.generation = 1


physics_blender.register()
objects = (_grid("MC2DebugA", 0.0), _grid("MC2DebugB", 0.008))
for obj in objects:
    obj.hotools_mesh_collision.collided_by_groups = 1
collider_owner = bpy.data.objects.new("MC2DebugCollider", None)
bpy.context.scene.collection.objects.link(collider_owner)
world = world_types.PhysicsWorldCache()
world.collider_snapshot = {
    "frame": 1,
    "source_count": 1,
    "colliders": [{
        "key": "mc2-debug-sphere",
        "owner": collider_owner,
        "type": "SPHERE",
        "center": (0.03, 0.03, -0.02),
        "radius": 0.025,
        "primary_group": 1,
    }],
}
node_uid = "mc2-debug-acceptance"
try:
    tasks = tuple(_task(obj) for obj in objects)
    _world_frame(world, 1, None)
    solver_module.step_mc2(
        world,
        tasks,
        frame_inputs={task.task_id: _frame_input(task, 1) for task in tasks},
        dt=1.0 / 90.0,
    )
    _world_frame(world, 2, 1)
    solver_module.step_mc2(
        world,
        tasks,
        frame_inputs={task.task_id: _frame_input(task, 2) for task in tasks},
        dt=1.0 / 90.0,
    )
    contexts = [world.solver_slots[task.task_id].data["native_context"] for task in tasks]
    interaction = world.backend_resources[native_module.MC2_INTERACTION_RESOURCE_KEY]
    assert all(context.inspect()["debug_readback_count"] == 0 for context in contexts)
    assert interaction.inspect()["debug_readback_count"] == 0
    print("[PASS] debug disabled has zero native readback")

    debug_draw.update_mc2_debug_draw_store(
        node_uid,
        world,
        True,
        show_self_primitives=True,
        show_self_grid=True,
        show_self_candidates=True,
    )
    assert debug_draw.mc2_debug_draw_store_snapshot(node_uid)["line_vertex_count"] == 0
    assert all(slot.data["_debug_capture_state"]["requested"] for slot in world.solver_slots.values())
    print("[PASS] implicit node requests without immediate readback")

    solver_module.step_mc2(
        world,
        tasks,
        frame_inputs={task.task_id: _frame_input(task, 2) for task in tasks},
        dt=1.0 / 90.0,
    )
    assert all(context.inspect()["debug_readback_count"] == 0 for context in contexts)
    assert interaction.inspect()["debug_readback_count"] == 0
    print("[PASS] same-frame evaluation does not consume request")

    _world_frame(world, 3, 2)
    solver_module.step_mc2(
        world,
        tasks,
        frame_inputs={task.task_id: _frame_input(task, 3) for task in tasks},
        dt=1.0 / 90.0,
    )
    assert all(context.inspect()["debug_readback_count"] > 0 for context in contexts)
    assert interaction.inspect()["debug_readback_count"] == 1
    for task in tasks:
        slot = world.solver_slots[task.task_id]
        state = slot.data["_debug_capture_state"]
        snapshot = slot.data["_debug_draw_snapshot"]
        assert state["requested"] is False and state["captured_frame"] == 3
        assert snapshot["frame"] == 3
        assert snapshot["native"]["positions"].flags.writeable is False
        assert snapshot["topology"]["edges"].flags.writeable is False
        assert snapshot["motion"]["max_distances"].flags.writeable is False
        assert snapshot["center"]["frame_sync"]["action"] == "updated"
        assert snapshot["center"]["frame_shift"]["keep_teleport"] is True
        assert snapshot["center"]["negative_scale_transition"]["active"] is True
        assert snapshot["center"]["source_world_linear"].flags.writeable is False
        assert snapshot["collision"]["particle_radii"].shape[0] == 16
        assert tuple(snapshot["collision"]["colliders"]["types"]) == (0,)
        assert snapshot["output"]["writeback_target_kind"] == "mesh_vertex"
        assert len(snapshot["output"]["writeback_targets"]) == 16
        self_state = snapshot["self_collision"]
        assert self_state["particle_indices"].flags.writeable is False
        assert self_state["primitive_grids"].flags.writeable is False
    interaction_snapshot = interaction.debug_draw_snapshot()
    assert interaction_snapshot["positions"].flags.writeable is False
    assert interaction_snapshot["native"]["candidate_count"] > 0
    print("[PASS] next true advance captures frozen slot and world interaction state")

    debug_draw.update_mc2_debug_draw_store(
        node_uid,
        world,
        True,
        show_self_primitives=True,
        show_self_grid=True,
        show_self_candidates=True,
    )
    rendered = debug_draw.mc2_debug_draw_store_snapshot(node_uid)
    assert rendered["batch_count"] > 0 and rendered["line_vertex_count"] > 0
    debug_draw.update_mc2_debug_draw_store(
        node_uid,
        world,
        True,
        show_self_primitives=True,
        show_self_grid=True,
        show_self_candidates=True,
        task_filter=tasks[0].task_id,
    )
    filtered = debug_draw.mc2_debug_draw_store_snapshot(node_uid)
    assert 0 < filtered["line_vertex_count"] < rendered["line_vertex_count"]
    debug_draw.update_mc2_debug_draw_store(
        node_uid,
        world,
        True,
        show_self_primitives=True,
        show_self_grid=True,
        show_self_candidates=True,
    )
    objects[0].data.vertices[0].co.x += 10.0
    debug_draw.update_mc2_debug_draw_store(
        node_uid,
        world,
        True,
        show_self_primitives=True,
        show_self_grid=True,
        show_self_candidates=True,
    )
    rerendered = debug_draw.mc2_debug_draw_store_snapshot(node_uid)
    assert rerendered["coordinate_checksum"] == rendered["coordinate_checksum"]
    print("[PASS] renderer consumes frozen snapshot instead of current RNA")

    world.omni_cache_dispose("mc2_debug_acceptance")
    assert debug_draw.mc2_debug_draw_store_snapshot(node_uid) is None
    print("[PASS] world dispose clears implicit MC2 draw state")
finally:
    if world.valid:
        world.omni_cache_dispose("mc2_debug_cleanup")
    debug_draw.clear_mc2_debug_draw_store()
    for obj in objects:
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)
    bpy.data.objects.remove(collider_owner, do_unlink=True)
    physics_blender.unregister()


print("MC2 debug draw: PASS")
