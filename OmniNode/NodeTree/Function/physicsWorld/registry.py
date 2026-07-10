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
_RUNTIME_SOLVER_MODULES: dict[str, dict] = {}
_REGISTERED_PROPERTY_CLASSES: list[type] = []
_REGISTERED_PROPERTY_BINDINGS: list[tuple[object, str]] = []


def builtin_solver_domains() -> tuple[str, ...]:
    return tuple(_BUILTIN_SOLVER_DOMAINS)


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


def register_solver_blender_properties() -> int:
    """由物理世界统一注册所有 solver 拥有的 Blender 参数。"""
    if _REGISTERED_PROPERTY_CLASSES or _REGISTERED_PROPERTY_BINDINGS:
        return len(_REGISTERED_PROPERTY_BINDINGS)

    import bpy

    registered_classes: list[type] = []
    registered_bindings: list[tuple[object, str]] = []
    try:
        declarations = [
            resolve_solver_blender_properties(domain)
            for domain in all_solver_module_descriptors()
        ]
        for declaration in declarations:
            for cls in _as_tuple(declaration.get("classes")):
                bpy.utils.register_class(cls)
                registered_classes.append(cls)

        for declaration in declarations:
            for binding in _as_tuple(declaration.get("bindings")):
                if not isinstance(binding, dict):
                    continue
                owner = binding.get("owner")
                name = str(binding.get("name") or "").strip()
                property_kind = str(binding.get("property") or "").strip()
                property_type = binding.get("type")
                if owner is None or not name or property_kind != "pointer" or property_type is None:
                    raise ValueError(f"invalid solver Blender property binding: {binding!r}")
                if hasattr(owner, name):
                    raise RuntimeError(f"solver Blender property already registered: {owner.__name__}.{name}")
                setattr(owner, name, bpy.props.PointerProperty(type=property_type))
                registered_bindings.append((owner, name))
    except Exception:
        for owner, name in reversed(registered_bindings):
            if hasattr(owner, name):
                delattr(owner, name)
        for cls in reversed(registered_classes):
            bpy.utils.unregister_class(cls)
        raise

    _REGISTERED_PROPERTY_CLASSES.extend(registered_classes)
    _REGISTERED_PROPERTY_BINDINGS.extend(registered_bindings)
    return len(registered_bindings)


def unregister_solver_blender_properties() -> None:
    """按注册逆序释放 solver Blender 参数。"""
    import bpy

    for owner, name in reversed(_REGISTERED_PROPERTY_BINDINGS):
        if hasattr(owner, name):
            delattr(owner, name)
    _REGISTERED_PROPERTY_BINDINGS.clear()

    for cls in reversed(_REGISTERED_PROPERTY_CLASSES):
        bpy.utils.unregister_class(cls)
    _REGISTERED_PROPERTY_CLASSES.clear()


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
