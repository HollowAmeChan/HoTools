"""形态键混合矩阵的纯数学单元测试（不需要 Blender 的 bpy 支持）。"""

import math
import sys
from pathlib import Path


ADDON_DIR = Path(__file__).resolve().parents[1]
BLEND_UTILS_DIR = ADDON_DIR / "ShapekeyTools" / "blend_utils"
if str(BLEND_UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(BLEND_UTILS_DIR))

import blend_space_math as blend


def assert_close(value, expected, tolerance=1e-6, message=""):
    if abs(value - expected) > tolerance:
        raise AssertionError(f"{message}: {value} != {expected}")


def assert_weights(weights, expected, tolerance=1e-6, message=""):
    if len(weights) != len(expected):
        raise AssertionError(f"{message}: 权重长度 {len(weights)} != {len(expected)}")
    for index, (value, target) in enumerate(zip(weights, expected)):
        assert_close(value, target, tolerance, f"{message}[{index}]")


SQUARE = ((1.0, 1.0), (-1.0, 1.0), (-1.0, -1.0), (1.0, -1.0))

# ── Delaunay 剖分 ──────────────────────────────────────────────────────────
unique, triangles = blend.triangulate2d(SQUARE)
assert len(unique) == 4, unique
assert len(triangles) == 2, triangles
for triangle in triangles:
    a, b, c = (unique[index] for index in triangle)
    area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    assert area > 0.0, f"三角形不是逆时针：{triangle}"

# 重复点会被合并，重复下标仍映射到同一个唯一点
unique_dup, triangles_dup, source = blend.triangulate_points(SQUARE + ((1.0, 1.0),))
assert len(unique_dup) == 4 and len(triangles_dup) == 2 and source[-1] == 0

# 共线点集没有三角形，但点仍然保留
collinear, collinear_triangles = blend.triangulate2d(((0.0, 0.0), (1.0, 0.0), (2.0, 0.0)))
assert len(collinear) == 3 and collinear_triangles == []

# 内部点会参与剖分，形成稳定的扇形
grid = ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0), (0.0, 0.0))
grid_unique, grid_triangles = blend.triangulate2d(grid)
assert len(grid_triangles) == 4, grid_triangles
covered = [index for triangle in grid_triangles for index in triangle]
assert set(covered) == {0, 1, 2, 3, 4}


# 3x3 抖动网格：三角形数必须满足 Euler 关系 2n - 2 - h（h 为凸包点数）
def jittered_grid(size, amplitude=0.15):
    points = []
    step = 2.0 / (size - 1)
    for row in range(size):
        for column in range(size):
            u = -1.0 + column * step
            v = -1.0 + row * step
            if 0 < row < size - 1 and 0 < column < size - 1:
                u += amplitude * ((row * 7 + column * 3) % 5 - 2) / 2.0
                v -= amplitude * ((row * 5 + column * 11) % 5 - 2) / 2.0
            points.append((u, v))
    return tuple(points)


for size in (3, 4, 5):
    cloud = jittered_grid(size)
    unique_cloud, triangles_cloud = blend.triangulate2d(cloud)
    boundary = blend._hull_edges(triangles_cloud)
    hull_count = len({index for edge in boundary for index in edge})
    expected = 2 * len(unique_cloud) - 2 - hull_count
    assert len(triangles_cloud) == expected, (
        f"{size}x{size} 抖动网格三角形数 {len(triangles_cloud)} != {expected}")
    area_sum = 0.0
    for i, j, k in triangles_cloud:
        a, b, c = unique_cloud[i], unique_cloud[j], unique_cloud[k]
        area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        assert area > 0.0, f"逆时针被破坏：{(i, j, k)}"
        area_sum += area
    # 叉积给出的是两倍面积：2x2 的方形区域期望 8.0
    assert_close(area_sum, 8.0, 1e-6, f"{size}x{size} 剖分应铺满凸包")
    for step in range(21):
        for other in range(21):
            u = -1.2 + step * 0.12
            v = -1.2 + other * 0.12
            weights = blend.blend_weights(cloud, u, v, blend.MODE_CARTESIAN_2D)
            assert_close(sum(weights), 1.0, 1e-9, f"({u:.2f},{v:.2f}) 权重和")
            assert all(value >= -1e-12 for value in weights), weights


# ── 2D 笛卡尔权重（Unity 2D Freeform Cartesian 口径） ──────────────────────
# 正方形的对角线被剖分选中，中心点必然落在对角线边上，因此只由该边两端点决定。
assert_weights(
    blend.blend_weights(SQUARE, 0.0, 0.0, blend.MODE_CARTESIAN_2D),
    (0.0, 0.5, 0.0, 0.5),
    message="正方形对角线边界上的权重",
)
# 五个点的十字布局：中心点落在剖分三角形的内部，四个外围点才可能同时有权重。
cross = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0), (0.0, 0.0))
centre = blend.blend_weights(cross, 0.0, 0.0, blend.MODE_CARTESIAN_2D)
assert_weights(centre, (0.0, 0.0, 0.0, 0.0, 1.0), message="与坐标点重合时应完全取该点")
# 中心点一定落在某个剖分三角形内部，所以它的权重由该三角形的三个顶点决定。
inside_blend = blend.blend_weights(cross, 0.2, 0.2, blend.MODE_CARTESIAN_2D)
assert_close(sum(inside_blend), 1.0, message="中心点附近权重和")
assert inside_blend[0] > 0.0 and inside_blend[1] > 0.0, inside_blend
assert_weights(
    blend.blend_weights(SQUARE, 1.0, 1.0, blend.MODE_CARTESIAN_2D),
    (1.0, 0.0, 0.0, 0.0),
    message="顶点处应完全取该顶点",
)
assert_weights(
    blend.blend_weights(SQUARE, 0.0, 1.0, blend.MODE_CARTESIAN_2D),
    (0.5, 0.5, 0.0, 0.0),
    message="上边界中点应均分上方两点",
)
# 凸包外：投影到最近边，权重仍归一化且只落在该边两端
outside = blend.blend_weights(SQUARE, 3.0, 0.0, blend.MODE_CARTESIAN_2D)
assert_weights(outside, (0.5, 0.0, 0.0, 0.5), message="凸包外应投影到最近边")
assert_close(sum(outside), 1.0, message="凸包外权重必须归一化")

# 权重永远归一化、永远非负
for u, v in ((0.3, -0.4), (-0.9, 0.2), (1.4, -1.3), (0.0, 0.0), (-2.0, 2.0)):
    weights = blend.blend_weights(SQUARE, u, v, blend.MODE_CARTESIAN_2D)
    assert_close(sum(weights), 1.0, message=f"({u},{v}) 权重和")
    assert all(value >= -1e-12 for value in weights), weights

# 三角形内部重心插值：单三角形输入时权重就是重心坐标
triangle_points = ((0.0, 0.0), (2.0, 0.0), (0.0, 2.0))
assert_weights(
    blend.blend_weights(triangle_points, 0.5, 0.5, blend.MODE_CARTESIAN_2D),
    (0.5, 0.25, 0.25),
    message="单三角形重心插值",
)


# ── 1D 简单混合 ────────────────────────────────────────────────────────────
line = ((-1.0, 0.0), (0.0, 0.0), (1.0, 0.0))
assert_weights(
    blend.blend_weights(line, 0.5, 0.0, blend.MODE_SIMPLE_1D),
    (0.0, 0.5, 0.5),
    message="1D 相邻两点插值",
)
assert_weights(
    blend.blend_weights(line, -2.0, 0.0, blend.MODE_SIMPLE_1D),
    (1.0, 0.0, 0.0),
    message="1D 超出范围夹到端点",
)
assert_weights(
    blend.blend_weights(line, 2.0, 0.0, blend.MODE_SIMPLE_1D),
    (0.0, 0.0, 1.0),
    message="1D 超出范围夹到另一端点",
)


# ── 2D 方向混合 ───────────────────────────────────────────────────────────
directional = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))
assert_weights(
    blend.blend_weights(directional, 1.0, 0.0, blend.MODE_DIRECTIONAL_2D),
    (1.0, 0.0, 0.0, 0.0),
    message="方向混合的顶点",
)
diagonal = blend.blend_weights(directional, 0.7, 0.7, blend.MODE_DIRECTIONAL_2D)
assert_close(sum(diagonal), 1.0, message="方向混合权重和")
assert diagonal[0] > 0.0 and diagonal[1] > 0.0, diagonal
assert_close(diagonal[0], diagonal[1], 1e-6, "45° 应对称均分")

# 半径超出参考半径时整体衰减，但权重仍归一化
far = blend.blend_weights(directional, 5.0, 5.0, blend.MODE_DIRECTIONAL_2D)
assert_close(sum(far), 1.0, message="方向混合远端权重和")
assert far[0] > far[1] - 1e-9, far


# ── 退化输入 ──────────────────────────────────────────────────────────────
assert blend.blend_weights((), 0.0, 0.0) == []
assert_weights(blend.blend_weights(((2.0, 2.0),), 0.0, 0.0), (1.0,),
               message="单点永远 100%")
# 重复坐标平分权重（保持与输入等长）
duplicated = blend.blend_weights(SQUARE + ((1.0, 1.0),), 1.0, 1.0)
assert_weights(duplicated, (0.5, 0.0, 0.0, 0.0, 0.5), message="重复坐标平分权重")

try:
    blend.blend_weights(SQUARE, 0.0, 0.0, 'NOPE')
except blend.BlendSpaceError:
    pass
else:
    raise AssertionError("未知混合模式应抛出 BlendSpaceError")

try:
    blend.blend_weights(((float('nan'), 0.0), (0.0, 0.0)), 0.0, 0.0)
except blend.BlendSpaceError:
    pass
else:
    raise AssertionError("非法坐标应抛出 BlendSpaceError")


# ── 坐标映射 ──────────────────────────────────────────────────────────────
axis_range = blend.plot_axis_range(SQUARE)
assert axis_range == (-1.15, 1.15, -1.15, 1.15), axis_range
rect = (100.0, 200.0, 230.0, 230.0)
px, py = blend.uv_to_pixel(0.0, 0.0, rect, axis_range)
assert_close(px, 215.0, message="中心 x")
assert_close(py, 315.0, message="中心 y")
u, v = blend.pixel_to_uv(px, py, rect, axis_range)
assert_close(u, 0.0) and assert_close(v, 0.0)
px, py = blend.uv_to_pixel(-1.15, 1.15, rect, axis_range)
assert_close(px, 100.0) and assert_close(py, 430.0)
assert blend.plot_axis_range(((0.0, 0.0),)) == (-0.5, 0.5, -0.5, 0.5)

print("BLEND_SPACE_MATH_OK", math.pi)
