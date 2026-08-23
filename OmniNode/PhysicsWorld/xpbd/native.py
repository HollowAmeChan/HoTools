"""XPBD 家族共享的 nanobind 模块装载边界。"""

from __future__ import annotations

from ....Utils.optional_dependencies import import_native_module


XPBD_REQUIRED_NATIVE_SYMBOLS = (
    "MeshXpbdContextV1",
    "mesh_xpbd_create_context_v1",
)
_NATIVE_MODULE = None


def native_module():
    global _NATIVE_MODULE
    if _NATIVE_MODULE is None:
        _NATIVE_MODULE = import_native_module("hotools_native")
    return _NATIVE_MODULE


def require_xpbd_native_module(module=None):
    module = native_module() if module is None else module
    if not all(hasattr(module, name) for name in XPBD_REQUIRED_NATIVE_SYMBOLS):
        raise RuntimeError("hotools_native 缺少 XPBD context API")
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
