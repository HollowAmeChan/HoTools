"""Opt-in MC2 hotspot timing and console aggregation."""

from __future__ import annotations

import math
import time


MC2_HOTSPOT_TIMING_RESOURCE_KEY = "mc2.hotspot_timing.profile"


def _range_text(minimum, maximum, *, digits=0, suffix="") -> str:
    if minimum is None or maximum is None:
        return "-"
    if digits:
        low = f"{float(minimum):.{digits}f}"
        high = f"{float(maximum):.{digits}f}"
    else:
        low = str(int(minimum))
        high = str(int(maximum))
    return f"{low}{suffix}" if low == high else f"{low}..{high}{suffix}"


class MC2HotspotTimingProfile:
    """Aggregate explicitly requested MC2 timing samples per Physics World."""

    PRINT_INTERVAL = 1.0
    MAX_STAGES = 12

    def __init__(self, *, clock=time.perf_counter, printer=print):
        self._clock = clock
        self._printer = printer
        self._disposed = False
        self._reset_window(self._clock())

    def _reset_window(self, now: float) -> None:
        self._window_started = float(now)
        self._samples = 0
        self._total_seconds = 0.0
        self._stage_totals = {}
        self._stage_maxima = {}
        self._detail_totals = {}
        self._detail_maxima = {}
        self._host_detail_totals = {}
        self._host_detail_maxima = {}
        self._candidate_detail_totals = {}
        self._candidate_detail_maxima = {}
        self._candidate_metric_totals = {}
        self._metrics = {}
        self._setup_totals = {}
        self._action_totals = {
            "created": 0,
            "rebuilt": 0,
            "updated": 0,
            "reused": 0,
            "pruned": 0,
        }
        self._state_totals = {
            "scheduled_tasks": 0,
            "reset_tasks": 0,
            "teleport_tasks": 0,
            "debug_tasks": 0,
            "native_group_frames": 0,
            "ready_frames": 0,
            "writeback_results": 0,
        }
        self._last_frame = 0
        self._last_generation = 0
        self._last_sample_at = None

    def _add_metric(self, name: str, value: float) -> None:
        value = float(value)
        metric = self._metrics.get(name)
        if metric is None:
            self._metrics[name] = {"sum": value, "min": value, "max": value}
            return
        metric["sum"] += value
        metric["min"] = min(metric["min"], value)
        metric["max"] = max(metric["max"], value)

    def add_sample(
        self,
        stage_seconds: dict[str, float],
        detail_seconds: dict[str, float],
        host_detail_seconds: dict[str, float],
        candidate_detail_seconds: dict[str, float],
        candidate_metrics: dict[str, int],
        total_seconds: float,
        context: dict,
        *,
        now: float,
    ) -> None:
        if self._disposed:
            return
        if (
            self._samples > 0
            and self._last_sample_at is not None
            and float(now) - self._last_sample_at
            > max(float(self.PRINT_INTERVAL) * 4.0, 1.0)
        ):
            self._reset_window(float(now))
        self._samples += 1
        self._last_sample_at = float(now)
        self._total_seconds += max(float(total_seconds), 0.0)
        for stage, seconds in stage_seconds.items():
            seconds = max(float(seconds), 0.0)
            self._stage_totals[stage] = self._stage_totals.get(stage, 0.0) + seconds
            self._stage_maxima[stage] = max(
                self._stage_maxima.get(stage, 0.0), seconds
            )
        for stage, seconds in detail_seconds.items():
            seconds = max(float(seconds), 0.0)
            self._detail_totals[stage] = self._detail_totals.get(stage, 0.0) + seconds
            self._detail_maxima[stage] = max(
                self._detail_maxima.get(stage, 0.0), seconds
            )
        for stage, seconds in host_detail_seconds.items():
            seconds = max(float(seconds), 0.0)
            self._host_detail_totals[stage] = (
                self._host_detail_totals.get(stage, 0.0) + seconds
            )
            self._host_detail_maxima[stage] = max(
                self._host_detail_maxima.get(stage, 0.0), seconds
            )
        for stage, seconds in candidate_detail_seconds.items():
            seconds = max(float(seconds), 0.0)
            self._candidate_detail_totals[stage] = (
                self._candidate_detail_totals.get(stage, 0.0) + seconds
            )
            self._candidate_detail_maxima[stage] = max(
                self._candidate_detail_maxima.get(stage, 0.0), seconds
            )
        for name, value in candidate_metrics.items():
            value = int(value)
            if value < 0:
                raise ValueError("MC2 candidate timing metrics must be non-negative")
            self._candidate_metric_totals[name] = (
                self._candidate_metric_totals.get(name, 0) + value
            )

        for name in (
            "tasks", "particles", "substeps", "max_substeps", "batches",
            "colliders", "interaction_tasks", "interaction_pairs", "dt",
        ):
            self._add_metric(name, context.get(name, 0))
        for setup_type, count in dict(context.get("setup_counts") or {}).items():
            self._setup_totals[str(setup_type)] = (
                self._setup_totals.get(str(setup_type), 0) + int(count)
            )
        for name in self._action_totals:
            self._action_totals[name] += int(context.get(name, 0))
        for name in self._state_totals:
            self._state_totals[name] += int(context.get(name, 0))
        self._last_frame = int(context.get("frame", 0))
        self._last_generation = int(context.get("generation", 0))

        if float(now) - self._window_started < self.PRINT_INTERVAL:
            return
        self._printer("\n".join(self.format_report(float(now))))
        self._reset_window(float(now))

    def _metric(self, name: str) -> dict:
        return self._metrics.get(name, {"sum": 0.0, "min": None, "max": None})

    def format_report(self, now: float) -> list[str]:
        samples = max(int(self._samples), 1)
        elapsed = max(float(now) - self._window_started, 0.0)
        average_total_ms = self._total_seconds / samples * 1000.0
        tasks = self._metric("tasks")
        particles = self._metric("particles")
        substeps = self._metric("substeps")
        max_substeps = self._metric("max_substeps")
        batches = self._metric("batches")
        colliders = self._metric("colliders")
        interaction_tasks = self._metric("interaction_tasks")
        interaction_pairs = self._metric("interaction_pairs")
        dt = self._metric("dt")
        dt_min_ms = None if dt["min"] is None else dt["min"] * 1000.0
        dt_max_ms = None if dt["max"] is None else dt["max"] * 1000.0
        setup_text = " ".join(
            f"{name}={count / samples:.1f}"
            for name, count in sorted(self._setup_totals.items())
        ) or "none"

        lines = [
            "",
            "-" * 72,
            "MC2 HOTSPOT TIMING  |  MC2模拟步",
            "-" * 72,
            (
                f"  Summary: interval={elapsed * 1000.0:.1f}ms  "
                f"samples={samples}  hz={samples / max(elapsed, 1e-6):.2f}  "
                f"total={average_total_ms:.3f}ms"
            ),
            (
                "  Scope: "
                f"frame={self._last_frame}  generation={self._last_generation}  "
                f"tasks={_range_text(tasks['min'], tasks['max'])}  "
                f"particles={_range_text(particles['min'], particles['max'])}  "
                f"dt={_range_text(dt_min_ms, dt_max_ms, digits=3, suffix='ms')}"
            ),
            (
                "    setups(avg): " + setup_text + "  "
                f"scheduled_tasks(avg)={self._state_totals['scheduled_tasks'] / samples:.1f}  "
                f"substeps={_range_text(substeps['min'], substeps['max'])}  "
                f"parallel_rounds={_range_text(max_substeps['min'], max_substeps['max'])}  "
                f"native_batches={_range_text(batches['min'], batches['max'])}"
            ),
            (
                "    collision scope: "
                f"colliders={_range_text(colliders['min'], colliders['max'])}  "
                f"cross_task_participants={_range_text(interaction_tasks['min'], interaction_tasks['max'])}  "
                f"pairs={_range_text(interaction_pairs['min'], interaction_pairs['max'])}"
            ),
            (
                "  State: "
                f"create={self._action_totals['created']}  "
                f"rebuild={self._action_totals['rebuilt']}  "
                f"update={self._action_totals['updated']}  "
                f"reuse={self._action_totals['reused']}  "
                f"prune={self._action_totals['pruned']}"
            ),
            (
                "    "
                f"reset={self._state_totals['reset_tasks']}  "
                f"teleport={self._state_totals['teleport_tasks']}  "
                f"native_group_frames={self._state_totals['native_group_frames']}  "
                f"debug_tasks={self._state_totals['debug_tasks']}  "
                f"ready={self._state_totals['ready_frames']}/{samples}  "
                f"writeback={self._state_totals['writeback_results']}"
            ),
        ]

        ordered = sorted(
            self._stage_totals,
            key=lambda stage: self._stage_totals[stage],
            reverse=True,
        )
        shown = ordered[: max(int(self.MAX_STAGES), 1)]
        if shown:
            lines.append("  Slow Stages:")
            for index, stage in enumerate(shown, start=1):
                average_ms = self._stage_totals[stage] / samples * 1000.0
                maximum_ms = self._stage_maxima[stage] * 1000.0
                percentage = average_ms / max(average_total_ms, 1e-6) * 100.0
                lines.append(
                    f"    {index:02d}. {stage} = {average_ms:.3f}ms  "
                    f"({percentage:.0f}%, max={maximum_ms:.3f}ms)"
                )
        hidden = ordered[len(shown):]
        if hidden:
            hidden_ms = (
                sum(self._stage_totals[name] for name in hidden)
                / samples
                * 1000.0
            )
            lines.append(f"    .. other_stages = {hidden_ms:.3f}ms")

        host_detail_order = sorted(
            self._host_detail_totals,
            key=lambda stage: self._host_detail_totals[stage],
            reverse=True,
        )
        host_detail_total = sum(self._host_detail_totals.values()) / samples * 1000.0
        if host_detail_order:
            lines.append("  Host Frame明细（包含于统一域Frame）:")
            for index, stage in enumerate(host_detail_order, start=1):
                average_ms = self._host_detail_totals[stage] / samples * 1000.0
                maximum_ms = self._host_detail_maxima[stage] * 1000.0
                percentage = average_ms / max(host_detail_total, 1e-6) * 100.0
                lines.append(
                    f"    {index:02d}. {stage} = {average_ms:.3f}ms  "
                    f"({percentage:.0f}% Frame占比, max={maximum_ms:.3f}ms)"
                )

        solve_total = (
            self._stage_totals.get("统一域求解", 0.0)
            + self._stage_totals.get("模拟求解", 0.0)
        ) / samples * 1000.0
        detail_order = sorted(
            self._detail_totals,
            key=lambda stage: self._detail_totals[stage],
            reverse=True,
        )
        if detail_order:
            lines.append("  求解明细（包含于统一域求解）:")
            for index, stage in enumerate(detail_order, start=1):
                average_ms = self._detail_totals[stage] / samples * 1000.0
                maximum_ms = self._detail_maxima[stage] * 1000.0
                percentage = average_ms / max(solve_total, 1e-6) * 100.0
                lines.append(
                    f"    {index:02d}. {stage} = {average_ms:.3f}ms  "
                    f"({percentage:.0f}% 求解占比, max={maximum_ms:.3f}ms)"
                )
        candidate_order = sorted(
            self._candidate_detail_totals,
            key=lambda stage: self._candidate_detail_totals[stage],
            reverse=True,
        )
        candidate_total_ms = (
            sum(self._candidate_detail_totals.values()) / samples * 1000.0
        )
        if candidate_order:
            lines.append("  Candidate生成明细（包含于CPU Self · Candidate生成）:")
            for index, stage in enumerate(candidate_order, start=1):
                average_ms = self._candidate_detail_totals[stage] / samples * 1000.0
                maximum_ms = self._candidate_detail_maxima[stage] * 1000.0
                percentage = average_ms / max(candidate_total_ms, 1e-6) * 100.0
                lines.append(
                    f"    {index:02d}. {stage} = {average_ms:.3f}ms  "
                    f"({percentage:.0f}% Candidate占比, max={maximum_ms:.3f}ms)"
                )
        if self._candidate_metric_totals:
            average = {
                name: value / samples
                for name, value in self._candidate_metric_totals.items()
            }
            raw = average.get("candidate_raw", 0.0)
            unique = average.get("candidate_unique", 0.0)
            duplicates = average.get("candidate_duplicates", 0.0)
            ratio = raw / max(unique, 1.0)
            lines.append(
                "    工作量(avg): "
                f"grid探测={average.get('candidate_grid_probes', 0.0):.1f}  "
                f"run命中={average.get('candidate_grid_run_hits', 0.0):.1f}  "
                f"pair访问={average.get('candidate_pair_visits', 0.0):.1f}  "
                f"raw={raw:.1f}  unique={unique:.1f}  "
                f"duplicates={duplicates:.1f}  raw/unique={ratio:.2f}x"
            )
            lines.append(
                "    过滤(avg): "
                f"source忽略={average.get('candidate_source_ignored', 0.0):.1f}  "
                f"owner={average.get('candidate_rejected_owner', 0.0):.1f}  "
                f"AABB={average.get('candidate_rejected_aabb', 0.0):.1f}  "
                f"target忽略={average.get('candidate_rejected_target_ignored', 0.0):.1f}  "
                f"全固定={average.get('candidate_rejected_all_fixed', 0.0):.1f}  "
                f"拓扑邻接={average.get('candidate_rejected_topology', 0.0):.1f}"
            )
        return lines

    def dispose(self, _reason: str = "") -> None:
        self._disposed = True
        self._reset_window(self._clock())

    def omni_cache_dispose(self, reason: str) -> None:
        self.dispose(reason)


class MC2HotspotTimingSession:
    """Measure once per boundary and fan the result to overlay and console."""

    def __init__(self, profile, *, overlay=None, clock=time.perf_counter):
        self._profile = profile
        self._overlay = overlay
        self._clock = clock
        self._started = None
        self._cursor = None
        self._stages = {}
        self._detail_cursor = None
        self._details = {}
        self._host_detail_cursor = None
        self._host_details = {}
        self._candidate_details = {}
        self._candidate_metrics = {}

    def restart(self) -> None:
        now = self._clock()
        self._started = now
        self._cursor = now
        self._stages = {}
        self._detail_cursor = None
        self._details = {}
        self._host_detail_cursor = None
        self._host_details = {}
        self._candidate_details = {}
        self._candidate_metrics = {}

    def checkpoint(self, stage: str) -> float:
        stage = str(stage or "").strip()
        if not stage:
            raise ValueError("MC2 timing stage must not be empty")
        now = self._clock()
        if self._cursor is None:
            self._started = now
            self._cursor = now
            return 0.0
        seconds = max(now - self._cursor, 0.0)
        self._stages[stage] = self._stages.get(stage, 0.0) + seconds
        if self._overlay is not None:
            self._overlay.record(stage, seconds)
        self._cursor = now
        return seconds

    def detail_restart(self) -> None:
        self._detail_cursor = self._clock()

    def host_detail_restart(self) -> None:
        self._host_detail_cursor = self._clock()

    def host_detail_checkpoint(self, stage: str) -> float:
        stage = str(stage or "").strip()
        if not stage:
            raise ValueError("MC2 host detail timing stage must not be empty")
        now = self._clock()
        if self._host_detail_cursor is None:
            self._host_detail_cursor = now
            return 0.0
        seconds = max(now - self._host_detail_cursor, 0.0)
        self._host_details[stage] = self._host_details.get(stage, 0.0) + seconds
        self._host_detail_cursor = now
        return seconds

    def detail_checkpoint(self, stage: str) -> float:
        stage = str(stage or "").strip()
        if not stage:
            raise ValueError("MC2 detail timing stage must not be empty")
        now = self._clock()
        if self._detail_cursor is None:
            self._detail_cursor = now
            return 0.0
        seconds = max(now - self._detail_cursor, 0.0)
        self._details[stage] = self._details.get(stage, 0.0) + seconds
        self._detail_cursor = now
        return seconds

    def detail_native_checkpoint(self, native_timing: dict) -> float:
        now = self._clock()
        if self._detail_cursor is None:
            self._detail_cursor = now
            return 0.0
        elapsed = max(now - self._detail_cursor, 0.0)
        stages = native_timing.get("stages") if isinstance(native_timing, dict) else None
        if not isinstance(stages, dict):
            raise ValueError("MC2 native detail timing must provide stage values")
        native_total = 0.0
        for raw_stage, raw_seconds in stages.items():
            stage = str(raw_stage or "").strip()
            seconds = float(raw_seconds)
            if not stage or not math.isfinite(seconds) or seconds < 0.0:
                raise ValueError("MC2 native detail timing contains an invalid sample")
            self._details[stage] = self._details.get(stage, 0.0) + seconds
            native_total += seconds
        candidate_breakdown = native_timing.get("candidate_breakdown", {})
        candidate_metrics = native_timing.get("candidate_metrics", {})
        if not isinstance(candidate_breakdown, dict) or not isinstance(
            candidate_metrics, dict
        ):
            raise ValueError("MC2 native candidate timing payload is invalid")
        for raw_stage, raw_seconds in candidate_breakdown.items():
            stage = str(raw_stage or "").strip()
            seconds = float(raw_seconds)
            if not stage or not math.isfinite(seconds) or seconds < 0.0:
                raise ValueError("MC2 native candidate breakdown is invalid")
            self._candidate_details[stage] = (
                self._candidate_details.get(stage, 0.0) + seconds
            )
        for raw_name, raw_value in candidate_metrics.items():
            name = str(raw_name or "").strip()
            value = int(raw_value)
            if not name or value < 0:
                raise ValueError("MC2 native candidate metric is invalid")
            self._candidate_metrics[name] = self._candidate_metrics.get(name, 0) + value
        residual = max(elapsed - native_total, 0.0)
        if residual > 0.0:
            stage = str(
                native_timing.get("residual_stage", "native · 边界与未归类")
            ).strip()
            if not stage:
                raise ValueError("MC2 native detail residual stage must not be empty")
            self._details[stage] = self._details.get(stage, 0.0) + residual
        self._detail_cursor = now
        return elapsed

    def finish(self, context: dict) -> None:
        now = self._clock()
        started = now if self._started is None else self._started
        total_seconds = max(now - started, 0.0)
        other_seconds = max(total_seconds - sum(self._stages.values()), 0.0)
        stages = dict(self._stages)
        if other_seconds > 0.0:
            stages["其他"] = stages.get("其他", 0.0) + other_seconds
            if self._overlay is not None:
                self._overlay.record("其他", other_seconds)
        self._profile.add_sample(
            stages,
            dict(self._details),
            dict(self._host_details),
            dict(self._candidate_details),
            dict(self._candidate_metrics),
            total_seconds,
            dict(context),
            now=now,
        )


def make_mc2_hotspot_timing(world, *, overlay=None) -> MC2HotspotTimingSession:
    profile = world.backend_resources.get(MC2_HOTSPOT_TIMING_RESOURCE_KEY)
    if profile is None or getattr(profile, "_disposed", False):
        profile = MC2HotspotTimingProfile()
        world.backend_resources[MC2_HOTSPOT_TIMING_RESOURCE_KEY] = profile
    if not isinstance(profile, MC2HotspotTimingProfile):
        raise RuntimeError("MC2 hotspot timing resource key is occupied by another owner")
    return MC2HotspotTimingSession(profile, overlay=overlay)
