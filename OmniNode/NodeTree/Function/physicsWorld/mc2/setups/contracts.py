"""MC2 setup adapter 的轻量声明契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class MC2SetupAdapterContract:
    setup_type: str
    source_kind: str
    writeback_channel: str
    topology_builder: Callable = field(repr=False, compare=False)
    initial_state_builder: Callable = field(repr=False, compare=False)
    implementation_status: str = "topology_slot_framework"

    def build_source_topology(self, source, source_index: int):
        return self.topology_builder(source, int(source_index))

    def build_initial_state(self, task, topology):
        return self.initial_state_builder(task, topology)

    def debug_dict(self) -> dict:
        return {
            "setup_type": self.setup_type,
            "source_kind": self.source_kind,
            "writeback_channel": self.writeback_channel,
            "topology_builder": getattr(self.topology_builder, "__name__", ""),
            "initial_state_builder": getattr(self.initial_state_builder, "__name__", ""),
            "implementation_status": self.implementation_status,
        }
