"""Deterministic 2D UV math, independent of Blender transform state."""

from math import floor, isfinite


def checked_points(points):
    points = tuple(tuple(point) for point in points)
    if not points:
        raise ValueError('没有选中的 UV')
    if any(len(point) != 2 or not all(isfinite(v) for v in point) for point in points):
        raise ValueError('UV 坐标必须是有限二维数值')
    return points


def bounds_center(points):
    points = checked_points(points)
    return tuple((min(p[a] for p in points) + max(p[a] for p in points)) * .5 for a in (0, 1))


def fit_points_to_tile(points, tile=(0, 0), margin=0.0):
    """Center the selection AABB, then maximize uniform scale inside a UV tile.

    Keep aspect and orientation. A zero-width/height line is valid; a single
    collapsed point is simply placed at the tile center without division by zero.
    """
    points = checked_points(points)
    if len(tile) != 2 or not all(isfinite(v) for v in tile) or not isfinite(margin) or not 0 <= margin < .5:
        raise ValueError('目标象限或边距无效')
    low = tuple(min(p[a] for p in points) for a in (0, 1))
    high = tuple(max(p[a] for p in points) for a in (0, 1))
    center = tuple((low[a]+high[a])*.5 for a in (0, 1))
    extent = max(high[a]-low[a] for a in (0, 1))
    scale = (1-2*margin)/extent if extent > 0 else 1.0
    return tuple(tuple(tile[a]+.5+(p[a]-center[a])*scale for a in (0, 1)) for p in points)


def unstack_offsets(islands, mode='HORIZONTAL', gap=.01):
    """Translations for ordered island coordinates; the first island stays put.

    AABB arrangement advances to each preceding island's far edge. TILE is the
    baking layout: every remaining island receives the SAME (+1, 0) translation,
    preserving their mutual overlap instead of stepping through successive tiles.
    """
    if mode not in {'HORIZONTAL', 'VERTICAL', 'TILE'} or not isfinite(gap) or gap < 0:
        raise ValueError('排列模式或间距无效')
    islands = tuple(checked_points(points) for points in islands)
    if not islands:
        raise ValueError('没有选中的 UV 岛')
    if mode == 'TILE':
        return ((0.0, 0.0),) + ((1.0, 0.0),)*(len(islands)-1)
    axis = 0 if mode == 'HORIZONTAL' else 1
    end = max(p[axis] for p in islands[0])
    offsets = [(0.0, 0.0)]
    for points in islands[1:]:
        low, high = min(p[axis] for p in points), max(p[axis] for p in points)
        shift = end+gap-low
        offsets.append((shift, 0.0) if axis == 0 else (0.0, shift))
        end = end+gap+(high-low)
    return tuple(offsets)


def mirror_points(points, axis, center):
    points = checked_points(points)
    if axis not in (0, 1) or len(center) != 2 or not all(isfinite(v) for v in center):
        raise ValueError('镜像轴或中心无效')
    return tuple(tuple(2 * center[a] - p[a] if a == axis else p[a] for a in (0, 1)) for p in points)


def mirror_in_tile(points, axis):
    """Mirror an entire island about the middle of its own integer UV tile.

    Boundary coordinates are allowed; islands crossing tiles are rejected rather
    than being assigned to a guessed tile. Negative UV tiles work identically.
    """
    points = checked_points(points)
    center = bounds_center(points)
    tile = tuple(floor(value) for value in center)
    if any(min(p[a] for p in points) < tile[a]-1e-6 or
           max(p[a] for p in points) > tile[a]+1+1e-6 for a in (0, 1)):
        raise ValueError('岛跨越多个 UV 象限')
    return mirror_points(points, axis, tuple(value+.5 for value in tile))


def translate_points(points, direction, distance, image_size=None):
    points = checked_points(points)
    directions = {'POS_U': (0, 1), 'NEG_U': (0, -1), 'POS_V': (1, 1), 'NEG_V': (1, -1)}
    if direction not in directions or not isfinite(distance) or distance < 0:
        raise ValueError('方向无效，或距离不是非负有限值')
    axis, sign = directions[direction]
    if image_size is not None:
        if len(image_size) != 2 or any(not isfinite(v) or v <= 0 for v in image_size):
            raise ValueError('像素平移需要有效的图像尺寸')
        distance /= image_size[axis]
    return tuple(tuple(p[a] + sign * distance if a == axis else p[a] for a in (0, 1)) for p in points)


def align_points(points, axis, method, cursor=None):
    points = checked_points(points)
    if axis not in (0, 1):
        raise ValueError('对齐轴无效')
    values = [p[axis] for p in points]
    if method == 'MIN':
        target = min(values)
    elif method == 'MAX':
        target = max(values)
    elif method == 'AVERAGE':
        target = sum(values) / len(values)
    elif method == 'ZERO':
        target = 0.0
    elif method == 'CURSOR' and cursor is not None and isfinite(cursor):
        target = cursor
    else:
        raise ValueError('对齐方式或 UV 光标坐标无效')
    return tuple(tuple(target if a == axis else p[a] for a in (0, 1)) for p in points)
