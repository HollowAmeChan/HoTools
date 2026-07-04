# -*- coding: utf-8 -*-
# Unity .anim（YAML 文本）文档构建。
# 与 Blender 解耦，只接受纯 Python 数据结构。

import zlib
from .interpolation import UnityKey, _INF


def unity_crc32(text: str) -> int:
    """Unity ClipBindingConstant 中 path / attribute 字段用的 CRC32（无符号）。"""
    return zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF


def fmt(value: float) -> str:
    """数值→紧凑字符串：整数不带小数点，其余保留 6 位去尾零。"""
    if value == _INF or value == float('inf'):
        return "Infinity"
    if value == -_INF or value == float('-inf'):
        return "-Infinity"
    if value == int(value):
        return str(int(value))
    return ("%.6f" % value).rstrip("0").rstrip(".")


def _keyframe_block(key: UnityKey) -> str:
    return (
        "        - serializedVersion: 3\n"
        f"          time: {fmt(key.time)}\n"
        f"          value: {fmt(key.value)}\n"
        f"          inSlope: {fmt(key.in_slope)}\n"
        f"          outSlope: {fmt(key.out_slope)}\n"
        f"          tangentMode: {key.tangent_mode}\n"
        f"          weightedMode: {key.weighted_mode}\n"
        f"          inWeight: {fmt(key.in_weight)}\n"
        f"          outWeight: {fmt(key.out_weight)}\n"
    )


def _float_curve_block(
    keys: list[UnityKey],
    attribute: str,
    path: str,
    class_id: int,
) -> str:
    """单条 float 曲线块（m_FloatCurves / m_EditorCurves 通用）。"""
    kf_text = "".join(_keyframe_block(k) for k in keys)
    return (
        "  - curve:\n"
        "      serializedVersion: 2\n"
        "      m_Curve:\n"
        f"{kf_text}"
        "      m_PreInfinity: 2\n"
        "      m_PostInfinity: 2\n"
        "      m_RotationOrder: 4\n"
        f"    attribute: {attribute}\n"
        f"    path: {path}\n"
        f"    classID: {class_id}\n"
        "    script: {fileID: 0}\n"
    )


def _binding_block(attribute: str, path: str, class_id: int) -> str:
    """m_ClipBindingConstant.genericBindings 里一条绑定（使用 CRC32）。"""
    return (
        "    - serializedVersion: 2\n"
        f"      path: {unity_crc32(path)}\n"
        f"      attribute: {unity_crc32(attribute)}\n"
        "      script: {fileID: 0}\n"
        f"      typeID: {class_id}\n"
        "      customType: 0\n"
        "      isPPtrCurve: 0\n"
        "      isIntCurve: 0\n"
        "      isSerializeReferenceCurve: 0\n"
    )


# ── 公开 API ─────────────────────────────────────────────────

ANIM_FILE_ID = 7400000


def build_document(
    clip_name: str,
    curves: list[tuple[list[UnityKey], str, str, int]],
    stop_time: float,
    fps: float,
    loop: bool,
) -> str:
    """拼出完整 .anim（Unity YAML）文档字符串。

    curves: list of (keys, attribute, target_path, class_id)
    """
    curve_blocks   = "".join(_float_curve_block(k, a, p, c) for k, a, p, c in curves)
    binding_blocks = "".join(_binding_block(a, p, c)        for _, a, p, c in curves)
    loop_flag = 1 if loop else 0

    return (
        "%YAML 1.1\n"
        "%TAG !u! tag:unity3d.com,2011:\n"
        f"--- !u!74 &{ANIM_FILE_ID}\n"
        "AnimationClip:\n"
        "  m_ObjectHideFlags: 0\n"
        "  m_CorrespondingSourceObject: {fileID: 0}\n"
        "  m_PrefabInstance: {fileID: 0}\n"
        "  m_PrefabAsset: {fileID: 0}\n"
        f"  m_Name: {clip_name}\n"
        "  serializedVersion: 6\n"
        "  m_Legacy: 0\n"
        "  m_Compressed: 0\n"
        "  m_UseHighQualityCurve: 1\n"
        "  m_RotationCurves: []\n"
        "  m_CompressedRotationCurves: []\n"
        "  m_EulerCurves: []\n"
        "  m_PositionCurves: []\n"
        "  m_ScaleCurves: []\n"
        "  m_FloatCurves:\n"
        f"{curve_blocks}"
        "  m_PPtrCurves: []\n"
        f"  m_SampleRate: {fmt(fps)}\n"
        "  m_WrapMode: 0\n"
        "  m_Bounds:\n"
        "    m_Center: {x: 0, y: 0, z: 0}\n"
        "    m_Extent: {x: 0, y: 0, z: 0}\n"
        "  m_ClipBindingConstant:\n"
        "    genericBindings:\n"
        f"{binding_blocks}"
        "    pptrCurveMapping: []\n"
        "  m_AnimationClipSettings:\n"
        "    serializedVersion: 2\n"
        "    m_AdditiveReferencePoseClip: {fileID: 0}\n"
        "    m_AdditiveReferencePoseTime: 0\n"
        "    m_StartTime: 0\n"
        f"    m_StopTime: {fmt(stop_time)}\n"
        "    m_OrientationOffsetY: 0\n"
        "    m_Level: 0\n"
        "    m_CycleOffset: 0\n"
        "    m_HasAdditiveReferencePose: 0\n"
        f"    m_LoopTime: {loop_flag}\n"
        "    m_LoopBlend: 0\n"
        "    m_LoopBlendOrientation: 0\n"
        "    m_LoopBlendPositionY: 0\n"
        "    m_LoopBlendPositionXZ: 0\n"
        "    m_KeepOriginalOrientation: 0\n"
        "    m_KeepOriginalPositionY: 1\n"
        "    m_KeepOriginalPositionXZ: 0\n"
        "    m_HeightFromFeet: 0\n"
        "    m_Mirror: 0\n"
        "  m_EditorCurves:\n"
        f"{curve_blocks}"
        "  m_EulerEditorCurves: []\n"
        "  m_HasGenericRootTransform: 0\n"
        "  m_HasMotionFloatCurves: 0\n"
        "  m_Events: []\n"
    )
