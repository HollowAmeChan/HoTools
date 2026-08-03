"""PoseBone 写回相关的通用矩阵辅助函数。"""

from __future__ import annotations


def matrix_basis_from_pose_matrix(
    pose_bone,
    target_matrix,
    target_pose_matrices=None,
    reference_pose_matrices=None,
):
    """从最终 Pose 矩阵反算局部 basis。

    ``target_pose_matrices`` 是本次模拟输出的完整目标集合；当父骨不在
    模拟集合中时，使用写回前捕获的 ``reference_pose_matrices``，而不是
    读取已经被前一个骨骼写回影响的实时父级矩阵。
    """

    target_pose_matrices = target_pose_matrices or {}
    reference_pose_matrices = reference_pose_matrices or {}
    bone_rest = pose_bone.bone.matrix_local
    parent = getattr(pose_bone, "parent", None)
    if parent is None:
        return bone_rest.inverted() @ target_matrix

    parent_matrix = target_pose_matrices.get(parent.name)
    if parent_matrix is None:
        parent_matrix = reference_pose_matrices.get(parent.name)
    if parent_matrix is None:
        parent_matrix = parent.matrix.copy()
    parent_rest = parent.bone.matrix_local
    parent_space = parent_matrix @ parent_rest.inverted() @ bone_rest
    return parent_space.inverted() @ target_matrix
