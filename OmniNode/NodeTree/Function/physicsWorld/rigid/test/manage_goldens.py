"""Compare or explicitly approve versioned Rigid/Jolt canonical golden traces."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import traceback
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[5]
DEFAULT_GOLDEN_ROOT = HERE / "goldens" / "jolt-5.2.0_windows-x64_release"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from canonical import physical_frame, physical_trace_hash
from compare_traces import compare_traces
from fixture_runtime import NativeFixtureRuntime, default_native_dir, load_native_module
from schema import Fixture, FixtureError, discover_fixtures, load_fixture


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-root", type=Path, default=HERE / "fixtures")
    parser.add_argument("--golden-root", type=Path, default=DEFAULT_GOLDEN_ROOT)
    parser.add_argument("--native-dir", type=Path, default=None)
    parser.add_argument("--id", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--abs-tol", type=float, default=2.0e-5)
    parser.add_argument("--rel-tol", type=float, default=1.0e-6)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(r"C:\tmp\hotools_jolt_golden"),
    )
    parser.add_argument("--approve-golden", action="store_true")
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--reason", default="")
    return parser


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _write_trace(path: Path, trace: Sequence[Mapping[str, Any]]) -> tuple[str, int]:
    encoded = _json_bytes(list(trace))
    compressed = gzip.compress(encoded, compresslevel=9, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(compressed)
    return hashlib.sha256(compressed).hexdigest(), len(compressed)


def _read_trace(path: Path) -> list[dict[str, Any]]:
    value = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"golden trace must be a JSON object list: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{stamp}-pid{os.getpid()}"


def _load_selected(
    fixture_root: Path,
    requested_ids: Sequence[str],
    required_tags: Sequence[str],
) -> list[Fixture]:
    fixtures = [load_fixture(path) for path in discover_fixtures(fixture_root)]
    id_filter = set(requested_ids)
    tag_filter = set(required_tags)
    selected = [
        fixture for fixture in fixtures
        if (not id_filter or fixture.id in id_filter)
        and (not tag_filter or tag_filter.issubset(set(fixture.tags)))
    ]
    missing = sorted(id_filter - {fixture.id for fixture in selected})
    if missing:
        raise FixtureError(f"golden fixture not found: {', '.join(missing)}")
    if not selected:
        raise FixtureError("no golden fixtures selected")
    return sorted(selected, key=lambda item: item.id)


def _physical_trace(trace: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [physical_frame(frame) for frame in trace]


def _numeric_errors(left: Any, right: Any, errors: list[float]) -> None:
    if isinstance(left, bool) or isinstance(right, bool):
        return
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        a = float(left)
        b = float(right)
        if math.isfinite(a) and math.isfinite(b):
            errors.append(abs(a - b))
        return
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        for key in set(left) & set(right):
            if str(key) == "raw_f32_hex":
                continue
            _numeric_errors(left[key], right[key], errors)
        return
    sequence_types = (str, bytes, bytearray)
    if (
        isinstance(left, Sequence) and not isinstance(left, sequence_types)
        and isinstance(right, Sequence) and not isinstance(right, sequence_types)
    ):
        for a, b in zip(left, right):
            _numeric_errors(a, b, errors)


def _trace_summary(trace: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    frames = list(trace)
    return {
        "frame_count": len(frames),
        "first_frame": int(frames[0]["frame"]) if frames else -1,
        "last_frame": int(frames[-1]["frame"]) if frames else -1,
        "contact_event_count": sum(len(frame.get("contacts", ())) for frame in frames),
        "query_result_count": sum(len(frame.get("queries", ())) for frame in frames),
        "physical_hash": physical_trace_hash(frames),
        "first_frame_hash": (
            hashlib.sha256(_json_bytes(frames[0])).hexdigest() if frames else ""
        ),
        "last_frame_hash": (
            hashlib.sha256(_json_bytes(frames[-1])).hexdigest() if frames else ""
        ),
    }


def _diff_summary(
    old_trace: Sequence[Mapping[str, Any]] | None,
    new_trace: Sequence[Mapping[str, Any]],
    *,
    abs_tol: float,
    rel_tol: float,
) -> dict[str, Any]:
    new_summary = _trace_summary(new_trace)
    if old_trace is None:
        return {
            "old_exists": False,
            "comparison_passed": False,
            "max_abs_error": None,
            "rms_error": None,
            "differences": ["initial golden approval"],
            "old": None,
            "new": new_summary,
        }
    comparison = compare_traces(
        old_trace, new_trace, abs_tol=abs_tol, rel_tol=rel_tol,
    )
    errors: list[float] = []
    _numeric_errors(old_trace, new_trace, errors)
    rms = math.sqrt(sum(value * value for value in errors) / len(errors)) if errors else 0.0
    return {
        "old_exists": True,
        "comparison_passed": comparison.passed,
        "max_abs_error": comparison.max_abs_error,
        "rms_error": rms,
        "differences": list(comparison.differences),
        "old": _trace_summary(old_trace),
        "new": new_summary,
    }


def _load_manifest(golden_root: Path) -> dict[str, Any]:
    path = golden_root / "manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"golden manifest must be an object: {path}")
    if value.get("schema") != "hotools_jolt_golden_manifest_v1":
        raise ValueError("unsupported Jolt golden manifest schema")
    return value


def _run_fixtures(native, fixtures: Sequence[Fixture]) -> list[dict[str, Any]]:
    records = []
    for fixture in fixtures:
        result = NativeFixtureRuntime(native).run(fixture, 0)
        failures = [item for item in result.assertions if not item.get("passed")]
        if failures:
            raise RuntimeError(f"{fixture.id} assertions failed: {failures}")
        trace = _physical_trace(result.trace)
        records.append({
            "fixture": fixture,
            "trace": trace,
            "physical_hash": physical_trace_hash(trace),
        })
    return records


def check_goldens(
    *,
    fixture_root: Path,
    golden_root: Path,
    native_dir: Path,
    requested_ids: Sequence[str] = (),
    required_tags: Sequence[str] = (),
    abs_tol: float = 2.0e-5,
    rel_tol: float = 1.0e-6,
) -> dict[str, Any]:
    fixtures = _load_selected(fixture_root, requested_ids, required_tags)
    manifest = _load_manifest(golden_root)
    manifest_fixtures = manifest.get("fixtures")
    if not isinstance(manifest_fixtures, dict):
        raise ValueError("golden manifest fixtures must be an object")
    native = load_native_module(native_dir)
    results = []
    for record in _run_fixtures(native, fixtures):
        fixture = record["fixture"]
        expected = manifest_fixtures.get(fixture.id)
        differences: list[str] = []
        comparison = None
        if not isinstance(expected, dict):
            differences.append("fixture missing from golden manifest")
        elif expected.get("fixture_hash") != fixture.content_hash:
            differences.append("fixture hash changed; explicit reapproval required")
        else:
            trace_path = golden_root / str(expected.get("trace_file") or "")
            if not trace_path.is_file():
                differences.append(f"golden trace missing: {trace_path.name}")
            else:
                compressed_hash = _sha256_file(trace_path)
                if compressed_hash != expected.get("compressed_sha256"):
                    differences.append("golden trace compressed hash mismatch")
                golden_trace = _read_trace(trace_path)
                comparison = compare_traces(
                    golden_trace,
                    record["trace"],
                    abs_tol=abs_tol,
                    rel_tol=rel_tol,
                )
                differences.extend(comparison.differences)
                if expected.get("physical_hash") != physical_trace_hash(golden_trace):
                    differences.append("golden manifest physical hash mismatch")
        results.append({
            "id": fixture.id,
            "passed": not differences,
            "physical_hash": record["physical_hash"],
            "max_abs_error": comparison.max_abs_error if comparison else None,
            "differences": differences,
        })
    return {
        "schema": "hotools_jolt_golden_check_v1",
        "golden_id": str(manifest.get("id") or ""),
        "passed": all(item["passed"] for item in results),
        "fixture_count": len(results),
        "passed_count": sum(1 for item in results if item["passed"]),
        "failed_count": sum(1 for item in results if not item["passed"]),
        "fixtures": results,
    }


def approve_goldens(
    *,
    fixture_root: Path,
    golden_root: Path,
    native_dir: Path,
    reviewer: str,
    reason: str,
    abs_tol: float,
    rel_tol: float,
    artifact_dir: Path,
) -> dict[str, Any]:
    reviewer = reviewer.strip()
    reason = reason.strip()
    if not reviewer or not reason:
        raise ValueError("--approve-golden requires non-empty --reviewer and --reason")

    fixtures = _load_selected(fixture_root, (), ())
    native = load_native_module(native_dir)
    records = _run_fixtures(native, fixtures)
    old_manifest = None
    if (golden_root / "manifest.json").is_file():
        old_manifest = _load_manifest(golden_root)
    old_fixtures = (
        old_manifest.get("fixtures", {}) if isinstance(old_manifest, dict) else {}
    )

    artifact_root = artifact_dir.resolve() / _run_id()
    diffs = []
    new_entries = {}
    payloads = {}
    for record in records:
        fixture = record["fixture"]
        trace = record["trace"]
        old_trace = None
        old_entry = old_fixtures.get(fixture.id)
        if isinstance(old_entry, dict):
            old_path = golden_root / str(old_entry.get("trace_file") or "")
            if old_path.is_file():
                old_trace = _read_trace(old_path)
        diff = _diff_summary(
            old_trace, trace, abs_tol=abs_tol, rel_tol=rel_tol,
        )
        diff["id"] = fixture.id
        diffs.append(diff)

        trace_file = f"{fixture.id}.json.gz"
        compressed = gzip.compress(_json_bytes(trace), compresslevel=9, mtime=0)
        payloads[trace_file] = compressed
        new_entries[fixture.id] = {
            "fixture_hash": fixture.content_hash,
            "source": fixture.source,
            "tags": list(fixture.tags),
            "trace_file": trace_file,
            "trace_frames": len(trace),
            "physical_hash": record["physical_hash"],
            "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
            "compressed_bytes": len(compressed),
        }

    approval = {
        "approved_utc": datetime.now(timezone.utc).isoformat(),
        "approved_commit": _git_head(),
        "reviewer": reviewer,
        "reason": reason,
    }
    manifest = {
        "schema": "hotools_jolt_golden_manifest_v1",
        "id": "jolt-5.2.0_windows-x64_release",
        "jolt_version": "5.2.0",
        "runner": NativeFixtureRuntime.RUNNER_ID,
        "runner_version": 1,
        "fixture_schema": "hotools_jolt_fixture_v1",
        "native_module": Path(native.__file__).name,
        "native_module_sha256": _sha256_file(Path(native.__file__)),
        "contract_sha256": {
            "rigid/specs.py": _sha256_file(HERE.parent / "specs.py"),
            "rigid/backends/jolt.py": _sha256_file(HERE.parent / "backends" / "jolt.py"),
        },
        "build": {
            "configuration": "Release",
            "generator": "Visual Studio 17 2022",
            "compiler_toolchain": "MSVC / MSBuild 17.14",
            "job_system": "JobSystemSingleThreaded",
            "cross_platform_deterministic": False,
            "jolt_profiler": False,
            "jolt_debug_renderer": False,
            "msvc_runtime": "dynamic",
            "avx": False,
            "avx2": False,
        },
        "python": sys.version,
        "platform": platform.platform(),
        "abs_tolerance": abs_tol,
        "rel_tolerance": rel_tol,
        "approval": approval,
        "fixture_count": len(new_entries),
        "fixtures": new_entries,
    }
    approval_report = {
        "schema": "hotools_jolt_golden_approval_report_v1",
        "golden_id": manifest["id"],
        "fixture_count": len(diffs),
        "initial_approval": old_manifest is None,
        "approval": approval,
        "fixtures": diffs,
    }
    _write_json(artifact_root / "approval-report.json", approval_report)

    golden_root.mkdir(parents=True, exist_ok=True)
    for name, compressed in payloads.items():
        (golden_root / name).write_bytes(compressed)
    _write_json(golden_root / "manifest.json", manifest)
    return {
        "manifest": manifest,
        "approval_report": approval_report,
        "approval_report_path": str((artifact_root / "approval-report.json").resolve()),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.abs_tol < 0.0 or args.rel_tol < 0.0:
            raise ValueError("golden tolerances cannot be negative")
        native_dir = (args.native_dir or default_native_dir(REPO_ROOT)).resolve()
        if args.approve_golden:
            if args.id or args.tag:
                raise ValueError("golden approval must cover the complete fixture catalog")
            result = approve_goldens(
                fixture_root=args.fixture_root.resolve(),
                golden_root=args.golden_root.resolve(),
                native_dir=native_dir,
                reviewer=args.reviewer,
                reason=args.reason,
                abs_tol=args.abs_tol,
                rel_tol=args.rel_tol,
                artifact_dir=args.artifact_dir,
            )
            print(
                f"approved {result['manifest']['fixture_count']} fixtures; "
                f"report={result['approval_report_path']}"
            )
            return 0
        report = check_goldens(
            fixture_root=args.fixture_root.resolve(),
            golden_root=args.golden_root.resolve(),
            native_dir=native_dir,
            requested_ids=args.id,
            required_tags=args.tag,
            abs_tol=args.abs_tol,
            rel_tol=args.rel_tol,
        )
        for item in report["fixtures"]:
            state = "PASS" if item["passed"] else "FAIL"
            print(f"[{state}] {item['id']} max_abs={item['max_abs_error']}")
            for difference in item["differences"][:10]:
                print(f"  {difference}")
        print(
            f"summary: {report['passed_count']}/{report['fixture_count']} passed"
        )
        return 0 if report["passed"] else 1
    except Exception as exc:
        print(f"fatal: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
