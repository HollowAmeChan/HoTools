"""MeshCloth static data assembly for the MC2 slot.

This is still pre-solver work: it builds the source-aligned final proxy and
baseline static contracts, then keeps them available for later native ABI and
debug work. It does not allocate backend resources or publish simulation
results.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...mesh_baseline import MC2MeshBaselineBuildResult
from ...mesh_baseline import build_mc2_mesh_baseline
from ...names import MC2_SETUP_MESH_CLOTH
from ...specs import MC2TaskSpec
from ...topology import MC2TopologySpec
from .final_proxy import MC2MeshFinalProxyBuildResult
from .final_proxy import build_blender_mesh_final_proxy


@dataclass(frozen=True)
class MC2MeshClothStaticBuildResult:
    finalizer: MC2MeshFinalProxyBuildResult
    baseline: MC2MeshBaselineBuildResult

    @property
    def final_proxy(self):
        return self.baseline.final_proxy

    def __post_init__(self) -> None:
        if not isinstance(self.finalizer, MC2MeshFinalProxyBuildResult):
            raise TypeError("finalizer must be MC2MeshFinalProxyBuildResult")
        if not isinstance(self.baseline, MC2MeshBaselineBuildResult):
            raise TypeError("baseline must be MC2MeshBaselineBuildResult")
        if self.finalizer.proxy.task_id != self.baseline.final_proxy.task_id:
            raise ValueError("finalizer and baseline task_id must match")
        if self.finalizer.proxy.vertex_identities != self.baseline.final_proxy.vertex_identities:
            raise ValueError("finalizer and baseline vertex identities must match")

    def debug_dict(self, *, include_signatures: bool = True) -> dict:
        result = {
            "setup_type": MC2_SETUP_MESH_CLOTH,
            "vertex_count": self.final_proxy.vertex_count,
            "edge_count": len(self.final_proxy.edges),
            "triangle_count": len(self.final_proxy.triangles),
            "baseline_count": len(self.baseline.baseline.baseline_ranges),
            "fixed_count": sum(
                1 for value in self.final_proxy.vertex_attributes if value & 0x01
            ),
        }
        if include_signatures:
            result.update(
                {
                    "proxy_signature": self.final_proxy.proxy_signature,
                    "baseline_signature": self.baseline.baseline.baseline_signature,
                }
            )
        return result


def _resolve_mesh_object(source):
    if isinstance(source, dict):
        source = source.get("proxy_obj") or source.get("object")
    if getattr(source, "type", None) != "MESH":
        return None
    mesh = getattr(source, "data", None)
    if mesh is None or not hasattr(mesh, "vertices"):
        return None
    return source


def _mesh_cloth_pin_settings(obj) -> tuple[bool, str]:
    properties = getattr(obj, "hotools_mesh_collision", None)
    if properties is None:
        return False, ""
    return (
        bool(getattr(properties, "pin_enabled", False)),
        str(getattr(properties, "pin_vertex_group", "") or ""),
    )


def build_mc2_mesh_cloth_static(
    obj,
    *,
    task_id: str,
    topology_signature: str | None = None,
) -> MC2MeshClothStaticBuildResult:
    pin_enabled, pin_vertex_group = _mesh_cloth_pin_settings(obj)
    finalizer = build_blender_mesh_final_proxy(
        obj,
        task_id=task_id,
        pin_enabled=pin_enabled,
        pin_vertex_group=pin_vertex_group,
        expected_mesh_topology_signature=topology_signature,
    )
    baseline = build_mc2_mesh_baseline(finalizer.proxy)
    return MC2MeshClothStaticBuildResult(finalizer=finalizer, baseline=baseline)


def build_mc2_mesh_cloth_static_for_task(
    task: MC2TaskSpec,
    topology: MC2TopologySpec,
) -> MC2MeshClothStaticBuildResult | None:
    if not isinstance(task, MC2TaskSpec):
        raise TypeError("task must be MC2TaskSpec")
    if not isinstance(topology, MC2TopologySpec):
        raise TypeError("topology must be MC2TopologySpec")
    if task.setup_type != MC2_SETUP_MESH_CLOTH:
        return None
    resolved = tuple(_resolve_mesh_object(source) for source in task.sources)
    mesh_sources = tuple(source for source in resolved if source is not None)
    if not mesh_sources:
        return None
    if len(task.sources) != 1 or len(mesh_sources) != 1:
        raise ValueError("MeshCloth MC2 static build expects exactly one proxy mesh source")
    obj = mesh_sources[0]
    return build_mc2_mesh_cloth_static(
        obj,
        task_id=task.task_id,
        topology_signature=None,
    )


__all__ = [
    "MC2MeshClothStaticBuildResult",
    "build_mc2_mesh_cloth_static",
    "build_mc2_mesh_cloth_static_for_task",
]
