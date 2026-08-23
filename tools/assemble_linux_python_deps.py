#!/usr/bin/env python3
"""Assemble reproducible Linux x86_64 Python dependencies for HoTools."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DependencySpec:
    abi: str
    python_version: tuple[int, int]
    requirements: Path
    required_packages: tuple[str, ...]
    extension_modules: tuple[str, ...]


_SPECS = {
    "py311": DependencySpec(
        abi="py311",
        python_version=(3, 11),
        requirements=Path("requirements/linux-py311.txt"),
        required_packages=("PIL", "cffi", "pycparser", "pypinyin", "pyoidn"),
        extension_modules=("_cffi_backend", "PIL/_imaging"),
    ),
    "py313": DependencySpec(
        abi="py313",
        python_version=(3, 13),
        requirements=Path("requirements/linux-py313.txt"),
        required_packages=("PIL", "cffi", "pycparser", "pypinyin", "pyoidn"),
        extension_modules=("_cffi_backend", "PIL/_imaging"),
    ),
}


def dependency_spec(abi: str) -> DependencySpec:
    try:
        return _SPECS[abi]
    except KeyError as exc:
        raise ValueError(f"unsupported ABI: {abi}") from exc


def validate_interpreter(
    spec: DependencySpec,
    reported_version: tuple[int, int] | list[int],
    reported_platform: str,
    reported_machine: str,
) -> None:
    if tuple(reported_version) != spec.python_version:
        raise ValueError(
            f"Python version mismatch: expected {spec.python_version}, "
            f"got {tuple(reported_version)}"
        )
    if reported_platform != "linux":
        raise ValueError(f"platform mismatch: expected linux, got {reported_platform}")
    if reported_machine.lower() not in {"x86_64", "amd64"}:
        raise ValueError(
            f"machine mismatch: expected x86_64, got {reported_machine}"
        )


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def validate_dependency_tree(
    root: Path,
    spec: DependencySpec,
    extension_suffix: str,
) -> dict[str, list[str]]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"dependency directory does not exist: {root}")

    expected_tag = f"cpython-{spec.python_version[0]}{spec.python_version[1]}"
    binaries: list[str] = []
    forbidden_suffixes = {".pyd", ".dll", ".exe"}
    cpython_tag = re.compile(r"\.cpython-(\d+)")

    for path in root.rglob("*"):
        relative = _relative(path, root)
        if path.is_symlink():
            raise ValueError(f"symlink is forbidden: {relative}")
        if not path.is_file():
            continue
        lowered = relative.lower()
        if path.suffix.lower() in forbidden_suffixes or "win_amd64" in lowered:
            raise ValueError(f"Windows artifact is forbidden: {relative}")
        with path.open("rb") as stream:
            header = stream.read(4)
        if header.startswith(b"MZ"):
            raise ValueError(f"PE binary is forbidden: {relative}")
        if ".cpython-" in path.name:
            match = cpython_tag.search(path.name)
            if match and match.group(1) != expected_tag.removeprefix("cpython-"):
                raise ValueError(f"wrong CPython ABI in {relative}")
        if header.startswith(b"\x7fELF"):
            binaries.append(relative)

    packages = []
    for package in spec.required_packages:
        marker = root / package / "__init__.py"
        if not marker.is_file():
            raise ValueError(f"required package is missing: {package}")
        packages.append(package)
    for module in spec.extension_modules:
        extension = root / f"{module}{extension_suffix}"
        if not extension.is_file():
            raise ValueError(f"required extension is missing: {module}")
        if extension.read_bytes()[:4] != b"\x7fELF":
            raise ValueError(f"required extension is not ELF: {_relative(extension, root)}")

    oidn_library = root / "pyoidn" / "oidn" / "lib" / "libOpenImageDenoise.so"
    if not oidn_library.is_file() or oidn_library.read_bytes()[:4] != b"\x7fELF":
        raise ValueError("required Linux OIDN ELF library is missing")

    return {"packages": sorted(packages), "binaries": sorted(binaries)}


def _probe_interpreter(python: Path) -> dict[str, object]:
    script = (
        "import json,platform,sys,sysconfig;"
        "print(json.dumps({'version':list(sys.version_info[:2]),"
        "'platform':sys.platform,'machine':platform.machine(),"
        "'extension_suffix':sysconfig.get_config_var('EXT_SUFFIX')}))"
    )
    result = subprocess.run(
        [str(python), "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _pinned_requirements(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _validate_oidn_linkage(root: Path) -> None:
    oidn_lib = root / "pyoidn" / "oidn" / "lib"
    libraries = [oidn_lib / "libOpenImageDenoise.so"]
    libraries.extend(sorted(oidn_lib.glob("libOpenImageDenoise_device_cpu.so.*")))
    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = str(oidn_lib)
    for library in libraries:
        result = subprocess.run(
            ["ldd", str(library)],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        output = result.stdout + result.stderr
        if "not found" in output:
            raise ValueError(f"unresolved OIDN shared library: {output.strip()}")


def assemble(
    spec: DependencySpec,
    python: Path,
    output: Path,
    repo_root: Path,
) -> Path:
    python = python.resolve()
    repo_root = repo_root.resolve()
    output = output.resolve()
    requirements = repo_root / spec.requirements
    if not python.is_file():
        raise ValueError(f"Python executable does not exist: {python}")
    if not requirements.is_file():
        raise ValueError(f"requirements file does not exist: {requirements}")

    probe = _probe_interpreter(python)
    validate_interpreter(
        spec,
        probe["version"],
        str(probe["platform"]),
        str(probe["machine"]),
    )
    extension_suffix = str(probe["extension_suffix"])
    expected_tag = f".cpython-{spec.python_version[0]}{spec.python_version[1]}-"
    if not extension_suffix.startswith(expected_tag) or not extension_suffix.endswith(".so"):
        raise ValueError(f"unexpected Linux extension suffix: {extension_suffix}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}-assemble-", dir=output.parent
    ) as temporary:
        staging = Path(temporary) / "installed"
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--only-binary=:all:",
                "--no-deps",
                "--requirement",
                str(requirements),
                "--target",
                str(staging),
            ],
            check=True,
        )
        previous_native = output / "HotoolsPackage"
        if previous_native.is_dir():
            shutil.copytree(previous_native, staging / "HotoolsPackage")
        inventory = validate_dependency_tree(staging, spec, extension_suffix)
        _validate_oidn_linkage(staging)
        manifest = {
            "schema": 1,
            "abi": spec.abi,
            "platform": "linux-x86_64",
            "python_version": ".".join(map(str, spec.python_version)),
            "extension_suffix": extension_suffix,
            "requirements": _pinned_requirements(requirements),
            **inventory,
        }
        (staging / "_hotools_dependency_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        backup = output.parent / f".{output.name}-backup-{uuid.uuid4().hex}"
        had_previous = output.exists()
        try:
            if had_previous:
                os.replace(output, backup)
            os.replace(staging, output)
        except BaseException:
            if had_previous and backup.exists() and not output.exists():
                os.replace(backup, output)
            raise
        else:
            if backup.exists():
                shutil.rmtree(backup)
    return output


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abi", required=True, choices=sorted(_SPECS))
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    spec = dependency_spec(args.abi)
    output = args.output or repo_root / "_Lib" / spec.abi / "linux-x86_64"
    assembled = assemble(spec, args.python, output, repo_root)
    print(assembled)
    return 0


if __name__ == "__main__":
    sys.exit(main())
