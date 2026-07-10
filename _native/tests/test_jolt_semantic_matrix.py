"""声明式 Rigid/Jolt 语义矩阵的 native 回归入口。"""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = (
    ROOT / "OmniNode" / "NodeTree" / "Function" / "physicsWorld" / "rigid" / "test"
)
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from canonical import traces_bitwise_equal  # noqa: E402
from fixture_runtime import NativeFixtureRuntime, load_native_module  # noqa: E402
from schema import BodySpec, FixtureError, discover_fixtures, load_fixture  # noqa: E402


def _native_dir() -> Path:
    py_lib = "py313" if sys.version_info >= (3, 13) else "py311"
    return Path(os.environ.get(
        "HOTOOLS_NATIVE_TEST_DIR",
        ROOT / "_Lib" / py_lib / "HotoolsPackage",
    ))


def _fixtures():
    fixtures = [
        load_fixture(path)
        for path in discover_fixtures(TEST_ROOT / "fixtures")
    ]
    return sorted(fixtures, key=lambda fixture: fixture.id)


def _body_fixtures():
    return [
        fixture for fixture in _fixtures()
        if not fixture.constraints and not ({"contact", "query"} & set(fixture.tags))
    ]


def _constraint_fixtures():
    return [fixture for fixture in _fixtures() if fixture.constraints]


def _contact_query_fixtures():
    return [fixture for fixture in _fixtures() if {"contact", "query"} & set(fixture.tags)]


def test_jolt_semantic_fixture_catalog():
    fixtures = _fixtures()
    ids = [fixture.id for fixture in fixtures]
    assert ids == sorted(ids), "semantic fixture discovery order must be stable"
    assert len(ids) == len(set(ids)), "semantic fixture ids must be unique"
    assert {
        "BODY-001", "FREE-001", "FREE-002", "FREE-003",
        "FIXED-001", "POINT-001", "DIST-001", "DIST-002", "HINGE-001",
        "HINGE-002", "SLIDER-001", "SLIDER-002", "CONE-001", "CONE-002",
        "DIST-003", "HINGE-003", "HINGE-004", "HINGE-005", "HINGE-006",
        "SLIDER-003", "SLIDER-004", "SLIDER-005", "SLIDER-006",
        "PAIR-001", "PAIR-002", "PAIR-003",
        "EVENT-001", "EVENT-002", "QUERY-001",
        "BODY-004", "BODY-005", "BODY-006", "COLL-001", "COLL-002",
        "FILTER-001",
        "FRAME-002", "SHAPE-004",
        "COLL-005",
        "FILTER-002",
        "FRAME-001",
        "BODY-003", "BODY-007",
        "SHAPE-001", "SHAPE-003",
        "COLL-003",
        "FILTER-003",
        "SWING_TWIST-001",
        "SIX_DOF-001", "SIX_DOF-002", "SIX_DOF-003", "SIX_DOF-004",
    }.issubset(ids)
    for fixture in fixtures:
        assert "p0" in fixture.tags
        assert fixture.assertions
        assert fixture.sample_frames[0] == 0


def test_jolt_fixture_rejects_degenerate_shapes():
    """退化形状必须在进入 native 前由 fixture 协议明确拒绝。"""
    invalid_shapes = [
        {"type": "SPHERE", "radius": 0.0},
        {"type": "BOX", "half_extents": [0.5, 0.0, 0.5]},
        {"type": "CAPSULE", "half_height": -1.0, "radius": 0.5},
        {"type": "BOX", "rotation_wxyz": [0.0, 0.0, 0.0, 0.0]},
    ]
    for index, shape in enumerate(invalid_shapes):
        try:
            BodySpec.from_data(
                {"id": f"invalid_{index}", "type": "DYNAMIC", "shape": shape},
                f"invalid_shapes[{index}]",
            )
        except FixtureError:
            continue
        raise AssertionError(f"degenerate shape {shape!r} was accepted")


def test_jolt_p0_semantic_matrix():
    native = load_native_module(_native_dir())
    for fixture in _body_fixtures():
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


def test_jolt_p0_constraint_semantic_matrix():
    native = load_native_module(_native_dir())
    if not hasattr(native.JoltWorld, "get_constraint_state"):
        raise RuntimeError("SKIP: 当前 Python ABI 的 hotools_jolt 缺少约束状态接口")
    for fixture in _constraint_fixtures():
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


def test_jolt_p0_contact_query_semantic_matrix():
    native = load_native_module(_native_dir())
    if not hasattr(native.JoltWorld, "get_contact_events") or not hasattr(
        native.JoltWorld, "cast_ray",
    ):
        raise RuntimeError("SKIP: 当前 Python ABI 的 hotools_jolt 缺少 contact/query 接口")
    for fixture in _contact_query_fixtures():
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


def test_jolt_constraint_draw_size_is_non_physical():
    """修改约束调试绘制尺寸不得改变任何物理 trace 字段。"""
    native = load_native_module(_native_dir())
    if not hasattr(native.JoltWorld, "get_constraint_state"):
        raise RuntimeError("SKIP: 当前 Python ABI 的 hotools_jolt 缺少约束状态接口")
    source = next(fixture for fixture in _fixtures() if fixture.id == "HINGE-001")
    constraint = source.constraints[0]
    small = replace(source, constraints=(replace(constraint, draw_size=0.0),))
    large = replace(source, constraints=(replace(constraint, draw_size=100.0),))
    small_result = NativeFixtureRuntime(native).run(small, 0)
    large_result = NativeFixtureRuntime(native).run(large, 0)
    assert small_result.physical_hash == large_result.physical_hash
    assert traces_bitwise_equal(small_result.trace, large_result.trace)


def test_jolt_cross_process_hash_stability():
    """同一 fixture 在十个全新进程中的 physical hash 必须一致。"""
    runner = TEST_ROOT / "run_native_semantics.py"
    hashes: list[str] = []
    with tempfile.TemporaryDirectory(prefix="hotools-jolt-det-") as artifact_root:
        for repeat_index in range(10):
            completed = subprocess.run(
                [
                    sys.executable,
                    str(runner),
                    "--id", "FREE-001",
                    "--repeat", "1",
                    "--artifact-dir", str(Path(artifact_root) / str(repeat_index)),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            assert completed.returncode == 0, completed.stdout + completed.stderr
            match = re.search(
                r"\[PASS\] FREE-001 repeats=1 hash=([0-9a-f]+)", completed.stdout,
            )
            assert match is not None, completed.stdout
            hashes.append(match.group(1))
    assert len(set(hashes)) == 1, f"cross-process hashes differ: {hashes}"
