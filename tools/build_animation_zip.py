#!/usr/bin/env python3
"""Build the optional, Blender-version-independent Humanoid animation pack."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hotools_animation_pack", ROOT / "BoneTools/HumanoidDebug/animation_pack.py"
)
PACK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACK)


def build_animation_zip(repo_root: Path, output: Path, version: str) -> dict:
    directory = repo_root / "BoneTools/HumanoidDebug/animations" / PACK.PACK_DIRECTORY
    files = sorted(path for path in directory.rglob("*") if path.suffix.lower() == ".anim")
    manifest = {
        "kind": PACK.PACK_KIND, "schema": PACK.PACK_SCHEMA,
        "version": version, "files": [],
    }
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Invalid animation source: {path}")
        with path.open("rb") as stream:
            if stream.read(128).startswith(b"version https://git-lfs.github.com/spec/v1"):
                raise ValueError(f"Unresolved Git LFS pointer: {path}. Run 'git lfs pull'.")
        manifest["files"].append({
            "path": path.relative_to(directory).as_posix(),
            "size": path.stat().st_size,
            "sha256": PACK.file_digest(path),
        })
    PACK.validate_manifest(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr(PACK.MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            for entry in manifest["files"]:
                archive.write(directory / entry["path"], "animations/" + entry["path"])
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    print(f"Built {output} ({output.stat().st_size / 1024**2:.2f} MiB, {len(files)} animations)")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    build_animation_zip(args.repo_root.resolve(), args.output.resolve(), args.version)
