"""MC2 Physics World slot 的轻量运行状态壳。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .initial_state import MC2InitialStateSpec


@dataclass
class MC2ParticleBuffer:
    """与 Unity particle reset job 对齐的共享动态数组。"""

    particle_count: int
    next_positions: np.ndarray
    old_positions: np.ndarray
    old_rotations: np.ndarray
    base_positions: np.ndarray
    base_rotations: np.ndarray
    old_frame_positions: np.ndarray
    old_frame_rotations: np.ndarray
    velocity_positions: np.ndarray
    display_positions: np.ndarray
    velocities: np.ndarray
    real_velocities: np.ndarray
    friction: np.ndarray
    static_friction: np.ndarray
    collision_normals: np.ndarray
    step_basic_positions: np.ndarray
    step_basic_rotations: np.ndarray
    parent_indices: np.ndarray
    depths: np.ndarray
    fixed_mask: np.ndarray
    source_indices: np.ndarray
    source_local_indices: np.ndarray
    reset_count: int = 0
    disposed: bool = False

    @classmethod
    def allocate(cls, initial: MC2InitialStateSpec) -> "MC2ParticleBuffer":
        if not isinstance(initial, MC2InitialStateSpec):
            raise TypeError("initial 必须是 MC2InitialStateSpec")
        count = int(initial.particle_count)
        zeros3 = np.zeros((count, 3), dtype=np.float32)
        zeros4 = np.zeros((count, 4), dtype=np.float32)
        return cls(
            particle_count=count,
            next_positions=zeros3.copy(),
            old_positions=zeros3.copy(),
            old_rotations=zeros4.copy(),
            base_positions=zeros3.copy(),
            base_rotations=zeros4.copy(),
            old_frame_positions=zeros3.copy(),
            old_frame_rotations=zeros4.copy(),
            velocity_positions=zeros3.copy(),
            display_positions=zeros3.copy(),
            velocities=zeros3.copy(),
            real_velocities=zeros3.copy(),
            friction=np.zeros(count, dtype=np.float32),
            static_friction=np.zeros(count, dtype=np.float32),
            collision_normals=zeros3.copy(),
            step_basic_positions=zeros3.copy(),
            step_basic_rotations=zeros4.copy(),
            parent_indices=np.ascontiguousarray(initial.parent_indices, dtype=np.int32),
            depths=np.ascontiguousarray(initial.depths, dtype=np.float32),
            fixed_mask=np.ascontiguousarray(initial.fixed_mask, dtype=np.bool_),
            source_indices=np.ascontiguousarray(initial.source_indices, dtype=np.int32),
            source_local_indices=np.ascontiguousarray(initial.source_local_indices, dtype=np.int32),
        )

    def reset_from_frame(self, frame_input) -> None:
        if self.disposed:
            raise RuntimeError("cannot reset a disposed MC2 particle buffer")
        if frame_input.particle_count != self.particle_count:
            raise ValueError("frame input particle count mismatch")
        positions = np.ascontiguousarray(frame_input.world_positions, dtype=np.float32)
        rotations = np.ascontiguousarray(frame_input.world_rotations_xyzw, dtype=np.float32)
        for name in (
            "next_positions", "old_positions", "base_positions", "old_frame_positions",
            "velocity_positions", "display_positions",
            "step_basic_positions",
        ):
            getattr(self, name)[:] = positions
        for name in (
            "old_rotations", "base_rotations", "old_frame_rotations", "step_basic_rotations",
        ):
            getattr(self, name)[:] = rotations
        self.velocities.fill(0.0)
        self.real_velocities.fill(0.0)
        self.friction.fill(0.0)
        self.static_friction.fill(0.0)
        self.collision_normals.fill(0.0)
        self.reset_count += 1

    def update_base_pose(self, frame_input) -> None:
        if self.disposed:
            raise RuntimeError("cannot update a disposed MC2 particle buffer")
        if frame_input.particle_count != self.particle_count:
            raise ValueError("frame input particle count mismatch")
        self.base_positions[:] = frame_input.world_positions
        self.base_rotations[:] = frame_input.world_rotations_xyzw
        self.step_basic_positions[:] = frame_input.world_positions
        self.step_basic_rotations[:] = frame_input.world_rotations_xyzw

    def dispose(self) -> None:
        self.disposed = True
        self.particle_count = 0
        for name in (
            "next_positions", "old_positions", "base_positions", "old_frame_positions",
            "velocity_positions", "display_positions", "velocities", "real_velocities",
            "collision_normals", "step_basic_positions",
        ):
            setattr(self, name, np.zeros((0, 3), dtype=np.float32))
        for name in ("old_rotations", "base_rotations", "old_frame_rotations", "step_basic_rotations"):
            setattr(self, name, np.zeros((0, 4), dtype=np.float32))
        for name in ("friction", "static_friction", "depths"):
            setattr(self, name, np.zeros(0, dtype=np.float32))
        for name in ("parent_indices", "source_indices", "source_local_indices"):
            setattr(self, name, np.zeros(0, dtype=np.int32))
        self.fixed_mask = np.zeros(0, dtype=np.bool_)

    def debug_dict(self) -> dict:
        velocity_max = (
            float(np.max(np.linalg.norm(self.velocities, axis=1)))
            if self.particle_count and self.velocities.size
            else 0.0
        )
        return {
            "particle_count": self.particle_count,
            "position_shape": tuple(self.next_positions.shape),
            "rotation_shape": tuple(self.base_rotations.shape),
            "fixed_count": int(np.count_nonzero(self.fixed_mask)),
            "velocity_max": velocity_max,
            "reset_count": self.reset_count,
            "disposed": self.disposed,
        }


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


__all__ = ["MC2ParticleBuffer", "MC2SlotRuntimeState"]
