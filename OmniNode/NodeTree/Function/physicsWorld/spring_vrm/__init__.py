# physicsWorld.spring_vrm - 统一物理世界里的 VRM SpringBone 领域
#
# 这是 VRM SpringBone 的新物理世界重写入口。旧 Physics.py 解算器
# 只作为审查和数值参考来源，不作为兼容层迁入。
#
#   specs.py       - 从节点输入构建稳定的 SpringVRM 规格
#   solver.py      - 把规格注册进 PhysicsWorldCache 解算器槽
#   results.py     - 纯快照结果流辅助函数
#   implicit_objects.py - VRM 骨链隐式对象注册入口
#   declaration.py - 解算器契约和旧实现丢弃审查清单

from .declaration import (
    SPRING_VRM_LEGACY_DISCARD_AUDIT,
    SPRING_VRM_SOLVER_DECLARATION,
)
from .results import (
    SPRING_VRM_POSE_CHANNEL,
    SPRING_VRM_SOLVER_ID,
    SPRING_VRM_STATS_CHANNEL,
    clear_spring_vrm_pose_results,
    clear_spring_vrm_stats_results,
    get_spring_vrm_stats_result,
    iter_spring_vrm_pose_results,
    iter_spring_vrm_stats_results,
    make_spring_vrm_pose_result,
    make_spring_vrm_stats_result,
    publish_spring_vrm_pose_result,
    publish_spring_vrm_stats_result,
)
from .solver import (
    SPRING_VRM_SLOT_KIND,
    register_spring_vrm_from_chain_properties,
    register_spring_vrm_specs,
    step_spring_vrm,
)
from .implicit_objects import (
    SPRING_VRM_OBJECT_REGISTER_PRODUCER,
    bone_chains_from_bone_values,
    collect_spring_vrm_chain_objects,
    make_spring_vrm_chain_properties,
    normalize_spring_vrm_chain_objects,
    register_spring_vrm_chain_objects,
    spring_vrm_chain_object_signature,
    spring_vrm_chain_object_stable_id,
)
from .specs import (
    SpringVRMChainSpec,
    SpringVRMSolverSpec,
    build_spring_vrm_solver_specs,
    make_spring_vrm_slot_id,
    normalize_spring_vrm_chain_properties,
)
from ..names import SPRING_VRM_CHAIN_OBJECT_TAG

__all__ = [
    "SPRING_VRM_LEGACY_DISCARD_AUDIT",
    "SPRING_VRM_POSE_CHANNEL",
    "SPRING_VRM_CHAIN_OBJECT_TAG",
    "SPRING_VRM_OBJECT_REGISTER_PRODUCER",
    "SPRING_VRM_SLOT_KIND",
    "SPRING_VRM_SOLVER_DECLARATION",
    "SPRING_VRM_SOLVER_ID",
    "SPRING_VRM_STATS_CHANNEL",
    "SpringVRMChainSpec",
    "SpringVRMSolverSpec",
    "bone_chains_from_bone_values",
    "build_spring_vrm_solver_specs",
    "clear_spring_vrm_pose_results",
    "clear_spring_vrm_stats_results",
    "get_spring_vrm_stats_result",
    "iter_spring_vrm_pose_results",
    "iter_spring_vrm_stats_results",
    "make_spring_vrm_pose_result",
    "make_spring_vrm_slot_id",
    "make_spring_vrm_stats_result",
    "make_spring_vrm_chain_properties",
    "normalize_spring_vrm_chain_properties",
    "normalize_spring_vrm_chain_objects",
    "collect_spring_vrm_chain_objects",
    "publish_spring_vrm_pose_result",
    "publish_spring_vrm_stats_result",
    "register_spring_vrm_chain_objects",
    "register_spring_vrm_from_chain_properties",
    "register_spring_vrm_specs",
    "spring_vrm_chain_object_signature",
    "spring_vrm_chain_object_stable_id",
    "step_spring_vrm",
]
