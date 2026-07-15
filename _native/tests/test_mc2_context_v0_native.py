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
    test_tether_rollout_gate_and_source_order()
    print("PASS gated Tether source order")
    test_angle_runtime_values_and_source_order()
    print("PASS Angle runtime values and source order")
    test_motion_zero_max_distance_and_source_order()
    print("PASS Motion zero MaxDistance and source order")
    test_collider_upload_is_transactional()
    print("PASS collider upload transaction")
    test_point_collision_projection_and_post()
    print("PASS Point collision projection and post")
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
