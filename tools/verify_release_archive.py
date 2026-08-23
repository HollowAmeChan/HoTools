#!/usr/bin/env python3
"""Validate and import a Linux release ZIP with matching standalone Python."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import sys
import tempfile
import zipfile

from build_release_zip import release_target, validate_archive


def verify(archive_path: Path, abi: str) -> None:
    target = release_target(abi, "linux-x86_64")
    expected_version = {"py311": (3, 11), "py313": (3, 13)}[abi]
    if sys.version_info[:2] != expected_version:
        raise RuntimeError(
            f"Expected Python {expected_version}, found {sys.version_info[:2]}"
        )
    validate_archive(archive_path, target)

    with tempfile.TemporaryDirectory(prefix="hotools-release-") as temporary:
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(temporary)
        runtime = Path(temporary) / "HoTools" / Path(target.runtime_root.as_posix())
        sys.path[:0] = [str(runtime / "HotoolsPackage"), str(runtime)]
        modules = [
            importlib.import_module(name)
            for name in (
                "PIL",
                "cffi",
                "pyoidn",
                "hotools_native",
                "hotools_jolt",
                "hotools_boolean",
            )
        ]
        device = modules[2].Device()
        device.commit()
        if device.get_error() is not None:
            raise RuntimeError(f"OIDN device error: {device.get_error()}")
        for module in modules:
            module_file = Path(module.__file__).resolve()
            if not module_file.is_relative_to(runtime):
                raise RuntimeError(f"Module escaped packaged runtime: {module_file}")
        print("HOTOOLS_RELEASE_ARCHIVE_OK", abi, *(module.__name__ for module in modules))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("abi", choices=("py311", "py313"))
    args = parser.parse_args()
    verify(args.zip_path.resolve(), args.abi)
    return 0


if __name__ == "__main__":
    sys.exit(main())
