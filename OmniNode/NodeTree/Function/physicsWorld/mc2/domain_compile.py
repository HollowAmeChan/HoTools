"""Backend-neutral MeshCloth domain compilation from ordered static fragments."""

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
    fragments: tuple[MC2MeshStaticFragmentV1, ...]
    program: MC2CompiledDomainProgramV1
    parameters: MC2DomainParameterPacketV1
    effective_parameter_signatures: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.fragments or any(
            not isinstance(fragment, MC2MeshStaticFragmentV1)
            for fragment in self.fragments
        ):
            raise TypeError("fragments must contain MC2MeshStaticFragmentV1")
        if not isinstance(self.program, MC2CompiledDomainProgramV1):
            raise TypeError("program must be MC2CompiledDomainProgramV1")
        if not isinstance(self.parameters, MC2DomainParameterPacketV1):
            raise TypeError("parameters must be MC2DomainParameterPacketV1")
        if len(self.effective_parameter_signatures) != len(self.fragments) or any(
            not str(signature or "")
            for signature in self.effective_parameter_signatures
        ):
            raise ValueError("effective parameter signatures must match fragments")
        if self.program.partition_count != len(self.fragments):
            raise ValueError("compiled domain partitions must match fragments")
        if self.program.partition_ids != tuple(
            fragment.partition_id for fragment in self.fragments
        ):
            raise ValueError("compiled domain partition order must match fragments")
        if self.parameters.layout_signature != self.program.layout_signature:
            raise ValueError("compiled domain parameter layout does not match program")

    @property
    def single_fragment(self) -> MC2MeshStaticFragmentV1:
        if len(self.fragments) != 1:
            raise ValueError("compiled domain does not contain exactly one fragment")
        return self.fragments[0]

    @property
    def fragment(self) -> MC2MeshStaticFragmentV1:
        """E1 compatibility view; multi-partition callers must use fragments."""
        return self.single_fragment

    @property
    def single_effective_parameter_signature(self) -> str:
        if len(self.effective_parameter_signatures) != 1:
            raise ValueError("compiled domain does not contain exactly one parameter set")
        return self.effective_parameter_signatures[0]

    @property
    def effective_parameter_signature(self) -> str:
        """E1 compatibility view for the single-partition shadow path."""
        return self.single_effective_parameter_signature

    def debug_dict(self) -> dict:
        return {
            "domain_signature": self.program.domain_signature,
            "layout_signature": self.program.layout_signature,
            "parameter_layout_signature": self.parameters.parameter_layout_signature,
            "parameter_signature": self.parameters.parameter_signature,
            "effective_parameter_signatures": list(self.effective_parameter_signatures),
            "fragments": [fragment.debug_dict() for fragment in self.fragments],
            "program": self.program.debug_dict(),
        }


@dataclass(frozen=True)
class MC2DomainCompileCacheReportV1:
    previous_partition_ids: tuple[str, ...]
    partition_ids: tuple[str, ...]
    added_partition_ids: tuple[str, ...]
    removed_partition_ids: tuple[str, ...]
    common_order_changed: bool
    layout_cache_hit: bool
    program_cache_hit: bool
    parameter_layout_cache_hit: bool
    parameter_value_cache_hit: bool

    @property
    def exact_cache_hit(self) -> bool:
        return self.program_cache_hit and self.parameter_value_cache_hit

    def debug_dict(self) -> dict:
        return {
            "previous_partition_ids": list(self.previous_partition_ids),
            "partition_ids": list(self.partition_ids),
            "added_partition_ids": list(self.added_partition_ids),
            "removed_partition_ids": list(self.removed_partition_ids),
            "common_order_changed": self.common_order_changed,
            "layout_cache_hit": self.layout_cache_hit,
            "program_cache_hit": self.program_cache_hit,
            "parameter_layout_cache_hit": self.parameter_layout_cache_hit,
            "parameter_value_cache_hit": self.parameter_value_cache_hit,
            "exact_cache_hit": self.exact_cache_hit,
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


def _bending_marker_flag(sign: int) -> int:
    """Encode MC2's signed dihedral/volume marker losslessly in uint flags."""
    value = int(sign)
    return 100 if value == 100 else (1 if value < 0 else 0)


def _runtime_maps(effective: MC2RuntimeParametersV0) -> tuple[dict, dict, dict]:
    if not isinstance(effective, MC2RuntimeParametersV0):
        raise TypeError("effective must be MC2RuntimeParametersV0")
    return (
        dict(zip(MC2_RUNTIME_FLOAT_FIELDS, effective.float_values)),
        dict(zip(MC2_RUNTIME_INT_FIELDS, effective.int_values)),
        dict(zip(MC2_RUNTIME_CURVE_FIELDS, effective.curve_values)),
    )


def _source_elements(fragment: MC2MeshStaticFragmentV1) -> np.ndarray:
    values = []
    for identity in fragment.final_proxy.vertex_identities:
        prefix, marker, suffix = str(identity).rpartition("v")
        if not marker or not prefix.endswith(":") or not suffix.isdigit():
            raise ValueError(f"unsupported Mesh particle identity: {identity!r}")
        values.append(int(suffix))
    return np.asarray(values, dtype=np.uint32)


def _fragment_offsets(
    fragments: tuple[MC2MeshStaticFragmentV1, ...],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    starts = []
    counts = []
    cursor = 0
    for fragment in fragments:
        count = int(fragment.final_proxy.vertex_count)
        starts.append(cursor)
        counts.append(count)
        cursor += count
    return tuple(starts), tuple(counts)


def _program_for_fragments(
    fragments: tuple[MC2MeshStaticFragmentV1, ...],
    *,
    domain_id: str,
    required_capabilities=(),
) -> MC2CompiledDomainProgramV1:
    starts, counts = _fragment_offsets(fragments)
    particle_partition = np.concatenate(tuple(
        np.full(count, partition_index, dtype=np.uint32)
        for partition_index, count in enumerate(counts)
    ))
    source_elements = np.concatenate(tuple(_source_elements(fragment) for fragment in fragments))
    bind_positions = np.concatenate(tuple(
        np.asarray(fragment.finalizer.vertex_bind_pose_positions, dtype=np.float32)
        for fragment in fragments
    ))
    bind_rotations = np.concatenate(tuple(
        np.asarray(fragment.finalizer.vertex_bind_pose_rotations, dtype=np.float32)
        for fragment in fragments
    ))
    attributes = np.concatenate(tuple(
        np.asarray(fragment.final_proxy.vertex_attributes, dtype=np.uint32)
        for fragment in fragments
    ))

    constraint_rows = {"distance": [], "tether": [], "bending": []}
    constraint_flags = {"distance": [], "tether": [], "bending": []}
    constraint_owners = {"distance": [], "tether": [], "bending": []}
    for partition_index, (fragment, offset) in enumerate(zip(fragments, starts)):
        distance = fragment.distance
        for vertex, (start, length) in enumerate(distance.distance_ranges):
            for record in range(start, start + length):
                constraint_rows["distance"].append((
                    offset + vertex,
                    offset + int(distance.distance_targets[record]),
                ))
                constraint_flags["distance"].append(
                    1 if distance.distance_rest_signed[record] < 0.0 else 0
                )
                constraint_owners["distance"].append(partition_index)

        for vertex, root in enumerate(fragment.baseline.baseline.root_indices):
            root = int(root)
            if root >= 0 and root != vertex:
                constraint_rows["tether"].append((offset + vertex, offset + root))
                constraint_flags["tether"].append(0)
                constraint_owners["tether"].append(partition_index)

        if fragment.bending is not None:
            for row, sign in zip(
                fragment.bending.bending_quads,
                fragment.bending.bending_sign_or_volume,
            ):
                constraint_rows["bending"].append(
                    tuple(offset + int(value) for value in row)
                )
                constraint_flags["bending"].append(_bending_marker_flag(sign))
                constraint_owners["bending"].append(partition_index)

    constraint_tables = tuple(
        make_mc2_constraint_topology_table(
            kind,
            constraint_rows[kind],
            constraint_owners[kind],
            flags=constraint_flags[kind],
        )
        for kind in ("distance", "tether", "bending")
        if constraint_rows[kind]
    )

    primitive_rows = {"point": [], "edge": [], "triangle": []}
    primitive_owners = {"point": [], "edge": [], "triangle": []}
    for partition_index, (fragment, offset) in enumerate(zip(fragments, starts)):
        self_collision = fragment.self_collision
        cursor = 0
        for kind, width, amount in (
            ("point", 1, self_collision.point_count),
            ("edge", 2, self_collision.edge_count),
            ("triangle", 3, self_collision.triangle_count),
        ):
            for index in range(cursor, cursor + amount):
                primitive_rows[kind].append(tuple(
                    offset + int(value)
                    for value in self_collision.particle_indices[index][:width]
                ))
                primitive_owners[kind].append(partition_index)
            cursor += amount
    primitive_tables = tuple(
        make_mc2_primitive_topology_table(
            kind, primitive_rows[kind], primitive_owners[kind]
        )
        for kind in ("point", "edge", "triangle")
        if primitive_rows[kind]
    )

    baseline_parents = []
    baseline_starts = []
    baseline_counts = []
    baseline_data = []
    for fragment, offset in zip(fragments, starts):
        baseline = fragment.baseline.baseline
        parents = np.asarray(baseline.parent_indices, dtype=np.int32)
        ranges = np.asarray(baseline.baseline_ranges, dtype=np.int32)
        if ranges.size == 0:
            ranges = np.empty((0, 2), dtype=np.int32)
        data = np.asarray(baseline.baseline_data, dtype=np.int32)
        if parents.shape != (len(fragment.final_proxy.local_positions),):
            raise ValueError("Mesh baseline parent_indices must cover every particle")
        if ranges.ndim != 2 or ranges.shape[1] != 2:
            raise ValueError("Mesh baseline ranges must be int32 pairs")
        baseline_parents.extend(
            int(parent) + offset if int(parent) >= 0 else -1 for parent in parents
        )
        data_offset = len(baseline_data)
        baseline_starts.extend(data_offset + int(row[0]) for row in ranges)
        baseline_counts.extend(int(row[1]) for row in ranges)
        baseline_data.extend(int(value) + offset for value in data)

    output_targets = tuple(
        MC2OutputTargetV1(
            target_id=fragment.output_target_id,
            partition_index=partition_index,
            element_count=count,
            space_kind="mesh_object_local_offset",
        )
        for partition_index, (fragment, count) in enumerate(zip(fragments, counts))
    )
    return make_mc2_compiled_domain_program(
        domain_id=domain_id,
        setup_type=MC2_SETUP_MESH_CLOTH,
        partition_ids=tuple(fragment.partition_id for fragment in fragments),
        partition_flags=(0x03,) * len(fragments),
        partition_particle_views=tuple(
            make_mc2_span_view(start, start + count)
            for start, count in zip(starts, counts)
        ),
        partition_center_local_position=tuple(
            fragment.center.local_center_position for fragment in fragments
        ),
        partition_initial_local_gravity_direction=tuple(
            fragment.center.initial_local_gravity_direction for fragment in fragments
        ),
        particle_partition_index=particle_partition,
        particle_source_element=source_elements,
        particle_bind_position=bind_positions,
        particle_bind_rotation=bind_rotations,
        particle_attribute_flags=attributes,
        constraint_tables=constraint_tables,
        primitive_tables=primitive_tables,
        output_targets=output_targets,
        output_target_index=np.concatenate(tuple(
            np.full(count, partition_index, dtype=np.uint32)
            for partition_index, count in enumerate(counts)
        )),
        output_source_element=source_elements,
        required_capabilities=tuple(required_capabilities),
        baseline_parent_indices=np.asarray(baseline_parents, dtype=np.int32),
        baseline_line_start=np.asarray(baseline_starts, dtype=np.int32),
        baseline_line_count=np.asarray(baseline_counts, dtype=np.int32),
        baseline_line_data=np.asarray(baseline_data, dtype=np.int32),
    )


def _parameter_packet_for_fragments(
    fragments: tuple[MC2MeshStaticFragmentV1, ...],
    effectives: tuple[MC2RuntimeParametersV0, ...],
    program: MC2CompiledDomainProgramV1,
    *,
    collision_groups: tuple[int, ...],
    collision_masks: tuple[int, ...],
) -> MC2DomainParameterPacketV1:
    runtime_maps = tuple(_runtime_maps(effective) for effective in effectives)
    partition_fields = MC2_RUNTIME_FLOAT_FIELDS
    partition_values = [
        [floats[name] for name in partition_fields]
        for floats, _ints, _curves in runtime_maps
    ]
    uint_fields = MC2_RUNTIME_INT_FIELDS + ("collision_group", "collision_mask")
    uint_values = [
        [
            *(ints[name] for name in MC2_RUNTIME_INT_FIELDS),
            collision_group,
            collision_mask,
        ]
        for (_floats, ints, _curves), collision_group, collision_mask in zip(
            runtime_maps, collision_groups, collision_masks
        )
    ]

    particle_fields = (
        "depth", "radius_multiplier", "radius", "damping", "distance_stiffness",
        "angle_restoration_stiffness", "angle_limit", "max_distance", "backstop_distance",
        "self_collision_thickness", "collision_limit_distance", "cloth_mass", "collision_friction",
    )
    particle_blocks = []
    for fragment, (floats, _ints, curves) in zip(fragments, runtime_maps):
        depths = np.asarray(fragment.baseline.baseline.depths, dtype=np.float32)
        particle_blocks.append(np.column_stack((
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
            np.full(
                len(depths), floats["collision_dynamic_friction"], dtype=np.float32
            ),
        )))
    particle_values = np.concatenate(tuple(particle_blocks))

    constraint_values = {"distance": [], "tether": [], "bending": []}
    for fragment, (floats, _ints, curves) in zip(fragments, runtime_maps):
        depths = np.asarray(fragment.baseline.baseline.depths, dtype=np.float32)
        distance_stiffness = _sample_curve(curves["distance_stiffness"], depths)
        for vertex, (start, length) in enumerate(fragment.distance.distance_ranges):
            for record in range(start, start + length):
                constraint_values["distance"].append((
                    abs(float(fragment.distance.distance_rest_signed[record])),
                    float(distance_stiffness[vertex]),
                ))

        positions = np.asarray(fragment.final_proxy.local_positions, dtype=np.float32)
        for vertex, root in enumerate(fragment.baseline.baseline.root_indices):
            root = int(root)
            if root >= 0 and root != vertex:
                delta = positions[root] - positions[vertex]
                constraint_values["tether"].append((float(np.linalg.norm(delta)), 1.0))

        if fragment.bending is not None:
            constraint_values["bending"].extend(
                (float(rest), float(floats["bending_stiffness"]))
                for rest in fragment.bending.bending_rest_angle_or_volume
            )

    constraint_parameters = []
    if constraint_values["distance"]:
        constraint_parameters.append(make_mc2_float_soa_table(
            "distance", ("rest_length", "stiffness"), constraint_values["distance"]
        ))
    if constraint_values["tether"]:
        constraint_parameters.append(make_mc2_float_soa_table(
            "tether", ("rest_length", "stiffness"), constraint_values["tether"]
        ))
    if constraint_values["bending"]:
        constraint_parameters.append(make_mc2_float_soa_table(
            "bending", ("rest_value", "stiffness"), constraint_values["bending"]
        ))

    return make_mc2_domain_parameter_packet(
        program,
        domain_scalars=make_mc2_float_soa_table("domain", (), ((),)),
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


def _validated_collision_groups(count: int, values) -> tuple[int, ...]:
    if values is None:
        if count > 32:
            raise ValueError("automatic collision groups support at most 32 partitions")
        values = tuple(1 << index for index in range(count))
    result = tuple(values)
    if len(result) != count:
        raise ValueError("collision_groups must match fragment count")
    for value in result:
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise TypeError("collision_group values must be integers")
        value = int(value)
        if not 1 <= value <= 0x80000000 or value & (value - 1):
            raise ValueError("collision_group must be one positive uint32 bit")
    return tuple(int(value) for value in result)


def _validated_collision_masks(count: int, values) -> tuple[int, ...]:
    result = (0xFFFFFFFF,) * count if values is None else tuple(values)
    if len(result) != count:
        raise ValueError("collision_masks must match fragment count")
    for value in result:
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise TypeError("collision_mask values must be integers")
        if not 0 <= int(value) <= 0xFFFFFFFF:
            raise ValueError("collision_mask must fit uint32")
    return tuple(int(value) for value in result)


def compile_mc2_mesh_static_fragments(
    fragments,
    effectives,
    *,
    domain_id: str | None = None,
    collision_groups=None,
    collision_masks=None,
) -> MC2MeshCompiledDomainV1:
    fragments = tuple(fragments)
    effectives = tuple(effectives)
    if not fragments:
        raise ValueError("Mesh domain compile requires at least one fragment")
    if any(not isinstance(fragment, MC2MeshStaticFragmentV1) for fragment in fragments):
        raise TypeError("fragments must contain MC2MeshStaticFragmentV1")
    if len(effectives) != len(fragments) or any(
        not isinstance(effective, MC2RuntimeParametersV0) for effective in effectives
    ):
        raise TypeError("effectives must match fragments with MC2RuntimeParametersV0")
    partition_ids = tuple(fragment.partition_id for fragment in fragments)
    if len(set(partition_ids)) != len(partition_ids):
        raise ValueError("Mesh domain partition ids must be unique")
    target_ids = tuple(fragment.output_target_id for fragment in fragments)
    if len(set(target_ids)) != len(target_ids):
        raise ValueError("Mesh domain output target ids must be unique")
    groups = _validated_collision_groups(len(fragments), collision_groups)
    masks = _validated_collision_masks(len(fragments), collision_masks)
    resolved_domain_id = domain_id or f"mc2.domain:{'|'.join(partition_ids)}"

    required = ["mesh_cloth"]
    self_mode_index = MC2_RUNTIME_INT_FIELDS.index("self_collision_mode")
    if any(
        effective.int_values[self_mode_index] != 0
        and fragment.self_collision.primitive_count
        for fragment, effective in zip(fragments, effectives)
    ):
        required.append("self_collision")
    program = _program_for_fragments(
        fragments,
        domain_id=resolved_domain_id,
        required_capabilities=tuple(required),
    )
    parameters = _parameter_packet_for_fragments(
        fragments,
        effectives,
        program,
        collision_groups=groups,
        collision_masks=masks,
    )
    return MC2MeshCompiledDomainV1(
        fragments=fragments,
        program=program,
        parameters=parameters,
        effective_parameter_signatures=tuple(
            effective.parameter_signature for effective in effectives
        ),
    )


def compile_mc2_mesh_static_fragment(
    fragment: MC2MeshStaticFragmentV1,
    effective: MC2RuntimeParametersV0,
    *,
    collision_group: int = 1,
    collision_mask: int = 0xFFFF,
) -> MC2MeshCompiledDomainV1:
    return compile_mc2_mesh_static_fragments(
        (fragment,),
        (effective,),
        collision_groups=(collision_group,),
        collision_masks=(collision_mask,),
    )


def compare_mc2_domain_compile_cache(
    previous: MC2MeshCompiledDomainV1 | None,
    current: MC2MeshCompiledDomainV1,
) -> MC2DomainCompileCacheReportV1:
    if previous is not None and not isinstance(previous, MC2MeshCompiledDomainV1):
        raise TypeError("previous must be MC2MeshCompiledDomainV1 or None")
    if not isinstance(current, MC2MeshCompiledDomainV1):
        raise TypeError("current must be MC2MeshCompiledDomainV1")
    previous_ids = previous.program.partition_ids if previous is not None else ()
    current_ids = current.program.partition_ids
    added = tuple(value for value in current_ids if value not in previous_ids)
    removed = tuple(value for value in previous_ids if value not in current_ids)
    previous_common = tuple(value for value in previous_ids if value in current_ids)
    current_common = tuple(value for value in current_ids if value in previous_ids)
    return MC2DomainCompileCacheReportV1(
        previous_partition_ids=previous_ids,
        partition_ids=current_ids,
        added_partition_ids=added,
        removed_partition_ids=removed,
        common_order_changed=previous_common != current_common,
        layout_cache_hit=(
            previous is not None
            and previous.program.layout_signature == current.program.layout_signature
        ),
        program_cache_hit=(
            previous is not None
            and previous.program.domain_signature == current.program.domain_signature
        ),
        parameter_layout_cache_hit=(
            previous is not None
            and previous.parameters.parameter_layout_signature
            == current.parameters.parameter_layout_signature
        ),
        parameter_value_cache_hit=(
            previous is not None
            and previous.parameters.parameter_signature
            == current.parameters.parameter_signature
        ),
    )


__all__ = [
    "MC2DomainCompileCacheReportV1",
    "MC2MeshCompiledDomainV1",
    "compare_mc2_domain_compile_cache",
    "compile_mc2_mesh_static_fragment",
    "compile_mc2_mesh_static_fragments",
]
