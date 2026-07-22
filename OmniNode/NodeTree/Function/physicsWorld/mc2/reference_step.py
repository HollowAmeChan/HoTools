"""Compile one MC2 reference substep from domain-owned inputs.

This module is a pure host/domain boundary.  It reads compiled effective
parameter SoA, the current frame packet, and the scheduler substep plan.  It
does not read Blender, own Physics World state, or execute a native pass.
"""

from __future__ import annotations

from typing import Mapping

import numpy as np

from .domain_compile import MC2MeshCompiledDomainV1
from .domain_ir import MC2DomainFramePacketV1
from .scheduler import MC2SubstepPlan


def _table_fields(table) -> dict[str, int]:
    return {name: index for index, name in enumerate(table.fields)}


def _particle_column(table, fields: Mapping[str, int], name: str) -> np.ndarray:
    if name not in fields:
        raise ValueError(f"particle parameter table lacks {name}")
    values = np.asarray(table.values[:, fields[name]], dtype=np.float32)
    values.flags.writeable = False
    return values


def _partition_scalar(table, fields: Mapping[str, int], name: str) -> float:
    if name not in fields:
        raise ValueError(f"partition parameter table lacks {name}")
    return float(table.values[0, fields[name]])


def _partition_vector(table, fields: Mapping[str, int], names: tuple[str, ...]) -> tuple[float, ...]:
    return tuple(_partition_scalar(table, fields, name) for name in names)


def _particle_partition_column(compiled, table, fields, name, *, dtype=np.float32):
    if name not in fields:
        raise ValueError(f"partition parameter table lacks {name}")
    owners = np.asarray(compiled.program.particle_partition_index, dtype=np.intp)
    values = np.ascontiguousarray(table.values[owners, fields[name]], dtype=dtype)
    values.flags.writeable = False
    return values


def _scaled_particle_column(
    table,
    fields: Mapping[str, int],
    name: str,
    scale: float,
) -> np.ndarray:
    if name not in fields:
        raise ValueError(f"particle parameter table lacks {name}")
    values = np.asarray(table.values[:, fields[name]], dtype=np.float32)
    values = np.ascontiguousarray(values * np.float32(scale), dtype=np.float32)
    values.flags.writeable = False
    return values


def _require_single_partition(compiled: MC2MeshCompiledDomainV1) -> None:
    if not isinstance(compiled, MC2MeshCompiledDomainV1):
        raise TypeError("compiled must be MC2MeshCompiledDomainV1")
    if compiled.program.partition_count != 1:
        raise ValueError("reference settings currently require exactly one partition")


def _validate_vector(values, shape: tuple[int, ...], name: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float32)
    if array.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} cannot contain NaN/Inf")
    array = np.ascontiguousarray(array, dtype=np.float32)
    array.flags.writeable = False
    return array


def make_mc2_reference_pipeline_settings(
    compiled: MC2MeshCompiledDomainV1,
    frame_packet: MC2DomainFramePacketV1,
    substep_plan: MC2SubstepPlan,
    *,
    anchor_component_local_positions,
    step_basic_positions,
    step_basic_rotations,
    motion_base_positions,
    motion_base_rotations,
    distance_weights,
    point_collision=None,
    edge_collision=None,
    self_collision=None,
    old_positions=None,
) -> dict[str, object]:
    """Build the explicit settings accepted by ``step_reference_pipeline_full``.

    The function intentionally supports one partition only; E4 will add a
    whole-domain packet after the multi-source transaction contract is frozen.
    ``point_collision``, ``edge_collision`` and ``self_collision`` are already
    typed domain snapshots and are passed through without mutation.
    """
    _require_single_partition(compiled)
    if not isinstance(frame_packet, MC2DomainFramePacketV1):
        raise TypeError("frame_packet must be MC2DomainFramePacketV1")
    if not isinstance(substep_plan, MC2SubstepPlan):
        raise TypeError("substep_plan must be MC2SubstepPlan")
    program = compiled.program
    if frame_packet.domain_signature != program.domain_signature:
        raise ValueError("frame packet domain signature does not match compiled program")
    if frame_packet.layout_signature != program.layout_signature:
        raise ValueError("frame packet layout signature does not match compiled program")

    particle_count = program.particle_count
    partition_fields = _table_fields(compiled.parameters.partition_parameters)
    partition_uint_fields = _table_fields(compiled.parameters.partition_uint_parameters)
    particle_fields = _table_fields(compiled.parameters.particle_parameters)
    partition_uint = compiled.parameters.partition_uint_parameters.values[0]

    anchor = _validate_vector(
        anchor_component_local_positions,
        (1, 3),
        "anchor_component_local_positions",
    )
    step_positions = _validate_vector(step_basic_positions, (particle_count, 3), "step_basic_positions")
    step_rotations = _validate_vector(step_basic_rotations, (particle_count, 4), "step_basic_rotations")
    motion_positions = _validate_vector(motion_base_positions, (particle_count, 3), "motion_base_positions")
    motion_rotations = _validate_vector(motion_base_rotations, (particle_count, 4), "motion_base_rotations")
    weights = _validate_vector(distance_weights, (1,), "distance_weights")
    if old_positions is not None:
        old_positions = _validate_vector(old_positions, (particle_count, 3), "old_positions")

    collision_mode = int(partition_uint[partition_uint_fields["collision_mode"]])
    selected_mode = 1 if point_collision is not None else 2 if edge_collision is not None else 0
    if collision_mode != selected_mode:
        raise ValueError("compiled collision_mode does not match the selected collision pass")
    self_collision_mode = int(partition_uint[partition_uint_fields["self_collision_mode"]])
    if (self_collision_mode != 0) != (self_collision is not None):
        raise ValueError("compiled self_collision_mode does not match the selected self pass")

    gravity = _partition_scalar(compiled.parameters.partition_parameters, partition_fields, "gravity")
    gravity_direction = _partition_vector(
        compiled.parameters.partition_parameters,
        partition_fields,
        ("gravity_direction_x", "gravity_direction_y", "gravity_direction_z"),
    )
    gravity_ratio = float(frame_packet.gravity_ratio[0])
    velocity_weight = float(frame_packet.velocity_weight[0])
    particle_values = compiled.parameters.particle_parameters

    settings: dict[str, object] = {
        "anchor_component_local_positions": anchor,
        "dt": float(substep_plan.simulation_delta_time),
        "frame_interpolation": float(substep_plan.frame_interpolation),
        "distance_weights": weights,
        "simulation_power": float(substep_plan.powers.integration),
        "distance_simulation_power": float(substep_plan.powers.distance_bending),
        "bending_simulation_power": float(substep_plan.powers.distance_bending),
        "velocity_weight": velocity_weight,
        "gravity": tuple(float(value * gravity * gravity_ratio) for value in gravity_direction),
        "step_basic_positions": step_positions,
        "tether_compression": _partition_scalar(
            compiled.parameters.partition_parameters, partition_fields, "tether_compression_limit"
        ),
        "tether_stretch": _partition_scalar(
            compiled.parameters.partition_parameters, partition_fields, "tether_stretch_limit"
        ),
        "step_basic_rotations": step_rotations,
        "angle_restoration_values": _scaled_particle_column(
            particle_values,
            particle_fields,
            "angle_restoration_stiffness",
            substep_plan.powers.angle,
        ),
        # V0 scales restoration strength by the substep angle power, but
        # samples the angle-limit curve as an instantaneous bound.
        "angle_limit_values": _particle_column(
            particle_values,
            particle_fields,
            "angle_limit",
        ),
        "angle_restoration_velocity_attenuation": _partition_scalar(
            compiled.parameters.partition_parameters,
            partition_fields,
            "angle_restoration_velocity_attenuation",
        ),
        "angle_restoration_gravity_falloff": _partition_scalar(
            compiled.parameters.partition_parameters,
            partition_fields,
            "angle_restoration_gravity_falloff",
        ),
        "angle_limit_stiffness": _partition_scalar(
            compiled.parameters.partition_parameters, partition_fields, "angle_limit_stiffness"
        ),
        "angle_restoration_enabled": bool(
            partition_uint[partition_uint_fields["use_angle_restoration"]]
        ),
        "angle_limit_enabled": bool(partition_uint[partition_uint_fields["use_angle_limit"]]),
        "motion_base_positions": motion_positions,
        "motion_base_rotations": motion_rotations,
        "motion_max_distances": _particle_column(particle_values, particle_fields, "max_distance"),
        "motion_stiffness_values": np.full(
            particle_count,
            _partition_scalar(compiled.parameters.partition_parameters, partition_fields, "motion_stiffness"),
            dtype=np.float32,
        ),
        "motion_backstop_radii": np.full(
            particle_count,
            _partition_scalar(compiled.parameters.partition_parameters, partition_fields, "backstop_radius"),
            dtype=np.float32,
        ),
        "motion_backstop_distances": _particle_column(
            particle_values, particle_fields, "backstop_distance"
        ),
        "motion_normal_axis": int(partition_uint[partition_uint_fields["normal_axis"]]),
        "motion_max_distance_enabled": bool(partition_uint[partition_uint_fields["use_max_distance"]]),
        "motion_backstop_enabled": bool(partition_uint[partition_uint_fields["use_backstop"]]),
        "point_collision": point_collision,
        "edge_collision": edge_collision,
        "self_collision": self_collision,
        "collision_mode": collision_mode,
        "self_collision_enabled": self_collision is not None,
    }
    if old_positions is not None:
        settings["post_step"] = {
            "old_positions": old_positions,
            "dt": float(substep_plan.simulation_delta_time),
            "dynamic_friction": _partition_scalar(
                compiled.parameters.partition_parameters, partition_fields, "collision_dynamic_friction"
            ),
            "static_friction_speed": _partition_scalar(
                compiled.parameters.partition_parameters, partition_fields, "collision_static_friction"
            ),
            "particle_speed_limit": _partition_scalar(
                compiled.parameters.partition_parameters, partition_fields, "particle_speed_limit"
            ),
            "velocity_weight": velocity_weight,
        }
    return settings


def make_mc2_compiled_domain_pipeline_settings(
    compiled: MC2MeshCompiledDomainV1,
    frame_packet: MC2DomainFramePacketV1,
    substep_plan: MC2SubstepPlan,
    *,
    anchor_component_local_positions,
    step_basic_positions,
    step_basic_rotations,
    distance_weights,
    external_collision,
) -> dict[str, object]:
    """Compile one E4 whole-domain substep without collapsing partition values."""

    if not isinstance(compiled, MC2MeshCompiledDomainV1):
        raise TypeError("compiled must be MC2MeshCompiledDomainV1")
    if not isinstance(frame_packet, MC2DomainFramePacketV1):
        raise TypeError("frame_packet must be MC2DomainFramePacketV1")
    if not isinstance(substep_plan, MC2SubstepPlan):
        raise TypeError("substep_plan must be MC2SubstepPlan")
    program = compiled.program
    if (
        frame_packet.domain_signature != program.domain_signature
        or frame_packet.layout_signature != program.layout_signature
    ):
        raise ValueError("frame packet identity does not match compiled program")
    count = program.particle_count
    partitions = program.partition_count
    anchor = _validate_vector(
        anchor_component_local_positions,
        (partitions, 3),
        "anchor_component_local_positions",
    )
    step_positions = _validate_vector(
        step_basic_positions, (count, 3), "step_basic_positions"
    )
    step_rotations = _validate_vector(
        step_basic_rotations, (count, 4), "step_basic_rotations"
    )
    weights = _validate_vector(distance_weights, (partitions,), "distance_weights")
    partition = compiled.parameters.partition_parameters
    partition_uint = compiled.parameters.partition_uint_parameters
    particle = compiled.parameters.particle_parameters
    partition_fields = _table_fields(partition)
    uint_fields = _table_fields(partition_uint)
    particle_fields = _table_fields(particle)

    def partition_float(name):
        return _particle_partition_column(
            compiled, partition, partition_fields, name, dtype=np.float32
        )

    def partition_uint_value(name):
        return _particle_partition_column(
            compiled, partition_uint, uint_fields, name, dtype=np.uint32
        )

    motion_stiffness = partition_float("motion_stiffness")
    backstop_radii = partition_float("backstop_radius")
    settings = {
        "anchor_component_local_positions": anchor,
        "dt": float(substep_plan.simulation_delta_time),
        "frame_interpolation": float(substep_plan.frame_interpolation),
        "distance_weights": weights,
        "simulation_power": float(substep_plan.powers.integration),
        "distance_simulation_power": float(substep_plan.powers.distance_bending),
        "bending_simulation_power": float(substep_plan.powers.distance_bending),
        "step_basic_positions": step_positions,
        "tether_compression_values": partition_float("tether_compression_limit"),
        "tether_stretch_values": partition_float("tether_stretch_limit"),
        "step_basic_rotations": step_rotations,
        "angle_restoration_values": _scaled_particle_column(
            particle, particle_fields, "angle_restoration_stiffness",
            substep_plan.powers.angle,
        ),
        "angle_limit_values": _particle_column(
            particle, particle_fields, "angle_limit"
        ),
        "angle_restoration_velocity_attenuation_values": partition_float(
            "angle_restoration_velocity_attenuation"
        ),
        "angle_restoration_gravity_falloff_values": partition_float(
            "angle_restoration_gravity_falloff"
        ),
        "angle_limit_stiffness_values": partition_float("angle_limit_stiffness"),
        "angle_restoration_enabled_values": partition_uint_value(
            "use_angle_restoration"
        ),
        "angle_limit_enabled_values": partition_uint_value("use_angle_limit"),
        "motion_base_positions": frame_packet.animated_base_world_positions,
        "motion_base_rotations": frame_packet.animated_base_world_rotations,
        "motion_max_distances": _particle_column(
            particle, particle_fields, "max_distance"
        ),
        "motion_stiffness_values": motion_stiffness,
        "motion_backstop_radii": backstop_radii,
        "motion_backstop_distances": _particle_column(
            particle, particle_fields, "backstop_distance"
        ),
        "motion_normal_axis_values": _particle_partition_column(
            compiled, partition_uint, uint_fields, "normal_axis", dtype=np.int32
        ),
        "motion_max_distance_enabled_values": partition_uint_value("use_max_distance"),
        "motion_backstop_enabled_values": partition_uint_value("use_backstop"),
        "external_collision": external_collision,
        "post_step": {
            "dt": float(substep_plan.simulation_delta_time),
            "dynamic_friction_values": partition_float("collision_dynamic_friction"),
            "static_friction_speed_values": partition_float("collision_static_friction"),
            "particle_speed_limit_values": partition_float("particle_speed_limit"),
        },
    }
    return settings


__all__ = [
    "make_mc2_compiled_domain_pipeline_settings",
    "make_mc2_reference_pipeline_settings",
]
