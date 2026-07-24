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
MC2_BACKEND_CONTRACT_SCHEMA_VERSION = 1
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
    baseline_parent_indices: np.ndarray | None = None
    baseline_line_start: np.ndarray | None = None
    baseline_line_count: np.ndarray | None = None
    baseline_line_data: np.ndarray | None = None
    baseline_vertex_local_position: np.ndarray | None = None
    baseline_vertex_local_rotation: np.ndarray | None = None
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
        baseline_values = (
            self.baseline_parent_indices,
            self.baseline_line_start,
            self.baseline_line_count,
            self.baseline_line_data,
        )
        if any(value is not None for value in baseline_values):
            if any(value is None for value in baseline_values):
                raise ValueError("baseline line arrays must be provided as a complete group")
            parent = self.baseline_parent_indices
            starts = self.baseline_line_start
            counts = self.baseline_line_count
            data = self.baseline_line_data
            _validate_array(parent, np.int32, (particle_count,), "baseline_parent_indices")
            line_count = len(starts)
            _validate_array(starts, np.int32, (line_count,), "baseline_line_start")
            _validate_array(counts, np.int32, (line_count,), "baseline_line_count")
            _validate_array(data, np.int32, (len(data),), "baseline_line_data")
            if np.any(parent < -1) or np.any(parent >= particle_count):
                raise ValueError("baseline_parent_indices is out of range")
            if np.any(starts < 0) or np.any(counts < 0):
                raise ValueError("baseline line ranges cannot be negative")
            if np.any(starts.astype(np.int64) + counts.astype(np.int64) > len(data)):
                raise ValueError("baseline line range exceeds baseline_line_data")
            if len(data) and (np.any(data < 0) or np.any(data >= particle_count)):
                raise ValueError("baseline_line_data is out of range")
        baseline_pose_values = (
            self.baseline_vertex_local_position,
            self.baseline_vertex_local_rotation,
        )
        if any(value is not None for value in baseline_pose_values):
            if any(value is None for value in baseline_pose_values):
                raise ValueError(
                    "baseline vertex local pose arrays must be provided as a complete group"
                )
            _validate_array(
                self.baseline_vertex_local_position,
                np.float32,
                (particle_count, 3),
                "baseline_vertex_local_position",
            )
            _validate_array(
                self.baseline_vertex_local_rotation,
                np.float32,
                (particle_count, 4),
                "baseline_vertex_local_rotation",
            )
            if self.baseline_line_data is None:
                raise ValueError(
                    "baseline vertex local pose requires baseline line topology"
                )
            active = np.unique(self.baseline_line_data)
            if len(active):
                _unit_quaternion_check(
                    self.baseline_vertex_local_rotation[active],
                    "active baseline_vertex_local_rotation",
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
            self.baseline_parent_indices,
            self.baseline_line_start,
            self.baseline_line_count,
            self.baseline_line_data,
            self.baseline_vertex_local_position,
            self.baseline_vertex_local_rotation,
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
            "baseline_lines_ready": self.baseline_parent_indices is not None,
            "baseline_pose_ready": self.baseline_vertex_local_position is not None,
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
    baseline_parent_indices=None,
    baseline_line_start=None,
    baseline_line_count=None,
    baseline_line_data=None,
    baseline_vertex_local_position=None,
    baseline_vertex_local_rotation=None,
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
        baseline_parent_indices=(
            None if baseline_parent_indices is None else _readonly_array(
                baseline_parent_indices, np.int32, (particle_count,), "baseline_parent_indices"
            )
        ),
        baseline_line_start=(
            None if baseline_line_start is None else _readonly_array(
                baseline_line_start, np.int32, (len(baseline_line_start),), "baseline_line_start"
            )
        ),
        baseline_line_count=(
            None if baseline_line_count is None else _readonly_array(
                baseline_line_count, np.int32, (len(baseline_line_count),), "baseline_line_count"
            )
        ),
        baseline_line_data=(
            None if baseline_line_data is None else _readonly_array(
                baseline_line_data, np.int32, (len(baseline_line_data),), "baseline_line_data"
            )
        ),
        baseline_vertex_local_position=(
            None if baseline_vertex_local_position is None else _readonly_array(
                baseline_vertex_local_position,
                np.float32,
                (particle_count, 3),
                "baseline_vertex_local_position",
            )
        ),
        baseline_vertex_local_rotation=(
            None if baseline_vertex_local_rotation is None else _readonly_array(
                baseline_vertex_local_rotation,
                np.float32,
                (particle_count, 4),
                "baseline_vertex_local_rotation",
            )
        ),
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
    animated_base_world_rotations: np.ndarray
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
    frame_delta_time: float = 0.0
    simulation_delta_time: float = 0.0
    time_scale: float = 1.0
    skip_count: int = 0
    is_running: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "domain_signature", _text(self.domain_signature, "domain_signature")
        )
        object.__setattr__(
            self, "layout_signature", _text(self.layout_signature, "layout_signature")
        )
        if self.schema_version != MC2_DOMAIN_IR_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 frame schema version")
        for value, name, minimum in (
            (self.frame_delta_time, "frame_delta_time", 0.0),
            (self.simulation_delta_time, "simulation_delta_time", 0.0),
            (self.time_scale, "time_scale", 0.0),
        ):
            if not np.isfinite(float(value)) or float(value) < minimum:
                raise ValueError(f"{name} must be finite and non-negative")
        if isinstance(self.skip_count, bool) or int(self.skip_count) < 0:
            raise ValueError("skip_count must be a non-negative integer")
        if not isinstance(self.is_running, (bool, np.bool_)):
            raise TypeError("is_running must be boolean")
        particle_count = len(self.animated_base_world_positions)
        partition_count = len(self.partition_world_position)
        _validate_array(
            self.animated_base_world_positions,
            np.float32,
            (particle_count, 3),
            "animated_base_world_positions",
        )
        _validate_array(
            self.animated_base_world_rotations,
            np.float32,
            (particle_count, 4),
            "animated_base_world_rotations",
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
        _unit_quaternion_check(
            self.animated_base_world_rotations,
            "animated_base_world_rotations",
        )
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
            "frame_delta_time": float(self.frame_delta_time),
            "simulation_delta_time": float(self.simulation_delta_time),
            "time_scale": float(self.time_scale),
            "skip_count": int(self.skip_count),
            "is_running": bool(self.is_running),
        }


def make_mc2_domain_frame_packet(
    program: MC2CompiledDomainProgramV1,
    *,
    frame: int,
    generation: int,
    animated_base_world_positions,
    animated_base_world_rotations,
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
    frame_delta_time: float = 0.0,
    simulation_delta_time: float = 0.0,
    time_scale: float = 1.0,
    skip_count: int = 0,
    is_running: bool = False,
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
        animated_base_world_rotations=_readonly_float(
            animated_base_world_rotations,
            (particle_count, 4),
            "animated_base_world_rotations",
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
        frame_delta_time=float(frame_delta_time),
        simulation_delta_time=float(simulation_delta_time),
        time_scale=float(time_scale),
        skip_count=int(skip_count),
        is_running=bool(is_running),
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


_BACKEND_BUFFER_ROLES = frozenset((
    "static_topology",
    "static_value",
    "parameter",
    "frame",
    "state",
    "transient",
    "output",
    "debug",
))
_BACKEND_BUFFER_LIFETIMES = frozenset((
    "domain",
    "frame",
    "substep",
    "result",
    "request",
))
_BACKEND_TRANSFER_POLICIES = frozenset((
    "layout_rebuild",
    "domain_value_update",
    "parameter_dirty_span",
    "frame_dirty_span",
    "backend_owned",
    "single_result_readback",
    "request_only_readback",
))
_BACKEND_COUNT_SOURCES = frozenset((
    "fixed",
    "frame_collider_count",
    "candidate_count",
    "contact_count",
    "intersection_count",
    "debug_request",
))
_BACKEND_PASS_SCOPES = frozenset(("frame", "substep", "result"))


@dataclass(frozen=True)
class MC2BackendBufferSpecV1:
    """Concrete backend allocation and transfer requirement for one buffer."""

    name: str
    role: str
    dtype: str
    components: int
    logical_count: int
    hard_capacity: int | None
    count_source: str
    lifetime: str
    transfer_policy: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "buffer name"))
        if self.role not in _BACKEND_BUFFER_ROLES:
            raise ValueError(f"unsupported backend buffer role: {self.role!r}")
        if self.dtype not in ("float32", "uint32", "int32", "uint8"):
            raise ValueError(f"unsupported backend buffer dtype: {self.dtype!r}")
        if isinstance(self.components, bool) or int(self.components) <= 0:
            raise ValueError("buffer components must be a positive integer")
        if isinstance(self.logical_count, bool) or int(self.logical_count) < 0:
            raise ValueError("buffer logical_count must be a non-negative integer")
        if self.hard_capacity is not None and (
            isinstance(self.hard_capacity, bool)
            or int(self.hard_capacity) < int(self.logical_count)
        ):
            raise ValueError("buffer hard_capacity cannot be below logical_count")
        if self.count_source not in _BACKEND_COUNT_SOURCES:
            raise ValueError(f"unsupported backend count source: {self.count_source!r}")
        if self.count_source == "fixed" and self.hard_capacity != self.logical_count:
            raise ValueError("fixed backend buffers require exact hard_capacity")
        if self.lifetime not in _BACKEND_BUFFER_LIFETIMES:
            raise ValueError(f"unsupported backend buffer lifetime: {self.lifetime!r}")
        if self.transfer_policy not in _BACKEND_TRANSFER_POLICIES:
            raise ValueError(
                f"unsupported backend transfer policy: {self.transfer_policy!r}"
            )

    def debug_dict(self) -> dict:
        return {
            "name": self.name,
            "role": self.role,
            "dtype": self.dtype,
            "components": self.components,
            "logical_count": self.logical_count,
            "hard_capacity": self.hard_capacity,
            "count_source": self.count_source,
            "lifetime": self.lifetime,
            "transfer_policy": self.transfer_policy,
        }


@dataclass(frozen=True)
class MC2BackendPassSpecV1:
    """One ordered pass with explicit buffer hazards and activation condition."""

    name: str
    scope: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    depends_on: tuple[str, ...]
    condition: str = "always"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "pass name"))
        if self.scope not in _BACKEND_PASS_SCOPES:
            raise ValueError(f"unsupported backend pass scope: {self.scope!r}")
        object.__setattr__(self, "reads", _unique(self.reads, "pass reads"))
        object.__setattr__(self, "writes", _unique(self.writes, "pass writes"))
        object.__setattr__(
            self, "depends_on", _unique(self.depends_on, "pass dependencies")
        )
        object.__setattr__(self, "condition", _text(self.condition, "pass condition"))
    def debug_dict(self) -> dict:
        return {
            "name": self.name,
            "scope": self.scope,
            "reads": list(self.reads),
            "writes": list(self.writes),
            "depends_on": list(self.depends_on),
            "condition": self.condition,
        }


@dataclass(frozen=True)
class MC2BackendDataPassContractV1:
    """P6 data/pass contract; it allocates or executes no backend resources."""

    layout_signature: str
    buffers: tuple[MC2BackendBufferSpecV1, ...]
    passes: tuple[MC2BackendPassSpecV1, ...]
    schema_version: int = MC2_BACKEND_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MC2_BACKEND_CONTRACT_SCHEMA_VERSION:
            raise ValueError("unsupported MC2 backend contract schema version")
        object.__setattr__(
            self, "layout_signature", _text(self.layout_signature, "layout_signature")
        )
        if any(not isinstance(item, MC2BackendBufferSpecV1) for item in self.buffers):
            raise TypeError("buffers must contain MC2BackendBufferSpecV1")
        if any(not isinstance(item, MC2BackendPassSpecV1) for item in self.passes):
            raise TypeError("passes must contain MC2BackendPassSpecV1")
        buffer_names = tuple(item.name for item in self.buffers)
        pass_names = tuple(item.name for item in self.passes)
        if len(set(buffer_names)) != len(buffer_names):
            raise ValueError("backend buffer names must be unique")
        if len(set(pass_names)) != len(pass_names):
            raise ValueError("backend pass names must be unique")
        known_buffers = set(buffer_names)
        known_passes: set[str] = set()
        for item in self.passes:
            unknown_buffers = (set(item.reads) | set(item.writes)) - known_buffers
            if unknown_buffers:
                raise ValueError(
                    f"backend pass {item.name!r} references unknown buffers: "
                    + ", ".join(sorted(unknown_buffers))
                )
            unknown_dependencies = set(item.depends_on) - known_passes
            if unknown_dependencies:
                raise ValueError(
                    f"backend pass {item.name!r} has forward/unknown dependencies: "
                    + ", ".join(sorted(unknown_dependencies))
                )
            known_passes.add(item.name)

    def buffer(self, name: str) -> MC2BackendBufferSpecV1:
        for item in self.buffers:
            if item.name == name:
                return item
        raise KeyError(name)

    def debug_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "layout_signature": self.layout_signature,
            "buffers": [item.debug_dict() for item in self.buffers],
            "passes": [item.debug_dict() for item in self.passes],
        }


@dataclass(frozen=True)
class MC2BackendDirtySpanV1:
    """One half-open contiguous row range uploaded as a unit."""

    buffer_name: str
    start: int
    stop: int
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "buffer_name", _text(self.buffer_name, "dirty buffer name")
        )
        if (
            isinstance(self.start, bool)
            or isinstance(self.stop, bool)
            or int(self.start) < 0
            or int(self.stop) <= int(self.start)
        ):
            raise ValueError("dirty span must be a non-empty half-open row range")
        object.__setattr__(self, "reason", _text(self.reason, "dirty span reason"))

    def debug_dict(self) -> dict:
        return {
            "buffer_name": self.buffer_name,
            "start": int(self.start),
            "stop": int(self.stop),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MC2BackendUploadPlanV1:
    """P6 host-to-backend transfer plan; it performs no transfer itself."""

    layout_signature: str
    layout_rebuild: bool
    parameter_rebuild: bool
    reallocate_buffers: tuple[str, ...]
    program_spans: tuple[MC2BackendDirtySpanV1, ...]
    parameter_spans: tuple[MC2BackendDirtySpanV1, ...]
    frame_spans: tuple[MC2BackendDirtySpanV1, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "layout_signature", _text(self.layout_signature, "layout_signature")
        )
        if type(self.layout_rebuild) is not bool or type(self.parameter_rebuild) is not bool:
            raise TypeError("upload rebuild flags must be bool")
        object.__setattr__(
            self,
            "reallocate_buffers",
            _unique(self.reallocate_buffers, "reallocate_buffers"),
        )
        spans = self.program_spans + self.parameter_spans + self.frame_spans
        if any(not isinstance(item, MC2BackendDirtySpanV1) for item in spans):
            raise TypeError("upload spans must contain MC2BackendDirtySpanV1")
        by_buffer: dict[str, list[MC2BackendDirtySpanV1]] = {}
        for item in spans:
            by_buffer.setdefault(item.buffer_name, []).append(item)
        for name, items in by_buffer.items():
            ordered = sorted(items, key=lambda item: item.start)
            if any(left.stop > right.start for left, right in zip(ordered, ordered[1:])):
                raise ValueError(f"upload spans overlap for {name!r}")

    def debug_dict(self) -> dict:
        return {
            "layout_signature": self.layout_signature,
            "layout_rebuild": self.layout_rebuild,
            "parameter_rebuild": self.parameter_rebuild,
            "reallocate_buffers": list(self.reallocate_buffers),
            "program_spans": [item.debug_dict() for item in self.program_spans],
            "parameter_spans": [item.debug_dict() for item in self.parameter_spans],
            "frame_spans": [item.debug_dict() for item in self.frame_spans],
        }


@dataclass(frozen=True)
class MC2BackendDynamicCapacityPolicyV1:
    """Two-phase count/grow/emit transaction for one generated buffer."""

    buffer_name: str
    count_phase: str
    emit_phase: str
    hard_capacity: int
    growth_policy: str = "next_power_of_two_capped_by_hard_capacity"
    overflow_policy: str = "rollback_substep_and_fail_without_publish"
    publishes_state_before_capacity_fit: bool = False
    retry_limit: int = 1
    required_statistics: tuple[str, ...] = (
        "capacity",
        "emitted_count",
        "grow_count",
        "overflow_count",
        "required_count",
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "buffer_name", _text(self.buffer_name, "capacity buffer name")
        )
        object.__setattr__(self, "count_phase", _text(self.count_phase, "count phase"))
        object.__setattr__(self, "emit_phase", _text(self.emit_phase, "emit phase"))
        if isinstance(self.hard_capacity, bool) or int(self.hard_capacity) < 0:
            raise ValueError("dynamic hard_capacity must be non-negative")
        if self.growth_policy != "next_power_of_two_capped_by_hard_capacity":
            raise ValueError("unsupported dynamic capacity growth policy")
        if self.overflow_policy != "rollback_substep_and_fail_without_publish":
            raise ValueError("dynamic overflow must roll back and fail without publishing")
        if type(self.publishes_state_before_capacity_fit) is not bool:
            raise TypeError("publishes_state_before_capacity_fit must be bool")
        if self.publishes_state_before_capacity_fit:
            raise ValueError("dynamic capacity must fit before staged state is published")
        if self.retry_limit != 1:
            raise ValueError("dynamic capacity emit may retry exactly once after growth")
        object.__setattr__(
            self,
            "required_statistics",
            _ordered_unique(self.required_statistics, "required_statistics"),
        )

    def debug_dict(self) -> dict:
        return {
            "buffer_name": self.buffer_name,
            "count_phase": self.count_phase,
            "emit_phase": self.emit_phase,
            "hard_capacity": int(self.hard_capacity),
            "growth_policy": self.growth_policy,
            "overflow_policy": self.overflow_policy,
            "publishes_state_before_capacity_fit": self.publishes_state_before_capacity_fit,
            "retry_limit": self.retry_limit,
            "required_statistics": list(self.required_statistics),
        }


@dataclass(frozen=True)
class MC2BackendIOContractV1:
    host_inputs: tuple[str, ...]
    host_outputs: tuple[str, ...]
    result_readback_phase: str
    publish_policy: str
    debug_readback_policy: str
    substep_result_readback: bool
    backend_may_access_blender: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "host_inputs", _ordered_unique(self.host_inputs, "host_inputs"))
        object.__setattr__(self, "host_outputs", _ordered_unique(self.host_outputs, "host_outputs"))
        if self.result_readback_phase != "once_after_final_substep":
            raise ValueError("result readback must occur once after the final substep")
        if self.publish_policy != "validate_all_targets_then_atomic_publish":
            raise ValueError("backend output must use atomic multi-target publish")
        if self.debug_readback_policy != "explicit_request_after_production_pass":
            raise ValueError("debug readback must remain request-driven")
        if type(self.substep_result_readback) is not bool or self.substep_result_readback:
            raise ValueError("substep result readback is forbidden")
        if type(self.backend_may_access_blender) is not bool or self.backend_may_access_blender:
            raise ValueError("backend code cannot access Blender/RNA")


@dataclass(frozen=True)
class MC2BackendNumericalPolicyV1:
    exact_channels: tuple[str, ...]
    position_atol: float
    position_rtol: float
    rotation_component_atol: float
    rotation_component_rtol: float
    velocity_atol: float
    velocity_rtol: float
    finite_required: bool
    tolerance_source: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "exact_channels", _ordered_unique(self.exact_channels, "exact_channels")
        )
        for name in (
            "position_atol",
            "position_rtol",
            "rotation_component_atol",
            "rotation_component_rtol",
            "velocity_atol",
            "velocity_rtol",
        ):
            value = float(getattr(self, name))
            if not np.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if type(self.finite_required) is not bool or not self.finite_required:
            raise ValueError("backend numerical outputs must remain finite")
        if self.tolerance_source != "shared_cpu_reference_fixture_per_pass_with_global_caps":
            raise ValueError("unsupported backend tolerance source")


MC2_BACKEND_IO_CONTRACT_V1 = MC2BackendIOContractV1(
    host_inputs=(
        "compiled_program",
        "domain_parameters",
        "frame_collider_packet",
        "frame_packet",
    ),
    host_outputs=(
        "logical_domain_output",
        "optional_requested_debug_snapshot",
    ),
    result_readback_phase="once_after_final_substep",
    publish_policy="validate_all_targets_then_atomic_publish",
    debug_readback_policy="explicit_request_after_production_pass",
    substep_result_readback=False,
    backend_may_access_blender=False,
)

MC2_BACKEND_NUMERICAL_POLICY_V1 = MC2BackendNumericalPolicyV1(
    exact_channels=(
        "candidate_contact_counts",
        "candidate_contact_keys",
        "collision_filter_decisions",
        "domain_partition_output_identity",
        "frame_generation",
        "topology_indices",
        "validity_and_teleport_flags",
    ),
    position_atol=5.0e-4,
    position_rtol=5.0e-4,
    rotation_component_atol=5.0e-4,
    rotation_component_rtol=5.0e-4,
    velocity_atol=2.0e-3,
    velocity_rtol=5.0e-3,
    finite_required=True,
    tolerance_source="shared_cpu_reference_fixture_per_pass_with_global_caps",
)


def _backend_array_spec(
    name: str,
    role: str,
    values: np.ndarray,
    *,
    lifetime: str,
    transfer_policy: str,
) -> MC2BackendBufferSpecV1:
    array = np.asarray(values)
    if array.ndim == 0:
        logical_count, components = 1, 1
    else:
        logical_count = int(array.shape[0])
        components = int(np.prod(array.shape[1:], dtype=np.int64)) or 1
    return MC2BackendBufferSpecV1(
        name=name,
        role=role,
        dtype=str(array.dtype),
        components=components,
        logical_count=logical_count,
        hard_capacity=logical_count,
        count_source="fixed",
        lifetime=lifetime,
        transfer_policy=transfer_policy,
    )


def make_mc2_backend_data_pass_contract(
    program: MC2CompiledDomainProgramV1,
    parameters: MC2DomainParameterPacketV1,
) -> MC2BackendDataPassContractV1:
    """Build the concrete P6 allocation/pass manifest for one compiled layout."""

    if not isinstance(program, MC2CompiledDomainProgramV1):
        raise TypeError("program must be MC2CompiledDomainProgramV1")
    if not isinstance(parameters, MC2DomainParameterPacketV1):
        raise TypeError("parameters must be MC2DomainParameterPacketV1")
    if parameters.layout_signature != program.layout_signature:
        raise ValueError("parameter packet layout does not match program")

    buffers: list[MC2BackendBufferSpecV1] = []
    add = buffers.append
    for name, role, values, policy in (
        ("program.partition_flags", "static_topology", program.partition_flags, "layout_rebuild"),
        ("program.partition_center_local_position", "static_value", program.partition_center_local_position, "domain_value_update"),
        ("program.partition_initial_local_gravity_direction", "static_value", program.partition_initial_local_gravity_direction, "domain_value_update"),
        ("program.particle_partition_index", "static_topology", program.particle_partition_index, "layout_rebuild"),
        ("program.particle_source_element", "static_topology", program.particle_source_element, "layout_rebuild"),
        ("program.particle_bind_position", "static_value", program.particle_bind_position, "domain_value_update"),
        ("program.particle_bind_rotation", "static_value", program.particle_bind_rotation, "domain_value_update"),
        ("program.particle_attribute_flags", "static_topology", program.particle_attribute_flags, "layout_rebuild"),
        ("program.output_target_index", "static_topology", program.output_target_index, "layout_rebuild"),
        ("program.output_source_element", "static_topology", program.output_source_element, "layout_rebuild"),
    ):
        add(_backend_array_spec(name, role, values, lifetime="domain", transfer_policy=policy))
    particle_indices = np.concatenate(tuple(
        view.resolved_indices() for view in program.partition_particle_views
    )).astype(np.uint32, copy=False)
    add(_backend_array_spec(
        "program.partition_particle_indices",
        "static_topology",
        particle_indices,
        lifetime="domain",
        transfer_policy="layout_rebuild",
    ))
    for table in program.constraint_tables:
        for suffix, values in (
            ("indices", table.indices),
            ("owner_partition_index", table.owner_partition_index),
            ("flags", table.flags),
        ):
            add(_backend_array_spec(
                f"program.constraint.{table.kind}.{suffix}",
                "static_topology",
                values,
                lifetime="domain",
                transfer_policy="layout_rebuild",
            ))
    for table in program.primitive_tables:
        for suffix, values in (
            ("indices", table.indices),
            ("owner_partition_index", table.owner_partition_index),
        ):
            add(_backend_array_spec(
                f"program.primitive.{table.kind}.{suffix}",
                "static_topology",
                values,
                lifetime="domain",
                transfer_policy="layout_rebuild",
            ))
    for name in (
        "baseline_parent_indices",
        "baseline_line_start",
        "baseline_line_count",
        "baseline_line_data",
        "baseline_vertex_local_position",
        "baseline_vertex_local_rotation",
    ):
        values = getattr(program, name)
        if values is not None:
            add(_backend_array_spec(
                f"program.{name}",
                "static_topology" if "position" not in name and "rotation" not in name else "static_value",
                values,
                lifetime="domain",
                transfer_policy="layout_rebuild" if "position" not in name and "rotation" not in name else "domain_value_update",
            ))
    parameter_tables = (
        parameters.domain_scalars,
        parameters.partition_parameters,
        parameters.partition_uint_parameters,
        parameters.particle_parameters,
        *parameters.constraint_parameters,
    )
    for table in parameter_tables:
        if table.values.shape[1] == 0:
            continue
        add(_backend_array_spec(
            f"parameter.{table.name}",
            "parameter",
            table.values,
            lifetime="domain",
            transfer_policy="parameter_dirty_span",
        ))

    particle_count = program.particle_count
    partition_count = program.partition_count
    for name, dtype, components, count in (
        ("frame.animated_base_position", "float32", 3, particle_count),
        ("frame.animated_base_rotation", "float32", 4, particle_count),
        ("frame.animated_base_normal", "float32", 3, particle_count),
        ("frame.partition_position", "float32", 3, partition_count),
        ("frame.partition_rotation", "float32", 4, partition_count),
        ("frame.partition_scale", "float32", 3, partition_count),
        ("frame.partition_linear", "float32", 9, partition_count),
        ("frame.anchor_position", "float32", 3, partition_count),
        ("frame.anchor_rotation", "float32", 4, partition_count),
        ("frame.anchor_present", "uint32", 1, partition_count),
        ("frame.partition_flags", "uint32", 1, partition_count),
        ("frame.velocity_weight", "float32", 1, partition_count),
        ("frame.gravity_ratio", "float32", 1, partition_count),
    ):
        add(MC2BackendBufferSpecV1(
            name, "frame", dtype, components, count, count, "fixed", "frame",
            "frame_dirty_span",
        ))
    for name, dtype, components in (
        ("frame.collider_type", "int32", 1),
        ("frame.collider_group_bit", "int32", 1),
        ("frame.collider_center", "float32", 3),
        ("frame.collider_segment_a", "float32", 3),
        ("frame.collider_segment_b", "float32", 3),
        ("frame.collider_old_center", "float32", 3),
        ("frame.collider_old_segment_a", "float32", 3),
        ("frame.collider_old_segment_b", "float32", 3),
        ("frame.collider_radius", "float32", 1),
    ):
        add(MC2BackendBufferSpecV1(
            name, "frame", dtype, components, 0, None,
            "frame_collider_count", "frame", "frame_dirty_span",
        ))
    for name, components, count in (
        ("state.world_position", 3, particle_count),
        ("state.world_rotation", 4, particle_count),
        ("state.world_normal", 3, particle_count),
        ("state.velocity_reference_position", 3, particle_count),
        ("state.velocity", 3, particle_count),
        ("state.real_velocity", 3, particle_count),
        ("state.static_friction", 1, particle_count),
        ("state.partition_previous_position", 3, partition_count),
        ("state.partition_previous_rotation", 4, partition_count),
        ("state.anchor_previous_position", 3, partition_count),
        ("state.anchor_previous_rotation", 4, partition_count),
        ("state.center_old_position", 3, partition_count),
        ("state.center_old_rotation", 4, partition_count),
        ("state.center_previous_frame_position", 3, partition_count),
        ("state.center_previous_frame_rotation", 4, partition_count),
        ("state.center_smoothing_velocity", 3, partition_count),
        ("state.center_velocity_weight", 1, partition_count),
        ("transient.step_basic_position", 3, particle_count),
        ("transient.step_basic_rotation", 4, particle_count),
    ):
        add(MC2BackendBufferSpecV1(
            name,
            "state" if name.startswith("state.") else "transient",
            "float32",
            components,
            count,
            count,
            "fixed",
            "domain" if name.startswith("state.") else "substep",
            "backend_owned",
        ))

    primitive_counts = {
        kind: next(
            (table.primitive_count for table in program.primitive_tables if table.kind == kind),
            0,
        )
        for kind in _PRIMITIVE_WIDTHS
    }
    candidate_limit = (
        primitive_counts["edge"] * max(primitive_counts["edge"] - 1, 0) // 2
        + primitive_counts["point"] * primitive_counts["triangle"]
    )
    intersection_limit = primitive_counts["edge"] * primitive_counts["triangle"]
    if max(candidate_limit, intersection_limit) > 0x7FFFFFFF:
        raise OverflowError("MC2 self buffer bound exceeds signed 31-bit primitive keys")
    for name, role, dtype, components, source, limit, lifetime, transfer in (
        ("transient.self_candidates", "transient", "int32", 3, "candidate_count", candidate_limit, "substep", "backend_owned"),
        ("transient.self_contacts", "transient", "float32", 12, "contact_count", candidate_limit, "substep", "backend_owned"),
        ("debug.self_intersections", "debug", "int32", 5, "intersection_count", intersection_limit, "request", "request_only_readback"),
        ("debug.pass_records", "debug", "float32", 16, "debug_request", None, "request", "request_only_readback"),
    ):
        add(MC2BackendBufferSpecV1(
            name, role, dtype, components, 0, limit, source, lifetime, transfer
        ))
    for name, dtype, components, count in (
        ("output.logical_world_position", "float32", 3, particle_count),
        ("output.logical_world_rotation", "float32", 4, particle_count),
        ("output.validity", "uint32", 1, 1),
    ):
        add(MC2BackendBufferSpecV1(
            name,
            "output",
            dtype,
            components,
            count,
            count,
            "fixed",
            "result",
            "single_result_readback",
        ))

    topology = tuple(
        item.name for item in buffers if item.role in ("static_topology", "static_value")
    )
    parameter_names = tuple(item.name for item in buffers if item.role == "parameter")
    frame_names = tuple(item.name for item in buffers if item.role == "frame")
    state = tuple(item.name for item in buffers if item.role == "state")
    step_basic = (
        "transient.step_basic_position",
        "transient.step_basic_rotation",
    )
    passes = (
        MC2BackendPassSpecV1("prepare_step_basic", "substep", topology + parameter_names + frame_names + state, step_basic, ()),
        MC2BackendPassSpecV1("task_reference_teleport", "substep", frame_names + state, state, ("prepare_step_basic",)),
        MC2BackendPassSpecV1("center_frame_shift", "substep", frame_names + parameter_names + state, state, ("task_reference_teleport",)),
        MC2BackendPassSpecV1("center", "substep", frame_names + parameter_names + state, state, ("center_frame_shift",)),
        MC2BackendPassSpecV1("center_inertia", "substep", parameter_names + state, state, ("center",)),
        MC2BackendPassSpecV1("integration", "substep", parameter_names + frame_names + state, state, ("center_inertia",)),
        MC2BackendPassSpecV1("tether", "substep", topology + parameter_names + step_basic + state, state, ("integration",), "constraint:tether"),
        MC2BackendPassSpecV1("distance_a", "substep", topology + parameter_names + state, state, ("tether",), "constraint:distance"),
        MC2BackendPassSpecV1("angle", "substep", topology + parameter_names + step_basic + state, state, ("distance_a",), "baseline:angle"),
        MC2BackendPassSpecV1("bending", "substep", topology + parameter_names + state, state, ("angle",), "constraint:bending"),
        MC2BackendPassSpecV1("external_collision", "substep", parameter_names + frame_names + state, state, ("bending",)),
        MC2BackendPassSpecV1("distance_b", "substep", topology + parameter_names + state, state, ("external_collision",), "constraint:distance"),
        MC2BackendPassSpecV1("motion", "substep", topology + parameter_names + frame_names + step_basic + state, state, ("distance_b",)),
        MC2BackendPassSpecV1("whole_domain_self", "substep", topology + parameter_names + state, state + ("transient.self_candidates", "transient.self_contacts"), ("motion",), "capability:self_collision"),
        MC2BackendPassSpecV1("post_history", "substep", parameter_names + state, state, ("whole_domain_self",)),
        MC2BackendPassSpecV1("publish_output", "result", state, ("output.logical_world_position", "output.logical_world_rotation", "output.validity"), ("post_history",)),
    )
    return MC2BackendDataPassContractV1(
        layout_signature=program.layout_signature,
        buffers=tuple(buffers),
        passes=passes,
    )


def _backend_program_arrays(program: MC2CompiledDomainProgramV1) -> dict[str, np.ndarray]:
    result = {
        "program.partition_flags": program.partition_flags,
        "program.partition_center_local_position": program.partition_center_local_position,
        "program.partition_initial_local_gravity_direction": (
            program.partition_initial_local_gravity_direction
        ),
        "program.particle_partition_index": program.particle_partition_index,
        "program.particle_source_element": program.particle_source_element,
        "program.particle_bind_position": program.particle_bind_position,
        "program.particle_bind_rotation": program.particle_bind_rotation,
        "program.particle_attribute_flags": program.particle_attribute_flags,
        "program.output_target_index": program.output_target_index,
        "program.output_source_element": program.output_source_element,
        "program.partition_particle_indices": np.concatenate(tuple(
            view.resolved_indices() for view in program.partition_particle_views
        )).astype(np.uint32, copy=False),
    }
    for table in program.constraint_tables:
        result[f"program.constraint.{table.kind}.indices"] = table.indices
        result[f"program.constraint.{table.kind}.owner_partition_index"] = (
            table.owner_partition_index
        )
        result[f"program.constraint.{table.kind}.flags"] = table.flags
    for table in program.primitive_tables:
        result[f"program.primitive.{table.kind}.indices"] = table.indices
        result[f"program.primitive.{table.kind}.owner_partition_index"] = (
            table.owner_partition_index
        )
    for name in (
        "baseline_parent_indices",
        "baseline_line_start",
        "baseline_line_count",
        "baseline_line_data",
        "baseline_vertex_local_position",
        "baseline_vertex_local_rotation",
    ):
        values = getattr(program, name)
        if values is not None:
            result[f"program.{name}"] = values
    return result


def _backend_parameter_arrays(
    parameters: MC2DomainParameterPacketV1,
) -> dict[str, np.ndarray]:
    tables = (
        parameters.domain_scalars,
        parameters.partition_parameters,
        parameters.partition_uint_parameters,
        parameters.particle_parameters,
        *parameters.constraint_parameters,
    )
    return {
        f"parameter.{table.name}": table.values
        for table in tables
        if table.values.shape[1] > 0
    }


def _backend_frame_arrays(
    frame_packet: MC2DomainFramePacketV1,
    collider_arrays: dict[str, object] | None,
) -> dict[str, np.ndarray]:
    result = {
        "frame.animated_base_position": frame_packet.animated_base_world_positions,
        "frame.animated_base_rotation": frame_packet.animated_base_world_rotations,
        "frame.animated_base_normal": frame_packet.animated_base_world_normals,
        "frame.partition_position": frame_packet.partition_world_position,
        "frame.partition_rotation": frame_packet.partition_world_rotation,
        "frame.partition_scale": frame_packet.partition_world_scale,
        "frame.partition_linear": frame_packet.partition_world_linear,
        "frame.anchor_position": frame_packet.anchor_world_position,
        "frame.anchor_rotation": frame_packet.anchor_world_rotation,
        "frame.anchor_present": frame_packet.anchor_present,
        "frame.partition_flags": frame_packet.partition_frame_flags,
        "frame.velocity_weight": frame_packet.velocity_weight,
        "frame.gravity_ratio": frame_packet.gravity_ratio,
    }
    if collider_arrays is None:
        collider_arrays = {
            "collider_types": np.empty((0,), dtype=np.int32),
            "collider_group_bits": np.empty((0,), dtype=np.int32),
            "collider_centers": np.empty((0, 3), dtype=np.float32),
            "collider_segment_a": np.empty((0, 3), dtype=np.float32),
            "collider_segment_b": np.empty((0, 3), dtype=np.float32),
            "collider_old_centers": np.empty((0, 3), dtype=np.float32),
            "collider_old_segment_a": np.empty((0, 3), dtype=np.float32),
            "collider_old_segment_b": np.empty((0, 3), dtype=np.float32),
            "collider_radii": np.empty((0,), dtype=np.float32),
        }
    if not isinstance(collider_arrays, dict):
        raise TypeError("collider_arrays must be a dict or None")
    collider_names = {
        "collider_types": "frame.collider_type",
        "collider_group_bits": "frame.collider_group_bit",
        "collider_centers": "frame.collider_center",
        "collider_segment_a": "frame.collider_segment_a",
        "collider_segment_b": "frame.collider_segment_b",
        "collider_old_centers": "frame.collider_old_center",
        "collider_old_segment_a": "frame.collider_old_segment_a",
        "collider_old_segment_b": "frame.collider_old_segment_b",
        "collider_radii": "frame.collider_radius",
    }
    if set(collider_arrays) != set(collider_names):
        raise ValueError("collider_arrays must contain the complete native collider table")
    counts = set()
    for source_name, buffer_name in collider_names.items():
        array = np.asarray(collider_arrays[source_name])
        if array.ndim == 0:
            raise ValueError(f"{source_name} must contain collider rows")
        counts.add(int(array.shape[0]))
        result[buffer_name] = array
    if len(counts) != 1:
        raise ValueError("collider arrays must share one row count")
    return result


def _backend_dirty_spans(
    buffer_name: str,
    previous: np.ndarray | None,
    current: np.ndarray,
    reason: str,
) -> tuple[MC2BackendDirtySpanV1, ...]:
    current = np.asarray(current)
    row_count = int(current.shape[0]) if current.ndim else 1
    if row_count == 0:
        return ()
    if previous is None:
        return (MC2BackendDirtySpanV1(buffer_name, 0, row_count, reason),)
    previous = np.asarray(previous)
    if previous.dtype != current.dtype or previous.shape != current.shape:
        return (MC2BackendDirtySpanV1(buffer_name, 0, row_count, reason),)
    if current.ndim == 0:
        changed = np.asarray([not np.array_equal(previous, current)], dtype=np.bool_)
    elif current.ndim == 1:
        changed = previous != current
    else:
        changed = np.any(previous != current, axis=tuple(range(1, current.ndim)))
    indices = np.flatnonzero(changed)
    if not len(indices):
        return ()
    spans = []
    start = int(indices[0])
    stop = start + 1
    for value in indices[1:]:
        value = int(value)
        if value == stop:
            stop += 1
            continue
        spans.append(MC2BackendDirtySpanV1(buffer_name, start, stop, reason))
        start, stop = value, value + 1
    spans.append(MC2BackendDirtySpanV1(buffer_name, start, stop, reason))
    return tuple(spans)


def make_mc2_backend_upload_plan(
    program: MC2CompiledDomainProgramV1,
    parameters: MC2DomainParameterPacketV1,
    frame_packet: MC2DomainFramePacketV1,
    *,
    collider_arrays: dict[str, object] | None = None,
    previous_program: MC2CompiledDomainProgramV1 | None = None,
    previous_parameters: MC2DomainParameterPacketV1 | None = None,
    previous_frame_packet: MC2DomainFramePacketV1 | None = None,
    previous_collider_arrays: dict[str, object] | None = None,
) -> MC2BackendUploadPlanV1:
    """Compare immutable packets and emit exact contiguous host upload ranges."""

    if not isinstance(program, MC2CompiledDomainProgramV1):
        raise TypeError("program must be MC2CompiledDomainProgramV1")
    if not isinstance(parameters, MC2DomainParameterPacketV1):
        raise TypeError("parameters must be MC2DomainParameterPacketV1")
    if not isinstance(frame_packet, MC2DomainFramePacketV1):
        raise TypeError("frame_packet must be MC2DomainFramePacketV1")
    if parameters.layout_signature != program.layout_signature:
        raise ValueError("parameter packet layout does not match program")
    if (
        frame_packet.layout_signature != program.layout_signature
        or frame_packet.domain_signature != program.domain_signature
    ):
        raise ValueError("frame packet identity does not match program")
    if previous_program is not None and not isinstance(
        previous_program, MC2CompiledDomainProgramV1
    ):
        raise TypeError("previous_program must be MC2CompiledDomainProgramV1 or None")
    if previous_parameters is not None and not isinstance(
        previous_parameters, MC2DomainParameterPacketV1
    ):
        raise TypeError(
            "previous_parameters must be MC2DomainParameterPacketV1 or None"
        )
    if previous_frame_packet is not None and not isinstance(
        previous_frame_packet, MC2DomainFramePacketV1
    ):
        raise TypeError(
            "previous_frame_packet must be MC2DomainFramePacketV1 or None"
        )

    layout_rebuild = (
        previous_program is None
        or previous_program.layout_signature != program.layout_signature
    )
    parameter_rebuild = (
        layout_rebuild
        or previous_parameters is None
        or previous_parameters.parameter_layout_signature
        != parameters.parameter_layout_signature
    )
    current_program_arrays = _backend_program_arrays(program)
    previous_program_arrays = (
        {} if layout_rebuild else _backend_program_arrays(previous_program)
    )
    current_parameter_arrays = _backend_parameter_arrays(parameters)
    previous_parameter_arrays = (
        {} if parameter_rebuild else _backend_parameter_arrays(previous_parameters)
    )
    current_frame_arrays = _backend_frame_arrays(frame_packet, collider_arrays)
    previous_frame_valid = (
        not layout_rebuild
        and previous_frame_packet is not None
        and previous_frame_packet.layout_signature == frame_packet.layout_signature
        and previous_frame_packet.domain_signature == frame_packet.domain_signature
    )
    previous_frame_arrays = (
        _backend_frame_arrays(previous_frame_packet, previous_collider_arrays)
        if previous_frame_valid
        else {}
    )

    program_spans = tuple(
        span
        for name, current in current_program_arrays.items()
        for span in _backend_dirty_spans(
            name,
            previous_program_arrays.get(name),
            current,
            "layout_rebuild" if layout_rebuild else "domain_value_update",
        )
    )
    parameter_spans = tuple(
        span
        for name, current in current_parameter_arrays.items()
        for span in _backend_dirty_spans(
            name,
            previous_parameter_arrays.get(name),
            current,
            "parameter_rebuild" if parameter_rebuild else "parameter_dirty_span",
        )
    )
    frame_spans = tuple(
        span
        for name, current in current_frame_arrays.items()
        for span in _backend_dirty_spans(
            name,
            previous_frame_arrays.get(name),
            current,
            "frame_dirty_span",
        )
    )
    reallocate = []
    for current_arrays, previous_arrays in (
        (current_program_arrays, previous_program_arrays),
        (current_parameter_arrays, previous_parameter_arrays),
        (current_frame_arrays, previous_frame_arrays),
    ):
        for name, current in current_arrays.items():
            previous = previous_arrays.get(name)
            if (
                previous is None
                or np.asarray(previous).dtype != np.asarray(current).dtype
                or np.asarray(previous).shape != np.asarray(current).shape
            ):
                reallocate.append(name)
    return MC2BackendUploadPlanV1(
        layout_signature=program.layout_signature,
        layout_rebuild=layout_rebuild,
        parameter_rebuild=parameter_rebuild,
        reallocate_buffers=tuple(reallocate),
        program_spans=program_spans,
        parameter_spans=parameter_spans,
        frame_spans=frame_spans,
    )


def make_mc2_backend_dynamic_capacity_policies(
    contract: MC2BackendDataPassContractV1,
) -> tuple[MC2BackendDynamicCapacityPolicyV1, ...]:
    if not isinstance(contract, MC2BackendDataPassContractV1):
        raise TypeError("contract must be MC2BackendDataPassContractV1")
    phases = (
        ("transient.self_candidates", "self_candidate_count", "self_candidate_emit"),
        ("transient.self_contacts", "self_contact_count", "self_contact_emit"),
        ("debug.self_intersections", "intersection_count", "intersection_emit"),
    )
    result = []
    for buffer_name, count_phase, emit_phase in phases:
        buffer = contract.buffer(buffer_name)
        if buffer.hard_capacity is None:
            raise ValueError(f"dynamic buffer {buffer_name!r} lacks a hard capacity")
        result.append(MC2BackendDynamicCapacityPolicyV1(
            buffer_name=buffer_name,
            count_phase=count_phase,
            emit_phase=emit_phase,
            hard_capacity=buffer.hard_capacity,
        ))
    return tuple(result)


__all__ = [
    "MC2_BACKEND_CONTRACT_SCHEMA_VERSION",
    "MC2_BACKEND_IO_CONTRACT_V1",
    "MC2_BACKEND_NUMERICAL_POLICY_V1",
    "MC2_DOMAIN_IR_SCHEMA_VERSION",
    "MC2_PARTITION_FRAME_DISABLED",
    "MC2_PARTITION_FRAME_KEEP",
    "MC2_PARTITION_FRAME_RESET",
    "MC2BackendBufferSpecV1",
    "MC2BackendDataPassContractV1",
    "MC2BackendDirtySpanV1",
    "MC2BackendDynamicCapacityPolicyV1",
    "MC2BackendIOContractV1",
    "MC2BackendNumericalPolicyV1",
    "MC2BackendPassSpecV1",
    "MC2BackendUploadPlanV1",
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
    "make_mc2_backend_data_pass_contract",
    "make_mc2_backend_dynamic_capacity_policies",
    "make_mc2_backend_upload_plan",
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
