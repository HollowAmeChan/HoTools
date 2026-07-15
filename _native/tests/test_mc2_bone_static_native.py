import importlib
import os
import sys
import types
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


NODETREE = ROOT / "OmniNode" / "NodeTree"
FUNCTION = NODETREE / "Function"
PHYSICS_WORLD = FUNCTION / "physicsWorld"
for package_name, package_path in (
    ("HoTools", ROOT),
    ("HoTools.OmniNode", ROOT / "OmniNode"),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PHYSICS_WORLD),
):
    module = types.ModuleType(package_name)
    module.__path__ = [str(package_path)]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

bone_rotation = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.bone_rotation"
)


def _expect_error(exception, callback, text):
    try:
        callback()
    except exception as exc:
        assert text in str(exc), str(exc)
    else:
        raise AssertionError(f"expected {exception.__name__}: {text}")


def _proxy():
    count = 3
    positions = np.array([[0, 0, 0], [0, 1, 0], [0, 2, 0]], dtype=np.float32)
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
    local_positions = np.array([[0, 0, 0], [0, 1, 0], [0, 1, 0]], dtype=np.float32)
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
    bind_positions = np.array([[0, 0, 0], [0, -1, 0], [0, -2, 0]], dtype=np.float32)
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

        distance_ranges = np.array([[0, 1], [1, 2], [3, 1]], dtype=np.int32)
        distance_targets = np.array([1, 2, 0, 1], dtype=np.int32)
        distance_rests = np.ones(4, dtype=np.float32)
        hotools_native.mc2_context_v0_update_distance_static(
            context,
            distance_ranges,
            distance_targets,
            distance_rests,
        )
        hotools_native.mc2_context_v0_update_bending_static(
            context,
            np.empty((0, 4), dtype=np.int32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=np.int8),
        )
        floats = np.zeros(47, dtype=np.float32)
        floats[0] = 5.0
        floats[1] = 1.0
        floats[6:9] = 1.0
        ints = np.zeros(11, dtype=np.int32)
        curves = np.zeros((9, 16), dtype=np.float32)
        curves[2, :] = 1.0
        hotools_native.mc2_context_v0_update_parameters(
            context,
            floats,
            ints,
            curves,
        )
        base_positions = _proxy()[0].copy()
        base_rotations = np.tile(
            np.array([[0, 0, 0, 1]], dtype=np.float32),
            (3, 1),
        )
        hotools_native.mc2_context_v0_update_dynamic(
            context,
            1,
            0,
            base_positions,
            base_rotations,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
        )
        hotools_native.mc2_context_v0_reset(context)
        hotools_native.mc2_context_v0_step(context, 0.1, 1.0, 1.0)
        state_positions = np.empty((3, 3), dtype=np.float32)
        state_rotations = np.empty((3, 4), dtype=np.float32)
        step_positions = np.empty((3, 3), dtype=np.float32)
        step_rotations = np.empty((3, 4), dtype=np.float32)
        output_positions = np.empty((3, 3), dtype=np.float32)
        output_rotations = np.empty((3, 4), dtype=np.float32)
        hotools_native.mc2_context_v0_read(
            context,
            state_positions,
            state_rotations,
        )
        hotools_native.mc2_context_v0_read_step_basic(
            context,
            step_positions,
            step_rotations,
        )
        hotools_native.mc2_context_v0_read_bone_output(
            context,
            output_positions,
            output_rotations,
        )
        expected = bone_rotation.evaluate_mc2_bone_line_rotation(
            attributes=_proxy()[4],
            positions=state_positions,
            rotations=state_rotations,
            base_positions=step_positions,
            base_rotations=step_rotations,
            vertex_local_positions=_baseline()[8],
            vertex_local_rotations=_baseline()[9],
            vertex_to_transform_rotations=_bone()[7],
            parent_indices=_baseline()[0],
            transform_scales=np.ones((3, 3), dtype=np.float32),
            transform_local_positions=np.zeros((3, 3), dtype=np.float32),
            transform_local_rotations=base_rotations,
            child_ranges=_baseline()[1],
            child_data=_baseline()[2],
            baseline_data=_baseline()[5],
            rotational_interpolation=1.0,
            root_rotation=1.0,
            animation_pose_ratio=0.0,
            blend_weight=1.0,
        )
        np.testing.assert_allclose(
            output_positions,
            np.asarray(expected.world_positions, dtype=np.float32),
            rtol=2.0e-6,
            atol=5.0e-7,
        )
        np.testing.assert_allclose(
            output_rotations,
            np.asarray(expected.world_rotations, dtype=np.float32),
            rtol=2.0e-6,
            atol=1.0e-6,
        )
        info = hotools_native.mc2_context_v0_inspect(context)
        assert info["bone_output_ready"] is True
        assert info["bone_line_output_count"] == 1

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
