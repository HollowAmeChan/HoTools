"""Raw ABI tests for MC2 native static-build kernels."""

from __future__ import annotations

import gc
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


def test_mesh_final_proxy_owned_context_transfer() -> None:
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
    owned = hotools_native.mc2_build_mesh_final_proxy_derived_v0(
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
        True,
    )
    proxy_arrays = (
        owned["proxy_local_positions"],
        owned["proxy_local_normals"],
        owned["proxy_local_tangents"],
        owned["proxy_uvs"],
        owned["proxy_attributes"],
        owned["proxy_edges"],
        owned["proxy_triangles"],
    )
    proxy_owners = (
        owned["_proxy_positions_owner"],
        owned["_proxy_normals_owner"],
        owned["_proxy_tangents_owner"],
        owned["_proxy_uvs_owner"],
        owned["_proxy_attributes_owner"],
        owned["_proxy_edges_owner"],
        owned["_proxy_triangles_owner"],
    )
    frame_arrays = (
        owned["frame_triangle_ranges"],
        owned["frame_triangle_records"],
        owned["frame_bind_rotations"],
    )
    frame_owners = (
        owned["_frame_triangle_ranges_owner"],
        owned["_frame_triangle_records_owner"],
        owned["_frame_bind_rotations_owner"],
    )
    context = hotools_native.mc2_context_v0_create(0, 4)
    try:
        hotools_native.mc2_context_v0_update_proxy_static(
            context, *proxy_arrays, *proxy_owners
        )
        hotools_native.mc2_context_v0_update_frame_producer_static(
            context, *frame_arrays, *frame_owners
        )
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["proxy_static_ready"] is True
        assert info["proxy_static_revision"] == 1
        assert info["owned_static_take_count"] == 2
        try:
            hotools_native.mc2_context_v0_update_proxy_static(
                context, *proxy_arrays, *proxy_owners
            )
        except ValueError as exc:
            assert "owner does not match" in str(exc)
        else:
            raise AssertionError("consumed proxy owner was accepted twice")
    finally:
        hotools_native.mc2_context_v0_free(context)


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


def test_mesh_baseline_owned_context_transfer() -> None:
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
    owned = hotools_native.mc2_build_mesh_baseline_derived_v0(
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
        True,
    )
    baseline_arrays = (
        owned["baseline_parents"],
        owned["baseline_child_ranges"],
        owned["baseline_child_data"],
        owned["baseline_flags"],
        owned["baseline_ranges"],
        owned["baseline_data"],
        owned["baseline_roots"],
        owned["baseline_depths"],
        owned["baseline_local_positions"],
        owned["baseline_local_rotations"],
    )
    baseline_owners = (
        owned["_baseline_parents_owner"],
        owned["_baseline_child_ranges_owner"],
        owned["_baseline_child_data_owner"],
        owned["_baseline_flags_owner"],
        owned["_baseline_ranges_owner"],
        owned["_baseline_data_owner"],
        owned["_baseline_roots_owner"],
        owned["_baseline_depths_owner"],
        owned["_baseline_local_positions_owner"],
        owned["_baseline_local_rotations_owner"],
    )
    context = hotools_native.mc2_context_v0_create(0, 3)
    try:
        hotools_native.mc2_context_v0_update_proxy_static(
            context,
            positions.astype(np.float32),
            normals.astype(np.float32),
            tangents.astype(np.float32),
            np.zeros((3, 2), dtype=np.float32),
            attributes,
            edges,
            np.empty((0, 3), dtype=np.int32),
        )
        hotools_native.mc2_context_v0_update_baseline_static(
            context, *baseline_arrays, *baseline_owners
        )
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["baseline_static_ready"] is True
        assert info["baseline_static_revision"] == 1
        assert info["owned_static_take_count"] == 1
        try:
            hotools_native.mc2_context_v0_update_baseline_static(
                context, *baseline_arrays, *baseline_owners
            )
        except ValueError as exc:
            assert "owner does not match" in str(exc)
        else:
            raise AssertionError("consumed baseline owner was accepted twice")
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_distance_derived_arrays_and_owner() -> None:
    positions = np.asarray(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
        ),
        dtype=np.float64,
    )
    attributes = np.asarray((0x02,) * 4, dtype=np.uint8)
    parents = np.asarray((-1,) * 4, dtype=np.int32)
    edges = np.asarray(((0, 1), (0, 2), (0, 3), (1, 2), (2, 3)), dtype=np.int32)
    triangles = np.asarray(((0, 1, 2), (0, 2, 3)), dtype=np.int32)
    adjacency_ranges = np.asarray(((0, 3), (3, 2), (5, 3), (8, 2)), dtype=np.int32)
    adjacency_data = np.asarray((3, 2, 1, 2, 0, 3, 1, 0, 2, 0), dtype=np.int32)

    derived = hotools_native.mc2_build_distance_derived_v0(
        positions,
        attributes,
        parents,
        edges,
        triangles,
        adjacency_ranges,
        adjacency_data,
    )
    ranges = derived["distance_ranges"]
    targets = derived["distance_targets"]
    rests = derived["distance_rest_signed"]
    del derived
    gc.collect()

    assert ranges.dtype == np.int32 and ranges.shape == (4, 2)
    assert targets.dtype == np.int32 and targets.shape == (12,)
    assert rests.dtype == np.float32 and rests.shape == (12,)
    np.testing.assert_array_equal(ranges, ((0, 3), (3, 3), (6, 3), (9, 3)))
    np.testing.assert_array_equal(targets, (3, 2, 1, 3, 2, 0, 3, 1, 0, 1, 2, 0))
    np.testing.assert_allclose(
        rests,
        (
            -1.0, -np.sqrt(2.0), -1.0,
            -np.sqrt(2.0), -1.0, -1.0,
            -1.0, -1.0, -np.sqrt(2.0),
            -np.sqrt(2.0), -1.0, -1.0,
        ),
        atol=1.0e-6,
    )


def test_bending_derived_arrays() -> None:
    positions = np.asarray(
        ((0.0, 1.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        dtype=np.float32,
    )
    attributes = np.asarray((0x02,) * 4, dtype=np.uint8)
    edges = np.asarray(((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)), dtype=np.int32)
    triangles = np.asarray(((0, 2, 3), (1, 3, 2)), dtype=np.int32)
    columns = np.eye(4, dtype=np.float32).T.copy()

    derived = hotools_native.mc2_build_bending_derived_v0(
        positions,
        attributes,
        edges,
        triangles,
        columns,
    )

    assert derived["bending_quads"].dtype == np.int32
    assert derived["bending_rest_angle_or_volume"].dtype == np.float32
    assert derived["bending_sign_or_volume"].dtype == np.int8
    np.testing.assert_array_equal(derived["bending_quads"], ((1, 0, 2, 3),))
    np.testing.assert_allclose(derived["bending_rest_angle_or_volume"], (0.0,), atol=1.0e-7)
    np.testing.assert_array_equal(derived["bending_sign_or_volume"], (1,))


def test_self_collision_derived_arrays() -> None:
    attributes = np.asarray((0x01, 0x02, 0x00, 0x82), dtype=np.uint8)
    depths = np.asarray((0.0, 0.25, 0.5, 1.0), dtype=np.float64)
    edges = np.asarray(((0, 1), (1, 2)), dtype=np.int32)
    triangles = np.asarray(((0, 1, 3),), dtype=np.int32)

    derived = hotools_native.mc2_build_self_collision_derived_v0(
        attributes,
        depths,
        edges,
        triangles,
    )

    assert derived["point_count"] == 4
    assert derived["edge_count"] == 2
    assert derived["triangle_count"] == 1
    np.testing.assert_array_equal(
        derived["primitive_flags"],
        (
            0x24000000,
            0,
            0x64000000,
            0,
            0x05000000,
            0x49000000,
            0x06000000,
        ),
    )
    np.testing.assert_array_equal(
        derived["particle_indices"],
        (
            (0, -1, -1),
            (1, -1, -1),
            (2, -1, -1),
            (3, -1, -1),
            (0, 1, -1),
            (1, 2, -1),
            (0, 1, 3),
        ),
    )
    np.testing.assert_allclose(
        derived["primitive_depths"],
        (0.0, 0.25, 0.5, 1.0, 0.125, 0.375, 1.25 / 3.0),
        atol=1.0e-7,
    )


def test_center_static_derived_arrays_and_owner() -> None:
    positions = np.asarray(
        ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 3.0)),
        dtype=np.float64,
    )
    normals = np.asarray(((0.0, 1.0, 0.0),) * 4, dtype=np.float64)
    tangents = np.asarray(((0.0, 0.0, 1.0),) * 4, dtype=np.float64)
    attributes = np.asarray((0x01, 0x02, 0x01, 0x01), dtype=np.uint8)
    bind_rotations = np.asarray(((0.0, 0.0, 0.0, 1.0),) * 4, dtype=np.float64)
    edges = np.asarray(((0, 1), (0, 2), (1, 2)), dtype=np.int32)
    gravity = np.asarray((0.436435759, -0.8728715, 0.21821788), dtype=np.float64)

    derived = hotools_native.mc2_build_center_static_derived_v0(
        positions,
        normals,
        tangents,
        attributes,
        bind_rotations,
        edges,
        gravity,
    )
    fixed = derived["fixed_indices"]
    center = derived["local_center_position"]
    local_gravity = derived["initial_local_gravity_direction"]
    del derived
    gc.collect()

    assert fixed.dtype == np.int32
    assert center.dtype == np.float32
    assert local_gravity.dtype == np.float32
    np.testing.assert_array_equal(fixed, (0, 2, 3))
    np.testing.assert_allclose(center, (0.0, 2.0 / 3.0, 1.0), atol=1.0e-7)
    np.testing.assert_allclose(local_gravity, gravity, atol=1.0e-7)

    invalid_bind_rotations = bind_rotations.copy()
    invalid_bind_rotations[1] = 0.0
    try:
        hotools_native.mc2_build_center_static_derived_v0(
            positions,
            normals,
            tangents,
            attributes,
            invalid_bind_rotations,
            edges,
            gravity,
        )
    except ValueError as exc:
        assert "vertex bind pose rotation" in str(exc)
    else:
        raise AssertionError("invalid non-fixed bind rotation was accepted")


if __name__ == "__main__":
    test_triangle_direction_unifies_connected_surface()
    print("PASS MC2 native triangle direction")
    test_triangle_direction_rejects_degenerate_input()
    print("PASS MC2 native triangle direction validation")
    test_mesh_final_proxy_derived_arrays()
    print("PASS MC2 native final proxy derived arrays")
    test_mesh_final_proxy_owned_context_transfer()
    print("PASS MC2 native final proxy owned context transfer")
    test_mesh_baseline_derived_arrays()
    print("PASS MC2 native baseline derived arrays")
    test_mesh_baseline_owned_context_transfer()
    print("PASS MC2 native baseline owned context transfer")
    test_distance_derived_arrays_and_owner()
    print("PASS MC2 native Distance derived arrays")
    test_bending_derived_arrays()
    print("PASS MC2 native Bending derived arrays")
    test_self_collision_derived_arrays()
    print("PASS MC2 native self-collision derived arrays")
    test_center_static_derived_arrays_and_owner()
    print("PASS MC2 native Center static derived arrays")
