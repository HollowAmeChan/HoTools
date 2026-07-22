"""Measure production MC2 stages on fixed Mesh and Bone assets in Blender 4.5."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
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
names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names"
)
nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.nodes"
)
parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs"
)
solver = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.solver"
)
debug = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.debug"
)
native_context = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.native_context"
)
mesh_static = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.static_build"
)
bone_static = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.bone_cloth.static_build"
)
mesh_frame = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.frame_input"
)
bone_frame = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.bone_frame_input"
)
base_pose = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.base_pose"
)


_HOT_FRAMES_OVERRIDE = int(os.environ.get("MC2_BENCH_HOT_FRAMES", "0") or 0)


CASES = (
    {"name": "small", "grid": 10, "chains": 4, "chain_length": 8, "hot_frames": 8},
    {"name": "medium", "grid": 24, "chains": 12, "chain_length": 12, "hot_frames": 7},
    {"name": "large", "grid": 40, "chains": 24, "chain_length": 16, "hot_frames": 6},
)
if _HOT_FRAMES_OVERRIDE > 0:
    CASES = tuple(
        {**case, "hot_frames": _HOT_FRAMES_OVERRIDE}
        for case in CASES
    )

CEILINGS = {
    "small": {"cold_ms": 40.0, "hot_ms": 12.0, "change_ms": 40.0, "debug_ms": 30.0, "allocation_bytes": 4_000_000},
    "medium": {"cold_ms": 80.0, "hot_ms": 20.0, "change_ms": 80.0, "debug_ms": 50.0, "allocation_bytes": 8_000_000},
    "large": {"cold_ms": 160.0, "hot_ms": 40.0, "change_ms": 160.0, "debug_ms": 100.0, "allocation_bytes": 16_000_000},
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


class StageRecorder:
    def __init__(self) -> None:
        self.totals = defaultdict(float)
        self._patches = []

    def patch(self, owner, name: str, stage: str) -> None:
        original = getattr(owner, name)

        def wrapped(*args, **kwargs):
            started = time.perf_counter_ns()
            try:
                return original(*args, **kwargs)
            finally:
                self.totals[stage] += (time.perf_counter_ns() - started) / 1.0e6

        setattr(owner, name, wrapped)
        self._patches.append((owner, name, original))

    def snapshot(self) -> dict:
        return dict(self.totals)

    def delta(self, before: dict) -> dict:
        keys = set(before) | set(self.totals)
        return {
            key: float(self.totals.get(key, 0.0) - before.get(key, 0.0))
            for key in sorted(keys)
        }

    def restore(self) -> None:
        for owner, name, original in reversed(self._patches):
            setattr(owner, name, original)
        self._patches.clear()


def _install_stage_probes() -> StageRecorder:
    recorder = StageRecorder()
    recorder.patch(solver, "prepare_observed_static_inputs", "static_observation")
    recorder.patch(solver, "build_mc2_topology_spec", "topology_fingerprint")
    recorder.patch(mesh_static, "build_mc2_mesh_cloth_static_for_task", "static_build")
    recorder.patch(bone_static, "build_mc2_bone_cloth_static_for_task", "static_build")
    recorder.patch(mesh_frame, "build_mc2_mesh_frame_input_for_task", "frame_prepare")
    recorder.patch(bone_frame, "build_mc2_bone_frame_input", "frame_prepare")
    recorder.patch(native_context.MC2NativeContextV0, "clone_mesh_config_static", "static_clone")
    recorder.patch(native_context.MC2NativeContextV0, "clone_bone_config_static", "static_clone")
    recorder.patch(native_context.MC2NativeInteractionV0, "step_group", "all_task_group_step")
    recorder.patch(solver, "make_mc2_result_candidate", "result_build")
    recorder.patch(solver, "make_mc2_mesh_result", "result_build")
    recorder.patch(solver, "make_mc2_bone_result", "result_build")
    recorder.patch(solver, "merge_mc2_bone_results", "result_build")
    recorder.patch(solver, "make_mc2_stats_result", "result_build")
    recorder.patch(solver, "publish_mc2_result_transaction", "result_publish")
    recorder.patch(solver, "capture_requested_mc2_debug", "debug_capture")
    return recorder


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
        uv_layer.data[loop.index].uv = positions[loop.vertex_index][:2]
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


def _profile():
    return parameters.make_mc2_particle_profile(
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


def _run_step(recorder, world, tasks, frame, previous, domain) -> dict:
    bpy.context.scene.frame_set(frame)
    _set_world_frame(world, frame, previous)
    before = recorder.snapshot()
    started = time.perf_counter_ns()
    _, ready, status = nodes.physicsMC2Step(
        world,
        tasks,
        simulation_frequency=60,
        max_simulation_count_per_frame=1,
    )
    solver_ms = (time.perf_counter_ns() - started) / 1.0e6
    assert ready, status
    write_started = time.perf_counter_ns()
    if domain == "mesh_cloth":
        written = writeback.writeback_gn_attributes(world)
    else:
        written = writeback.writeback_bone_transforms(world)
    writeback_ms = (time.perf_counter_ns() - write_started) / 1.0e6
    assert written > 0
    # 提交本帧写回产生的 depsgraph 更新；下一项 authoring 修改属于下一安全批次。
    bpy.context.view_layer.update()
    stages = recorder.delta(before)
    stages.update({
        "solver_total": solver_ms,
        "writeback": writeback_ms,
        "total": solver_ms + writeback_ms,
    })
    return stages


def _hot_summary(records) -> dict:
    keys = sorted({key for record in records for key in record})
    return {key: _summary(record.get(key, 0.0) for record in records) for key in keys}


def _allocation_peak(callback) -> int:
    tracemalloc.start()
    try:
        callback()
        return int(tracemalloc.get_traced_memory()[1])
    finally:
        tracemalloc.stop()


def _assert_ceilings(case: str, result: dict) -> None:
    ceiling = CEILINGS[case]
    assert result["cold"]["total"] <= ceiling["cold_ms"]
    assert result["hot"]["total"]["p95_ms"] <= ceiling["hot_ms"]
    assert result["config"]["total"] <= ceiling["change_ms"]
    assert result["change"]["total"] <= ceiling["change_ms"]
    assert result["debug"]["total"] <= ceiling["debug_ms"]
    assert result["python_allocation_peak_bytes"] <= ceiling["allocation_bytes"]


def _assert_stage_coverage(result: dict) -> None:
    cold = result["cold"]
    hot = result["hot"]
    config = result["config"]
    change = result["change"]
    debug_result = result["debug"]
    assert cold["static_observation"] > 0.0
    assert cold["topology_fingerprint"] > 0.0
    assert cold["static_build"] > 0.0
    assert hot["static_observation"]["mean_ms"] > 0.0
    assert hot["frame_prepare"]["mean_ms"] > 0.0
    assert hot["all_task_group_step"]["mean_ms"] > 0.0
    assert hot["result_build"]["mean_ms"] > 0.0
    assert hot["result_publish"]["mean_ms"] > 0.0
    assert hot["writeback"]["mean_ms"] > 0.0
    assert hot["static_build"]["max_ms"] == 0.0
    assert config["static_clone"] > 0.0
    assert config["static_build"] == 0.0
    assert change["static_build"] > 0.0
    assert debug_result["debug_capture"] > 0.0


def _benchmark_mesh(case, recorder) -> dict:
    obj = base_object = world = None
    try:
        obj, pin = _make_grid(f"MC2Hotspot_{case['name']}_Mesh", case["grid"])
        bpy.context.view_layer.update()
        base_object = base_pose.ensure_base_pose_proxy(
            obj,
            expected_mesh_topology_signature=base_pose.mesh_topology_signature(obj),
        )
        world = world_types.PhysicsWorldCache()
        world.generation = 1
        task = specs.make_mc2_task_spec(names.MC2_SETUP_MESH_CLOTH, [obj], profile=_profile())
        cold = _run_step(recorder, world, (task,), 1, None, "mesh_cloth")
        previous = 1
        hot_records = []
        for frame in range(2, case["hot_frames"] + 2):
            obj.location.x = 0.03 * math.sin(frame * 0.13)
            bpy.context.view_layer.update()
            hot_records.append(_run_step(recorder, world, (task,), frame, previous, "mesh_cloth"))
            previous = frame
        config_task = specs.make_mc2_task_spec(
            names.MC2_SETUP_MESH_CLOTH,
            [obj],
            profile=replace(_profile(), gravity_direction=(0.0, -1.0, 0.0)),
        )
        assert config_task.task_id == task.task_id
        config = _run_step(recorder, world, (config_task,), previous + 1, previous, "mesh_cloth")
        previous += 1
        pin.add((case["grid"],), 1.0, "REPLACE")
        obj.update_tag()
        bpy.context.view_layer.update()
        change = _run_step(recorder, world, (config_task,), previous + 1, previous, "mesh_cloth")
        previous += 1
        assert debug.request_mc2_debug_capture(
            world, filters={"show_topology": True, "show_output": True}
        ) == 1
        debug_result = _run_step(recorder, world, (config_task,), previous + 1, previous, "mesh_cloth")
        previous += 1
        allocation_peak = _allocation_peak(
            lambda: _run_step(recorder, world, (config_task,), previous + 1, previous, "mesh_cloth")
        )
        result = {
            "domain": "mesh_cloth",
            "case": case["name"],
            "particles": case["grid"] ** 2,
            "cold": cold,
            "hot": _hot_summary(hot_records[2:]),
            "config": config,
            "change_kind": "surface_pin",
            "change": change,
            "debug": debug_result,
            "python_allocation_peak_bytes": allocation_peak,
            "ceiling": CEILINGS[case["name"]],
        }
        _assert_ceilings(case["name"], result)
        _assert_stage_coverage(result)
        return result
    finally:
        if world is not None:
            world.omni_cache_dispose("mc2 hotspot benchmark")
        _remove_object(base_object)
        _remove_object(obj)


def _benchmark_bone(case, recorder) -> dict:
    armature = world = None
    try:
        armature, chains = _make_product_armature(
            f"MC2Hotspot_{case['name']}_Bone",
            case["chains"],
            case["chain_length"],
        )
        bpy.context.view_layer.update()
        world = world_types.PhysicsWorldCache()
        world.generation = 1
        task = nodes._physicsMC2BoneClothTaskV0Oracle(
            [(armature, "Parent")], profile=_profile(), connection_mode=1
        )[0][0]
        cold = _run_step(recorder, world, (task,), 1, None, "bone_cloth")
        previous = 1
        hot_records = []
        for frame in range(2, case["hot_frames"] + 2):
            parent = armature.pose.bones["Parent"]
            parent.rotation_mode = "XYZ"
            parent.rotation_euler.z = 0.1 * math.sin(frame * 0.11)
            bpy.context.view_layer.update()
            hot_records.append(_run_step(recorder, world, (task,), frame, previous, "bone_cloth"))
            previous = frame
        config_task = nodes._physicsMC2BoneClothTaskV0Oracle(
            [(armature, "Parent")],
            profile=replace(_profile(), gravity_direction=(0.0, -1.0, 0.0)),
            connection_mode=1,
        )[0][0]
        assert config_task.task_id == task.task_id
        config = _run_step(recorder, world, (config_task,), previous + 1, previous, "bone_cloth")
        previous += 1
        bpy.context.view_layer.objects.active = armature
        armature.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        armature.data.edit_bones[chains[-1][-1]].tail.z += 0.125
        bpy.ops.object.mode_set(mode="OBJECT")
        armature.select_set(False)
        bpy.context.view_layer.update()
        change = _run_step(recorder, world, (config_task,), previous + 1, previous, "bone_cloth")
        previous += 1
        assert debug.request_mc2_debug_capture(
            world, filters={"show_topology": True, "show_output": True}
        ) == 1
        debug_result = _run_step(recorder, world, (config_task,), previous + 1, previous, "bone_cloth")
        previous += 1
        allocation_peak = _allocation_peak(
            lambda: _run_step(recorder, world, (config_task,), previous + 1, previous, "bone_cloth")
        )
        result = {
            "domain": "bone_cloth",
            "case": case["name"],
            "particles": case["chains"] * case["chain_length"],
            "cold": cold,
            "hot": _hot_summary(hot_records[2:]),
            "config": config,
            "change_kind": "geometry_rest_tail",
            "change": change,
            "debug": debug_result,
            "python_allocation_peak_bytes": allocation_peak,
            "ceiling": CEILINGS[case["name"]],
        }
        _assert_ceilings(case["name"], result)
        _assert_stage_coverage(result)
        return result
    finally:
        if world is not None:
            world.omni_cache_dispose("mc2 hotspot benchmark")
        _remove_object(armature)


def main() -> None:
    physics_blender.register()
    recorder = _install_stage_probes()
    try:
        results = []
        for case in CASES:
            results.append(_benchmark_mesh(case, recorder))
            results.append(_benchmark_bone(case, recorder))
        payload = {
            "schema": "mc2_hotspot_benchmark_v0",
            "environment": {
                "blender": bpy.app.version_string,
                "python": sys.version.split()[0],
                "substeps": 1,
                "iterations": 4,
                "collision": False,
                "self_collision": False,
            },
            "results": results,
        }
        print("MC2_HOTSPOT_BENCHMARK=" + json.dumps(payload, sort_keys=True))
        print("MC2 hotspot benchmark: PASS")
    finally:
        recorder.restore()
        if physics_blender.is_registered():
            physics_blender.unregister()


if __name__ == "__main__":
    main()
