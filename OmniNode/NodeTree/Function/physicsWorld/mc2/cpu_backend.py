"""E3 CPU backend lifecycle boundary for compiled MC2 domains.

This module owns only backend-domain state.  A native/C++ kernel is injected
through ``MC2CPUKernelV1``; the adapter never imports Blender or the V0 slot
context and therefore remains testable without allocating native resources.
"""

from __future__ import annotations

from typing import Mapping, Protocol

import numpy as np

from .domain_capabilities import MC2BackendCapabilitiesV1
from .domain_capabilities import evaluate_mc2_backend_capabilities
from .domain_compile import MC2MeshCompiledDomainV1
from .domain_ir import MC2DomainFrameOutputV1
from .domain_ir import MC2DomainFramePacketV1
from .domain_ir import MC2PhysicalIndexMapV1
from .domain_ir import make_mc2_domain_frame_output
from .domain_ir import make_mc2_physical_index_map


MC2_CPU_REFERENCE_CAPABILITIES = MC2BackendCapabilitiesV1(
    backend_id="mc2_cpu_domain_v1",
    schema_versions=(1,),
    setup_types=("mesh_cloth",),
    capabilities=("mesh_cloth", "self_collision"),
    max_particles=0xFFFFFFFF,
    index_width_bits=32,
    supports_physical_reorder=True,
)


class MC2CPUKernelV1(Protocol):
    """The narrow native kernel ABI consumed by this adapter."""

    def create_domain(self, program, parameters): ...

    def update_frame(self, handle, frame_packet): ...

    def step(self, handle, frame_packet, scheduler_settings, collider_snapshot): ...

    def read_output(self, handle) -> MC2DomainFrameOutputV1: ...

    def inspect(self, handle) -> Mapping[str, object]: ...

    def dispose(self, handle) -> None: ...


class MC2CPUBackendDomainV1:
    """A slot-independent CPU domain handle with atomic lifecycle updates."""

    def __init__(
        self,
        compiled: MC2MeshCompiledDomainV1,
        kernel: MC2CPUKernelV1,
        handle,
        physical_index_map: MC2PhysicalIndexMapV1,
    ) -> None:
        self._compiled = compiled
        self._kernel = kernel
        self._handle = handle
        self._physical_index_map = physical_index_map
        self._latest_frame: MC2DomainFramePacketV1 | None = None
        self._last_output: MC2DomainFrameOutputV1 | None = None
        self._step_count = 0
        self._partition_history = {
            partition_id: {"last_frame": None, "generation": None}
            for partition_id in compiled.program.partition_ids
        }

    @property
    def disposed(self) -> bool:
        return self._handle is None

    @property
    def compiled(self) -> MC2MeshCompiledDomainV1:
        return self._compiled

    @property
    def physical_index_map(self) -> MC2PhysicalIndexMapV1:
        return self._physical_index_map

    @property
    def latest_frame(self) -> MC2DomainFramePacketV1 | None:
        return self._latest_frame

    @property
    def last_output(self) -> MC2DomainFrameOutputV1 | None:
        return self._last_output

    @classmethod
    def create(
        cls,
        compiled: MC2MeshCompiledDomainV1,
        kernel: MC2CPUKernelV1,
        *,
        capabilities: MC2BackendCapabilitiesV1 = MC2_CPU_REFERENCE_CAPABILITIES,
    ) -> "MC2CPUBackendDomainV1":
        if not isinstance(compiled, MC2MeshCompiledDomainV1):
            raise TypeError("compiled must be MC2MeshCompiledDomainV1")
        report = evaluate_mc2_backend_capabilities(compiled.program, capabilities)
        if not report.compatible:
            raise RuntimeError(
                "MC2 CPU backend capability gate rejected domain: "
                + ", ".join(report.blockers)
            )
        required_methods = (
            "create_domain", "update_frame", "step", "read_output", "inspect", "dispose"
        )
        if any(not callable(getattr(kernel, name, None)) for name in required_methods):
            raise TypeError("kernel does not implement MC2CPUKernelV1")
        handle = None
        try:
            handle = kernel.create_domain(compiled.program, compiled.parameters)
            if handle is None:
                raise RuntimeError("CPU kernel returned an empty domain handle")
            identity = np.arange(compiled.program.particle_count, dtype=np.uint32)
            physical_index_map = make_mc2_physical_index_map(identity)
            return cls(compiled, kernel, handle, physical_index_map)
        except Exception:
            if handle is not None:
                try:
                    kernel.dispose(handle)
                except Exception:
                    pass
            raise

    def update_frame(self, frame_packet: MC2DomainFramePacketV1) -> None:
        self._ensure_live()
        if not isinstance(frame_packet, MC2DomainFramePacketV1):
            raise TypeError("frame_packet must be MC2DomainFramePacketV1")
        self._validate_identity(frame_packet.domain_signature, frame_packet.layout_signature)
        self._kernel.update_frame(self._handle, frame_packet)
        self._latest_frame = frame_packet
        for partition_id in self._partition_history:
            self._partition_history[partition_id] = {
                "last_frame": int(frame_packet.frame),
                "generation": int(frame_packet.generation),
            }

    def step(
        self,
        scheduler_settings: Mapping[str, object],
        collider_snapshot=None,
    ) -> None:
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("CPU backend step requires update_frame first")
        if not isinstance(scheduler_settings, Mapping):
            raise TypeError("scheduler_settings must be a mapping")
        settings = dict(scheduler_settings)
        if settings.get("distance_slice") is True:
            step_distance = getattr(self._kernel, "step_distance", None)
            if not callable(step_distance):
                raise RuntimeError("CPU kernel does not expose the distance slice")
            if settings.pop("distance_slice") is not True:
                raise RuntimeError("distance_slice must be true when requested")
            if settings != {"data_path_only": True} or collider_snapshot is not None:
                raise RuntimeError(
                    "distance_slice requires data_path_only=True and no colliders"
                )
            step_distance(self._handle)
        else:
            self._kernel.step(
                self._handle,
                self._latest_frame,
                settings,
                collider_snapshot,
            )
        self._step_count += 1

    def read_output(self) -> MC2DomainFrameOutputV1:
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("CPU backend read_output requires update_frame first")
        output = self._kernel.read_output(self._handle)
        if not isinstance(output, MC2DomainFrameOutputV1):
            raise TypeError("CPU kernel returned an invalid MC2DomainFrameOutputV1")
        self._validate_identity(output.domain_signature, output.layout_signature)
        if (output.frame, output.generation) != (
            self._latest_frame.frame, self._latest_frame.generation
        ):
            raise RuntimeError("CPU backend output frame identity does not match input")
        if output.index_order == "logical":
            normalized = output
        else:
            physical_to_logical = np.asarray(output.physical_to_logical, dtype=np.uint32)
            logical_to_physical = np.empty_like(physical_to_logical)
            logical_to_physical[physical_to_logical] = np.arange(
                len(physical_to_logical), dtype=np.uint32
            )
            positions = output.world_positions[logical_to_physical]
            rotations = output.world_rotations_xyzw
            if len(rotations):
                rotations = rotations[logical_to_physical]
            normalized = make_mc2_domain_frame_output(
                self._compiled.program,
                self._latest_frame,
                world_positions=positions,
                world_rotations_xyzw=rotations if len(rotations) else None,
                validity_flags=output.validity_flags,
                backend_revision=output.backend_revision,
                backend_kind=output.backend_kind,
                timing_token=output.timing_token,
            )
        self._last_output = normalized
        return normalized

    def inspect(self) -> dict:
        self._ensure_live()
        kernel_state = self._kernel.inspect(self._handle)
        if not isinstance(kernel_state, Mapping):
            raise TypeError("CPU kernel inspect must return a mapping")
        return {
            "backend_id": MC2_CPU_REFERENCE_CAPABILITIES.backend_id,
            "domain_signature": self._compiled.program.domain_signature,
            "layout_signature": self._compiled.program.layout_signature,
            "physical_layout_revision": 1,
            "particle_count": self._compiled.program.particle_count,
            "partition_ids": self._compiled.program.partition_ids,
            "step_count": self._step_count,
            "partition_history": {
                key: dict(value) for key, value in self._partition_history.items()
            },
            "kernel": dict(kernel_state),
        }

    def dispose(self) -> None:
        if self._handle is not None:
            handle = self._handle
            self._handle = None
            try:
                self._kernel.dispose(handle)
            finally:
                self._latest_frame = None
                self._last_output = None
                self._partition_history.clear()

    def __enter__(self) -> "MC2CPUBackendDomainV1":
        self._ensure_live()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.dispose()

    def _validate_identity(self, domain_signature: str, layout_signature: str) -> None:
        if domain_signature != self._compiled.program.domain_signature:
            raise ValueError("CPU backend domain signature mismatch")
        if layout_signature != self._compiled.program.layout_signature:
            raise ValueError("CPU backend layout signature mismatch")

    def _ensure_live(self) -> None:
        if self._handle is None:
            raise RuntimeError("MC2 CPU backend domain has been disposed")


def create_mc2_cpu_backend_domain(
    compiled: MC2MeshCompiledDomainV1,
    kernel: MC2CPUKernelV1,
    *,
    capabilities: MC2BackendCapabilitiesV1 = MC2_CPU_REFERENCE_CAPABILITIES,
) -> MC2CPUBackendDomainV1:
    return MC2CPUBackendDomainV1.create(
        compiled,
        kernel,
        capabilities=capabilities,
    )


__all__ = [
    "MC2_CPU_REFERENCE_CAPABILITIES",
    "MC2CPUBackendDomainV1",
    "MC2CPUKernelV1",
    "create_mc2_cpu_backend_domain",
]
