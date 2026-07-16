"""Pure Python parity tests for MC2 MeshCloth final-proxy extraction."""

from __future__ import annotations

import glob
import importlib
import json
import math
import os
import sys
import types


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
NODETREE = os.path.join(HOTOOLS, "OmniNode", "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(FUNCTION, "physicsWorld")
FIXTURE_DIRECTORY = os.path.join(os.path.dirname(__file__), "fixtures", "tier_a")
FLOAT_ABS_TOLERANCE = 1.0e-6
FLOAT_REL_TOLERANCE = 1.0e-6

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


final_proxy = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.final_proxy"
)


def _fixtures():
    paths = sorted(glob.glob(os.path.join(FIXTURE_DIRECTORY, "mesh_proxy_*.json")))
    assert len(paths) == 8, paths
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


def _assert_vector_rows_close(actual, expected, label: str) -> None:
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


def _build_from_fixture(fixture):
    payload = fixture["input"]
    return final_proxy.build_mc2_final_proxy(
        task_id=payload["task_id"],
        setup_type="mesh_cloth",
        vertex_identities=payload["vertex_identities"],
        local_positions=payload["local_positions"],
        local_normals=payload["local_normals"],
        local_tangents=payload["local_tangents"],
        uvs=payload["uvs"],
        vertex_attributes=payload["vertex_attributes"],
        lines=payload["lines"],
        triangles=payload["triangles"],
    )


def test_final_proxy_matches_tier_a_oracle_fixtures() -> None:
    for fixture_name, fixture in _fixtures():
        result = _build_from_fixture(fixture)
        expected = fixture["expected"]["proxy"]

        assert list(result.proxy.vertex_attributes) == expected["vertex_attributes"], fixture_name
        assert [list(row) for row in result.proxy.triangles] == expected["triangles"], fixture_name
        assert {tuple(row) for row in result.proxy.edges} == {
            tuple(row) for row in expected["edges"]
        }, fixture_name
        assert [list(row) for row in result.vertex_to_vertex_ranges] == expected[
            "vertex_to_vertex_ranges"
        ], fixture_name
        assert list(result.vertex_to_vertex_data) == expected["vertex_to_vertex_data"], fixture_name
        assert [
            [list(record) for record in rows]
            for rows in result.vertex_to_triangle_records
        ] == expected["vertex_to_triangle_records"], fixture_name

        _assert_vector_rows_close(
            result.proxy.local_normals,
            expected["local_normals"],
            f"{fixture_name}:local_normals",
        )
        _assert_vector_rows_close(
            result.proxy.local_tangents,
            expected["local_tangents"],
            f"{fixture_name}:local_tangents",
        )
        _assert_vector_rows_close(
            result.vertex_bind_pose_positions,
            expected["vertex_bind_pose_positions"],
            f"{fixture_name}:vertex_bind_pose_positions",
        )
        _assert_vector_rows_close(
            result.vertex_bind_pose_rotations,
            expected["vertex_bind_pose_rotations"],
            f"{fixture_name}:vertex_bind_pose_rotations",
        )


TESTS = (("MC2 Mesh final proxy matches Tier A oracle", test_final_proxy_matches_tier_a_oracle_fixtures),)


def main() -> None:
    passed = 0
    for name, test in TESTS:
        test()
        passed += 1
        print(f"[PASS] {name}")
    print(f"{passed}/{len(TESTS)} passed")


if __name__ == "__main__":
    main()
