"""N3 frame input, continuity, and explicit particle reset contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .center_state import MC2CenterFramePoseSpec


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
    raw_pose_matrices: np.ndarray | None = None
    source_world_linear: np.ndarray | None = None
    center_frame_pose: MC2CenterFramePoseSpec | None = None
    velocity_weight: float = 1.0
    gravity_ratio: float = 1.0
    scale_ratio: float = 1.0
    negative_scale_sign: float = 1.0
    frame_interpolation: float = 1.0
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
        raw_pose_matrices = self.raw_pose_matrices
        if rotations.shape not in ((len(positions), 4), (0, 4)):
            raise ValueError("world_rotations_xyzw must have shape [N,4] or [0,4]")
        if len(rotations) == 0 and raw_pose_matrices is None:
            if self.source_world_linear is None:
                raise ValueError("native-produced Mesh frame requires source_world_linear")
        if raw_pose_matrices is not None:
            if (
                raw_pose_matrices.dtype != np.float32
                or raw_pose_matrices.shape != (len(positions), 3, 3)
                or raw_pose_matrices.flags.writeable
                or not np.isfinite(raw_pose_matrices).all()
            ):
                raise ValueError("raw_pose_matrices must be finite read-only float32[N,3,3]")
            if len(rotations) != 0:
                raise ValueError("raw Bone frame cannot also contain host-produced rotations")
        if positions.flags.writeable or rotations.flags.writeable:
            raise ValueError("MC2 frame arrays must be read-only")
        if not np.isfinite(positions).all() or not np.isfinite(rotations).all():
            raise ValueError("MC2 frame input cannot contain NaN/Inf")
        linear = self.source_world_linear
        if linear is not None:
            if linear.dtype != np.float32 or linear.shape != (3, 3):
                raise TypeError("source_world_linear must be float32[3,3]")
            if linear.flags.writeable or not np.isfinite(linear).all():
                raise ValueError("source_world_linear must be finite and read-only")
            if abs(float(np.linalg.det(linear.astype(np.float64)))) <= 1.0e-12:
                raise ValueError("source_world_linear must be invertible")
        center_pose = self.center_frame_pose
        if center_pose is not None:
            from .center_state import MC2CenterFramePoseSpec

            if not isinstance(center_pose, MC2CenterFramePoseSpec):
                raise TypeError("center_frame_pose must be MC2CenterFramePoseSpec")
            if center_pose.frame != self.frame or center_pose.generation != self.generation:
                raise ValueError("center_frame_pose frame identity must match MC2 frame input")
        if not 0.0 <= float(self.velocity_weight) <= 1.0:
            raise ValueError("velocity_weight must be in 0..1")
        if not 0.0 <= float(self.gravity_ratio) <= 1.0:
            raise ValueError("gravity_ratio must be in 0..1")
        if not np.isfinite(self.scale_ratio) or float(self.scale_ratio) <= 0.0:
            raise ValueError("scale_ratio must be finite and positive")
        if float(self.negative_scale_sign) not in (-1.0, 1.0):
            raise ValueError("negative_scale_sign must be -1 or 1")
        if not 0.0 <= float(self.frame_interpolation) <= 1.0:
            raise ValueError("frame_interpolation must be in 0..1")
        lengths = np.linalg.norm(rotations, axis=1)
        if len(lengths) and not np.allclose(lengths, 1.0, rtol=1.0e-5, atol=1.0e-6):
            raise ValueError("world_rotations_xyzw must contain unit quaternions")
        if self.schema_version != MC2_FRAME_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 frame schema version")

    @property
    def particle_count(self) -> int:
        return int(len(self.world_positions))

    @property
    def native_producer_kind(self) -> str:
        if self.raw_pose_matrices is not None:
            return "bone"
        if len(self.world_rotations_xyzw) == 0:
            return "mesh"
        return "host"


def make_mc2_frame_input(
    *,
    task_id: object,
    topology_signature: object,
    frame: object,
    generation: object,
    world_positions,
    world_rotations_xyzw,
    raw_pose_matrices=None,
    source_world_linear=None,
    center_frame_pose=None,
    velocity_weight: object = 1.0,
    gravity_ratio: object = 1.0,
    scale_ratio: object = 1.0,
    negative_scale_sign: object = 1.0,
    frame_interpolation: object = 1.0,
) -> MC2FrameInputSpec:
    return MC2FrameInputSpec(
        task_id=str(task_id or ""),
        topology_signature=str(topology_signature or ""),
        frame=int(frame),
        generation=int(generation),
        world_positions=_readonly(world_positions, 3, "world_positions"),
        world_rotations_xyzw=(
            _readonly(world_rotations_xyzw, 4, "world_rotations_xyzw")
            if world_rotations_xyzw is not None
            else _readonly((), 4, "world_rotations_xyzw")
        ),
        raw_pose_matrices=(
            _readonly(raw_pose_matrices, 3, "raw_pose_matrices").reshape((-1, 3, 3))
            if raw_pose_matrices is not None
            else None
        ),
        source_world_linear=(
            _readonly(source_world_linear, 3, "source_world_linear")
            if source_world_linear is not None
            else None
        ),
        center_frame_pose=center_frame_pose,
        velocity_weight=float(velocity_weight),
        gravity_ratio=float(gravity_ratio),
        scale_ratio=float(scale_ratio),
        negative_scale_sign=float(negative_scale_sign),
        frame_interpolation=float(frame_interpolation),
    )


@dataclass
class MC2SlotRuntimeState:
    task_id: str
    topology_signature: str
    config_signature: str
    parameter_signature: str
    settings_signature: str
    world_generation: int
    particle_count: int
    allocation_reason: str = "created"
    parameter_revision: int = 0
    settings_revision: int = 0
    reset_count: int = 0
    last_reset_reason: str = "allocation_pending"
    last_frame: int | None = None
    last_frame_generation: int | None = None
    frame_revision: int = 0
    initialized: bool = False
    disposed: bool = False
    dispose_reason: str = ""

    def update_contracts(
        self,
        *,
        config_signature: str,
        parameter_signature: str,
        settings_signature: str,
    ) -> tuple[bool, bool]:
        parameter_changed = (
            self.config_signature != config_signature
            or self.parameter_signature != parameter_signature
        )
        settings_changed = self.settings_signature != settings_signature
        if parameter_changed:
            self.config_signature = config_signature
            self.parameter_signature = parameter_signature
            self.parameter_revision += 1
        if settings_changed:
            self.settings_signature = settings_signature
            self.settings_revision += 1
        return parameter_changed, settings_changed

    def dispose(self, reason: str) -> None:
        self.disposed = True
        self.dispose_reason = str(reason or "dispose")
        self.initialized = False

    def mark_frame_reset(self, frame_input, reason: str) -> None:
        self.last_frame = int(frame_input.frame)
        self.last_frame_generation = int(frame_input.generation)
        self.frame_revision += 1
        self.reset_count += 1
        self.last_reset_reason = str(reason)
        self.initialized = True

    def mark_frame_update(self, frame_input) -> None:
        self.last_frame = int(frame_input.frame)
        self.last_frame_generation = int(frame_input.generation)
        self.frame_revision += 1

    def debug_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "topology_signature": self.topology_signature,
            "config_signature": self.config_signature,
            "parameter_signature": self.parameter_signature,
            "settings_signature": self.settings_signature,
            "world_generation": self.world_generation,
            "particle_count": self.particle_count,
            "allocation_reason": self.allocation_reason,
            "parameter_revision": self.parameter_revision,
            "settings_revision": self.settings_revision,
            "reset_count": self.reset_count,
            "last_reset_reason": self.last_reset_reason,
            "last_frame": self.last_frame,
            "last_frame_generation": self.last_frame_generation,
            "frame_revision": self.frame_revision,
            "initialized": self.initialized,
            "disposed": self.disposed,
            "dispose_reason": self.dispose_reason,
        }


@dataclass(frozen=True)
class MC2FrameSyncResult:
    action: str
    reset_reason: str
    frame: int
    generation: int


def plan_mc2_frame_sync(runtime_state, frame_input, *, user_reset=False):
    """Classify a frame transition without mutating host or native state."""
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


__all__ = [
    "MC2_FRAME_SCHEMA_VERSION",
    "MC2FrameInputSpec",
    "MC2FrameSyncResult",
    "MC2SlotRuntimeState",
    "make_mc2_frame_input",
    "plan_mc2_frame_sync",
]
