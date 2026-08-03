"""PoseBone 写回相关的通用矩阵辅助函数。"""

from __future__ import annotations


def _parent_pose_matrix(
    pose_bone,
    target_pose_matrices,
    reference_pose_matrices,
):
    parent = getattr(pose_bone, "parent", None)
    if parent is None:
        return None
    parent_matrix = target_pose_matrices.get(parent.name)
    if parent_matrix is None:
        parent_matrix = reference_pose_matrices.get(parent.name)
    if parent_matrix is None:
        parent_matrix = parent.matrix.copy()
    return parent_matrix


def _convert_local_to_pose(
    pose_bone,
    matrix,
    *,
    parent_matrix=None,
    invert: bool,
):
    """调用 Blender 的 Bone 空间转换，并为纯宿主假对象保留最小回退。"""

    bone = pose_bone.bone
    converter = getattr(bone, "convert_local_to_pose", None)
    if callable(converter):
        kwargs = {"invert": bool(invert)}
        parent = getattr(pose_bone, "parent", None)
        if parent is not None:
            kwargs.update({
                "parent_matrix": parent_matrix,
                "parent_matrix_local": parent.bone.matrix_local,
            })
        return converter(matrix, bone.matrix_local, **kwargs)

    # 非 Blender 单元测试假对象没有 RNA 方法；真实运行必定走上面的原生路径。
    bone_rest = bone.matrix_local
    parent = getattr(pose_bone, "parent", None)
    if parent is None:
        return bone_rest.inverted() @ matrix if invert else bone_rest @ matrix
    parent_space = parent_matrix @ parent.bone.matrix_local.inverted() @ bone_rest
    return parent_space.inverted() @ matrix if invert else parent_space @ matrix


def pose_matrix_from_matrix_basis(
    pose_bone,
    matrix_basis,
    target_pose_matrices=None,
    reference_pose_matrices=None,
):
    """从逻辑 ``matrix_basis`` 重建最终 Pose 矩阵。

    Blender 原生转换会遵守 ``inherit_scale``、``use_local_location`` 等
    Bone 继承选项，避免手写父空间乘法只在默认骨骼设置下成立。
    """

    target_pose_matrices = target_pose_matrices or {}
    reference_pose_matrices = reference_pose_matrices or {}
    parent_matrix = _parent_pose_matrix(
        pose_bone,
        target_pose_matrices,
        reference_pose_matrices,
    )
    return _convert_local_to_pose(
        pose_bone,
        matrix_basis,
        parent_matrix=parent_matrix,
        invert=False,
    )


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
    parent_matrix = _parent_pose_matrix(
        pose_bone,
        target_pose_matrices,
        reference_pose_matrices,
    )
    return _convert_local_to_pose(
        pose_bone,
        target_matrix,
        parent_matrix=parent_matrix,
        invert=True,
    )
