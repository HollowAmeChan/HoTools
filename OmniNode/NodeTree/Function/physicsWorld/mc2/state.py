"""Lightweight host lifecycle state for an MC2 native-context slot."""

from __future__ import annotations

from dataclasses import dataclass


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


__all__ = ["MC2SlotRuntimeState"]
