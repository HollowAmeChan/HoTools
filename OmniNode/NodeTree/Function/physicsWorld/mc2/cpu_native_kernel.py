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
    "mc2_domain_cpu_v1_configure_baseline",
    "mc2_domain_cpu_v1_step_angle",
    "mc2_domain_cpu_v1_step_motion",
    "mc2_domain_cpu_v1_step_external_collision",
    "mc2_domain_cpu_v1_step_self_collision",
    "mc2_domain_cpu_v1_step_external_edge_collision",
    "mc2_domain_cpu_v1_configure_tether",
    "mc2_domain_cpu_v1_step_tether",
    "mc2_domain_cpu_v1_configure_bending",
    "mc2_domain_cpu_v1_step_bending",
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
            self._configure_baseline(handle, program)
            self._configure_tether(handle, program)
            self._configure_bending(handle, program, parameters)
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
        bending_slice = settings.pop("bending_slice", False) is True
        angle_slice = settings.pop("angle_slice", False) is True
        motion_slice = settings.pop("motion_slice", False) is True
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
        if sum((distance_slice, tether_slice, bending_slice, angle_slice, motion_slice)) > 1:
            raise ValueError("constraint slices are mutually exclusive")
        if tether_slice:
            self.step_tether(key, settings)
        elif bending_slice:
            if settings:
                raise ValueError("bending_slice does not accept additional inputs")
            self._module.mc2_domain_cpu_v1_step_bending(key)
        elif angle_slice:
            self.step_angle(key, settings)
        elif motion_slice:
            self.step_motion(key, settings)
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

    def step_bending(self, handle) -> None:
        key = self._require_handle(handle)
        self._module.mc2_domain_cpu_v1_step_bending(key)

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
        if any(table.kind == "bending" for table in program.constraint_tables):
            self.step_bending(key)

    def step_reference_pipeline(self, handle, settings: Mapping[str, object]) -> None:
        """Run the landed native structural reference order through Motion."""
        required = {
            "anchor_component_local_positions", "dt", "frame_interpolation",
            "distance_weights", "simulation_power", "velocity_weight", "gravity",
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
        if program.baseline_parent_indices is None:
            raise RuntimeError("reference pipeline requires baseline line SoA")
        self.step_center_frame_shift(key, settings["anchor_component_local_positions"])
        self.step_center(key, {
            "dt": settings["dt"], "frame_interpolation": settings["frame_interpolation"],
            "distance_weights": settings["distance_weights"],
        })
        self.step_integration(key, {
            "dt": settings["dt"], "simulation_power": settings["simulation_power"],
            "velocity_weight": settings["velocity_weight"], "gravity": settings["gravity"],
        })
        self.step_tether(key, {
            "step_basic_positions": settings["step_basic_positions"],
            "compression": settings["tether_compression"], "stretch": settings["tether_stretch"],
        })
        self.step_distance(key)
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
        if any(table.kind == "bending" for table in program.constraint_tables):
            self.step_bending(key)
        self.step_distance(key)
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
        """Run the V0 pass order, with collision passes supplied explicitly.

        Collision inputs are nested so the caller cannot accidentally mix a
        Physics World snapshot with the structural pass inputs.  ``None`` is
        an explicit disabled pass; a mapping invokes that pass at its V0
        position.  This is a reference transaction only and does not replace
        the product solver path.
        """
        required = {
            "anchor_component_local_positions", "dt", "frame_interpolation",
            "distance_weights", "simulation_power", "velocity_weight", "gravity",
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
        key = self._require_handle(handle)
        structural = {
            name: settings[name] for name in required
            if name not in {"point_collision", "edge_collision", "self_collision"}
        }
        # Keep the same explicit structural prefix as step_reference_pipeline,
        # then insert V0 collision passes before Distance B and self after Motion.
        self.step_center_frame_shift(key, structural["anchor_component_local_positions"])
        self.step_center(key, {
            "dt": structural["dt"], "frame_interpolation": structural["frame_interpolation"],
            "distance_weights": structural["distance_weights"],
        })
        self.step_integration(key, {
            "dt": structural["dt"], "simulation_power": structural["simulation_power"],
            "velocity_weight": structural["velocity_weight"], "gravity": structural["gravity"],
        })
        self.step_tether(key, {
            "step_basic_positions": structural["step_basic_positions"],
            "compression": structural["tether_compression"],
            "stretch": structural["tether_stretch"],
        })
        self.step_distance(key)
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
        if any(table.kind == "bending" for table in self._programs[key].constraint_tables):
            self.step_bending(key)
        point_collision = settings["point_collision"]
        if point_collision is not None:
            if not isinstance(point_collision, Mapping):
                raise TypeError("point_collision must be a mapping or None")
            self.step_external_collision(key, point_collision)
        edge_collision = settings["edge_collision"]
        if edge_collision is not None:
            if not isinstance(edge_collision, Mapping):
                raise TypeError("edge_collision must be a mapping or None")
            self.step_external_edge_collision(key, edge_collision)
        self.step_distance(key)
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
        self_collision = settings["self_collision"]
        if self_collision is not None:
            if not isinstance(self_collision, Mapping):
                raise TypeError("self_collision must be a mapping or None")
            self.step_self_collision(key, self_collision)

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
            "baseline_slice_ready": bool(result.get("baseline_ready", False)),
            "distance_slice_ready": True,
            "tether_slice_ready": any(
                table.kind == "tether" for table in self._programs[key].constraint_tables
            ),
            "bending_slice_ready": any(
                table.kind == "bending" for table in self._programs[key].constraint_tables
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
