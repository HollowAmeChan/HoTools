"""Approved Rigid/Jolt canonical golden regression gate."""

from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = (
    ROOT / "OmniNode" / "NodeTree" / "Function" / "physicsWorld" / "rigid" / "test"
)
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from manage_goldens import DEFAULT_GOLDEN_ROOT, check_goldens  # noqa: E402


def _native_dir() -> Path:
    abi = "py313" if sys.version_info >= (3, 13) else "py311"
    return Path(os.environ.get(
        "HOTOOLS_NATIVE_TEST_DIR",
        ROOT / "_Lib" / abi / "HotoolsPackage",
    ))


def test_jolt_approved_golden_matrix():
    report = check_goldens(
        fixture_root=TEST_ROOT / "fixtures",
        golden_root=DEFAULT_GOLDEN_ROOT,
        native_dir=_native_dir(),
    )
    failures = [
        (item["id"], item["differences"])
        for item in report["fixtures"]
        if not item["passed"]
    ]
    assert report["fixture_count"] == 60
    assert report["passed"], failures
