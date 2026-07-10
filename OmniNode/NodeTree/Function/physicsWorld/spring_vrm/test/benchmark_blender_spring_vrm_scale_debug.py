"""SpringBone multi-armature scaling and debug-capture benchmark.

Usage:
    blender.exe --background --factory-startup --python spring_vrm/test/benchmark_blender_spring_vrm_scale_debug.py

Environment:
    SPRING_SCALE_ARMATURES=1,8,32
    SPRING_SCALE_BONES=8
    SPRING_DEBUG_BONES=128
    SPRING_MATRIX_WARMUP=40
    SPRING_MATRIX_FRAMES=300
"""

from __future__ import annotations

import json
import os
import runpy
import statistics
import time
from pathlib import Path

import bpy


HERE = Path(__file__).resolve().parent
HARNESS_PATH = HERE / "test_blender_spring_vrm.py"
BASE_BENCHMARK_PATH = HERE / "benchmark_blender_spring_vrm.py"


def _load_modules() -> tuple[dict, dict]:
    harness = runpy.run_path(str(HARNESS_PATH), run_name="spring_vrm_matrix_harness")
    base = runpy.run_path(str(BASE_BENCHMARK_PATH), run_name="spring_vrm_matrix_base")
    return harness, base


def _parse_ints(name: str, default: str) -> list[int]:
    raw = os.environ.get(name, default)
    return [max(1, int(item.strip())) for item in raw.split(",") if item.strip()]


def _summary(samples: list[float]) -> dict:
    ordered = sorted(float(value) for value in samples)
    if not ordered:
        return {"median_ms": 0.0, "p95_ms": 0.0, "mean_ms": 0.0, "samples": 0}
    p95_index = min(len(ordered) - 1, int(0.95 * len(ordered)))
    return {
        "median_ms": statistics.median(ordered),
        "p95_ms": ordered[p95_index],
        "mean_ms": statistics.fmean(ordered),
        "samples": len(ordered),
    }


def _spring_resources(world) -> dict:
    slots = [
        slot for slot in getattr(world, "solver_slots", {}).values()
        if getattr(slot, "kind", "") == "spring_vrm"
    ]
    contexts = []
    for slot in slots:
        native_contexts = slot.data.get("_native_ctxs")
        if isinstance(native_contexts, dict):
            contexts.extend(native_contexts.values())
    return {
        "slot_count": len(slots),
        "context_count": len(contexts),
        "cpp_handle_count": sum(1 for context in contexts if getattr(context, "_handle", None) is not None),
        "buffer_count": sum(
            int(value is not None)
            for context in contexts
            for value in (context._static, context._dynamic, context._result)
        ),
    }


def _run_scale_case(
    harness: dict,
    make_armature,
    armature_count: int,
    bones_per_armature: int,
    warmup: int,
    frames: int,
    frame_base: int,
) -> dict:
    armatures = [
        make_armature(f"SpringScale{armature_count}_{index}", bones_per_armature)
        for index in range(armature_count)
    ]
    properties = []
    for armature in armatures:
        properties.extend(harness["physicsSpringVRMChainProperties"](
            [{"armature": armature, "bone": "root"}],
            stiffness_force=1.0,
            drag_force=0.4,
            gravity_dir=(1.0, 0.0, 0.0),
            gravity_power=9.8,
        ))

    cache = harness["_OmniCache"]()
    total_samples = []
    solver_samples = []
    writeback_samples = []
    total = warmup + frames
    world = None
    try:
        for offset in range(total):
            frame = frame_base + offset
            started = time.perf_counter()
            world, _frame, _collider_count, restart = harness["_world_for_frame"](
                cache,
                armatures[0],
                frame,
                reset=(offset == 0),
                extra_objects=armatures[1:],
            )
            world, object_count, _dirty_count, _version = harness["physicsSpringVRMChainRegister"](
                world,
                properties,
            )
            if object_count != armature_count:
                raise AssertionError(f"expected {armature_count} chain objects, got {object_count}")

            solver_started = time.perf_counter()
            world, write_count, _solver_ms = harness["physicsSpringVRMSolver"](world, substeps=1)
            solver_wall_ms = (time.perf_counter() - solver_started) * 1000.0
            expected_writes = armature_count * bones_per_armature
            if write_count != expected_writes:
                raise AssertionError(f"expected {expected_writes} writes, got {write_count}")

            writeback_started = time.perf_counter()
            applied = harness["apply_all_writebacks"](world, restart=restart)
            writeback_ms = (time.perf_counter() - writeback_started) * 1000.0
            if applied != expected_writes:
                raise AssertionError(f"expected {expected_writes} applied writes, got {applied}")
            cache, _world, solver_count = harness["physicsWorldCommit"](world, enabled=True)
            if solver_count != armature_count:
                raise AssertionError(f"expected {armature_count} slots, got {solver_count}")

            if offset >= warmup:
                total_samples.append((time.perf_counter() - started) * 1000.0)
                solver_samples.append(solver_wall_ms)
                writeback_samples.append(writeback_ms)

        resources = _spring_resources(world)
        expected_buffers = armature_count * 3
        if resources != {
            "slot_count": armature_count,
            "context_count": armature_count,
            "cpp_handle_count": armature_count,
            "buffer_count": expected_buffers,
        }:
            raise AssertionError(f"unexpected scale resources: {resources}")
        return {
            "armatures": armature_count,
            "bones_per_armature": bones_per_armature,
            "total_bones": armature_count * bones_per_armature,
            "total": _summary(total_samples),
            "solver": _summary(solver_samples),
            "writeback": _summary(writeback_samples),
            "resources": resources,
        }
    finally:
        for armature in reversed(armatures):
            harness["_delete_object"](armature)


def _request_debug(debug_node, world) -> None:
    debug_node(
        world,
        show_solved_chain=True,
        show_roots=True,
        show_colliders=True,
        color_by_group=True,
    )


def _run_debug_case(
    harness: dict,
    make_armature,
    mode: str,
    bone_count: int,
    warmup: int,
    frames: int,
    frame_base: int,
) -> dict:
    armature = make_armature(f"SpringDebug{mode}", bone_count)
    properties = harness["physicsSpringVRMChainProperties"](
        [{"armature": armature, "bone": "root"}],
        stiffness_force=1.0,
        drag_force=0.4,
        gravity_dir=(1.0, 0.0, 0.0),
        gravity_power=9.8,
    )
    debug_node = harness["_pw"]("spring_vrm.nodes").physicsSpringVRMDebugDraw
    cache = harness["_OmniCache"]()
    total_samples = []
    solver_samples = []
    debug_node_samples = []
    capture_frame_samples = []
    capture_cost_samples = []
    total = warmup + frames
    world = None
    try:
        for offset in range(total):
            frame = frame_base + offset
            started = time.perf_counter()
            world, _frame, _collider_count, restart = harness["_world_for_frame"](
                cache,
                armature,
                frame,
                reset=(offset == 0),
            )
            world, _object_count, _dirty_count, _version = harness["physicsSpringVRMChainRegister"](
                world,
                properties,
            )

            solver_started = time.perf_counter()
            world, write_count, _solver_ms = harness["physicsSpringVRMSolver"](world, substeps=1)
            solver_wall_ms = (time.perf_counter() - solver_started) * 1000.0
            if write_count != bone_count:
                raise AssertionError(f"debug {mode}: expected {bone_count} writes, got {write_count}")

            slot = next(
                slot for slot in world.solver_slots.values()
                if getattr(slot, "kind", "") == "spring_vrm"
            )
            state = slot.data.get("_debug_capture_state")
            captured_this_frame = (
                isinstance(state, dict)
                and int(state.get("attempted_frame", -1)) == frame
            )
            if captured_this_frame and offset >= warmup:
                capture_frame_samples.append((time.perf_counter() - started) * 1000.0)
                capture_cost_samples.append(float(state.get("capture_ms", 0.0) or 0.0))

            debug_started = time.perf_counter()
            if mode == "continuous" or (mode == "one_shot" and offset == warmup - 1):
                _request_debug(debug_node, world)
            debug_node_ms = (time.perf_counter() - debug_started) * 1000.0

            harness["apply_all_writebacks"](world, restart=restart)
            cache, _world, solver_count = harness["physicsWorldCommit"](world, enabled=True)
            if solver_count != 1:
                raise AssertionError(f"debug {mode}: expected one slot, got {solver_count}")

            if offset >= warmup:
                total_samples.append((time.perf_counter() - started) * 1000.0)
                solver_samples.append(solver_wall_ms)
                debug_node_samples.append(debug_node_ms)

        expected_captures = 0 if mode == "off" else (1 if mode == "one_shot" else frames)
        if len(capture_cost_samples) != expected_captures:
            raise AssertionError(
                f"debug {mode}: expected {expected_captures} captures, got {len(capture_cost_samples)}"
            )
        resources = _spring_resources(world)
        if resources != {
            "slot_count": 1,
            "context_count": 1,
            "cpp_handle_count": 1,
            "buffer_count": 3,
        }:
            raise AssertionError(f"debug {mode}: unexpected resources {resources}")
        return {
            "mode": mode,
            "simulated_bones": bone_count,
            "total": _summary(total_samples),
            "solver": _summary(solver_samples),
            "debug_node": _summary(debug_node_samples),
            "capture_frame": _summary(capture_frame_samples),
            "capture_cost": _summary(capture_cost_samples),
            "capture_count": len(capture_cost_samples),
            "resources": resources,
        }
    finally:
        harness["_delete_object"](armature)


def main() -> None:
    harness, base = _load_modules()
    make_armature = base["_make_chain_armature"]
    warmup = max(2, int(os.environ.get("SPRING_MATRIX_WARMUP", "40")))
    frames = max(10, int(os.environ.get("SPRING_MATRIX_FRAMES", "300")))
    bones_per_armature = max(1, int(os.environ.get("SPRING_SCALE_BONES", "8")))
    debug_bones = max(1, int(os.environ.get("SPRING_DEBUG_BONES", "128")))

    scale_cases = []
    for index, armature_count in enumerate(_parse_ints("SPRING_SCALE_ARMATURES", "1,8,32")):
        scale_cases.append(_run_scale_case(
            harness,
            make_armature,
            armature_count,
            bones_per_armature,
            warmup,
            frames,
            1000 + index * 1000,
        ))
    baseline_ms = scale_cases[0]["total"]["median_ms"]
    baseline_per_armature = baseline_ms / scale_cases[0]["armatures"]
    for case in scale_cases:
        case["ratio_to_1"] = case["total"]["median_ms"] / baseline_ms if baseline_ms > 0.0 else 0.0
        case["median_ms_per_armature"] = case["total"]["median_ms"] / case["armatures"]
        case["per_armature_ratio_to_1"] = (
            case["median_ms_per_armature"] / baseline_per_armature
            if baseline_per_armature > 0.0 else 0.0
        )

    debug_cases = [
        _run_debug_case(
            harness,
            make_armature,
            mode,
            debug_bones,
            warmup,
            frames,
            5000 + index * 1000,
        )
        for index, mode in enumerate(("off", "one_shot", "continuous"))
    ]
    debug_baseline_ms = debug_cases[0]["total"]["median_ms"]
    for case in debug_cases:
        case["total_ratio_to_off"] = (
            case["total"]["median_ms"] / debug_baseline_ms
            if debug_baseline_ms > 0.0 else 0.0
        )

    report = {
        "schema": "spring_vrm_scale_debug_benchmark_v1",
        "blender": bpy.app.version_string,
        "warmup_frames": warmup,
        "measured_frames": frames,
        "scale_cases": scale_cases,
        "debug_cases": debug_cases,
    }
    print("SPRING_VRM_SCALE_DEBUG_JSON=" + json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
