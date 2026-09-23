"""混合矩阵的形态键与物体工具。

负责“把数据模型解析成真实物体、把权重落到真实形态键”这一层的取值逻辑：

- 操作物体条目 → 真实对象（指针失效时按名字回查）；
- 启用且有效的物体列表、启用点位列表；
- 对象的形态键名（不含参考键）、整个矩阵引用的键名；
- 从当前选择快速挑操作物体、把一个对象加进列表（去重）。

数据模型在 ``blend_debug_store``：这里只读数据，不注册属性、不定义算子。
"""

from __future__ import annotations

import bpy


# region 点位与物体取值


def enabled_points(item):
    """返回参与混合的坐标点（跳过临时禁用的）。"""
    if item is None:
        return ()
    return tuple(point for point in item.points if point.enabled)


def resolve_object(entry):
    """把操作物体条目解析成真实对象；指针失效时按名字回查并写回。"""
    obj = entry.object
    if obj is not None:
        return obj
    cached = entry.object_name
    if cached:
        found = bpy.data.objects.get(cached)
        if found is not None:
            entry.object = found
            return found
    return None


def active_objects(item, context=None):
    """返回列表里所有仍然有效的对象（顺带按名字回查失效的指针）。

    ``context`` 只为兼容旧调用签名保留：作用范围就是列表本身，刻意不回退到
    「当前选中物体」，空列表 = 什么也不写。
    """
    result = []
    if item is None:
        return result
    for entry in item.objects:
        obj = resolve_object(entry)
        if obj is not None:
            result.append(obj)
    return result


def total_objects(item) -> int:
    """列表里实际记了几行（含指针失效的行）。"""
    return len(item.objects) if item is not None else 0


def shape_key_names(obj):
    """返回对象的形态键名（不含参考键）。"""
    if obj is None or getattr(obj, "type", None) != 'MESH':
        return []
    shape_keys = getattr(obj.data, "shape_keys", None)
    if shape_keys is None:
        return []
    basis = shape_keys.reference_key
    return [
        key.name for key in shape_keys.key_blocks
        if basis is None or key != basis
    ]


def unique_shape_keys(item):
    """返回该调试矩阵引用的全部形态键名（保持首次出现顺序）。"""
    names = []
    if item is None:
        return names
    for point in item.points:
        name = point.shape_key
        if name and name not in names:
            names.append(name)
    return names


def candidate_shape_keys(item, context=None):
    """返回可选的形态键名：全部操作物体上的键名 + 活动物体上的键名。

    注意：这里刻意不做成 EnumProperty 的 items 回调。Blender 4.5 在“存值不在候选里”
    时会反复重入读 ``self`` 的 items 回调，直接爆栈，因此坐标点的键名用普通字符串
    + 显式挑选菜单（见 ``OP_ShapekeyTools_BlendPointSetShapeKey``）。
    """
    names = []
    if item is not None:
        for entry in item.objects:
            obj = resolve_object(entry)
            if obj is None:
                continue
            for name in shape_key_names(obj):
                if name not in names:
                    names.append(name)
    active = getattr(context, "object", None) if context is not None else None
    for name in shape_key_names(active):
        if name not in names:
            names.append(name)
    return names


# endregion


# region 操作物体列表


def mesh_candidates(context):
    """快速添加的候选物体：选中项优先，其次当前活动物体。"""
    candidates = [
        obj for obj in context.selected_objects
        if getattr(obj, "type", None) == 'MESH'
    ]
    active = getattr(context, "object", None)
    if getattr(active, "type", None) == 'MESH' and active not in candidates:
        candidates.append(active)
    return candidates


def append_object(item, obj) -> bool:
    """把一个对象加入操作物体列表；已存在或类型不符时返回 ``False``。"""
    if item is None or obj is None or getattr(obj, "type", None) != 'MESH':
        return False
    for entry in item.objects:
        if resolve_object(entry) == obj or entry.object_name == obj.name:
            return False
    entry = item.objects.add()
    entry.object = obj
    entry.object_name = obj.name
    return True


def append_objects(item, objects) -> int:
    """批量加入并返回新增数量。"""
    added = 0
    for obj in objects:
        if append_object(item, obj):
            added += 1
    return added


def ensure_active_object(item, context) -> bool:
    """列表为空时把活动物体补进去，返回是否发生了变化。"""
    if item is None or len(item.objects):
        return False
    active = getattr(context, "object", None)
    if getattr(active, "type", None) != 'MESH':
        return False
    return append_object(item, active)


# endregion
