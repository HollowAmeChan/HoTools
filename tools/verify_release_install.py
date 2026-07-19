"""Install and enable a release ZIP inside an isolated Blender user directory."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import traceback

import bpy


def parse_args() -> argparse.Namespace:
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("abi", choices=("py311", "py313"))
    return parser.parse_args(arguments)


def verify(zip_path: Path, abi: str) -> None:
    expected_version = {"py311": (3, 11), "py313": (3, 13)}[abi]
    if sys.version_info[:2] != expected_version:
        raise RuntimeError(
            f"Expected Python {expected_version}, found {sys.version_info[:2]}"
        )

    result = bpy.ops.preferences.addon_install(filepath=str(zip_path), overwrite=True)
    if "FINISHED" not in result:
        raise RuntimeError(f"Addon installation failed: {result}")
    result = bpy.ops.preferences.addon_enable(module="HoTools")
    if "FINISHED" not in result:
        raise RuntimeError(f"Addon enable failed: {result}")

    import HoTools
    import cffi
    from PIL import Image
    import hotools_jolt
    import hotools_native
    import pyoidn

    addon_root = Path(HoTools.__file__).resolve().parent
    other_abi = "py313" if abi == "py311" else "py311"
    if (addon_root / "_Lib" / other_abi).exists():
        raise RuntimeError(f"Installed ZIP leaked {other_abi}")

    device = pyoidn.Device()
    device.commit()
    print(
        "HOTOOLS_RELEASE_INSTALL_OK",
        bpy.app.version_string,
        abi,
        Image.__version__,
        cffi.__version__,
        type(device).__name__,
        hotools_jolt.__name__,
        hotools_native.__name__,
    )
    bpy.ops.wm.quit_blender()


def main() -> None:
    args = parse_args()
    verify(args.zip_path.resolve(), args.abi)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc()
        os._exit(1)
