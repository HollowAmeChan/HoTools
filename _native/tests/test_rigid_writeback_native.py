"""公共刚体写回反算的 native ABI 测试。"""

import math
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, os.environ.get(
    "HOTOOLS_NATIVE_TEST_DIR",
    str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage"),
))

import hotools_native  # noqa: E402


def _compute(base_euler, solved_quaternion, mode):
    return hotools_native.compute_rigid_delta_columns_v2(
        np.zeros((1, 3), dtype=np.float32),
        np.asarray([base_euler], dtype=np.float32),
        np.asarray([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
        np.asarray([[0.0, 0.0, 0.0, 1.0]], dtype=np.float32),
        np.zeros((1, 3), dtype=np.float32),
        np.asarray([solved_quaternion], dtype=np.float32),
        np.asarray([0], dtype=np.int32),
        np.asarray([mode], dtype=np.int32),
    )


def test_rigid_writeback_euler_orders():
    """六种 Euler 顺序都应返回有限的列式结果。"""
    for mode in range(6):
        result = _compute((0.2, -0.4, 0.7), (0.9, 0.1, -0.2, 0.3), mode)
        assert len(result) == 3
        locations, eulers, quaternions = result
        assert locations.shape == (1, 3)
        assert eulers.shape == (1, 3)
        assert quaternions.shape == (1, 4)
        assert np.isfinite(eulers).all()
        assert np.isfinite(quaternions).all()


def test_rigid_writeback_non_euler_modes():
    """Quaternion 与 Axis-Angle 模式保留四元数增量，Euler 增量置零。"""
    for mode in (6, 7):
        locations, eulers, quaternions = _compute(
            (0.0, 0.0, 0.0),
            (math.cos(0.25), 0.0, math.sin(0.25), 0.0),
            mode,
        )
        assert np.allclose(eulers, 0.0)
        assert np.isclose(np.linalg.norm(quaternions[0]), 1.0, atol=1.0e-5)
        assert np.isfinite(locations).all()
