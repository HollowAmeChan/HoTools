# physicsWorld.spring_vrm - 统一物理世界里的 VRM SpringBone 领域
#
# 包初始化必须保持轻量。根级 physicsWorld.names 会兼容重导出 spring_vrm.names；
# 如果这里提前导入 solver/native，会在插件启用时形成 names -> spring_vrm -> native
# -> names 的循环导入。
#
#   names.py       - SpringBone 自有 id / channel / tag 常量
#   capabilities.py - SpringBone 自有能力表和更新频率表
#   declaration.py - 解算器契约和旧实现丢弃审查清单
#   specs.py       - 从节点输入构建稳定的 SpringVRM 规格
#   solver.py      - 把规格注册进 PhysicsWorldCache 解算器槽
#   results.py     - 纯快照结果流辅助函数
#   implicit_objects.py - VRM 骨链隐式对象注册入口

from __future__ import annotations

from importlib import import_module

from .capabilities import (
    BONE_COLLISION_CAPABILITY,
    BONE_COLLISION_CAPABILITY_ID,
    SPRING_VRM_UPDATE_FREQUENCY_TABLE,
)
from .declaration import (
    SPRING_VRM_LEGACY_DISCARD_AUDIT,
    SPRING_VRM_SOLVER_DECLARATION,
)
from .names import (
    BONE_COLLISION_OVERRIDE_OBJECT_TAG,
    SPRING_VRM_CHAIN_OBJECT_TAG,
    SPRING_VRM_POSE_CHANNEL,
    SPRING_VRM_SLOT_KIND,
    SPRING_VRM_SOLVER_ID,
    SPRING_VRM_STATS_CHANNEL,
    SPRING_VRM_STEP_WRITER_ID,
)


_LAZY_EXPORTS = {
    # results.py
    "clear_spring_vrm_pose_results": ".results",
    "clear_spring_vrm_stats_results": ".results",
    "get_spring_vrm_stats_result": ".results",
    "iter_spring_vrm_pose_results": ".results",
    "iter_spring_vrm_stats_results": ".results",
    "make_spring_vrm_pose_result": ".results",
    "make_spring_vrm_stats_result": ".results",
    "publish_spring_vrm_pose_result": ".results",
    "publish_spring_vrm_stats_result": ".results",
    # solver.py
    "register_spring_vrm_from_chain_properties": ".solver",
    "register_spring_vrm_specs": ".solver",
    "step_spring_vrm": ".solver",
    # implicit_objects.py
    "SPRING_VRM_OBJECT_REGISTER_PRODUCER": ".implicit_objects",
    "bone_chains_from_bone_values": ".implicit_objects",
    "collect_spring_vrm_chain_objects": ".implicit_objects",
    "make_spring_vrm_chain_properties": ".implicit_objects",
    "normalize_spring_vrm_chain_objects": ".implicit_objects",
    "register_spring_vrm_chain_objects": ".implicit_objects",
    "spring_vrm_chain_object_signature": ".implicit_objects",
    "spring_vrm_chain_object_stable_id": ".implicit_objects",
    # specs.py
    "SpringVRMChainSpec": ".specs",
    "SpringVRMSolverSpec": ".specs",
    "build_spring_vrm_solver_specs": ".specs",
    "make_spring_vrm_slot_id": ".specs",
    "normalize_spring_vrm_chain_properties": ".specs",
}


def __getattr__(name: str):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = [
    "BONE_COLLISION_CAPABILITY",
    "BONE_COLLISION_CAPABILITY_ID",
    "BONE_COLLISION_OVERRIDE_OBJECT_TAG",
    "SPRING_VRM_LEGACY_DISCARD_AUDIT",
    "SPRING_VRM_POSE_CHANNEL",
    "SPRING_VRM_CHAIN_OBJECT_TAG",
    "SPRING_VRM_OBJECT_REGISTER_PRODUCER",
    "SPRING_VRM_SLOT_KIND",
    "SPRING_VRM_SOLVER_DECLARATION",
    "SPRING_VRM_SOLVER_ID",
    "SPRING_VRM_STATS_CHANNEL",
    "SPRING_VRM_STEP_WRITER_ID",
    "SPRING_VRM_UPDATE_FREQUENCY_TABLE",
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
