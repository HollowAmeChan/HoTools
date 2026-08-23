#!/usr/bin/env python3
"""Build one Blender-installable HoTools ZIP for an ABI and platform."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fnmatch
from pathlib import Path, PurePosixPath
import sys
import zipfile


@dataclass(frozen=True)
class ReleaseTarget:
    abi: str
    platform: str
    native_suffix: str
    runtime_root: PurePosixPath


_ABI_SUFFIXES = {
    "py311": {
        "windows-x86_64": ".cp311-win_amd64.pyd",
        "linux-x86_64": ".cpython-311-x86_64-linux-gnu.so",
    },
    "py313": {
        "windows-x86_64": ".cp313-win_amd64.pyd",
        "linux-x86_64": ".cpython-313-x86_64-linux-gnu.so",
    },
}
SUPPORTED_ABIS = tuple(_ABI_SUFFIXES)
SUPPORTED_PLATFORMS = ("windows-x86_64", "linux-x86_64")


def release_target(abi: str, platform: str) -> ReleaseTarget:
    try:
        suffix = _ABI_SUFFIXES[abi][platform]
    except KeyError as exc:
        raise ValueError(f"unsupported release target: {abi}/{platform}") from exc
    root = PurePosixPath("_Lib") / abi
    if platform == "linux-x86_64":
        root /= platform
    return ReleaseTarget(abi, platform, suffix, root)


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
                candidates = ["/".join(parts[index:]) for index in range(len(parts))]
            else:
                candidates = list(parts if directory_only else parts[-1:])

            if directory_only:
                directory_parts = parts if is_dir else parts[:-1]
                if any(fnmatch.fnmatchcase(part, pattern) for part in directory_parts):
                    return True
            elif any(fnmatch.fnmatchcase(candidate, pattern) for candidate in candidates):
                return True
        return False


def _matches_target_runtime(relative: PurePosixPath, target: ReleaseTarget) -> bool:
    if not relative.parts or relative.parts[0] != "_Lib":
        return True
    if len(relative.parts) == 1:
        return True
    if relative.parts[1] != target.abi:
        return False
    if len(relative.parts) == 2:
        return True
    third = relative.parts[2]
    if target.platform == "linux-x86_64":
        return third == target.platform
    return third not in SUPPORTED_PLATFORMS


def collect_files(repo_root: Path, target: ReleaseTarget) -> list[Path]:
    ignore = ReleaseIgnore(repo_root / ".releaseignore")
    files: list[Path] = []

    for path in sorted(repo_root.rglob("*")):
        relative = PurePosixPath(path.relative_to(repo_root).as_posix())
        if path.is_symlink():
            raise ValueError(f"Release input contains a symlink: {relative}")
        if ignore.matches(relative, path.is_dir()):
            continue
        if not _matches_target_runtime(relative, target):
            continue
        if path.is_file():
            files.append(path)

    return files


def _required_runtime_files(target: ReleaseTarget) -> set[PurePosixPath]:
    root = target.runtime_root
    suffix = target.native_suffix
    required = {
        PurePosixPath("__init__.py"),
        PurePosixPath("ShapekeyTools/shapekey_catalog.csv"),
        root / "PIL/__init__.py",
        root / "cffi/__init__.py",
        root / "pyoidn/__init__.py",
        root / f"_cffi_backend{suffix}",
    }
    required.update(
        root / "HotoolsPackage" / f"{module}{suffix}"
        for module in ("hotools_native", "hotools_jolt", "hotools_boolean")
    )
    if target.platform == "linux-x86_64":
        required.add(root / "pyoidn/oidn/lib/libOpenImageDenoise.so")
    return required


def validate_inputs(
    repo_root: Path, target: ReleaseTarget, files: list[Path]
) -> None:
    relative_files = {
        PurePosixPath(path.relative_to(repo_root).as_posix()) for path in files
    }
    missing = sorted(_required_runtime_files(target) - relative_files)
    if missing:
        raise ValueError(f"Missing target runtime file: {missing[0]}")


def validate_archive(
    output: Path, target: ReleaseTarget
) -> tuple[int, list[str]]:
    with zipfile.ZipFile(output) as archive:
        members = archive.namelist()
        if not members or any(not member.startswith("HoTools/") for member in members):
            raise ValueError("ZIP must contain exactly one HoTools root directory")

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
            relative = PurePosixPath(*relative_parts)
            if not _matches_target_runtime(relative, target):
                raise ValueError(f"ZIP contains a non-target runtime: {member}")

            lowered = member.lower()
            if target.platform == "linux-x86_64":
                if lowered.endswith((".pyd", ".dll", ".exe")) or "win_amd64" in lowered:
                    raise ValueError(f"Linux ZIP contains a Windows artifact: {member}")
                if not member.endswith("/") and archive.read(member)[:2] == b"MZ":
                    raise ValueError(f"Linux ZIP contains a PE binary: {member}")
            elif lowered.endswith(".so"):
                raise ValueError(f"Windows ZIP contains a Linux artifact: {member}")

    return len(members), members


def build_zip(
    repo_root: Path, output: Path, abi: str, platform: str
) -> None:
    target = release_target(abi, platform)
    files = collect_files(repo_root, target)
    validate_inputs(repo_root, target, files)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for source in files:
            relative = PurePosixPath(source.relative_to(repo_root).as_posix())
            archive.write(source, (PurePosixPath("HoTools") / relative).as_posix())

    try:
        member_count, _ = validate_archive(output, target)
    except Exception:
        output.unlink(missing_ok=True)
        raise

    size_mib = output.stat().st_size / (1024 * 1024)
    print(
        f"Built {output} ({size_mib:.2f} MiB, {member_count} files, "
        f"{abi}, {platform})"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abi", choices=SUPPORTED_ABIS, required=True)
    parser.add_argument("--platform", choices=SUPPORTED_PLATFORMS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_zip(
        args.repo_root.resolve(), args.output.resolve(), args.abi, args.platform
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
