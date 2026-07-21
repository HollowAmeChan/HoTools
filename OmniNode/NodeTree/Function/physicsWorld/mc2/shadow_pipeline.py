"""Opt-in E1 shadow compile and old/new static comparison."""

from __future__ import annotations

from dataclasses import dataclass
import time

import numpy as np

from .domain_compile import MC2MeshCompiledDomainV1
from .domain_compile import compile_mc2_mesh_static_fragment
from .runtime_parameters import make_mc2_runtime_parameters
from .setups.mesh_cloth.source_capture import capture_mc2_mesh_partition_static_snapshot
from .setups.mesh_cloth.static_build import build_mc2_mesh_cloth_static
from .setups.mesh_cloth.static_fragment import build_mc2_mesh_static_fragment
from .specs import MC2TaskSpec
from .topology import MC2MeshRawSnapshot, MC2TopologySpec


@dataclass(frozen=True)
class MC2ShadowComparisonItemV1:
    name: str
    matched: bool
    expected: object
    actual: object

    def __post_init__(self) -> None:
        if not str(self.name or ""):
            raise ValueError("shadow comparison item name cannot be empty")
        if type(self.matched) is not bool:
            raise TypeError("shadow comparison item matched must be bool")

    def debug_dict(self) -> dict:
        return {
            "name": self.name,
            "matched": self.matched,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass(frozen=True)
class MC2MeshShadowComparisonReportV1:
    task_id: str
    compiled_domain_signature: str
    checks: tuple[MC2ShadowComparisonItemV1, ...]
    timing_seconds: dict[str, float]

    def __post_init__(self) -> None:
        if not str(self.task_id or "") or not str(self.compiled_domain_signature or ""):
            raise ValueError("shadow report identity cannot be empty")
        if not isinstance(self.checks, tuple) or not self.checks:
            raise ValueError("shadow report requires comparison checks")
        if any(not isinstance(item, MC2ShadowComparisonItemV1) for item in self.checks):
            raise TypeError("shadow report checks must be MC2ShadowComparisonItemV1")
        names = tuple(item.name for item in self.checks)
        if len(set(names)) != len(names):
            raise ValueError("shadow report check names must be unique")
        if not isinstance(self.timing_seconds, dict):
            raise TypeError("shadow report timing_seconds must be a dict")
        if any(float(value) < 0.0 for value in self.timing_seconds.values()):
            raise ValueError("shadow report timing cannot be negative")

    @property
    def compatible(self) -> bool:
        return all(item.matched for item in self.checks)

    def debug_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "compiled_domain_signature": self.compiled_domain_signature,
            "compatible": self.compatible,
            "checks": [item.debug_dict() for item in self.checks],
            "timing_seconds": dict(self.timing_seconds),
        }


def _array_equal(left, right) -> bool:
    return np.array_equal(np.asarray(left), np.asarray(right))


def compare_mc2_mesh_static_to_compiled(
    legacy_static,
    compiled: MC2MeshCompiledDomainV1,
    *,
    effective_parameter_signature: str | None = None,
) -> MC2MeshShadowComparisonReportV1:
    if not isinstance(compiled, MC2MeshCompiledDomainV1):
        raise TypeError("compiled must be MC2MeshCompiledDomainV1")
    legacy_proxy = legacy_static.final_proxy
    fragment = compiled.single_fragment
    compiled_proxy = fragment.final_proxy
    legacy_baseline = legacy_static.baseline.baseline
    compiled_baseline = fragment.baseline.baseline
    legacy_distance = legacy_static.distance
    compiled_distance = fragment.distance
    checks = [
        MC2ShadowComparisonItemV1(
            "particle_count",
            legacy_proxy.vertex_count == compiled.program.particle_count,
            legacy_proxy.vertex_count,
            compiled.program.particle_count,
        ),
        MC2ShadowComparisonItemV1(
            "proxy_signature",
            legacy_proxy.proxy_signature == compiled_proxy.proxy_signature,
            legacy_proxy.proxy_signature,
            compiled_proxy.proxy_signature,
        ),
        MC2ShadowComparisonItemV1(
            "proxy_edges",
            _array_equal(legacy_proxy.edges, compiled_proxy.edges),
            len(legacy_proxy.edges),
            len(compiled_proxy.edges),
        ),
        MC2ShadowComparisonItemV1(
            "proxy_triangles",
            _array_equal(legacy_proxy.triangles, compiled_proxy.triangles),
            len(legacy_proxy.triangles),
            len(compiled_proxy.triangles),
        ),
        MC2ShadowComparisonItemV1(
            "particle_attributes",
            _array_equal(legacy_proxy.vertex_attributes, compiled_proxy.vertex_attributes),
            tuple(int(value) for value in legacy_proxy.vertex_attributes),
            tuple(int(value) for value in compiled_proxy.vertex_attributes),
        ),
        MC2ShadowComparisonItemV1(
            "baseline_signature",
            legacy_baseline.baseline_signature == compiled_baseline.baseline_signature,
            legacy_baseline.baseline_signature,
            compiled_baseline.baseline_signature,
        ),
        MC2ShadowComparisonItemV1(
            "baseline_depths",
            _array_equal(legacy_baseline.depths, compiled_baseline.depths),
            len(legacy_baseline.depths),
            len(compiled_baseline.depths),
        ),
        MC2ShadowComparisonItemV1(
            "distance_signature",
            legacy_distance.distance_signature == compiled_distance.distance_signature,
            legacy_distance.distance_signature,
            compiled_distance.distance_signature,
        ),
        MC2ShadowComparisonItemV1(
            "distance_records",
            legacy_distance.record_count == compiled_distance.record_count,
            legacy_distance.record_count,
            compiled_distance.record_count,
        ),
        MC2ShadowComparisonItemV1(
            "bending_signature",
            getattr(legacy_static.bending, "bending_signature", None)
            == getattr(fragment.bending, "bending_signature", None),
            getattr(legacy_static.bending, "record_count", 0),
            getattr(fragment.bending, "record_count", 0),
        ),
        MC2ShadowComparisonItemV1(
            "self_collision_signature",
            legacy_static.self_collision.static_signature
            == fragment.self_collision.static_signature,
            legacy_static.self_collision.primitive_count,
            fragment.self_collision.primitive_count,
        ),
        MC2ShadowComparisonItemV1(
            "radius_multipliers",
            _array_equal(legacy_static.radius_multipliers, fragment.radius_multipliers),
            len(legacy_static.radius_multipliers),
            len(fragment.radius_multipliers),
        ),
        MC2ShadowComparisonItemV1(
            "effective_parameter_signature",
            (
                compiled.single_effective_parameter_signature
                == (
                    effective_parameter_signature
                    or compiled.single_effective_parameter_signature
                )
            ),
            effective_parameter_signature or compiled.single_effective_parameter_signature,
            compiled.single_effective_parameter_signature,
        ),
    ]
    return MC2MeshShadowComparisonReportV1(
        task_id=fragment.partition_id,
        compiled_domain_signature=compiled.program.domain_signature,
        checks=tuple(checks),
        timing_seconds={},
    )


def run_mc2_mesh_shadow_compile(
    source,
    task: MC2TaskSpec,
    topology: MC2TopologySpec,
    raw_snapshot: MC2MeshRawSnapshot,
    *,
    shadow_enabled: bool = False,
    legacy_static=None,
    timing=None,
) -> MC2MeshShadowComparisonReportV1 | None:
    """Run E1 only when explicitly enabled; disabled path does no source work."""

    if type(shadow_enabled) is not bool:
        raise TypeError("shadow_enabled must be bool")
    if not shadow_enabled:
        return None
    if not isinstance(task, MC2TaskSpec) or not isinstance(topology, MC2TopologySpec):
        raise TypeError("shadow compile requires MC2TaskSpec and MC2TopologySpec")
    if task.setup_type != "mesh_cloth":
        raise ValueError("E1 shadow compile only supports MeshCloth")
    if not isinstance(raw_snapshot, MC2MeshRawSnapshot):
        raise TypeError("shadow compile requires MC2MeshRawSnapshot")
    started = time.perf_counter()
    if timing is not None:
        timing.detail_restart()
    snapshot = capture_mc2_mesh_partition_static_snapshot(
        source,
        raw_snapshot,
        partition_id=task.task_id,
        source_identity=task.source_signature,
        source_revision=topology.sources[0].identity_signature,
        output_target_id=f"{task.task_id}:output:0",
    )
    captured = time.perf_counter()
    if timing is not None:
        timing.detail_checkpoint("shadow capture")
    fragment = build_mc2_mesh_static_fragment(
        snapshot,
        world_gravity_direction=task.profile.gravity_direction,
    )
    fragmented = time.perf_counter()
    if timing is not None:
        timing.detail_checkpoint("shadow fragment")
    effective = make_mc2_runtime_parameters(
        task.profile,
        task.setup_options,
        task.task_parameters,
    )
    compiled = compile_mc2_mesh_static_fragment(fragment, effective)
    compiled_at = time.perf_counter()
    if timing is not None:
        timing.detail_checkpoint("shadow compile")
    if legacy_static is None:
        legacy_static = build_mc2_mesh_cloth_static(
            source,
            task_id=task.task_id,
            world_gravity_direction=task.profile.gravity_direction,
            raw_snapshot=raw_snapshot,
        )
    legacy_at = time.perf_counter()
    if timing is not None:
        timing.detail_checkpoint("shadow legacy static")
    report = compare_mc2_mesh_static_to_compiled(
        legacy_static,
        compiled,
        effective_parameter_signature=effective.parameter_signature,
    )
    if timing is not None:
        timing.detail_checkpoint("shadow compare")
    timing = {
        "capture": max(captured - started, 0.0),
        "fragment": max(fragmented - captured, 0.0),
        "compile": max(compiled_at - fragmented, 0.0),
        "legacy_static": max(legacy_at - compiled_at, 0.0),
        "total": max(legacy_at - started, 0.0),
    }
    return MC2MeshShadowComparisonReportV1(
        task_id=report.task_id,
        compiled_domain_signature=report.compiled_domain_signature,
        checks=report.checks,
        timing_seconds=timing,
    )


__all__ = [
    "MC2MeshShadowComparisonReportV1",
    "MC2ShadowComparisonItemV1",
    "compare_mc2_mesh_static_to_compiled",
    "run_mc2_mesh_shadow_compile",
]
