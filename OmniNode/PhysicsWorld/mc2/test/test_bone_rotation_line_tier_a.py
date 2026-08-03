"""Tier A source fixtures for MC2 Bone Line post rotation/output."""

from __future__ import annotations

import glob
import importlib
import json
import os
import sys
import types
from copy import deepcopy

import numpy as np


MC2_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD = os.path.dirname(MC2_ROOT)
FUNCTION = os.path.dirname(PHYSICS_WORLD)
NODETREE = os.path.dirname(FUNCTION)
OMNINODE = NODETREE
HOTOOLS = os.path.dirname(OMNINODE)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.Function", FUNCTION),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD),
    ("HoTools.OmniNode.PhysicsWorld.mc2", MC2_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

bone_rotation = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.test.bone_rotation_reference"
)
mc2_native = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.native"
)


FIXTURE_DIRECTORY = os.path.join(os.path.dirname(__file__), "fixtures", "tier_a")
EXPECTED_COMMIT = "418f89ff31a45bb4b2336641ad5907a1110eabea"
EXPECTED_PRODUCERS = [
    "Runtime/Manager/VirtualMesh/VirtualMeshManager.cs::SimulationPostProxyMeshUpdateLine",
    "Runtime/Manager/VirtualMesh/VirtualMeshManager.cs::SimulationPostProxyMeshUpdateWorldTransform",
    "Runtime/Manager/VirtualMesh/VirtualMeshManager.cs::SimulationPostProxyMeshUpdateLocalTransform",
]


def _fixtures():
    paths = sorted(glob.glob(os.path.join(FIXTURE_DIRECTORY, "bone_rotation_line_*.json")))
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
    return bone_rotation.evaluate_mc2_bone_line_rotation(
        attributes=values["attributes"],
        positions=values["positions"],
        rotations=values["rotations"],
        base_positions=values["base_positions"],
        base_rotations=values["base_rotations"],
        vertex_local_positions=values["vertex_local_positions"],
        vertex_local_rotations=values["vertex_local_rotations"],
        vertex_to_transform_rotations=values["vertex_to_transform_rotations"],
        parent_indices=values["parent_indices"],
        transform_scales=values["transform_scales"],
        transform_local_positions=values["transform_local_positions"],
        transform_local_rotations=values["transform_local_rotations"],
        child_ranges=values["child_ranges"],
        child_data=values["child_data"],
        baseline_data=values["baseline_data"],
        rotational_interpolation=values["rotational_interpolation"],
        root_rotation=values["root_rotation"],
        animation_pose_ratio=values["animation_pose_ratio"],
        blend_weight=values["blend_weight"],
    )


def test_bone_line_rotation_matches_tier_a() -> None:
    for fixture in _fixtures().values():
        result = _evaluate(fixture)
        expected = fixture["expected"]
        for name in (
            "proxy_rotations",
            "world_positions",
            "world_rotations",
            "local_positions",
            "local_rotations",
        ):
            np.testing.assert_allclose(
                np.asarray(getattr(result, name), dtype=np.float32),
                np.asarray(expected[name], dtype=np.float32),
                rtol=2.0e-6,
                atol=5.0e-7,
                err_msg=f"{fixture['case_id']}:{name}",
            )


def test_bone_line_rotation_locks_stage_order() -> None:
    fixtures = _fixtures()
    full = _evaluate(fixtures["bone_rotation_line_full_001"])
    assert full.proxy_rotations[1] != full.local_rotations[1]
    np.testing.assert_allclose(full.local_rotations[2], (0, 0, 0, 1), atol=5.0e-7)

    interpolated = _evaluate(fixtures["bone_rotation_line_interpolation_001"])
    assert abs(interpolated.proxy_rotations[0][2]) < abs(full.proxy_rotations[0][2])
    assert abs(interpolated.proxy_rotations[1][2]) < abs(full.proxy_rotations[1][2])

    animated = _evaluate(fixtures["bone_rotation_line_animation_pose_001"])
    assert animated.proxy_rotations[0][2] > 0.0
    assert full.proxy_rotations[0][2] < 0.0

    preserved_fixture = deepcopy(fixtures["bone_rotation_line_full_001"])
    preserved_fixture["input"]["transform_local_positions"][0] = [3.0, 4.0, 5.0]
    preserved_fixture["input"]["transform_local_rotations"][0] = [0.0, 0.0, 0.5, 0.8660254]
    preserved = _evaluate(preserved_fixture)
    np.testing.assert_allclose(preserved.local_positions[0], (3, 4, 5), atol=1.0e-6)
    np.testing.assert_allclose(
        preserved.local_rotations[0],
        (0.0, 0.0, 0.5, 0.8660254),
        atol=1.0e-6,
    )


def test_native_bone_line_output_matches_tier_a() -> None:
    native = mc2_native.require_mc2_native_module()
    for fixture in _fixtures().values():
        values = fixture["input"]
        count = len(values["positions"])
        output = np.empty((count, 4), dtype=np.float32)
        native.mc2_bone_line_output_v1(
            np.ascontiguousarray(values["attributes"], dtype=np.uint8),
            np.ascontiguousarray(values["positions"], dtype=np.float32),
            np.ascontiguousarray(values["base_positions"], dtype=np.float32),
            np.ascontiguousarray(values["base_rotations"], dtype=np.float32),
            np.ascontiguousarray(values["child_ranges"], dtype=np.int32),
            np.ascontiguousarray(values["child_data"], dtype=np.int32),
            np.ascontiguousarray(((0, count),), dtype=np.int32),
            np.ascontiguousarray(values["baseline_data"], dtype=np.int32),
            np.ascontiguousarray(
                values["vertex_local_positions"], dtype=np.float32
            ),
            np.ascontiguousarray(
                values["vertex_local_rotations"], dtype=np.float32
            ),
            np.empty((0, 3), dtype=np.int32),
            np.zeros((count, 2), dtype=np.float32),
            np.zeros((count, 2), dtype=np.int32),
            np.empty((0, 2), dtype=np.int32),
            np.ascontiguousarray(
                ((0.0, 0.0, 0.0, 1.0),) * count,
                dtype=np.float32,
            ),
            np.ascontiguousarray(
                values["vertex_to_transform_rotations"], dtype=np.float32
            ),
            np.ascontiguousarray((
                values["rotational_interpolation"],
                values["root_rotation"],
                values["animation_pose_ratio"],
                values["blend_weight"],
            ), dtype=np.float32),
            output,
        )
        np.testing.assert_allclose(
            output,
            np.asarray(fixture["expected"]["world_rotations"], dtype=np.float32),
            rtol=2.0e-6,
            atol=5.0e-7,
            err_msg=f"{fixture['case_id']}:native world rotations",
        )


def _native_bone_mesh_output(values, *, child_ranges, child_data) -> np.ndarray:
    native = mc2_native.require_mc2_native_module()
    count = len(values["positions"])
    output = np.empty((count, 4), dtype=np.float32)
    native.mc2_bone_mesh_output_v1(
        np.ascontiguousarray(values["attributes"], dtype=np.uint8),
        np.ascontiguousarray(values["positions"], dtype=np.float32),
        np.ascontiguousarray(values["base_positions"], dtype=np.float32),
        np.ascontiguousarray(values["base_rotations"], dtype=np.float32),
        np.ascontiguousarray(child_ranges, dtype=np.int32),
        np.ascontiguousarray(child_data, dtype=np.int32),
        np.ascontiguousarray(((0, count),), dtype=np.int32),
        np.ascontiguousarray(values["baseline_data"], dtype=np.int32),
        np.ascontiguousarray(values["vertex_local_positions"], dtype=np.float32),
        np.ascontiguousarray(values["vertex_local_rotations"], dtype=np.float32),
        np.empty((0, 3), dtype=np.int32),
        np.zeros((count, 2), dtype=np.float32),
        np.zeros((count, 2), dtype=np.int32),
        np.empty((0, 2), dtype=np.int32),
        np.ascontiguousarray(
            ((0.0, 0.0, 0.0, 1.0),) * count,
            dtype=np.float32,
        ),
        np.ascontiguousarray(
            values["vertex_to_transform_rotations"], dtype=np.float32
        ),
        np.ascontiguousarray((
            1.0,
            1.0,
            values["animation_pose_ratio"],
            values["blend_weight"],
        ), dtype=np.float32),
        output,
    )
    return output


def _rotate_vector_xyzw(rotation, vector) -> np.ndarray:
    quaternion = np.asarray(rotation, dtype=np.float32)
    value = np.asarray(vector, dtype=np.float32)
    xyz = quaternion[:3]
    return value + np.float32(2.0) * np.cross(
        xyz,
        np.cross(xyz, value) + quaternion[3] * value,
    )


def test_native_bone_mesh_tail_absorption_uses_recorded_endpoint() -> None:
    values = _fixtures()["bone_rotation_line_full_001"]["input"]
    endpoint_ranges = ((0, 1), (1, 1), (2, 0))
    endpoint_data = (1, 2)
    wrong_parent_data = (2, 2)
    disabled_ranges = ((0, 0),) * len(values["positions"])
    enabled = _native_bone_mesh_output(
        values,
        child_ranges=endpoint_ranges,
        child_data=endpoint_data,
    )
    wrong_parent = _native_bone_mesh_output(
        values,
        child_ranges=endpoint_ranges,
        child_data=wrong_parent_data,
    )
    disabled = _native_bone_mesh_output(
        values,
        child_ranges=disabled_ranges,
        child_data=(),
    )

    simulated_positions = np.asarray(values["positions"], dtype=np.float32)
    recorded_direction = simulated_positions[1] - simulated_positions[0]
    recorded_direction /= np.linalg.norm(recorded_direction)
    output_axis = _rotate_vector_xyzw(enabled[0], (0.0, 1.0, 0.0))
    output_axis /= np.linalg.norm(output_axis)
    np.testing.assert_allclose(
        output_axis,
        recorded_direction,
        rtol=1.0e-6,
        atol=1.0e-6,
    )

    assert not np.allclose(enabled[0], wrong_parent[0], rtol=1.0e-6, atol=1.0e-7)
    assert not np.allclose(enabled[0], disabled[0], rtol=1.0e-6, atol=1.0e-7)
    np.testing.assert_allclose(
        disabled,
        np.asarray(((0.0, 0.0, 0.0, 1.0),) * len(disabled)),
        rtol=1.0e-6,
        atol=1.0e-7,
    )
    np.testing.assert_allclose(
        np.linalg.norm(disabled, axis=1),
        np.ones(len(disabled), dtype=np.float32),
        rtol=1.0e-6,
        atol=1.0e-7,
    )


TESTS = (
    ("Tier A Bone Line rotation", test_bone_line_rotation_matches_tier_a),
    ("Bone Line rotation stage order", test_bone_line_rotation_locks_stage_order),
    ("Native Bone Line output", test_native_bone_line_output_matches_tier_a),
    (
        "Native Bone mesh Tail absorption",
        test_native_bone_mesh_tail_absorption_uses_recorded_endpoint,
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
