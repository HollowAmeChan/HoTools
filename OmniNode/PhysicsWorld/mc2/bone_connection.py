"""MC2 BoneCloth transform connection -> proxy topology contract."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math


MC2_BONE_CONNECTION_LINE = 0
MC2_BONE_CONNECTION_AUTOMATIC = 1
MC2_BONE_CONNECTION_SEQUENTIAL_LOOP = 2
MC2_BONE_CONNECTION_SEQUENTIAL_NON_LOOP = 3
MC2_BONE_CONNECTION_MODES = (
    MC2_BONE_CONNECTION_LINE,
    MC2_BONE_CONNECTION_AUTOMATIC,
    MC2_BONE_CONNECTION_SEQUENTIAL_LOOP,
    MC2_BONE_CONNECTION_SEQUENTIAL_NON_LOOP,
)
HOTOOLS_BONE_CONNECTION_LINE = 0
HOTOOLS_BONE_CONNECTION_SEQUENTIAL = 1
HOTOOLS_BONE_CONNECTION_SEQUENTIAL_LOOP = 2
HOTOOLS_BONE_CONNECTION_MODES = (
    HOTOOLS_BONE_CONNECTION_LINE,
    HOTOOLS_BONE_CONNECTION_SEQUENTIAL,
    HOTOOLS_BONE_CONNECTION_SEQUENTIAL_LOOP,
)


def _signature(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _edge(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _triangle(a: int, b: int, c: int) -> tuple[int, int, int]:
    return tuple(sorted((a, b, c)))


def _distance(left, right) -> float:
    return math.sqrt(sum((a - b) * (a - b) for a, b in zip(left, right)))


def _length_squared(value) -> float:
    return sum(component * component for component in value)


def _automatic_root_order(positions, roots) -> tuple[tuple[int, ...], float]:
    pending = list(roots)
    ordered = [pending[0]]
    last_distance = 0.0
    while pending:
        current = ordered[-1]
        if current in pending:
            pending.remove(current)
        minimum_distance = math.inf
        minimum_root = None
        for root in pending:
            distance = _distance(positions[current], positions[root])
            if distance < minimum_distance:
                minimum_distance = distance
                minimum_root = root
        if minimum_root is None:
            continue
        if last_distance == 0.0 or minimum_distance < last_distance * 1.5:
            ordered.append(minimum_root)
            last_distance = (
                minimum_distance
                if last_distance == 0.0
                else (last_distance + minimum_distance) * 0.5
            )
        else:
            ordered.reverse()
            last_distance = 0.0
    return tuple(ordered), last_distance


@dataclass(frozen=True)
class MC2BoneConnectionSpec:
    connection_mode: int
    particle_count: int
    root_order: tuple[int, ...]
    source_vertex_order: tuple[int, ...]
    root_indices: tuple[int, ...]
    levels: tuple[int, ...]
    lines: tuple[tuple[int, int], ...]
    triangles: tuple[tuple[int, int, int], ...]
    topology_signature: str
    connection_model: str = "mc2_source"
    schema_version: int = 1

    def debug_dict(self, *, include_arrays: bool = False) -> dict:
        result = {
            "connection_mode": self.connection_mode,
            "particle_count": self.particle_count,
            "root_count": len(self.root_order),
            "line_count": len(self.lines),
            "triangle_count": len(self.triangles),
            "topology_signature": self.topology_signature,
            "connection_model": self.connection_model,
            "schema_version": self.schema_version,
        }
        if include_arrays:
            result.update({
                "root_order": self.root_order,
                "source_vertex_order": self.source_vertex_order,
                "root_indices": self.root_indices,
                "levels": self.levels,
                "lines": self.lines,
                "triangles": self.triangles,
            })
        return result


def build_mc2_bone_connection(
    positions,
    parent_indices,
    root_indices,
    connection_mode: int,
    *,
    child_indices=None,
) -> MC2BoneConnectionSpec:
    """Reproduce ``VirtualMesh.ImportBoneType`` topology membership.

    Array order is the MC2 transform/particle order.  Membership is canonicalized
    because the source stores the final sets in ``HashSet`` enumeration order.
    """

    connection_mode = int(connection_mode)
    if connection_mode not in MC2_BONE_CONNECTION_MODES:
        raise ValueError("MC2 Bone connection_mode must be in 0..3")
    positions = tuple(tuple(float(component) for component in value) for value in positions)
    parents = tuple(int(value) for value in parent_indices)
    roots = tuple(int(value) for value in root_indices)
    count = len(positions)
    if any(len(value) != 3 or not all(math.isfinite(component) for component in value) for value in positions):
        raise ValueError("MC2 Bone positions must be finite float3 values")
    if len(parents) != count:
        raise ValueError("MC2 Bone parent_indices length mismatch")
    if any(parent < -1 or parent >= count for parent in parents):
        raise ValueError("MC2 Bone parent index out of range")
    if not roots or len(set(roots)) != len(roots):
        raise ValueError("MC2 Bone root_indices must be non-empty and unique")
    if any(root < 0 or root >= count for root in roots):
        raise ValueError("MC2 Bone root index out of range")

    if child_indices is None:
        children = [[] for _ in range(count)]
        for index, parent in enumerate(parents):
            if parent >= 0:
                children[parent].append(index)
    else:
        children = [list(int(child) for child in values) for values in child_indices]
        if len(children) != count:
            raise ValueError("MC2 Bone child_indices length mismatch")
        listed_children: set[int] = set()
        for parent, values in enumerate(children):
            if len(set(values)) != len(values):
                raise ValueError("MC2 Bone child_indices contains duplicates")
            for child in values:
                if child < 0 or child >= count or parents[child] != parent:
                    raise ValueError("MC2 Bone child relation does not match parent_indices")
                if child in listed_children:
                    raise ValueError("MC2 Bone child is listed by multiple parents")
                listed_children.add(child)
        if listed_children != {index for index, parent in enumerate(parents) if parent >= 0}:
            raise ValueError("MC2 Bone child_indices does not cover every parent relation")

    source_vertex_order: list[int] = []
    source_stack = list(roots)
    while source_stack:
        index = source_stack.pop()
        source_vertex_order.append(index)
        source_stack.extend(children[index])
    if len(source_vertex_order) != count or len(set(source_vertex_order)) != count:
        raise ValueError("MC2 Bone roots/children do not form a complete forest")
    source_vertex_order_tuple = tuple(source_vertex_order)

    if connection_mode == MC2_BONE_CONNECTION_LINE:
        lines = tuple(sorted({_edge(index, parent) for index, parent in enumerate(parents) if parent >= 0}))
        payload = {
            "schema_version": 1,
            "connection_mode": connection_mode,
            "particle_count": count,
            "root_order": roots,
            "source_vertex_order": source_vertex_order_tuple,
            "root_indices": [-1] * count,
            "levels": [-1] * count,
            "lines": lines,
            "triangles": (),
        }
        return MC2BoneConnectionSpec(
            connection_mode=connection_mode,
            particle_count=count,
            root_order=roots,
            source_vertex_order=source_vertex_order_tuple,
            root_indices=tuple(payload["root_indices"]),
            levels=tuple(payload["levels"]),
            lines=lines,
            triangles=(),
            topology_signature=_signature(payload),
        )

    loop_connection = connection_mode == MC2_BONE_CONNECTION_SEQUENTIAL_LOOP
    sequential = connection_mode in (
        MC2_BONE_CONNECTION_SEQUENTIAL_LOOP,
        MC2_BONE_CONNECTION_SEQUENTIAL_NON_LOOP,
    )
    ordered_roots = roots
    last_distance = 0.0
    if connection_mode == MC2_BONE_CONNECTION_AUTOMATIC:
        ordered_roots, last_distance = _automatic_root_order(positions, roots)
        if len(ordered_roots) >= 3:
            end_distance = _distance(positions[ordered_roots[0]], positions[ordered_roots[-1]])
            if end_distance < last_distance * 1.5:
                loop_connection = True

    links = [[] for _ in range(count)]
    levels = [-1] * count
    vertex_roots = [-1] * count
    by_level: list[list[int]] = []
    main_edges: set[tuple[int, int]] = set()
    visited: set[int] = set()
    for root_order_index, root in enumerate(ordered_roots):
        stack = [(root, 0)]
        while stack:
            index, level = stack.pop()
            if index in visited:
                raise ValueError("MC2 Bone roots overlap or contain a cycle")
            visited.add(index)
            while len(by_level) <= level:
                by_level.append([])
            by_level[level].append(index)
            levels[index] = level
            vertex_roots[index] = root_order_index
            parent = parents[index]
            if parent >= 0:
                links[index].append(parent)
                main_edges.add(_edge(index, parent))
            for child in children[index]:
                stack.append((child, level + 1))
                links[index].append(child)
                main_edges.add(_edge(index, child))
    if len(visited) != count:
        raise ValueError("MC2 Bone roots do not cover every particle")

    last_root_index = len(ordered_roots) - 1
    for index in range(count):
        level = levels[index]
        candidates = by_level[level]
        root_index = vertex_roots[index]

        def allowed(other: int) -> bool:
            if other == index:
                return False
            other_root = vertex_roots[other]
            first_last = {root_index, other_root} == {0, last_root_index} and last_root_index > 0
            if not loop_connection and first_last:
                return False
            if sequential and not (loop_connection and first_last):
                return abs(root_index - other_root) <= 1
            return True

        first_distance = math.inf
        first_index = -1
        for other in candidates:
            if not allowed(other):
                continue
            distance = _distance(positions[index], positions[other])
            if distance < first_distance:
                first_distance = distance
                first_index = other
        if first_index < 0:
            continue
        links[index].append(first_index)
        limit = math.inf if sequential else first_distance * 1.5
        for other in candidates:
            if other == first_index or not allowed(other):
                continue
            if _distance(positions[index], positions[other]) <= limit:
                links[index].append(other)

    edges: set[tuple[int, int]] = set()
    triangle_edges: set[tuple[int, int]] = set()
    triangles: set[tuple[int, int, int]] = set()
    for index in source_vertex_order_tuple:
        linked = links[index]
        if len(linked) == 1:
            edges.add(_edge(index, linked[0]))
            continue
        for other in linked:
            edges.add(_edge(index, other))
        position = positions[index]
        for left_offset, left in enumerate(linked[:-1]):
            vector_left = tuple(positions[left][axis] - position[axis] for axis in range(3))
            for right in linked[left_offset + 1:]:
                vector_right = tuple(positions[right][axis] - position[axis] for axis in range(3))
                left_length = _length_squared(vector_left)
                right_length = _length_squared(vector_right)
                if left_length < 1.0e-6 or right_length < 1.0e-6:
                    continue
                cosine = sum(a * b for a, b in zip(vector_left, vector_right)) / math.sqrt(left_length * right_length)
                angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
                if angle >= 120.0:
                    continue
                root = vertex_roots[index]
                left_root = vertex_roots[left]
                right_root = vertex_roots[right]
                if left_root != root and right_root != root and left_root != right_root:
                    continue
                if not ({_edge(index, left), _edge(index, right), _edge(left, right)} & main_edges):
                    continue
                triangle = _triangle(index, left, right)
                if triangle not in triangles:
                    triangles.add(triangle)
                    triangle_edges.add(_edge(index, left))
                    triangle_edges.add(_edge(index, right))

    final_lines = tuple(sorted(edges - triangle_edges))
    final_triangles = tuple(sorted(triangles))
    payload = {
        "schema_version": 1,
        "connection_mode": connection_mode,
        "particle_count": count,
        "root_order": ordered_roots,
        "source_vertex_order": source_vertex_order_tuple,
        "root_indices": vertex_roots,
        "levels": levels,
        "lines": final_lines,
        "triangles": final_triangles,
    }
    return MC2BoneConnectionSpec(
        connection_mode=connection_mode,
        particle_count=count,
        root_order=ordered_roots,
        source_vertex_order=source_vertex_order_tuple,
        root_indices=tuple(vertex_roots),
        levels=tuple(levels),
        lines=final_lines,
        triangles=final_triangles,
        topology_signature=_signature(payload),
    )


def build_hotools_bone_connection(
    positions,
    parent_indices,
    chains,
    connection_mode: int,
) -> MC2BoneConnectionSpec:
    """Build HoTools' ordered-chain BoneCloth product topology.

    A task is one lateral group. Chain order is the node multi-input order and
    vertices at the same chain-local depth are connected pairwise.
    """

    connection_mode = int(connection_mode)
    if connection_mode not in HOTOOLS_BONE_CONNECTION_MODES:
        raise ValueError("HoTools Bone connection_mode must be in 0..2")
    position_values = tuple(
        tuple(float(component) for component in value)
        for value in positions
    )
    parents = tuple(int(value) for value in parent_indices)
    count = len(position_values)
    if len(parents) != count:
        raise ValueError("HoTools Bone parent_indices length mismatch")
    if any(
        len(value) != 3
        or not all(math.isfinite(component) for component in value)
        for value in position_values
    ):
        raise ValueError("HoTools Bone positions must be finite float3 values")
    if any(parent < -1 or parent >= count for parent in parents):
        raise ValueError("HoTools Bone parent index out of range")

    chain_values = tuple(tuple(int(vertex) for vertex in chain) for chain in chains)
    if not chain_values or any(not chain for chain in chain_values):
        raise ValueError("HoTools Bone chains must be non-empty")
    flattened = tuple(vertex for chain in chain_values for vertex in chain)
    if len(flattened) != count or set(flattened) != set(range(count)):
        raise ValueError("HoTools Bone chains must cover every particle exactly once")
    for chain in chain_values:
        if parents[chain[0]] >= 0:
            raise ValueError("HoTools Bone chain head must be parentless in the task")
        for depth, vertex in enumerate(chain[1:], start=1):
            if parents[vertex] != chain[depth - 1]:
                raise ValueError("HoTools Bone chain order must follow parent relations")

    roots = tuple(chain[0] for chain in chain_values)
    levels = [-1] * count
    vertex_roots = [-1] * count
    main_edges: set[tuple[int, int]] = set()
    for chain_index, chain in enumerate(chain_values):
        for depth, vertex in enumerate(chain):
            levels[vertex] = depth
            vertex_roots[vertex] = chain_index
            if depth:
                main_edges.add(_edge(chain[depth - 1], vertex))

    lateral_edges: set[tuple[int, int]] = set()

    def connect(left, right) -> None:
        for depth in range(min(len(left), len(right))):
            lateral_edges.add(_edge(left[depth], right[depth]))

    if connection_mode != HOTOOLS_BONE_CONNECTION_LINE:
        for chain_index in range(len(chain_values) - 1):
            connect(chain_values[chain_index], chain_values[chain_index + 1])
        if (
            connection_mode == HOTOOLS_BONE_CONNECTION_SEQUENTIAL_LOOP
            and len(chain_values) >= 3
        ):
            connect(chain_values[-1], chain_values[0])

    edges = main_edges | lateral_edges
    adjacency: list[list[int]] = [[] for _ in range(count)]
    for left, right in edges:
        adjacency[left].append(right)
        adjacency[right].append(left)

    triangles: set[tuple[int, int, int]] = set()
    if lateral_edges:
        for vertex, neighbors in enumerate(adjacency):
            ordered_neighbors = sorted(neighbors)
            position = position_values[vertex]
            for left_offset, left in enumerate(ordered_neighbors[:-1]):
                for right in ordered_neighbors[left_offset + 1:]:
                    if not (
                        _edge(vertex, left) in main_edges
                        or _edge(vertex, right) in main_edges
                    ):
                        continue
                    roots_in_triangle = {
                        vertex_roots[vertex],
                        vertex_roots[left],
                        vertex_roots[right],
                    }
                    if len(roots_in_triangle) == 3:
                        continue
                    left_vector = tuple(
                        position_values[left][axis] - position[axis]
                        for axis in range(3)
                    )
                    right_vector = tuple(
                        position_values[right][axis] - position[axis]
                        for axis in range(3)
                    )
                    left_length = _length_squared(left_vector)
                    right_length = _length_squared(right_vector)
                    if left_length <= 1.0e-12 or right_length <= 1.0e-12:
                        continue
                    cosine = sum(
                        left_value * right_value
                        for left_value, right_value in zip(left_vector, right_vector)
                    ) / math.sqrt(left_length * right_length)
                    angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
                    if angle < 120.0:
                        triangles.add(_triangle(vertex, left, right))

    payload = {
        "schema_version": 1,
        "connection_model": "hotools_product",
        "connection_mode": connection_mode,
        "particle_count": count,
        "root_order": roots,
        "source_vertex_order": flattened,
        "root_indices": vertex_roots,
        "levels": levels,
        "lines": tuple(sorted(edges)),
        "triangles": tuple(sorted(triangles)),
    }
    return MC2BoneConnectionSpec(
        connection_mode=connection_mode,
        particle_count=count,
        root_order=roots,
        source_vertex_order=flattened,
        root_indices=tuple(vertex_roots),
        levels=tuple(levels),
        lines=payload["lines"],
        triangles=payload["triangles"],
        topology_signature=_signature(payload),
        connection_model="hotools_product",
    )


__all__ = [
    "HOTOOLS_BONE_CONNECTION_LINE",
    "HOTOOLS_BONE_CONNECTION_MODES",
    "HOTOOLS_BONE_CONNECTION_SEQUENTIAL",
    "HOTOOLS_BONE_CONNECTION_SEQUENTIAL_LOOP",
    "MC2_BONE_CONNECTION_AUTOMATIC",
    "MC2_BONE_CONNECTION_LINE",
    "MC2_BONE_CONNECTION_MODES",
    "MC2_BONE_CONNECTION_SEQUENTIAL_LOOP",
    "MC2_BONE_CONNECTION_SEQUENTIAL_NON_LOOP",
    "MC2BoneConnectionSpec",
    "build_hotools_bone_connection",
    "build_mc2_bone_connection",
]
