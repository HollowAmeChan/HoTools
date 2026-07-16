"""BoneCloth/BoneSpring Line static assembly for staged MC2 registration."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from ...bone_static import MC2BoneStaticSpec
from ...bone_static import build_mc2_bone_static
from ...center_state import MC2CenterStaticSpec
from ...center_state import build_mc2_center_static
from ...distance_static import MC2DistanceStaticSpec
from ...distance_static import build_mc2_distance_static
from ...names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from ...self_collision_static import MC2SelfCollisionStaticSpec
from ...self_collision_static import build_mc2_self_collision_static
from ...specs import MC2TaskSpec
from ...topology import MC2TopologySpec
from ...topology import _thaw
from ....utils.math3d import (
    matrix4_tuple_from_flat as _matrix_from_flat,
    quaternion_from_matrix4_xyzw_tuple as _quaternion_from_matrix,
    rotate_vector_unit_xyzw_tuple_fast as _rotate_xyzw,
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


@dataclass(frozen=True)
class MC2BoneClothStaticBuildResult:
    topology_signature: str
    connection_mode: int
    connection_model: str
    bone: MC2BoneStaticSpec
    distance: MC2DistanceStaticSpec
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
            raise TypeError("bone must be MC2BoneStaticSpec")
        if not isinstance(self.distance, MC2DistanceStaticSpec):
            raise TypeError("distance must be MC2DistanceStaticSpec")
        if not isinstance(self.center, MC2CenterStaticSpec):
            raise TypeError("center must be MC2CenterStaticSpec")
        if not isinstance(self.self_collision, MC2SelfCollisionStaticSpec):
            raise TypeError("self_collision must be MC2SelfCollisionStaticSpec")
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
            "distance_record_count": len(self.distance.distance_targets),
            "center_fixed_count": len(self.center.fixed_indices),
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


def bone_cloth_static_input_signature_for_task(
    task: MC2TaskSpec,
    topology: MC2TopologySpec,
) -> str | None:
    if not isinstance(task, MC2TaskSpec):
        raise TypeError("task must be MC2TaskSpec")
    if not isinstance(topology, MC2TopologySpec):
        raise TypeError("topology must be MC2TopologySpec")
    if task.setup_type not in MC2_LINE_BONE_SETUP_TYPES:
        return None
    _require_mc2_bone_static_domain(task, topology)
    _flatten_bone_records(topology)
    payload = {
        "schema_version": MC2_BONE_STATIC_SCHEMA_VERSION,
        "setup_type": task.setup_type,
        "topology_signature": topology.topology_signature,
        "connection_mode": topology.connection_mode,
        "connection_model": topology.connection_model,
        "selection_rule": "parentless_fixed_else_move",
        "normal_alignment_mode": 0,
        "world_gravity_direction": task.profile.gravity_direction,
    }
    return _signature(payload)


def build_mc2_bone_cloth_static_for_task(
    task: MC2TaskSpec,
    topology: MC2TopologySpec,
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
    records = _flatten_bone_records(topology)
    if len(records) != topology.particle_count:
        raise ValueError("BoneCloth topology record count mismatch")
    identities = []
    positions = []
    normals = []
    tangents = []
    transform_rotations = []
    parents = []
    roots = []
    attributes = []
    for vertex, record in enumerate(records):
        identity = str(record.get("name") or "")
        if not identity:
            raise ValueError("BoneCloth static bone identity cannot be empty")
        parent = int(record.get("parent_index", -1))
        matrix = _matrix_from_flat(record.get("matrix_local"))
        rotation = _quaternion_from_matrix(matrix)
        identities.append(identity)
        positions.append(tuple(float(value) for value in record.get("head", (0, 0, 0))))
        normals.append(_rotate_xyzw(rotation, (0.0, 1.0, 0.0)))
        tangents.append(_rotate_xyzw(rotation, (0.0, 0.0, 1.0)))
        transform_rotations.append(rotation)
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
            for vertex in range(len(records))
        )
    else:
        uvs = ((0.0, 0.0),) * len(records)

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
    )
    distance = build_mc2_distance_static(
        bone.proxy,
        bone.baseline,
        vertex_to_vertex_ranges=bone.finalizer.vertex_to_vertex_ranges,
        vertex_to_vertex_data=bone.finalizer.vertex_to_vertex_data,
    )
    center = build_mc2_center_static(
        bone.proxy,
        vertex_bind_pose_rotations=bone.finalizer.vertex_bind_pose_rotations,
        world_gravity_direction=task.profile.gravity_direction,
    )
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
    "bone_cloth_static_input_signature_for_task",
    "build_mc2_bone_cloth_static_for_task",
    "mc2_bone_static_domain_error",
]
