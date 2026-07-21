"""Native E3 MC2 CPU domain data-path owner tests."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, os.environ.get(
    "HOTOOLS_NATIVE_TEST_DIR",
    str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage"),
))

import hotools_native  # noqa: E402


def _create():
    bind_positions = np.asarray(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        dtype=np.float32,
    )
    bind_rotations = np.asarray(
        ((0.0, 0.0, 0.0, 1.0),) * 3,
        dtype=np.float32,
    )
    bind_positions.flags.writeable = False
    bind_rotations.flags.writeable = False
    return hotools_native.mc2_domain_cpu_v1_create(
        1,
        3,
        "domain:test",
        "layout:test",
        bind_positions,
        bind_rotations,
    )


def _frame(offset=0.0):
    positions = np.asarray(
        ((offset, 0.0, 0.0), (1.0 + offset, 0.0, 0.0), (offset, 1.0, 0.0)),
        dtype=np.float32,
    )
    normals = np.asarray(((0.0, 0.0, 1.0),) * 3, dtype=np.float32)
    positions.flags.writeable = False
    normals.flags.writeable = False
    return positions, normals


def test_domain_cpu_native_lifecycle_and_owned_frame_output():
    before = hotools_native.mc2_domain_cpu_v1_stats()["live_domain_count"]
    handle = _create()
    assert hotools_native.mc2_domain_cpu_v1_stats()["live_domain_count"] == before + 1
    try:
        info = hotools_native.mc2_domain_cpu_v1_inspect(handle)
        assert info["particle_count"] == 3
        assert info["frame"] == -1
        positions, normals = _frame(2.0)
        expected_positions = positions.copy()
        hotools_native.mc2_domain_cpu_v1_update_frame(
            handle,
            "domain:test",
            "layout:test",
            8,
            3,
            positions,
            normals,
        )
        positions.flags.writeable = True
        positions[:] = -100.0
        hotools_native.mc2_domain_cpu_v1_step(handle)
        output = hotools_native.mc2_domain_cpu_v1_read(handle)
        assert output["frame"] == 8
        assert output["generation"] == 3
        assert output["step_count"] == 1
        assert output["backend_kind"] == "mc2_domain_cpu_v1_datapath"
        assert np.array_equal(output["world_positions"], expected_positions)
        assert np.array_equal(output["world_normals"], normals)
    finally:
        hotools_native.mc2_domain_cpu_v1_dispose(handle)
        hotools_native.mc2_domain_cpu_v1_dispose(handle)
    assert hotools_native.mc2_domain_cpu_v1_stats()["live_domain_count"] == before


def test_domain_cpu_native_rejects_identity_without_mutating_published_frame():
    handle = _create()
    try:
        positions, normals = _frame(1.0)
        hotools_native.mc2_domain_cpu_v1_update_frame(
            handle,
            "domain:test",
            "layout:test",
            4,
            2,
            positions,
            normals,
        )
        bad_positions, bad_normals = _frame(9.0)
        try:
            hotools_native.mc2_domain_cpu_v1_update_frame(
                handle,
                "domain:wrong",
                "layout:test",
                5,
                2,
                bad_positions,
                bad_normals,
            )
        except ValueError as exc:
            assert "signature mismatch" in str(exc)
        else:
            raise AssertionError("mismatched domain signature was accepted")
        output = hotools_native.mc2_domain_cpu_v1_read(handle)
        assert output["frame"] == 4
        assert np.array_equal(output["world_positions"], positions)
    finally:
        hotools_native.mc2_domain_cpu_v1_dispose(handle)


def test_domain_cpu_native_requires_frame_before_step():
    handle = _create()
    try:
        try:
            hotools_native.mc2_domain_cpu_v1_step(handle)
        except RuntimeError as exc:
            assert "requires update_frame" in str(exc)
        else:
            raise AssertionError("step without frame was accepted")
    finally:
        hotools_native.mc2_domain_cpu_v1_dispose(handle)


if __name__ == "__main__":
    tests = sorted(
        (name, value)
        for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"MC2 native CPU domain: {len(tests)} passed")
