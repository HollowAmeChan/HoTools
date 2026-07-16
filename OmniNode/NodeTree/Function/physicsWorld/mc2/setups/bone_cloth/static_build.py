"""BoneCloth/BoneSpring Line static assembly for staged MC2 registration."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

import numpy as np

from ...bone_static import MC2BoneNativeData, MC2BoneStaticSpec
from ...bone_static import build_mc2_bone_static
from ...center_state import MC2CenterStaticMetadata, MC2CenterStaticSpec
from ...center_state import build_mc2_center_static
from ...distance_static import MC2DistanceStaticMetadata, MC2DistanceStaticSpec
from ...distance_static import build_mc2_distance_static
from ...mesh_baseline import MC2MeshBaselineMetadata
from ...names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from ...self_collision_static import (
    MC2SelfCollisionStaticMetadata,
    MC2SelfCollisionStaticSpec,
)
from ...self_collision_static import build_mc2_self_collision_static
from ...specs import MC2TaskSpec
from ...topology import MC2BoneRawSnapshot, MC2TopologySpec
from ...topology import _thaw
from ..mesh_cloth.final_proxy import (
    MC2MeshFinalizerNativeData,
    MC2MeshFinalizerNativeMetadata,
    MC2MeshProxyNativeMetadata,
)


MC2_BONE_STATIC_SCHEMA_VERSION = 3
MC2_LINE_BONE_SETUP_TYPES = (MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING)


def mc2_bone_static_domain_error(
    setup_type: str,
    connection_mode: int,
    triangles,
    connection_model: str = "mc2_source",
) -> str:
    triangle_count = len(tuple(triangles or ()))
    if setup_type == MC2_SETUP_BONE_SPRING and int(connection_mode) != 0:
        return "BoneSpring requires Line connection mode"
    if triangle_count and connection_model != "hotools_product":
        return (
            "MC2 Bone mesh connection is unsupported: ImportBoneType produces zero UV, "
            f"so {triangle_count} triangle tangent/basis record(s) would degenerate; "
            "use Line or a connection result containing no triangles"
        )
    return ""


def _require_mc2_bone_static_domain(task: MC2TaskSpec, topology: MC2TopologySpec) -> None:
    triangles = topology.bone_connection.triangles if topology.bone_connection else ()
    error = mc2_bone_static_domain_error(
        task.setup_type,
        topology.connection_mode,
        triangles,
        getattr(topology, "connection_model", "mc2_source"),
    )
    if error:
        raise ValueError(error)


def _signature(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _readonly_array(values, dtype, width: int | None = None) -> np.ndarray:
    result = np.array(values, dtype=dtype, copy=True, order="C")
    if width is not None:
        result = result.reshape((-1, width))
    result.flags.writeable = False
    return result


@dataclass(frozen=True)
class MC2BoneClothStaticMetadata:
    topology_signature: str
    connection_mode: int
    connection_model: str
    final_proxy: MC2MeshProxyNativeMetadata
    finalizer: MC2MeshFinalizerNativeMetadata
    baseline: MC2MeshBaselineMetadata
    distance: MC2DistanceStaticMetadata
    center: MC2CenterStaticMetadata
    self_collision: MC2SelfCollisionStaticMetadata
    bone_static_signature: str
    static_signature: str
    schema_version: int = MC2_BONE_STATIC_SCHEMA_VERSION
    native_owned: bool = True

    def __post_init__(self) -> None:
        if self.schema_version != MC2_BONE_STATIC_SCHEMA_VERSION:
            raise ValueError("unsupported BoneCloth static metadata schema")
        if not self.topology_signature or not self.bone_static_signature:
            raise ValueError("BoneCloth static metadata signatures cannot be empty")
        if self.connection_mode not in range(4):
            raise ValueError("connection_mode must be in 0..3")
        if self.connection_model not in ("mc2_source", "hotools_product"):
            raise ValueError("unsupported BoneCloth connection_model")
        if self.distance.proxy_signature != self.final_proxy.proxy_signature:
            raise ValueError("distance and Bone proxy signatures must match")
        if self.distance.baseline_signature != self.baseline.baseline_signature:
            raise ValueError("distance and Bone baseline signatures must match")
        if self.center.proxy_signature != self.final_proxy.proxy_signature:
            raise ValueError("center and Bone proxy signatures must match")
        if self.self_collision.proxy_signature != self.final_proxy.proxy_signature:
            raise ValueError("self collision and Bone proxy signatures must match")
        if self.static_signature != _signature(self.signature_payload()):
            raise ValueError("static_signature does not match BoneCloth metadata payload")

    def signature_payload(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "topology_signature": self.topology_signature,
            "connection_mode": self.connection_mode,
            "connection_model": self.connection_model,
            "bone_static_signature": self.bone_static_signature,
            "distance_signature": self.distance.distance_signature,
            "center_static_signature": self.center.center_static_signature,
            "self_collision_static_signature": self.self_collision.static_signature,
        }

    def debug_dict(self) -> dict:
        return {
            "setup_type": self.final_proxy.setup_type,
            "connection_mode": self.connection_mode,
            "connection_model": self.connection_model,
            "vertex_count": self.final_proxy.vertex_count,
            "edge_count": len(self.final_proxy.edges),
            "baseline_count": self.baseline.baseline_count,
            "distance_record_count": self.distance.record_count,
            "center_fixed_count": self.center.fixed_count,
            "self_collision_primitive_count": self.self_collision.primitive_count,
            **self.signature_payload(),
            "static_signature": self.static_signature,
            "native_owned": True,
        }


@dataclass(frozen=True)
class MC2BoneClothStaticBuildResult:
    topology_signature: str
    connection_mode: int
    connection_model: str
    bone: MC2BoneStaticSpec | MC2BoneNativeData
    distance: MC2DistanceStaticSpec | MC2DistanceStaticMetadata
    center: MC2CenterStaticSpec | MC2CenterStaticMetadata
    self_collision: MC2SelfCollisionStaticSpec | MC2SelfCollisionStaticMetadata
    static_signature: str
    schema_version: int = MC2_BONE_STATIC_SCHEMA_VERSION

    @property
    def final_proxy(self):
        return self.bone.proxy

    @property
    def finalizer(self):
        return self.bone.finalizer

    @property
    def baseline(self):
        return self.bone.baseline

    def compact_native_static(self) -> MC2BoneClothStaticMetadata:
        proxy = self.final_proxy
        finalizer = self.finalizer
        baseline = self.baseline
        return MC2BoneClothStaticMetadata(
            topology_signature=self.topology_signature,
            connection_mode=self.connection_mode,
            connection_model=self.connection_model,
            final_proxy=MC2MeshProxyNativeMetadata(
                task_id=proxy.task_id,
                setup_type=proxy.setup_type,
                vertex_identities=proxy.vertex_identities,
                vertex_attributes=_readonly_array(proxy.vertex_attributes, np.uint8),
                edges=_readonly_array(proxy.edges, np.int32, 2),
                triangles=_readonly_array(proxy.triangles, np.int32, 3),
                proxy_signature=proxy.proxy_signature,
            ),
            finalizer=MC2MeshFinalizerNativeMetadata(
                proxy_signature=finalizer.proxy_signature,
                vertex_count=finalizer.vertex_count,
                neighbor_count=len(finalizer.vertex_to_vertex_data),
                triangle_record_count=(
                    len(finalizer.vertex_to_triangle_data)
                    if isinstance(finalizer, MC2MeshFinalizerNativeData)
                    else sum(
                        len(records) for records in finalizer.vertex_to_triangle_records
                    )
                ),
                every_vertex_has_triangle=(
                    finalizer.every_vertex_has_triangle
                    if isinstance(finalizer, MC2MeshFinalizerNativeData)
                    else all(
                        bool(records) for records in finalizer.vertex_to_triangle_records
                    )
                ),
            ),
            baseline=MC2MeshBaselineMetadata(
                proxy_signature=baseline.proxy_signature,
                vertex_count=baseline.vertex_count,
                baseline_count=len(baseline.baseline_ranges),
                depths=_readonly_array(baseline.depths, np.float32),
                baseline_signature=baseline.baseline_signature,
            ),
            distance=(
                self.distance
                if isinstance(self.distance, MC2DistanceStaticMetadata)
                else MC2DistanceStaticMetadata(
                    proxy_signature=self.distance.proxy_signature,
                    baseline_signature=self.distance.baseline_signature,
                    vertex_count=self.distance.vertex_count,
                    record_count=self.distance.record_count,
                    distance_signature=self.distance.distance_signature,
                )
            ),
            center=(
                self.center
                if isinstance(self.center, MC2CenterStaticMetadata)
                else MC2CenterStaticMetadata(
                    task_id=self.center.task_id,
                    proxy_signature=self.center.proxy_signature,
                    fixed_count=self.center.fixed_count,
                    center_static_signature=self.center.center_static_signature,
                )
            ),
            self_collision=(
                self.self_collision
                if isinstance(self.self_collision, MC2SelfCollisionStaticMetadata)
                else MC2SelfCollisionStaticMetadata(
                    proxy_signature=self.self_collision.proxy_signature,
                    point_count=self.self_collision.point_count,
                    edge_count=self.self_collision.edge_count,
                    triangle_count=self.self_collision.triangle_count,
                    static_signature=self.self_collision.static_signature,
                )
            ),
            bone_static_signature=self.bone.static_signature,
            static_signature=self.static_signature,
        )

    def __post_init__(self) -> None:
        if self.schema_version != MC2_BONE_STATIC_SCHEMA_VERSION:
            raise ValueError("unsupported BoneCloth static build schema")
        if not self.topology_signature:
            raise ValueError("topology_signature cannot be empty")
        if self.connection_mode not in range(4):
            raise ValueError("connection_mode must be in 0..3")
        if self.connection_model not in ("mc2_source", "hotools_product"):
            raise ValueError("unsupported BoneCloth connection_model")
        if not isinstance(self.bone, (MC2BoneStaticSpec, MC2BoneNativeData)):
            raise TypeError("bone must be MC2 Bone static data")
        if not isinstance(self.distance, (MC2DistanceStaticSpec, MC2DistanceStaticMetadata)):
            raise TypeError("distance must be MC2 Distance static data")
        if not isinstance(self.center, (MC2CenterStaticSpec, MC2CenterStaticMetadata)):
            raise TypeError("center must be MC2 Center static data")
        if not isinstance(
            self.self_collision,
            (MC2SelfCollisionStaticSpec, MC2SelfCollisionStaticMetadata),
        ):
            raise TypeError("self_collision must be MC2 self-collision static data")
        if self.distance.proxy_signature != self.final_proxy.proxy_signature:
            raise ValueError("distance and Bone proxy signatures must match")
        if self.distance.baseline_signature != self.baseline.baseline_signature:
            raise ValueError("distance and Bone baseline signatures must match")
        if self.center.proxy_signature != self.final_proxy.proxy_signature:
            raise ValueError("center and Bone proxy signatures must match")
        if self.self_collision.proxy_signature != self.final_proxy.proxy_signature:
            raise ValueError("self collision and Bone proxy signatures must match")
        if self.static_signature != _signature(self.signature_payload()):
            raise ValueError("static_signature does not match BoneCloth static payload")

    def signature_payload(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "topology_signature": self.topology_signature,
            "connection_mode": self.connection_mode,
            "connection_model": self.connection_model,
            "bone_static_signature": self.bone.static_signature,
            "distance_signature": self.distance.distance_signature,
            "center_static_signature": self.center.center_static_signature,
            "self_collision_static_signature": self.self_collision.static_signature,
        }

    def debug_dict(self) -> dict:
        return {
            "setup_type": self.final_proxy.setup_type,
            "connection_mode": self.connection_mode,
            "connection_model": self.connection_model,
            "vertex_count": self.final_proxy.vertex_count,
            "edge_count": len(self.final_proxy.edges),
            "baseline_count": len(self.baseline.baseline_ranges),
            "distance_record_count": self.distance.record_count,
            "center_fixed_count": self.center.fixed_count,
            "self_collision_primitive_count": self.self_collision.primitive_count,
            **self.signature_payload(),
            "static_signature": self.static_signature,
        }


def _flatten_bone_records(topology: MC2TopologySpec) -> tuple[dict, ...]:
    if not topology.sources or not all(source.resolved for source in topology.sources):
        raise ValueError("BoneCloth static requires resolved Armature chain sources")
    armatures = set()
    flattened = []
    for source in topology.sources:
        payload = _thaw(source.payload)
        armatures.add((
            int(payload.get("armature_pointer", 0) or 0),
            str(payload.get("armature_name") or ""),
        ))
        records = tuple(payload.get("bones") or ())
        offset = len(flattened)
        for record in records:
            copied = dict(record)
            parent = int(copied.get("parent_index", -1))
            copied["parent_index"] = -1 if parent < 0 else offset + parent
            copied["child_indices"] = tuple(
                offset + int(child)
                for child in copied.get("child_indices", ())
            )
            flattened.append(copied)
    if len(armatures) != 1:
        raise ValueError("BoneCloth task sources must belong to one Armature")
    if len(flattened) != topology.particle_count:
        raise ValueError("BoneCloth topology record count mismatch")
    return tuple(flattened)


def build_mc2_bone_cloth_static_for_task(
    task: MC2TaskSpec,
    topology: MC2TopologySpec,
    *,
    raw_snapshots=None,
    native_context=None,
) -> MC2BoneClothStaticBuildResult | None:
    if not isinstance(task, MC2TaskSpec):
        raise TypeError("task must be MC2TaskSpec")
    if not isinstance(topology, MC2TopologySpec):
        raise TypeError("topology must be MC2TopologySpec")
    if task.task_id != topology.task_id or task.setup_type != topology.setup_type:
        raise ValueError("BoneCloth static task/topology identity mismatch")
    if task.setup_type not in MC2_LINE_BONE_SETUP_TYPES:
        return None
    _require_mc2_bone_static_domain(task, topology)
    if topology.bone_connection is None:
        raise ValueError("BoneCloth Line static requires frozen connection topology")
    snapshots = tuple(raw_snapshots or ())
    use_snapshots = (
        len(snapshots) == len(topology.sources)
        and all(isinstance(item, MC2BoneRawSnapshot) for item in snapshots)
    )
    records = () if use_snapshots else _flatten_bone_records(topology)
    record_count = sum(len(item.names) for item in snapshots) if use_snapshots else len(records)
    if record_count != topology.particle_count:
        raise ValueError("BoneCloth topology record count mismatch")
    identities = []
    positions = []
    normals = []
    tangents = []
    transform_rotations = []
    parents = []
    roots = []
    attributes = []
    if use_snapshots:
        armatures = {
            (item.armature_pointer, item.armature_name)
            for item in snapshots
        }
        if len(armatures) != 1:
            raise ValueError("BoneCloth task sources must belong to one Armature")
        source_rows = []
        offset = 0
        for snapshot in snapshots:
            for local_index, identity in enumerate(snapshot.names):
                local_parent = int(snapshot.parents[local_index])
                source_rows.append((
                    identity,
                    -1 if local_parent < 0 else offset + local_parent,
                    snapshot.head_tail[local_index, :3],
                    tuple(float(value) for value in snapshot.matrices[local_index]),
                ))
            offset += len(snapshot.names)
    else:
        source_rows = tuple(
            (
                str(record.get("name") or ""),
                int(record.get("parent_index", -1)),
                record.get("head", (0, 0, 0)),
                record.get("matrix_local"),
            )
            for record in records
        )
    matrices = np.ascontiguousarray(
        tuple(row[3] for row in source_rows),
        dtype=np.float32,
    ).reshape((record_count, 16))
    transform_values = np.empty((record_count, 4), dtype=np.float64)
    normal_values = np.empty((record_count, 3), dtype=np.float64)
    tangent_values = np.empty((record_count, 3), dtype=np.float64)
    from ...native import native_module

    native_module().mc2_build_bone_rest_frames_v0(
        matrices,
        transform_values,
        normal_values,
        tangent_values,
    )
    for vertex, (identity, parent, head, _matrix_values) in enumerate(source_rows):
        if not identity:
            raise ValueError("BoneCloth static bone identity cannot be empty")
        identities.append(identity)
        positions.append(tuple(float(value) for value in head))
        normals.append(tuple(float(value) for value in normal_values[vertex]))
        tangents.append(tuple(float(value) for value in tangent_values[vertex]))
        transform_rotations.append(tuple(float(value) for value in transform_values[vertex]))
        parents.append(parent)
        if parent < 0:
            roots.append(vertex)
            attributes.append(0x01)
        else:
            attributes.append(0x02)

    if topology.bone_connection.triangles:
        if topology.connection_model != "hotools_product":
            raise ValueError("Bone triangle UV generation is product-mode only")
        root_values = topology.bone_connection.root_indices
        level_values = topology.bone_connection.levels
        root_count = max(root_values, default=0) + 1
        max_level = max(level_values, default=0)
        uvs = tuple(
            (
                float(root_values[vertex]) / float(max(root_count - 1, 1)),
                float(level_values[vertex]) / float(max(max_level, 1)),
            )
            for vertex in range(record_count)
        )
    else:
        uvs = ((0.0, 0.0),) * record_count

    bone = build_mc2_bone_static(
        task_id=task.task_id,
        setup_type=task.setup_type,
        vertex_identities=identities,
        local_positions=positions,
        local_normals=normals,
        local_tangents=tangents,
        uvs=uvs,
        vertex_attributes=attributes,
        parent_indices=parents,
        root_indices=roots,
        transform_local_rotations=transform_rotations,
        lines=topology.bone_connection.lines,
        triangles=topology.bone_connection.triangles,
        native_context=native_context,
    )
    if native_context is not None:
        native_context.initialize_bone_proxy_baseline(bone)
    distance = build_mc2_distance_static(
        bone.proxy,
        bone.baseline,
        vertex_to_vertex_ranges=bone.finalizer.vertex_to_vertex_ranges,
        vertex_to_vertex_data=bone.finalizer.vertex_to_vertex_data,
        native_context=native_context,
    )
    center = build_mc2_center_static(
        bone.proxy,
        vertex_bind_pose_rotations=bone.finalizer.vertex_bind_pose_rotations,
        world_gravity_direction=task.profile.gravity_direction,
        native_context=native_context,
    )
    self_collision = build_mc2_self_collision_static(
        bone.proxy,
        bone.baseline.depths,
        native_context=native_context,
    )
    signature_payload = {
        "schema_version": MC2_BONE_STATIC_SCHEMA_VERSION,
        "topology_signature": topology.topology_signature,
        "connection_mode": topology.connection_mode,
        "connection_model": topology.connection_model,
        "bone_static_signature": bone.static_signature,
        "distance_signature": distance.distance_signature,
        "center_static_signature": center.center_static_signature,
        "self_collision_static_signature": self_collision.static_signature,
    }
    return MC2BoneClothStaticBuildResult(
        topology_signature=topology.topology_signature,
        connection_mode=topology.connection_mode,
        connection_model=topology.connection_model,
        bone=bone,
        distance=distance,
        center=center,
        self_collision=self_collision,
        static_signature=_signature(signature_payload),
    )


__all__ = [
    "MC2BoneClothStaticBuildResult",
    "MC2BoneClothStaticMetadata",
    "build_mc2_bone_cloth_static_for_task",
    "mc2_bone_static_domain_error",
]
