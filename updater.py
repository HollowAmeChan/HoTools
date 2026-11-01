"""HoTools release metadata and read-only GitHub version checks."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import bpy
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
    """Return whether this checkout is a local/dev build excluded from checks."""
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
            "update_available": False,
            "development_build": True,
        }
    repository = str(local.get("repository") or DEFAULT_REPOSITORY)
    release = _request_json(f"{_repository_url(repository)}/releases/latest")
    latest_tag = str(release.get("tag_name") or "").strip()
    if not latest_tag:
        raise ValueError("GitHub release has no tag")
    return {
        "current_version": str(local.get("version") or current_tag),
        "current_tag": current_tag,
        "latest_version": str(release.get("name") or latest_tag),
        "latest_tag": latest_tag,
        "release_name": str(release.get("name") or latest_tag),
        "published_at": str(release.get("published_at") or ""),
        "update_available": is_newer_version(current_tag, latest_tag),
        "development_build": False,
    }


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

        if prefs:
            prefs.hoTools_update_current = result["current_tag"]
            prefs.hoTools_update_latest = result["latest_tag"]

        if result.get("development_build"):
            message = "当前是本地开发版本，已跳过 GitHub 更新检查"
        elif result["update_available"]:
            message = f"发现新版本 {result['latest_tag']}，请获取安装包后手动安装"
        else:
            message = "HoTools 已是最新版本"
        if prefs:
            prefs.hoTools_update_status = message
        self.report({"INFO"}, message)
        return {"FINISHED"}


CLASSES = (HO_OT_check_update,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


__all__ = [
    "CLASSES",
    "HO_OT_check_update",
    "check_for_update",
    "is_newer_version",
    "is_development_build",
    "read_version_info",
]
