"""N3 frame input, continuity, and explicit particle reset contracts."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


MC2_FRAME_SCHEMA_VERSION = 0


def _readonly(values, width: int, name: str) -> np.ndarray:
    array = np.ascontiguousarray(values, dtype=np.float32).reshape((-1, width))
    if not np.isfinite(array).all():
        raise ValueError(f"{name} cannot contain NaN/Inf")
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class MC2FrameInputSpec:
    task_id: str
    topology_signature: str
    frame: int
    generation: int
    world_positions: np.ndarray
    world_rotations_xyzw: np.ndarray
    velocity_weight: float = 1.0
    gravity_ratio: float = 1.0
    scale_ratio: float = 1.0
    negative_scale_sign: float = 1.0
    schema_version: int = MC2_FRAME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.task_id or not self.topology_signature:
            raise ValueError("MC2 frame input requires task and topology identity")
        positions = self.world_positions
        rotations = self.world_rotations_xyzw
        if positions.dtype != np.float32 or rotations.dtype != np.float32:
            raise TypeError("MC2 frame arrays must be float32")
        if positions.ndim != 2 or positions.shape[1] != 3:
            raise ValueError("world_positions must have shape [N,3]")
        if rotations.shape != (len(positions), 4):
            raise ValueError("world_rotations_xyzw must have shape [N,4]")
        if positions.flags.writeable or rotations.flags.writeable:
            raise ValueError("MC2 frame arrays must be read-only")
        if not np.isfinite(positions).all() or not np.isfinite(rotations).all():
            raise ValueError("MC2 frame input cannot contain NaN/Inf")
        if not 0.0 <= float(self.velocity_weight) <= 1.0:
            raise ValueError("velocity_weight must be in 0..1")
        if not 0.0 <= float(self.gravity_ratio) <= 1.0:
            raise ValueError("gravity_ratio must be in 0..1")
        if not np.isfinite(self.scale_ratio) or float(self.scale_ratio) <= 0.0:
            raise ValueError("scale_ratio must be finite and positive")
        if float(self.negative_scale_sign) not in (-1.0, 1.0):
            raise ValueError("negative_scale_sign must be -1 or 1")
        lengths = np.linalg.norm(rotations, axis=1)
        if len(lengths) and not np.allclose(lengths, 1.0, rtol=1.0e-5, atol=1.0e-6):
            raise ValueError("world_rotations_xyzw must contain unit quaternions")
        if self.schema_version != MC2_FRAME_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 frame schema version")

    @property
    def particle_count(self) -> int:
        return int(len(self.world_positions))


def make_mc2_frame_input(
    *,
    task_id: object,
    topology_signature: object,
    frame: object,
    generation: object,
    world_positions,
    world_rotations_xyzw,
    velocity_weight: object = 1.0,
    gravity_ratio: object = 1.0,
    scale_ratio: object = 1.0,
    negative_scale_sign: object = 1.0,
) -> MC2FrameInputSpec:
    return MC2FrameInputSpec(
        task_id=str(task_id or ""),
        topology_signature=str(topology_signature or ""),
        frame=int(frame),
        generation=int(generation),
        world_positions=_readonly(world_positions, 3, "world_positions"),
        world_rotations_xyzw=_readonly(world_rotations_xyzw, 4, "world_rotations_xyzw"),
        velocity_weight=float(velocity_weight),
        gravity_ratio=float(gravity_ratio),
        scale_ratio=float(scale_ratio),
        negative_scale_sign=float(negative_scale_sign),
    )


@dataclass(frozen=True)
class MC2FrameSyncResult:
    action: str
    reset_reason: str
    frame: int
    generation: int


def plan_mc2_frame_sync(runtime_state, frame_input, *, user_reset=False):
    """Classify a frame transition without mutating host or native state."""
    from .state import MC2SlotRuntimeState

    if not isinstance(runtime_state, MC2SlotRuntimeState):
        raise TypeError("runtime_state must be MC2SlotRuntimeState")
    if not isinstance(frame_input, MC2FrameInputSpec):
        raise TypeError("frame_input must be MC2FrameInputSpec")
    if runtime_state.disposed:
        raise RuntimeError("cannot sync a disposed MC2 slot")
    if frame_input.task_id != runtime_state.task_id:
        raise ValueError("frame input task identity mismatch")
    if frame_input.topology_signature != runtime_state.topology_signature:
        raise ValueError("frame input topology identity mismatch")
    if frame_input.particle_count != runtime_state.particle_count:
        raise ValueError("frame input particle count mismatch")

    same_identity = (
        runtime_state.last_frame == frame_input.frame
        and runtime_state.last_frame_generation == frame_input.generation
    )
    if same_identity and not user_reset:
        return MC2FrameSyncResult("same_frame", "", frame_input.frame, frame_input.generation)

    reset_reason = ""
    if user_reset:
        reset_reason = "user_reset"
    elif not runtime_state.initialized:
        reset_reason = "first_valid_pose"
    elif runtime_state.last_frame_generation != frame_input.generation:
        reset_reason = "frame_generation_changed"
    elif frame_input.frame < runtime_state.last_frame:
        reset_reason = "time_reversed"
    elif frame_input.frame > runtime_state.last_frame + 1:
        reset_reason = "time_discontinuity"

    action = "reset" if reset_reason else "updated"
    return MC2FrameSyncResult(action, reset_reason, frame_input.frame, frame_input.generation)


def sync_mc2_frame_input(runtime_state, particle_buffer, frame_input, *, user_reset=False):
    """Commit a previously valid frame transition to host particle state."""
    from .state import MC2ParticleBuffer

    if not isinstance(particle_buffer, MC2ParticleBuffer):
        raise TypeError("particle_buffer must be MC2ParticleBuffer")
    if particle_buffer.disposed:
        raise RuntimeError("cannot sync a disposed MC2 slot")
    result = plan_mc2_frame_sync(runtime_state, frame_input, user_reset=user_reset)
    if result.action == "same_frame":
        return result
    if result.action == "reset":
        particle_buffer.reset_from_frame(frame_input)
        runtime_state.mark_frame_reset(frame_input, result.reset_reason)
    else:
        particle_buffer.update_base_pose(frame_input)
        runtime_state.mark_frame_update(frame_input)
    return result


__all__ = [
    "MC2_FRAME_SCHEMA_VERSION",
    "MC2FrameInputSpec",
    "MC2FrameSyncResult",
    "make_mc2_frame_input",
    "plan_mc2_frame_sync",
    "sync_mc2_frame_input",
]
