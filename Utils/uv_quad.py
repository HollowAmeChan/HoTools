"""Rectangular quad bodies and centered triangle tips from 3D strip metrics.

No Blender or external addon dependency. Integer grid coordinates are propagated
across quad edges and checked globally before generating exact orthogonal rows.
"""

from collections import defaultdict, deque
from math import atan2, cos, fsum, hypot, isfinite, pi, sin, sqrt

from .uv_topology import IslandTopology, TopologyError


class QuadLayoutError(ValueError):
    """The quad body or its terminal triangle layout is incompatible."""


def quad_lattice(topology, seed=0):
    faces = topology.polygons
    if not 0 <= seed < len(faces) or any(len(face) != 4 for face in faces):
        raise QuadLayoutError('四边化需要完整的四边形 UV 岛')
    positions = dict(zip(faces[seed], ((0, 0), (1, 0), (1, 1), (0, 1))))
    visited, pending = {seed}, deque((seed,))
    while pending:
        index = pending.popleft()
        face = faces[index]
        center = tuple(sum(positions[v][axis] for v in face)/4 for axis in (0, 1))
        for a, b in zip(face, face[1:]+face[:1]):
            pa, pb = positions[a], positions[b]
            dx, dy = pb[0]-pa[0], pb[1]-pa[1]
            if abs(dx)+abs(dy) != 1:
                raise QuadLayoutError('四边形行列拓扑不相容')
            side = -dy*(center[0]-(pa[0]+pb[0])/2)+dx*(center[1]-(pa[1]+pb[1])/2)
            nx, ny = (dy, -dx) if side > 0 else (-dy, dx)
            for adjacent in topology.edge_faces[tuple(sorted((a, b)))]:
                if adjacent == index:
                    continue
                other = faces[adjacent]
                start = other.index(a)
                step = 1 if other[(start+1) % 4] == b else -1
                c, d = other[(start+2*step) % 4], other[(start+3*step) % 4]
                proposed = {a: pa, b: pb, c: (pb[0]+nx, pb[1]+ny), d: (pa[0]+nx, pa[1]+ny)}
                if any(v in positions and positions[v] != point for v, point in proposed.items()):
                    raise QuadLayoutError('四边形拓扑存在闭合冲突或极点，请切开 UV 后再四边化')
                positions.update(proposed)
                if adjacent not in visited:
                    visited.add(adjacent)
                    pending.append(adjacent)
    if len(positions) != len(topology.coordinates) or len(set(positions.values())) != len(positions):
        raise QuadLayoutError('四边形行列拓扑会产生重叠或断开')
    return tuple(positions[v] for v in range(len(topology.coordinates)))


def _area(points):
    origin = points[0]
    return fsum((a[0]-origin[0])*(b[1]-origin[1])-(a[1]-origin[1])*(b[0]-origin[0])
                for a, b in zip(points[1:], points[2:]))/2


def _quad_body(topology, seed):
    """Recognize terminal triangle fans attached to an edge-connected quad body.

    Every tip triangle has exactly one vertex outside the quad body. Its opposite
    edge must attach directly to a quad; interior triangulation is not a tip.
    """
    faces = topology.polygons
    quads = [i for i, face in enumerate(faces) if len(face) == 4]
    if not quads or any(len(face) not in (3, 4) for face in faces):
        raise QuadLayoutError('四边化需要四边形主体；末端允许三角尖端')
    if not 0 <= seed < len(faces):
        raise QuadLayoutError('四边化种子面无效')
    if len(quads) == len(faces):
        return topology, tuple(range(len(topology.coordinates))), seed, {}
    vertices = sorted({v for i in quads for v in faces[i]})
    members = set(vertices)
    tips = defaultdict(list)
    for i, face in enumerate(faces):
        if len(face) == 4:
            continue
        outside = set(face)-members
        if len(outside) != 1:
            raise QuadLayoutError('混合面不是附在四边形主体末端的三角尖端')
        tip = next(iter(outside))
        base = tuple(sorted(v for v in face if v != tip))
        attached = [f for f in topology.edge_faces[base] if len(faces[f]) == 4]
        if len(attached) != 1:
            raise QuadLayoutError('三角尖端的底边需要连接四边形主体')
        tips[tip].append((base, attached[0]))
    remap = {v: i for i, v in enumerate(vertices)}
    try:
        body = IslandTopology([topology.coordinates[v] for v in vertices],
                              [tuple(remap[v] for v in faces[i]) for i in quads])
    except TopologyError as exc:
        raise QuadLayoutError('尖端连接的四边形主体不连通') from exc
    body_seed = quads.index(seed) if seed in quads else 0
    return body, tuple(vertices), body_seed, tips


def _triangle_height(a, b, base):
    """3D altitude from side lengths, normalized before squaring."""
    largest = max(a, b, base)
    if largest <= 0 or base <= 0:
        raise ValueError('三角尖端存在零长 3D 底边')
    a, b, base = a/largest, b/largest, base/largest
    along = (a*a+base*base-b*b)/(2*base)
    height = sqrt(max(0.0, a*a-along*along))*largest
    if height <= largest*1e-12:
        raise ValueError('三角尖端的 3D 高度退化')
    return height


def _append_triangle_tips(topology, lattice, grid, tips, edge_lengths, largest):
    for tip, bases in tips.items():
        base_nodes = {v for edge, face in bases for v in edge}
        degrees = defaultdict(int)
        neighbors = defaultdict(set)
        for (a, b), face in bases:
            degrees[a] += 1
            degrees[b] += 1
            neighbors[a].add(b)
            neighbors[b].add(a)
        ends = [v for v in base_nodes if degrees[v] == 1]
        if len(ends) != 2 or any(degrees[v] > 2 for v in base_nodes):
            raise QuadLayoutError('三角尖端底边需要形成单条开链')
        reached, pending = set(), [ends[0]]
        while pending:
            node = pending.pop()
            if node not in reached:
                reached.add(node)
                pending.extend(neighbors[node]-reached)
        if reached != base_nodes:
            raise QuadLayoutError('同一三角尖点连接了不连续的底边')
        normal_axis = next((a for a in (0, 1) if len({lattice[v][a] for v in base_nodes}) == 1), None)
        if normal_axis is None:
            raise QuadLayoutError('三角尖端底边跨越了四边形主体的转角')
        midpoint = tuple((grid[ends[0]][a]+grid[ends[1]][a])/2 for a in (0, 1))
        sides, weights, heights = [], [], []
        for (a, b), face in bases:
            center = sum(grid[v][normal_axis] for v in topology.polygons[face])/4
            sides.append(1 if center > midpoint[normal_axis] else -1)
            base = edge_lengths[tuple(sorted((a, b)))]
            height = _triangle_height(edge_lengths[tuple(sorted((tip, a)))],
                                      edge_lengths[tuple(sorted((tip, b)))], base)
            weights.append(base/largest)
            heights.append(height/largest)
        if len(set(sides)) != 1:
            raise QuadLayoutError('三角尖端底边的四边形主体方向不一致')
        # Fan height = 2 * total 3D triangle area / total base arc length.
        height = fsum(w*h for w, h in zip(weights, heights))/fsum(weights)
        point = list(midpoint)
        point[normal_axis] -= sides[0]*height
        grid[tip] = tuple(point)


def quadrify_coordinates(topology, edge_lengths, seed=0, direction='KEEP', pins=None):
    """Rectify a quad body and center terminal triangle tips in one UV frame.

    edge_lengths maps each sorted UV-node edge to its 3D length. Opposite rows
    share averaged interval lengths, so varying 3D face shapes cannot bend a UV
    row. KEEP fits the old UV orientation; AUTO snaps that frame to the U/V axes.
    A terminal triangle/fan apex is centered over its straight base chain, with
    height from 3D triangle altitudes. Area/pose are preserved unless pins fix them.
    Original pin coordinates constrain one common similarity transform. An
    incompatible pin set is rejected instead of bending the rectangular result.
    """
    if direction not in {'KEEP', 'AUTO'}:
        raise ValueError('四边化方向无效')
    body, body_vertices, body_seed, tips = _quad_body(topology, seed)
    local_lattice = quad_lattice(body, body_seed)
    lattice = {v: point for v, point in zip(body_vertices, local_lattice)}
    body_edges = [tuple(sorted((body_vertices[a], body_vertices[b]))) for a, b in body.edge_faces]
    if any(edge not in edge_lengths or not isfinite(edge_lengths[edge]) or edge_lengths[edge] < 0
           for edge in topology.edge_faces):
        raise ValueError('四边化需要有效的 3D 网格边长')
    strips = (defaultdict(list), defaultdict(list))
    for edge in body_edges:
        a, b = (lattice[v] for v in edge)
        axis = 0 if a[0] != b[0] else 1
        length = edge_lengths.get(edge)
        if length is None or not isfinite(length) or length < 0:
            raise ValueError('四边化需要有效的 3D 网格边长')
        strips[axis][min(a[axis], b[axis])].append(length)
    largest = max(length for strip in strips for values in strip.values() for length in values)
    if largest == 0:
        raise ValueError('四边形网格的 3D 边长为零')
    levels = []
    for axis, strip in enumerate(strips):
        low = min(p[axis] for p in lattice.values())
        high = max(p[axis] for p in lattice.values())
        positions = {low: 0.0}
        for interval in range(low, high):
            values = strip.get(interval, ())
            width = fsum(value/largest for value in values)/len(values) if values else 0
            if width <= 0:
                raise ValueError('四边形行列存在零长或缺失的 3D 间隔')
            positions[interval+1] = positions[interval]+width
        levels.append(positions)
    grid = [None]*len(topology.coordinates)
    for v, (x, y) in lattice.items():
        grid[v] = levels[0][x], levels[1][y]
    _append_triangle_tips(topology, lattice, grid, tips, edge_lengths, largest)
    grid = tuple(grid)
    before = topology.coordinates
    original_area = fsum(abs(_area([before[v] for v in face])) for face in topology.polygons)
    grid_area = fsum(abs(_area([grid[v] for v in face])) for face in topology.polygons)
    seed_area = _area([before[body_vertices[v]] for v in body.polygons[body_seed]])
    if original_area <= 0 or grid_area <= 0 or seed_area == 0:
        raise ValueError('原 UV 面退化，无法保留四边化朝向')
    handedness = 1 if seed_area > 0 else -1
    pins = {} if pins is None else dict(pins)
    if any(not isinstance(v, int) or not 0 <= v < len(grid) or len(p) != 2 or
           not all(isfinite(value) for value in p) for v, p in pins.items()):
        raise ValueError('四边化固定点无效')
    anchors = sorted(pins) if len(pins) >= 2 else list(range(len(grid)))
    targets = pins if len(pins) >= 2 else dict(enumerate(before))
    center_grid = tuple(fsum(grid[v][a] for v in anchors)/len(anchors) for a in (0, 1))
    center_old = tuple(fsum(targets[v][a] for v in anchors)/len(anchors) for a in (0, 1))
    local = [(grid[v][0]-center_grid[0], handedness*(grid[v][1]-center_grid[1])) for v in anchors]
    reference = [(targets[v][0]-center_old[0], targets[v][1]-center_old[1]) for v in anchors]
    dot = fsum(x*u+y*v for (x, y), (u, v) in zip(local, reference))
    cross = fsum(x*v-y*u for (x, y), (u, v) in zip(local, reference))
    angle = atan2(cross, dot)
    if direction == 'AUTO':
        angle = round(angle/(pi/2))*(pi/2)
        c, s = round(cos(angle)), round(sin(angle))
    else:
        c, s = cos(angle), sin(angle)
    scale = sqrt(original_area/grid_area)
    if len(pins) >= 2:
        denominator = fsum(x*x+y*y for x, y in local)
        scale = fsum((c*x-s*y)*u+(s*x+c*y)*v for (x, y), (u, v) in zip(local, reference))/denominator
        if scale <= 0:
            raise ValueError('原固定点与四边化方向冲突；可取消尊重原固定点')
    result = tuple((center_old[0]+scale*(c*(x-center_grid[0])-s*handedness*(y-center_grid[1])),
                    center_old[1]+scale*(s*(x-center_grid[0])+c*handedness*(y-center_grid[1]))) for x, y in grid)
    if len(pins) == 1:
        vertex, target = next(iter(pins.items()))
        dx, dy = target[0]-result[vertex][0], target[1]-result[vertex][1]
        result = tuple((x+dx, y+dy) for x, y in result)
    extent = max(hypot(p[0]-before[0][0], p[1]-before[0][1]) for p in before)
    if any(hypot(result[v][0]-target[0], result[v][1]-target[1]) > max(extent*1e-6, 1e-8)
           for v, target in pins.items()):
        raise ValueError('原固定点与矩形行列冲突；可取消尊重原固定点')
    result = tuple(pins.get(v, point) for v, point in enumerate(result))
    if any(not isfinite(value) for point in result for value in point):
        raise ValueError('四边化产生无效 UV 坐标')
    for face in topology.polygons:
        if _area([before[v] for v in face])*_area([result[v] for v in face]) <= 0:
            raise ValueError('四边化会改变 UV 面朝向，已跳过该岛')
    return result
