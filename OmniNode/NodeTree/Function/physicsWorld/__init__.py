# physicsWorld - 统一物理世界包
#
# 目录语义：
#   types.py        - PhysicsWorldCache、FrameContext、Scope、SolverSlot
#   scope.py        - 对象列表合并、过滤、去重、作用域 key
#   world.py        - 物理世界 Begin / Commit / 碰撞快照 / 生命周期
#   debug.py        - 调试快照、文本展开、状态校验
#   registry.py     - 解算器子模块装载、回调汇总和运行入口
#   declarations.py - 解算器声明注册表和迁移审查入口
#   nodes.py        - 对外暴露的通用函数节点
#   names.py        - 解算器 / 通道 / 后端 / 隐式对象全局名称常量
#   utils/          - 新物理世界通用数学、身份、缓冲辅助函数
#   rigid/          - 刚体 / Jolt 领域
#   spring_vrm/     - VRM SpringBone 重写领域

from importlib import import_module

from .types import (
    PhysicsObjectScope,
    PhysicsFrameContext,
    PhysicsColliderSource,
    PhysicsSolverSlot,
    PhysicsWorldCache,
)
from .scope import (
    build_scope_key,
    dedupe_objects,
    merge_object_lists,
    objects_from_collection,
    filter_objects_by_type,
    make_scope,
    collect_physics_sources,
)
from .world import (
    physicsWorldBegin,
    physicsWorldCommit,
    build_collider_snapshot,
)
from .debug import (
    snapshot_to_text,
    result_items_to_text,
    validate_world,
    print_world_summary,
)
from .registry import (
    all_solver_module_descriptors,
    builtin_solver_domains,
    collect_scope_solver_specs,
    iter_scope_collectors,
    iter_scope_restart_handlers,
    iter_solver_declarations,
    register_solver_module,
    resolve_solver_declaration,
    run_scope_restart_handlers,
    unregister_solver_module,
)
from .declarations import (
    SOLVER_DECLARATION_REQUIRED_KEYS,
    all_solver_declarations,
    get_solver_declaration,
    normalize_solver_declaration,
    register_solver_declaration,
    solver_declaration_summary,
    solver_declarations_debug_snapshot,
    unregister_solver_declaration,
    validate_solver_declaration,
)
from .names import (
    BONE_TRANSFORM_CHANNEL,
    GN_ATTRIBUTE_CHANNEL,
    RIGID_BODY_DELTA_CHANNEL,
)


_COMPAT_EXPORTS = {
    "BONE_COLLISION_CAPABILITY": ".declarations",
    "BONE_COLLISION_CAPABILITY_ID": ".declarations",
    "RIGID_CAPABILITIES": ".declarations",
    "RIGID_SOLVER_DECLARATION": ".declarations",
    "RIGID_UPDATE_FREQUENCY_TABLE": ".declarations",
    "SPRING_VRM_SOLVER_DECLARATION": ".declarations",
    "SPRING_VRM_UPDATE_FREQUENCY_TABLE": ".declarations",
    "BONE_COLLISION_OVERRIDE_OBJECT_TAG": ".names",
    "JOLT_STEP_WRITER_ID": ".names",
    "RIGID_BACKEND_RESOURCE_KEY": ".names",
    "RIGID_BODY_COMMANDS_CHANNEL": ".names",
    "RIGID_BODY_REGISTER_WRITER_ID": ".names",
    "RIGID_BODY_SLOT_KIND": ".names",
    "RIGID_CONSTRAINT_REGISTER_WRITER_ID": ".names",
    "RIGID_CONSTRAINT_STATE_CHANNEL": ".names",
    "RIGID_CONSTRAINT_SLOT_KIND": ".names",
    "RIGID_DEBUG_DRAW_MODE": ".names",
    "RIGID_GENERATED_CONSTRAINT_OBJECT_TAG": ".names",
    "RIGID_JOLT_WORLD_SETTING_OBJECT_TAG": ".names",
    "RIGID_MATERIAL_PRESET_OBJECT_TAG": ".names",
    "RIGID_RAGDOLL_PROXY_OBJECT_TAG": ".names",
    "RIGID_SOLVER_ID": ".names",
    "RIGID_SOLVER_STATS_CHANNEL": ".names",
    "RIGID_TRANSFORM_CHANNEL": ".names",
    "SPRING_VRM_CHAIN_OBJECT_TAG": ".names",
    "SPRING_VRM_POSE_CHANNEL": ".names",
    "SPRING_VRM_SLOT_KIND": ".names",
    "SPRING_VRM_SOLVER_ID": ".names",
    "SPRING_VRM_STATS_CHANNEL": ".names",
    "SPRING_VRM_STEP_WRITER_ID": ".names",
}


def __getattr__(name: str):
    module_name = _COMPAT_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = [
    # types
    "PhysicsObjectScope",
    "PhysicsFrameContext",
    "PhysicsColliderSource",
    "PhysicsSolverSlot",
    "PhysicsWorldCache",
    # scope
    "build_scope_key",
    "dedupe_objects",
    "merge_object_lists",
    "objects_from_collection",
    "filter_objects_by_type",
    "make_scope",
    "collect_physics_sources",
    # world
    "physicsWorldBegin",
    "physicsWorldCommit",
    "build_collider_snapshot",
    # debug
    "snapshot_to_text",
    "result_items_to_text",
    "validate_world",
    "print_world_summary",
    # solver 装载器
    "all_solver_module_descriptors",
    "builtin_solver_domains",
    "collect_scope_solver_specs",
    "iter_scope_collectors",
    "iter_scope_restart_handlers",
    "iter_solver_declarations",
    "register_solver_module",
    "resolve_solver_declaration",
    "run_scope_restart_handlers",
    "unregister_solver_module",
    # 声明
    "BONE_COLLISION_CAPABILITY",
    "BONE_COLLISION_CAPABILITY_ID",
    "RIGID_CAPABILITIES",
    "RIGID_SOLVER_DECLARATION",
    "RIGID_UPDATE_FREQUENCY_TABLE",
    "SOLVER_DECLARATION_REQUIRED_KEYS",
    "SPRING_VRM_SOLVER_DECLARATION",
    "SPRING_VRM_UPDATE_FREQUENCY_TABLE",
    "all_solver_declarations",
    "get_solver_declaration",
    "normalize_solver_declaration",
    "register_solver_declaration",
    "solver_declaration_summary",
    "solver_declarations_debug_snapshot",
    "unregister_solver_declaration",
    "validate_solver_declaration",
    # names
    "BONE_TRANSFORM_CHANNEL",
    "BONE_COLLISION_OVERRIDE_OBJECT_TAG",
    "GN_ATTRIBUTE_CHANNEL",
    "JOLT_STEP_WRITER_ID",
    "RIGID_BODY_DELTA_CHANNEL",
    "RIGID_BACKEND_RESOURCE_KEY",
    "RIGID_BODY_COMMANDS_CHANNEL",
    "RIGID_BODY_REGISTER_WRITER_ID",
    "RIGID_BODY_SLOT_KIND",
    "RIGID_CONSTRAINT_REGISTER_WRITER_ID",
    "RIGID_CONSTRAINT_STATE_CHANNEL",
    "RIGID_CONSTRAINT_SLOT_KIND",
    "RIGID_DEBUG_DRAW_MODE",
    "RIGID_GENERATED_CONSTRAINT_OBJECT_TAG",
    "RIGID_JOLT_WORLD_SETTING_OBJECT_TAG",
    "RIGID_MATERIAL_PRESET_OBJECT_TAG",
    "RIGID_RAGDOLL_PROXY_OBJECT_TAG",
    "RIGID_SOLVER_ID",
    "RIGID_SOLVER_STATS_CHANNEL",
    "RIGID_TRANSFORM_CHANNEL",
    "SPRING_VRM_CHAIN_OBJECT_TAG",
    "SPRING_VRM_POSE_CHANNEL",
    "SPRING_VRM_SLOT_KIND",
    "SPRING_VRM_SOLVER_ID",
    "SPRING_VRM_STATS_CHANNEL",
    "SPRING_VRM_STEP_WRITER_ID",
]
