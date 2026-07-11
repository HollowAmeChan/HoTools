"""Tier A source fixtures for MC2 ConvertProxyMesh finalization."""

from __future__ import annotations

import glob
import json
import math
import os


FIXTURE_DIRECTORY = os.path.join(os.path.dirname(__file__), "fixtures", "tier_a")
EXPECTED_COMMIT = "418f89ff31a45bb4b2336641ad5907a1110eabea"
EXPECTED_UNITY = "6000.3.15f1"


def _fixtures():
    paths = sorted(glob.glob(os.path.join(FIXTURE_DIRECTORY, "mesh_proxy_*.json")))
    assert len(paths) == 8, paths
    result = {}
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
        assert source["producer"] == [
            "Runtime/VirtualMesh/Function/VirtualMeshProxy.cs::ConvertProxyMesh"
        ]
        result[fixture["case_id"]] = fixture
    return result


def _edge_set(fixture):
    return {tuple(edge) for edge in fixture["expected"]["proxy"]["edges"]}


def _length(vector):
    return math.sqrt(sum(float(value) * float(value) for value in vector))


def test_proxy_fixtures_lock_convert_proxy_mesh_facts() -> None:
    fixtures = _fixtures()

    consistent = fixtures["mesh_proxy_consistent_winding_001"]
    assert consistent["expected"]["proxy"]["triangles"] == [[0, 1, 2]]
    assert _edge_set(consistent) == {(0, 1), (0, 2), (1, 2)}
    assert consistent["expected"]["proxy"]["vertex_attributes"] == [0x81, 0x82, 0x82]

    reversed_neighbor = fixtures["mesh_proxy_reversed_neighbor_001"]
    assert reversed_neighbor["input"]["triangles"][1] == [1, 2, 3]
    assert reversed_neighbor["expected"]["proxy"]["triangles"][1] == [1, 3, 2]

    layer_boundary = fixtures["mesh_proxy_layer_boundary_001"]
    assert layer_boundary["expected"]["proxy"]["triangles"][1] == [1, 2, 3]
    assert layer_boundary["expected"]["proxy"]["local_normals"][3] != [0, 0, 1]

    uv_tangent = fixtures["mesh_proxy_uv_tangent_001"]
    assert uv_tangent["expected"]["proxy"]["local_tangents"][0] != [1, 0, 0]

    zero_area = fixtures["mesh_proxy_uv_zero_area_001"]
    assert zero_area["input"]["uvs"] == [[0, 0], [1, 1], [2, 2]]
    assert _length(zero_area["expected"]["proxy"]["local_tangents"][0]) > 0.99

    cap = fixtures["mesh_proxy_vertex_triangle_cap_001"]
    assert len(cap["input"]["triangles"]) == 8
    assert len(cap["expected"]["proxy"]["vertex_to_triangle_records"][0]) == 7
    assert cap["expected"]["proxy"]["vertex_to_triangle_records"][0][-1] == [0, 6]

    loose_line = fixtures["mesh_proxy_triangle_loose_line_001"]
    assert (3, 4) in _edge_set(loose_line)
    assert loose_line["expected"]["proxy"]["vertex_attributes"][3:5] == [0x02, 0x02]
    assert loose_line["expected"]["proxy"]["vertex_to_triangle_records"][3:5] == [[], []]

    attribute_or = fixtures["mesh_proxy_attribute_or_001"]
    assert attribute_or["expected"]["proxy"]["vertex_attributes"] == [0x91, 0x92, 0x82]


TESTS = (
    (
        "Tier A ConvertProxyMesh final proxy facts",
        test_proxy_fixtures_lock_convert_proxy_mesh_facts,
    ),
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
