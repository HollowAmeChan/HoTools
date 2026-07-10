"""Structured tolerant comparison for semantic runner traces."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class TraceComparison:
    passed: bool
    differences: tuple[str, ...]
    max_abs_error: float


def _compare(
    left: Any,
    right: Any,
    path: str,
    differences: list[str],
    errors: list[float],
    abs_tol: float,
    rel_tol: float,
) -> None:
    if path.endswith(".runner") or path.endswith(".stats.step_ms"):
        return
    if path.endswith(".raw_f32_hex"):
        return
    if isinstance(left, bool) or isinstance(right, bool):
        if left is not right:
            differences.append(f"{path}: {left!r} != {right!r}")
        return
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        a = float(left)
        b = float(right)
        if not math.isfinite(a) or not math.isfinite(b):
            differences.append(f"{path}: non-finite comparison {a!r}, {b!r}")
            return
        error = abs(a - b)
        errors.append(error)
        if error > abs_tol + rel_tol * max(abs(a), abs(b)):
            differences.append(f"{path}: {a!r} != {b!r} (abs={error:.9g})")
        return
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        left_keys = set(left)
        right_keys = set(right)
        if left_keys != right_keys:
            differences.append(
                f"{path}: keys {sorted(left_keys)!r} != {sorted(right_keys)!r}"
            )
            return
        for key in sorted(left_keys, key=str):
            _compare(
                left[key], right[key], f"{path}.{key}", differences, errors,
                abs_tol, rel_tol,
            )
        return
    if (
        isinstance(left, Sequence) and not isinstance(left, (str, bytes, bytearray))
        and isinstance(right, Sequence) and not isinstance(right, (str, bytes, bytearray))
    ):
        if len(left) != len(right):
            differences.append(f"{path}: length {len(left)} != {len(right)}")
            return
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            _compare(
                left_item, right_item, f"{path}[{index}]", differences, errors,
                abs_tol, rel_tol,
            )
        return
    if left != right:
        differences.append(f"{path}: {left!r} != {right!r}")


def compare_traces(
    left: Sequence[Mapping[str, Any]],
    right: Sequence[Mapping[str, Any]],
    *,
    abs_tol: float = 2.0e-5,
    rel_tol: float = 1.0e-6,
    max_differences: int = 50,
) -> TraceComparison:
    differences: list[str] = []
    errors: list[float] = []
    _compare(left, right, "trace", differences, errors, abs_tol, rel_tol)
    return TraceComparison(
        passed=not differences,
        differences=tuple(differences[:max_differences]),
        max_abs_error=max(errors, default=0.0),
    )
