"""Backend-neutral MC2 unified-domain contracts.

This module is intentionally isolated from Blender, PhysicsWorldCache, solver
slots, native handles, and node execution.  It defines the E0 POD boundary
only.  Capture code, backend adapters, and writeback code will consume these
contracts in later migration stages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

import numpy as np


MC2_DOMAIN_IR_SCHEMA_VERSION = 1
MC2_PARTITION_FRAME_RESET = 1 << 0
MC2_PARTITION_FRAME_KEEP = 1 << 1
MC2_PARTITION_FRAME_DISABLED = 1 << 2
_SETUP_TYPES = frozenset(("mesh_cloth", "bone_cloth", "bone_spring"))
_INDEX_VIEW_KINDS = frozenset(("span", "indices"))
_CONSTRAINT_WIDTHS = {
    "distance": 2,
    "tether": 2,
    "bending": 4,
    "angle": 2,
}
_PRIMITIVE_WIDTHS = {
    "point": 1,
    "edge": 2,
    "triangle": 3,
}
_OUTPUT_SPACE_KINDS = frozenset(("mesh_object_local_offset", "bone_pose"))


def _text(value: object, name: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{name} cannot be empty")
    return result


def _ordered_unique(values, name: str) -> tuple[str, ...]:
    result = tuple(_text(value, name) for value in values)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must be unique")
    if result != tuple(sorted(result)):
        raise ValueError(f"{name} must be sorted")
    return result


def _unique(values, name: str) -> tuple[str, ...]:
    result = tuple(_text(value, name) for value in values)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must be unique")
    return result


def _readonly_array(values, dtype, shape: tuple[int, ...], name: str) -> np.ndarray:
    array = np.array(values, dtype=dtype, order="C", copy=True)
    if array.size == 0 and 0 in shape:
        array = array.reshape(shape)
    if array.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {array.shape}")
    if np.issubdtype(array.dtype, np.floating) and not np.isfinite(array).all():
        raise ValueError(f"{name} cannot contain NaN/Inf")
    array.setflags(write=False)
    return array


def _validate_array(
    value: object,
    dtype,
    shape: tuple[int, ...],
    name: str,
) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise TypeError(f"{name} must be a numpy.ndarray")
    if value.dtype != np.dtype(dtype) or value.shape != shape:
        raise ValueError(
            f"{name} must be {np.dtype(dtype)}{shape}, got {value.dtype}{value.shape}"
        )
    if value.flags.writeable or not value.flags.c_contiguous:
        raise ValueError(f"{name} must be contiguous and read-only")
    if np.issubdtype(value.dtype, np.floating) and not np.isfinite(value).all():
        raise ValueError(f"{name} cannot contain NaN/Inf")
    return value


def _readonly_uint(values, shape: tuple[int, ...], name: str) -> np.ndarray:
    return _readonly_array(values, np.uint32, shape, name)


def _readonly_float(values, shape: tuple[int, ...], name: str) -> np.ndarray:
    return _readonly_array(values, np.float32, shape, name)


def _digest(parts) -> str:
    digest = hashlib.sha256(b"mc2_domain_ir_v1\0")
    def visit(part) -> None:
        if isinstance(part, np.ndarray):
            digest.update(b"array\0")
            digest.update(str(part.dtype).encode("ascii"))
            digest.update(json.dumps(part.shape, separators=(",", ":")).encode("ascii"))
            digest.update(part.tobytes(order="C"))
            return
        if isinstance(part, dict):
            digest.update(b"mapping\0")
            for key in sorted(part, key=str):
                visit(str(key))
                visit(part[key])
            digest.update(b"/mapping\0")
            return
        if isinstance(part, (tuple, list)):
            digest.update(b"sequence\0")
            for item in part:
                visit(item)
            digest.update(b"/sequence\0")
            return
        digest.update(type(part).__name__.encode("ascii"))
        digest.update(b"\0")
        digest.update(str(part).encode("utf-8"))
        digest.update(b"\0")
    for part in parts:
        visit(part)
    return digest.hexdigest()


@dataclass(frozen=True)
class MC2MeshPartitionStaticSnapshotV1:
    """One MeshCloth source captured as read-only host POD."""

    partition_id: str
    source_identity: str
    source_revision: str
    output_target_id: str
    local_positions: np.ndarray
    local_normals: np.ndarray
    edges: np.ndarray
    triangles: np.ndarray
    triangle_loops: np.ndarray
    loop_vertices: np.ndarray
    loop_uvs: np.ndarray
    pin_weights: np.ndarray
    pin_present: bool
    radius_multipliers: np.ndarray
    source_bind_matrix: np.ndarray
    source_element_ids: np.ndarray
    has_uv: bool
    schema_version: int = MC2_DOMAIN_IR_SCHEMA_VERSION
    static_signature: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != MC2_DOMAIN_IR_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 static snapshot schema version")
        object.__setattr__(self, "partition_id", _text(self.partition_id, "partition_id"))
        object.__setattr__(self, "source_identity", _text(self.source_identity, "source_identity"))
        object.__setattr__(self, "source_revision", _text(self.source_revision, "source_revision"))
        object.__setattr__(self, "output_target_id", _text(self.output_target_id, "output_target_id"))
        if type(self.pin_present) is not bool or type(self.has_uv) is not bool:
            raise TypeError("pin_present and has_uv must be bool")
        vertex_count = len(self.local_positions)
        loop_count = len(self.loop_vertices)
        _validate_array(self.local_positions, np.float32, (vertex_count, 3), "local_positions")
        _validate_array(self.local_normals, np.float32, (vertex_count, 3), "local_normals")
        if vertex_count == 0:
            raise ValueError("static snapshot must contain at least one vertex")
        _validate_array(self.edges, np.uint32, self.edges.shape, "edges")
        _validate_array(self.triangles, np.uint32, self.triangles.shape, "triangles")
        _validate_array(self.triangle_loops, np.uint32, self.triangle_loops.shape, "triangle_loops")
        _validate_array(self.loop_vertices, np.uint32, (loop_count,), "loop_vertices")
        uv_shape = self.loop_uvs.shape
        if uv_shape not in ((loop_count, 2), (0, 2)):
            raise ValueError("loop_uvs must have shape [L,2] or [0,2]")
        _validate_array(self.loop_uvs, np.float32, uv_shape, "loop_uvs")
        if self.has_uv and uv_shape != (loop_count, 2):
            raise ValueError("has_uv requires one UV per loop")
        if not self.has_uv and uv_shape != (0, 2):
            raise ValueError("loop_uvs must be empty when has_uv is false")
        pin_shape = self.pin_weights.shape
        if pin_shape not in ((vertex_count,), (0,)):
            raise ValueError("pin_weights must have shape [V] or [0]")
        _validate_array(self.pin_weights, np.float32, pin_shape, "pin_weights")
        if self.pin_present and pin_shape != (vertex_count,):
            raise ValueError("pin_present requires one weight per vertex")
        if not self.pin_present and pin_shape != (0,):
            raise ValueError("pin_weights must be empty when pin_present is false")
        _validate_array(
            self.radius_multipliers,
            np.float32,
            (vertex_count,),
            "radius_multipliers",
        )
        _validate_array(
            self.source_bind_matrix,
            np.float32,
            (4, 4),
            "source_bind_matrix",
        )
        _validate_array(
            self.source_element_ids,
            np.uint32,
            (vertex_count,),
            "source_element_ids",
        )
        if np.any(self.edges >= vertex_count) or np.any(self.triangles >= vertex_count):
            raise ValueError("static topology contains an out-of-range vertex")
        if np.any(self.triangle_loops >= loop_count) and len(self.triangle_loops):
            raise ValueError("triangle_loops contains an out-of-range loop")
        if np.any(self.loop_vertices >= vertex_count) and loop_count:
            raise ValueError("loop_vertices contains an out-of-range vertex")
        if self.edges.ndim != 2 or self.edges.shape[1] != 2:
            raise ValueError("edges must have shape [E,2]")
        if self.triangles.ndim != 2 or self.triangles.shape[1] != 3:
            raise ValueError("triangles must have shape [T,3]")
        if self.triangle_loops.ndim != 2 or self.triangle_loops.shape[1] != 3:
            raise ValueError("triangle_loops must have shape [T,3]")
        if len(self.triangle_loops) != len(self.triangles):
            raise ValueError("triangle_loops must match triangles")
        if np.any(self.pin_weights < 0.0) or np.any(self.pin_weights > 1.0):
            raise ValueError("pin_weights must be in 0..1")
        if np.any(self.radius_multipliers < 0.0) or np.any(self.radius_multipliers > 1.0):
            raise ValueError("radius_multipliers must be in 0..1")
        if len(set(int(value) for value in self.source_element_ids)) != vertex_count:
            raise ValueError("source_element_ids must be unique")
        determinant = np.linalg.det(self.source_bind_matrix[:3, :3].astype(np.float64))
        if abs(float(determinant)) <= 1.0e-12:
            raise ValueError("source_bind_matrix must be invertible")
        object.__setattr__(self, "static_signature", _digest((
            self.schema_version,
            self.partition_id,
            self.source_identity,
            self.source_revision,
            self.output_target_id,
            self.local_positions,
            self.local_normals,
            self.edges,
            self.triangles,
            self.triangle_loops,
            self.loop_vertices,
            self.loop_uvs,
            self.pin_weights,
            self.pin_present,
            self.radius_multipliers,
            self.source_bind_matrix,
            self.source_element_ids,
            self.has_uv,
        )))

    @property
    def vertex_count(self) -> int:
        return int(len(self.local_positions))

    def debug_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "partition_id": self.partition_id,
            "source_identity": self.source_identity,
            "source_revision": self.source_revision,
            "output_target_id": self.output_target_id,
            "static_signature": self.static_signature,
            "vertex_count": self.vertex_count,
            "edge_count": len(self.edges),
            "triangle_count": len(self.triangles),
            "has_uv": self.has_uv,
            "pin_present": self.pin_present,
        }


def make_mc2_mesh_partition_static_snapshot(
    *,
    partition_id: str,
    source_identity: str,
    source_revision: str,
    output_target_id: str,
    local_positions,
    local_normals,
    edges,
    triangles,
    triangle_loops,
    loop_vertices,
    loop_uvs=None,
    pin_weights=None,
    pin_present: bool = False,
    radius_multipliers=None,
    source_bind_matrix,
    source_element_ids=None,
    has_uv: bool = False,
) -> MC2MeshPartitionStaticSnapshotV1:
    if type(pin_present) is not bool or type(has_uv) is not bool:
        raise TypeError("pin_present and has_uv must be bool")
    vertex_count = len(local_positions)
    loop_count = len(loop_vertices)
    normalized_loop_uvs = () if loop_uvs is None else loop_uvs
    normalized_pin_weights = () if pin_weights is None else pin_weights
    normalized_radius = (1.0,) * vertex_count if radius_multipliers is None else radius_multipliers
    normalized_source_ids = tuple(range(vertex_count)) if source_element_ids is None else source_element_ids
    triangle_rows = tuple(tuple(int(value) for value in row) for row in triangles)
    triangle_loop_rows = tuple(tuple(int(value) for value in row) for row in triangle_loops)
    edge_rows = tuple(tuple(int(value) for value in row) for row in edges)
    return MC2MeshPartitionStaticSnapshotV1(
        partition_id=partition_id,
        source_identity=source_identity,
        source_revision=source_revision,
        output_target_id=output_target_id,
        local_positions=_readonly_float(local_positions, (vertex_count, 3), "local_positions"),
        local_normals=_readonly_float(local_normals, (vertex_count, 3), "local_normals"),
        edges=_readonly_uint(edge_rows, (len(edge_rows), 2), "edges"),
        triangles=_readonly_uint(triangle_rows, (len(triangle_rows), 3), "triangles"),
        triangle_loops=_readonly_uint(
            triangle_loop_rows, (len(triangle_loop_rows), 3), "triangle_loops"
        ),
        loop_vertices=_readonly_uint(loop_vertices, (loop_count,), "loop_vertices"),
        loop_uvs=_readonly_float(
            normalized_loop_uvs,
            (loop_count, 2) if has_uv else (0, 2),
            "loop_uvs",
        ),
        pin_weights=_readonly_float(
            normalized_pin_weights,
            (vertex_count,) if pin_present else (0,),
            "pin_weights",
        ),
        pin_present=pin_present,
        radius_multipliers=_readonly_float(
            normalized_radius, (vertex_count,), "radius_multipliers"
        ),
        source_bind_matrix=_readonly_float(source_bind_matrix, (4, 4), "source_bind_matrix"),
        source_element_ids=_readonly_uint(
            normalized_source_ids, (vertex_count,), "source_element_ids"
        ),
        has_uv=has_uv,
    )


@dataclass(frozen=True)
class MC2IndexViewV1:
    """A logical particle view that may be contiguous or explicitly indexed."""

    kind: str
    start: int = 0
    stop: int = 0
    indices: np.ndarray | None = None

    def __post_init__(self) -> None:
        kind = _text(self.kind, "index view kind")
        if kind not in _INDEX_VIEW_KINDS:
            raise ValueError(f"unsupported index view kind: {kind!r}")
        object.__setattr__(self, "kind", kind)
        if isinstance(self.start, bool) or isinstance(self.stop, bool):
            raise TypeError("index view bounds must be integers")
        if kind == "span":
            if self.indices is not None:
                raise ValueError("span view cannot contain explicit indices")
            if int(self.start) < 0 or int(self.stop) < int(self.start):
                raise ValueError("span view bounds are invalid")
            object.__setattr__(self, "start", int(self.start))
            object.__setattr__(self, "stop", int(self.stop))
            return
        if self.start != 0 or self.stop != 0:
            raise ValueError("indices view cannot contain span bounds")
        if self.indices is None:
            raise ValueError("indices view requires an indices array")
        _validate_array(self.indices, np.uint32, (len(self.indices),), "index view indices")

    @property
    def count(self) -> int:
        if self.kind == "span":
            return self.stop - self.start
        return int(len(self.indices))

    def resolved_indices(self) -> np.ndarray:
        if self.kind == "span":
            result = np.arange(self.start, self.stop, dtype=np.uint32)
            result.setflags(write=False)
            return result
        return self.indices

    def debug_dict(self) -> dict:
        return {
            "kind": self.kind,
            "start": self.start,
            "stop": self.stop,
            "indices": (
                [int(value) for value in self.indices]
                if self.indices is not None
                else None
            ),
        }


def make_mc2_span_view(start: int, stop: int) -> MC2IndexViewV1:
    return MC2IndexViewV1(kind="span", start=int(start), stop=int(stop))


def make_mc2_index_view(indices) -> MC2IndexViewV1:
    array = _readonly_uint(indices, (len(indices),), "index view indices")
    return MC2IndexViewV1(kind="indices", indices=array)


@dataclass(frozen=True)
class MC2ConstraintTopologyTableV1:
    kind: str
    indices: np.ndarray
    owner_partition_index: np.ndarray
    flags: np.ndarray
    allow_cross_partition: bool = False

    def __post_init__(self) -> None:
        kind = _text(self.kind, "constraint kind").lower()
        width = _CONSTRAINT_WIDTHS.get(kind)
        if width is None:
            raise ValueError(f"unsupported constraint kind: {kind!r}")
        object.__setattr__(self, "kind", kind)
        if self.indices.ndim != 2 or self.indices.shape[1] != width:
            raise ValueError(f"{kind} indices must have shape [K,{width}]")
        _validate_array(self.indices, np.uint32, self.indices.shape, f"{kind} indices")
        count = len(self.indices)
        _validate_array(
            self.owner_partition_index,
            np.uint32,
            (count,),
            f"{kind} owner_partition_index",
        )
        _validate_array(self.flags, np.uint32, (count,), f"{kind} flags")
        if type(self.allow_cross_partition) is not bool:
            raise TypeError("allow_cross_partition must be bool")

    @property
    def record_count(self) -> int:
        return int(len(self.indices))

    def debug_dict(self) -> dict:
        return {
            "kind": self.kind,
            "record_count": self.record_count,
            "allow_cross_partition": self.allow_cross_partition,
        }


def make_mc2_constraint_topology_table(
    kind: str,
    indices,
    owner_partition_index,
    *,
    flags=None,
    allow_cross_partition: bool = False,
) -> MC2ConstraintTopologyTableV1:
    normalized_kind = _text(kind, "constraint kind").lower()
    width = _CONSTRAINT_WIDTHS.get(normalized_kind)
    if width is None:
        raise ValueError(f"unsupported constraint kind: {normalized_kind!r}")
    index_rows = tuple(tuple(int(item) for item in row) for row in indices)
    index_array = _readonly_uint(index_rows, (len(index_rows), width), f"{normalized_kind} indices")
    owners = _readonly_uint(
        tuple(int(item) for item in owner_partition_index),
        (len(index_rows),),
        f"{normalized_kind} owner_partition_index",
    )
    flag_values = (0,) * len(index_rows) if flags is None else tuple(int(item) for item in flags)
    flag_array = _readonly_uint(flag_values, (len(index_rows),), f"{normalized_kind} flags")
    return MC2ConstraintTopologyTableV1(
        kind=normalized_kind,
        indices=index_array,
        owner_partition_index=owners,
        flags=flag_array,
        allow_cross_partition=allow_cross_partition,
    )


@dataclass(frozen=True)
class MC2PrimitiveTopologyTableV1:
    kind: str
    indices: np.ndarray
    owner_partition_index: np.ndarray

    def __post_init__(self) -> None:
        kind = _text(self.kind, "primitive kind").lower()
        width = _PRIMITIVE_WIDTHS.get(kind)
        if width is None:
            raise ValueError(f"unsupported primitive kind: {kind!r}")
        object.__setattr__(self, "kind", kind)
        if self.indices.ndim != 2 or self.indices.shape[1] != width:
            raise ValueError(f"{kind} indices must have shape [K,{width}]")
        _validate_array(self.indices, np.uint32, self.indices.shape, f"{kind} indices")
        _validate_array(
            self.owner_partition_index,
            np.uint32,
            (len(self.indices),),
            f"{kind} owner_partition_index",
        )

    @property
    def primitive_count(self) -> int:
        return int(len(self.indices))

    def debug_dict(self) -> dict:
        return {"kind": self.kind, "primitive_count": self.primitive_count}


def make_mc2_primitive_topology_table(
    kind: str,
    indices,
    owner_partition_index,
) -> MC2PrimitiveTopologyTableV1:
    normalized_kind = _text(kind, "primitive kind").lower()
    width = _PRIMITIVE_WIDTHS.get(normalized_kind)
    if width is None:
        raise ValueError(f"unsupported primitive kind: {normalized_kind!r}")
    rows = tuple(tuple(int(item) for item in row) for row in indices)
    return MC2PrimitiveTopologyTableV1(
        kind=normalized_kind,
        indices=_readonly_uint(rows, (len(rows), width), f"{normalized_kind} indices"),
        owner_partition_index=_readonly_uint(
            tuple(int(item) for item in owner_partition_index),
            (len(rows),),
            f"{normalized_kind} owner_partition_index",
        ),
    )


@dataclass(frozen=True)
class MC2OutputTargetV1:
    target_id: str
    partition_index: int
    element_count: int
    space_kind: str = "mesh_object_local_offset"

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_id", _text(self.target_id, "output target id"))
        if self.partition_index < 0:
            raise ValueError("output target partition_index must be non-negative")
        if self.element_count < 0:
            raise ValueError("output target element_count must be non-negative")
        space_kind = _text(self.space_kind, "output target space_kind")
        if space_kind not in _OUTPUT_SPACE_KINDS:
            raise ValueError(f"unsupported output target space: {space_kind!r}")
        object.__setattr__(self, "space_kind", space_kind)

    def debug_dict(self) -> dict:
        return {
            "target_id": self.target_id,
            "partition_index": self.partition_index,
            "element_count": self.element_count,
            "space_kind": self.space_kind,
        }


@dataclass(frozen=True)
class MC2CompiledDomainProgramV1:
    """Immutable logical domain program, before backend physical layout."""

    domain_id: str
    setup_type: str
    partition_ids: tuple[str, ...]
    partition_flags: np.ndarray
    partition_particle_views: tuple[MC2IndexViewV1, ...]
    partition_center_local_position: np.ndarray
    partition_initial_local_gravity_direction: np.ndarray
    particle_partition_index: np.ndarray
    particle_source_element: np.ndarray
    particle_bind_position: np.ndarray
    particle_bind_rotation: np.ndarray
    particle_attribute_flags: np.ndarray
    constraint_tables: tuple[MC2ConstraintTopologyTableV1, ...]
    primitive_tables: tuple[MC2PrimitiveTopologyTableV1, ...]
    output_targets: tuple[MC2OutputTargetV1, ...]
    output_target_index: np.ndarray
    output_source_element: np.ndarray
    required_capabilities: tuple[str, ...] = ()
    schema_version: int = MC2_DOMAIN_IR_SCHEMA_VERSION
    domain_signature: str = field(init=False)
    layout_signature: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != MC2_DOMAIN_IR_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 domain IR schema version")
        domain_id = _text(self.domain_id, "domain_id")
        setup_type = _text(self.setup_type, "setup_type").lower()
        if setup_type not in _SETUP_TYPES:
            raise ValueError(f"unsupported MC2 setup_type: {setup_type!r}")
        object.__setattr__(self, "domain_id", domain_id)
        object.__setattr__(self, "setup_type", setup_type)
        partition_ids = _unique(self.partition_ids, "partition_ids")
        object.__setattr__(self, "partition_ids", partition_ids)
        partition_count = len(partition_ids)
        if partition_count == 0:
            raise ValueError("compiled domain must contain at least one partition")
        _validate_array(
            self.partition_flags,
            np.uint32,
            (partition_count,),
            "partition_flags",
        )
        if len(self.partition_particle_views) != partition_count:
            raise ValueError("partition_particle_views must match partition_ids")
        if any(not isinstance(view, MC2IndexViewV1) for view in self.partition_particle_views):
            raise TypeError("partition_particle_views must contain MC2IndexViewV1")
        _validate_array(
            self.partition_center_local_position,
            np.float32,
            (partition_count, 3),
            "partition_center_local_position",
        )
        _validate_array(
            self.partition_initial_local_gravity_direction,
            np.float32,
            (partition_count, 3),
            "partition_initial_local_gravity_direction",
        )
        if any(
            not isinstance(table, MC2ConstraintTopologyTableV1)
            for table in self.constraint_tables
        ):
            raise TypeError("constraint_tables must contain MC2ConstraintTopologyTableV1")
        if any(
            not isinstance(table, MC2PrimitiveTopologyTableV1)
            for table in self.primitive_tables
        ):
            raise TypeError("primitive_tables must contain MC2PrimitiveTopologyTableV1")
        if any(not isinstance(target, MC2OutputTargetV1) for target in self.output_targets):
            raise TypeError("output_targets must contain MC2OutputTargetV1")
        constraint_kinds = tuple(table.kind for table in self.constraint_tables)
        if len(set(constraint_kinds)) != len(constraint_kinds):
            raise ValueError("constraint table kinds must be unique")
        primitive_kinds = tuple(table.kind for table in self.primitive_tables)
        if len(set(primitive_kinds)) != len(primitive_kinds):
            raise ValueError("primitive table kinds must be unique")
        particle_count = len(self.particle_partition_index)
        _validate_array(
            self.particle_partition_index,
            np.uint32,
            (particle_count,),
            "particle_partition_index",
        )
        _validate_array(
            self.particle_source_element,
            np.uint32,
            (particle_count,),
            "particle_source_element",
        )
        _validate_array(
            self.particle_bind_position,
            np.float32,
            (particle_count, 3),
            "particle_bind_position",
        )
        _validate_array(
            self.particle_bind_rotation,
            np.float32,
            (particle_count, 4),
            "particle_bind_rotation",
        )
        _validate_array(
            self.particle_attribute_flags,
            np.uint32,
            (particle_count,),
            "particle_attribute_flags",
        )
        if particle_count == 0:
            raise ValueError("compiled domain must contain at least one particle")
        if np.any(self.particle_partition_index >= partition_count):
            raise ValueError("particle_partition_index contains unknown partition")
        logical_identities = tuple(zip(
            (int(value) for value in self.particle_partition_index),
            (int(value) for value in self.particle_source_element),
        ))
        if len(set(logical_identities)) != particle_count:
            raise ValueError("logical particle source identities must be unique")
        _unit_quaternion_check(self.particle_bind_rotation, "particle_bind_rotation")
        if len(self.output_target_index) != particle_count:
            raise ValueError("output_target_index must match particle count")
        _validate_array(
            self.output_target_index,
            np.uint32,
            (particle_count,),
            "output_target_index",
        )
        _validate_array(
            self.output_source_element,
            np.uint32,
            (particle_count,),
            "output_source_element",
        )
        if not self.output_targets:
            raise ValueError("compiled domain requires at least one output target")
        target_ids = tuple(target.target_id for target in self.output_targets)
        if len(set(target_ids)) != len(target_ids):
            raise ValueError("output target ids must be unique")
        if np.any(self.output_target_index >= len(self.output_targets)):
            raise ValueError("output_target_index contains unknown target")
        if any(
            target.partition_index >= partition_count
            for target in self.output_targets
        ):
            raise ValueError("output target references unknown partition")
        required_capabilities = _ordered_unique(
            self.required_capabilities, "required_capabilities"
        )
        object.__setattr__(self, "required_capabilities", required_capabilities)
        self._validate_views()
        self._validate_topology_tables()
        self._validate_output_map()
        layout_parts = self._signature_parts(include_values=False)
        domain_parts = self._signature_parts(include_values=True)
        object.__setattr__(self, "layout_signature", _digest(layout_parts))
        object.__setattr__(self, "domain_signature", _digest(domain_parts))

    @property
    def particle_count(self) -> int:
        return int(len(self.particle_partition_index))

    @property
    def partition_count(self) -> int:
        return len(self.partition_ids)

    def _validate_views(self) -> None:
        seen = np.zeros(self.particle_count, dtype=np.uint8)
        for partition_index, view in enumerate(self.partition_particle_views):
            indices = view.resolved_indices()
            if len(indices) and np.any(indices >= self.particle_count):
                raise ValueError("partition particle view contains out-of-range index")
            if len(indices) and np.any(seen[indices] != 0):
                raise ValueError("partition particle views overlap")
            seen[indices] = 1
            if len(indices) and np.any(
                self.particle_partition_index[indices] != partition_index
            ):
                raise ValueError("partition particle view disagrees with particle owner")
        if not np.all(seen == 1):
            raise ValueError("partition particle views must cover every particle once")

    def _validate_topology_tables(self) -> None:
        for table in self.constraint_tables:
            if not isinstance(table, MC2ConstraintTopologyTableV1):
                raise TypeError("constraint_tables must contain MC2ConstraintTopologyTableV1")
            if np.any(table.indices >= self.particle_count):
                raise ValueError(f"{table.kind} table contains out-of-range particle")
            if np.any(table.owner_partition_index >= self.partition_count):
                raise ValueError(f"{table.kind} table contains unknown owner partition")
            if not table.allow_cross_partition and table.record_count:
                endpoint_partitions = self.particle_partition_index[table.indices]
                if np.any(endpoint_partitions != table.owner_partition_index[:, None]):
                    raise ValueError(
                        f"{table.kind} table contains cross-partition structural record"
                    )
        for table in self.primitive_tables:
            if not isinstance(table, MC2PrimitiveTopologyTableV1):
                raise TypeError("primitive_tables must contain MC2PrimitiveTopologyTableV1")
            if np.any(table.indices >= self.particle_count):
                raise ValueError(f"{table.kind} primitive contains out-of-range particle")
            if np.any(table.owner_partition_index >= self.partition_count):
                raise ValueError(f"{table.kind} primitive contains unknown owner partition")
            if table.primitive_count:
                endpoint_partitions = self.particle_partition_index[table.indices]
                if np.any(endpoint_partitions != table.owner_partition_index[:, None]):
                    raise ValueError(
                        f"{table.kind} primitive contains cross-partition topology"
                    )

    def _validate_output_map(self) -> None:
        for particle_index, target_index in enumerate(self.output_target_index):
            target = self.output_targets[int(target_index)]
            if int(self.particle_partition_index[particle_index]) != target.partition_index:
                raise ValueError("output target partition disagrees with particle owner")
            if int(self.output_source_element[particle_index]) >= target.element_count:
                raise ValueError("output map source element is out of target range")
        for target_index, target in enumerate(self.output_targets):
            elements = self.output_source_element[self.output_target_index == target_index]
            if len(elements) != target.element_count:
                raise ValueError("output target element count is not fully mapped")
            if len(elements) and len(set(int(value) for value in elements)) != len(elements):
                raise ValueError("output target source elements must be unique")

    def _signature_parts(self, *, include_values: bool) -> tuple:
        parts = [
            self.schema_version,
            self.domain_id,
            self.setup_type,
            self.partition_ids,
            self.partition_flags,
            tuple(view.debug_dict() for view in self.partition_particle_views),
            self.particle_partition_index,
            self.particle_source_element,
            self.particle_attribute_flags,
            tuple(table.debug_dict() for table in self.constraint_tables),
            tuple(table.indices for table in self.constraint_tables),
            tuple(table.owner_partition_index for table in self.constraint_tables),
            tuple(table.flags for table in self.constraint_tables),
            tuple(table.allow_cross_partition for table in self.constraint_tables),
            tuple(table.debug_dict() for table in self.primitive_tables),
            tuple(table.indices for table in self.primitive_tables),
            tuple(table.owner_partition_index for table in self.primitive_tables),
            tuple(target.debug_dict() for target in self.output_targets),
            self.output_target_index,
            self.output_source_element,
            self.required_capabilities,
        ]
        if include_values:
            parts.extend((
                self.partition_center_local_position,
                self.partition_initial_local_gravity_direction,
                self.particle_bind_position,
                self.particle_bind_rotation,
            ))
        return tuple(parts)

    def debug_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "domain_id": self.domain_id,
            "setup_type": self.setup_type,
            "domain_signature": self.domain_signature,
            "layout_signature": self.layout_signature,
            "partition_count": self.partition_count,
            "particle_count": self.particle_count,
            "constraint_tables": [table.debug_dict() for table in self.constraint_tables],
            "primitive_tables": [table.debug_dict() for table in self.primitive_tables],
            "output_targets": [target.debug_dict() for target in self.output_targets],
            "required_capabilities": list(self.required_capabilities),
        }


def make_mc2_compiled_domain_program(
    *,
    domain_id: str,
    setup_type: str,
    partition_ids,
    partition_flags,
    partition_particle_views,
    partition_center_local_position,
    partition_initial_local_gravity_direction,
    particle_partition_index,
    particle_source_element,
    particle_bind_position,
    particle_bind_rotation,
    particle_attribute_flags,
    constraint_tables=(),
    primitive_tables=(),
    output_targets=(),
    output_target_index,
    output_source_element,
    required_capabilities=(),
) -> MC2CompiledDomainProgramV1:
    partition_ids = tuple(_text(value, "partition_id") for value in partition_ids)
    particle_count = len(particle_partition_index)
    return MC2CompiledDomainProgramV1(
        domain_id=domain_id,
        setup_type=setup_type,
        partition_ids=partition_ids,
        partition_flags=_readonly_uint(
            partition_flags, (len(partition_ids),), "partition_flags"
        ),
        partition_particle_views=tuple(partition_particle_views),
        partition_center_local_position=_readonly_float(
            partition_center_local_position,
            (len(partition_ids), 3),
            "partition_center_local_position",
        ),
        partition_initial_local_gravity_direction=_readonly_float(
            partition_initial_local_gravity_direction,
            (len(partition_ids), 3),
            "partition_initial_local_gravity_direction",
        ),
        particle_partition_index=_readonly_uint(
            particle_partition_index, (particle_count,), "particle_partition_index"
        ),
        particle_source_element=_readonly_uint(
            particle_source_element, (particle_count,), "particle_source_element"
        ),
        particle_bind_position=_readonly_float(
            particle_bind_position, (particle_count, 3), "particle_bind_position"
        ),
        particle_bind_rotation=_readonly_float(
            particle_bind_rotation, (particle_count, 4), "particle_bind_rotation"
        ),
        particle_attribute_flags=_readonly_uint(
            particle_attribute_flags, (particle_count,), "particle_attribute_flags"
        ),
        constraint_tables=tuple(constraint_tables),
        primitive_tables=tuple(primitive_tables),
        output_targets=tuple(output_targets),
        output_target_index=_readonly_uint(
            output_target_index, (particle_count,), "output_target_index"
        ),
        output_source_element=_readonly_uint(
            output_source_element, (particle_count,), "output_source_element"
        ),
        required_capabilities=tuple(required_capabilities),
    )


@dataclass(frozen=True)
class MC2FloatSoATableV1:
    name: str
    fields: tuple[str, ...]
    values: np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "SoA table name"))
        fields = _unique(self.fields, "SoA fields")
        object.__setattr__(self, "fields", fields)
        if self.values.ndim != 2 or self.values.shape[1] != len(fields):
            raise ValueError("SoA values shape must match fields")
        _validate_array(self.values, np.float32, self.values.shape, f"{self.name} values")

    @property
    def row_count(self) -> int:
        return int(self.values.shape[0])

    @property
    def field_count(self) -> int:
        return len(self.fields)

    def debug_dict(self) -> dict:
        return {
            "name": self.name,
            "fields": list(self.fields),
            "row_count": self.row_count,
            "field_count": self.field_count,
        }


def make_mc2_float_soa_table(name: str, fields, values) -> MC2FloatSoATableV1:
    field_tuple = tuple(_text(value, "SoA field") for value in fields)
    array = _readonly_float(values, (len(values), len(field_tuple)), f"{name} values")
    return MC2FloatSoATableV1(name=name, fields=field_tuple, values=array)


@dataclass(frozen=True)
class MC2UIntSoATableV1:
    name: str
    fields: tuple[str, ...]
    values: np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "SoA table name"))
        fields = _unique(self.fields, "SoA fields")
        object.__setattr__(self, "fields", fields)
        if self.values.ndim != 2 or self.values.shape[1] != len(fields):
            raise ValueError("SoA values shape must match fields")
        _validate_array(self.values, np.uint32, self.values.shape, f"{self.name} values")

    @property
    def row_count(self) -> int:
        return int(self.values.shape[0])

    @property
    def field_count(self) -> int:
        return len(self.fields)

    def debug_dict(self) -> dict:
        return {
            "name": self.name,
            "fields": list(self.fields),
            "row_count": self.row_count,
            "field_count": self.field_count,
        }


def make_mc2_uint_soa_table(name: str, fields, values) -> MC2UIntSoATableV1:
    field_tuple = tuple(_text(value, "SoA field") for value in fields)
    array = _readonly_uint(values, (len(values), len(field_tuple)), f"{name} values")
    return MC2UIntSoATableV1(name=name, fields=field_tuple, values=array)


@dataclass(frozen=True)
class MC2DomainParameterPacketV1:
    layout_signature: str
    domain_scalars: MC2FloatSoATableV1
    partition_parameters: MC2FloatSoATableV1
    partition_uint_parameters: MC2UIntSoATableV1
    particle_parameters: MC2FloatSoATableV1
    constraint_parameters: tuple[MC2FloatSoATableV1, ...]
    schema_version: int = MC2_DOMAIN_IR_SCHEMA_VERSION
    parameter_layout_signature: str = field(init=False)
    parameter_signature: str = field(init=False)

    def __post_init__(self) -> None:
        layout_signature = _text(self.layout_signature, "layout_signature")
        if self.schema_version != MC2_DOMAIN_IR_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 parameter schema version")
        for table in (
            self.domain_scalars,
            self.partition_parameters,
            self.particle_parameters,
        ):
            if not isinstance(table, MC2FloatSoATableV1):
                raise TypeError("parameter packet tables must be MC2FloatSoATableV1")
        if not isinstance(self.partition_uint_parameters, MC2UIntSoATableV1):
            raise TypeError(
                "partition_uint_parameters must be MC2UIntSoATableV1"
            )
        if self.domain_scalars.row_count != 1:
            raise ValueError("domain_scalars must contain exactly one row")
        if not isinstance(self.constraint_parameters, tuple) or any(
            not isinstance(table, MC2FloatSoATableV1)
            for table in self.constraint_parameters
        ):
            raise TypeError("constraint_parameters must contain SoA tables")
        object.__setattr__(self, "layout_signature", layout_signature)
        parameter_layout_signature = _digest((
            self.schema_version,
            self.layout_signature,
            self.domain_scalars.debug_dict(),
            self.partition_parameters.debug_dict(),
            self.partition_uint_parameters.debug_dict(),
            self.particle_parameters.debug_dict(),
            tuple(table.debug_dict() for table in self.constraint_parameters),
        ))
        object.__setattr__(
            self, "parameter_layout_signature", parameter_layout_signature
        )
        object.__setattr__(
            self,
            "parameter_signature",
            _digest((
                self.schema_version,
                self.layout_signature,
                self.parameter_layout_signature,
                self.domain_scalars.values,
                self.partition_parameters.values,
                self.partition_uint_parameters.values,
                self.particle_parameters.values,
                tuple(table.values for table in self.constraint_parameters),
            )),
        )

    def debug_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "layout_signature": self.layout_signature,
            "parameter_layout_signature": self.parameter_layout_signature,
            "parameter_signature": self.parameter_signature,
            "domain_scalars": self.domain_scalars.debug_dict(),
            "partition_parameters": self.partition_parameters.debug_dict(),
            "partition_uint_parameters": self.partition_uint_parameters.debug_dict(),
            "particle_parameters": self.particle_parameters.debug_dict(),
            "constraint_parameters": [
                table.debug_dict() for table in self.constraint_parameters
            ],
        }


def make_mc2_domain_parameter_packet(
    program: MC2CompiledDomainProgramV1,
    *,
    domain_scalars: MC2FloatSoATableV1,
    partition_parameters: MC2FloatSoATableV1,
    partition_uint_parameters: MC2UIntSoATableV1,
    particle_parameters: MC2FloatSoATableV1,
    constraint_parameters=(),
) -> MC2DomainParameterPacketV1:
    if not isinstance(program, MC2CompiledDomainProgramV1):
        raise TypeError("program must be MC2CompiledDomainProgramV1")
    if partition_parameters.row_count != program.partition_count:
        raise ValueError("partition parameter rows must match partition count")
    if partition_uint_parameters.row_count != program.partition_count:
        raise ValueError("partition uint parameter rows must match partition count")
    if particle_parameters.row_count != program.particle_count:
        raise ValueError("particle parameter rows must match particle count")
    expected_kinds = tuple(table.kind for table in program.constraint_tables)
    values = tuple(constraint_parameters)
    if len(values) != len(expected_kinds):
        raise ValueError("constraint parameter table count must match program")
    for table, kind, topology in zip(values, expected_kinds, program.constraint_tables):
        if table.name != kind:
            raise ValueError("constraint parameter table names must match topology kinds")
        if table.row_count != topology.record_count:
            raise ValueError(f"{kind} parameter rows must match topology records")
    return MC2DomainParameterPacketV1(
        layout_signature=program.layout_signature,
        domain_scalars=domain_scalars,
        partition_parameters=partition_parameters,
        partition_uint_parameters=partition_uint_parameters,
        particle_parameters=particle_parameters,
        constraint_parameters=values,
    )


def _unit_quaternion_check(values: np.ndarray, name: str) -> None:
    if len(values):
        lengths = np.linalg.norm(values, axis=1)
        if not np.allclose(lengths, 1.0, rtol=1.0e-5, atol=1.0e-6):
            raise ValueError(f"{name} must contain unit xyzw quaternions")


@dataclass(frozen=True)
class MC2DomainFramePacketV1:
    domain_signature: str
    layout_signature: str
    frame: int
    generation: int
    animated_base_world_positions: np.ndarray
    animated_base_world_normals: np.ndarray
    partition_world_position: np.ndarray
    partition_world_rotation: np.ndarray
    partition_world_scale: np.ndarray
    partition_world_linear: np.ndarray
    anchor_world_position: np.ndarray
    anchor_world_rotation: np.ndarray
    anchor_present: np.ndarray
    partition_frame_flags: np.ndarray
    velocity_weight: np.ndarray
    gravity_ratio: np.ndarray
    schema_version: int = MC2_DOMAIN_IR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "domain_signature", _text(self.domain_signature, "domain_signature")
        )
        object.__setattr__(
            self, "layout_signature", _text(self.layout_signature, "layout_signature")
        )
        if self.schema_version != MC2_DOMAIN_IR_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 frame schema version")
        particle_count = len(self.animated_base_world_positions)
        partition_count = len(self.partition_world_position)
        _validate_array(
            self.animated_base_world_positions,
            np.float32,
            (particle_count, 3),
            "animated_base_world_positions",
        )
        normal_shape = self.animated_base_world_normals.shape
        if normal_shape not in ((particle_count, 3), (0, 3)):
            raise ValueError(
                "animated_base_world_normals must have shape [N,3] or [0,3]"
            )
        _validate_array(
            self.animated_base_world_normals,
            np.float32,
            normal_shape,
            "animated_base_world_normals",
        )
        _validate_array(
            self.partition_world_position,
            np.float32,
            (partition_count, 3),
            "partition_world_position",
        )
        _validate_array(
            self.partition_world_rotation,
            np.float32,
            (partition_count, 4),
            "partition_world_rotation",
        )
        _validate_array(
            self.partition_world_scale,
            np.float32,
            (partition_count, 3),
            "partition_world_scale",
        )
        _validate_array(
            self.partition_world_linear,
            np.float32,
            (partition_count, 3, 3),
            "partition_world_linear",
        )
        _validate_array(
            self.anchor_world_position,
            np.float32,
            (partition_count, 3),
            "anchor_world_position",
        )
        _validate_array(
            self.anchor_world_rotation,
            np.float32,
            (partition_count, 4),
            "anchor_world_rotation",
        )
        _validate_array(
            self.anchor_present,
            np.uint32,
            (partition_count,),
            "anchor_present",
        )
        _validate_array(
            self.partition_frame_flags,
            np.uint32,
            (partition_count,),
            "partition_frame_flags",
        )
        reset_keep = MC2_PARTITION_FRAME_RESET | MC2_PARTITION_FRAME_KEEP
        if np.any((self.partition_frame_flags & reset_keep) == reset_keep):
            raise ValueError("partition frame cannot request Reset and Keep together")
        _validate_array(
            self.velocity_weight,
            np.float32,
            (partition_count,),
            "velocity_weight",
        )
        _validate_array(
            self.gravity_ratio,
            np.float32,
            (partition_count,),
            "gravity_ratio",
        )
        _unit_quaternion_check(self.partition_world_rotation, "partition_world_rotation")
        _unit_quaternion_check(self.anchor_world_rotation, "anchor_world_rotation")
        if np.any(np.abs(self.partition_world_scale) <= 1.0e-12):
            raise ValueError("partition_world_scale must be non-zero")
        determinants = np.linalg.det(self.partition_world_linear.astype(np.float64))
        if np.any(np.abs(determinants) <= 1.0e-12):
            raise ValueError("partition_world_linear must be invertible")
        if np.any(self.anchor_present > 1):
            raise ValueError("anchor_present must contain 0 or 1")
        for name, values in (
            ("velocity_weight", self.velocity_weight),
            ("gravity_ratio", self.gravity_ratio),
        ):
            if np.any(values < 0.0) or np.any(values > 1.0):
                raise ValueError(f"{name} must be in 0..1")
        if int(self.frame) < 0 or int(self.generation) < 0:
            raise ValueError("frame and generation must be non-negative")

    def debug_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "domain_signature": self.domain_signature,
            "layout_signature": self.layout_signature,
            "frame": int(self.frame),
            "generation": int(self.generation),
            "particle_count": len(self.animated_base_world_positions),
            "partition_count": len(self.partition_world_position),
        }


def make_mc2_domain_frame_packet(
    program: MC2CompiledDomainProgramV1,
    *,
    frame: int,
    generation: int,
    animated_base_world_positions,
    animated_base_world_normals=None,
    partition_world_position,
    partition_world_rotation,
    partition_world_scale,
    partition_world_linear,
    anchor_world_position=None,
    anchor_world_rotation=None,
    anchor_present=None,
    partition_frame_flags=None,
    velocity_weight=None,
    gravity_ratio=None,
) -> MC2DomainFramePacketV1:
    if not isinstance(program, MC2CompiledDomainProgramV1):
        raise TypeError("program must be MC2CompiledDomainProgramV1")
    particle_count = program.particle_count
    partition_count = program.partition_count
    identity_position = ((0.0, 0.0, 0.0),) * partition_count
    identity_rotation = ((0.0, 0.0, 0.0, 1.0),) * partition_count
    zero_flags = (0,) * partition_count
    ones = (1.0,) * partition_count
    return MC2DomainFramePacketV1(
        domain_signature=program.domain_signature,
        layout_signature=program.layout_signature,
        frame=int(frame),
        generation=int(generation),
        animated_base_world_positions=_readonly_float(
            animated_base_world_positions,
            (particle_count, 3),
            "animated_base_world_positions",
        ),
        animated_base_world_normals=_readonly_float(
            ()
            if animated_base_world_normals is None
            else animated_base_world_normals,
            (0, 3) if animated_base_world_normals is None else (particle_count, 3),
            "animated_base_world_normals",
        ),
        partition_world_position=_readonly_float(
            partition_world_position,
            (partition_count, 3),
            "partition_world_position",
        ),
        partition_world_rotation=_readonly_float(
            partition_world_rotation,
            (partition_count, 4),
            "partition_world_rotation",
        ),
        partition_world_scale=_readonly_float(
            partition_world_scale,
            (partition_count, 3),
            "partition_world_scale",
        ),
        partition_world_linear=_readonly_float(
            partition_world_linear,
            (partition_count, 3, 3),
            "partition_world_linear",
        ),
        anchor_world_position=_readonly_float(
            identity_position if anchor_world_position is None else anchor_world_position,
            (partition_count, 3),
            "anchor_world_position",
        ),
        anchor_world_rotation=_readonly_float(
            identity_rotation if anchor_world_rotation is None else anchor_world_rotation,
            (partition_count, 4),
            "anchor_world_rotation",
        ),
        anchor_present=_readonly_uint(
            zero_flags if anchor_present is None else anchor_present,
            (partition_count,),
            "anchor_present",
        ),
        partition_frame_flags=_readonly_uint(
            zero_flags if partition_frame_flags is None else partition_frame_flags,
            (partition_count,),
            "partition_frame_flags",
        ),
        velocity_weight=_readonly_float(
            ones if velocity_weight is None else velocity_weight,
            (partition_count,),
            "velocity_weight",
        ),
        gravity_ratio=_readonly_float(
            ones if gravity_ratio is None else gravity_ratio,
            (partition_count,),
            "gravity_ratio",
        ),
    )


@dataclass(frozen=True)
class MC2PhysicalIndexMapV1:
    """Backend-private logical/physical permutation, kept out of authoring specs."""

    logical_to_physical: np.ndarray
    physical_to_logical: np.ndarray

    def __post_init__(self) -> None:
        count = len(self.logical_to_physical)
        _validate_array(
            self.logical_to_physical,
            np.uint32,
            (count,),
            "logical_to_physical",
        )
        _validate_array(
            self.physical_to_logical,
            np.uint32,
            (count,),
            "physical_to_logical",
        )
        expected = np.arange(count, dtype=np.uint32)
        if not np.array_equal(np.sort(self.logical_to_physical), expected):
            raise ValueError("logical_to_physical must be a permutation")
        if not np.array_equal(np.sort(self.physical_to_logical), expected):
            raise ValueError("physical_to_logical must be a permutation")
        if not np.array_equal(
            self.logical_to_physical[self.physical_to_logical], expected
        ):
            raise ValueError("logical/physical index maps are not inverses")


def make_mc2_physical_index_map(physical_to_logical) -> MC2PhysicalIndexMapV1:
    physical = _readonly_uint(
        physical_to_logical,
        (len(physical_to_logical),),
        "physical_to_logical",
    )
    logical = np.empty_like(physical)
    logical[physical] = np.arange(len(physical), dtype=np.uint32)
    logical.setflags(write=False)
    return MC2PhysicalIndexMapV1(
        logical_to_physical=logical,
        physical_to_logical=physical,
    )


@dataclass(frozen=True)
class MC2DomainFrameOutputV1:
    domain_signature: str
    layout_signature: str
    frame: int
    generation: int
    world_positions: np.ndarray
    world_rotations_xyzw: np.ndarray
    validity_flags: int
    backend_revision: int
    backend_kind: str
    index_order: str = "logical"
    physical_to_logical: np.ndarray | None = None
    timing_token: str | None = None
    schema_version: int = MC2_DOMAIN_IR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "domain_signature", _text(self.domain_signature, "domain_signature")
        )
        object.__setattr__(
            self, "layout_signature", _text(self.layout_signature, "layout_signature")
        )
        if self.schema_version != MC2_DOMAIN_IR_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 output schema version")
        if self.index_order not in ("logical", "physical"):
            raise ValueError("index_order must be logical or physical")
        particle_count = len(self.world_positions)
        _validate_array(
            self.world_positions,
            np.float32,
            (particle_count, 3),
            "world_positions",
        )
        rotation_shape = self.world_rotations_xyzw.shape
        if rotation_shape not in ((particle_count, 4), (0, 4)):
            raise ValueError("world_rotations_xyzw must have shape [N,4] or [0,4]")
        _validate_array(
            self.world_rotations_xyzw,
            np.float32,
            rotation_shape,
            "world_rotations_xyzw",
        )
        _unit_quaternion_check(self.world_rotations_xyzw, "world_rotations_xyzw")
        if self.index_order == "logical" and self.physical_to_logical is not None:
            raise ValueError("logical output cannot contain physical index map")
        if self.index_order == "physical":
            if self.physical_to_logical is None:
                raise ValueError("physical output requires physical_to_logical")
            _validate_array(
                self.physical_to_logical,
                np.uint32,
                (particle_count,),
                "physical_to_logical",
            )
            if not np.array_equal(
                np.sort(self.physical_to_logical),
                np.arange(particle_count, dtype=np.uint32),
            ):
                raise ValueError("physical_to_logical must be a permutation")
        if int(self.backend_revision) <= 0:
            raise ValueError("backend_revision must be positive")
        object.__setattr__(
            self, "backend_kind", _text(self.backend_kind, "backend_kind")
        )
        if int(self.frame) < 0 or int(self.generation) < 0:
            raise ValueError("frame and generation must be non-negative")
        if self.timing_token is not None:
            object.__setattr__(self, "timing_token", _text(self.timing_token, "timing_token"))

    def debug_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "domain_signature": self.domain_signature,
            "layout_signature": self.layout_signature,
            "frame": int(self.frame),
            "generation": int(self.generation),
            "particle_count": len(self.world_positions),
            "validity_flags": int(self.validity_flags),
            "backend_revision": int(self.backend_revision),
            "backend_kind": self.backend_kind,
            "index_order": self.index_order,
            "has_timing_token": self.timing_token is not None,
        }


def make_mc2_domain_frame_output(
    program: MC2CompiledDomainProgramV1,
    frame_packet: MC2DomainFramePacketV1,
    *,
    world_positions,
    world_rotations_xyzw=None,
    validity_flags: int = 0,
    backend_revision: int,
    backend_kind: str,
    index_order: str = "logical",
    physical_to_logical=None,
    timing_token: str | None = None,
) -> MC2DomainFrameOutputV1:
    if not isinstance(program, MC2CompiledDomainProgramV1):
        raise TypeError("program must be MC2CompiledDomainProgramV1")
    if not isinstance(frame_packet, MC2DomainFramePacketV1):
        raise TypeError("frame_packet must be MC2DomainFramePacketV1")
    if frame_packet.domain_signature != program.domain_signature:
        raise ValueError("frame packet domain signature does not match program")
    rotations = () if world_rotations_xyzw is None else world_rotations_xyzw
    position_values = tuple(tuple(float(value) for value in row) for row in world_positions)
    rotation_values = tuple(tuple(float(value) for value in row) for row in rotations)
    physical_values = None
    if physical_to_logical is not None:
        physical_values = _readonly_uint(
            physical_to_logical,
            (program.particle_count,),
            "physical_to_logical",
        )
    return MC2DomainFrameOutputV1(
        domain_signature=program.domain_signature,
        layout_signature=program.layout_signature,
        frame=frame_packet.frame,
        generation=frame_packet.generation,
        world_positions=_readonly_float(
            position_values,
            (program.particle_count, 3),
            "world_positions",
        ),
        world_rotations_xyzw=_readonly_float(
            rotation_values,
            (0, 4) if world_rotations_xyzw is None else (program.particle_count, 4),
            "world_rotations_xyzw",
        ),
        validity_flags=int(validity_flags),
        backend_revision=int(backend_revision),
        backend_kind=backend_kind,
        index_order=index_order,
        physical_to_logical=physical_values,
        timing_token=timing_token,
    )


__all__ = [
    "MC2_DOMAIN_IR_SCHEMA_VERSION",
    "MC2_PARTITION_FRAME_DISABLED",
    "MC2_PARTITION_FRAME_KEEP",
    "MC2_PARTITION_FRAME_RESET",
    "MC2CompiledDomainProgramV1",
    "MC2ConstraintTopologyTableV1",
    "MC2DomainFrameOutputV1",
    "MC2DomainFramePacketV1",
    "MC2DomainParameterPacketV1",
    "MC2FloatSoATableV1",
    "MC2IndexViewV1",
    "MC2MeshPartitionStaticSnapshotV1",
    "MC2OutputTargetV1",
    "MC2PhysicalIndexMapV1",
    "MC2PrimitiveTopologyTableV1",
    "MC2UIntSoATableV1",
    "make_mc2_compiled_domain_program",
    "make_mc2_constraint_topology_table",
    "make_mc2_domain_frame_output",
    "make_mc2_domain_frame_packet",
    "make_mc2_domain_parameter_packet",
    "make_mc2_float_soa_table",
    "make_mc2_index_view",
    "make_mc2_mesh_partition_static_snapshot",
    "make_mc2_physical_index_map",
    "make_mc2_primitive_topology_table",
    "make_mc2_span_view",
    "make_mc2_uint_soa_table",
]
