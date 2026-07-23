"""Measure product whole-domain self-collision thickness on one fixed mesh."""

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
TEST_ROOT = os.path.join(PW_ROOT, "test")

for path in (HOTOOLS, os.path.dirname(HOTOOLS), TEST_ROOT):
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


mixed = importlib.import_module("test_blender_mc2_product_mixed_output_soak")
physics_blender = mixed.physics_blender
nodes = mixed.nodes
parameters = mixed.parameters
product_slot = mixed.product_slot
world_types = mixed.world_types
base_pose = mixed.base_pose
gn_offset = mixed.gn_offset
world_names = mixed.world_names


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
                faces.extend(
                    ((a, b, d), (a, d, c))
                    if layer == 0
                    else ((a, d, b), (a, c, d))
                )
    mesh = bpy.data.meshes.new("MC2ProductSelfRadiusBenchmarkMesh")
    mesh.from_pydata(vertices, (), faces)
    mesh.uv_layers.new(name="UVMap")
    mesh.update()
    obj = bpy.data.objects.new("MC2ProductSelfRadiusBenchmark", mesh)
    bpy.context.scene.collection.objects.link(obj)
    pin = obj.vertex_groups.new(name="MC2Pin")
    pin.add(tuple(range(size)), 1.0, "REPLACE")
    obj.hotools_mesh_collision.pin_enabled = True
    obj.hotools_mesh_collision.pin_vertex_group = pin.name
    obj.hotools_mesh_collision.collided_by_groups = 1
    gn_offset.write_gn_local_offsets(
        obj, np.zeros((len(mesh.vertices), 3), dtype=np.float32)
    )
    signature = base_pose.mesh_topology_signature(obj)
    proxy = base_pose.ensure_base_pose_proxy(
        obj, expected_mesh_topology_signature=signature
    )
    return obj, proxy


def _remove_mesh(obj):
    if obj is None or obj.name not in bpy.data.objects:
        return
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and not mesh.users:
        bpy.data.meshes.remove(mesh)


def _request(world, obj, radius):
    entries, count = nodes.physicsMC2MeshObject([obj])
    assert count == 1 and len(entries) == 1
    entries, count = nodes.physicsMC2MeshOverride(
        entries,
        profile=parameters.make_mc2_particle_profile(
            gravity=0.0,
            damping=0.0,
            radius=radius,
            collision_mode=0,
            self_collision_mode=2,
            particle_speed_limit=4.0,
        ),
    )
    assert count == 1
    requests, report = nodes.physicsMC2MeshCollector(
        world, entries, include_implicit=False
    )
    assert len(requests) == 1 and report
    return requests[0]


def _run_case(label, radius, frames=40):
    world = world_types.PhysicsWorldCache()
    obj = proxy = None
    samples = []
    candidate_count = contact_count = 0
    try:
        physics_blender.register()
        obj, proxy = _double_layer_grid()
        mixed.bone_soak._set_frame(world, 1, 1200)
        world.collider_snapshot = {"frame": 1, "colliders": []}
        request = _request(world, obj, radius)
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type, request.domain_signature
        )
        for frame in range(1, frames + 1):
            mixed.bone_soak._set_frame(world, frame, 1200)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            started = time.perf_counter_ns()
            returned, ready, status = nodes.physicsMC2Step(
                world, [request], simulation_frequency=90,
                max_simulation_count_per_frame=1,
            )
            assert returned is world and ready is True, status
            samples.append((time.perf_counter_ns() - started) / 1.0e6)
            owner = world.solver_slots[slot_id].data["owner"]
            kernel = owner.inspect()["domain"]["kernel"]
            candidate_count = int(kernel.get("whole_domain_self_last_candidate_count", 0))
            contact_count = int(kernel.get("whole_domain_self_last_contact_count", 0))
            output = owner.read_output()
            assert np.all(np.isfinite(output.world_positions))
        stable = samples[5:]
        return {
            "model": label,
            "radius": float(radius),
            "derived_self_thickness": float(radius) * 0.25,
            "mean_ms": statistics.fmean(stable),
            "p95_ms": sorted(stable)[max(0, int(len(stable) * 0.95) - 1)],
            "candidate_count": candidate_count,
            "contact_count": contact_count,
        }
    finally:
        world.omni_cache_dispose("mc2_product_self_radius_cleanup")
        _remove_mesh(obj)
        _remove_mesh(proxy)
        if physics_blender.is_registered():
            physics_blender.unregister()


results = (
    _run_case("radius_0_02", 0.02),
    _run_case("radius_0_02_repeat", 0.02),
    _run_case("radius_0_08", 0.08),
)
assert results[0]["candidate_count"] == results[1]["candidate_count"]
assert results[0]["contact_count"] == results[1]["contact_count"]
assert results[2]["candidate_count"] > results[0]["candidate_count"]
for result in results:
    print("MC2_PRODUCT_SELF_RADIUS_BENCH", result)

print("MC2 product self radius benchmark: PASS")
