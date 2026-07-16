"""Tier A source fixtures for MC2 DistanceConstraint static data."""

from __future__ import annotations

import glob
import importlib
import json
import math
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

static_data = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.static_data"
)
distance_static = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.distance_static"
)


FIXTURE_DIRECTORY = os.path.join(os.path.dirname(__file__), "fixtures", "tier_a")
EXPECTED_COMMIT = "418f89ff31a45bb4b2336641ad5907a1110eabea"
EXPECTED_UNITY = "6000.3.15f1"
EXPECTED_PRODUCERS = [
    "Runtime/Cloth/Constraints/DistanceConstraint.cs::CreateData",
    "Runtime/Utility/Data/DataUtility.cs::Pack12_20",
]


def _fixtures():
    paths = sorted(
        path
        for path in glob.glob(os.path.join(FIXTURE_DIRECTORY, "distance_*.json"))
        if not os.path.basename(path).startswith("distance_runtime_")
    )
    assert len(paths) == 7, paths
    result = {}
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            fixture = json.load(handle)
        source = fixture["source"]
        assert source["oracle_tier"] == "A"
        assert source["version"] == "2.18.1"
        assert source["commit"] == EXPECTED_COMMIT
        assert source["unity_editor"] == EXPECTED_UNITY
        assert source["producer"] == EXPECTED_PRODUCERS
        result[fixture["case_id"]] = fixture
    return result


def _runtime_fixtures():
    paths = sorted(glob.glob(os.path.join(FIXTURE_DIRECTORY, "distance_runtime_*.json")))
    assert len(paths) == 2, paths
    result = {}
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            fixture = json.load(handle)
        source = fixture["source"]
        assert source["oracle_tier"] == "A"
        assert source["version"] == "2.18.1"
        assert source["commit"] == EXPECTED_COMMIT
        assert source["unity_editor"] == EXPECTED_UNITY
        assert source["producer"] == [
            "Runtime/Cloth/Constraints/DistanceConstraint.cs::SolverConstraint"
        ]
        result[fixture["case_id"]] = fixture
    return result


def _records(fixture):
    expected = fixture["expected"]
    ranges = expected["distance_ranges"]
    targets = expected["distance_targets"]
    rests = expected["distance_rest_signed"]
    result = []
    for start, count in ranges:
        records = [
            (int(targets[index]), float(rests[index]))
            for index in range(start, start + count)
        ]
        result.append(tuple(sorted(records)))
    return tuple(result)


def _has_record(records, target, rest):
    return any(
        item_target == target
        and math.isclose(item_rest, rest, abs_tol=1.0e-6, rel_tol=1.0e-6)
        for item_target, item_rest in records
    )


def _build(fixture, *, native_context=None):
    payload = fixture["input"]
    count = len(payload["local_positions"])
    proxy = static_data.make_mc2_proxy_static_spec(
        task_id="mc2:mesh_cloth:" + fixture["case_id"],
        setup_type=payload["setup_type"],
        vertex_identities=[f"mesh:v{index}" for index in range(count)],
        local_positions=payload["local_positions"],
        local_normals=[[0, 0, 1] for _ in range(count)],
        local_tangents=[[1, 0, 0] for _ in range(count)],
        uvs=[[0, 0] for _ in range(count)],
        vertex_attributes=payload["vertex_attributes"],
        edges=payload["edges"],
        triangles=payload["triangles"],
    )
    adjacency = payload["vertex_to_vertex"]
    ranges = []
    data = []
    for values in adjacency:
        ranges.append((len(data), len(values)))
        data.extend(values)
    parents = tuple(payload["parent_indices"])
    children = [[] for _ in range(count)]
    for child, parent in enumerate(parents):
        if parent >= 0:
            children[parent].append(child)
    child_ranges = []
    child_data = []
    for values in children:
        child_ranges.append((len(child_data), len(values)))
        child_data.extend(values)
    baseline = static_data.make_mc2_baseline_static_spec(
        proxy_signature=proxy.proxy_signature,
        vertex_count=count,
        parent_indices=parents,
        child_ranges=child_ranges,
        child_data=child_data,
        baseline_flags=(),
        baseline_ranges=(),
        baseline_data=(),
        root_indices=(-1,) * count,
        depths=(0.0,) * count,
        vertex_local_positions=((0.0, 0.0, 0.0),) * count,
        vertex_local_rotations=((0.0, 0.0, 0.0, 0.0),) * count,
    )
    return distance_static.build_mc2_distance_static(
        proxy,
        baseline,
        vertex_to_vertex_ranges=ranges,
        vertex_to_vertex_data=data,
        native_context=native_context,
    )


def test_distance_fixture_contract_and_packed_ranges() -> None:
    for fixture in _fixtures().values():
        expected = fixture["expected"]
        packed = expected["raw_packed_indices"]
        ranges = expected["distance_ranges"]
        targets = expected["distance_targets"]
        rests = expected["distance_rest_signed"]
        assert len(targets) == len(rests), fixture["case_id"]
        assert all(math.isfinite(float(value)) for value in rests)
        assert len(packed) == len(ranges)
        for raw, wanted in zip(packed, ranges):
            assert [(raw & 0xFFFFF), ((raw >> 20) & 0xFFF)] == wanted
        if ranges:
            cursor = 0
            for start, count in ranges:
                assert start == cursor
                assert 0 <= count <= 0xFFF
                cursor += count
            assert cursor == len(targets)
            assert all(0 <= target <= 0xFFFF for target in targets)
        else:
            assert targets == []
            assert rests == []


def test_distance_fixtures_lock_source_build_facts() -> None:
    fixtures = _fixtures()

    parent = _records(fixtures["distance_parent_horizontal_001"])
    assert tuple(tuple(target for target, _rest in group) for group in parent) == (
        (1, 2),
        (0, 2),
        (0, 1),
    )
    assert _has_record(parent[0], 1, 1.0)
    assert _has_record(parent[0], 2, 1.0)
    assert _has_record(parent[1], 2, -math.sqrt(2.0))
    assert _has_record(parent[2], 1, -math.sqrt(2.0))

    square = _records(fixtures["distance_square_shear_001"])
    assert _has_record(square[0], 3, -math.sqrt(2.0))
    assert _has_record(square[3], 0, -math.sqrt(2.0))
    assert sum(len(records) for records in square) == 12

    for case_id in (
        "distance_shear_normal_reject_001",
        "distance_shear_ratio_reject_001",
    ):
        rejected = _records(fixtures[case_id])
        assert all(target != 3 for target, _rest in rejected[0])
        assert all(target != 0 for target, _rest in rejected[3])
        assert sum(len(records) for records in rejected) == 10

    invalid = _records(fixtures["distance_invalid_filters_001"])
    assert len(invalid[0]) == 1
    assert _has_record(invalid[0], 3, -math.sqrt(2.0))
    assert _has_record(invalid[3], 0, -math.sqrt(2.0))
    assert all(target != 0 for target, _rest in invalid[1])
    assert all(target != 0 for target, _rest in invalid[2])

    empty = fixtures["distance_all_fixed_empty_001"]["expected"]
    assert empty == {
        "raw_packed_indices": [],
        "distance_ranges": [],
        "distance_targets": [],
        "distance_rest_signed": [],
    }

    zero = fixtures["distance_zero_kind_loss_001"]["expected"]
    assert len(zero["distance_rest_signed"]) == 6
    assert all(float(value) == 0.0 for value in zero["distance_rest_signed"])
    assert all(
        math.copysign(1.0, float(value)) > 0.0
        for value in zero["distance_rest_signed"]
    )


def test_distance_runtime_fixtures_prove_order_is_semantic() -> None:
    fixtures = _runtime_fixtures()
    nonzero_then_zero = fixtures["distance_runtime_nonzero_then_zero_001"]
    zero_then_nonzero = fixtures["distance_runtime_zero_then_nonzero_001"]

    assert nonzero_then_zero["input"]["distance_targets"] == [1, 2]
    assert nonzero_then_zero["input"]["distance_rest_signed"] == [1, 0]
    assert zero_then_nonzero["input"]["distance_targets"] == [2, 1]
    assert zero_then_nonzero["input"]["distance_rest_signed"] == [0, 1]

    first_next = float(nonzero_then_zero["expected"]["next_positions"][0][0])
    second_next = float(zero_then_nonzero["expected"]["next_positions"][0][0])
    first_velocity = float(
        nonzero_then_zero["expected"]["velocity_positions"][0][0]
    )
    second_velocity = float(
        zero_then_nonzero["expected"]["velocity_positions"][0][0]
    )
    assert math.isclose(first_next, 1.0, abs_tol=1.0e-6)
    assert math.isclose(first_velocity, 0.3, abs_tol=1.0e-6)
    assert math.isclose(second_next, 1.47846889, abs_tol=1.0e-6)
    assert math.isclose(second_velocity, 0.4435407, abs_tol=1.0e-6)
    assert not math.isclose(first_next, second_next, abs_tol=1.0e-6)


def test_distance_tier_a_fixtures_match_ordered_host_builder() -> None:
    for fixture in _fixtures().values():
        actual = _build(fixture)
        expected = fixture["expected"]
        wanted_ranges = expected["distance_ranges"]
        if not wanted_ranges:
            wanted_ranges = [[0, 0] for _ in fixture["input"]["local_positions"]]
        assert actual.distance_ranges == tuple(map(tuple, wanted_ranges)), fixture["case_id"]
        assert actual.distance_targets == tuple(expected["distance_targets"]), fixture["case_id"]
        assert len(actual.distance_rest_signed) == len(expected["distance_rest_signed"])
        for index, (value, wanted) in enumerate(
            zip(actual.distance_rest_signed, expected["distance_rest_signed"])
        ):
            assert math.isclose(
                value,
                float(wanted),
                abs_tol=1.0e-6,
                rel_tol=1.0e-6,
            ), f"{fixture['case_id']} rest[{index}]: {value} != {wanted}"
        buffers = distance_static.pack_mc2_distance_static(actual)
        assert buffers["distance_ranges"].dtype == np.int32
        assert buffers["distance_ranges"].shape == (actual.vertex_count, 2)
        assert buffers["distance_targets"].dtype == np.int32
        assert buffers["distance_rest_signed"].dtype == np.float32
        assert all(not value.flags.writeable for value in buffers.values())


def test_distance_signature_preserves_record_order() -> None:
    fixture = _runtime_fixtures()["distance_runtime_nonzero_then_zero_001"]
    first = distance_static.make_mc2_distance_static_spec(
        proxy_signature="p",
        baseline_signature="b",
        vertex_count=3,
        distance_ranges=((0, 2), (2, 0), (2, 0)),
        distance_targets=fixture["input"]["distance_targets"],
        distance_rest_signed=fixture["input"]["distance_rest_signed"],
    )
    second = distance_static.make_mc2_distance_static_spec(
        proxy_signature="p",
        baseline_signature="b",
        vertex_count=3,
        distance_ranges=((0, 2), (2, 0), (2, 0)),
        distance_targets=tuple(reversed(first.distance_targets)),
        distance_rest_signed=tuple(reversed(first.distance_rest_signed)),
    )
    assert first.distance_signature != second.distance_signature


def test_staged_distance_keeps_only_native_owned_metadata() -> None:
    fixture = _fixtures()["distance_square_shear_001"]
    full = _build(fixture)

    class StagedContext:
        record_count = -1

        def update_distance_derived(self, derived):
            self.record_count = len(derived["distance_targets"])

    context = StagedContext()
    staged = _build(fixture, native_context=context)
    assert isinstance(staged, distance_static.MC2DistanceStaticMetadata)
    assert staged.distance_signature == full.distance_signature
    assert staged.record_count == context.record_count == 12
    assert not hasattr(staged, "distance_targets")
    try:
        distance_static.pack_mc2_distance_static(staged)
    except TypeError as exc:
        assert "MC2DistanceStaticSpec" in str(exc)
    else:
        raise AssertionError("native-owned Distance metadata was accepted by the host packer")


def test_distance_spec_quantizes_float32_before_signature() -> None:
    first = distance_static.make_mc2_distance_static_spec(
        proxy_signature="p",
        baseline_signature="b",
        vertex_count=2,
        distance_ranges=((0, 1), (1, 0)),
        distance_targets=(1,),
        distance_rest_signed=(1.00000001,),
    )
    second = distance_static.make_mc2_distance_static_spec(
        proxy_signature="p",
        baseline_signature="b",
        vertex_count=2,
        distance_ranges=((0, 1), (1, 0)),
        distance_targets=(1,),
        distance_rest_signed=(1.00000002,),
    )
    assert first.distance_rest_signed == second.distance_rest_signed == (1.0,)
    assert first.distance_signature == second.distance_signature
    try:
        distance_static.make_mc2_distance_static_spec(
            proxy_signature="p",
            baseline_signature="b",
            vertex_count=2,
            distance_ranges=((0, 1), (1, 0)),
            distance_targets=(1,),
            distance_rest_signed=(1.0e300,),
        )
    except ValueError as exc:
        assert "float32" in str(exc)
    else:
        raise AssertionError("Distance rest overflow must be rejected before packing")


TESTS = (
    ("Tier A Distance fixture contract", test_distance_fixture_contract_and_packed_ranges),
    ("Tier A Distance source build facts", test_distance_fixtures_lock_source_build_facts),
    ("Tier A Distance runtime order semantics", test_distance_runtime_fixtures_prove_order_is_semantic),
    ("Tier A ordered Distance host parity", test_distance_tier_a_fixtures_match_ordered_host_builder),
    ("Distance signature preserves order", test_distance_signature_preserves_record_order),
    ("Distance staged metadata ownership", test_staged_distance_keeps_only_native_owned_metadata),
    ("Distance signature uses float32 values", test_distance_spec_quantizes_float32_before_signature),
)


def main() -> None:
    passed = 0
    for name, test in TESTS:
        test()
        passed += 1
        print(f"[PASS] {name}")
    print(f"{passed}/{len(TESTS)} passed")


if __name__ == "__main__":
    main()
