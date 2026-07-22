"""MeshCloth static data assembly for the MC2 slot.

This is still pre-solver work: it builds the source-aligned final proxy,
baseline, Distance, and TriangleBending static contracts for later native ABI
and debug work. It does not allocate backend resources or publish results.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...bending_static import MC2BendingStaticMetadata
from ...bending_static import MC2BendingStaticSpec
from ...bending_static import build_mc2_bending_static
from ...center_state import MC2CenterStaticMetadata
from ...center_state import MC2CenterStaticSpec
from ...center_state import build_mc2_center_static
from ...distance_static import MC2DistanceStaticMetadata
from ...distance_static import MC2DistanceStaticSpec
from ...distance_static import build_mc2_distance_static
from ...mesh_baseline import MC2MeshBaselineBuildResult
from ...mesh_baseline import build_mc2_mesh_baseline
from ...names import MC2_SETUP_MESH_CLOTH
from ...self_collision_static import MC2SelfCollisionStaticMetadata
from ...self_collision_static import MC2SelfCollisionStaticSpec
from ...self_collision_static import build_mc2_self_collision_static
from ...topology import MC2TopologySpec
from .final_proxy import MC2MeshFinalProxyBuildResult
from .final_proxy import build_blender_mesh_final_proxy


@dataclass(frozen=True)
class MC2MeshClothStaticBuildResult:
    mesh_topology_signature: str
    finalizer: MC2MeshFinalProxyBuildResult
    baseline: MC2MeshBaselineBuildResult
    distance: MC2DistanceStaticSpec | MC2DistanceStaticMetadata
    bending: MC2BendingStaticSpec | MC2BendingStaticMetadata | None
    center: MC2CenterStaticSpec | MC2CenterStaticMetadata
    self_collision: MC2SelfCollisionStaticSpec | MC2SelfCollisionStaticMetadata
    radius_multipliers: tuple[float, ...]

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
        if not isinstance(
            self.distance,
            (MC2DistanceStaticSpec, MC2DistanceStaticMetadata),
        ):
            raise TypeError("distance must be an MC2 Distance static result")
        if self.bending is not None and not isinstance(
            self.bending,
            (MC2BendingStaticSpec, MC2BendingStaticMetadata),
        ):
            raise TypeError("bending must be an MC2 Bending static result or None")
        if not isinstance(self.center, (MC2CenterStaticSpec, MC2CenterStaticMetadata)):
            raise TypeError("center must be an MC2 Center static result")
        if not isinstance(
            self.self_collision,
            (MC2SelfCollisionStaticSpec, MC2SelfCollisionStaticMetadata),
        ):
            raise TypeError("self_collision must be an MC2 self-collision static result")
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
        if self.self_collision.proxy_signature != self.baseline.final_proxy.proxy_signature:
            raise ValueError("self collision and final proxy signatures must match")
        if len(self.radius_multipliers) != self.final_proxy.vertex_count:
            raise ValueError("radius_multipliers must contain one value per vertex")
        if any(not 0.0 <= value <= 1.0 for value in self.radius_multipliers):
            raise ValueError("radius_multipliers must be in 0..1")

    def debug_dict(self, *, include_signatures: bool = True) -> dict:
        result = {
            "setup_type": MC2_SETUP_MESH_CLOTH,
            "mesh_topology_signature": self.mesh_topology_signature,
            "vertex_count": self.final_proxy.vertex_count,
            "edge_count": len(self.final_proxy.edges),
            "triangle_count": len(self.final_proxy.triangles),
            "baseline_count": (
                self.baseline.baseline.baseline_count
                if hasattr(self.baseline.baseline, "baseline_count")
                else len(self.baseline.baseline.baseline_ranges)
            ),
            "fixed_count": sum(
                1 for value in self.final_proxy.vertex_attributes if value & 0x01
            ),
            "distance_record_count": self.distance.record_count,
            "bending_record_count": (
                self.bending.record_count if self.bending is not None else 0
            ),
            "center_fixed_count": self.center.fixed_count,
            "self_collision_primitive_count": self.self_collision.primitive_count,
            "weighted_radius_vertex_count": sum(
                1 for value in self.radius_multipliers if value > 0.0
            ),
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
                    "self_collision_static_signature": self.self_collision.static_signature,
                }
            )
        return result

    def with_center(self, center: MC2CenterStaticMetadata):
        if not isinstance(center, MC2CenterStaticMetadata):
            raise TypeError("center must be MC2CenterStaticMetadata")
        return MC2MeshClothStaticBuildResult(
            mesh_topology_signature=self.mesh_topology_signature,
            finalizer=self.finalizer,
            baseline=self.baseline,
            distance=self.distance,
            bending=self.bending,
            center=center,
            self_collision=self.self_collision,
            radius_multipliers=self.radius_multipliers,
        )


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


def _mesh_radius_multipliers(obj, raw_snapshot=None) -> tuple[float, ...]:
    if raw_snapshot is not None:
        values = raw_snapshot.radius_multipliers
    else:
        properties = getattr(obj, "hotools_mesh_collision", None)
        group_name = str(getattr(properties, "radius_vertex_group", "") or "")
        if not group_name:
            return (1.0,) * len(obj.data.vertices)
        group = obj.vertex_groups.get(group_name)
        if group is None:
            raise ValueError(f"MC2 radius vertex group does not exist: {group_name!r}")
        values = [0.0] * len(obj.data.vertices)
        for vertex in obj.data.vertices:
            for assignment in vertex.groups:
                if int(assignment.group) == int(group.index):
                    values[vertex.index] = max(
                        0.0, min(1.0, float(assignment.weight))
                    )
                    break
    return tuple(float(value) for value in values)


def build_mc2_mesh_cloth_static(
    obj,
    *,
    task_id: str,
    topology_signature: str | None = None,
    world_gravity_direction=(0.0, -1.0, 0.0),
    native_context=None,
    raw_snapshot=None,
) -> MC2MeshClothStaticBuildResult:
    expected_mesh_topology_signature = str(topology_signature or "")
    pin_enabled, pin_vertex_group = _mesh_cloth_pin_settings(obj)
    radius_multipliers = _mesh_radius_multipliers(obj, raw_snapshot)
    finalizer = build_blender_mesh_final_proxy(
        obj,
        task_id=task_id,
        pin_enabled=pin_enabled,
        pin_vertex_group=pin_vertex_group,
        expected_mesh_topology_signature=expected_mesh_topology_signature,
        native_context=native_context,
        raw_snapshot=raw_snapshot,
    )
    actual_mesh_topology_signature = finalizer.mesh_topology_signature
    if not actual_mesh_topology_signature:
        raise RuntimeError("Mesh final proxy did not return a topology identity token")
    baseline = build_mc2_mesh_baseline(
        finalizer.proxy,
        native_context=native_context,
    )
    if native_context is not None:
        native_context.update_proxy_finalizer_derived(
            proxy=baseline.final_proxy,
            finalizer=finalizer.finalizer,
            radius_multipliers=radius_multipliers,
        )
        baseline_data = baseline.baseline
        native_context.update_baseline_derived(
            baseline_data,
            finalize_attributes=False,
        )
    distance = build_mc2_distance_static(
        baseline.final_proxy,
        baseline.baseline,
        vertex_to_vertex_ranges=finalizer.vertex_to_vertex_ranges,
        vertex_to_vertex_data=finalizer.vertex_to_vertex_data,
        native_context=native_context,
    )
    bending = build_mc2_bending_static(
        baseline.final_proxy,
        initial_local_to_world_columns=_matrix_world_columns(obj),
        native_context=native_context,
    )
    center = build_mc2_center_static(
        baseline.final_proxy,
        vertex_bind_pose_rotations=finalizer.vertex_bind_pose_rotations,
        world_gravity_direction=world_gravity_direction,
        native_context=native_context,
    )
    self_collision = build_mc2_self_collision_static(
        baseline.final_proxy,
        baseline.baseline.depths,
        native_context=native_context,
    )
    stored_baseline = baseline.compact_native_baseline()
    stored_finalizer = finalizer.compact_native_finalizer(
        proxy_metadata=stored_baseline.final_proxy,
    )
    result = MC2MeshClothStaticBuildResult(
        mesh_topology_signature=actual_mesh_topology_signature,
        finalizer=stored_finalizer,
        baseline=stored_baseline,
        distance=distance,
        bending=bending,
        center=center,
        self_collision=self_collision,
        radius_multipliers=radius_multipliers,
    )
    if native_context is not None:
        native_context.initialize_mesh_static_from_builders(result)
    return result


def build_mc2_mesh_cloth_static_for_task(
    task,
    topology: MC2TopologySpec,
    *,
    native_context=None,
    raw_snapshot=None,
) -> MC2MeshClothStaticBuildResult | None:
    from ...specs import MC2TaskSpec

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
        native_context=native_context,
        raw_snapshot=raw_snapshot,
    )


__all__ = [
    "MC2MeshClothStaticBuildResult",
    "build_mc2_mesh_cloth_static",
    "build_mc2_mesh_cloth_static_for_task",
]
