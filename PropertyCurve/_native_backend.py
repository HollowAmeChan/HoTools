"""定位 PropertyCurve 自己的原生采样内核 hotools_native。

归属：PropertyCurve 是 HoTools 父仓的贮藏内容，``hotools_native`` 由父仓
``_native`` 工程构建并放在 ``_Lib/<abi>/HotoolsPackage/``。物理世界（OmniNode
PhysicsWorld）只是 PropertyCurve 的调用方，不参与本模块的归属。

这里按自身位置解析该目录并把**模块对象**交给采样后端，避免依赖
``sys.path`` 顺序或模块名解析。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

MODULE_NAME = "hotools_native"
PACKAGE_DIR_NAME = "HotoolsPackage"
REQUIRED_SYMBOLS = (
    "sample_property_float_curve",
    "sample_property_color_curve",
)
_NATIVE_MODULE = None
_HAS_LOADED = False


def python_abi() -> str:
    """返回当前解释器对应的 HoTools ABI 目录名 (py311 / py313)。"""
    return "py313" if sys.version_info >= (3, 13) else "py311"


def native_package_dir() -> Path:
    """父仓 ``_Lib/<abi>/HotoolsPackage/`` 路径。"""
    plugin_root = Path(__file__).resolve().parents[1]
    return plugin_root / "_Lib" / python_abi() / PACKAGE_DIR_NAME


def is_available() -> bool:
    return native_module() is not None


def native_module():
    """返回可用的 hotools_native 模块；不可用时返回 None，由调用方回退 Python 后端。"""
    global _NATIVE_MODULE, _HAS_LOADED
    if _NATIVE_MODULE is not None:
        return _NATIVE_MODULE
    if _HAS_LOADED:
        return None
    _HAS_LOADED = True

    directory = native_package_dir()
    if not directory.is_dir():
        return None

    path = str(directory)
    inserted = path not in sys.path
    if inserted:
        sys.path.insert(0, path)
    try:
        module = importlib.import_module(MODULE_NAME)
    except ImportError:
        return None
    finally:
        if inserted:
            try:
                sys.path.remove(path)
            except ValueError:
                pass

    # 同名模块在别的目录里可能是残缺版本：必须逐符号确认后才接受。
    if not all(callable(getattr(module, name, None)) for name in REQUIRED_SYMBOLS):
        return None
    _NATIVE_MODULE = module
    return _NATIVE_MODULE


__all__ = [
    "MODULE_NAME",
    "PACKAGE_DIR_NAME",
    "REQUIRED_SYMBOLS",
    "is_available",
    "native_module",
    "native_package_dir",
    "python_abi",
]
