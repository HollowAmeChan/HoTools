import json
import os
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, os.environ.get("HOTOOLS_NATIVE_TEST_DIR", str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage")))

import hotools_native  # noqa: E402


def parameters():
    return (
        np.zeros(47, dtype=np.float32),
        np.zeros(11, dtype=np.int32),
        np.zeros((9, 16), dtype=np.float32),
    )


def frame(count, offset=0.0):
    positions = np.zeros((count, 3), dtype=np.float32)
    positions[:, 0] = np.arange(count, dtype=np.float32) + offset
    rotations = np.zeros((count, 4), dtype=np.float32)
    rotations[:, 3] = 1.0
    return positions, rotations


def update_dynamic(context, frame_index, generation, positions, rotations, **scalars):
    hotools_native.mc2_context_v0_update_dynamic(
        context,
        frame_index,
        generation,
        positions,
        rotations,
        scalars.get("velocity_weight", 1.0),
        scalars.get("gravity_ratio", 1.0),
        scalars.get("scale_ratio", 1.0),
        scalars.get("negative_scale_sign", 1.0),
        scalars.get("frame_interpolation", 1.0),
    )


def step(context, dt, simulation_power_y=1.0, simulation_power_z=1.0):
    hotools_native.mc2_context_v0_step(
        context, dt, simulation_power_y, simulation_power_z
    )


def static_arrays(count):
    positions = np.zeros((count, 3), dtype=np.float32)
    normals = np.zeros((count, 3), dtype=np.float32)
    normals[:, 2] = 1.0
    tangents = np.zeros((count, 3), dtype=np.float32)
    tangents[:, 0] = 1.0
    uvs = np.zeros((count, 2), dtype=np.float32)
    attributes = np.full(count, 2, dtype=np.uint8)
    edges = np.array([[index, index + 1] for index in range(count - 1)], dtype=np.int32).reshape(-1, 2)
    triangles = np.empty((0, 3), dtype=np.int32)
    parents = np.arange(-1, count - 1, dtype=np.int32)
    child_ranges = np.array(
        [[index, 1 if index + 1 < count else 0] for index in range(count)],
        dtype=np.int32,
    )
    child_data = np.arange(1, count, dtype=np.int32)
    flags = np.array([0], dtype=np.uint8)
    ranges = np.array([[0, count]], dtype=np.int32)
    data = np.arange(count, dtype=np.int32)
    roots = np.zeros(count, dtype=np.int32)
    depths = np.linspace(0.0, 1.0, count, dtype=np.float32)
    local_positions = np.zeros((count, 3), dtype=np.float32)
    local_rotations = np.zeros((count, 4), dtype=np.float32)
    local_rotations[:, 3] = 1.0
    return (
        (positions, normals, tangents, uvs, attributes, edges, triangles),
        (parents, child_ranges, child_data, flags, ranges, data, roots, depths, local_positions, local_rotations),
    )


def expect_error(exception, callback, text):
    try:
        callback()
    except exception as exc:
        assert text in str(exc), str(exc)
    else:
        raise AssertionError(f"expected {exception.__name__}: {text}")


def test_debug_baseline_readback_is_exact_and_validated():
    context = hotools_native.mc2_context_v0_create(0, 4)
    try:
        proxy, baseline = static_arrays(4)
        baseline = list(baseline)
        baseline[0] = np.array([-1, 0, 1, 2], dtype=np.int32)
        baseline[6] = np.array([-1, 0, 0, 0], dtype=np.int32)
        baseline[7] = np.array([0.0, 0.2, 0.55, 1.0], dtype=np.float32)
        hotools_native.mc2_context_v0_update_proxy_static(context, *proxy)
        hotools_native.mc2_context_v0_update_baseline_static(context, *baseline)

        parents = np.empty((4,), dtype=np.int32)
        roots = np.empty((4,), dtype=np.int32)
        depths = np.empty((4,), dtype=np.float32)
        hotools_native.mc2_context_v0_read_debug_baseline(
            context, parents, roots, depths
        )
        np.testing.assert_array_equal(parents, baseline[0])
        np.testing.assert_array_equal(roots, baseline[6])
        np.testing.assert_array_equal(depths, baseline[7])

        expect_error(
            TypeError,
            lambda: hotools_native.mc2_context_v0_read_debug_baseline(
                context,
                np.empty((4,), dtype=np.float32),
                roots,
                depths,
            ),
            "out_baseline_parents must use int32 elements",
        )
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_radius_vertex_multipliers_drive_self_primitive_thickness():
    context = hotools_native.mc2_context_v0_create(0, 3)
    try:
        proxy, baseline = static_arrays(3)
        proxy = list(proxy)
        proxy[6] = np.array([[0, 1, 2]], dtype=np.int32)
        radius_multipliers = np.array([0.0, 0.5, 1.0], dtype=np.float32)
        hotools_native.mc2_context_v0_update_proxy_static(
            context,
            *proxy,
            radius_multipliers,
        )
        baseline = list(baseline)
        baseline[7] = np.full(3, 0.5, dtype=np.float32)
        hotools_native.mc2_context_v0_update_baseline_static(context, *baseline)
        hotools_native.mc2_context_v0_update_distance_static(
            context,
            np.zeros((3, 2), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_bending_static(
            context,
            np.empty((0, 4), dtype=np.int32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=np.int8),
        )
        derived = hotools_native.mc2_build_self_collision_derived_v0(
            proxy[4],
            baseline[7],
            proxy[5],
            proxy[6],
        )
        hotools_native.mc2_context_v0_update_self_collision_static(
            context,
            derived["primitive_flags"],
            derived["particle_indices"],
            derived["primitive_depths"],
            derived["point_count"],
            derived["edge_count"],
            derived["triangle_count"],
        )
        floats, ints, curves = parameters()
        ints[9] = 2
        curves[8, :] = 0.01
        hotools_native.mc2_context_v0_update_parameters(context, floats, ints, curves)
        positions = np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            dtype=np.float32,
        )
        rotations = np.zeros((3, 4), dtype=np.float32)
        rotations[:, 3] = 1.0
        update_dynamic(context, 1, 1, positions, rotations)
        hotools_native.mc2_context_v0_reset(context)
        step(context, 1.0 / 90.0)

        primitive_count = int(derived["point_count"] + derived["edge_count"] + derived["triangle_count"])
        inverse_masses = np.empty((primitive_count, 3), dtype=np.float32)
        aabb_min = np.empty((primitive_count, 3), dtype=np.float32)
        aabb_max = np.empty((primitive_count, 3), dtype=np.float32)
        thickness = np.empty((primitive_count,), dtype=np.float32)
        hotools_native.mc2_context_v0_read_self_collision_primitives(
            context,
            inverse_masses,
            aabb_min,
            aabb_max,
            thickness,
        )
        np.testing.assert_allclose(
            thickness,
            np.array([0.0, 0.005, 0.01, 0.0025, 0.0075, 0.005], dtype=np.float32),
            rtol=0.0,
            atol=1.0e-7,
        )
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_tether_rollout_gate_and_source_order():
    context = hotools_native.mc2_context_v0_create(0, 2)
    try:
        proxy, baseline = static_arrays(2)
        proxy = list(proxy)
        proxy[4] = np.array([1, 2], dtype=np.uint8)
        baseline = list(baseline)
        baseline[6] = np.array([0, 0], dtype=np.int32)
        baseline[8][1, 0] = 1.0
        hotools_native.mc2_context_v0_update_proxy_static(context, *proxy)
        hotools_native.mc2_context_v0_update_baseline_static(context, *baseline)
        hotools_native.mc2_context_v0_update_distance_static(
            context,
            np.zeros((2, 2), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_bending_static(
            context,
            np.empty((0, 4), dtype=np.int32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=np.int8),
        )
        floats, ints, curves = parameters()
        floats[0] = 0.35
        floats[1] = 1.0
        floats[24] = 0.4
        floats[25] = 0.03
        hotools_native.mc2_context_v0_update_parameters(context, floats, ints, curves)
        positions = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32)
        rotations = np.zeros((2, 4), dtype=np.float32)
        rotations[:, 3] = 1.0

        hotools_native.mc2_context_v0_set_tether_enabled(context, True)
        update_dynamic(context, 1, 0, positions, rotations)
        hotools_native.mc2_context_v0_reset(context)
        step(context, 1.0, simulation_power_y=1.0, simulation_power_z=0.0)
        output = np.empty_like(positions)
        output_rotations = np.empty_like(rotations)
        hotools_native.mc2_context_v0_read(context, output, output_rotations)
        np.testing.assert_allclose(
            output,
            np.array([[0, 0, 0], [1.03, 0, 0]], dtype=np.float32),
            rtol=0.0,
            atol=1.0e-6,
        )
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["tether_enabled"] is True
        assert info["tether_solve_count"] == 1

        hotools_native.mc2_context_v0_set_tether_enabled(context, False)
        update_dynamic(context, 2, 0, positions, rotations)
        hotools_native.mc2_context_v0_reset(context)
        step(context, 1.0, simulation_power_y=1.0, simulation_power_z=0.0)
        hotools_native.mc2_context_v0_read(context, output, output_rotations)
        np.testing.assert_allclose(
            output,
            np.array([[0, 0, 0], [1.35, 0, 0]], dtype=np.float32),
            rtol=0.0,
            atol=1.0e-6,
        )
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["tether_enabled"] is False
        assert info["tether_solve_count"] == 1
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_angle_runtime_values_and_source_order():
    context = hotools_native.mc2_context_v0_create(0, 3)
    try:
        proxy, baseline = static_arrays(3)
        proxy = list(proxy)
        proxy[4] = np.array([1, 2, 2], dtype=np.uint8)
        baseline = list(baseline)
        baseline[8][1:, 0] = 1.0
        hotools_native.mc2_context_v0_update_proxy_static(context, *proxy)
        hotools_native.mc2_context_v0_update_baseline_static(context, *baseline)
        hotools_native.mc2_context_v0_update_distance_static(
            context,
            np.zeros((3, 2), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_bending_static(
            context,
            np.empty((0, 4), dtype=np.int32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=np.int8),
        )
        floats, ints, curves = parameters()
        floats[28] = 0.8
        ints[4] = 1
        curves[3, :] = 0.2
        hotools_native.mc2_context_v0_update_parameters(context, floats, ints, curves)
        positions = np.array(
            [[0, 0, 0], [0.8, 0.6, 0], [1.5, 1.3, 0]],
            dtype=np.float32,
        )
        rotations = np.zeros((3, 4), dtype=np.float32)
        rotations[:, 3] = 1.0
        update_dynamic(context, 1, 0, positions, rotations)
        hotools_native.mc2_context_v0_reset(context)
        step(context, 1.0 / 90.0, simulation_power_y=1.0, simulation_power_z=0.0)

        actual = np.empty_like(positions)
        actual_rotations = np.empty_like(rotations)
        step_basic_positions = np.empty_like(positions)
        step_basic_rotations = np.empty_like(rotations)
        hotools_native.mc2_context_v0_read(context, actual, actual_rotations)
        hotools_native.mc2_context_v0_read_step_basic(
            context, step_basic_positions, step_basic_rotations
        )
        expected = positions.copy()
        expected_velocity_reference = positions.copy()
        hotools_native.project_angle_constraints_mc2(
            expected,
            np.array([0.0, 1.0, 1.0], dtype=np.float32),
            baseline[0],
            baseline[4][:, 0].copy(),
            baseline[4][:, 1].copy(),
            baseline[5],
            step_basic_positions,
            step_basic_rotations,
            np.full(3, 0.2, dtype=np.float32),
            np.zeros(3, dtype=np.float32),
            expected_velocity_reference,
            0.8,
            0.0,
            0.0,
        )
        np.testing.assert_allclose(actual, expected, rtol=1.0e-6, atol=1.0e-6)
        assert not np.allclose(actual, positions, rtol=0.0, atol=1.0e-5)
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["angle_solve_count"] == 1
        assert info["distance_solve_count"] == 0
        assert info["bending_solve_count"] == 0

        limit_floats, limit_ints, limit_curves = parameters()
        limit_floats[30] = 1.0
        limit_ints[5] = 1
        limit_curves[4, :] = 0.0
        hotools_native.mc2_context_v0_update_parameters(
            context, limit_floats, limit_ints, limit_curves
        )
        update_dynamic(context, 2, 0, positions, rotations)
        hotools_native.mc2_context_v0_reset(context)
        step(context, 1.0 / 90.0, simulation_power_y=1.0, simulation_power_z=0.0)
        hotools_native.mc2_context_v0_read(context, actual, actual_rotations)
        assert not np.allclose(actual, positions, rtol=0.0, atol=1.0e-5)
        assert hotools_native.mc2_context_v0_inspect(context)["angle_solve_count"] == 2
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_motion_zero_max_distance_and_source_order():
    context = hotools_native.mc2_context_v0_create(0, 1)
    try:
        proxy, baseline = static_arrays(1)
        hotools_native.mc2_context_v0_update_proxy_static(context, *proxy)
        hotools_native.mc2_context_v0_update_baseline_static(context, *baseline)
        hotools_native.mc2_context_v0_update_distance_static(
            context,
            np.zeros((1, 2), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_bending_static(
            context,
            np.empty((0, 4), dtype=np.int32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=np.int8),
        )
        floats, ints, curves = parameters()
        floats[0] = 1.0
        floats[1] = 1.0
        floats[32] = 1.0
        ints[6] = 1
        curves[5, :] = 0.0
        hotools_native.mc2_context_v0_update_parameters(context, floats, ints, curves)
        positions = np.zeros((1, 3), dtype=np.float32)
        rotations = np.array([[0, 0, 0, 1]], dtype=np.float32)
        update_dynamic(context, 1, 0, positions, rotations)
        hotools_native.mc2_context_v0_reset(context)
        step(context, 1.0, simulation_power_y=1.0, simulation_power_z=0.0)
        actual = np.empty_like(positions)
        actual_rotations = np.empty_like(rotations)
        hotools_native.mc2_context_v0_read(context, actual, actual_rotations)
        np.testing.assert_allclose(actual, positions, rtol=0.0, atol=1.0e-7)
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["motion_solve_count"] == 1
        assert info["distance_solve_count"] == 0
        assert info["bending_solve_count"] == 0
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_collider_upload_is_transactional():
    context = hotools_native.mc2_context_v0_create(0, 1)
    try:
        types = np.array([0, 1, 2, 3], dtype=np.int32)
        groups = np.array([1, 2, 1, 1], dtype=np.int32)
        centers = np.zeros((4, 3), dtype=np.float32)
        segment_a = np.zeros((4, 3), dtype=np.float32)
        segment_b = np.zeros((4, 3), dtype=np.float32)
        radii = np.array([0.5, 0.25, 0.0, 1.0], dtype=np.float32)
        hotools_native.mc2_context_v0_update_colliders(
            context,
            3,
            types,
            groups,
            centers,
            segment_a,
            segment_b,
            centers.copy(),
            segment_a.copy(),
            segment_b.copy(),
            radii,
        )
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["collider_revision"] == 1
        assert info["collider_count"] == 4
        assert info["collided_by_groups"] == 3

        invalid_types = types.copy()
        invalid_types[2] = 9
        expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_colliders(
                context,
                3,
                invalid_types,
                groups,
                centers,
                segment_a,
                segment_b,
                centers,
                segment_a,
                segment_b,
                radii,
            ),
            "type",
        )
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["collider_revision"] == 1
        assert info["collider_count"] == 4
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_self_collision_static_upload_is_transactional():
    context = hotools_native.mc2_context_v0_create(0, 4)
    try:
        proxy, baseline = static_arrays(4)
        proxy = list(proxy)
        proxy[4] = np.array([1, 2, 0, 2], dtype=np.uint8)
        proxy[6] = np.array([[0, 1, 2]], dtype=np.int32)
        hotools_native.mc2_context_v0_update_proxy_static(context, *proxy)
        hotools_native.mc2_context_v0_update_baseline_static(context, *baseline)
        flags = np.array(
            [
                0x24000000, 0, 0x64000000, 0,
                0x05000000, 0x49000000, 0x45000000, 0x56000000,
            ],
            dtype=np.uint32,
        )
        indices = np.array(
            [
                [0, -1, -1], [1, -1, -1], [2, -1, -1], [3, -1, -1],
                [0, 1, -1], [1, 2, -1], [2, 3, -1], [0, 1, 2],
            ],
            dtype=np.int32,
        )
        vertex_depths = baseline[7]
        depths = np.array(
            [
                *vertex_depths,
                (vertex_depths[0] + vertex_depths[1]) / 2.0,
                (vertex_depths[1] + vertex_depths[2]) / 2.0,
                (vertex_depths[2] + vertex_depths[3]) / 2.0,
                (vertex_depths[0] + vertex_depths[1] + vertex_depths[2]) / 3.0,
            ],
            dtype=np.float32,
        )
        hotools_native.mc2_context_v0_update_self_collision_static(
            context, flags, indices, depths, 4, 3, 1,
        )
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["self_collision_static_ready"] is True
        assert info["self_collision_static_revision"] == 1
        assert info["self_primitive_count"] == 8
        assert info["self_point_primitive_count"] == 4
        assert info["self_edge_primitive_count"] == 3
        assert info["self_triangle_primitive_count"] == 1
        bad_flags = flags.copy()
        bad_flags[-1] ^= np.uint32(0x04000000)
        expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_self_collision_static(
                context, bad_flags, indices, depths, 4, 3, 1,
            ),
            "flags",
        )
        bad_indices = indices.copy()
        bad_indices[4] = (1, 0, -1)
        expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_self_collision_static(
                context, flags, bad_indices, depths, 4, 3, 1,
            ),
            "proxy order",
        )
        bad_depths = depths.copy()
        bad_depths[-1] += np.float32(0.1)
        expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_self_collision_static(
                context, flags, indices, bad_depths, 4, 3, 1,
            ),
            "depth",
        )
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["self_collision_static_revision"] == 1
        assert info["self_primitive_count"] == 8
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_self_collision_primitive_dynamics_follow_first_step_source_order():
    context = hotools_native.mc2_context_v0_create(0, 3)
    try:
        proxy, baseline = static_arrays(3)
        proxy = list(proxy)
        proxy[4] = np.array([1, 2, 2], dtype=np.uint8)
        proxy[6] = np.array([[0, 1, 2]], dtype=np.int32)
        hotools_native.mc2_context_v0_update_proxy_static(context, *proxy)
        hotools_native.mc2_context_v0_update_baseline_static(context, *baseline)
        flags = np.array(
            [
                0x24000000, 0, 0,
                0x05000000, 0x01000000,
                0x06000000,
            ],
            dtype=np.uint32,
        )
        indices = np.array(
            [
                [0, -1, -1], [1, -1, -1], [2, -1, -1],
                [0, 1, -1], [1, 2, -1],
                [0, 1, 2],
            ],
            dtype=np.int32,
        )
        vertex_depths = baseline[7]
        depths = np.array(
            [
                *vertex_depths,
                (vertex_depths[0] + vertex_depths[1]) / 2.0,
                (vertex_depths[1] + vertex_depths[2]) / 2.0,
                (vertex_depths[0] + vertex_depths[1] + vertex_depths[2]) / 3.0,
            ],
            dtype=np.float32,
        )
        hotools_native.mc2_context_v0_update_self_collision_static(
            context, flags, indices, depths, 3, 2, 1,
        )
        floats, ints, curves = parameters()
        floats[35] = 0.25
        ints[9] = 2
        curves[8] = np.linspace(0.01, 0.025, 16, dtype=np.float32)
        hotools_native.mc2_context_v0_update_parameters(context, floats, ints, curves)
        positions = np.array(
            [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 3.0, 0.0]],
            dtype=np.float32,
        )
        rotations = np.zeros((3, 4), dtype=np.float32)
        rotations[:, 3] = 1.0
        update_dynamic(context, 10, 4, positions, rotations, scale_ratio=2.0)
        hotools_native.mc2_context_v0_reset(context)
        step(context, 1.0 / 90.0, simulation_power_z=0.0)

        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["self_primitive_dynamic_ready"] is True
        assert info["self_grid_dynamic_ready"] is True
        assert info["self_primitive_update_count"] == 1
        assert info["self_grid_update_count"] == 1
        assert info["self_point_grid_count"] == 1
        assert info["self_edge_grid_count"] == 1
        assert info["self_triangle_grid_count"] == 1
        assert abs(info["self_max_primitive_size"] - 3.0) < 1.0e-6
        assert abs(info["self_grid_size"] - 9.0) < 1.0e-6
        inverse_masses = np.empty((6, 3), dtype=np.float32)
        aabb_min = np.empty((6, 3), dtype=np.float32)
        aabb_max = np.empty((6, 3), dtype=np.float32)
        thickness = np.empty(6, dtype=np.float32)
        hotools_native.mc2_context_v0_read_self_collision_primitives(
            context, inverse_masses, aabb_min, aabb_max, thickness,
        )
        expected_thickness = np.interp(
            depths, np.linspace(0.0, 1.0, 16), curves[8]
        ).astype(np.float32) * np.float32(2.0)
        np.testing.assert_allclose(thickness, expected_thickness, rtol=0.0, atol=1.0e-7)
        fixed_inverse_mass = np.float32(1.0 / (100.0 + 0.25 * 50.0))
        move_inverse_mass = np.float32(1.0 / (1.0 + 0.25 * 50.0))
        expected_inverse_masses = np.zeros((6, 3), dtype=np.float32)
        for primitive, record in enumerate(indices):
            for axis, vertex in enumerate(record):
                if vertex < 0:
                    continue
                expected_inverse_masses[primitive, axis] = (
                    fixed_inverse_mass if vertex == 0 else move_inverse_mass
                )
        np.testing.assert_allclose(
            inverse_masses, expected_inverse_masses, rtol=0.0, atol=1.0e-7
        )
        for primitive, record in enumerate(indices):
            vertices = record[record >= 0]
            expected_min = positions[vertices].min(axis=0) - expected_thickness[primitive]
            expected_max = positions[vertices].max(axis=0) + expected_thickness[primitive]
            np.testing.assert_allclose(aabb_min[primitive], expected_min, rtol=0.0, atol=1.0e-6)
            np.testing.assert_allclose(aabb_max[primitive], expected_max, rtol=0.0, atol=1.0e-6)

        step(context, 1.0 / 90.0, simulation_power_z=0.0)
        assert hotools_native.mc2_context_v0_inspect(context)["self_primitive_update_count"] == 1
        update_dynamic(context, 11, 4, positions, rotations, scale_ratio=2.0)
        step(context, 1.0 / 90.0, simulation_power_z=0.0)
        assert hotools_native.mc2_context_v0_inspect(context)["self_primitive_update_count"] == 2

        ints[9] = 0
        hotools_native.mc2_context_v0_update_parameters(context, floats, ints, curves)
        update_dynamic(context, 12, 4, positions, rotations, scale_ratio=2.0)
        step(context, 1.0 / 90.0, simulation_power_z=0.0)
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["self_primitive_dynamic_ready"] is False
        assert info["self_grid_dynamic_ready"] is False
        assert info["self_primitive_update_count"] == 2
        assert info["self_grid_update_count"] == 2
        assert info["self_grid_count"] == 0
        assert info["self_max_primitive_size"] == 0.0
        assert info["self_grid_size"] == 0.0
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_self_collision_grid_sort_and_unity_hash():
    context = hotools_native.mc2_context_v0_create(0, 6)
    try:
        proxy, baseline = static_arrays(6)
        edges = np.array(
            [[0, 2], [1, 3], [2, 4], [3, 5], [4, 0], [5, 1]],
            dtype=np.int32,
        )
        triangles = np.array([[0, 2, 4], [1, 3, 5]], dtype=np.int32)
        proxy = list(proxy)
        proxy[5] = edges
        proxy[6] = triangles
        hotools_native.mc2_context_v0_update_proxy_static(context, *proxy)
        hotools_native.mc2_context_v0_update_baseline_static(context, *baseline)
        particle_indices = np.concatenate(
            (
                np.column_stack(
                    (
                        np.arange(6, dtype=np.int32),
                        np.full(6, -1, dtype=np.int32),
                        np.full(6, -1, dtype=np.int32),
                    )
                ),
                np.column_stack((edges, np.full(6, -1, dtype=np.int32))),
                triangles,
            ),
            axis=0,
        )
        flags = np.concatenate(
            (
                np.zeros(6, dtype=np.uint32),
                np.full(6, 0x01000000, dtype=np.uint32),
                np.full(2, 0x02000000, dtype=np.uint32),
            )
        )
        vertex_depths = baseline[7]
        depths = np.concatenate(
            (
                vertex_depths,
                vertex_depths[edges].mean(axis=1),
                vertex_depths[triangles].mean(axis=1),
            )
        ).astype(np.float32)
        hotools_native.mc2_context_v0_update_self_collision_static(
            context, flags, particle_indices, depths, 6, 6, 2,
        )
        floats, ints, curves = parameters()
        ints[9] = 2
        curves[8] = 0.01
        hotools_native.mc2_context_v0_update_parameters(context, floats, ints, curves)
        positions = np.array(
            [
                [10.1, 0.1, 0.0], [0.1, 0.1, 0.0],
                [11.1, 0.1, 0.0], [1.1, 0.1, 0.0],
                [10.1, 1.1, 0.0], [0.1, 1.1, 0.0],
            ],
            dtype=np.float32,
        )
        rotations = np.zeros((6, 4), dtype=np.float32)
        rotations[:, 3] = 1.0
        update_dynamic(context, 20, 5, positions, rotations)
        hotools_native.mc2_context_v0_reset(context)
        step(context, 1.0 / 90.0, simulation_power_z=0.0)

        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["self_grid_dynamic_ready"] is True
        assert info["self_grid_update_count"] == 1
        assert info["self_point_grid_count"] == 2
        assert info["self_edge_grid_count"] == 2
        assert info["self_triangle_grid_count"] == 2
        assert info["self_grid_count"] == 6
        assert abs(info["self_max_primitive_size"] - 1.0) < 1.0e-6
        assert abs(info["self_grid_size"] - 3.0) < 1.0e-6
        sorted_indices = np.empty((14, 3), dtype=np.int32)
        grids = np.empty((14, 3), dtype=np.int32)
        hashes = np.empty(14, dtype=np.int32)
        starts = np.empty(14, dtype=np.int32)
        counts = np.empty(14, dtype=np.int32)
        hotools_native.mc2_context_v0_read_self_collision_grid(
            context, sorted_indices, grids, hashes, starts, counts,
        )
        expected_indices = np.array(
            [
                [1, -1, -1], [3, -1, -1], [5, -1, -1],
                [0, -1, -1], [2, -1, -1], [4, -1, -1],
                [1, 3, -1], [3, 5, -1], [5, 1, -1],
                [0, 2, -1], [2, 4, -1], [4, 0, -1],
                [1, 3, 5], [0, 2, 4],
            ],
            dtype=np.int32,
        )
        np.testing.assert_array_equal(sorted_indices, expected_indices)
        expected_grids = np.array(
            [[0, 0, 0]] * 3 + [[3, 0, 0]] * 3
            + [[0, 0, 0]] * 3 + [[3, 0, 0]] * 3
            + [[0, 0, 0], [3, 0, 0]],
            dtype=np.int32,
        )
        np.testing.assert_array_equal(grids, expected_grids)

        def unity_int3_hash(grid):
            value = (
                (int(grid[0]) & 0xFFFFFFFF) * 0x4C7F6DD1
                + (int(grid[1]) & 0xFFFFFFFF) * 0x4822A3E9
                + (int(grid[2]) & 0xFFFFFFFF) * 0xAAC3C25D
                + 0xD21D0945
            ) & 0xFFFFFFFF
            return value if value < 0x80000000 else value - 0x100000000

        for chunk_start, near_start, far_start, run_count in (
            (0, 0, 3, 3), (6, 6, 9, 3), (12, 12, 13, 1),
        ):
            expected_runs = sorted(
                [
                    (unity_int3_hash((0, 0, 0)), near_start, run_count),
                    (unity_int3_hash((3, 0, 0)), far_start, run_count),
                ]
            )
            np.testing.assert_array_equal(
                hashes[chunk_start : chunk_start + 2],
                [record[0] for record in expected_runs],
            )
            np.testing.assert_array_equal(
                starts[chunk_start : chunk_start + 2],
                [record[1] for record in expected_runs],
            )
            np.testing.assert_array_equal(
                counts[chunk_start : chunk_start + 2],
                [record[2] for record in expected_runs],
            )

        collapsed = np.zeros_like(positions)
        update_dynamic(context, 21, 5, collapsed, rotations)
        hotools_native.mc2_context_v0_reset(context)
        step(context, 1.0 / 90.0, simulation_power_z=0.0)
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["self_primitive_dynamic_ready"] is True
        assert info["self_grid_dynamic_ready"] is False
        assert info["self_primitive_update_count"] == 2
        assert info["self_grid_update_count"] == 1
        assert info["self_grid_count"] == 0
        expect_error(
            RuntimeError,
            lambda: hotools_native.mc2_context_v0_read_self_collision_grid(
                context, sorted_indices, grids, hashes, starts, counts,
            ),
            "not ready",
        )
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_self_collision_broadphase_candidates_are_filtered_and_typed():
    edge_context = hotools_native.mc2_context_v0_create(0, 4)
    point_triangle_context = hotools_native.mc2_context_v0_create(0, 4)
    try:
        proxy, baseline = static_arrays(4)
        edges = np.array([[0, 1], [2, 3]], dtype=np.int32)
        proxy = list(proxy)
        proxy[5] = edges
        hotools_native.mc2_context_v0_update_proxy_static(edge_context, *proxy)
        hotools_native.mc2_context_v0_update_baseline_static(edge_context, *baseline)
        edge_indices = np.column_stack(
            (edges, np.full(2, -1, dtype=np.int32))
        )
        edge_depths = baseline[7][edges].mean(axis=1).astype(np.float32)
        hotools_native.mc2_context_v0_update_self_collision_static(
            edge_context,
            np.full(2, 0x01000000, dtype=np.uint32),
            edge_indices,
            edge_depths,
            0,
            2,
            0,
        )
        floats, ints, curves = parameters()
        ints[9] = 2
        curves[8] = 0.05
        hotools_native.mc2_context_v0_update_parameters(
            edge_context, floats, ints, curves
        )
        positions = np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
             [0.0, 0.04, 0.0], [1.0, 0.04, 0.0]],
            dtype=np.float32,
        )
        rotations = np.zeros((4, 4), dtype=np.float32)
        rotations[:, 3] = 1.0
        update_dynamic(edge_context, 30, 6, positions, rotations)
        hotools_native.mc2_context_v0_reset(edge_context)
        step(edge_context, 1.0 / 90.0, simulation_power_z=0.0)
        info = hotools_native.mc2_context_v0_inspect(edge_context)
        assert info["self_candidate_ready"] is True
        assert info["self_candidate_update_count"] == 1
        assert info["self_contact_candidate_count"] == 1
        assert info["self_contact_ready"] is True
        assert info["self_contact_build_count"] == 1
        assert info["self_contact_update_count"] == 0
        assert info["self_contact_solver_iteration_count"] == 4
        assert info["self_contact_sum_count"] == 4
        assert info["self_contact_cache_count"] == 1
        assert info["self_contact_enabled_count"] == 1
        candidates = np.empty((1, 3), dtype=np.int32)
        hotools_native.mc2_context_v0_read_self_collision_candidates(
            edge_context, candidates
        )
        np.testing.assert_array_equal(candidates, [[0, 1, 0]])
        contact_indices = np.empty((1, 2), dtype=np.int32)
        contact_types = np.empty(1, dtype=np.int32)
        contact_enabled = np.empty(1, dtype=np.uint8)
        contact_thickness = np.empty(1, dtype=np.float32)
        contact_s = np.empty(1, dtype=np.float32)
        contact_t = np.empty(1, dtype=np.float32)
        contact_normals = np.empty((1, 3), dtype=np.float32)
        hotools_native.mc2_context_v0_read_self_collision_contacts(
            edge_context,
            contact_indices,
            contact_types,
            contact_enabled,
            contact_thickness,
            contact_s,
            contact_t,
            contact_normals,
        )
        np.testing.assert_array_equal(contact_indices, [[0, 1]])
        np.testing.assert_array_equal(contact_types, [0])
        np.testing.assert_array_equal(contact_enabled, [1])
        np.testing.assert_allclose(
            contact_thickness, [np.float32(np.float16(0.1))], rtol=0.0, atol=0.0
        )
        np.testing.assert_array_equal(contact_s, [0.0])
        np.testing.assert_array_equal(contact_t, [0.0])
        np.testing.assert_array_equal(contact_normals, [[0.0, -1.0, 0.0]])
        solved_positions = np.empty_like(positions)
        solved_rotations = np.empty_like(rotations)
        hotools_native.mc2_context_v0_read(
            edge_context, solved_positions, solved_rotations
        )
        expected_positions = positions.copy()
        half_thickness = np.float32(np.float16(0.1))
        for _ in range(4):
            projected = np.float32(expected_positions[2, 1] - expected_positions[0, 1])
            if projected > half_thickness:
                continue
            scale = np.float32(np.float32(half_thickness - projected) / np.float32(2.0))
            fixed_a = np.int32(np.float32(-scale * np.float32(1000000.0)))
            fixed_b = np.int32(np.float32(scale * np.float32(1000000.0)))
            expected_positions[0, 1] += np.float32(fixed_a) * np.float32(0.000001)
            expected_positions[2, 1] += np.float32(fixed_b) * np.float32(0.000001)
        np.testing.assert_allclose(
            solved_positions, expected_positions, rtol=0.0, atol=1.0e-7
        )
        step(edge_context, 1.0 / 90.0, simulation_power_z=0.0)
        edge_info = hotools_native.mc2_context_v0_inspect(edge_context)
        assert edge_info["self_candidate_update_count"] == 1
        assert edge_info["self_contact_build_count"] == 1
        assert edge_info["self_contact_update_count"] == 1
        assert edge_info["self_contact_enabled_count"] == 1
        assert edge_info["self_contact_solver_iteration_count"] == 8
        assert edge_info["self_contact_sum_count"] == 8

        proxy, baseline = static_arrays(4)
        edges = np.array([[0, 1], [1, 2], [2, 0]], dtype=np.int32)
        triangles = np.array([[0, 1, 2]], dtype=np.int32)
        proxy = list(proxy)
        proxy[5] = edges
        proxy[6] = triangles
        hotools_native.mc2_context_v0_update_proxy_static(
            point_triangle_context, *proxy
        )
        hotools_native.mc2_context_v0_update_baseline_static(
            point_triangle_context, *baseline
        )
        particle_indices = np.concatenate(
            (
                np.column_stack(
                    (
                        np.arange(4, dtype=np.int32),
                        np.full(4, -1, dtype=np.int32),
                        np.full(4, -1, dtype=np.int32),
                    )
                ),
                np.column_stack((edges, np.full(3, -1, dtype=np.int32))),
                triangles,
            ),
            axis=0,
        )
        flags = np.concatenate(
            (
                np.zeros(4, dtype=np.uint32),
                np.full(3, 0x01000000, dtype=np.uint32),
                np.full(1, 0x02000000, dtype=np.uint32),
            )
        )
        depths = np.concatenate(
            (
                baseline[7],
                baseline[7][edges].mean(axis=1),
                baseline[7][triangles].mean(axis=1),
            )
        ).astype(np.float32)
        hotools_native.mc2_context_v0_update_self_collision_static(
            point_triangle_context, flags, particle_indices, depths, 4, 3, 1,
        )
        hotools_native.mc2_context_v0_update_parameters(
            point_triangle_context, floats, ints, curves
        )
        positions = np.array(
            [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0],
             [0.0, 2.0, 0.0], [0.5, 0.5, 0.01]],
            dtype=np.float32,
        )
        update_dynamic(point_triangle_context, 31, 6, positions, rotations)
        hotools_native.mc2_context_v0_reset(point_triangle_context)
        step(point_triangle_context, 1.0 / 90.0, simulation_power_z=0.0)
        info = hotools_native.mc2_context_v0_inspect(point_triangle_context)
        assert info["self_candidate_ready"] is True
        assert info["self_contact_candidate_count"] == 1
        assert info["self_contact_ready"] is True
        assert info["self_contact_cache_count"] == 1
        assert info["self_contact_enabled_count"] == 1
        assert info["self_contact_solver_iteration_count"] == 4
        assert info["self_contact_sum_count"] == 4
        candidates = np.empty((1, 3), dtype=np.int32)
        hotools_native.mc2_context_v0_read_self_collision_candidates(
            point_triangle_context, candidates
        )
        np.testing.assert_array_equal(candidates, [[3, 7, 1]])
        hotools_native.mc2_context_v0_read_self_collision_contacts(
            point_triangle_context,
            contact_indices,
            contact_types,
            contact_enabled,
            contact_thickness,
            contact_s,
            contact_t,
            contact_normals,
        )
        np.testing.assert_array_equal(contact_indices, [[3, 7]])
        np.testing.assert_array_equal(contact_types, [1])
        np.testing.assert_array_equal(contact_enabled, [1])
        np.testing.assert_allclose(
            contact_thickness, [np.float32(np.float16(0.1))], rtol=0.0, atol=0.0
        )
        np.testing.assert_array_equal(contact_s, [1.0])
        np.testing.assert_array_equal(contact_t, [0.0])
        np.testing.assert_array_equal(contact_normals, [[0.0, 0.0, 0.0]])
        solved_positions = np.empty_like(positions)
        hotools_native.mc2_context_v0_read(
            point_triangle_context, solved_positions, solved_rotations
        )
        assert solved_positions[3, 2] > positions[3, 2]
        assert np.all(solved_positions[:3, 2] < positions[:3, 2])
        assert abs(float(solved_positions[:, 2].sum() - positions[:, 2].sum())) < 5.0e-6
    finally:
        hotools_native.mc2_context_v0_free(edge_context)
        hotools_native.mc2_context_v0_free(point_triangle_context)


def test_self_collision_intersect_records_commit_only_on_final_substep():
    context = hotools_native.mc2_context_v0_create(0, 5)
    try:
        proxy, baseline = static_arrays(5)
        proxy = list(proxy)
        edges = np.array(
            [[0, 1], [1, 2], [2, 0], [3, 4]],
            dtype=np.int32,
        )
        triangles = np.array([[0, 1, 2]], dtype=np.int32)
        proxy[5] = edges
        proxy[6] = triangles
        hotools_native.mc2_context_v0_update_proxy_static(context, *proxy)
        hotools_native.mc2_context_v0_update_baseline_static(context, *baseline)
        particle_indices = np.concatenate(
            (
                np.column_stack(
                    (
                        np.arange(5, dtype=np.int32),
                        np.full(5, -1, dtype=np.int32),
                        np.full(5, -1, dtype=np.int32),
                    )
                ),
                np.column_stack((edges, np.full(4, -1, dtype=np.int32))),
                triangles,
            ),
            axis=0,
        )
        primitive_flags = np.concatenate(
            (
                np.zeros(5, dtype=np.uint32),
                np.full(4, 0x01000000, dtype=np.uint32),
                np.full(1, 0x02000000, dtype=np.uint32),
            )
        )
        depths = np.concatenate(
            (
                baseline[7],
                baseline[7][edges].mean(axis=1),
                baseline[7][triangles].mean(axis=1),
            )
        ).astype(np.float32)
        hotools_native.mc2_context_v0_update_self_collision_static(
            context, primitive_flags, particle_indices, depths, 5, 4, 1,
        )
        floats, ints, curves = parameters()
        ints[9] = 2
        curves[8] = 0.001
        hotools_native.mc2_context_v0_update_parameters(
            context, floats, ints, curves
        )
        positions = np.array(
            [
                [0.0, 0.0, 0.0],
                [2.0, 0.0, 0.0],
                [0.0, 2.0, 0.0],
                [0.5, 0.5, 1.0],
                [0.5, 0.5, -1.0],
            ],
            dtype=np.float32,
        )
        rotations = np.zeros((5, 4), dtype=np.float32)
        rotations[:, 3] = 1.0

        update_dynamic(context, 1, 0, positions, rotations)
        hotools_native.mc2_context_v0_reset(context)
        step(context, 1.0 / 90.0, simulation_power_z=0.0)
        first_info = hotools_native.mc2_context_v0_inspect(context)
        assert first_info["self_intersect_detection_count"] == 1
        assert first_info["self_intersect_solve_count"] == 1
        assert first_info["self_intersect_record_count"] == 0
        assert first_info["self_intersect_particle_count"] == 0

        update_dynamic(context, 2, 0, positions, rotations)
        hotools_native.mc2_context_v0_step(
            context, 1.0 / 90.0, 1.0, 0.0, 1.0, False
        )
        middle_info = hotools_native.mc2_context_v0_inspect(context)
        assert middle_info["self_intersect_detection_count"] == 2
        assert middle_info["self_intersect_solve_count"] == 1
        assert middle_info["self_intersect_record_count"] == 1
        records = np.empty((1, 5), dtype=np.int32)
        particle_flags = np.empty(5, dtype=np.uint8)
        current_primitive_flags = np.empty(10, dtype=np.uint32)
        hotools_native.mc2_context_v0_read_self_collision_intersections(
            context, records, particle_flags, current_primitive_flags
        )
        np.testing.assert_array_equal(records, [[3, 4, 0, 1, 2]])
        np.testing.assert_array_equal(particle_flags, np.zeros(5, dtype=np.uint8))

        hotools_native.mc2_context_v0_step(
            context, 1.0 / 90.0, 1.0, 0.0, 1.0, True
        )
        final_info = hotools_native.mc2_context_v0_inspect(context)
        assert final_info["self_intersect_detection_count"] == 2
        assert final_info["self_intersect_solve_count"] == 2
        assert final_info["self_intersect_particle_count"] == 2
        hotools_native.mc2_context_v0_read_self_collision_intersections(
            context, records, particle_flags, current_primitive_flags
        )
        np.testing.assert_array_equal(particle_flags, [0, 0, 0, 1, 1])

        update_dynamic(context, 3, 0, positions, rotations)
        step(context, 1.0 / 90.0, simulation_power_z=0.0)
        third_info = hotools_native.mc2_context_v0_inspect(context)
        assert third_info["self_intersect_detection_count"] == 3
        assert third_info["self_intersect_solve_count"] == 3
        assert third_info["self_intersect_record_count"] == 0
        assert third_info["self_intersect_particle_count"] == 0
        records = np.empty((0, 5), dtype=np.int32)
        hotools_native.mc2_context_v0_read_self_collision_intersections(
            context, records, particle_flags, current_primitive_flags
        )
        sorted_indices = np.empty((10, 3), dtype=np.int32)
        grids = np.empty((10, 3), dtype=np.int32)
        hashes = np.empty(10, dtype=np.int32)
        starts = np.empty(10, dtype=np.int32)
        counts = np.empty(10, dtype=np.int32)
        hotools_native.mc2_context_v0_read_self_collision_grid(
            context, sorted_indices, grids, hashes, starts, counts
        )
        crossing_row = np.flatnonzero(
            np.all(sorted_indices == np.array([3, 4, -1], dtype=np.int32), axis=1)
        )
        np.testing.assert_array_equal(crossing_row, [8])
        assert current_primitive_flags[crossing_row[0]] & 0x7 == 0x3
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_point_collision_projection_and_post():
    context = hotools_native.mc2_context_v0_create(0, 1)
    try:
        proxy, baseline = static_arrays(1)
        hotools_native.mc2_context_v0_update_proxy_static(context, *proxy)
        hotools_native.mc2_context_v0_update_baseline_static(context, *baseline)
        hotools_native.mc2_context_v0_update_distance_static(
            context, np.zeros((1, 2), dtype=np.int32),
            np.empty(0, dtype=np.int32), np.empty(0, dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_bending_static(
            context, np.empty((0, 4), dtype=np.int32),
            np.empty(0, dtype=np.float32), np.empty(0, dtype=np.int8),
        )
        floats, ints, curves = parameters()
        ints[8] = 1
        curves[1, :] = 0.25
        hotools_native.mc2_context_v0_update_parameters(context, floats, ints, curves)
        zero = np.zeros((1, 3), dtype=np.float32)
        hotools_native.mc2_context_v0_update_colliders(
            context, 1,
            np.array([0], dtype=np.int32), np.array([1], dtype=np.int32),
            zero, zero, zero, zero.copy(), zero.copy(), zero.copy(),
            np.array([0.5], dtype=np.float32),
        )
        rotations = np.array([[0, 0, 0, 1]], dtype=np.float32)
        update_dynamic(context, 1, 0, zero, rotations)
        hotools_native.mc2_context_v0_reset(context)
        step(context, 1.0 / 90.0)
        output = np.empty_like(zero)
        output_rotations = np.empty_like(rotations)
        hotools_native.mc2_context_v0_read(context, output, output_rotations)
        np.testing.assert_allclose(output[0], (0, 0, 0.75), atol=1.0e-6)
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["point_collision_solve_count"] == 1
        assert info["distance_solve_count"] == 0
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_bone_spring_soft_sphere_limit_and_velocity_reference():
    context = hotools_native.mc2_context_v0_create(0, 1)
    try:
        hotools_native.mc2_context_v0_set_setup_kind(context, 2)
        proxy, baseline = static_arrays(1)
        proxy = list(proxy)
        proxy[4] = np.array([1], dtype=np.uint8)
        hotools_native.mc2_context_v0_update_proxy_static(context, *proxy)
        hotools_native.mc2_context_v0_update_baseline_static(context, *baseline)
        hotools_native.mc2_context_v0_update_distance_static(
            context, np.zeros((1, 2), dtype=np.int32),
            np.empty(0, dtype=np.int32), np.empty(0, dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_bending_static(
            context, np.empty((0, 4), dtype=np.int32),
            np.empty(0, dtype=np.float32), np.empty(0, dtype=np.int8),
        )
        floats, ints, curves = parameters()
        ints[8] = 1
        curves[1, :] = 0.5
        curves[7, :] = 0.2
        hotools_native.mc2_context_v0_update_parameters(context, floats, ints, curves)
        positions = np.array([[0.1, 0.0, 0.0]], dtype=np.float32)
        rotations = np.array([[0.0, 0.0, 0.0, 1.0]], dtype=np.float32)
        centers = np.zeros((1, 3), dtype=np.float32)
        hotools_native.mc2_context_v0_update_colliders(
            context, 1,
            np.array([0], dtype=np.int32), np.array([1], dtype=np.int32),
            centers, centers.copy(), centers.copy(),
            centers.copy(), centers.copy(), centers.copy(),
            np.array([1.0], dtype=np.float32),
        )
        update_dynamic(context, 1, 0, positions, rotations)
        hotools_native.mc2_context_v0_reset(context)
        step(context, 1.0 / 90.0)
        output = np.empty_like(positions)
        output_rotations = np.empty_like(rotations)
        hotools_native.mc2_context_v0_read(context, output, output_rotations)
        np.testing.assert_allclose(output[0], (0.232, 0.0, 0.0), atol=1.0e-6)
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["setup_kind"] == 2
        assert info["fixed_count"] == 1
        assert info["point_collision_solve_count"] == 1
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_edge_collision_projection_and_post():
    context = hotools_native.mc2_context_v0_create(0, 3)
    try:
        proxy, baseline = static_arrays(3)
        hotools_native.mc2_context_v0_update_proxy_static(context, *proxy)
        hotools_native.mc2_context_v0_update_baseline_static(context, *baseline)
        hotools_native.mc2_context_v0_update_distance_static(
            context, np.zeros((3, 2), dtype=np.int32),
            np.empty(0, dtype=np.int32), np.empty(0, dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_bending_static(
            context, np.empty((0, 4), dtype=np.int32),
            np.empty(0, dtype=np.float32), np.empty(0, dtype=np.int8),
        )
        floats, ints, curves = parameters()
        ints[8] = 2
        curves[1, :] = 0.18
        hotools_native.mc2_context_v0_update_parameters(context, floats, ints, curves)
        positions = np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, -0.05, 0.0]],
            dtype=np.float32,
        )
        rotations = np.zeros((3, 4), dtype=np.float32)
        rotations[:, 3] = 1.0
        centers = np.array([[0.5, -0.1, 0.0]], dtype=np.float32)
        segments = centers.copy()
        hotools_native.mc2_context_v0_update_colliders(
            context, 1,
            np.array([0], dtype=np.int32), np.array([1], dtype=np.int32),
            centers, segments, segments, centers.copy(), segments.copy(), segments.copy(),
            np.array([0.15], dtype=np.float32),
        )
        update_dynamic(context, 1, 0, positions, rotations)
        hotools_native.mc2_context_v0_reset(context)
        step(context, 1.0 / 90.0)
        output = np.empty_like(positions)
        output_rotations = np.empty_like(rotations)
        hotools_native.mc2_context_v0_read(context, output, output_rotations)
        assert np.max(np.linalg.norm(output - positions, axis=1)) > 0.0
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["edge_collision_solve_count"] == 1
        assert info["point_collision_solve_count"] == 0
        assert info["distance_solve_count"] == 0
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_lifecycle_and_transactional_validation():
    baseline = hotools_native.mc2_context_v0_stats().copy()
    first = hotools_native.mc2_context_v0_create(0, 2)
    second = hotools_native.mc2_context_v0_create(0, 3)
    third = hotools_native.mc2_context_v0_create(0, 4)
    fourth = hotools_native.mc2_context_v0_create(0, 2)
    fifth = hotools_native.mc2_context_v0_create(0, 4)
    assert hotools_native.mc2_context_v0_stats()["live"] == baseline["live"] + 5
    try:
        second_positions, second_rotations = frame(3)
        expect_error(
            RuntimeError,
            lambda: update_dynamic(second, 0, 0, second_positions, second_rotations),
            "parameters have not been uploaded",
        )
        info = hotools_native.mc2_context_v0_inspect(first)
        assert info["schema"] == "mc2_context_v0"
        assert info["vertex_count"] == 2
        assert not info["initialized"]

        proxy, baseline_static = static_arrays(2)
        hotools_native.mc2_context_v0_update_proxy_static(first, *proxy)
        hotools_native.mc2_context_v0_update_baseline_static(first, *baseline_static)
        info = hotools_native.mc2_context_v0_inspect(first)
        assert info["proxy_static_ready"] is True
        assert info["baseline_static_ready"] is True
        assert info["proxy_static_revision"] == 1
        assert info["baseline_static_revision"] == 1
        assert info["edge_count"] == 1
        assert info["triangle_count"] == 0
        assert info["baseline_count"] == 1
        assert info["fixed_count"] == 0

        hotools_native.mc2_context_v0_update_center_static(
            first,
            np.empty((0,), dtype=np.int32),
            np.zeros(3, dtype=np.float32),
            np.array([0.0, -1.0, 0.0], dtype=np.float32),
        )
        info = hotools_native.mc2_context_v0_inspect(first)
        assert info["center_static_ready"] is True
        assert info["center_static_revision"] == 1
        assert info["center_fixed_count"] == 0

        bad_proxy = list(proxy)
        bad_proxy[5] = np.array([[0, 2]], dtype=np.int32)
        expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_proxy_static(first, *bad_proxy),
            "out-of-range",
        )
        assert hotools_native.mc2_context_v0_inspect(first)["proxy_static_revision"] == 1

        bad_baseline = list(baseline_static)
        bad_baseline[1] = np.array([[0, 0], [0, 0]], dtype=np.int32)
        expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_baseline_static(first, *bad_baseline),
            "does not cover",
        )
        assert hotools_native.mc2_context_v0_inspect(first)["baseline_static_revision"] == 1

        distance_ranges = np.array([[0, 1], [1, 1]], dtype=np.int32)
        distance_targets = np.array([1, 0], dtype=np.int32)
        distance_rests = np.array([1.0, 1.0], dtype=np.float32)
        hotools_native.mc2_context_v0_update_distance_static(
            first, distance_ranges, distance_targets, distance_rests
        )
        empty_quads = np.empty((0, 4), dtype=np.int32)
        empty_rests = np.empty((0,), dtype=np.float32)
        empty_markers = np.empty((0,), dtype=np.int8)
        hotools_native.mc2_context_v0_update_bending_static(
            first, empty_quads, empty_rests, empty_markers
        )
        info = hotools_native.mc2_context_v0_inspect(first)
        assert info["distance_static_ready"] is True
        assert info["bending_static_ready"] is True
        assert info["distance_record_count"] == 2
        assert info["bending_record_count"] == 0

        bad_distance_rests = np.array([-0.0, -1.0], dtype=np.float32)
        expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_distance_static(
                first, distance_ranges, distance_targets, bad_distance_rests
            ),
            "+0.0",
        )
        assert hotools_native.mc2_context_v0_inspect(first)["distance_static_revision"] == 1

        quads = np.array([[0, 1, 2, 3]], dtype=np.int32)
        bend_rests = np.array([0.5], dtype=np.float32)
        markers = np.array([1], dtype=np.int8)
        third_proxy, _third_baseline = static_arrays(4)
        hotools_native.mc2_context_v0_update_proxy_static(third, *third_proxy)
        hotools_native.mc2_context_v0_update_bending_static(third, quads, bend_rests, markers)
        assert hotools_native.mc2_context_v0_inspect(third)["bending_record_count"] == 1
        bad_markers = np.array([7], dtype=np.int8)
        expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_bending_static(
                third, quads, bend_rests, bad_markers
            ),
            "marker",
        )
        assert hotools_native.mc2_context_v0_inspect(third)["bending_static_revision"] == 1

        bending_proxy, bending_baseline = static_arrays(4)
        bending_proxy = list(bending_proxy)
        bending_proxy[4] = np.array([1, 2, 2, 2], dtype=np.uint8)
        bending_baseline = list(bending_baseline)
        bending_baseline[7] = np.full(4, 0.5, dtype=np.float32)
        hotools_native.mc2_context_v0_update_proxy_static(third, *bending_proxy)
        hotools_native.mc2_context_v0_update_baseline_static(third, *bending_baseline)
        hotools_native.mc2_context_v0_update_distance_static(
            third,
            np.zeros((4, 2), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_bending_static(
            third,
            np.array([[1, 0, 2, 3]], dtype=np.int32),
            np.array([0.0], dtype=np.float32),
            np.array([1], dtype=np.int8),
        )
        bending_floats, bending_ints, bending_curves = parameters()
        bending_floats[27] = 1.0
        bending_ints[3] = 2
        hotools_native.mc2_context_v0_update_parameters(
            third, bending_floats, bending_ints, bending_curves
        )
        bending_positions = np.array(
            [[0, 1, 0], [0, -0.8660254, -0.5], [0, 0, 0], [1, 0, 0]],
            dtype=np.float32,
        )
        bending_rotations = np.zeros((4, 4), dtype=np.float32)
        bending_rotations[:, 3] = 1.0
        update_dynamic(third, 1, 0, bending_positions, bending_rotations)
        hotools_native.mc2_context_v0_reset(third)
        step(third, 1.0 / 90.0, simulation_power_y=1.0, simulation_power_z=1.0)
        bending_out = np.empty_like(bending_positions)
        bending_out_rotations = np.empty_like(bending_rotations)
        hotools_native.mc2_context_v0_read(third, bending_out, bending_out_rotations)
        np.testing.assert_allclose(
            bending_out,
            np.array(
                [[0, 1, 0], [0, -0.9210874, -0.404629], [0, 0.055062, -0.205497], [1, 0, 0]],
                dtype=np.float32,
            ),
            rtol=1.0e-6,
            atol=2.0e-5,
        )
        assert hotools_native.mc2_context_v0_inspect(third)["bending_solve_count"] == 1

        floats, ints, curves = parameters()
        curves[2, :] = 1.0
        hotools_native.mc2_context_v0_update_parameters(first, floats, ints, curves)
        assert hotools_native.mc2_context_v0_inspect(first)["parameter_revision"] == 1

        bad_ints = ints.copy()
        bad_ints[4] = 7
        expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_parameters(first, floats, bad_ints, curves),
            "boolean parameter",
        )
        assert hotools_native.mc2_context_v0_inspect(first)["parameter_revision"] == 1

        bad = floats.copy()
        bad[4] = np.nan
        expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_parameters(first, bad, ints, curves),
            "NaN/Inf",
        )
        assert hotools_native.mc2_context_v0_inspect(first)["parameter_revision"] == 1

        positions, rotations = frame(2, 1.5)
        positions[1, 0] = 3.5
        expect_error(
            ValueError,
            lambda: update_dynamic(
                first, 12, 7, positions, rotations, velocity_weight=2.0
            ),
            "out of range",
        )
        assert hotools_native.mc2_context_v0_inspect(first)["dynamic_revision"] == 0
        update_dynamic(first, 12, 7, positions, rotations)
        bad_rotations = rotations.copy()
        bad_rotations[0] = 0.0
        expect_error(
            ValueError,
            lambda: update_dynamic(first, 13, 7, positions, bad_rotations),
            "unit quaternions",
        )
        info = hotools_native.mc2_context_v0_inspect(first)
        assert info["dynamic_revision"] == 1 and info["frame"] == 12

        expect_error(
            RuntimeError,
            lambda: step(first, 1.0 / 60.0),
            "not ready",
        )
        hotools_native.mc2_context_v0_reset(first)
        step(first, 1.0 / 60.0)
        out_positions = np.empty_like(positions)
        out_rotations = np.empty_like(rotations)
        hotools_native.mc2_context_v0_read(first, out_positions, out_rotations)
        np.testing.assert_allclose(
            out_positions,
            np.array(
                [[1.6603498, 0.0, 0.0], [2.6753435, 0.0, 0.0]],
                dtype=np.float32,
            ),
            rtol=0.0,
            atol=1.0e-6,
        )
        np.testing.assert_array_equal(out_rotations, rotations)
        info = hotools_native.mc2_context_v0_inspect(first)
        assert info["reset_count"] == 1 and info["step_count"] == 1
        assert info["distance_solve_count"] == 2

        tier_a_proxy, tier_a_baseline = static_arrays(3)
        hotools_native.mc2_context_v0_update_proxy_static(second, *tier_a_proxy)
        hotools_native.mc2_context_v0_update_baseline_static(second, *tier_a_baseline)
        tier_a_ranges = np.array([[0, 2], [2, 0], [2, 0]], dtype=np.int32)
        tier_a_targets = np.array([1, 2], dtype=np.int32)
        tier_a_rests = np.array([1.0, 0.0], dtype=np.float32)
        hotools_native.mc2_context_v0_update_distance_static(
            second, tier_a_ranges, tier_a_targets, tier_a_rests
        )
        hotools_native.mc2_context_v0_update_bending_static(
            second, empty_quads, empty_rests, empty_markers
        )
        pin_floats, pin_ints, pin_curves = parameters()
        pin_curves[2, :] = 1.0
        hotools_native.mc2_context_v0_update_parameters(
            second, pin_floats, pin_ints, pin_curves
        )
        tier_a_positions, pin_rotations = frame(3)
        tier_a_positions[:, 0] = np.array([0.0, 2.0, 4.0], dtype=np.float32)
        update_dynamic(
            second, 1, 0, tier_a_positions, pin_rotations
        )
        hotools_native.mc2_context_v0_reset(second)
        step(second, 1.0 / 60.0)
        tier_a_out = np.empty_like(tier_a_positions)
        tier_a_out_rotations = np.empty_like(pin_rotations)
        hotools_native.mc2_context_v0_read(
            second, tier_a_out, tier_a_out_rotations
        )
        np.testing.assert_allclose(
            tier_a_out,
            np.array([[1.75, 0.0, 0.0], [2.0, 0.0, 0.0], [4.0, 0.0, 0.0]], dtype=np.float32),
            rtol=0.0,
            atol=1.0e-6,
        )

        pin_proxy = list(tier_a_proxy)
        pin_proxy[4] = np.array([1, 2, 2], dtype=np.uint8)
        hotools_native.mc2_context_v0_update_proxy_static(second, *pin_proxy)
        hotools_native.mc2_context_v0_update_center_static(
            second,
            np.array([0], dtype=np.int32),
            np.zeros(3, dtype=np.float32),
            np.array([0.0, -1.0, 0.0], dtype=np.float32),
        )
        expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_center_static(
                second,
                np.array([0, 0], dtype=np.int32),
                np.zeros(3, dtype=np.float32),
                np.array([0.0, -1.0, 0.0], dtype=np.float32),
            ),
            "unique",
        )
        expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_center_static(
                second,
                np.array([1], dtype=np.int32),
                np.array([1.0, 0.0, 0.0], dtype=np.float32),
                np.array([0.0, -1.0, 0.0], dtype=np.float32),
            ),
            "Move vertices",
        )
        expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_center_static(
                second,
                np.array([0], dtype=np.int32),
                np.array([1.0, 0.0, 0.0], dtype=np.float32),
                np.array([0.0, -1.0, 0.0], dtype=np.float32),
            ),
            "fixed vertex average",
        )
        expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_center_static(
                second,
                np.array([0], dtype=np.int32),
                np.zeros(3, dtype=np.float32),
                np.array([0.0, -2.0, 0.0], dtype=np.float32),
            ),
            "unit length",
        )
        assert hotools_native.mc2_context_v0_inspect(second)["center_static_revision"] == 1
        hotools_native.mc2_context_v0_update_baseline_static(second, *tier_a_baseline)
        empty_distance_ranges = np.zeros((3, 2), dtype=np.int32)
        empty_distance_targets = np.empty((0,), dtype=np.int32)
        empty_distance_rests = np.empty((0,), dtype=np.float32)
        hotools_native.mc2_context_v0_update_distance_static(
            second,
            empty_distance_ranges,
            empty_distance_targets,
            empty_distance_rests,
        )
        hotools_native.mc2_context_v0_update_bending_static(
            second, empty_quads, empty_rests, empty_markers
        )
        pin_positions, pin_rotations = frame(3)
        update_dynamic(
            second, 1, 0, pin_positions, pin_rotations
        )
        hotools_native.mc2_context_v0_reset(second)
        moved_pin_positions = pin_positions.copy()
        moved_pin_positions[0, 0] = 5.0
        update_dynamic(
            second, 2, 0, moved_pin_positions, pin_rotations
        )
        step(second, 1.0 / 60.0)
        pin_out_positions = np.empty_like(pin_positions)
        pin_out_rotations = np.empty_like(pin_rotations)
        hotools_native.mc2_context_v0_read(
            second, pin_out_positions, pin_out_rotations
        )
        np.testing.assert_array_equal(
            pin_out_positions,
            np.array([[5.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=np.float32),
        )
        assert hotools_native.mc2_context_v0_inspect(second)["distance_solve_count"] == 2

        interpolated_positions = pin_positions.copy()
        interpolated_positions[0, 0] = 9.0
        interpolated_rotations = pin_rotations.copy()
        interpolated_rotations[0] = np.array(
            [0.0, 0.0, 1.0, 0.0], dtype=np.float32
        )
        update_dynamic(
            second,
            3,
            0,
            interpolated_positions,
            interpolated_rotations,
            frame_interpolation=0.25,
        )
        step(second, 1.0 / 60.0)
        hotools_native.mc2_context_v0_read(
            second, pin_out_positions, pin_out_rotations
        )
        np.testing.assert_allclose(
            pin_out_positions[0],
            np.array([6.0, 0.0, 0.0], dtype=np.float32),
            rtol=0.0,
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            pin_out_rotations[0],
            np.array([0.0, 0.0, 0.38268343, 0.9238795], dtype=np.float32),
            rtol=0.0,
            atol=1.0e-6,
        )

        before_bad_interpolation = hotools_native.mc2_context_v0_inspect(second)
        expect_error(
            ValueError,
            lambda: update_dynamic(
                second,
                4,
                0,
                interpolated_positions,
                interpolated_rotations,
                frame_interpolation=1.5,
            ),
            "out of range",
        )
        after_bad_interpolation = hotools_native.mc2_context_v0_inspect(second)
        assert after_bad_interpolation["dynamic_revision"] == before_bad_interpolation["dynamic_revision"]
        assert after_bad_interpolation["frame"] == before_bad_interpolation["frame"]

        integration_proxy, integration_baseline = static_arrays(2)
        integration_proxy = list(integration_proxy)
        integration_proxy[4] = np.array([2, 1], dtype=np.uint8)
        hotools_native.mc2_context_v0_update_proxy_static(fourth, *integration_proxy)
        hotools_native.mc2_context_v0_update_baseline_static(fourth, *integration_baseline)
        hotools_native.mc2_context_v0_update_distance_static(
            fourth,
            np.zeros((2, 2), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_bending_static(
            fourth, empty_quads, empty_rests, empty_markers
        )
        integration_floats, integration_ints, integration_curves = parameters()
        integration_floats[0] = 9.0
        integration_floats[2] = -1.0
        integration_curves[0, :] = 0.2
        hotools_native.mc2_context_v0_update_parameters(
            fourth, integration_floats, integration_ints, integration_curves
        )
        integration_positions = np.array(
            [[1.0, 2.0, 3.0], [10.0, 0.0, 0.0]], dtype=np.float32
        )
        integration_rotations = np.zeros((2, 4), dtype=np.float32)
        integration_rotations[:, 3] = 1.0
        update_dynamic(
            fourth,
            1,
            0,
            integration_positions,
            integration_rotations,
            velocity_weight=0.8,
            gravity_ratio=0.75,
            scale_ratio=1.5,
        )
        hotools_native.mc2_context_v0_reset(fourth)
        step(fourth, 0.1, simulation_power_z=0.5)
        step(fourth, 0.1, simulation_power_z=0.5)
        integration_out = np.empty_like(integration_positions)
        integration_out_rotations = np.empty_like(integration_rotations)
        hotools_native.mc2_context_v0_read(
            fourth, integration_out, integration_out_rotations
        )
        np.testing.assert_allclose(
            integration_out,
            np.array([[1.0, 1.73918, 3.0], [10.0, 0.0, 0.0]], dtype=np.float32),
            rtol=0.0,
            atol=1.0e-5,
        )
        assert hotools_native.mc2_context_v0_inspect(fourth)["particle_prediction_count"] == 2

        volume_proxy, volume_baseline = static_arrays(4)
        volume_baseline = list(volume_baseline)
        volume_baseline[7] = np.full(4, 0.5, dtype=np.float32)
        hotools_native.mc2_context_v0_update_proxy_static(fifth, *volume_proxy)
        hotools_native.mc2_context_v0_update_baseline_static(fifth, *volume_baseline)
        hotools_native.mc2_context_v0_update_distance_static(
            fifth,
            np.zeros((4, 2), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_bending_static(
            fifth,
            np.array([[1, 0, 2, 3], [1, 0, 2, 3]], dtype=np.int32),
            np.array([1.74532926, 164.134628], dtype=np.float32),
            np.array([-1, 100], dtype=np.int8),
        )
        volume_floats, volume_ints, volume_curves = parameters()
        volume_floats[27] = 1.0
        volume_ints[3] = 2
        hotools_native.mc2_context_v0_update_parameters(
            fifth, volume_floats, volume_ints, volume_curves
        )
        volume_positions = np.array(
            [[0, 1, 0], [0, -0.342020154, -0.9396926], [0, 0, 0], [1, 0, 0]],
            dtype=np.float32,
        )
        volume_rotations = np.zeros((4, 4), dtype=np.float32)
        volume_rotations[:, 3] = 1.0
        expected_by_sign = {
            1.0: np.array(
                [[0, 1.00353646, -0.0571785], [0, -0.289499164, -0.9625721],
                 [-0.0035365, -0.0560575, 0.0800585], [1.00353646, 0, 0]],
                dtype=np.float32,
            ),
            -1.0: np.array(
                [[0, 0.9736465, 0.3263115], [0, -0.6396396, -0.8033236],
                 [0.0263535, 0.323973, -0.462681], [0.9736465, 0, 0]],
                dtype=np.float32,
            ),
        }
        for frame_index, sign in enumerate((1.0, -1.0), start=1):
            update_dynamic(
                fifth,
                frame_index,
                frame_index,
                volume_positions,
                volume_rotations,
                scale_ratio=1.25,
                negative_scale_sign=sign,
            )
            hotools_native.mc2_context_v0_reset(fifth)
            step(fifth, 1.0 / 90.0, simulation_power_y=1.0, simulation_power_z=1.0)
            volume_out = np.empty_like(volume_positions)
            volume_out_rotations = np.empty_like(volume_rotations)
            hotools_native.mc2_context_v0_read(fifth, volume_out, volume_out_rotations)
            np.testing.assert_allclose(
                volume_out, expected_by_sign[sign], rtol=1.0e-6, atol=2.0e-5
            )
    finally:
        hotools_native.mc2_context_v0_free(first)
        hotools_native.mc2_context_v0_free(first)
        hotools_native.mc2_context_v0_free(second)
        hotools_native.mc2_context_v0_free(third)
        hotools_native.mc2_context_v0_free(fourth)
        hotools_native.mc2_context_v0_free(fifth)
    assert hotools_native.mc2_context_v0_stats()["live"] == baseline["live"]
    assert hotools_native.mc2_context_v0_inspect(first)["released"] is True
    expect_error(RuntimeError, lambda: hotools_native.mc2_context_v0_reset(first), "released")


def test_create_free_soak_has_no_live_growth():
    baseline = hotools_native.mc2_context_v0_stats()["live"]
    for _ in range(1000):
        context = hotools_native.mc2_context_v0_create(0, 1)
        hotools_native.mc2_context_v0_free(context)
    assert hotools_native.mc2_context_v0_stats()["live"] == baseline


def test_center_step_matches_tier_a_fixture():
    fixture_path = (
        ROOT
        / "OmniNode" / "NodeTree" / "Function" / "physicsWorld" / "mc2"
        / "test" / "fixtures" / "tier_a" / "center_step_inertia_001.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    values = fixture["input"]
    expected = fixture["expected"]
    context = hotools_native.mc2_context_v0_create(0, 1)
    try:
        proxy, baseline = static_arrays(1)
        proxy = list(proxy)
        proxy[4] = np.array([1], dtype=np.uint8)
        hotools_native.mc2_context_v0_update_proxy_static(context, *proxy)
        hotools_native.mc2_context_v0_update_baseline_static(context, *baseline)
        hotools_native.mc2_context_v0_update_center_static(
            context,
            np.array([0], dtype=np.int32),
            np.zeros(3, dtype=np.float32),
            np.asarray(values["initial_local_gravity_direction"], dtype=np.float32),
        )
        floats, ints, curves = parameters()
        floats[0] = values["gravity"]
        floats[1:4] = values["world_gravity_direction"]
        floats[4] = values["gravity_falloff"]
        floats[5] = values["stabilization_time_after_reset"]
        floats[6] = values["parameter_blend_weight"]
        floats[16] = values["local_inertia"]
        floats[17] = values["local_movement_speed_limit"]
        floats[18] = values["local_rotation_speed_limit"]
        hotools_native.mc2_context_v0_update_parameters(context, floats, ints, curves)

        frame_positions, frame_rotations = frame(1)
        update_dynamic(
            context,
            1,
            0,
            frame_positions,
            frame_rotations,
            velocity_weight=values["velocity_weight_before_step"],
            frame_interpolation=expected["frame_interpolation"],
        )
        hotools_native.mc2_context_v0_reset(context)
        half_angle = np.float32(
            np.radians(values["frame_world_rotation_axis_angle"]["degrees"]) * 0.5
        )
        frame_rotation = np.asarray(
            [0.0, np.sin(half_angle), 0.0, np.cos(half_angle)], dtype=np.float32
        )
        center_args = (
            np.asarray(values["old_frame_world_position"], dtype=np.float32),
            np.asarray(values["frame_world_position"], dtype=np.float32),
            np.asarray(values["old_frame_world_rotation_xyzw"], dtype=np.float32),
            frame_rotation,
            np.asarray(values["old_frame_world_scale"], dtype=np.float32),
            np.asarray(values["frame_world_scale"], dtype=np.float32),
            np.asarray(values["old_frame_world_position"], dtype=np.float32),
            np.asarray(values["old_frame_world_rotation_xyzw"], dtype=np.float32),
            np.asarray(values["init_scale"], dtype=np.float32),
            np.asarray(values["negative_scale_direction"], dtype=np.float32),
            values["distance_weight"],
            expected["frame_interpolation"],
            values["velocity_weight_before_step"],
        )
        hotools_native.mc2_context_v0_update_center_dynamic(context, *center_args)
        before_invalid = hotools_native.mc2_context_v0_inspect(context)
        bad_args = list(center_args)
        bad_args[3] = np.zeros(4, dtype=np.float32)
        expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_center_dynamic(context, *bad_args),
            "unit quaternion",
        )
        after_invalid = hotools_native.mc2_context_v0_inspect(context)
        assert after_invalid["center_dynamic_revision"] == before_invalid["center_dynamic_revision"]

        outputs = (
            np.empty(3, dtype=np.float32), np.empty(4, dtype=np.float32),
            np.empty(3, dtype=np.float32), np.empty(4, dtype=np.float32),
            np.empty(3, dtype=np.float32), np.empty(4, dtype=np.float32),
            np.empty(3, dtype=np.float32),
        )
        expect_error(
            RuntimeError,
            lambda: hotools_native.mc2_context_v0_read_center_step(context, *outputs),
            "not ready",
        )
        step(context, values["simulation_delta_time"])
        scalars = hotools_native.mc2_context_v0_read_center_step(context, *outputs)
        actual = {
            "frame_interpolation": scalars["frame_interpolation"],
            "now_world_position": outputs[0],
            "now_world_rotation_xyzw": outputs[1],
            "step_vector": outputs[2],
            "step_rotation_xyzw": outputs[3],
            "step_move_inertia_ratio": scalars["step_move_inertia_ratio"],
            "step_rotation_inertia_ratio": scalars["step_rotation_inertia_ratio"],
            "inertia_vector": outputs[4],
            "inertia_rotation_xyzw": outputs[5],
            "angular_velocity": scalars["angular_velocity"],
            "rotation_axis": outputs[6],
            "scale_ratio": scalars["scale_ratio"],
            "gravity_dot": scalars["gravity_dot"],
            "gravity_ratio": scalars["gravity_ratio"],
            "velocity_weight": scalars["velocity_weight"],
            "blend_weight": scalars["blend_weight"],
        }
        for field, expected_value in expected.items():
            np.testing.assert_allclose(actual[field], expected_value, rtol=1.0e-6, atol=1.0e-6)
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["center_step_count"] == 1
        assert info["center_result_ready"] is True
        assert info["center_dynamic_ready"] is False
        hotools_native.mc2_context_v0_reset(context)
        reset_info = hotools_native.mc2_context_v0_inspect(context)
        assert reset_info["center_result_ready"] is False
        assert reset_info["center_dynamic_ready"] is False
    finally:
        hotools_native.mc2_context_v0_free(context)


def test_particle_inertia_matches_tier_a_fixture():
    fixture_path = (
        ROOT
        / "OmniNode" / "NodeTree" / "Function" / "physicsWorld" / "mc2"
        / "test" / "fixtures" / "tier_a" / "particle_step_inertia_001.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    values = fixture["input"]
    expected = fixture["expected"]
    context = hotools_native.mc2_context_v0_create(0, 1)
    try:
        proxy, baseline = static_arrays(1)
        baseline = list(baseline)
        baseline[7] = np.array([values["depth"]], dtype=np.float32)
        hotools_native.mc2_context_v0_update_proxy_static(context, *proxy)
        hotools_native.mc2_context_v0_update_baseline_static(context, *baseline)
        hotools_native.mc2_context_v0_update_distance_static(
            context,
            np.zeros((1, 2), dtype=np.int32),
            np.empty((0,), dtype=np.int32),
            np.empty((0,), dtype=np.float32),
        )
        hotools_native.mc2_context_v0_update_bending_static(
            context,
            np.empty((0, 4), dtype=np.int32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=np.int8),
        )
        hotools_native.mc2_context_v0_update_center_static(
            context,
            np.empty((0,), dtype=np.int32),
            np.zeros(3, dtype=np.float32),
            np.array([0.0, -1.0, 0.0], dtype=np.float32),
        )

        floats, ints, curves = parameters()
        floats[0] = 10.0
        floats[1:4] = (1.0, 0.0, 0.0)
        hotools_native.mc2_context_v0_update_parameters(context, floats, ints, curves)
        pre_positions = np.array([[2.9, 2.0, 1.0]], dtype=np.float32)
        rotations = np.array([[0.0, 0.0, 0.0, 1.0]], dtype=np.float32)
        update_dynamic(context, 1, 0, pre_positions, rotations)
        hotools_native.mc2_context_v0_reset(context)
        step(context, values["simulation_delta_time"], simulation_power_z=0.0)

        floats[0] = 0.0
        floats[5] = 1.0
        floats[16] = 0.75
        floats[17] = -1.0
        floats[18] = 600.0
        floats[19] = values["depth_inertia"]
        hotools_native.mc2_context_v0_update_parameters(context, floats, ints, curves)
        animated_positions = np.asarray([values["animated_position"]], dtype=np.float32)
        update_dynamic(
            context,
            2,
            0,
            animated_positions,
            rotations,
            velocity_weight=values["velocity_weight"],
        )
        step_half_angle = np.float32(
            np.radians(values["step_rotation_axis_angle"]["degrees"]) * 0.5
        )
        frame_rotation = np.array(
            [0.0, 0.0, np.sin(step_half_angle), np.cos(step_half_angle)],
            dtype=np.float32,
        )
        hotools_native.mc2_context_v0_update_center_dynamic(
            context,
            np.asarray(values["old_world_position"], dtype=np.float32),
            np.asarray(values["old_world_position"], dtype=np.float32)
                + np.asarray(values["step_vector"], dtype=np.float32),
            np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32),
            frame_rotation,
            np.ones(3, dtype=np.float32),
            np.ones(3, dtype=np.float32),
            np.asarray(values["old_world_position"], dtype=np.float32),
            np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32),
            np.ones(3, dtype=np.float32),
            np.ones(3, dtype=np.float32),
            1.0,
            1.0,
            values["velocity_weight"] - values["simulation_delta_time"],
        )
        step(context, values["simulation_delta_time"], simulation_power_z=0.0)
        out_positions = np.empty((1, 3), dtype=np.float32)
        out_rotations = np.empty((1, 4), dtype=np.float32)
        hotools_native.mc2_context_v0_read(context, out_positions, out_rotations)
        np.testing.assert_allclose(
            out_positions, expected["next_positions"], rtol=0.0, atol=1.0e-6
        )
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["particle_inertia_count"] == 1
        assert info["particle_prediction_count"] == 2
        assert info["step_basic_ready"] is True
    finally:
        hotools_native.mc2_context_v0_free(context)


if __name__ == "__main__":
    test_debug_baseline_readback_is_exact_and_validated()
    print("PASS debug baseline readback")
    test_tether_rollout_gate_and_source_order()
    print("PASS gated Tether source order")
    test_angle_runtime_values_and_source_order()
    print("PASS Angle runtime values and source order")
    test_motion_zero_max_distance_and_source_order()
    print("PASS Motion zero MaxDistance and source order")
    test_collider_upload_is_transactional()
    print("PASS collider upload transaction")
    test_self_collision_static_upload_is_transactional()
    print("PASS self-collision static upload transaction")
    test_self_collision_primitive_dynamics_follow_first_step_source_order()
    print("PASS self-collision first-step primitive dynamics")
    test_self_collision_grid_sort_and_unity_hash()
    print("PASS self-collision grid sort and Unity hash")
    test_self_collision_broadphase_candidates_are_filtered_and_typed()
    print("PASS self-collision broadphase candidates")
    test_self_collision_intersect_records_commit_only_on_final_substep()
    print("PASS self-collision cross-frame Intersect")
    test_point_collision_projection_and_post()
    print("PASS Point collision projection and post")
    test_bone_spring_soft_sphere_limit_and_velocity_reference()
    print("PASS BoneSpring soft sphere limit and velocity reference")
    test_edge_collision_projection_and_post()
    print("PASS Edge collision projection and post")
    test_lifecycle_and_transactional_validation()
    print("PASS lifecycle and transactional validation")
    test_create_free_soak_has_no_live_growth()
    print("PASS create/free soak")
    test_center_step_matches_tier_a_fixture()
    print("PASS Center step Tier A fixture")
    test_particle_inertia_matches_tier_a_fixture()
    print("PASS particle inertia Tier A fixture")
