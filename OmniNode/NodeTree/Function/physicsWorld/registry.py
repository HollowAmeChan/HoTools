"""统一物理世界的解算器模块注册表。

这里是公共物理世界生命周期与各解算器领域之间的轻量装载边界。
物理世界核心只调用这里汇总出的通用回调；具体解算器包自行声明要提供哪些回调。
"""

from __future__ import annotations

import os
import sys
import importlib.util
from importlib import import_module
from copy import deepcopy
from typing import Callable


_BUILTIN_SOLVER_DOMAINS = ("spring_vrm", "rigid")
_BUILTIN_COMPONENT_DOMAINS = ("collision",)
_RUNTIME_SOLVER_MODULES: dict[str, dict] = {}
_REGISTERED_COMPONENT_PROPERTY_DOMAINS: list[str] = []
_REGISTERED_SOLVER_PROPERTY_DOMAINS: list[str] = []
_PHYSICS_WORLD_BLENDER_PROPERTIES_ACTIVE = False
_SOLVER_BLENDER_PROPERTIES_ACTIVE = False


def builtin_solver_domains() -> tuple[str, ...]:
    return tuple(_BUILTIN_SOLVER_DOMAINS)


def builtin_component_domains() -> tuple[str, ...]:
    return tuple(_BUILTIN_COMPONENT_DOMAINS)


def _component_descriptor(domain: str) -> dict:
    package = import_module(f".{domain}", __package__)
    declared = getattr(package, "COMPONENT_MODULE", None)
    data = {
        "component_id": str(domain),
        "kind": "core",
        "depends_on": (),
        "capabilities": None,
        "blender_properties": None,
    }
    if isinstance(declared, dict):
        data.update(declared)
    return data


def all_component_descriptors() -> dict[str, dict]:
    return {
        domain: _component_descriptor(domain)
        for domain in _BUILTIN_COMPONENT_DOMAINS
    }


def resolve_component_capabilities(domain: str) -> dict:
    """解析 core component 拥有的共享 capability。"""
    descriptor = _component_descriptor(domain)
    value = _resolve_ref(domain, descriptor.get("capabilities"))
    return deepcopy(value) if isinstance(value, dict) else {}


def all_component_capabilities() -> dict[str, dict]:
    """合并共享 capability，并拒绝不同 component 重复拥有同一 identifier。"""
    capabilities: dict[str, dict] = {}
    owners: dict[str, str] = {}
    for domain in _BUILTIN_COMPONENT_DOMAINS:
        for capability_id, declaration in resolve_component_capabilities(domain).items():
            key = str(capability_id or "").strip()
            if not key:
                raise ValueError(f"component {domain} 声明了空 capability identifier")
            previous_owner = owners.get(key)
            if previous_owner is not None:
                raise RuntimeError(
                    f"共享 capability {key} 同时由 {previous_owner} 与 {domain} 拥有"
                )
            owners[key] = domain
            capabilities[key] = deepcopy(declaration)
    return capabilities


def _load_solver_package(domain: str):
    package_name = f"{__package__}.{domain}"
    package = import_module(f".{domain}", __package__)
    if getattr(package, "SOLVER_MODULE", None) is not None:
        return package

    package_paths = list(getattr(package, "__path__", ()) or ())
    if not package_paths:
        return package

    init_path = os.path.join(package_paths[0], "__init__.py")
    if not os.path.exists(init_path):
        return package

    spec = importlib.util.spec_from_file_location(
        package_name,
        init_path,
        submodule_search_locations=package_paths,
    )
    if spec is None or spec.loader is None:
        return package
    module = importlib.util.module_from_spec(spec)
    module.__package__ = package_name
    module.__path__ = package_paths
    sys.modules[package_name] = module
    spec.loader.exec_module(module)
    return module


def _default_descriptor(domain: str) -> dict:
    return {
        "domain": str(domain),
        "solver_id": str(domain),
        "declaration": None,
        "nodes": (),
        "capabilities": None,
        "blender_properties": None,
        "property_dependencies": (),
        "debug_draw_modes": None,
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
    if _SOLVER_BLENDER_PROPERTIES_ACTIVE:
        declaration = resolve_solver_blender_properties(key)
        if declaration.get("classes") or declaration.get("bindings"):
            from .blender_registry import register_blender_property_domain

            try:
                register_blender_property_domain(
                    key,
                    declaration,
                    dependencies=data.get("property_dependencies", ()),
                )
                if key not in _REGISTERED_SOLVER_PROPERTY_DOMAINS:
                    _REGISTERED_SOLVER_PROPERTY_DOMAINS.append(key)
            except Exception:
                _RUNTIME_SOLVER_MODULES.pop(key, None)
                raise
    return dict(data)


def unregister_solver_module(domain: str) -> None:
    key = str(domain or "").strip()
    if key in _REGISTERED_SOLVER_PROPERTY_DOMAINS:
        from .blender_registry import unregister_blender_property_domain

        unregister_blender_property_domain(key)
        _REGISTERED_SOLVER_PROPERTY_DOMAINS.remove(key)
    _RUNTIME_SOLVER_MODULES.pop(key, None)


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
    if isinstance(ref, dict):
        return ref
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


def _resolve_module_ref(domain: str, ref):
    if not isinstance(ref, str) or ":" in ref:
        return None
    package = f"{__package__}.{domain}"
    return import_module(ref, package=package) if ref.startswith(".") else import_module(ref)


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


def iter_solver_node_modules() -> list[dict]:
    modules: list[dict] = []
    for domain, descriptor in all_solver_module_descriptors().items():
        for module_ref in _as_tuple(descriptor.get("nodes")):
            module = _resolve_module_ref(domain, module_ref)
            if module is None:
                continue
            modules.append({
                "domain": domain,
                "solver_id": _descriptor_solver_id(domain, descriptor),
                "module_ref": module_ref,
                "module": module,
            })
    return modules


def resolve_solver_capabilities(domain: str) -> dict:
    descriptor = _solver_descriptor(domain)
    ref = descriptor.get("capabilities")
    value = _resolve_ref(domain, ref)
    return deepcopy(value) if isinstance(value, dict) else {}


def resolve_solver_blender_properties(domain: str) -> dict:
    """解析 solver 自己声明的 Blender class 与 RNA binding。"""
    descriptor = _solver_descriptor(domain)
    ref = descriptor.get("blender_properties")
    value = _resolve_ref(domain, ref)
    return value if isinstance(value, dict) else {}


def resolve_component_blender_properties(domain: str) -> dict:
    descriptor = _component_descriptor(domain)
    ref = descriptor.get("blender_properties")
    value = _resolve_ref(domain, ref)
    return value if isinstance(value, dict) else {}


def register_physics_world_blender_properties() -> int:
    """注册 core component 后再注册 solver domain 的全部 Blender 属性。"""
    global _PHYSICS_WORLD_BLENDER_PROPERTIES_ACTIVE
    from .blender_registry import (
        blender_property_domain_snapshot,
        register_blender_property_domain,
        unregister_blender_property_domain,
    )

    if _PHYSICS_WORLD_BLENDER_PROPERTIES_ACTIVE:
        domains = tuple(_REGISTERED_COMPONENT_PROPERTY_DOMAINS) + tuple(_REGISTERED_SOLVER_PROPERTY_DOMAINS)
        return sum(
            int(blender_property_domain_snapshot(domain).get("binding_count", 0))
            for domain in domains
        )

    registered_now: list[str] = []
    try:
        for domain, descriptor in all_component_descriptors().items():
            declaration = resolve_component_blender_properties(domain)
            if not declaration.get("classes") and not declaration.get("bindings"):
                continue
            register_blender_property_domain(
                domain,
                declaration,
                dependencies=descriptor.get("depends_on", ()),
            )
            registered_now.append(domain)
        _REGISTERED_COMPONENT_PROPERTY_DOMAINS.extend(registered_now)
        solver_count = register_solver_blender_properties()
    except Exception:
        for domain in reversed(registered_now):
            unregister_blender_property_domain(domain, force=True)
        _REGISTERED_COMPONENT_PROPERTY_DOMAINS.clear()
        raise

    _PHYSICS_WORLD_BLENDER_PROPERTIES_ACTIVE = True
    component_count = sum(
        int(blender_property_domain_snapshot(domain).get("binding_count", 0))
        for domain in _REGISTERED_COMPONENT_PROPERTY_DOMAINS
    )
    return component_count + int(solver_count)


def unregister_physics_world_blender_properties() -> None:
    """按 solver -> core component 的逆依赖顺序释放全部物理 RNA。"""
    global _PHYSICS_WORLD_BLENDER_PROPERTIES_ACTIVE
    from .blender_registry import unregister_blender_property_domain

    unregister_solver_blender_properties()
    for domain in reversed(tuple(_REGISTERED_COMPONENT_PROPERTY_DOMAINS)):
        unregister_blender_property_domain(domain, force=True)
    _REGISTERED_COMPONENT_PROPERTY_DOMAINS.clear()
    _PHYSICS_WORLD_BLENDER_PROPERTIES_ACTIVE = False


def register_solver_blender_properties() -> int:
    """由物理世界统一注册所有 solver 拥有的 Blender 参数。"""
    global _SOLVER_BLENDER_PROPERTIES_ACTIVE
    from .blender_registry import (
        blender_property_domain_snapshot,
        register_blender_property_domain,
        unregister_blender_property_domain,
    )

    if _SOLVER_BLENDER_PROPERTIES_ACTIVE:
        return sum(
            int(blender_property_domain_snapshot(domain).get("binding_count", 0))
            for domain in _REGISTERED_SOLVER_PROPERTY_DOMAINS
        )

    registered_now: list[str] = []
    try:
        for domain, descriptor in all_solver_module_descriptors().items():
            declaration = resolve_solver_blender_properties(domain)
            if not declaration.get("classes") and not declaration.get("bindings"):
                continue
            register_blender_property_domain(
                domain,
                declaration,
                dependencies=descriptor.get("property_dependencies", ()),
            )
            registered_now.append(domain)
    except Exception:
        for domain in reversed(registered_now):
            unregister_blender_property_domain(domain, force=True)
        raise

    _REGISTERED_SOLVER_PROPERTY_DOMAINS.extend(
        domain for domain in registered_now
        if domain not in _REGISTERED_SOLVER_PROPERTY_DOMAINS
    )
    _SOLVER_BLENDER_PROPERTIES_ACTIVE = True
    return sum(
        int(blender_property_domain_snapshot(domain).get("binding_count", 0))
        for domain in _REGISTERED_SOLVER_PROPERTY_DOMAINS
    )


def unregister_solver_blender_properties() -> None:
    """按注册逆序释放 solver Blender 参数。"""
    global _SOLVER_BLENDER_PROPERTIES_ACTIVE
    from .blender_registry import unregister_blender_property_domain

    for domain in reversed(tuple(_REGISTERED_SOLVER_PROPERTY_DOMAINS)):
        unregister_blender_property_domain(domain, force=True)
    _REGISTERED_SOLVER_PROPERTY_DOMAINS.clear()
    _SOLVER_BLENDER_PROPERTIES_ACTIVE = False


def resolve_solver_debug_draw_modes(domain: str) -> dict:
    descriptor = _solver_descriptor(domain)
    ref = descriptor.get("debug_draw_modes")
    value = _resolve_ref(domain, ref)
    return deepcopy(value) if isinstance(value, dict) else {}


def iter_solver_capabilities() -> list[dict]:
    return [
        {
            "domain": domain,
            "solver_id": _descriptor_solver_id(domain, descriptor),
            "capabilities": resolve_solver_capabilities(domain),
        }
        for domain, descriptor in all_solver_module_descriptors().items()
    ]


def iter_solver_debug_draw_modes() -> list[dict]:
    return [
        {
            "domain": domain,
            "solver_id": _descriptor_solver_id(domain, descriptor),
            "debug_draw_modes": resolve_solver_debug_draw_modes(domain),
        }
        for domain, descriptor in all_solver_module_descriptors().items()
    ]


def validate_solver_registry() -> dict:
    problems: list[dict] = []
    seen_solver_ids: dict[str, str] = {}
    seen_slot_kinds: dict[str, str] = {}
    seen_result_channels: dict[str, str] = {}
    seen_implicit_tags: dict[str, str] = {}
    seen_debug_modes: dict[str, str] = {}

    def _check_unique(bucket: dict[str, str], kind: str, value: str, domain: str) -> None:
        key = str(value or "").strip()
        if not key:
            return
        previous = bucket.get(key)
        if previous is not None and previous != domain:
            problems.append({
                "kind": kind,
                "id": key,
                "domains": [previous, domain],
            })
            return
        bucket[key] = domain

    for domain, descriptor in all_solver_module_descriptors().items():
        _check_unique(seen_solver_ids, "solver_id", _descriptor_solver_id(domain, descriptor), domain)
        declaration = resolve_solver_declaration(domain) or {}

        for slot_kind in _as_tuple(declaration.get("slot_kind")):
            _check_unique(seen_slot_kinds, "slot_kind", slot_kind, domain)

        export = declaration.get("export") if isinstance(declaration.get("export"), dict) else {}
        for channel in _as_tuple(export.get("result_channels")):
            _check_unique(seen_result_channels, "result_channel", channel, domain)

        implicit = declaration.get("implicit_objects") if isinstance(declaration.get("implicit_objects"), dict) else {}
        for tag in _as_tuple(implicit.get("consumes")) + _as_tuple(implicit.get("planned")):
            _check_unique(seen_implicit_tags, "implicit_object_tag", tag, domain)

        for mode_id in resolve_solver_debug_draw_modes(domain):
            _check_unique(seen_debug_modes, "debug_draw_mode", mode_id, domain)

    return {
        "valid": not problems,
        "problems": problems,
        "solver_ids": dict(seen_solver_ids),
        "slot_kinds": dict(seen_slot_kinds),
        "result_channels": dict(seen_result_channels),
        "implicit_object_tags": dict(seen_implicit_tags),
        "debug_draw_modes": dict(seen_debug_modes),
    }


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
