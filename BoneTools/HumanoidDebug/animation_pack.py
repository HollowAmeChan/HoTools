"""Optional animation pack downloads and transactions, independent of Blender."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import urllib.parse
import urllib.request
import zipfile


PACK_KIND = "hotools-humanoid-animations"
PACK_SCHEMA = 1
PACK_PREFIX = "HoTools-Humanoid-Animations-"
MANIFEST_NAME = "manifest.json"
INSTALLED_MANIFEST = ".installed.json"
PACK_DIRECTORY = "VRM"
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
MAX_FILES = 512
CHUNK_SIZE = 1024 * 1024
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPOSITORY = "HollowAmeChan/HoTools"


class CancelledError(Exception):
    pass


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError("已取消")


def _progress(callback, message, factor):
    if callback:
        callback(message, max(0.0, min(1.0, factor)))


def file_digest(path, cancel=None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            _check_cancel(cancel)
            digest.update(chunk)
    return digest.hexdigest()


def _is_lfs_pointer(path):
    if path.stat().st_size > 1024:
        return False
    with path.open("rb") as stream:
        return stream.read(128).startswith(b"version https://git-lfs.github.com/spec/v1")


def validate_manifest(manifest):
    if (
        not isinstance(manifest, dict)
        or manifest.get("kind") != PACK_KIND
        or manifest.get("schema") != PACK_SCHEMA
    ):
        raise ValueError("不是受支持的 HoTools 人型动画包")
    files = manifest.get("files")
    if not isinstance(files, list) or not 0 < len(files) <= MAX_FILES:
        raise ValueError("动画包文件列表无效")
    names = set()
    total = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("动画包文件记录无效")
        name = entry.get("path", "")
        if not isinstance(name, str):
            raise ValueError("动画包文件路径无效")
        path = PurePosixPath(name)
        if (
            not name or "\\" in name or ":" in name
            or any(char in name for char in '\x00<>?"|*')
            or any(ord(char) < 32 for char in name)
            or path.is_absolute() or ".." in path.parts
            or path.as_posix() != name or path.suffix.casefold() != ".anim"
            or any(part.endswith((" ", ".")) for part in path.parts)
            or any(re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)
                   for part in path.parts)
            or name.casefold() in names
        ):
            raise ValueError("动画包包含无效或重复的文件路径")
        names.add(name.casefold())
        size = entry.get("size")
        if type(size) is not int or not 0 < size <= MAX_FILE_BYTES:
            raise ValueError("动画文件大小无效")
        if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))):
            raise ValueError("动画文件缺少 SHA256 校验")
        total += size
    if total > MAX_TOTAL_BYTES:
        raise ValueError("动画包解压体积超出限制")
    return manifest


def _destination(root, name):
    root = Path(root)
    path = root / name
    if root.is_symlink() or path.is_symlink():
        raise ValueError("动画安装位置不能是符号链接")
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("动画文件路径超出安装目录") from exc
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError("动画目录不能包含符号链接")
    if path.exists() and not path.is_file():
        raise ValueError(f"动画文件位置已被目录占用: {name}")
    return path


def _installed_manifest(target):
    path = _destination(target, INSTALLED_MANIFEST)
    if not path.is_file():
        return None
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("动画安装记录无效")
    return validate_manifest(json.loads(path.read_text(encoding="utf-8")))


def installed_info(library):
    target = Path(library) / PACK_DIRECTORY
    try:
        manifest = _installed_manifest(target)
        if manifest:
            complete = all(
                (path := _destination(target, item["path"])).is_file()
                and path.stat().st_size == item["size"]
                for item in manifest["files"]
            )
            return {
                "managed": True, "complete": complete,
                "count": len(manifest["files"]),
                "version": str(manifest.get("version", "")),
            }
        count = sum(
            1 for path in target.rglob("*")
            if path.is_file() and not path.is_symlink()
            and path.suffix.lower() == ".anim" and not _is_lfs_pointer(path)
        )
        return {"managed": False, "complete": bool(count), "count": count, "version": ""}
    except (OSError, ValueError, TypeError):
        return {"managed": False, "complete": False, "count": 0, "version": ""}


def _commit_files(target, changes, backup, cancel):
    """Replace prepared files; restore every previous file on failure/cancel."""
    records = []
    try:
        for name, source in changes:
            _check_cancel(cancel)
            destination = _destination(target, name)
            old = backup / name
            if destination.exists():
                old.parent.mkdir(parents=True, exist_ok=True)
                destination.replace(old)
            records.append((destination, old))
            if source is not None:
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.replace(destination)
    except BaseException:
        for destination, old in reversed(records):
            destination.unlink(missing_ok=True)
            if old.exists():
                old.replace(destination)
        raise


def install_archive(archive_path, library, *, progress=None, cancel=None):
    library = Path(library).resolve()
    target = library / PACK_DIRECTORY
    if Path(archive_path).stat().st_size > MAX_DOWNLOAD_BYTES:
        raise ValueError("动画 ZIP 大小超出限制")
    library.mkdir(parents=True, exist_ok=True)
    try:
        previous = _installed_manifest(target)
    except (ValueError, TypeError):
        # A fresh download can repair damaged metadata. Existing files still
        # have to match the new package hashes before they may be replaced.
        previous = None
    old_files = {entry["path"]: entry for entry in previous["files"]} if previous else {}
    # Staging is outside the library so refresh never sees incomplete .anim files.
    with tempfile.TemporaryDirectory(prefix=".hotools-animations-", dir=library.parent) as temp:
        stage = Path(temp) / "new"
        stage.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_FILES + 1:
                raise ValueError("动画 ZIP 文件数量超出限制")
            names = [entry.filename for entry in entries]
            if len(names) != len(set(name.casefold() for name in names)):
                raise ValueError("动画 ZIP 包含重复文件")
            info = archive.getinfo(MANIFEST_NAME)
            if info.file_size > 1024 * 1024:
                raise ValueError("动画包清单过大")
            manifest = validate_manifest(json.loads(archive.read(info).decode("utf-8")))
            expected = {MANIFEST_NAME} | {"animations/" + item["path"] for item in manifest["files"]}
            if set(names) != expected:
                raise ValueError("动画 ZIP 内容与清单不一致")
            total = sum(item["size"] for item in manifest["files"])
            done = 0
            for item in manifest["files"]:
                _check_cancel(cancel)
                entry = archive.getinfo("animations/" + item["path"])
                if entry.file_size != item["size"] or stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError(f"动画 ZIP 文件无效: {item['path']}")
                staged = _destination(stage, item["path"])
                staged.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with archive.open(entry) as source, staged.open("wb") as output:
                    while chunk := source.read(CHUNK_SIZE):
                        _check_cancel(cancel)
                        digest.update(chunk)
                        output.write(chunk)
                        done += len(chunk)
                        _progress(progress, "校验并解压动画", done / total)
                if digest.hexdigest() != item["sha256"]:
                    raise ValueError(f"动画校验失败: {item['path']}")
                destination = _destination(target, item["path"])
                if destination.is_file() and not _is_lfs_pointer(destination):
                    actual = file_digest(destination, cancel)
                    old_digest = old_files.get(item["path"], {}).get("sha256")
                    if actual not in {item["sha256"], old_digest}:
                        raise ValueError(f"请先移走同名的自定义动画: {item['path']}")

        new_names = {item["path"] for item in manifest["files"]}
        changes = [(item["path"], stage / item["path"]) for item in manifest["files"]]
        for name, item in old_files.items():
            destination = _destination(target, name)
            if name not in new_names and destination.is_file():
                if file_digest(destination, cancel) == item["sha256"]:
                    changes.append((name, None))
        marker = stage / INSTALLED_MANIFEST
        marker.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        changes.append((INSTALLED_MANIFEST, marker))
        _progress(progress, "安装动画", 1.0)
        _commit_files(target, changes, Path(temp) / "backup", cancel)
    return manifest


def uninstall(library, *, progress=None, cancel=None):
    library = Path(library).resolve()
    target = library / PACK_DIRECTORY
    manifest = _installed_manifest(target)
    if manifest is None:
        raise ValueError("没有由 HoTools 安装的动画包")
    changes = []
    preserved = 0
    for index, item in enumerate(manifest["files"]):
        _check_cancel(cancel)
        destination = _destination(target, item["path"])
        if destination.is_file():
            if file_digest(destination, cancel) == item["sha256"]:
                changes.append((item["path"], None))
            else:
                preserved += 1
        _progress(progress, "移除官方动画", (index + 1) / len(manifest["files"]))
    removed = len(changes)
    changes.append((INSTALLED_MANIFEST, None))
    with tempfile.TemporaryDirectory(prefix=".hotools-animations-", dir=library.parent) as temp:
        _commit_files(target, changes, Path(temp) / "backup", cancel)
    # Only remove empty managed directories; additional user files stay in place.
    for name, _source in changes:
        parent = (target / name).parent
        while parent != library:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    return {"removed": removed, "preserved": preserved}


def read_metadata():
    try:
        data = json.loads((PLUGIN_ROOT / "version_info.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def release_asset(metadata):
    repository = str(metadata.get("repository") or DEFAULT_REPOSITORY)
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise ValueError("GitHub 仓库配置无效")
    tag = str(metadata.get("release_tag") or "dev")
    development = tag.lower() in {"dev", "development", "local"}
    suffix = "latest" if development else "tags/" + urllib.parse.quote(tag, safe="")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/releases/{suffix}",
        headers={"User-Agent": "HoTools-animation-pack", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))
    if not isinstance(release, dict) or not isinstance(release.get("assets"), list):
        raise ValueError("GitHub 返回的动画包发布信息无效")
    desired = None if development else metadata.get("animation_pack_asset")
    assets = [
        item for item in release.get("assets", [])
        if isinstance(item, dict)
        and str(item.get("name", "")).startswith(PACK_PREFIX)
        and str(item.get("name", "")).endswith(".zip")
        and (not desired or item.get("name") == desired)
    ]
    if len(assets) != 1:
        raise ValueError("该发布版本尚未提供动画包，请稍后重试或从本地 ZIP 安装")
    asset = assets[0]
    url = urllib.parse.urlparse(str(asset.get("browser_download_url", "")))
    if url.scheme != "https" or url.netloc != "github.com" or not url.path.startswith(f"/{repository}/releases/download/"):
        raise ValueError("动画包下载地址无效")
    size = asset.get("size")
    if type(size) is not int or not 0 < size <= MAX_DOWNLOAD_BYTES:
        raise ValueError("动画包下载大小无效")
    return asset


def download_and_install(library, *, metadata=None, progress=None, cancel=None):
    _check_cancel(cancel)
    _progress(progress, "查找动画包", 0.0)
    asset = release_asset(metadata if metadata is not None else read_metadata())
    _check_cancel(cancel)
    request = urllib.request.Request(
        asset["browser_download_url"], headers={"User-Agent": "HoTools-animation-pack"}
    )
    with tempfile.TemporaryDirectory(prefix="hotools-animation-download-") as temp:
        archive_path = Path(temp) / "animations.zip"
        digest = hashlib.sha256()
        received = 0
        with urllib.request.urlopen(request, timeout=30) as response, archive_path.open("wb") as output:
            while chunk := response.read(CHUNK_SIZE):
                _check_cancel(cancel)
                received += len(chunk)
                if received > asset["size"] or received > MAX_DOWNLOAD_BYTES:
                    raise ValueError("动画包下载大小与发布记录不一致")
                digest.update(chunk)
                output.write(chunk)
                _progress(progress, "下载动画包", received / asset["size"])
        if received != asset["size"]:
            raise ValueError("动画包下载不完整，请重试")
        expected_digest = asset.get("digest")
        if expected_digest and expected_digest != "sha256:" + digest.hexdigest():
            raise ValueError("动画 ZIP 校验失败，请重试")
        return install_archive(archive_path, library, progress=progress, cancel=cancel)
