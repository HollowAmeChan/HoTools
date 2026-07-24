"""Native E3 data-path kernel for ``MC2CPUBackendDomainV1``.

The default product step remains unavailable.  Explicit data-path, Distance,
and Center inertia slices are opt-in so they cannot be mistaken for the
product solver.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from .domain_ir import MC2CompiledDomainProgramV1
from .domain_ir import MC2DomainFramePacketV1
from .domain_ir import MC2DomainParameterPacketV1
from .domain_ir import make_mc2_domain_frame_output
from .collider_frame import MC2DomainColliderFrameSpec
from .native import native_module


_NATIVE_SYMBOLS = (
    "mc2_domain_cpu_v1_create",
    "mc2_domain_cpu_v1_create_parameter_staging",
    "mc2_domain_cpu_v1_swap_parameter_staging",
    "mc2_domain_cpu_v1_update_frame",
    "mc2_domain_cpu_v1_step",
    "mc2_domain_cpu_v1_configure_distance",
    "mc2_domain_cpu_v1_step_distance",
    "mc2_domain_cpu_v1_configure_baseline",
    "mc2_domain_cpu_v1_configure_baseline_pose",
    "mc2_domain_cpu_v1_prepare_step_basic_pose",
    "mc2_domain_cpu_v1_prepare_step_basic_pose_partitioned",
    "mc2_domain_cpu_v1_step_angle",
    "mc2_domain_cpu_v1_step_angle_partitioned",
    "mc2_domain_cpu_v1_step_motion",
    "mc2_domain_cpu_v1_step_motion_partitioned",
    "mc2_domain_cpu_v1_step_external_collision",
    "mc2_domain_cpu_v1_step_self_collision",
    "mc2_domain_cpu_v1_configure_whole_domain_self",
    "mc2_domain_cpu_v1_step_whole_domain_self",
    "mc2_domain_cpu_v1_step_whole_domain_self_owned",
    "mc2_domain_cpu_v1_configure_compiled_external_collision",
    "mc2_domain_cpu_v1_step_compiled_external_collision",
    "mc2_domain_cpu_v1_step_external_edge_collision",
    "mc2_domain_cpu_v1_configure_tether",
    "mc2_domain_cpu_v1_step_tether",
    "mc2_domain_cpu_v1_step_tether_partitioned",
    "mc2_domain_cpu_v1_configure_bending",
    "mc2_domain_cpu_v1_step_bending",
    "mc2_domain_cpu_v1_configure_inertia",
    "mc2_domain_cpu_v1_configure_constraint_friction",
    "mc2_domain_cpu_v1_step_inertia",
    "mc2_domain_cpu_v1_configure_center",
    "mc2_domain_cpu_v1_step_center",
    "mc2_domain_cpu_v1_step_center_inertia",
    "mc2_domain_cpu_v1_configure_center_frame_shift",
    "mc2_domain_cpu_v1_step_task_reference_teleport",
    "mc2_domain_cpu_v1_step_center_frame_shift",
    "mc2_domain_cpu_v1_configure_integration",
    "mc2_domain_cpu_v1_step_integration",
    "mc2_domain_cpu_v1_step_integration_partitioned",
    "mc2_domain_cpu_v1_step_post",
    "mc2_domain_cpu_v1_step_post_owned",
    "mc2_domain_cpu_v1_step_post_owned_partitioned",
    "mc2_domain_cpu_v1_read",
    "mc2_domain_cpu_v1_read_dynamics_debug",
    "mc2_domain_cpu_v1_begin_constraint_debug",
    "mc2_domain_cpu_v1_end_constraint_debug",
    "mc2_domain_cpu_v1_read_constraint_debug",
    "mc2_domain_cpu_v1_clear_constraint_debug",
    "mc2_domain_cpu_v1_read_center_debug",
    "mc2_domain_cpu_v1_read_task_reference_teleport",
    "mc2_domain_cpu_v1_inspect",
    "mc2_domain_cpu_v1_dispose",
    "mc2_center_frame_shift_v1_evaluate",
)


@dataclass
class _MC2NativeParameterUpdateV1:
    owner_handle: int
    staging_handle: int
    old_program: MC2CompiledDomainProgramV1
    old_parameters: MC2DomainParameterPacketV1
    new_program: MC2CompiledDomainProgramV1
    new_parameters: MC2DomainParameterPacketV1
    applied: bool = False
    closed: bool = False


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
            self._configure_domain(handle, program, parameters)
        except Exception:
            self._module.mc2_domain_cpu_v1_dispose(handle)
            raise
        self._programs[handle] = program
        self._parameters[handle] = parameters
        return handle

    def stage_parameter_update(
        self,
        handle,
        program: MC2CompiledDomainProgramV1,
        parameters: MC2DomainParameterPacketV1,
    ) -> _MC2NativeParameterUpdateV1:
        key = self._require_handle(handle)
        if not isinstance(program, MC2CompiledDomainProgramV1):
            raise TypeError("program must be MC2CompiledDomainProgramV1")
        if not isinstance(parameters, MC2DomainParameterPacketV1):
            raise TypeError("parameters must be MC2DomainParameterPacketV1")
        old_program = self._programs[key]
        if (
            program.domain_signature != old_program.domain_signature
            or program.layout_signature != old_program.layout_signature
            or program.particle_count != old_program.particle_count
            or program.partition_count != old_program.partition_count
        ):
            raise ValueError("parameter update must preserve native domain identity")
        if parameters.layout_signature != program.layout_signature:
            raise ValueError("native CPU parameter layout does not match program")
        staging = int(self._module.mc2_domain_cpu_v1_create_parameter_staging(key))
        if staging <= 0:
            raise RuntimeError("native CPU parameter staging returned an invalid handle")
        try:
            self._configure_domain(staging, program, parameters)
        except Exception:
            self._module.mc2_domain_cpu_v1_dispose(staging)
            raise
        return _MC2NativeParameterUpdateV1(
            owner_handle=key,
            staging_handle=staging,
            old_program=old_program,
            old_parameters=self._parameters[key],
            new_program=program,
            new_parameters=parameters,
        )

    def apply_parameter_update(self, handle, update) -> None:
        key, update = self._require_parameter_update(handle, update)
        if update.applied:
            raise RuntimeError("native CPU parameter update is already applied")
        self._module.mc2_domain_cpu_v1_swap_parameter_staging(
            key, update.staging_handle
        )
        self._programs[key] = update.new_program
        self._parameters[key] = update.new_parameters
        update.applied = True

    def rollback_parameter_update(self, handle, update) -> None:
        key, update = self._require_parameter_update(handle, update)
        if not update.applied:
            raise RuntimeError("native CPU parameter update is not applied")
        self._module.mc2_domain_cpu_v1_swap_parameter_staging(
            key, update.staging_handle
        )
        self._programs[key] = update.old_program
        self._parameters[key] = update.old_parameters
        update.applied = False

    def finish_parameter_update(self, handle, update) -> None:
        _key, update = self._require_parameter_update(handle, update)
        if not update.applied:
            raise RuntimeError("native CPU parameter update must be applied before finish")
        self._module.mc2_domain_cpu_v1_dispose(update.staging_handle)
        update.closed = True

    def discard_parameter_update(self, update) -> None:
        if not isinstance(update, _MC2NativeParameterUpdateV1):
            raise TypeError("update must be a native CPU parameter update")
        if update.closed:
            return
        if update.applied:
            raise RuntimeError("cannot discard an applied native CPU parameter update")
        self._module.mc2_domain_cpu_v1_dispose(update.staging_handle)
        update.closed = True

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
        if collider_snapshot is not None:
            raise RuntimeError("native MC2 CPU base pass does not consume colliders")
        if self._frames.get(key) is not frame_packet:
            raise ValueError("native MC2 CPU step frame is not the published frame packet")
        if settings:
            raise ValueError("native MC2 CPU base step does not accept settings")
        self._module.mc2_domain_cpu_v1_step(key)

    def step_distance(
        self, handle, simulation_power: float = 1.0, debug_phase: int = -1
    ) -> None:
        key = self._require_handle(handle)
        self._module.mc2_domain_cpu_v1_step_distance(
            key, float(simulation_power), int(debug_phase)
        )

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

    def step_tether_partitioned(self, handle, settings: Mapping[str, object]) -> None:
        key = self._require_handle(handle)
        required = {"step_basic_positions", "compression_values", "stretch_values"}
        if set(settings) != required:
            raise ValueError("partitioned tether requires exactly its particle inputs")
        program = self._programs[key]
        positions = np.ascontiguousarray(settings["step_basic_positions"], dtype=np.float32)
        compression = np.ascontiguousarray(settings["compression_values"], dtype=np.float32)
        stretch = np.ascontiguousarray(settings["stretch_values"], dtype=np.float32)
        if positions.shape != (program.particle_count, 3):
            raise ValueError("step_basic_positions must match particle_count x 3")
        if compression.shape != (program.particle_count,) or stretch.shape != (program.particle_count,):
            raise ValueError("partitioned tether limits must match particle_count")
        for array in (positions, compression, stretch):
            array.flags.writeable = False
        self._module.mc2_domain_cpu_v1_step_tether_partitioned(
            key, positions, compression, stretch
        )

    def step_bending(self, handle, simulation_power: float = 1.0) -> None:
        key = self._require_handle(handle)
        self._module.mc2_domain_cpu_v1_step_bending(key, float(simulation_power))

    def step_angle(self, handle, settings: Mapping[str, object]) -> None:
        key = self._require_handle(handle)
        required = {
            "step_basic_positions", "step_basic_rotations", "restoration_values",
            "limit_values", "restoration_velocity_attenuation",
            "restoration_gravity_falloff", "limit_stiffness",
            "restoration_enabled", "limit_enabled",
        }
        if set(settings) != required:
            raise ValueError("angle slice requires exactly its explicit step inputs")
        program = self._programs[key]
        arrays = {}
        for name, width in (
            ("step_basic_positions", 3), ("step_basic_rotations", 4),
        ):
            array = np.ascontiguousarray(settings[name], dtype=np.float32)
            if array.shape != (program.particle_count, width):
                raise ValueError(f"{name} must match particle_count x {width}")
            array.flags.writeable = False
            arrays[name] = array
        for name in ("restoration_values", "limit_values"):
            array = np.ascontiguousarray(settings[name], dtype=np.float32)
            if array.shape != (program.particle_count,):
                raise ValueError(f"{name} must match particle_count")
            array.flags.writeable = False
            arrays[name] = array
        self._module.mc2_domain_cpu_v1_step_angle(
            key, arrays["step_basic_positions"], arrays["step_basic_rotations"],
            arrays["restoration_values"], arrays["limit_values"],
            float(settings["restoration_velocity_attenuation"]),
            float(settings["restoration_gravity_falloff"]),
            float(settings["limit_stiffness"]), bool(settings["restoration_enabled"]),
            bool(settings["limit_enabled"]),
        )

    def step_angle_partitioned(self, handle, settings: Mapping[str, object]) -> None:
        key = self._require_handle(handle)
        required = {
            "step_basic_positions", "step_basic_rotations", "restoration_values",
            "limit_values", "restoration_velocity_attenuation_values",
            "restoration_gravity_falloff_values", "limit_stiffness_values",
            "restoration_enabled_values", "limit_enabled_values",
        }
        if set(settings) != required:
            raise ValueError("partitioned angle requires exactly its particle inputs")
        program = self._programs[key]
        arrays = {}
        for name, dtype, shape in (
            ("step_basic_positions", np.float32, (program.particle_count, 3)),
            ("step_basic_rotations", np.float32, (program.particle_count, 4)),
            ("restoration_values", np.float32, (program.particle_count,)),
            ("limit_values", np.float32, (program.particle_count,)),
            ("restoration_velocity_attenuation_values", np.float32, (program.particle_count,)),
            ("restoration_gravity_falloff_values", np.float32, (program.particle_count,)),
            ("limit_stiffness_values", np.float32, (program.particle_count,)),
            ("restoration_enabled_values", np.uint32, (program.particle_count,)),
            ("limit_enabled_values", np.uint32, (program.particle_count,)),
        ):
            array = np.ascontiguousarray(settings[name], dtype=dtype)
            if array.shape != shape:
                raise ValueError(f"{name} must have shape {shape}")
            array.flags.writeable = False
            arrays[name] = array
        self._module.mc2_domain_cpu_v1_step_angle_partitioned(
            key, *(arrays[name] for name in (
                "step_basic_positions", "step_basic_rotations", "restoration_values",
                "limit_values", "restoration_velocity_attenuation_values",
                "restoration_gravity_falloff_values", "limit_stiffness_values",
                "restoration_enabled_values", "limit_enabled_values",
            ))
        )

    def step_motion(self, handle, settings: Mapping[str, object]) -> None:
        key = self._require_handle(handle)
        required = {
            "base_positions", "base_rotations", "max_distances", "stiffness_values",
            "backstop_radii", "backstop_distances", "normal_axis",
            "max_distance_enabled", "backstop_enabled",
        }
        if set(settings) != required:
            raise ValueError("motion slice requires exactly its explicit step inputs")
        program = self._programs[key]
        arrays = {}
        for name, width in (("base_positions", 3), ("base_rotations", 4)):
            array = np.ascontiguousarray(settings[name], dtype=np.float32)
            if array.shape != (program.particle_count, width):
                raise ValueError(f"{name} must match particle_count x {width}")
            array.flags.writeable = False
            arrays[name] = array
        for name in ("max_distances", "stiffness_values", "backstop_radii", "backstop_distances"):
            array = np.ascontiguousarray(settings[name], dtype=np.float32)
            if array.shape != (program.particle_count,):
                raise ValueError(f"{name} must match particle_count")
            array.flags.writeable = False
            arrays[name] = array
        self._module.mc2_domain_cpu_v1_step_motion(
            key, arrays["base_positions"], arrays["base_rotations"],
            arrays["max_distances"], arrays["stiffness_values"],
            arrays["backstop_radii"], arrays["backstop_distances"],
            int(settings["normal_axis"]), bool(settings["max_distance_enabled"]),
            bool(settings["backstop_enabled"]),
        )

    def step_motion_partitioned(self, handle, settings: Mapping[str, object]) -> None:
        key = self._require_handle(handle)
        required = {
            "base_positions", "base_rotations", "max_distances", "stiffness_values",
            "backstop_radii", "backstop_distances", "normal_axis_values",
            "max_distance_enabled_values", "backstop_enabled_values",
        }
        if set(settings) != required:
            raise ValueError("partitioned motion requires exactly its particle inputs")
        program = self._programs[key]
        arrays = {}
        for name, dtype, shape in (
            ("base_positions", np.float32, (program.particle_count, 3)),
            ("base_rotations", np.float32, (program.particle_count, 4)),
            ("max_distances", np.float32, (program.particle_count,)),
            ("stiffness_values", np.float32, (program.particle_count,)),
            ("backstop_radii", np.float32, (program.particle_count,)),
            ("backstop_distances", np.float32, (program.particle_count,)),
            ("normal_axis_values", np.int32, (program.particle_count,)),
            ("max_distance_enabled_values", np.uint32, (program.particle_count,)),
            ("backstop_enabled_values", np.uint32, (program.particle_count,)),
        ):
            array = np.ascontiguousarray(settings[name], dtype=dtype)
            if array.shape != shape:
                raise ValueError(f"{name} must have shape {shape}")
            array.flags.writeable = False
            arrays[name] = array
        self._module.mc2_domain_cpu_v1_step_motion_partitioned(
            key, *(arrays[name] for name in (
                "base_positions", "base_rotations", "max_distances", "stiffness_values",
                "backstop_radii", "backstop_distances", "normal_axis_values",
                "max_distance_enabled_values", "backstop_enabled_values",
            ))
        )

    def step_post(self, handle, settings: Mapping[str, object]) -> None:
        key = self._require_handle(handle)
        required = {
            "old_positions", "dt", "dynamic_friction", "static_friction_speed",
            "particle_speed_limit", "velocity_weight",
        }
        if set(settings) != required:
            raise ValueError("post slice requires exactly its explicit inputs")
        program = self._programs[key]
        old_positions = np.ascontiguousarray(settings["old_positions"], dtype=np.float32)
        if old_positions.shape != (program.particle_count, 3):
            raise ValueError("post old_positions must match particle_count x 3")
        old_positions.flags.writeable = False
        self._module.mc2_domain_cpu_v1_step_post(
            key,
            old_positions,
            float(settings["dt"]),
            float(settings["dynamic_friction"]),
            float(settings["static_friction_speed"]),
            float(settings["particle_speed_limit"]),
            float(settings["velocity_weight"]),
        )

    def step_post_owned(self, handle, settings: Mapping[str, object]) -> None:
        """Commit post/history from the native-owned substep snapshot."""
        key = self._require_handle(handle)
        required = {
            "dt", "dynamic_friction", "static_friction_speed",
            "particle_speed_limit", "velocity_weight",
        }
        if set(settings) != required:
            raise ValueError("owned post slice requires exactly its scalar inputs")
        self._module.mc2_domain_cpu_v1_step_post_owned(
            key,
            float(settings["dt"]),
            float(settings["dynamic_friction"]),
            float(settings["static_friction_speed"]),
            float(settings["particle_speed_limit"]),
            float(settings["velocity_weight"]),
        )

    def step_post_owned_partitioned(self, handle, settings: Mapping[str, object]) -> None:
        key = self._require_handle(handle)
        required = {
            "dt", "dynamic_friction_values", "static_friction_speed_values",
            "particle_speed_limit_values",
        }
        if set(settings) != required:
            raise ValueError("partitioned owned post requires exactly its particle inputs")
        program = self._programs[key]
        arrays = []
        for name in (
            "dynamic_friction_values", "static_friction_speed_values",
            "particle_speed_limit_values",
        ):
            array = np.ascontiguousarray(settings[name], dtype=np.float32)
            if array.shape != (program.particle_count,):
                raise ValueError(f"{name} must match particle_count")
            array.flags.writeable = False
            arrays.append(array)
        self._module.mc2_domain_cpu_v1_step_post_owned_partitioned(
            key, float(settings["dt"]), *arrays
        )

    def step_integration_partitioned(self, handle, settings: Mapping[str, object]) -> None:
        key = self._require_handle(handle)
        required = {"dt", "simulation_power"}
        if set(settings) != required:
            raise ValueError("partitioned integration requires exactly dt/simulation_power")
        self._module.mc2_domain_cpu_v1_step_integration_partitioned(
            key, float(settings["dt"]), float(settings["simulation_power"])
        )

    def step_external_collision(self, handle, settings: Mapping[str, object]) -> None:
        key = self._require_handle(handle)
        required = {
            "base_positions", "collision_radii", "friction", "collided_by_groups",
            "collider_types", "collider_group_bits", "collider_centers",
            "collider_segment_a", "collider_segment_b", "collider_old_centers",
            "collider_old_segment_a", "collider_old_segment_b", "collider_radii",
        }
        if set(settings) != required:
            raise ValueError("external collision slice requires exactly its explicit inputs")
        program = self._programs[key]
        arrays = {}
        for name in ("base_positions", "collider_centers", "collider_segment_a", "collider_segment_b",
                     "collider_old_centers", "collider_old_segment_a", "collider_old_segment_b"):
            array = np.ascontiguousarray(settings[name], dtype=np.float32)
            expected = (program.particle_count, 3) if name == "base_positions" else (len(settings["collider_types"]), 3)
            if array.shape != expected:
                raise ValueError(f"{name} has invalid shape")
            array.flags.writeable = False
            arrays[name] = array
        for name in ("collision_radii", "friction"):
            array = np.ascontiguousarray(settings[name], dtype=np.float32)
            if array.shape != (program.particle_count,):
                raise ValueError(f"{name} must match particle_count")
            array.flags.writeable = False
            arrays[name] = array
        for name in ("collider_types", "collider_group_bits"):
            array = np.ascontiguousarray(settings[name], dtype=np.int32)
            array.flags.writeable = False
            arrays[name] = array
        collider_radii = np.ascontiguousarray(settings["collider_radii"], dtype=np.float32)
        if collider_radii.shape != arrays["collider_types"].shape:
            raise ValueError("collider_radii must match collider count")
        collider_radii.flags.writeable = False
        arrays["collider_radii"] = collider_radii
        self._module.mc2_domain_cpu_v1_step_external_collision(
            key, arrays["base_positions"], arrays["collision_radii"], arrays["friction"],
            int(settings["collided_by_groups"]), arrays["collider_types"],
            arrays["collider_group_bits"], arrays["collider_centers"],
            arrays["collider_segment_a"], arrays["collider_segment_b"],
            arrays["collider_old_centers"], arrays["collider_old_segment_a"],
            arrays["collider_old_segment_b"], arrays["collider_radii"],
        )

    def step_self_collision(self, handle, settings: Mapping[str, object]) -> None:
        key = self._require_handle(handle)
        required = {"old_positions", "edges", "triangles", "friction", "surface_thickness"}
        if set(settings) != required:
            raise ValueError("self collision slice requires exactly its explicit inputs")
        program = self._programs[key]
        old_positions = np.ascontiguousarray(settings["old_positions"], dtype=np.float32)
        if old_positions.shape != (program.particle_count, 3):
            raise ValueError("old_positions must match particle_count x 3")
        edges = np.ascontiguousarray(settings["edges"], dtype=np.int32)
        triangles = np.ascontiguousarray(settings["triangles"], dtype=np.int32)
        if edges.ndim != 2 or edges.shape[1] != 2:
            raise ValueError("edges must have shape [E,2]")
        if triangles.ndim != 2 or triangles.shape[1] != 3:
            raise ValueError("triangles must have shape [T,3]")
        friction = np.ascontiguousarray(settings["friction"], dtype=np.float32)
        if friction.shape != (program.particle_count,):
            raise ValueError("friction must match particle_count")
        for array in (old_positions, edges, triangles, friction):
            array.flags.writeable = False
        self._module.mc2_domain_cpu_v1_step_self_collision(
            key, old_positions, edges, triangles, friction,
            float(settings["surface_thickness"]),
        )

    def step_whole_domain_self(self, handle, old_positions) -> None:
        """Run the configured E4 whole-domain self pass once."""
        key = self._require_handle(handle)
        program = self._programs[key]
        positions = np.ascontiguousarray(old_positions, dtype=np.float32)
        if positions.shape != (program.particle_count, 3):
            raise ValueError("old_positions must match particle_count x 3")
        positions.flags.writeable = False
        self._module.mc2_domain_cpu_v1_step_whole_domain_self(key, positions)

    def step_whole_domain_self_owned(self, handle) -> None:
        """Run E4 whole-domain self from the native-owned substep snapshot."""
        key = self._require_handle(handle)
        self._module.mc2_domain_cpu_v1_step_whole_domain_self_owned(key)

    def _prepare_compiled_external_collision(
        self,
        handle: int,
        settings: Mapping[str, object] | MC2DomainColliderFrameSpec,
    ) -> dict[str, np.ndarray]:
        if isinstance(settings, MC2DomainColliderFrameSpec):
            settings = settings.native_mapping()
        elif not isinstance(settings, Mapping):
            raise TypeError(
                "compiled external collision must be a domain collider POD or mapping"
            )
        required = {
            "collider_types", "collider_group_bits", "collider_centers",
            "collider_segment_a", "collider_segment_b", "collider_old_centers",
            "collider_old_segment_a", "collider_old_segment_b", "collider_radii",
        }
        if set(settings) != required:
            raise ValueError(
                "compiled external collision requires exactly one public collider table"
            )
        self._require_handle(handle)
        collider_types = np.ascontiguousarray(settings["collider_types"], dtype=np.int32)
        collider_group_bits = np.ascontiguousarray(
            settings["collider_group_bits"], dtype=np.int32
        )
        collider_radii = np.ascontiguousarray(settings["collider_radii"], dtype=np.float32)
        if collider_types.ndim != 1:
            raise ValueError("collider_types must be one-dimensional")
        if (
            collider_group_bits.shape != collider_types.shape
            or collider_radii.shape != collider_types.shape
        ):
            raise ValueError("compiled collider metadata must match collider count")
        arrays = {
            "collider_types": collider_types,
            "collider_group_bits": collider_group_bits,
            "collider_radii": collider_radii,
        }
        for name in (
            "collider_centers", "collider_segment_a", "collider_segment_b",
            "collider_old_centers", "collider_old_segment_a", "collider_old_segment_b",
        ):
            array = np.ascontiguousarray(settings[name], dtype=np.float32)
            if array.shape != (len(collider_types), 3):
                raise ValueError(f"{name} has invalid shape")
            arrays[name] = array
        if not all(np.all(np.isfinite(array)) for array in arrays.values()):
            raise ValueError("compiled external collider table must be finite")
        for array in arrays.values():
            array.flags.writeable = False
        return arrays

    def _run_compiled_external_collision(
        self,
        handle: int,
        arrays: Mapping[str, np.ndarray],
    ) -> None:
        self._module.mc2_domain_cpu_v1_step_compiled_external_collision(
            handle,
            arrays["collider_types"], arrays["collider_group_bits"],
            arrays["collider_centers"], arrays["collider_segment_a"],
            arrays["collider_segment_b"], arrays["collider_old_centers"],
            arrays["collider_old_segment_a"], arrays["collider_old_segment_b"],
            arrays["collider_radii"],
        )

    def step_compiled_external_collision(
        self,
        handle,
        settings: Mapping[str, object],
    ) -> None:
        key = self._require_handle(handle)
        arrays = self._prepare_compiled_external_collision(key, settings)
        self._run_compiled_external_collision(key, arrays)

    def step_external_edge_collision(self, handle, settings: Mapping[str, object]) -> None:
        key = self._require_handle(handle)
        required = {
            "collision_radii", "edges", "friction", "collided_by_groups", "collider_types",
            "collider_group_bits", "collider_centers", "collider_segment_a", "collider_segment_b",
            "collider_old_centers", "collider_old_segment_a", "collider_old_segment_b", "collider_radii",
        }
        if set(settings) != required:
            raise ValueError("external edge collision slice requires exactly its explicit inputs")
        program = self._programs[key]
        particle_radii = np.ascontiguousarray(settings["collision_radii"], dtype=np.float32)
        friction = np.ascontiguousarray(settings["friction"], dtype=np.float32)
        edges = np.ascontiguousarray(settings["edges"], dtype=np.int32)
        if particle_radii.shape != (program.particle_count,) or friction.shape != (program.particle_count,):
            raise ValueError("collision_radii/friction must match particle_count")
        if edges.ndim != 2 or edges.shape[1] != 2:
            raise ValueError("edges must have shape [E,2]")
        collider_types = np.ascontiguousarray(settings["collider_types"], dtype=np.int32)
        collider_group_bits = np.ascontiguousarray(settings["collider_group_bits"], dtype=np.int32)
        collider_radii = np.ascontiguousarray(settings["collider_radii"], dtype=np.float32)
        if collider_group_bits.shape != collider_types.shape or collider_radii.shape != collider_types.shape:
            raise ValueError("collider metadata must match collider count")
        arrays = {
            "collider_centers": np.ascontiguousarray(settings["collider_centers"], dtype=np.float32),
            "collider_segment_a": np.ascontiguousarray(settings["collider_segment_a"], dtype=np.float32),
            "collider_segment_b": np.ascontiguousarray(settings["collider_segment_b"], dtype=np.float32),
            "collider_old_centers": np.ascontiguousarray(settings["collider_old_centers"], dtype=np.float32),
            "collider_old_segment_a": np.ascontiguousarray(settings["collider_old_segment_a"], dtype=np.float32),
            "collider_old_segment_b": np.ascontiguousarray(settings["collider_old_segment_b"], dtype=np.float32),
        }
        for name, array in arrays.items():
            if array.shape != (len(collider_types), 3):
                raise ValueError(f"{name} has invalid shape")
        for array in (particle_radii, friction, edges, collider_types, collider_group_bits, collider_radii, *arrays.values()):
            array.flags.writeable = False
        self._module.mc2_domain_cpu_v1_step_external_edge_collision(
            key, particle_radii, edges, friction, int(settings["collided_by_groups"]),
            collider_types, collider_group_bits, arrays["collider_centers"], arrays["collider_segment_a"],
            arrays["collider_segment_b"], arrays["collider_old_centers"], arrays["collider_old_segment_a"],
            arrays["collider_old_segment_b"], collider_radii,
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

    def step_center_inertia(self, handle) -> None:
        self._module.mc2_domain_cpu_v1_step_center_inertia(self._require_handle(handle))

    def step_center_frame_shift(self, handle, anchor_component_local_positions) -> None:
        key = self._require_handle(handle)
        values = np.ascontiguousarray(anchor_component_local_positions, dtype=np.float32)
        program = self._programs[key]
        if values.shape != (program.partition_count, 3):
            raise ValueError("anchor_component_local_positions must match partition_count x 3")
        values.flags.writeable = False
        self._module.mc2_domain_cpu_v1_step_center_frame_shift(key, values)

    def step_task_reference_teleport(self, handle) -> None:
        key = self._require_handle(handle)
        self._module.mc2_domain_cpu_v1_step_task_reference_teleport(key)

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
        has_distance = any(table.kind == "distance" for table in program.constraint_tables)
        has_bending = any(table.kind == "bending" for table in program.constraint_tables)
        has_tether = any(table.kind == "tether" for table in program.constraint_tables)
        has_angle = program.baseline_parent_indices is not None
        self.step_task_reference_teleport(key)
        self.step_center_frame_shift(key, settings["anchor_component_local_positions"])
        self.step_center(key, {
            "dt": settings["dt"],
            "frame_interpolation": settings["frame_interpolation"],
            "distance_weights": settings["distance_weights"],
        })
        self.step_center_inertia(key)
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
        if has_distance:
            self.step_distance(key, debug_phase=0)
        if has_bending:
            self.step_bending(key)

    def step_reference_pipeline(self, handle, settings: Mapping[str, object]) -> None:
        """Run the landed native structural reference order through Motion."""
        required = {
            "anchor_component_local_positions", "dt", "frame_interpolation",
            "distance_weights", "simulation_power", "distance_simulation_power",
            "bending_simulation_power",
            "velocity_weight", "gravity",
            "step_basic_positions", "tether_compression", "tether_stretch",
            "step_basic_rotations", "angle_restoration_values", "angle_limit_values",
            "angle_restoration_velocity_attenuation", "angle_restoration_gravity_falloff",
            "angle_limit_stiffness", "angle_restoration_enabled", "angle_limit_enabled",
            "motion_base_positions", "motion_base_rotations", "motion_max_distances",
            "motion_stiffness_values", "motion_backstop_radii", "motion_backstop_distances",
            "motion_normal_axis", "motion_max_distance_enabled", "motion_backstop_enabled",
        }
        if set(settings) != required:
            raise ValueError("reference pipeline requires exactly its explicit pass inputs")
        key = self._require_handle(handle)
        program = self._programs[key]
        has_distance = any(table.kind == "distance" for table in program.constraint_tables)
        has_bending = any(table.kind == "bending" for table in program.constraint_tables)
        has_tether = any(table.kind == "tether" for table in program.constraint_tables)
        has_angle = program.baseline_parent_indices is not None
        self.step_task_reference_teleport(key)
        self.step_center_frame_shift(key, settings["anchor_component_local_positions"])
        self.step_center(key, {
            "dt": settings["dt"], "frame_interpolation": settings["frame_interpolation"],
            "distance_weights": settings["distance_weights"],
        })
        self.step_center_inertia(key)
        self.step_integration(key, {
            "dt": settings["dt"], "simulation_power": settings["simulation_power"],
            "velocity_weight": settings["velocity_weight"], "gravity": settings["gravity"],
        })
        if has_tether:
            self.step_tether(key, {
                "step_basic_positions": settings["step_basic_positions"],
                "compression": settings["tether_compression"], "stretch": settings["tether_stretch"],
            })
        if has_distance:
            self.step_distance(
                key, settings["distance_simulation_power"], debug_phase=0
            )
        if has_angle:
            self.step_angle(key, {
                "step_basic_positions": settings["step_basic_positions"],
                "step_basic_rotations": settings["step_basic_rotations"],
                "restoration_values": settings["angle_restoration_values"],
                "limit_values": settings["angle_limit_values"],
                "restoration_velocity_attenuation": settings["angle_restoration_velocity_attenuation"],
                "restoration_gravity_falloff": settings["angle_restoration_gravity_falloff"],
                "limit_stiffness": settings["angle_limit_stiffness"],
                "restoration_enabled": settings["angle_restoration_enabled"],
                "limit_enabled": settings["angle_limit_enabled"],
            })
        if has_bending:
            self.step_bending(key, settings["bending_simulation_power"])
        if has_distance:
            self.step_distance(
                key, settings["distance_simulation_power"], debug_phase=1
            )
        self.step_motion(key, {
            "base_positions": settings["motion_base_positions"],
            "base_rotations": settings["motion_base_rotations"],
            "max_distances": settings["motion_max_distances"],
            "stiffness_values": settings["motion_stiffness_values"],
            "backstop_radii": settings["motion_backstop_radii"],
            "backstop_distances": settings["motion_backstop_distances"],
            "normal_axis": settings["motion_normal_axis"],
            "max_distance_enabled": settings["motion_max_distance_enabled"],
            "backstop_enabled": settings["motion_backstop_enabled"],
        })

    def step_reference_pipeline_full(self, handle, settings: Mapping[str, object]) -> None:
        """按当前 reference 顺序执行，并显式接收碰撞 pass。

        碰撞输入保持嵌套，避免调用方把 Physics World snapshot 与结构 pass
        输入混用。``None`` 表示显式禁用；mapping 在固定混合顺序的位置执行
        对应 pass。本入口只提供 reference 事务，不替代产品 solver 路径。
        """
        settings = dict(settings)
        post_step = settings.pop("post_step", None)
        collision_mode = settings.pop("collision_mode", None)
        self_collision_enabled = settings.pop("self_collision_enabled", None)
        required = {
            "anchor_component_local_positions", "dt", "frame_interpolation",
            "distance_weights", "simulation_power", "distance_simulation_power",
            "bending_simulation_power",
            "velocity_weight", "gravity",
            "step_basic_positions", "tether_compression", "tether_stretch",
            "step_basic_rotations", "angle_restoration_values", "angle_limit_values",
            "angle_restoration_velocity_attenuation", "angle_restoration_gravity_falloff",
            "angle_limit_stiffness", "angle_restoration_enabled", "angle_limit_enabled",
            "motion_base_positions", "motion_base_rotations", "motion_max_distances",
            "motion_stiffness_values", "motion_backstop_radii", "motion_backstop_distances",
            "motion_normal_axis", "motion_max_distance_enabled", "motion_backstop_enabled",
            "point_collision", "edge_collision", "self_collision",
        }
        if set(settings) != required:
            raise ValueError("full reference pipeline requires exactly its explicit pass inputs")
        point_collision = settings["point_collision"]
        edge_collision = settings["edge_collision"]
        self_collision = settings["self_collision"]
        if point_collision is not None and edge_collision is not None:
            raise ValueError("point and edge collision modes are mutually exclusive")
        if collision_mode is not None:
            if isinstance(collision_mode, bool) or int(collision_mode) != collision_mode:
                raise ValueError("collision_mode must be 0, 1, or 2")
            collision_mode = int(collision_mode)
            if collision_mode not in (0, 1, 2):
                raise ValueError("collision_mode must be 0, 1, or 2")
            selected_mode = 1 if point_collision is not None else 2 if edge_collision is not None else 0
            if collision_mode != selected_mode:
                raise ValueError("collision_mode does not match the selected collision pass")
        if self_collision_enabled is not None:
            if not isinstance(self_collision_enabled, bool):
                raise TypeError("self_collision_enabled must be bool")
            if self_collision_enabled != (self_collision is not None):
                raise ValueError("self_collision_enabled does not match self_collision")
        key = self._require_handle(handle)
        structural = {
            name: settings[name] for name in required
            if name not in {"point_collision", "edge_collision", "self_collision"}
        }
        program = self._programs[key]
        has_distance = any(table.kind == "distance" for table in program.constraint_tables)
        has_bending = any(table.kind == "bending" for table in program.constraint_tables)
        has_tether = any(table.kind == "tether" for table in program.constraint_tables)
        has_angle = program.baseline_parent_indices is not None
        # 结构前缀与 step_reference_pipeline 一致；外碰位于 Distance B 前，
        # whole-domain self 位于 Motion 后。
        self.step_task_reference_teleport(key)
        self.step_center_frame_shift(key, structural["anchor_component_local_positions"])
        self.step_center(key, {
            "dt": structural["dt"], "frame_interpolation": structural["frame_interpolation"],
            "distance_weights": structural["distance_weights"],
        })
        self.step_center_inertia(key)
        self.step_integration(key, {
            "dt": structural["dt"], "simulation_power": structural["simulation_power"],
            "velocity_weight": structural["velocity_weight"], "gravity": structural["gravity"],
        })
        if has_tether:
            self.step_tether(key, {
                "step_basic_positions": structural["step_basic_positions"],
                "compression": structural["tether_compression"],
                "stretch": structural["tether_stretch"],
            })
        if has_distance:
            self.step_distance(
                key, structural["distance_simulation_power"], debug_phase=0
            )
        if has_angle:
            self.step_angle(key, {
                "step_basic_positions": structural["step_basic_positions"],
                "step_basic_rotations": structural["step_basic_rotations"],
                "restoration_values": structural["angle_restoration_values"],
                "limit_values": structural["angle_limit_values"],
                "restoration_velocity_attenuation": structural["angle_restoration_velocity_attenuation"],
                "restoration_gravity_falloff": structural["angle_restoration_gravity_falloff"],
                "limit_stiffness": structural["angle_limit_stiffness"],
                "restoration_enabled": structural["angle_restoration_enabled"],
                "limit_enabled": structural["angle_limit_enabled"],
            })
        if has_bending:
            self.step_bending(key, structural["bending_simulation_power"])
        if point_collision is not None:
            if not isinstance(point_collision, Mapping):
                raise TypeError("point_collision must be a mapping or None")
            self.step_external_collision(key, point_collision)
        if edge_collision is not None:
            if not isinstance(edge_collision, Mapping):
                raise TypeError("edge_collision must be a mapping or None")
            self.step_external_edge_collision(key, edge_collision)
        if has_distance:
            self.step_distance(
                key, structural["distance_simulation_power"], debug_phase=1
            )
        self.step_motion(key, {
            "base_positions": structural["motion_base_positions"],
            "base_rotations": structural["motion_base_rotations"],
            "max_distances": structural["motion_max_distances"],
            "stiffness_values": structural["motion_stiffness_values"],
            "backstop_radii": structural["motion_backstop_radii"],
            "backstop_distances": structural["motion_backstop_distances"],
            "normal_axis": structural["motion_normal_axis"],
            "max_distance_enabled": structural["motion_max_distance_enabled"],
            "backstop_enabled": structural["motion_backstop_enabled"],
        })
        if self_collision is not None:
            if not isinstance(self_collision, Mapping):
                raise TypeError("self_collision must be a mapping or None")
            self.step_self_collision(key, self_collision)
        if post_step is not None:
            if not isinstance(post_step, Mapping):
                raise TypeError("post_step must be a mapping or None")
            self.step_post(key, post_step)

    def step_compiled_domain_pipeline_full(
        self,
        handle,
        settings: Mapping[str, object],
    ) -> None:
        """Run the fixed E4 structural, external, self, and post order."""
        settings = dict(settings)
        if "external_collision" not in settings:
            raise ValueError("compiled domain pipeline requires external_collision")
        external_collision = settings.pop("external_collision")
        if not isinstance(external_collision, (Mapping, MC2DomainColliderFrameSpec)):
            raise TypeError("external_collision must be a public domain collider table")
        if "post_step" not in settings:
            raise ValueError("compiled domain pipeline requires post_step")
        post_step = settings.pop("post_step")
        if not isinstance(post_step, Mapping):
            raise TypeError("post_step must be a mapping")
        post_required = {
            "dt", "dynamic_friction_values", "static_friction_speed_values",
            "particle_speed_limit_values",
        }
        if set(post_step) != post_required:
            raise ValueError("compiled domain post_step requires exactly its particle inputs")
        key = self._require_handle(handle)
        program = self._programs[key]
        post_values = {"dt": float(post_step["dt"])}
        if not np.isfinite(post_values["dt"]) or post_values["dt"] <= 0.0:
            raise ValueError("compiled domain post_step dt is invalid")
        for name in (
            "dynamic_friction_values", "static_friction_speed_values",
            "particle_speed_limit_values",
        ):
            array = np.ascontiguousarray(post_step[name], dtype=np.float32)
            if array.shape != (program.particle_count,) or not np.isfinite(array).all():
                raise ValueError(f"compiled domain post_step {name} is invalid")
            array.flags.writeable = False
            post_values[name] = array
        if (
            np.any(post_values["dynamic_friction_values"] < 0.0)
            or np.any(post_values["dynamic_friction_values"] > 1.0)
            or np.any(post_values["static_friction_speed_values"] < 0.0)
        ):
            raise ValueError("compiled domain post_step particle values are invalid")
        collider_arrays = self._prepare_compiled_external_collision(key, external_collision)
        required = {
            "anchor_component_local_positions", "dt", "frame_interpolation",
            "distance_weights", "simulation_power", "distance_simulation_power",
            "bending_simulation_power", "step_basic_positions",
            "tether_compression_values", "tether_stretch_values",
            "step_basic_rotations", "angle_restoration_values", "angle_limit_values",
            "angle_restoration_velocity_attenuation_values",
            "angle_restoration_gravity_falloff_values", "angle_limit_stiffness_values",
            "angle_restoration_enabled_values", "angle_limit_enabled_values",
            "motion_base_positions", "motion_base_rotations", "motion_max_distances",
            "motion_stiffness_values", "motion_backstop_radii", "motion_backstop_distances",
            "motion_normal_axis_values", "motion_max_distance_enabled_values",
            "motion_backstop_enabled_values",
        }
        if set(settings) != required:
            raise ValueError("compiled domain pipeline requires exactly its structural inputs")
        has_distance = any(table.kind == "distance" for table in program.constraint_tables)
        has_bending = any(table.kind == "bending" for table in program.constraint_tables)
        has_tether = any(table.kind == "tether" for table in program.constraint_tables)
        has_angle = program.baseline_parent_indices is not None

        self.step_task_reference_teleport(key)
        self.step_center_frame_shift(key, settings["anchor_component_local_positions"])
        self.step_center(key, {
            "dt": settings["dt"], "frame_interpolation": settings["frame_interpolation"],
            "distance_weights": settings["distance_weights"],
        })
        self.step_center_inertia(key)
        self.step_integration_partitioned(key, {
            "dt": settings["dt"], "simulation_power": settings["simulation_power"],
        })
        if has_tether:
            self.step_tether_partitioned(key, {
                "step_basic_positions": settings["step_basic_positions"],
                "compression_values": settings["tether_compression_values"],
                "stretch_values": settings["tether_stretch_values"],
            })
        if has_distance:
            self.step_distance(
                key, settings["distance_simulation_power"], debug_phase=0
            )
        if has_angle:
            self.step_angle_partitioned(key, {
                "step_basic_positions": settings["step_basic_positions"],
                "step_basic_rotations": settings["step_basic_rotations"],
                "restoration_values": settings["angle_restoration_values"],
                "limit_values": settings["angle_limit_values"],
                "restoration_velocity_attenuation_values": settings[
                    "angle_restoration_velocity_attenuation_values"
                ],
                "restoration_gravity_falloff_values": settings[
                    "angle_restoration_gravity_falloff_values"
                ],
                "limit_stiffness_values": settings["angle_limit_stiffness_values"],
                "restoration_enabled_values": settings["angle_restoration_enabled_values"],
                "limit_enabled_values": settings["angle_limit_enabled_values"],
            })
        if has_bending:
            self.step_bending(key, settings["bending_simulation_power"])
        self._run_compiled_external_collision(key, collider_arrays)
        if has_distance:
            self.step_distance(
                key, settings["distance_simulation_power"], debug_phase=1
            )
        self.step_motion_partitioned(key, {
            "base_positions": settings["motion_base_positions"],
            "base_rotations": settings["motion_base_rotations"],
            "max_distances": settings["motion_max_distances"],
            "stiffness_values": settings["motion_stiffness_values"],
            "backstop_radii": settings["motion_backstop_radii"],
            "backstop_distances": settings["motion_backstop_distances"],
            "normal_axis_values": settings["motion_normal_axis_values"],
            "max_distance_enabled_values": settings["motion_max_distance_enabled_values"],
            "backstop_enabled_values": settings["motion_backstop_enabled_values"],
        })
        self.step_whole_domain_self_owned(key)
        self.step_post_owned_partitioned(key, post_values)

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
        return dict(self._module.mc2_domain_cpu_v1_inspect(key))

    def read_debug_state(self, handle) -> dict:
        """Read native dynamics/debug arrays only when explicitly requested."""
        key = self._require_handle(handle)
        raw = self._module.mc2_domain_cpu_v1_read_dynamics_debug(key)
        return {
            "velocities": np.asarray(raw["velocities"], dtype=np.float32),
            "velocity_reference_positions": np.asarray(
                raw["velocity_reference_positions"], dtype=np.float32
            ),
            "real_velocities": np.asarray(raw["real_velocities"], dtype=np.float32),
            "world_normals": np.asarray(raw["world_normals"], dtype=np.float32),
        }

    def begin_constraint_debug(self, handle, mask: int) -> None:
        key = self._require_handle(handle)
        self._module.mc2_domain_cpu_v1_begin_constraint_debug(key, int(mask))

    def end_constraint_debug(self, handle) -> None:
        key = self._require_handle(handle)
        self._module.mc2_domain_cpu_v1_end_constraint_debug(key)

    def read_constraint_debug_state(self, handle) -> dict:
        key = self._require_handle(handle)
        raw = dict(self._module.mc2_domain_cpu_v1_read_constraint_debug(key))
        result = {
            "active_mask": int(raw.get("active_mask", 0)),
            "captured_mask": int(raw.get("captured_mask", 0)),
        }
        distance_raw = raw.get("distance_results")
        if distance_raw is not None:
            distance_raw = dict(distance_raw)
            count = int(distance_raw["record_count"])
            result["distance_results"] = {
                "origins": np.asarray(distance_raw["origins"], dtype=np.float32).reshape((2, count, 3)),
                "target_origins": np.asarray(distance_raw["target_origins"], dtype=np.float32).reshape((2, count, 3)),
                "corrections": np.asarray(distance_raw["corrections"], dtype=np.float32).reshape((2, count, 3)),
                "lengths": np.asarray(distance_raw["lengths"], dtype=np.float32).reshape((2, count)),
                "rests": np.asarray(distance_raw["rests"], dtype=np.float32).reshape((2, count)),
                "stiffnesses": np.asarray(distance_raw["stiffnesses"], dtype=np.float32).reshape((2, count)),
                "valid": np.asarray(distance_raw["valid"], dtype=np.uint8).reshape((2, count)),
                "hit": np.asarray(distance_raw["hit"], dtype=np.uint8).reshape((2, count)),
                "vertices": np.asarray(distance_raw["vertices"], dtype=np.int32).reshape((2, count)),
                "targets": np.asarray(distance_raw["targets"], dtype=np.int32).reshape((2, count)),
                "partitions": np.asarray(distance_raw["partitions"], dtype=np.uint32).reshape((2, count)),
                "target_partitions": np.asarray(distance_raw["target_partitions"], dtype=np.uint32).reshape((2, count)),
            }
        tether_raw = raw.get("tether_results")
        if tether_raw is not None:
            tether_raw = dict(tether_raw)
            count = int(tether_raw["record_count"])
            result["tether_results"] = {
                "origins": np.asarray(tether_raw["origins"], dtype=np.float32).reshape((count, 3)),
                "root_origins": np.asarray(tether_raw["root_origins"], dtype=np.float32).reshape((count, 3)),
                "corrections": np.asarray(tether_raw["corrections"], dtype=np.float32).reshape((count, 3)),
                "lengths": np.asarray(tether_raw["lengths"], dtype=np.float32).reshape((count,)),
                "rests": np.asarray(tether_raw["rests"], dtype=np.float32).reshape((count,)),
                "minimums": np.asarray(tether_raw["minimums"], dtype=np.float32).reshape((count,)),
                "maximums": np.asarray(tether_raw["maximums"], dtype=np.float32).reshape((count,)),
                "stiffnesses": np.asarray(tether_raw["stiffnesses"], dtype=np.float32).reshape((count,)),
                "branches": np.asarray(tether_raw["branches"], dtype=np.int8).reshape((count,)),
                "valid": np.asarray(tether_raw["valid"], dtype=np.uint8).reshape((count,)),
                "hit": np.asarray(tether_raw["hit"], dtype=np.uint8).reshape((count,)),
                "vertices": np.asarray(tether_raw["vertices"], dtype=np.int32).reshape((count,)),
                "roots": np.asarray(tether_raw["roots"], dtype=np.int32).reshape((count,)),
                "partitions": np.asarray(tether_raw["partitions"], dtype=np.uint32).reshape((count,)),
                "root_partitions": np.asarray(tether_raw["root_partitions"], dtype=np.uint32).reshape((count,)),
            }
        bending_raw = raw.get("bending_results")
        if bending_raw is not None:
            bending_raw = dict(bending_raw)
            count = int(bending_raw["record_count"])
            result["bending_results"] = {
                "origins": np.asarray(bending_raw["origins"], dtype=np.float32).reshape((count, 4, 3)),
                "corrections": np.asarray(bending_raw["corrections"], dtype=np.float32).reshape((count, 4, 3)),
                "currents": np.asarray(bending_raw["currents"], dtype=np.float32).reshape((count,)),
                "rests": np.asarray(bending_raw["rests"], dtype=np.float32).reshape((count,)),
                "stiffnesses": np.asarray(bending_raw["stiffnesses"], dtype=np.float32).reshape((count,)),
                "valid": np.asarray(bending_raw["valid"], dtype=np.uint8).reshape((count,)),
                "hit": np.asarray(bending_raw["hit"], dtype=np.uint8).reshape((count,)),
                "vertices": np.asarray(bending_raw["vertices"], dtype=np.int32).reshape((count, 4)),
                "kinds": np.asarray(bending_raw["kinds"], dtype=np.int8).reshape((count,)),
                "markers": np.asarray(bending_raw["markers"], dtype=np.int32).reshape((count,)),
                "partitions": np.asarray(bending_raw["partitions"], dtype=np.uint32).reshape((count, 4)),
            }
        external_raw = raw.get("external_collision_results")
        if external_raw is not None:
            external_raw = dict(external_raw)
            count = int(external_raw["record_count"])
            result["external_collision_results"] = {
                "primitive_kinds": np.asarray(external_raw["primitive_kinds"], dtype=np.int32).reshape((count,)),
                "primitive_indices": np.asarray(external_raw["primitive_indices"], dtype=np.int32).reshape((count,)),
                "collider_indices": np.asarray(external_raw["collider_indices"], dtype=np.int32).reshape((count,)),
                "vertices": np.asarray(external_raw["vertices"], dtype=np.int32).reshape((count, 2)),
                "partitions": np.asarray(external_raw["partitions"], dtype=np.uint32).reshape((count, 2)),
                "origins": np.asarray(external_raw["origins"], dtype=np.float32).reshape((count, 2, 3)),
                "role_corrections": np.asarray(external_raw["role_corrections"], dtype=np.float32).reshape((count, 2, 3)),
                "positions": np.asarray(external_raw["positions"], dtype=np.float32).reshape((count, 3)),
                "normals": np.asarray(external_raw["normals"], dtype=np.float32).reshape((count, 3)),
                "corrections": np.asarray(external_raw["corrections"], dtype=np.float32).reshape((count, 3)),
                "particle_partitions": np.asarray(external_raw["particle_partitions"], dtype=np.uint32).reshape((-1,)),
                "partition_modes": np.asarray(external_raw["partition_modes"], dtype=np.uint32).reshape((-1,)),
                "partition_masks": np.asarray(external_raw["partition_masks"], dtype=np.uint32).reshape((-1,)),
                "particle_radii": np.asarray(external_raw["particle_radii"], dtype=np.float32).reshape((-1,)),
                "friction_before": np.asarray(external_raw["friction_before"], dtype=np.float32).reshape((-1,)),
                "friction_after": np.asarray(external_raw["friction_after"], dtype=np.float32).reshape((-1,)),
            }
        self_raw = raw.get("whole_domain_self_results")
        if self_raw is not None:
            self_raw = dict(self_raw)
            primitive_count = (
                int(self_raw["point_primitive_count"])
                + int(self_raw["edge_primitive_count"])
                + int(self_raw["triangle_primitive_count"])
            )
            contact_count = np.asarray(
                self_raw["contact_types"], dtype=np.int32
            ).size
            result["whole_domain_self_results"] = {
                "frame": int(self_raw["frame"]),
                "generation": int(self_raw["generation"]),
                "point_primitive_count": int(self_raw["point_primitive_count"]),
                "edge_primitive_count": int(self_raw["edge_primitive_count"]),
                "triangle_primitive_count": int(self_raw["triangle_primitive_count"]),
                "point_grid_count": int(self_raw["point_grid_count"]),
                "edge_grid_count": int(self_raw["edge_grid_count"]),
                "triangle_grid_count": int(self_raw["triangle_grid_count"]),
                "max_primitive_size": float(self_raw["max_primitive_size"]),
                "grid_size": float(self_raw["grid_size"]),
                "primitive_flags": np.asarray(self_raw["primitive_flags"], dtype=np.uint32).reshape((primitive_count,)),
                "particle_indices": np.asarray(self_raw["particle_indices"], dtype=np.int32).reshape((primitive_count, 3)),
                "primitive_depths": np.asarray(self_raw["primitive_depths"], dtype=np.float32).reshape((primitive_count,)),
                "inverse_masses": np.asarray(self_raw["inverse_masses"], dtype=np.float32).reshape((primitive_count, 3)),
                "aabb_min": np.asarray(self_raw["aabb_min"], dtype=np.float32).reshape((primitive_count, 3)),
                "aabb_max": np.asarray(self_raw["aabb_max"], dtype=np.float32).reshape((primitive_count, 3)),
                "thickness": np.asarray(self_raw["thickness"], dtype=np.float32).reshape((primitive_count,)),
                "owner_indices": np.asarray(self_raw["owner_indices"], dtype=np.int32).reshape((primitive_count,)),
                "owner_group_bits": np.asarray(self_raw["owner_group_bits"], dtype=np.int32).reshape((-1,)),
                "owner_collision_masks": np.asarray(self_raw["owner_collision_masks"], dtype=np.int32).reshape((-1,)),
                "primitive_grids": np.asarray(self_raw["primitive_grids"], dtype=np.int32).reshape((primitive_count, 3)),
                "grid_hashes": np.asarray(self_raw["grid_hashes"], dtype=np.int32).reshape((primitive_count,)),
                "grid_starts": np.asarray(self_raw["grid_starts"], dtype=np.int32).reshape((primitive_count,)),
                "grid_counts": np.asarray(self_raw["grid_counts"], dtype=np.int32).reshape((primitive_count,)),
                "candidates": np.asarray(self_raw["candidates"], dtype=np.int32).reshape((-1, 3)),
                "contact_indices": np.asarray(self_raw["contact_indices"], dtype=np.int32).reshape((contact_count, 2)),
                "contact_types": np.asarray(self_raw["contact_types"], dtype=np.int32).reshape((contact_count,)),
                "contact_enabled": np.asarray(self_raw["contact_enabled"], dtype=np.uint8).reshape((contact_count,)),
                "contact_thickness": np.asarray(self_raw["contact_thickness"], dtype=np.float32).reshape((contact_count,)),
                "contact_s": np.asarray(self_raw["contact_s"], dtype=np.float32).reshape((contact_count,)),
                "contact_t": np.asarray(self_raw["contact_t"], dtype=np.float32).reshape((contact_count,)),
                "contact_normals": np.asarray(self_raw["contact_normals"], dtype=np.float32).reshape((contact_count, 3)),
                "contact_corrections": np.asarray(self_raw["contact_corrections"], dtype=np.float32).reshape((contact_count, 2, 3)),
                "intersect_records": np.asarray(self_raw["intersect_records"], dtype=np.int32).reshape((-1, 5)),
            }
        motion_raw = raw.get("motion_results")
        if motion_raw is not None:
            motion_raw = dict(motion_raw)
            count = int(motion_raw["particle_count"])
            result["motion_results"] = {
                "origins": np.asarray(motion_raw["origins"], dtype=np.float32).reshape((2, count, 3)),
                "targets": np.asarray(motion_raw["targets"], dtype=np.float32).reshape((2, count, 3)),
                "corrections": np.asarray(motion_raw["corrections"], dtype=np.float32).reshape((2, count, 3)),
                "limits": np.asarray(motion_raw["limits"], dtype=np.float32).reshape((2, count)),
                "valid": np.asarray(motion_raw["valid"], dtype=np.uint8).reshape((2, count)),
                "vertices": np.asarray(motion_raw["vertices"], dtype=np.int32).reshape((2, count)),
                "partitions": np.asarray(motion_raw["partitions"], dtype=np.uint32).reshape((2, count)),
            }
        angle_raw = raw.get("angle_results")
        if angle_raw is not None:
            angle_raw = dict(angle_raw)
            count = int(angle_raw["baseline_data_count"])
            result["angle_results"] = {
                "origins": np.asarray(angle_raw["origins"], dtype=np.float32).reshape((2, 3, count, 2, 3)),
                "targets": np.asarray(angle_raw["targets"], dtype=np.float32).reshape((2, 3, count, 3)),
                "target_vectors": np.asarray(angle_raw["target_vectors"], dtype=np.float32).reshape((2, 3, count, 3)),
                "corrections": np.asarray(angle_raw["corrections"], dtype=np.float32).reshape((2, 3, count, 2, 3)),
                "currents": np.asarray(angle_raw["currents"], dtype=np.float32).reshape((2, 3, count)),
                "limits": np.asarray(angle_raw["limits"], dtype=np.float32).reshape((2, 3, count)),
                "valid": np.asarray(angle_raw["valid"], dtype=np.uint8).reshape((2, 3, count)),
                "children": np.asarray(angle_raw["children"], dtype=np.int32).reshape((2, 3, count)),
                "parents": np.asarray(angle_raw["parents"], dtype=np.int32).reshape((2, 3, count)),
                "partitions": np.asarray(angle_raw["partitions"], dtype=np.uint32).reshape((2, 3, count)),
            }
        return result

    def clear_constraint_debug(self, handle) -> None:
        key = self._require_handle(handle)
        self._module.mc2_domain_cpu_v1_clear_constraint_debug(key)

    def read_center_debug_state(self, handle) -> dict:
        """Read the native partitioned Center/Teleport observation slice."""
        key = self._require_handle(handle)
        return dict(self._module.mc2_domain_cpu_v1_read_center_debug(key))

    def read_task_reference_teleport_state(self, handle) -> dict:
        key = self._require_handle(handle)
        return dict(self._module.mc2_domain_cpu_v1_read_task_reference_teleport(key))

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

    def _require_parameter_update(self, handle, update):
        key = self._require_handle(handle)
        if not isinstance(update, _MC2NativeParameterUpdateV1):
            raise TypeError("update must be a native CPU parameter update")
        if update.owner_handle != key or update.closed:
            raise RuntimeError("native CPU parameter update is stale")
        return key, update

    def _configure_domain(
        self,
        handle: int,
        program: MC2CompiledDomainProgramV1,
        parameters: MC2DomainParameterPacketV1,
    ) -> None:
        self._configure_distance(handle, program, parameters)
        self._configure_baseline(handle, program)
        self._configure_tether(handle, program)
        self._configure_bending(handle, program, parameters)
        self._configure_inertia(handle, program, parameters)
        self._configure_constraint_friction(handle, parameters)
        self._configure_whole_domain_self(handle, program, parameters)
        self._configure_compiled_external_collision(handle, program, parameters)
        self._configure_center(handle, parameters)
        self._configure_center_frame_shift(handle, parameters)
        self._configure_integration(handle, parameters)

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
        particle_fields = {
            name: index for index, name in enumerate(parameters.particle_parameters.fields)
        }
        missing_particle = {"depth", "collision_friction"} - set(particle_fields)
        if missing_particle:
            raise ValueError(
                "particle parameter table lacks Distance mass fields: "
                + ", ".join(sorted(missing_particle))
            )
        particle_values = parameters.particle_parameters.values
        depth_array = np.asarray(
            particle_values[:, particle_fields["depth"]], dtype=np.float32
        )
        friction_array = np.asarray(
            particle_values[:, particle_fields["collision_friction"]], dtype=np.float32
        )
        partition_fields = {
            name: index for index, name in enumerate(parameters.partition_parameters.fields)
        }
        if "distance_velocity_attenuation" not in partition_fields:
            raise ValueError(
                "partition parameter table lacks distance_velocity_attenuation"
            )
        attenuation_by_partition = np.asarray(
            parameters.partition_parameters.values[
                :, partition_fields["distance_velocity_attenuation"]
            ],
            dtype=np.float32,
        )
        attenuation_array = np.asarray(
            attenuation_by_partition[program.particle_partition_index],
            dtype=np.float32,
        )
        starts_array = np.asarray(starts, dtype=np.int32)
        counts_array = np.asarray(counts, dtype=np.int32)
        neighbors_array = np.asarray(neighbors, dtype=np.int32)
        rest_array = np.asarray(rest, dtype=np.float32)
        stiffness_array = np.asarray(stiffness, dtype=np.float32)
        for array in (
            starts_array, counts_array, neighbors_array, rest_array, stiffness_array,
            depth_array, friction_array, attenuation_array,
        ):
            array.flags.writeable = False
        self._module.mc2_domain_cpu_v1_configure_distance(
            handle,
            starts_array,
            counts_array,
            neighbors_array,
            rest_array,
            stiffness_array,
            depth_array,
            friction_array,
            attenuation_array,
        )

    def _configure_baseline(
        self,
        handle: int,
        program: MC2CompiledDomainProgramV1,
    ) -> None:
        if program.baseline_parent_indices is None:
            return
        arrays = (
            np.asarray(program.baseline_parent_indices, dtype=np.int32),
            np.asarray(program.baseline_line_start, dtype=np.int32),
            np.asarray(program.baseline_line_count, dtype=np.int32),
            np.asarray(program.baseline_line_data, dtype=np.int32),
        )
        for array in arrays:
            array.flags.writeable = False
        self._module.mc2_domain_cpu_v1_configure_baseline(handle, *arrays)
        if program.baseline_vertex_local_position is not None:
            pose_arrays = (
                np.asarray(program.baseline_vertex_local_position, dtype=np.float32),
                np.asarray(program.baseline_vertex_local_rotation, dtype=np.float32),
            )
            for array in pose_arrays:
                array.flags.writeable = False
            self._module.mc2_domain_cpu_v1_configure_baseline_pose(handle, *pose_arrays)

    def prepare_step_basic_pose(self, handle, animation_pose_ratio=0.0) -> dict:
        key = self._require_handle(handle)
        ratios = np.asarray(animation_pose_ratio)
        if ratios.ndim == 1:
            ratios = np.ascontiguousarray(ratios, dtype=np.float32)
            if ratios.shape != (self._programs[key].partition_count,):
                raise ValueError("animation_pose_ratios must match partition_count")
            ratios.flags.writeable = False
            result = self._module.mc2_domain_cpu_v1_prepare_step_basic_pose_partitioned(
                key, ratios
            )
        elif ratios.ndim == 0:
            result = self._module.mc2_domain_cpu_v1_prepare_step_basic_pose(
                key, float(ratios)
            )
        else:
            raise ValueError("animation_pose_ratio must be scalar or partition vector")
        return {
            "positions": np.asarray(result["positions"], dtype=np.float32),
            "rotations": np.asarray(result["rotations"], dtype=np.float32),
        }

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

    def _configure_bending(
        self,
        handle: int,
        program: MC2CompiledDomainProgramV1,
        parameters: MC2DomainParameterPacketV1,
    ) -> None:
        bending_table = next(
            (table for table in program.constraint_tables if table.kind == "bending"),
            None,
        )
        if bending_table is None:
            return
        parameter_table = next(
            (table for table in parameters.constraint_parameters if table.name == "bending"),
            None,
        )
        if parameter_table is None or parameter_table.row_count != bending_table.record_count:
            raise ValueError("bending topology has no matching parameter table")
        fields = {name: index for index, name in enumerate(parameter_table.fields)}
        if "rest_value" not in fields or "stiffness" not in fields:
            raise ValueError("bending parameter table lacks rest_value/stiffness")
        dihedral_pairs = []
        dihedral_rest = []
        dihedral_signs = []
        volume_pairs = []
        volume_rest = []
        stiffness = np.zeros(program.particle_count, dtype=np.float32)
        stiffness_counts = np.zeros(program.particle_count, dtype=np.int32)
        for record, row in enumerate(bending_table.indices):
            quad = tuple(int(value) for value in row)
            rest = float(parameter_table.values[record, fields["rest_value"]])
            value = float(parameter_table.values[record, fields["stiffness"]])
            marker = int(bending_table.flags[record])
            if marker == 100:
                volume_pairs.extend(quad)
                volume_rest.append(rest)
            else:
                dihedral_pairs.extend(quad)
                dihedral_rest.append(rest)
                dihedral_signs.append(-1 if marker == 1 else 1)
            for vertex in quad:
                stiffness[vertex] += value
                stiffness_counts[vertex] += 1
        nonzero = stiffness_counts != 0
        stiffness[nonzero] /= stiffness_counts[nonzero]
        dihedral_pairs_array = np.asarray(dihedral_pairs, dtype=np.int32).reshape((len(dihedral_rest), 4))
        volume_pairs_array = np.asarray(volume_pairs, dtype=np.int32).reshape((len(volume_rest), 4))
        arrays = (
            dihedral_pairs_array,
            np.asarray(dihedral_rest, dtype=np.float32),
            np.asarray(dihedral_signs, dtype=np.int32),
            volume_pairs_array,
            np.asarray(volume_rest, dtype=np.float32),
            stiffness,
        )
        for array in arrays:
            array.flags.writeable = False
        self._module.mc2_domain_cpu_v1_configure_bending(handle, *arrays)

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

    def _configure_constraint_friction(
        self,
        handle: int,
        parameters: MC2DomainParameterPacketV1,
    ) -> None:
        fields = {
            name: index for index, name in enumerate(parameters.particle_parameters.fields)
        }
        if "collision_friction" not in fields:
            raise ValueError("particle parameter table lacks collision_friction")
        values = np.asarray(
            parameters.particle_parameters.values[:, fields["collision_friction"]],
            dtype=np.float32,
        )
        values.flags.writeable = False
        self._module.mc2_domain_cpu_v1_configure_constraint_friction(handle, values)

    def _configure_whole_domain_self(
        self,
        handle: int,
        program: MC2CompiledDomainProgramV1,
        parameters: MC2DomainParameterPacketV1,
    ) -> None:
        primitive_tables = {table.kind: table for table in program.primitive_tables}
        point_table = primitive_tables.get("point")
        edge_table = primitive_tables.get("edge")
        triangle_table = primitive_tables.get("triangle")
        points = np.asarray(
            point_table.indices[:, 0] if point_table is not None else np.empty((0,)),
            dtype=np.int32,
        ).reshape((-1,))
        edges = np.asarray(
            edge_table.indices if edge_table is not None else np.empty((0, 2)),
            dtype=np.int32,
        ).reshape((-1, 2))
        triangles = np.asarray(
            triangle_table.indices if triangle_table is not None else np.empty((0, 3)),
            dtype=np.int32,
        ).reshape((-1, 3))

        partition_fields = {
            name: index
            for index, name in enumerate(parameters.partition_uint_parameters.fields)
        }
        required_partition = {
            "self_collision_mode", "collision_group", "collision_mask",
        }
        missing_partition = required_partition - set(partition_fields)
        if missing_partition:
            raise ValueError(
                "partition uint parameter table lacks whole-domain self fields: "
                + ", ".join(sorted(missing_partition))
            )
        partition_values = parameters.partition_uint_parameters.values
        modes = np.asarray(
            partition_values[:, partition_fields["self_collision_mode"]], dtype=np.uint32
        )
        groups = np.asarray(
            partition_values[:, partition_fields["collision_group"]], dtype=np.uint32
        )
        masks = np.asarray(
            partition_values[:, partition_fields["collision_mask"]], dtype=np.uint32
        )

        particle_fields = {
            name: index for index, name in enumerate(parameters.particle_parameters.fields)
        }
        required_particle = {
            "radius_multiplier", "self_collision_thickness", "collision_friction",
            "cloth_mass",
        }
        missing_particle = required_particle - set(particle_fields)
        if missing_particle:
            raise ValueError(
                "particle parameter table lacks whole-domain self fields: "
                + ", ".join(sorted(missing_particle))
            )
        particle_values = parameters.particle_parameters.values
        friction = np.asarray(
            particle_values[:, particle_fields["collision_friction"]], dtype=np.float32
        )
        thickness = np.asarray(
            particle_values[:, particle_fields["self_collision_thickness"]]
            * particle_values[:, particle_fields["radius_multiplier"]],
            dtype=np.float32,
        )
        cloth_mass = np.asarray(
            particle_values[:, particle_fields["cloth_mass"]], dtype=np.float32
        )
        for array in (
            points, edges, triangles, modes, groups, masks, friction, thickness, cloth_mass,
        ):
            array.flags.writeable = False
        self._module.mc2_domain_cpu_v1_configure_whole_domain_self(
            handle, points, edges, triangles, modes, groups, masks, friction, thickness,
            cloth_mass,
        )

    def _configure_compiled_external_collision(
        self,
        handle: int,
        program: MC2CompiledDomainProgramV1,
        parameters: MC2DomainParameterPacketV1,
    ) -> None:
        primitive_tables = {table.kind: table for table in program.primitive_tables}
        edge_table = primitive_tables.get("edge")
        edges = np.asarray(
            edge_table.indices if edge_table is not None else np.empty((0, 2)),
            dtype=np.int32,
        ).reshape((-1, 2))
        partition_fields = {
            name: index
            for index, name in enumerate(parameters.partition_uint_parameters.fields)
        }
        required_partition = {"collision_mode", "collided_by_groups"}
        missing_partition = required_partition - set(partition_fields)
        if missing_partition:
            raise ValueError(
                "partition uint parameter table lacks compiled external collision fields: "
                + ", ".join(sorted(missing_partition))
            )
        partition_values = parameters.partition_uint_parameters.values
        modes = np.asarray(
            partition_values[:, partition_fields["collision_mode"]], dtype=np.uint32
        )
        masks = np.asarray(
            partition_values[:, partition_fields["collided_by_groups"]], dtype=np.uint32
        )
        particle_fields = {
            name: index for index, name in enumerate(parameters.particle_parameters.fields)
        }
        required_particle = {"radius_multiplier", "radius", "collision_friction"}
        missing_particle = required_particle - set(particle_fields)
        if missing_particle:
            raise ValueError(
                "particle parameter table lacks compiled external collision fields: "
                + ", ".join(sorted(missing_particle))
            )
        particle_values = parameters.particle_parameters.values
        radii = np.asarray(
            particle_values[:, particle_fields["radius"]]
            * particle_values[:, particle_fields["radius_multiplier"]],
            dtype=np.float32,
        )
        friction = np.asarray(
            particle_values[:, particle_fields["collision_friction"]], dtype=np.float32
        )
        for array in (edges, modes, masks, radii, friction):
            array.flags.writeable = False
        self._module.mc2_domain_cpu_v1_configure_compiled_external_collision(
            handle, edges, modes, masks, radii, friction
        )

    def _configure_center(
        self,
        handle: int,
        parameters: MC2DomainParameterPacketV1,
    ) -> None:
        table = parameters.partition_parameters
        fields = {name: index for index, name in enumerate(table.fields)}
        required = {
            "local_inertia", "local_movement_speed_limit", "local_rotation_speed_limit",
            "depth_inertia",
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
                "depth_inertia",
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
            scalar["depth_inertia"],
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
