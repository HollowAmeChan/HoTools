"""Native VRM SpringBone solver smoke tests."""

from __future__ import annotations

import gc
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


def test_legacy_spring_vrm_entrypoint_is_removed():
    assert not hasattr(hotools_native, "solve_spring_bone_vrm_cpp")


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


# ─────────────────────────────────────────────────────────────────────────────
# Context API smoke tests
# ─────────────────────────────────────────────────────────────────────────────

_HAS_CONTEXT_API = hasattr(hotools_native, "spring_vrm_create_context")


def _skip_if_no_context_api():
    if not _HAS_CONTEXT_API:
        raise AssertionError("spring_vrm_create_context not available in this build")

def _context_from_args(a) -> object:
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


def _context_from_base() -> object:
    """用 _base_args() 里的静态数据创建一个 SpringVrmContext capsule。"""
    return _context_from_args(_base_args())


def _update_context_from_args(ctx, a):
    hotools_native.spring_vrm_update_dynamic(
        ctx,
        a[4].ravel(),   # current_heads
        a[5].ravel(),   # current_pose_matrices
        a[6].ravel(),   # current_pose_quaternions
        a[7].ravel(),   # parent_pose_quaternions
        a[8].ravel(),   # current_pose_tails
        a[19],          # armature_world
        a[20],          # armature_world_inv
        a[17],          # root_quaternion
        a[18],          # root_tail_world
        a[21],          # gravity_dir
        a[22],          # hit_radii
        a[23],          # collided_by_groups
        a[24],          # collider_types
        a[25],          # collider_groups
        a[26].ravel(),  # collider_centers
        a[27].ravel(),  # collider_segment_a
        a[28].ravel(),  # collider_segment_b
        a[29],          # collider_radii
    )


def _update_dynamic_from_base(ctx, args=None):
    _update_context_from_args(ctx, args if args is not None else _base_args())


def _read_context_state(ctx, bone_count=1, collider_count=0):
    matrices = np.zeros(bone_count * 16, dtype=np.float32)
    quaternions = np.zeros(bone_count * 4, dtype=np.float32)
    hotools_native.spring_vrm_read_results(ctx, matrices, quaternions)

    heads = np.zeros(bone_count * 3, dtype=np.float32)
    tails = np.zeros(bone_count * 3, dtype=np.float32)
    prev_tails = np.zeros(bone_count * 3, dtype=np.float32)
    pose_tails = np.zeros(bone_count * 3, dtype=np.float32)
    hit_radii = np.zeros(bone_count, dtype=np.float32)
    masks = np.zeros(bone_count, dtype=np.int32)
    collider_types = np.zeros(collider_count, dtype=np.int32)
    collider_groups = np.zeros(collider_count, dtype=np.int32)
    collider_centers = np.zeros(collider_count * 3, dtype=np.float32)
    collider_a = np.zeros(collider_count * 3, dtype=np.float32)
    collider_b = np.zeros(collider_count * 3, dtype=np.float32)
    collider_radii = np.zeros(collider_count, dtype=np.float32)
    hotools_native.spring_vrm_read_debug(
        ctx,
        heads, tails, prev_tails, pose_tails, hit_radii, masks,
        collider_types, collider_groups, collider_centers,
        collider_a, collider_b, collider_radii,
    )
    return matrices, quaternions, tails, prev_tails


def test_context_api_create_and_free():
    _skip_if_no_context_api()
    assert hasattr(hotools_native, "free_spring_vrm_context")
    ctx = _context_from_base()
    assert ctx is not None
    hotools_native.free_spring_vrm_context(ctx)
    hotools_native.free_spring_vrm_context(ctx)
    try:
        hotools_native.spring_vrm_reset_state(ctx)
    except ValueError:
        pass
    else:
        raise AssertionError("freed context must reject subsequent API calls")


def test_context_api_gc_destructor_and_recreate():
    _skip_if_no_context_api()
    for _ in range(128):
        ctx = _context_from_base()
        assert ctx is not None
        ctx = None
    gc.collect()

    ctx = _context_from_base()
    try:
        _update_dynamic_from_base(ctx)
        hotools_native.spring_vrm_reset_state(ctx)
        hotools_native.spring_vrm_step(ctx, 1.0 / 60.0, 1, 0.0, 0.0, 0.0)
    finally:
        hotools_native.free_spring_vrm_context(ctx)


def test_context_api_rejects_bad_static_buffer_length():
    _skip_if_no_context_api()
    a = _base_args()
    try:
        hotools_native.spring_vrm_create_context(
            1, 1,
            np.empty(0, dtype=np.float32),
            a[10].ravel(), a[11].ravel(), a[12].ravel(), a[13].ravel(),
            a[14], a[15], a[16],
        )
    except ValueError as exc:
        assert "lengths" in str(exc)
    else:
        raise AssertionError("short context static buffer should raise ValueError")


def test_context_api_rejects_bad_dynamic_buffer_length():
    _skip_if_no_context_api()
    ctx = _context_from_base()
    a = _base_args()
    ident = _identity_matrix()
    zero3 = np.zeros(3, dtype=np.float32)
    id_quat = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    try:
        hotools_native.spring_vrm_update_dynamic(
            ctx,
            np.zeros(2, dtype=np.float32),
            a[5].ravel(), a[6].ravel(), a[7].ravel(), a[8].ravel(),
            ident, ident, id_quat, zero3, zero3, a[22], a[23],
            np.empty(0, dtype=np.int32), np.empty(0, dtype=np.int32),
            np.empty(0, dtype=np.float32), np.empty(0, dtype=np.float32),
            np.empty(0, dtype=np.float32), np.empty(0, dtype=np.float32),
        )
    except ValueError as exc:
        assert "current_heads" in str(exc)
    else:
        raise AssertionError("short context dynamic buffer should raise ValueError")


def test_context_api_rejects_bad_collision_mask_dtype():
    _skip_if_no_context_api()
    ctx = _context_from_base()
    args = _base_args()
    args[23] = np.asarray((1.0,), dtype=np.float32)
    try:
        try:
            _update_context_from_args(ctx, args)
        except (TypeError, ValueError) as exc:
            assert "collided_by_groups" in str(exc)
        else:
            raise AssertionError("float32 collision mask should raise ValueError")
    finally:
        hotools_native.free_spring_vrm_context(ctx)


def test_context_api_rejects_mismatched_collider_arrays():
    _skip_if_no_context_api()
    ctx = _context_from_base()
    args = _base_args(
        collider_types=(0,),
        collider_groups=(),
        collider_centers=((0.0, 0.0, 0.0),),
        collider_segment_a=((0.0, 0.0, 0.0),),
        collider_segment_b=((0.0, 0.0, 0.0),),
        collider_radii=(1.0,),
    )
    try:
        try:
            _update_context_from_args(ctx, args)
        except ValueError as exc:
            assert "collider_groups" in str(exc)
        else:
            raise AssertionError("mismatched collider arrays should raise ValueError")
    finally:
        hotools_native.free_spring_vrm_context(ctx)


def test_context_api_rejects_bad_result_buffer_length():
    _skip_if_no_context_api()
    ctx = _context_from_base()
    try:
        hotools_native.spring_vrm_read_results(
            ctx,
            np.zeros(15, dtype=np.float32),
            np.zeros(4, dtype=np.float32),
        )
    except ValueError as exc:
        assert "out_matrices" in str(exc)
    else:
        raise AssertionError("short context result buffer should raise ValueError")


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


def test_context_api_preserves_full_current_head_vector():
    _skip_if_no_context_api()
    """update_dynamic must copy all XYZ head components, not just one float per bone."""
    ctx = _context_from_base()
    args = _base_args(gravity_power=0.0)
    args[4] = np.asarray(((1.0, 2.0, 3.0),), dtype=np.float32)
    args[8] = np.asarray(((1.0, 2.0, 4.0),), dtype=np.float32)
    args[0] = args[8].copy()
    args[1] = args[8].copy()

    _update_dynamic_from_base(ctx, args)
    hotools_native.spring_vrm_reset_state(ctx)
    hotools_native.spring_vrm_step(ctx, 1.0 / 60.0, 1, 0.0, 0.0, 0.0)

    out_mat = np.zeros(16, dtype=np.float32)
    out_quat = np.zeros(4, dtype=np.float32)
    hotools_native.spring_vrm_read_results(ctx, out_mat, out_quat)

    translation = out_mat.reshape((4, 4))[:3, 3]
    assert np.allclose(translation, (1.0, 2.0, 3.0), atol=1.0e-6), \
        f"context update_dynamic 应保留完整 head XYZ，实际 translation={translation}"


def _run_context_collider(
    collider_type,
    *,
    center,
    segment_a,
    segment_b,
    radius,
    collider_group=1,
    collided_by_groups=1,
):
    args = _base_args(
        gravity_dir=(0.0, 0.0, 0.0),
        hit_radius=0.01,
        collided_by_groups=collided_by_groups,
        collider_types=(collider_type,),
        collider_groups=(collider_group,),
        collider_centers=(center,),
        collider_segment_a=(segment_a,),
        collider_segment_b=(segment_b,),
        collider_radii=(radius,),
        gravity_power=0.0,
    )
    ctx = _context_from_args(args)
    try:
        _update_context_from_args(ctx, args)
        hotools_native.spring_vrm_reset_state(ctx)
        hotools_native.spring_vrm_step(ctx, 1.0 / 60.0, 1, 0.0, 0.0, 0.0)
        matrices, _, tails, _ = _read_context_state(ctx, collider_count=1)
        return matrices.reshape((-1, 4, 4))[0], tails.reshape((-1, 3))[0]
    finally:
        hotools_native.free_spring_vrm_context(ctx)


def _assert_collider_deflects(matrix, tail, label):
    assert np.isfinite(matrix).all(), f"{label} matrix contains non-finite values"
    assert np.isfinite(tail).all(), f"{label} tail contains non-finite values"
    assert not np.allclose(matrix, np.eye(4, dtype=np.float32), atol=1.0e-4), (
        f"{label} should deflect the SpringBone tail"
    )


def test_context_api_sphere_collider():
    _skip_if_no_context_api()
    matrix, tail = _run_context_collider(
        0,
        center=(0.5, 0.0, 0.8),
        segment_a=(0.5, 0.0, 0.8),
        segment_b=(0.5, 0.0, 0.8),
        radius=0.8,
    )
    _assert_collider_deflects(matrix, tail, "SPHERE")


def test_context_api_capsule_collider():
    _skip_if_no_context_api()
    matrix, tail = _run_context_collider(
        1,
        center=(0.5, 0.0, 0.8),
        segment_a=(0.5, 0.0, 0.4),
        segment_b=(0.5, 0.0, 1.2),
        radius=0.6,
    )
    _assert_collider_deflects(matrix, tail, "CAPSULE")


def test_context_api_plane_collider():
    _skip_if_no_context_api()
    matrix, tail = _run_context_collider(
        2,
        center=(0.2, 0.0, 0.0),
        segment_a=(1.0, 0.0, 0.0),
        segment_b=(0.0, 0.0, 0.0),
        radius=0.0,
    )
    _assert_collider_deflects(matrix, tail, "PLANE")


def test_context_api_box_collider():
    _skip_if_no_context_api()
    matrix, tail = _run_context_collider(
        3,
        center=(0.2, 0.0, 1.0),
        segment_a=(0.4, 0.0, 0.0),
        segment_b=(0.0, 0.4, 0.0),
        radius=0.4,
    )
    _assert_collider_deflects(matrix, tail, "BOX")


def test_context_api_collision_group_mask():
    _skip_if_no_context_api()
    blocked_matrix, blocked_tail = _run_context_collider(
        1,
        center=(0.5, 0.0, 0.8),
        segment_a=(0.5, 0.0, 0.4),
        segment_b=(0.5, 0.0, 1.2),
        radius=0.6,
        collider_group=2,
        collided_by_groups=1,
    )
    allowed_matrix, allowed_tail = _run_context_collider(
        1,
        center=(0.5, 0.0, 0.8),
        segment_a=(0.5, 0.0, 0.4),
        segment_b=(0.5, 0.0, 1.2),
        radius=0.6,
        collider_group=2,
        collided_by_groups=2,
    )

    assert np.allclose(blocked_matrix, np.eye(4, dtype=np.float32), atol=1.0e-6)
    assert np.allclose(blocked_tail, (0.0, 0.0, 1.0), atol=1.0e-6)
    _assert_collider_deflects(allowed_matrix, allowed_tail, "group-2 CAPSULE")


def test_context_api_zero_length_stays_finite():
    _skip_if_no_context_api()
    args = _base_args(gravity_dir=(1.0, 0.0, 0.0), gravity_power=9.8)
    args[9][0] = 0.0
    args[4][0] = (0.0, 0.0, 0.0)
    args[8][0] = (0.0, 0.0, 0.0)
    args[0][0] = (0.0, 0.0, 0.0)
    args[1][0] = (0.0, 0.0, 0.0)

    ctx = _context_from_args(args)
    _update_context_from_args(ctx, args)
    hotools_native.spring_vrm_reset_state(ctx)
    hotools_native.spring_vrm_step(ctx, 1.0 / 60.0, 1, 0.0, 0.0, 9.8)
    matrices, quaternions, tails, prev_tails = _read_context_state(ctx)

    assert np.isfinite(matrices).all()
    assert np.isfinite(quaternions).all()
    assert np.isfinite(tails).all()
    assert np.isfinite(prev_tails).all()
