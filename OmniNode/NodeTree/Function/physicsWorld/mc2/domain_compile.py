"""E1 single-partition compilation from a MeshCloth static fragment."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .domain_ir import MC2CompiledDomainProgramV1
from .domain_ir import MC2DomainParameterPacketV1
from .domain_ir import MC2OutputTargetV1
from .domain_ir import make_mc2_compiled_domain_program
from .domain_ir import make_mc2_constraint_topology_table
from .domain_ir import make_mc2_domain_parameter_packet
from .domain_ir import make_mc2_float_soa_table
from .domain_ir import make_mc2_span_view
from .domain_ir import make_mc2_primitive_topology_table
from .domain_ir import make_mc2_uint_soa_table
from .names import MC2_SETUP_MESH_CLOTH
from .runtime_parameters import MC2_RUNTIME_FLOAT_FIELDS
from .runtime_parameters import MC2_RUNTIME_INT_FIELDS
from .runtime_parameters import MC2_RUNTIME_CURVE_FIELDS
from .runtime_parameters import MC2RuntimeParametersV0
from .setups.mesh_cloth.static_fragment import MC2MeshStaticFragmentV1


@dataclass(frozen=True)
class MC2MeshCompiledDomainV1:
    fragment: MC2MeshStaticFragmentV1
    program: MC2CompiledDomainProgramV1
    parameters: MC2DomainParameterPacketV1
    effective_parameter_signature: str

    def __post_init__(self) -> None:
        if not isinstance(self.fragment, MC2MeshStaticFragmentV1):
            raise TypeError("fragment must be MC2MeshStaticFragmentV1")
        if not isinstance(self.program, MC2CompiledDomainProgramV1):
            raise TypeError("program must be MC2CompiledDomainProgramV1")
        if not isinstance(self.parameters, MC2DomainParameterPacketV1):
            raise TypeError("parameters must be MC2DomainParameterPacketV1")
        if not str(self.effective_parameter_signature or ""):
            raise ValueError("effective_parameter_signature cannot be empty")
        if self.program.partition_count != 1:
            raise ValueError("E1 Mesh compiled domain must contain one partition")
        if self.parameters.layout_signature != self.program.layout_signature:
            raise ValueError("compiled domain parameter layout does not match program")

    def debug_dict(self) -> dict:
        return {
            "domain_signature": self.program.domain_signature,
            "layout_signature": self.program.layout_signature,
            "parameter_layout_signature": self.parameters.parameter_layout_signature,
            "parameter_signature": self.parameters.parameter_signature,
            "effective_parameter_signature": self.effective_parameter_signature,
            "fragment": self.fragment.debug_dict(),
            "program": self.program.debug_dict(),
        }


def _sample_curve(values, depths, *, square_depth: bool = False) -> np.ndarray:
    curve = np.asarray(values, dtype=np.float32)
    depth = np.asarray(depths, dtype=np.float32)
    if curve.shape != (16,):
        raise ValueError("MC2 curve rows must contain 16 samples")
    if square_depth:
        depth = depth * depth
    scaled = np.clip(depth, 0.0, 1.0) * np.float32(15.0)
    lower = np.floor(scaled).astype(np.int32)
    upper = np.minimum(lower + 1, 15)
    ratio = scaled - lower.astype(np.float32)
    result = curve[lower] * (1.0 - ratio) + curve[upper] * ratio
    result = np.ascontiguousarray(result, dtype=np.float32)
    result.setflags(write=False)
    return result


def _runtime_maps(effective: MC2RuntimeParametersV0) -> tuple[dict, dict, dict]:
    if not isinstance(effective, MC2RuntimeParametersV0):
        raise TypeError("effective must be MC2RuntimeParametersV0")
    return (
        dict(zip(MC2_RUNTIME_FLOAT_FIELDS, effective.float_values)),
        dict(zip(MC2_RUNTIME_INT_FIELDS, effective.int_values)),
        dict(zip(MC2_RUNTIME_CURVE_FIELDS, effective.curve_values)),
    )


def _program_for_fragment(
    fragment: MC2MeshStaticFragmentV1,
    *,
    required_capabilities=(),
) -> MC2CompiledDomainProgramV1:
    proxy = fragment.final_proxy
    count = proxy.vertex_count
    particle_partition = np.zeros(count, dtype=np.uint32)
    source_elements = np.asarray(
        [int(value.split("v", 1)[1]) for value in proxy.vertex_identities],
        dtype=np.uint32,
    )
    bind_positions = np.asarray(
        fragment.finalizer.vertex_bind_pose_positions,
        dtype=np.float32,
    )
    bind_rotations = np.asarray(
        fragment.finalizer.vertex_bind_pose_rotations,
        dtype=np.float32,
    )
    attributes = np.asarray(proxy.vertex_attributes, dtype=np.uint32)

    constraint_tables = []
    distance = fragment.distance
    distance_rows = []
    distance_flags = []
    distance_owners = []
    for vertex, (start, length) in enumerate(distance.distance_ranges):
        for record in range(start, start + length):
            distance_rows.append((vertex, int(distance.distance_targets[record])))
            distance_flags.append(1 if distance.distance_rest_signed[record] < 0.0 else 0)
            distance_owners.append(0)
    if distance_rows:
        constraint_tables.append(
            make_mc2_constraint_topology_table(
                "distance", distance_rows, distance_owners, flags=distance_flags
            )
        )

    baseline = fragment.baseline.baseline
    tether_rows = []
    for vertex, root in enumerate(baseline.root_indices):
        root = int(root)
        if root >= 0 and root != vertex:
            tether_rows.append((vertex, root))
    if tether_rows:
        constraint_tables.append(
            make_mc2_constraint_topology_table(
                "tether", tether_rows, (0,) * len(tether_rows)
            )
        )

    if fragment.bending is not None and fragment.bending.record_count:
        constraint_tables.append(
            make_mc2_constraint_topology_table(
                "bending",
                fragment.bending.bending_quads,
                (0,) * fragment.bending.record_count,
                flags=tuple(
                    1 if value < 0 else 0
                    for value in fragment.bending.bending_sign_or_volume
                ),
            )
        )

    self_collision = fragment.self_collision
    primitive_tables = []
    cursor = 0
    for kind, width, amount in (
        ("point", 1, self_collision.point_count),
        ("edge", 2, self_collision.edge_count),
        ("triangle", 3, self_collision.triangle_count),
    ):
        rows = [
            tuple(int(value) for value in self_collision.particle_indices[index][:width])
            for index in range(cursor, cursor + amount)
        ]
        if rows:
            primitive_tables.append(
                make_mc2_primitive_topology_table(kind, rows, (0,) * len(rows))
            )
        cursor += amount

    target = MC2OutputTargetV1(
        target_id=fragment.output_target_id,
        partition_index=0,
        element_count=count,
        space_kind="mesh_object_local_offset",
    )
    return make_mc2_compiled_domain_program(
        domain_id=f"mc2.domain:{fragment.partition_id}",
        setup_type=MC2_SETUP_MESH_CLOTH,
        partition_ids=(fragment.partition_id,),
        partition_flags=(0x03,),
        partition_particle_views=(make_mc2_span_view(0, count),),
        particle_partition_index=particle_partition,
        particle_source_element=source_elements,
        particle_bind_position=bind_positions,
        particle_bind_rotation=bind_rotations,
        particle_attribute_flags=attributes,
        constraint_tables=tuple(constraint_tables),
        primitive_tables=tuple(primitive_tables),
        output_targets=(target,),
        output_target_index=(0,) * count,
        output_source_element=source_elements,
        required_capabilities=tuple(required_capabilities),
    )


def _parameter_packet_for_fragment(
    fragment: MC2MeshStaticFragmentV1,
    effective: MC2RuntimeParametersV0,
    program: MC2CompiledDomainProgramV1,
    *,
    collision_group: int = 1,
    collision_mask: int = 0xFFFF,
) -> MC2DomainParameterPacketV1:
    floats, ints, curves = _runtime_maps(effective)
    depths = np.asarray(fragment.baseline.baseline.depths, dtype=np.float32)
    domain_fields = ("gravity",)
    domain_values = [[floats["gravity"]]]
    partition_fields = tuple(name for name in MC2_RUNTIME_FLOAT_FIELDS if name != "gravity")
    partition_values = [[floats[name] for name in partition_fields]]
    uint_fields = MC2_RUNTIME_INT_FIELDS + ("collision_group", "collision_mask")
    uint_values = [[*(ints[name] for name in MC2_RUNTIME_INT_FIELDS), collision_group, collision_mask]]

    particle_fields = (
        "depth", "radius_multiplier", "radius", "damping", "distance_stiffness",
        "angle_restoration_stiffness", "angle_limit", "max_distance", "backstop_distance",
        "self_collision_thickness", "collision_limit_distance", "cloth_mass", "collision_friction",
    )
    particle_values = np.column_stack((
        depths,
        fragment.radius_multipliers,
        _sample_curve(curves["radius"], depths),
        _sample_curve(curves["damping"], depths),
        _sample_curve(curves["distance_stiffness"], depths),
        _sample_curve(curves["angle_restoration_stiffness"], depths),
        _sample_curve(curves["angle_limit"], depths),
        _sample_curve(curves["max_distance"], depths, square_depth=True),
        _sample_curve(curves["backstop_distance"], depths, square_depth=True),
        _sample_curve(curves["self_collision_thickness"], depths),
        _sample_curve(curves["collision_limit_distance"], depths),
        np.full(len(depths), floats["cloth_mass"], dtype=np.float32),
        np.full(len(depths), floats["collision_dynamic_friction"], dtype=np.float32),
    ))

    constraint_parameters = []
    distance_values = []
    for vertex, (start, length) in enumerate(fragment.distance.distance_ranges):
        for record in range(start, start + length):
            distance_values.append((
                abs(float(fragment.distance.distance_rest_signed[record])),
                float(_sample_curve(curves["distance_stiffness"], np.asarray((depths[vertex],)))[0]),
            ))
    if distance_values:
        constraint_parameters.append(
            make_mc2_float_soa_table("distance", ("rest_length", "stiffness"), distance_values)
        )

    tether_values = []
    positions = np.asarray(fragment.final_proxy.local_positions, dtype=np.float32)
    for row in program.constraint_tables:
        if row.kind != "tether":
            continue
        for first, second in row.indices:
            delta = positions[int(second)] - positions[int(first)]
            tether_values.append((float(np.linalg.norm(delta)), 1.0))
    if tether_values:
        constraint_parameters.append(
            make_mc2_float_soa_table("tether", ("rest_length", "stiffness"), tether_values)
        )

    if fragment.bending is not None and fragment.bending.record_count:
        constraint_parameters.append(
            make_mc2_float_soa_table(
                "bending",
                ("rest_value", "stiffness"),
                tuple(
                    (float(rest), float(floats["bending_stiffness"]))
                    for rest in fragment.bending.bending_rest_angle_or_volume
                ),
            )
        )

    return make_mc2_domain_parameter_packet(
        program,
        domain_scalars=make_mc2_float_soa_table("domain", domain_fields, domain_values),
        partition_parameters=make_mc2_float_soa_table(
            "partition", partition_fields, partition_values
        ),
        partition_uint_parameters=make_mc2_uint_soa_table(
            "partition_uint", uint_fields, uint_values
        ),
        particle_parameters=make_mc2_float_soa_table(
            "particle", particle_fields, particle_values
        ),
        constraint_parameters=tuple(constraint_parameters),
    )


def compile_mc2_mesh_static_fragment(
    fragment: MC2MeshStaticFragmentV1,
    effective: MC2RuntimeParametersV0,
    *,
    collision_group: int = 1,
    collision_mask: int = 0xFFFF,
) -> MC2MeshCompiledDomainV1:
    if not isinstance(fragment, MC2MeshStaticFragmentV1):
        raise TypeError("fragment must be MC2MeshStaticFragmentV1")
    if not isinstance(effective, MC2RuntimeParametersV0):
        raise TypeError("effective must be MC2RuntimeParametersV0")
    if (
        not 1 <= int(collision_group) <= 0x80000000
        or int(collision_group) & (int(collision_group) - 1)
    ):
        raise ValueError("collision_group must be one positive uint32 bit")
    if not 0 <= int(collision_mask) <= 0xFFFFFFFF:
        raise ValueError("collision_mask must fit uint32")
    required = ["mesh_cloth"]
    if effective.int_values[9] != 0 and fragment.self_collision.primitive_count:
        required.append("self_collision")
    program = _program_for_fragment(fragment, required_capabilities=tuple(required))
    parameters = _parameter_packet_for_fragment(
        fragment,
        effective,
        program,
        collision_group=int(collision_group),
        collision_mask=int(collision_mask),
    )
    return MC2MeshCompiledDomainV1(
        fragment=fragment,
        program=program,
        parameters=parameters,
        effective_parameter_signature=effective.parameter_signature,
    )


__all__ = [
    "MC2MeshCompiledDomainV1",
    "compile_mc2_mesh_static_fragment",
]
