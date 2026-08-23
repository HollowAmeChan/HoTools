#!/usr/bin/env python3
"""Build and validate HoTools native extensions for Linux x86_64."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NativeSpec:
    abi: str
    python_version: tuple[int, int]


@dataclass(frozen=True)
class ModuleSpec:
    name: str
    target: str
    cmake_option: str


_NATIVE_SPECS = {
    "py311": NativeSpec("py311", (3, 11)),
    "py313": NativeSpec("py313", (3, 13)),
}

_MODULE_SPECS = {
    "native": ModuleSpec("native", "hotools_native", "HOTOOLS_BUILD_NATIVE"),
    "jolt": ModuleSpec("jolt", "hotools_jolt", "HOTOOLS_BUILD_JOLT"),
    "boolean": ModuleSpec(
        "boolean", "hotools_boolean", "HOTOOLS_BUILD_BOOLEAN"
    ),
}


def native_spec(abi: str) -> NativeSpec:
    try:
        return _NATIVE_SPECS[abi]
    except KeyError as exc:
        raise ValueError(f"unsupported ABI: {abi}") from exc


def module_spec(name: str) -> ModuleSpec:
    try:
        return _MODULE_SPECS[name]
    except KeyError as exc:
        raise ValueError(f"unsupported module: {name}") from exc


def validate_interpreter(
    spec: NativeSpec,
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


def cmake_configure_command(
    *,
    source: Path,
    build: Path,
    python: Path,
    runtime: Path,
    module: ModuleSpec,
) -> list[str]:
    enabled = {
        item.cmake_option: "ON" if item == module else "OFF"
        for item in _MODULE_SPECS.values()
    }
    return [
        "cmake",
        "-S",
        str(source),
        "-B",
        str(build),
        "-G",
        "Ninja",
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DHOTOOLS_PYTHON_EXECUTABLE={python}",
        f"-DHOTOOLS_RUNTIME_DIR={runtime}",
        *(f"-D{option}={value}" for option, value in enabled.items()),
    ]


def validate_artifact(
    artifact: Path,
    spec: NativeSpec,
    module: ModuleSpec,
    extension_suffix: str,
) -> None:
    expected_name = f"{module.target}{extension_suffix}"
    if artifact.name != expected_name:
        raise ValueError(
            f"native filename mismatch: expected {expected_name}, got {artifact.name}"
        )
    expected_tag = f"cpython-{spec.python_version[0]}{spec.python_version[1]}"
    if expected_tag not in artifact.name:
        raise ValueError(f"native filename has wrong ABI: {artifact.name}")
    if not artifact.is_file() or artifact.read_bytes()[:4] != b"\x7fELF":
        raise ValueError(f"native artifact is not ELF: {artifact}")


def validate_tool_outputs(
    file_output: str,
    ldd_output: str,
    dynamic_output: str,
) -> None:
    if "ELF" not in file_output or not re.search(r"x86[-_]64", file_output, re.I):
        raise ValueError(f"file did not report x86_64 ELF: {file_output.strip()}")
    if "not found" in ldd_output:
        raise ValueError(f"unresolved shared library: {ldd_output.strip()}")
    for match in re.finditer(
        r"\((?:RPATH|RUNPATH)\).*?\[([^]]*)\]", dynamic_output
    ):
        for entry in match.group(1).split(":"):
            if entry.startswith("/"):
                raise ValueError(f"absolute RPATH/RUNPATH is forbidden: {entry}")


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


def _tool_output(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout + result.stderr


def validate_built_artifact(
    artifact: Path,
    spec: NativeSpec,
    module: ModuleSpec,
    extension_suffix: str,
) -> None:
    validate_artifact(artifact, spec, module, extension_suffix)
    validate_tool_outputs(
        _tool_output(["file", str(artifact)]),
        _tool_output(["ldd", str(artifact)]),
        _tool_output(["readelf", "-d", str(artifact)]),
    )


def _write_manifest(
    runtime: Path,
    spec: NativeSpec,
    extension_suffix: str,
) -> None:
    modules = []
    for module in _MODULE_SPECS.values():
        artifact = runtime / f"{module.target}{extension_suffix}"
        if artifact.is_file():
            modules.append(artifact.name)
    manifest = {
        "schema": 1,
        "abi": spec.abi,
        "platform": "linux-x86_64",
        "python_version": ".".join(map(str, spec.python_version)),
        "extension_suffix": extension_suffix,
        "build_type": "Release",
        "compiler": os.environ.get("CXX", "system-default"),
        "modules": sorted(modules),
    }
    (runtime / "_hotools_native_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_modules(
    *,
    spec: NativeSpec,
    python: Path,
    modules: list[ModuleSpec],
    source: Path,
    build_root: Path,
    runtime: Path,
    jobs: int,
) -> list[Path]:
    python = python.resolve()
    source = source.resolve()
    build_root = build_root.resolve()
    runtime = runtime.resolve()
    if not python.is_file():
        raise ValueError(f"Python executable does not exist: {python}")
    probe = _probe_interpreter(python)
    validate_interpreter(
        spec,
        probe["version"],
        str(probe["platform"]),
        str(probe["machine"]),
    )
    extension_suffix = str(probe["extension_suffix"])
    expected = f".cpython-{spec.python_version[0]}{spec.python_version[1]}-"
    if not extension_suffix.startswith(expected) or not extension_suffix.endswith(".so"):
        raise ValueError(f"unexpected extension suffix: {extension_suffix}")

    runtime.mkdir(parents=True, exist_ok=True)
    build_environment = os.environ.copy()
    build_environment["CCACHE_DIR"] = str(build_root / "ccache")
    artifacts = []
    for module in modules:
        build = build_root / f"{spec.abi}-{module.name}"
        subprocess.run(
            cmake_configure_command(
                source=source,
                build=build,
                python=python,
                runtime=runtime,
                module=module,
            ),
            check=True,
            env=build_environment,
        )
        subprocess.run(
            [
                "cmake",
                "--build",
                str(build),
                "--target",
                module.target,
                "--parallel",
                str(jobs),
            ],
            check=True,
            env=build_environment,
        )
        artifact = runtime / f"{module.target}{extension_suffix}"
        validate_built_artifact(artifact, spec, module, extension_suffix)
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(runtime)
        subprocess.run(
            [str(python), "-c", f"import {module.target}; print({module.target}.__file__)"],
            check=True,
            env=environment,
        )
        artifacts.append(artifact)
        _write_manifest(runtime, spec, extension_suffix)
    return artifacts


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abi", required=True, choices=sorted(_NATIVE_SPECS))
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument(
        "--module",
        action="append",
        choices=list(_MODULE_SPECS),
        dest="modules",
    )
    parser.add_argument("--jobs", type=int, default=max(1, min(2, os.cpu_count() or 1)))
    parser.add_argument("--build-root", type=Path)
    parser.add_argument("--runtime-dir", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.jobs < 1:
        raise ValueError("--jobs must be positive")
    repo_root = Path(__file__).resolve().parents[1]
    spec = native_spec(args.abi)
    selected = args.modules or list(_MODULE_SPECS)
    artifacts = build_modules(
        spec=spec,
        python=args.python,
        modules=[module_spec(name) for name in selected],
        source=repo_root / "_native",
        build_root=args.build_root or repo_root / "_native" / "build" / "linux",
        runtime=args.runtime_dir
        or repo_root / "_Lib" / spec.abi / "linux-x86_64" / "HotoolsPackage",
        jobs=args.jobs,
    )
    for artifact in artifacts:
        print(artifact)
    return 0


if __name__ == "__main__":
    sys.exit(main())
