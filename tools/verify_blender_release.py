#!/usr/bin/env python3
"""Install a HoTools ZIP in an isolated Blender user directory and verify it."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def verify(blender: Path, zip_path: Path, abi: str) -> None:
    blender = blender.resolve()
    zip_path = zip_path.resolve()
    if not blender.is_file():
        raise ValueError(f"Blender executable does not exist: {blender}")
    if not zip_path.is_file():
        raise ValueError(f"release ZIP does not exist: {zip_path}")

    verifier = Path(__file__).with_name("verify_release_install.py").resolve()
    with tempfile.TemporaryDirectory(prefix=f"hotools-blender-{abi}-") as temporary:
        isolated = Path(temporary)
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        directories = {
            "BLENDER_USER_CONFIG": isolated / "config",
            "BLENDER_USER_SCRIPTS": isolated / "scripts",
            "BLENDER_USER_DATAFILES": isolated / "datafiles",
            "XDG_CACHE_HOME": isolated / "xdg-cache",
            "XDG_CONFIG_HOME": isolated / "xdg-config",
            "XDG_DATA_HOME": isolated / "xdg-data",
        }
        for name, directory in directories.items():
            directory.mkdir(parents=True)
            environment[name] = str(directory)
        environment["PYTHONNOUSERSITE"] = "1"

        subprocess.run(
            [
                str(blender),
                "--background",
                "--factory-startup",
                "--python",
                str(verifier),
                "--",
                str(zip_path),
                abi,
            ],
            check=True,
            env=environment,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("blender", type=Path)
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("abi", choices=("py311", "py313"))
    args = parser.parse_args()
    verify(args.blender, args.zip_path, args.abi)
    return 0


if __name__ == "__main__":
    sys.exit(main())
