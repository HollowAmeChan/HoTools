"""BoneCloth 写回层回归测试。

在 Blender 后台模式运行：
    blender --background --python test_bone_io.py

覆盖的关键回归点
─────────────────
1. depth=0 链首固定骨旋转写回
   故障：修复前 depth=0 骨骼的旋转始终保持动画状态，物理方向不反映到骨骼朝向，
         导致首端骨骼与子骨链在视觉上断裂（穿模）。
   验证：write_bone_rotations 后 depth=0 骨骼的 matrix_basis 应不再是 identity，
         且头部位置保持在动画位置（不被物理位移）。

2. depth≥1 可动骨正常写回
   验证：depth=1 骨骼的 matrix_basis 也非 identity，旋转方向符合物理粒子朝向。

3. restore_initial_pose 重置
   验证：调用后所有骨骼 matrix_basis 均重置为 identity。

4. 空 records 不崩溃
   验证：传入空 records 时写回函数静默返回，不抛异常。
"""

from __future__ import annotations

import sys
import traceback

import bpy
import mathutils
import numpy as np


# ---------------------------------------------------------------------------
# 被测函数导入
# ---------------------------------------------------------------------------

_BASE = "OmniNode.NodeTree.Function.physicsMC2BoneCloth"

from OmniNode.NodeTree.Function.physicsMC2BoneCloth.bone_io import (  # noqa: E402
    build_bone_write_records,
    write_bone_rotations,
    restore_initial_pose,
    _write_per_bone_independent,
)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

_EPSILON = 1e-4


def _mat_almost_identity(m: mathutils.Matrix) -> bool:
    """判断矩阵是否近似单位矩阵（旋转部分）。"""
    ident = mathutils.Matrix.Identity(4)
    for row in range(3):
        for col in range(3):
            if abs(m[row][col] - ident[row][col]) > _EPSILON:
                return False
    return True


def _rotation_angle_rad(m: mathutils.Matrix) -> float:
    """返回矩阵旋转部分对应的旋转角度（弧度）。"""
    q = m.to_quaternion()
    # |w| = cos(angle/2)，夹角 = 2*acos(|w|)
    import math
    return 2.0 * math.acos(max(-1.0, min(1.0, abs(float(q.w)))))


def _make_armature(
    chain_length: int = 2,
    bone_length: float = 1.0,
    root_name: str = "root_ctrl",
) -> bpy.types.Object:
    """
    创建极简骨架：
        root_ctrl（不进模拟，是所有链的父级）
            chain_0（depth=0 链首固定骨）
                chain_1（depth=1 可动骨）
                    ...
    返回骨架物体（处于 POSE 模式）。
    """
    mesh = bpy.data.meshes.new("_test_mesh")
    arm_data = bpy.data.armatures.new("_test_arm")
    arm_obj = bpy.data.objects.new("_test_arm_obj", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj

    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = arm_data.edit_bones

    # root_ctrl：共用父级，不进模拟
    root_eb = edit_bones.new(root_name)
    root_eb.head = (0.0, 0.0, -bone_length)
    root_eb.tail = (0.0, 0.0, 0.0)

    prev_eb = root_eb
    for i in range(chain_length):
        eb = edit_bones.new(f"chain_{i}")
        eb.head = (0.0, 0.0, float(i) * bone_length)
        eb.tail = (0.0, 0.0, float(i + 1) * bone_length)
        eb.parent = prev_eb
        eb.use_connect = i > 0  # chain_0 不 connect（方便独立测头位置）
        prev_eb = eb

    bpy.ops.object.mode_set(mode="POSE")
    return arm_obj


def _cleanup(arm_obj: bpy.types.Object) -> None:
    """删除测试用骨架，不影响后续测试。"""
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.data.objects.remove(arm_obj, do_unlink=True)


# ---------------------------------------------------------------------------
# 测试 1：depth=0 链首固定骨旋转写回
# ---------------------------------------------------------------------------

def test_depth0_rotation_writeback() -> None:
    """
    depth=0（链首固定骨）在 _write_per_bone_independent 路径下应写回旋转，
    且头部位置保持动画状态不被物理位移。

    构造场景：
        chain_0 (depth=0) 原始朝向 +Z（(0,0,0)->(0,0,1)）
        chain_1 (depth=1) 原始朝向 +Z（(0,0,1)->(0,0,2)）

    物理粒子位置：
        粒子 0 = (0, 0, 0)    chain_0 head，由 base_positions 固定，不被物理移动
        粒子 1 = (1, 0, 1)    chain_1 head 偏移至 (+X, 0, +Z) 方向
        粒子 2 = (2, 0, 2)    末端虚拟粒子

    期望：
        chain_0 旋转应跟随 chain_1 方向，不再是 identity
        chain_1 旋转应跟随末端粒子方向，不再是 identity
        chain_0 头部世界坐标仍在原点附近
    """
    arm_obj = _make_armature(chain_length=2)
    try:
        chains = [{"bones": ["chain_0", "chain_1"]}]
        records = build_bone_write_records(arm_obj, chains)

        assert len(records) == 2, f"期望 2 条记录，实际 {len(records)}"
        r0 = next(r for r in records if r["bone_name"] == "chain_0")
        r1 = next(r for r in records if r["bone_name"] == "chain_1")
        assert r0["depth"] == 0, f"chain_0 的 depth 应为 0，实际 {r0['depth']}"
        assert r1["depth"] == 1, f"chain_1 的 depth 应为 1，实际 {r1['depth']}"

        # 物理粒子坐标（世界空间）
        display_positions = np.array([
            [0.0, 0.0, 0.0],   # 粒子 0：chain_0 head，位置锁定
            [1.0, 0.0, 1.0],   # 粒子 1：chain_1 head，偏向 +X
            [2.0, 0.0, 2.0],   # 粒子 2：末端
        ], dtype=np.float32)

        # base_positions 只在 native 路径使用，Python 路径忽略此参数
        base_positions = np.array([
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 2.0],
        ], dtype=np.float32)

        write_runtime: dict = {}
        # 强制走 Python 退化路径，排除 native 不可用的干扰
        _write_per_bone_independent(
            arm_obj,
            records,
            display_positions,
            rotational_interpolation=1.0,
            write_runtime=write_runtime,
        )

        pose_chain_0 = arm_obj.pose.bones["chain_0"]
        pose_chain_1 = arm_obj.pose.bones["chain_1"]

        basis_0 = pose_chain_0.matrix_basis
        basis_1 = pose_chain_1.matrix_basis

        # ── 回归断言 1：chain_0 旋转必须非 identity ──────────────────────────
        # 修复前：depth=0 不进入写回循环，旋转永远保持 identity。
        # 修复后：depth=0 链首固定骨参与 _write_per_bone_independent，旋转跟随子骨方向。
        angle_0 = _rotation_angle_rad(basis_0)
        assert angle_0 > 0.05, (  # > ~3 度说明旋转发生了
            f"[回归] depth=0 chain_0 的旋转角度 {angle_0:.4f} rad ≈ 0，"
            "说明首骨写回未生效——这是已修复的穿模 bug 复现！"
        )

        # ── 断言 2：chain_1 旋转也非 identity ────────────────────────────────
        angle_1 = _rotation_angle_rad(basis_1)
        assert angle_1 > 0.05, (
            f"depth=1 chain_1 的旋转角度 {angle_1:.4f} rad ≈ 0，写回异常"
        )

        # ── 断言 3：chain_0 头部世界坐标未被物理移动 ─────────────────────────
        head_world = (arm_obj.matrix_world @ pose_chain_0.head).to_3d()
        assert head_world.length < 0.2, (
            f"depth=0 chain_0 头部被物理移动至 {head_world}，"
            "depth=0 骨骼头部必须保持动画位置"
        )

        print("PASS test_depth0_rotation_writeback")
    finally:
        _cleanup(arm_obj)


# ---------------------------------------------------------------------------
# 测试 2：restore_initial_pose 重置所有骨骼到 identity
# ---------------------------------------------------------------------------

def test_restore_initial_pose() -> None:
    """restore_initial_pose 应将 records 中所有骨骼的 matrix_basis 重置为 identity。"""
    arm_obj = _make_armature(chain_length=3)
    try:
        chains = [{"bones": ["chain_0", "chain_1", "chain_2"]}]
        records = build_bone_write_records(arm_obj, chains)

        # 先手动把骨骼旋转改掉
        rot_quat = mathutils.Quaternion((0.707, 0.707, 0.0, 0.0))
        for r in records:
            r["pose_bone"].matrix_basis = rot_quat.to_matrix().to_4x4()

        # 确认已被改变
        for r in records:
            angle = _rotation_angle_rad(r["pose_bone"].matrix_basis)
            assert angle > 0.05, f"{r['bone_name']} 预设旋转没生效"

        restore_initial_pose(records)

        for r in records:
            basis = r["pose_bone"].matrix_basis
            assert _mat_almost_identity(basis), (
                f"{r['bone_name']} 在 restore_initial_pose 后 matrix_basis 不是 identity：{basis}"
            )

        print("PASS test_restore_initial_pose")
    finally:
        _cleanup(arm_obj)


# ---------------------------------------------------------------------------
# 测试 3：空 records 不崩溃
# ---------------------------------------------------------------------------

def test_empty_records_no_crash() -> None:
    """write_bone_rotations 和 restore_initial_pose 传入空 records 时静默返回。"""
    arm_obj = _make_armature(chain_length=1)
    try:
        display_positions = np.zeros((1, 3), dtype=np.float32)
        # 不应抛异常
        write_bone_rotations(
            arm_obj,
            chains=[],
            records=[],
            display_positions=display_positions,
            base_positions=display_positions,
            rotational_interpolation=1.0,
            blend_weight=1.0,
        )
        restore_initial_pose([])
        print("PASS test_empty_records_no_crash")
    finally:
        _cleanup(arm_obj)


# ---------------------------------------------------------------------------
# 测试 4：build_bone_write_records 记录结构完整性
# ---------------------------------------------------------------------------

def test_build_bone_write_records_structure() -> None:
    """
    build_bone_write_records 产生的记录应满足：
      - 每条记录有 bone_name / depth / particle_index / child_particle / parent_particle
      - depth=0 的 parent_particle == -1
      - depth>0 的 parent_particle >= 0
      - child_particle 指向链中的下一个粒子（最后一个为 -1）
    """
    arm_obj = _make_armature(chain_length=3)
    try:
        chains = [{"bones": ["chain_0", "chain_1", "chain_2"]}]
        records = build_bone_write_records(arm_obj, chains)

        assert len(records) == 3

        depths = [r["depth"] for r in records]
        assert depths == [0, 1, 2], f"深度序列应为 [0,1,2]，实际 {depths}"

        # depth=0 无父粒子
        assert records[0]["parent_particle"] == -1, "depth=0 的 parent_particle 应为 -1"
        # 中间骨骼有父有子
        assert records[1]["parent_particle"] == 0, f"depth=1 parent_particle 应为 0，实际 {records[1]['parent_particle']}"
        assert records[1]["child_particle"] == 2, f"depth=1 child_particle 应为 2，实际 {records[1]['child_particle']}"
        # 末尾无子粒子
        assert records[2]["child_particle"] == -1, "最后一个骨骼 child_particle 应为 -1"

        # 每条记录必须包含必要字段
        required_fields = {
            "bone_name", "pose_bone", "depth", "particle_index",
            "child_particle", "parent_particle", "bone_rest", "bone_rest_inv",
        }
        for r in records:
            missing = required_fields - set(r.keys())
            assert not missing, f"{r['bone_name']} 缺少字段：{missing}"

        print("PASS test_build_bone_write_records_structure")
    finally:
        _cleanup(arm_obj)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def run_all() -> bool:
    tests = [
        test_build_bone_write_records_structure,
        test_depth0_rotation_writeback,
        test_restore_initial_pose,
        test_empty_records_no_crash,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}", file=sys.stderr)
            traceback.print_exc()
            failed += 1
    print(f"\n[test_bone_io] {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
