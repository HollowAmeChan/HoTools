"""Transactional scheduler and Anchor history for the fused Mesh product slot."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math

import numpy as np

from .center_state import mc2_anchor_component_local_position
from .domain_ir import MC2DomainFramePacketV1
from .parameters import MC2SolverSettingsSpec
from .scheduler import MC2FrameSchedule
from .scheduler import MC2SubstepPlan
from .scheduler import MC2TimeSchedulerState


def _readonly_anchor_table(values, partition_count: int, name: str) -> np.ndarray:
    array = np.ascontiguousarray(values, dtype=np.float32)
    if array.shape != (partition_count, 3) or not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite with shape ({partition_count}, 3)")
    array = np.array(array, dtype=np.float32, order="C", copy=True)
    array.flags.writeable = False
    return array


def _next_anchor_component_local_positions(
    frame_packet: MC2DomainFramePacketV1,
) -> np.ndarray:
    values = np.zeros((len(frame_packet.anchor_present), 3), dtype=np.float32)
    for index, present in enumerate(frame_packet.anchor_present):
        if int(present):
            values[index] = mc2_anchor_component_local_position(
                frame_packet.partition_world_position[index],
                frame_packet.anchor_world_position[index],
                frame_packet.anchor_world_rotation[index],
            )
    values.flags.writeable = False
    return values


@dataclass(frozen=True)
class MC2MeshProductScheduledFrameV1:
    frame_packet: MC2DomainFramePacketV1
    schedule: MC2FrameSchedule
    anchor_component_local_positions: np.ndarray
    next_anchor_component_local_positions: np.ndarray
    base_revision: int
    _owner_token: object
    _staged_scheduler: MC2TimeSchedulerState

    def __post_init__(self) -> None:
        if not isinstance(self.frame_packet, MC2DomainFramePacketV1):
            raise TypeError("frame_packet must be MC2DomainFramePacketV1")
        if not isinstance(self.schedule, MC2FrameSchedule):
            raise TypeError("schedule must be MC2FrameSchedule")
        if not isinstance(self._staged_scheduler, MC2TimeSchedulerState):
            raise TypeError("staged scheduler must be MC2TimeSchedulerState")
        if self.base_revision < 0:
            raise ValueError("base_revision cannot be negative")
        partition_count = len(self.frame_packet.partition_world_position)
        object.__setattr__(
            self,
            "anchor_component_local_positions",
            _readonly_anchor_table(
                self.anchor_component_local_positions,
                partition_count,
                "anchor_component_local_positions",
            ),
        )
        object.__setattr__(
            self,
            "next_anchor_component_local_positions",
            _readonly_anchor_table(
                self.next_anchor_component_local_positions,
                partition_count,
                "next_anchor_component_local_positions",
            ),
        )


@dataclass(frozen=True)
class MC2MeshProductScheduledSubstepV1:
    plan: MC2SubstepPlan
    base_revision: int
    _owner_token: object
    _staged_scheduler: MC2TimeSchedulerState

    def __post_init__(self) -> None:
        if not isinstance(self.plan, MC2SubstepPlan):
            raise TypeError("plan must be MC2SubstepPlan")
        if self.base_revision < 0:
            raise ValueError("base_revision cannot be negative")
        if not isinstance(self._staged_scheduler, MC2TimeSchedulerState):
            raise TypeError("staged scheduler must be MC2TimeSchedulerState")


class MC2MeshProductSchedulerStateV1:
    """Own committed time and per-partition Anchor local history."""

    __slots__ = (
        "partition_ids",
        "_time_scheduler",
        "_anchor_component_local_positions",
        "_revision",
        "_owner_token",
    )

    def __init__(self, partition_ids) -> None:
        partition_ids = tuple(str(value or "").strip() for value in partition_ids)
        if not partition_ids or any(not value for value in partition_ids):
            raise ValueError("partition_ids cannot be empty")
        if len(set(partition_ids)) != len(partition_ids):
            raise ValueError("partition_ids must be unique")
        self.partition_ids = partition_ids
        self._time_scheduler = MC2TimeSchedulerState()
        anchors = np.zeros((len(partition_ids), 3), dtype=np.float32)
        anchors.flags.writeable = False
        self._anchor_component_local_positions = anchors
        self._revision = 0
        self._owner_token = object()

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def anchor_component_local_positions(self) -> np.ndarray:
        return self._anchor_component_local_positions

    def stage_frame(
        self,
        frame_packet: MC2DomainFramePacketV1,
        settings: MC2SolverSettingsSpec,
        *,
        frame_delta_time: float,
        world_time_scale: float,
    ) -> MC2MeshProductScheduledFrameV1:
        if not isinstance(frame_packet, MC2DomainFramePacketV1):
            raise TypeError("frame_packet must be MC2DomainFramePacketV1")
        if not isinstance(settings, MC2SolverSettingsSpec):
            raise TypeError("settings must be MC2SolverSettingsSpec")
        if len(frame_packet.partition_world_position) != len(self.partition_ids):
            raise ValueError("frame packet partition count does not match scheduler state")
        frame_dt = float(frame_delta_time)
        world_scale = float(world_time_scale)
        if not math.isfinite(frame_dt) or frame_dt <= 0.0:
            raise ValueError("frame_delta_time must be finite and positive")
        if not math.isfinite(world_scale) or world_scale < 0.0:
            raise ValueError("world_time_scale must be finite and non-negative")
        effective_time_scale = world_scale * float(settings.time_scale)
        staged_scheduler = self._time_scheduler.clone()
        schedule = staged_scheduler.plan_frame(
            frame_delta_time=frame_dt,
            now_time_scale=effective_time_scale,
            simulation_delta_time=1.0 / float(settings.simulation_frequency),
            max_simulation_count_per_frame=settings.max_simulation_count_per_frame,
        )
        running = schedule.update_count > 0
        packet = replace(
            frame_packet,
            frame_delta_time=schedule.frame_delta_time,
            simulation_delta_time=(
                schedule.simulation_delta_time if running else 0.0
            ),
            time_scale=schedule.now_time_scale,
            skip_count=schedule.skip_count,
            is_running=running,
        )
        return MC2MeshProductScheduledFrameV1(
            frame_packet=packet,
            schedule=schedule,
            anchor_component_local_positions=self._anchor_component_local_positions,
            next_anchor_component_local_positions=(
                _next_anchor_component_local_positions(packet)
            ),
            base_revision=self._revision,
            _owner_token=self._owner_token,
            _staged_scheduler=staged_scheduler,
        )

    def validate_commit(self, staged: MC2MeshProductScheduledFrameV1) -> None:
        if not isinstance(staged, MC2MeshProductScheduledFrameV1):
            raise TypeError("staged must be MC2MeshProductScheduledFrameV1")
        if staged._owner_token is not self._owner_token:
            raise ValueError("scheduled frame belongs to another scheduler state")
        if staged.base_revision != self._revision:
            raise RuntimeError("scheduled frame is stale")

    def commit(self, staged: MC2MeshProductScheduledFrameV1) -> None:
        self.validate_commit(staged)
        self._time_scheduler = staged._staged_scheduler
        self._anchor_component_local_positions = (
            staged.next_anchor_component_local_positions
        )
        self._revision += 1

    def stage_substep(self, update_index: int) -> MC2MeshProductScheduledSubstepV1:
        staged_scheduler = self._time_scheduler.clone()
        plan = staged_scheduler.advance_substep(update_index)
        return MC2MeshProductScheduledSubstepV1(
            plan=plan,
            base_revision=self._revision,
            _owner_token=self._owner_token,
            _staged_scheduler=staged_scheduler,
        )

    def validate_substep_commit(
        self,
        staged: MC2MeshProductScheduledSubstepV1,
    ) -> None:
        if not isinstance(staged, MC2MeshProductScheduledSubstepV1):
            raise TypeError("staged must be MC2MeshProductScheduledSubstepV1")
        if staged._owner_token is not self._owner_token:
            raise ValueError("scheduled substep belongs to another scheduler state")
        if staged.base_revision != self._revision:
            raise RuntimeError("scheduled substep is stale")

    def commit_substep(self, staged: MC2MeshProductScheduledSubstepV1) -> None:
        self.validate_substep_commit(staged)
        self._time_scheduler = staged._staged_scheduler
        self._revision += 1

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_mesh_product_scheduler_state_v1",
            "partition_ids": list(self.partition_ids),
            "revision": self._revision,
            "anchor_component_local_positions": (
                self._anchor_component_local_positions.tolist()
            ),
            "time_scheduler": self._time_scheduler.debug_dict(),
        }


__all__ = [
    "MC2MeshProductScheduledFrameV1",
    "MC2MeshProductScheduledSubstepV1",
    "MC2MeshProductSchedulerStateV1",
]
