import os
import sys
from pathlib import Path

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


def _expect_error(exception, callback, text):
    try:
        callback()
    except exception as exc:
        assert text in str(exc), str(exc)
    else:
        raise AssertionError(f"expected {exception.__name__}: {text}")


def _proxy():
    count = 3
    positions = np.array([[0, 0, 0], [0, 1, 0], [0.25, 2, 0]], dtype=np.float32)
    normals = np.tile(np.array([[0, 1, 0]], dtype=np.float32), (count, 1))
    tangents = np.tile(np.array([[0, 0, 1]], dtype=np.float32), (count, 1))
    uvs = np.zeros((count, 2), dtype=np.float32)
    attributes = np.array([1, 2, 2], dtype=np.uint8)
    edges = np.array([[0, 1], [1, 2]], dtype=np.int32)
    triangles = np.empty((0, 3), dtype=np.int32)
    return positions, normals, tangents, uvs, attributes, edges, triangles


def _baseline():
    parents = np.array([-1, 0, 1], dtype=np.int32)
    child_ranges = np.array([[0, 1], [1, 1], [2, 0]], dtype=np.int32)
    child_data = np.array([1, 2], dtype=np.int32)
    flags = np.array([1], dtype=np.uint8)
    ranges = np.array([[0, 3]], dtype=np.int32)
    data = np.array([0, 1, 2], dtype=np.int32)
    roots = np.array([-1, 0, 0], dtype=np.int32)
    depths = np.array([0, 0.5, 1], dtype=np.float32)
    local_positions = np.array([[0, 0, 0], [0, 1, 0], [0.25, 1, 0]], dtype=np.float32)
    local_rotations = np.tile(np.array([[0, 0, 0, 1]], dtype=np.float32), (3, 1))
    return (
        parents,
        child_ranges,
        child_data,
        flags,
        ranges,
        data,
        roots,
        depths,
        local_positions,
        local_rotations,
    )


def _bone():
    vertex_ranges = np.array([[0, 1], [1, 2], [3, 1]], dtype=np.int32)
    vertex_data = np.array([1, 2, 0, 1], dtype=np.int32)
    triangle_ranges = np.zeros((3, 2), dtype=np.int32)
    triangle_data = np.empty((0, 2), dtype=np.int32)
    bind_positions = np.array([[0, 0, 0], [0, -1, 0], [-0.25, -2, 0]], dtype=np.float32)
    identity = np.tile(np.array([[0, 0, 0, 1]], dtype=np.float32), (3, 1))
    return (
        vertex_ranges,
        vertex_data,
        triangle_ranges,
        triangle_data,
        bind_positions,
        identity.copy(),
        identity.copy(),
        identity.copy(),
    )


def test_bone_static_native_transaction():
    context = hotools_native.mc2_context_v0_create(0, 3)
    try:
        _expect_error(
            RuntimeError,
            lambda: hotools_native.mc2_context_v0_update_bone_static(context, *_bone()),
            "requires proxy and baseline",
        )
        hotools_native.mc2_context_v0_update_proxy_static(context, *_proxy())
        hotools_native.mc2_context_v0_update_baseline_static(context, *_baseline())
        hotools_native.mc2_context_v0_update_bone_static(context, *_bone())
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["bone_static_ready"] is True
        assert info["bone_static_revision"] == 1
        assert info["bone_vertex_adjacency_count"] == 4
        assert info["bone_vertex_triangle_record_count"] == 0

        bad_adjacency = list(_bone())
        bad_adjacency[1] = np.array([1, 0, 1, 1], dtype=np.int32)
        _expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_bone_static(
                context,
                *bad_adjacency,
            ),
            "self or duplicate",
        )
        assert hotools_native.mc2_context_v0_inspect(context)["bone_static_revision"] == 1

        bad_rotation = list(_bone())
        bad_rotation[7] = np.zeros((3, 4), dtype=np.float32)
        _expect_error(
            ValueError,
            lambda: hotools_native.mc2_context_v0_update_bone_static(
                context,
                *bad_rotation,
            ),
            "unit quaternions",
        )
        assert hotools_native.mc2_context_v0_inspect(context)["bone_static_revision"] == 1
    finally:
        hotools_native.mc2_context_v0_free(context)


if __name__ == "__main__":
    test_bone_static_native_transaction()
    print("MC2 Bone static native: PASS")
