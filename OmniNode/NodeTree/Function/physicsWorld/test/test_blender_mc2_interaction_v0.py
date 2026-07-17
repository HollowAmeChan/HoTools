"""Blender/native acceptance for world-level MC2 cross-object self interaction."""

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
static_build = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.static_build"
)
frame_state = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.frame_state"
)
native_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.native_context"
)
runtime_parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.runtime_parameters"
)
solver_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.solver"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
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
    mesh.from_pydata(vertices, [], faces)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    extent = max((size - 1) * spacing, 1.0e-6)
    for loop in mesh.loops:
        x, y, _z = vertices[loop.vertex_index]
        uv_layer.data[loop.index].uv = (x / extent, y / extent)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _context(obj, frame: int):
    profile = parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=0.0,
        radius=0.02,
        self_collision_mode=0,
        self_collision_sync_mode=2,
    )
    task = specs.make_mc2_task_spec(
        "mesh_cloth",
        [obj],
        profile=profile,
        setup_options=parameters.make_mc2_setup_options(
            "mesh_cloth",
            self_collision_radius_model="derived_radius",
        ),
    )
    topology = topology_module.build_mc2_topology_spec(task)
    positions = np.asarray([tuple(vertex.co) for vertex in obj.data.vertices], dtype=np.float32)
    rotations = np.zeros((len(positions), 4), dtype=np.float32)
    rotations[:, 3] = 1.0
    context = native_module.MC2NativeContextV0(len(positions))
    static_build.build_mc2_mesh_cloth_static_for_task(
        task, topology, native_context=context
    )
    context.update_parameters(
        runtime_parameters.make_mc2_runtime_parameters(profile, task.setup_options)
    )
    context.update_dynamic(frame_state.make_mc2_frame_input(
        task_id=task.task_id,
        topology_signature=topology.topology_signature,
        frame=frame,
        generation=1,
        world_positions=positions,
        world_rotations_xyzw=rotations,
    ))
    context.reset()
    return context, task, topology, positions, rotations


def _advance(context, task, topology, positions, rotations, frame):
    context.update_dynamic(frame_state.make_mc2_frame_input(
        task_id=task.task_id,
        topology_signature=topology.topology_signature,
        frame=frame,
        generation=1,
        world_positions=positions,
        world_rotations_xyzw=rotations,
    ))


def _frame_input(bundle, frame):
    _context_value, task, topology, positions, rotations = bundle
    return frame_state.make_mc2_frame_input(
        task_id=task.task_id,
        topology_signature=topology.topology_signature,
        frame=frame,
        generation=1,
        world_positions=positions,
        world_rotations_xyzw=rotations,
        source_world_linear=np.eye(3, dtype=np.float32),
    )


objects = (_grid("MC2InteractionA", 0.0), _grid("MC2InteractionB", 0.008))
contexts = []
interaction = native_module.MC2NativeInteractionV0()
try:
    bundles = [_context(obj, 1) for obj in objects]
    contexts = [bundle[0] for bundle in bundles]
    before = [context.read()[0].copy() for context in contexts]
    interaction.step_group(contexts, (1, 2), (0, 0), 1.0 / 90.0)
    info = interaction.inspect()
    after = [context.read()[0].copy() for context in contexts]
    assert info["participant_count"] == 2
    assert info["candidate_count"] > 0
    assert info["contact_count"] > 0
    assert not np.array_equal(before[0], after[0]) or not np.array_equal(before[1], after[1])
    print("[PASS] automatic cross-owner contact")

    blocked = native_module.MC2NativeInteractionV0()
    blocked_contexts = []
    try:
        blocked_bundles = [_context(obj, 1) for obj in objects]
        blocked_contexts = [bundle[0] for bundle in blocked_bundles]
        blocked.step_group(blocked_contexts, (1, 2), (1, 2), 1.0 / 90.0)
        blocked_info = blocked.inspect()
        assert blocked_info["candidate_count"] == 0
        assert blocked_info["contact_count"] == 0
        print("[PASS] mutual group mask exclusion")
    finally:
        blocked.dispose()
        for context in blocked_contexts:
            context.dispose()

    for bundle in bundles:
        _advance(bundle[0], bundle[1], bundle[2], bundle[3], bundle[4], 2)
    interaction.step_group(contexts, (1, 2), (0, 0), 1.0 / 90.0)
    cross_frame_info = interaction.inspect()
    assert cross_frame_info["intersect_record_count"] > 0
    print("[PASS] cross-owner intersection history")

    revision = cross_frame_info["scope_revision"]
    bundle = bundles[0]
    _advance(bundle[0], bundle[1], bundle[2], bundle[3], bundle[4], 3)
    interaction.step_group((bundle[0],), (1,), (0,), 1.0 / 90.0)
    removed_info = interaction.inspect()
    assert removed_info["participant_count"] == 1
    assert removed_info["scope_revision"] == revision + 1
    for bundle in bundles:
        _advance(bundle[0], bundle[1], bundle[2], bundle[3], bundle[4], 4)
    interaction.step_group(contexts, (1, 2), (0, 0), 1.0 / 90.0)
    restored_info = interaction.inspect()
    assert restored_info["participant_count"] == 2
    assert restored_info["scope_revision"] == revision + 2
    print("[PASS] dynamic remove and restore")

    world = world_types.PhysicsWorldCache()
    try:
        tasks = [bundle[1] for bundle in bundles]
        solver_module.step_mc2(
            world,
            tasks,
            frame_inputs={bundle[1].task_id: _frame_input(bundle, 1) for bundle in bundles},
            dt=1.0 / 90.0,
        )
        solver_module.step_mc2(
            world,
            tasks,
            frame_inputs={bundle[1].task_id: _frame_input(bundle, 2) for bundle in bundles},
            dt=1.0 / 90.0,
        )
        production_interaction = world.backend_resources[
            native_module.MC2_INTERACTION_RESOURCE_KEY
        ]
        production_info = production_interaction.inspect()
        assert production_info["participant_count"] == 2
        assert production_info["candidate_count"] > 0
        assert production_info["contact_count"] > 0
        assert all(
            world.solver_slots[task.task_id].data["native_context"].inspect()["step_count"] == 1
            for task in tasks
        )
        print("[PASS] production solver lockstep interaction")
    finally:
        world.omni_cache_dispose("mc2_interaction_acceptance")
finally:
    interaction.dispose()
    for context in contexts:
        context.dispose()
    for obj in objects:
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)


print("MC2 interaction V0: PASS")
