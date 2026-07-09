"""统一物理世界的解算器声明注册表。"""

from __future__ import annotations

from copy import deepcopy
from importlib import import_module

from .rigid.names import RIGID_SOLVER_ID


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
_COMPAT_EXPORTS = {
    "BONE_COLLISION_CAPABILITY": ".spring_vrm.capabilities",
    "BONE_COLLISION_CAPABILITY_ID": ".spring_vrm.capabilities",
    "SPRING_VRM_UPDATE_FREQUENCY_TABLE": ".spring_vrm.capabilities",
    "SPRING_VRM_SOLVER_DECLARATION": ".spring_vrm.declaration",
    "RIGID_CAPABILITIES": ".rigid.capabilities",
    "RIGID_UPDATE_FREQUENCY_TABLE": ".rigid.capabilities",
    "RIGID_SOLVER_DECLARATION": ".rigid.declaration",
}


def __getattr__(name: str):
    module_name = _COMPAT_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name, __package__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def _load_spring_vrm_solver_declaration() -> dict:
    module = import_module(".spring_vrm.declaration", __package__)
    return module.SPRING_VRM_SOLVER_DECLARATION


def _load_rigid_solver_declaration() -> dict:
    module = import_module(".rigid.declaration", __package__)
    return module.RIGID_SOLVER_DECLARATION


# 兼容旧导入路径的符号。权威声明位于 physicsWorld/rigid/declaration.py。
RIGID_SOLVER_DECLARATION = _load_rigid_solver_declaration()


_BUILTIN_SOLVER_DECLARATION_LOADERS = {
    _SPRING_VRM_SOLVER_ID: _load_spring_vrm_solver_declaration,
    RIGID_SOLVER_ID: _load_rigid_solver_declaration,
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
    """返回解算器声明的稳定深拷贝形态。"""
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
    data = normalize_solver_declaration(declaration)
    solver_id = str(data.get("solver_id") or "").strip()
    if not solver_id:
        raise ValueError("解算器声明需要 solver_id")
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
