"""Debug timing collection and formatted MC2 reports."""

from __future__ import annotations

import time

import bpy

from ....OmniDebug import OmniDebug


_DEBUG_PROFILES = {}

_MC2_TIMING_SUM_STAGES = {
    "cache",
    "base_proxy",
    "base_pose_sync",
    "rebuild",
    "solve_total",
    "solve_setup",
    "solve_setup.params",
    "solve_setup.motion_samples",
    "solve_setup.native_context",
    "write",
}


def begin_timing() -> dict:
    return {"start": time.perf_counter(), "stages": {}}


def add_timing(timing: dict | None, stage: str, seconds: float) -> None:
    if timing is None:
        return
    stages = timing.setdefault("stages", {})
    stages[stage] = stages.get(stage, 0.0) + max(float(seconds), 0.0)


def _timing_stage_is_sum(stage: str) -> bool:
    return str(stage) in _MC2_TIMING_SUM_STAGES


def _timing_role_label(stage: str) -> str:
    if _timing_stage_is_sum(stage):
        return OmniDebug.str_color("[sum]", 93)
    return OmniDebug.str_color("[step]", 95)


def _timing_stage_label(stage: str) -> str:
    if _timing_stage_is_sum(stage):
        return OmniDebug.str_color(stage, 93)
    return OmniDebug.func_label(stage)


def _timing_value_label(stage: str, text: str) -> str:
    if _timing_stage_is_sum(stage):
        return OmniDebug.str_color(text, 93)
    return OmniDebug.value_label(text)


def _format_debug_timing_report(
    backend: str,
    obj_name: str,
    output_key: str,
    frame: int,
    vertex_count: int,
    constraint_count: int,
    elapsed: float,
    sample_count: int,
    totals: dict,
) -> list[str]:
    elapsed_ms = max(float(elapsed), 0.000001) * 1000.0
    hz = sample_count / max(float(elapsed), 0.000001)
    total_ms = totals.get("total", 0.0) / sample_count * 1000.0
    divider = OmniDebug.str_color("-" * 72, 90)
    title = (
        f"{OmniDebug.str_color('OMNI DEBUG TIMING', 97)}"
        f"  |  {OmniDebug.section_label('MC2')} "
        f"{OmniDebug.func_label(str(backend).upper())}"
    )

    lines = [
        "",
        divider,
        title,
        divider,
        f"  {OmniDebug.section_label('Summary')}: "
        f"interval={OmniDebug.value_label(f'{elapsed_ms:.1f}ms')}  "
        f"samples={OmniDebug.value_label(sample_count)}  "
        f"hz={OmniDebug.value_label(f'{hz:.2f}')}  "
        f"total={OmniDebug.func_label(f'{total_ms:.3f}ms')}",
        f"  {OmniDebug.section_label('Context')}: "
        f"obj={OmniDebug.node_label(obj_name)}  "
        f"key={OmniDebug.value_label(output_key)}  "
        f"frame={OmniDebug.value_label(frame)}  "
        f"verts={OmniDebug.value_label(vertex_count)}  "
        f"constraints={OmniDebug.value_label(constraint_count)}",
    ]

    step_stages = [stage for stage in totals if stage != "total"]
    step_stages.sort(key=lambda stage: totals[stage], reverse=True)

    if step_stages:
        lines.append(f"  {OmniDebug.section_label('Slow Steps')}:")
        for index, stage in enumerate(step_stages, start=1):
            avg_ms = totals[stage] / sample_count * 1000.0
            lines.append(
                f"    {OmniDebug.value_label(f'{index:02d}.')} "
                f"{_timing_role_label(stage)} "
                f"{_timing_stage_label(stage)} = {_timing_value_label(stage, f'{avg_ms:.3f}ms')}"
            )

    return lines


def publish_debug_timing(
    obj: bpy.types.Object,
    output_key: str,
    frame: int,
    vertex_count: int,
    constraint_count: int,
    timing: dict | None,
    backend_label: str = "py",
) -> None:
    if timing is None:
        return

    add_timing(timing, "total", time.perf_counter() - float(timing.get("start", time.perf_counter())))
    backend = str(backend_label or "py")
    key = (int(obj.as_pointer()), str(output_key), f"mc2_{backend}")
    now = time.perf_counter()
    profile = _DEBUG_PROFILES.get(key)
    first_publish = profile is None
    if profile is None:
        profile = {
            "last_print": 0.0,
            "frames": 0,
            "frame": frame,
            "vertex_count": vertex_count,
            "constraint_count": constraint_count,
            "stages": {},
        }
        _DEBUG_PROFILES[key] = profile

    profile["frames"] += 1
    profile["frame"] = frame
    profile["vertex_count"] = vertex_count
    profile["constraint_count"] = constraint_count
    totals = profile["stages"]
    for stage, seconds in timing.get("stages", {}).items():
        totals[stage] = totals.get(stage, 0.0) + float(seconds)

    if not first_publish and now - float(profile["last_print"]) < 1.0:
        return

    sample_count = max(int(profile["frames"]), 1)
    elapsed = (
        max(float(totals.get("total", 0.0)) / sample_count, 0.000001)
        if first_publish
        else max(now - float(profile["last_print"]), 0.000001)
    )
    print(
        "\n".join(
            _format_debug_timing_report(
                backend,
                obj.name_full,
                output_key,
                int(profile["frame"]),
                int(profile["vertex_count"]),
                int(profile["constraint_count"]),
                elapsed,
                sample_count,
                totals,
            )
        )
    )

    _DEBUG_PROFILES[key] = {
        "last_print": now,
        "frames": 0,
        "stages": {},
    }
