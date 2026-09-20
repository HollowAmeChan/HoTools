"""物理世界原生扩展（hotools_physics / hotools_jolt）的统一解析与加载边界。

归属关系
--------
PropertyCurve 是 HoTools 父仓的**贮藏内容（核心资源）**，它的原生采样内核
``hotools_native`` 由父仓 ``_native`` 工程构建并放在 ``_Lib/<abi>/HotoolsPackage/``。
物理世界只是 PropertyCurve 的**调用方**（MC2 曲线参数、预设 payload），不拥有、
不扩展它，因此这里**不**回退到 ``hotools_native``：那会把“物理原生缺失”伪装成
“符号缺失”的静默降级，难以定位。

物理世界自持的两个 pyd 由本扩展构建，产物位于
``PhysicsWorld/native/runtime/<abi>/``，不写入父仓 ``_Lib``。

解析顺序
--------
1. 显式环境变量覆盖：``HOTOOLS_PHYSICS_NATIVE_DIR``，其次 ``HOTOOLS_NATIVE_TEST_DIR``
   （后者是原生测试长期使用的入口，保持兼容）。
2. 扩展自带 ``native/runtime/<abi>/``。
3. 父仓 ``_Lib/<abi>/HotoolsPackage/``（仅开发过渡期；命中时打 warning）
4. 显式开启 ``HOTOOLS_LEGACY_NATIVE_FALLBACK=1`` 时，额外尝试父仓 ``hotools_native``
   （最终态下它不含物理符号，只作为逃生门）。

判定标准是“探针符号齐全”，不是“import 成功”。
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import warnings
from pathlib import Path

PHYSICS_MODULE_NAME = "hotools_physics"
JOLT_MODULE_NAME = "hotools_jolt"
LEGACY_MODULE_NAME = "hotools_native"

# 这些符号必须同时存在，才算一个可用的物理原生模块。
# 覆盖 MC2 静态构建/域内核、Field runtime、XPBD context、SpringVRM、RigidWriteback。
PHYSICS_PROBE_SYMBOLS = (
    "mc2_mesh_static_fingerprint_v1",
    "mc2_bone_static_fingerprint_v1",
    "mc2_domain_cpu_v1_create",
    "mc2_domain_cpu_v1_step_tether_partitioned",
    "field_runtime_v1_create",
    "field_runtime_v1_sample_air_velocity",
    "mesh_xpbd_create_context_v1",
    "spring_vrm_create_context",
    "compute_rigid_delta_columns_v2",
)
JOLT_PROBE_SYMBOLS = (
    "JoltWorld",
    "WORLD_HANDLE",
    "INVALID_HANDLE",
)

PHYSICS_DIR_ENV = "HOTOOLS_PHYSICS_NATIVE_DIR"
LEGACY_TEST_DIR_ENV = "HOTOOLS_NATIVE_TEST_DIR"
LEGACY_FALLBACK_ENV = "HOTOOLS_LEGACY_NATIVE_FALLBACK"

_NATIVE_DIR = Path(__file__).resolve().parent / "native"
_LEGACY_WARNED: set[str] = set()


def python_abi() -> str:
    """返回当前解释器对应的 HoTools ABI 目录名（py311 / py313）。"""
    return "py313" if sys.version_info >= (3, 13) else "py311"


def native_runtime_dir() -> Path:
    """扩展自持的 pyd 目录。"""
    return _NATIVE_DIR / "runtime" / python_abi()


def legacy_native_dir() -> Path:
    """父仓 HoTools 的原生包目录（开发过渡期回退用）。"""
    return _NATIVE_DIR.parents[2] / "_Lib" / python_abi() / "HotoolsPackage"


def native_search_dirs() -> tuple[Path, ...]:
    """按解析顺序返回候选目录（仅返回存在的目录）。"""
    candidates: list[Path] = []
    for env_name in (PHYSICS_DIR_ENV, LEGACY_TEST_DIR_ENV):
        override = os.environ.get(env_name)
        if override:
            candidates.append(Path(override))
    candidates.append(native_runtime_dir())
    candidates.append(legacy_native_dir())
    ordered: list[Path] = []
    for candidate in candidates:
        if candidate.is_dir() and candidate not in ordered:
            ordered.append(candidate)
    return tuple(ordered)


def native_search_paths() -> tuple[str, ...]:
    """人类可读的候选目录列表（用于错误提示）。"""
    return tuple(str(path) for path in native_search_dirs())


def _warn_legacy(label: str, directory: Path) -> None:
    key = f"{label}:{directory}"
    if key in _LEGACY_WARNED:
        return
    _LEGACY_WARNED.add(key)
    warnings.warn(
        f"{label} 从父仓目录加载（{directory}）。该回退仅用于开发过渡期，"
        f"正式构建请把 pyd 放到 {native_runtime_dir()}。",
        RuntimeWarning,
        stacklevel=2,
    )


def _symbols_ready(module, required: tuple[str, ...], *, attribute: bool = False) -> bool:
    if attribute:
        return all(hasattr(module, name) for name in required)
    return all(callable(getattr(module, name, None)) for name in required)


def _try_import(directory: Path, module_name: str):
    path = str(directory)
    inserted = path not in sys.path
    if inserted:
        sys.path.insert(0, path)
        # 目录可能是在本进程启动后才出现的（例如刚构建完 pyd）。解释器会缓存
        # 目录列表，不失效就永远看不到新文件，表现为“明明有 pyd 却一直加载失败”。
        importlib.invalidate_caches()
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None
    finally:
        if inserted:
            try:
                sys.path.remove(path)
            except ValueError:
                pass


def _load_probed(module_name: str, required: tuple[str, ...], *, attribute: bool = False):
    """按候选目录逐个尝试加载并校验探针符号，命中即返回模块。"""
    for directory in native_search_dirs():
        module = _try_import(directory, module_name)
        if module is None:
            continue
        if not _symbols_ready(module, required, attribute=attribute):
            # 目录里可能有同名但残缺的模块：继续找下一个候选，不做静默接受。
            continue
        if directory == native_runtime_dir():
            return module
        if directory == legacy_native_dir():
            _warn_legacy(module_name, directory)
            return module
        return module
    return None


def load_physics_module():
    """加载扩展自持的 hotools_physics；不可用时返回 None。"""
    module = _load_probed(PHYSICS_MODULE_NAME, PHYSICS_PROBE_SYMBOLS)
    if module is not None:
        return module
    if os.environ.get(LEGACY_FALLBACK_ENV) == "1":
        return _load_probed(LEGACY_MODULE_NAME, PHYSICS_PROBE_SYMBOLS)
    return None


def load_jolt_module():
    """加载扩展自持的 hotools_jolt；不可用时返回 None（刚性物理静默降级）。"""
    return _load_probed(JOLT_MODULE_NAME, JOLT_PROBE_SYMBOLS, attribute=True)


def physics_native_unavailable_reason() -> str:
    """返回人类可读的失败原因（用于报错信息）。"""
    searched = native_search_paths()
    searched_text = "、".join(searched) if searched else "（无存在的候选目录）"
    return (
        f"未找到可用的 {PHYSICS_MODULE_NAME} 原生扩展。"
        f"已查找：{searched_text}。"
        "请在 OmniNode/PhysicsWorld/native 下运行 build.bat 生成对应 Python ABI 的 pyd。"
    )


def module_path(module) -> str:
    return getattr(module, "__file__", "<unknown>")


def is_extension_owned(module) -> bool:
    """判断模块是否来自扩展自持目录（而非父仓回退）。"""
    path = getattr(module, "__file__", None)
    if not path:
        return False
    try:
        return Path(path).resolve().is_relative_to(native_runtime_dir().resolve())
    except (OSError, ValueError):
        return False


__all__ = [
    "JOLT_MODULE_NAME",
    "JOLT_PROBE_SYMBOLS",
    "LEGACY_FALLBACK_ENV",
    "LEGACY_MODULE_NAME",
    "LEGACY_TEST_DIR_ENV",
    "PHYSICS_DIR_ENV",
    "PHYSICS_MODULE_NAME",
    "PHYSICS_PROBE_SYMBOLS",
    "is_extension_owned",
    "legacy_native_dir",
    "load_jolt_module",
    "load_physics_module",
    "module_path",
    "native_runtime_dir",
    "native_search_dirs",
    "native_search_paths",
    "physics_native_unavailable_reason",
    "python_abi",
]
