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


if __name__ == "__main__":
    test_triangle_direction_unifies_connected_surface()
    print("PASS MC2 native triangle direction")
    test_triangle_direction_rejects_degenerate_input()
    print("PASS MC2 native triangle direction validation")
