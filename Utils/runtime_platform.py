"""Resolve HoTools runtime dependency paths by CPython ABI and platform."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import platform
import sys


class UnsupportedRuntimeError(RuntimeError):
    """Raised when HoTools has no dependency target for this runtime."""


@dataclass(frozen=True)
class RuntimeTarget:
    abi: str
    platform_id: str
    dependency_dir: Path
    native_dir: Path
    legacy_dependency_dir: Path | None


def resolve_runtime_target(
    addon_root: Path,
    python_version: tuple[int, int] | None = None,
    sys_platform: str | None = None,
    machine: str | None = None,
) -> RuntimeTarget:
    """Return the exact dependency target for a supported runtime."""

    version = python_version or sys.version_info[:2]
    abi_by_version = {(3, 11): "py311", (3, 13): "py313"}
    if version not in abi_by_version:
        raise UnsupportedRuntimeError(
            "HoTools supports Python 3.11 and 3.13; "
            f"found Python {version[0]}.{version[1]}"
        )

    os_name = sys_platform or sys.platform
    cpu = (machine or platform.machine()).lower()
    if cpu not in {"x86_64", "amd64"}:
        raise UnsupportedRuntimeError(
            f"HoTools does not support architecture {cpu}"
        )

    abi = abi_by_version[version]
    abi_dir = Path(addon_root) / "_Lib" / abi
    if os_name.startswith("linux"):
        platform_id = "linux-x86_64"
        legacy = None
    elif os_name == "win32":
        platform_id = "windows-x86_64"
        legacy = abi_dir
    else:
        raise UnsupportedRuntimeError(
            f"HoTools does not support platform {os_name}"
        )

    dependency_dir = abi_dir / platform_id
    return RuntimeTarget(
        abi=abi,
        platform_id=platform_id,
        dependency_dir=dependency_dir,
        native_dir=dependency_dir / "HotoolsPackage",
        legacy_dependency_dir=legacy,
    )


def configure_runtime_paths(target: RuntimeTarget) -> tuple[Path, ...]:
    """Prepend existing dependency paths, most specific path first."""

    candidates = [target.native_dir, target.dependency_dir]
    if target.legacy_dependency_dir is not None:
        candidates.extend(
            (
                target.legacy_dependency_dir / "HotoolsPackage",
                target.legacy_dependency_dir,
            )
        )

    inserted: list[Path] = []
    for directory in reversed(candidates):
        text = str(directory)
        if directory.exists() and text not in sys.path:
            sys.path.insert(0, text)
            inserted.append(directory)
    return tuple(reversed(inserted))
