"""Native E3 data-path kernel for ``MC2CPUBackendDomainV1``.

The current native owner validates and transports compiled/frame data but does
not yet run numerical integration or constraints.  ``data_path_only`` is
therefore mandatory so this kernel cannot be mistaken for the product solver.
"""

from __future__ import annotations

from collections.abc import Mapping

from .domain_ir import MC2CompiledDomainProgramV1
from .domain_ir import MC2DomainFramePacketV1
from .domain_ir import MC2DomainParameterPacketV1
from .domain_ir import make_mc2_domain_frame_output
from .native import native_module


_NATIVE_SYMBOLS = (
    "mc2_domain_cpu_v1_create",
    "mc2_domain_cpu_v1_update_frame",
    "mc2_domain_cpu_v1_step",
    "mc2_domain_cpu_v1_read",
    "mc2_domain_cpu_v1_inspect",
    "mc2_domain_cpu_v1_dispose",
)


class MC2NativeCPUKernelV1:
    """Explicitly non-numerical native owner used to validate the E3 ABI."""

    def __init__(self, *, module=None) -> None:
        self._module = native_module() if module is None else module
        missing = tuple(
            symbol for symbol in _NATIVE_SYMBOLS
            if not callable(getattr(self._module, symbol, None))
        )
        if missing:
            raise RuntimeError(
                "MC2 native CPU data-path symbols are unavailable: "
                + ", ".join(missing)
            )
        self._programs: dict[int, MC2CompiledDomainProgramV1] = {}
        self._frames: dict[int, MC2DomainFramePacketV1] = {}

    def create_domain(
        self,
        program: MC2CompiledDomainProgramV1,
        parameters: MC2DomainParameterPacketV1,
    ):
        if not isinstance(program, MC2CompiledDomainProgramV1):
            raise TypeError("program must be MC2CompiledDomainProgramV1")
        if not isinstance(parameters, MC2DomainParameterPacketV1):
            raise TypeError("parameters must be MC2DomainParameterPacketV1")
        if parameters.layout_signature != program.layout_signature:
            raise ValueError("native CPU parameter layout does not match program")
        handle = int(self._module.mc2_domain_cpu_v1_create(
            program.schema_version,
            program.particle_count,
            program.domain_signature,
            program.layout_signature,
            program.particle_bind_position,
            program.particle_bind_rotation,
        ))
        if handle <= 0:
            raise RuntimeError("native CPU domain returned an invalid handle")
        self._programs[handle] = program
        return handle

    def update_frame(self, handle, frame_packet: MC2DomainFramePacketV1) -> None:
        key = self._require_handle(handle)
        if not isinstance(frame_packet, MC2DomainFramePacketV1):
            raise TypeError("frame_packet must be MC2DomainFramePacketV1")
        self._module.mc2_domain_cpu_v1_update_frame(
            key,
            frame_packet.domain_signature,
            frame_packet.layout_signature,
            frame_packet.frame,
            frame_packet.generation,
            frame_packet.animated_base_world_positions,
            frame_packet.animated_base_world_normals,
        )
        self._frames[key] = frame_packet

    def step(
        self,
        handle,
        frame_packet: MC2DomainFramePacketV1,
        scheduler_settings: Mapping[str, object],
        collider_snapshot,
    ) -> None:
        key = self._require_handle(handle)
        if dict(scheduler_settings) != {"data_path_only": True}:
            raise RuntimeError(
                "native MC2 CPU numerical kernel is not ready; "
                "only data_path_only=True is accepted"
            )
        if collider_snapshot is not None:
            raise RuntimeError("native MC2 CPU data-path slice does not consume colliders")
        if self._frames.get(key) is not frame_packet:
            raise ValueError("native MC2 CPU step frame is not the published frame packet")
        self._module.mc2_domain_cpu_v1_step(key)

    def read_output(self, handle):
        key = self._require_handle(handle)
        frame_packet = self._frames.get(key)
        if frame_packet is None:
            raise RuntimeError("native MC2 CPU output requires update_frame first")
        raw = self._module.mc2_domain_cpu_v1_read(key)
        return make_mc2_domain_frame_output(
            self._programs[key],
            frame_packet,
            world_positions=raw["world_positions"],
            backend_revision=1,
            backend_kind=str(raw["backend_kind"]),
        )

    def inspect(self, handle) -> dict:
        key = self._require_handle(handle)
        result = dict(self._module.mc2_domain_cpu_v1_inspect(key))
        result.update({
            "numerical_kernel_ready": False,
            "data_path_only": True,
        })
        return result

    def dispose(self, handle) -> None:
        key = int(handle or 0)
        if key <= 0 or key not in self._programs:
            return
        try:
            self._module.mc2_domain_cpu_v1_dispose(key)
        finally:
            self._programs.pop(key, None)
            self._frames.pop(key, None)

    def _require_handle(self, handle) -> int:
        key = int(handle or 0)
        if key <= 0 or key not in self._programs:
            raise RuntimeError("native MC2 CPU domain handle is not owned by this kernel")
        return key


__all__ = ["MC2NativeCPUKernelV1"]
