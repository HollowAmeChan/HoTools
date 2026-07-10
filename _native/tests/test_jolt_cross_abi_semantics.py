"""Rigid/Jolt 跨 CPython ABI 自动差分 smoke。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
RUNNER = (
    ROOT / "OmniNode" / "NodeTree" / "Function" / "physicsWorld"
    / "rigid" / "test" / "run_cross_abi_semantics.py"
)


def test_jolt_cross_abi_semantic_report():
    with tempfile.TemporaryDirectory(prefix="hotools-jolt-cross-abi-") as directory:
        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--id", "FREE-001",
                "--id", "BREAK-001",
                "--repeat", "1",
                "--artifact-dir", directory,
            ],
            cwd=str(ROOT),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        output = completed.stdout + completed.stderr
        if completed.returncode == 2 and "未找到可用的 CPython" in output:
            raise RuntimeError("SKIP: 需要本地 CPython 3.11 与 3.13")
        assert completed.returncode == 0, output
        reports = list(Path(directory).glob("*/cross-abi-report.json"))
        assert len(reports) == 1
        report = json.loads(reports[0].read_text(encoding="utf-8"))
        assert report["schema"] == "hotools_jolt_cross_abi_report_v1"
        assert report["passed"] is True
        assert report["fixture_count"] == 2
        assert report["failed_count"] == 0
        assert {item["id"] for item in report["fixtures"]} == {
            "FREE-001", "BREAK-001",
        }
