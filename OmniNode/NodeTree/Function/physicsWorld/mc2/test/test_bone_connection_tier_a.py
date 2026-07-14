"""Tier A source fixtures for MC2 Bone transform connection topology."""

from __future__ import annotations

import glob
import importlib
import json
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

bone_connection = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.bone_connection"
)


FIXTURE_DIRECTORY = os.path.join(os.path.dirname(__file__), "fixtures", "tier_a")
EXPECTED_COMMIT = "418f89ff31a45bb4b2336641ad5907a1110eabea"
EXPECTED_UNITY = "6000.3.15f1"
EXPECTED_PRODUCER = [
    "Runtime/VirtualMesh/Function/VirtualMeshInputOutput.cs::ImportBoneType"
]


def _fixtures():
    paths = sorted(glob.glob(os.path.join(FIXTURE_DIRECTORY, "bone_connection_*.json")))
    assert len(paths) == 8, paths
    fixtures = {}
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            fixture = json.load(handle)
        source = fixture["source"]
        assert source["oracle_tier"] == "A"
        assert source["version"] == "2.18.1"
        assert source["commit"] == EXPECTED_COMMIT
        assert source["unity_editor"] == EXPECTED_UNITY
        assert source["producer"] == EXPECTED_PRODUCER
        fixtures[fixture["case_id"]] = fixture
    return fixtures


def _build(fixture):
    input_data = fixture["input"]
    return bone_connection.build_mc2_bone_connection(
        input_data["positions"],
        input_data["parent_indices"],
        input_data["root_indices"],
        input_data["connection_mode"],
        child_indices=input_data["child_indices"],
    )


def test_bone_connection_builder_matches_tier_a_membership() -> None:
    for fixture in _fixtures().values():
        result = _build(fixture)
        expected = fixture["expected"]
        assert [list(value) for value in result.lines] == expected["lines"], fixture["case_id"]
        assert [list(value) for value in result.triangles] == expected["triangles"], fixture["case_id"]


def test_bone_connection_modes_lock_source_boundaries() -> None:
    fixtures = _fixtures()
    line = _build(fixtures["bone_connection_line_branch_001"])
    assert line.triangles == ()
    assert line.lines == ((0, 1), (2, 3), (2, 4))

    loop = _build(fixtures["bone_connection_sequential_loop_001"])
    nonloop = _build(fixtures["bone_connection_sequential_nonloop_001"])
    assert loop.connection_mode == bone_connection.MC2_BONE_CONNECTION_SEQUENTIAL_LOOP
    assert nonloop.connection_mode == bone_connection.MC2_BONE_CONNECTION_SEQUENTIAL_NON_LOOP
    assert set(nonloop.triangles) < set(loop.triangles)

    automatic = _build(fixtures["bone_connection_automatic_reverse_001"])
    assert automatic.root_order == (4, 6, 2, 0)
    assert automatic.triangles == (
        (0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3),
        (4, 5, 6), (4, 5, 7), (4, 6, 7), (5, 6, 7),
    )

    residual = _build(fixtures["bone_connection_zero_residual_001"])
    assert residual.triangles == ()
    assert residual.lines == ((0, 1), (2, 3))

    below_angle = _build(fixtures["bone_connection_angle_119_001"])
    above_angle = _build(fixtures["bone_connection_angle_121_001"])
    assert set(above_angle.triangles) < set(below_angle.triangles)
    assert len(below_angle.triangles) == len(above_angle.triangles) + 1


def test_bone_connection_membership_survives_identity_remap() -> None:
    for fixture in _fixtures().values():
        input_data = fixture["input"]
        old_indices = sorted(range(len(input_data["names"])), key=input_data["names"].__getitem__)
        old_to_new = {old: new for new, old in enumerate(old_indices)}
        positions = [input_data["positions"][old] for old in old_indices]
        parents = [
            old_to_new[parent] if parent >= 0 else -1
            for parent in (input_data["parent_indices"][old] for old in old_indices)
        ]
        children = [
            [old_to_new[child] for child in input_data["child_indices"][old]]
            for old in old_indices
        ]
        roots = [old_to_new[root] for root in input_data["root_indices"]]
        result = bone_connection.build_mc2_bone_connection(
            positions,
            parents,
            roots,
            input_data["connection_mode"],
            child_indices=children,
        )
        expected_lines = sorted(
            tuple(sorted(old_to_new[index] for index in edge))
            for edge in fixture["expected"]["lines"]
        )
        expected_triangles = sorted(
            tuple(sorted(old_to_new[index] for index in triangle))
            for triangle in fixture["expected"]["triangles"]
        )
        assert result.lines == tuple(expected_lines), fixture["case_id"]
        assert result.triangles == tuple(expected_triangles), fixture["case_id"]


TESTS = (
    ("Tier A Bone connection membership", test_bone_connection_builder_matches_tier_a_membership),
    ("Bone connection mode boundaries", test_bone_connection_modes_lock_source_boundaries),
    ("Bone connection identity remap", test_bone_connection_membership_survives_identity_remap),
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
