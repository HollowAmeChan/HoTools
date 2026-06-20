import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, os.environ.get("HOTOOLS_NATIVE_TEST_DIR", str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage")))

import hotools_native  # noqa: E402


MOVE = 1 << 2
MOTION = 1 << 3


def _minimal_full_core_args(positions, old_positions, edges, triangles, *, self_enabled=True):
    vertex_count = len(positions)
    identity = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    empty_i32 = np.empty(0, dtype=np.int32)
    empty_i32_quad = np.empty((0, 4), dtype=np.int32)
    empty_f32 = np.empty(0, dtype=np.float32)
    return (
        positions,
        old_positions,
        old_positions.copy(),
        np.zeros_like(positions),
        np.zeros_like(positions),
        np.zeros(vertex_count, dtype=np.float32),
        np.zeros(vertex_count, dtype=np.float32),
        np.zeros_like(positions),
        np.zeros(vertex_count, dtype=np.float32),
        old_positions.copy(),
        np.repeat(identity.reshape(1, 4), vertex_count, axis=0).copy(),
        old_positions.copy(),
        old_positions.copy(),
        np.asarray(((0.0, 0.0, 1.0),) * vertex_count, dtype=np.float32),
        np.repeat(identity.reshape(1, 4), vertex_count, axis=0).copy(),
        np.full(vertex_count, MOVE | MOTION, dtype=np.uint8),
        np.zeros(vertex_count, dtype=np.float32),
        np.full(vertex_count, -1, dtype=np.int32),
        np.zeros(vertex_count, dtype=np.float32),
        np.full(vertex_count, -1, dtype=np.int32),
        np.zeros(vertex_count, dtype=np.int32),
        np.zeros(vertex_count, dtype=np.int32),
        empty_i32,
        np.zeros((vertex_count, 3), dtype=np.float32),
        np.repeat(identity.reshape(1, 4), vertex_count, axis=0).copy(),
        np.zeros(vertex_count, dtype=np.int32),
        np.zeros(vertex_count, dtype=np.int32),
        empty_i32,
        empty_f32,
        np.zeros(vertex_count, dtype=np.float32),
        np.zeros(vertex_count, dtype=np.int32),
        np.zeros(vertex_count, dtype=np.int32),
        empty_i32,
        empty_f32,
        np.zeros(vertex_count, dtype=np.float32),
        empty_i32_quad,
        empty_f32,
        empty_i32,
        empty_i32_quad,
        empty_f32,
        np.zeros(vertex_count, dtype=np.float32),
        np.zeros(vertex_count, dtype=np.float32),
        np.zeros(vertex_count, dtype=np.float32),
        np.zeros(vertex_count, dtype=np.float32),
        np.zeros(vertex_count, dtype=np.float32),
        np.full(vertex_count, 10.0, dtype=np.float32),
        np.zeros(vertex_count, dtype=np.float32),
        np.zeros(vertex_count, dtype=np.float32),
        np.zeros(vertex_count, dtype=np.float32),
        edges,
        triangles,
        np.zeros(vertex_count, dtype=np.float32),
        empty_i32,
        empty_i32,
        np.empty((0, 3), dtype=np.float32),
        np.empty((0, 3), dtype=np.float32),
        np.empty((0, 3), dtype=np.float32),
        np.empty((0, 3), dtype=np.float32),
        np.empty((0, 3), dtype=np.float32),
        np.empty((0, 3), dtype=np.float32),
        empty_f32,
        np.asarray(((0.0, 0.0, 0.0),), dtype=np.float32),
        np.asarray(((0.0, 0.0, 0.0),), dtype=np.float32),
        np.asarray(((0.0, 0.0, 0.0, 1.0),), dtype=np.float32),
        np.asarray(((0.0, 0.0, 0.0),), dtype=np.float32),
        np.asarray(((0.0, 0.0, 0.0, 1.0),), dtype=np.float32),
        np.asarray(((0.0, 0.0, 0.0),), dtype=np.float32),
        np.asarray(((0.0, 0.0, 0.0),), dtype=np.float32),
        np.zeros(1, dtype=np.float32),
        np.ones(1, dtype=np.float32),
        1.0 / 60.0,
        1.0 / 60.0,
        1,
        0,
        np.zeros(3, dtype=np.float32),
        0.0,
        0.0,
        False,
        0.0,
        0.0,
        0.0,
        0.2,
        -1.0,
        0.0,
        1,
        0,
        0,
        1.3,
        0.0,
        1.0,
        self_enabled,
        0.05,
        0.0,
    )


def test_point_triangle_contact():
    positions = np.array(
        [
            [0.25, 0.25, 0.01],
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    old_positions = positions.copy()
    old_positions[0, 2] = 0.04
    inv_masses = np.ones(4, dtype=np.float32)
    attributes = np.full(4, MOVE, dtype=np.uint8)
    normals = np.zeros_like(positions)
    friction = np.zeros(4, dtype=np.float32)

    hotools_native.project_self_collisions_mc2(
        positions,
        old_positions,
        inv_masses,
        np.empty((0, 2), dtype=np.int32),
        np.asarray([[1, 2, 3]], dtype=np.int32),
        attributes,
        normals,
        friction,
        0.05,
    )

    assert positions[0, 2] > 0.03
    assert positions[1:4, 2].mean() < 0.0
    assert np.isclose(np.linalg.norm(normals[0]), 1.0, atol=1.0e-5)
    assert friction[0] > 0.0


def test_edge_edge_contact():
    positions = np.asarray(
        [
            [-0.5, 0.0, 0.0],
            [0.5, 0.0, 0.0],
            [0.0, -0.5, 0.01],
            [0.0, 0.5, 0.01],
        ],
        dtype=np.float32,
    )
    old_positions = positions.copy()
    old_positions[2:, 2] = 0.04
    inv_masses = np.ones(4, dtype=np.float32)
    attributes = np.full(4, MOVE, dtype=np.uint8)
    normals = np.zeros_like(positions)
    friction = np.zeros(4, dtype=np.float32)

    hotools_native.project_self_collisions_mc2(
        positions,
        old_positions,
        inv_masses,
        np.asarray([[0, 1], [2, 3]], dtype=np.int32),
        np.empty((0, 3), dtype=np.int32),
        attributes,
        normals,
        friction,
        0.05,
    )

    assert positions[:2, 2].mean() < 0.0
    assert positions[2:, 2].mean() > 0.02
    assert np.isclose(np.linalg.norm(normals[2]), 1.0, atol=1.0e-5)
    assert friction[2] > 0.0


def test_full_core_self_collision_stage():
    positions = np.array(
        [
            [0.25, 0.25, 0.01],
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    old_positions = positions.copy()
    old_positions[0, 2] = 0.04
    hotools_native.solve_meshcloth_mc2(
        *_minimal_full_core_args(
            positions,
            old_positions,
            np.empty((0, 2), dtype=np.int32),
            np.asarray([[1, 2, 3]], dtype=np.int32),
        )
    )

    assert positions[0, 2] > 0.03
    assert positions[1:4, 2].mean() < 0.0


if __name__ == "__main__":
    test_point_triangle_contact()
    test_edge_edge_contact()
    test_full_core_self_collision_stage()
    print("mc2 self collision native smoke test passed")
