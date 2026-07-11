"""在后台 Blender 中采样 Rigid/Jolt native、pipeline 与 writeback 性能。"""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import time
import traceback
from typing import Any, Sequence

HERE = Path(__file__).resolve().parent
RIGID_ROOT = HERE.parent
REPO_ROOT = HERE.parents[5]
HARNESS_PATH = RIGID_ROOT / "backends" / "test_blender_rigid.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("hotools_jolt_benchmark_harness", HARNESS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 Blender 测试基础设施: {HARNESS_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _argv_after_separator() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _int_list(value: str) -> list[int]:
    values = sorted({int(part.strip()) for part in value.split(",") if part.strip()})
    if not values or any(item < 1 for item in values):
        raise argparse.ArgumentTypeError("数量列表必须包含正整数")
    return values


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warmup", type=int, default=10, help="每个 case 的预热帧数，默认 10。")
    parser.add_argument("--samples", type=int, default=60, help="每个 case 的采样帧数，默认 60。")
    parser.add_argument("--body-counts", type=_int_list, default=_int_list("1,128,1024"))
    parser.add_argument("--constraint-counts", type=_int_list, default=_int_list("32,256"))
    parser.add_argument("--contact-counts", type=_int_list, default=_int_list("32,256"))
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(r"C:\tmp\hotools_jolt_benchmark"),
        help="报告产物父目录。",
    )
    parser.add_argument(
        "--threshold-file",
        type=Path,
        default=HERE / "performance_thresholds.json",
        help="冻结性能阈值 JSON；默认使用测试目录中的版本化阈值。",
    )
    parser.add_argument(
        "--no-threshold-check",
        action="store_true",
        help="只采样不执行冻结阈值，供自定义数量或探索性测量使用。",
    )
    return parser


def _run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{stamp}-pid{os.getpid()}"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"性能阈值必须是 JSON object: {path}")
    return value


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _metric(values: Sequence[float]) -> dict[str, float]:
    return {
        "p50": statistics.median(values) if values else 0.0,
        "p95": _percentile(values, 0.95),
        "max": max(values, default=0.0),
        "mean": statistics.fmean(values) if values else 0.0,
    }


def _memory_snapshot() -> dict[str, int]:
    if os.name != "nt":
        return {"working_set": 0, "peak_working_set": 0}

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ProcessMemoryCounters),
        ctypes.c_ulong,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    process = kernel32.GetCurrentProcess()
    ok = psapi.GetProcessMemoryInfo(
        process, ctypes.byref(counters), counters.cb)
    if not ok:
        return {"working_set": 0, "peak_working_set": 0}
    return {
        "working_set": int(counters.WorkingSetSize),
        "peak_working_set": int(counters.PeakWorkingSetSize),
    }


def _world_setting(harness, world, *, max_bodies: int, gravity=(0.0, 0.0, 0.0)) -> None:
    properties = harness.make_rigid_jolt_world_setting_properties(
        gravity=gravity,
        max_bodies=max_bodies,
        max_body_pairs=max(64, max_bodies * 8),
        max_contact_constraints=max(64, max_bodies * 4),
        enabled=True,
        source_id="benchmark",
        priority=100,
    )
    harness.register_rigid_jolt_world_setting_objects(world, properties, enabled=True)


def _measure_case(
    harness,
    *,
    case_id: str,
    title: str,
    objects: Sequence[object],
    scope,
    warmup: int,
    samples: int,
    max_bodies: int,
    gravity=(0.0, 0.0, 0.0),
    expected_bodies: int,
    expected_constraints: int,
    expected_min_contacts: int = 0,
) -> dict[str, Any]:
    scene = harness.bpy.context.scene
    cache_state = None
    timings = {
        "native_step_ms": [],
        "pipeline_without_writeback_ms": [],
        "writeback_ms": [],
        "total_ms": [],
    }
    contact_event_counts: list[int] = []
    working_set_samples: list[int] = []
    errors: list[str] = []
    memory_before = _memory_snapshot()
    world = None
    try:
        for index in range(warmup + samples):
            frame = index + 1
            frame_started = time.perf_counter()
            scene.frame_set(frame)
            world, _, _, restart = harness.physicsWorldBegin(
                cache_state=cache_state,
                scene=scene,
                object_scope=scope,
                enabled=True,
            )
            if index == 0:
                _world_setting(
                    harness, world, max_bodies=max_bodies, gravity=gravity)
            harness.step_rigid_bodies(world, enabled=True)
            after_solver = time.perf_counter()
            before_writeback = time.perf_counter()
            write_count = harness.apply_all_writebacks(world, restart=restart)
            after_writeback = time.perf_counter()
            stats = harness.get_rigid_solver_stats_result(
                world, frame=scene.frame_current, generation=world.generation)
            before_commit = time.perf_counter()
            cache_state, _, _ = harness.physicsWorldCommit(world, enabled=True)
            finished = time.perf_counter()
            if stats is None:
                raise RuntimeError(f"{case_id} 第 {frame} 帧缺少 solver stats")
            if stats["body_count"] != expected_bodies:
                raise RuntimeError(
                    f"{case_id} 第 {frame} 帧刚体数 {stats['body_count']} != {expected_bodies}"
                )
            if stats["constraint_count"] != expected_constraints:
                raise RuntimeError(
                    f"{case_id} 第 {frame} 帧约束数 {stats['constraint_count']} != {expected_constraints}"
                )
            if stats["sync_error_count"] or stats["result_error_count"]:
                raise RuntimeError(f"{case_id} 第 {frame} 帧出现 solver error: {stats!r}")
            if write_count < 0:
                raise RuntimeError(f"{case_id} 第 {frame} 帧 writeback 返回负数")
            if index >= warmup:
                contact_count = int(stats.get("contact_event_count", 0) or 0)
                if contact_count < expected_min_contacts:
                    raise RuntimeError(
                        f"{case_id} 第 {frame} 帧接触事件数 {contact_count} "
                        f"< {expected_min_contacts}"
                    )
                timings["native_step_ms"].append(float(stats["step_ms"]))
                timings["pipeline_without_writeback_ms"].append(
                    ((after_solver - frame_started) + (finished - before_commit)) * 1000.0
                )
                timings["writeback_ms"].append(
                    (after_writeback - before_writeback) * 1000.0
                )
                timings["total_ms"].append((finished - frame_started) * 1000.0)
                contact_event_counts.append(contact_count)
                working_set_samples.append(_memory_snapshot()["working_set"])
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        if world is not None:
            world.omni_cache_dispose(f"benchmark:{case_id}")
        harness._del(*objects)
    memory_after = _memory_snapshot()
    working_set_high_water = max(
        working_set_samples,
        default=memory_after["working_set"],
    )
    return {
        "id": case_id,
        "title": title,
        "passed": not errors and len(timings["total_ms"]) == samples,
        "warmup": warmup,
        "samples": len(timings["total_ms"]),
        "expected_body_count": expected_bodies,
        "expected_constraint_count": expected_constraints,
        "expected_min_contact_count": expected_min_contacts,
        "metrics_ms": {name: _metric(values) for name, values in timings.items()},
        "contact_event_count": {
            **_metric(contact_event_counts),
            "min": min(contact_event_counts, default=0),
        },
        "memory": {
            "working_set_before": memory_before["working_set"],
            "working_set_after": memory_after["working_set"],
            "working_set_high_water": working_set_high_water,
            "working_set_high_water_delta": max(
                0, working_set_high_water - memory_before["working_set"]
            ),
            "process_peak_working_set": memory_after["peak_working_set"],
        },
        "errors": errors,
    }


def _body_case(harness, count: int, args) -> dict[str, Any]:
    side = max(1, math.ceil(math.sqrt(count)))
    objects = [
        harness._make_obj(
            f"PERF_Body_{count}_{index}",
            ((index % side) * 2.0, (index // side) * 2.0, 2.0),
        )
        for index in range(count)
    ]
    for obj in objects:
        obj.hotools_rigid_body.allow_sleeping = False
    scope = harness.make_scope(
        objects,
        include_rigid_body=True,
        include_rigid_constraint=False,
        include_passive_collision=False,
        include_bone_collision=False,
        include_mesh_collision=False,
    )
    return _measure_case(
        harness,
        case_id=f"PERF-BODY-{count}",
        title=f"{count} 个无接触动态刚体",
        objects=objects,
        scope=scope,
        warmup=args.warmup,
        samples=args.samples,
        max_bodies=count + 16,
        expected_bodies=count,
        expected_constraints=0,
    )


def _constraint_case(harness, count: int, args) -> dict[str, Any]:
    bodies = [
        harness._make_obj(
            f"PERF_ConstraintBody_{count}_{index}",
            (float(index), 0.0, 2.0),
            body_type="STATIC" if index == 0 else "DYNAMIC",
        )
        for index in range(count + 1)
    ]
    for body in bodies[1:]:
        body.hotools_rigid_body.allow_sleeping = False
    constraints = []
    for index in range(count):
        constraint = harness._make_constraint_empty(
            f"PERF_Constraint_{count}_{index}",
            bodies[index],
            bodies[index + 1],
            loc=(index + 0.5, 0.0, 2.0),
        )
        constraint.hotools_rigid_constraint.constraint_type = "DISTANCE"
        constraint.hotools_rigid_constraint.distance_min = 1.0
        constraint.hotools_rigid_constraint.distance_max = 1.0
        constraints.append(constraint)
    objects = bodies + constraints
    scope = harness.make_scope(
        objects,
        include_rigid_body=True,
        include_rigid_constraint=True,
        include_passive_collision=False,
        include_bone_collision=False,
        include_mesh_collision=False,
    )
    return _measure_case(
        harness,
        case_id=f"PERF-CONSTRAINT-{count}",
        title=f"{count} 个 Distance 约束链",
        objects=objects,
        scope=scope,
        warmup=args.warmup,
        samples=args.samples,
        max_bodies=count + 32,
        expected_bodies=count + 1,
        expected_constraints=count,
    )


def _contact_case(harness, count: int, args) -> dict[str, Any]:
    side = max(1, math.ceil(math.sqrt(count)))
    ground = harness._make_ground(f"PERF_ContactGround_{count}")
    bodies = [
        harness._make_obj(
            f"PERF_ContactBody_{count}_{index}",
            ((index % side) * 0.9, (index // side) * 0.9, 0.4),
        )
        for index in range(count)
    ]
    for body in bodies:
        body.hotools_rigid_body.allow_sleeping = False
    objects = [ground] + bodies
    scope = harness.make_scope(
        objects,
        include_rigid_body=True,
        include_rigid_constraint=False,
        include_passive_collision=False,
        include_bone_collision=False,
        include_mesh_collision=False,
    )
    return _measure_case(
        harness,
        case_id=f"PERF-CONTACT-{count}",
        title=f"{count} 个动态刚体接触地面",
        objects=objects,
        scope=scope,
        warmup=args.warmup,
        samples=args.samples,
        max_bodies=count + 32,
        gravity=(0.0, 0.0, -9.81),
        expected_bodies=count + 1,
        expected_constraints=0,
        expected_min_contacts=count,
    )


def _evaluate_thresholds(
    cases: Sequence[dict[str, Any]],
    thresholds: dict[str, Any],
    *,
    warmup: int,
    samples: int,
    blender_version: Sequence[int],
) -> dict[str, Any]:
    if thresholds.get("schema") != "hotools_jolt_blender_performance_thresholds_v1":
        raise ValueError("不支持的 Jolt 性能阈值 schema")

    requirements = thresholds.get("requirements")
    case_thresholds = thresholds.get("cases")
    if not isinstance(requirements, dict) or not isinstance(case_thresholds, dict):
        raise ValueError("性能阈值缺少 requirements/cases")

    errors: list[str] = []
    required_blender = tuple(int(item) for item in requirements.get("blender_version", ()))
    actual_blender = tuple(int(item) for item in blender_version[:len(required_blender)])
    if required_blender and actual_blender != required_blender:
        errors.append(
            f"Blender version {actual_blender} != required {required_blender}"
        )
    required_system = str(requirements.get("platform_system") or "")
    if required_system and platform.system() != required_system:
        errors.append(
            f"platform.system {platform.system()!r} != required {required_system!r}"
        )
    required_machine = str(requirements.get("platform_machine") or "")
    if required_machine and platform.machine() != required_machine:
        errors.append(
            f"platform.machine {platform.machine()!r} != required {required_machine!r}"
        )
    min_warmup = int(requirements.get("min_warmup", 0) or 0)
    min_samples = int(requirements.get("min_samples", 1) or 1)
    if warmup < min_warmup:
        errors.append(f"warmup {warmup} < required {min_warmup}")
    if samples < min_samples:
        errors.append(f"samples {samples} < required {min_samples}")

    results = []
    for case in cases:
        if not isinstance(case, dict):
            errors.append(f"benchmark case 不是 object: {case!r}")
            continue
        case_id = str(case.get("id") or "")
        expected = case_thresholds.get(case_id)
        differences: list[str] = []
        observed: dict[str, float] = {}
        if not isinstance(expected, dict):
            differences.append(f"没有冻结阈值: {case_id}")
        else:
            metric_limits = expected.get("metrics_ms")
            if not isinstance(metric_limits, dict):
                differences.append("阈值缺少 metrics_ms")
            else:
                actual_metrics = case.get("metrics_ms") or {}
                for metric_name, percentiles in metric_limits.items():
                    actual_metric = actual_metrics.get(metric_name)
                    if not isinstance(actual_metric, dict) or not isinstance(percentiles, dict):
                        differences.append(f"缺少 metric: {metric_name}")
                        continue
                    for percentile, limit_value in percentiles.items():
                        actual_value = float(actual_metric.get(percentile, math.inf))
                        limit = float(limit_value)
                        key = f"{metric_name}.{percentile}"
                        observed[key] = actual_value
                        if not math.isfinite(actual_value) or actual_value > limit:
                            differences.append(
                                f"{key} {actual_value:.6g} ms > {limit:.6g} ms"
                            )
            memory_limit = int(expected.get("working_set_high_water_max_bytes", 0) or 0)
            memory_value = int((case.get("memory") or {}).get("working_set_high_water", 0) or 0)
            observed["working_set_high_water_bytes"] = float(memory_value)
            if memory_limit > 0 and memory_value > memory_limit:
                differences.append(
                    f"working_set_high_water {memory_value} > {memory_limit} bytes"
                )
        results.append({
            "id": case_id,
            "passed": not differences,
            "observed": observed,
            "differences": differences,
        })

    return {
        "schema": "hotools_jolt_blender_performance_gate_v1",
        "threshold_id": str(thresholds.get("id") or ""),
        "passed": not errors and all(item["passed"] for item in results),
        "errors": errors,
        "cases": results,
    }


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    if args.warmup < 0 or args.samples < 1:
        raise ValueError("--warmup 必须非负且 --samples 必须大于等于 1")
    harness = _load_harness()
    threshold_source = None
    threshold_config = None
    if not args.no_threshold_check:
        threshold_source = args.threshold_file.resolve()
        threshold_config = _read_json(threshold_source)
        preflight = _evaluate_thresholds(
            (),
            threshold_config,
            warmup=args.warmup,
            samples=args.samples,
            blender_version=harness.bpy.app.version,
        )
        if preflight["errors"]:
            raise RuntimeError(
                "性能阈值环境预检失败: " + "; ".join(preflight["errors"])
            )
    cases = []
    for count in args.body_counts:
        cases.append(_body_case(harness, count, args))
    for count in args.constraint_counts:
        cases.append(_constraint_case(harness, count, args))
    for count in args.contact_counts:
        cases.append(_contact_case(harness, count, args))
    threshold_gate = None
    if threshold_config is not None:
        threshold_gate = _evaluate_thresholds(
            cases,
            threshold_config,
            warmup=args.warmup,
            samples=args.samples,
            blender_version=harness.bpy.app.version,
        )
    cases_passed = all(case["passed"] for case in cases)
    thresholds_passed = threshold_gate is None or bool(threshold_gate["passed"])
    report = {
        "schema": "hotools_jolt_blender_benchmark_v1",
        "passed": cases_passed and thresholds_passed,
        "thresholds_frozen": threshold_gate is not None,
        "threshold_source": str(threshold_source) if threshold_source is not None else "",
        "threshold_gate": threshold_gate,
        "warmup": args.warmup,
        "samples": args.samples,
        "python": sys.version,
        "platform": platform.platform(),
        "blender_version": tuple(harness.bpy.app.version),
        "measurement_policy": {
            "clock": "time.perf_counter",
            "percentile": "nearest-rank",
            "memory": "Windows process working set",
        },
        "cases": cases,
    }
    run_root = args.artifact_dir.resolve() / _run_id()
    report_path = run_root / "benchmark-report.json"
    _write_json(report_path, report)
    for case in cases:
        state = "通过" if case["passed"] else "失败"
        metrics = case["metrics_ms"]
        print(
            f"[{state}] {case['id']} samples={case['samples']}；"
            f"native P50/P95={metrics['native_step_ms']['p50']:.4g}/"
            f"{metrics['native_step_ms']['p95']:.4g} ms；"
            f"pipeline P50/P95={metrics['pipeline_without_writeback_ms']['p50']:.4g}/"
            f"{metrics['pipeline_without_writeback_ms']['p95']:.4g} ms；"
            f"writeback P50/P95={metrics['writeback_ms']['p50']:.4g}/"
            f"{metrics['writeback_ms']['p95']:.4g} ms；"
            f"接触事件 min/P95={case['contact_event_count']['min']:.0f}/"
            f"{case['contact_event_count']['p95']:.4g}；"
            f"工作集高水位={case['memory']['working_set_high_water'] / 1048576.0:.2f} MiB"
        )
        for error in case["errors"]:
            print(f"  {error}")
    if threshold_gate is not None:
        for error in threshold_gate["errors"]:
            print(f"[阈值环境失败] {error}")
        for item in threshold_gate["cases"]:
            state = "通过" if item["passed"] else "失败"
            print(f"[阈值{state}] {item['id']}")
            for difference in item["differences"]:
                print(f"  {difference}")
    threshold_state = (
        "未检查" if threshold_gate is None
        else ("通过" if threshold_gate["passed"] else "失败")
    )
    print(
        f"汇总：{'通过' if report['passed'] else '失败'}；"
        f"冻结阈值={threshold_state}；报告：{report_path}"
    )
    return (0 if report["passed"] else 1), report


def main() -> int:
    args = _parser().parse_args(_argv_after_separator())
    try:
        code, _report = run(args)
        return code
    except Exception as exc:
        print(f"致命错误：{type(exc).__name__}：{exc}", file=sys.stderr)
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
