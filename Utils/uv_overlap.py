"""UV overlap workspaces: connected groups of triangles with shared area."""

from math import hypot, isfinite


def _bounds(points):
    return (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))


def _boxes_overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _triangles_overlap(a, b, tolerance):
    # Strict separating-axis test: touching borders/vertices share no UV area.
    # Translate the projections to avoid cancellation in distant UDIM tiles.
    origin = a[0]
    for triangle in (a, b):
        for first, last in zip(triangle, triangle[1:]+triangle[:1]):
            dx, dy = last[0]-first[0], last[1]-first[1]
            length = hypot(dx, dy)
            if length == 0:
                continue
            nx, ny = -dy/length, dx/length
            pa = [nx*(p[0]-origin[0])+ny*(p[1]-origin[1]) for p in a]
            pb = [nx*(p[0]-origin[0])+ny*(p[1]-origin[1]) for p in b]
            if min(max(pa), max(pb))-max(min(pa), min(pb)) <= tolerance:
                return False
    return True


def overlap_workspaces(triangle_groups, epsilon=1e-9):
    """Return stable island-index groups connected by positive-area overlap.

    Each input group is one island's triangulated UV faces. AABB is only a broad
    phase; triangulation preserves concave islands and holes. A overlaps B and B
    overlaps C puts all three in one workspace. A standalone island is a valid
    one-member workspace. Degenerate triangles have no area and cannot join it.
    epsilon is relative to the two islands' extent, independent of UV scale.
    """
    if not isfinite(epsilon) or epsilon < 0:
        raise ValueError('UV 重叠容差必须是有限非负数值')
    prepared, boxes = [], []
    for triangles in triangle_groups:
        items = []
        for triangle in triangles:
            triangle = tuple(tuple(p) for p in triangle)
            if len(triangle) != 3 or any(len(p) != 2 or not all(isfinite(v) for v in p) for p in triangle):
                raise ValueError('UV 重叠检测需要有效的二维三角面')
            a, b, c = triangle
            if (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]) != 0:
                items.append((triangle, _bounds(triangle)))
        prepared.append(items)
        boxes.append(_bounds([p for triangle, box in items for p in triangle]) if items else None)
    parents = list(range(len(prepared)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    sweep = sorted((i for i, box in enumerate(boxes) if box is not None), key=lambda i: (boxes[i][0], i))
    for position, i in enumerate(sweep):
        a = boxes[i]
        for next_position in range(position+1, len(sweep)):
            j = sweep[next_position]
            b = boxes[j]
            if b[0] >= a[2]:
                break
            if root(i) == root(j) or not _boxes_overlap(a, b):
                continue
            tolerance = epsilon*max(a[2]-a[0], a[3]-a[1], b[2]-b[0], b[3]-b[1])
            if any(_boxes_overlap(ta_box, tb_box) and _triangles_overlap(ta, tb, tolerance)
                   for ta, ta_box in prepared[i] for tb, tb_box in prepared[j]):
                parents[root(j)] = root(i)
    groups = {}
    for index in range(len(prepared)):
        groups.setdefault(root(index), []).append(index)
    return tuple(sorted((tuple(group) for group in groups.values()), key=lambda group: group[0]))
