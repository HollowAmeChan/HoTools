"""在 CPython 3.11 与 3.13 间运行并差分 Rigid/Jolt 语义矩阵。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Sequence

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[5]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from compare_traces import compare_traces


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-root", type=Path, default=HERE / "fixtures",
        help="递归包含 fixture JSON 文件的目录。",
    )
    parser.add_argument("--id", action="append", default=[], help="指定 fixture ID，可重复传入。")
    parser.add_argument("--tag", action="append", default=[], help="筛选必须包含的标签，可重复传入。")
    parser.add_argument("--repeat", type=int, default=2, help="每套 ABI 的新世界重复次数，默认 2。")
    parser.add_argument(
        "--artifact-dir", type=Path, default=Path(r"C:\tmp\hotools_jolt_cross_abi"),
        help="跨 ABI 报告与子运行产物的父目录。",
    )
    parser.add_argument("--python311", type=Path, default=None, help="CPython 3.11 可执行文件。")
    parser.add_argument("--python313", type=Path, default=None, help="CPython 3.13 可执行文件。")
    parser.add_argument("--abs-tol", type=float, default=2.0e-5, help="绝对误差容差。")
    parser.add_argument("--rel-tol", type=float, default=1.0e-6, help="相对误差容差。")
    return parser


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    values = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if not isinstance(value, dict):
                raise RuntimeError(f"{path} 第 {line_number} 行不是 JSON object")
            values.append(value)
    return values


def _run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{stamp}-pid{os.getpid()}"


def _candidate_interpreters(major: int, minor: int) -> list[Path]:
    candidates: list[Path] = []
    if sys.version_info[:2] == (major, minor):
        candidates.append(Path(sys.executable))
    name = f"python{major}.{minor}"
    discovered = shutil.which(name) or shutil.which(f"python{major}{minor}")
    if discovered:
        candidates.append(Path(discovered))
    local_app_data_value = os.environ.get("LOCALAPPDATA")
    if local_app_data_value:
        local_app_data = Path(local_app_data_value)
        candidates.extend([
            local_app_data / "Programs" / "Python" / f"Python{major}{minor}" / "python.exe",
            local_app_data / "Microsoft" / "WindowsApps" / f"python{major}.{minor}.exe",
        ])
        windows_apps = local_app_data / "Microsoft" / "WindowsApps"
        if windows_apps.is_dir():
            candidates.extend(windows_apps.glob(
                f"PythonSoftwareFoundation.Python.{major}.{minor}_*/python.exe"
            ))
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate.resolve()))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _probe_interpreter(path: Path, expected: tuple[int, int]) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    script = (
        "import json,sys; print(json.dumps({"
        "'version':[sys.version_info.major,sys.version_info.minor,sys.version_info.micro],"
        "'executable':sys.executable,'python':sys.version}))"
    )
    completed = subprocess.run(
        [str(path), "-c", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    if completed.returncode != 0:
        return None
    try:
        info = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        return None
    if tuple(info.get("version", ())[:2]) != expected:
        return None
    info["requested_path"] = str(path.resolve())
    return info


def _resolve_interpreter(
    explicit: Path | None, major: int, minor: int,
) -> tuple[Path, dict[str, Any]]:
    candidates = [explicit] if explicit is not None else _candidate_interpreters(major, minor)
    for candidate in candidates:
        if candidate is None:
            continue
        info = _probe_interpreter(candidate, (major, minor))
        if info is not None:
            return candidate.resolve(), info
    detail = str(explicit) if explicit is not None else "、".join(str(item) for item in candidates)
    raise RuntimeError(f"未找到可用的 CPython {major}.{minor}：{detail or '无候选路径'}")


def _child_command(
    python: Path,
    abi: str,
    args: argparse.Namespace,
    artifact_dir: Path,
) -> list[str]:
    command = [
        str(python), str(HERE / "run_native_semantics.py"),
        "--fixture-root", str(args.fixture_root.resolve()),
        "--repeat", str(args.repeat),
        "--artifact-dir", str(artifact_dir),
        "--native-dir", str(REPO_ROOT / "_Lib" / abi / "HotoolsPackage"),
    ]
    for fixture_id in args.id:
        command.extend(("--id", fixture_id))
    for tag in args.tag:
        command.extend(("--tag", tag))
    return command


def _run_child(
    python: Path,
    abi: str,
    args: argparse.Namespace,
    run_root: Path,
) -> dict[str, Any]:
    child_root = run_root / abi
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        _child_command(python, abi, args, child_root),
        cwd=str(REPO_ROOT),
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    manifests = sorted(child_root.glob("*/manifest.json"))
    if len(manifests) != 1:
        raise RuntimeError(
            f"{abi} 子运行应产生一个 manifest，实际为 {len(manifests)}；"
            f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )
    manifest_path = manifests[0]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "abi": abi,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "manifest_path": str(manifest_path.resolve()),
        "manifest": manifest,
    }


def _fixture_map(child: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["id"]): item
        for item in child["manifest"].get("fixtures", [])
    }


def _trace_path(child: dict[str, Any], fixture_id: str) -> Path:
    artifact_dir = Path(child["manifest"]["artifact_dir"])
    return artifact_dir / fixture_id / "repeat-00.jsonl"


def _compare_children(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    abs_tol: float,
    rel_tol: float,
) -> list[dict[str, Any]]:
    left_fixtures = _fixture_map(left)
    right_fixtures = _fixture_map(right)
    fixture_ids = sorted(set(left_fixtures) | set(right_fixtures))
    results = []
    for fixture_id in fixture_ids:
        left_item = left_fixtures.get(fixture_id)
        right_item = right_fixtures.get(fixture_id)
        differences: list[str] = []
        max_abs_error = 0.0
        if left_item is None or right_item is None:
            differences.append("两套 ABI 的 fixture 集合不一致")
        else:
            if left_item.get("fixture_hash") != right_item.get("fixture_hash"):
                differences.append("fixture 内容 hash 不一致")
            if not left_item.get("passed") or not right_item.get("passed"):
                differences.append("至少一套 ABI 的语义运行失败")
            if not differences:
                comparison = compare_traces(
                    _read_jsonl(_trace_path(left, fixture_id)),
                    _read_jsonl(_trace_path(right, fixture_id)),
                    abs_tol=abs_tol,
                    rel_tol=rel_tol,
                )
                max_abs_error = comparison.max_abs_error
                differences.extend(comparison.differences)
        results.append({
            "id": fixture_id,
            "passed": not differences,
            "fixture_hash": (
                str(left_item.get("fixture_hash", "")) if left_item else ""
            ),
            "max_abs_error": max_abs_error,
            "differences": differences,
        })
    return results


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    if args.repeat < 1:
        raise RuntimeError("--repeat 必须大于等于 1")
    if args.abs_tol < 0.0 or args.rel_tol < 0.0:
        raise RuntimeError("误差容差不能为负数")
    python311, info311 = _resolve_interpreter(args.python311, 3, 11)
    python313, info313 = _resolve_interpreter(args.python313, 3, 13)
    run_root = args.artifact_dir.resolve() / _run_id()
    run_root.mkdir(parents=True, exist_ok=True)
    children = [
        _run_child(python311, "py311", args, run_root),
        _run_child(python313, "py313", args, run_root),
    ]
    fixture_results = _compare_children(
        children[0], children[1], abs_tol=args.abs_tol, rel_tol=args.rel_tol
    )
    child_passed = all(
        child["returncode"] == 0 and child["manifest"].get("failed") == 0
        for child in children
    )
    passed = child_passed and all(item["passed"] for item in fixture_results)
    report = {
        "schema": "hotools_jolt_cross_abi_report_v1",
        "passed": passed,
        "abs_tolerance": args.abs_tol,
        "rel_tolerance": args.rel_tol,
        "fixture_count": len(fixture_results),
        "passed_count": sum(1 for item in fixture_results if item["passed"]),
        "failed_count": sum(1 for item in fixture_results if not item["passed"]),
        "max_abs_error": max(
            (float(item["max_abs_error"]) for item in fixture_results), default=0.0
        ),
        "interpreters": {"py311": info311, "py313": info313},
        "children": [{
            "abi": child["abi"],
            "returncode": child["returncode"],
            "manifest_path": child["manifest_path"],
            "native_module": child["manifest"].get("native_module", ""),
        } for child in children],
        "fixtures": fixture_results,
    }
    report_path = run_root / "cross-abi-report.json"
    _write_json(report_path, report)
    for item in fixture_results:
        state = "通过" if item["passed"] else "失败"
        print(
            f"[{state}] {item['id']} 最大绝对误差={item['max_abs_error']:.9g}"
        )
        for difference in item["differences"][:10]:
            print(f"  {difference}")
    print(
        f"汇总：{report['passed_count']}/{report['fixture_count']} 通过；"
        f"最大绝对误差={report['max_abs_error']:.9g}；报告：{report_path}"
    )
    return (0 if passed else 1), report


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        code, _report = run(args)
        return code
    except Exception as exc:
        print(f"致命错误：{type(exc).__name__}：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
