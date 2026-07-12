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
    assert hotools_native.mc2_context_v0_stats()["live"] == baseline["live"] + 2
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

        floats, ints, curves = parameters()
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
        np.testing.assert_array_equal(out_positions, positions)
        np.testing.assert_array_equal(out_rotations, rotations)
        info = hotools_native.mc2_context_v0_inspect(first)
        assert info["reset_count"] == 1 and info["step_count"] == 1
    finally:
        hotools_native.mc2_context_v0_free(first)
        hotools_native.mc2_context_v0_free(first)
        hotools_native.mc2_context_v0_free(second)
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
