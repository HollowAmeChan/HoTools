"""MC2 三种 setup 的纯静态拓扑快照。"""

from __future__ import annotations

from collections.abc import Mapping
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
from .source_identity import mc2_source_token


@dataclass(frozen=True)
class _MC2TopologyIntentV1:
    task_id: str
    setup_type: str
    topology_signature: str
    sources: tuple[object, ...]
    profile: object
    setup_options: object


def _task_intent(task) -> _MC2TopologyIntentV1:
    from .specs import MC2TaskSpec

    if not isinstance(task, MC2TaskSpec):
        raise TypeError("task 必须是 MC2TaskSpec")
    return _MC2TopologyIntentV1(
        task_id=task.task_id,
        setup_type=task.setup_type,
        topology_signature=task.topology_signature,
        sources=task.sources,
        profile=task.profile,
        setup_options=task.setup_options,
    )


def _partition_intent(partition) -> _MC2TopologyIntentV1:
    from .partition_specs import MC2ResolvedPartitionSpec
    from .product_bone_authoring import MC2BonePartitionSourceV1

    if not isinstance(partition, MC2ResolvedPartitionSpec):
        raise TypeError("partition 必须是 MC2ResolvedPartitionSpec")
    source = partition.source
    if partition.setup_type == "mesh_cloth":
        sources = (source,)
    else:
        if not isinstance(source, MC2BonePartitionSourceV1):
            raise TypeError("Bone product partition source 类型无效")
        sources = source.task_sources
    topology_signature = _signature({
        "schema": "mc2_partition_topology_intent_v1",
        "partition_id": partition.stable_id,
        "setup_type": partition.setup_type,
        "source": mc2_source_token(source),
        "setup_options": partition.setup_options.debug_dict(),
    })
    return _MC2TopologyIntentV1(
        task_id=partition.stable_id,
        setup_type=partition.setup_type,
        topology_signature=topology_signature,
        sources=sources,
        profile=partition.profile,
        setup_options=partition.setup_options,
    )


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


def thaw_mc2_topology_payload(value):
    if isinstance(value, tuple):
        if all(
            isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            for item in value
        ):
            return {key: thaw_mc2_topology_payload(item) for key, item in value}
        return [thaw_mc2_topology_payload(item) for item in value]
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
    triangle_loops: np.ndarray
    polygon_loop_totals: np.ndarray
    loop_vertices: np.ndarray
    loop_uvs: np.ndarray
    pin_weights: np.ndarray
    radius_multipliers: np.ndarray
    pin_enabled: bool
    pin_name: str
    radius_group_name: str
    has_uv: bool


@dataclass(frozen=True)
class MC2BoneRawSnapshot:
    armature_pointer: int
    armature_name: str
    requested: tuple[str, ...]
    names: tuple[str, ...]
    parents: np.ndarray
    head_tail: np.ndarray
    matrices: np.ndarray
    resolved: bool


@dataclass(frozen=True)
class _MC2ArmatureRestSnapshot:
    names: tuple[str, ...]
    name_to_index: dict[str, int]
    parent_names: tuple[str, ...]
    head_tail: np.ndarray
    matrices: np.ndarray


def _unresolved_source_fingerprint(source, kind: str) -> dict[str, str]:
    token = mc2_source_token(source)
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
    if (
        mesh is None
        or not hasattr(mesh, "vertices")
        or not hasattr(mesh, "edges")
        or not hasattr(mesh, "polygons")
        or not hasattr(mesh, "loops")
        or not callable(getattr(mesh, "calc_loop_triangles", None))
    ):
        return None
    positions = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    normals = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    edges = np.empty(len(mesh.edges) * 2, dtype=np.int32)
    mesh.vertices.foreach_get("co", positions)
    mesh.vertices.foreach_get("normal", normals)
    mesh.edges.foreach_get("vertices", edges)
    mesh.calc_loop_triangles()
    triangles = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", triangles)
    triangle_loops = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("loops", triangle_loops)
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
    radius_group_name = str(getattr(properties, "radius_vertex_group", "") or "")
    radius_multipliers = np.ones(len(mesh.vertices), dtype=np.float32)
    if radius_group_name:
        radius_group = source.vertex_groups.get(radius_group_name)
        if radius_group is None:
            raise ValueError(
                f"MC2 radius vertex group does not exist: {radius_group_name!r}"
            )
        radius_multipliers.fill(0.0)
        radius_group_index = int(radius_group.index)
        for vertex in mesh.vertices:
            for assignment in vertex.groups:
                if int(assignment.group) == radius_group_index:
                    radius_multipliers[vertex.index] = max(
                        0.0, min(1.0, float(assignment.weight))
                    )
                    break
    arrays = (
        positions,
        normals,
        edges,
        triangles,
        triangle_loops,
        polygon_loop_totals,
        loop_vertices,
        uvs,
        weights,
        radius_multipliers,
    )
    for values in arrays:
        values.flags.writeable = False
    return MC2MeshRawSnapshot(
        source_pointer=_pointer(source),
        mesh_pointer=_pointer(mesh),
        positions=positions.reshape((-1, 3)),
        normals=normals.reshape((-1, 3)),
        edges=edges.reshape((-1, 2)),
        triangles=triangles.reshape((-1, 3)),
        triangle_loops=triangle_loops.reshape((-1, 3)),
        polygon_loop_totals=polygon_loop_totals,
        loop_vertices=loop_vertices,
        loop_uvs=uvs.reshape((-1, 2)),
        pin_weights=weights,
        radius_multipliers=radius_multipliers,
        pin_enabled=pin_enabled,
        pin_name=pin_name,
        radius_group_name=radius_group_name,
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

    return dict(native_module().mc2_mesh_static_fingerprint_v1(
        snapshot.positions.reshape((-1,)),
        snapshot.normals.reshape((-1,)),
        snapshot.edges.reshape((-1,)),
        snapshot.triangles.reshape((-1,)),
        snapshot.loop_vertices,
        snapshot.loop_uvs.reshape((-1,)),
        snapshot.pin_weights,
        snapshot.radius_multipliers,
        snapshot.source_pointer,
        snapshot.mesh_pointer,
        snapshot.pin_enabled,
        snapshot.pin_name,
        snapshot.radius_group_name,
        snapshot.has_uv,
    ))


def read_mc2_static_source_observation(
    task: "MC2TaskSpec",
    source,
    *,
    armature_rest_snapshots: dict[int, _MC2ArmatureRestSnapshot] | None = None,
) -> tuple[
    dict[str, str],
    MC2MeshRawSnapshot | MC2BoneRawSnapshot | None,
]:
    """Read one source once and derive its topology/geometry/surface hashes."""

    intent = _task_intent(task)
    return _read_mc2_static_source_observation(
        intent.setup_type,
        source,
        armature_rest_snapshots=armature_rest_snapshots,
    )


def read_mc2_partition_static_source_observation(partition, source):
    """从 resolved partition 读取一个 source，不创建旧 task spec。"""

    intent = _partition_intent(partition)
    return _read_mc2_static_source_observation(intent.setup_type, source)


def _read_mc2_static_source_observation(
    setup_type: str,
    source,
    *,
    armature_rest_snapshots: dict[int, _MC2ArmatureRestSnapshot] | None = None,
):
    if setup_type == "mesh_cloth":
        snapshot = _read_mesh_raw_snapshot(source)
        return _mesh_input_fingerprint(source, snapshot), snapshot
    shared_rest = armature_rest_snapshots
    if shared_rest is None:
        shared_rest = {}
    snapshot = _read_bone_raw_snapshot(source, shared_rest)
    return _bone_input_fingerprint(source, snapshot), snapshot


def compose_mc2_static_inputs(
    task: "MC2TaskSpec",
    source_fingerprints,
    raw_snapshots,
) -> tuple[
    MC2StaticInputFingerprint,
    tuple[MC2MeshRawSnapshot | MC2BoneRawSnapshot | None, ...],
]:
    """Compose one task fingerprint from already observed source snapshots."""

    return _compose_mc2_static_inputs(
        _task_intent(task),
        source_fingerprints,
        raw_snapshots,
    )


def compose_mc2_partition_static_inputs(
    partition,
    source_fingerprints,
    raw_snapshots,
):
    """从 resolved partition 合成静态身份，不创建旧 task spec。"""

    return _compose_mc2_static_inputs(
        _partition_intent(partition),
        source_fingerprints,
        raw_snapshots,
    )


def _compose_mc2_static_inputs(
    intent: _MC2TopologyIntentV1,
    source_fingerprints,
    raw_snapshots,
):
    sources = tuple(source_fingerprints)
    snapshots = tuple(raw_snapshots)
    if len(sources) != len(intent.sources) or len(snapshots) != len(intent.sources):
        raise ValueError("MC2 static source observation count does not match intent sources")
    for source in sources:
        if not isinstance(source, Mapping) or any(
            key not in source for key in ("topology", "geometry", "surface")
        ):
            raise TypeError("MC2 static source fingerprint is invalid")
    topology = _compact_signature((
        "mc2_task_topology_v1",
        intent.setup_type,
        intent.topology_signature,
        tuple(source["topology"] for source in sources),
    ))
    geometry = _compact_signature((
        "mc2_task_geometry_v1",
        intent.setup_type,
        tuple(source["geometry"] for source in sources),
    ))
    surface = _compact_signature((
        "mc2_task_surface_v1",
        intent.setup_type,
        tuple(source["surface"] for source in sources),
    ))
    config = _compact_signature((
        "mc2_task_static_config_v1",
        intent.setup_type,
        tuple(float(value) for value in intent.profile.gravity_direction),
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
    return fingerprint, snapshots


def prepare_static_inputs_for_task(
    task: "MC2TaskSpec",
) -> tuple[
    MC2StaticInputFingerprint,
    tuple[MC2MeshRawSnapshot | MC2BoneRawSnapshot | None, ...],
]:
    """Read each source once and derive the native static fingerprint."""

    return _prepare_static_inputs_for_intent(_task_intent(task))


def _prepare_static_inputs_for_intent(
    intent: _MC2TopologyIntentV1,
):
    sources = []
    raw_snapshots: list[MC2MeshRawSnapshot | MC2BoneRawSnapshot | None] = []
    armature_rest_snapshots: dict[int, _MC2ArmatureRestSnapshot] = {}
    for source in intent.sources:
        source_fingerprint, snapshot = _read_mc2_static_source_observation(
            intent.setup_type,
            source,
            armature_rest_snapshots=armature_rest_snapshots,
        )
        sources.append(source_fingerprint)
        raw_snapshots.append(snapshot)
    return _compose_mc2_static_inputs(
        intent,
        sources,
        raw_snapshots,
    )


def prepare_static_inputs_for_partition(partition):
    """读取一个 resolved Bone partition，且不创建 MC2TaskSpec。"""

    return _prepare_static_inputs_for_intent(_partition_intent(partition))


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
        names = ()
    elif explicit_chain:
        names = tuple(name for name in requested if _collection_get(collection, name) is not None)
    else:
        names = _collect_bone_names(collection, requested)

    return armature, collection, requested, explicit_chain, names


def _read_armature_rest_snapshot(collection) -> _MC2ArmatureRestSnapshot:
    bones = tuple(collection or ())
    names = tuple(str(getattr(bone, "name", "") or "") for bone in bones)
    name_to_index = {name: index for index, name in enumerate(names)}
    parent_names = tuple(
        str(getattr(getattr(bone, "parent", None), "name", "") or "")
        for bone in bones
    )
    heads = np.empty((len(bones), 3), dtype=np.float32)
    tails = np.empty((len(bones), 3), dtype=np.float32)
    matrices = np.empty((len(bones), 16), dtype=np.float32)
    foreach_get = getattr(collection, "foreach_get", None)
    used_bulk = False
    if callable(foreach_get):
        try:
            foreach_get("head_local", heads.reshape((-1,)))
            foreach_get("tail_local", tails.reshape((-1,)))
            foreach_get("matrix_local", matrices.reshape((-1,)))
            matrices[:] = (
                matrices.reshape((-1, 4, 4))
                .transpose((0, 2, 1))
                .reshape((-1, 16))
            )
            used_bulk = True
        except (AttributeError, RuntimeError, TypeError):
            pass
    if not used_bulk:
        for index, bone in enumerate(bones):
            heads[index] = _vector3(getattr(bone, "head_local", None))
            tails[index] = _vector3(getattr(bone, "tail_local", None))
            matrices[index] = _matrix16(getattr(bone, "matrix_local", None))
    return _MC2ArmatureRestSnapshot(
        names=names,
        name_to_index=name_to_index,
        parent_names=parent_names,
        head_tail=np.concatenate((heads, tails), axis=1),
        matrices=matrices,
    )


def _read_bone_raw_snapshot(
    source,
    armature_rest_snapshots: dict[int, _MC2ArmatureRestSnapshot] | None = None,
) -> MC2BoneRawSnapshot:
    armature, collection, requested, explicit_chain, names = _bone_source_selection(source)
    name_to_index = {name: index for index, name in enumerate(names)}
    armature_pointer = _pointer(armature)
    cache = armature_rest_snapshots if armature_rest_snapshots is not None else {}
    rest = cache.get(armature_pointer)
    if rest is None:
        rest = _read_armature_rest_snapshot(collection)
        cache[armature_pointer] = rest
    selected_indices = np.asarray(
        tuple(rest.name_to_index[name] for name in names),
        dtype=np.int32,
    )
    parents = np.empty(len(names), dtype=np.int32)
    for index, name in enumerate(names):
        parent_name = rest.parent_names[int(selected_indices[index])]
        parents[index] = name_to_index.get(parent_name, -1)
    head_tail = np.ascontiguousarray(rest.head_tail[selected_indices])
    matrices = np.ascontiguousarray(rest.matrices[selected_indices])
    resolved = (
        collection is not None and len(names) == len(requested)
        if explicit_chain
        else collection is not None and bool(names)
    )
    return MC2BoneRawSnapshot(
        armature_pointer=armature_pointer,
        armature_name=str(
            getattr(armature, "name_full", getattr(armature, "name", "")) or ""
        ),
        requested=requested,
        names=names,
        parents=parents,
        head_tail=head_tail,
        matrices=matrices,
        resolved=resolved,
    )


def _bone_input_fingerprint(
    source,
    snapshot: MC2BoneRawSnapshot | None = None,
) -> dict[str, str]:
    if snapshot is None:
        snapshot = _read_bone_raw_snapshot(source)
    from .native import native_module

    return dict(native_module().mc2_bone_static_fingerprint_v1(
        snapshot.parents,
        snapshot.head_tail.reshape((-1,)),
        snapshot.matrices.reshape((-1,)),
        snapshot.armature_pointer,
        snapshot.armature_name,
        "\0".join(snapshot.requested),
        "\0".join(snapshot.names),
        snapshot.resolved,
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
    bone_names: tuple[str, ...] = ()

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
            result["payload"] = thaw_mc2_topology_payload(self.payload)
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
    token = mc2_source_token(source)
    identity_signature = _signature(token)
    payload = _mesh_payload(source) if source_kind == "mesh" else _bone_payload(source)
    if source_kind == "mesh":
        particle_count = len(payload["positions"])
        bone_names = ()
    else:
        particle_count = len(payload["bones"])
        bone_names = tuple(
            str(record.get("name") or "")
            for record in payload["bones"]
        )
    frozen_payload = _freeze(payload)
    return MC2SourceTopologySpec(
        source_index=source_index,
        source_kind=source_kind,
        identity_signature=identity_signature,
        payload_signature=_signature(payload),
        particle_count=particle_count,
        resolved=bool(payload["resolved"]),
        payload=frozen_payload,
        bone_names=bone_names,
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
    token = mc2_source_token(source)
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


def _build_compact_bone_source_topology(
    source,
    source_index: int,
    snapshot: MC2BoneRawSnapshot,
) -> MC2SourceTopologySpec:
    payload = {
        "resolved": snapshot.resolved,
        "armature_name": snapshot.armature_name,
        "armature_pointer": snapshot.armature_pointer,
        "requested": snapshot.requested,
    }
    return MC2SourceTopologySpec(
        source_index=source_index,
        source_kind="bone_chain",
        identity_signature=_signature(mc2_source_token(source)),
        payload_signature=_signature((
            snapshot.armature_pointer,
            snapshot.armature_name,
            snapshot.requested,
            snapshot.names,
        )),
        particle_count=len(snapshot.names),
        resolved=snapshot.resolved,
        payload=_freeze(payload),
        bone_names=snapshot.names,
    )


def _build_mc2_topology_spec(
    intent: _MC2TopologyIntentV1,
    *,
    static_input_fingerprint: MC2StaticInputFingerprint | None = None,
    static_input_snapshots: tuple[
        MC2MeshRawSnapshot | MC2BoneRawSnapshot | None, ...
    ] | None = None,
) -> MC2TopologySpec:
    from .setups import get_mc2_setup_adapter

    adapter = get_mc2_setup_adapter(intent.setup_type)
    source_topology_builders = {
        "build_mc2_mesh_source_topology": build_mc2_mesh_source_topology,
        "build_mc2_bone_source_topology": build_mc2_bone_source_topology,
    }
    try:
        source_topology_builder = source_topology_builders[
            adapter.topology_builder_name
        ]
    except KeyError as exc:
        raise RuntimeError(
            f"MC2 setup adapter has unknown topology builder: "
            f"{adapter.topology_builder_name!r}"
        ) from exc
    if (
        intent.setup_type == "mesh_cloth"
        and len(intent.sources) == 1
        and isinstance(static_input_fingerprint, MC2StaticInputFingerprint)
    ):
        sources = (
            _build_compact_mesh_source_topology(
                intent.sources[0],
                0,
                static_input_fingerprint,
            ),
        )
    elif (
        intent.setup_type in ("bone_cloth", "bone_spring")
        and static_input_snapshots is not None
        and len(static_input_snapshots) == len(intent.sources)
        and all(isinstance(item, MC2BoneRawSnapshot) for item in static_input_snapshots)
    ):
        sources = tuple(
            _build_compact_bone_source_topology(source, index, snapshot)
            for index, (source, snapshot) in enumerate(
                zip(intent.sources, static_input_snapshots)
            )
        )
    else:
        sources = tuple(
            source_topology_builder(source, index)
            for index, source in enumerate(intent.sources)
        )
    bone_connection = None
    if sources and all(source.source_kind == "bone_chain" for source in sources):
        seen_bones: set[tuple[int, str]] = set()
        positions: list[tuple[float, float, float]] = []
        parent_indices: list[int] = []
        child_indices: list[tuple[int, ...]] = []
        root_indices: list[int] = []
        product_chains: list[tuple[int, ...]] = []
        compact_bone_snapshots = (
            tuple(static_input_snapshots)
            if static_input_snapshots is not None
            and len(static_input_snapshots) == len(sources)
            and all(isinstance(item, MC2BoneRawSnapshot) for item in static_input_snapshots)
            else ()
        )
        for snapshot in compact_bone_snapshots:
            if snapshot.resolved:
                continue
            for name in snapshot.requested:
                key = (snapshot.armature_pointer, name)
                if key in seen_bones:
                    raise ValueError(f"MC2 task bone source overlaps: {name!r}")
                seen_bones.add(key)
        for source, snapshot in zip(sources, compact_bone_snapshots):
            source_offset = len(positions)
            product_chains.append(tuple(
                source_offset + local_index
                for local_index in range(len(snapshot.names))
            ))
            for local_index, name in enumerate(snapshot.names):
                key = (snapshot.armature_pointer, name)
                if key in seen_bones:
                    raise ValueError(f"MC2 task bone source overlaps: {name!r}")
                seen_bones.add(key)
                local_parent = int(snapshot.parents[local_index])
                if local_parent < 0:
                    root_indices.append(source_offset + local_index)
                    parent_indices.append(-1)
                else:
                    parent_indices.append(source_offset + local_parent)
                child_indices.append(tuple(
                    source_offset + child
                    for child, parent in enumerate(snapshot.parents)
                    if int(parent) == local_index
                ))
                positions.append(tuple(
                    float(value) for value in snapshot.head_tail[local_index, :3]
                ))
        for source in (() if compact_bone_snapshots else sources):
            payload = thaw_mc2_topology_payload(source.payload)
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
            if intent.setup_options.connection_model == "hotools_product":
                bone_connection = build_hotools_bone_connection(
                    positions,
                    parent_indices,
                    product_chains,
                    intent.setup_options.connection_mode,
                )
            else:
                bone_connection = build_mc2_bone_connection(
                    positions,
                    parent_indices,
                    root_indices,
                    intent.setup_options.connection_mode,
                    child_indices=child_indices,
                )
    signature_payload = {
        "schema_version": 1,
        "setup_type": intent.setup_type,
        "task_topology_signature": intent.topology_signature,
        "connection_mode": intent.setup_options.connection_mode,
        "connection_model": intent.setup_options.connection_model,
    }
    if intent.setup_type == "mesh_cloth":
        mesh_fingerprint = static_input_fingerprint
        if not isinstance(mesh_fingerprint, MC2StaticInputFingerprint):
            mesh_fingerprint = _prepare_static_inputs_for_intent(intent)[0]
        signature_payload["mesh_topology_fingerprint"] = mesh_fingerprint.topology
    else:
        bone_fingerprint = static_input_fingerprint
        if not isinstance(bone_fingerprint, MC2StaticInputFingerprint):
            bone_fingerprint = _prepare_static_inputs_for_intent(intent)[0]
        signature_payload["bone_topology_fingerprint"] = bone_fingerprint.topology
    if bone_connection is not None:
        signature_payload["bone_connection_signature"] = bone_connection.topology_signature
    return MC2TopologySpec(
        task_id=intent.task_id,
        setup_type=intent.setup_type,
        task_topology_signature=intent.topology_signature,
        connection_mode=intent.setup_options.connection_mode,
        connection_model=intent.setup_options.connection_model,
        sources=sources,
        particle_count=sum(source.particle_count for source in sources),
        topology_signature=_signature(signature_payload),
        bone_connection=bone_connection,
    )


def build_mc2_topology_spec(
    task,
    *,
    static_input_fingerprint: MC2StaticInputFingerprint | None = None,
    static_input_snapshots: tuple[
        MC2MeshRawSnapshot | MC2BoneRawSnapshot | None, ...
    ] | None = None,
) -> MC2TopologySpec:
    return _build_mc2_topology_spec(
        _task_intent(task),
        static_input_fingerprint=static_input_fingerprint,
        static_input_snapshots=static_input_snapshots,
    )


def build_mc2_partition_topology_spec(
    partition,
    *,
    static_input_fingerprint: MC2StaticInputFingerprint | None = None,
    static_input_snapshots: tuple[MC2BoneRawSnapshot, ...] | None = None,
) -> MC2TopologySpec:
    """用同一拓扑核心编译 resolved Bone partition。"""

    return _build_mc2_topology_spec(
        _partition_intent(partition),
        static_input_fingerprint=static_input_fingerprint,
        static_input_snapshots=static_input_snapshots,
    )


__all__ = [
    "MC2StaticInputFingerprint",
    "MC2MeshRawSnapshot",
    "MC2BoneRawSnapshot",
    "MC2SourceTopologySpec",
    "MC2TopologySpec",
    "build_mc2_bone_source_topology",
    "build_mc2_mesh_source_topology",
    "build_mc2_partition_topology_spec",
    "build_mc2_topology_spec",
    "compose_mc2_static_inputs",
    "compose_mc2_partition_static_inputs",
    "prepare_static_inputs_for_task",
    "prepare_static_inputs_for_partition",
    "read_mc2_partition_static_source_observation",
    "read_mc2_static_source_observation",
    "static_input_fingerprint_for_task",
    "thaw_mc2_topology_payload",
]
