"""BoneCloth 骨骼姿态写回。

把 solver 输出的 display_positions（世界空间粒子位置）转回骨骼旋转，写入 PoseBone.matrix_basis。
复用 SpringBone 已验证的 matrix_basis 写回路径：
  - connected 子骨不能直接批量写 PoseBone.matrix，必须通过 matrix_basis
  - 只改方向（旋转），保留 base pose 的缩放，不改 loc（骨骼平移由父骨 tail 决定）
  - 写回顺序按深度升序（父先于子），避免子骨参考旧父矩阵

初版只做 Line 路径：每根骨的方向来自“自身粒子 → 子粒子”的向量。
叶子骨没有子粒子，用父方向外推。
"""

from __future__ import annotations

import bpy
import mathutils
import numpy as np


EPSILON = 1e-8


def build_bone_write_records(
    armature_obj: bpy.types.Object,
    chains: list[dict],
) -> list[dict]:
    """为每根参与模拟的骨骼建立写回记录。

    记录里缓存 rest 矩阵和父链信息，避免每帧重复取。
    child_particle: 该骨在粒子数组中“下一节”的索引（用于取方向）；叶子为 -1。
    parent_particle: 上一节索引；root 为 -1。
    """
    records: list[dict] = []
    pose_bones = armature_obj.pose.bones
    pose_index_by_name = {pose_bone.name: index for index, pose_bone in enumerate(pose_bones)}

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
                records.append(
                    {
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
                        # init_axis_local / init_rotation 必须用 rest bone 数据，
                        # 不能读 pose_bone.tail/.head/.matrix（含物理写回，跳帧归位会失效）
                        "init_axis_local": _init_axis_local_rest(pose_bone),
                        "init_rotation": pose_bone.bone.matrix_local.to_quaternion().copy(),
                        "init_scale": pose_bone.matrix.to_scale().copy(),
                    }
                )
        particle_cursor += len(bone_names)
    return records


def _init_axis_local_rest(pose_bone) -> mathutils.Vector:
    """骨骼 rest pose 方向（armature object space 单位向量）。

    用 pose_bone.bone.tail_local - head_local（编辑骨位置），
    不受 matrix_basis 写回影响，确保跳帧归位时方向正确。
    """
    bone = pose_bone.bone
    axis = mathutils.Vector(bone.tail_local) - mathutils.Vector(bone.head_local)
    if axis.length <= EPSILON:
        return mathutils.Vector((0.0, 1.0, 0.0))
    return axis.normalized()


def _target_matrix_for_record(
    armature_obj: bpy.types.Object,
    record: dict,
    display_positions: np.ndarray,
    rotational_interpolation: float,
    target_pose_matrices: dict,
) -> mathutils.Matrix | None:
    """根据模拟后的粒子方向生成目标 pose-space matrix。

    方向 = 子粒子 - 自身粒子（叶子骨用父方向外推）。
    只改旋转，保留初始缩放。rotational_interpolation 控制 lerp（0=保持初始朝向，1=完全跟随）。
    """
    pose_bone = record["pose_bone"]
    matrix_world = armature_obj.matrix_world
    particle_index = record["particle_index"]
    child_particle = record["child_particle"]
    parent_particle = record["parent_particle"]

    head_world = mathutils.Vector(display_positions[particle_index])

    if child_particle >= 0:
        next_world = mathutils.Vector(display_positions[child_particle])
        direction_world = next_world - head_world
    elif parent_particle >= 0:
        # 叶子骨：用父→自身方向外推
        prev_world = mathutils.Vector(display_positions[parent_particle])
        direction_world = head_world - prev_world
    else:
        return None

    if direction_world.length <= EPSILON:
        return None

    # 世界方向转回 armature object space
    desired_direction_local = matrix_world.inverted().to_3x3() @ direction_world
    if desired_direction_local.length <= EPSILON:
        return None
    desired_direction_local.normalize()

    init_axis_local = record["init_axis_local"]
    init_rotation = record["init_rotation"]
    init_scale = record["init_scale"]

    rotation_delta = init_axis_local.rotation_difference(desired_direction_local)
    ratio = max(0.0, min(1.0, float(rotational_interpolation)))
    if ratio < 1.0:
        rotation_delta = mathutils.Quaternion().slerp(rotation_delta, ratio)

    # head 位置：root 用当前 pose head，非 root 由父目标矩阵推出（保持 connected 关系）
    parent = record.get("parent")
    if parent is not None and record.get("parent_rest_inv") is not None:
        parent_matrix = target_pose_matrices.get(record.get("parent_name") or "")
        if parent_matrix is not None:
            head_pose = (parent_matrix @ record["parent_rest_inv"] @ record["bone_rest"]).translation
        else:
            head_pose = matrix_world.inverted() @ head_world
    else:
        head_pose = matrix_world.inverted() @ head_world

    return mathutils.Matrix.LocRotScale(
        head_pose,
        rotation_delta @ init_rotation,
        init_scale,
    )


def write_bone_rotations(
    armature_obj: bpy.types.Object,
    records: list[dict],
    display_positions: np.ndarray,
    rotational_interpolation: float,
    write_runtime: dict | None = None,
) -> None:
    """把 display_positions 写回骨骼旋转（matrix_basis 批量写）。

    按深度升序处理，保证父骨的目标矩阵先算好，供子骨 head 定位复用。
    """
    if not records:
        return

    display = np.ascontiguousarray(display_positions, dtype=np.float32)
    # depth=0 是 root/FIXED 骨，由动画控制，物理不写回旋转。
    # 写回 root 骨会改变其 tail 位置，移动子骨 head，破坏下一帧的基准。
    ordered = sorted(
        [rec for rec in records if rec.get("depth", 0) > 0],
        key=lambda rec: rec["depth"],
    )

    # 第一遍：算出每根骨的目标 pose-space matrix
    target_pose_matrices: dict[str, mathutils.Matrix] = {}
    for record in ordered:
        target_matrix = _target_matrix_for_record(
            armature_obj,
            record,
            display,
            rotational_interpolation,
            target_pose_matrices,
        )
        if target_matrix is not None:
            target_pose_matrices[record["bone_name"]] = target_matrix

    # 第二遍：把目标矩阵转成 matrix_basis 批量写回
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

    fallback_updates: list[tuple] = []
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
                (rec["pose_bone"], _matrix_basis_from_target(rec, target_pose_matrices[rec["bone_name"]], target_pose_matrices))
                for rec in ordered
                if rec["bone_name"] in target_pose_matrices
            ]

    for pose_bone, basis_matrix in fallback_updates:
        pose_bone.matrix_basis = basis_matrix


def _matrix_basis_from_target(
    record: dict,
    target_matrix: mathutils.Matrix,
    target_pose_matrices: dict,
) -> mathutils.Matrix:
    """把目标 pose-space matrix 转成可写入的 matrix_basis。"""
    parent = record.get("parent")
    if parent is None or record.get("parent_rest_inv") is None:
        return record["bone_rest_inv"] @ target_matrix
    parent_matrix = target_pose_matrices.get(record.get("parent_name") or "")
    if parent_matrix is None:
        parent_matrix = parent.matrix
    parent_space = parent_matrix @ record["parent_rest_inv"] @ record["bone_rest"]
    return parent_space.inverted() @ target_matrix


def _pack_matrix_into(basis_values: list, offset: int, matrix: mathutils.Matrix) -> None:
    """按 Blender foreach_set 期望的列主序把 4x4 矩阵写入扁平列表。"""
    basis_values[offset + 0] = float(matrix[0][0])
    basis_values[offset + 1] = float(matrix[1][0])
    basis_values[offset + 2] = float(matrix[2][0])
    basis_values[offset + 3] = float(matrix[3][0])
    basis_values[offset + 4] = float(matrix[0][1])
    basis_values[offset + 5] = float(matrix[1][1])
    basis_values[offset + 6] = float(matrix[2][1])
    basis_values[offset + 7] = float(matrix[3][1])
    basis_values[offset + 8] = float(matrix[0][2])
    basis_values[offset + 9] = float(matrix[1][2])
    basis_values[offset + 10] = float(matrix[2][2])
    basis_values[offset + 11] = float(matrix[3][2])
    basis_values[offset + 12] = float(matrix[0][3])
    basis_values[offset + 13] = float(matrix[1][3])
    basis_values[offset + 14] = float(matrix[2][3])
    basis_values[offset + 15] = float(matrix[3][3])


def restore_initial_pose(armature_obj: bpy.types.Object, records: list[dict]) -> None:
    """把记录里的初始 pose 还原到骨骼（reset / 跳帧冷启动用）。"""
    for record in records:
        pose_bone = record.get("pose_bone")
        if pose_bone is None:
            continue
        try:
            pose_bone.matrix_basis = mathutils.Matrix.Identity(4)
        except Exception:
            pass
