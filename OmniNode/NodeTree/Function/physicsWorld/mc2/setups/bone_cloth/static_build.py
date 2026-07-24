"""BoneCloth/BoneSpring Line static assembly for staged MC2 registration."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

import numpy as np

from ...bending_static import MC2BendingStaticSpec
from ...bending_static import build_mc2_bending_static
from ...bone_static import MC2BoneStaticSpec
from ...bone_static import build_mc2_bone_static
from ...center_state import MC2CenterStaticSpec
from ...center_state import build_mc2_center_static
from ...distance_static import MC2DistanceStaticSpec
from ...distance_static import build_mc2_distance_static
from ...names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from ...self_collision_static import (
    MC2SelfCollisionStaticSpec,
)
from ...self_collision_static import build_mc2_self_collision_static
from ...self_collision_static import make_empty_mc2_self_collision_static
from ...topology import MC2BoneRawSnapshot, MC2TopologySpec
from ...topology import thaw_mc2_topology_payload

MC2_BONE_STATIC_SCHEMA_VERSION = 4
MC2_LINE_BONE_SETUP_TYPES = (MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING)


@dataclass(frozen=True)
class _MC2BoneStaticIntentV1:
    task_id: str
    setup_type: str
    profile: object
    sources: tuple[object, ...]


def _partition_static_intent(partition) -> _MC2BoneStaticIntentV1:
    from ...partition_specs import MC2ResolvedPartitionSpec
    from .authoring import MC2BonePartitionSourceV1

    if not isinstance(partition, MC2ResolvedPartitionSpec):
        raise TypeError("partition must be MC2ResolvedPartitionSpec")
    if not isinstance(partition.source, MC2BonePartitionSourceV1):
        raise TypeError("Bone product partition source is invalid")
    return _MC2BoneStaticIntentV1(
        task_id=partition.stable_id,
        setup_type=partition.setup_type,
        profile=partition.profile,
        sources=partition.source.task_sources,
    )


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


def _require_mc2_bone_static_domain(intent, topology: MC2TopologySpec) -> None:
    triangles = topology.bone_connection.triangles if topology.bone_connection else ()
    error = mc2_bone_static_domain_error(
        intent.setup_type,
        topology.connection_mode,
        triangles,
        getattr(topology, "connection_model", "mc2_source"),
    )
    if error:
        raise ValueError(error)


def _signature(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()





@dataclass(frozen=True)
class MC2BoneClothStaticBuildResult:
    topology_signature: str
    connection_mode: int
    connection_model: str
    bone: MC2BoneStaticSpec
    distance: MC2DistanceStaticSpec
    bending: MC2BendingStaticSpec | None
    center: MC2CenterStaticSpec
    self_collision: MC2SelfCollisionStaticSpec
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


    def __post_init__(self) -> None:
        if self.schema_version != MC2_BONE_STATIC_SCHEMA_VERSION:
            raise ValueError("unsupported BoneCloth static build schema")
        if not self.topology_signature:
            raise ValueError("topology_signature cannot be empty")
        if self.connection_mode not in range(4):
            raise ValueError("connection_mode must be in 0..3")
        if self.connection_model not in ("mc2_source", "hotools_product"):
            raise ValueError("unsupported BoneCloth connection_model")
        if not isinstance(self.bone, MC2BoneStaticSpec):
            raise TypeError("bone must be MC2 Bone static data")
        if not isinstance(self.distance, MC2DistanceStaticSpec):
            raise TypeError("distance must be MC2 Distance static data")
        if self.bending is not None and not isinstance(self.bending, MC2BendingStaticSpec):
            raise TypeError("bending must be MC2 Bending static data or None")
        if not isinstance(self.center, MC2CenterStaticSpec):
            raise TypeError("center must be MC2 Center static data")
        if not isinstance(self.self_collision, MC2SelfCollisionStaticSpec):
            raise TypeError("self_collision must be MC2 self-collision static data")
        if self.distance.proxy_signature != self.final_proxy.proxy_signature:
            raise ValueError("distance and Bone proxy signatures must match")
        if self.distance.baseline_signature != self.baseline.baseline_signature:
            raise ValueError("distance and Bone baseline signatures must match")
        if (
            self.bending is not None
            and self.bending.proxy_signature != self.final_proxy.proxy_signature
        ):
            raise ValueError("bending and Bone proxy signatures must match")
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
            "bending_signature": (
                self.bending.bending_signature if self.bending is not None else "empty"
            ),
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
            "bending_record_count": (
                self.bending.record_count if self.bending is not None else 0
            ),
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
        payload = thaw_mc2_topology_payload(source.payload)
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


def _initial_armature_world_columns(intent: _MC2BoneStaticIntentV1):
    for source in intent.sources:
        armature = source.get("armature") if isinstance(source, dict) else None
        matrix = getattr(armature, "matrix_world", None)
        if matrix is not None:
            return tuple(
                tuple(float(matrix[row][column]) for row in range(4))
                for column in range(4)
            )
    return None


def build_mc2_bone_static_for_partition(
    partition,
    topology: MC2TopologySpec,
    *,
    raw_snapshots=None,
) -> MC2BoneClothStaticBuildResult | None:
    """从 resolved Bone partition 构建完整宿主静态包。"""

    return _build_mc2_bone_static(
        _partition_static_intent(partition),
        topology,
        raw_snapshots=raw_snapshots,
    )


def _build_mc2_bone_static(
    intent: _MC2BoneStaticIntentV1,
    topology: MC2TopologySpec,
    *,
    raw_snapshots=None,
) -> MC2BoneClothStaticBuildResult | None:
    if not isinstance(topology, MC2TopologySpec):
        raise TypeError("topology must be MC2TopologySpec")
    if intent.task_id != topology.task_id or intent.setup_type != topology.setup_type:
        raise ValueError("BoneCloth static task/topology identity mismatch")
    if intent.setup_type not in MC2_LINE_BONE_SETUP_TYPES:
        return None
    _require_mc2_bone_static_domain(intent, topology)
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
    if use_snapshots:
        armatures = {
            (item.armature_pointer, item.armature_name)
            for item in snapshots
        }
        if len(armatures) != 1:
            raise ValueError("BoneCloth task sources must belong to one Armature")
        identities = []
        parent_chunks = []
        position_chunks = []
        matrix_chunks = []
        offset = 0
        for snapshot in snapshots:
            identities.extend(snapshot.names)
            local_parents = np.ascontiguousarray(snapshot.parents, dtype=np.int32)
            parent_chunks.append(np.where(local_parents < 0, -1, local_parents + offset))
            position_chunks.append(
                np.ascontiguousarray(snapshot.head_tail[:, :3], dtype=np.float64)
            )
            matrix_chunks.append(
                np.ascontiguousarray(snapshot.matrices, dtype=np.float32)
            )
            offset += len(snapshot.names)
        identities = tuple(identities)
        parents = np.concatenate(parent_chunks)
        positions = np.concatenate(position_chunks, axis=0)
        matrices = np.concatenate(matrix_chunks, axis=0).reshape((record_count, 16))
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
        identities = tuple(row[0] for row in source_rows)
        parents = np.fromiter(
            (row[1] for row in source_rows),
            dtype=np.int32,
            count=record_count,
        )
        positions = np.ascontiguousarray(
            tuple(row[2] for row in source_rows),
            dtype=np.float64,
        ).reshape((record_count, 3))
        matrices = np.ascontiguousarray(
            tuple(row[3] for row in source_rows),
            dtype=np.float32,
        ).reshape((record_count, 16))
    if any(not identity for identity in identities):
        raise ValueError("BoneCloth static bone identity cannot be empty")
    transform_values = np.empty((record_count, 4), dtype=np.float64)
    normal_values = np.empty((record_count, 3), dtype=np.float64)
    tangent_values = np.empty((record_count, 3), dtype=np.float64)
    from ...native import native_module

    native_module().mc2_build_bone_rest_frames(
        matrices,
        transform_values,
        normal_values,
        tangent_values,
    )
    roots = np.flatnonzero(parents < 0).astype(np.int32, copy=False)
    attributes = np.where(parents < 0, 0x01, 0x02).astype(np.uint8, copy=False)

    if topology.bone_connection.triangles:
        if topology.connection_model != "hotools_product":
            raise ValueError("Bone triangle UV generation is product-mode only")
        root_values = np.asarray(topology.bone_connection.root_indices, dtype=np.float64)
        level_values = np.asarray(topology.bone_connection.levels, dtype=np.float64)
        root_count = int(np.max(root_values, initial=0.0)) + 1
        max_level = float(np.max(level_values, initial=0.0))
        uvs = np.empty((record_count, 2), dtype=np.float64)
        uvs[:, 0] = root_values / float(max(root_count - 1, 1))
        uvs[:, 1] = level_values / float(max(max_level, 1.0))
    else:
        uvs = np.zeros((record_count, 2), dtype=np.float64)

    bone = build_mc2_bone_static(
        task_id=intent.task_id,
        setup_type=intent.setup_type,
        vertex_identities=identities,
        local_positions=positions,
        local_normals=normal_values,
        local_tangents=tangent_values,
        uvs=uvs,
        vertex_attributes=attributes,
        parent_indices=parents,
        root_indices=roots,
        transform_local_rotations=transform_values,
        lines=topology.bone_connection.lines,
        triangles=topology.bone_connection.triangles,
    )
    distance = build_mc2_distance_static(
        bone.proxy,
        bone.baseline,
        vertex_to_vertex_ranges=bone.finalizer.vertex_to_vertex_ranges,
        vertex_to_vertex_data=bone.finalizer.vertex_to_vertex_data,
    )
    bending = build_mc2_bending_static(
        bone.proxy,
        initial_local_to_world_columns=_initial_armature_world_columns(intent),
    )
    center = build_mc2_center_static(
        bone.proxy,
        vertex_bind_pose_rotations=bone.finalizer.vertex_bind_pose_rotations,
        world_gravity_direction=intent.profile.gravity_direction,
    )
    if intent.setup_type == MC2_SETUP_BONE_SPRING:
        self_collision = make_empty_mc2_self_collision_static(
            bone.proxy.proxy_signature
        )
    else:
        self_collision = build_mc2_self_collision_static(
            bone.proxy,
            bone.baseline.depths,
        )
    signature_payload = {
        "schema_version": MC2_BONE_STATIC_SCHEMA_VERSION,
        "topology_signature": topology.topology_signature,
        "connection_mode": topology.connection_mode,
        "connection_model": topology.connection_model,
        "bone_static_signature": bone.static_signature,
        "distance_signature": distance.distance_signature,
        "bending_signature": (
            bending.bending_signature if bending is not None else "empty"
        ),
        "center_static_signature": center.center_static_signature,
        "self_collision_static_signature": self_collision.static_signature,
    }
    return MC2BoneClothStaticBuildResult(
        topology_signature=topology.topology_signature,
        connection_mode=topology.connection_mode,
        connection_model=topology.connection_model,
        bone=bone,
        distance=distance,
        bending=bending,
        center=center,
        self_collision=self_collision,
        static_signature=_signature(signature_payload),
    )


__all__ = [
    "MC2BoneClothStaticBuildResult",
    "build_mc2_bone_static_for_partition",
    "mc2_bone_static_domain_error",
]
