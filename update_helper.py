"""Replace HoTools after Blender exits, then start Blender again.

This file is launched by the running Blender process as a separate background
Blender process. It must stay stdlib-only until the final quit call so that the
addon directory can be replaced safely on Windows.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile


def _detached_creationflags() -> int:
    if os.name != "nt":
        return 0
    return (
        getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
    )


def _launch_blender(args: list[str]) -> None:
    kwargs = {
        "close_fds": True,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        try:
            subprocess.Popen(args, creationflags=_detached_creationflags(), **kwargs)
            return
        except OSError:
            fallback = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
            )
            subprocess.Popen(args, creationflags=fallback, **kwargs)
            return
    subprocess.Popen(args, start_new_session=True, **kwargs)


def _config_path() -> Path:
    try:
        marker = sys.argv.index("--")
        return Path(sys.argv[marker + 1]).resolve()
    except (ValueError, IndexError):
        raise RuntimeError("HoTools update helper requires a config path")


def _process_alive(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _extract_release(zip_path: Path, staging_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.namelist()
        if not members or any(not name.startswith("HoTools/") for name in members):
            raise RuntimeError("Downloaded ZIP does not contain a HoTools root")
        for name in members:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError("Downloaded ZIP contains an unsafe path")
        archive.extractall(staging_dir)
    source = staging_dir / "HoTools"
    if not (source / "__init__.py").is_file():
        raise RuntimeError("Downloaded ZIP is not a valid HoTools package")
    return source


def _replace_package(source: Path, target: Path) -> None:
    backup = target.with_name(f"{target.name}.update-backup-{os.getpid()}")
    try:
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        os.replace(target, backup)
        os.replace(source, target)
    except Exception:
        if not target.exists() and backup.exists():
            os.replace(backup, target)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def main() -> int:
    config_path = _config_path()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    old_pid = int(config["old_pid"])
    zip_path = Path(config["zip_path"]).resolve()
    plugin_dir = Path(config["plugin_dir"]).resolve()
    blender_path = str(config["blender_path"])
    blend_path = str(config.get("blend_path") or "")
    helper_path = Path(config.get("helper_path") or "")

    # The old process may still be returning through Blender's operator stack.
    deadline = time.monotonic() + 30.0
    while _process_alive(old_pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    if _process_alive(old_pid):
        raise RuntimeError("Timed out waiting for the old Blender process")

    success = False
    error = None
    staging_dir = Path(tempfile.mkdtemp(prefix=".HoTools-update-", dir=str(plugin_dir.parent)))
    try:
        source = _extract_release(zip_path, staging_dir)
        _replace_package(source, plugin_dir)
        success = True
    except Exception as exc:
        error = exc
        print(f"HoTools package replacement failed: {exc}", file=sys.stderr)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        try:
            zip_path.unlink(missing_ok=True)
            config_path.unlink(missing_ok=True)
            helper_path.unlink(missing_ok=True)
        except OSError:
            pass

    if not success:
        raise error or RuntimeError("HoTools package replacement failed")

    args = [blender_path]
    if blend_path:
        args.append(blend_path)
    _launch_blender(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"HoTools update failed: {exc}", file=sys.stderr)
        raise
