"""通过 hotools_jolt 运行声明式 Rigid/Jolt 语义 fixture。

示例：
    python run_native_semantics.py --tag p0
    python run_native_semantics.py --id FREE-001 --repeat 10
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import sys
import traceback
from typing import Any, Sequence

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[5]
if __package__ in {None, ""}:
    sys.path.insert(0, str(HERE))
    from canonical import traces_bitwise_equal
    from fixture_runtime import NativeFixtureRuntime, default_native_dir, load_native_module
    from schema import Fixture, FixtureError, discover_fixtures, load_fixture
else:
    from .canonical import traces_bitwise_equal
    from .fixture_runtime import NativeFixtureRuntime, default_native_dir, load_native_module
    from .schema import Fixture, FixtureError, discover_fixtures, load_fixture


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-root", type=Path, default=HERE / "fixtures",
        help="递归包含 fixture JSON 文件的目录。",
    )
    parser.add_argument("--id", action="append", default=[], help="运行指定 fixture ID，可重复传入。")
    parser.add_argument("--tag", action="append", default=[], help="筛选必须包含的标签，可重复传入。")
    parser.add_argument("--repeat", type=int, default=2, help="新建世界重复次数，默认 2。")
    parser.add_argument(
        "--artifact-dir", type=Path, default=Path(r"C:\tmp\hotools_jolt_test"),
        help="测试产物的父目录。",
    )
    parser.add_argument(
        "--native-dir", type=Path, default=None,
        help="包含当前 Python ABI 对应 hotools_jolt 的目录。",
    )
    parser.add_argument("--list", action="store_true", help="只列出选中的 fixture，不执行。")
    return parser


def _load_selected(args: argparse.Namespace) -> list[Fixture]:
    selected: list[Fixture] = []
    requested_ids = set(args.id)
    required_tags = set(args.tag)
    seen_ids: set[str] = set()
    for path in discover_fixtures(args.fixture_root):
        fixture = load_fixture(path)
        if fixture.id in seen_ids:
            raise FixtureError(f"duplicate fixture id across files: {fixture.id}")
        seen_ids.add(fixture.id)
        if requested_ids and fixture.id not in requested_ids:
            continue
        if required_tags and not required_tags.issubset(set(fixture.tags)):
            continue
        selected.append(fixture)
    missing = sorted(requested_ids - {fixture.id for fixture in selected})
    if missing:
        raise FixtureError(f"requested fixture ids were not found/selected: {', '.join(missing)}")
    if not selected:
        raise FixtureError("no fixtures selected")
    return sorted(selected, key=lambda item: item.id)


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, values: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            stream.write("\n")


def _run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{stamp}-pid{os.getpid()}"


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    if args.repeat < 1:
        raise FixtureError("--repeat must be >= 1")
    fixtures = _load_selected(args)
    if args.list:
        for fixture in fixtures:
            print(f"{fixture.id}\t{','.join(fixture.tags)}\t{fixture.title}")
        return 0, {"listed": len(fixtures)}

    native_dir = (args.native_dir or default_native_dir(REPO_ROOT)).resolve()
    native = load_native_module(native_dir)
    run_root = args.artifact_dir.resolve() / _run_id()
    started = datetime.now(timezone.utc)
    fixture_results: list[dict[str, Any]] = []

    for fixture in fixtures:
        repeats = []
        reference_trace = None
        deterministic = True
        fixture_error = ""
        for repeat_index in range(args.repeat):
            try:
                result = NativeFixtureRuntime(native).run(fixture, repeat_index)
                repeat_dir = run_root / _safe_name(fixture.id)
                _write_jsonl(repeat_dir / f"repeat-{repeat_index:02d}.jsonl", result.trace)
                _write_json(repeat_dir / f"assertions-{repeat_index:02d}.json", result.assertions)
                if reference_trace is None:
                    reference_trace = result.trace
                elif not traces_bitwise_equal(reference_trace, result.trace):
                    deterministic = False
                repeats.append({
                    "repeat": repeat_index,
                    "passed": result.passed,
                    "physical_hash": result.physical_hash,
                    "assertions": result.assertions,
                    "trace_frames": len(result.trace),
                })
            except Exception as exc:
                fixture_error = f"{type(exc).__name__}: {exc}"
                repeats.append({
                    "repeat": repeat_index,
                    "passed": False,
                    "physical_hash": "",
                    "assertions": [],
                    "trace_frames": 0,
                    "error": fixture_error,
                    "traceback": traceback.format_exc(),
                })
                deterministic = False
                break
        passed = (
            len(repeats) == args.repeat
            and all(item["passed"] for item in repeats)
            and deterministic
        )
        fixture_record = {
            "id": fixture.id,
            "title": fixture.title,
            "source": fixture.source,
            "tags": list(fixture.tags),
            "fixture_path": str(fixture.path),
            "fixture_hash": fixture.content_hash,
            "passed": passed,
            "deterministic_bitwise": deterministic,
            "error": fixture_error,
            "repeats": repeats,
        }
        fixture_results.append(fixture_record)
        status = "PASS" if passed else "FAIL"
        hashes = sorted({item["physical_hash"][:12] for item in repeats if item["physical_hash"]})
        print(f"[{status}] {fixture.id} repeats={len(repeats)} hash={','.join(hashes) or '-'}")
        if not passed:
            for item in repeats:
                for assertion in item.get("assertions", []):
                    if not assertion.get("passed"):
                        print(f"  assertion {assertion['kind']}: {assertion['message']}")
                if item.get("error"):
                    print(f"  {item['error']}")

    finished = datetime.now(timezone.utc)
    passed_count = sum(1 for item in fixture_results if item["passed"])
    summary = {
        "schema": "hotools_jolt_native_run_v1",
        "runner": NativeFixtureRuntime.RUNNER_ID,
        "started_utc": started.isoformat(),
        "finished_utc": finished.isoformat(),
        "duration_seconds": (finished - started).total_seconds(),
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "native_module": str(Path(native.__file__).resolve()),
        "native_dir": str(native_dir),
        "fixture_root": str(args.fixture_root.resolve()),
        "repeat": args.repeat,
        "passed": passed_count,
        "failed": len(fixture_results) - passed_count,
        "total": len(fixture_results),
        "fixtures": fixture_results,
        "artifact_dir": str(run_root),
    }
    _write_json(run_root / "manifest.json", summary)
    print(
        f"summary: {summary['passed']}/{summary['total']} passed; "
        f"artifacts={run_root}"
    )
    return (0 if summary["failed"] == 0 else 1), summary


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        code, _summary = run(args)
        return code
    except Exception as exc:
        print(f"fatal: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
