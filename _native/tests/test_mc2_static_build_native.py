"""Raw ABI tests for MC2 native static-build kernels."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
package_dir = Path(
    os.environ.get("HOTOOLS_NATIVE_TEST_DIR", ROOT / "_Lib" / "py313" / "HotoolsPackage")
)
sys.path.insert(0, str(package_dir))

import hotools_native


def test_triangle_direction_unifies_connected_surface() -> None:
    positions = np.asarray(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
        ),
        dtype=np.float64,
    )
    triangles = np.asarray(((0, 1, 2), (0, 3, 2)), dtype=np.int32)
    normals = np.empty((2, 3), dtype=np.float64)

    hotools_native.mc2_optimize_triangle_direction_v0(
        positions,
        triangles,
        normals,
    )

    np.testing.assert_array_equal(triangles, ((0, 1, 2), (0, 2, 3)))
    np.testing.assert_allclose(normals, ((0.0, 0.0, 1.0),) * 2, atol=1.0e-12)


def test_triangle_direction_rejects_degenerate_input() -> None:
    positions = np.asarray(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        dtype=np.float64,
    )
    triangles = np.asarray(((0, 1, 2),), dtype=np.int32)
    normals = np.empty((1, 3), dtype=np.float64)
    try:
        hotools_native.mc2_optimize_triangle_direction_v0(
            positions,
            triangles,
            normals,
        )
    except ValueError as exc:
        assert "triangle normal must be non-zero" in str(exc)
    else:
        raise AssertionError("degenerate triangle was accepted")


def test_mesh_final_proxy_derived_arrays() -> None:
    positions = np.asarray(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)),
        dtype=np.float64,
    )
    normals = np.asarray(((0.0, 0.0, 1.0),) * 4, dtype=np.float64)
    tangents = np.asarray(((1.0, 0.0, 0.0),) * 4, dtype=np.float64)
    uvs = np.asarray(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)), dtype=np.float64)
    attributes = np.asarray((0x02,) * 4, dtype=np.uint8)
    triangles = np.asarray(((0, 1, 2), (0, 2, 3)), dtype=np.int32)
    triangle_normals = np.asarray(((0.0, 0.0, 1.0),) * 2, dtype=np.float64)
    lines = np.empty((0, 2), dtype=np.int32)
    out_edges = np.empty((6, 2), dtype=np.int32)
    neighbor_ranges = np.empty((4, 2), dtype=np.int32)
    neighbor_data = np.empty(12, dtype=np.int32)
    triangle_ranges = np.empty((4, 2), dtype=np.int32)
    triangle_data = np.empty((6, 2), dtype=np.int32)
    bind_positions = np.empty((4, 3), dtype=np.float64)
    bind_rotations = np.empty((4, 4), dtype=np.float64)

    counts = hotools_native.mc2_build_mesh_final_proxy_derived_v0(
        positions,
        normals,
        tangents,
        uvs,
        attributes,
        triangles,
        triangle_normals,
        lines,
        out_edges,
        neighbor_ranges,
        neighbor_data,
        triangle_ranges,
        triangle_data,
        bind_positions,
        bind_rotations,
    )

    assert counts == {"edge_count": 5, "neighbor_count": 10, "triangle_record_count": 6}
    np.testing.assert_array_equal(
        out_edges[:5],
        ((0, 1), (0, 2), (0, 3), (1, 2), (2, 3)),
    )
    np.testing.assert_array_equal(neighbor_ranges, ((0, 3), (3, 2), (5, 3), (8, 2)))
    np.testing.assert_array_equal(neighbor_data[:10], (3, 2, 1, 2, 0, 3, 1, 0, 2, 0))
    np.testing.assert_array_equal(triangle_ranges, ((0, 2), (2, 1), (3, 2), (5, 1)))
    assert np.all(attributes & np.uint8(0x80))
    np.testing.assert_allclose(normals, ((0.0, 0.0, 1.0),) * 4, atol=1.0e-12)
    np.testing.assert_allclose(tangents, ((0.0, -1.0, 0.0),) * 4, atol=1.0e-12)
    np.testing.assert_allclose(bind_positions, -positions, atol=1.0e-12)
    np.testing.assert_allclose(np.linalg.norm(bind_rotations, axis=1), 1.0, atol=1.0e-12)


def test_mesh_baseline_derived_arrays() -> None:
    positions = np.asarray(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        dtype=np.float64,
    )
    normals = np.asarray(((0.0, 0.0, 1.0),) * 3, dtype=np.float64)
    tangents = np.asarray(((1.0, 0.0, 0.0),) * 3, dtype=np.float64)
    attributes = np.asarray((0x01, 0x02, 0x02), dtype=np.uint8)
    edges = np.asarray(((0, 1), (1, 2)), dtype=np.int32)
    parents = np.empty(3, dtype=np.int32)
    child_ranges = np.empty((3, 2), dtype=np.int32)
    child_data = np.empty(3, dtype=np.int32)
    baseline_flags = np.empty(3, dtype=np.uint8)
    baseline_ranges = np.empty((3, 2), dtype=np.int32)
    baseline_data = np.empty(3, dtype=np.int32)
    roots = np.empty(3, dtype=np.int32)
    depths = np.empty(3, dtype=np.float64)
    local_positions = np.empty((3, 3), dtype=np.float64)
    local_rotations = np.empty((3, 4), dtype=np.float64)

    counts = hotools_native.mc2_build_mesh_baseline_derived_v0(
        positions,
        normals,
        tangents,
        attributes,
        edges,
        parents,
        child_ranges,
        child_data,
        baseline_flags,
        baseline_ranges,
        baseline_data,
        roots,
        depths,
        local_positions,
        local_rotations,
    )

    assert counts == {"child_count": 2, "baseline_count": 1, "baseline_data_count": 3}
    np.testing.assert_array_equal(parents, (-1, 0, 1))
    np.testing.assert_array_equal(child_ranges, ((0, 1), (1, 1), (2, 0)))
    np.testing.assert_array_equal(child_data[:2], (1, 2))
    np.testing.assert_array_equal(baseline_flags[:1], (0x01,))
    np.testing.assert_array_equal(baseline_ranges[:1], ((0, 3),))
    np.testing.assert_array_equal(baseline_data, (0, 1, 2))
    np.testing.assert_array_equal(roots, (-1, 0, 0))
    np.testing.assert_allclose(depths, (0.0, 0.5, 1.0), atol=1.0e-12)
    np.testing.assert_allclose(
        local_positions,
        ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 1.0)),
        atol=1.0e-12,
    )
    np.testing.assert_allclose(local_rotations, ((0.0, 0.0, 0.0, 1.0),) * 3, atol=1.0e-12)

    shared_attributes = np.asarray((0x01, 0x02, 0x02), dtype=np.uint8)
    shared_roots = np.empty(3, dtype=np.int32)
    shared_depths = np.empty(3, dtype=np.float64)
    shared_positions = np.empty((3, 3), dtype=np.float64)
    shared_rotations = np.empty((3, 4), dtype=np.float64)
    hotools_native.mc2_build_baseline_pose_depth_derived_v0(
        positions,
        normals,
        tangents,
        shared_attributes,
        parents,
        baseline_data,
        shared_roots,
        shared_depths,
        shared_positions,
        shared_rotations,
    )
    np.testing.assert_array_equal(shared_attributes, attributes)
    np.testing.assert_array_equal(shared_roots, roots)
    np.testing.assert_allclose(shared_depths, depths, atol=1.0e-12)
    np.testing.assert_allclose(shared_positions, local_positions, atol=1.0e-12)
    np.testing.assert_allclose(shared_rotations, local_rotations, atol=1.0e-12)


if __name__ == "__main__":
    test_triangle_direction_unifies_connected_surface()
    print("PASS MC2 native triangle direction")
    test_triangle_direction_rejects_degenerate_input()
    print("PASS MC2 native triangle direction validation")
    test_mesh_final_proxy_derived_arrays()
    print("PASS MC2 native final proxy derived arrays")
    test_mesh_baseline_derived_arrays()
    print("PASS MC2 native baseline derived arrays")
