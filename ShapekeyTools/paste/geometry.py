"""形态键匹配用的无状态公共工具。

这些能力原本只长在 ``ShapekeyTools.transfer.ShapeKeyTransfer`` 里，服务于
「传递形态键」；粘贴的尽力匹配分支需要同一套「基型几何 + 平均 UV + KD-tree」
能力，所以抽到本模块，两边共用同一份实现。

本模块不持有任何 Blender 实例状态，也不修改传入的数据。
"""

import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

from Utils import shapekey_utils


class ShapekeyMatchError(ValueError):
    """匹配所需的形态键、几何或 UV 数据缺失、非法时抛出。"""


# 与 transfer 的传递模式保持同一套标识，方便用户在两处看到同样的说法。
MODE_VERTEX_INDEX = 'MOD_VERTEX_INDEX'
MODE_WORLD_POSITION = 'MOD_WORLD_POSITION'
MODE_UV_POSITION = 'MOD_UV_POSITION'

#: 左右象限的判定轴：本地 X 轴（Blender 角色流程里左右方向就是 X）。
SIDE_AXIS = 0


def _as_point(co):
    """把 2D / 3D 坐标统一成 KD-tree 需要的三元组。"""
    if len(co) >= 3:
        return (co[0], co[1], co[2])
    return (co[0], co[1], 0.0)


def average_uv_per_vertex(mesh, uv_layer=None):
    """按顶点平均该顶点所有 loop 的 UV，返回 ``{顶点索引: Vector((u, v))}``。

    口径与 transfer 的老实现一致：使用**活动** UV 层（UV 层列表里高亮、
    也就是 UV 编辑器显示的那层），不是激活渲染的那层；只有出现在面里的
    顶点会有记录。
    """
    layer = uv_layer if uv_layer is not None else mesh.uv_layers.active
    if layer is None:
        raise ShapekeyMatchError("网格没有活动 UV 层")

    loop_count = len(mesh.loops)
    vertex_count = len(mesh.vertices)
    if loop_count == 0 or vertex_count == 0:
        return {}

    vertex_indices = np.empty(loop_count, dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", vertex_indices)

    coordinates = np.empty(loop_count * 2, dtype=np.float32)
    layer.data.foreach_get("uv", coordinates)
    coordinates = coordinates.reshape((-1, 2))

    counts = np.bincount(vertex_indices, minlength=vertex_count)
    sum_u = np.bincount(
        vertex_indices, weights=coordinates[:, 0], minlength=vertex_count)
    sum_v = np.bincount(
        vertex_indices, weights=coordinates[:, 1], minlength=vertex_count)

    averages = {}
    for index in np.flatnonzero(counts):
        position = int(index)
        averages[position] = Vector((
            sum_u[position] / counts[position],
            sum_v[position] / counts[position],
        ))
    return averages


def build_kdtree(items):
    """用 ``(索引, 坐标)`` 序列建 KD-tree，返回 ``(kd, 原索引列表)``。

    KD-tree 只接受稠密的插入值，所以稀疏点集（只选中的顶点、只有 UV 的顶点）
    必须经过这层映射才能拿回真实顶点索引；两个返回值在查询时配对使用，
    见 :func:`nearest`。空输入返回 ``(None, [])``。
    """
    items = list(items)
    if not items:
        return None, []

    kd = KDTree(len(items))
    indices = []
    for position, (index, co) in enumerate(items):
        kd.insert(_as_point(co), position)
        indices.append(index)
    kd.balance()
    return kd, indices


def nearest(kd, indices, co):
    """最近邻查询，返回 ``(原索引 | None, 距离)``；树为空时返回 ``(None, inf)``。"""
    if kd is None:
        return None, float('inf')

    _, position, distance = kd.find(_as_point(co))
    if position is None:
        return None, float('inf')
    return indices[position], distance


def bbox_diagonal(points):
    """点集包围盒的对角线长度；空集或单点返回 0。"""
    array = np.asarray(points, dtype=np.float64).reshape((-1, 3))
    if len(array) < 2:
        return 0.0
    return float(np.linalg.norm(array.max(axis=0) - array.min(axis=0)))


def side_mask(positions):
    """按模型原点把顶点分到左右两个象限，返回布尔数组。

    本地 ``SIDE_AXIS`` 轴坐标 >= 0 记为 True；原点上的点算正侧。源与目标用同一条
    规则，所以只要是同一套左右布局就不会错位。

    用途：镜像对称的模型经常让左右两侧**共用同一片 UV**（UV 上完全重合），
    这时纯 UV 最近邻会在两侧的同名点之间随便挑一个，必须靠这个掩码把两侧分开。
    """
    array = np.asarray(positions, dtype=np.float64).reshape((-1, 3))
    return array[:, SIDE_AXIS] >= 0.0


def to_world(obj, positions):
    """把物体本地坐标批量变换到世界空间，返回新的 ``(顶点数, 3)`` 数组。"""
    array = np.asarray(positions, dtype=np.float64).reshape((-1, 3))
    if len(array) == 0:
        return array
    matrix = np.array(obj.matrix_world, dtype=np.float64)
    return array @ matrix[:3, :3].T + matrix[:3, 3]


def basis_positions(obj):
    """读取物体基型（参考键）的本地坐标，返回 ``(顶点数, 3)`` 数组。"""
    shape_keys = shapekey_utils.require_shape_keys(obj)
    basis = shape_keys.reference_key
    if basis is None:
        raise ShapekeyMatchError("形态键数据缺少参考键")
    return shapekey_utils.read_shape_key_positions(basis)
