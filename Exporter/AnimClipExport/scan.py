# -*- coding: utf-8 -*-
# 扫描 Blender 场景，收集"FBX 带不走的属性动画轨道"候选列表。

from dataclasses import dataclass, field
from . import mapping


@dataclass
class AnimTrackInfo:
    """一条候选属性动画轨道的描述信息（扫描结果）。"""
    obj_name:    str    # 来源物体名
    data_path:   str    # fcurve.data_path
    array_index: int    # fcurve.array_index
    key_count:   int    # 关键帧数量
    # 解析后的 Unity 绑定信息（来自 mapping.resolve）
    unity_attr:  str    = ""
    unity_cls:   int    = 1
    is_boolean:  bool   = False
    # 人类可读标签（显示在 UI 列表里）
    label:       str    = ""

    def __post_init__(self):
        attr, cls, is_bool = mapping.resolve(self.data_path, self.array_index)
        self.unity_attr = attr
        self.unity_cls  = cls
        self.is_boolean = is_bool
        self.label = _make_label(self.data_path, self.array_index)


def _make_label(data_path: str, array_index: int) -> str:
    """生成人类可读标签：取路径最末 token，多分量属性补上 [i] 后缀。"""
    leaf = mapping._leaf_token(data_path)
    return f"{leaf}[{array_index}]" if array_index > 0 else leaf


def _iter_actions(obj):
    """产出物体身上所有相关 Action（当前 action + 所有 NLA strip）。"""
    anim = getattr(obj, "animation_data", None)
    if anim is None:
        return
    if anim.action is not None:
        yield anim.action
    for track in anim.nla_tracks:
        for strip in track.strips:
            if strip.action is not None:
                yield strip.action


def _gather_objects(selected):
    """从选中物体出发，收集扫描范围内的所有物体（去重）。

    - 如果选中物体属于 mmd 模型，展开成整棵树（Root + 所有后代）；
    - 否则只扫选中物体本身。
    """
    result = []
    seen: set[str] = set()

    def _add(obj):
        if obj is None or obj.name in seen:
            return
        seen.add(obj.name)
        result.append(obj)

    def _add_tree(root):
        """递归添加 root 及其所有后代。"""
        _add(root)
        for child in root.children_recursive:
            _add(child)

    def _find_mmd_root(obj):
        node = obj
        while node is not None:
            if getattr(node, "mmd_type", "") == "ROOT":
                return node
            node = node.parent
        return None

    for obj in selected:
        mmd_root = _find_mmd_root(obj)
        if mmd_root is not None:
            _add_tree(mmd_root)
        else:
            _add(obj)

    return result


def scan(selected_objects) -> list[AnimTrackInfo]:
    """扫描选中物体，返回所有"FBX 带不走的属性动画"轨道信息列表。

    每条 fcurve 只出现一次（同一 data_path+array_index 跨 action 去重取首次命中）。
    """
    tracks: list[AnimTrackInfo] = []
    # 用 (obj_name, data_path, array_index) 去重，避免同属性多个 action 重复列出
    seen_keys: set[tuple[str, str, int]] = set()

    for obj in _gather_objects(selected_objects):
        for action in _iter_actions(obj):
            for fcurve in action.fcurves:
                dp  = fcurve.data_path
                idx = fcurve.array_index

                # 跳过 FBX 已处理轨道
                if mapping.is_fbx_handled(dp):
                    continue

                key = (obj.name, dp, idx)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                kp_count = len(fcurve.keyframe_points)
                if kp_count == 0:
                    continue

                tracks.append(AnimTrackInfo(
                    obj_name=obj.name,
                    data_path=dp,
                    array_index=idx,
                    key_count=kp_count,
                ))

    return tracks


def find_fcurve(obj, data_path: str, array_index: int):
    """在物体所有 Action 里找到指定的 fcurve，返回首个命中；找不到返回 None。"""
    for action in _iter_actions(obj):
        fc = action.fcurves.find(data_path, index=array_index)
        if fc is not None and len(fc.keyframe_points) > 0:
            return fc
    return None
