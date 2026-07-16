"""Measure MC2 self-collision thickness cost on one fixed double-layer grid."""

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


parameters = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters")
specs = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs")
topology_module = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology")
static_build = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.static_build"
)
frame_state = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.frame_state")
native_module = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.native")
runtime_parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.runtime_parameters"
)


def _double_layer_grid(size=18, spacing=0.02, layer_gap=0.012):
    vertices = []
    faces = []
    layer_vertex_count = size * size
    for layer, z in enumerate((0.0, layer_gap)):
        offset = layer * layer_vertex_count
        for y in range(size):
            for x in range(size):
                vertices.append((x * spacing, y * spacing, z))
        for y in range(size - 1):
            for x in range(size - 1):
                a = offset + y * size + x
                b = a + 1
                c = a + size
                d = c + 1
                if layer == 0:
                    faces.extend(((a, b, d), (a, d, c)))
                else:
                    faces.extend(((a, d, b), (a, c, d)))
    mesh = bpy.data.meshes.new("MC2_SelfRadiusBenchmarkMesh")
    mesh.from_pydata(vertices, [], faces)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    extent = max(float(size - 1) * spacing, 1.0e-6)
    for loop in mesh.loops:
        x, y, _z = vertices[loop.vertex_index]
        uv_layer.data[loop.index].uv = (x / extent, y / extent)
    mesh.update()
    obj = bpy.data.objects.new("MC2_SelfRadiusBenchmark", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _run_case(obj, label, thickness, frames=40):
    profile = parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=0.0,
        radius=0.02,
        self_collision_mode=2,
        self_collision_thickness=thickness,
    )
    task = specs.make_mc2_task_spec("mesh_cloth", [obj], profile=profile)
    topology = topology_module.build_mc2_topology_spec(task)
    positions = np.asarray([tuple(vertex.co) for vertex in obj.data.vertices], dtype=np.float32)
    rotations = np.zeros((len(positions), 4), dtype=np.float32)
    rotations[:, 3] = 1.0
    context = native_module.MC2NativeContextV0(len(positions))
    try:
        static_build.build_mc2_mesh_cloth_static_for_task(
            task, topology, native_context=context
        )
        effective = runtime_parameters.make_mc2_runtime_parameters(
            profile,
            task.setup_options,
        )
        context.update_parameters(effective)
        samples = []
        info = None
        for frame in range(1, frames + 1):
            frame_input = frame_state.make_mc2_frame_input(
                task_id=task.task_id,
                topology_signature=topology.topology_signature,
                frame=frame,
                generation=1,
                world_positions=positions,
                world_rotations_xyzw=rotations,
            )
            start = time.perf_counter_ns()
            context.update_dynamic(frame_input)
            context.reset()
            context.step_no_collision(1.0 / 90.0)
            samples.append((time.perf_counter_ns() - start) / 1.0e6)
        info = context.inspect()
    finally:
        context.dispose()
    stable = samples[5:]
    return {
        "model": label,
        "thickness": thickness,
        "mean_ms": statistics.fmean(stable),
        "p95_ms": sorted(stable)[max(0, int(len(stable) * 0.95) - 1)],
        "candidate_count": info["self_contact_candidate_count"],
        "contact_count": info["self_contact_cache_count"],
        "enabled_contact_count": info["self_contact_enabled_count"],
        "primitive_count": info["self_primitive_count"],
        "grid_count": info["self_grid_count"],
    }


obj = _double_layer_grid()
try:
    results = [
        _run_case(obj, "source_separate", 0.005),
        _run_case(obj, "derived_radius_x_0_25", 0.02 * 0.25),
        _run_case(obj, "radius_equal", 0.02),
    ]
    for result in results:
        print("MC2_SELF_RADIUS_BENCH", result)
finally:
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.meshes.remove(mesh)


print("MC2 self radius benchmark: PASS")
