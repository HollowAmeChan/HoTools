"""MC2 三种 setup 的纯静态拓扑快照。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np

from .bone_connection import (
    MC2BoneConnectionSpec,
    build_hotools_bone_connection,
    build_mc2_bone_connection,
)
from .specs import MC2TaskSpec, _source_token


def _freeze(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("MC2 topology 不能包含 NaN/Inf")
        return value
    if isinstance(value, dict):
        return tuple(
            (str(key), _freeze(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    raise TypeError(f"MC2 topology 包含不可冻结值: {type(value).__name__}")


def _thaw(value):
    if isinstance(value, tuple):
        if all(
            isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            for item in value
        ):
            return {key: _thaw(item) for key, item in value}
        return [_thaw(item) for item in value]
    return value


def _signature(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _compact_signature(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.blake2b(encoded.encode("utf-8"), digest_size=16).hexdigest()


@dataclass(frozen=True)
class MC2StaticInputFingerprint:
    topology: str
    geometry: str
    surface: str
    config: str
    source: str
    overall: str

    def __post_init__(self) -> None:
        for name in ("topology", "geometry", "surface", "config", "source", "overall"):
            value = getattr(self, name)
            if len(value) != 32 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"MC2 {name} fingerprint must be 32 lowercase hex characters")

    def native_values(self) -> tuple[str, str, str, str, str]:
        return self.topology, self.geometry, self.surface, self.config, self.overall

    def debug_dict(self) -> dict:
        return {
            "topology": self.topology,
            "geometry": self.geometry,
            "surface": self.surface,
            "config": self.config,
            "source": self.source,
            "overall": self.overall,
        }


@dataclass(frozen=True)
class MC2MeshRawSnapshot:
    source_pointer: int
    mesh_pointer: int
    positions: np.ndarray
    normals: np.ndarray
    edges: np.ndarray
    triangles: np.ndarray
    polygon_loop_totals: np.ndarray
    loop_vertices: np.ndarray
    loop_uvs: np.ndarray
    pin_weights: np.ndarray
    pin_enabled: bool
    pin_name: str
    has_uv: bool


def _unresolved_source_fingerprint(source, kind: str) -> dict[str, str]:
    token = _source_token(source)
    topology = _compact_signature((kind, "unresolved", token))
    geometry = _compact_signature((kind, "geometry", "unresolved"))
    surface = _compact_signature((kind, "surface", "unresolved"))
    return {
        "topology": topology,
        "geometry": geometry,
        "surface": surface,
    }


def _read_mesh_raw_snapshot(source) -> MC2MeshRawSnapshot | None:
    mesh = getattr(source, "data", None)
    if mesh is None:
        return None
    mesh.update()
    positions = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    normals = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    edges = np.empty(len(mesh.edges) * 2, dtype=np.int32)
    mesh.vertices.foreach_get("co", positions)
    mesh.vertices.foreach_get("normal", normals)
    mesh.edges.foreach_get("vertices", edges)
    mesh.calc_loop_triangles()
    triangles = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", triangles)
    polygon_loop_totals = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("loop_total", polygon_loop_totals)
    loop_vertices = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loop_vertices)
    uv_layer = getattr(getattr(mesh, "uv_layers", None), "active", None)
    if uv_layer is None:
        uvs = np.empty((0,), dtype=np.float32)
    else:
        uvs = np.empty(len(uv_layer.data) * 2, dtype=np.float32)
        uv_layer.data.foreach_get("uv", uvs)

    properties = getattr(source, "hotools_mesh_collision", None)
    pin_enabled = bool(getattr(properties, "pin_enabled", False))
    pin_name = str(getattr(properties, "pin_vertex_group", "") or "")
    weights = np.empty((0,), dtype=np.float32)
    if pin_enabled and pin_name:
        group = source.vertex_groups.get(pin_name)
        group_index = int(group.index) if group is not None else -1
        weights = np.zeros(len(mesh.vertices), dtype=np.float32)
        if group_index >= 0:
            for vertex in mesh.vertices:
                for assignment in vertex.groups:
                    if int(assignment.group) == group_index:
                        weights[vertex.index] = float(assignment.weight)
                        break
    return MC2MeshRawSnapshot(
        source_pointer=_pointer(source),
        mesh_pointer=_pointer(mesh),
        positions=positions.reshape((-1, 3)),
        normals=normals.reshape((-1, 3)),
        edges=edges.reshape((-1, 2)),
        triangles=triangles.reshape((-1, 3)),
        polygon_loop_totals=polygon_loop_totals,
        loop_vertices=loop_vertices,
        loop_uvs=uvs.reshape((-1, 2)),
        pin_weights=weights,
        pin_enabled=pin_enabled,
        pin_name=pin_name,
        has_uv=uv_layer is not None,
    )


def _mesh_input_fingerprint(
    source,
    snapshot: MC2MeshRawSnapshot | None = None,
) -> dict[str, str]:
    if snapshot is None:
        snapshot = _read_mesh_raw_snapshot(source)
    if snapshot is None:
        return _unresolved_source_fingerprint(source, "mesh")
    from .native import native_module

    return dict(native_module().mc2_mesh_static_fingerprint_v0(
        snapshot.positions.reshape((-1,)),
        snapshot.normals.reshape((-1,)),
        snapshot.edges.reshape((-1,)),
        snapshot.triangles.reshape((-1,)),
        snapshot.loop_vertices,
        snapshot.loop_uvs.reshape((-1,)),
        snapshot.pin_weights,
        snapshot.source_pointer,
        snapshot.mesh_pointer,
        snapshot.pin_enabled,
        snapshot.pin_name,
        snapshot.has_uv,
    ))


def prepare_static_inputs_for_task(
    task: "MC2TaskSpec",
) -> tuple[MC2StaticInputFingerprint, tuple[MC2MeshRawSnapshot | None, ...]]:
    """Read each Mesh source once and derive the native static fingerprint."""

    if not isinstance(task, MC2TaskSpec):
        raise TypeError("task 必须是 MC2TaskSpec")
    sources = []
    mesh_snapshots: list[MC2MeshRawSnapshot | None] = []
    for source in task.sources:
        if task.setup_type == "mesh_cloth":
            snapshot = _read_mesh_raw_snapshot(source)
            mesh_snapshots.append(snapshot)
            sources.append(_mesh_input_fingerprint(source, snapshot))
        else:
            mesh_snapshots.append(None)
            sources.append(_bone_input_fingerprint(source))
    topology = _compact_signature((
        "mc2_task_topology_v1",
        task.setup_type,
        task.topology_signature,
        tuple(source["topology"] for source in sources),
    ))
    geometry = _compact_signature((
        "mc2_task_geometry_v1",
        task.setup_type,
        tuple(source["geometry"] for source in sources),
    ))
    surface = _compact_signature((
        "mc2_task_surface_v1",
        task.setup_type,
        tuple(source["surface"] for source in sources),
    ))
    config = _compact_signature((
        "mc2_task_static_config_v1",
        task.setup_type,
        tuple(float(value) for value in task.profile.gravity_direction),
    ))
    source = _compact_signature(("mc2_task_source_v1", topology, geometry, surface))
    overall = _compact_signature(("mc2_task_static_v1", source, config))
    fingerprint = MC2StaticInputFingerprint(
        topology=topology,
        geometry=geometry,
        surface=surface,
        config=config,
        source=source,
        overall=overall,
    )
    return fingerprint, tuple(mesh_snapshots)


def static_input_fingerprint_for_task(task: "MC2TaskSpec") -> MC2StaticInputFingerprint:
    """Classify Blender static inputs without materializing frozen topology."""

    return prepare_static_inputs_for_task(task)[0]


def _vector3(value) -> tuple[float, float, float]:
    if value is None:
        return (0.0, 0.0, 0.0)
    if all(hasattr(value, axis) for axis in ("x", "y", "z")):
        values = (value.x, value.y, value.z)
    else:
        try:
            values = tuple(value)
        except TypeError:
            return (0.0, 0.0, 0.0)
    if len(values) < 3:
        return (0.0, 0.0, 0.0)
    result = tuple(float(values[index]) for index in range(3))
    if not all(math.isfinite(component) for component in result):
        raise ValueError("MC2 topology 坐标不能包含 NaN/Inf")
    return result


def _matrix16(value) -> tuple[float, ...]:
    if value is None:
        return ()
    try:
        rows = tuple(value)
        flat = tuple(float(component) for row in rows for component in row)
    except (TypeError, ValueError):
        return ()
    if len(flat) != 16:
        return ()
    if not all(math.isfinite(component) for component in flat):
        raise ValueError("MC2 topology 矩阵不能包含 NaN/Inf")
    return flat


def _collection_get(collection, name: str):
    getter = getattr(collection, "get", None)
    if callable(getter):
        try:
            return getter(name)
        except Exception:
            return None
    for item in collection or ():
        if str(getattr(item, "name", "") or "") == name:
            return item
    return None


def _pointer(value) -> int:
    pointer = getattr(value, "as_pointer", None)
    if not callable(pointer):
        return 0
    try:
        return max(0, int(pointer()))
    except Exception:
        return 0


def _mesh_payload(source) -> dict:
    data = getattr(source, "data", None)
    vertices = tuple(getattr(data, "vertices", ()) or ())
    edges = tuple(getattr(data, "edges", ()) or ())
    polygons = tuple(getattr(data, "polygons", ()) or ())
    positions = tuple(_vector3(getattr(vertex, "co", None)) for vertex in vertices)
    normals = tuple(
        _vector3(getattr(vertex, "normal", None))
        if getattr(vertex, "normal", None) is not None
        else (0.0, 1.0, 0.0)
        for vertex in vertices
    )
    edge_indices = tuple(
        tuple(int(index) for index in tuple(getattr(edge, "vertices", ()) or ())[:2])
        for edge in edges
    )
    polygon_indices = tuple(
        tuple(int(index) for index in tuple(getattr(polygon, "vertices", ()) or ()))
        for polygon in polygons
    )
    triangles: list[tuple[int, int, int]] = []
    for polygon in polygon_indices:
        if len(polygon) < 3:
            continue
        root = polygon[0]
        triangles.extend(
            (root, polygon[index], polygon[index + 1])
            for index in range(1, len(polygon) - 1)
        )
    return {
        "resolved": data is not None,
        "name": str(getattr(source, "name_full", getattr(source, "name", "")) or ""),
        "positions": positions,
        "normals": normals,
        "edges": edge_indices,
        "triangles": tuple(triangles),
        "polygon_count": len(polygon_indices),
    }


def _bone_children(bone) -> tuple:
    try:
        return tuple(getattr(bone, "children", ()) or ())
    except Exception:
        return ()


def _collect_bone_names(collection, requested: tuple[str, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    stack = [
        bone
        for name in reversed(requested)
        if (bone := _collection_get(collection, name)) is not None
    ]
    while stack:
        bone = stack.pop()
        name = str(getattr(bone, "name", "") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        ordered.append(name)
        children = _bone_children(bone)
        stack.extend(reversed(children))
    return tuple(ordered)


def _bone_source_selection(source):
    if isinstance(source, tuple) and len(source) == 2:
        armature = source[0]
        requested = (str(source[1] or ""),)
        explicit_chain = False
    elif isinstance(source, dict):
        armature = source.get("armature")
        explicit = tuple(str(name) for name in (source.get("bones") or ()) if str(name))
        root = str(source.get("root_bone") or source.get("bone") or "").strip()
        requested = explicit or ((root,) if root else ())
        explicit_chain = bool(explicit)
    else:
        armature = None
        requested = ()
        explicit_chain = False

    armature_data = getattr(armature, "data", None)
    collection = getattr(armature_data, "bones", None)
    if collection is None:
        names = requested
    elif explicit_chain:
        names = tuple(name for name in requested if _collection_get(collection, name) is not None)
    else:
        names = _collect_bone_names(collection, requested)

    return armature, collection, requested, explicit_chain, names


def _bone_input_fingerprint(source) -> dict[str, str]:
    armature, collection, requested, explicit_chain, names = _bone_source_selection(source)
    name_to_index = {name: index for index, name in enumerate(names)}
    parents = np.empty(len(names), dtype=np.int32)
    head_tail = np.empty((len(names), 6), dtype=np.float32)
    matrices = np.empty((len(names), 16), dtype=np.float32)
    for index, name in enumerate(names):
        bone = _collection_get(collection, name) if collection is not None else None
        parent_name = str(getattr(getattr(bone, "parent", None), "name", "") or "")
        parents[index] = name_to_index.get(parent_name, -1)
        head_tail[index, :3] = _vector3(getattr(bone, "head_local", None))
        head_tail[index, 3:] = _vector3(getattr(bone, "tail_local", None))
        matrices[index] = _matrix16(getattr(bone, "matrix_local", None))
    resolved = (
        collection is not None and len(names) == len(requested)
        if explicit_chain
        else collection is not None and bool(names)
    )
    from .native import native_module

    return dict(native_module().mc2_bone_static_fingerprint_v0(
        parents,
        head_tail.reshape((-1,)),
        matrices.reshape((-1,)),
        _pointer(armature),
        str(getattr(armature, "name_full", getattr(armature, "name", "")) or ""),
        "\0".join(requested),
        "\0".join(names),
        resolved,
    ))


def _bone_payload(source) -> dict:
    armature, collection, requested, explicit_chain, names = _bone_source_selection(source)
    name_to_index = {name: index for index, name in enumerate(names)}
    records = []
    for name in names:
        bone = _collection_get(collection, name) if collection is not None else None
        parent = getattr(bone, "parent", None)
        parent_name = str(getattr(parent, "name", "") or "")
        records.append(
            {
                "name": name,
                "parent_index": name_to_index.get(parent_name, -1),
                "child_indices": tuple(
                    name_to_index[child_name]
                    for child in _bone_children(bone)
                    if (child_name := str(getattr(child, "name", "") or "")) in name_to_index
                ),
                "head": _vector3(getattr(bone, "head_local", None)),
                "tail": _vector3(getattr(bone, "tail_local", None)),
                "matrix_local": _matrix16(getattr(bone, "matrix_local", None)),
            }
        )
    return {
        "resolved": collection is not None and len(records) == len(requested) if explicit_chain else collection is not None and bool(records),
        "armature_name": str(getattr(armature, "name_full", getattr(armature, "name", "")) or ""),
        "armature_pointer": _pointer(armature),
        "requested": requested,
        "bones": tuple(records),
    }


@dataclass(frozen=True)
class MC2SourceTopologySpec:
    source_index: int
    source_kind: str
    identity_signature: str
    payload_signature: str
    particle_count: int
    resolved: bool
    payload: tuple

    def debug_dict(self, *, include_payload: bool = False) -> dict:
        result = {
            "source_index": self.source_index,
            "source_kind": self.source_kind,
            "identity_signature": self.identity_signature,
            "payload_signature": self.payload_signature,
            "particle_count": self.particle_count,
            "resolved": self.resolved,
        }
        if include_payload:
            result["payload"] = _thaw(self.payload)
        return result


@dataclass(frozen=True)
class MC2TopologySpec:
    task_id: str
    setup_type: str
    task_topology_signature: str
    connection_mode: int
    connection_model: str
    sources: tuple[MC2SourceTopologySpec, ...]
    particle_count: int
    topology_signature: str
    bone_connection: MC2BoneConnectionSpec | None = None
    schema_version: int = 1

    def debug_dict(self, *, include_payload: bool = False) -> dict:
        return {
            "task_id": self.task_id,
            "setup_type": self.setup_type,
            "task_topology_signature": self.task_topology_signature,
            "connection_mode": self.connection_mode,
            "connection_model": self.connection_model,
            "source_count": len(self.sources),
            "particle_count": self.particle_count,
            "topology_signature": self.topology_signature,
            "schema_version": self.schema_version,
            "bone_connection": (
                self.bone_connection.debug_dict(include_arrays=include_payload)
                if self.bone_connection is not None
                else None
            ),
            "sources": [
                source.debug_dict(include_payload=include_payload)
                for source in self.sources
            ],
        }


def _build_source_topology(source_kind: str, source, source_index: int) -> MC2SourceTopologySpec:
    token = _source_token(source)
    identity_signature = _signature(token)
    payload = _mesh_payload(source) if source_kind == "mesh" else _bone_payload(source)
    if source_kind == "mesh":
        particle_count = len(payload["positions"])
    else:
        particle_count = len(payload["bones"])
    frozen_payload = _freeze(payload)
    return MC2SourceTopologySpec(
        source_index=source_index,
        source_kind=source_kind,
        identity_signature=identity_signature,
        payload_signature=_signature(payload),
        particle_count=particle_count,
        resolved=bool(payload["resolved"]),
        payload=frozen_payload,
    )


def build_mc2_mesh_source_topology(source, source_index: int) -> MC2SourceTopologySpec:
    return _build_source_topology("mesh", source, source_index)


def build_mc2_bone_source_topology(source, source_index: int) -> MC2SourceTopologySpec:
    return _build_source_topology("bone_chain", source, source_index)


def _build_compact_mesh_source_topology(
    source,
    source_index: int,
    fingerprint: MC2StaticInputFingerprint,
) -> MC2SourceTopologySpec:
    token = _source_token(source)
    mesh = getattr(source, "data", None)
    resolved = mesh is not None and hasattr(mesh, "vertices")
    particle_count = len(mesh.vertices) if resolved else 0
    payload = {
        "resolved": resolved,
        "name": str(getattr(source, "name_full", getattr(source, "name", "")) or ""),
        "native_source_fingerprint": fingerprint.source,
    }
    return MC2SourceTopologySpec(
        source_index=source_index,
        source_kind="mesh",
        identity_signature=_signature(token),
        payload_signature=fingerprint.source,
        particle_count=particle_count,
        resolved=resolved,
        payload=_freeze(payload),
    )


def build_mc2_topology_spec(
    task: MC2TaskSpec,
    *,
    static_input_fingerprint: MC2StaticInputFingerprint | None = None,
) -> MC2TopologySpec:
    if not isinstance(task, MC2TaskSpec):
        raise TypeError("task 必须是 MC2TaskSpec")
    # 局部导入避免 setup adapter 声明与 topology 类型之间形成模块初始化环。
    from .setups import get_mc2_setup_adapter

    adapter = get_mc2_setup_adapter(task.setup_type)
    if (
        task.setup_type == "mesh_cloth"
        and len(task.sources) == 1
        and isinstance(static_input_fingerprint, MC2StaticInputFingerprint)
    ):
        sources = (
            _build_compact_mesh_source_topology(
                task.sources[0],
                0,
                static_input_fingerprint,
            ),
        )
    else:
        sources = tuple(
            adapter.build_source_topology(source, index)
            for index, source in enumerate(task.sources)
        )
    bone_connection = None
    if sources and all(source.source_kind == "bone_chain" for source in sources):
        seen_bones: set[tuple[int, str]] = set()
        positions: list[tuple[float, float, float]] = []
        parent_indices: list[int] = []
        child_indices: list[tuple[int, ...]] = []
        root_indices: list[int] = []
        product_chains: list[tuple[int, ...]] = []
        for source in sources:
            payload = _thaw(source.payload)
            armature_pointer = int(payload.get("armature_pointer", 0) or 0)
            records = payload.get("bones", ())
            source_offset = len(positions)
            product_chains.append(tuple(
                source_offset + local_index
                for local_index in range(len(records))
            ))
            for local_index, record in enumerate(records):
                key = (armature_pointer, str(record.get("name") or ""))
                if key in seen_bones:
                    raise ValueError(
                        f"MC2 task 的骨链 source 重叠: {record.get('name')!r}"
                    )
                seen_bones.add(key)
                local_parent = int(record.get("parent_index", -1))
                if local_parent < 0:
                    root_indices.append(source_offset + local_index)
                    parent_indices.append(-1)
                else:
                    parent_indices.append(source_offset + local_parent)
                child_indices.append(tuple(
                    source_offset + int(child)
                    for child in record.get("child_indices", ())
                ))
                positions.append(tuple(float(value) for value in record["head"]))
        if positions and all(source.resolved for source in sources):
            if task.setup_options.connection_model == "hotools_product":
                bone_connection = build_hotools_bone_connection(
                    positions,
                    parent_indices,
                    product_chains,
                    task.setup_options.connection_mode,
                )
            else:
                bone_connection = build_mc2_bone_connection(
                    positions,
                    parent_indices,
                    root_indices,
                    task.setup_options.connection_mode,
                    child_indices=child_indices,
                )
    signature_payload = {
        "schema_version": 1,
        "setup_type": task.setup_type,
        "task_topology_signature": task.topology_signature,
        "connection_mode": task.setup_options.connection_mode,
        "connection_model": task.setup_options.connection_model,
    }
    if task.setup_type == "mesh_cloth":
        mesh_fingerprint = static_input_fingerprint
        if not isinstance(mesh_fingerprint, MC2StaticInputFingerprint):
            mesh_fingerprint = static_input_fingerprint_for_task(task)
        signature_payload["mesh_topology_fingerprint"] = mesh_fingerprint.topology
    else:
        signature_payload["source_payload_signatures"] = [
            source.payload_signature for source in sources
        ]
    if bone_connection is not None:
        signature_payload["bone_connection_signature"] = bone_connection.topology_signature
    return MC2TopologySpec(
        task_id=task.task_id,
        setup_type=task.setup_type,
        task_topology_signature=task.topology_signature,
        connection_mode=task.setup_options.connection_mode,
        connection_model=task.setup_options.connection_model,
        sources=sources,
        particle_count=sum(source.particle_count for source in sources),
        topology_signature=_signature(signature_payload),
        bone_connection=bone_connection,
    )


__all__ = [
    "MC2StaticInputFingerprint",
    "MC2MeshRawSnapshot",
    "MC2SourceTopologySpec",
    "MC2TopologySpec",
    "build_mc2_bone_source_topology",
    "build_mc2_mesh_source_topology",
    "build_mc2_topology_spec",
    "prepare_static_inputs_for_task",
    "static_input_fingerprint_for_task",
]
