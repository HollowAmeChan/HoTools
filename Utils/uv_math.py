"""Deterministic 2D UV math, independent of Blender transform state."""

from math import isfinite


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


def mirror_points(points, axis, center):
    points = checked_points(points)
    if axis not in (0, 1) or len(center) != 2 or not all(isfinite(v) for v in center):
        raise ValueError('镜像轴或中心无效')
    return tuple(tuple(2 * center[a] - p[a] if a == axis else p[a] for a in (0, 1)) for p in points)


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
