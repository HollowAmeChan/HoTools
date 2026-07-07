"""Native VRM SpringBone solver smoke tests."""

from __future__ import annotations

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


def _identity_matrix() -> np.ndarray:
    return np.asarray((
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ), dtype=np.float32)


def _base_args(
    *,
    gravity_dir=(1.0, 0.0, 0.0),
    hit_radius=0.0,
    collided_by_groups=0,
    collider_types=(),
    collider_groups=(),
    collider_centers=(),
    collider_segment_a=(),
    collider_segment_b=(),
    collider_radii=(),
    dt=1.0 / 60.0,
    substeps=1,
    stiffness_force=0.0,
    drag_force=0.0,
    gravity_power=9.8,
):
    current_tails = np.asarray(((0.0, 0.0, 1.0),), dtype=np.float32)
    prev_tails = current_tails.copy()
    target_matrices = np.asarray((_identity_matrix(),), dtype=np.float32)
    target_quaternions = np.asarray(((0.0, 0.0, 0.0, 1.0),), dtype=np.float32)
    current_heads = np.asarray(((0.0, 0.0, 0.0),), dtype=np.float32)
    current_pose_matrices = target_matrices.copy()
    current_pose_quaternions = target_quaternions.copy()
    parent_pose_quaternions = target_quaternions.copy()
    current_pose_tails = current_tails.copy()
    lengths = np.asarray((1.0,), dtype=np.float32)
    init_axis_local = np.asarray(((0.0, 0.0, 1.0),), dtype=np.float32)
    init_axis_parent = init_axis_local.copy()
    init_rotations = target_quaternions.copy()
    init_scales = np.asarray(((1.0, 1.0, 1.0),), dtype=np.float32)
    parent_indices = np.asarray((-1,), dtype=np.int32)
    pinned = np.asarray((0,), dtype=np.uint8)
    use_connect = np.asarray((0,), dtype=np.uint8)
    root_quaternion = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    root_tail_world = np.asarray((0.0, 0.0, 0.0), dtype=np.float32)
    armature_world = _identity_matrix()
    armature_world_inv = _identity_matrix()
    gravity_dir_array = np.asarray(gravity_dir, dtype=np.float32)
    hit_radii = np.asarray((float(hit_radius),), dtype=np.float32)
    collided_by_groups_array = np.asarray((int(collided_by_groups),), dtype=np.int32)

    return [
        current_tails,
        prev_tails,
        target_matrices,
        target_quaternions,
        current_heads,
        current_pose_matrices,
        current_pose_quaternions,
        parent_pose_quaternions,
        current_pose_tails,
        lengths,
        init_axis_local,
        init_axis_parent,
        init_rotations,
        init_scales,
        parent_indices,
        pinned,
        use_connect,
        root_quaternion,
        root_tail_world,
        armature_world,
        armature_world_inv,
        gravity_dir_array,
        hit_radii,
        collided_by_groups_array,
        np.asarray(collider_types, dtype=np.int32),
        np.asarray(collider_groups, dtype=np.int32),
        np.asarray(collider_centers, dtype=np.float32).reshape((-1, 3)),
        np.asarray(collider_segment_a, dtype=np.float32).reshape((-1, 3)),
        np.asarray(collider_segment_b, dtype=np.float32).reshape((-1, 3)),
        np.asarray(collider_radii, dtype=np.float32),
        float(dt),
        int(substeps),
        float(stiffness_force),
        float(drag_force),
        float(gravity_power),
    ]


def _solve(args):
    hotools_native.solve_spring_bone_vrm_cpp(*args)
    return args


def _tail(args) -> np.ndarray:
    return args[0][0].copy()


def test_spring_bone_vrm_gravity_projects_to_bone_length():
    args = _solve(_base_args(gravity_dir=(1.0, 0.0, 0.0), gravity_power=9.8))
    tail = _tail(args)
    assert tail[0] > 0.01
    assert abs(float(np.linalg.norm(tail)) - 1.0) < 1.0e-5
    assert args[2][0, 0] < 1.0


def test_spring_bone_vrm_plane_collider_pushes_tail():
    args = _solve(_base_args(
        gravity_power=0.0,
        hit_radius=0.2,
        collided_by_groups=1,
        collider_types=(2,),
        collider_groups=(1,),
        collider_centers=((0.1, 0.0, 1.0),),
        collider_segment_a=((1.0, 0.0, 0.0),),
        collider_segment_b=((0.0, 0.0, 0.0),),
        collider_radii=(0.0,),
    ))
    assert _tail(args)[0] > 0.1


def test_spring_bone_vrm_box_collider_pushes_tail():
    args = _solve(_base_args(
        gravity_power=0.0,
        hit_radius=0.05,
        collided_by_groups=1,
        collider_types=(3,),
        collider_groups=(1,),
        collider_centers=((0.0, 0.0, 1.0),),
        collider_segment_a=((0.2, 0.0, 0.0),),
        collider_segment_b=((0.0, 0.2, 0.0),),
        collider_radii=(0.2,),
    ))
    assert _tail(args)[0] > 0.1


def test_spring_bone_vrm_rejects_bad_current_tail_shape():
    args = _base_args()
    args[0] = np.zeros((1, 2), dtype=np.float32)
    try:
        hotools_native.solve_spring_bone_vrm_cpp(*args)
    except ValueError as exc:
        assert "current_tails" in str(exc)
    else:
        raise AssertionError("bad current_tails shape should raise ValueError")
