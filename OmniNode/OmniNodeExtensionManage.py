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
import shutil
import time
import zipfile
from pathlib import Path

import bpy

MANIFEST_FILENAME = "extension.json"
REGISTRATION_FILENAME = "omninode_registration.py"
TRASH_DIRNAME = ".trash"
ADDON_PACKAGE = "HoTools"


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
            if destination.exists():
                _move_to_trash(destination)
            destination.mkdir(parents=True, exist_ok=True)
            for child in list(staging.iterdir()):
                os.replace(child, destination / child.name)
            shutil.rmtree(staging, ignore_errors=True)
        else:
            destination = root / payload.name
            if destination.exists():
                _move_to_trash(destination)
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
        if destination.exists():
            _move_to_trash(destination)
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
    # 扩展安装位里的**仓库开发检出**（含 .git）也算"已存在"
    if install_root.is_dir():
        for entry in install_root.iterdir():
            if not entry.is_dir() or not (entry / ".git").exists():
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

    # 开发期保护：扩展安装位里可能是扩展仓库的开发检出（含 .git）。
    # 卸载它会连同仓库历史和未提交改动一起删掉，风险远大于收益，直接拒绝。
    if (directory / ".git").exists():
        return {
            "ok": False,
            "error": (
                f"{directory.name} 看起来是扩展仓库的开发检出（含 .git），"
                "拒绝卸载；请在仓库里用 git 管理，或手动移除"
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
    """把目录改名进同级 .trash/。被占用的文件不影响目录改名。"""
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
    OmniNode.unregister()
    OmniNode.register()


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
    "addon_root",
    "bundled_extensions_dir",
    "extension_search_dirs",
    "install_from_directory",
    "install_from_zip",
    "install_targets",
    "installed_extensions",
    "purge_trash",
    "register",
    "uninstall",
    "unregister",
    "user_extensions_dir",
]
