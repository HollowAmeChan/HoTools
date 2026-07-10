"""Reproducible context-only SpringBone benchmark for Blender background mode.

Usage:
    blender.exe --background --factory-startup --python spring_vrm/test/benchmark_blender_spring_vrm.py

Environment:
    SPRING_BENCH_SIZES=8,32,128
    SPRING_BENCH_WARMUP=20
    SPRING_BENCH_FRAMES=120
    SPRING_BENCH_COLLIDERS=0
"""

from __future__ import annotations

import cProfile
import io
import json
import os
import runpy
import statistics
import time
import pstats
from pathlib import Path

import bpy


HERE = Path(__file__).resolve().parent
HOTOOLS = HERE.parents[5]
HARNESS_PATH = HERE / "test_blender_spring_vrm.py"


def _load_harness() -> dict:
    return runpy.run_path(str(HARNESS_PATH), run_name="spring_vrm_benchmark_harness")


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
                f"context path expected {len(colliders)} colliders, got {_collider_count}"
            )
        begin_ms = (time.perf_counter() - stage_started) * 1000.0
        stage_started = time.perf_counter()
        world, object_count, _dirty_count, _version = harness["physicsSpringVRMChainRegister"](
            world,
            properties,
        )
        if object_count != 1:
            raise AssertionError(f"context path registered {object_count} chains")
        register_ms = (time.perf_counter() - stage_started) * 1000.0
        stage_started = time.perf_counter()
        world, write_count, solver_ms = harness["physicsSpringVRMSolver"](world, substeps=1)
        if write_count != len(armature.pose.bones) - 1:
            raise AssertionError(f"context path produced {write_count} writes")
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
        armature = _make_chain_armature(f"SpringBenchContext{bone_count}", bone_count)
        properties = harness["physicsSpringVRMChainProperties"](
            [{"armature": armature, "bone": "root"}],
            stiffness_force=1.0,
            drag_force=0.4,
            gravity_dir=(1.0, 0.0, 0.0),
            gravity_power=9.8,
        )
        args = (
            harness, armature, properties, colliders,
            warmup, frames, 5000 + case_index * 1000,
        )
        case["context"] = _profiled("CONTEXT", _run_new, *args) if profile else _run_new(*args)
        harness["_delete_object"](armature)
        for collider in colliders:
            harness["_delete_object"](collider)

        results.append(case)

    report = {
        "schema": "spring_vrm_context_benchmark_v2",
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
