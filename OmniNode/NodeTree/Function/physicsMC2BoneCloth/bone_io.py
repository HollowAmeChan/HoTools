"""BoneCloth 骨骼姿态写回。

把 solver 输出的 display_positions（世界空间粒子位置）转回骨骼旋转，写入 PoseBone.matrix_basis。

核心算法：MC2 SimulationPostProxyMeshUpdateLine（VirtualMeshManager.cs L790）
  C++ 实现在 _native/src/mc2_bonecloth_io.cpp，通过 hotools_native.solve_mc2_bonecloth_io 调用。
  Python 退化路径在 _write_per_bone_independent，作为 native 不可用时的兜底。

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
                    "init_scale": pose_bone.matrix.to_scale().copy(),
                })
        particle_cursor += len(bone_names)
    return records


# ---------------------------------------------------------------------------
# 矩阵工具
# ---------------------------------------------------------------------------

def _matrix_basis_from_target(record, target_matrix, parent_pose_matrices):
    parent = record.get("parent")
    if parent is None or record.get("parent_rest_inv") is None:
        return record["bone_rest_inv"] @ target_matrix
    parent_name = record.get("parent_name") or ""
    parent_matrix = parent_pose_matrices.get(parent_name)
    if parent_matrix is None:
        parent_matrix = parent.matrix
    parent_space = parent_matrix @ record["parent_rest_inv"] @ record["bone_rest"]
    return parent_space.inverted() @ target_matrix


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
            _write_from_world_rotations(
                armature_obj, records, world_rotations, display_positions, write_runtime
            )
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

def _write_from_world_rotations(armature_obj, records, world_rotations, display_positions, write_runtime):
    """MC2 世界旋转 Z 轴 → 骨骼方向 → matrix_basis。depth=0 root 用动画矩阵。"""
    _MC2_FORWARD = np.asarray([0.0, 0.0, 1.0], dtype=np.float32)

    def _qrot_np(q, v):
        nq = q / (np.linalg.norm(q) + 1e-16)
        qv = nq[:3]
        uv = np.cross(qv, v)
        uuv = np.cross(qv, uv)
        return v + 2.0 * (nq[3] * uv + uuv)

    ordered = sorted(
        [rec for rec in records if rec.get("depth", 0) > 0],
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

        if depth == 0:
            parent_pose_matrices[bone_name] = record["pose_bone"].matrix.copy()
            continue

        if pidx < 0 or pidx >= len(world_rotations):
            continue

        wq = world_rotations[pidx]
        dir_np = _qrot_np(wq, _MC2_FORWARD)
        desired_local = arm_inv_3x3 @ mathutils.Vector((float(dir_np[0]), float(dir_np[1]), float(dir_np[2])))
        if desired_local.length <= EPSILON:
            continue
        desired_local.normalize()

        bone = record["pose_bone"].bone
        init_axis = mathutils.Vector(bone.tail_local) - mathutils.Vector(bone.head_local)
        if init_axis.length <= EPSILON:
            init_axis = mathutils.Vector((0.0, 1.0, 0.0))
        init_axis.normalize()
        arm_quat = init_axis.rotation_difference(desired_local) @ bone.matrix_local.to_quaternion()

        # 直接用粒子世界坐标作骨骼头部位置，避免父链传播的累积误差导致末端漂移。
        if (
            display_positions is not None
            and pidx < len(display_positions)
        ):
            dp = display_positions[pidx]
            head_pose = (mat_world_inv @ mathutils.Vector((float(dp[0]), float(dp[1]), float(dp[2])))).to_3d()
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

        target_matrix = mathutils.Matrix.LocRotScale(head_pose, arm_quat, record["init_scale"])
        parent_pose_matrices[bone_name] = target_matrix

    _batch_write_basis(armature_obj, ordered, parent_pose_matrices, write_runtime)


# ---------------------------------------------------------------------------
# 退化路径：每骨独立计算
# ---------------------------------------------------------------------------

def _write_per_bone_independent(armature_obj, records, display_positions, rotational_interpolation, write_runtime):
    matrix_world = armature_obj.matrix_world
    ordered = sorted(
        [rec for rec in records if rec.get("depth", 0) > 0],
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
            head_pose, rotation_delta @ init_rotation, record["init_scale"]
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
