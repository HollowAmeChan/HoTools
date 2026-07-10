"""Tier A full-array comparison for the pure MC2 Mesh baseline builder."""

from __future__ import annotations

import glob
import importlib
import json
import math
import os
import sys
import types


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
mesh_baseline = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.mesh_baseline"
)


FIXTURE_DIRECTORY = os.path.join(os.path.dirname(__file__), "fixtures", "tier_a")
EXPECTED_COMMIT = "418f89ff31a45bb4b2336641ad5907a1110eabea"
EXPECTED_UNITY = "6000.3.15f1"


def _fixtures():
    paths = sorted(glob.glob(os.path.join(FIXTURE_DIRECTORY, "mesh_baseline_*.json")))
    assert len(paths) == 9, paths
    result = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            fixture = json.load(handle)
        source = fixture["source"]
        assert source["oracle_tier"] == "A"
        assert source["version"] == "2.18.1"
        assert source["commit"] == EXPECTED_COMMIT
        assert source["unity_editor"] == EXPECTED_UNITY
        assert source["burst"] == "1.8.29"
        assert source["collections"] == "2.6.5"
        assert source["mathematics"] == "1.3.3"
        assert all(value != "unknown" for value in (
            source["burst"], source["collections"], source["mathematics"]
        ))
        result.append(fixture)
    return result


def _build(fixture):
    payload = fixture["input"]
    proxy = static_data.make_mc2_proxy_static_spec(
        task_id=payload["task_id"],
        setup_type=payload["setup_type"],
        vertex_identities=payload["vertex_identities"],
        local_positions=payload["local_positions"],
        local_normals=payload["local_normals"],
        local_tangents=payload["local_tangents"],
        uvs=payload["uvs"],
        vertex_attributes=payload["vertex_attributes"],
        edges=payload["edges"],
        triangles=payload["triangles"],
    )
    return mesh_baseline.build_mc2_mesh_baseline(proxy)


def _assert_floats(actual, expected, abs_tolerance, rel_tolerance, label):
    assert len(actual) == len(expected), label
    for index, (value, wanted) in enumerate(zip(actual, expected)):
        if isinstance(value, (tuple, list)):
            _assert_floats(
                value,
                wanted,
                abs_tolerance,
                rel_tolerance,
                f"{label}[{index}]",
            )
            continue
        assert math.isclose(
            float(value),
            float(wanted),
            abs_tol=abs_tolerance,
            rel_tol=rel_tolerance,
        ), f"{label}[{index}]: {value} != {wanted}"


def _groups(ranges, data, *, sort_values):
    groups = []
    for start, count in ranges:
        values = tuple(data[start:start + count])
        groups.append(tuple(sorted(values)) if sort_values else values)
    return tuple(groups)


def _baseline_components(ranges, data, flags):
    result = []
    for index, (start, count) in enumerate(ranges):
        values = tuple(data[start:start + count])
        assert values
        result.append((values[0], tuple(sorted(values)), flags[index]))
    return tuple(sorted(result))


def _validate_expected_contract(fixture):
    payload = fixture["input"]
    expected = fixture["expected"]
    final_proxy = static_data.make_mc2_proxy_static_spec(
        task_id=payload["task_id"],
        setup_type=payload["setup_type"],
        vertex_identities=payload["vertex_identities"],
        local_positions=payload["local_positions"],
        local_normals=payload["local_normals"],
        local_tangents=payload["local_tangents"],
        uvs=payload["uvs"],
        vertex_attributes=expected["proxy"]["vertex_attributes"],
        edges=payload["edges"],
        triangles=payload["triangles"],
    )
    baseline = dict(expected["baseline"])
    return static_data.make_mc2_baseline_static_spec(
        proxy_signature=final_proxy.proxy_signature,
        vertex_count=len(payload["vertex_identities"]),
        **baseline,
    )


def test_tier_a_fixtures_match_hotools_builder() -> None:
    compared = 0
    for fixture in _fixtures():
        _validate_expected_contract(fixture)
        comparison = fixture["comparison"]
        if not comparison["compare_to_hotools"]:
            continue
        result = _build(fixture)
        actual = result.baseline
        expected = fixture["expected"]
        expected_baseline = expected["baseline"]
        abs_tolerance = float(comparison["float_abs_tolerance"])
        rel_tolerance = float(comparison["float_rel_tolerance"])

        assert result.final_proxy.vertex_attributes == tuple(
            expected["proxy"]["vertex_attributes"]
        ), fixture["case_id"]
        assert actual.parent_indices == tuple(expected_baseline["parent_indices"])
        assert actual.root_indices == tuple(expected_baseline["root_indices"])
        assert actual.baseline_flags == tuple(expected_baseline["baseline_flags"])
        assert tuple(count for _start, count in actual.baseline_ranges) == tuple(
            count for _start, count in expected_baseline["baseline_ranges"]
        )
        assert _groups(actual.child_ranges, actual.child_data, sort_values=True) == _groups(
            expected_baseline["child_ranges"],
            expected_baseline["child_data"],
            sort_values=True,
        )
        assert _baseline_components(
            actual.baseline_ranges,
            actual.baseline_data,
            actual.baseline_flags,
        ) == _baseline_components(
            expected_baseline["baseline_ranges"],
            expected_baseline["baseline_data"],
            expected_baseline["baseline_flags"],
        )
        _assert_floats(
            actual.depths,
            expected_baseline["depths"],
            abs_tolerance,
            rel_tolerance,
            f"{fixture['case_id']}.depths",
        )
        _assert_floats(
            actual.vertex_local_positions,
            expected_baseline["vertex_local_positions"],
            abs_tolerance,
            rel_tolerance,
            f"{fixture['case_id']}.vertex_local_positions",
        )
        _assert_floats(
            actual.vertex_local_rotations,
            expected_baseline["vertex_local_rotations"],
            abs_tolerance,
            rel_tolerance,
            f"{fixture['case_id']}.vertex_local_rotations",
        )
        compared += 1
    assert compared == 8


def test_equal_cost_fixture_proves_source_order_boundary() -> None:
    fixtures = {fixture["case_id"]: fixture for fixture in _fixtures()}
    low = fixtures["mesh_baseline_equal_cost_low_first_001"]
    high = fixtures["mesh_baseline_equal_cost_high_first_001"]
    assert low["input"]["source_adjacency"][2] == [0, 1]
    assert high["input"]["source_adjacency"][2] == [1, 0]
    assert low["expected"]["baseline"]["parent_indices"][2] == 0
    assert high["expected"]["baseline"]["parent_indices"][2] == 1
    assert low["comparison"]["compare_to_hotools"] is True
    assert high["comparison"]["compare_to_hotools"] is False
    assert _build(low).baseline.parent_indices[2] == 0
    assert _build(high).baseline.parent_indices[2] == 0


TESTS = (
    ("Tier A full-array Mesh baseline parity", test_tier_a_fixtures_match_hotools_builder),
    ("equal-cost source order boundary", test_equal_cost_fixture_proves_source_order_boundary),
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
