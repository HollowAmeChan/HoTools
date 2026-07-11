"""Rigid/Jolt 稳定性 runner 的短帧中文 smoke。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
RUNNER = (
    ROOT / "OmniNode" / "NodeTree" / "Function" / "physicsWorld"
    / "rigid" / "test" / "run_native_soak.py"
)


def test_jolt_soak_report_smoke():
    with tempfile.TemporaryDirectory(prefix="hotools-jolt-soak-") as directory:
        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--frames", "300",
                "--sample-every", "100",
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
        assert completed.returncode == 0, output
        reports = list(Path(directory).glob("*/soak-report.json"))
        assert len(reports) == 1, "应生成唯一 soak 报告"
        report = json.loads(reports[0].read_text(encoding="utf-8"))
        assert report["schema"] == "hotools_jolt_soak_report_v1"
        assert report["passed"] is True
        assert report["frames_per_scenario"] == 300
        assert {item["id"] for item in report["scenarios"]} == {
            "SOAK-STACK-001", "SOAK-CHAIN-001",
        }
        assert all(item["frames_completed"] == 300 for item in report["scenarios"])
        assert all(item["passed"] for item in report["scenarios"])
