"""Pure Python parity tests for the MC2 Bone Line static bundle."""

from __future__ import annotations

import glob
import importlib
import json
import math
import os
import sys
import types
from types import SimpleNamespace


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
NODETREE = os.path.join(HOTOOLS, "OmniNode", "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(FUNCTION, "physicsWorld")
FIXTURE_DIRECTORY = os.path.join(os.path.dirname(__file__), "fixtures", "tier_a")
FLOAT_ABS_TOLERANCE = 2.0e-6
FLOAT_REL_TOLERANCE = 2.0e-6

for path in (HOTOOLS, os.path.dirname(HOTOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", os.path.join(HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PW_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module


bone_static = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.bone_static"
)
static_build = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.bone_cloth.static_build"
)


def _fixtures():
    paths = sorted(glob.glob(os.path.join(FIXTURE_DIRECTORY, "bone_static_*.json")))
    assert len(paths) == 3, paths
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            yield os.path.basename(path), json.load(handle)


def _close(actual: float, expected: float) -> bool:
    return math.isclose(
        float(actual),
        float(expected),
        abs_tol=FLOAT_ABS_TOLERANCE,
        rel_tol=FLOAT_REL_TOLERANCE,
    )


def _assert_rows_close(actual, expected, label: str) -> None:
    assert len(actual) == len(expected), label
    for row_index, (actual_row, expected_row) in enumerate(zip(actual, expected)):
        assert len(actual_row) == len(expected_row), (label, row_index)
        for component_index, (actual_value, expected_value) in enumerate(
            zip(actual_row, expected_row)
        ):
            assert _close(actual_value, expected_value), (
                label,
                row_index,
                component_index,
                actual_value,
                expected_value,
            )


def _build(fixture):
    payload = fixture["input"]
    return bone_static.build_mc2_bone_static(
        task_id=payload["task_id"],
        vertex_identities=payload["vertex_identities"],
        local_positions=payload["local_positions"],
        local_normals=payload["local_normals"],
        local_tangents=payload["local_tangents"],
        uvs=payload["uvs"],
        vertex_attributes=payload["vertex_attributes"],
        parent_indices=payload["parent_indices"],
        root_indices=payload["root_indices"],
        transform_local_rotations=payload["transform_local_rotations"],
        lines=payload["lines"],
        triangles=payload["triangles"],
        normal_alignment_mode=payload["normal_alignment_mode"],
        normal_adjustment_center=payload["normal_adjustment_center"],
    )


def test_bone_static_matches_tier_a_oracle() -> None:
    for fixture_name, fixture in _fixtures():
        result = _build(fixture)
        expected = fixture["expected"]
        proxy = expected["proxy"]
        baseline = expected["baseline"]

        assert list(result.proxy.vertex_attributes) == proxy["vertex_attributes"], fixture_name
        assert [list(row) for row in result.proxy.triangles] == proxy["triangles"], fixture_name
        assert [list(row) for row in result.proxy.edges] == proxy["edges"], fixture_name
        assert [list(row) for row in result.finalizer.vertex_to_vertex_ranges] == proxy[
            "vertex_to_vertex_ranges"
        ], fixture_name
        assert list(result.finalizer.vertex_to_vertex_data) == proxy[
            "vertex_to_vertex_data"
        ], fixture_name
        assert [
            [list(record) for record in rows]
            for rows in result.finalizer.vertex_to_triangle_records
        ] == proxy["vertex_to_triangle_records"], fixture_name

        assert list(result.baseline.parent_indices) == baseline["parent_indices"], fixture_name
        assert [list(row) for row in result.baseline.child_ranges] == baseline[
            "child_ranges"
        ], fixture_name
        assert list(result.baseline.child_data) == baseline["child_data"], fixture_name
        assert list(result.baseline.baseline_flags) == baseline["baseline_flags"], fixture_name
        assert [list(row) for row in result.baseline.baseline_ranges] == baseline[
            "baseline_ranges"
        ], fixture_name
        assert list(result.baseline.baseline_data) == baseline["baseline_data"], fixture_name
        assert list(result.baseline.root_indices) == baseline["root_indices"], fixture_name

        for actual, expected_rows, label in (
            (result.proxy.local_normals, proxy["local_normals"], "local_normals"),
            (result.proxy.local_tangents, proxy["local_tangents"], "local_tangents"),
            (
                result.finalizer.vertex_bind_pose_positions,
                proxy["vertex_bind_pose_positions"],
                "vertex_bind_pose_positions",
            ),
            (
                result.finalizer.vertex_bind_pose_rotations,
                proxy["vertex_bind_pose_rotations"],
                "vertex_bind_pose_rotations",
            ),
            (result.baseline.vertex_local_positions, baseline["vertex_local_positions"], "vertex_local_positions"),
            (result.baseline.vertex_local_rotations, baseline["vertex_local_rotations"], "vertex_local_rotations"),
            (
                result.normal_adjustment_rotations,
                expected["normal_adjustment_rotations"],
                "normal_adjustment_rotations",
            ),
            (
                result.vertex_to_transform_rotations,
                expected["vertex_to_transform_rotations"],
                "vertex_to_transform_rotations",
            ),
        ):
            _assert_rows_close(actual, expected_rows, f"{fixture_name}:{label}")
        assert all(
            _close(actual, expected_value)
            for actual, expected_value in zip(result.baseline.depths, baseline["depths"])
        ), fixture_name


def test_bone_static_pack_is_read_only_and_complete() -> None:
    _fixture_name, fixture = next(_fixtures())
    result = _build(fixture)
    packed = bone_static.pack_mc2_bone_static(result)
    assert {
        "local_positions",
        "vertex_to_vertex_ranges",
        "vertex_to_triangle_ranges",
        "vertex_bind_pose_rotations",
        "parent_indices",
        "vertex_local_rotations",
        "normal_adjustment_rotations",
        "vertex_to_transform_rotations",
    } <= set(packed)
    assert all(not value.flags.writeable for value in packed.values())


def test_bone_mesh_connection_zero_uv_domain_gate() -> None:
    assert static_build.mc2_bone_static_domain_error("bone_cloth", 1, ()) == ""
    assert static_build.mc2_bone_static_domain_error("bone_cloth", 2, ()) == ""
    error = static_build.mc2_bone_static_domain_error(
        "bone_cloth",
        1,
        ((0, 1, 2),),
    )
    assert "ImportBoneType produces zero UV" in error
    assert "triangle tangent/basis" in error
    assert "use Line" in error
    assert static_build.mc2_bone_static_domain_error(
        "bone_spring", 1, ()
    ) == "BoneSpring requires Line connection mode"
    try:
        static_build._require_mc2_bone_static_domain(
            SimpleNamespace(setup_type="bone_cloth"),
            SimpleNamespace(
                connection_mode=1,
                bone_connection=SimpleNamespace(triangles=((0, 1, 2),)),
            ),
        )
    except ValueError as exc:
        assert str(exc) == error
    else:
        raise AssertionError("triangle Bone membership bypassed the zero-UV gate")


TESTS = (
    ("MC2 Bone static matches Tier A oracle", test_bone_static_matches_tier_a_oracle),
    ("MC2 Bone static pack is read-only and complete", test_bone_static_pack_is_read_only_and_complete),
    ("MC2 Bone zero-UV static domain gate", test_bone_mesh_connection_zero_uv_domain_gate),
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
