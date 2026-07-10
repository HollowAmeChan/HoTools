"""MC2 Physics World slot 的轻量运行状态壳。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .initial_state import MC2InitialStateSpec


def _positions(values) -> np.ndarray:
    return np.ascontiguousarray(values, dtype=np.float32).reshape((-1, 3))


def _rotations(values) -> np.ndarray:
    return np.ascontiguousarray(values, dtype=np.float32).reshape((-1, 4))


@dataclass
class MC2ParticleBuffer:
    """与 Unity particle reset job 对齐的共享动态数组。"""

    particle_count: int
    next_positions: np.ndarray
    old_positions: np.ndarray
    old_rotations: np.ndarray
    base_positions: np.ndarray
    base_rotations: np.ndarray
    previous_positions: np.ndarray
    previous_rotations: np.ndarray
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
    reset_count: int = 1
    disposed: bool = False

    @classmethod
    def from_initial_state(cls, initial: MC2InitialStateSpec) -> "MC2ParticleBuffer":
        if not isinstance(initial, MC2InitialStateSpec):
            raise TypeError("initial 必须是 MC2InitialStateSpec")
        positions = _positions(initial.rest_positions)
        rotations = _rotations(initial.rest_rotations)
        count = int(initial.particle_count)
        zeros3 = np.zeros((count, 3), dtype=np.float32)
        return cls(
            particle_count=count,
            next_positions=positions.copy(),
            old_positions=positions.copy(),
            old_rotations=rotations.copy(),
            base_positions=positions.copy(),
            base_rotations=rotations.copy(),
            previous_positions=positions.copy(),
            previous_rotations=rotations.copy(),
            velocity_positions=positions.copy(),
            display_positions=positions.copy(),
            velocities=zeros3.copy(),
            real_velocities=zeros3.copy(),
            friction=np.zeros(count, dtype=np.float32),
            static_friction=np.zeros(count, dtype=np.float32),
            collision_normals=zeros3.copy(),
            step_basic_positions=positions.copy(),
            step_basic_rotations=rotations.copy(),
            parent_indices=np.ascontiguousarray(initial.parent_indices, dtype=np.int32),
            depths=np.ascontiguousarray(initial.depths, dtype=np.float32),
            fixed_mask=np.ascontiguousarray(initial.fixed_mask, dtype=np.bool_),
            source_indices=np.ascontiguousarray(initial.source_indices, dtype=np.int32),
            source_local_indices=np.ascontiguousarray(initial.source_local_indices, dtype=np.int32),
        )

    def reset(self, initial: MC2InitialStateSpec) -> None:
        replacement = type(self).from_initial_state(initial)
        reset_count = self.reset_count + 1
        self.__dict__.update(replacement.__dict__)
        self.reset_count = reset_count

    def dispose(self) -> None:
        self.disposed = True
        self.particle_count = 0
        for name in (
            "next_positions", "old_positions", "base_positions", "previous_positions",
            "velocity_positions", "display_positions", "velocities", "real_velocities",
            "collision_normals", "step_basic_positions",
        ):
            setattr(self, name, np.zeros((0, 3), dtype=np.float32))
        for name in ("old_rotations", "base_rotations", "previous_rotations", "step_basic_rotations"):
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
    topology_signature: str
    config_signature: str
    parameter_signature: str
    settings_signature: str
    world_generation: int
    particle_count: int
    parameter_revision: int = 0
    settings_revision: int = 0
    reset_count: int = 1
    last_reset_reason: str = "created"
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

    def debug_dict(self) -> dict:
        return {
            "topology_signature": self.topology_signature,
            "config_signature": self.config_signature,
            "parameter_signature": self.parameter_signature,
            "settings_signature": self.settings_signature,
            "world_generation": self.world_generation,
            "particle_count": self.particle_count,
            "parameter_revision": self.parameter_revision,
            "settings_revision": self.settings_revision,
            "reset_count": self.reset_count,
            "last_reset_reason": self.last_reset_reason,
            "initialized": self.initialized,
            "disposed": self.disposed,
            "dispose_reason": self.dispose_reason,
        }


__all__ = ["MC2ParticleBuffer", "MC2SlotRuntimeState"]
