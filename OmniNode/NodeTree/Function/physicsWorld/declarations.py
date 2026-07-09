"""统一物理世界的 solver 声明 registry。"""

from __future__ import annotations

from copy import deepcopy
from importlib import import_module

from .names import (
    JOLT_STEP_WRITER_ID,
    RIGID_BACKEND_RESOURCE_KEY,
    RIGID_BODY_COMMANDS_CHANNEL,
    RIGID_BODY_REGISTER_WRITER_ID,
    RIGID_BODY_SLOT_KIND,
    RIGID_CONSTRAINT_REGISTER_WRITER_ID,
    RIGID_CONSTRAINT_SLOT_KIND,
    RIGID_GENERATED_CONSTRAINT_OBJECT_TAG,
    RIGID_JOLT_WORLD_SETTING_OBJECT_TAG,
    RIGID_MATERIAL_PRESET_OBJECT_TAG,
    RIGID_RAGDOLL_PROXY_OBJECT_TAG,
    RIGID_SOLVER_ID,
    RIGID_SOLVER_STATS_CHANNEL,
    RIGID_TRANSFORM_CHANNEL,
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


_SPRING_VRM_SOLVER_ID = "spring_vrm"
_SPRING_VRM_COMPAT_EXPORTS = {
    "BONE_COLLISION_CAPABILITY": ".spring_vrm.capabilities",
    "BONE_COLLISION_CAPABILITY_ID": ".spring_vrm.capabilities",
    "SPRING_VRM_UPDATE_FREQUENCY_TABLE": ".spring_vrm.capabilities",
    "SPRING_VRM_SOLVER_DECLARATION": ".spring_vrm.declaration",
}


def __getattr__(name: str):
    module_name = _SPRING_VRM_COMPAT_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name, __package__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def _load_spring_vrm_solver_declaration() -> dict:
    module = import_module(".spring_vrm.declaration", __package__)
    return module.SPRING_VRM_SOLVER_DECLARATION


RIGID_SOLVER_DECLARATION = {
    "solver_id": RIGID_SOLVER_ID,
    "slot_kind": [RIGID_BODY_SLOT_KIND, RIGID_CONSTRAINT_SLOT_KIND],
    "stage": "jolt_vertical_slice",
    "native_strategy": "jolt_backend_with_python_world_glue",
    # 节点名必须与 rigid/nodes.py 的 bl_label 一致。旧的"刚体注册/刚体约束注册"
    # 独立节点已并入 physicsWorldBegin（对象范围自动登记刚体/约束），不再作为节点存在；
    # 这里只列真实存在的 rigid 节点，避免 debug snapshot 展示幽灵节点。
    "nodes": [
        "刚体模拟步",
        "刚体结果-读取状态",
        "刚体世界-Jolt设置属性",
        "刚体世界-Jolt设置注册",
        "刚体生成约束属性",
        "刚体生成约束注册",
        "刚体命令-设置速度",
        "刚体命令-施加力",
        "刚体命令-施加冲量",
        "刚体命令-重力倍率",
        "刚体命令-材质响应",
        "刚体命令-运动质量",
        "刚体命令-激活状态",
    ],
    "writers": [
        RIGID_BODY_REGISTER_WRITER_ID,
        RIGID_CONSTRAINT_REGISTER_WRITER_ID,
        JOLT_STEP_WRITER_ID,
    ],
    "consumes": [
        "PhysicsWorldCache.frame_context",
        "来自 solver slot 的 RigidBodySpec",
        "来自 solver slot 的 ConstraintSpec",
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


_BUILTIN_SOLVER_DECLARATION_LOADERS = {
    _SPRING_VRM_SOLVER_ID: _load_spring_vrm_solver_declaration,
    RIGID_SOLVER_ID: lambda: RIGID_SOLVER_DECLARATION,
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
            problems.append(f"缺少必需字段: {key}")

    solver_id = str(data.get("solver_id") or "").strip()
    if not solver_id:
        problems.append("solver_id 不能为空")

    if not data.get("slot_kind"):
        problems.append("slot_kind 不能为空")

    if not data.get("consumes"):
        problems.append("consumes 不能为空")

    if not data.get("produces"):
        problems.append("produces 不能为空")

    writeback = data.get("writeback")
    if not isinstance(writeback, dict):
        problems.append("writeback 必须是 dict")
    elif writeback.get("solver_inline_writeback") is not False:
        problems.append("writeback.solver_inline_writeback 必须是 False")

    implicit = data.get("implicit_objects")
    if implicit is not None and not isinstance(implicit, dict):
        problems.append("implicit_objects 存在时必须是 dict")

    return problems


def register_solver_declaration(declaration: dict) -> dict:
    """注册运行时 solver 声明；未来外部 solver 接入时使用。"""
    data = normalize_solver_declaration(declaration)
    solver_id = str(data.get("solver_id") or "").strip()
    if not solver_id:
        raise ValueError("solver 声明需要 solver_id")
    _RUNTIME_SOLVER_DECLARATIONS[solver_id] = data
    return deepcopy(data)


def unregister_solver_declaration(solver_id: str) -> None:
    _RUNTIME_SOLVER_DECLARATIONS.pop(str(solver_id), None)


def get_solver_declaration(solver_id: str) -> dict | None:
    solver_key = str(solver_id or "")
    declaration = _RUNTIME_SOLVER_DECLARATIONS.get(solver_key)
    if declaration is None:
        loader = _BUILTIN_SOLVER_DECLARATION_LOADERS.get(solver_key)
        declaration = loader() if loader is not None else None
    if declaration is None:
        return None
    return normalize_solver_declaration(declaration)


def all_solver_declarations() -> dict[str, dict]:
    declarations: dict[str, dict] = {}
    for solver_id, loader in _BUILTIN_SOLVER_DECLARATION_LOADERS.items():
        declarations[str(solver_id)] = normalize_solver_declaration(loader())
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
