"""Bone DomainV1 帧方向无状态 native ABI 回归。"""

from __future__ import annotations

import os
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(
    0,
    os.environ.get(
        "HOTOOLS_NATIVE_TEST_DIR",
        str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage"),
    ),
)

import hotools_native  # noqa: E402


IDENTITY_QUATERNION = np.array((0.0, 0.0, 0.0, 1.0), dtype=np.float32)


def _expect_error(exception, callback, text):
    try:
        callback()
    except exception as exc:
        assert text in str(exc), str(exc)
    else:
        raise AssertionError(f"expected {exception.__name__}: {text}")


def _orientations(matrices, component=None, vertex_to_transform=None):
    matrices = np.ascontiguousarray(matrices, dtype=np.float32)
    count = len(matrices)
    if component is None:
        component = IDENTITY_QUATERNION
    if vertex_to_transform is None:
        vertex_to_transform = np.tile(IDENTITY_QUATERNION, (count, 1))
    output = np.full((count, 4), np.nan, dtype=np.float32)
    hotools_native.mc2_bone_frame_orientations_v1(
        matrices,
        np.ascontiguousarray(component, dtype=np.float32),
        np.ascontiguousarray(vertex_to_transform, dtype=np.float32),
        output,
    )
    return output


def test_bone_frame_orientation_preserves_component_and_scale_free_basis():
    matrices = np.array(
        (
            np.eye(3),
            np.diag((2.0, 3.0, 4.0)),
        ),
        dtype=np.float32,
    )
    half = np.float32(np.sqrt(0.5))
    component = np.array((0.0, 0.0, half, half), dtype=np.float32)
    result = _orientations(matrices, component=component)
    np.testing.assert_allclose(
        result,
        np.tile(component, (2, 1)),
        rtol=0.0,
        atol=2.0e-6,
    )


def test_bone_frame_orientation_applies_inverse_vertex_to_transform():
    half = np.float32(np.sqrt(0.5))
    vertex_to_transform = np.array(((half, 0.0, 0.0, half),), dtype=np.float32)
    result = _orientations(
        np.eye(3, dtype=np.float32)[None, :, :],
        vertex_to_transform=vertex_to_transform,
    )
    np.testing.assert_allclose(
        result,
        np.array(((-half, 0.0, 0.0, half),), dtype=np.float32),
        rtol=0.0,
        atol=2.0e-6,
    )


def test_bone_frame_orientation_failure_is_output_atomic():
    matrices = np.array((np.eye(3), np.eye(3)), dtype=np.float32)
    matrices[1, 0, 1] = 0.25
    vertex_to_transform = np.tile(IDENTITY_QUATERNION, (2, 1))
    output = np.full((2, 4), 17.0, dtype=np.float32)
    _expect_error(
        ValueError,
        lambda: hotools_native.mc2_bone_frame_orientations_v1(
            matrices,
            IDENTITY_QUATERNION,
            vertex_to_transform,
            output,
        ),
        "proper and shear-free",
    )
    np.testing.assert_array_equal(output, np.full((2, 4), 17.0, dtype=np.float32))


def test_bone_frame_orientation_rejects_invalid_pose_and_quaternions():
    identity = np.eye(3, dtype=np.float32)[None, :, :]
    reflected = identity.copy()
    reflected[0, 0, 0] = -1.0
    _expect_error(
        ValueError,
        lambda: _orientations(reflected),
        "proper and shear-free",
    )
    zero_scale = identity.copy()
    zero_scale[0, :, 0] = 0.0
    _expect_error(ValueError, lambda: _orientations(zero_scale), "zero scale")
    _expect_error(
        ValueError,
        lambda: _orientations(identity, component=(0.0, 0.0, 0.0, 2.0)),
        "unit quaternion",
    )
    _expect_error(
        ValueError,
        lambda: _orientations(
            identity,
            vertex_to_transform=np.array(((0.0, 0.0, 0.0, 0.0),), dtype=np.float32),
        ),
        "unit quaternions",
    )
