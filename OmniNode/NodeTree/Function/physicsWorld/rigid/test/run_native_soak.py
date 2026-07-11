"""运行 Rigid/Jolt 原生 10,000 帧稳定性门禁并输出机器可读报告。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
import traceback
from typing import Any, Callable, Sequence

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[5]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from fixture_runtime import default_native_dir, load_native_module


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=10000, help="每个场景的模拟帧数，默认 10000。")
    parser.add_argument("--sample-every", type=int, default=1000, help="报告样本间隔，默认 1000 帧。")
    parser.add_argument("--native-dir", type=Path, default=None, help="当前 Python ABI 的 hotools_jolt 目录。")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(r"C:\tmp\hotools_jolt_soak"),
        help="报告产物父目录。",
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


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _add_box(
    world,
    *,
    body_type: str,
    position: tuple[float, float, float],
    half_extents: tuple[float, float, float],
    allow_sleeping: bool = True,
) -> int:
    return int(world.add_body(
        body_type=body_type,
        mass=1.0,
        friction=0.8,
        restitution=0.0,
        position=position,
        rotation_wxyz=(1.0, 0.0, 0.0, 0.0),
        shape_type="BOX",
        shape_half_extents=half_extents,
        allow_sleeping=allow_sleeping,
    ))


def _add_sphere(
    world,
    *,
    body_type: str,
    position: tuple[float, float, float],
) -> int:
    return int(world.add_body(
        body_type=body_type,
        mass=1.0,
        friction=0.5,
        restitution=0.0,
        position=position,
        rotation_wxyz=(1.0, 0.0, 0.0, 0.0),
        shape_type="SPHERE",
        shape_radius=0.25,
        allow_sleeping=False,
    ))


def _body_metrics(world, handles: Sequence[int]) -> tuple[float, float, float, list[tuple[float, float, float]]]:
    max_position_abs = 0.0
    max_linear_speed = 0.0
    min_z = math.inf
    positions = []
    for handle in handles:
        state = world.get_body_state(handle)
        position = tuple(float(value) for value in state[0])
        rotation = tuple(float(value) for value in state[1])
        linear_velocity = tuple(float(value) for value in state[2])
        angular_velocity = tuple(float(value) for value in state[3])
        values = position + rotation + linear_velocity + angular_velocity
        if not all(math.isfinite(value) for value in values):
            raise RuntimeError(f"刚体 {handle} 出现非有限数值: {values!r}")
        positions.append(position)
        max_position_abs = max(max_position_abs, *(abs(value) for value in position))
        max_linear_speed = max(max_linear_speed, math.sqrt(sum(value * value for value in linear_velocity)))
        min_z = min(min_z, position[2])
    return max_position_abs, max_linear_speed, min_z, positions


def _run_scenario(
    *,
    name: str,
    title: str,
    world,
    dynamic_handles: Sequence[int],
    expected_body_count: int,
    expected_constraint_count: int,
    frames: int,
    sample_every: int,
    residual: Callable[[], float],
    residual_limit: float,
    minimum_z_limit: float,
) -> dict[str, Any]:
    samples = []
    step_times = []
    errors: list[str] = []
    max_position_abs = 0.0
    max_linear_speed = 0.0
    max_constraint_residual = 0.0
    started = time.perf_counter()
    try:
        for frame in range(1, frames + 1):
            step_times.append(float(world.step(1.0 / 60.0, 1)))
            if int(world.body_count) != expected_body_count:
                raise RuntimeError(
                    f"第 {frame} 帧刚体数变化: {world.body_count} != {expected_body_count}"
                )
            if int(world.constraint_count) != expected_constraint_count:
                raise RuntimeError(
                    f"第 {frame} 帧约束数变化: {world.constraint_count} != {expected_constraint_count}"
                )
            position_abs, linear_speed, min_z, positions = _body_metrics(world, dynamic_handles)
            current_residual = float(residual())
            if not math.isfinite(current_residual):
                raise RuntimeError(f"第 {frame} 帧约束残差不是有限数: {current_residual}")
            max_position_abs = max(max_position_abs, position_abs)
            max_linear_speed = max(max_linear_speed, linear_speed)
            max_constraint_residual = max(max_constraint_residual, current_residual)
            if min_z < minimum_z_limit:
                raise RuntimeError(f"第 {frame} 帧最低 Z={min_z:.9g}，低于 {minimum_z_limit:g}")
            if position_abs > 100.0:
                raise RuntimeError(f"第 {frame} 帧位置绝对值 {position_abs:.9g} 失控")
            if current_residual > residual_limit:
                raise RuntimeError(
                    f"第 {frame} 帧约束残差 {current_residual:.9g} 超过 {residual_limit:g}"
                )
            if frame == 1 or frame == frames or frame % sample_every == 0:
                samples.append({
                    "frame": frame,
                    "body_count": int(world.body_count),
                    "constraint_count": int(world.constraint_count),
                    "max_position_abs": position_abs,
                    "max_linear_speed": linear_speed,
                    "minimum_z": min_z,
                    "constraint_residual": current_residual,
                    "positions": positions,
                })
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    wall_seconds = time.perf_counter() - started
    passed = not errors and len(step_times) == frames
    result = {
        "id": name,
        "title": title,
        "passed": passed,
        "frames_requested": frames,
        "frames_completed": len(step_times),
        "body_count": expected_body_count,
        "constraint_count": expected_constraint_count,
        "max_position_abs": max_position_abs,
        "max_linear_speed": max_linear_speed,
        "max_constraint_residual": max_constraint_residual,
        "constraint_residual_limit": residual_limit,
        "wall_seconds": wall_seconds,
        "step_ms_p50": statistics.median(step_times) if step_times else 0.0,
        "step_ms_p95": _percentile(step_times, 0.95),
        "step_ms_max": max(step_times, default=0.0),
        "samples": samples,
        "errors": errors,
    }
    world.clear()
    return result


def _stack_scenario(native, frames: int, sample_every: int) -> dict[str, Any]:
    world = native.JoltWorld(max_bodies=32, max_body_pairs=256, max_contact_constraints=128)
    _add_box(
        world,
        body_type="STATIC",
        position=(0.0, 0.0, -0.5),
        half_extents=(4.0, 4.0, 0.5),
    )
    dynamic = [
        _add_box(
            world,
            body_type="DYNAMIC",
            position=(0.01 * (index % 2), 0.0, 0.5 + index * 1.01),
            half_extents=(0.5, 0.5, 0.5),
        )
        for index in range(12)
    ]
    return _run_scenario(
        name="SOAK-STACK-001",
        title="十二层箱体堆叠 10,000 帧稳定性",
        world=world,
        dynamic_handles=dynamic,
        expected_body_count=13,
        expected_constraint_count=0,
        frames=frames,
        sample_every=sample_every,
        residual=lambda: 0.0,
        residual_limit=0.0,
        minimum_z_limit=-0.2,
    )


def _chain_scenario(native, frames: int, sample_every: int) -> dict[str, Any]:
    world = native.JoltWorld(max_bodies=32, max_body_pairs=256, max_contact_constraints=128)
    world.set_gravity((0.0, 0.0, -9.81))
    body_handles = [_add_sphere(world, body_type="STATIC", position=(0.0, 0.0, 0.0))]
    body_handles.extend(
        _add_sphere(world, body_type="DYNAMIC", position=(0.0, 0.0, -float(index)))
        for index in range(1, 9)
    )
    constraints = []
    for index in range(8):
        point_a = (0.0, 0.0, -float(index))
        point_b = (0.0, 0.0, -float(index + 1))
        constraints.append(int(world.add_constraint(
            constraint_type="DISTANCE",
            body_a_handle=body_handles[index],
            body_b_handle=body_handles[index + 1],
            anchor_pos=point_a,
            anchor_rot_wxyz=(1.0, 0.0, 0.0, 0.0),
            distance_min=1.0,
            distance_max=1.0,
            use_separate_anchor_frames=True,
            anchor_pos_a=point_a,
            anchor_rot_wxyz_a=(1.0, 0.0, 0.0, 0.0),
            anchor_pos_b=point_b,
            anchor_rot_wxyz_b=(1.0, 0.0, 0.0, 0.0),
        )))
    world.add_body_impulse(body_handles[-1], (2.0, 0.0, 0.0), (0.0, 0.0, 0.0))

    def residual() -> float:
        values = []
        for handle in constraints:
            state = world.get_constraint_state(handle)
            values.append(abs(float(state[3]) - 1.0))
        return max(values, default=0.0)

    return _run_scenario(
        name="SOAK-CHAIN-001",
        title="八节 Distance 约束链 10,000 帧稳定性",
        world=world,
        dynamic_handles=body_handles[1:],
        expected_body_count=9,
        expected_constraint_count=8,
        frames=frames,
        sample_every=sample_every,
        residual=residual,
        residual_limit=0.02,
        minimum_z_limit=-20.0,
    )


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    if args.frames < 1:
        raise ValueError("--frames 必须大于等于 1")
    if args.sample_every < 1:
        raise ValueError("--sample-every 必须大于等于 1")
    native_dir = (args.native_dir or default_native_dir(REPO_ROOT)).resolve()
    native = load_native_module(native_dir)
    run_root = args.artifact_dir.resolve() / _run_id()
    scenarios = [
        _stack_scenario(native, args.frames, args.sample_every),
        _chain_scenario(native, args.frames, args.sample_every),
    ]
    report = {
        "schema": "hotools_jolt_soak_report_v1",
        "passed": all(item["passed"] for item in scenarios),
        "frames_per_scenario": args.frames,
        "sample_every": args.sample_every,
        "python": sys.version,
        "python_executable": sys.executable,
        "native_module": str(Path(native.__file__).resolve()),
        "scenarios": scenarios,
    }
    report_path = run_root / "soak-report.json"
    _write_json(report_path, report)
    for item in scenarios:
        state = "通过" if item["passed"] else "失败"
        print(
            f"[{state}] {item['id']} {item['frames_completed']}/{item['frames_requested']} 帧；"
            f"最大残差={item['max_constraint_residual']:.9g}；"
            f"step P95={item['step_ms_p95']:.6g} ms"
        )
        for error in item["errors"]:
            print(f"  {error}")
    print(f"汇总：{'通过' if report['passed'] else '失败'}；报告：{report_path}")
    return (0 if report["passed"] else 1), report


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        code, _report = run(args)
        return code
    except Exception as exc:
        print(f"致命错误：{type(exc).__name__}：{exc}", file=sys.stderr)
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
