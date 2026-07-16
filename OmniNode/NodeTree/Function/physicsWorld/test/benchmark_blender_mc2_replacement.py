"""Compare the legacy CPP full-core and Physics World MC2 production paths."""

from __future__ import annotations

import importlib
import cProfile
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
from mathutils import Vector


HERE = os.path.dirname(os.path.abspath(__file__))
PHYSICS_WORLD = os.path.dirname(HERE)
FUNCTION = os.path.dirname(PHYSICS_WORLD)
NODETREE = os.path.dirname(FUNCTION)
OMNINODE = os.path.dirname(NODETREE)
HOTOOLS = os.path.dirname(OMNINODE)

for path in (HOTOOLS, os.path.dirname(HOTOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PHYSICS_WORLD),
    (
        "HoTools.OmniNode.NodeTree.Function.physicsMC2MeshCloth",
        os.path.join(FUNCTION, "physicsMC2MeshCloth"),
    ),
    (
        "HoTools.OmniNode.NodeTree.Function.physicsMC2MeshCloth.runtime",
        os.path.join(FUNCTION, "physicsMC2MeshCloth", "runtime"),
    ),
    (
        "HoTools.OmniNode.NodeTree.Function.physicsMC2BoneCloth",
        os.path.join(FUNCTION, "physicsMC2BoneCloth"),
    ),
    (
        "HoTools.OmniNode.NodeTree.Function.physicsMC2BoneCloth.runtime",
        os.path.join(FUNCTION, "physicsMC2BoneCloth", "runtime"),
    ),
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
mc2_names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names"
)
mc2_nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.nodes"
)
mc2_parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
mc2_specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs"
)
mc2_debug = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.debug"
)
mc2_base_pose = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.base_pose"
)
legacy_mesh = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsMC2MeshCloth.runtime.controller"
)
legacy_bone = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsMC2BoneCloth.runtime.controller"
)


CASES = (
    {"name": "small", "grid": 10, "chains": 4, "chain_length": 8, "frames": 18},
    {"name": "medium", "grid": 24, "chains": 12, "chain_length": 12, "frames": 14},
    {"name": "large", "grid": 40, "chains": 24, "chain_length": 16, "frames": 10},
)


def _percentile_95(values) -> float:
    ordered = sorted(float(value) for value in values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _summary(values) -> dict:
    return {
        "samples": len(values),
        "mean_ms": statistics.fmean(values),
        "p95_ms": _percentile_95(values),
        "max_ms": max(values),
    }


def _cache_payload(value):
    return getattr(value, "value", value)


def _set_world_frame(world, frame: int, previous: int | None) -> None:
    context = world.frame_context
    context.previous_frame = previous
    context.frame = frame
    context.continuous = previous is not None and frame == previous + 1
    context.same_frame = previous == frame
    context.reset_requested = False
    context.restart_required = previous is None
    context.raw_dt = 1.0 / 60.0
    context.dt = 1.0 / 60.0
    context.time_scale = 1.0
    context.substeps = 1
    context.generation = 1


def _remove_object(obj) -> None:
    if obj is None or obj.name not in bpy.data.objects:
        return
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is None or data.users:
        return
    if isinstance(data, bpy.types.Mesh):
        bpy.data.meshes.remove(data)
    elif isinstance(data, bpy.types.Armature):
        bpy.data.armatures.remove(data)


def _make_grid(name: str, width: int):
    positions = []
    faces = []
    denominator = max(width - 1, 1)
    for y in range(width):
        for x in range(width):
            positions.append((x / denominator, y / denominator, 0.0))
    for y in range(width - 1):
        for x in range(width - 1):
            first = y * width + x
            faces.append((first, first + 1, first + width + 1))
            faces.append((first, first + width + 1, first + width))
    mesh = bpy.data.meshes.new(f"{name}Data")
    mesh.from_pydata(positions, (), faces)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        vertex = positions[loop.vertex_index]
        uv_layer.data[loop.index].uv = vertex[:2]
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    pin = obj.vertex_groups.new(name="MC2Pin")
    pin.add(tuple(range(width)), 1.0, "REPLACE")
    props = obj.hotools_mesh_collision
    props.pin_enabled = True
    props.pin_vertex_group = pin.name
    return obj, pin


def _make_product_armature(name: str, chain_count: int, chain_length: int):
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
        names = []
        for depth in range(chain_length):
            bone = data.edit_bones.new(f"Chain{chain_index}_{depth}")
            bone.head = (x, depth * 0.12, 1.0)
            bone.tail = (x, (depth + 1) * 0.12, 1.0)
            bone.parent = previous
            bone.use_connect = depth > 0
            previous = bone
            names.append(bone.name)
        chains.append(names)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj, chains


def _profile():
    return mc2_parameters.make_mc2_particle_profile(
        gravity=9.0,
        damping=0.1,
        radius=0.02,
        tether_compression=0.4,
        distance_stiffness=1.0,
        bending_stiffness=1.0,
        angle_restoration_enabled=True,
        angle_restoration_stiffness=0.2,
        angle_restoration_velocity_attenuation=0.8,
        collision_mode=0,
        self_collision_mode=0,
        self_collision_sync_mode=0,
    )


def _legacy_mesh_settings(obj):
    return [{
        "proxy_obj": obj,
        "enabled": True,
        "blend_weight": 1.0,
        "damping": 0.1,
        "use_tether": True,
        "tether_compression": 0.4,
        "use_distance": True,
        "distance_stiffness": 1.0,
        "use_bend": True,
        "bend_stiffness": 1.0,
        "use_angle_restoration": True,
        "angle_restoration_stiffness": 0.2,
        "angle_restoration_velocity_attenuation": 0.8,
        "angle_restoration_gravity_falloff": 0.0,
        "use_angle_limit": False,
        "angle_limit": 60.0,
        "angle_limit_stiffness": 1.0,
        "collision_radius": 0.02,
        "use_max_distance": False,
        "use_backstop": False,
        "motion_stiffness": 1.0,
    }]


def _legacy_mesh_step(cache, obj, frame: int):
    bpy.context.scene.frame_set(frame)
    result = legacy_mesh.run_mesh_cloth_mc2_node(
        cache_state=cache,
        mesh_cloth_settings=_legacy_mesh_settings(obj),
        scene=bpy.context.scene,
        enabled=True,
        reset=False,
        substeps=1,
        iterations=4,
        gravity_dir=Vector((0.0, 0.0, -1.0)),
        gravity_power=9.0,
        gravity_falloff=0.0,
        stablization_time_after_reset=0.1,
        anchor_obj=None,
        anchor_inertia=0.0,
        world_inertia=1.0,
        movement_inertia_smoothing=0.4,
        local_inertia=1.0,
        depth_inertia=0.0,
        centrifugal=0.0,
        movement_speed_limit=5.0,
        rotation_speed_limit=720.0,
        local_movement_speed_limit=-1.0,
        local_rotation_speed_limit=-1.0,
        particle_speed_limit=4.0,
        teleport_mode=0,
        teleport_distance=0.5,
        teleport_rotation=90.0,
        normal_axis=1,
        animation_pose_ratio=0.0,
        use_collider_collision=False,
        collider_friction=0.05,
        collider_collision_mode=0,
        time_scale=1.0,
        skip_writing=False,
        debug_output=False,
        solver_backend="cpp",
    )
    return _cache_payload(result[0])


def _new_mesh_step(world, task, settings, frame: int, previous: int | None):
    bpy.context.scene.frame_set(frame)
    _set_world_frame(world, frame, previous)
    started = time.perf_counter_ns()
    _, ready, status = mc2_nodes.physicsMC2Step(world, [task], settings=settings)
    step_ms = (time.perf_counter_ns() - started) / 1.0e6
    assert ready, status
    write_started = time.perf_counter_ns()
    assert writeback.writeback_gn_attributes(world) == 1
    write_ms = (time.perf_counter_ns() - write_started) / 1.0e6
    return step_ms, write_ms


def _numpy_bytes(value, seen=None) -> int:
    seen = seen if seen is not None else set()
    identity = id(value)
    if identity in seen:
        return 0
    seen.add(identity)
    if isinstance(value, np.ndarray):
        return int(value.nbytes)
    if isinstance(value, dict):
        return sum(_numpy_bytes(item, seen) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return sum(_numpy_bytes(item, seen) for item in value)
    if hasattr(value, "__dict__"):
        return _numpy_bytes(vars(value), seen)
    return 0


def _allocation_peak(callback) -> int:
    tracemalloc.start()
    try:
        callback()
        return int(tracemalloc.get_traced_memory()[1])
    finally:
        tracemalloc.stop()


def _profile_call(callback):
    profiler = cProfile.Profile()
    result = profiler.runcall(callback)
    records = []
    for entry in profiler.getstats():
        code = entry.code
        if isinstance(code, str):
            continue
        filename = str(code.co_filename)
        if "HoTools" not in filename:
            continue
        records.append({
            "function": f"{os.path.basename(filename)}:{code.co_firstlineno}:{code.co_name}",
            "calls": int(entry.callcount),
            "self_ms": float(entry.inlinetime) * 1000.0,
            "cumulative_ms": float(entry.totaltime) * 1000.0,
        })
    records.sort(key=lambda item: item["cumulative_ms"], reverse=True)
    return result, records[:16]


def _benchmark_mesh(case: dict, backend: str) -> dict:
    obj = pin = base_object = None
    cache = world = None
    try:
        obj, pin = _make_grid(f"MC2_{backend}_{case['name']}_Mesh", case["grid"])
        bpy.context.view_layer.update()
        base_object = mc2_base_pose.ensure_base_pose_proxy(
            obj,
            expected_mesh_topology_signature=mc2_base_pose.mesh_topology_signature(obj),
        )
        if backend == "legacy_cpp":
            started = time.perf_counter_ns()
            cache = _legacy_mesh_step(None, obj, 1)
            build_ms = (time.perf_counter_ns() - started) / 1.0e6
            timings = []
            for frame in range(2, case["frames"] + 2):
                obj.location.x = 0.03 * math.sin(frame * 0.13)
                bpy.context.view_layer.update()
                started = time.perf_counter_ns()
                cache = _legacy_mesh_step(cache, obj, frame)
                timings.append((time.perf_counter_ns() - started) / 1.0e6)
            pin.add((case["grid"],), 1.0, "REPLACE")
            started = time.perf_counter_ns()
            replacement_cache = _legacy_mesh_step(None, obj, case["frames"] + 2)
            rebuild_ms = (time.perf_counter_ns() - started) / 1.0e6
            dispose = getattr(cache, "omni_cache_dispose", None)
            if callable(dispose):
                dispose("replacement benchmark static rebuild")
            cache = replacement_cache
            allocation_peak = _allocation_peak(
                lambda: _legacy_mesh_step(cache, obj, case["frames"] + 3)
            )
            native_info = getattr(getattr(cache, "native_context", None), "native_info", None) or {}
            return {
                "backend": backend,
                "domain": "mesh_cloth",
                "case": case["name"],
                "particles": case["grid"] ** 2,
                "build_ms": build_ms,
                "rebuild_ms": rebuild_ms,
                "hot": _summary(timings[2:]),
                "write_mean_ms": None,
                "debug_capture_ms": None,
                "python_allocation_peak_bytes": allocation_peak,
                "host_numpy_bytes": _numpy_bytes(cache),
                "native_estimated_bytes": native_info.get("estimated_bytes"),
            }

        world = world_types.PhysicsWorldCache()
        world.generation = 1
        task = mc2_specs.make_mc2_task_spec(
            mc2_names.MC2_SETUP_MESH_CLOTH,
            [obj],
            profile=_profile(),
        )
        settings = mc2_parameters.make_mc2_solver_settings(
            substeps=1,
            iterations=4,
            simulation_frequency=60,
            max_simulation_count_per_frame=1,
        )
        build_profile_top = None
        step_ms, write_ms = _new_mesh_step(world, task, settings, 1, None)
        build_ms = step_ms + write_ms
        timings = []
        writes = []
        previous = 1
        for frame in range(2, case["frames"] + 2):
            obj.location.x = 0.03 * math.sin(frame * 0.13)
            bpy.context.view_layer.update()
            step_ms, write_ms = _new_mesh_step(world, task, settings, frame, previous)
            timings.append(step_ms + write_ms)
            writes.append(write_ms)
            previous = frame
        profile_top = None
        if case["name"] == "large":
            (profile_result, profile_top) = _profile_call(
                lambda: _new_mesh_step(
                    world, task, settings, case["frames"] + 2, previous
                )
            )
            previous = case["frames"] + 2
        pin.add((case["grid"],), 1.0, "REPLACE")
        step_ms, write_ms = _new_mesh_step(
            world, task, settings, case["frames"] + 3, previous
        )
        rebuild_ms = step_ms + write_ms
        previous = case["frames"] + 3
        if case["name"] == "large":
            pin.add((case["grid"] + 1,), 1.0, "REPLACE")
            ((_profile_step, _profile_write), build_profile_top) = _profile_call(
                lambda: _new_mesh_step(
                    world, task, settings, case["frames"] + 4, previous
                )
            )
            previous = case["frames"] + 4
        assert mc2_debug.request_mc2_debug_capture(world) == 1
        step_ms, write_ms = _new_mesh_step(
            world, task, settings, previous + 1, previous
        )
        debug_capture_ms = step_ms + write_ms
        previous += 1
        allocation_peak = _allocation_peak(
            lambda: _new_mesh_step(
                world, task, settings, previous + 1, previous
            )
        )
        slot = world.solver_slots[task.task_id]
        native_info = slot.data["native_context"].inspect()
        return {
            "backend": backend,
            "domain": "mesh_cloth",
            "case": case["name"],
            "particles": case["grid"] ** 2,
            "build_ms": build_ms,
            "rebuild_ms": rebuild_ms,
            "hot": _summary(timings[2:]),
            "write_mean_ms": statistics.fmean(writes[2:]),
            "debug_capture_ms": debug_capture_ms,
            "python_allocation_peak_bytes": allocation_peak,
            "host_numpy_bytes": _numpy_bytes(slot.data),
            "native_estimated_bytes": native_info.get("estimated_bytes"),
            "profile_top": profile_top,
            "build_profile_top": build_profile_top,
        }
    finally:
        if world is not None:
            world.omni_cache_dispose("replacement benchmark")
        dispose = getattr(cache, "omni_cache_dispose", None)
        if callable(dispose):
            dispose("replacement benchmark")
        _remove_object(base_object)
        _remove_object(obj)


def _legacy_bone_settings(armature, chains):
    physics = {
        "blend_weight": 1.0,
        "rotational_interpolation": 1.0,
        "damping": 0.1,
        "use_tether": True,
        "tether_compression": 0.4,
        "use_distance": True,
        "distance_stiffness": 1.0,
        "use_bend": True,
        "bend_stiffness": 1.0,
        "use_angle_restoration": True,
        "angle_restoration_stiffness": 0.2,
        "angle_restoration_velocity_attenuation": 0.8,
        "use_angle_limit": False,
        "use_max_distance": False,
        "use_backstop": False,
        "motion_stiffness": 1.0,
        "use_collider_collision": False,
        "collider_collision_mode": 0,
    }
    return [
        {
            "armature": armature,
            "root_bone": names[0],
            "bones": list(names),
            "enabled": True,
            "lateral_group": "benchmark",
            "params": physics,
        }
        for names in chains
    ]


def _legacy_bone_step(cache, armature, chains, frame: int):
    bpy.context.scene.frame_set(frame)
    result = legacy_bone.run_bone_cloth_mc2_node(
        cache_state=cache,
        bone_cloth_chains=_legacy_bone_settings(armature, chains),
        connection_mode=1,
        scene=bpy.context.scene,
        enabled=True,
        reset=False,
        substeps=1,
        iterations=4,
        gravity_dir=Vector((0.0, 0.0, -1.0)),
        gravity_power=9.0,
        gravity_falloff=0.0,
        stablization_time_after_reset=0.1,
        anchor_obj=None,
        anchor_inertia=0.0,
        world_inertia=1.0,
        movement_inertia_smoothing=0.4,
        local_inertia=1.0,
        depth_inertia=0.0,
        centrifugal=0.0,
        movement_speed_limit=5.0,
        rotation_speed_limit=720.0,
        local_movement_speed_limit=-1.0,
        local_rotation_speed_limit=-1.0,
        particle_speed_limit=4.0,
        teleport_mode=0,
        teleport_distance=0.5,
        teleport_rotation=90.0,
        time_scale=1.0,
        skip_writing=False,
        debug_output=False,
        use_self_collision=False,
        solver_backend="cpp",
    )
    return _cache_payload(result[0])


def _new_bone_step(world, task, settings, frame: int, previous: int | None):
    bpy.context.scene.frame_set(frame)
    _set_world_frame(world, frame, previous)
    started = time.perf_counter_ns()
    _, ready, status = mc2_nodes.physicsMC2Step(world, [task], settings=settings)
    step_ms = (time.perf_counter_ns() - started) / 1.0e6
    assert ready, status
    write_started = time.perf_counter_ns()
    written = writeback.writeback_bone_transforms(world)
    write_ms = (time.perf_counter_ns() - write_started) / 1.0e6
    assert written > 0
    return step_ms, write_ms


def _benchmark_bone(case: dict, backend: str) -> dict:
    armature = None
    cache = world = None
    try:
        armature, chains = _make_product_armature(
            f"MC2_{backend}_{case['name']}_Bone",
            case["chains"],
            case["chain_length"],
        )
        bpy.context.view_layer.update()
        if backend == "legacy_cpp":
            started = time.perf_counter_ns()
            cache = _legacy_bone_step(None, armature, chains, 1)
            build_ms = (time.perf_counter_ns() - started) / 1.0e6
            timings = []
            for frame in range(2, case["frames"] + 2):
                armature.pose.bones["Parent"].rotation_mode = "XYZ"
                armature.pose.bones["Parent"].rotation_euler.z = 0.1 * math.sin(frame * 0.11)
                bpy.context.view_layer.update()
                started = time.perf_counter_ns()
                cache = _legacy_bone_step(cache, armature, chains, frame)
                timings.append((time.perf_counter_ns() - started) / 1.0e6)
            allocation_peak = _allocation_peak(
                lambda: _legacy_bone_step(cache, armature, chains, case["frames"] + 2)
            )
            return {
                "backend": backend,
                "domain": "bone_cloth",
                "case": case["name"],
                "particles": case["chains"] * case["chain_length"],
                "build_ms": build_ms,
                "rebuild_ms": None,
                "hot": _summary(timings[2:]),
                "write_mean_ms": None,
                "debug_capture_ms": None,
                "python_allocation_peak_bytes": allocation_peak,
                "host_numpy_bytes": _numpy_bytes(cache),
                "native_estimated_bytes": None,
            }

        world = world_types.PhysicsWorldCache()
        world.generation = 1
        tasks = mc2_nodes.physicsMC2BoneClothTask(
            [(armature, "Parent")],
            profile=_profile(),
            connection_mode=1,
        )
        assert len(tasks) == 1
        task = tasks[0]
        settings = mc2_parameters.make_mc2_solver_settings(
            substeps=1,
            iterations=4,
            simulation_frequency=60,
            max_simulation_count_per_frame=1,
        )
        step_ms, write_ms = _new_bone_step(world, task, settings, 1, None)
        build_ms = step_ms + write_ms
        timings = []
        writes = []
        previous = 1
        for frame in range(2, case["frames"] + 2):
            armature.pose.bones["Parent"].rotation_mode = "XYZ"
            armature.pose.bones["Parent"].rotation_euler.z = 0.1 * math.sin(frame * 0.11)
            bpy.context.view_layer.update()
            step_ms, write_ms = _new_bone_step(world, task, settings, frame, previous)
            timings.append(step_ms + write_ms)
            writes.append(write_ms)
            previous = frame
        profile_top = None
        if case["name"] == "large":
            (profile_result, profile_top) = _profile_call(
                lambda: _new_bone_step(
                    world, task, settings, case["frames"] + 2, previous
                )
            )
            previous = case["frames"] + 2
        allocation_peak = _allocation_peak(
            lambda: _new_bone_step(
                world, task, settings, case["frames"] + 3, previous
            )
        )
        slot = world.solver_slots[task.task_id]
        native_info = slot.data["native_context"].inspect()
        return {
            "backend": backend,
            "domain": "bone_cloth",
            "case": case["name"],
            "particles": case["chains"] * case["chain_length"],
            "build_ms": build_ms,
            "rebuild_ms": None,
            "hot": _summary(timings[2:]),
            "write_mean_ms": statistics.fmean(writes[2:]),
            "debug_capture_ms": None,
            "python_allocation_peak_bytes": allocation_peak,
            "host_numpy_bytes": _numpy_bytes(slot.data),
            "native_estimated_bytes": native_info.get("estimated_bytes"),
            "profile_top": profile_top,
        }
    finally:
        if world is not None:
            world.omni_cache_dispose("replacement benchmark")
        if isinstance(cache, dict):
            for owner in cache.get("armatures", {}).values():
                dispose = getattr(owner, "omni_cache_dispose", None)
                if callable(dispose):
                    dispose("replacement benchmark")
        _remove_object(armature)


def main() -> None:
    physics_blender.register()
    results = []
    try:
        for case in CASES:
            for backend in ("legacy_cpp", "physics_world"):
                results.append(_benchmark_mesh(case, backend))
                results.append(_benchmark_bone(case, backend))
        comparisons = []
        for domain in ("mesh_cloth", "bone_cloth"):
            for case in CASES:
                legacy = next(
                    item for item in results
                    if item["domain"] == domain and item["case"] == case["name"]
                    and item["backend"] == "legacy_cpp"
                )
                current = next(
                    item for item in results
                    if item["domain"] == domain and item["case"] == case["name"]
                    and item["backend"] == "physics_world"
                )
                comparisons.append({
                    "domain": domain,
                    "case": case["name"],
                    "hot_speedup": legacy["hot"]["mean_ms"] / current["hot"]["mean_ms"],
                    "build_speedup": legacy["build_ms"] / current["build_ms"],
                })
        payload = {
            "schema": "mc2_replacement_benchmark_v0",
            "environment": {"blender": bpy.app.version_string, "python": sys.version.split()[0]},
            "common_domain": {
                "substeps": 1,
                "iterations": 4,
                "collision": False,
                "self_collision": False,
                "legacy_backend": "cpp_full_core",
            },
            "results": results,
            "comparisons": comparisons,
        }
        print("MC2_REPLACEMENT_BENCHMARK=" + json.dumps(payload, sort_keys=True))
    finally:
        if physics_blender.is_registered():
            physics_blender.unregister()


if __name__ == "__main__":
    main()
