"""PoseBone 写回相关的通用矩阵辅助函数。"""

from __future__ import annotations


def matrix_basis_from_pose_matrix(pose_bone, target_matrix, target_pose_matrices=None):
    target_pose_matrices = target_pose_matrices or {}
    bone_rest = pose_bone.bone.matrix_local
    parent = getattr(pose_bone, "parent", None)
    if parent is None:
        return bone_rest.inverted() @ target_matrix

    parent_matrix = target_pose_matrices.get(parent.name)
    if parent_matrix is None:
        parent_matrix = parent.matrix
    parent_rest = parent.bone.matrix_local
    parent_space = parent_matrix @ parent_rest.inverted() @ bone_rest
    return parent_space.inverted() @ target_matrix
