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
    "mc2_domain_cpu_v1_configure_tether",
    "mc2_domain_cpu_v1_step_tether",
    "mc2_domain_cpu_v1_configure_inertia",
    "mc2_domain_cpu_v1_step_inertia",
    "mc2_domain_cpu_v1_configure_center",
    "mc2_domain_cpu_v1_step_center",
    "mc2_domain_cpu_v1_configure_center_frame_shift",
    "mc2_domain_cpu_v1_step_center_frame_shift",
    "mc2_domain_cpu_v1_configure_integration",
    "mc2_domain_cpu_v1_step_integration",
    "mc2_domain_cpu_v1_read",
    "mc2_domain_cpu_v1_inspect",
    "mc2_domain_cpu_v1_dispose",
    "mc2_center_frame_shift_v1_evaluate",
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
            program.partition_count,
            program.domain_signature,
            program.layout_signature,
            program.particle_bind_position,
            program.particle_bind_rotation,
            program.particle_partition_index,
            program.particle_attribute_flags,
            program.partition_center_local_position,
            program.partition_initial_local_gravity_direction,
        ))
        if handle <= 0:
            raise RuntimeError("native CPU domain returned an invalid handle")
        try:
            self._configure_distance(handle, program, parameters)
            self._configure_tether(handle, program)
            self._configure_inertia(handle, program, parameters)
            self._configure_center(handle, parameters)
            self._configure_center_frame_shift(handle, parameters)
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
            frame_packet.animated_base_world_rotations,
            frame_packet.animated_base_world_normals,
            frame_packet.partition_world_position,
            frame_packet.partition_world_rotation,
            frame_packet.partition_world_scale,
            frame_packet.partition_world_linear,
            frame_packet.anchor_world_position,
            frame_packet.anchor_world_rotation,
            frame_packet.anchor_present,
            frame_packet.partition_frame_flags,
            frame_packet.velocity_weight,
            frame_packet.gravity_ratio,
            frame_packet.frame_delta_time,
            frame_packet.simulation_delta_time,
            frame_packet.time_scale,
            frame_packet.skip_count,
            frame_packet.is_running,
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
        tether_slice = settings.pop("tether_slice", False) is True
        data_path_only = settings.pop("data_path_only", False) is True
        if not data_path_only:
            raise RuntimeError(
                "native MC2 CPU numerical kernel is not ready; "
                "only data_path_only=True is accepted"
            )
        if collider_snapshot is not None:
            raise RuntimeError("native MC2 CPU data-path slice does not consume colliders")
        if self._frames.get(key) is not frame_packet:
            raise ValueError("native MC2 CPU step frame is not the published frame packet")
        if distance_slice and tether_slice:
            raise ValueError("distance_slice and tether_slice are mutually exclusive")
        if tether_slice:
            self.step_tether(key, settings)
        elif distance_slice:
            if settings:
                raise ValueError("distance_slice does not accept additional inputs")
            self._module.mc2_domain_cpu_v1_step_distance(key)
        else:
            if settings:
                raise ValueError("data_path_only step does not accept additional inputs")
            self._module.mc2_domain_cpu_v1_step(key)

    def step_distance(self, handle) -> None:
        key = self._require_handle(handle)
        self._module.mc2_domain_cpu_v1_step_distance(key)

    def step_tether(self, handle, settings: Mapping[str, object]) -> None:
        key = self._require_handle(handle)
        required = {"step_basic_positions", "compression", "stretch"}
        if set(settings) != required:
            raise ValueError("tether slice requires exactly its explicit step inputs")
        positions = np.ascontiguousarray(settings["step_basic_positions"], dtype=np.float32)
        program = self._programs[key]
        if positions.shape != (program.particle_count, 3):
            raise ValueError("step_basic_positions must match particle_count x 3")
        positions.flags.writeable = False
        self._module.mc2_domain_cpu_v1_step_tether(
            key, positions, float(settings["compression"]), float(settings["stretch"])
        )

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

    def step_center(self, handle, settings: Mapping[str, object]) -> None:
        key = self._require_handle(handle)
        required = {"dt", "frame_interpolation", "distance_weights"}
        if set(settings) != required:
            raise ValueError("Center slice requires exactly dt/frame_interpolation/distance_weights")
        weights = np.ascontiguousarray(settings["distance_weights"], dtype=np.float32)
        program = self._programs[key]
        if weights.shape != (program.partition_count,):
            raise ValueError("distance_weights must match partition_count")
        weights.flags.writeable = False
        self._module.mc2_domain_cpu_v1_step_center(
            key, float(settings["dt"]), float(settings["frame_interpolation"]), weights
        )

    def step_center_frame_shift(self, handle, anchor_component_local_positions) -> None:
        key = self._require_handle(handle)
        values = np.ascontiguousarray(anchor_component_local_positions, dtype=np.float32)
        program = self._programs[key]
        if values.shape != (program.partition_count, 3):
            raise ValueError("anchor_component_local_positions must match partition_count x 3")
        values.flags.writeable = False
        self._module.mc2_domain_cpu_v1_step_center_frame_shift(key, values)

    def step_reference_slices(self, handle, settings: Mapping[str, object]) -> None:
        """Run the currently landed native reference pass prefix in fixed order."""
        required = {
            "anchor_component_local_positions", "dt", "frame_interpolation",
            "distance_weights", "simulation_power", "velocity_weight", "gravity",
        }
        program = self._programs[self._require_handle(handle)]
        has_tether = any(table.kind == "tether" for table in program.constraint_tables)
        if has_tether:
            required.update({"step_basic_positions", "tether_compression", "tether_stretch"})
        if set(settings) != required:
            raise ValueError("reference slices require exactly their explicit pass inputs")
        key = self._require_handle(handle)
        self.step_center_frame_shift(key, settings["anchor_component_local_positions"])
        self.step_center(key, {
            "dt": settings["dt"],
            "frame_interpolation": settings["frame_interpolation"],
            "distance_weights": settings["distance_weights"],
        })
        self.step_integration(key, {
            "dt": settings["dt"],
            "simulation_power": settings["simulation_power"],
            "velocity_weight": settings["velocity_weight"],
            "gravity": settings["gravity"],
        })
        if has_tether:
            self.step_tether(key, {
                "step_basic_positions": settings["step_basic_positions"],
                "compression": settings["tether_compression"],
                "stretch": settings["tether_stretch"],
            })
        self.step_distance(key)

    def evaluate_center_frame_shift(self, settings: Mapping[str, object]) -> dict:
        """Run the explicit native Center frame-shift slice only."""
        key_set = {
            "old_component_position", "component_position",
            "old_component_rotation", "component_rotation", "component_scale",
            "initial_scale", "frame_world_position", "frame_world_rotation",
            "old_frame_world_position", "old_frame_world_rotation",
            "now_world_position", "now_world_rotation", "old_anchor_position",
            "old_anchor_rotation", "anchor_position", "anchor_rotation",
            "anchor_component_local_position", "smoothing_velocity", "use_anchor",
            "is_running", "anchor_inertia", "world_inertia", "movement_speed_limit",
            "rotation_speed_limit", "movement_inertia_smoothing", "frame_delta_time",
            "simulation_delta_time", "time_scale", "skip_count", "velocity_weight",
            "teleport_mode", "teleport_distance", "teleport_rotation",
        }
        if set(settings) != key_set:
            raise ValueError("Center frame-shift slice requires exactly its explicit inputs")
        arrays = {}
        for name, width in (
            ("old_component_position", 3), ("component_position", 3),
            ("old_component_rotation", 4), ("component_rotation", 4),
            ("component_scale", 3), ("initial_scale", 3),
            ("frame_world_position", 3), ("frame_world_rotation", 4),
            ("old_frame_world_position", 3), ("old_frame_world_rotation", 4),
            ("now_world_position", 3), ("now_world_rotation", 4),
            ("old_anchor_position", 3), ("old_anchor_rotation", 4),
            ("anchor_position", 3), ("anchor_rotation", 4),
            ("anchor_component_local_position", 3), ("smoothing_velocity", 3),
        ):
            array = np.ascontiguousarray(settings[name], dtype=np.float32)
            if array.shape != (width,):
                raise ValueError(f"{name} must be a flat vector of length {width}")
            array.flags.writeable = False
            arrays[name] = array
        return dict(self._module.mc2_center_frame_shift_v1_evaluate(
            *(arrays[name] for name in (
                "old_component_position", "component_position",
                "old_component_rotation", "component_rotation", "component_scale",
                "initial_scale", "frame_world_position", "frame_world_rotation",
                "old_frame_world_position", "old_frame_world_rotation",
                "now_world_position", "now_world_rotation", "old_anchor_position",
                "old_anchor_rotation", "anchor_position", "anchor_rotation",
                "anchor_component_local_position", "smoothing_velocity",
            )),
            bool(settings["use_anchor"]), bool(settings["is_running"]),
            float(settings["anchor_inertia"]), float(settings["world_inertia"]),
            float(settings["movement_speed_limit"]), float(settings["rotation_speed_limit"]),
            float(settings["movement_inertia_smoothing"]), float(settings["frame_delta_time"]),
            float(settings["simulation_delta_time"]), float(settings["time_scale"]),
            int(settings["skip_count"]), float(settings["velocity_weight"]),
            int(settings["teleport_mode"]), float(settings["teleport_distance"]),
            float(settings["teleport_rotation"]),
        ))

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
            world_rotations_xyzw=raw["world_rotations_xyzw"],
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
            "tether_slice_ready": any(
                table.kind == "tether" for table in self._programs[key].constraint_tables
            ),
            "inertia_slice_ready": True,
            "integration_slice_ready": True,
            "center_slice_ready": True,
            "center_frame_shift_slice_ready": True,
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

    def _configure_tether(
        self,
        handle: int,
        program: MC2CompiledDomainProgramV1,
    ) -> None:
        tether_table = next(
            (table for table in program.constraint_tables if table.kind == "tether"),
            None,
        )
        if tether_table is None:
            return
        roots = np.full(program.particle_count, -1, dtype=np.int32)
        for row in tether_table.indices:
            vertex, root = int(row[0]), int(row[1])
            if roots[vertex] != -1 and int(roots[vertex]) != root:
                raise ValueError("tether topology assigns multiple roots to one vertex")
            roots[vertex] = root
        roots.flags.writeable = False
        self._module.mc2_domain_cpu_v1_configure_tether(handle, roots)

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

    def _configure_center(
        self,
        handle: int,
        parameters: MC2DomainParameterPacketV1,
    ) -> None:
        table = parameters.partition_parameters
        fields = {name: index for index, name in enumerate(table.fields)}
        required = {
            "local_inertia", "local_movement_speed_limit", "local_rotation_speed_limit",
            "gravity", "gravity_direction_x", "gravity_direction_y", "gravity_direction_z",
            "gravity_falloff", "stabilization_time_after_reset", "blend_weight",
        }
        missing = required - set(fields)
        if missing:
            raise ValueError("partition parameter table lacks Center fields: " + ", ".join(sorted(missing)))
        values = table.values
        scalar = {
            name: np.asarray(values[:, fields[name]], dtype=np.float32)
            for name in (
                "local_inertia", "local_movement_speed_limit", "local_rotation_speed_limit",
                "gravity", "gravity_falloff", "stabilization_time_after_reset", "blend_weight",
            )
        }
        directions = np.column_stack((
            values[:, fields["gravity_direction_x"]],
            values[:, fields["gravity_direction_y"]],
            values[:, fields["gravity_direction_z"]],
        )).astype(np.float32, copy=False)
        arrays = tuple(scalar.values()) + (directions,)
        for array in arrays:
            array.flags.writeable = False
        self._module.mc2_domain_cpu_v1_configure_center(
            handle,
            scalar["local_inertia"],
            scalar["local_movement_speed_limit"],
            scalar["local_rotation_speed_limit"],
            scalar["gravity"],
            directions,
            scalar["gravity_falloff"],
            scalar["stabilization_time_after_reset"],
            scalar["blend_weight"],
        )

    def _configure_center_frame_shift(
        self,
        handle: int,
        parameters: MC2DomainParameterPacketV1,
    ) -> None:
        table = parameters.partition_parameters
        fields = {name: index for index, name in enumerate(table.fields)}
        required_float = {
            "anchor_inertia", "world_inertia", "movement_inertia_smoothing",
            "movement_speed_limit", "rotation_speed_limit", "teleport_distance",
            "teleport_rotation",
        }
        missing = required_float - set(fields)
        uint_table = parameters.partition_uint_parameters
        uint_fields = {name: index for index, name in enumerate(uint_table.fields)}
        if "teleport_mode" not in uint_fields:
            missing.add("teleport_mode")
        if missing:
            raise ValueError(
                "partition parameter table lacks Center frame-shift fields: "
                + ", ".join(sorted(missing))
            )
        values = table.values
        arrays = {
            name: np.asarray(values[:, fields[name]], dtype=np.float32)
            for name in required_float
        }
        teleport_modes = np.asarray(
            uint_table.values[:, uint_fields["teleport_mode"]], dtype=np.int32
        )
        for array in (*arrays.values(), teleport_modes):
            array.flags.writeable = False
        self._module.mc2_domain_cpu_v1_configure_center_frame_shift(
            handle,
            arrays["anchor_inertia"],
            arrays["world_inertia"],
            arrays["movement_inertia_smoothing"],
            arrays["movement_speed_limit"],
            arrays["rotation_speed_limit"],
            teleport_modes,
            arrays["teleport_distance"],
            arrays["teleport_rotation"],
        )


__all__ = ["MC2NativeCPUKernelV1"]
