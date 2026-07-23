"""Product-only MC2 hotspot benchmark for fixed Mesh and Bone assets."""

from __future__ import annotations

import importlib
import json
import math
import os
import statistics
import sys
import time
import tracemalloc
import types

import bpy
import numpy as np


HERE = os.path.dirname(os.path.abspath(__file__))
PHYSICS_WORLD = os.path.dirname(HERE)
FUNCTION = os.path.dirname(PHYSICS_WORLD)
NODETREE = os.path.dirname(FUNCTION)
OMNINODE = os.path.dirname(NODETREE)
HOTOOLS = os.path.dirname(OMNINODE)

for path in (HOTOOLS, os.path.dirname(HOTOOLS), HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PHYSICS_WORLD),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module


physics_blender = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)
writeback = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.writeback"
)
nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.nodes"
)
parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
product_slot = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_slot"
)
debug = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.debug"
)
base_pose = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.base_pose"
)
gn_offset = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.gn_offset"
)


HOT_FRAMES_OVERRIDE = int(os.environ.get("MC2_BENCH_HOT_FRAMES", "0") or 0)
CASES = (
    {"name": "small", "grid": 10, "chains": 4, "chain_length": 8, "hot_frames": 8},
    {"name": "medium", "grid": 24, "chains": 12, "chain_length": 12, "hot_frames": 7},
    {"name": "large", "grid": 40, "chains": 24, "chain_length": 16, "hot_frames": 6},
)
if HOT_FRAMES_OVERRIDE > 0:
    CASES = tuple({**case, "hot_frames": HOT_FRAMES_OVERRIDE} for case in CASES)

CEILINGS = {
    "small": {"cold_ms": 80.0, "hot_ms": 35.0, "change_ms": 80.0, "debug_ms": 80.0, "allocation_bytes": 8_000_000},
    "medium": {"cold_ms": 180.0, "hot_ms": 140.0, "change_ms": 180.0, "debug_ms": 160.0, "allocation_bytes": 24_000_000},
    "large": {"cold_ms": 520.0, "hot_ms": 420.0, "change_ms": 520.0, "debug_ms": 320.0, "allocation_bytes": 64_000_000},
}


def _summary(values) -> dict:
    values = tuple(float(value) for value in values)
    ordered = sorted(values)
    return {
        "samples": len(values),
        "mean_ms": statistics.fmean(values),
        "p95_ms": ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)],
        "max_ms": max(values),
    }


def _set_world_frame(world, frame: int, previous: int | None) -> None:
    context = world.frame_context
    context.previous_frame = previous
    context.frame = frame
    context.same_frame = False
    context.continuous = frame > 1
    context.raw_dt = 1.0 / 60.0
    context.dt = 1.0 / 60.0
    context.time_scale = 1.0
    context.generation = 1
    context.restart_required = False
    context.reset_requested = False
    world.generation = 1


def _mesh_object(name: str, width: int):
    denominator = float(max(1, width - 1))
    positions = [
        (x / denominator, y / denominator, 0.0)
        for y in range(width)
        for x in range(width)
    ]
    faces = []
    for y in range(width - 1):
        for x in range(width - 1):
            first = y * width + x
            faces.extend(((first, first + 1, first + width + 1), (first, first + width + 1, first + width)))
    mesh = bpy.data.meshes.new(f"{name}Data")
    mesh.from_pydata(positions, (), faces)
    uv = mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        uv.data[loop.index].uv = positions[loop.vertex_index][:2]
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    pin = obj.vertex_groups.new(name="MC2Pin")
    pin.add(tuple(range(width)), 1.0, "REPLACE")
    obj.hotools_mesh_collision.pin_enabled = True
    obj.hotools_mesh_collision.pin_vertex_group = pin.name
    obj.hotools_mesh_collision.collided_by_groups = 1
    gn_offset.write_gn_local_offsets(obj, np.zeros((len(mesh.vertices), 3), dtype=np.float32))
    proxy = base_pose.ensure_base_pose_proxy(
        obj, expected_mesh_topology_signature=base_pose.mesh_topology_signature(obj)
    )
    return obj, proxy, pin


def _armature(name: str, chain_count: int, chain_length: int):
    data = bpy.data.armatures.new(f"{name}Data")
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    parent = data.edit_bones.new("Parent")
    parent.head = (0.0, 0.0, 0.0)
    parent.tail = (0.0, 0.0, 1.0)
    chains = []
    for chain_index in range(chain_count):
        x = (chain_index - (chain_count - 1) * 0.5) * 0.12
        previous = parent
        chain = []
        for depth in range(chain_length):
            bone = data.edit_bones.new(f"Chain{chain_index}_{depth}")
            bone.head = (x, depth * 0.12, 1.0)
            bone.tail = (x, (depth + 1) * 0.12, 1.0)
            bone.parent = previous
            bone.use_connect = depth > 0
            previous = bone
            chain.append(bone.name)
        chains.append(chain)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj, chains


def _remove_object(obj) -> None:
    if obj is None:
        return
    try:
        name = obj.name
        object_type = obj.type
        data = obj.data
    except ReferenceError:
        return
    if name not in bpy.data.objects:
        return
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and not data.users:
        collection = bpy.data.meshes if object_type == "MESH" else bpy.data.armatures
        collection.remove(data)


def _profile(*, bone: bool = False, gravity_direction=(0.0, 0.0, -1.0)):
    return parameters.make_mc2_particle_profile(
        gravity=9.0 if not bone else 3.0,
        gravity_direction=gravity_direction,
        damping=0.1,
        radius=0.02,
        tether_compression=0.4,
        distance_stiffness=1.0,
        bending_stiffness=0.0 if bone else 1.0,
        angle_restoration_enabled=not bone,
        angle_restoration_stiffness=0.2,
        angle_restoration_velocity_attenuation=0.8,
        collision_mode=0,
        self_collision_mode=0,
        self_collision_sync_mode=0,
    )


def _mesh_request(world, obj, profile):
    entries, count = nodes.physicsMC2MeshObject([obj])
    assert count == 1
    entries, count = nodes.physicsMC2MeshOverride(entries, profile=profile)
    assert count == 1
    requests, report = nodes.physicsMC2MeshCollector(world, entries, include_implicit=False)
    assert len(requests) == 1 and report
    return requests[0]


def _bone_request(armature, profile):
    requests, _names = nodes.physicsMC2BoneClothTask(
        [{"armature": armature, "bone": "Parent"}],
        profile=profile,
        connection_mode=1,
        collided_by_groups=1,
    )
    assert len(requests) == 1
    return requests[0]


def _run_step(world, request, frame, previous, domain) -> float:
    bpy.context.scene.frame_set(frame)
    _set_world_frame(world, frame, previous)
    world.collider_snapshot = {"frame": frame, "colliders": []}
    started = time.perf_counter_ns()
    returned, ready, status = nodes.physicsMC2Step(
        world, [request], simulation_frequency=60, max_simulation_count_per_frame=1
    )
    solver_ms = (time.perf_counter_ns() - started) / 1.0e6
    assert returned is world and ready is True, status
    write_started = time.perf_counter_ns()
    written = (
        writeback.writeback_gn_attributes(world)
        if domain == "mesh_cloth"
        else writeback.writeback_bone_transforms(world)
    )
    writeback_ms = (time.perf_counter_ns() - write_started) / 1.0e6
    assert written > 0
    bpy.context.view_layer.update()
    slot_id = product_slot.make_mc2_product_slot_id(request.setup_type, request.domain_signature)
    slot = world.solver_slots[slot_id]
    assert "native_context" not in slot.data and "spec" not in slot.data
    owner = slot.data["owner"]
    output = owner.read_output()
    assert output.frame == frame
    return {
        "solver_total": solver_ms,
        "writeback": writeback_ms,
        "total": solver_ms + writeback_ms,
    }


def _allocation_peak(callback) -> int:
    tracemalloc.start()
    try:
        callback()
        return int(tracemalloc.get_traced_memory()[1])
    finally:
        tracemalloc.stop()


def _assert_result(case: str, result: dict) -> None:
    ceiling = CEILINGS[case]
    assert result["cold"]["total"] <= ceiling["cold_ms"]
    assert result["hot"]["p95_ms"] <= ceiling["hot_ms"]
    assert result["config"]["total"] <= ceiling["change_ms"]
    assert result["change"]["total"] <= ceiling["change_ms"]
    assert result["debug"]["total"] <= ceiling["debug_ms"]
    assert result["python_allocation_peak_bytes"] <= ceiling["allocation_bytes"]


def _benchmark_mesh(case: dict) -> dict:
    world = obj = proxy = None
    try:
        obj, proxy, pin = _mesh_object(f"MC2ProductHotspot_{case['name']}_Mesh", case["grid"])
        world = world_types.PhysicsWorldCache()
        request = _mesh_request(world, obj, _profile())
        cold = _run_step(world, request, 1, None, "mesh_cloth")
        hot_records = []
        previous = 1
        for frame in range(2, case["hot_frames"] + 2):
            obj.location.x = 0.03 * math.sin(frame * 0.13)
            hot_records.append(_run_step(world, request, frame, previous, "mesh_cloth"))
            previous = frame
        config_request = _mesh_request(world, obj, _profile(gravity_direction=(0.0, -1.0, 0.0)))
        config = _run_step(world, config_request, previous + 1, previous, "mesh_cloth")
        previous += 1
        pin.add((case["grid"],), 1.0, "REPLACE")
        obj.update_tag()
        bpy.context.view_layer.update()
        change_request = _mesh_request(world, obj, _profile(gravity_direction=(0.0, -1.0, 0.0)))
        change = _run_step(world, change_request, previous + 1, previous, "mesh_cloth")
        previous += 1
        assert debug.request_mc2_debug_capture(world, filters={"show_topology": True, "show_output": True}) == 1
        debug_result = _run_step(world, change_request, previous + 1, previous, "mesh_cloth")
        allocation_peak = _allocation_peak(
            lambda: _run_step(world, change_request, previous + 2, previous + 1, "mesh_cloth")
        )
        result = {
            "domain": "mesh_cloth", "case": case["name"], "particles": case["grid"] ** 2,
            "cold": cold, "hot": _summary(record["total"] for record in hot_records[2:]),
            "config": config, "change": change, "debug": debug_result,
            "python_allocation_peak_bytes": allocation_peak, "ceiling": CEILINGS[case["name"]],
        }
        _assert_result(case["name"], result)
        return result
    finally:
        if world is not None:
            world.omni_cache_dispose("mc2 product hotspot mesh cleanup")
        _remove_object(proxy)
        _remove_object(obj)


def _benchmark_bone(case: dict) -> dict:
    world = armature = None
    try:
        armature, chains = _armature(f"MC2ProductHotspot_{case['name']}_Bone", case["chains"], case["chain_length"])
        world = world_types.PhysicsWorldCache()
        request = _bone_request(armature, _profile(bone=True))
        cold = _run_step(world, request, 1, None, "bone_cloth")
        hot_records = []
        previous = 1
        for frame in range(2, case["hot_frames"] + 2):
            parent = armature.pose.bones["Parent"]
            parent.rotation_mode = "XYZ"
            parent.rotation_euler.z = 0.1 * math.sin(frame * 0.11)
            hot_records.append(_run_step(world, request, frame, previous, "bone_cloth"))
            previous = frame
        config_request = _bone_request(armature, _profile(bone=True, gravity_direction=(0.0, -1.0, 0.0)))
        config = _run_step(world, config_request, previous + 1, previous, "bone_cloth")
        previous += 1
        bpy.context.view_layer.objects.active = armature
        armature.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        armature.data.edit_bones[chains[-1][-1]].tail.z += 0.125
        bpy.ops.object.mode_set(mode="OBJECT")
        armature.select_set(False)
        bpy.context.view_layer.update()
        change_request = _bone_request(armature, _profile(bone=True, gravity_direction=(0.0, -1.0, 0.0)))
        change = _run_step(world, change_request, previous + 1, previous, "bone_cloth")
        previous += 1
        assert debug.request_mc2_debug_capture(world, filters={"show_topology": True, "show_output": True}) == 1
        debug_result = _run_step(world, change_request, previous + 1, previous, "bone_cloth")
        allocation_peak = _allocation_peak(
            lambda: _run_step(world, change_request, previous + 2, previous + 1, "bone_cloth")
        )
        result = {
            "domain": "bone_cloth", "case": case["name"],
            "particles": case["chains"] * case["chain_length"], "cold": cold,
            "hot": _summary(record["total"] for record in hot_records[2:]),
            "config": config, "change": change, "debug": debug_result,
            "python_allocation_peak_bytes": allocation_peak, "ceiling": CEILINGS[case["name"]],
        }
        _assert_result(case["name"], result)
        return result
    finally:
        if world is not None:
            world.omni_cache_dispose("mc2 product hotspot bone cleanup")
        _remove_object(armature)


def main() -> None:
    physics_blender.register()
    try:
        results = []
        for case in CASES:
            results.append(_benchmark_mesh(case))
            results.append(_benchmark_bone(case))
        payload = {
            "schema": "mc2_hotspot_benchmark_product_v1",
            "environment": {"blender": bpy.app.version_string, "python": sys.version.split()[0], "substeps": 1, "iterations": 4, "collision": False, "self_collision": False},
            "results": results,
        }
        print("MC2_HOTSPOT_BENCHMARK=" + json.dumps(payload, sort_keys=True))
        print("MC2 product hotspot benchmark: PASS")
    finally:
        if physics_blender.is_registered():
            physics_blender.unregister()


if __name__ == "__main__":
    main()
