"""Modal topology-safe redistribution of a continuous quad strip.

The operator has two explicit input modes:

* ``LOOPS`` expects two or more selected transverse edge loops.
* ``STRIP`` expects two selected longitudinal edge chains that delimit a
  unique quad strip.

Both modes are converted into the same :class:`_StripDescriptor`.  Preview
meshes are rebuilt from an immutable edit-mesh snapshot, so changing the wheel
value never compounds an earlier dissolve or split.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math

import bmesh
import bpy
from bpy.props import FloatProperty, IntProperty
from bpy.types import Operator
from mathutils import Vector

from Utils.hud import draw_mouse_hud_rows

from .offset_edges_modal import (
    _ensure_edit_mode,
    _mesh_snapshot,
    _restore_snapshot_bmesh,
    _selected_edge_keys,
)


_EPSILON = 1.0e-9
_MAX_RING_STATES = 4096
_MAX_SEGMENTS = 512
_DEFAULT_SMOOTHNESS = 0.55
_DEFAULT_SLIDE_STRENGTH = 0.0
_IDENTITY_LAYER_NAME = "hotools_resegment_identity"


_HUD_NAMESPACE_KEY = "hotools_resegment_hud_handles"
_ACTIVE_HUD_HANDLES = bpy.app.driver_namespace.setdefault(
    _HUD_NAMESPACE_KEY,
    set(),
)


def cleanup_resegment_huds():
    """Remove HUD handlers left behind by a reload or hard cancel."""
    for handle in list(_ACTIVE_HUD_HANDLES):
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
        except (AttributeError, RuntimeError, TypeError, ReferenceError):
            pass
        _ACTIVE_HUD_HANDLES.discard(handle)


def _edge_key(edge):
    first, second = edge.verts
    return tuple(sorted((first.index, second.index)))


def _state_key(edges):
    return tuple(sorted(_edge_key(edge) for edge in edges))


def _edge_by_key(bm, key):
    first, second = key
    if first < 0 or second < 0 or first >= len(bm.verts) or second >= len(bm.verts):
        return None
    try:
        edge = bm.edges.get((bm.verts[first], bm.verts[second]))
    except (AttributeError, IndexError, TypeError, ValueError):
        edge = None
    if edge is not None and edge.is_valid:
        return edge
    return next(
        (
            item for item in bm.edges
            if item.is_valid and _edge_key(item) == tuple(sorted(key))
        ),
        None,
    )


def _identity_layer(bm):
    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    layer = bm.verts.layers.int.get(_IDENTITY_LAYER_NAME)
    if layer is None:
        layer = bm.verts.layers.int.new(_IDENTITY_LAYER_NAME)
    for vertex in bm.verts:
        vertex[layer] = vertex.index
    return layer


def _vertex_by_identity(bm, identity_layer, identity):
    return next(
        (
            vertex for vertex in bm.verts
            if vertex.is_valid and vertex[identity_layer] == identity
        ),
        None,
    )


def _edge_by_identity(bm, identity_layer, first_id, second_id):
    wanted = {first_id, second_id}
    return next(
        (
            edge for edge in bm.edges
            if edge.is_valid
            and {vertex[identity_layer] for vertex in edge.verts} == wanted
        ),
        None,
    )


def _identity_edge_key(edge, identity_layer):
    return tuple(sorted(vertex[identity_layer] for vertex in edge.verts))


def _remove_identity_layer(bm, identity_layer):
    try:
        bm.verts.layers.int.remove(identity_layer)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass


def _edges_from_state(bm, key):
    edges = []
    for edge_key in key:
        edge = _edge_by_key(bm, edge_key)
        if edge is None:
            return None
        edges.append(edge)
    return edges


def _edge_components(edges):
    remaining = {
        edge for edge in edges if edge.is_valid and not edge.hide
    }
    components = []
    while remaining:
        seed = min(remaining, key=lambda item: item.index)
        remaining.remove(seed)
        component = {seed}
        pending = [seed]
        while pending:
            edge = pending.pop()
            linked = {
                other
                for vertex in edge.verts
                for other in vertex.link_edges
                if other in remaining and other.is_valid and not other.hide
            }
            remaining.difference_update(linked)
            component.update(linked)
            pending.extend(linked)
        components.append(component)
    return components


def _selected_edge_components(bm):
    """Return connected components of visible selected edges."""
    return _edge_components(
        edge for edge in bm.edges if edge.select
    )


def _dominant_edge_axis(edges):
    matrix = [[0.0, 0.0, 0.0] for _ in range(3)]
    for edge in edges:
        delta = edge.verts[1].co - edge.verts[0].co
        if delta.length <= _EPSILON:
            continue
        delta.normalize()
        for row in range(3):
            for column in range(3):
                matrix[row][column] += delta[row] * delta[column]
    axis_index = max(range(3), key=lambda index: matrix[index][index])
    axis = Vector(tuple(1.0 if index == axis_index else 0.0
                        for index in range(3)))
    for _iteration in range(32):
        updated = Vector(tuple(
            sum(matrix[row][column] * axis[column] for column in range(3))
            for row in range(3)
        ))
        if updated.length <= _EPSILON:
            return None
        updated.normalize()
        if (updated - axis).length <= 1.0e-8:
            axis = updated
            break
        axis = updated
    return axis


def _edges_aligned_to_axis(edges, axis, minimum_alignment=0.55):
    if axis is None:
        return []
    aligned = []
    for edge in edges:
        direction = edge.verts[1].co - edge.verts[0].co
        if direction.length <= _EPSILON:
            continue
        if abs(direction.normalized().dot(axis)) >= minimum_alignment:
            aligned.append(edge)
    return aligned


def _ordered_component(edges):
    """Order a simple open chain or cyclic edge loop."""
    edges = {edge for edge in edges if edge.is_valid and not edge.hide}
    if not edges:
        raise ValueError("选中的边为空")

    adjacency = {}
    edge_lookup = {}
    for edge in edges:
        first, second = edge.verts
        adjacency.setdefault(first, []).append(second)
        adjacency.setdefault(second, []).append(first)
        edge_lookup[frozenset((first, second))] = edge

    degrees = [len(neighbors) for neighbors in adjacency.values()]
    cyclic = all(degree == 2 for degree in degrees)
    open_chain = (
        sum(degree == 1 for degree in degrees) == 2
        and all(degree <= 2 for degree in degrees)
    )
    if not (cyclic or open_chain):
        raise ValueError("选中的边存在分叉，不能识别为连续环线")

    if cyclic:
        start = min(adjacency, key=lambda item: item.index)
        first_neighbor = min(adjacency[start], key=lambda item: item.index)
    else:
        start = min(
            (vertex for vertex, neighbors in adjacency.items()
             if len(neighbors) == 1),
            key=lambda item: item.index,
        )
        first_neighbor = adjacency[start][0]

    vertices = [start]
    previous = None
    current = start
    while True:
        candidates = [
            vertex for vertex in adjacency[current]
            if vertex is not previous
        ]
        if not candidates:
            break
        if previous is None:
            next_vertex = first_neighbor
        else:
            next_vertex = min(candidates, key=lambda item: item.index)
        if next_vertex is start:
            if not cyclic:
                break
            break
        if next_vertex in vertices:
            raise ValueError("选中的边无法组成单一连续环线")
        vertices.append(next_vertex)
        previous, current = current, next_vertex
        if cyclic and len(vertices) == len(adjacency):
            break

    if len(vertices) != len(adjacency):
        raise ValueError("选中的边不是完整的连续环线")

    ordered_edges = []
    edge_count = len(vertices) if cyclic else len(vertices) - 1
    for index in range(edge_count):
        next_index = (index + 1) % len(vertices)
        edge = edge_lookup.get(
            frozenset((vertices[index], vertices[next_index]))
        )
        if edge is None:
            raise ValueError("环线顺序中缺少连接边")
        ordered_edges.append(edge)
    return vertices, ordered_edges, cyclic


def _opposite_edge(face, edge):
    candidates = [
        other for other in face.edges
        if other is not edge
        and not any(vertex in edge.verts for vertex in other.verts)
    ]
    return candidates[0] if len(candidates) == 1 else None


def _face_edge_mapping(face, edge, opposite):
    """Map each endpoint of ``edge`` to its corresponding opposite endpoint."""
    opposite_vertices = set(opposite.verts)
    mapping = {}
    for vertex in edge.verts:
        candidates = []
        for face_edge in face.edges:
            if vertex not in face_edge.verts or face_edge is edge:
                continue
            other = face_edge.other_vert(vertex)
            if other in opposite_vertices:
                candidates.append(other)
        if len(candidates) != 1:
            return None
        mapping[vertex.index] = candidates[0].index
    return mapping


def _ring_transitions(bm, state_key, allowed_faces=None):
    """Return all valid quad-face transitions to an opposite edge ring."""
    edges = _edges_from_state(bm, state_key)
    if not edges:
        return []
    try:
        current_vertices, current_edges, cyclic = _ordered_component(edges)
    except ValueError:
        return []

    allowed_faces = set(allowed_faces) if allowed_faces is not None else None
    records_by_edge = {}
    for edge in current_edges:
        records = []
        for face in sorted(edge.link_faces, key=lambda item: item.index):
            if (
                not face.is_valid
                or face.hide
                or len(face.verts) != 4
                or (allowed_faces is not None and face.index not in allowed_faces)
            ):
                continue
            opposite = _opposite_edge(face, edge)
            if opposite is None or not opposite.is_valid:
                continue
            mapping = _face_edge_mapping(face, edge, opposite)
            if mapping is None:
                continue
            records.append((_edge_key(opposite), face.index, mapping))
        records_by_edge[_edge_key(edge)] = records

    first_edge = current_edges[0]
    first_key = _edge_key(first_edge)
    transitions = []
    for seed in records_by_edge.get(first_key, ()):
        chosen = [seed]
        mapping = dict(seed[2])
        valid = True
        for index in range(1, len(current_edges)):
            edge = current_edges[index]
            edge_key = _edge_key(edge)
            shared_vertex = current_vertices[index].index
            expected_target = mapping.get(shared_vertex)
            if expected_target is None:
                valid = False
                break
            candidates = [
                record for record in records_by_edge.get(edge_key, ())
                if record[2].get(shared_vertex) == expected_target
                and expected_target in record[0]
            ]
            if len(candidates) != 1:
                valid = False
                break
            chosen.append(candidates[0])
            mapping.update(candidates[0][2])

        if not valid:
            continue

        target_keys = tuple(sorted(record[0] for record in chosen))
        target_edges = _edges_from_state(bm, target_keys)
        if not target_edges:
            continue
        try:
            target_vertices, _ordered_target_edges, target_cyclic = (
                _ordered_component(target_edges)
            )
        except ValueError:
            continue
        if target_cyclic != cyclic:
            continue
        if set(mapping.values()) != {vertex.index for vertex in target_vertices}:
            continue
        if len(set(face_id for _edge, face_id, _mapping in chosen)) != len(chosen):
            continue
        transitions.append({
            "state_key": target_keys,
            "faces": tuple(record[1] for record in chosen),
            "mapping": mapping,
        })

    unique = {}
    for transition in transitions:
        unique.setdefault(transition["state_key"], transition)
    return list(unique.values())


def _find_loop_path(bm, candidates, allowed_faces=None):
    """Find the shortest path containing the largest number of picked loops."""
    if len(candidates) < 2:
        raise ValueError("至少需要选择两条环线")

    candidate_by_key = {
        candidate["state_key"]: candidate
        for candidate in candidates
    }
    selected_keys = set(candidate_by_key)
    path_options = []
    state_limit = max(
        256,
        min(_MAX_RING_STATES, max(1, len(bm.faces)) * 8),
    )

    for start_key in selected_keys:
        queue = deque([(start_key, (start_key,))])
        visited = {start_key}
        while queue and len(visited) <= state_limit:
            state_key, path = queue.popleft()
            if state_key in selected_keys and state_key != start_key:
                path_options.append(path)
            for transition in _ring_transitions(
                bm, state_key, allowed_faces=allowed_faces
            ):
                next_key = transition["state_key"]
                if next_key in visited:
                    continue
                visited.add(next_key)
                queue.append((next_key, path + (next_key,)))

    if not path_options:
        raise ValueError("选中的环线之间没有找到连续的四边面条带")

    def score(path):
        selected_count = sum(key in selected_keys for key in path)
        return selected_count, -len(path)

    best_score = max(score(path) for path in path_options)
    best_paths = [path for path in path_options if score(path) == best_score]
    unique_paths = {}
    for path in best_paths:
        reverse = tuple(reversed(path))
        canonical = min(path, reverse)
        unique_paths.setdefault(canonical, path)
    if len(unique_paths) > 1:
        raise ValueError("选中的环线对应多个同样合理的条带方向")

    path = next(iter(unique_paths.values()))
    if sum(key in selected_keys for key in path) != len(selected_keys):
        raise ValueError("所有选中的环线必须位于同一条连续条带上")
    return path


def _ring_positions(bm, ring_ids):
    positions = []
    for ring in ring_ids:
        row = []
        for vertex_id in ring:
            if vertex_id < 0 or vertex_id >= len(bm.verts):
                raise ValueError("环线顶点索引无效")
            row.append(bm.verts[vertex_id].co.copy())
        positions.append(tuple(row))
    return tuple(positions)


def _ring_parameters(positions):
    if len(positions) < 2:
        return (0.0, 1.0)
    distances = [0.0]
    for index in range(1, len(positions)):
        distance = sum(
            (positions[index][column] - positions[index - 1][column]).length
            for column in range(len(positions[index]))
        ) / max(1, len(positions[index]))
        distances.append(distances[-1] + distance)
    total = distances[-1]
    if total <= _EPSILON:
        return tuple(index / max(1, len(positions) - 1)
                     for index in range(len(positions)))
    return tuple(distance / total for distance in distances)


def _column_parameters(positions):
    parameters = []
    for column in range(len(positions[0])):
        distances = [0.0]
        for ring_index in range(1, len(positions)):
            distance = (
                positions[ring_index][column]
                - positions[ring_index - 1][column]
            ).length
            distances.append(distances[-1] + distance)
        total = distances[-1]
        if total <= _EPSILON:
            raise ValueError("条带中的纵向网格路径长度为零")
        parameters.append(tuple(distance / total for distance in distances))
    return tuple(parameters)


@dataclass
class _StripDescriptor:
    mode: str
    cyclic: bool
    ring_ids: tuple[tuple[int, ...], ...]
    ring_edge_keys: tuple[tuple[tuple[int, int], ...], ...]
    region_faces: frozenset[int]
    source_positions: tuple[tuple[Vector, ...], ...]
    source_parameters: tuple[float, ...]
    column_parameters: tuple[tuple[float, ...], ...]

    @property
    def segment_count(self):
        return len(self.ring_ids) - 1

    @property
    def vertex_count(self):
        return len(self.ring_ids[0])

    @property
    def column_count(self):
        return self.vertex_count if self.cyclic else self.vertex_count - 1


def _descriptor_from_path(bm, path, mode, allowed_faces=None):
    first_edges = _edges_from_state(bm, path[0])
    if not first_edges:
        raise ValueError("条带起始环线已失效")
    first_vertices, _ordered_edges, cyclic = _ordered_component(first_edges)
    ring_ids = [tuple(vertex.index for vertex in first_vertices)]
    ring_edge_keys = [tuple(path[0])]
    region_faces = set()
    current_vertices = list(first_vertices)

    for current_key, next_key in zip(path, path[1:]):
        transition = next(
            (
                item for item in _ring_transitions(
                    bm, current_key, allowed_faces=allowed_faces
                )
                if item["state_key"] == next_key
            ),
            None,
        )
        if transition is None:
            raise ValueError("条带方向在构建期间失效")
        next_ids = tuple(
            transition["mapping"][vertex.index]
            for vertex in current_vertices
        )
        next_edges = _edges_from_state(bm, next_key)
        if not next_edges:
            raise ValueError("条带中间环线已失效")
        next_vertex_ids = {
            next_vertex.index
            for next_edge in next_edges
            for next_vertex in next_edge.verts
        }
        if set(next_ids) != next_vertex_ids:
            raise ValueError("相邻环线的顶点对应关系不完整")
        ring_ids.append(next_ids)
        ring_edge_keys.append(tuple(next_key))
        region_faces.update(transition["faces"])
        current_vertices = [
            bm.verts[vertex_id] for vertex_id in next_ids
        ]

    if len(set(ring_ids)) != len(ring_ids):
        raise ValueError("条带环线重复，无法重新分段")
    if any(len(ring) != len(ring_ids[0]) for ring in ring_ids):
        raise ValueError("条带中的环线顶点数量不一致")
    expected_faces = (len(path) - 1) * (
        len(ring_ids[0]) if cyclic else len(ring_ids[0]) - 1
    )
    if len(region_faces) != expected_faces:
        raise ValueError("条带面数量不连续，可能包含非流形或分叉拓扑")
    for face in bm.faces:
        if face.index not in region_faces:
            continue
        if (
            not face.is_valid
            or len(face.verts) != 4
            or any(len(edge.link_faces) not in {1, 2} for edge in face.edges)
        ):
            raise ValueError("条带包含非流形边或无效四边面")

    positions = _ring_positions(bm, ring_ids)
    parameters = _ring_parameters(positions)
    column_parameters = _column_parameters(positions)
    if len(parameters) != len(ring_ids):
        raise ValueError("无法计算条带参数")
    internal_edges = set(
        edge_key
        for ring in ring_edge_keys[1:-1]
        for edge_key in ring
    )
    if not internal_edges and len(ring_ids) > 2:
        raise ValueError("条带缺少可移除的内部环线")
    return _StripDescriptor(
        mode=mode,
        cyclic=cyclic,
        ring_ids=tuple(ring_ids),
        ring_edge_keys=tuple(ring_edge_keys),
        region_faces=frozenset(region_faces),
        source_positions=positions,
        source_parameters=parameters,
        column_parameters=column_parameters,
    )


def _loop_descriptor(bm):
    components = _selected_edge_components(bm)
    if len(components) < 2:
        raise ValueError("环线模式至少需要选择两条环线")

    candidates = []
    seen_keys = set()
    for component in components:
        vertices, edges, cyclic = _ordered_component(component)
        if len(edges) < 2:
            raise ValueError("每条环线至少需要两条连续边")
        key = _state_key(edges)
        if key in seen_keys:
            raise ValueError("选中了重复的环线")
        seen_keys.add(key)
        candidates.append({
            "state_key": key,
            "vertices": vertices,
            "cyclic": cyclic,
        })

    first = candidates[0]
    if any(
        candidate["cyclic"] != first["cyclic"]
        or len(candidate["vertices"]) != len(first["vertices"])
        for candidate in candidates
    ):
        raise ValueError("所有环线必须具有相同的顶点数量和开闭类型")

    path = _find_loop_path(bm, candidates)
    descriptor = _descriptor_from_path(bm, path, "LOOPS")
    expected_faces = descriptor.segment_count * descriptor.column_count
    if len(descriptor.region_faces) != expected_faces:
        raise ValueError(
            "环线之间的四边面数量不匹配（需要连续的纯四边面条带）"
        )
    return descriptor


def _walk_rail_path(bm, start_edge, target_keys, start_face):
    """Walk across opposite edges of consecutive quads."""
    current_edge = start_edge
    face = start_face
    faces = []
    visited = set()
    for _ in range(_MAX_RING_STATES):
        if (
            face is None
            or not face.is_valid
            or face.hide
            or len(face.verts) != 4
            or current_edge is None
        ):
            return None
        edge_key = _edge_key(current_edge)
        if edge_key in visited:
            return None
        visited.add(edge_key)
        opposite = _opposite_edge(face, current_edge)
        if opposite is None:
            return None
        faces.append(face.index)
        opposite_key = _edge_key(opposite)
        if opposite_key in target_keys:
            return faces, opposite_key
        next_faces = [
            candidate for candidate in opposite.link_faces
            if candidate is not face
            and candidate.is_valid
            and not candidate.hide
            and len(candidate.verts) == 4
        ]
        if len(next_faces) != 1:
            return None
        current_edge = opposite
        face = next_faces[0]
    return None


def _boundary_components(bm, region_faces, rail_keys, rail_endpoints):
    """Find the two non-rail boundary chains of a quad patch."""
    region_faces = set(region_faces)
    rail_keys = set(rail_keys)
    edge_faces = {}
    for face in bm.faces:
        if face.is_valid and face.index in region_faces:
            for edge in face.edges:
                edge_faces.setdefault(_edge_key(edge), []).append(edge)

    boundary_edges = []
    for key, edges in edge_faces.items():
        if key in rail_keys or len(edges) != 1:
            continue
        boundary_edges.append(edges[0])
    components = []
    remaining = set(boundary_edges)
    while remaining:
        seed = min(remaining, key=lambda item: item.index)
        remaining.remove(seed)
        component = {seed}
        pending = [seed]
        while pending:
            edge = pending.pop()
            linked = {
                other for vertex in edge.verts for other in vertex.link_edges
                if other in remaining
            }
            remaining.difference_update(linked)
            component.update(linked)
            pending.extend(linked)
        components.append(component)

    wanted = set(rail_endpoints)
    result = []
    for component in components:
        vertices, edges, cyclic = _ordered_component(component)
        if cyclic:
            continue
        endpoint_ids = {vertices[0].index, vertices[-1].index}
        if len(endpoint_ids & wanted) != 2:
            continue
        result.append((vertices, edges))
    if len(result) != 2:
        raise ValueError("竖边之间没有唯一的两条横向边界")
    return result


def _path_key(edges):
    return tuple(_edge_key(edge) for edge in edges)


def _cycle_corner_indices(vertices):
    count = len(vertices)
    if count < 4:
        return []
    scores = []
    for index, vertex in enumerate(vertices):
        previous = vertices[(index - 1) % count]
        following = vertices[(index + 1) % count]
        incoming = vertex.co - previous.co
        outgoing = following.co - vertex.co
        if incoming.length <= _EPSILON or outgoing.length <= _EPSILON:
            scores.append(0.0)
        else:
            scores.append(1.0 - incoming.normalized().dot(outgoing.normalized()))

    corners = [
        index for index, score in enumerate(scores)
        if score >= 0.2
        and score >= scores[(index - 1) % count]
        and score >= scores[(index + 1) % count]
    ]
    return corners if 2 <= len(corners) <= 24 else []


def _cycle_arc(vertices, edges, start, end, direction):
    count = len(vertices)
    ordered_vertices = [vertices[start]]
    ordered_edges = []
    index = start
    while index != end:
        if direction > 0:
            ordered_edges.append(edges[index])
            index = (index + 1) % count
        else:
            previous_index = (index - 1) % count
            ordered_edges.append(edges[previous_index])
            index = previous_index
        ordered_vertices.append(vertices[index])
        if len(ordered_edges) >= count:
            return None
    if len(ordered_edges) < 2:
        return None
    return ordered_vertices, ordered_edges


def _selected_chain_candidates(component):
    """Extract simple selected chains, including arcs from a capped cycle."""
    try:
        vertices, edges, cyclic = _ordered_component(component)
        if not cyclic:
            return [(vertices, edges)]
        corners = _cycle_corner_indices(vertices)
        if not corners:
            raise ValueError("闭合竖边选区没有可识别的端部转角")
        candidates = {}
        for first_index, start in enumerate(corners):
            for end in corners[first_index + 1:]:
                for direction in (-1, 1):
                    arc = _cycle_arc(vertices, edges, start, end, direction)
                    if arc is None:
                        continue
                    key = tuple(sorted(_edge_key(edge) for edge in arc[1]))
                    candidates.setdefault(key, arc)
        return list(candidates.values())
    except ValueError:
        pass

    selected_edges = {
        edge for edge in component if edge.is_valid and not edge.hide
    }
    adjacency = {}
    for edge in selected_edges:
        first, second = edge.verts
        adjacency.setdefault(first, []).append(edge)
        adjacency.setdefault(second, []).append(edge)

    candidates = {}
    visited = set()
    junctions = [
        vertex for vertex, linked in adjacency.items()
        if len(linked) != 2
    ]
    for start in sorted(junctions, key=lambda item: item.index):
        for first_edge in sorted(adjacency[start], key=lambda item: item.index):
            if first_edge in visited:
                continue
            path_edges = [first_edge]
            path_vertices = [start]
            previous_edge = first_edge
            current = first_edge.other_vert(start)
            while len(adjacency.get(current, ())) == 2:
                next_edge = next(
                    edge for edge in adjacency[current]
                    if edge is not previous_edge
                )
                if next_edge in visited:
                    break
                path_edges.append(next_edge)
                path_vertices.append(current)
                previous_edge = next_edge
                current = next_edge.other_vert(current)
            path_vertices.append(current)
            visited.update(path_edges)
            if len(path_edges) >= 2:
                candidates.setdefault(
                    tuple(sorted(_edge_key(edge) for edge in path_edges)),
                    (path_vertices, path_edges),
                )

    if not candidates:
        raise ValueError("无法从当前边选区提取连续的竖向路径")
    return list(candidates.values())


def _strip_region(bm, rail_a_edges, rail_b_edges):
    rail_b_keys = {_edge_key(edge) for edge in rail_b_edges}
    paths_by_edge = []
    for edge in rail_a_edges:
        candidates = []
        for face in sorted(edge.link_faces, key=lambda item: item.index):
            if not face.is_valid or face.hide or len(face.verts) != 4:
                continue
            result = _walk_rail_path(bm, edge, rail_b_keys, face)
            if result is not None:
                candidates.append(result)
        if not candidates:
            raise ValueError("竖边之间没有连续的四边面路径")
        paths_by_edge.append(candidates)

    a_edge_keys = [_edge_key(edge) for edge in rail_a_edges]
    b_edge_keys = [_edge_key(edge) for edge in rail_b_edges]
    valid_orientations = []
    for reverse in (False, True):
        chosen = []
        valid = True
        for index, candidates in enumerate(paths_by_edge):
            target_index = (
                len(b_edge_keys) - 1 - index if reverse else index
            )
            target_key = b_edge_keys[target_index]
            matches = [
                item for item in candidates
                if item[1] == target_key
            ]
            if len(matches) != 1:
                valid = False
                break
            chosen.append(matches[0])
        if not valid:
            continue
        lengths = {len(item[0]) for item in chosen}
        if len(lengths) != 1:
            continue
        face_ids = [face_id for item in chosen for face_id in item[0]]
        if len(set(face_ids)) != len(face_ids):
            continue
        valid_orientations.append((reverse, chosen))

    if len(valid_orientations) != 1:
        raise ValueError("竖边对应多个可能的四边面条带")
    _reverse, chosen = valid_orientations[0]
    return frozenset(
        face_id for item in chosen for face_id in item[0]
    )


def _descriptor_from_rails(bm, first, second):
    a_vertices, a_edges = first
    b_vertices, b_edges = second
    if len(a_edges) != len(b_edges):
        raise ValueError("两条竖边的分段数量必须一致")
    if len(a_vertices) < 2:
        raise ValueError("竖边长度不足")

    rail_keys = {_edge_key(edge) for edge in a_edges + b_edges}
    rail_endpoints = (
        a_vertices[0].index,
        a_vertices[-1].index,
        b_vertices[0].index,
        b_vertices[-1].index,
    )
    region_faces = _strip_region(bm, a_edges, b_edges)
    boundary = _boundary_components(
        bm,
        region_faces,
        rail_keys,
        rail_endpoints,
    )

    endpoint_candidates = []
    for vertices, edges in boundary:
        vertex_ids = {vertex.index for vertex in vertices}
        a_end = next(
            (
                vertex for vertex in a_vertices
                if vertex.index in vertex_ids
                and vertex.index in {a_vertices[0].index, a_vertices[-1].index}
            ),
            None,
        )
        b_end = next(
            (
                vertex for vertex in b_vertices
                if vertex.index in vertex_ids
                and vertex.index in {b_vertices[0].index, b_vertices[-1].index}
            ),
            None,
        )
        if a_end is None or b_end is None:
            continue
        ordered_vertices = list(vertices)
        if ordered_vertices[0].index != a_end.index:
            ordered_vertices.reverse()
        endpoint_candidates.append((ordered_vertices, edges))

    if len(endpoint_candidates) != 2:
        raise ValueError("竖边条带的两端边界无法确定")
    endpoint_candidates.sort(
        key=lambda item: (
            0 if item[0][0].index == a_vertices[0].index else 1
        )
    )
    start_vertices, start_edges = endpoint_candidates[0]
    end_vertices, end_edges = endpoint_candidates[1]
    if len(start_vertices) != len(end_vertices):
        raise ValueError("条带两端横向环线的顶点数量不一致")

    start_key = _state_key(start_edges)
    end_key = _state_key(end_edges)
    path = _find_loop_path(
        bm,
        [
            {
                "state_key": start_key,
                "vertices": start_vertices,
                "cyclic": False,
            },
            {
                "state_key": end_key,
                "vertices": end_vertices,
                "cyclic": False,
            },
        ],
        allowed_faces=region_faces,
    )
    descriptor = _descriptor_from_path(
        bm,
        path,
        "STRIP",
        allowed_faces=region_faces,
    )
    if descriptor.segment_count != len(a_edges):
        raise ValueError("竖边长度与内部横向环线数量不一致")
    if len(descriptor.region_faces) != len(region_faces):
        raise ValueError("竖边条带存在未覆盖或重复的四边面")
    return descriptor


def _cap_components(bm, endpoint_vertices, selected_rail_edges):
    endpoint_vertices = set(endpoint_vertices)
    cap_edges = {
        edge for edge in bm.edges
        if edge.is_valid
        and not edge.hide
        and edge not in selected_rail_edges
        and edge.verts[0] in endpoint_vertices
        and edge.verts[1] in endpoint_vertices
    }
    components = []
    remaining = set(cap_edges)
    while remaining:
        seed = min(remaining, key=lambda edge: edge.index)
        remaining.remove(seed)
        component = {seed}
        pending = [seed]
        while pending:
            edge = pending.pop()
            linked = {
                other
                for vertex in edge.verts
                for other in vertex.link_edges
                if other in remaining
            }
            remaining.difference_update(linked)
            component.update(linked)
            pending.extend(linked)
        components.append(component)
    return components


def _parallel_rail_descriptor(bm, components):
    rails = []
    for component in components:
        if (
            isinstance(component, tuple)
            and len(component) == 2
            and isinstance(component[0], list)
        ):
            vertices, edges = component
            cyclic = False
        else:
            vertices, edges, cyclic = _ordered_component(component)
        if cyclic:
            raise ValueError("每条竖向路径需要是开放连续链")
        if len(edges) < 1:
            raise ValueError("竖向路径为空")
        rails.append((vertices, edges))

    segment_counts = {len(edges) for _vertices, edges in rails}
    if len(segment_counts) != 1:
        raise ValueError("所选竖向路径的边数不一致")
    segment_count = next(iter(segment_counts))
    if segment_count < 1:
        raise ValueError("竖向路径至少需要一条边")

    endpoints = [
        vertex
        for vertices, _edges in rails
        for vertex in (vertices[0], vertices[-1])
    ]
    if len(set(endpoints)) != len(endpoints):
        raise ValueError("竖向路径共享端点，无法组成规则条带")
    selected_rail_edges = {
        edge for _vertices, edges in rails for edge in edges
    }
    cap_components = _cap_components(
        bm,
        endpoints,
        selected_rail_edges,
    )
    if len(cap_components) != 2:
        raise ValueError(
            "这些竖向边没有连接到同一对端部环线；"
            "请选中条带内连续的纵向边"
        )

    caps = []
    for component in cap_components:
        cap_vertices, cap_edges, cyclic = _ordered_component(component)
        if len(cap_vertices) != len(rails):
            raise ValueError("端部环线与所选竖向路径数量不匹配")
        caps.append((cap_vertices, cap_edges, cyclic))
    if caps[0][2] != caps[1][2]:
        raise ValueError("条带两端的环线开闭类型不一致")

    cap_a, cap_b = caps
    rail_by_a_endpoint = {}
    for vertices, edges in rails:
        first, last = vertices[0], vertices[-1]
        in_a = first in cap_a[0]
        in_b = first in cap_b[0]
        if in_a == in_b:
            raise ValueError("一条竖向路径的两个端点没有落在不同端环")
        if in_a:
            rail_by_a_endpoint[first] = (vertices, edges)
        else:
            rail_by_a_endpoint[last] = (list(reversed(vertices)), list(reversed(edges)))

    if set(rail_by_a_endpoint) != set(cap_a[0]):
        raise ValueError("无法将所有竖向路径对应到起始环线")

    ring_ids = []
    for step in range(segment_count + 1):
        ring_ids.append(tuple(
            rail_by_a_endpoint[vertex][0][step].index
            for vertex in cap_a[0]
        ))

    cyclic = cap_a[2]
    column_count = len(rails) if cyclic else len(rails) - 1
    ring_edge_keys = []
    region_faces = set()
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    for step, ring in enumerate(ring_ids):
        ring_edges = []
        for column in range(column_count):
            next_column = (column + 1) % len(ring)
            first_id = ring[column]
            second_id = ring[next_column]
            edge = bm.edges.get((bm.verts[first_id], bm.verts[second_id]))
            if edge is None or not edge.is_valid:
                raise ValueError("相邻竖向路径之间缺少横向连接边")
            ring_edges.append(_edge_key(edge))
            if step == segment_count:
                continue

            next_ring = ring_ids[step + 1]
            next_first_id = next_ring[column]
            next_second_id = next_ring[next_column]
            wanted = {
                first_id,
                second_id,
                next_first_id,
                next_second_id,
            }
            matches = [
                face
                for face in bm.verts[first_id].link_faces
                if face.is_valid
                and len(face.verts) == 4
                and {vertex.index for vertex in face.verts} == wanted
            ]
            if len(matches) != 1:
                raise ValueError(
                    "相邻竖向路径之间必须由唯一四边面连接"
                )
            region_faces.add(matches[0].index)
        ring_edge_keys.append(tuple(ring_edges))

    expected_faces = segment_count * column_count
    if len(region_faces) != expected_faces:
        raise ValueError("所选纵向边没有覆盖完整、连续的四边面条带")

    positions = _ring_positions(bm, ring_ids)
    source_parameters = _ring_parameters(positions)
    column_parameters = _column_parameters(positions)
    return _StripDescriptor(
        mode="STRIP",
        cyclic=cyclic,
        ring_ids=tuple(ring_ids),
        ring_edge_keys=tuple(ring_edge_keys),
        region_faces=frozenset(region_faces),
        source_positions=positions,
        source_parameters=source_parameters,
        column_parameters=column_parameters,
    )


def _strip_descriptor(bm):
    components = _selected_edge_components(bm)
    selected_edges = [
        edge for edge in bm.edges
        if edge.is_valid and edge.select and not edge.hide
    ]
    axis = _dominant_edge_axis(selected_edges)
    rail_components = _edge_components(
        _edges_aligned_to_axis(selected_edges, axis)
    )
    if len(rail_components) >= 3:
        try:
            return _parallel_rail_descriptor(bm, rail_components)
        except (RuntimeError, TypeError, ValueError, IndexError):
            pass

    candidates = []
    for component in components:
        try:
            candidates.extend(_selected_chain_candidates(component))
        except ValueError:
            continue

    parallel_results = []
    lengths = sorted({
        len(edges) for _vertices, edges in candidates
        if len(edges) >= 1
    })
    for edge_count in lengths:
        rails = [
            candidate for candidate in candidates
            if len(candidate[1]) == edge_count
        ]
        if len(rails) < 3:
            continue
        try:
            descriptor = _parallel_rail_descriptor(bm, rails)
        except (RuntimeError, TypeError, ValueError, IndexError):
            continue
        signature = (
            descriptor.region_faces,
            min(descriptor.ring_ids[0], descriptor.ring_ids[-1]),
            max(descriptor.ring_ids[0], descriptor.ring_ids[-1]),
        )
        parallel_results.append((
            len(rails),
            sum(len(edges) for _vertices, edges in rails),
            signature,
            descriptor,
        ))

    if parallel_results:
        best_coverage = max(
            (rail_count, selected_length)
            for rail_count, selected_length, _signature, _descriptor
            in parallel_results
        )
        best_results = [
            result for result in parallel_results
            if result[:2] == best_coverage
        ]
        unique = {}
        for _rail_count, _selected_length, signature, descriptor in best_results:
            unique.setdefault(signature, descriptor)
        if len(unique) == 1:
            return next(iter(unique.values()))
        raise ValueError(
            "所选平行边对应多个同样合理的条带，请缩小选择范围"
        )

    valid = {}
    for first_index, first in enumerate(candidates):
        first_edges = set(first[1])
        for second in candidates[first_index + 1:]:
            if first_edges.intersection(second[1]):
                continue
            if len(first[1]) != len(second[1]):
                continue
            try:
                descriptor = _descriptor_from_rails(bm, first, second)
            except (RuntimeError, TypeError, ValueError, IndexError):
                continue
            key = (
                descriptor.ring_ids[0],
                descriptor.ring_ids[-1],
                descriptor.region_faces,
            )
            reverse_key = (
                descriptor.ring_ids[-1],
                descriptor.ring_ids[0],
                descriptor.region_faces,
            )
            descriptor_key = min(key, reverse_key)
            rail_length = sum(
                edge.calc_length() for edge in first[1] + second[1]
            )
            previous = valid.get(descriptor_key)
            if previous is None or rail_length > previous[1]:
                valid[descriptor_key] = (descriptor, rail_length)

    if not valid:
        raise ValueError(
            "未找到唯一的竖边条带；请选目标带内沿分段方向延伸的平行边链。"
            "圆柱可选中带内全部轴向边"
        )
    best_length = max(score for _descriptor, score in valid.values())
    best = [
        descriptor
        for descriptor, score in valid.values()
        if abs(score - best_length) <= _EPSILON
    ]
    if len(best) > 1:
        raise ValueError(
            "当前选区对应多个可能的四边面条带，请只保留目标条带的两侧竖边"
        )
    return best[0]


def _build_descriptor(context, mode):
    active = _ensure_edit_mode(context)
    if active is None:
        raise ValueError("请在网格编辑模式下运行")
    bm = bmesh.from_edit_mesh(active.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    selected_edges = [
        edge for edge in bm.edges
        if edge.is_valid and edge.select and not edge.hide
    ]
    if not selected_edges:
        raise ValueError("请先选择边")
    return _loop_descriptor(bm) if mode == "LOOPS" else _strip_descriptor(bm)


def _linear_sample(values, parameters, value):
    if value <= parameters[0] + _EPSILON:
        return values[0].copy()
    if value >= parameters[-1] - _EPSILON:
        return values[-1].copy()
    for index in range(1, len(parameters)):
        right = parameters[index]
        if value <= right + _EPSILON:
            left = parameters[index - 1]
            span = max(right - left, _EPSILON)
            factor = max(0.0, min(1.0, (value - left) / span))
            return values[index - 1].lerp(values[index], factor)
    return values[-1].copy()


def _distribution_parameter(source_parameters, normalized_index, smoothness):
    """Blend even spacing with the original monotone ring distribution."""
    if len(source_parameters) <= 2:
        return normalized_index
    source_position = normalized_index * (len(source_parameters) - 1)
    left = int(math.floor(source_position))
    right = min(len(source_parameters) - 1, left + 1)
    factor = source_position - left
    shaped = (
        source_parameters[left]
        + (source_parameters[right] - source_parameters[left]) * factor
    )
    return max(
        0.0,
        min(
            1.0,
            normalized_index * (1.0 - smoothness)
            + shaped * smoothness,
        ),
    )


def _target_positions(descriptor, segment_count, smoothness, slide_strength):
    segment_count = max(1, min(_MAX_SEGMENTS, int(segment_count)))
    smoothness = max(0.0, min(1.0, float(smoothness)))
    slide_strength = max(0.0, min(1.0, float(slide_strength)))
    result = []

    for index in range(segment_count + 1):
        normalized = index / float(segment_count)
        shared_parameter = _distribution_parameter(
            descriptor.source_parameters,
            normalized,
            smoothness,
        )
        ring = tuple(
            _linear_sample(
                tuple(source_ring[column]
                      for source_ring in descriptor.source_positions),
                descriptor.column_parameters[column],
                (
                    shared_parameter * (1.0 - slide_strength)
                    + normalized * slide_strength
                ),
            )
            for column in range(descriptor.vertex_count)
        )
        result.append(ring)
    result[0] = tuple(position.copy() for position in descriptor.source_positions[0])
    result[-1] = tuple(position.copy() for position in descriptor.source_positions[-1])
    return tuple(result)


def _find_direct_face(bm, a_ids, b_ids, identity_layer):
    a_set = set(a_ids)
    b_set = set(b_ids)
    matches = []
    for face in bm.faces:
        if not face.is_valid or len(face.verts) != 4:
            continue
        ids = {vertex[identity_layer] for vertex in face.verts}
        if len(ids & a_set) == 2 and len(ids & b_set) == 2:
            if ids.issubset(a_set | b_set):
                matches.append(face)
    return matches


def _find_face_with_far_edge(point_a, point_b, far_ids, identity_layer):
    far_ids = set(far_ids)
    common = set(point_a.link_faces) & set(point_b.link_faces)
    return next(
        (
            face for face in common
            if face.is_valid
            and far_ids.issubset(
                vertex[identity_layer] for vertex in face.verts
            )
        ),
        None,
    )


def _split_side_edge(
        bm, edge, start_id, end_id, target_positions, identity_layer):
    current = edge
    previous_vertex = _vertex_by_identity(
        bm, identity_layer, start_id)
    if previous_vertex is None:
        raise RuntimeError("纵向边起点已失效")
    points = []
    segment_count = len(target_positions) - 1
    for index in range(1, segment_count):
        target = index / float(segment_count)
        local = target
        if points:
            previous_target = (index - 1) / float(segment_count)
            local = (target - previous_target) / max(
                1.0 - previous_target,
                _EPSILON,
            )
        _unused, point = bmesh.utils.edge_split(
            current,
            previous_vertex,
            local,
        )
        point.co = target_positions[index].copy()
        points.append(point)
        current = next(
            (
                linked for linked in point.link_edges
                if end_id in {
                    vertex[identity_layer] for vertex in linked.verts
                }
            ),
            None,
        )
        if current is None:
            raise RuntimeError("纵向边切分后无法找到剩余边")
        previous_vertex = point
    return points


def _apply_descriptor(
        bm, descriptor, segment_count, smoothness, slide_strength=0.0):
    if descriptor.vertex_count < 2 or descriptor.column_count < 1:
        raise ValueError("条带宽度不足")

    identity_layer = _identity_layer(bm)
    internal_edges = []
    for edge_key in (
        edge_key
        for ring in descriptor.ring_edge_keys[1:-1]
        for edge_key in ring
    ):
        edge = _edge_by_key(bm, edge_key)
        if edge is None:
            raise RuntimeError("内部环线在预览快照中已失效")
        internal_edges.append(edge)
    if internal_edges:
        bmesh.ops.dissolve_edges(
            bm,
            edges=internal_edges,
            use_verts=True,
            use_face_split=False,
        )
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

    a_ids = descriptor.ring_ids[0]
    b_ids = descriptor.ring_ids[-1]
    column_specs = []
    for index in range(descriptor.column_count):
        next_index = (
            (index + 1) % descriptor.vertex_count
            if descriptor.cyclic else index + 1
        )
        a_pair = frozenset((a_ids[index], a_ids[next_index]))
        b_pair = frozenset((b_ids[index], b_ids[next_index]))
        matches = _find_direct_face(
            bm,
            a_pair,
            b_pair,
            identity_layer,
        )
        if len(matches) != 1:
            raise RuntimeError("端点环线之间的四边面无法唯一重建")
        side_a = _edge_by_identity(
            bm,
            identity_layer,
            a_ids[index],
            b_ids[index],
        )
        side_b = _edge_by_identity(
            bm,
            identity_layer,
            a_ids[next_index],
            b_ids[next_index],
        )
        if side_a is None or side_b is None:
            raise RuntimeError("端点环线之间缺少纵向连接边")
        if (
            side_a.calc_length() <= _EPSILON
            or side_b.calc_length() <= _EPSILON
            or matches[0].calc_area() <= _EPSILON
        ):
            raise RuntimeError("条带包含零长度边或零面积面")
        column_specs.append({
            "index": index,
            "next_index": next_index,
            "a_ids": (a_ids[index], a_ids[next_index]),
            "b_ids": (b_ids[index], b_ids[next_index]),
            "normal": matches[0].normal.copy(),
        })

    targets = _target_positions(
        descriptor,
        segment_count,
        smoothness,
        slide_strength,
    )
    split_points = {}
    created_points = []
    next_identity = -1
    for index in range(descriptor.vertex_count):
        side = _edge_by_identity(
            bm,
            identity_layer,
            a_ids[index],
            b_ids[index],
        )
        if side is None:
            raise RuntimeError("纵向边不存在，无法分配新分段")
        split_points[index] = _split_side_edge(
            bm,
            side,
            a_ids[index],
            b_ids[index],
            tuple(ring[index] for ring in targets),
            identity_layer,
        )
        for point in split_points[index]:
            point[identity_layer] = next_identity
            next_identity -= 1
            created_points.append(point)

    new_edge_records = []
    for column in column_specs:
        index = column["index"]
        next_index = column["next_index"]
        for cut_index in range(1, segment_count):
            point_a = split_points[index][cut_index - 1]
            point_b = split_points[next_index][cut_index - 1]
            face = _find_face_with_far_edge(
                point_a,
                point_b,
                column["b_ids"],
                identity_layer,
            )
            if face is None:
                raise RuntimeError("新横向环线无法穿过目标四边面")
            bmesh.utils.face_split(face, point_a, point_b)
            new_edge = next(
                (
                    edge for edge in point_a.link_edges
                    if edge.is_valid and point_b in edge.verts
                ),
                None,
            )
            if new_edge is None:
                raise RuntimeError("新横向环线没有生成连接边")
            new_edge_records.append((new_edge, column["normal"]))

    bm.normal_update()
    for point in created_points:
        if any(
            edge.calc_length() <= _EPSILON
            for edge in point.link_edges
            if edge.is_valid
        ):
            raise RuntimeError("重新分段生成了零长度边")
    for edge, normal in new_edge_records:
        if edge is None or not edge.is_valid:
            raise RuntimeError("重新分段生成了失效环线")
        if len(edge.link_faces) != 2:
            raise RuntimeError("新横向环线不是完整的流形边")
        for face in edge.link_faces:
            if (
                len(face.verts) != 4
                or face.calc_area() <= _EPSILON
                or face.normal.dot(normal) <= _EPSILON
            ):
                raise RuntimeError("重新分段生成了翻转或零面积面")
    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    bm.edges.ensure_lookup_table()
    bm.edges.index_update()
    for edge in bm.edges:
        if not edge.is_valid:
            continue
        if edge.calc_length() <= _EPSILON and any(
            vertex in created_points for vertex in edge.verts
        ):
            raise RuntimeError("重新分段生成了零长度边")
    new_edge_keys = {
        _edge_key(edge)
        for edge, _normal in new_edge_records
        if edge.is_valid
    }
    return new_edge_keys


def _write_preview(active, work_bm, selected_edge_keys):
    bpy.ops.object.mode_set(mode="OBJECT")
    try:
        for vertex in work_bm.verts:
            vertex.select_set(False)
        for edge in work_bm.edges:
            edge.select_set(False)
        for face in work_bm.faces:
            face.select_set(False)
        for edge in work_bm.edges:
            if edge.is_valid and _edge_key(edge) in selected_edge_keys:
                edge.select_set(True)
        work_bm.normal_update()
        work_bm.to_mesh(active.data)
        active.data.update()
    finally:
        bpy.ops.object.mode_set(mode="EDIT")
    edit_bm = bmesh.from_edit_mesh(active.data)
    edit_bm.verts.ensure_lookup_table()
    edit_bm.edges.ensure_lookup_table()
    edit_bm.faces.ensure_lookup_table()
    for vertex in edit_bm.verts:
        vertex.select_set(False)
    for edge in edit_bm.edges:
        edge.select_set(False)
    for face in edit_bm.faces:
        face.select_set(False)
    for edge in edit_bm.edges:
        if edge.is_valid and _edge_key(edge) in selected_edge_keys:
            edge.select_set(True)
    bmesh.update_edit_mesh(
        active.data,
        loop_triangles=False,
        destructive=False,
    )


def _selected_current_edge_keys(bm, identity_layer, original_keys,
                                generated_keys):
    original_keys = set(original_keys or ())
    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    bm.edges.ensure_lookup_table()
    bm.edges.index_update()
    selected = {
        _edge_key(edge)
        for edge in bm.edges
        if _identity_edge_key(edge, identity_layer) in original_keys
    }
    selected.update(generated_keys)
    return selected


class _ResegmentOperatorBase(Operator):
    bl_options = {"REGISTER", "UNDO"}
    selection_mode = "LOOPS"
    mode_label = "环线"

    segment_count: IntProperty(
        name="分段数",
        default=1,
        min=1,
        max=_MAX_SEGMENTS,
        description="两端固定环线之间的区间数量",
    )  # type: ignore
    smoothness: FloatProperty(
        name="平滑度",
        default=_DEFAULT_SMOOTHNESS,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        description="控制整体分布：0 偏向均匀，1 尽量保留原有环线间距",
    )  # type: ignore
    slide_strength: FloatProperty(
        name="纵向等距滑移",
        default=_DEFAULT_SLIDE_STRENGTH,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        description=(
            "沿每条纵向网格路径滑动中间环线；0 不额外滑移，"
            "1 使每条路径上的新边长度尽量均匀"
        ),
    )  # type: ignore

    _source_object = None
    _snapshot = None
    _descriptor = None
    _original_selected_edge_keys = None
    _handle_text = None
    _timer = None
    _window_manager = None
    _preview_dirty = False
    _mouse_x = 0.0
    _mouse_y = 0.0

    @classmethod
    def poll(cls, context):
        return _ensure_edit_mode(context) is not None

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "segment_count")
        layout.prop(self, "smoothness")
        layout.prop(self, "slide_strength")

    def _tag_redraw(self, context):
        area = getattr(context, "area", None)
        if area is not None:
            try:
                area.tag_redraw()
            except (AttributeError, ReferenceError, RuntimeError):
                pass

    def _hud_rows(self):
        mode_hint = (
            "选带内平行竖边"
            if self.selection_mode == "STRIP" else "环线模式"
        )
        return [
            (0, "重新分段", mode_hint),
            (24, "滚轮：", f"分段 {self.segment_count}"),
            (48, "Ctrl+滚轮：", f"整体分布 {self.smoothness:.2f}"),
            (72, "Alt+滚轮：", f"纵向等距滑移 {self.slide_strength:.2f}"),
            (96, "R：", "重置参数"),
            (120, "左键 / 回车：", "确认"),
            (144, "右键 / Esc：", "取消"),
        ]

    def _draw_hud(self):
        try:
            draw_mouse_hud_rows(
                (self._mouse_x, self._mouse_y),
                self._hud_rows(),
                offset=24,
                size=15,
            )
        except (AttributeError, RuntimeError, TypeError, ValueError,
                ReferenceError):
            pass

    def _install_hud(self):
        if self._handle_text is not None:
            return
        cleanup_resegment_huds()
        try:
            self._handle_text = bpy.types.SpaceView3D.draw_handler_add(
                self._draw_hud,
                (),
                "WINDOW",
                "POST_PIXEL",
            )
            _ACTIVE_HUD_HANDLES.add(self._handle_text)
        except (AttributeError, RuntimeError, TypeError, ReferenceError):
            self._handle_text = None

    def _remove_hud(self):
        handle = self._handle_text
        self._handle_text = None
        if handle is None:
            return
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
        except (AttributeError, RuntimeError, TypeError, ReferenceError):
            pass
        _ACTIVE_HUD_HANDLES.discard(handle)

    def _free_snapshot(self):
        snapshot = self._snapshot
        self._snapshot = None
        if snapshot is not None:
            try:
                if snapshot.users == 0:
                    bpy.data.meshes.remove(snapshot)
            except (AttributeError, ReferenceError, RuntimeError):
                pass

    def _cleanup(self):
        self._remove_hud()
        timer = self._timer
        self._timer = None
        if timer is not None and self._window_manager is not None:
            try:
                self._window_manager.event_timer_remove(timer)
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
        self._window_manager = None
        self._preview_dirty = False
        self._free_snapshot()
        self._source_object = None
        self._descriptor = None
        self._original_selected_edge_keys = None

    def _restore(self):
        if self._source_object is None or self._snapshot is None:
            return
        _restore_snapshot_bmesh(
            self._source_object,
            self._snapshot,
            self._original_selected_edge_keys,
        )

    def _cancel(self, context):
        try:
            self._restore()
        except (AttributeError, RuntimeError, TypeError, ValueError,
                ReferenceError) as error:
            self.report({"WARNING"}, f"取消时未能还原网格：{error}")
        self._cleanup()
        self._tag_redraw(context)
        return {"CANCELLED"}

    def _finish(self, context):
        if self._preview_dirty:
            try:
                self._rebuild(context)
            except (AttributeError, RuntimeError, TypeError, ValueError,
                    IndexError, ReferenceError) as error:
                self.report({"WARNING"}, f"重新分段预览失败：{error}")
                return self._cancel(context)
        self._cleanup()
        self._tag_redraw(context)
        return {"FINISHED"}

    def _rebuild(self, context):
        if self._source_object is None or self._snapshot is None:
            raise RuntimeError("重新分段快照已失效")
        work_bm = bmesh.new()
        try:
            work_bm.from_mesh(self._snapshot)
            work_bm.verts.ensure_lookup_table()
            work_bm.edges.ensure_lookup_table()
            work_bm.faces.ensure_lookup_table()
            identity_layer = _identity_layer(work_bm)
            new_edge_keys = _apply_descriptor(
                work_bm,
                self._descriptor,
                self.segment_count,
                self.smoothness,
                self.slide_strength,
            )
            selected_keys = _selected_current_edge_keys(
                work_bm,
                identity_layer,
                self._original_selected_edge_keys,
                new_edge_keys,
            )
            _remove_identity_layer(work_bm, identity_layer)
            _write_preview(self._source_object, work_bm, selected_keys)
        finally:
            work_bm.free()
        self._preview_dirty = False
        self._tag_redraw(context)

    def _prepare(self, context):
        active = _ensure_edit_mode(context)
        if active is None:
            self.report({"WARNING"}, "请在网格编辑模式下运行")
            return False
        self._window_manager = context.window_manager
        try:
            descriptor = _build_descriptor(context, self.selection_mode)
            snapshot = _mesh_snapshot(active)
            self._source_object = active
            self._snapshot = snapshot
            self._descriptor = descriptor
            self._original_selected_edge_keys = _selected_edge_keys(active)
            return True
        except (AttributeError, RuntimeError, TypeError, ValueError,
                IndexError, ReferenceError) as error:
            self.report({"WARNING"}, f"无法识别重新分段条带：{error}")
            self._cleanup()
            return False

    def invoke(self, context, event):
        if not self._prepare(context):
            return {"CANCELLED"}
        self.segment_count = self._descriptor.segment_count
        self.smoothness = _DEFAULT_SMOOTHNESS
        self.slide_strength = _DEFAULT_SLIDE_STRENGTH
        self._mouse_x = event.mouse_region_x
        self._mouse_y = event.mouse_region_y
        try:
            self._rebuild(context)
        except (AttributeError, RuntimeError, TypeError, ValueError,
                IndexError, ReferenceError) as error:
            self.report({"WARNING"}, f"重新分段预览失败：{error}")
            return self._cancel(context)
        self._install_hud()
        try:
            self._timer = context.window_manager.event_timer_add(
                0.04,
                window=context.window,
            )
        except (AttributeError, RuntimeError, TypeError):
            self._timer = None
        context.window_manager.modal_handler_add(self)
        self._tag_redraw(context)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self._prepare(context):
            return {"CANCELLED"}
        try:
            self._rebuild(context)
        except (AttributeError, RuntimeError, TypeError, ValueError,
                IndexError, ReferenceError) as error:
            self.report({"WARNING"}, f"重新分段失败：{error}")
            return self._cancel(context)
        self._cleanup()
        return {"FINISHED"}

    def modal(self, context, event):
        if context.active_object is not self._source_object:
            return self._cancel(context)
        if (
            event.type == "TIMER"
            and self._timer is not None
            and event.timer == self._timer
            and self._preview_dirty
        ):
            try:
                self._rebuild(context)
            except (AttributeError, RuntimeError, TypeError, ValueError,
                    IndexError, ReferenceError) as error:
                self.report({"WARNING"}, f"重新分段预览失败：{error}")
                return self._cancel(context)
            return {"RUNNING_MODAL"}
        if event.type in {"ESC", "RIGHTMOUSE"}:
            return self._cancel(context)
        if (
            event.type in {"RET", "NUMPAD_ENTER", "LEFTMOUSE", "SPACE"}
            and event.value == "PRESS"
        ):
            return self._finish(context)
        if event.type == "MOUSEMOVE":
            self._mouse_x = event.mouse_region_x
            self._mouse_y = event.mouse_region_y
            self._tag_redraw(context)
            return {"RUNNING_MODAL"}

        changed = False
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            direction = 1 if event.type == "WHEELUPMOUSE" else -1
            if event.alt:
                self.slide_strength = max(
                    0.0,
                    min(1.0, self.slide_strength + direction * 0.05),
                )
            elif event.ctrl:
                self.smoothness = max(
                    0.0,
                    min(1.0, self.smoothness + direction * 0.05),
                )
            elif not event.shift:
                self.segment_count = max(
                    1,
                    min(_MAX_SEGMENTS, self.segment_count + direction),
                )
            else:
                return {"PASS_THROUGH"}
            changed = True
        elif event.type == "R" and event.value == "PRESS":
            self.segment_count = self._descriptor.segment_count
            self.smoothness = _DEFAULT_SMOOTHNESS
            self.slide_strength = _DEFAULT_SLIDE_STRENGTH
            changed = True

        if changed:
            self._preview_dirty = True
            if self._timer is None:
                try:
                    self._rebuild(context)
                except (AttributeError, RuntimeError, TypeError, ValueError,
                        IndexError, ReferenceError) as error:
                    self.report({"WARNING"}, f"重新分段预览失败：{error}")
                    return self._cancel(context)
            self._tag_redraw(context)

        if event.type in {
            "MIDDLEMOUSE",
            "TRACKPADPAN",
            "TRACKPADZOOM",
            "NDOF_MOTION",
        } or event.type.startswith("NDOF"):
            return {"PASS_THROUGH"}
        return {"RUNNING_MODAL"}


class HO_OT_ResegmentLoops(_ResegmentOperatorBase):
    bl_idname = "ho.resegment_loops"
    bl_label = "重新分段（环线）"
    bl_description = (
        "固定所选最外侧环线，在连续四边面条带中重新分配中间环线"
    )
    selection_mode = "LOOPS"
    mode_label = "环线"


class HO_OT_ResegmentStrip(_ResegmentOperatorBase):
    bl_idname = "ho.resegment_strip"
    bl_label = "重新分段（竖边）"
    bl_description = (
        "选择目标四边面带内沿分段方向延伸的平行边链（可选整排/整圈）；"
        "自动识别两端横向环线并重新分配分段"
    )
    selection_mode = "STRIP"
    mode_label = "竖边"


RESEGMENT_CLASSES = (HO_OT_ResegmentLoops, HO_OT_ResegmentStrip)


__all__ = [
    "HO_OT_ResegmentLoops",
    "HO_OT_ResegmentStrip",
    "RESEGMENT_CLASSES",
    "cleanup_resegment_huds",
]
