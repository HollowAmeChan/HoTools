"""Private MC2 native readback snapshot; not a published solver result."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


MC2_RESULT_CANDIDATE_SCHEMA_VERSION = 0


@dataclass(frozen=True)
class MC2ResultCandidateV0:
    task_id: str
    slot_id: str
    setup_type: str
    frame: int
    generation: int
    world_generation: int
    topology_signature: str
    revision: int
    native_reset_count: int
    native_step_count: int
    native_dynamic_revision: int
    world_positions: np.ndarray
    world_rotations_xyzw: np.ndarray
    ready: bool = False
    schema_version: int = MC2_RESULT_CANDIDATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MC2_RESULT_CANDIDATE_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 result candidate schema")
        if not self.task_id or not self.slot_id or not self.setup_type:
            raise ValueError("MC2 result candidate identity cannot be empty")
        if not self.topology_signature or self.revision <= 0:
            raise ValueError("MC2 result candidate revision identity is invalid")
        if self.ready:
            raise ValueError("private MC2 result candidate cannot be ready")
        if self.native_reset_count <= 0 or self.native_step_count < 0:
            raise ValueError("MC2 result candidate native lifecycle is invalid")
        if self.native_dynamic_revision <= 0:
            raise ValueError("MC2 result candidate native revision is invalid")
        positions = self.world_positions
        rotations = self.world_rotations_xyzw
        if positions.dtype != np.float32 or positions.ndim != 2 or positions.shape[1] != 3:
            raise TypeError("candidate world_positions must be float32[N,3]")
        if rotations.dtype != np.float32 or rotations.shape != (len(positions), 4):
            raise TypeError("candidate world_rotations_xyzw must be float32[N,4]")
        if positions.flags.writeable or rotations.flags.writeable:
            raise ValueError("MC2 result candidate arrays must be read-only")
        if not np.isfinite(positions).all() or not np.isfinite(rotations).all():
            raise ValueError("MC2 result candidate arrays cannot contain NaN/Inf")

    @property
    def particle_count(self) -> int:
        return int(len(self.world_positions))

    def debug_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "slot_id": self.slot_id,
            "setup_type": self.setup_type,
            "frame": self.frame,
            "generation": self.generation,
            "world_generation": self.world_generation,
            "revision": self.revision,
            "ready": self.ready,
            "particle_count": self.particle_count,
            "native_reset_count": self.native_reset_count,
            "native_step_count": self.native_step_count,
            "native_dynamic_revision": self.native_dynamic_revision,
        }


def make_mc2_result_candidate(
    *,
    spec,
    slot,
    frame_input,
    revision: int,
    native_info: dict,
    world_positions,
    world_rotations_xyzw,
) -> MC2ResultCandidateV0:
    if spec.task_id != slot.slot_id or frame_input.task_id != spec.task_id:
        raise ValueError("MC2 result candidate host task identity mismatch")
    positions = np.array(world_positions, dtype=np.float32, order="C", copy=True)
    rotations = np.array(world_rotations_xyzw, dtype=np.float32, order="C", copy=True)
    if native_info.get("schema") != "mc2_context_v0" or native_info.get("released") is True:
        raise ValueError("MC2 result candidate requires a live native context V0")
    if not bool(native_info.get("initialized")):
        raise ValueError("MC2 result candidate requires initialized native state")
    if int(native_info.get("vertex_count", -1)) != len(positions):
        raise ValueError("MC2 result candidate native particle count mismatch")
    if (
        int(native_info.get("frame", -1)) != frame_input.frame
        or int(native_info.get("generation", -1)) != frame_input.generation
    ):
        raise ValueError("MC2 result candidate native frame identity mismatch")
    positions.flags.writeable = False
    rotations.flags.writeable = False
    return MC2ResultCandidateV0(
        task_id=spec.task_id,
        slot_id=slot.slot_id,
        setup_type=spec.setup_type,
        frame=frame_input.frame,
        generation=frame_input.generation,
        world_generation=slot.world_generation,
        topology_signature=frame_input.topology_signature,
        revision=int(revision),
        native_reset_count=int(native_info["reset_count"]),
        native_step_count=int(native_info["step_count"]),
        native_dynamic_revision=int(native_info["dynamic_revision"]),
        world_positions=positions,
        world_rotations_xyzw=rotations,
    )


__all__ = [
    "MC2_RESULT_CANDIDATE_SCHEMA_VERSION",
    "MC2ResultCandidateV0",
    "make_mc2_result_candidate",
]
