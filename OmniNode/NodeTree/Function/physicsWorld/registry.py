"""统一物理世界的解算器模块注册表。

这里是公共物理世界生命周期与各解算器领域之间的轻量装载边界。
物理世界核心只调用这里汇总出的通用回调；具体解算器包自行声明要提供哪些回调。
"""

from __future__ import annotations

from importlib import import_module
from copy import deepcopy
from typing import Callable


_BUILTIN_SOLVER_DOMAINS = ("spring_vrm", "rigid")
_RUNTIME_SOLVER_MODULES: dict[str, dict] = {}


def builtin_solver_domains() -> tuple[str, ...]:
    return tuple(_BUILTIN_SOLVER_DOMAINS)


def _load_solver_package(domain: str):
    return import_module(f".{domain}", __package__)


def _default_descriptor(domain: str) -> dict:
    return {
        "domain": str(domain),
        "solver_id": str(domain),
        "declaration": None,
        "scope_collectors": (),
        "scope_restart_handlers": (),
    }


def _solver_descriptor(domain: str) -> dict:
    runtime = _RUNTIME_SOLVER_MODULES.get(str(domain))
    if isinstance(runtime, dict):
        data = _default_descriptor(domain)
        data.update(runtime)
        return data

    package = _load_solver_package(str(domain))
    declared = getattr(package, "SOLVER_MODULE", None)
    data = _default_descriptor(domain)
    if isinstance(declared, dict):
        data.update(declared)
    return data


def register_solver_module(domain: str, descriptor: dict) -> dict:
    key = str(domain or "").strip()
    if not key:
        raise ValueError("solver module domain 不能为空")
    data = _default_descriptor(key)
    if isinstance(descriptor, dict):
        data.update(descriptor)
    data["domain"] = key
    _RUNTIME_SOLVER_MODULES[key] = data
    return dict(data)


def unregister_solver_module(domain: str) -> None:
    _RUNTIME_SOLVER_MODULES.pop(str(domain or ""), None)


def all_solver_module_descriptors() -> dict[str, dict]:
    domains = list(_BUILTIN_SOLVER_DOMAINS)
    for domain in _RUNTIME_SOLVER_MODULES:
        if domain not in domains:
            domains.append(domain)
    return {domain: _solver_descriptor(domain) for domain in domains}


def _as_tuple(value) -> tuple:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _resolve_ref(domain: str, ref):
    if callable(ref):
        return ref
    if not isinstance(ref, str):
        return None

    module_ref, sep, attr_name = ref.partition(":")
    if not sep or not module_ref or not attr_name:
        return None

    package = f"{__package__}.{domain}"
    module = import_module(module_ref, package=package) if module_ref.startswith(".") else import_module(module_ref)
    return getattr(module, attr_name, None)


def _resolve_hook(domain: str, hook_ref) -> Callable | None:
    hook = _resolve_ref(domain, hook_ref)
    return hook if callable(hook) else None


def _resolve_declaration_ref(domain: str, declaration_ref):
    if isinstance(declaration_ref, dict):
        return deepcopy(declaration_ref)

    declaration = _resolve_ref(domain, declaration_ref)
    if callable(declaration):
        try:
            declaration = declaration()
        except TypeError:
            return None
    if isinstance(declaration, dict):
        return deepcopy(declaration)
    return None


def _descriptor_solver_id(domain: str, descriptor: dict) -> str:
    solver_id = str(descriptor.get("solver_id") or "").strip()
    return solver_id or str(domain)


def _iter_hooks(hook_key: str) -> list[dict]:
    hooks: list[dict] = []
    for domain, descriptor in all_solver_module_descriptors().items():
        for hook_ref in _as_tuple(descriptor.get(hook_key)):
            hook = _resolve_hook(domain, hook_ref)
            if hook is None:
                continue
            hooks.append({
                "domain": domain,
                "hook": hook,
                "hook_ref": hook_ref,
            })
    return hooks


def iter_scope_collectors() -> list[dict]:
    return _iter_hooks("scope_collectors")


def iter_scope_restart_handlers() -> list[dict]:
    return _iter_hooks("scope_restart_handlers")


def resolve_solver_declaration(domain: str):
    descriptor = _solver_descriptor(domain)
    declaration_ref = descriptor.get("declaration")
    return _resolve_declaration_ref(domain, declaration_ref)


def iter_solver_declarations() -> list[dict]:
    declarations: list[dict] = []
    for domain, descriptor in all_solver_module_descriptors().items():
        declaration = resolve_solver_declaration(domain)
        if declaration is None:
            continue
        declarations.append({
            "domain": domain,
            "solver_id": _descriptor_solver_id(domain, descriptor),
            "declaration": declaration,
        })
    return declarations


def _record_hook_error(world, domain: str, hook_key: str, exc: Exception) -> None:
    if world is None or not hasattr(world, "runtime_cache") or not hasattr(world, "set_runtime_cache"):
        return
    try:
        errors = list(world.runtime_cache("solver_registry_errors") or [])
        errors.append({
            "domain": str(domain),
            "hook": str(hook_key),
            "error": str(exc),
        })
        world.set_runtime_cache("solver_registry_errors", errors[-32:])
    except Exception:
        pass


def run_scope_restart_handlers(world, scope) -> int:
    count = 0
    for entry in iter_scope_restart_handlers():
        try:
            entry["hook"](world, scope)
            count += 1
        except Exception as exc:
            _record_hook_error(world, entry.get("domain", ""), "scope_restart_handlers", exc)
    return count


def collect_scope_solver_specs(world, scope) -> int:
    count = 0
    for entry in iter_scope_collectors():
        try:
            entry["hook"](world, scope)
            count += 1
        except Exception as exc:
            _record_hook_error(world, entry.get("domain", ""), "scope_collectors", exc)
    return count
