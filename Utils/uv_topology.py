"""Pure-Python face-topology matching for forced UV vertex stacking.

No Blender transforms, mesh tangents, numpy, or coordinate-only welding. Shape
comparison allows rotation, reflection and uniform scale; the returned bijection
is then used to COPY every master coordinate, including interior vertices.
"""

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from math import atan2, cos, hypot, isfinite, sin, sqrt


class TopologyError(ValueError):
    pass


class MatchBudgetExceeded(RuntimeError):
    pass


class IslandTopology:
    def __init__(self, coordinates, polygons):
        self.coordinates = tuple(tuple(point) for point in coordinates)
        self.polygons = tuple(tuple(face) for face in polygons)
        if not self.coordinates or not self.polygons:
            raise TopologyError('空岛')
        if any(len(point) != 2 or not all(isfinite(value) for value in point) for point in self.coordinates):
            raise TopologyError('UV 坐标包含无效数值')
        self.edge_faces = defaultdict(list)
        self.neighbors = [set() for _ in self.coordinates]
        self.incident = [[] for _ in self.coordinates]
        for index, face in enumerate(self.polygons):
            if len(face) < 3 or len(set(face)) != len(face):
                raise TopologyError('岛包含退化面')
            for vertex in face:
                if vertex < 0 or vertex >= len(self.coordinates):
                    raise TopologyError('面顶点索引无效')
                self.incident[vertex].append(len(face))
            for a, b in zip(face, face[1:] + face[:1]):
                self.edge_faces[tuple(sorted((a, b)))].append(index)
                self.neighbors[a].add(b)
                self.neighbors[b].add(a)
        if any(len(faces) > 2 for faces in self.edge_faces.values()):
            raise TopologyError('岛包含非流形 UV 边')
        if any(not faces for faces in self.incident):
            raise TopologyError('岛包含孤立 UV 顶点')
        self.boundary_degree = [0] * len(self.coordinates)
        for (a, b), faces in self.edge_faces.items():
            if len(faces) == 1:
                self.boundary_degree[a] += 1
                self.boundary_degree[b] += 1
        # The propagation algorithm requires one edge-connected face component.
        reached, pending = set(), [0]
        while pending:
            face_index = pending.pop()
            if face_index in reached:
                continue
            reached.add(face_index)
            face = self.polygons[face_index]
            for a, b in zip(face, face[1:] + face[:1]):
                pending.extend(self.edge_faces[tuple(sorted((a, b)))])
        if len(reached) != len(self.polygons):
            raise TopologyError('岛不是沿 UV 边连通的单一组件')
        self.signature = (len(self.coordinates), len(self.edge_faces), len(self.polygons),
                          tuple(sorted(Counter(map(len, self.polygons)).items())),
                          tuple(sorted(Counter(self.boundary_degree).items())))


@dataclass(frozen=True)
class TopologyMatch:
    mapping: tuple  # source vertex -> master vertex
    error: float   # maximum border deviation / master border bbox diagonal
    reflected: bool
    rotation: float
    vertex_error: float  # all vertices: tie-break only, never blocks correction


def _colors(first, second):
    graphs = (first, second)
    keys = [[(len(g.neighbors[i]), g.boundary_degree[i], tuple(sorted(g.incident[i])))
             for i in range(len(g.coordinates))] for g in graphs]
    for _ in range(7):
        palette = {key: index for index, key in enumerate(sorted(set(keys[0] + keys[1])))}
        colors = [[palette[key] for key in group] for group in keys]
        keys = [[(colors[j][i], tuple(sorted(colors[j][n] for n in g.neighbors[i])))
                 for i in range(len(g.coordinates))] for j, g in enumerate(graphs)]
    return colors


def _polygon_alignment(face, a, b):
    """Order an adjacent face starting with the specified directed edge."""
    index = face.index(a)
    if face[(index + 1) % len(face)] == b:
        return tuple(face[(index + offset) % len(face)] for offset in range(len(face)))
    if face[(index - 1) % len(face)] == b:
        return tuple(face[(index - offset) % len(face)] for offset in range(len(face)))
    return None


def _propagate(source, master, root, destination, seed, source_colors, master_colors, budget):
    mapping, reverse, face_map, reverse_faces = {}, {}, {}, {}
    pending = deque([(root, destination, source.polygons[root], seed)])
    while pending:
        a_face, b_face, a_order, b_order = pending.popleft()
        budget[0] -= len(a_order)
        if budget[0] < 0:
            raise MatchBudgetExceeded('拓扑匹配达到工作量上限，请缩小选区')
        if a_face in face_map:
            if face_map[a_face] != b_face or any(mapping[a] != b for a, b in zip(a_order, b_order)):
                return None
            continue
        if b_face in reverse_faces or len(a_order) != len(b_order):
            return None
        for a, b in zip(a_order, b_order):
            if source_colors[a] != master_colors[b] or mapping.get(a, b) != b or reverse.get(b, a) != a:
                return None
            mapping[a], reverse[b] = b, a
        face_map[a_face], reverse_faces[b_face] = b_face, a_face
        for a, b in zip(a_order, a_order[1:] + a_order[:1]):
            other_a = [f for f in source.edge_faces[tuple(sorted((a, b)))] if f != a_face]
            other_b = [f for f in master.edge_faces[tuple(sorted((mapping[a], mapping[b])))] if f != b_face]
            if len(other_a) != len(other_b):
                return None
            if other_a:
                next_a, next_b = other_a[0], other_b[0]
                order_a = _polygon_alignment(source.polygons[next_a], a, b)
                order_b = _polygon_alignment(master.polygons[next_b], mapping[a], mapping[b])
                if order_a is None or order_b is None:
                    return None
                pending.append((next_a, next_b, order_a, order_b))
    if len(mapping) != len(source.coordinates) or len(face_map) != len(source.polygons):
        return None
    return tuple(mapping[index] for index in range(len(source.coordinates)))


def _shape_match(source, master, mapping):
    # Identify shape using the border; displaced interior vertices are exactly
    # what topology copying is meant to fix. All vertices still affect tie-breaks.
    samples = [i for i, degree in enumerate(source.boundary_degree) if degree] or list(range(len(mapping)))
    count = len(samples)
    src_center = tuple(sum(source.coordinates[i][axis] for i in samples) / count for axis in (0, 1))
    dst_center = tuple(sum(master.coordinates[mapping[i]][axis] for i in samples) / count for axis in (0, 1))
    src = [(p[0] - src_center[0], p[1] - src_center[1]) for p in source.coordinates]
    dst = [(master.coordinates[i][0] - dst_center[0], master.coordinates[i][1] - dst_center[1]) for i in mapping]
    src_radius = sqrt(sum(src[i][0]**2 + src[i][1]**2 for i in samples) / count)
    dst_radius = sqrt(sum(dst[i][0]**2 + dst[i][1]**2 for i in samples) / count)
    diagonal = hypot(*(max(master.coordinates[mapping[i]][a] for i in samples) -
                       min(master.coordinates[mapping[i]][a] for i in samples) for a in (0, 1)))
    if min(src_radius, dst_radius, diagonal) <= 1e-15:
        return None
    scale = dst_radius / src_radius
    results = []
    for sign in (1, -1):
        dot = sum(src[i][0]*dst[i][0] + sign*src[i][1]*dst[i][1] for i in samples)
        cross = sum(src[i][0]*dst[i][1] - sign*src[i][1]*dst[i][0] for i in samples)
        angle = atan2(cross, dot)
        c, s = cos(angle), sin(angle)
        errors = [hypot(scale*(c*x - s*sign*y) - u, scale*(s*x + c*sign*y) - v) / diagonal
                  for (x, y), (u, v) in zip(src, dst)]
        error = max(errors[i] for i in samples)
        vertex_error = sqrt(sum(value*value for value in errors) / len(errors))
        results.append(TopologyMatch(mapping, error, sign == -1, angle, vertex_error))
    return min(results, key=_match_score)


def _match_score(match):
    # Treat floating-point-equivalent fits alike; symmetric ties prefer the
    # smallest orientation change, then a non-reflected mapping, then stable IDs.
    return (round(match.error, 12), round(match.vertex_error, 12), abs(match.rotation), match.reflected, match.mapping)


def match_islands(source, master, tolerance=0.05, max_work=500000):
    """Return a face-preserving bijection, or None for topology/shape mismatch.

    tolerance is relative to master border bbox diagonal after normalization.
    It gates border identification only: all interior vertices are forcibly copied.
    Budget exhaustion raises rather than silently claiming no match exists.
    """
    if not isfinite(tolerance) or tolerance < 0:
        raise ValueError('形状容差必须是非负有限值')
    if source.signature != master.signature:
        return None
    source_colors, master_colors = _colors(source, master)
    if Counter(source_colors) != Counter(master_colors):
        return None
    master_faces = defaultdict(list)
    for index, face in enumerate(master.polygons):
        master_faces[(len(face), tuple(sorted(master_colors[v] for v in face)))].append(index)
    root = min(range(len(source.polygons)), key=lambda i: (
        len(master_faces[(len(source.polygons[i]), tuple(sorted(source_colors[v] for v in source.polygons[i])))]), i))
    root_face = source.polygons[root]
    candidates = master_faces[(len(root_face), tuple(sorted(source_colors[v] for v in root_face)))]
    best, budget = None, [max_work]
    for destination in candidates:
        face = master.polygons[destination]
        for sign in (1, -1):
            for offset in range(len(face)):
                seed = tuple(face[(offset + sign * i) % len(face)] for i in range(len(face)))
                if any(source_colors[a] != master_colors[b] for a, b in zip(root_face, seed)):
                    continue
                mapping = _propagate(source, master, root, destination, seed, source_colors, master_colors, budget)
                if mapping is None:
                    continue
                match = _shape_match(source, master, mapping)
                if match is not None and match.error <= tolerance + 1e-12 and (best is None or _match_score(match) < _match_score(best)):
                    best = match
    return best
