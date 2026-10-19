"""Open UV chains and line constraints, independent of mesh tangents."""

from collections import defaultdict
from math import acos, atan2, cos, degrees, fsum, hypot, isfinite, sin

from .uv_math import checked_points


def trace_open_chains(edges):
    edges = {tuple(sorted(edge)) for edge in edges}
    adjacency = defaultdict(set)
    for a, b in edges:
        if a == b:
            raise ValueError('选中线包含零长拓扑边')
        adjacency[a].add(b)
        adjacency[b].add(a)
    if any(len(neighbors) > 2 for neighbors in adjacency.values()):
        raise ValueError('选中线存在分叉或交叉，请使用多条不相交的开链')
    chains = []
    remaining = set(edges)
    for start in sorted(v for v, neighbors in adjacency.items() if len(neighbors) == 1):
        edge = tuple(sorted((start, next(iter(adjacency[start])))))
        if edge not in remaining:
            continue
        chain, previous, current = [start], None, start
        while True:
            following = sorted(n for n in adjacency[current] if n != previous and tuple(sorted((n, current))) in remaining)
            if not following:
                break
            next_vertex = following[0]
            remaining.remove(tuple(sorted((current, next_vertex))))
            chain.append(next_vertex)
            previous, current = current, next_vertex
        chains.append(tuple(chain))
    if remaining:
        raise ValueError('闭环不能压成一条直线，请先选取开链')
    return tuple(chains)


def fit_line(points):
    points = checked_points(points)
    if len(points) < 2:
        raise ValueError('拟合直线至少需要两个 UV 点')
    center = tuple(sum(point[a] for point in points) / len(points) for a in (0, 1))
    xx = sum((p[0]-center[0])**2 for p in points)
    yy = sum((p[1]-center[1])**2 for p in points)
    xy = sum((p[0]-center[0])*(p[1]-center[1]) for p in points)
    if xx + yy <= 1e-24:
        raise ValueError('线的 UV 长度为零')
    angle = .5 * atan2(2*xy, xx-yy)
    direction = cos(angle), sin(angle)
    delta = points[-1][0]-points[0][0], points[-1][1]-points[0][1]
    if direction[0]*delta[0] + direction[1]*delta[1] < 0:
        direction = -direction[0], -direction[1]
    return center, direction


def distribute_chain_by_lengths(points, edge_lengths):
    """Straighten an ordered chain to its fixed endpoints using 3D edge ratios.

    Zero-length mesh edges collapse their UV segment. A fully zero-length mesh
    chain or coincident UV endpoints cannot define the requested ratio. Normalize
    lengths before summation so tiny/large object scales remain well conditioned.
    """
    points = checked_points(points)
    edge_lengths = tuple(edge_lengths)
    if len(points) < 2 or len(edge_lengths) != len(points)-1:
        raise ValueError('UV 开链点数与 3D 边长数量不匹配')
    if any(not isfinite(length) or length < 0 for length in edge_lengths):
        raise ValueError('3D 边长必须是有限非负数值')
    largest = max(edge_lengths)
    if largest == 0:
        raise ValueError('所选线的 3D 总长度为零')
    first, last = points[0], points[-1]
    if first == last:
        raise ValueError('UV 线的两端重合，无法保持端点并分配长度')
    normalized = tuple(length/largest for length in edge_lengths)
    total = fsum(normalized)
    result, accumulated = [first], 0.0
    for length in normalized[:-1]:
        accumulated += length
        t = accumulated/total
        result.append(tuple((1-t)*a+t*b for a, b in zip(first, last)))
    return tuple(result) + (last,)


def _axis_direction(direction, mode):
    if mode == 'KEEP':
        return direction
    axis = 0 if mode == 'U' or (mode == 'AUTO' and abs(direction[0]) >= abs(direction[1])) else 1
    sign = 1 if direction[axis] >= 0 else -1
    return (sign, 0) if axis == 0 else (0, sign)


def _project_joint_lines(frame, chains):
    """Alternate line fitting and shared-point projection until all lines agree.

    Triangulated grids have rows, columns AND diagonals; independently freezing
    their noisy fitted lines overconstrains intersections. Refit jointly instead.
    """
    current = list(frame)
    scale = max(hypot(max(p[0] for p in frame)-min(p[0] for p in frame),
                      max(p[1] for p in frame)-min(p[1] for p in frame)), 1e-12)
    members = sorted({v for chain in chains for v in chain})
    residual = float('inf')
    for _ in range(256):
        totals = {v: [0.0, 0.0, 0] for v in members}
        for chain in chains:
            center, direction = fit_line([current[v] for v in chain])
            for vertex in chain:
                x, y = current[vertex]
                along = (x-center[0])*direction[0]+(y-center[1])*direction[1]
                totals[vertex][0] += center[0]+direction[0]*along
                totals[vertex][1] += center[1]+direction[1]*along
                totals[vertex][2] += 1
        for vertex, (x, y, count) in totals.items():
            current[vertex] = x/count, y/count
        residual = 0.0
        for chain in chains:
            center, direction = fit_line([current[v] for v in chain])
            residual = max(residual, max(abs(direction[0]*(current[v][1]-center[1])-
                                              direction[1]*(current[v][0]-center[0])) for v in chain))
        if residual <= scale*1e-8:
            break
    if residual > scale*1e-6:
        raise ValueError('所选近直线无法同时收敛，请降低直化阈值')
    return {v: current[v] for v in members}


def _align_joint_lines(frame, chains):
    """Keep crossing/diagonal lines straight, then rotate their dominant frame.

    The fourth angular moment groups parallel AND perpendicular lines together.
    This keeps grid rows/columns dominant over a few long triangular diagonals.
    """
    constraints = _project_joint_lines(frame, chains)
    directions = []
    for chain in chains:
        points = [constraints[v] for v in chain]
        center, direction = fit_line(points)
        angle = atan2(direction[1], direction[0])
        weight = sum(hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(points, points[1:]))
        directions.append((center, direction, angle, weight))
    c4 = fsum(weight*cos(4*angle) for center, direction, angle, weight in directions)
    s4 = fsum(weight*sin(4*angle) for center, direction, angle, weight in directions)
    center, direction, angle, weight = max(directions, key=lambda item: (
        round(c4*cos(4*item[2])+s4*sin(4*item[2]), 10), item[3]))
    target = _axis_direction(direction, 'AUTO')
    rotation = atan2(target[1], target[0])-angle
    c, s = cos(rotation), sin(rotation)
    def rotate(point):
        x, y = point[0]-center[0], point[1]-center[1]
        return center[0]+c*x-s*y, center[1]+s*x+c*y
    return tuple(rotate(point) for point in frame), {v: rotate(point) for v, point in constraints.items()}


def line_constraints(coordinates, chains, mode='AUTO', preserve_lengths=True):
    """Rotate a stable UV frame, then constrain lines; return initial UVs + pins.

    Manual chains preserve arc lengths and cannot share vertices. Automatic
    lines project points and solve shared intersections jointly, so quad rows
    and columns can be straightened together without last-line-wins writes.
    """
    coordinates = checked_points(coordinates)
    if not chains or mode not in {'AUTO', 'U', 'V', 'KEEP'}:
        raise ValueError('没有可用开链或线方向无效')
    if any(len(chain) < 2 or any(not isinstance(v, int) or v < 0 or v >= len(coordinates) for v in chain)
           for chain in chains):
        raise ValueError('开链顶点索引或数量无效')
    def length(chain):
        return sum(hypot(coordinates[b][0]-coordinates[a][0], coordinates[b][1]-coordinates[a][1]) for a, b in zip(chain, chain[1:]))
    primary = max(chains, key=lambda chain: (length(chain), tuple(-v for v in chain)))
    center, original_direction = fit_line([coordinates[i] for i in primary])
    target_direction = _axis_direction(original_direction, mode)
    angle = atan2(target_direction[1], target_direction[0]) - atan2(original_direction[1], original_direction[0])
    c, s = cos(angle), sin(angle)
    frame = tuple((center[0]+c*(x-center[0])-s*(y-center[1]),
                   center[1]+s*(x-center[0])+c*(y-center[1])) for x, y in coordinates)
    if not preserve_lengths and mode == 'KEEP':
        return frame, _project_joint_lines(frame, chains)
    constraints, equations = {}, defaultdict(list)
    for chain in chains:
        points = [frame[i] for i in chain]
        midpoint, direction = fit_line(points)
        direction = _axis_direction(direction, mode)
        if preserve_lengths:
            distances = [0.0]
            for a, b in zip(points, points[1:]):
                distances.append(distances[-1]+hypot(b[0]-a[0], b[1]-a[1]))
            for vertex, distance in zip(chain, distances):
                target = tuple(midpoint[a]+direction[a]*(distance-distances[-1]*.5) for a in (0, 1))
                if vertex in constraints:
                    raise ValueError('手动线约束存在共享顶点，请拆成不相交开链')
                constraints[vertex] = target
        else:
            normal = -direction[1], direction[0]
            offset = normal[0]*midpoint[0]+normal[1]*midpoint[1]
            for vertex in chain:
                equations[vertex].append((*normal, offset))
    for vertex, rows in equations.items():
        x, y = frame[vertex]
        aa = sum(a*a for a, b, k in rows)
        ab = sum(a*b for a, b, k in rows)
        bb = sum(b*b for a, b, k in rows)
        ak = sum(a*k for a, b, k in rows)
        bk = sum(b*k for a, b, k in rows)
        det = aa*bb-ab*ab
        if det > 1e-12:
            target = ((ak*bb-bk*ab)/det, (bk*aa-ak*ab)/det)
        else:
            a, b, k = rows[0]
            shift = k-a*x-b*y
            target = x+a*shift, y+b*shift
        if any(abs(a*target[0]+b*target[1]-k) > 1e-6 for a, b, k in rows):
            if mode == 'AUTO' and not preserve_lengths:
                return _align_joint_lines(frame, chains)
            raise ValueError('多条直线约束不相容，请降低直化阈值')
        constraints[vertex] = target
    return frame, constraints


def ensure_orientation_anchor(frame, constraints, candidates=None):
    """Collinear pins have a reflection ambiguity; add one original-frame pin."""
    vertices = sorted(constraints)
    first = vertices[0]
    last = max(vertices, key=lambda v: hypot(constraints[v][0]-constraints[first][0], constraints[v][1]-constraints[first][1]))
    a, b = constraints[first], constraints[last]
    dx, dy = b[0]-a[0], b[1]-a[1]
    length = hypot(dx, dy)
    if length <= 1e-12:
        raise ValueError('约束退化，无法确定岛朝向')
    def distance(point):
        return abs(dx*(point[1]-a[1])-dy*(point[0]-a[0]))/length
    scale = max(hypot(p[0]-a[0], p[1]-a[1]) for p in frame)
    if any(distance(point) > max(scale*1e-7, 1e-12) for point in constraints.values()):
        return constraints
    candidates = [v for v in (range(len(frame)) if candidates is None else candidates) if v not in constraints]
    if not candidates:
        raise ValueError('所有顶点将被压到一条线，岛会退化')
    anchor = max(candidates, key=lambda v: (distance(frame[v]), -v))
    if distance(frame[anchor]) <= max(scale*1e-7, 1e-12):
        raise ValueError('岛没有可用的离线方向锚点')
    return {**constraints, anchor: frame[anchor]}


def ensure_region_anchors(frame, constraints, polygons, chains):
    """Anchor each free face region bounded by the pinned lines independently.

    A pinned internal line splits the parameterization into independent sides;
    an anchor on only one side cannot prevent the other side reflecting onto it.
    """
    edge_faces = defaultdict(list)
    for face_index, face in enumerate(polygons):
        for a, b in zip(face, face[1:] + face[:1]):
            edge_faces[tuple(sorted((a, b)))].append(face_index)
    barriers = {tuple(sorted(edge)) for chain in chains for edge in zip(chain, chain[1:])}
    adjacency = [set() for _ in polygons]
    for edge, linked in edge_faces.items():
        if edge not in barriers:
            for a in linked:
                adjacency[a].update(b for b in linked if b != a)
    remaining = set(range(len(polygons)))
    result = dict(constraints)
    while remaining:
        pending = [min(remaining)]
        vertices = set()
        while pending:
            face_index = pending.pop()
            if face_index not in remaining:
                continue
            remaining.remove(face_index)
            vertices.update(polygons[face_index])
            pending.extend(adjacency[face_index] & remaining)
        local = {v: result[v] for v in vertices if v in result}
        free = sorted(vertices - set(local))
        if len(local) >= 2 and free:
            result.update(ensure_orientation_anchor(frame, local, free))
    return result


def find_straight_chains(topology, angle_threshold=10.0, deviation_threshold=.005, include_internal=True):
    """Pair mutually nearest opposite edges, then reject globally curved chains.

    The deviation threshold is maximum perpendicular distance / total arc length.
    Local turns alone are insufficient: finely subdivided circles are rejected.
    """
    if not isfinite(angle_threshold) or not 0 <= angle_threshold <= 180 or not isfinite(deviation_threshold) or deviation_threshold < 0:
        raise ValueError('直化阈值必须是有效非负数值')
    coordinates = topology.coordinates
    edges = sorted(edge for edge, faces in topology.edge_faces.items() if include_internal or len(faces) == 1)
    neighbors = defaultdict(list)
    for a, b in edges:
        neighbors[a].append(b)
        neighbors[b].append(a)
    paired = {}
    for vertex, linked in neighbors.items():
        choices = {}
        for a in linked:
            ax, ay = coordinates[a][0]-coordinates[vertex][0], coordinates[a][1]-coordinates[vertex][1]
            options = []
            for b in linked:
                if a == b:
                    continue
                bx, by = coordinates[b][0]-coordinates[vertex][0], coordinates[b][1]-coordinates[vertex][1]
                denominator = hypot(ax, ay)*hypot(bx, by)
                if denominator <= 1e-24:
                    continue
                turn = degrees(acos(max(-1, min(1, -(ax*bx+ay*by)/denominator))))
                if turn <= angle_threshold:
                    options.append((turn, b))
            options.sort()
            if options and (len(options) == 1 or options[1][0]-options[0][0] > 1e-4):
                choices[a] = options[0][1]
        for a, b in choices.items():
            if choices.get(b) == a:
                paired[(a, vertex)] = b
    remaining = set(edges)
    chains = []
    for a, b in [(a, b) for a, b in edges] + [(b, a) for a, b in edges]:
        if (b, a) in paired or tuple(sorted((a, b))) not in remaining:
            continue
        chain = [a, b]
        remaining.remove(tuple(sorted((a, b))))
        while (chain[-2], chain[-1]) in paired:
            next_vertex = paired[(chain[-2], chain[-1])]
            edge = tuple(sorted((chain[-1], next_vertex)))
            if edge not in remaining:
                break
            remaining.remove(edge)
            chain.append(next_vertex)
        if len(chain) < 3:
            continue
        points = [coordinates[v] for v in chain]
        center, direction = fit_line(points)
        arc = sum(hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(points, points[1:]))
        deviation = max(abs(direction[0]*(p[1]-center[1])-direction[1]*(p[0]-center[0])) for p in points)
        # Reject closed/near-closed arcs even if local directions were paired.
        chord = hypot(points[-1][0]-points[0][0], points[-1][1]-points[0][1])
        if arc > 1e-12 and chord/arc > .9 and deviation/arc <= deviation_threshold:
            chains.append(tuple(chain))
    return tuple(chains)
