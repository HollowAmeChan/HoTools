# physicsWorld.utils - 统一物理世界通用辅助函数
#
# 这里只放新物理世界实现中已经出现、且不属于某个 solver 算法的纯 helper。
# 旧 solver 中的函数必须先经过审查，再决定是否抽入这里。

from .ids import (
    as_pointer,
    data_pointer,
    make_typed_slot_id,
    stable_short_hash,
)
from .values import (
    float3,
    matrix16,
    matrix_from_16,
)
from .writeback_pose import matrix_basis_from_pose_matrix

__all__ = [
    "as_pointer",
    "data_pointer",
    "float3",
    "make_typed_slot_id",
    "matrix16",
    "matrix_basis_from_pose_matrix",
    "matrix_from_16",
    "stable_short_hash",
]
