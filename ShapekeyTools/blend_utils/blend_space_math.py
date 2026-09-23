"""形态键混合矩阵的纯数学核心。

这个模块只依赖标准库，不导入 bpy / numpy，因此可以被 Blender 之外的单元测试
直接导入。它负责矩阵调试里最容易出错、也最需要独立的两个算法：

1. 二维 Delaunay 三角剖分（Bowyer-Watson 增量插入 + 虚拟超级三角形）；
2. 由坐标点集与当前输入坐标求各点的混合权重。

权重语义对齐 Unity 的混合树（Blend Tree）：

- ``CARTESIAN_2D``（2D 自由形式笛卡尔）：坐标点做 Delaunay 剖分，输入点落在某个
  三角形内时用重心坐标插值（三角形外按最近边界投影），即 Unity 的
  ``ComputeWeightsFreeformCartesian2D``；
- ``SIMPLE_1D``（1D 简单混合）：按第一参数排序后只在相邻两点之间插值；
- ``DIRECTIONAL_2D``（2D 自由形式方向）：按坐标点相对原点的角度分区，输入角度落在
  相邻两点之间时按角度比例插值，半径方向做衰减，即 Unity 的
  ``ComputeWeightsFreeformDirectional2D``。
"""

from __future__ import annotations

import math

__all__ = (
    "BLEND_MODE_ITEMS",
    "BlendSpaceError",
    "MODE_CARTESIAN_2D",
    "MODE_DIRECTIONAL_2D",
    "MODE_SIMPLE_1D",
    "barycentric_weights",
    "blend_weights",
    "blend_weights_cartesian_2d",
    "blend_weights_directional_2d",
    "blend_weights_simple_1d",
    "find_nearest_edge",
    "pixel_to_uv",
    "plot_axis_range",
    "point_in_triangle",
    "triangulate2d",
    "triangulate_points",
    "uv_to_pixel",
)

# region 常量

MODE_SIMPLE_1D = 'SIMPLE_1D'
MODE_CARTESIAN_2D = 'CARTESIAN_2D'
MODE_DIRECTIONAL_2D = 'DIRECTIONAL_2D'

BLEND_MODE_ITEMS = (
    (MODE_CARTESIAN_2D, "2D 笛卡尔",
     "Delaunay 三角剖分 + 重心插值（Unity 2D Freeform Cartesian）"),
    (MODE_DIRECTIONAL_2D, "2D 方向",
     "按角度分区插值 + 半径衰减（Unity 2D Freeform Directional）"),
    (MODE_SIMPLE_1D, "1D 简单", "只在第一参数方向上的相邻两点之间插值"),
)

DUPLICATE_EPSILON = 1e-6
INSIDE_EPSILON = 1e-9
_EDGE_PARALLEL_EPSILON = 1e-12


class BlendSpaceError(ValueError):
    """混合矩阵的坐标点集不合法时抛出。"""


# endregion


# region 三角剖分


def _cross(ax, ay, bx, by):
    return ax * by - ay * bx


def _deduplicate(points, epsilon=DUPLICATE_EPSILON):
    """按容差去重，返回 ``(唯一点列表, 原下标 -> 唯一下标)``。"""
    unique = []
    source = []
    scale = max((abs(float(x)) for point in points for x in point[:2]), default=0.0)
    tolerance = max(epsilon, epsilon * scale)
    for index, point in enumerate(points):
        x, y = float(point[0]), float(point[1])
        if not (math.isfinite(x) and math.isfinite(y)):
            raise BlendSpaceError(f"第 {index + 1} 个坐标包含非法数值")
        for unique_index, (ux, uy) in enumerate(unique):
            if abs(ux - x) <= tolerance and abs(uy - y) <= tolerance:
                source.append(unique_index)
                break
        else:
            source.append(len(unique))
            unique.append((x, y))
    return unique, source


def _super_triangle(points):
    """构造一定包含全部点的逆时针超级三角形。"""
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    minimum_x, maximum_x = min(xs), max(xs)
    minimum_y, maximum_y = min(ys), max(ys)
    center_x = (minimum_x + maximum_x) * 0.5
    center_y = (minimum_y + maximum_y) * 0.5
    span = max(maximum_x - minimum_x, maximum_y - minimum_y, 1e-6)
    # 顺序必须是 (左下, 右下, 上)，叉积为正，剖分结果才是逆时针三角形。
    return (
        (center_x - 32.0 * span, center_y - 16.0 * span),
        (center_x + 32.0 * span, center_y - 16.0 * span),
        (center_x, center_y + 32.0 * span),
    )


def _circumcircle_contains(triangle, points, px, py, epsilon):
    """用外接圆行列式判断点是否落在三角形外接圆内。"""
    (ax, ay), (bx, by), (cx, cy) = (points[i] for i in triangle)
    determinant = _cross(bx - ax, by - ay, cx - ax, cy - ay)
    if abs(determinant) <= _EDGE_PARALLEL_EPSILON:
        return False
    axx, ayy = ax - px, ay - py
    bxx, byy = bx - px, by - py
    cxx, cyy = cx - px, cy - py
    a_square = axx * axx + ayy * ayy
    b_square = bxx * bxx + byy * byy
    c_square = cxx * cxx + cyy * cyy
    numerator = (
        a_square * _cross(bxx, byy, cxx, cyy)
        - b_square * _cross(axx, ayy, cxx, cyy)
        + c_square * _cross(axx, ayy, bxx, byy)
    )
    return numerator * determinant > -epsilon


def _hull_triangles(unique, source):
    """Bowyer-Watson 增量插入，返回按原下标表示的逆时针三角形。"""
    super_a, super_b, super_c = _super_triangle(unique)
    working = list(unique) + [super_a, super_b, super_c]
    offset = len(unique)
    triangles = [(offset, offset + 1, offset + 2)]
    scale = max((abs(x) for point in unique for x in point), default=1.0)
    epsilon = 1e-12 * scale * scale

    for point_index in range(len(unique)):
        px, py = working[point_index]
        bad_flags = [
            _circumcircle_contains(triangle, working, px, py, epsilon)
            for triangle in triangles
        ]
        if not any(bad_flags):
            continue

        # 只把「正向」边交给空腔重建：内部边在两个坏三角形里各出现一次（方向相反，
        # 互相抵消），剩下单向出现的就是空腔边界，且方向天然保证新三角形为逆时针。
        boundary = {}
        for triangle, is_bad in zip(triangles, bad_flags):
            if not is_bad:
                continue
            a, b, c = triangle
            for edge in ((a, b), (b, c), (c, a)):
                reverse = (edge[1], edge[0])
                if boundary.pop(reverse, None) is None:
                    boundary[edge] = True

        kept = [
            triangle for triangle, is_bad in zip(triangles, bad_flags)
            if not is_bad
        ]
        triangles.clear()
        triangles.extend(kept)
        for a, b in boundary:
            if len({a, b, point_index}) != 3:
                continue
            (ax, ay), (bx, by) = working[a], working[b]
            if abs(_cross(bx - ax, by - ay,
                          px - ax, py - ay)) <= _EDGE_PARALLEL_EPSILON:
                # 三点共线时丢弃，避免把退化三角形留在结果里。
                continue
            triangles.append((a, b, point_index))

    kept = [
        triangle for triangle in triangles
        if all(index < offset for index in triangle)
    ]
    return [tuple(source[index] for index in triangle) for triangle in kept]


def triangulate2d(points, *, epsilon=DUPLICATE_EPSILON):
    """对二维点集做 Delaunay 三角剖分。

    参数 ``points`` 为 ``((u, v), ...)``。返回 ``(unique, triangles)``：

    - ``unique``：去重后的唯一点坐标，按首次出现顺序；
    - ``triangles``：三角形的 ``(i, j, k)``，下标指向 ``unique``，且为逆时针。

    点数少于 3 或全部共线时返回空三角形列表（调用方按最近边界处理）。
    """
    coordinates = [(float(point[0]), float(point[1])) for point in points]
    unique, _ = _deduplicate(coordinates, epsilon)
    if len(unique) < 3:
        return unique, []
    return unique, _hull_triangles(unique, list(range(len(unique))))


def triangulate_points(points, *, epsilon=DUPLICATE_EPSILON):
    """与 :func:`triangulate2d` 相同，但保留「原下标 -> 唯一下标」的映射。

    返回 ``(unique, triangles, indices)``。
    """
    coordinates = [(float(point[0]), float(point[1])) for point in points]
    unique, source = _deduplicate(coordinates, epsilon)
    if len(unique) < 3:
        return unique, [], source
    return unique, _hull_triangles(unique, source), source


# endregion


# region 权重


def _triangle_double_area(ax, ay, bx, by, cx, cy):
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def point_in_triangle(px, py, a, b, c, *, epsilon=INSIDE_EPSILON):
    """返回点是否在三角形内（含边界），三角形需为逆时针。"""
    ax, ay = a
    bx, by = b
    cx, cy = c
    total = _triangle_double_area(ax, ay, bx, by, cx, cy)
    if abs(total) <= _EDGE_PARALLEL_EPSILON:
        return False
    sign = 1.0 if total > 0.0 else -1.0
    tolerance = -epsilon * abs(total)
    for (x1, y1), (x2, y2) in ((a, b), (b, c), (c, a)):
        if (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1) < tolerance * sign:
            return False
    return True


def barycentric_weights(px, py, a, b, c):
    """返回点相对三角形的重心权重 ``(wa, wb, wc)``，全为零表示退化三角形。"""
    ax, ay = a
    bx, by = b
    cx, cy = c
    denominator = _triangle_double_area(ax, ay, bx, by, cx, cy)
    if abs(denominator) <= _EDGE_PARALLEL_EPSILON:
        return 0.0, 0.0, 0.0
    weight_a = ((bx - px) * (cy - py) - (by - py) * (cx - px)) / denominator
    weight_b = ((cx - px) * (ay - py) - (cy - py) * (ax - px)) / denominator
    return weight_a, weight_b, 1.0 - weight_a - weight_b


def find_nearest_edge(points, px, py):
    """返回 ``(i, j, t)``：最近边的两端点下标与其上的投影比例。"""
    best = None
    best_distance = None
    for index in range(len(points)):
        ax, ay = points[index]
        bx, by = points[(index + 1) % len(points)]
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        if length_squared <= _EDGE_PARALLEL_EPSILON:
            t = 0.0
        else:
            t = ((px - ax) * dx + (py - ay) * dy) / length_squared
            t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        qx = ax + dx * t
        qy = ay + dy * t
        distance = (px - qx) ** 2 + (py - qy) ** 2
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best = (index, (index + 1) % len(points), t)
    if best is None:
        return None
    return best


def _hull_edges(triangles):
    """从三角形列表里取出只出现一次的边（凸包边界）。"""
    counter = {}
    for triangle in triangles:
        for edge in ((triangle[0], triangle[1]),
                     (triangle[1], triangle[2]),
                     (triangle[2], triangle[0])):
            key = (edge[0], edge[1]) if edge[0] < edge[1] else (edge[1], edge[0])
            counter[key] = counter.get(key, 0) + 1
    return [edge for edge, count in counter.items() if count == 1]


def _normalize(weights):
    total = sum(weights)
    if total <= 0.0:
        return [0.0] * len(weights)
    return [value / total for value in weights]


def _inside_any(u, v, unique, triangles):
    for i, j, k in triangles:
        if point_in_triangle(u, v, unique[i], unique[j], unique[k]):
            return True
    return False


def _barycentric_spread(u, v, unique, triangles):
    """落在某个三角形内时，返回该三角形三顶点的重心权重向量。"""
    for i, j, k in triangles:
        a, b, c = unique[i], unique[j], unique[k]
        if not point_in_triangle(u, v, a, b, c):
            continue
        wa, wb, wc = barycentric_weights(u, v, a, b, c)
        return _normalize([
            max(0.0, wa) if index == i else
            max(0.0, wb) if index == j else
            max(0.0, wc) if index == k else 0.0
            for index in range(len(unique))
        ])
    return None


def _snap_to_hull(u, v, unique, triangles):
    """凸包外时投影到最近的凸包边，返回权重向量。"""
    hull = _hull_edges(triangles)
    hull_points = sorted({index for edge in hull for index in edge})
    if len(hull_points) < 2:
        return None
    edge = find_nearest_edge([unique[index] for index in hull_points], u, v)
    if edge is None:
        return None
    edge_start, edge_end, t = edge
    weights = [0.0] * len(unique)
    weights[hull_points[edge_start]] = 1.0 - t
    weights[hull_points[edge_end]] = t
    return _normalize(weights)


def blend_weights_cartesian_2d(points, u, v):
    """Unity ``ComputeWeightsFreeformCartesian2D`` 的等价实现。

    输入点落在剖分三角形内 → 重心插值；落在凸包外 → 投影到最近的凸包边。
    """
    unique, triangles = triangulate2d(points)
    if not unique:
        return []
    if not triangles:
        return blend_weights_simple_1d(points, u, v)

    u = float(u)
    v = float(v)
    spread = _barycentric_spread(u, v, unique, triangles)
    if spread is not None:
        return spread
    snapped = _snap_to_hull(u, v, unique, triangles)
    if snapped is not None:
        return snapped
    return _normalize([1.0 if index == 0 else 0.0 for index in range(len(unique))])


def blend_weights_directional_2d(points, u, v):
    """Unity ``ComputeWeightsFreeformDirectional2D`` 的等价实现。

    凸包内仍是重心插值；凸包外按相对原点的角度在相邻两点之间插值，
    半径超出该角度上的参考半径时整体衰减（参考 Unity 的 ``ComputeWeights``）。
    """
    unique, triangles = triangulate2d(points)
    if not unique:
        return []
    if not triangles:
        return blend_weights_simple_1d(points, u, v)

    u = float(u)
    v = float(v)
    if _inside_any(u, v, unique, triangles):
        spread = _barycentric_spread(u, v, unique, triangles)
        if spread is not None:
            return spread

    input_angle = math.atan2(v, u)
    input_radius = math.hypot(u, v)
    hull = sorted({index for edge in _hull_edges(triangles) for index in edge})
    if len(hull) < 2:
        return blend_weights_simple_1d(points, u, v)
    sectors = []
    for index in hull:
        px, py = unique[index]
        sectors.append((math.atan2(py, px), math.hypot(px, py), index))
    sectors.sort()

    weights = [0.0] * len(unique)
    count = len(sectors)
    for position in range(count):
        angle_a, radius_a, index_a = sectors[position]
        angle_b, radius_b, index_b = sectors[(position + 1) % count]
        span = angle_b - angle_a
        if position == count - 1:
            span += 2.0 * math.pi
        if span <= 0.0:
            continue
        delta = input_angle - angle_a
        while delta < 0.0:
            delta += 2.0 * math.pi
        while delta >= 2.0 * math.pi:
            delta -= 2.0 * math.pi
        if delta > span:
            continue
        blend = delta / span
        reference_radius = radius_a + (radius_b - radius_a) * blend
        if input_radius <= reference_radius:
            weights[index_a] += 1.0 - blend
            weights[index_b] += blend
        else:
            # 超出参考半径：按「参考半径到较近点半径」的距离线性衰减到 0。
            margin = reference_radius - min(radius_a, radius_b)
            scale = 1.0 - (input_radius - reference_radius) / (2.0 * margin) \
                if margin > _EDGE_PARALLEL_EPSILON else 0.0
            scale = max(0.0, min(1.0, scale))
            weights[index_a] += (1.0 - blend) * scale
            weights[index_b] += blend * scale
    if not any(weights):
        snapped = _snap_to_hull(u, v, unique, triangles)
        if snapped is not None:
            return snapped
        return _normalize([1.0 if index == 0 else 0.0 for index in range(len(unique))])
    return _normalize(weights)


def blend_weights_simple_1d(points, u, v):  # noqa: ARG001 - 1D 只用第一参数
    """1D 简单混合：按第一参数排序，只在相邻两点之间线性插值。

    第一参数相同的点会被合并成同一个位置（按 ``(u, v)`` 排序后取第一个作为代表），
    否则同一 ``u`` 上的多个点会让「相邻段」不唯一、结果依赖输入顺序。
    """
    unique, _ = _deduplicate([(float(point[0]), float(point[1])) for point in points])
    if not unique:
        return []
    if len(unique) == 1:
        return [1.0]

    # 按 (u, v) 排序并用「严格更大的 u」分组，保证同 u 的点行为确定。
    order = sorted(range(len(unique)), key=lambda index: unique[index])
    legs = []
    for index in order:
        if legs and abs(unique[legs[-1]][0] - unique[index][0]) <= _EDGE_PARALLEL_EPSILON:
            continue
        legs.append(index)
    if len(legs) == 1:
        weights = [0.0] * len(unique)
        weights[legs[0]] = 1.0
        return weights

    u = float(u)
    weights = [0.0] * len(unique)
    first, last = legs[0], legs[-1]
    if u <= unique[first][0]:
        weights[first] = 1.0
        return weights
    if u >= unique[last][0]:
        weights[last] = 1.0
        return weights
    for position in range(len(legs) - 1):
        index_a, index_b = legs[position], legs[position + 1]
        start = unique[index_a][0]
        end = unique[index_b][0]
        if not start <= u <= end:
            continue
        span = end - start
        t = 0.0 if span <= _EDGE_PARALLEL_EPSILON else (u - start) / span
        weights[index_a] = 1.0 - t
        weights[index_b] = t
        return weights
    weights[last] = 1.0
    return weights


def blend_weights(points, u, v, mode=MODE_CARTESIAN_2D):
    """按混合模式计算权重。

    ``points`` 为 ``((u, v), ...)``，返回与 ``points`` 等长的权重列表（已归一化）。
    重复坐标会平分该坐标的权重，因此返回长度始终等于输入长度。
    """
    coordinates = [(float(point[0]), float(point[1])) for point in points]
    if not coordinates:
        return []
    if mode == MODE_SIMPLE_1D:
        return blend_weights_simple_1d(coordinates, u, v)
    if mode == MODE_DIRECTIONAL_2D:
        raw = blend_weights_directional_2d(coordinates, u, v)
    elif mode == MODE_CARTESIAN_2D:
        raw = blend_weights_cartesian_2d(coordinates, u, v)
    else:
        raise BlendSpaceError(f"未知的混合模式：{mode}")

    if not raw:
        return [0.0] * len(coordinates)
    _, source = _deduplicate(coordinates)
    weights = [0.0] * len(coordinates)
    for original_index, unique_index in enumerate(source):
        if unique_index < len(raw):
            weights[original_index] = raw[unique_index]
    return _normalize(weights)


# endregion


# region 坐标映射


def plot_axis_range(points, *, padding=1.15, minimum_span=1.0):
    """返回坐标系绘件的 ``(u_min, u_max, v_min, v_max)``。

    以零点为中心对称展开（与 Unity 混合树的绘制口径一致），并保证最小跨度，
    这样只有 0/1 开关类坐标时也能看到一个正常的十字坐标系。
    """
    maximum = 0.0
    for point in points:
        maximum = max(maximum, abs(float(point[0])), abs(float(point[1])))
    maximum = max(maximum * padding, minimum_span * 0.5)
    return -maximum, maximum, -maximum, maximum


def uv_to_pixel(u, v, rect, axis_range):
    """把混合坐标映射到区域像素坐标。``rect`` 为 ``(x, y, width, height)``。"""
    x, y, width, height = rect
    u_min, u_max, v_min, v_max = axis_range
    u_span = u_max - u_min
    v_span = v_max - v_min
    scale_u = width / u_span if abs(u_span) > _EDGE_PARALLEL_EPSILON else 1.0
    scale_v = height / v_span if abs(v_span) > _EDGE_PARALLEL_EPSILON else 1.0
    return (
        x + (float(u) - u_min) * scale_u,
        y + (float(v) - v_min) * scale_v,
    )


def pixel_to_uv(px, py, rect, axis_range):
    """:func:`uv_to_pixel` 的逆运算。"""
    x, y, width, height = rect
    u_min, u_max, v_min, v_max = axis_range
    u = u_min + (float(px) - x) * (u_max - u_min) / width if width else u_min
    v = v_min + (float(py) - y) * (v_max - v_min) / height if height else v_min
    return u, v


# endregion
