"""HoTools release metadata and in-Blender GitHub updater."""

from __future__ import annotations

import json
import re
import shutil
import sys
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator


PLUGIN_DIR = Path(__file__).resolve().parent
VERSION_FILE = PLUGIN_DIR / "version_info.json"
DEFAULT_REPOSITORY = "HollowAmeChan/HoTools"
GITHUB_API = "https://api.github.com"
_TAG_TOKEN_RE = re.compile(r"\d+|[A-Za-z]+")
_DEVELOPMENT_VALUES = {"dev", "development", "local", "unknown"}


def read_version_info(path: Path = VERSION_FILE) -> dict:
    """Read the package metadata without making Blender RNA part of the API."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {
            "schema": 1,
            "version": "dev",
            "release_tag": "dev",
            "release_name": "HoTools development build",
            "repository": DEFAULT_REPOSITORY,
            "channel": "stable",
        }
    if not isinstance(data, dict):
        return {"schema": 1, "version": "dev", "release_tag": "dev"}
    return data


def is_development_build(metadata: dict | None = None) -> bool:
    """Return whether this checkout is a local/dev build excluded from updates."""
    metadata = metadata if metadata is not None else read_version_info()
    channel = str(metadata.get("channel") or "").strip().lower()
    version = str(metadata.get("version") or "").strip().lower()
    release_tag = str(metadata.get("release_tag") or "").strip().lower()
    return (
        channel in _DEVELOPMENT_VALUES
        or version in _DEVELOPMENT_VALUES
        or release_tag in _DEVELOPMENT_VALUES
    )


def _repository_url(repository: str) -> str:
    repository = str(repository or DEFAULT_REPOSITORY).strip().strip("/")
    if repository.startswith("https://github.com/"):
        repository = repository.removeprefix("https://github.com/").strip("/")
    if not re.fullmatch(r"[^/]+/[^/]+", repository):
        repository = DEFAULT_REPOSITORY
    return f"{GITHUB_API}/repos/{repository}"


def _version_key(value: str) -> tuple:
    """Return a deterministic comparison key for timestamp and semver tags."""
    text = str(value or "").strip().lstrip("vV")
    tokens = _TAG_TOKEN_RE.findall(text)
    if not tokens:
        return ((0, ""),)
    result = []
    for token in tokens:
        if token.isdigit():
            result.append((1, int(token)))
        else:
            result.append((0, token.lower()))
    return tuple(result)


def is_newer_version(current: str, latest: str) -> bool:
    current = str(current or "").strip()
    latest = str(latest or "").strip()
    if not latest or current == latest:
        return False
    if not current or current.lower() in {"dev", "development", "unknown"}:
        return True
    current_key = _version_key(current)
    latest_key = _version_key(latest)
    if latest_key != current_key:
        current_has_text = bool(re.search(r"[A-Za-z]", current.lstrip("vV")))
        latest_has_text = bool(re.search(r"[A-Za-z]", latest.lstrip("vV")))
        if current_key[: len(latest_key)] == latest_key and current_has_text and not latest_has_text:
            return True
        if latest_key[: len(current_key)] == current_key and not current_has_text and latest_has_text:
            return False
        return latest_key > current_key
    # Preserve update visibility for non-semver tags with different text.
    return current != latest


def python_abi() -> str:
    return f"py{sys.version_info.major}{sys.version_info.minor}"


def _request_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "HoTools-updater",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GitHub returned an invalid release response")
    return payload


def find_release_asset(release: dict, abi: str | None = None) -> dict | None:
    abi = abi or python_abi()
    assets = release.get("assets", ())
    if not isinstance(assets, list):
        return None
    candidates = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name", ""))
        url = str(asset.get("browser_download_url", ""))
        if name.endswith(f"-{abi}.zip") and url.startswith("https://github.com/"):
            candidates.append(asset)
    if not candidates:
        return None
    return candidates[0]


def check_for_update() -> dict:
    """Fetch the latest stable release and return a UI-friendly result."""
    local = read_version_info()
    current_tag = str(local.get("release_tag") or local.get("version") or "dev")
    if is_development_build(local):
        return {
            "current_version": str(local.get("version") or current_tag),
            "current_tag": current_tag,
            "latest_version": "",
            "latest_tag": "",
            "release_name": "",
            "published_at": "",
            "asset_name": "",
            "download_url": "",
            "update_available": False,
            "asset_available": False,
            "development_build": True,
        }
    repository = str(local.get("repository") or DEFAULT_REPOSITORY)
    release = _request_json(f"{_repository_url(repository)}/releases/latest")
    latest_tag = str(release.get("tag_name") or "").strip()
    if not latest_tag:
        raise ValueError("GitHub release has no tag")
    asset = find_release_asset(release)
    return {
        "current_version": str(local.get("version") or current_tag),
        "current_tag": current_tag,
        "latest_version": str(release.get("name") or latest_tag),
        "latest_tag": latest_tag,
        "release_name": str(release.get("name") or latest_tag),
        "published_at": str(release.get("published_at") or ""),
        "asset_name": str(asset.get("name")) if asset else "",
        "download_url": str(asset.get("browser_download_url")) if asset else "",
        "update_available": is_newer_version(current_tag, latest_tag),
        "asset_available": asset is not None,
        "development_build": False,
    }


def download_release(url: str, target: Path) -> None:
    if not url.startswith("https://github.com/"):
        raise ValueError("Refusing to download an untrusted release URL")
    request = urllib.request.Request(url, headers={"User-Agent": "HoTools-updater"})
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output)
    if not target.is_file() or target.stat().st_size == 0:
        raise ValueError("Downloaded release ZIP is empty")


def schedule_package_update(zip_path: Path, plugin_dir: Path = PLUGIN_DIR) -> Path:
    """Start a background Blender helper that replaces the package after exit."""
    helper_source = plugin_dir / "update_helper.py"
    if not helper_source.is_file():
        raise RuntimeError("HoTools update helper is missing")
    helper_copy = Path(tempfile.gettempdir()) / f"HoTools-update-helper-{os.getpid()}.py"
    shutil.copy2(helper_source, helper_copy)
    config_path = Path(tempfile.gettempdir()) / f"HoTools-update-{os.getpid()}.json"
    config_path.write_text(
        json.dumps(
            {
                "old_pid": os.getpid(),
                "zip_path": str(zip_path),
                "plugin_dir": str(plugin_dir),
                "blender_path": bpy.app.binary_path,
                "blend_path": bpy.data.filepath or "",
                "helper_path": str(helper_copy),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    try:
        result = bpy.ops.ho.restart_blender(
            "EXEC_DEFAULT",
            confirm_restart=True,
            startup_script=str(helper_copy),
            startup_script_config=str(config_path),
        )
        if "CANCELLED" in result:
            raise RuntimeError("Blender 拒绝启动更新脚本")
    except Exception:
        config_path.unlink(missing_ok=True)
        helper_copy.unlink(missing_ok=True)
        raise
    return config_path


def _prefs(context):
    addon = context.preferences.addons.get(__package__ or "HoTools")
    return addon.preferences if addon else None


class HO_OT_check_update(Operator):
    bl_idname = "ho.check_for_update"
    bl_label = "检查 HoTools 更新"
    bl_description = "从 GitHub 获取最新发布版并比较版本"

    def execute(self, context):
        prefs = _prefs(context)
        try:
            result = check_for_update()
        except (OSError, ValueError, urllib.error.URLError) as exc:
            if prefs:
                prefs.hoTools_update_status = f"检查失败: {exc}"
            self.report({"ERROR"}, f"检查更新失败: {exc}")
            return {"CANCELLED"}

        if prefs and result.get("development_build"):
            prefs.hoTools_update_current = result["current_tag"]
            prefs.hoTools_update_latest = ""
            prefs.hoTools_update_download_url = ""
            prefs.hoTools_update_asset_name = ""
            prefs.hoTools_update_status = "本地开发版本，不参与自动更新"
            self.report({"INFO"}, "当前是本地开发版本，已跳过 GitHub 更新检查")
            return {"FINISHED"}

        if prefs:
            prefs.hoTools_update_current = result["current_tag"]
            prefs.hoTools_update_latest = result["latest_tag"]
            prefs.hoTools_update_download_url = (
                result["download_url"]
                if result["update_available"] and result["asset_available"]
                else ""
            )
            prefs.hoTools_update_asset_name = (
                result["asset_name"]
                if result["update_available"] and result["asset_available"]
                else ""
            )
            if result["update_available"] and result["asset_available"]:
                prefs.hoTools_update_status = f"发现新版本 {result['latest_tag']}"
            elif result["update_available"]:
                prefs.hoTools_update_status = (
                    f"发现 {result['latest_tag']}，没有适用于当前 Python 的安装包"
                )
            else:
                prefs.hoTools_update_status = "当前已是最新版本"
        if result["update_available"] and result["asset_available"]:
            self.report({"INFO"}, f"发现新版本 {result['latest_tag']}")
        elif result["update_available"]:
            self.report({"WARNING"}, "有新版本，但没有匹配当前 Blender Python 的 ZIP")
        else:
            self.report({"INFO"}, "HoTools 已是最新版本")
        return {"FINISHED"}


class HO_OT_install_update(Operator):
    bl_idname = "ho.install_update"
    bl_label = "安装 HoTools 更新"
    bl_description = "下载最新安装包，关闭 Blender 后替换插件并重启"
    confirm_install: BoolProperty(
        name="确认安装并重启",
        description="安装完成后会重启 Blender；当前未保存内容不会自动保存",
        default=True,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "confirm_install")

    def execute(self, context):
        if not self.confirm_install:
            self.report({"WARNING"}, "请确认安装并重启 Blender")
            return {"CANCELLED"}
        prefs = _prefs(context)
        url = str(getattr(prefs, "hoTools_update_download_url", "") or "")
        tag = str(getattr(prefs, "hoTools_update_latest", "") or "")
        if not url or not tag:
            self.report({"WARNING"}, "请先检查更新")
            return {"CANCELLED"}

        safe_tag = re.sub(r"[^A-Za-z0-9._-]+", "_", tag.lstrip("v")) or "latest"
        temp_path = Path(tempfile.gettempdir()) / f"HoTools-update-{safe_tag}.zip"
        try:
            download_release(url, temp_path)
            schedule_package_update(temp_path)
        except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
            try:
                if prefs:
                    prefs.hoTools_update_status = f"安装失败: {exc}"
            except (AttributeError, ReferenceError, RuntimeError):
                # The addon may already be unregistered after addon_remove.
                pass
            self.report({"ERROR"}, f"更新安装失败: {exc}")
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return {"CANCELLED"}

        # restart_blender owns the delayed quit and the injected helper script.
        return {"FINISHED"}


CLASSES = (HO_OT_check_update, HO_OT_install_update)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


__all__ = [
    "CLASSES",
    "HO_OT_check_update",
    "HO_OT_install_update",
    "check_for_update",
    "find_release_asset",
    "is_newer_version",
    "is_development_build",
    "read_version_info",
]
