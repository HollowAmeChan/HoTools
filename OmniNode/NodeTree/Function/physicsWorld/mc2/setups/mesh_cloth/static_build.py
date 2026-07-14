"""MeshCloth static data assembly for the MC2 slot.

This is still pre-solver work: it builds the source-aligned final proxy,
baseline, Distance, and TriangleBending static contracts for later native ABI
and debug work. It does not allocate backend resources or publish results.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from ...bending_static import MC2BendingStaticSpec
from ...bending_static import build_mc2_bending_static
from ...center_state import MC2CenterStaticSpec
from ...center_state import build_mc2_center_static
from ...distance_static import MC2DistanceStaticSpec
from ...distance_static import build_mc2_distance_static
from ...mesh_baseline import MC2MeshBaselineBuildResult
from ...mesh_baseline import build_mc2_mesh_baseline
from ...names import MC2_SETUP_MESH_CLOTH
from ...specs import MC2TaskSpec
from ...topology import MC2TopologySpec
from .final_proxy import MC2MeshFinalProxyBuildResult
from .final_proxy import _mesh_triangles, _mesh_uvs, _vertex_group_weights
from .final_proxy import build_blender_mesh_final_proxy


@dataclass(frozen=True)
class MC2MeshClothStaticBuildResult:
    mesh_topology_signature: str
    finalizer: MC2MeshFinalProxyBuildResult
    baseline: MC2MeshBaselineBuildResult
    distance: MC2DistanceStaticSpec
    bending: MC2BendingStaticSpec | None
    center: MC2CenterStaticSpec

    @property
    def final_proxy(self):
        return self.baseline.final_proxy

    def __post_init__(self) -> None:
        if not self.mesh_topology_signature:
            raise ValueError("mesh_topology_signature cannot be empty")
        if not isinstance(self.finalizer, MC2MeshFinalProxyBuildResult):
            raise TypeError("finalizer must be MC2MeshFinalProxyBuildResult")
        if not isinstance(self.baseline, MC2MeshBaselineBuildResult):
            raise TypeError("baseline must be MC2MeshBaselineBuildResult")
        if not isinstance(self.distance, MC2DistanceStaticSpec):
            raise TypeError("distance must be MC2DistanceStaticSpec")
        if self.bending is not None and not isinstance(
            self.bending,
            MC2BendingStaticSpec,
        ):
            raise TypeError("bending must be MC2BendingStaticSpec or None")
        if not isinstance(self.center, MC2CenterStaticSpec):
            raise TypeError("center must be MC2CenterStaticSpec")
        if self.finalizer.proxy.task_id != self.baseline.final_proxy.task_id:
            raise ValueError("finalizer and baseline task_id must match")
        if self.finalizer.proxy.vertex_identities != self.baseline.final_proxy.vertex_identities:
            raise ValueError("finalizer and baseline vertex identities must match")
        if self.distance.proxy_signature != self.baseline.final_proxy.proxy_signature:
            raise ValueError("distance and final proxy signatures must match")
        if self.distance.baseline_signature != self.baseline.baseline.baseline_signature:
            raise ValueError("distance and baseline signatures must match")
        if (
            self.bending is not None
            and self.bending.proxy_signature != self.baseline.final_proxy.proxy_signature
        ):
            raise ValueError("bending and final proxy signatures must match")
        if self.center.proxy_signature != self.baseline.final_proxy.proxy_signature:
            raise ValueError("center and final proxy signatures must match")

    def debug_dict(self, *, include_signatures: bool = True) -> dict:
        result = {
            "setup_type": MC2_SETUP_MESH_CLOTH,
            "mesh_topology_signature": self.mesh_topology_signature,
            "vertex_count": self.final_proxy.vertex_count,
            "edge_count": len(self.final_proxy.edges),
            "triangle_count": len(self.final_proxy.triangles),
            "baseline_count": len(self.baseline.baseline.baseline_ranges),
            "fixed_count": sum(
                1 for value in self.final_proxy.vertex_attributes if value & 0x01
            ),
            "distance_record_count": len(self.distance.distance_targets),
            "bending_record_count": (
                self.bending.record_count if self.bending is not None else 0
            ),
            "center_fixed_count": len(self.center.fixed_indices),
        }
        if include_signatures:
            result.update(
                {
                    "proxy_signature": self.final_proxy.proxy_signature,
                    "baseline_signature": self.baseline.baseline.baseline_signature,
                    "distance_signature": self.distance.distance_signature,
                    "bending_signature": (
                        self.bending.bending_signature
                        if self.bending is not None
                        else None
                    ),
                    "center_static_signature": self.center.center_static_signature,
                }
            )
        return result


def _matrix_world_columns(obj) -> tuple[tuple[float, float, float, float], ...]:
    matrix = getattr(obj, "matrix_world", None)
    if matrix is None:
        return (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    return tuple(
        tuple(float(matrix[row][column]) for row in range(4))
        for column in range(4)
    )


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


def mesh_cloth_static_input_signature(
    obj,
    *,
    topology_signature: str,
    world_gravity_direction=(0.0, -1.0, 0.0),
) -> str:
    obj = _resolve_mesh_object(obj)
    if obj is None:
        raise ValueError("MeshCloth static input signature requires one Mesh object")
    mesh = obj.data
    mesh.update()
    triangles = _mesh_triangles(mesh)
    edges = tuple(sorted(
        tuple(sorted(int(value) for value in edge.vertices))
        for edge in mesh.edges
    ))
    uvs = _mesh_uvs(mesh, triangles, uv_layer_name=None)
    pin_enabled, pin_vertex_group = _mesh_cloth_pin_settings(obj)
    vertex_count = len(mesh.vertices)
    if not pin_enabled:
        attributes = (0x02,) * vertex_count
    elif not pin_vertex_group:
        attributes = (0x01,) * vertex_count
    else:
        weights = _vertex_group_weights(obj, pin_vertex_group, vertex_count)
        attributes = tuple(0x01 if weight > 0.0 else 0x02 for weight in weights)
    payload = {
        "schema_version": 3,
        "topology_signature": str(topology_signature or ""),
        "mesh_edges": edges,
        "mesh_triangles": triangles,
        "pin_enabled": pin_enabled,
        "pin_vertex_group": pin_vertex_group,
        "vertex_attributes": attributes,
        "uvs": uvs,
        "world_gravity_direction": tuple(float(value) for value in world_gravity_direction),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def mesh_cloth_static_input_signature_for_task(
    task: MC2TaskSpec,
    topology: MC2TopologySpec,
) -> str | None:
    if not isinstance(task, MC2TaskSpec):
        raise TypeError("task must be MC2TaskSpec")
    if not isinstance(topology, MC2TopologySpec):
        raise TypeError("topology must be MC2TopologySpec")
    if task.setup_type != MC2_SETUP_MESH_CLOTH:
        return None
    resolved = tuple(_resolve_mesh_object(source) for source in task.sources)
    mesh_sources = tuple(source for source in resolved if source is not None)
    if len(task.sources) != 1 or len(mesh_sources) != 1:
        raise ValueError("MeshCloth static input expects exactly one proxy mesh source")
    return mesh_cloth_static_input_signature(
        mesh_sources[0],
        topology_signature=topology.topology_signature,
        world_gravity_direction=task.profile.gravity_direction,
    )


def build_mc2_mesh_cloth_static(
    obj,
    *,
    task_id: str,
    topology_signature: str | None = None,
    world_gravity_direction=(0.0, -1.0, 0.0),
) -> MC2MeshClothStaticBuildResult:
    from .base_pose import mesh_topology_signature

    actual_mesh_topology_signature = mesh_topology_signature(obj)
    expected_mesh_topology_signature = str(topology_signature or "")
    if (
        expected_mesh_topology_signature
        and expected_mesh_topology_signature != actual_mesh_topology_signature
    ):
        raise ValueError("MeshCloth static build topology token changed before build")
    pin_enabled, pin_vertex_group = _mesh_cloth_pin_settings(obj)
    finalizer = build_blender_mesh_final_proxy(
        obj,
        task_id=task_id,
        pin_enabled=pin_enabled,
        pin_vertex_group=pin_vertex_group,
        expected_mesh_topology_signature=actual_mesh_topology_signature,
    )
    baseline = build_mc2_mesh_baseline(finalizer.proxy)
    distance = build_mc2_distance_static(
        baseline.final_proxy,
        baseline.baseline,
        vertex_to_vertex_ranges=finalizer.vertex_to_vertex_ranges,
        vertex_to_vertex_data=finalizer.vertex_to_vertex_data,
    )
    bending = build_mc2_bending_static(
        baseline.final_proxy,
        initial_local_to_world_columns=_matrix_world_columns(obj),
    )
    center = build_mc2_center_static(
        baseline.final_proxy,
        vertex_bind_pose_rotations=finalizer.vertex_bind_pose_rotations,
        world_gravity_direction=world_gravity_direction,
    )
    return MC2MeshClothStaticBuildResult(
        mesh_topology_signature=actual_mesh_topology_signature,
        finalizer=finalizer,
        baseline=baseline,
        distance=distance,
        bending=bending,
        center=center,
    )


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
        world_gravity_direction=task.profile.gravity_direction,
    )


__all__ = [
    "MC2MeshClothStaticBuildResult",
    "build_mc2_mesh_cloth_static",
    "build_mc2_mesh_cloth_static_for_task",
    "mesh_cloth_static_input_signature",
    "mesh_cloth_static_input_signature_for_task",
]
