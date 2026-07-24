"""Tier A source fixtures for MC2 Bone triangle rotation/output."""

from __future__ import annotations

import glob
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

bone_rotation = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.test.bone_rotation_reference"
)


FIXTURE_DIRECTORY = os.path.join(os.path.dirname(__file__), "fixtures", "tier_a")
EXPECTED_COMMIT = "418f89ff31a45bb4b2336641ad5907a1110eabea"
EXPECTED_PRODUCERS = [
    "Runtime/Manager/VirtualMesh/VirtualMeshManager.cs::SimulationPostProxyMeshUpdateTriangle",
    "Runtime/Manager/VirtualMesh/VirtualMeshManager.cs::SimulationPostProxyMeshUpdateTriangleSum",
    "Runtime/Manager/VirtualMesh/VirtualMeshManager.cs::SimulationPostProxyMeshUpdateWorldTransform",
    "Runtime/Manager/VirtualMesh/VirtualMeshManager.cs::SimulationPostProxyMeshUpdateLocalTransform",
]


def _fixtures():
    paths = sorted(glob.glob(os.path.join(FIXTURE_DIRECTORY, "bone_rotation_triangle_*.json")))
    assert len(paths) == 3, paths
    fixtures = {}
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            fixture = json.load(handle)
        source = fixture["source"]
        assert source["oracle_tier"] == "A"
        assert source["version"] == "2.18.1"
        assert source["commit"] == EXPECTED_COMMIT
        assert source["unity_editor"] == "6000.3.15f1"
        assert source["producer"] == EXPECTED_PRODUCERS
        fixtures[fixture["case_id"]] = fixture
    return fixtures


def _evaluate(fixture):
    values = fixture["input"]
    return bone_rotation.evaluate_mc2_bone_triangle_rotation(
        attributes=values["attributes"],
        positions=values["positions"],
        rotations=values["rotations"],
        triangles=values["triangles"],
        uvs=values["uvs"],
        vertex_to_triangle_records=values["vertex_to_triangle_records"],
        normal_adjustment_rotations=values["normal_adjustment_rotations"],
        vertex_to_transform_rotations=values["vertex_to_transform_rotations"],
        parent_indices=values["parent_indices"],
        transform_scales=values["transform_scales"],
        transform_local_positions=values["transform_local_positions"],
        transform_local_rotations=values["transform_local_rotations"],
    )


def test_bone_triangle_rotation_matches_tier_a() -> None:
    for fixture in _fixtures().values():
        result = _evaluate(fixture)
        expected = fixture["expected"]
        for name in (
            "triangle_normals",
            "triangle_tangents",
            "proxy_rotations",
            "world_positions",
            "world_rotations",
            "local_positions",
            "local_rotations",
        ):
            np.testing.assert_allclose(
                np.asarray(getattr(result, name), dtype=np.float32),
                np.asarray(expected[name], dtype=np.float32),
                rtol=3.0e-6,
                atol=8.0e-7,
                err_msg=f"{fixture['case_id']}:{name}",
            )


def test_bone_triangle_rotation_locks_override_order() -> None:
    fixtures = _fixtures()
    override_fixture = fixtures["bone_rotation_triangle_override_001"]
    override = _evaluate(override_fixture)
    assert len(set(override.proxy_rotations)) == 1
    assert tuple(override_fixture["input"]["rotations"][0]) != override.proxy_rotations[0]
    np.testing.assert_allclose(override.local_rotations[1:], ((0, 0, 0, 1),) * 2, atol=1.0e-6)

    flipped = _evaluate(fixtures["bone_rotation_triangle_flip_001"])
    assert len(set(flipped.proxy_rotations)) == 3
    assert abs(flipped.local_rotations[1][0]) > 0.99
    assert abs(flipped.local_rotations[2][2]) > 0.99

    adjusted = _evaluate(fixtures["bone_rotation_triangle_adjustment_001"])
    assert len(set(adjusted.proxy_rotations)) == 3
    assert abs(adjusted.local_rotations[1][2] - 0.258819) < 1.0e-5


TESTS = (
    ("Tier A Bone triangle rotation", test_bone_triangle_rotation_matches_tier_a),
    ("Bone triangle override order", test_bone_triangle_rotation_locks_override_order),
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
