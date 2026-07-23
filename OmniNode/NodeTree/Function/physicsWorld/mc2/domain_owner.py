"""统一 MC2 产品域的事务化 CPU owner。"""

from __future__ import annotations

from dataclasses import dataclass

from .cpu_backend import MC2_CPU_REFERENCE_CAPABILITIES
from .cpu_backend import MC2CPUBackendDomainV1
from .cpu_backend import MC2CPUKernelV1
from .cpu_backend import create_mc2_cpu_backend_domain
from .domain_capabilities import MC2BackendCapabilitiesV1
from .domain_collect import MC2DomainDraftV1
from .domain_compile import MC2DomainCompileCacheReportV1
from .domain_compile import MC2CompiledDomainV1
from .domain_compile import compare_mc2_domain_compile_cache
from .domain_compile import compile_mc2_domain_draft
from .setups.mesh_cloth.fragment_cache import MC2MeshFragmentCacheV1


@dataclass(frozen=True)
class MC2FusedCPUOwnerSyncReportV1:
    action: str
    owner_revision: int
    fragment_cache_revision: int
    fragment_cache_hits: int
    fragment_builds: int
    compile_cache: MC2DomainCompileCacheReportV1
    old_domain_cleanup_error: str | None = None

    def __post_init__(self) -> None:
        if self.action not in {"created", "reused", "parameters_updated", "replaced"}:
            raise ValueError("invalid fused CPU owner sync action")
        if self.owner_revision <= 0 or self.fragment_cache_revision <= 0:
            raise ValueError("fused CPU owner revisions must be positive")
        if self.fragment_cache_hits < 0 or self.fragment_builds < 0:
            raise ValueError("fragment cache counters cannot be negative")
        if not isinstance(self.compile_cache, MC2DomainCompileCacheReportV1):
            raise TypeError("compile_cache must be MC2DomainCompileCacheReportV1")

    @property
    def native_domain_reused(self) -> bool:
        return self.action in {"reused", "parameters_updated"}

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_fused_cpu_owner_sync_report_v1",
            "action": self.action,
            "owner_revision": self.owner_revision,
            "fragment_cache_revision": self.fragment_cache_revision,
            "fragment_cache_hits": self.fragment_cache_hits,
            "fragment_builds": self.fragment_builds,
            "native_domain_reused": self.native_domain_reused,
            "old_domain_cleanup_error": self.old_domain_cleanup_error,
            "compile_cache": self.compile_cache.debug_dict(),
        }


class MC2FusedCPUOwnerV1:
    """Owns exactly one live native domain and its committed host products."""

    def __init__(
        self,
        kernel: MC2CPUKernelV1,
        *,
        capabilities: MC2BackendCapabilitiesV1 = MC2_CPU_REFERENCE_CAPABILITIES,
        fragment_cache=None,
    ) -> None:
        if not isinstance(capabilities, MC2BackendCapabilitiesV1):
            raise TypeError("capabilities must be MC2BackendCapabilitiesV1")
        if fragment_cache is None:
            fragment_cache = MC2MeshFragmentCacheV1()
        if any(
            not callable(getattr(fragment_cache, name, None))
            for name in ("inspect", "clear")
        ):
            raise TypeError("fragment_cache must implement inspect/clear")
        self._kernel = kernel
        self._capabilities = capabilities
        self._fragment_cache = fragment_cache
        self._domain: MC2CPUBackendDomainV1 | None = None
        self._compiled: MC2CompiledDomainV1 | None = None
        self._draft: MC2DomainDraftV1 | None = None
        self._revision = 0
        self._last_report: MC2FusedCPUOwnerSyncReportV1 | None = None
        self._cleanup_errors: list[str] = []

    @property
    def domain(self) -> MC2CPUBackendDomainV1 | None:
        return self._domain

    @property
    def compiled(self) -> MC2CompiledDomainV1 | None:
        return self._compiled

    @property
    def draft(self) -> MC2DomainDraftV1 | None:
        return self._draft

    @property
    def fragment_cache(self):
        return self._fragment_cache

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def last_report(self) -> MC2FusedCPUOwnerSyncReportV1 | None:
        return self._last_report

    def sync(
        self,
        draft: MC2DomainDraftV1,
        snapshots,
        *,
        world_gravity_direction=(0.0, -1.0, 0.0),
        world_gravity_directions=None,
    ) -> MC2FusedCPUOwnerSyncReportV1:
        if not isinstance(draft, MC2DomainDraftV1):
            raise TypeError("draft must be MC2DomainDraftV1")
        if draft.setup_type != "mesh_cloth":
            raise ValueError("snapshot cache sync 只接受 mesh_cloth draft")
        snapshots = tuple(snapshots)
        snapshot_ids = tuple(
            str(getattr(snapshot, "partition_id", "")) for snapshot in snapshots
        )
        if snapshot_ids != draft.partition_ids:
            raise ValueError(
                "Mesh fused owner snapshot order does not match resolved partition ids"
            )

        batch = self._fragment_cache.stage(
            snapshots,
            world_gravity_direction=world_gravity_direction,
            world_gravity_directions=world_gravity_directions,
        )
        current = compile_mc2_domain_draft(draft, batch.fragments)
        return self._sync_compiled(
            draft,
            current,
            commit_static=lambda: self._fragment_cache.commit(batch),
            fragment_cache_revision=self._fragment_cache.revision + 1,
            fragment_cache_hits=batch.hit_count,
            fragment_builds=batch.build_count,
        )

    def sync_fragments(
        self,
        draft: MC2DomainDraftV1,
        fragments,
        *,
        fragment_cache_revision: int = 1,
        fragment_cache_hits: int = 0,
        fragment_builds: int = 0,
        commit_static=None,
    ) -> MC2FusedCPUOwnerSyncReportV1:
        """提交任意 setup 的宿主 fragments，复用同一 native domain owner。"""

        if not isinstance(draft, MC2DomainDraftV1):
            raise TypeError("draft must be MC2DomainDraftV1")
        fragments = tuple(fragments)
        fragment_ids = tuple(
            str(getattr(fragment, "partition_id", "")) for fragment in fragments
        )
        if fragment_ids != draft.partition_ids:
            raise ValueError("fused owner fragment order does not match draft partitions")
        current = compile_mc2_domain_draft(draft, fragments)
        if commit_static is None:
            commit_static = lambda: None
        if not callable(commit_static):
            raise TypeError("commit_static must be callable")
        return self._sync_compiled(
            draft,
            current,
            commit_static=commit_static,
            fragment_cache_revision=int(fragment_cache_revision),
            fragment_cache_hits=int(fragment_cache_hits),
            fragment_builds=int(fragment_builds),
        )

    def _sync_compiled(
        self,
        draft: MC2DomainDraftV1,
        current: MC2CompiledDomainV1,
        *,
        commit_static,
        fragment_cache_revision: int,
        fragment_cache_hits: int,
        fragment_builds: int,
    ) -> MC2FusedCPUOwnerSyncReportV1:
        cache_report = compare_mc2_domain_compile_cache(self._compiled, current)
        if self._domain is not None and cache_report.exact_cache_hit:
            commit_static()
            self._compiled = current
            self._draft = draft
            self._revision += 1
            report = self._make_report_values(
                "reused",
                cache_report,
                fragment_cache_revision=fragment_cache_revision,
                fragment_cache_hits=fragment_cache_hits,
                fragment_builds=fragment_builds,
            )
            self._last_report = report
            return report

        if (
            self._domain is not None
            and cache_report.program_cache_hit
            and cache_report.parameter_layout_cache_hit
            and not cache_report.parameter_value_cache_hit
        ):
            self._domain.update_parameters(current, commit_host=commit_static)
            self._compiled = current
            self._draft = draft
            self._revision += 1
            report = self._make_report_values(
                "parameters_updated",
                cache_report,
                fragment_cache_revision=fragment_cache_revision,
                fragment_cache_hits=fragment_cache_hits,
                fragment_builds=fragment_builds,
            )
            self._last_report = report
            return report

        staged_domain = create_mc2_cpu_backend_domain(
            current,
            self._kernel,
            capabilities=self._capabilities,
        )
        try:
            commit_static()
        except Exception:
            try:
                staged_domain.dispose()
            except Exception:
                pass
            raise

        old_domain = self._domain
        action = "created" if old_domain is None else "replaced"
        self._domain = staged_domain
        self._compiled = current
        self._draft = draft
        self._revision += 1
        cleanup_error = None
        if old_domain is not None:
            try:
                old_domain.dispose()
            except Exception as exc:
                cleanup_error = f"{type(exc).__name__}: {exc}"
                self._cleanup_errors.append(cleanup_error)
        report = self._make_report_values(
            action,
            cache_report,
            fragment_cache_revision=fragment_cache_revision,
            fragment_cache_hits=fragment_cache_hits,
            fragment_builds=fragment_builds,
            cleanup_error=cleanup_error,
        )
        self._last_report = report
        return report

    def update_frame(self, frame_packet) -> None:
        """Publish one validated whole-domain frame to the live native owner."""

        self._require_domain().update_frame(frame_packet)

    def step(self, settings) -> None:
        """Run the fixed E4 compiled pass order on the live native owner."""

        self._require_domain().step_compiled_domain_pipeline_full(settings)

    def apply_zero_substep_frame(self, anchor_component_local_positions) -> None:
        """Apply Center/Teleport state for a frame with no physics substep."""

        self._require_domain().step_center_frame_shift(
            anchor_component_local_positions
        )

    def prepare_step_basic_pose(self) -> dict:
        """Build the partition-aware StepBasic pose through the live owner."""

        return self._require_domain().prepare_step_basic_pose()

    def read_output(self):
        """Read one logical-order domain result from the live native owner."""

        return self._require_domain().read_output()

    def read_debug_state(self):
        """Read explicit native dynamics through the product-owned domain."""

        return self._require_domain().read_debug_state()

    def begin_constraint_debug(self, mask: int) -> None:
        self._require_domain().begin_constraint_debug(int(mask))

    def end_constraint_debug(self) -> None:
        self._require_domain().end_constraint_debug()

    def read_constraint_debug_state(self):
        return self._require_domain().read_constraint_debug_state()

    def clear_constraint_debug(self) -> None:
        self._require_domain().clear_constraint_debug()

    def read_center_debug_state(self):
        """Read explicit partitioned Center/Teleport observations."""

        return self._require_domain().read_center_debug_state()

    def inspect(self) -> dict:
        return {
            "schema": "mc2_fused_cpu_owner_v1",
            "revision": self._revision,
            "live": self._domain is not None,
            "partition_ids": (
                list(self._compiled.program.partition_ids)
                if self._compiled is not None
                else []
            ),
            "domain": self._domain.inspect() if self._domain is not None else None,
            "fragment_cache": self._fragment_cache.inspect(),
            "cleanup_errors": list(self._cleanup_errors),
            "last_sync": (
                self._last_report.debug_dict()
                if self._last_report is not None
                else None
            ),
        }

    def dispose(self) -> None:
        domain = self._domain
        self._domain = None
        self._compiled = None
        self._draft = None
        self._last_report = None
        self._fragment_cache.clear()
        if domain is not None:
            domain.dispose()

    def _make_report_values(
        self,
        action,
        cache_report,
        *,
        fragment_cache_revision,
        fragment_cache_hits,
        fragment_builds,
        cleanup_error=None,
    ) -> MC2FusedCPUOwnerSyncReportV1:
        return MC2FusedCPUOwnerSyncReportV1(
            action=action,
            owner_revision=self._revision,
            fragment_cache_revision=fragment_cache_revision,
            fragment_cache_hits=fragment_cache_hits,
            fragment_builds=fragment_builds,
            compile_cache=cache_report,
            old_domain_cleanup_error=cleanup_error,
        )

    def _require_domain(self) -> MC2CPUBackendDomainV1:
        if self._domain is None:
            raise RuntimeError("MC2 fused CPU owner has no live domain")
        return self._domain


# E5-B 迁移包装；E7-S 删除 Mesh 专名。
MC2MeshFusedCPUOwnerV1 = MC2FusedCPUOwnerV1


__all__ = [
    "MC2FusedCPUOwnerV1",
    "MC2FusedCPUOwnerSyncReportV1",
    "MC2MeshFusedCPUOwnerV1",
]
