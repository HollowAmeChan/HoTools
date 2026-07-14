"""Source-aligned MC2 fixed-step time scheduling state."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


MC2_DEFAULT_SIMULATION_FREQUENCY = 90
MC2_DEFAULT_MAX_SIMULATION_COUNT_PER_FRAME = 3
MC2_MIN_SIMULATION_FREQUENCY = 30
MC2_MAX_SIMULATION_FREQUENCY = 150
MC2_MIN_SIMULATION_COUNT_PER_FRAME = 1
MC2_MAX_SIMULATION_COUNT_PER_FRAME = 5


def _f32(value: object) -> np.float32:
    return np.float32(value)


@dataclass(frozen=True)
class MC2FrameSchedule:
    frame_delta_time: float
    now_time_scale: float
    simulation_delta_time: float
    max_simulation_count_per_frame: int
    planned_update_count: int
    update_count: int
    skip_count: int
    time: float
    old_time: float
    now_update_time: float
    old_update_time: float
    frame_update_time: float
    frame_old_time: float

    @property
    def is_running(self) -> bool:
        return self.update_count > 0

    def debug_dict(self) -> dict:
        return dict(self.__dict__)


class MC2TimeSchedulerState:
    """Persistent producer for TeamData update/skip counts and step ratios."""

    __slots__ = (
        "time",
        "old_time",
        "now_update_time",
        "old_update_time",
        "frame_update_time",
        "frame_old_time",
        "frame_revision",
        "step_revision",
        "_active_schedule",
        "_next_step_index",
    )

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.time = 0.0
        self.old_time = 0.0
        self.now_update_time = 0.0
        self.old_update_time = 0.0
        self.frame_update_time = 0.0
        self.frame_old_time = 0.0
        self.frame_revision = 0
        self.step_revision = 0
        self._active_schedule: MC2FrameSchedule | None = None
        self._next_step_index = 0

    def plan_frame(
        self,
        *,
        frame_delta_time: float,
        now_time_scale: float,
        simulation_delta_time: float | None = None,
        max_simulation_count_per_frame: int = (
            MC2_DEFAULT_MAX_SIMULATION_COUNT_PER_FRAME
        ),
    ) -> MC2FrameSchedule:
        if (
            self._active_schedule is not None
            and self._next_step_index < self._active_schedule.update_count
        ):
            raise RuntimeError("previous MC2 frame still has pending simulation steps")
        frame_delta_time = float(frame_delta_time)
        now_time_scale = float(now_time_scale)
        if simulation_delta_time is None:
            simulation_delta_time = 1.0 / MC2_DEFAULT_SIMULATION_FREQUENCY
        simulation_delta_time = float(simulation_delta_time)
        if (
            isinstance(max_simulation_count_per_frame, bool)
            or int(max_simulation_count_per_frame)
            != max_simulation_count_per_frame
        ):
            raise ValueError("max_simulation_count_per_frame must be an integer")
        max_count = int(max_simulation_count_per_frame)
        if not math.isfinite(frame_delta_time) or frame_delta_time < 0.0:
            raise ValueError("frame_delta_time must be finite and non-negative")
        if not math.isfinite(now_time_scale) or now_time_scale < 0.0:
            raise ValueError("now_time_scale must be finite and non-negative")
        if not math.isfinite(simulation_delta_time) or simulation_delta_time <= 0.0:
            raise ValueError("simulation_delta_time must be finite and positive")
        if max_count < 1:
            raise ValueError("max_simulation_count_per_frame must be positive")

        frame_dt = _f32(frame_delta_time)
        time_scale = _f32(now_time_scale)
        simulation_dt = _f32(simulation_delta_time)
        add_time = _f32(frame_dt * time_scale)
        next_time = _f32(_f32(self.time) + add_time)
        interval = _f32(next_time - _f32(self.now_update_time))
        planned_count = int(_f32(interval / simulation_dt))
        update_count = min(planned_count, max_count)
        skip_count = planned_count - update_count
        if skip_count > 0:
            next_time = _f32(next_time - _f32(simulation_dt * _f32(skip_count)))

        next_now_update_time = _f32(self.now_update_time)
        if update_count > 0 and add_time == _f32(0.0):
            update_count = 0
            skip_count = 0
            next_now_update_time = _f32(next_time - simulation_dt + _f32(0.0001))

        next_frame_old_time = _f32(self.frame_old_time)
        next_frame_update_time = _f32(self.frame_update_time)
        next_old_update_time = _f32(self.old_update_time)
        if update_count > 0:
            next_frame_old_time = _f32(self.frame_update_time)
            next_frame_update_time = next_time
            next_old_update_time = next_now_update_time

        previous_time = _f32(self.time)
        self.old_time = float(previous_time)
        self.time = float(next_time)
        self.now_update_time = float(next_now_update_time)
        self.old_update_time = float(next_old_update_time)
        self.frame_update_time = float(next_frame_update_time)
        self.frame_old_time = float(next_frame_old_time)
        self.frame_revision += 1
        self._next_step_index = 0
        schedule = MC2FrameSchedule(
            frame_delta_time=float(frame_dt),
            now_time_scale=float(time_scale),
            simulation_delta_time=float(simulation_dt),
            max_simulation_count_per_frame=max_count,
            planned_update_count=planned_count,
            update_count=update_count,
            skip_count=skip_count,
            time=self.time,
            old_time=self.old_time,
            now_update_time=self.now_update_time,
            old_update_time=self.old_update_time,
            frame_update_time=self.frame_update_time,
            frame_old_time=self.frame_old_time,
        )
        self._active_schedule = schedule
        return schedule

    def advance_step(self, update_index: int) -> float:
        schedule = self._active_schedule
        if schedule is None:
            raise RuntimeError("MC2 frame must be planned before advancing a step")
        if (
            isinstance(update_index, bool)
            or int(update_index) != update_index
            or update_index != self._next_step_index
        ):
            raise ValueError("MC2 step index must advance sequentially")
        if update_index >= schedule.update_count:
            raise IndexError("MC2 step index exceeds the current update count")
        now_update_time = _f32(
            _f32(self.now_update_time) + _f32(schedule.simulation_delta_time)
        )
        frame_old_time = _f32(self.frame_old_time)
        denominator = _f32(_f32(self.time) - frame_old_time)
        ratio = (
            np.clip(
                _f32((now_update_time - frame_old_time) / denominator),
                _f32(0.0),
                _f32(1.0),
            )
            if denominator > _f32(0.0)
            else _f32(1.0)
        )
        self.now_update_time = float(now_update_time)
        self._next_step_index += 1
        self.step_revision += 1
        return float(_f32(ratio))

    def debug_dict(self) -> dict:
        return {
            "time": self.time,
            "old_time": self.old_time,
            "now_update_time": self.now_update_time,
            "old_update_time": self.old_update_time,
            "frame_update_time": self.frame_update_time,
            "frame_old_time": self.frame_old_time,
            "frame_revision": self.frame_revision,
            "step_revision": self.step_revision,
            "next_step_index": self._next_step_index,
            "active_schedule": (
                self._active_schedule.debug_dict()
                if self._active_schedule is not None
                else None
            ),
        }


__all__ = [
    "MC2_DEFAULT_MAX_SIMULATION_COUNT_PER_FRAME",
    "MC2_DEFAULT_SIMULATION_FREQUENCY",
    "MC2_MAX_SIMULATION_COUNT_PER_FRAME",
    "MC2_MAX_SIMULATION_FREQUENCY",
    "MC2_MIN_SIMULATION_COUNT_PER_FRAME",
    "MC2_MIN_SIMULATION_FREQUENCY",
    "MC2FrameSchedule",
    "MC2TimeSchedulerState",
]
