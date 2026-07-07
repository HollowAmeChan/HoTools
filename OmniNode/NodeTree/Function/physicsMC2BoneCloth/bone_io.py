"""BoneCloth 骨骼姿态写回。

把 solver 输出的 display_positions（世界空间粒子位置）转回骨骼旋转，写入 PoseBone.matrix_basis。

核心算法：MC2 SimulationPostProxyMeshUpdateLine（VirtualMeshManager.cs L790）
  C++ 实现在 _native/src/mc2_bonecloth_io.cpp，通过 hotools_native.solve_mc2_bonecloth_io 调用。
  Python 退化路径在 _write_per_bone_independent，作为 native 不可用时的兜底。

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 写回层的骨骼角色划分（与 bone_build.py 中的深度定义完全对应）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# root_bone（节点输入的共用父级）
#   不在 records 里，写回层对其完全无感知，位置和旋转始终保持动画状态。
#
# depth = 0（链首固定骨，MC2_ATTR_FIXED）
#   位置由 solver 每帧还原到 base_positions（动画姿态），写回层尊重此约束：
#     head_pose = 当前动画骨头位置，不走链式传播
#     （若走链式传播，其父骨 root_bone 不在 parent_pose_matrices 中，
#      会错误回退到 root_bone 原点，导致所有链头吸到同一点）
#   旋转由 C++ 按 root_rotation 参数（默认 1.0）计算后写回，
#   使链首骨能跟随子骨链方向旋转，而不是永远朝向动画方向。
#
# depth ≥ 1（可动骨，MC2_ATTR_MOVE）
#   位置和旋转均由物理驱动。
#   head_pose 由父骨矩阵链式传播（父骨尾 = 子骨头），保证骨链视觉连续。
#   旋转由 rotational_interpolation 参数控制与动画的混合比例。
#
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

写回路径与 SpringBone 一致：
  - connected 子骨通过 matrix_basis 写回，不直接改 PoseBone.matrix
  - 写回顺序按深度升序（父先于子），避免子骨参考旧父矩阵
  - 只改方向（旋转），保留 base pose 的缩放，不改 loc
"""

from __future__ import annotations

import bpy
import mathutils
import numpy as np

EPSILON = 1e-8

# ---------------------------------------------------------------------------
# Native 模块加载（可选，不可用时退化到 Python 路径）
# ---------------------------------------------------------------------------
try:
    from HotoolsPackage import hotools_native as _native  # type: ignore[import]
    _HAS_NATIVE = hasattr(_native, "solve_mc2_bonecloth_io")
except Exception:
    _native = None
    _HAS_NATIVE = False


# ---------------------------------------------------------------------------
# 写回记录构建
# ---------------------------------------------------------------------------

def build_bone_write_records(
    armature_obj: bpy.types.Object,
    chains: list,
) -> list:
    """为每根参与模拟的骨骼建立写回记录。"""
    records: list = []
    pose_bones = armature_obj.pose.bones
    pose_index_by_name = {pb.name: idx for idx, pb in enumerate(pose_bones)}

    particle_cursor = 0
    for chain in chains:
        bone_names = chain.get("bones") or []
        chain_particle_start = particle_cursor
        for local_index, bone_name in enumerate(bone_names):
            particle_index = chain_particle_start + local_index
            pose_bone = pose_bones.get(bone_name)
            if pose_bone is not None:
                parent = getattr(pose_bone, "parent", None)
                bone_rest = pose_bone.bone.matrix_local.copy()
                child_particle = (
                    chain_particle_start + local_index + 1
                    if local_index + 1 < len(bone_names)
                    else -1
                )
                parent_particle = (
                    chain_particle_start + local_index - 1
                    if local_index > 0
                    else -1
                )
                records.append({
                    "bone_name": bone_name,
                    "pose_bone": pose_bone,
                    "pose_index": int(pose_index_by_name.get(bone_name, -1)),
                    "particle_index": int(particle_index),
                    "child_particle": int(child_particle),
                    "parent_particle": int(parent_particle),
                    "depth": int(local_index),
                    "parent": parent,
                    "parent_name": parent.name if parent is not None else "",
                    "bone_rest": bone_rest,
                    "bone_rest_inv": bone_rest.inverted(),
                    "parent_rest_inv": (
                        parent.bone.matrix_local.inverted() if parent is not None else None
                    ),
                    # init_scale 保留供调试查看，写回时不使用（物理写回强制 scale=(1,1,1)，见 _matrix_basis_from_target）
                    "init_scale": pose_bone.matrix.to_scale().copy(),
                })
        particle_cursor += len(bone_names)
    return records


# ---------------------------------------------------------------------------
# 矩阵工具
# ---------------------------------------------------------------------------

def _matrix_basis_from_target(record, target_matrix, parent_pose_matrices):
    """把骨架空间目标矩阵转换为 matrix_basis（父骨本地空间），强制不写缩放。

    设计原则（与 MC2 Unity 对齐）：
    ─ MC2 SimulationPostProxyMeshUpdateLine 只修改 localRotation，不触碰 localScale。
      物理写回只允许改旋转，禁止改缩放。若 matrix_basis 带非单位缩放，会逐帧累积，
      导致骨骼视觉拉长 → 末端漂移 → 最终爆炸。
    ─ 父骨矩阵去掉缩放分量再参与计算，防止父骨的缩放传播到子骨 matrix_basis。
    ─ Connected 骨骼（头锁父尾）：Blender 自动忽略 matrix_basis 的 Translation 部分，
      只有 Rotation 生效——与 MC2 仅改旋转的行为完全一致，无需打断骨骼。
    ─ Disconnected 骨骼：Translation 也生效，由调用方传入正确的 target_matrix.translation。
    """
    parent = record.get("parent")
    if parent is None or record.get("parent_rest_inv") is None:
        raw = record["bone_rest_inv"] @ target_matrix
    else:
        parent_name = record.get("parent_name") or ""
        parent_matrix = parent_pose_matrices.get(parent_name)
        if parent_matrix is None:
            parent_matrix = parent.matrix
        # 剔除父骨缩放，防止非单位 scale 传播进子骨 matrix_basis
        par_loc, par_rot, _par_scale = parent_matrix.decompose()
        parent_matrix_no_scale = mathutils.Matrix.LocRotScale(par_loc, par_rot, mathutils.Vector((1.0, 1.0, 1.0)))
        parent_space = parent_matrix_no_scale @ record["parent_rest_inv"] @ record["bone_rest"]
        raw = parent_space.inverted() @ target_matrix
    # 强制 scale=(1,1,1)：物理写回只允许写旋转，永远不写缩放
    loc, rot, _scale = raw.decompose()
    return mathutils.Matrix.LocRotScale(loc, rot, mathutils.Vector((1.0, 1.0, 1.0)))


def _pack_matrix_into(basis_values, offset, matrix):
    basis_values[offset + 0]  = float(matrix[0][0])
    basis_values[offset + 1]  = float(matrix[1][0])
    basis_values[offset + 2]  = float(matrix[2][0])
    basis_values[offset + 3]  = float(matrix[3][0])
    basis_values[offset + 4]  = float(matrix[0][1])
    basis_values[offset + 5]  = float(matrix[1][1])
    basis_values[offset + 6]  = float(matrix[2][1])
    basis_values[offset + 7]  = float(matrix[3][1])
    basis_values[offset + 8]  = float(matrix[0][2])
    basis_values[offset + 9]  = float(matrix[1][2])
    basis_values[offset + 10] = float(matrix[2][2])
    basis_values[offset + 11] = float(matrix[3][2])
    basis_values[offset + 12] = float(matrix[0][3])
    basis_values[offset + 13] = float(matrix[1][3])
    basis_values[offset + 14] = float(matrix[2][3])
    basis_values[offset + 15] = float(matrix[3][3])


# ---------------------------------------------------------------------------
# 主写回入口
# ---------------------------------------------------------------------------

def write_bone_rotations(
    armature_obj,
    chains,
    records,
    display_positions,
    base_positions,
    rotational_interpolation,
    blend_weight,
    write_runtime=None,
    step_basic_rotations=None,
    vertex_local_positions=None,
    vertex_local_rotations=None,
    parent_indices=None,
    baseline_start=None,
    baseline_count=None,
    baseline_data=None,
    attributes=None,
    anime_ratio=0.0,
    root_rotation=0.5,
):
    """把 display_positions 写回骨骼旋转（matrix_basis 批量写）。

    有 baseline 数组且 native 可用时走 C++ SimulationPostProxyMeshUpdateLine 链式路径；
    否则退化为每骨独立计算路径。
    """
    if not records:
        return

    use_baseline = (
        _HAS_NATIVE
        and step_basic_rotations is not None
        and vertex_local_positions is not None
        and vertex_local_rotations is not None
        and parent_indices is not None
        and baseline_start is not None
        and baseline_count is not None
        and baseline_data is not None
        and attributes is not None
        and len(baseline_data) > 0
    )

    if use_baseline:
        # 初始化输出数组为 step_basic_rotations（C++ 会原地修改）
        world_rotations = import_numpy().ascontiguousarray(step_basic_rotations, dtype="float32").copy()
        try:
            _native.solve_mc2_bonecloth_io(
                world_rotations,
                import_numpy().ascontiguousarray(display_positions,      dtype="float32"),
                import_numpy().ascontiguousarray(base_positions,         dtype="float32"),
                import_numpy().ascontiguousarray(step_basic_rotations,   dtype="float32"),
                import_numpy().ascontiguousarray(vertex_local_positions, dtype="float32"),
                import_numpy().ascontiguousarray(vertex_local_rotations, dtype="float32"),
                import_numpy().ascontiguousarray(parent_indices,         dtype="int32"),
                import_numpy().ascontiguousarray(baseline_start,         dtype="int32"),
                import_numpy().ascontiguousarray(baseline_count,         dtype="int32"),
                import_numpy().ascontiguousarray(baseline_data,          dtype="int32"),
                import_numpy().ascontiguousarray(attributes,             dtype="uint8"),
                float(rotational_interpolation),
                float(blend_weight),
                float(anime_ratio),
                float(root_rotation),
            )
            _write_from_world_rotations(armature_obj, records, world_rotations, write_runtime)
            return
        except Exception:
            pass  # 退化到独立计算路径

    _write_per_bone_independent(
        armature_obj, records, display_positions, rotational_interpolation, write_runtime
    )


def import_numpy():
    return np


# ---------------------------------------------------------------------------
# 链式路径写回
# ---------------------------------------------------------------------------

def _write_from_world_rotations(armature_obj, records, world_rotations, write_runtime):
    """MC2 世界旋转 → 骨骼方向 → matrix_basis（链式路径）。

    设计原则（与 MC2 SimulationPostProxyMeshUpdateLine 对齐）：

    【只改旋转，不改缩放】
      MC2 Unity 只修改 Transform.localRotation，localScale 从不触碰。
      本函数构造 target_matrix 时强制 scale=(1,1,1)；
      _matrix_basis_from_target 写入前再次剔除缩放，双重保险。
      若允许缩放进入 matrix_basis，每帧累积后骨骼视觉被拉长，最终爆炸。

    【head部位置：父链传播，不用粒子坐标】
      每根骨骼的 head_pose 由父骨矩阵链式推算（父骨尾 = 子骨头），
      与 MC2 中 Transform 层级位置由父子关系决定的逻辑等价。
      不直接取 display_positions 作 head_pose：物理距离约束有柔性，
      粒子间距可能略大于 rest 长度；若直接取粒子坐标，骨链会出现视觉断缝。

    【Connected / Disconnected 骨骼均兼容，无需打断骨骼】
      Connected 骨骼（头锁父尾）：Blender 自动忽略 matrix_basis 的 Translation，
        只有 Rotation 生效——与 MC2 仅写旋转的行为完全一致。
      Disconnected 骨骼：Translation 也生效，head_pose 由父链传播提供正确值。
      推荐使用 Connected 骨骼：与 MC2 原生行为最贴近，位置由动画层级保证稳定。

    【depth=0 链首固定骨也参与写回】
      Root 骨（FIXED 粒子）位置由动画锁定，但其旋转通过 C++ root_rotation 参数
      按子骨链方向计算，写回后首骨可以跟随物理方向旋转，防止链首"卡死"。
    """
    _MC2_FORWARD = np.asarray([0.0, 0.0, 1.0], dtype=np.float32)

    def _qrot_np(q, v):
        nq = q / (np.linalg.norm(q) + 1e-16)
        qv = nq[:3]
        uv = np.cross(qv, v)
        uuv = np.cross(qv, uv)
        return v + 2.0 * (nq[3] * uv + uuv)

    ordered = sorted(
        records,   # depth=0（链首固定骨）也纳入写回，使其随子骨链方向旋转
        key=lambda r: r["depth"],
    )

    matrix_world = armature_obj.matrix_world
    mat_world_inv = matrix_world.inverted()
    arm_inv_3x3 = matrix_world.to_3x3().inverted()
    parent_pose_matrices = {}

    for record in records:
        bone_name = record["bone_name"]
        pidx = record["particle_index"]
        depth = record.get("depth", 0)

        if pidx < 0 or pidx >= len(world_rotations):
            # 粒子索引越界：depth=0 退回到动画矩阵（保证后续链不断裂），其余跳过
            if depth == 0:
                parent_pose_matrices[bone_name] = record["pose_bone"].matrix.copy()
            continue

        wq = world_rotations[pidx]
        dir_np = _qrot_np(wq, _MC2_FORWARD)
        desired_local = arm_inv_3x3 @ mathutils.Vector((float(dir_np[0]), float(dir_np[1]), float(dir_np[2])))
        if desired_local.length <= EPSILON:
            # 方向退化：同上退回
            if depth == 0:
                parent_pose_matrices[bone_name] = record["pose_bone"].matrix.copy()
            continue
        desired_local.normalize()

        bone = record["pose_bone"].bone
        init_axis = mathutils.Vector(bone.tail_local) - mathutils.Vector(bone.head_local)
        if init_axis.length <= EPSILON:
            init_axis = mathutils.Vector((0.0, 1.0, 0.0))
        init_axis.normalize()
        arm_quat = init_axis.rotation_difference(desired_local) @ bone.matrix_local.to_quaternion()

        # 头部位置：
        # depth=0（链首固定骨）：粒子位置由动画锁定，直接取当前动画头位置。
        #   不走链式传播——其父骨（root_bone 共享父级）不在 parent_pose_matrices 里，
        #   若走传播会退到 parent.matrix.translation（根骨原点），导致所有链头吸到同一点。
        # depth>0：MC2 链式传播——父骨尾部即子骨头部，保证骨链视觉连续。
        #   不用 display_positions 直接作头部：物理有弹性拉伸时粒子距离 ≠ rest 长度，
        #   直接取粒子坐标会导致相邻骨骼出现视觉断缝。
        if depth == 0:
            head_pose = (mat_world_inv @ record["pose_bone"].head).to_3d()
        else:
            parent = record.get("parent")
            parent_name = record.get("parent_name") or ""
            if parent is not None and record.get("parent_rest_inv") is not None:
                par_mat = parent_pose_matrices.get(parent_name)
                if par_mat is not None:
                    head_pose = (par_mat @ record["parent_rest_inv"] @ record["bone_rest"]).translation
                else:
                    head_pose = parent.matrix.translation.copy()
            else:
                head_pose = (mat_world_inv @ record["pose_bone"].head).to_3d()

        target_matrix = mathutils.Matrix.LocRotScale(head_pose, arm_quat, mathutils.Vector((1.0, 1.0, 1.0)))
        parent_pose_matrices[bone_name] = target_matrix

    _batch_write_basis(armature_obj, ordered, parent_pose_matrices, write_runtime)


# ---------------------------------------------------------------------------
# 退化路径：每骨独立计算
# ---------------------------------------------------------------------------

def _write_per_bone_independent(armature_obj, records, display_positions, rotational_interpolation, write_runtime):
    matrix_world = armature_obj.matrix_world
    ordered = sorted(
        records,   # depth=0 链首固定骨也纳入，使其跟随子骨链方向旋转
        key=lambda r: r["depth"],
    )
    target_pose_matrices = {}
    for record in ordered:
        particle_index = record["particle_index"]
        child_particle  = record["child_particle"]
        parent_particle = record["parent_particle"]
        head_world = mathutils.Vector(display_positions[particle_index])
        if child_particle >= 0:
            direction_world = mathutils.Vector(display_positions[child_particle]) - head_world
        elif parent_particle >= 0:
            direction_world = head_world - mathutils.Vector(display_positions[parent_particle])
        else:
            continue
        if direction_world.length <= EPSILON:
            continue
        desired_local = matrix_world.inverted().to_3x3() @ direction_world
        if desired_local.length <= EPSILON:
            continue
        desired_local.normalize()
        bone = record["pose_bone"].bone
        init_axis = mathutils.Vector(bone.tail_local) - mathutils.Vector(bone.head_local)
        if init_axis.length <= EPSILON:
            init_axis = mathutils.Vector((0.0, 1.0, 0.0))
        init_axis.normalize()
        init_rotation = bone.matrix_local.to_quaternion()
        rotation_delta = init_axis.rotation_difference(desired_local)
        ratio = max(0.0, min(1.0, float(rotational_interpolation)))
        if ratio < 1.0:
            rotation_delta = mathutils.Quaternion().slerp(rotation_delta, ratio)
        parent = record.get("parent")
        parent_name = record.get("parent_name") or ""
        if parent is not None and record.get("parent_rest_inv") is not None:
            par_mat = target_pose_matrices.get(parent_name)
            if par_mat is not None:
                head_pose = (par_mat @ record["parent_rest_inv"] @ record["bone_rest"]).translation
            else:
                head_pose = matrix_world.inverted() @ head_world
        else:
            head_pose = matrix_world.inverted() @ head_world
        target_matrix = mathutils.Matrix.LocRotScale(
            head_pose, rotation_delta @ init_rotation, mathutils.Vector((1.0, 1.0, 1.0))
        )
        target_pose_matrices[record["bone_name"]] = target_matrix
    _batch_write_basis(armature_obj, ordered, target_pose_matrices, write_runtime)


# ---------------------------------------------------------------------------
# 批量写 matrix_basis（两条路径共用）
# ---------------------------------------------------------------------------

def _batch_write_basis(armature_obj, ordered, target_pose_matrices, write_runtime):
    pose_bones = armature_obj.pose.bones
    basis_value_count = len(pose_bones) * 16
    if isinstance(write_runtime, dict):
        basis_values = write_runtime.get("basis_values")
        if not isinstance(basis_values, list) or len(basis_values) != basis_value_count:
            basis_values = [0.0] * basis_value_count
            write_runtime["basis_values"] = basis_values
    else:
        basis_values = [0.0] * basis_value_count
    try:
        pose_bones.foreach_get("matrix_basis", basis_values)
        can_foreach_set = True
    except Exception:
        can_foreach_set = False
    fallback_updates = []
    for record in ordered:
        bone_name = record["bone_name"]
        target_matrix = target_pose_matrices.get(bone_name)
        if target_matrix is None:
            continue
        basis_matrix = _matrix_basis_from_target(record, target_matrix, target_pose_matrices)
        if can_foreach_set:
            pose_index = int(record.get("pose_index", -1))
            if pose_index >= 0:
                _pack_matrix_into(basis_values, pose_index * 16, basis_matrix)
        else:
            fallback_updates.append((record["pose_bone"], basis_matrix))
    if can_foreach_set:
        try:
            pose_bones.foreach_set("matrix_basis", basis_values)
            return
        except Exception:
            fallback_updates = [
                (rec["pose_bone"],
                 _matrix_basis_from_target(rec, target_pose_matrices[rec["bone_name"]], target_pose_matrices))
                for rec in ordered if rec["bone_name"] in target_pose_matrices
            ]
    for pose_bone, basis_matrix in fallback_updates:
        pose_bone.matrix_basis = basis_matrix


# ---------------------------------------------------------------------------
# 重置
# ---------------------------------------------------------------------------

def restore_initial_pose(records):
    """把记录里的骨骼 matrix_basis 重置为 identity（reset / 跳帧冷启动用）。"""
    for record in records:
        pose_bone = record.get("pose_bone")
        if pose_bone is None:
            continue
        try:
            pose_bone.matrix_basis = mathutils.Matrix.Identity(4)
        except Exception:
            pass
