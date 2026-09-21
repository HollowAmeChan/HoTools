"""OmniNode 扩展的安装 / 卸载 / 状态查询。

设计要点
--------
* **禁用 ≠ 卸载**：禁用只改 `hoTools_omninode_disabled_extensions`（见父仓
  `__init__.py`），磁盘文件不动；本模块负责真正的增删。
* **安装落点**：优先插件内 ``OmniNode/extensions/<名>/``，不可写时退到
  Blender 用户目录 ``<user>/extensions/``（应对只读插件库安装）。两个位置都在
  注册器的搜索根里。
* **卸载两段式**：先把扩展目录改名进同级 ``.trash/``（Windows 上被加载的 pyd
  会锁住文件，但目录改名仍然成功），下次启动或手动清理时再真正删除。这样
  "卸载" 对用户始终可用，不需要先关 Blender。
* 本模块不 import bpy 之外的东西；`OmniNodeRegister` 不反向依赖它。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import bpy

MANIFEST_FILENAME = "extension.json"
REGISTRATION_FILENAME = "omninode_registration.py"
TRASH_DIRNAME = ".trash"
ADDON_PACKAGE = "HoTools"

# 开发检出保护标记。放在扩展目录根（与 extension.json 同级）即视为"本机开发版"：
# 卸载 / 安装覆盖 / 改名都不会碰它，避免误删正在改的源码。
# 内含 .git 的目录（扩展仓库的开发检出）同样自动受保护。
DEVELOPMENT_MARKER_FILENAME = ".hotools-dev"
DEVELOPMENT_MARKER_TEXT = (
    "此目录是 HoTools 扩展的开发检出，请勿删除。\n"
    "父仓的扩展安装/卸载/覆盖都不会改动它。\n"
    "（改用 git 管理，或手动移除本文件以恢复可卸载状态。）\n"
)

# 扩展的发布仓库：Release 里放 -py311 / -py313 两个安装包（对应 Blender 4.5 / 5.x）。
EXTENSION_REPOSITORY = "HollowAmeChan/Hotools-Omninode-Physics"
EXTENSION_API_ROOT = f"https://api.github.com/repos/{EXTENSION_REPOSITORY}"
# 只接受 https://github.com/ 下的下载地址，避免响应被篡改后拉到任意主机。
EXTENSION_DOWNLOAD_PREFIX = "https://github.com/"


def python_abi() -> str:
    """当前解释器对应的扩展安装包后缀（Blender 4.5 → py311，5.x → py313）。"""
    return f"py{sys.version_info.major}{sys.version_info.minor}"


# ---------------------------------------------------------------------------
# 目录解析
# ---------------------------------------------------------------------------

def addon_root() -> Path:
    """父仓插件根目录。"""
    import HoTools

    return Path(HoTools.__file__).resolve().parent


def bundled_extensions_dir() -> Path:
    """插件内置的扩展安装位（随包分发时可能只读）。"""
    return addon_root() / "OmniNode" / "extensions"


def user_extensions_dir() -> Path:
    """Blender 用户目录下的扩展安装位（总是可写）。"""
    try:
        base = Path(bpy.utils.user_resource("EXTENSIONS"))
    except Exception:  # noqa: BLE001 - 极早期调用时 resource 可能不可用
        base = Path.home() / ".config" / "blender" / "extensions"
    return base / "HoTools-Omninode"


def install_targets() -> tuple[Path, ...]:
    """按优先级返回候选安装目录（用于“装到哪里”）。"""
    return (bundled_extensions_dir(), user_extensions_dir())


def extension_search_dirs() -> tuple[Path, ...]:
    """返回已存在的扩展目录（两个落点都返回，注册器据此发现扩展）。"""
    return tuple(
        directory
        for directory in install_targets()
        if directory.is_dir()
    )


def _trash_dir(parent: Path) -> Path:
    return parent / TRASH_DIRNAME


# ---------------------------------------------------------------------------
# 状态查询
# ---------------------------------------------------------------------------

def _describe_directory(directory: Path, *, location: str, source: str) -> dict:
    from .OmniNodeRegister import _read_extension_manifest

    manifest_path = directory / MANIFEST_FILENAME
    manifest, error = (
        _read_extension_manifest(manifest_path) if manifest_path.is_file() else ({}, "")
    )
    return {
        "identifier": str(
            manifest.get("identifier") or manifest.get("id") or directory.name
        ),
        "display_name": str(
            manifest.get("display_name") or manifest.get("name") or directory.name
        ),
        "version": str(manifest.get("version") or ""),
        "source": source,
        "directory": str(directory),
        "location": location,
        "writable": _is_writable(directory),
        "manifest_error": error,
    }


def _looks_like_extension(directory: Path) -> bool:
    if (directory / MANIFEST_FILENAME).is_file():
        return True
    if (directory / REGISTRATION_FILENAME).is_file():
        return True
    return any(directory.glob(f"*/{REGISTRATION_FILENAME}"))


def installed_extensions(*, search_roots=None) -> tuple[dict, ...]:
    """扫描三个落点，返回每个扩展目录的轻量描述（不导入其代码）。

    区分三类位置（``location`` 字段）：
      * ``插件内模块``   —— 直接位于 ``OmniNode/`` 下，随主仓跟踪，不可卸载
      * ``插件内安装``   —— ``OmniNode/extensions/``，用户安装，随插件目录走
      * ``用户目录安装`` —— Blender 用户扩展目录，用户安装，插件只读时的落点
    """
    omni_node = Path(__file__).resolve().parent
    bundled = bundled_extensions_dir()
    user_dir = user_extensions_dir()
    plan = (
        (omni_node, "插件内模块", "bundled-inplace", False),
        (bundled, "插件内安装", "manifest", True),
        (user_dir, "用户目录安装", "manifest", True),
    )
    if search_roots:
        plan = tuple(
            (Path(root), "插件内安装", "manifest", True) for root in search_roots
        )

    rows: list[dict] = []
    seen: set[str] = set()
    for root, location, source, _removable in plan:
        if not root.is_dir():
            continue
        is_omni_node = root.resolve() == omni_node.resolve()
        for directory in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
            if not directory.is_dir() or directory.name in {TRASH_DIRNAME, "__pycache__"}:
                continue
            if is_omni_node and directory.name == "extensions":
                continue
            if not _looks_like_extension(directory):
                continue
            key = str(directory.resolve())
            if key in seen:
                continue
            seen.add(key)
            row = _describe_directory(directory, location=location, source=source)
            # 内置模块属于插件本体，不提供卸载入口。
            row["removable"] = not is_omni_node
            rows.append(row)
    return tuple(rows)


def _is_writable(path: Path) -> bool:
    probe = path / ".ho_write_probe"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 安装
# ---------------------------------------------------------------------------

def install_from_zip(archive_path, *, target_root: Path | None = None) -> dict:
    """把扩展 ZIP 解压到安装位。返回 {ok, path, identifier, error}。"""
    archive = Path(archive_path)
    if not archive.is_file():
        return {"ok": False, "error": f"ZIP 不存在：{archive}"}
    if not zipfile.is_zipfile(archive):
        return {"ok": False, "error": f"不是合法的 ZIP：{archive}"}

    identifier = _peek_identifier(archive)
    root = _select_install_root(target_root, identifier=identifier)
    if root is None:
        return {"ok": False, "error": "没有可写的安装目录（插件目录只读且用户目录不可用）"}

    staging = root / f".staging-{int(time.time())}"
    try:
        with zipfile.ZipFile(archive) as zf:
            _extract_safely(zf, staging)
        payload = _locate_extension_payload(staging)
        if payload is None:
            shutil.rmtree(staging, ignore_errors=True)
            return {
                "ok": False,
                "error": (
                    f"ZIP 里没有找到扩展（需要 {MANIFEST_FILENAME} 或 "
                    f"{REGISTRATION_FILENAME}）"
                ),
            }
        # ZIP 没有顶层包装目录时 payload 就是暂存目录本身。此时把**内容**搬进
        # 目标名目录，避免 os.replace(dir, dir) 这种自改名失败。
        if payload == staging:
            destination = root / _payload_dir_name(payload)
            guarded = _guard_destination(destination, "安装")
            if guarded is not None:
                return guarded
            if destination.exists() and not _move_to_trash(destination):
                return {
                    "ok": False,
                    "error": f"无法腾出安装位（现有目录搬不动）：{destination}",
                }
            destination.mkdir(parents=True, exist_ok=True)
            for child in list(staging.iterdir()):
                os.replace(child, destination / child.name)
            shutil.rmtree(staging, ignore_errors=True)
        else:
            destination = root / payload.name
            guarded = _guard_destination(destination, "安装")
            if guarded is not None:
                return guarded
            if destination.exists() and not _move_to_trash(destination):
                return {
                    "ok": False,
                    "error": f"无法腾出安装位（现有目录搬不动）：{destination}",
                }
            os.replace(payload, destination)
            shutil.rmtree(staging, ignore_errors=True)
        # 目录名统一为清单 identifier（见 _payload_dir_name 的说明）。
        destination = _rename_to_identifier(destination)
        identifier = _read_identifier(destination) or destination.name
        _invalidate_import_caches()
        return {
            "ok": True,
            "path": str(destination),
            "identifier": identifier,
            "location": str(root),
        }
    except Exception as exc:  # noqa: BLE001 - 安装失败必须把暂存目录清干净
        shutil.rmtree(staging, ignore_errors=True)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _guard_destination(destination: Path, action: str) -> dict | None:
    """安装落点若已是开发检出，返回拒绝结果；否则返回 None。"""
    if not _is_development_checkout(destination):
        return None
    return {
        "ok": False,
        "error": (
            f"{destination.name} 是本机开发检出（含 "
            f"{DEVELOPMENT_MARKER_FILENAME} 或 .git），拒绝{action}覆盖。"
            "请改用 git 更新，或先移除该目录/标记"
        ),
    }


def install_from_directory(source_dir, *, target_root: Path | None = None) -> dict:
    """从本地目录复制安装扩展（开发期常用）。"""
    source = Path(source_dir)
    if not source.is_dir():
        return {"ok": False, "error": f"目录不存在：{source}"}
    if not (
        (source / MANIFEST_FILENAME).is_file()
        or (source / REGISTRATION_FILENAME).is_file()
    ):
        return {
            "ok": False,
            "error": (
                f"目录里没有 {MANIFEST_FILENAME} 或 {REGISTRATION_FILENAME}：{source}"
            ),
        }
    root = _select_install_root(target_root)
    if root is None:
        return {"ok": False, "error": "没有可写的安装目录"}

    destination = root / source.name
    try:
        guarded = _guard_destination(destination, "安装")
        if guarded is not None:
            return guarded
        if destination.exists() and not _move_to_trash(destination):
            return {
                "ok": False,
                "error": f"无法腾出安装位（现有目录搬不动）：{destination}",
            }
        shutil.copytree(
            source,
            destination,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".git", ".fetch-cache", "build", "runtime",
            ),
        )
        # 目录名统一为清单 identifier：带点号的版本后缀会变成非法 Python 标识符，
        # 导致扩展注册模块无法作为包导入。
        destination = _rename_to_identifier(destination)
        identifier = _read_identifier(destination) or destination.name
        _invalidate_import_caches()
        return {
            "ok": True,
            "path": str(destination),
            "identifier": identifier,
            "location": str(root),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _select_install_root(
    explicit: Path | None,
    *,
    identifier: str = "",
) -> Path | None:
    """选安装目录。

    未显式指定时优先插件内 `extensions/`；但若同一 identifier 已经存在于
    **插件内模块目录**（`OmniNode/<名字>/`，即随包自带的那份），则改装到用户目录，
    避免落一个同名扩展与内置模块打架。
    """
    if explicit is not None:
        target = Path(explicit)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        return target if _is_writable(target) else None

    bundled = bundled_extensions_dir()
    user_dir = user_extensions_dir()
    order = [bundled, user_dir]
    if identifier and _identifier_present_elsewhere(identifier, bundled):
        order = [user_dir, bundled]
    for candidate in order:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        if _is_writable(candidate):
            return candidate
    return None


def _is_development_checkout(directory: Path) -> bool:
    """判断目录是否是"本机开发版"（不可被安装流程搬走/覆盖/删除）。

    两个信号任一命中即视为开发检出：

    * 目录根有 `.hotools-dev` 标记文件（显式声明，推荐给非 git 管理的开发目录）；
    * 目录根有 `.git`（扩展仓库的开发检出）。

    保护在 ``_move_to_trash`` 里统一生效，因此卸载、安装覆盖、改名三条破坏性路径
    都拦得住——不会出现"更新一次把正在改的源码挪进回收站"。
    """
    try:
        if not directory.is_dir():
            return False
        if (directory / DEVELOPMENT_MARKER_FILENAME).is_file():
            return True
        return (directory / ".git").exists()
    except OSError:
        return False


def ensure_development_marker(directory: Path, *, write: bool = True) -> dict:
    """给开发检出打上 ``.hotools-dev`` 标记；返回 {ok, path, created, error}。"""
    directory = Path(directory)
    if not directory.is_dir():
        return {"ok": False, "error": f"目录不存在：{directory}"}
    marker = directory / DEVELOPMENT_MARKER_FILENAME
    existed = marker.is_file()
    if write and not existed:
        try:
            marker.write_text(DEVELOPMENT_MARKER_TEXT, encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": f"写入标记失败：{exc}"}
    return {"ok": True, "path": str(marker), "created": not existed}


def _identifier_present_elsewhere(identifier: str, install_root: Path) -> bool:
    """检查同一 identifier 是否已存在于插件内模块目录或仓库开发检出里。"""
    from .OmniNodeRegister import _read_extension_manifest

    omni_node = Path(__file__).resolve().parent
    for entry in omni_node.iterdir():
        if not entry.is_dir() or entry.name in {"extensions", "__pycache__"}:
            continue
        manifest_path = entry / MANIFEST_FILENAME
        if manifest_path.is_file():
            manifest, error = _read_extension_manifest(manifest_path)
            if not error and str(manifest.get("identifier") or "").strip() == identifier:
                return True
    # 扩展安装位里的**开发检出**也算"已存在"
    if install_root.is_dir():
        for entry in install_root.iterdir():
            if not entry.is_dir() or not _is_development_checkout(entry):
                continue
            manifest_path = entry / MANIFEST_FILENAME
            if manifest_path.is_file():
                manifest, error = _read_extension_manifest(manifest_path)
                if not error and str(manifest.get("identifier") or "").strip() == identifier:
                    return True
    return False


def _peek_identifier(archive: Path) -> str:
    """不解压整个包，读出 ZIP 内的清单 identifier（用于选安装目录）。"""
    try:
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                if name.replace("\\", "/").endswith(MANIFEST_FILENAME):
                    try:
                        data = json.loads(zf.read(name).decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if isinstance(data, dict):
                        value = str(
                            data.get("identifier") or data.get("id") or ""
                        ).strip()
                        if value:
                            return value
    except (OSError, zipfile.BadZipFile):
        return ""
    return ""


def _payload_dir_name(staging: Path) -> str:
    """安装目录名：优先用清单里的 identifier。

    发布 ZIP 常见的目录名是 ``<Name>-<version>``（带点号的版本号会变成非法 Python
    标识符，导致扩展注册模块无法导入），因此统一以 identifier 作为目录名。
    """
    from .OmniNodeRegister import _read_extension_manifest

    manifest_path = staging / MANIFEST_FILENAME
    if manifest_path.is_file():
        manifest, error = _read_extension_manifest(manifest_path)
        if not error:
            name = str(
                manifest.get("identifier") or manifest.get("id") or ""
            ).strip()
            if name:
                return name
    for child in staging.iterdir():
        if child.is_dir():
            nested_manifest = child / MANIFEST_FILENAME
            if nested_manifest.is_file():
                manifest, error = _read_extension_manifest(nested_manifest)
                if not error:
                    name = str(
                        manifest.get("identifier") or manifest.get("id") or ""
                    ).strip()
                    if name:
                        return name
    return "extension"


def _rename_to_identifier(directory: Path) -> Path:
    """把安装目录改名为清单 identifier（已是则原样返回）。"""
    wanted = _payload_dir_name(directory)
    if directory.name == wanted or not wanted or wanted == "extension":
        return directory
    target = directory.parent / wanted
    if target.exists():
        _move_to_trash(target)
    try:
        os.replace(directory, target)
    except OSError:
        return directory
    return target


def _extract_safely(archive: zipfile.ZipFile, destination: Path) -> None:
    """解压并拒绝路径穿越（zip-slip）与绝对路径成员。"""
    destination.mkdir(parents=True, exist_ok=True)
    resolved_root = destination.resolve()
    for member in archive.infolist():
        name = member.filename.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts:
            raise ValueError(f"ZIP 含非法路径成员：{member.filename}")
        archive.extract(member, destination)
        target = (destination / name).resolve()
        if not str(target).startswith(str(resolved_root)):
            raise ValueError(f"ZIP 成员越出目标目录：{member.filename}")


def _locate_extension_payload(staging: Path) -> Path | None:
    """在解压结果里定位扩展根：允许 ZIP 里套一层目录。"""
    candidates: list[Path] = []

    def _is_extension_root(path: Path) -> bool:
        if (path / MANIFEST_FILENAME).is_file():
            return True
        if (path / REGISTRATION_FILENAME).is_file():
            return True
        return any(path.glob(f"*/{REGISTRATION_FILENAME}"))

    if _is_extension_root(staging):
        candidates.append(staging)
    for child in sorted(staging.iterdir()):
        if child.is_dir() and _is_extension_root(child):
            candidates.append(child)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # 多个候选：优先带清单的，其次名字像仓库根的
    with_manifest = [c for c in candidates if (c / MANIFEST_FILENAME).is_file()]
    if len(with_manifest) == 1:
        return with_manifest[0]
    return candidates[0]


# ---------------------------------------------------------------------------
# 卸载
# ---------------------------------------------------------------------------

def uninstall(identifier_or_path, *, target_root: Path | None = None) -> dict:
    """卸载扩展：先移入 .trash，再尽力删除。

    返回 {ok, trashed, removed, pending, error}。``pending=True`` 表示文件仍被
    占用（通常是刚加载的 pyd），已移入回收目录，下次清理即可。

    ``target_root`` 与 install_from_zip 对称：指定时只在安装位里查找该
    identifier，不做全局描述符查找（测试 / 非默认安装位必需）。
    """
    from .OmniNodeRegister import find_extension_descriptor

    directory: Path | None = None
    identifier = str(identifier_or_path)

    if target_root is not None:
        candidate = Path(target_root) / identifier
        if candidate.is_dir():
            directory = candidate
    if directory is None:
        descriptor = find_extension_descriptor(identifier)
        if descriptor is not None:
            directory = Path(descriptor.directory)
        else:
            candidate = Path(identifier)
            if candidate.is_dir():
                directory = candidate

    if directory is None or not directory.is_dir():
        return {"ok": False, "error": f"找不到扩展：{identifier}"}

    if directory.parent.name == "OmniNode" and directory.name != "extensions":
        return {
            "ok": False,
            "error": (
                f"{directory.name} 位于插件包内部（内置模块），"
                "请先把它移出到 extensions/ 再卸载"
            ),
        }

    # 开发期保护：扩展安装位里可能是扩展仓库的开发检出（含 .git 或 .hotools-dev）。
    # 卸载它会连同仓库历史和未提交改动一起删掉，风险远大于收益，直接拒绝。
    if _is_development_checkout(directory):
        marker = DEVELOPMENT_MARKER_FILENAME
        return {
            "ok": False,
            "error": (
                f"{directory.name} 是本机开发检出（含 {marker} 或 .git），拒绝卸载；"
                "请在仓库里用 git 管理，或先移除该标记/手动移除目录"
            ),
        }

    trashed = _move_to_trash(directory)
    if trashed is None:
        return {"ok": False, "error": f"无法移动扩展目录：{directory}"}

    removed = _force_delete(trashed)
    _invalidate_import_caches()
    return {
        "ok": True,
        "trashed": str(trashed),
        "removed": removed,
        "pending": not removed,
    }


def _move_to_trash(directory: Path) -> Path | None:
    """把目录改名进同级 .trash/。被占用的文件不影响目录改名。

    **开发检出直接拒绝**：卸载、安装覆盖、改名都经这里，保护放在这一层才不会有
    漏网路径（曾经出现过"验证脚本一跑，把正在用的扩展目录挪进了回收站"）。
    调用方需要区分"拒绝"与"失败"时，先用 ``_is_development_checkout`` 判断。
    """
    if _is_development_checkout(directory):
        return None
    trash = _trash_dir(directory.parent)
    try:
        trash.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = trash / f"{directory.name}-{stamp}"
    suffix = 1
    while target.exists():
        target = trash / f"{directory.name}-{stamp}-{suffix}"
        suffix += 1
    try:
        os.replace(directory, target)
    except OSError:
        return None
    return target


def _force_delete(path: Path) -> bool:
    """尽力删除；被占用的文件留在原地，返回 False。"""
    try:
        shutil.rmtree(path)
        return True
    except OSError:
        return False


def purge_trash(*, target_root: Path | None = None) -> dict:
    """清理回收目录里残留的扩展（重启后调用即可真正删除）。

    ``target_root`` 指定时只清理该安装位（测试 / 非默认安装位）。
    """
    removed = 0
    pending = 0
    roots = (Path(target_root),) if target_root is not None else install_targets()
    for root in roots:
        trash = _trash_dir(root)
        if not trash.is_dir():
            continue
        for entry in sorted(trash.iterdir(), key=lambda p: p.name.casefold()):
            if not entry.is_dir():
                continue
            if _force_delete(entry):
                removed += 1
            else:
                pending += 1
    return {"ok": True, "removed": removed, "pending": pending}


def _invalidate_import_caches() -> None:
    import importlib

    importlib.invalidate_caches()


def _read_identifier(directory: Path) -> str:
    from .OmniNodeRegister import _read_extension_manifest

    manifest_path = directory / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return directory.name
    manifest, error = _read_extension_manifest(manifest_path)
    if error:
        return directory.name
    return str(manifest.get("identifier") or manifest.get("id") or directory.name)


# ---------------------------------------------------------------------------
# Blender 算子（偏好面板用）
# ---------------------------------------------------------------------------

def _reload_extensions(context) -> None:
    """安装/卸载后重建注册表，让扩展立即生效或消失。"""
    from .. import OmniNode

    prefs = context.preferences.addons[ADDON_PACKAGE].preferences
    if not prefs.hoTools_OmniNodeFeatures_enable:
        return
    # 走延迟重建入口：扩展开关不得反注册节点类（已有工程里可能有活实例）。
    apply_switch = getattr(OmniNode.OmniNodeRegister, "apply_extension_switch", None)
    if callable(apply_switch):
        apply_switch()
        return
    OmniNode.unregister()
    OmniNode.register()


def _forget_disabled(context, identifier: str) -> None:
    """把 identifier 从"已禁用扩展"列表里移除，让新装/更新的扩展立即可用。"""
    try:
        prefs = context.preferences.addons[ADDON_PACKAGE].preferences
    except (AttributeError, KeyError):
        return
    raw = getattr(prefs, "hoTools_omninode_disabled_extensions", "")
    kept = [item for item in str(raw or "").split("|") if item.strip() and item != identifier]
    updated = "|".join(kept)
    if updated != str(raw or ""):
        prefs.hoTools_omninode_disabled_extensions = updated


class HO_OT_omninode_install_extension(bpy.types.Operator):
    bl_idname = "ho.omninode_install_extension"
    bl_label = "安装扩展"
    bl_description = "从本地 ZIP 或目录安装 OmniNode 扩展"

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')  # type: ignore

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        path = self.filepath.strip()
        if not path:
            self.report({'ERROR'}, "请选择一个 ZIP 或目录")
            return {'CANCELLED'}
        candidate = Path(path)
        if candidate.is_dir():
            result = install_from_directory(candidate)
        elif candidate.is_file() and candidate.suffix.lower() == ".zip":
            result = install_from_zip(candidate)
        else:
            self.report({'ERROR'}, "只支持扩展 ZIP 或包含扩展的目录")
            return {'CANCELLED'}

        if not result.get("ok"):
            self.report({'ERROR'}, f"安装失败：{result.get('error')}")
            return {'CANCELLED'}
        _reload_extensions(context)
        self.report(
            {'INFO'},
            f"已安装扩展 {result.get('identifier')} → {result.get('location')}",
        )
        return {'FINISHED'}


def _request_release(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "HoTools-extension-manager",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GitHub 返回的 release 数据格式不正确")
    return payload


def find_release_asset(release: dict, abi: str | None = None) -> dict | None:
    """在 release 资产里挑出与当前 Python ABI 匹配的安装包。"""
    abi = abi or python_abi()
    suffix = f"-{abi}.zip"
    for asset in release.get("assets", ()) or ():
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if name.endswith(suffix) and url.startswith(EXTENSION_DOWNLOAD_PREFIX):
            return asset
    return None


def latest_extension_release() -> dict:
    """取扩展仓库的最新 release（含 tag、名称与匹配当前 ABI 的资产）。"""
    release = _request_release(f"{EXTENSION_API_ROOT}/releases/latest")
    tag = str(release.get("tag_name") or "").strip()
    if not tag:
        raise ValueError("最新 release 没有 tag")
    asset = find_release_asset(release)
    return {
        "tag": tag,
        "name": str(release.get("name") or tag),
        "published_at": str(release.get("published_at") or ""),
        "asset": asset,
        "asset_name": str(asset.get("name")) if asset else "",
        "download_url": str(asset.get("browser_download_url")) if asset else "",
        "abi": python_abi(),
        "available": asset is not None,
    }


def download_extension_release(url: str, target: Path) -> None:
    """把 release 资产下载到 target。"""
    if not url.startswith(EXTENSION_DOWNLOAD_PREFIX):
        raise ValueError(f"拒绝从非 GitHub 地址下载：{url}")
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url, headers={"User-Agent": "HoTools-extension-manager"}
    )
    with urllib.request.urlopen(request, timeout=300) as response, target.open(
        "wb"
    ) as output:
        shutil.copyfileobj(response, output)
    if not target.is_file() or target.stat().st_size == 0:
        raise ValueError("下载到的文件为空")


def _latest_download_url(asset_name: str, tag: str | None = None) -> str:
    """拼 release 资产下载直链。

    注意：**不能用 `/releases/latest/download/`**。本仓库的发布全是 prerelease
    （自动发版用时间戳 tag），`/releases/latest` 指向不到它们，直链会 404。
    必须带上具体 tag。
    """
    if tag:
        return f"https://github.com/{EXTENSION_REPOSITORY}/releases/download/{tag}/{asset_name}"
    return f"https://github.com/{EXTENSION_REPOSITORY}/releases/latest/download/{asset_name}"


def _latest_release_tag() -> str:
    """抓最新 release 的 tag，不查 API。

    `/releases/latest` 会 302 到 `/releases/tag/<tag>`（prerelease 会被落到
    `/releases`），因此读最终 URL 即可。这条路不消耗 GitHub API 配额——未认证
    请求每小时只有 60 次，实测很容易撞上限流导致按钮失效。
    """
    request = urllib.request.Request(
        f"https://github.com/{EXTENSION_REPOSITORY}/releases/latest",
        headers={"User-Agent": "HoTools-extension-manager"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        final_url = str(response.geturl() or "")
    match = re.search(r"/releases/tag/([^/?#]+)", final_url)
    if not match:
        raise ValueError(f"未能从 {final_url} 解析出 release tag")
    return match.group(1)


def download_latest_extension(target: Path, abi: str | None = None) -> dict:
    """下载最新 Release 里匹配本机 ABI 的安装包。

    返回 {tag, asset_name, url, size}。候选顺序（前两条都不走 API，因此不受
    未认证限流影响；API 只作为最后兜底）：
      1. 重定向抓 tag → /releases/download/<tag>/<资产名>
      2. /releases/latest/download/<资产名>（有正式 release 时成立）
      3. GitHub API 查最新 release（受限流影响，仅在前面都失败时尝试）
    """
    abi = abi or python_abi()
    asset_name = f"HoTools-Omninode-Physics-{abi}.zip"

    attempts: list[tuple[str, str]] = []
    tag = ""
    redirect_error: Exception | None = None
    try:
        tag = _latest_release_tag()
        attempts.append((tag, _latest_download_url(asset_name, tag)))
    except (OSError, ValueError, urllib.error.URLError) as exc:
        redirect_error = exc
    attempts.append(("", _latest_download_url(asset_name)))

    api_error: Exception | None = None
    release: dict | None = None
    last_error: Exception | None = None
    for candidate_tag, url in attempts:
        try:
            download_extension_release(url, target)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
            continue
        return {
            "tag": candidate_tag or tag or asset_name,
            "asset_name": asset_name,
            "url": url,
            "size": target.stat().st_size,
        }

    # 前面的直链都失败，才动用 API（可能已被限流）。
    try:
        release = latest_extension_release()
    except (OSError, ValueError, urllib.error.URLError) as exc:
        api_error = exc
    if release and release["available"]:
        try:
            download_extension_release(release["download_url"], target)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
        else:
            return {
                "tag": release["tag"],
                "asset_name": release["asset_name"],
                "url": release["download_url"],
                "size": target.stat().st_size,
            }

    details = [f"直链：{last_error or '无可用直链'}"]
    if redirect_error is not None:
        details.append(f"抓 tag：{redirect_error}")
    if api_error is not None:
        details.append(f"API：{api_error}")
    raise ValueError("；".join(details))


class HO_OT_omninode_fetch_extension(bpy.types.Operator):
    bl_idname = "ho.omninode_fetch_extension"
    bl_label = "从 GitHub 下载并安装扩展"
    bl_description = (
        "从物理世界扩展仓库的最新 Release 下载与本机 Blender 匹配的安装包"
        "（Blender 4.5 → py311，5.x → py313）并安装"
    )

    def execute(self, context):
        abi = python_abi()
        archive = Path(tempfile.mkdtemp(prefix="hotools-ext-")) / (
            f"HoTools-Omninode-Physics-{abi}.zip"
        )
        try:
            self.report({'INFO'}, f"正在下载最新扩展包（{abi}）…")
            info = download_latest_extension(archive, abi)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            shutil.rmtree(archive.parent, ignore_errors=True)
            self.report({'ERROR'}, f"下载失败：{exc}")
            return {'CANCELLED'}

        try:
            result = install_from_zip(archive)
            size_kib = archive.stat().st_size // 1024 if archive.is_file() else 0
        finally:
            shutil.rmtree(archive.parent, ignore_errors=True)

        if not result.get("ok"):
            self.report({'ERROR'}, f"安装失败：{result.get('error')}")
            return {'CANCELLED'}

        # 装好后清掉禁用记录，否则"下载安装"完仍然是被禁用状态，看着像没装上。
        identifier = str(result.get("identifier") or "")
        if identifier:
            _forget_disabled(context, identifier)
        _reload_extensions(context)
        self.report(
            {'INFO'},
            f"已安装扩展 {identifier}（{info['tag']}，{abi}，{size_kib} KiB）"
            f" → {result.get('location')}",
        )
        return {'FINISHED'}


class HO_OT_omninode_uninstall_extension(bpy.types.Operator):
    bl_idname = "ho.omninode_uninstall_extension"
    bl_label = "卸载扩展"
    bl_description = "从磁盘移除该扩展（移入回收目录，重启后彻底删除）"

    identifier: bpy.props.StringProperty(default="")  # type: ignore

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        result = uninstall(self.identifier)
        if not result.get("ok"):
            self.report({'ERROR'}, f"卸载失败：{result.get('error')}")
            return {'CANCELLED'}
        _reload_extensions(context)
        if result.get("pending"):
            self.report(
                {'WARNING'},
                "扩展已移入回收目录；文件仍被占用，重启 Blender 后会被清理",
            )
        else:
            self.report({'INFO'}, f"已卸载扩展 {self.identifier}")
        return {'FINISHED'}


class HO_OT_omninode_purge_extension_trash(bpy.types.Operator):
    bl_idname = "ho.omninode_purge_extension_trash"
    bl_label = "清理扩展回收站"
    bl_description = "删除之前卸载时因文件占用而残留的扩展目录"

    def execute(self, context):
        result = purge_trash()
        if result["pending"]:
            self.report(
                {'WARNING'},
                f"清理 {result['removed']} 项，仍有 {result['pending']} 项被占用",
            )
        else:
            self.report({'INFO'}, f"已清理 {result['removed']} 项")
        return {'FINISHED'}


CLASSES = (
    HO_OT_omninode_install_extension,
    HO_OT_omninode_fetch_extension,
    HO_OT_omninode_uninstall_extension,
    HO_OT_omninode_purge_extension_trash,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:  # noqa: BLE001 - 重复反注册不应阻断插件卸载
            pass


__all__ = [
    "CLASSES",
    "DEVELOPMENT_MARKER_FILENAME",
    "EXTENSION_REPOSITORY",
    "addon_root",
    "bundled_extensions_dir",
    "download_extension_release",
    "download_latest_extension",
    "ensure_development_marker",
    "extension_search_dirs",
    "find_release_asset",
    "install_from_directory",
    "install_from_zip",
    "install_targets",
    "installed_extensions",
    "latest_extension_release",
    "purge_trash",
    "python_abi",
    "register",
    "uninstall",
    "unregister",
    "user_extensions_dir",
]
