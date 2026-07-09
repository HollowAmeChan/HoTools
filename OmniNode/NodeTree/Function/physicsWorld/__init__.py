# physicsWorld - 统一物理世界包
#
# 目录语义：
#   types.py        - PhysicsWorldCache、FrameContext、Scope、SolverSlot
#   scope.py        - 对象列表合并、过滤、去重、作用域 key
#   world.py        - World Begin / Commit / collider snapshot / 生命周期
#   debug.py        - 调试快照、文本展开、状态校验
#   declarations.py - solver 声明 registry 和迁移审查入口
#   nodes.py        - 对外暴露的通用函数节点
#   names.py        - solver/channel/backend/implicit object 全局名称常量
#   utils/          - 新物理世界通用数学、id、buffer 辅助函数
#   rigid/          - 刚体 / Jolt domain
#   spring_vrm/     - VRM SpringBone 重写 domain

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
from .declarations import (
    BONE_COLLISION_CAPABILITY,
    BONE_COLLISION_CAPABILITY_ID,
    RIGID_SOLVER_DECLARATION,
    SOLVER_DECLARATION_REQUIRED_KEYS,
    SPRING_VRM_SOLVER_DECLARATION,
    SPRING_VRM_UPDATE_FREQUENCY_TABLE,
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
    BONE_COLLISION_OVERRIDE_OBJECT_TAG,
    JOLT_STEP_WRITER_ID,
    RIGID_BACKEND_RESOURCE_KEY,
    RIGID_BODY_COMMANDS_CHANNEL,
    RIGID_BODY_REGISTER_WRITER_ID,
    RIGID_BODY_SLOT_KIND,
    RIGID_CONSTRAINT_REGISTER_WRITER_ID,
    RIGID_CONSTRAINT_SLOT_KIND,
    RIGID_GENERATED_CONSTRAINT_OBJECT_TAG,
    RIGID_MATERIAL_PRESET_OBJECT_TAG,
    RIGID_RAGDOLL_PROXY_OBJECT_TAG,
    RIGID_SOLVER_ID,
    RIGID_SOLVER_STATS_CHANNEL,
    RIGID_TRANSFORM_CHANNEL,
    SPRING_VRM_CHAIN_OBJECT_TAG,
    SPRING_VRM_POSE_CHANNEL,
    SPRING_VRM_SLOT_KIND,
    SPRING_VRM_SOLVER_ID,
    SPRING_VRM_STATS_CHANNEL,
    SPRING_VRM_STEP_WRITER_ID,
)

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
    # declarations
    "BONE_COLLISION_CAPABILITY",
    "BONE_COLLISION_CAPABILITY_ID",
    "RIGID_SOLVER_DECLARATION",
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
    "BONE_COLLISION_OVERRIDE_OBJECT_TAG",
    "JOLT_STEP_WRITER_ID",
    "RIGID_BACKEND_RESOURCE_KEY",
    "RIGID_BODY_COMMANDS_CHANNEL",
    "RIGID_BODY_REGISTER_WRITER_ID",
    "RIGID_BODY_SLOT_KIND",
    "RIGID_CONSTRAINT_REGISTER_WRITER_ID",
    "RIGID_CONSTRAINT_SLOT_KIND",
    "RIGID_GENERATED_CONSTRAINT_OBJECT_TAG",
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
