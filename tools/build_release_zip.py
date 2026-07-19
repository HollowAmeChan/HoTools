#!/usr/bin/env python3
"""Build one Blender-installable HoTools ZIP for a specific Python ABI."""

from __future__ import annotations

import argparse
import fnmatch
from pathlib import Path, PurePosixPath
import sys
import zipfile


SUPPORTED_ABIS = {
    "py311": "cp311-win_amd64",
    "py313": "cp313-win_amd64",
}


class ReleaseIgnore:
    """Small rsync-style matcher for the patterns used by .releaseignore."""

    def __init__(self, ignore_file: Path) -> None:
        self.patterns: list[tuple[str, bool, bool]] = []
        for line_number, raw_line in enumerate(
            ignore_file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            pattern = raw_line.strip()
            if not pattern or pattern.startswith("#"):
                continue
            if pattern.startswith("!"):
                raise ValueError(
                    f"{ignore_file}:{line_number}: negated patterns are not supported"
                )
            anchored = pattern.startswith("/")
            directory_only = pattern.endswith("/")
            pattern = pattern.strip("/")
            self.patterns.append((pattern, anchored, directory_only))

    def matches(self, relative_path: PurePosixPath, is_dir: bool) -> bool:
        parts = relative_path.parts
        path_text = relative_path.as_posix()
        for pattern, anchored, directory_only in self.patterns:
            if anchored:
                if directory_only:
                    if path_text == pattern or path_text.startswith(pattern + "/"):
                        return True
                elif fnmatch.fnmatchcase(path_text, pattern):
                    return True
                continue

            if "/" in pattern:
                candidates = [
                    "/".join(parts[index:]) for index in range(len(parts))
                ]
            else:
                candidates = list(parts if directory_only else parts[-1:])

            if directory_only:
                directory_parts = parts if is_dir else parts[:-1]
                if any(fnmatch.fnmatchcase(part, pattern) for part in directory_parts):
                    return True
            elif any(fnmatch.fnmatchcase(candidate, pattern) for candidate in candidates):
                return True
        return False


def collect_files(repo_root: Path, abi: str) -> list[Path]:
    ignore = ReleaseIgnore(repo_root / ".releaseignore")
    other_abis = set(SUPPORTED_ABIS) - {abi}
    files: list[Path] = []

    for path in sorted(repo_root.rglob("*")):
        relative = PurePosixPath(path.relative_to(repo_root).as_posix())
        if path.is_symlink():
            raise ValueError(f"Release input contains a symlink: {relative}")
        if ignore.matches(relative, path.is_dir()):
            continue
        if len(relative.parts) >= 2 and relative.parts[0] == "_Lib":
            if relative.parts[1] in other_abis:
                continue
        if path.is_file():
            files.append(path)

    return files


def validate_inputs(repo_root: Path, abi: str, files: list[Path]) -> None:
    relative_files = {
        PurePosixPath(path.relative_to(repo_root).as_posix()) for path in files
    }
    native_tag = SUPPORTED_ABIS[abi]
    required_files = {
        PurePosixPath("__init__.py"),
        PurePosixPath(f"_Lib/{abi}/PIL/__init__.py"),
        PurePosixPath(f"_Lib/{abi}/cffi/__init__.py"),
        PurePosixPath(f"_Lib/{abi}/pyoidn/__init__.py"),
        PurePosixPath(f"_Lib/{abi}/_cffi_backend.{native_tag}.pyd"),
        PurePosixPath(
            f"_Lib/{abi}/HotoolsPackage/hotools_jolt.{native_tag}.pyd"
        ),
        PurePosixPath(
            f"_Lib/{abi}/HotoolsPackage/hotools_native.{native_tag}.pyd"
        ),
    }
    missing = sorted(required_files - relative_files)
    if missing:
        raise ValueError(f"Missing target runtime file: {missing[0]}")


def validate_archive(output: Path, abi: str) -> tuple[int, list[str]]:
    with zipfile.ZipFile(output) as archive:
        members = archive.namelist()

    if not members or any(not member.startswith("HoTools/") for member in members):
        raise ValueError("ZIP must contain exactly one HoTools root directory")

    other_abis = set(SUPPORTED_ABIS) - {abi}
    forbidden_roots = {".git", ".github", ".agents", ".claude", "_native", "tools"}
    for member in members:
        path = PurePosixPath(member)
        relative_parts = path.parts[1:]
        if relative_parts and relative_parts[0] in forbidden_roots:
            raise ValueError(f"ZIP contains a development path: {member}")
        if any(part in {"test", "tests", "__pycache__"} for part in relative_parts):
            raise ValueError(f"ZIP contains a test/cache path: {member}")
        if relative_parts:
            name = relative_parts[-1]
            if any(
                fnmatch.fnmatchcase(name, pattern)
                for pattern in ("test_*.py", "_test_*.py", "*_test.py")
            ):
                raise ValueError(f"ZIP contains a test file: {member}")
        if any(member.startswith(f"HoTools/_Lib/{other}/") for other in other_abis):
            raise ValueError(f"ZIP contains a non-target ABI: {member}")

    return len(members), members


def build_zip(repo_root: Path, output: Path, abi: str) -> None:
    files = collect_files(repo_root, abi)
    validate_inputs(repo_root, abi, files)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for source in files:
            relative = PurePosixPath(source.relative_to(repo_root).as_posix())
            archive.write(source, (PurePosixPath("HoTools") / relative).as_posix())

    try:
        member_count, _ = validate_archive(output, abi)
    except Exception:
        output.unlink(missing_ok=True)
        raise

    size_mib = output.stat().st_size / (1024 * 1024)
    print(f"Built {output} ({size_mib:.2f} MiB, {member_count} files, {abi})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abi", choices=sorted(SUPPORTED_ABIS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    output = args.output.resolve()
    build_zip(repo_root, output, args.abi)
    return 0


if __name__ == "__main__":
    sys.exit(main())
