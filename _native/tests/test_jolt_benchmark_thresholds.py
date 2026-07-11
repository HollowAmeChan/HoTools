"""Rigid/Jolt Blender benchmark threshold gate unit tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_PATH = (
    ROOT
    / "OmniNode"
    / "NodeTree"
    / "Function"
    / "physicsWorld"
    / "rigid"
    / "test"
    / "benchmark_blender_rigid.py"
)


def _load_benchmark():
    spec = importlib.util.spec_from_file_location(
        "hotools_jolt_benchmark_threshold_test", BENCHMARK_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load benchmark module: {BENCHMARK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _thresholds():
    return {
        "schema": "hotools_jolt_blender_performance_thresholds_v1",
        "id": "unit-test",
        "requirements": {
            "blender_version": [4, 5],
            "min_warmup": 10,
            "min_samples": 60,
        },
        "cases": {
            "PERF-BODY-1": {
                "metrics_ms": {
                    "native_step_ms": {"p50": 1.0, "p95": 2.0},
                    "pipeline_without_writeback_ms": {"p50": 3.0, "p95": 4.0},
                    "writeback_ms": {"p50": 5.0, "p95": 6.0},
                },
                "working_set_high_water_max_bytes": 1024,
            }
        },
    }


def _case(*, native_p95=1.5, memory=512, case_id="PERF-BODY-1"):
    return {
        "id": case_id,
        "metrics_ms": {
            "native_step_ms": {"p50": 0.5, "p95": native_p95},
            "pipeline_without_writeback_ms": {"p50": 2.0, "p95": 3.0},
            "writeback_ms": {"p50": 4.0, "p95": 5.0},
        },
        "memory": {"working_set_high_water": memory},
    }


def test_jolt_benchmark_threshold_gate_passes():
    module = _load_benchmark()
    result = module._evaluate_thresholds(
        [_case()],
        _thresholds(),
        warmup=10,
        samples=60,
        blender_version=(4, 5, 0),
    )
    assert result["passed"]
    assert result["cases"][0]["passed"]


def test_jolt_benchmark_threshold_gate_rejects_regression():
    module = _load_benchmark()
    result = module._evaluate_thresholds(
        [_case(native_p95=2.1, memory=2048)],
        _thresholds(),
        warmup=10,
        samples=60,
        blender_version=(4, 5, 0),
    )
    assert not result["passed"]
    differences = result["cases"][0]["differences"]
    assert any("native_step_ms.p95" in item for item in differences)
    assert any("working_set_high_water" in item for item in differences)


def test_jolt_benchmark_threshold_gate_rejects_unknown_case_and_short_run():
    module = _load_benchmark()
    result = module._evaluate_thresholds(
        [_case(case_id="PERF-CUSTOM-2")],
        _thresholds(),
        warmup=5,
        samples=30,
        blender_version=(4, 5, 0),
    )
    assert not result["passed"]
    assert any("warmup" in item for item in result["errors"])
    assert any("samples" in item for item in result["errors"])
    assert any("没有冻结阈值" in item for item in result["cases"][0]["differences"])


def test_jolt_benchmark_threshold_gate_rejects_invalid_case_record():
    module = _load_benchmark()
    result = module._evaluate_thresholds(
        [None],
        _thresholds(),
        warmup=10,
        samples=60,
        blender_version=(4, 5, 0),
    )
    assert not result["passed"]
    assert any("benchmark case" in item for item in result["errors"])
