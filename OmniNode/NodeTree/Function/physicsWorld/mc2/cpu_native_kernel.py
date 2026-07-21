"""Native E3 data-path kernel for ``MC2CPUBackendDomainV1``.

The default product step remains unavailable.  Explicit data-path, Distance,
and Center inertia slices are opt-in so they cannot be mistaken for the
product solver.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from .domain_ir import MC2CompiledDomainProgramV1
from .domain_ir import MC2DomainFramePacketV1
from .domain_ir import MC2DomainParameterPacketV1
from .domain_ir import make_mc2_domain_frame_output
from .native import native_module


_NATIVE_SYMBOLS = (
    "mc2_domain_cpu_v1_create",
    "mc2_domain_cpu_v1_update_frame",
    "mc2_domain_cpu_v1_step",
    "mc2_domain_cpu_v1_configure_distance",
    "mc2_domain_cpu_v1_step_distance",
    "mc2_domain_cpu_v1_configure_inertia",
    "mc2_domain_cpu_v1_step_inertia",
    "mc2_domain_cpu_v1_configure_integration",
    "mc2_domain_cpu_v1_step_integration",
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
        self._parameters: dict[int, MC2DomainParameterPacketV1] = {}
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
        try:
            self._configure_distance(handle, program, parameters)
            self._configure_inertia(handle, program, parameters)
            self._configure_integration(handle, parameters)
        except Exception:
            self._module.mc2_domain_cpu_v1_dispose(handle)
            raise
        self._programs[handle] = program
        self._parameters[handle] = parameters
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
        settings = dict(scheduler_settings)
        distance_slice = settings.pop("distance_slice", False) is True
        if settings != {"data_path_only": True}:
            raise RuntimeError(
                "native MC2 CPU numerical kernel is not ready; "
                "only data_path_only=True is accepted"
            )
        if collider_snapshot is not None:
            raise RuntimeError("native MC2 CPU data-path slice does not consume colliders")
        if self._frames.get(key) is not frame_packet:
            raise ValueError("native MC2 CPU step frame is not the published frame packet")
        if distance_slice:
            self._module.mc2_domain_cpu_v1_step_distance(key)
        else:
            self._module.mc2_domain_cpu_v1_step(key)

    def step_distance(self, handle) -> None:
        key = self._require_handle(handle)
        self._module.mc2_domain_cpu_v1_step_distance(key)

    def step_inertia(self, handle, settings: Mapping[str, object]) -> None:
        key = self._require_handle(handle)
        required = {
            "old_world_position", "step_vector", "step_rotation",
            "inertia_vector", "inertia_rotation", "depth_inertia",
        }
        if set(settings) != required:
            raise ValueError("inertia slice requires exactly its explicit frame inputs")
        arrays = {
            name: np.ascontiguousarray(settings[name], dtype=np.float32)
            for name in required - {"depth_inertia"}
        }
        for name, expected in (
            ("old_world_position", 3), ("step_vector", 3), ("step_rotation", 4),
            ("inertia_vector", 3), ("inertia_rotation", 4),
        ):
            if arrays[name].shape != (expected,):
                raise ValueError(f"{name} must be a flat vector of length {expected}")
            arrays[name].flags.writeable = False
        self._module.mc2_domain_cpu_v1_step_inertia(
            key,
            arrays["old_world_position"],
            arrays["step_vector"],
            arrays["step_rotation"],
            arrays["inertia_vector"],
            arrays["inertia_rotation"],
            float(settings["depth_inertia"]),
        )

    def step_integration(self, handle, settings: Mapping[str, object]) -> None:
        key = self._require_handle(handle)
        required = {"dt", "simulation_power", "velocity_weight", "gravity"}
        if set(settings) != required:
            raise ValueError("integration slice requires exactly its explicit step inputs")
        gravity = np.ascontiguousarray(settings["gravity"], dtype=np.float32)
        if gravity.shape != (3,):
            raise ValueError("gravity must be a flat vector of length 3")
        gravity.flags.writeable = False
        self._module.mc2_domain_cpu_v1_step_integration(
            key,
            float(settings["dt"]),
            float(settings["simulation_power"]),
            float(settings["velocity_weight"]),
            gravity,
        )

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
            "distance_slice_ready": True,
            "inertia_slice_ready": True,
            "integration_slice_ready": True,
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
            self._parameters.pop(key, None)
            self._frames.pop(key, None)

    def _require_handle(self, handle) -> int:
        key = int(handle or 0)
        if key <= 0 or key not in self._programs:
            raise RuntimeError("native MC2 CPU domain handle is not owned by this kernel")
        return key

    def _configure_distance(
        self,
        handle: int,
        program: MC2CompiledDomainProgramV1,
        parameters: MC2DomainParameterPacketV1,
    ) -> None:
        distance_table = next(
            (table for table in program.constraint_tables if table.kind == "distance"),
            None,
        )
        if distance_table is None:
            return
        parameter_table = next(
            (table for table in parameters.constraint_parameters if table.name == "distance"),
            None,
        )
        if parameter_table is None:
            raise ValueError("distance topology has no distance parameter table")
        fields = {name: index for index, name in enumerate(parameter_table.fields)}
        if "rest_length" not in fields or "stiffness" not in fields:
            raise ValueError("distance parameter table lacks rest_length/stiffness")
        rows = [[] for _ in range(program.particle_count)]
        for row in distance_table.indices:
            vertex, neighbor = (int(row[0]), int(row[1]))
            rows[vertex].append(neighbor)
        starts = []
        counts = []
        neighbors = []
        for values in rows:
            starts.append(len(neighbors))
            counts.append(len(values))
            neighbors.extend(values)
        rest = parameter_table.values[:, fields["rest_length"]]
        stiffness = parameter_table.values[:, fields["stiffness"]]
        starts_array = np.asarray(starts, dtype=np.int32)
        counts_array = np.asarray(counts, dtype=np.int32)
        neighbors_array = np.asarray(neighbors, dtype=np.int32)
        rest_array = np.asarray(rest, dtype=np.float32)
        stiffness_array = np.asarray(stiffness, dtype=np.float32)
        for array in (
            starts_array, counts_array, neighbors_array, rest_array, stiffness_array
        ):
            array.flags.writeable = False
        self._module.mc2_domain_cpu_v1_configure_distance(
            handle,
            starts_array,
            counts_array,
            neighbors_array,
            rest_array,
            stiffness_array,
        )

    def _configure_inertia(
        self,
        handle: int,
        program: MC2CompiledDomainProgramV1,
        parameters: MC2DomainParameterPacketV1,
    ) -> None:
        table = parameters.particle_parameters
        fields = {name: index for index, name in enumerate(table.fields)}
        if "depth" not in fields:
            raise ValueError("particle parameter table lacks depth")
        depths = np.asarray(table.values[:, fields["depth"]], dtype=np.float32)
        fixed = (np.asarray(program.particle_attribute_flags, dtype=np.uint32) & 1) != 0
        inv_masses = np.where(fixed, 0.0, 1.0).astype(np.float32)
        depths.flags.writeable = False
        inv_masses.flags.writeable = False
        self._module.mc2_domain_cpu_v1_configure_inertia(handle, depths, inv_masses)

    def _configure_integration(
        self,
        handle: int,
        parameters: MC2DomainParameterPacketV1,
    ) -> None:
        table = parameters.particle_parameters
        fields = {name: index for index, name in enumerate(table.fields)}
        if "damping" not in fields:
            raise ValueError("particle parameter table lacks damping")
        damping = np.asarray(table.values[:, fields["damping"]], dtype=np.float32)
        damping.flags.writeable = False
        self._module.mc2_domain_cpu_v1_configure_integration(handle, damping)


__all__ = ["MC2NativeCPUKernelV1"]
