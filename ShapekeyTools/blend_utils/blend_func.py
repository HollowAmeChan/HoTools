"""形态键混合矩阵的功能工具（数据 ↔ 权重 ↔ 形态键的中间层）。

这里放的都是“算与写”，不放界面也不放 GPU：

- 权重求值缓存：UI 每帧重绘、绘件每次重画都要权重，签名不变就不重复做剖分；
- 把权重真正写进操作物体形态键的实现与结果报告；
- 权重归零。

取值工具（物体/点位/键名）在 ``shapekey_utils``，数据模型在 ``blend_debug_store``。
"""

from __future__ import annotations

try:
    from . import blend_space_math as _math
    from . import shapekey_utils as _keys
except ImportError:  # 兼容旧工具直接导入脚本
    import blend_space_math as _math
    import shapekey_utils as _keys


# region 权重求值缓存


_WEIGHT_CACHE: dict = {"key": None, "weights": (), "names": ()}


def _weight_signature(item):
    """权重缓存签名：只要这些值没变，就不必重新做三角剖分。"""
    return (
        round(item.cursor_u, 4),
        round(item.cursor_v, 4),
        item.mix_mode,
        tuple(
            (round(point.u, 4), round(point.v, 4), point.shape_key)
            for point in item.points
        ),
    )


def evaluate_item(item):
    """求当前输入坐标下各坐标点的权重，返回 ``(weights, names)``。

    结果按签名缓存，UI 每帧重绘时不会重复做剖分。
    """
    if item is None:
        return (), ()
    signature = _weight_signature(item)
    if _WEIGHT_CACHE["key"] == signature:
        return _WEIGHT_CACHE["weights"], _WEIGHT_CACHE["names"]

    points = tuple(item.points)
    coordinates = [(point.u, point.v) for point in points]
    weights = _math.blend_weights(coordinates, item.cursor_u, item.cursor_v,
                                  item.mix_mode)
    names = tuple(
        point.shape_key or point.name or f"点位 {index + 1}"
        for index, point in enumerate(points)
    )
    _WEIGHT_CACHE["key"] = signature
    _WEIGHT_CACHE["weights"] = tuple(weights)
    _WEIGHT_CACHE["names"] = names
    return _WEIGHT_CACHE["weights"], _WEIGHT_CACHE["names"]


def invalidate_weight_cache():
    """外部改了影响权重的数据后调用（例如数据被脚本直接改写）。"""
    _WEIGHT_CACHE["key"] = None


# endregion


# region 取值辅助


# 直接复用 shapekey_utils 的取值实现，避免这里再抄一层转发（参数顺序也保持一致：
# item 在前、context 在后）。
resolve_item_objects = _keys.active_objects
candidate_shape_keys = _keys.candidate_shape_keys
candidate_shape_key_names = _keys.candidate_shape_keys
points = _keys.points
active_objects = _keys.active_objects
unique_shape_keys = _keys.unique_shape_keys
shape_key_names = _keys.shape_key_names


def item_weights(item):
    """返回 ``[(形态键名, 权重), ...]``，跳过没有名字的坐标点。"""
    entries = tuple(item.points) if item is not None else ()
    if not entries:
        return []
    coordinates = [(point.u, point.v) for point in entries]
    weights = _math.blend_weights(coordinates, item.cursor_u, item.cursor_v,
                                  item.mix_mode)
    resolved = []
    for point, weight in zip(entries, weights):
        name = point.shape_key or point.name
        if name:
            resolved.append((name, weight))
    return resolved


# endregion


# region 权重写入


class BlendApplyReport:
    """一次权重写入的结果摘要。"""

    def __init__(self):
        self.objects = 0
        self.written = 0
        self.missing_keys = []
        self.failed = []
        self.skipped_objects = []
        self.muted = []

    @property
    def total(self) -> int:
        return self.written

    def summary(self) -> str:
        parts = [f"写入 {self.written} 个形态键 / {self.objects} 个物体"]
        if self.missing_keys:
            names = "、".join(sorted(set(self.missing_keys))[:4])
            parts.append(f"缺少形态键：{names}")
        if self.skipped_objects:
            parts.append(f"跳过 {len(self.skipped_objects)} 个无效物体")
        if self.muted:
            parts.append(f"静音 {self.muted[0]}")
        if self.failed:
            parts.append(f"失败 {len(self.failed)}：{self.failed[0]}")
        return "；".join(parts)


def apply_weights(context, item, report=None) -> BlendApplyReport:
    """把当前权重写进操作物体的形态键。

    与 Unity 混合树一致的口径：权重按坐标求解，再作为各形态键的 value 写入。
    ``ho_bs_mute_others`` 打开时，矩阵之外的形态键会被静音，保证预览与矩阵一致。
    """
    if report is None:
        report = BlendApplyReport()
    if item is None:
        return report

    pairs = item_weights(item)
    if not pairs:
        return report

    mute_others = bool(getattr(context.scene, "ho_bs_mute_others", False))
    matrix_names = {name for name, _weight in pairs}
    for obj in resolve_item_objects(item, context):
        shape_keys = getattr(obj.data, "shape_keys", None)
        if shape_keys is None:
            report.skipped_objects.append(obj.name)
            continue
        key_blocks = shape_keys.key_blocks
        basis = shape_keys.reference_key
        report.objects += 1

        if mute_others:
            hidden = 0
            for key in key_blocks:
                if key == basis or key.name in matrix_names:
                    continue
                if not key.mute:
                    key.mute = True
                hidden += 1
            if hidden:
                report.muted.append(f"{obj.name} {hidden} 个键")

        for name, weight in pairs:
            key = key_blocks.get(name)
            if key is None:
                if name not in report.missing_keys:
                    report.missing_keys.append(name)
                continue
            if key == basis:
                continue
            try:
                key.value = float(weight)
            except (TypeError, ValueError, ReferenceError) as exc:
                report.failed.append(f"{obj.name}.{name}: {exc}")
                continue
            report.written += 1
    return report


def clear_all_keys(item, context=None) -> int:
    """全键归零：列表里每个物体的**所有**形态键都归零，并把活动键切回基型。

    和形态键工具里的「全键归零 + 选中基型」是同一件事，不限于矩阵里出现的键；
    只有当前活动物体需要切活动键（其它物体没有“活动键”这个概念）。
    返回归零的键数量。
    """
    cleared = 0
    active_object = getattr(context, "object", None) if context is not None else None
    for obj in _keys.active_objects(item):
        shape_keys = getattr(obj.data, "shape_keys", None)
        if shape_keys is None:
            continue
        basis = shape_keys.reference_key
        for key in shape_keys.key_blocks:
            if key == basis:
                continue
            if key.value != 0.0:
                key.value = 0.0
                cleared += 1
        if obj is active_object and basis is not None:
            try:
                obj.active_shape_key_index = shape_keys.key_blocks.find(basis.name)
            except (AttributeError, ReferenceError, TypeError, ValueError):
                pass
    return cleared


# endregion
