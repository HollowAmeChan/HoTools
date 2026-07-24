"""E0 tests for the backend-neutral MC2 unified-domain contracts."""

from __future__ import annotations

from dataclasses import replace
import importlib
import json
import os
import sys
import types

import numpy as np


MC2_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD = os.path.dirname(MC2_ROOT)
FUNCTION = os.path.dirname(PHYSICS_WORLD)
NODETREE = os.path.dirname(FUNCTION)
OMNINODE = os.path.dirname(NODETREE)
HOTOOLS = os.path.dirname(OMNINODE)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PHYSICS_WORLD),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2", MC2_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

ir = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_ir"
)
domain_capabilities = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_capabilities"
)


FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "domain_pipeline",
    "two_mesh_static",
    "two_mesh_domain_v1.json",
)
SINGLE_FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "domain_pipeline",
    "single_mesh",
    "single_mesh_domain_v1.json",
)
FRAME_FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "domain_pipeline",
    "two_mesh_frames",
    "two_mesh_frames_v1.json",
)
MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "domain_pipeline",
    "schema_v1",
    "manifest.json",
)


def _load_fixture() -> dict:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
        fixture = json.load(handle)
    assert fixture["schema_version"] == ir.MC2_DOMAIN_IR_SCHEMA_VERSION
    return fixture


def _load_single_fixture() -> dict:
    with open(SINGLE_FIXTURE_PATH, "r", encoding="utf-8") as handle:
        fixture = json.load(handle)
    assert fixture["schema_version"] == ir.MC2_DOMAIN_IR_SCHEMA_VERSION
    return fixture


def _load_frame_fixture() -> dict:
    with open(FRAME_FIXTURE_PATH, "r", encoding="utf-8") as handle:
        fixture = json.load(handle)
    assert fixture["schema_version"] == ir.MC2_DOMAIN_IR_SCHEMA_VERSION
    return fixture


def test_fixture_manifest_resolves_every_e0_asset() -> None:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    assert manifest["schema_version"] == ir.MC2_DOMAIN_IR_SCHEMA_VERSION
    base = os.path.dirname(MANIFEST_PATH)
    assert all(
        os.path.isfile(os.path.normpath(os.path.join(base, relative)))
        for relative in manifest["fixtures"].values()
    )
    assert "MC2BackendCapabilitiesV1" in manifest["contracts"]


def _build_program(fixture: dict):
    payload = fixture["program"]
    views = tuple(
        ir.make_mc2_span_view(item["start"], item["stop"])
        if item["kind"] == "span"
        else ir.make_mc2_index_view(item["indices"])
        for item in payload["partition_particle_views"]
    )
    constraints = tuple(
        ir.make_mc2_constraint_topology_table(
            item["kind"],
            item["indices"],
            item["owner_partition_index"],
            flags=item["flags"],
        )
        for item in payload["constraint_tables"]
    )
    primitives = tuple(
        ir.make_mc2_primitive_topology_table(
            item["kind"], item["indices"], item["owner_partition_index"]
        )
        for item in payload["primitive_tables"]
    )
    targets = tuple(
        ir.MC2OutputTargetV1(**item) for item in payload["output_targets"]
    )
    return ir.make_mc2_compiled_domain_program(
        domain_id=payload["domain_id"],
        setup_type=payload["setup_type"],
        partition_ids=payload["partition_ids"],
        partition_flags=payload["partition_flags"],
        partition_particle_views=views,
        partition_center_local_position=payload["partition_center_local_position"],
        partition_initial_local_gravity_direction=(
            payload["partition_initial_local_gravity_direction"]
        ),
        particle_partition_index=payload["particle_partition_index"],
        particle_source_element=payload["particle_source_element"],
        particle_bind_position=payload["particle_bind_position"],
        particle_bind_rotation=payload["particle_bind_rotation"],
        particle_attribute_flags=payload["particle_attribute_flags"],
        constraint_tables=constraints,
        primitive_tables=primitives,
        output_targets=targets,
        output_target_index=payload["output_target_index"],
        output_source_element=payload["output_source_element"],
        required_capabilities=payload["required_capabilities"],
    )


def _build_static_snapshots(fixture: dict):
    return tuple(
        ir.make_mc2_mesh_partition_static_snapshot(**payload)
        for payload in fixture["static_snapshots"]
    )


def _build_parameters(fixture: dict, program):
    payload = fixture["parameters"]
    domain = ir.make_mc2_float_soa_table(
        "domain", payload["domain_scalars"]["fields"], payload["domain_scalars"]["values"]
    )
    partitions = ir.make_mc2_float_soa_table(
        "partition",
        payload["partition_parameters"]["fields"],
        payload["partition_parameters"]["values"],
    )
    partition_uints = ir.make_mc2_uint_soa_table(
        "partition_uint",
        payload["partition_uint_parameters"]["fields"],
        payload["partition_uint_parameters"]["values"],
    )
    particles = ir.make_mc2_float_soa_table(
        "particle",
        payload["particle_parameters"]["fields"],
        payload["particle_parameters"]["values"],
    )
    constraints = tuple(
        ir.make_mc2_float_soa_table(
            item["name"], item["fields"], item["values"]
        )
        for item in payload["constraint_parameters"]
    )
    return ir.make_mc2_domain_parameter_packet(
        program,
        domain_scalars=domain,
        partition_parameters=partitions,
        partition_uint_parameters=partition_uints,
        particle_parameters=particles,
        constraint_parameters=constraints,
    )


def _build_frame(program, frame_index: int = 0):
    fixture = _load_frame_fixture()
    return ir.make_mc2_domain_frame_packet(
        program, **fixture["frames"][frame_index]
    )


def test_fixture_builds_one_logical_domain_with_ordered_partitions() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    assert program.partition_ids == ("sleeve", "coat")
    assert program.partition_count == 2
    assert program.particle_count == 5
    assert program.partition_particle_views[0].resolved_indices().tolist() == [0, 1, 2]
    assert program.partition_particle_views[1].resolved_indices().tolist() == [3, 4]
    assert program.debug_dict()["constraint_tables"] == [
        {"kind": "distance", "record_count": 3, "allow_cross_partition": False},
        {"kind": "tether", "record_count": 1, "allow_cross_partition": False},
    ]
    assert program.domain_signature == _build_program(fixture).domain_signature
    assert program.layout_signature == _build_program(fixture).layout_signature


def test_backend_data_pass_contract_freezes_concrete_buffers_and_order() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    parameters = _build_parameters(fixture, program)
    contract = ir.make_mc2_backend_data_pass_contract(program, parameters)

    assert contract.layout_signature == program.layout_signature
    assert tuple(item.name for item in contract.passes) == (
        "prepare_step_basic",
        "task_reference_teleport",
        "center_frame_shift",
        "center",
        "center_inertia",
        "integration",
        "tether",
        "distance_a",
        "angle",
        "bending",
        "external_collision",
        "distance_b",
        "motion",
        "whole_domain_self",
        "post_history",
        "publish_output",
    )
    assert contract.buffer("program.particle_bind_position").logical_count == 5
    bind_position = contract.buffer("program.particle_bind_position")
    assert bind_position.components * np.dtype(bind_position.dtype).itemsize == 12
    assert contract.buffer("output.logical_world_position").hard_capacity == 5
    assert contract.buffer("frame.collider_center").hard_capacity is None

    primitive_counts = {
        table.kind: table.primitive_count for table in program.primitive_tables
    }
    edge_count = primitive_counts.get("edge", 0)
    expected_candidates = (
        edge_count * max(edge_count - 1, 0) // 2
        + primitive_counts.get("point", 0) * primitive_counts.get("triangle", 0)
    )
    assert (
        contract.buffer("transient.self_candidates").hard_capacity
        == expected_candidates
    )
    assert (
        contract.buffer("transient.self_contacts").hard_capacity
        == expected_candidates
    )
    assert contract.buffer("debug.self_intersections").hard_capacity == (
        edge_count * primitive_counts.get("triangle", 0)
    )
    whole_self = next(item for item in contract.passes if item.name == "whole_domain_self")
    assert "state.world_position" in set(whole_self.reads) & set(whole_self.writes)
    assert whole_self.condition == "capability:self_collision"


def test_backend_data_pass_contract_rejects_unknown_buffer_dependency() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    parameters = _build_parameters(fixture, program)
    contract = ir.make_mc2_backend_data_pass_contract(program, parameters)
    bad_pass = ir.MC2BackendPassSpecV1(
        name="bad",
        scope="substep",
        reads=("missing.buffer",),
        writes=(),
        depends_on=(),
    )
    try:
        ir.MC2BackendDataPassContractV1(
            layout_signature=program.layout_signature,
            buffers=contract.buffers,
            passes=(bad_pass,),
        )
    except ValueError as exc:
        assert "unknown buffers" in str(exc)
    else:
        raise AssertionError("backend contract accepted an unknown pass buffer")


def test_backend_upload_plan_emits_only_changed_contiguous_rows() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    parameters = _build_parameters(fixture, program)
    frame = _build_frame(program)

    initial = ir.make_mc2_backend_upload_plan(program, parameters, frame)
    assert initial.layout_rebuild is True
    assert initial.parameter_rebuild is True
    assert initial.program_spans and initial.parameter_spans and initial.frame_spans
    assert "program.particle_bind_position" in initial.reallocate_buffers
    assert "frame.collider_center" in initial.reallocate_buffers

    unchanged = ir.make_mc2_backend_upload_plan(
        program,
        parameters,
        frame,
        previous_program=program,
        previous_parameters=parameters,
        previous_frame_packet=frame,
    )
    assert unchanged.layout_rebuild is False
    assert unchanged.parameter_rebuild is False
    assert unchanged.reallocate_buffers == ()
    assert unchanged.program_spans == ()
    assert unchanged.parameter_spans == ()
    assert unchanged.frame_spans == ()

    particle_values = parameters.particle_parameters.values.copy()
    particle_values[1, 0] += np.float32(0.25)
    changed_particles = ir.make_mc2_float_soa_table(
        "particle",
        parameters.particle_parameters.fields,
        particle_values,
    )
    changed_parameters = ir.make_mc2_domain_parameter_packet(
        program,
        domain_scalars=parameters.domain_scalars,
        partition_parameters=parameters.partition_parameters,
        partition_uint_parameters=parameters.partition_uint_parameters,
        particle_parameters=changed_particles,
        constraint_parameters=parameters.constraint_parameters,
    )
    positions = frame.animated_base_world_positions.copy()
    positions[3, 0] += np.float32(1.0)
    positions.flags.writeable = False
    changed_frame = replace(frame, animated_base_world_positions=positions)
    changed = ir.make_mc2_backend_upload_plan(
        program,
        changed_parameters,
        changed_frame,
        previous_program=program,
        previous_parameters=parameters,
        previous_frame_packet=frame,
    )
    assert changed.layout_rebuild is False
    assert changed.parameter_rebuild is False
    assert changed.program_spans == ()
    assert [item.debug_dict() for item in changed.parameter_spans] == [{
        "buffer_name": "parameter.particle",
        "start": 1,
        "stop": 2,
        "reason": "parameter_dirty_span",
    }]
    assert [item.debug_dict() for item in changed.frame_spans] == [{
        "buffer_name": "frame.animated_base_position",
        "start": 3,
        "stop": 4,
        "reason": "frame_dirty_span",
    }]


def test_backend_upload_plan_reallocates_complete_collider_soa_on_count_change() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    parameters = _build_parameters(fixture, program)
    frame = _build_frame(program)
    colliders = {
        "collider_types": np.asarray((0,), dtype=np.int32),
        "collider_group_bits": np.asarray((1,), dtype=np.int32),
        "collider_centers": np.asarray(((0.0, 0.0, 0.0),), dtype=np.float32),
        "collider_segment_a": np.asarray(((0.0, 0.0, 0.0),), dtype=np.float32),
        "collider_segment_b": np.asarray(((0.0, 0.0, 0.0),), dtype=np.float32),
        "collider_old_centers": np.asarray(((0.0, 0.0, 0.0),), dtype=np.float32),
        "collider_old_segment_a": np.asarray(((0.0, 0.0, 0.0),), dtype=np.float32),
        "collider_old_segment_b": np.asarray(((0.0, 0.0, 0.0),), dtype=np.float32),
        "collider_radii": np.asarray((0.5,), dtype=np.float32),
    }
    plan = ir.make_mc2_backend_upload_plan(
        program,
        parameters,
        frame,
        collider_arrays=colliders,
        previous_program=program,
        previous_parameters=parameters,
        previous_frame_packet=frame,
    )
    collider_reallocations = tuple(
        name for name in plan.reallocate_buffers if name.startswith("frame.collider_")
    )
    assert len(collider_reallocations) == 9
    collider_spans = tuple(
        item for item in plan.frame_spans if item.buffer_name.startswith("frame.collider_")
    )
    assert len(collider_spans) == 9
    assert all((item.start, item.stop) == (0, 1) for item in collider_spans)


def test_backend_capacity_io_and_numerical_policies_are_closed() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    parameters = _build_parameters(fixture, program)
    contract = ir.make_mc2_backend_data_pass_contract(program, parameters)
    policies = ir.make_mc2_backend_dynamic_capacity_policies(contract)
    assert tuple(item.buffer_name for item in policies) == (
        "transient.self_candidates",
        "transient.self_contacts",
        "debug.self_intersections",
    )
    assert all(item.retry_limit == 1 for item in policies)
    assert all(item.publishes_state_before_capacity_fit is False for item in policies)
    assert all(
        item.overflow_policy == "rollback_substep_and_fail_without_publish"
        for item in policies
    )
    assert tuple(item.hard_capacity for item in policies) == tuple(
        contract.buffer(item.buffer_name).hard_capacity for item in policies
    )

    io = ir.MC2_BACKEND_IO_CONTRACT_V1
    assert io.substep_result_readback is False
    assert io.backend_may_access_blender is False
    assert io.result_readback_phase == "once_after_final_substep"
    assert io.publish_policy == "validate_all_targets_then_atomic_publish"
    numerical = ir.MC2_BACKEND_NUMERICAL_POLICY_V1
    assert numerical.position_atol == numerical.position_rtol == 5.0e-4
    assert numerical.velocity_atol == 2.0e-3
    assert numerical.velocity_rtol == 5.0e-3
    assert "candidate_contact_keys" in numerical.exact_channels
    assert "validity_and_teleport_flags" in numerical.exact_channels


def test_single_mesh_fixture_uses_the_same_program_contract() -> None:
    fixture = _load_single_fixture()
    snapshots = _build_static_snapshots(fixture)
    program = _build_program(fixture)
    assert len(snapshots) == program.partition_count == 1
    assert snapshots[0].partition_id == program.partition_ids[0] == "single"
    assert snapshots[0].vertex_count == program.particle_count == 3
    assert program.output_targets[0].target_id == snapshots[0].output_target_id


def test_unknown_program_schema_is_rejected_before_backend_allocation() -> None:
    program = _build_program(_load_single_fixture())
    try:
        replace(program, schema_version=99)
    except ValueError as exc:
        assert "schema version" in str(exc)
    else:
        raise AssertionError("unknown domain schema was accepted")


def test_static_snapshot_fixture_is_source_local_and_read_only() -> None:
    fixture = _load_fixture()
    snapshots = _build_static_snapshots(fixture)
    assert tuple(snapshot.partition_id for snapshot in snapshots) == ("sleeve", "coat")
    assert snapshots[0].vertex_count == 3
    assert snapshots[1].vertex_count == 2
    assert snapshots[0].has_uv is True and snapshots[1].has_uv is False
    assert snapshots[0].pin_present is True and snapshots[1].pin_present is False
    assert snapshots[1].pin_weights.shape == (0,)
    assert not snapshots[0].local_positions.flags.writeable
    assert not snapshots[1].edges.flags.writeable
    assert snapshots[0].static_signature == _build_static_snapshots(fixture)[0].static_signature


def test_static_snapshot_rejects_bad_loop_or_vertex_mapping() -> None:
    fixture = _load_fixture()
    payload = dict(fixture["static_snapshots"][0])
    payload["triangles"] = [[0, 1, 3]]
    try:
        ir.make_mc2_mesh_partition_static_snapshot(**payload)
    except ValueError as exc:
        assert "out-of-range vertex" in str(exc)
    else:
        raise AssertionError("out-of-range static triangle was accepted")

    payload = dict(fixture["static_snapshots"][0])
    payload["triangle_loops"] = [[0, 1, 3]]
    try:
        ir.make_mc2_mesh_partition_static_snapshot(**payload)
    except ValueError as exc:
        assert "out-of-range loop" in str(exc)
    else:
        raise AssertionError("out-of-range static loop was accepted")


def test_program_arrays_are_read_only_and_layout_excludes_bind_values() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    assert not program.particle_bind_position.flags.writeable
    assert not program.particle_partition_index.flags.writeable
    payload = fixture["program"]
    changed = dict(payload)
    changed["particle_bind_position"] = [
        [value + 10.0 for value in row]
        for row in payload["particle_bind_position"]
    ]
    changed_fixture = dict(fixture)
    changed_fixture["program"] = changed
    changed_program = _build_program(changed_fixture)
    assert changed_program.layout_signature == program.layout_signature
    assert changed_program.domain_signature != program.domain_signature


def test_structural_tables_reject_cross_partition_records() -> None:
    fixture = _load_fixture()
    payload = dict(fixture["program"])
    tables = [dict(item) for item in payload["constraint_tables"]]
    tables[0]["indices"] = [[0, 3], [1, 2], [3, 4]]
    payload["constraint_tables"] = tables
    bad_fixture = dict(fixture)
    bad_fixture["program"] = payload
    try:
        _build_program(bad_fixture)
    except ValueError as exc:
        assert "cross-partition" in str(exc)
    else:
        raise AssertionError("cross-partition structural constraint was accepted")


def test_overlapping_or_incomplete_particle_views_are_rejected() -> None:
    fixture = _load_fixture()
    payload = dict(fixture["program"])
    payload["partition_particle_views"] = [
        {"kind": "span", "start": 0, "stop": 3},
        {"kind": "span", "start": 2, "stop": 5},
    ]
    bad_fixture = dict(fixture)
    bad_fixture["program"] = payload
    try:
        _build_program(bad_fixture)
    except ValueError as exc:
        assert "overlap" in str(exc)
    else:
        raise AssertionError("overlapping views were accepted")


def test_parameter_packet_hot_update_keeps_layout_signature() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    first = _build_parameters(fixture, program)
    changed_fixture = json.loads(json.dumps(fixture))
    changed_fixture["parameters"]["particle_parameters"]["values"][0][1] = 0.04
    second = _build_parameters(changed_fixture, program)
    assert first.layout_signature == second.layout_signature == program.layout_signature
    assert first.parameter_layout_signature == second.parameter_layout_signature
    assert first.parameter_signature != second.parameter_signature
    assert first.particle_parameters.row_count == program.particle_count


def test_collision_filters_are_typed_hot_update_parameters() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    first = _build_parameters(fixture, program)
    assert first.partition_uint_parameters.fields == (
        "collision_group",
        "collision_mask",
    )
    assert first.partition_uint_parameters.values.tolist() == [[1, 2], [2, 1]]
    assert not first.partition_uint_parameters.values.flags.writeable

    changed_fixture = json.loads(json.dumps(fixture))
    changed_fixture["parameters"]["partition_uint_parameters"]["values"][1][1] = 0
    second = _build_parameters(changed_fixture, program)
    assert first.layout_signature == second.layout_signature
    assert first.parameter_layout_signature == second.parameter_layout_signature
    assert first.parameter_signature != second.parameter_signature


def test_parameter_field_schema_has_its_own_layout_signature() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    first = _build_parameters(fixture, program)
    changed_fixture = json.loads(json.dumps(fixture))
    changed_fixture["parameters"]["partition_uint_parameters"]["fields"][1] = (
        "collision_layer_mask"
    )
    second = _build_parameters(changed_fixture, program)
    assert first.layout_signature == second.layout_signature == program.layout_signature
    assert first.parameter_layout_signature != second.parameter_layout_signature
    assert first.parameter_signature != second.parameter_signature


def test_backend_capability_gate_runs_without_loading_a_backend() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    declarations = tuple(
        domain_capabilities.MC2BackendCapabilitiesV1(**payload)
        for payload in fixture["backend_capabilities"]
    )
    cpu = domain_capabilities.evaluate_mc2_backend_capabilities(
        program, declarations[0]
    )
    gpu = domain_capabilities.evaluate_mc2_backend_capabilities(
        program, declarations[1]
    )
    assert cpu.compatible is True and cpu.blockers == ()
    assert gpu.compatible is False
    assert gpu.blockers == ("capability:self_collision",)


def test_backend_capability_declaration_rejects_non_integer_limits() -> None:
    valid = {
        "backend_id": "invalid",
        "schema_versions": (1,),
        "setup_types": ("mesh_cloth",),
        "capabilities": ("mesh_cloth",),
        "max_particles": 100,
    }
    for field, value in (
        ("schema_versions", (1.0,)),
        ("max_particles", True),
        ("index_width_bits", 32.0),
    ):
        payload = dict(valid)
        payload[field] = value
        try:
            domain_capabilities.MC2BackendCapabilitiesV1(**payload)
        except ValueError:
            pass
        else:
            raise AssertionError(f"non-integer capability field accepted: {field}")


def test_frame_packet_preserves_per_partition_transform_and_signed_scale() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    frame = _build_frame(program)
    assert frame.partition_world_position[0].tolist() == [1.0, 0.0, 0.0]
    assert frame.partition_world_position[1].tolist() == [-2.0, 0.0, 0.0]
    assert frame.partition_world_scale[1].tolist() == [1.0, -1.0, 1.0]
    assert frame.anchor_present.tolist() == [1, 0]
    assert not frame.partition_world_linear.flags.writeable


def test_two_frame_fixture_keeps_partition_teleport_and_motion_independent() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    first = _build_frame(program)
    second = _build_frame(program, 1)
    assert (first.frame, second.frame, first.generation, second.generation) == (
        12, 13, 4, 4
    )
    assert first.partition_frame_flags.tolist() == [
        0,
        ir.MC2_PARTITION_FRAME_RESET,
    ]
    assert second.partition_frame_flags.tolist() == [
        ir.MC2_PARTITION_FRAME_KEEP,
        0,
    ]
    assert second.partition_world_position[0].tolist() == [5.0, 0.0, 0.0]
    assert (
        second.partition_world_position[1].tolist()
        == first.partition_world_position[1].tolist()
    )
    assert second.velocity_weight.tolist() == [0.0, 0.5]


def test_optional_frame_normals_and_output_rotations_are_explicitly_empty() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    frame_payload = json.loads(json.dumps(_load_frame_fixture()["frames"][0]))
    frame_payload.pop("animated_base_world_normals")
    frame = ir.make_mc2_domain_frame_packet(program, **frame_payload)
    assert frame.animated_base_world_normals.shape == (0, 3)
    output = ir.make_mc2_domain_frame_output(
        program,
        frame,
        world_positions=frame_payload["animated_base_world_positions"],
        backend_revision=3,
        backend_kind="cpu_reference",
    )
    assert output.world_rotations_xyzw.shape == (0, 4)


def test_frame_packet_rejects_singular_source_transform() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    bad_frame = json.loads(json.dumps(_load_frame_fixture()["frames"][0]))
    bad_frame["partition_world_linear"][1][1][1] = 0.0
    try:
        ir.make_mc2_domain_frame_packet(program, **bad_frame)
    except ValueError as exc:
        assert "invertible" in str(exc)
    else:
        raise AssertionError("singular partition transform was accepted")


def test_physical_permutation_is_separate_from_logical_program() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    identity = ir.make_mc2_physical_index_map([0, 1, 2, 3, 4])
    reordered = ir.make_mc2_physical_index_map([3, 4, 0, 1, 2])
    assert identity.logical_to_physical.tolist() == [0, 1, 2, 3, 4]
    assert reordered.physical_to_logical.tolist() == [3, 4, 0, 1, 2]
    assert reordered.logical_to_physical.tolist() == [2, 3, 4, 0, 1]
    assert program.layout_signature == _build_program(fixture).layout_signature


def test_output_envelope_accepts_physical_order_with_explicit_map() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    frame_fixture = _load_frame_fixture()["frames"][0]
    frame = _build_frame(program)
    physical_to_logical = [3, 4, 0, 1, 2]
    physical_positions = [
        frame_fixture["animated_base_world_positions"][index]
        for index in physical_to_logical
    ]
    output = ir.make_mc2_domain_frame_output(
        program,
        frame,
        world_positions=physical_positions,
        backend_revision=1,
        backend_kind="cpu_reference",
        index_order="physical",
        physical_to_logical=physical_to_logical,
    )
    assert output.index_order == "physical"
    assert output.physical_to_logical.tolist() == physical_to_logical
    assert output.timing_token is None


def test_output_timing_token_is_optional_and_not_implicit() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    frame_fixture = _load_frame_fixture()["frames"][0]
    frame = _build_frame(program)
    output = ir.make_mc2_domain_frame_output(
        program,
        frame,
        world_positions=frame_fixture["animated_base_world_positions"],
        backend_revision=2,
        backend_kind="cpu_reference",
        timing_token="hotspot:frame-12",
    )
    assert output.timing_token == "hotspot:frame-12"


if __name__ == "__main__":
    passed = 0
    for test_name, test in sorted(globals().items()):
        if test_name.startswith("test_") and callable(test):
            test()
            passed += 1
            print(f"PASS {test_name}")
    print(f"MC2 domain IR: {passed} passed")
