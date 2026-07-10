"""MC2 Physics World slot 的轻量运行状态壳。"""

from __future__ import annotations

from dataclasses import dataclass


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


__all__ = ["MC2SlotRuntimeState"]
