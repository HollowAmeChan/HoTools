"""声明式 Rigid/Jolt 语义矩阵的 native 回归入口。"""

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

from canonical import traces_bitwise_equal  # noqa: E402
from fixture_runtime import NativeFixtureRuntime, load_native_module  # noqa: E402
from schema import discover_fixtures, load_fixture  # noqa: E402


def _native_dir() -> Path:
    py_lib = "py313" if sys.version_info >= (3, 13) else "py311"
    return Path(os.environ.get(
        "HOTOOLS_NATIVE_TEST_DIR",
        ROOT / "_Lib" / py_lib / "HotoolsPackage",
    ))


def _fixtures():
    return [
        load_fixture(path)
        for path in discover_fixtures(TEST_ROOT / "fixtures" / "p0")
    ]


def test_jolt_semantic_fixture_catalog():
    fixtures = _fixtures()
    ids = [fixture.id for fixture in fixtures]
    assert ids == sorted(ids), "semantic fixture discovery order must be stable"
    assert len(ids) == len(set(ids)), "semantic fixture ids must be unique"
    assert {"BODY-001", "FREE-001", "FREE-002", "FREE-003"}.issubset(ids)
    for fixture in fixtures:
        assert "p0" in fixture.tags
        assert fixture.assertions
        assert fixture.sample_frames[0] == 0


def test_jolt_p0_semantic_matrix():
    native = load_native_module(_native_dir())
    for fixture in _fixtures():
        first = NativeFixtureRuntime(native).run(fixture, 0)
        second = NativeFixtureRuntime(native).run(fixture, 1)
        failures = [item for item in first.assertions + second.assertions if not item["passed"]]
        assert not failures, f"{fixture.id} semantic assertions failed: {failures}"
        assert first.physical_hash == second.physical_hash, (
            f"{fixture.id} physical hash changed across fresh worlds"
        )
        assert traces_bitwise_equal(first.trace, second.trace), (
            f"{fixture.id} trace is not bitwise deterministic"
        )
