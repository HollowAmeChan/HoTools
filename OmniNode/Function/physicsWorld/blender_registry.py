"""Physics World 的 domain 级 Blender RNA 生命周期注册表。

本模块只在显式 register/unregister 时导入 bpy。它负责 PropertyGroup class、
RNA binding 与依赖顺序，不负责 solver runtime、节点注册或 UI 绘制。
"""

from __future__ import annotations

_REGISTERED_DOMAINS: dict[str, dict] = {}
_REGISTRATION_ORDER: list[str] = []


def _as_tuple(value) -> tuple:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _domain_key(domain: str) -> str:
    key = str(domain or "").strip()
    if not key:
        raise ValueError("Blender property domain 不能为空")
    return key


def _resolve_owner(owner, bpy):
    if isinstance(owner, str):
        owner = getattr(bpy.types, owner, None)
    return owner


def _type_name(value) -> str:
    if value is None:
        return ""
    module = str(getattr(value, "__module__", "") or "")
    name = str(getattr(value, "__qualname__", getattr(value, "__name__", "")) or "")
    return f"{module}:{name}" if module else name


def _owner_name(owner) -> str:
    return str(getattr(owner, "__name__", type(owner).__name__) or type(owner).__name__)


def _fingerprint_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return tuple(
            (str(key), _fingerprint_value(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(_fingerprint_value(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_fingerprint_value(item) for item in value), key=repr))
    if isinstance(value, type):
        return ("type", _type_name(value))
    if callable(value):
        return ("callable", _type_name(value))
    function = getattr(value, "function", None)
    keywords = getattr(value, "keywords", None)
    if callable(function) and isinstance(keywords, dict):
        return (
            "property_deferred",
            _type_name(function),
            _fingerprint_value(keywords),
        )
    return ("repr", repr(value))


def _class_declaration_id(cls) -> tuple:
    annotations = getattr(cls, "__annotations__", {}) or {}
    return (
        _type_name(cls),
        tuple(
            (str(name), _fingerprint_value(value))
            for name, value in annotations.items()
        ),
    )


def _declaration_fingerprint(classes: tuple, bindings: tuple, dependencies: tuple, bpy) -> tuple:
    class_ids = tuple(_class_declaration_id(cls) for cls in classes)
    binding_ids = []
    for binding in bindings:
        if not isinstance(binding, dict):
            binding_ids.append(("invalid", repr(binding)))
            continue
        owner = _resolve_owner(binding.get("owner"), bpy)
        factory = binding.get("factory")
        binding_ids.append((
            _owner_name(owner) if owner is not None else "",
            str(binding.get("name") or ""),
            str(binding.get("property") or ""),
            _type_name(binding.get("type")),
            _type_name(factory),
            _fingerprint_value(binding.get("kwargs") or {}),
        ))
    return class_ids, tuple(binding_ids), dependencies


def _normalize_binding(binding: dict, bpy) -> dict:
    if not isinstance(binding, dict):
        raise ValueError(f"invalid Blender property binding: {binding!r}")

    owner = _resolve_owner(binding.get("owner"), bpy)
    name = str(binding.get("name") or "").strip()
    if owner is None or not name:
        raise ValueError(f"invalid Blender property owner/name: {binding!r}")

    factory = binding.get("factory")
    property_kind = str(binding.get("property") or "").strip().lower()
    kwargs = dict(binding.get("kwargs") or {})

    if factory is None:
        factory_names = {
            "pointer": "PointerProperty",
            "bool": "BoolProperty",
            "enum": "EnumProperty",
            "float": "FloatProperty",
            "float_vector": "FloatVectorProperty",
            "int": "IntProperty",
            "string": "StringProperty",
            "collection": "CollectionProperty",
        }
        factory_name = factory_names.get(property_kind)
        if factory_name is None:
            raise ValueError(f"unsupported Blender property binding: {binding!r}")
        factory = getattr(bpy.props, factory_name)

    if not callable(factory):
        raise ValueError(f"Blender property factory 不可调用: {binding!r}")

    property_type = binding.get("type")
    if property_type is not None:
        kwargs.setdefault("type", property_type)
    if property_kind in {"pointer", "collection"} and kwargs.get("type") is None:
        raise ValueError(f"{property_kind} binding 缺少 type: {binding!r}")

    return {
        "owner": owner,
        "name": name,
        "factory": factory,
        "kwargs": kwargs,
        "property": property_kind,
    }


def register_blender_property_domain(
    domain: str,
    declaration: dict | None,
    *,
    dependencies=(),
) -> dict:
    """注册一个 component/solver domain 拥有的 class 与 RNA binding。"""
    import bpy

    key = _domain_key(domain)
    data = declaration if isinstance(declaration, dict) else {}
    classes = _as_tuple(data.get("classes"))
    raw_bindings = _as_tuple(data.get("bindings"))
    deps = tuple(dict.fromkeys(str(item).strip() for item in _as_tuple(dependencies) if str(item).strip()))
    fingerprint = _declaration_fingerprint(classes, raw_bindings, deps, bpy)

    current = _REGISTERED_DOMAINS.get(key)
    if current is not None:
        if current.get("fingerprint") != fingerprint:
            raise RuntimeError(f"Blender property domain 已注册但声明发生变化: {key}")
        return blender_property_domain_snapshot(key)

    missing_dependencies = [item for item in deps if item not in _REGISTERED_DOMAINS]
    if missing_dependencies:
        raise RuntimeError(
            f"Blender property domain {key} 缺少依赖: {', '.join(missing_dependencies)}"
        )

    normalized_bindings = tuple(_normalize_binding(binding, bpy) for binding in raw_bindings)

    seen_binding_keys: set[tuple[int, str]] = set()
    for binding in normalized_bindings:
        owner = binding["owner"]
        name = binding["name"]
        binding_key = (id(owner), name)
        if binding_key in seen_binding_keys:
            raise RuntimeError(f"domain {key} 重复声明 RNA binding: {_owner_name(owner)}.{name}")
        seen_binding_keys.add(binding_key)
        if hasattr(owner, name):
            raise RuntimeError(f"Blender property 已存在: {_owner_name(owner)}.{name}")

    registered_class_names = {
        _type_name(cls)
        for state in _REGISTERED_DOMAINS.values()
        for cls in state.get("classes", ())
    }
    for cls in classes:
        if not isinstance(cls, type):
            raise ValueError(f"domain {key} 的 Blender class 无效: {cls!r}")
        if _type_name(cls) in registered_class_names:
            raise RuntimeError(f"Blender class 已由其它 domain 注册: {_type_name(cls)}")

    registered_classes: list[type] = []
    registered_bindings: list[tuple[object, str]] = []
    try:
        for cls in classes:
            bpy.utils.register_class(cls)
            registered_classes.append(cls)

        for binding in normalized_bindings:
            owner = binding["owner"]
            name = binding["name"]
            prop = binding["factory"](**binding["kwargs"])
            setattr(owner, name, prop)
            registered_bindings.append((owner, name))
    except Exception:
        for owner, name in reversed(registered_bindings):
            if hasattr(owner, name):
                delattr(owner, name)
        for cls in reversed(registered_classes):
            bpy.utils.unregister_class(cls)
        raise

    _REGISTERED_DOMAINS[key] = {
        "domain": key,
        "classes": tuple(registered_classes),
        "bindings": tuple(registered_bindings),
        "dependencies": deps,
        "fingerprint": fingerprint,
    }
    _REGISTRATION_ORDER.append(key)
    return blender_property_domain_snapshot(key)


def unregister_blender_property_domain(domain: str, *, force: bool = False) -> bool:
    """只注销指定 domain；默认拒绝释放仍被其它 domain 依赖的属性。"""
    import bpy

    key = _domain_key(domain)
    state = _REGISTERED_DOMAINS.get(key)
    if state is None:
        return False

    dependents = [
        item
        for item, other in _REGISTERED_DOMAINS.items()
        if item != key and key in other.get("dependencies", ())
    ]
    if dependents and not force:
        raise RuntimeError(f"Blender property domain {key} 仍被依赖: {', '.join(dependents)}")

    errors: list[Exception] = []
    for owner, name in reversed(state.get("bindings", ())):
        try:
            if hasattr(owner, name):
                delattr(owner, name)
        except Exception as exc:
            errors.append(exc)

    for cls in reversed(state.get("classes", ())):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            errors.append(exc)

    _REGISTERED_DOMAINS.pop(key, None)
    if key in _REGISTRATION_ORDER:
        _REGISTRATION_ORDER.remove(key)
    if errors:
        raise RuntimeError(
            f"Blender property domain {key} 注销不完整: "
            + "; ".join(str(item) for item in errors)
        )
    return True


def unregister_all_blender_property_domains() -> None:
    """按真实注册逆序释放全部 domain，主要用于插件整体注销和测试清理。"""
    for domain in reversed(tuple(_REGISTRATION_ORDER)):
        unregister_blender_property_domain(domain, force=True)


def is_blender_property_domain_registered(domain: str) -> bool:
    return str(domain or "").strip() in _REGISTERED_DOMAINS


def registered_blender_property_domains() -> tuple[str, ...]:
    return tuple(_REGISTRATION_ORDER)


def blender_property_domain_snapshot(domain: str) -> dict:
    key = str(domain or "").strip()
    state = _REGISTERED_DOMAINS.get(key)
    if state is None:
        return {}
    return {
        "domain": key,
        "class_count": len(state.get("classes", ())),
        "binding_count": len(state.get("bindings", ())),
        "classes": [_type_name(cls) for cls in state.get("classes", ())],
        "bindings": [
            f"{_owner_name(owner)}.{name}"
            for owner, name in state.get("bindings", ())
        ],
        "dependencies": list(state.get("dependencies", ())),
    }


def blender_property_registry_snapshot() -> dict:
    return {
        "registration_order": list(_REGISTRATION_ORDER),
        "domains": {
            domain: blender_property_domain_snapshot(domain)
            for domain in _REGISTRATION_ORDER
        },
    }


__all__ = [
    "blender_property_domain_snapshot",
    "blender_property_registry_snapshot",
    "is_blender_property_domain_registered",
    "register_blender_property_domain",
    "registered_blender_property_domains",
    "unregister_all_blender_property_domains",
    "unregister_blender_property_domain",
]
