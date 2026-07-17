"""Compare automatic MC2 interaction scope with a ListObj-like partner graph."""

from __future__ import annotations

import importlib
import os
import statistics
import sys
import time
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
interaction_scope = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.interaction_scope"
)


def _grid(name, z, size=10, spacing=0.02):
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


def _bundle(obj):
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
        frame=1,
        generation=1,
        world_positions=positions,
        world_rotations_xyzw=rotations,
    ))
    context.reset()
    return context, task, topology, positions, rotations


def _advance(bundle, frame):
    context, task, topology, positions, rotations = bundle
    context.update_dynamic(frame_state.make_mc2_frame_input(
        task_id=task.task_id,
        topology_signature=topology.topology_signature,
        frame=frame,
        generation=1,
        world_positions=positions,
        world_rotations_xyzw=rotations,
    ))


def _masks_from_pairs(task_ids, pairs):
    index = {task_id: item for item, task_id in enumerate(task_ids)}
    masks = [0] * len(task_ids)
    for left, right in pairs:
        masks[index[left]] |= 1 << index[right]
        masks[index[right]] |= 1 << index[left]
    return tuple(masks)


def _run_case(objects, label, *, partner_graph=None, frames=35):
    bundles = [_bundle(obj) for obj in objects]
    contexts = [bundle[0] for bundle in bundles]
    task_ids = tuple(bundle[1].task_id for bundle in bundles)
    group_bits = tuple(1 << index for index in range(len(bundles)))
    interaction = native_module.MC2NativeInteractionV0()
    samples = []
    resolver_samples = []
    candidate_counts = []
    contact_counts = []
    try:
        for frame in range(1, frames + 1):
            for bundle in bundles:
                _advance(bundle, frame)
            if partner_graph is None:
                masks = (0,) * len(bundles)
            else:
                resolver_start = time.perf_counter_ns()
                pairs = interaction_scope.explicit_partner_pairs(partner_graph)
                masks = _masks_from_pairs(task_ids, pairs)
                resolver_samples.append((time.perf_counter_ns() - resolver_start) / 1.0e6)
            start = time.perf_counter_ns()
            interaction.step_group(contexts, group_bits, masks, 1.0 / 90.0)
            samples.append((time.perf_counter_ns() - start) / 1.0e6)
            frame_info = interaction.inspect()
            candidate_counts.append(frame_info["candidate_count"])
            contact_counts.append(frame_info["contact_count"])
        stable = samples[5:]
        info = interaction.inspect()
        return {
            "model": label,
            "mean_ms": statistics.fmean(stable),
            "p95_ms": sorted(stable)[max(0, int(len(stable) * 0.95) - 1)],
            "resolver_mean_ms": (
                statistics.fmean(resolver_samples[5:]) if resolver_samples else 0.0
            ),
            "candidate_peak": max(candidate_counts, default=0),
            "contact_peak": max(contact_counts, default=0),
            **info,
        }
    finally:
        interaction.dispose()
        for context in contexts:
            context.dispose()


def _run_dynamic_scope(objects):
    bundles = [_bundle(obj) for obj in objects]
    contexts = [bundle[0] for bundle in bundles]
    interaction = native_module.MC2NativeInteractionV0()
    try:
        timings = {}
        revisions = []
        for frame, active_count, label in (
            (1, 4, "initial_ms"),
            (2, 3, "remove_ms"),
            (3, 4, "restore_ms"),
        ):
            active = bundles[:active_count]
            for bundle in active:
                _advance(bundle, frame)
            start = time.perf_counter_ns()
            interaction.step_group(
                [bundle[0] for bundle in active],
                tuple(1 << index for index in range(active_count)),
                (0,) * active_count,
                1.0 / 90.0,
            )
            timings[label] = (time.perf_counter_ns() - start) / 1.0e6
            revisions.append(interaction.inspect()["scope_revision"])
        assert revisions == [1, 2, 3]
        return {"model": "automatic_dynamic_scope", **timings, "revisions": revisions}
    finally:
        interaction.dispose()
        for context in contexts:
            context.dispose()


objects = tuple(
    _grid(f"MC2InteractionBenchmark{index}", index * 0.006)
    for index in range(4)
)
try:
    probe = [_bundle(obj) for obj in objects]
    task_ids = tuple(bundle[1].task_id for bundle in probe)
    for bundle in probe:
        bundle[0].dispose()
    all_partner_graph = {
        task_id: tuple(other for other in task_ids if other != task_id)
        for task_id in task_ids
    }
    chain_partner_graph = {
        task_ids[index]: (task_ids[index + 1],)
        for index in range(len(task_ids) - 1)
    }
    results = (
        _run_case(objects, "automatic_wildcard"),
        _run_case(objects, "listobj_all_pairs", partner_graph=all_partner_graph),
        _run_case(objects, "listobj_sparse_chain", partner_graph=chain_partner_graph),
    )
    for result in results:
        print("MC2_INTERACTION_SCOPE_BENCH", result)
    dynamic_result = _run_dynamic_scope(objects)
    print("MC2_INTERACTION_SCOPE_DYNAMIC", dynamic_result)
    assert results[0]["pair_count"] == results[1]["pair_count"] == 6
    assert results[0]["candidate_peak"] == results[1]["candidate_peak"] > 0
    assert results[0]["contact_peak"] == results[1]["contact_peak"] > 0
    assert results[2]["pair_count"] == 3
finally:
    for obj in objects:
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)


print("MC2 interaction scope benchmark: PASS")
