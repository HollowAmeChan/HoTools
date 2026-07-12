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


def test_lifecycle_and_transactional_validation():
    baseline = hotools_native.mc2_context_v0_stats().copy()
    first = hotools_native.mc2_context_v0_create(0, 2)
    second = hotools_native.mc2_context_v0_create(0, 3)
    third = hotools_native.mc2_context_v0_create(0, 4)
    assert hotools_native.mc2_context_v0_stats()["live"] == baseline["live"] + 3
    try:
        second_positions, second_rotations = frame(3)
        expect_error(
            RuntimeError,
            lambda: hotools_native.mc2_context_v0_update_dynamic(
                second, 0, 0, second_positions, second_rotations
            ),
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
        hotools_native.mc2_context_v0_update_dynamic(first, 12, 7, positions, rotations)
        bad_rotations = rotations.copy()
        bad_rotations[0] = 0.0
        expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_dynamic(first, 13, 7, positions, bad_rotations),
            "unit quaternions",
        )
        info = hotools_native.mc2_context_v0_inspect(first)
        assert info["dynamic_revision"] == 1 and info["frame"] == 12

        expect_error(
            RuntimeError,
            lambda: hotools_native.mc2_context_v0_step(first, 1.0 / 60.0),
            "not ready",
        )
        hotools_native.mc2_context_v0_reset(first)
        hotools_native.mc2_context_v0_step(first, 1.0 / 60.0)
        out_positions = np.empty_like(positions)
        out_rotations = np.empty_like(rotations)
        hotools_native.mc2_context_v0_read(first, out_positions, out_rotations)
        np.testing.assert_allclose(
            out_positions,
            np.array([[2.0, 0.0, 0.0], [3.25, 0.0, 0.0]], dtype=np.float32),
            rtol=0.0,
            atol=1.0e-6,
        )
        np.testing.assert_array_equal(out_rotations, rotations)
        info = hotools_native.mc2_context_v0_inspect(first)
        assert info["reset_count"] == 1 and info["step_count"] == 1
        assert info["distance_solve_count"] == 1

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
        hotools_native.mc2_context_v0_update_dynamic(
            second, 1, 0, tier_a_positions, pin_rotations
        )
        hotools_native.mc2_context_v0_reset(second)
        hotools_native.mc2_context_v0_step(second, 1.0 / 60.0)
        tier_a_out = np.empty_like(tier_a_positions)
        tier_a_out_rotations = np.empty_like(pin_rotations)
        hotools_native.mc2_context_v0_read(
            second, tier_a_out, tier_a_out_rotations
        )
        np.testing.assert_allclose(
            tier_a_out,
            np.array([[1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [4.0, 0.0, 0.0]], dtype=np.float32),
            rtol=0.0,
            atol=1.0e-6,
        )

        pin_proxy = list(tier_a_proxy)
        pin_proxy[4] = np.array([1, 2, 2], dtype=np.uint8)
        hotools_native.mc2_context_v0_update_proxy_static(second, *pin_proxy)
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
        hotools_native.mc2_context_v0_update_dynamic(
            second, 1, 0, pin_positions, pin_rotations
        )
        hotools_native.mc2_context_v0_reset(second)
        moved_pin_positions = pin_positions.copy()
        moved_pin_positions[0, 0] = 5.0
        hotools_native.mc2_context_v0_update_dynamic(
            second, 2, 0, moved_pin_positions, pin_rotations
        )
        hotools_native.mc2_context_v0_step(second, 1.0 / 60.0)
        pin_out_positions = np.empty_like(pin_positions)
        pin_out_rotations = np.empty_like(pin_rotations)
        hotools_native.mc2_context_v0_read(
            second, pin_out_positions, pin_out_rotations
        )
        np.testing.assert_array_equal(
            pin_out_positions,
            np.array([[5.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=np.float32),
        )
        assert hotools_native.mc2_context_v0_inspect(second)["distance_solve_count"] == 1
    finally:
        hotools_native.mc2_context_v0_free(first)
        hotools_native.mc2_context_v0_free(first)
        hotools_native.mc2_context_v0_free(second)
        hotools_native.mc2_context_v0_free(third)
    assert hotools_native.mc2_context_v0_stats()["live"] == baseline["live"]
    assert hotools_native.mc2_context_v0_inspect(first)["released"] is True
    expect_error(RuntimeError, lambda: hotools_native.mc2_context_v0_reset(first), "released")


def test_create_free_soak_has_no_live_growth():
    baseline = hotools_native.mc2_context_v0_stats()["live"]
    for _ in range(1000):
        context = hotools_native.mc2_context_v0_create(0, 1)
        hotools_native.mc2_context_v0_free(context)
    assert hotools_native.mc2_context_v0_stats()["live"] == baseline


if __name__ == "__main__":
    test_lifecycle_and_transactional_validation()
    print("PASS lifecycle and transactional validation")
    test_create_free_soak_has_no_live_growth()
    print("PASS create/free soak")
