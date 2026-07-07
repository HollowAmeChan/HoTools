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


def test_spring_bone_vrm_capsule_collider_pushes_tail():
    args = _solve(_base_args(
        gravity_power=0.0,
        hit_radius=0.2,
        collided_by_groups=1,
        collider_types=(1,),
        collider_groups=(1,),
        collider_centers=((0.1, 0.0, 1.0),),
        collider_segment_a=((0.1, -0.5, 1.0),),
        collider_segment_b=((0.1, 0.5, 1.0),),
        collider_radii=(0.2,),
    ))
    tail = _tail(args)
    assert tail[0] < -0.1
    assert abs(float(np.linalg.norm(tail)) - 1.0) < 1.0e-5


def test_spring_bone_vrm_group_mask_skips_unmatched_collider():
    args = _solve(_base_args(
        gravity_power=0.0,
        hit_radius=0.2,
        collided_by_groups=1,
        collider_types=(0,),
        collider_groups=(2,),
        collider_centers=((0.0, 0.0, 1.0),),
        collider_segment_a=((0.0, 0.0, 0.0),),
        collider_segment_b=((0.0, 0.0, 0.0),),
        collider_radii=(0.35,),
    ))
    assert np.allclose(_tail(args), np.asarray((0.0, 0.0, 1.0), dtype=np.float32))


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


# ─────────────────────────────────────────────────────────────────────────────
# Context API（dual-call）smoke tests
# ─────────────────────────────────────────────────────────────────────────────

_HAS_CONTEXT_API = hasattr(hotools_native, "spring_vrm_create_context")


def _skip_if_no_context_api():
    if not _HAS_CONTEXT_API:
        raise Exception("SKIP: spring_vrm_create_context not available in this build")

def _context_from_base() -> object:
    """用 _base_args() 里的静态数据创建一个 SpringVrmContext capsule。"""
    a = _base_args()
    # static: lengths, init_axis_local, init_axis_parent, init_rotations, init_scales,
    #         parent_indices, pinned, use_connect  → base_args 里的索引 9-16
    return hotools_native.spring_vrm_create_context(
        1,          # schema
        1,          # bone_count
        a[9],       # lengths      (N,)
        a[10].ravel(),  # init_axis_local  (N*3,)
        a[11].ravel(),  # init_axis_parent
        a[12].ravel(),  # init_rotations   (N*4,)
        a[13].ravel(),  # init_scales      (N*3,)
        a[14],          # parent_indices
        a[15],          # pinned
        a[16],          # use_connect
    )


def _update_dynamic_from_base(ctx, args=None):
    a = args if args is not None else _base_args()
    zero3  = np.zeros(3,  dtype=np.float32)
    ident  = _identity_matrix()
    id_quat = np.asarray((0., 0., 0., 1.), dtype=np.float32)
    hotools_native.spring_vrm_update_dynamic(
        ctx,
        a[4].ravel(),   # current_heads
        a[5].ravel(),   # current_pose_matrices
        a[6].ravel(),   # current_pose_quaternions
        a[7].ravel(),   # parent_pose_quaternions
        a[8].ravel(),   # current_pose_tails
        ident,          # armature_world
        ident,          # armature_world_inv
        id_quat,        # root_quaternion
        zero3,          # root_tail_world
        np.asarray((1., 0., 0.), dtype=np.float32),  # gravity_dir
        a[22],          # hit_radii
        a[23],          # collided_by_groups
        np.empty(0, dtype=np.int32),                 # collider_types
        np.empty(0, dtype=np.int32),                 # collider_groups
        np.empty(0, dtype=np.float32),               # collider_centers
        np.empty(0, dtype=np.float32),               # collider_segment_a
        np.empty(0, dtype=np.float32),               # collider_segment_b
        np.empty(0, dtype=np.float32),               # collider_radii
    )


def test_context_api_create_and_free():
    _skip_if_no_context_api()
    """create_context 返回有效 capsule，多次 free 不崩溃。"""
    ctx = _context_from_base()
    assert ctx is not None
    # capsule 本身没有 Python 释放 API（析构器自动调用），测通过意味着不崩溃


def test_context_api_gravity_projects_to_bone_length():
    _skip_if_no_context_api()
    """context API 路径下重力效果与旧 35 参数路径一致。"""
    ctx = _context_from_base()
    _update_dynamic_from_base(ctx)
    hotools_native.spring_vrm_step(ctx, 1.0 / 60.0, 1, 0.0, 0.0, 9.8)

    out_mat  = np.zeros(16, dtype=np.float32)
    out_quat = np.zeros(4,  dtype=np.float32)
    hotools_native.spring_vrm_read_results(ctx, out_mat, out_quat)

    # target_matrix 应不再是单位矩阵（重力使骨骼偏转）
    identity = np.eye(4, dtype=np.float32).ravel()
    assert not np.allclose(out_mat, identity, atol=1e-4), \
        "经过一帧重力作用后 target_matrix 应偏离单位矩阵"


def test_context_api_reset_state_restores_pose_tail():
    _skip_if_no_context_api()
    """reset_state 应把 current/prev tails 置回 pose tail，使骨骼从当前 pose 重新开始。"""
    ctx = _context_from_base()

    # 先跑若干帧让骨骼偏移
    _update_dynamic_from_base(ctx)
    for _ in range(10):
        hotools_native.spring_vrm_step(ctx, 1.0 / 60.0, 1, 0.0, 0.0, 9.8)

    # reset：current_pose_tails 是 (0,0,1)，reset 后下一帧结果应接近 pose tail
    _update_dynamic_from_base(ctx)
    hotools_native.spring_vrm_reset_state(ctx)
    hotools_native.spring_vrm_step(ctx, 1.0 / 60.0, 1, 0.0, 0.0, 0.0)  # gravity=0，无扰动

    out_mat  = np.zeros(16, dtype=np.float32)
    out_quat = np.zeros(4,  dtype=np.float32)
    hotools_native.spring_vrm_read_results(ctx, out_mat, out_quat)

    # gravity_power=0 且 reset 后，骨骼应在 pose 方向附近（矩阵接近 identity）
    identity = np.eye(4, dtype=np.float32).ravel()
    assert np.allclose(out_mat, identity, atol=0.05), \
        f"reset 后 gravity=0 一帧，target_matrix 应接近 identity，实际：{out_mat}"


def test_context_api_capsule_collider():
    _skip_if_no_context_api()
    """capsule collider 推动 tail 与旧路径行为一致（不为零偏移）。"""
    ctx = _context_from_base()
    # capsule collider：轴线在 (0,0,0)→(0,0,2)，半径 0.8
    seg_a = np.asarray([[0., 0., 0.]], dtype=np.float32)
    seg_b = np.asarray([[0., 0., 2.]], dtype=np.float32)
    centers = (seg_a + seg_b) * 0.5

    a = _base_args()
    zero3  = np.zeros(3, dtype=np.float32)
    ident  = _identity_matrix()
    id_quat = np.asarray((0., 0., 0., 1.), dtype=np.float32)
    hotools_native.spring_vrm_update_dynamic(
        ctx,
        a[4].ravel(), a[5].ravel(), a[6].ravel(), a[7].ravel(), a[8].ravel(),
        ident, ident, id_quat, zero3,
        np.zeros(3, dtype=np.float32),  # gravity_dir=0，不施重力
        np.asarray((0.01,), dtype=np.float32),   # hit_radii
        np.asarray((1,),    dtype=np.int32),      # collided_by_groups（组1）
        np.asarray([1],  dtype=np.int32),         # collider_types: CAPSULE=1
        np.asarray([1],  dtype=np.int32),         # collider_groups: 组1
        centers.ravel(),
        seg_a.ravel(),
        seg_b.ravel(),
        np.asarray([0.8], dtype=np.float32),      # collider_radii
    )
    hotools_native.spring_vrm_step(ctx, 1.0 / 60.0, 1, 0.0, 0.0, 0.0)

    out_mat  = np.zeros(16, dtype=np.float32)
    out_quat = np.zeros(4,  dtype=np.float32)
    hotools_native.spring_vrm_read_results(ctx, out_mat, out_quat)

    # tail 的骨骼应被碰撞体推开，矩阵应偏离 identity
    identity = np.eye(4, dtype=np.float32).ravel()
    assert not np.allclose(out_mat, identity, atol=1e-4), \
        "capsule collider 应推动 tail 偏离初始方向"
