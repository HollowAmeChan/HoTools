"""统一物理世界的 solver 声明 registry。"""

from __future__ import annotations

from copy import deepcopy

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
    RIGID_JOLT_WORLD_SETTING_OBJECT_TAG,
    SPRING_VRM_CHAIN_OBJECT_TAG,
    SPRING_VRM_POSE_CHANNEL,
    SPRING_VRM_SLOT_KIND,
    SPRING_VRM_SOLVER_ID,
    SPRING_VRM_STATS_CHANNEL,
    SPRING_VRM_STEP_WRITER_ID,
)


SOLVER_DECLARATION_REQUIRED_KEYS = (
    "solver_id",
    "slot_kind",
    "stage",
    "consumes",
    "produces",
    "persistent_state",
    "dirty_keys",
    "same_frame_policy",
    "update_policy",
    "writeback",
)


BONE_COLLISION_CAPABILITY_ID = "bone_collision"


# 骨骼碰撞是解算器/领域能力，不是某一种属性存储格式。
#
# 当前显式界面存储仍然落在 Bone.hotools_collision 上。新的隐式覆写对象必须引用
# 同一份能力表，不能另抄一套独立字段结构。等测试证明行为完全对齐后，旧的显式
# 属性组应迁到这张表后面，只保留为生成层或适配层。
BONE_COLLISION_CAPABILITY = {
    "capability_id": BONE_COLLISION_CAPABILITY_ID,
    "display_name": "骨骼碰撞",
    "semantic_owner": "physicsWorld solver 能力表",
    "legacy_explicit_storage": "Bone.hotools_collision",
    "identity_input": "_OmniBone 骨骼 socket 值；内部从 socket 解析 armature 与 bone name",
    "supported_interfaces": {
        "explicit_legacy_property": {
            "storage": "Bone.hotools_collision",
            "status": "legacy_authoring_fallback",
        },
        "implicit_override_object": {
            "tag": BONE_COLLISION_OVERRIDE_OBJECT_TAG,
            "status": "planned",
            "input": "_OmniBone 骨骼 socket；armature 与 bone name 从 socket 值解析",
            "stable_id": (
                f"{BONE_COLLISION_OVERRIDE_OBJECT_TAG}:"
                "{armature_ptr}:{armature_data_ptr}:{bone_name}"
            ),
            "conflict_policy": "same_tag_and_stable_id_last_writer_wins",
        },
    },
    "fields": [
        {
            "name": "pin",
            "type": "bool",
            "default": False,
            "legacy_property": "Bone.hotools_collision.pin",
            "update_policy": "restart_only",
            "consumer_note": "SpringBone 在状态重建时读取非 root 骨骼 pin。",
        },
        {
            "name": "collision_type",
            "type": "enum",
            "values": ["NONE", "SPHERE", "CAPSULE"],
            "default": "NONE",
            "legacy_property": "Bone.hotools_collision.collision_type",
            "update_policy": "dirty_only_if_used_by_bone_collider_snapshot",
        },
        {
            "name": "radius",
            "type": "float",
            "default": 0.05,
            "legacy_property": "Bone.hotools_collision.radius",
            "update_policy": "dirty_only_or_restart_only_legacy_cpp",
            "consumer_note": "SpringBone 将该字段映射到 native hit_radii。",
        },
        {
            "name": "length",
            "type": "float",
            "default": 0.2,
            "legacy_property": "Bone.hotools_collision.length",
            "update_policy": "dirty_only_if_used_by_bone_collider_snapshot",
        },
        {
            "name": "offset",
            "type": "float3",
            "default": (0.0, 0.0, 0.0),
            "legacy_property": "Bone.hotools_collision.offset",
            "update_policy": "dirty_only_if_used_by_bone_collider_snapshot",
        },
        {
            "name": "primary_collision_group",
            "type": "int",
            "default": 1,
            "legacy_property": "Bone.hotools_collision.primary_collision_group",
            "update_policy": "dirty_only_if_used_by_bone_collider_snapshot",
        },
        {
            "name": "collided_by_groups",
            "type": "bitmask",
            "default": 0,
            "legacy_property": "Bone.hotools_collision.collided_by_groups",
            "update_policy": "dirty_only_or_restart_only_legacy_cpp",
            "consumer_note": "SpringBone 将该字段映射到 native collided_by_groups。",
        },
    ],
}


# SpringBone 更新频率权威表。
#
# 这张表必须留在代码里，保证 solver 声明、debug 视图、未来节点生成器和迁移测试
# 审查的是同一份策略。设计文档只能镜像这张表，不能成为另一份事实源。
SPRING_VRM_UPDATE_FREQUENCY_TABLE = [
    {
        "data": "frame / dt",
        "source": "PhysicsWorldCache.frame_context",
        "policy": "every_frame",
    },
    {
        "data": "chain root / bones",
        "source": f'world.implicit_objects["{SPRING_VRM_CHAIN_OBJECT_TAG}"]',
        "policy": "implicit_object_dirty",
    },
    {
        "data": "stiffness / drag / gravity",
        "source": f'world.implicit_objects["{SPRING_VRM_CHAIN_OBJECT_TAG}"]',
        "policy": "implicit_object_dirty",
    },
    {
        "data": "pose head / tail / parent target pose",
        "source": "PoseBone frame input",
        "policy": "every_frame",
    },
    {
        "data": "current_tail / prev_tail",
        "source": "slot.data.frame_state",
        "policy": "every_frame_mutate_in_place",
    },
    {
        "data": "initial axis / rotation / scale",
        "source": "slot.data.native_context static arrays",
        "policy": "restart_only",
    },
    {
        "data": "parent_indices / use_connect",
        "source": "armature topology",
        "policy": "topology_dirty",
    },
    {
        "data": "bone_collision.pin",
        "source": BONE_COLLISION_CAPABILITY_ID,
        "policy": "restart_only",
    },
    {
        "data": "bone_collision.radius -> hit_radii",
        "source": BONE_COLLISION_CAPABILITY_ID,
        "policy": "dirty_only_recommended_or_restart_only_legacy_cpp",
    },
    {
        "data": "bone_collision.collided_by_groups",
        "source": BONE_COLLISION_CAPABILITY_ID,
        "policy": "dirty_only_recommended_or_restart_only_legacy_cpp",
    },
    {
        "data": "object/bone colliders",
        "source": "PhysicsWorldCache.collider_snapshot",
        "policy": "every_frame_by_world_begin",
    },
    {
        "data": "collider arrays (spring_vrm_cpp ABI)",
        "source": "solver slot lazy collider array cache",
        "policy": "lazy_on_access",
    },
    {
        "data": "writeback plan / basis foreach buffer",
        "source": "slot.data.writeback_plan",
        "policy": "topology_dirty_or_restart_only_allocation",
    },
]


SPRING_VRM_SOLVER_DECLARATION = {
    "solver_id": SPRING_VRM_SOLVER_ID,
    "slot_kind": SPRING_VRM_SLOT_KIND,
    "stage": "spring_vrm_world_vertical_slice",
    "native_strategy": "cpp_only_no_python_runtime_backend",
    "nodes": [
        "VRM骨链属性",
        "VRM骨链对象注册",
        "SpringBone VRM模拟步",
    ],
    "planned_nodes": [
        "骨骼碰撞覆写属性",
        "骨骼碰撞覆写注册",
    ],
    "writers": [
        SPRING_VRM_STEP_WRITER_ID,
        SPRING_VRM_SOLVER_ID,
    ],
    "consumes": [
        "PhysicsWorldCache.frame_context",
        "PhysicsWorldCache.collider_snapshot",
        f'world.implicit_objects["{SPRING_VRM_CHAIN_OBJECT_TAG}"]',
        f"capability[{BONE_COLLISION_CAPABILITY_ID}] via legacy Bone.hotools_collision fallback",
        f"planned capability[{BONE_COLLISION_CAPABILITY_ID}] override via "
        f'world.implicit_objects["{BONE_COLLISION_OVERRIDE_OBJECT_TAG}"]',
    ],
    "produces": [
        f'world.result_streams["{SPRING_VRM_POSE_CHANNEL}"]',
        f'world.result_streams["{SPRING_VRM_STATS_CHANNEL}"]',
    ],
    "persistent_state": [
        "slot.data.frame_state",
        "slot.data.native_context",
        "slot.data.writeback_plan",
    ],
    "dirty_keys": [
        "world.generation",
        "armature_ptr",
        "armature_data_ptr",
        "implicit_object.signature",
        "implicit_object.version",
        f'world.implicit_objects["{BONE_COLLISION_OVERRIDE_OBJECT_TAG}"].signature',
        "Bone.hotools_collision capability fallback hash",
        "collider_snapshot.source_key",
        "native_layout_version",
    ],
    "same_frame_policy": "skip_republish_cached_results",
    "update_policy": {
        "implicit_objects": "lazy_by_tag_stable_id_signature",
        "topology": "rebuild_slot_on_armature_or_chain_topology_change",
        "params": "refresh_native_arrays_without_python_solver_backend",
        "bone_collision_profile": "resolve_capability_override_then_legacy_property_then_default",
        "colliders": "sample_world_collider_snapshot_each_step",
        "same_frame": "republish_last_pose_results_no_time_step",
    },
    "capabilities": {
        BONE_COLLISION_CAPABILITY_ID: BONE_COLLISION_CAPABILITY,
    },
    "update_frequency_table": SPRING_VRM_UPDATE_FREQUENCY_TABLE,
    "implicit_objects": {
        "consumes": [SPRING_VRM_CHAIN_OBJECT_TAG],
        "planned": [BONE_COLLISION_OVERRIDE_OBJECT_TAG],
        "entry_kind": "spring_vrm_chain",
        "producer_nodes": ["VRM骨链对象注册"],
        "planned_producer_nodes": ["骨骼碰撞覆写注册"],
        "update_policy": "lazy_by_signature",
        "conflict_policy": "same_tag_and_stable_id_last_writer_wins",
        "capability_binding": {
            BONE_COLLISION_OVERRIDE_OBJECT_TAG: BONE_COLLISION_CAPABILITY_ID,
        },
    },
    "writeback": {
        "owner": "physicsWorld.writeback",
        "target": "PoseBone.matrix_basis",
        "solver_inline_writeback": False,
        "update_tag_owner": "writeback.apply",
    },
    "export": {
        "result_channels": [SPRING_VRM_POSE_CHANNEL, SPRING_VRM_STATS_CHANNEL],
        "supports_bake": False,
    },
    "legacy_policy": "rewrite_only_no_compatibility",
}


RIGID_SOLVER_DECLARATION = {
    "solver_id": RIGID_SOLVER_ID,
    "slot_kind": [RIGID_BODY_SLOT_KIND, RIGID_CONSTRAINT_SLOT_KIND],
    "stage": "jolt_vertical_slice",
    "native_strategy": "jolt_backend_with_python_world_glue",
    "nodes": [
        "刚体注册",
        "刚体约束注册",
        "刚体世界-Jolt设置属性",
        "刚体世界-Jolt设置注册",
        "刚体生成约束属性",
        "刚体生成约束注册",
        "刚体模拟步",
    ],
    "writers": [
        RIGID_BODY_REGISTER_WRITER_ID,
        RIGID_CONSTRAINT_REGISTER_WRITER_ID,
        JOLT_STEP_WRITER_ID,
    ],
    "consumes": [
        "PhysicsWorldCache.frame_context",
        "RigidBodySpec from solver slots",
        "ConstraintSpec from solver slots",
        f'world.implicit_objects["{RIGID_JOLT_WORLD_SETTING_OBJECT_TAG}"]',
        f'world.implicit_objects["{RIGID_GENERATED_CONSTRAINT_OBJECT_TAG}"]',
        f'world.exchange["{RIGID_BODY_COMMANDS_CHANNEL}"]',
    ],
    "produces": [
        f'world.result_streams["{RIGID_TRANSFORM_CHANNEL}"]',
        f'world.result_streams["{RIGID_SOLVER_STATS_CHANNEL}"]',
    ],
    "persistent_state": [
        f'world.backend_resources["{RIGID_BACKEND_RESOURCE_KEY}"]',
        "slot.data.spec",
        "slot.data._jolt_generation",
        "slot.data._jolt_kinematic_pose_dirty",
    ],
    "dirty_keys": [
        "world.generation",
        "frame_context.restart_required",
        "RigidBodySpec.signature",
        "ConstraintSpec.signature",
        f'world.implicit_objects["{RIGID_JOLT_WORLD_SETTING_OBJECT_TAG}"].signature',
        f'world.implicit_objects["{RIGID_GENERATED_CONSTRAINT_OBJECT_TAG}"].signature',
        f'world.exchange["{RIGID_BODY_COMMANDS_CHANNEL}"]',
    ],
    "same_frame_policy": "sync_pending_or_publish_cached_transforms_no_step",
    "update_policy": {
        "body_spec": "sync_to_jolt_when_generation_or_signature_changes",
        "constraint_spec": "sync_to_jolt_when_generation_or_signature_changes",
        "kinematic_pose": "update_without_time_step_when_same_frame",
        "jolt_world_settings": "sync_to_jolt_adapter_by_implicit_object_signature",
        "commands": "consume_once_per_generation_frame_token",
        "same_frame": "publish_cached_transforms_no_time_step_unless_pending_sync",
    },
    "implicit_objects": {
        "consumes": [
            RIGID_JOLT_WORLD_SETTING_OBJECT_TAG,
            RIGID_GENERATED_CONSTRAINT_OBJECT_TAG,
        ],
        "planned": [
            RIGID_MATERIAL_PRESET_OBJECT_TAG,
            RIGID_RAGDOLL_PROXY_OBJECT_TAG,
        ],
        "entry_kind": "rigid_generated_object_or_jolt_world_setting",
        "producer_nodes": ["刚体世界-Jolt设置注册", "刚体生成约束注册"],
        "update_policy": "lazy_by_tag_stable_id_signature",
        "conflict_policy": "same_tag_and_stable_id_last_writer_wins",
    },
    "writeback": {
        "owner": "physicsWorld.writeback",
        "target": "Object.delta_transform",
        "solver_inline_writeback": False,
        "update_tag_owner": "writeback.apply",
    },
    "export": {
        "result_channels": [RIGID_TRANSFORM_CHANNEL, RIGID_SOLVER_STATS_CHANNEL],
        "supports_bake": False,
    },
    "legacy_policy": "new_world_only_no_compatibility",
}


_BUILTIN_SOLVER_DECLARATIONS = {
    SPRING_VRM_SOLVER_ID: SPRING_VRM_SOLVER_DECLARATION,
    RIGID_SOLVER_ID: RIGID_SOLVER_DECLARATION,
}

_RUNTIME_SOLVER_DECLARATIONS: dict[str, dict] = {}


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def normalize_solver_declaration(declaration: dict) -> dict:
    """返回声明的深拷贝，并把常用单值字段整理成稳定形态。"""
    data = deepcopy(declaration) if isinstance(declaration, dict) else {}
    if "slot_kind" in data:
        data["slot_kind"] = _as_list(data.get("slot_kind"))
    for key in ("consumes", "produces", "persistent_state", "dirty_keys", "writers", "nodes", "planned_nodes"):
        if key in data:
            data[key] = _as_list(data.get(key))
    implicit = data.get("implicit_objects")
    if isinstance(implicit, dict):
        implicit["consumes"] = _as_list(implicit.get("consumes"))
        implicit["planned"] = _as_list(implicit.get("planned"))
        implicit["producer_nodes"] = _as_list(implicit.get("producer_nodes"))
        implicit["planned_producer_nodes"] = _as_list(implicit.get("planned_producer_nodes"))
    return data


def validate_solver_declaration(declaration: dict) -> list[str]:
    """校验 solver 声明的最小结构，供 debug 节点和迁移审查使用。"""
    problems: list[str] = []
    data = normalize_solver_declaration(declaration)

    for key in SOLVER_DECLARATION_REQUIRED_KEYS:
        if key not in data:
            problems.append(f"missing required key: {key}")

    solver_id = str(data.get("solver_id") or "").strip()
    if not solver_id:
        problems.append("solver_id is empty")

    if not data.get("slot_kind"):
        problems.append("slot_kind is empty")

    if not data.get("consumes"):
        problems.append("consumes is empty")

    if not data.get("produces"):
        problems.append("produces is empty")

    writeback = data.get("writeback")
    if not isinstance(writeback, dict):
        problems.append("writeback must be a dict")
    elif writeback.get("solver_inline_writeback") is not False:
        problems.append("writeback.solver_inline_writeback must be False")

    implicit = data.get("implicit_objects")
    if implicit is not None and not isinstance(implicit, dict):
        problems.append("implicit_objects must be a dict when present")

    return problems


def register_solver_declaration(declaration: dict) -> dict:
    """注册运行时 solver 声明；未来外部 solver 接入时使用。"""
    data = normalize_solver_declaration(declaration)
    solver_id = str(data.get("solver_id") or "").strip()
    if not solver_id:
        raise ValueError("solver declaration requires solver_id")
    _RUNTIME_SOLVER_DECLARATIONS[solver_id] = data
    return deepcopy(data)


def unregister_solver_declaration(solver_id: str) -> None:
    _RUNTIME_SOLVER_DECLARATIONS.pop(str(solver_id), None)


def get_solver_declaration(solver_id: str) -> dict | None:
    solver_key = str(solver_id or "")
    declaration = _RUNTIME_SOLVER_DECLARATIONS.get(solver_key)
    if declaration is None:
        declaration = _BUILTIN_SOLVER_DECLARATIONS.get(solver_key)
    if declaration is None:
        return None
    return normalize_solver_declaration(declaration)


def all_solver_declarations() -> dict[str, dict]:
    declarations: dict[str, dict] = {}
    for solver_id, declaration in _BUILTIN_SOLVER_DECLARATIONS.items():
        declarations[str(solver_id)] = normalize_solver_declaration(declaration)
    for solver_id, declaration in _RUNTIME_SOLVER_DECLARATIONS.items():
        declarations[str(solver_id)] = normalize_solver_declaration(declaration)
    return declarations


def solver_declaration_summary(declaration: dict) -> dict:
    data = normalize_solver_declaration(declaration)
    writeback = data.get("writeback") if isinstance(data.get("writeback"), dict) else {}
    implicit = data.get("implicit_objects") if isinstance(data.get("implicit_objects"), dict) else {}
    capabilities = data.get("capabilities") if isinstance(data.get("capabilities"), dict) else {}
    update_frequency = data.get("update_frequency_table") if isinstance(data.get("update_frequency_table"), list) else []
    return {
        "solver_id": data.get("solver_id", ""),
        "stage": data.get("stage", ""),
        "slot_kind": list(data.get("slot_kind") or []),
        "native_strategy": data.get("native_strategy", ""),
        "nodes": list(data.get("nodes") or []),
        "planned_nodes": list(data.get("planned_nodes") or []),
        "consumes": list(data.get("consumes") or []),
        "produces": list(data.get("produces") or []),
        "persistent_state": list(data.get("persistent_state") or []),
        "dirty_keys": list(data.get("dirty_keys") or []),
        "same_frame_policy": data.get("same_frame_policy", ""),
        "implicit_object_tags": list(implicit.get("consumes") or []),
        "planned_implicit_object_tags": list(implicit.get("planned") or []),
        "implicit_object_update_policy": implicit.get("update_policy", ""),
        "capability_ids": list(capabilities.keys()),
        "update_frequency_count": len(update_frequency),
        "writeback_target": writeback.get("target", ""),
        "writeback_owner": writeback.get("owner", ""),
        "solver_inline_writeback": writeback.get("solver_inline_writeback"),
        "result_channels": list((data.get("export") or {}).get("result_channels") or []),
    }


def solver_declarations_debug_snapshot() -> dict:
    declarations = all_solver_declarations()
    solvers: dict[str, dict] = {}
    problems: dict[str, list[str]] = {}

    for solver_id, declaration in declarations.items():
        solvers[solver_id] = solver_declaration_summary(declaration)
        solver_problems = validate_solver_declaration(declaration)
        if solver_problems:
            problems[solver_id] = solver_problems

    return {
        "count": len(solvers),
        "required_keys": list(SOLVER_DECLARATION_REQUIRED_KEYS),
        "solvers": solvers,
        "problems": problems,
    }
