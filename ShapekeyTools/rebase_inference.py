"""FBSF 变基列表的保守推断与显式选中推断。"""

from __future__ import annotations

import re
import unicodedata

import numpy as np

from Utils import shapekey_utils

try:
    from . import rebase_core as _core
except ImportError:  # 兼容旧工具直接导入脚本
    import rebase_core as _core


_ASCII_TOKEN = re.compile(r"[A-Za-z]+|\d+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_EYE_TOKENS = frozenset({
    'blink', 'closed', 'close', 'eye', 'eyes', 'eyelid', 'eyelids',
    'lid', 'lids', 'squint', 'wide', 'wink',
})
_MOUTH_TOKENS = frozenset({
    'jaw', 'lip', 'lips', 'mouth', 'phoneme', 'tongue', 'viseme',
})
_GAZE_TOKENS = frozenset({'gaze', 'look'})
_EYE_BLOCKED_TOKENS = frozenset({'brow', 'iris', 'pupil'})


def _shape_key_data(obj):
    if obj is None or getattr(obj, "type", None) != 'MESH':
        return None
    return getattr(getattr(obj, "data", None), "shape_keys", None)


def _effective_reference_tag(item):
    return (
        item.reference_tag
        if item.function_tag == item.auto_function_tag
        else item.function_tag
    )


def _build_inference_data(obj):
    shape_keys = _shape_key_data(obj)
    if shape_keys is None or shape_keys.reference_key is None:
        return None
    basis = shape_keys.reference_key
    shape_names = tuple(
        key.name for key in shape_keys.key_blocks if key != basis)
    classification_context = _core._fbsf_classification_context(shape_names)
    basis_positions = shapekey_utils.read_shape_key_positions(basis)
    keys_by_name = {
        key.name: key for key in shape_keys.key_blocks if key != basis
    }
    delta_cache = {}

    def target_delta(shape_name):
        delta = delta_cache.get(shape_name)
        if delta is None:
            key = keys_by_name[shape_name]
            relative = shapekey_utils.read_shape_key_positions(key.relative_key)
            delta = shapekey_utils.read_shape_key_positions(key) - relative
            delta_cache[shape_name] = delta
        return delta

    return (
        shape_keys,
        basis_positions,
        keys_by_name,
        classification_context,
        target_delta,
    )


def _source_orientation(
        shape_keys, target_tags, classification_context, target_delta):
    orientation = []
    for item in shape_keys.ho_rebase_items:
        if (
                not item.merge
                or not item.mergeable
                or item.shape_key_name not in target_tags):
            continue
        function_tag = target_tags[item.shape_key_name][0]
        preset = _core._fbsf_auto_preset(
            item.shape_key_name, context=classification_context)
        channels = _core._fbsf_tag_channels(function_tag)
        if (
                'MMD' not in preset.standards
                and len(channels & {'LEFT_EYE', 'RIGHT_EYE'}) == 1):
            orientation.append(
                (function_tag, target_delta(item.shape_key_name)))
    return tuple(orientation)


def infer_uninitialized(obj):
    """刷新列表时保守推断新增行，不覆盖已有行。"""
    shape_keys = _shape_key_data(obj)
    if shape_keys is None:
        return 0
    pending_names = {
        item.shape_key_name for item in shape_keys.ho_rebase_items
        if not item.initialized
    }
    if not pending_names:
        return 0
    data = _build_inference_data(obj)
    if data is None:
        return 0
    (
        shape_keys,
        basis_positions,
        keys_by_name,
        classification_context,
        target_delta,
    ) = data
    pending = [
        item for item in shape_keys.ho_rebase_items
        if (
            item.shape_key_name in pending_names
            and item.shape_key_name in keys_by_name
        )
    ]
    if not pending:
        return 0

    target_tags = {
        item.shape_key_name: (
            item.function_tag,
            _effective_reference_tag(item),
        )
        for item in shape_keys.ho_rebase_items
        if item.shape_key_name in keys_by_name
    }
    left_is_positive, resolved = _core._fbsf_resolve_target_side_tags(
        target_tags,
        _source_orientation(
            shape_keys, target_tags, classification_context, target_delta),
        basis_positions,
        classification_context,
        target_delta,
        resolve_mmd=True,
    )
    resolved = _core._fbsf_resolve_keyword_eye_tags(
        resolved,
        basis_positions,
        left_is_positive,
        classification_context,
        target_delta,
    )
    for item in pending:
        resolved_tag = resolved.get(
            item.shape_key_name,
            (item.function_tag, item.reference_tag),
        )
        item.function_tag, item.reference_tag = resolved_tag
        item.auto_function_tag, item.auto_reference_tag = resolved_tag
        item.initialized = True
    shape_keys.ho_rebase_left_is_positive = 1 if left_is_positive else -1
    return len(pending)


def _name_tokens(shape_name):
    normalized = unicodedata.normalize('NFKC', shape_name)
    normalized = normalized.strip().lstrip('@+').strip()
    split_name = _CAMEL_BOUNDARY.sub(' ', normalized)
    tokens = frozenset(
        token.casefold() for token in _ASCII_TOKEN.findall(split_name))
    return normalized.casefold(), tokens


def _has_deformation(delta):
    vertex_energy = np.einsum('ij,ij->i', delta, delta)
    return (
        np.all(np.isfinite(vertex_energy))
        and float(np.sum(vertex_energy, dtype=np.float64)) >= 1e-10
    )


def _aggressive_eye_geometry_tag(
        delta, basis_positions, left_is_positive=True):
    """显式选中后使用较宽松的形变能量比例判定左右眼。"""
    delta = np.asarray(delta)
    basis_positions = np.asarray(basis_positions)
    if (
            delta.ndim != 2
            or delta.shape[1:] != (3,)
            or delta.shape != basis_positions.shape
            or len(delta) == 0):
        return None
    vertex_energy = np.einsum('ij,ij->i', delta, delta)
    if not np.all(np.isfinite(vertex_energy)):
        return None
    total_energy = float(np.sum(vertex_energy, dtype=np.float64))
    if total_energy < 1e-10:
        return None

    left_mask, right_mask = _core._fbsf_side_masks(
        basis_positions, left_is_positive)
    left_energy = float(np.sum(vertex_energy[left_mask], dtype=np.float64))
    right_energy = float(np.sum(vertex_energy[right_mask], dtype=np.float64))
    side_energy = left_energy + right_energy
    if side_energy < 1e-10 or side_energy / total_energy < 0.5:
        return None

    left_fraction = left_energy / side_energy
    if left_fraction >= 0.65:
        return 'LEFT_EYE'
    if left_fraction <= 0.35:
        return 'RIGHT_EYE'
    return 'BOTH_EYES'


def _aggressive_selected_tag(
        shape_name, delta, basis_positions, left_is_positive, context):
    """精确标准优先；未知名称再使用更积极的语义和几何判断。"""
    exact = _core._fbsf_auto_preset(shape_name, context=context)
    if (
            exact.function_tag != 'OTHERS'
            or exact.reference_tag != 'OTHERS'
            or exact.standards):
        return exact.function_tag, exact.reference_tag

    normalized, tokens = _name_tokens(shape_name)
    has_mouth_name = bool(tokens & _MOUTH_TOKENS)
    has_mouth_name = has_mouth_name or any(
        text in normalized for text in ('口', '唇', '舌'))
    strict_eye_name = _core._fbsf_keyword_eye_name(shape_name) is not None
    has_eye_name = strict_eye_name or bool(tokens & _EYE_TOKENS)
    has_eye_name = has_eye_name or any(
        text in normalized for text in ('目', '眼', '瞼', 'まばたき', 'ウィンク'))
    if tokens & _EYE_BLOCKED_TOKENS:
        has_eye_name = False
    if not _has_deformation(delta) or has_eye_name == has_mouth_name:
        return 'OTHERS', 'OTHERS'
    if has_mouth_name:
        return 'MOUTH', 'MOUTH'

    function_tag = _aggressive_eye_geometry_tag(
        delta, basis_positions, left_is_positive)
    if function_tag is None:
        return 'OTHERS', 'OTHERS'
    reference_tag = (
        'OTHERS' if tokens & _GAZE_TOKENS else function_tag)
    return function_tag, reference_tag


def infer_selected(obj):
    """更积极地重新推断勾选行；未选中行只提供上下文，不会被修改。"""
    shape_keys = _shape_key_data(obj)
    if shape_keys is None:
        return 0, 0
    selected_names = {
        item.shape_key_name for item in shape_keys.ho_rebase_items
        if item.selected
    }
    if not selected_names:
        return 0, 0
    data = _build_inference_data(obj)
    if data is None:
        return 0, 0
    (
        shape_keys,
        basis_positions,
        keys_by_name,
        classification_context,
        target_delta,
    ) = data
    selected = [
        item for item in shape_keys.ho_rebase_items
        if (
            item.shape_key_name in selected_names
            and item.shape_key_name in keys_by_name
        )
    ]
    if not selected:
        return 0, 0

    target_tags = {}
    for item in shape_keys.ho_rebase_items:
        if item.shape_key_name not in keys_by_name:
            continue
        if item.shape_key_name in selected_names:
            preset = _core._fbsf_auto_preset(
                item.shape_key_name, context=classification_context)
            target_tags[item.shape_key_name] = (
                preset.function_tag,
                preset.reference_tag,
            )
        else:
            target_tags[item.shape_key_name] = (
                item.function_tag,
                _effective_reference_tag(item),
            )

    left_is_positive, resolved = _core._fbsf_resolve_target_side_tags(
        target_tags,
        _source_orientation(
            shape_keys, target_tags, classification_context, target_delta),
        basis_positions,
        classification_context,
        target_delta,
        resolve_mmd=True,
    )
    classified_count = 0
    for item in selected:
        function_tag, reference_tag = resolved[item.shape_key_name]
        if (function_tag, reference_tag) == ('OTHERS', 'OTHERS'):
            function_tag, reference_tag = _aggressive_selected_tag(
                item.shape_key_name,
                target_delta(item.shape_key_name),
                basis_positions,
                left_is_positive,
                classification_context,
            )
        item.function_tag = function_tag
        item.reference_tag = reference_tag
        item.auto_function_tag = function_tag
        item.auto_reference_tag = reference_tag
        item.initialized = True
        if function_tag != 'OTHERS':
            classified_count += 1
    shape_keys.ho_rebase_left_is_positive = 1 if left_is_positive else -1
    return len(selected), classified_count


__all__ = ("infer_uninitialized", "infer_selected")
