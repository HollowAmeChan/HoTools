"""Tier A source fixtures for MC2 TriangleBendingConstraint static data."""

from __future__ import annotations

import glob
import json
import math
import os


FIXTURE_DIRECTORY = os.path.join(os.path.dirname(__file__), "fixtures", "tier_a")
EXPECTED_COMMIT = "418f89ff31a45bb4b2336641ad5907a1110eabea"
EXPECTED_UNITY = "6000.3.15f1"
EXPECTED_PRODUCERS = [
    "Runtime/Cloth/Constraints/TriangleBendingConstraint.cs::CreateData",
    "Runtime/Utility/Data/DataUtility.cs::Pack64",
]


def _fixtures():
    paths = sorted(
        path
        for path in glob.glob(os.path.join(FIXTURE_DIRECTORY, "bending_*.json"))
        if not os.path.basename(path).startswith("bending_runtime_")
    )
    assert len(paths) == 13, paths
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
    paths = sorted(glob.glob(os.path.join(FIXTURE_DIRECTORY, "bending_runtime_*.json")))
    assert len(paths) == 3, paths
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
            "Runtime/Cloth/Constraints/TriangleBendingConstraint.cs::SolverConstraint",
            "Runtime/Cloth/Constraints/TriangleBendingConstraint.cs::SumConstraint",
        ]
        result[fixture["case_id"]] = fixture
    return result


def _decode_pack64(value):
    return [
        (int(value) >> 48) & 0xFFFF,
        (int(value) >> 32) & 0xFFFF,
        (int(value) >> 16) & 0xFFFF,
        int(value) & 0xFFFF,
    ]


def test_bending_fixture_contract_and_pack64() -> None:
    for fixture in _fixtures().values():
        expected = fixture["expected"]
        packed = expected["raw_packed_quads"]
        quads = expected["ordered_quads"]
        rests = expected["rest_angle_or_volume"]
        markers = expected["sign_or_volume"]
        assert len(packed) == len(quads) == len(rests) == len(markers)
        assert [_decode_pack64(value) for value in packed] == quads
        assert all(len(quad) == 4 for quad in quads)
        assert all(0 <= index <= 0xFFFF for quad in quads for index in quad)
        assert all(math.isfinite(float(value)) for value in rests)
        assert set(markers).issubset({-1, 1, 100})
        diagnostic = expected["diagnostic_write"]
        assert diagnostic["runtime_consumed"] is False
        if expected["create_returned_null"]:
            assert diagnostic["write_ranges"] == []
        else:
            assert len(diagnostic["write_ranges"]) == len(
                fixture["input"]["local_positions"]
            )


def test_bending_fixtures_lock_source_build_facts() -> None:
    fixtures = _fixtures()

    flat = fixtures["bending_flat_dihedral_001"]["expected"]
    assert flat["ordered_quads"] == [[1, 0, 2, 3]]
    assert flat["sign_or_volume"] == [1]
    assert math.isclose(flat["rest_angle_or_volume"][0], 0.0, abs_tol=1.0e-7)

    folded = fixtures["bending_fold_100_double_001"]["expected"]
    assert folded["ordered_quads"] == [[1, 0, 2, 3], [1, 0, 2, 3]]
    assert folded["sign_or_volume"] == [-1, 100]
    assert math.isclose(
        folded["rest_angle_or_volume"][0],
        math.radians(100.0),
        abs_tol=1.0e-6,
    )

    volume_only = fixtures["bending_fold_130_volume_only_001"]["expected"]
    assert volume_only["ordered_quads"] == [[1, 0, 2, 3]]
    assert volume_only["sign_or_volume"] == [100]

    below_90 = fixtures["bending_fold_89_9_bending_only_001"]["expected"]
    below_120 = fixtures["bending_fold_119_9_double_001"]["expected"]
    above_120 = fixtures["bending_fold_120_1_volume_only_001"]["expected"]
    below_179 = fixtures["bending_fold_178_9_volume_only_001"]["expected"]
    assert below_90["sign_or_volume"] == [-1]
    assert below_120["sign_or_volume"] == [-1, 100]
    assert above_120["sign_or_volume"] == [100]
    assert below_179["sign_or_volume"] == [100]

    above_179 = fixtures["bending_fold_above_179_empty_001"]["expected"]
    assert above_179["create_returned_null"] is False
    assert above_179["ordered_quads"] == []

    for case_id in ("bending_all_fixed_empty_001", "bending_invalid_empty_001"):
        filtered = fixtures[case_id]["expected"]
        assert filtered["create_returned_null"] is False
        assert filtered["ordered_quads"] == []
        assert filtered["diagnostic_write"]["write_buffer_count"] == 0

    no_triangles = fixtures["bending_no_triangles_null_001"]["expected"]
    assert no_triangles["create_returned_null"] is True
    assert no_triangles["ordered_quads"] == []


def test_bending_volume_uses_initial_world_transform() -> None:
    fixtures = _fixtures()
    identity = fixtures["bending_fold_100_double_001"]["expected"]
    scaled = fixtures["bending_fold_100_scaled_world_001"]["expected"]
    assert identity["ordered_quads"] == scaled["ordered_quads"]
    assert identity["sign_or_volume"] == scaled["sign_or_volume"] == [-1, 100]
    assert math.isclose(
        identity["rest_angle_or_volume"][0],
        scaled["rest_angle_or_volume"][0],
        abs_tol=1.0e-6,
    )
    assert math.isclose(
        scaled["rest_angle_or_volume"][1],
        identity["rest_angle_or_volume"][1] * 8.0,
        abs_tol=1.0e-3,
        rel_tol=1.0e-6,
    )


def test_bending_volume_dedup_keeps_first_raw_role() -> None:
    fixture = _fixtures()["bending_tetra_volume_first_wins_001"]
    expected = fixture["expected"]
    markers = expected["sign_or_volume"]
    assert len(markers) == 7
    assert markers.count(100) == 1
    volume_index = markers.index(100)
    assert volume_index == 1
    assert expected["ordered_quads"][volume_index] == expected["ordered_quads"][0]
    assert sorted(expected["ordered_quads"][volume_index]) == [0, 1, 2, 3]
    assert len({tuple(sorted(quad)) for quad in expected["ordered_quads"]}) == 1


def test_bending_runtime_fixed_point_sum_and_clear() -> None:
    fixture = _runtime_fixtures()["bending_runtime_single_fixed_sum_001"]
    expected = fixture["expected"]
    assert expected["count_before_sum"] == [1, 1, 1, 1]
    assert any(value != 0 for value in expected["vector_components_before_sum"])
    assert expected["next_positions_after_sum"][0] == fixture["input"]["next_positions"][0]
    assert expected["next_positions_after_sum"][1] != fixture["input"]["next_positions"][1]
    assert expected["count_after_sum"] == [0, 0, 0, 0]
    assert expected["vector_after_sum"] == [[0, 0, 0]] * 4


def test_bending_runtime_scale_and_negative_sign_are_consumed() -> None:
    fixtures = _runtime_fixtures()
    positive = fixtures["bending_runtime_double_positive_scale_001"]
    negative = fixtures["bending_runtime_double_negative_scale_001"]
    assert positive["input"]["ordered_quads"] == negative["input"]["ordered_quads"]
    assert positive["input"]["rest_angle_or_volume"] == negative["input"]["rest_angle_or_volume"]
    assert positive["input"]["scale_ratio"] == negative["input"]["scale_ratio"] == 1.25
    assert positive["input"]["negative_scale_sign"] == 1
    assert negative["input"]["negative_scale_sign"] == -1
    assert positive["expected"]["count_before_sum"] == [2, 2, 2, 2]
    assert negative["expected"]["count_before_sum"] == [2, 2, 2, 2]
    assert positive["expected"]["next_positions_after_sum"] != negative["expected"]["next_positions_after_sum"]
    assert positive["expected"]["count_after_sum"] == negative["expected"]["count_after_sum"] == [0, 0, 0, 0]


TESTS = (
    ("Tier A Bending fixture contract", test_bending_fixture_contract_and_pack64),
    ("Tier A Bending source build facts", test_bending_fixtures_lock_source_build_facts),
    ("Bending initial world transform", test_bending_volume_uses_initial_world_transform),
    ("Bending volume first-wins role", test_bending_volume_dedup_keeps_first_raw_role),
    ("Bending fixed-point sum and clear", test_bending_runtime_fixed_point_sum_and_clear),
    ("Bending scale and negative sign", test_bending_runtime_scale_and_negative_sign_are_consumed),
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
