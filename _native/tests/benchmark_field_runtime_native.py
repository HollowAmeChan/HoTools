"""Field native Domain 热路径基准。

这个脚本不是单元测试：它用真实 MC2 Domain 的 native prepare/apply 入口测量
Field evaluator 和风响应。热循环只传 runtime handle 与 sample time，不向 Python
返回或重新上传粒子位置；结果以 JSON Lines 输出，方便保存到性能记录。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import time

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = f"py{sys.version_info.major}{sys.version_info.minor}"
NATIVE_DIR = Path(os.environ.get(
    "HOTOOLS_NATIVE_TEST_DIR",
    str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage"),
))
sys.path.insert(0, str(NATIVE_DIR))
import hotools_native  # noqa: E402


def _create_runtime(*, shape: str, turbulence: float, octaves: int, scope_solver: str):
    if shape == "box":
        world_to_local = np.asarray((
            (
                (0.1, 0.0, 0.0, 0.0),
                (0.0, 0.1, 0.0, 0.0),
                (0.0, 0.0, 0.1, 0.0),
                (0.0, 0.0, 0.0, 1.0),
            ),
        ), dtype=np.float64)
        shape_code = 1
    else:
        world_to_local = np.asarray((np.eye(4, dtype=np.float64),))
        shape_code = 0
    return int(hotools_native.field_runtime_v1_create(
        1,
        "field-benchmark-snapshot-v1",
        "field-benchmark-config-v1",
        f"field-benchmark-values-{shape}-{turbulence}-{octaves}",
        1,
        2,
        0.0,
        ("benchmark-wind",),
        np.asarray((0,), dtype=np.int32),
        np.asarray((shape_code,), dtype=np.int32),
        world_to_local,
        np.asarray(((1.0, 0.0, 0.0),), dtype=np.float64),
        np.asarray(((6.0, turbulence, 1.0, 0.5, 2.0, 0.5, 1.0),), dtype=np.float64),
        np.asarray((octaves,), dtype=np.uint32),
        np.asarray((0x12345678,), dtype=np.uint32),
        ((scope_solver,),),
        ((),),
        ((),),
        ((),),
        np.asarray((0,), dtype=np.uint32),
    ))


def _create_domain(particle_count: int, partition_count: int):
    if particle_count % partition_count:
        raise ValueError("particle_count 必须能被 partition_count 整除")
    rng = np.random.default_rng(0xC0DE + particle_count + partition_count)
    positions = rng.uniform(-0.8, 0.8, (particle_count, 3)).astype(np.float32)
    rotations = np.zeros((particle_count, 4), dtype=np.float32)
    rotations[:, 3] = 1.0
    partitions = np.repeat(
        np.arange(partition_count, dtype=np.uint32),
        particle_count // partition_count,
    )
    bind_positions = np.ascontiguousarray(positions)
    bind_rotations = np.ascontiguousarray(rotations)
    partition_positions = np.zeros((partition_count, 3), dtype=np.float32)
    partition_rotations = np.zeros((partition_count, 4), dtype=np.float32)
    partition_rotations[:, 3] = 1.0
    domain = int(hotools_native.mc2_domain_cpu_v1_create(
        1,
        particle_count,
        partition_count,
        f"field-benchmark-domain-{particle_count}-{partition_count}",
        "field-benchmark-layout-v1",
        bind_positions,
        bind_rotations,
        partitions,
        np.zeros(particle_count, dtype=np.uint32),
        partition_positions,
        np.tile(np.asarray((0.0, -1.0, 0.0), dtype=np.float32), (partition_count, 1)),
    ))
    normals = np.zeros((particle_count, 3), dtype=np.float32)
    normals[:, 2] = 1.0
    hotools_native.mc2_domain_cpu_v1_update_frame(
        domain,
        f"field-benchmark-domain-{particle_count}-{partition_count}",
        "field-benchmark-layout-v1",
        1,
        1,
        positions,
        rotations,
        normals,
        partition_positions,
        partition_rotations,
        np.ones((partition_count, 3), dtype=np.float32),
        np.tile(np.eye(3, dtype=np.float32), (partition_count, 1, 1)),
        np.zeros((partition_count, 3), dtype=np.float32),
        partition_rotations,
        np.zeros(partition_count, dtype=np.uint32),
        np.zeros(partition_count, dtype=np.uint32),
        np.ones(partition_count, dtype=np.float32),
        np.ones(partition_count, dtype=np.float32),
        1.0 / 60.0,
        1.0 / 90.0,
        1.0,
        0,
        True,
    )
    hotools_native.mc2_domain_cpu_v1_configure_inertia(
        domain,
        np.zeros(particle_count, dtype=np.float32),
        np.ones(particle_count, dtype=np.float32),
    )
    hotools_native.mc2_domain_cpu_v1_configure_field_consumers(
        domain,
        tuple(f"benchmark-partition-{index}" for index in range(partition_count)),
        tuple(() for _ in range(partition_count)),
        np.zeros(partition_count, dtype=np.uint32),
    )
    return domain


def _positions(particle_count: int, *, sparse: bool, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    if sparse:
        return np.ascontiguousarray(
            rng.uniform(-4.0, 4.0, (particle_count, 3)), dtype=np.float32
        )
    directions = rng.normal(size=(particle_count, 3))
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    radius = rng.random(particle_count) ** (1.0 / 3.0) * 0.8
    return np.ascontiguousarray(directions * radius[:, None], dtype=np.float32)


def run_case(
    particle_count: int,
    partition_count: int,
    scenario: str,
    warmup: int,
    iterations: int,
) -> dict:
    sparse = "sparse" in scenario
    turbulent = "turbulent" in scenario
    disabled = scenario == "disabled"
    scope_miss = scenario == "scope-miss"
    shape = "box" if scenario == "uniform" else "sphere"
    turbulence = 0.8 if turbulent else 0.0
    octaves = 4 if turbulent else 1
    runtime = _create_runtime(
        shape=shape,
        turbulence=turbulence,
        octaves=octaves,
        scope_solver="unmatched" if scope_miss else "mc2",
    )
    domain = _create_domain(particle_count, partition_count)
    positions = _positions(
        particle_count,
        sparse=sparse,
        seed=particle_count * 17 + partition_count,
    )
    # 当前辅助创建器先提交一组合法 frame；这里再提交一次目标位置，
    # 不把 frame update 计入热循环。
    rotations = np.zeros((particle_count, 4), dtype=np.float32)
    rotations[:, 3] = 1.0
    normals = np.zeros((particle_count, 3), dtype=np.float32)
    normals[:, 2] = 1.0
    partitions = np.repeat(
        np.arange(partition_count, dtype=np.uint32),
        particle_count // partition_count,
    )
    partition_positions = np.zeros((partition_count, 3), dtype=np.float32)
    partition_rotations = np.zeros((partition_count, 4), dtype=np.float32)
    partition_rotations[:, 3] = 1.0
    hotools_native.mc2_domain_cpu_v1_update_frame(
        domain,
        f"field-benchmark-domain-{particle_count}-{partition_count}",
        "field-benchmark-layout-v1",
        2,
        1,
        positions,
        rotations,
        normals,
        partition_positions,
        partition_rotations,
        np.ones((partition_count, 3), dtype=np.float32),
        np.tile(np.eye(3, dtype=np.float32), (partition_count, 1, 1)),
        np.zeros((partition_count, 3), dtype=np.float32),
        partition_rotations,
        np.zeros(partition_count, dtype=np.uint32),
        np.zeros(partition_count, dtype=np.uint32),
        np.ones(partition_count, dtype=np.float32),
        np.ones(partition_count, dtype=np.float32),
        1.0 / 60.0,
        1.0 / 90.0,
        1.0,
        0,
        True,
    )
    strengths = np.zeros(particle_count, dtype=np.float32) if disabled else np.ones(
        particle_count,
        dtype=np.float32,
    )
    hotools_native.mc2_domain_cpu_v1_configure_field_wind_response(domain, strengths)
    # 作用域上下文已在第一帧配置；重复配置只为保证第二帧仍是同一静态合同。
    hotools_native.mc2_domain_cpu_v1_configure_field_consumers(
        domain,
        tuple(f"benchmark-partition-{index}" for index in range(partition_count)),
        tuple(() for _ in range(partition_count)),
        np.zeros(partition_count, dtype=np.uint32),
    )
    try:
        def sample_once(index: int) -> None:
            active = hotools_native.mc2_domain_cpu_v1_prepare_field_wind(
                domain,
                runtime,
                index / 60.0,
            )
            if disabled or scope_miss:
                if active:
                    raise AssertionError("no-op benchmark unexpectedly activated Field response")
            else:
                if not active:
                    raise AssertionError("active benchmark unexpectedly skipped Field response")
                hotools_native.mc2_domain_cpu_v1_step_prepared_field_wind(domain, 1.0 / 90.0)

        for index in range(warmup):
            sample_once(index)
        durations = []
        started_sample = warmup
        for index in range(iterations):
            started = time.perf_counter()
            sample_once(started_sample + index)
            durations.append((time.perf_counter() - started) * 1000.0)
        state = dict(hotools_native.mc2_domain_cpu_v1_inspect(domain))
        values = sorted(durations)
        return {
            "schema": "field_native_benchmark_v1",
            "particles": particle_count,
            "partitions": partition_count,
            "scenario": scenario,
            "warmup": warmup,
            "iterations": iterations,
            "median_ms": statistics.median(values),
            "p95_ms": values[min(len(values) - 1, int(len(values) * 0.95))],
            "samples_per_second": 1000.0 / statistics.median(values),
            "field_sample_count": int(state["field_sample_count"]),
            "field_apply_count": int(state["field_apply_count"]),
            "field_sampled_field_count": int(state["field_sampled_field_count"]),
            "field_sample_buffer_valid": bool(state["field_sample_buffer_valid"]),
        }
    finally:
        hotools_native.mc2_domain_cpu_v1_dispose(domain)
        hotools_native.field_runtime_v1_dispose(runtime)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--particles", nargs="+", type=int, default=(1024, 16384, 65536))
    parser.add_argument("--partitions", nargs="+", type=int, default=(1, 8, 32))
    parser.add_argument(
        "--scenario",
        nargs="+",
        choices=("disabled", "scope-miss", "uniform", "sphere", "sphere-sparse", "sphere-turbulent", "sphere-sparse-turbulent"),
        default=("disabled", "scope-miss", "uniform", "sphere", "sphere-sparse", "sphere-turbulent", "sphere-sparse-turbulent"),
    )
    parser.add_argument("--warmup", type=int, default=30)
    parser.add_argument("--iterations", type=int, default=200)
    args = parser.parse_args()
    if args.warmup < 0 or args.iterations < 1:
        raise ValueError("warmup 必须非负，iterations 必须为正")
    for particle_count in args.particles:
        for partition_count in args.partitions:
            for scenario in args.scenario:
                if particle_count % partition_count:
                    continue
                print(json.dumps(run_case(
                    particle_count,
                    partition_count,
                    scenario,
                    args.warmup,
                    args.iterations,
                ), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
