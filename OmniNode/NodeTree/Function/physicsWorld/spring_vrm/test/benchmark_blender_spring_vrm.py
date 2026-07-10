"""Reproducible old-vs-world SpringBone benchmark for Blender background mode.

Usage:
    blender.exe --background --factory-startup --python spring_vrm/test/benchmark_blender_spring_vrm.py

Environment:
    SPRING_BENCH_SIZES=8,32,128
    SPRING_BENCH_WARMUP=20
    SPRING_BENCH_FRAMES=120
    SPRING_BENCH_COLLIDERS=0
"""

from __future__ import annotations

import importlib.util
import cProfile
import io
import json
import os
import runpy
import statistics
import sys
import time
import types
import pstats
from pathlib import Path

import bpy


HERE = Path(__file__).resolve().parent
HOTOOLS = HERE.parents[5]
HARNESS_PATH = HERE / "test_blender_spring_vrm.py"


def _load_harness() -> dict:
    return runpy.run_path(str(HARNESS_PATH), run_name="spring_vrm_benchmark_harness")


def _install_legacy_import_stubs() -> None:
    physics_tools_name = "HoTools.PhysicsTools"
    if physics_tools_name not in sys.modules:
        package = types.ModuleType(physics_tools_name)
        package.__path__ = [str(HOTOOLS / "PhysicsTools")]
        package.__package__ = physics_tools_name
        sys.modules[physics_tools_name] = package

    delta_name = f"{physics_tools_name}.deltaOutput"
    if delta_name not in sys.modules:
        module = types.ModuleType(delta_name)

        class PhysicsDeltaOutputSpec:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        module.PhysicsDeltaOutputSpec = PhysicsDeltaOutputSpec
        module.clear_delta_attribute = lambda *args, **kwargs: None
        module.ensure_delta_output = lambda *args, **kwargs: None
        module.write_world_delta_attribute = lambda *args, **kwargs: None
        sys.modules[delta_name] = module

    debug_name = "HoTools.OmniNode.NodeTree.OmniDebug"
    if debug_name not in sys.modules:
        module = types.ModuleType(debug_name)

        class OmniDebug:
            @staticmethod
            def _text(value, *args, **kwargs):
                return str(value)

            str_color = _text
            func_label = _text
            value_label = _text
            section_label = _text
            node_label = _text

        module.OmniDebug = OmniDebug
        sys.modules[debug_name] = module


def _load_legacy_module():
    _install_legacy_import_stubs()
    name = "HoTools.OmniNode.NodeTree.Function.Physics"
    path = HOTOOLS / "OmniNode" / "NodeTree" / "Function" / "Physics.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = name.rsplit(".", 1)[0]
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _make_chain_armature(name: str, simulated_bones: int):
    arm_data = bpy.data.armatures.new(f"{name}Data")
    arm_obj = bpy.data.objects.new(name, arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    parent = arm_data.edit_bones.new("root")
    parent.head = (0.0, 0.0, 0.0)
    parent.tail = (0.0, 0.0, 0.1)
    for index in range(1, simulated_bones + 1):
        bone = arm_data.edit_bones.new(f"bone_{index}")
        bone.parent = parent
        bone.use_connect = True
        bone.head = parent.tail
        bone.tail = (0.0, 0.0, 0.1 * (index + 1))
        parent = bone

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()
    return arm_obj


def _summary(samples: list[float]) -> dict:
    ordered = sorted(samples)
    p95_index = min(len(ordered) - 1, int(0.95 * len(ordered)))
    median_ms = statistics.median(ordered)
    return {
        "median_ms": median_ms,
        "p95_ms": ordered[p95_index],
        "mean_ms": statistics.fmean(ordered),
        "fps": 1000.0 / median_ms if median_ms > 0.0 else 0.0,
        "samples": len(ordered),
    }


def _run_new(
    harness: dict,
    armature,
    properties,
    colliders,
    warmup: int,
    frames: int,
    frame_base: int,
) -> dict:
    cache = harness["_OmniCache"]()
    samples = []
    solver_samples = []
    stage_samples = {name: [] for name in ("begin", "register", "solver", "writeback", "commit")}
    total = warmup + frames
    for offset in range(total):
        frame = frame_base + offset
        started = time.perf_counter()
        stage_started = started
        world, _frame, _collider_count, restart = harness["_world_for_frame"](
            cache,
            armature,
            frame,
            reset=(offset == 0),
            extra_objects=colliders,
            include_passive_collision=bool(colliders),
        )
        if _collider_count != len(colliders):
            raise AssertionError(
                f"new architecture expected {len(colliders)} colliders, got {_collider_count}"
            )
        begin_ms = (time.perf_counter() - stage_started) * 1000.0
        stage_started = time.perf_counter()
        world, object_count, _dirty_count, _version = harness["physicsSpringVRMChainRegister"](
            world,
            properties,
        )
        if object_count != 1:
            raise AssertionError(f"new architecture registered {object_count} chains")
        register_ms = (time.perf_counter() - stage_started) * 1000.0
        stage_started = time.perf_counter()
        world, write_count, solver_ms = harness["physicsSpringVRMSolver"](world, substeps=1)
        if write_count != len(armature.pose.bones) - 1:
            raise AssertionError(f"new architecture produced {write_count} writes")
        solver_wall_ms = (time.perf_counter() - stage_started) * 1000.0
        stage_started = time.perf_counter()
        harness["apply_all_writebacks"](world, restart=restart)
        writeback_ms = (time.perf_counter() - stage_started) * 1000.0
        stage_started = time.perf_counter()
        cache, _world, _solver_count = harness["physicsWorldCommit"](world, enabled=True)
        commit_ms = (time.perf_counter() - stage_started) * 1000.0
        elapsed = (time.perf_counter() - started) * 1000.0
        if offset >= warmup:
            samples.append(elapsed)
            solver_samples.append(float(solver_ms))
            for name, value in (
                ("begin", begin_ms),
                ("register", register_ms),
                ("solver", solver_wall_ms),
                ("writeback", writeback_ms),
                ("commit", commit_ms),
            ):
                stage_samples[name].append(value)
    result = _summary(samples)
    result["solver_median_ms"] = statistics.median(solver_samples)
    result["stage_median_ms"] = {
        name: statistics.median(values)
        for name, values in stage_samples.items()
    }
    return result


def _run_old(legacy, cache_type, armature, properties, warmup: int, frames: int, frame_base: int) -> dict:
    cache = cache_type()
    samples = []
    total = warmup + frames
    scene = bpy.context.scene
    for offset in range(total):
        frame = frame_base + offset
        started = time.perf_counter()
        scene.frame_set(frame)
        cache, _bones, _armatures, chain_count, _collider_count = legacy._run_spring_bone_vrm_node(
            backend_tag="cpp",
            cache_state=cache,
            vrm_chain_settings=properties,
            scene=scene,
            enabled=True,
            reset=(offset == 0),
            substeps=1,
            debug_output=False,
        )
        if chain_count != 1:
            raise AssertionError(f"old architecture registered {chain_count} chains")
        elapsed = (time.perf_counter() - started) * 1000.0
        if offset >= warmup:
            samples.append(elapsed)
    return _summary(samples)


def _parse_sizes() -> list[int]:
    raw = os.environ.get("SPRING_BENCH_SIZES", "8,32,128")
    return [max(1, int(item.strip())) for item in raw.split(",") if item.strip()]


def _profiled(label: str, fn, *args):
    profiler = cProfile.Profile()
    profiler.enable()
    try:
        return fn(*args)
    finally:
        profiler.disable()
        output = io.StringIO()
        pstats.Stats(profiler, stream=output).strip_dirs().sort_stats("cumulative").print_stats(35)
        print(f"SPRING_VRM_PROFILE_{label}\n{output.getvalue()}")


def main() -> None:
    harness = _load_harness()
    legacy = _load_legacy_module()
    warmup = max(1, int(os.environ.get("SPRING_BENCH_WARMUP", "20")))
    frames = max(10, int(os.environ.get("SPRING_BENCH_FRAMES", "120")))
    profile = os.environ.get("SPRING_BENCH_PROFILE", "0") == "1"
    collider_count = max(0, int(os.environ.get("SPRING_BENCH_COLLIDERS", "0")))
    results = []

    for case_index, bone_count in enumerate(_parse_sizes()):
        case = {"simulated_bones": bone_count}
        colliders = [
            harness["_make_sphere_collider"](
                f"SpringBenchCollider{bone_count}_{index}",
                (10.0 + index * 0.25, 0.0, 0.0),
                0.1,
                group=1,
            )
            for index in range(collider_count)
        ]
        old_armature = _make_chain_armature(f"SpringBenchOld{bone_count}", bone_count)
        old_properties = harness["physicsSpringVRMChainProperties"](
            [{"armature": old_armature, "bone": "root"}],
            stiffness_force=1.0,
            drag_force=0.4,
            gravity_dir=(1.0, 0.0, 0.0),
            gravity_power=9.8,
        )
        old_args = (
            legacy, harness["_OmniCache"], old_armature, old_properties,
            warmup, frames, 1000 + case_index * 1000,
        )
        case["old"] = _profiled("OLD", _run_old, *old_args) if profile else _run_old(*old_args)
        harness["_delete_object"](old_armature)

        new_armature = _make_chain_armature(f"SpringBenchNew{bone_count}", bone_count)
        new_properties = harness["physicsSpringVRMChainProperties"](
            [{"armature": new_armature, "bone": "root"}],
            stiffness_force=1.0,
            drag_force=0.4,
            gravity_dir=(1.0, 0.0, 0.0),
            gravity_power=9.8,
        )
        new_args = (
            harness, new_armature, new_properties, colliders,
            warmup, frames, 5000 + case_index * 1000,
        )
        case["new"] = _profiled("NEW", _run_new, *new_args) if profile else _run_new(*new_args)
        harness["_delete_object"](new_armature)
        for collider in colliders:
            harness["_delete_object"](collider)

        old_ms = case["old"]["median_ms"]
        new_ms = case["new"]["median_ms"]
        case["new_vs_old_ratio"] = new_ms / old_ms if old_ms > 0.0 else 0.0
        case["new_vs_old_percent"] = (new_ms / old_ms - 1.0) * 100.0 if old_ms > 0.0 else 0.0
        results.append(case)

    report = {
        "schema": "spring_vrm_architecture_benchmark_v1",
        "blender": bpy.app.version_string,
        "warmup_frames": warmup,
        "measured_frames": frames,
        "debug_capture": "disabled",
        "colliders": collider_count,
        "substeps": 1,
        "cases": results,
    }
    print("SPRING_VRM_BENCHMARK_JSON=" + json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
