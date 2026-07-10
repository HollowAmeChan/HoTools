"""Pure source-rule tests for the MC2 MeshCloth N0 baseline builder."""

from __future__ import annotations

import importlib
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


def _proxy(
    positions,
    attributes,
    edges,
    *,
    triangles=(),
    setup_type="mesh_cloth",
):
    count = len(positions)
    return static_data.make_mc2_proxy_static_spec(
        task_id="mc2:mesh_cloth:test",
        setup_type=setup_type,
        vertex_identities=[f"mesh:v{index}" for index in range(count)],
        local_positions=positions,
        local_normals=[(0.0, 0.0, 1.0)] * count,
        local_tangents=[(1.0, 0.0, 0.0)] * count,
        uvs=[(0.0, 0.0)] * count,
        vertex_attributes=attributes,
        edges=edges,
        triangles=triangles,
    )


def _assert_vector(actual, expected, tolerance=1.0e-6):
    assert len(actual) == len(expected)
    for value, wanted in zip(actual, expected):
        assert math.isclose(value, wanted, abs_tol=tolerance, rel_tol=tolerance), (actual, expected)


def _expect_error(exception_type, callback, text: str) -> None:
    try:
        callback()
    except exception_type as exc:
        assert text in str(exc), str(exc)
    else:
        raise AssertionError(f"expected {exception_type.__name__}: {text}")


def test_single_fixed_triangle_builds_source_pose() -> None:
    proxy = _proxy(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        (0x81, 0x82, 0x82),
        ((0, 1), (0, 2), (1, 2)),
        triangles=((0, 1, 2),),
    )
    result = mesh_baseline.build_mc2_mesh_baseline(proxy)
    baseline = result.baseline
    assert result.final_proxy is proxy
    assert baseline.parent_indices == (-1, 0, 0)
    assert baseline.child_ranges == ((0, 2), (2, 0), (2, 0))
    assert baseline.child_data == (1, 2)
    assert baseline.baseline_flags == (0,)
    assert baseline.baseline_ranges == ((0, 3),)
    assert baseline.baseline_data == (0, 1, 2)
    assert baseline.root_indices == (-1, 0, 0)
    assert baseline.depths == (0.0, 1.0, 1.0)
    _assert_vector(baseline.vertex_local_positions[1], (0.0, 0.0, 1.0))
    _assert_vector(baseline.vertex_local_positions[2], (1.0, 0.0, 0.0))
    _assert_vector(baseline.vertex_local_rotations[0], (0.0, 0.0, 0.0, 1.0))
    _assert_vector(baseline.vertex_local_rotations[1], (0.0, 0.0, 0.0, 1.0))


def test_no_fixed_keeps_zero_initialized_pose_arrays() -> None:
    proxy = _proxy(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        (0x82, 0x82, 0x82),
        ((0, 1), (0, 2), (1, 2)),
        triangles=((0, 1, 2),),
    )
    baseline = mesh_baseline.build_mc2_mesh_baseline(proxy).baseline
    assert baseline.parent_indices == (-1, -1, -1)
    assert baseline.child_data == ()
    assert baseline.baseline_data == ()
    assert baseline.root_indices == (-1, -1, -1)
    assert baseline.depths == (0.0, 0.0, 0.0)
    assert baseline.vertex_local_rotations == ((0.0, 0.0, 0.0, 0.0),) * 3


def test_disconnected_island_without_fixed_stays_outside_baseline() -> None:
    proxy = _proxy(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (3.0, 0.0, 0.0), (4.0, 0.0, 0.0)),
        (0x01, 0x02, 0x02, 0x02),
        ((0, 1), (2, 3)),
    )
    baseline = mesh_baseline.build_mc2_mesh_baseline(proxy).baseline
    assert baseline.parent_indices == (-1, 0, -1, -1)
    assert baseline.baseline_data == (0, 1)
    assert baseline.root_indices == (-1, 0, -1, -1)
    assert baseline.depths == (0.0, 1.0, 0.0, 0.0)
    assert baseline.vertex_local_rotations[2] == (0.0, 0.0, 0.0, 0.0)
    assert baseline.vertex_local_rotations[3] == (0.0, 0.0, 0.0, 0.0)


def test_parent_cost_uses_fixed_distance_then_move_angle() -> None:
    fixed_proxy = _proxy(
        ((0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        (0x01, 0x01, 0x02),
        ((0, 2), (1, 2)),
    )
    fixed_baseline = mesh_baseline.build_mc2_mesh_baseline(fixed_proxy).baseline
    assert fixed_baseline.parent_indices == (-1, -1, 0)
    assert fixed_baseline.baseline_data == (0, 2)

    angle_proxy = _proxy(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (2.0, 0.1, 0.0)),
        (0x01, 0x02, 0x02, 0x02),
        ((0, 1), (0, 2), (1, 3), (2, 3)),
    )
    angle_baseline = mesh_baseline.build_mc2_mesh_baseline(angle_proxy).baseline
    assert angle_baseline.parent_indices == (-1, 0, 0, 1)


def test_equal_cost_uses_lowest_vertex_index_canonical_tie_break() -> None:
    proxy = _proxy(
        ((-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        (0x01, 0x01, 0x02),
        ((0, 2), (1, 2)),
    )
    result = mesh_baseline.build_mc2_mesh_baseline(proxy)
    assert result.tie_break == "lowest_vertex_index"
    assert result.baseline.parent_indices == (-1, -1, 0)


def test_earlier_move_in_same_frontier_can_parent_later_move() -> None:
    proxy = _proxy(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        (0x01, 0x02, 0x02),
        ((0, 1), (0, 2), (1, 2)),
    )
    baseline = mesh_baseline.build_mc2_mesh_baseline(proxy).baseline
    assert baseline.parent_indices == (-1, 0, 1)
    assert baseline.root_indices == (-1, 0, 0)
    assert baseline.depths == (0.0, 0.5, 1.0)


def test_zero_distance_finalizes_proxy_attribute_and_signature() -> None:
    proxy = _proxy(
        ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        (0x01, 0x02),
        ((0, 1),),
    )
    result = mesh_baseline.build_mc2_mesh_baseline(proxy)
    assert result.final_proxy is not proxy
    assert result.final_proxy.vertex_attributes == (0x01, 0x22)
    assert result.final_proxy.proxy_signature != proxy.proxy_signature
    assert result.baseline.proxy_signature == result.final_proxy.proxy_signature
    assert result.baseline.vertex_local_positions[1] == (0.0, 0.0, 0.0)


def test_line_flag_and_non_mesh_rejection() -> None:
    proxy = _proxy(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        (0x01, 0x02),
        ((0, 1),),
    )
    result = mesh_baseline.build_mc2_mesh_baseline(proxy)
    assert result.baseline.baseline_flags == (mesh_baseline.MC2_BASELINE_INCLUDE_LINE,)

    bone_proxy = _proxy(
        ((0.0, 0.0, 0.0),),
        (0x01,),
        (),
        setup_type="bone_cloth",
    )
    _expect_error(
        ValueError,
        lambda: mesh_baseline.build_mc2_mesh_baseline(bone_proxy),
        "only accepts mesh_cloth",
    )


TESTS = (
    ("single fixed triangle source pose", test_single_fixed_triangle_builds_source_pose),
    ("no fixed zero initialization", test_no_fixed_keeps_zero_initialized_pose_arrays),
    ("disconnected island", test_disconnected_island_without_fixed_stays_outside_baseline),
    ("fixed distance and move angle", test_parent_cost_uses_fixed_distance_then_move_angle),
    ("canonical equal-cost tie", test_equal_cost_uses_lowest_vertex_index_canonical_tie_break),
    ("same-frontier move parent", test_earlier_move_in_same_frontier_can_parent_later_move),
    ("zero distance finalizes proxy", test_zero_distance_finalizes_proxy_attribute_and_signature),
    ("line flag and setup rejection", test_line_flag_and_non_mesh_rejection),
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
