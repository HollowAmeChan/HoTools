"""XPBD 家族共享的 nanobind 模块装载边界。"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys


XPBD_REQUIRED_NATIVE_SYMBOLS = (
    "MeshXpbdContextV1",
    "mesh_xpbd_create_context_v1",
)
_NATIVE_MODULE = None


def _ensure_bundled_native_path() -> None:
    override = os.environ.get("HOTOOLS_NATIVE_TEST_DIR")
    package_dir = Path(override) if override else None
    if package_dir is None:
        package_root = Path(__file__).resolve().parents[3]
        py_lib = "py313" if sys.version_info >= (3, 13) else "py311"
        package_dir = package_root / "_Lib" / py_lib / "HotoolsPackage"
    if package_dir.exists() and str(package_dir) not in sys.path:
        sys.path.insert(0, str(package_dir))


def native_module():
    global _NATIVE_MODULE
    if _NATIVE_MODULE is None:
        _ensure_bundled_native_path()
        _NATIVE_MODULE = importlib.import_module("hotools_native")
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
