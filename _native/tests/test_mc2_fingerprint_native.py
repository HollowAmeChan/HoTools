"""Raw ABI tests for the product-owned MC2 static fingerprints."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
package_dir = Path(
    os.environ.get(
        "HOTOOLS_NATIVE_TEST_DIR",
        ROOT / "_Lib" / PY_LIB / "HotoolsPackage",
    )
)
sys.path.insert(0, str(package_dir))

import hotools_native


def _assert_fingerprint(value) -> None:
    assert set(value) == {"topology", "geometry", "surface"}
    assert all(len(item) == 32 for item in value.values())


def test_mesh_product_fingerprint_v1_has_stable_shape() -> None:
    arguments = (
        np.asarray((0, 0, 0, 1, 0, 0, 0, 1, 0), dtype=np.float32),
        np.asarray((0, 0, 1) * 3, dtype=np.float32),
        np.asarray((0, 1, 1, 2, 0, 2), dtype=np.int32),
        np.asarray((0, 1, 2), dtype=np.int32),
        np.asarray((0, 1, 2), dtype=np.int32),
        np.empty((0,), dtype=np.float32),
        np.empty((0,), dtype=np.float32),
        np.ones((3,), dtype=np.float32),
        1,
        2,
        False,
        "",
        "",
        False,
    )
    product = hotools_native.mc2_mesh_static_fingerprint_v1(*arguments)
    _assert_fingerprint(product)


def test_bone_product_fingerprint_v1_has_stable_shape() -> None:
    arguments = (
        np.asarray((-1, 0), dtype=np.int32),
        np.asarray((0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 2, 0), dtype=np.float32),
        np.tile(np.identity(4, dtype=np.float32).reshape(-1), 2),
        123,
        "root",
        "line",
        "bone_cloth",
        True,
    )
    product = hotools_native.mc2_bone_static_fingerprint_v1(*arguments)
    _assert_fingerprint(product)
