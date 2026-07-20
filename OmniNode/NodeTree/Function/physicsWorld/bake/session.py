"""Shared identity, path, and manifest helpers for Physics World bake backends."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import uuid

import bpy


MANIFEST_SCHEMA = "hotools_physics_gn_bake_v1"
TARGET_UUID_KEY = "hotools_physics_bake_uuid"
_SAFE_PREFIX_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_prefix(value: str) -> str:
    prefix = _SAFE_PREFIX_RE.sub("_", str(value or "").strip()).strip("._")
    if not prefix:
        raise ValueError("物理烘焙文件前缀不能为空")
    return prefix


def resolve_cache_root(directory: str) -> Path:
    value = str(directory or "").strip()
    if not value:
        raise ValueError("物理烘焙缓存目录不能为空")
    if value.startswith("//") and not bpy.data.filepath:
        raise ValueError("使用 // 相对缓存目录前必须先保存 .blend")
    return Path(bpy.path.abspath(value)).resolve()


def manifest_path(root: Path, prefix: str) -> Path:
    return root / f"{prefix}.hotools-bake.json"


def read_manifest(root: Path, prefix: str) -> dict | None:
    path = manifest_path(root, prefix)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != MANIFEST_SCHEMA:
        return None
    return data


def write_manifest(root: Path, prefix: str, manifest: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    path = manifest_path(root, prefix)
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
    try:
        temp_path.write_text(payload, encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


__all__ = [
    "MANIFEST_SCHEMA",
    "TARGET_UUID_KEY",
    "manifest_path",
    "read_manifest",
    "resolve_cache_root",
    "safe_prefix",
    "write_manifest",
]
