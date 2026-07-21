"""E0 tests for the backend-neutral MC2 unified-domain contracts."""

from __future__ import annotations

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


FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "domain_pipeline",
    "schema_v1",
    "two_mesh_domain_v1.json",
)


def _load_fixture() -> dict:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
        fixture = json.load(handle)
    assert fixture["schema_version"] == ir.MC2_DOMAIN_IR_SCHEMA_VERSION
    return fixture


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
        particle_parameters=particles,
        constraint_parameters=constraints,
    )


def _build_frame(fixture: dict, program):
    return ir.make_mc2_domain_frame_packet(program, **fixture["frame"])


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
    assert first.parameter_signature != second.parameter_signature
    assert first.particle_parameters.row_count == program.particle_count


def test_frame_packet_preserves_per_partition_transform_and_signed_scale() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    frame = _build_frame(fixture, program)
    assert frame.partition_world_position[0].tolist() == [1.0, 0.0, 0.0]
    assert frame.partition_world_position[1].tolist() == [-2.0, 0.0, 0.0]
    assert frame.partition_world_scale[1].tolist() == [1.0, -1.0, 1.0]
    assert frame.anchor_present.tolist() == [1, 0]
    assert not frame.partition_world_linear.flags.writeable


def test_optional_frame_normals_and_output_rotations_are_explicitly_empty() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    frame_payload = json.loads(json.dumps(fixture["frame"]))
    frame_payload.pop("animated_base_world_normals")
    frame = ir.make_mc2_domain_frame_packet(program, **frame_payload)
    assert frame.animated_base_world_normals.shape == (0, 3)
    output = ir.make_mc2_domain_frame_output(
        program,
        frame,
        world_positions=fixture["frame"]["animated_base_world_positions"],
        backend_revision=3,
        backend_kind="cpu_reference",
    )
    assert output.world_rotations_xyzw.shape == (0, 4)


def test_frame_packet_rejects_singular_source_transform() -> None:
    fixture = _load_fixture()
    program = _build_program(fixture)
    bad_fixture = json.loads(json.dumps(fixture))
    bad_fixture["frame"]["partition_world_linear"][1][1][1] = 0.0
    try:
        _build_frame(bad_fixture, program)
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
    frame = _build_frame(fixture, program)
    physical_to_logical = [3, 4, 0, 1, 2]
    physical_positions = [
        fixture["frame"]["animated_base_world_positions"][index]
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
    frame = _build_frame(fixture, program)
    output = ir.make_mc2_domain_frame_output(
        program,
        frame,
        world_positions=fixture["frame"]["animated_base_world_positions"],
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
