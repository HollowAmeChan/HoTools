"""MC2 setup adapter 的轻量声明契约。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MC2SetupAdapterContract:
    setup_type: str
    source_kind: str
    writeback_channel: str
    topology_builder_name: str
    implementation_status: str = "native_context_framework"

    def debug_dict(self) -> dict:
        return {
            "setup_type": self.setup_type,
            "source_kind": self.source_kind,
            "writeback_channel": self.writeback_channel,
            "topology_builder": self.topology_builder_name,
            "implementation_status": self.implementation_status,
        }
