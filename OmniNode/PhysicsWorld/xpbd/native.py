"""XPBD 家族共享的 nanobind 模块装载边界。"""

from __future__ import annotations

from ..native_runtime import (
    PHYSICS_MODULE_NAME,
    load_physics_module,
    physics_native_unavailable_reason,
)


XPBD_REQUIRED_NATIVE_SYMBOLS = (
    "MeshXpbdContextV1",
    "mesh_xpbd_create_context_v1",
)
_NATIVE_MODULE = None


def native_module():
    global _NATIVE_MODULE
    if _NATIVE_MODULE is None:
        module = load_physics_module()
        if module is None:
            raise RuntimeError(physics_native_unavailable_reason())
        _NATIVE_MODULE = module
    return _NATIVE_MODULE


def require_xpbd_native_module(module=None):
    module = native_module() if module is None else module
    if not all(hasattr(module, name) for name in XPBD_REQUIRED_NATIVE_SYMBOLS):
        raise RuntimeError(f"{PHYSICS_MODULE_NAME} 缺少 XPBD context API")
    return module


# 原生 ABI 仍沿用已发布的 MeshXpbdContextV1 名称；Python 家族层不复制装载器。
require_mesh_xpbd_native_module = require_xpbd_native_module


def is_available() -> bool:
    try:
        require_xpbd_native_module()
    except Exception:
        return False
    return True


__all__ = [
    "XPBD_REQUIRED_NATIVE_SYMBOLS",
    "is_available",
    "native_module",
    "require_mesh_xpbd_native_module",
    "require_xpbd_native_module",
]
