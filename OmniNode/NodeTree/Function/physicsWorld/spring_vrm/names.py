"""VRM SpringBone 解算器自有名称常量。"""

from ..collision.names import BONE_COLLISION_OVERRIDE_OBJECT_TAG

SPRING_VRM_SOLVER_ID = "spring_vrm"
SPRING_VRM_STEP_WRITER_ID = "spring_vrm_step"
SPRING_VRM_SLOT_KIND = "spring_vrm"
# 兼容别名：SpringBone 姿态输出现在发布到通用 bone_transform 写回通道。
SPRING_VRM_POSE_CHANNEL = "bone_transform"
SPRING_VRM_STATS_CHANNEL = "spring_vrm_stats"
SPRING_VRM_DEBUG_DRAW_MODE = "spring_vrm.debug"
