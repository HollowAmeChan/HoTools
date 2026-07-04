"""BoneCloth 骨骼姿态写回。

把 solver 输出的 display_positions（世界空间粒子位置）转回骨骼旋转，写入 PoseBone.matrix_basis。

核心算法：MC2 SimulationPostProxyMeshUpdateLine（VirtualMeshManager.cs L790）
  - 按 baseline 从 root → leaf 自顶向下遍历
  - 每个骨的旋转由父骨的已更新旋转传播：crot = parent_rot * local_rest_rot * FromToRotation(tv, v)
  - 末端骨旋转在父骨处理时设置，不独立计算
  - 父骨自身旋转由子方向平均误差修正：rot = FromToRotation(ctv, cv, averageRate) * rot
  - 最终应用 blendWeight：rot = slerp(baseRot, rot, blendWeight)

写回路径与 SpringBone 一致：
  - connected 子骨通过 matrix_basis 写回，不直接改 PoseBone.matrix
  - 写回顺序按深度升序（父先于子），避免子骨参考旧父矩阵
  - 只改方向（旋转），保留 base pose 的缩放，不改 loc
"""

from __future__ import annotations

import bpy
import mathutils
import numpy as np

from ..physicsMC2MeshCloth.constants import MC2_ATTR_MOVE, MC2SystemConstants

EPSILON = 1e-8


# ---------------------------------------------------------------------------
# numpy 四元数工具（与 baseline.py 约定一致，格式均为 [x,y,z,w]）
# ---------------------------------------------------------------------------

def _qn(q: np.ndarray) -> np.ndarray:
    """归一化四元数，零长度返回 identity [0,0,0,1]。"""
    n = float(np.linalg.norm(q))
    return np.asarray(q / n, dtype=np.float32) if n > EPSILON else np.asarray((0., 0., 0., 1.), dtype=np.float32)


def _qmul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """四元数乘法 a*b，格式 [x,y,z,w]。"""
    ax, ay, az, aw = float(a[0]), float(a[1]), float(a[2]), float(a[3])
    bx, by, bz, bw = float(b[0]), float(b[1]), float(b[2]), float(b[3])
    return _qn(np.asarray((
        aw*bx + ax*bw + ay*bz - az*by,
        aw*by - ax*bz + ay*bw + az*bx,
        aw*bz + ax*by - ay*bx + az*bw,
        aw*bw - ax*bx - ay*by - az*bz,
    ), dtype=np.float32))


def _qinv(q: np.ndarray) -> np.ndarray:
    """四元数共轭（单位四元数的逆），格式 [x,y,z,w]。"""
    nq = _qn(q)
    return np.asarray((-nq[0], -nq[1], -nq[2], nq[3]), dtype=np.float32)


def _qrot(q: np.ndarray, v: np.ndarray) -> np.ndarray:
    """用四元数 q 旋转向量 v，格式 [x,y,z,w]。"""
    nq = _qn(q)
    qv = nq[:3]
    uv = np.cross(qv, v)
    uuv = np.cross(qv, uv)
    return np.ascontiguousarray(v + 2.0 * (nq[3] * uv + uuv), dtype=np.float32)


def _qslerp(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    """球面线性插值，格式 [x,y,z,w]。"""
    t = max(0.0, min(1.0, float(t)))
    qa = _qn(a)
    qb = _qn(b)
    dot = float(np.dot(qa, qb))
    if dot < 0.0:
        qb = -qb
        dot = -dot
    if dot > 0.9995:
        return _qn(qa + (qb - qa) * t)
    theta0 = float(np.arccos(max(-1.0, min(1.0, dot))))
    theta = theta0 * t
    s0 = float(np.cos(theta) - dot * np.sin(theta) / np.sin(theta0))
    s1 = float(np.sin(theta) / np.sin(theta0))
    return _qn(s0 * qa + s1 * qb)


def _from_to_rotation(v1: np.ndarray, v2: np.ndarray, t: float = 1.0) -> np.ndarray:
    """MC2 MathUtility.FromToRotation 的 Python 移植。

    返回将向量 v1 旋转到 v2 方向的四元数，t 是插值率（等比缩放旋转角度）。
    格式 [x,y,z,w]。
    """
    n1 = float(np.linalg.norm(v1))
    n2 = float(np.linalg.norm(v2))
    if n1 <= EPSILON or n2 <= EPSILON:
        return np.asarray((0., 0., 0., 1.), dtype=np.float32)
    nv1 = np.asarray(v1 / n1, dtype=np.float32)
    nv2 = np.asarray(v2 / n2, dtype=np.float32)

    c = float(np.dot(nv1, nv2))
    c = max(-1.0, min(1.0, c))

    # 完全相反
    if abs(1.0 + c) < 1e-6:
        angle = float(np.pi) * t
        if abs(nv1[0]) > abs(nv1[1]) and abs(nv1[0]) > abs(nv1[2]):
            axis = np.cross(nv1, np.asarray((0., 1., 0.), dtype=np.float32))
        else:
            axis = np.cross(nv1, np.asarray((1., 0., 0.), dtype=np.float32))
        na = float(np.linalg.norm(axis))
        if na <= EPSILON:
            return np.asarray((0., 0., 0., 1.), dtype=np.float32)
        axis = axis / na
    # 完全相同
    elif abs(1.0 - c) < 1e-6:
        return np.asarray((0., 0., 0., 1.), dtype=np.float32)
    else:
        angle = float(np.arccos(c)) * t
        axis = np.cross(nv1, nv2)
        na = float(np.linalg.norm(axis))
        if na <= EPSILON:
            return np.asarray((0., 0., 0., 1.), dtype=np.float32)
        axis = axis / na

    s = float(np.sin(angle * 0.5))
    c2 = float(np.cos(angle * 0.5))
    return _qn(np.asarray((axis[0]*s, axis[1]*s, axis[2]*s, c2), dtype=np.float32))


# ---------------------------------------------------------------------------
# MC2 SimulationPostProxyMeshUpdateLine 移植
# ---------------------------------------------------------------------------

def compute_bone_rotations_mc2_baseline(
    display_positions: np.ndarray,    # (N,3) 模拟后世界空间粒子位置
    base_positions: np.ndarray,       # (N,3) step_basic_positions（动画 base pose）
    base_rotations: np.ndarray,       # (N,4) step_basic_rotations，格式 [x,y,z,w]
    vertex_local_positions: np.ndarray,  # (N,3) 子骨在父骨 local 空间的 rest 位置
    vertex_local_rotations: np.ndarray,  # (N,4) 子骨相对父骨的 rest local 旋转 [x,y,z,w]
    parent_indices: np.ndarray,       # (N,) int32，-1 表示 root
    baseline_start: np.ndarray,       # baseline 链起始索引
    baseline_count: np.ndarray,       # baseline 链长度
    baseline_data: np.ndarray,        # 自顶向下遍历顺序（粒子全局索引）
    attributes: np.ndarray,           # (N,) uint8，MC2_ATTR_MOVE 标记
    rotational_interpolation: float,  # averageRate：父骨自身方向修正权重
    blend_weight: float,              # blendWeight：模拟结果与 base pose 混合权重
    anime_ratio: float = 0.0,         # animationPoseRatio：rest/animated 插值
) -> np.ndarray:                      # (N,4) 世界空间四元数 [x,y,z,w]
    """MC2 SimulationPostProxyMeshUpdateLine 的 Python numpy 移植。

    自顶向下遍历 baseline 链，按 MC2 语义传播旋转：
      crot = FromToRotation(tv, v) * parent_rot * local_rest_rot
    末端骨旋转由其父骨处理时设置，不独立计算，修复末端骨滑移问题。

    对应源码：VirtualMeshManager.cs L790-950
    """
    vertex_count = int(len(display_positions))
    if vertex_count == 0:
        return np.zeros((0, 4), dtype=np.float32)

    # 初始化旋转数组为 base pose 旋转（对应 MC2 初始 rotations[] = step_basic_rotations）
    rotations = np.ascontiguousarray(base_rotations, dtype=np.float32).copy()

    # 预先构建子骨列表（parent_indices → children dict）
    children_of: list[list[int]] = [[] for _ in range(vertex_count)]
    for ci in range(vertex_count):
        pi = int(parent_indices[ci])
        if 0 <= pi < vertex_count:
            children_of[pi].append(ci)

    average_rate = float(rotational_interpolation)
    bw = max(0.0, min(1.0, float(blend_weight)))
    ar = max(0.0, min(1.0, float(anime_ratio)))

    for line_idx in range(len(baseline_start)):
        start = int(baseline_start[line_idx])
        count = int(baseline_count[line_idx])

        # 自顶向下遍历（root 在最前）
        for data_offset in range(count):
            data_idx = start + data_offset
            if data_idx < 0 or data_idx >= len(baseline_data):
                continue
            lindex = int(baseline_data[data_idx])
            if lindex < 0 or lindex >= vertex_count:
                continue

            pos = np.asarray(display_positions[lindex], dtype=np.float32)
            rot = np.asarray(rotations[lindex], dtype=np.float32)

            base_pos = np.asarray(base_positions[lindex], dtype=np.float32)
            base_rot = np.asarray(base_rotations[lindex], dtype=np.float32)
            base_inv_rot = _qinv(base_rot)

            children = children_of[lindex]
            is_move = bool(int(attributes[lindex]) & MC2_ATTR_MOVE)

            if children:
                ctv = np.zeros(3, dtype=np.float32)  # 累积 rest 方向
                cv = np.zeros(3, dtype=np.float32)   # 累积 sim 方向

                for clindex in children:
                    if clindex < 0 or clindex >= vertex_count:
                        continue

                    cattr = int(attributes[clindex])
                    cpos = np.asarray(display_positions[clindex], dtype=np.float32)

                    # 子骨在父骨 base pose local 空间的位置和旋转
                    cbase_pos = np.asarray(base_positions[clindex], dtype=np.float32)
                    cbase_rot = np.asarray(base_rotations[clindex], dtype=np.float32)
                    cbase_local_pos = _qrot(base_inv_rot, cbase_pos - base_pos)
                    cbase_local_rot = _qmul(base_inv_rot, cbase_rot)

                    # rest local 与 animated local 插值（animationPoseRatio）
                    vl_pos = np.asarray(vertex_local_positions[clindex], dtype=np.float32)
                    vl_rot = np.asarray(vertex_local_rotations[clindex], dtype=np.float32)
                    lpos = vl_pos * (1.0 - ar) + cbase_local_pos * ar
                    lrot = _qslerp(vl_rot, cbase_local_rot, ar)

                    # rest 方向（tv）：父骨当前旋转 * 子骨 local rest 位置
                    tv = _qrot(rot, lpos)
                    ctv += tv

                    # 子骨当前模拟方向（v）
                    c_is_move = bool(cattr & MC2_ATTR_MOVE)
                    if c_is_move:
                        v = cpos - pos
                        cv += v

                        # 子骨世界旋转：parent_rot * local_rest_rot * FromToRotation(tv, v)
                        crot = _qmul(rot, lrot)
                        tv_len = float(np.linalg.norm(tv))
                        v_len = float(np.linalg.norm(v))
                        if tv_len > EPSILON and v_len > EPSILON:
                            q_corr = _from_to_rotation(tv, v)
                            crot = _qmul(q_corr, crot)

                        rotations[clindex] = crot
                    else:
                        # 固定子骨：sim 方向同 rest 方向
                        cv += tv

                # 父骨自身方向修正（averageRate 权重）
                t_parent = average_rate if is_move else 1.0
                ctv_len = float(np.linalg.norm(ctv))
                cv_len = float(np.linalg.norm(cv))
                if ctv_len > EPSILON and cv_len > EPSILON:
                    cq = _from_to_rotation(ctv, cv, t_parent)
                    rot = _qmul(cq, rot)

            # blendWeight：混合 base pose 旋转与模拟旋转
            rot = _qslerp(base_rot, rot, bw)

            rotations[lindex] = rot

    return np.ascontiguousarray(rotations, dtype=np.float32)


# ---------------------------------------------------------------------------
# 写回记录构建
# ---------------------------------------------------------------------------

def build_bone_write_records(
    armature_obj: bpy.types.Object,
    chains: list[dict],
) -> list[dict]:
    """为每根参与模拟的骨骼建立写回记录。

    记录包含 bone_rest / parent_rest_inv / init_scale，
    供 matrix_basis 写回时使用。
    """
    records: list[dict] = []
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
                    # init 数据用 rest bone，不受物理写回污染
                    "init_scale": pose_bone.matrix.to_scale().copy(),
                })
        particle_cursor += len(bone_names)
    return records


# ---------------------------------------------------------------------------
# 世界空间旋转 → matrix_basis 转换
# ---------------------------------------------------------------------------

def _world_quat_to_matrix_basis(
    armature_obj: bpy.types.Object,
    record: dict,
    world_rot_quat: np.ndarray,               # [x,y,z,w] 世界空间旋转
    parent_pose_matrices: dict,               # bone_name → 已计算的 armature-space pose matrix
) -> mathutils.Matrix:
    """把世界空间四元数旋转转成可写入 matrix_basis 的矩阵。

    转换路径：
      world_rot → armature_space_rot → pose_matrix（LocRotScale）→ matrix_basis
    """
    matrix_world = armature_obj.matrix_world
    arm_inv_3x3 = matrix_world.to_3x3().inverted()

    # 世界四元数转 armature space（mathutils 格式为 [w,x,y,z]）
    x, y, z, w = float(world_rot_quat[0]), float(world_rot_quat[1]), float(world_rot_quat[2]), float(world_rot_quat[3])
    arm_space_rot = arm_inv_3x3 @ mathutils.Quaternion((w, x, y, z)).to_matrix()
    arm_space_quat = arm_space_rot.to_quaternion()

    # 粒子 head 在 armature 空间的位置（从父或自身位置获取）
    parent = record.get("parent")
    if parent is not None and record.get("parent_rest_inv") is not None:
        parent_name = record.get("parent_name") or ""
        parent_matrix = parent_pose_matrices.get(parent_name)
        if parent_matrix is not None:
            head_pose = (parent_matrix @ record["parent_rest_inv"] @ record["bone_rest"]).translation
        else:
            head_pose = parent.matrix.translation.copy()
    else:
        head_pose = (matrix_world.inverted() @ mathutils.Vector((0., 0., 0.))).to_3d()

    init_scale = record["init_scale"]
    target_matrix = mathutils.Matrix.LocRotScale(head_pose, arm_space_quat, init_scale)
    return target_matrix


def _matrix_basis_from_target(
    record: dict,
    target_matrix: mathutils.Matrix,
    parent_pose_matrices: dict,
) -> mathutils.Matrix:
    """把目标 armature-space pose matrix 转成可写入的 matrix_basis。"""
    parent = record.get("parent")
    if parent is None or record.get("parent_rest_inv") is None:
        return record["bone_rest_inv"] @ target_matrix
    parent_name = record.get("parent_name") or ""
    parent_matrix = parent_pose_matrices.get(parent_name)
    if parent_matrix is None:
        parent_matrix = parent.matrix
    parent_space = parent_matrix @ record["parent_rest_inv"] @ record["bone_rest"]
    return parent_space.inverted() @ target_matrix


# ---------------------------------------------------------------------------
# 写回记录构建
# ---------------------------------------------------------------------------

def build_bone_write_records(
    armature_obj: bpy.types.Object,
    chains: list[dict],
) -> list[dict]:
    """为每根参与模拟的骨骼建立写回记录。"""
    records: list[dict] = []
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
                    "init_scale": pose_bone.matrix.to_scale().copy(),
                })
        particle_cursor += len(bone_names)
    return records


# ---------------------------------------------------------------------------
# 矩阵工具
# ---------------------------------------------------------------------------

def _matrix_basis_from_target(
    record: dict,
    target_matrix: "mathutils.Matrix",
    parent_pose_matrices: dict,
) -> "mathutils.Matrix":
    """把目标 armature-space pose matrix 转成可写入的 matrix_basis。"""
    parent = record.get("parent")
    if parent is None or record.get("parent_rest_inv") is None:
        return record["bone_rest_inv"] @ target_matrix
    parent_name = record.get("parent_name") or ""
    parent_matrix = parent_pose_matrices.get(parent_name)
    if parent_matrix is None:
        parent_matrix = parent.matrix
    parent_space = parent_matrix @ record["parent_rest_inv"] @ record["bone_rest"]
    return parent_space.inverted() @ target_matrix


def _pack_matrix_into(basis_values: list, offset: int, matrix: "mathutils.Matrix") -> None:
    """按 Blender foreach_set 期望的列主序把 4x4 矩阵写入扁平列表。"""
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
    armature_obj: "bpy.types.Object",
    chains: list,
    records: list,
    display_positions: "np.ndarray",
    base_positions: "np.ndarray",
    rotational_interpolation: float,
    blend_weight: float,
    write_runtime: "dict | None" = None,
    step_basic_rotations: "np.ndarray | None" = None,
    vertex_local_positions: "np.ndarray | None" = None,
    vertex_local_rotations: "np.ndarray | None" = None,
    parent_indices: "np.ndarray | None" = None,
    baseline_start: "np.ndarray | None" = None,
    baseline_count: "np.ndarray | None" = None,
    baseline_data: "np.ndarray | None" = None,
    attributes: "np.ndarray | None" = None,
    anime_ratio: float = 0.0,
) -> None:
    """把 display_positions 写回骨骼旋转（matrix_basis 批量写）。

    若提供了 step_basic_rotations 等 baseline 数组，走 MC2
    SimulationPostProxyMeshUpdateLine 链式旋转传播路径（修复末端骨滑移）。
    否则退化为每骨独立计算的向后兼容路径。
    """
    if not records:
        return

    use_baseline = (
        step_basic_rotations is not None
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
        world_rotations = compute_bone_rotations_mc2_baseline(
            display_positions=np.ascontiguousarray(display_positions, dtype=np.float32),
            base_positions=np.ascontiguousarray(base_positions, dtype=np.float32),
            base_rotations=np.ascontiguousarray(step_basic_rotations, dtype=np.float32),
            vertex_local_positions=np.ascontiguousarray(vertex_local_positions, dtype=np.float32),
            vertex_local_rotations=np.ascontiguousarray(vertex_local_rotations, dtype=np.float32),
            parent_indices=np.ascontiguousarray(parent_indices, dtype=np.int32),
            baseline_start=np.ascontiguousarray(baseline_start, dtype=np.int32),
            baseline_count=np.ascontiguousarray(baseline_count, dtype=np.int32),
            baseline_data=np.ascontiguousarray(baseline_data, dtype=np.int32),
            attributes=np.ascontiguousarray(attributes, dtype=np.uint8),
            rotational_interpolation=rotational_interpolation,
            blend_weight=blend_weight,
            anime_ratio=anime_ratio,
        )
        _write_from_world_rotations(armature_obj, records, world_rotations, write_runtime)
        return

    # 退化路径
    _write_per_bone_independent(
        armature_obj, records, display_positions, rotational_interpolation, write_runtime
    )


def _write_from_world_rotations(
    armature_obj: "bpy.types.Object",
    records: list,
    world_rotations: "np.ndarray",
    write_runtime: "dict | None",
) -> None:
    """把 MC2 baseline 计算的世界空间旋转数组写入 matrix_basis。

    MC2 的 _frame_rotation / baseline 旋转帧以 Z 轴为前向方向（骨骼指向方向）。
    Blender 骨骼以 Y 轴为指向方向。
    因此：从 MC2 世界旋转提取 Z 轴 = 物理后骨骼应指向的世界方向，
    再用 init_axis.rotation_difference(desired_dir_local) 转成 matrix_basis，
    与原有 per-bone 路径保持一致，只是方向数据来自链式传播而非独立计算。

    depth=0 的 root 骨由动画控制，直接用 pose_bone.matrix 填入 parent_pose_matrices，
    不做写回。
    """
    _MC2_FORWARD = np.asarray([0.0, 0.0, 1.0], dtype=np.float32)

    ordered = sorted(
        [rec for rec in records if rec.get("depth", 0) > 0],
        key=lambda r: r["depth"],
    )

    matrix_world = armature_obj.matrix_world
    arm_inv_3x3 = matrix_world.to_3x3().inverted()

    # 第一遍：建 parent_pose_matrices（含 root，供子骨查父矩阵用）
    # root 骨（depth==0）不受物理控制，直接用当前 animated pose 矩阵
    parent_pose_matrices: dict = {}
    for record in records:
        bone_name = record["bone_name"]
        pidx = record["particle_index"]
        depth = record.get("depth", 0)

        if depth == 0:
            # root 保持动画姿态
            parent_pose_matrices[bone_name] = record["pose_bone"].matrix.copy()
            continue

        if pidx < 0 or pidx >= len(world_rotations):
            continue

        # 从 MC2 旋转帧提取 Z 轴 = 骨骼应指向的世界方向
        wq = world_rotations[pidx]
        desired_dir_world_np = _qrot(wq, _MC2_FORWARD)
        desired_dir_world = mathutils.Vector((
            float(desired_dir_world_np[0]),
            float(desired_dir_world_np[1]),
            float(desired_dir_world_np[2]),
        ))
        # 转到 armature local space
        desired_dir_local = arm_inv_3x3 @ desired_dir_world
        if desired_dir_local.length <= EPSILON:
            continue
        desired_dir_local.normalize()

        # 用 rest 方向差值计算旋转（与 _write_per_bone_independent 路径相同）
        bone = record["pose_bone"].bone
        init_axis = mathutils.Vector(bone.tail_local) - mathutils.Vector(bone.head_local)
        if init_axis.length <= EPSILON:
            init_axis = mathutils.Vector((0.0, 1.0, 0.0))
        init_axis.normalize()
        init_rotation = bone.matrix_local.to_quaternion()
        arm_quat = init_axis.rotation_difference(desired_dir_local) @ init_rotation

        # head 位置：优先从父骨已计算的 pose matrix 推导
        parent = record.get("parent")
        parent_name = record.get("parent_name") or ""
        if parent is not None and record.get("parent_rest_inv") is not None:
            par_mat = parent_pose_matrices.get(parent_name)
            if par_mat is not None:
                head_pose = (par_mat @ record["parent_rest_inv"] @ record["bone_rest"]).translation
            else:
                head_pose = parent.matrix.translation.copy()
        else:
            pb = record["pose_bone"]
            head_pose = (matrix_world.inverted() @ pb.head).to_3d()

        target_matrix = mathutils.Matrix.LocRotScale(head_pose, arm_quat, record["init_scale"])
        parent_pose_matrices[bone_name] = target_matrix

    # 第二遍：只写非 root 骨
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

    fallback_updates: list = []
    for record in ordered:
        bone_name = record["bone_name"]
        target_matrix = parent_pose_matrices.get(bone_name)
        if target_matrix is None:
            continue
        basis_matrix = _matrix_basis_from_target(record, target_matrix, parent_pose_matrices)
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
                 _matrix_basis_from_target(
                     rec, parent_pose_matrices[rec["bone_name"]], parent_pose_matrices
                 ))
                for rec in ordered if rec["bone_name"] in parent_pose_matrices
            ]

    for pose_bone, basis_matrix in fallback_updates:
        pose_bone.matrix_basis = basis_matrix


def _write_per_bone_independent(
    armature_obj: "bpy.types.Object",
    records: list,
    display_positions: "np.ndarray",
    rotational_interpolation: float,
    write_runtime: "dict | None",
) -> None:
    """向后兼容：每骨独立计算写回，不依赖 baseline 数组。"""
    matrix_world = armature_obj.matrix_world

    ordered = sorted(
        [rec for rec in records if rec.get("depth", 0) > 0],
        key=lambda r: r["depth"],
    )

    target_pose_matrices: dict = {}
    for record in ordered:
        particle_index = record["particle_index"]
        child_particle = record["child_particle"]
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
        axis = mathutils.Vector(bone.tail_local) - mathutils.Vector(bone.head_local)
        if axis.length <= EPSILON:
            axis = mathutils.Vector((0.0, 1.0, 0.0))
        axis.normalize()
        init_rotation = bone.matrix_local.to_quaternion()

        rotation_delta = axis.rotation_difference(desired_local)
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
            head_pose, rotation_delta @ init_rotation, record["init_scale"]
        )
        target_pose_matrices[record["bone_name"]] = target_matrix

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

    fallback_updates: list = []
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
                 _matrix_basis_from_target(
                     rec, target_pose_matrices[rec["bone_name"]], target_pose_matrices
                 ))
                for rec in ordered if rec["bone_name"] in target_pose_matrices
            ]

    for pose_bone, basis_matrix in fallback_updates:
        pose_bone.matrix_basis = basis_matrix


# ---------------------------------------------------------------------------
# 重置
# ---------------------------------------------------------------------------

def restore_initial_pose(records: list) -> None:
    """把记录里的骨骼 matrix_basis 重置为 identity（reset / 跳帧冷启动用）。"""
    for record in records:
        pose_bone = record.get("pose_bone")
        if pose_bone is None:
            continue
        try:
            pose_bone.matrix_basis = mathutils.Matrix.Identity(4)
        except Exception:
            pass
