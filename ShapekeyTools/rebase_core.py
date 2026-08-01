"""FBSF 分类、推断与原子变基核心。"""

from dataclasses import dataclass
import re
import unicodedata

import numpy as np

from Utils import shapekey_utils

try:
    from . import shapekey_catalog as _shape_key_catalog
except ImportError:  # 兼容直接导入脚本
    import shapekey_catalog as _shape_key_catalog


class ShapeKeyRebaseError(RuntimeError):
    pass


# FBSF 的“区域”不是顶点遮罩，而是形态键的功能分类。合并开关只决定哪些键烘焙进
# Basis；来源和目标的功能标签共同决定是否进行眼睛或嘴部反向修正。
FBSF_FUNCTION_ITEMS = (
    ('BOTH_EYES', "双眼", "与双眼、左眼或右眼键进行 FBSF 修正"),
    ('LEFT_EYE', "左眼", "只参与左眼一侧的 FBSF 修正"),
    ('RIGHT_EYE', "右眼", "只参与右眼一侧的 FBSF 修正"),
    ('MOUTH', "嘴部", "只与嘴部键进行 FBSF 修正"),
    ('OTHERS', "其他", "跟随普通全局变基，不进行 FBSF 反向修正"),
)
FBSF_FUNCTION_TAGS = frozenset(item[0] for item in FBSF_FUNCTION_ITEMS)

_FBSF_TAG_CHANNELS = {
    'BOTH_EYES': frozenset({'LEFT_EYE', 'RIGHT_EYE'}),
    'LEFT_EYE': frozenset({'LEFT_EYE'}),
    'RIGHT_EYE': frozenset({'RIGHT_EYE'}),
    'MOUTH': frozenset({'MOUTH'}),
    'OTHERS': frozenset(),
}
def _fbsf_tag_channels(function_tag):
    return _FBSF_TAG_CHANNELS.get(function_tag, frozenset())


@dataclass(frozen=True)
class _FBSFShapePreset:
    function_tag: str = 'OTHERS'
    reference_tag: str = 'OTHERS'
    standards: frozenset = frozenset()
    semantic: str = 'OTHER'
    side_reliable: bool = False

    @property
    def standard(self):
        """兼容只读诊断；算法使用完整 standards 集合。"""
        if not self.standards:
            return 'UNKNOWN'
        if len(self.standards) == 1:
            return next(iter(self.standards))
        return '|'.join(sorted(self.standards))


_FBSF_BLENDER_SUFFIX = re.compile(r"\.\d{3,}$")
_FBSF_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_FBSF_ASCII_NAME_TOKEN = re.compile(r"[A-Za-z]+|\d+")
_FBSF_EYE_ACTION_COMPOUND = re.compile(
    r"(?:eye|face|auto|vrc)?(blink|wink)(?:left|right|l|r|\d+)*$")
_FBSF_KEYWORD_EYE_BLOCKED_TOKENS = frozenset({
    'backup', 'bak', 'base', 'basis', 'bone', 'brow', 'control', 'ctrl',
    'copy', 'correct', 'correction', 'corrective', 'debug', 'delete',
    'disabled', 'driver', 'fix', 'for',
    'frown', 'happy', 'helper', 'iris', 'jaw', 'joy', 'laugh', 'light',
    'joint', 'lip', 'lips', 'mask', 'material', 'mouth', 'old', 'phoneme',
    'proxy', 'rig',
    'pupil', 'reference', 'ref', 'sculpt', 'separator', 'smile', 'temp',
    'test', 'tex', 'texture', 'tmp', 'tongue', 'unused', 'viseme',
})
_FBSF_KEYWORD_EYE_BLOCKED_TEXT = (
    'バックアップ', 'コピー', 'テスト', 'マウス', 'リップ', '修正',
    '補助', '口', '舌', '笑',
)
_FBSF_KEYWORD_MIN_ACTIVE_VERTICES = 4
_FBSF_KEYWORD_MIN_SIDE_VERTEX_COVERAGE = 0.7
_FBSF_KEYWORD_MIN_SIDE_ENERGY_COVERAGE = 0.9
_FBSF_KEYWORD_SIDE_COUNT_DOMINANCE = 0.75
_FBSF_KEYWORD_SIDE_ENERGY_DOMINANCE = 0.95
_FBSF_KEYWORD_BILATERAL_LOWER = 0.35
_FBSF_KEYWORD_BILATERAL_UPPER = 0.65


def _fbsf_normalized_names(shape_name):
    """返回 NFKC 规范名，以及反复去掉 Blender 数字后缀的候选。"""
    return _shape_key_catalog.normalized_shape_key_names(shape_name)


def _fbsf_normalized_name(shape_name):
    return _shape_key_catalog.normalize_shape_key_name(shape_name)


def _fbsf_keyword_eye_name(shape_name):
    """保守识别眼睛动作类型，以及名称是否明确包含左右侧。"""
    normalized = unicodedata.normalize('NFKC', shape_name)
    normalized = normalized.strip().lstrip('@+').strip()
    while _FBSF_BLENDER_SUFFIX.search(normalized):
        normalized = _FBSF_BLENDER_SUFFIX.sub('', normalized)
    split_name = _FBSF_CAMEL_BOUNDARY.sub(' ', normalized)
    tokens = frozenset(
        token.casefold()
        for token in _FBSF_ASCII_NAME_TOKEN.findall(split_name)
    )
    if (
            tokens & _FBSF_KEYWORD_EYE_BLOCKED_TOKENS
            or any(text in normalized for text in _FBSF_KEYWORD_EYE_BLOCKED_TEXT)):
        return None

    action = None
    if 'wink' in tokens:
        action = 'WINK'
    elif 'blink' in tokens:
        action = 'BLINK'
    else:
        for token in tokens:
            match = _FBSF_EYE_ACTION_COMPOUND.fullmatch(token)
            if match is not None:
                action = match.group(1).upper()
                break
    if action is None:
        if 'ウィンク' in normalized or 'ウインク' in normalized:
            action = 'WINK'
        elif (
                'まばたき' in normalized
                or '眨眼' in normalized
                or '闭眼' in normalized
                or '閉眼' in normalized):
            action = 'BLINK'
    if action is None:
        return None

    sided = bool(tokens & {'left', 'right', 'l', 'r'})
    sided = sided or any(
        'left' in token
        or 'right' in token
        or re.search(r'(?:blink|wink)\d*[lr]\d*$', token) is not None
        for token in tokens
    )
    sided = sided or '左' in normalized or '右' in normalized
    return action, sided


_FBSF_EYE_SIDE_TAGS = {
    'BOTH': 'BOTH_EYES',
    'LEFT': 'LEFT_EYE',
    'RIGHT': 'RIGHT_EYE',
}


def _fbsf_catalog_entry_to_preset(entry):
    """把通用目录语义适配为 FBSF 的权能和参考权能。"""
    if entry.region == 'MOUTH':
        function_tag = reference_tag = 'MOUTH'
    elif entry.region == 'EYE':
        function_tag = _FBSF_EYE_SIDE_TAGS.get(entry.side, 'OTHERS')
        reference_tag = (
            function_tag if entry.semantic == 'EYELID' else 'OTHERS')
    else:
        function_tag = reference_tag = 'OTHERS'
    return _FBSFShapePreset(
        function_tag,
        reference_tag,
        entry.families,
        entry.semantic,
        entry.side_reliable,
    )


def _fbsf_classification_context(shape_names):
    return _shape_key_catalog.build_shape_key_context(shape_names)


def _fbsf_auto_preset(shape_name, shape_names=None, context=None):
    """以精确标准语义优先，保守识别一个形态键的 FBSF 权能。"""
    classification = _shape_key_catalog.classify_shape_key(
        shape_name,
        shape_names,
        context=context,
    )
    return _fbsf_catalog_entry_to_preset(classification)


def _fbsf_auto_function_tag(shape_name, shape_names=None, context=None):
    return _fbsf_auto_preset(
        shape_name, shape_names=shape_names, context=context).function_tag


def _fbsf_threshold_map(value, lower=0.05, upper=0.95):
    """截断本地近似算子计算出的相似度权重。"""
    if value <= lower:
        return 0.0
    if value >= upper:
        return 1.0
    return round(float(value), 3)


def _fbsf_side_similarity(target_delta, edit_delta, side_mask):
    """按内积启发式计算单侧反向修正权重。"""
    side_target = target_delta[side_mask]
    side_edit = edit_delta[side_mask]
    if len(side_edit) == 0:
        return 0.0

    target_energy = np.einsum("ij,ij->i", side_target, side_target)
    edit_vertex_energy = np.einsum("ij,ij->i", side_edit, side_edit)
    active = (target_energy >= 1e-10) | (edit_vertex_energy >= 1e-10)
    dot = np.einsum("ij,ij->i", side_target[active], side_edit[active])
    # 原实现对反向位移保留一半相似度，而不是直接把负内积归零。
    similarity_sum = float(np.sum(
        np.where(dot > 0.0, dot, -0.5 * dot), dtype=np.float64))
    edit_energy = float(np.sum(edit_vertex_energy[active], dtype=np.float64))
    if edit_energy < 1e-10:
        return 0.0
    score = np.clip(similarity_sum / edit_energy, 0.0, 1.0)
    return _fbsf_threshold_map(score)


def _fbsf_similarity(target_delta, edit_delta):
    """复刻源仓库嘴部定义使用的全网格内积相似度。"""
    target_energy = np.einsum("ij,ij->i", target_delta, target_delta)
    edit_vertex_energy = np.einsum("ij,ij->i", edit_delta, edit_delta)
    active = (target_energy >= 1e-10) | (edit_vertex_energy >= 1e-10)
    edit_energy = float(np.sum(edit_vertex_energy[active], dtype=np.float64))
    if edit_energy < 1e-10:
        return 0.0
    dot_sum = float(np.sum(
        np.einsum("ij,ij->i", target_delta[active], edit_delta[active]),
        dtype=np.float64,
    ))
    return _fbsf_threshold_map(np.clip(dot_sum / edit_energy, 0.0, 1.0))


def _fbsf_side_masks(basis_positions, left_is_positive=True):
    """返回角色语义上的左右侧；标准模型的角色左眼位于局部 +X。"""
    x = basis_positions[:, 0]
    positive_mask = x > 0.0
    negative_mask = x < 0.0
    if left_is_positive:
        return positive_mask, negative_mask
    return negative_mask, positive_mask


def _fbsf_dominant_eye_side_tag(
        delta, basis_positions, left_is_positive=True, dominance=0.8):
    """仅在形变几何明确单侧时返回语义左右侧。"""
    left_mask, right_mask = _fbsf_side_masks(
        basis_positions, left_is_positive)
    left_energy = float(np.sum(
        delta[left_mask] * delta[left_mask], dtype=np.float64))
    right_energy = float(np.sum(
        delta[right_mask] * delta[right_mask], dtype=np.float64))
    total_energy = left_energy + right_energy
    if total_energy < 1e-10:
        return None
    left_fraction = left_energy / total_energy
    if left_fraction >= dominance:
        return 'LEFT_EYE'
    if left_fraction <= 1.0 - dominance:
        return 'RIGHT_EYE'
    return None


def _fbsf_keyword_eye_geometry_tag(
        delta, basis_positions, left_is_positive=True,
        minimum_active_vertices=_FBSF_KEYWORD_MIN_ACTIVE_VERTICES):
    """仅在顶点数量和位移能量一致时分类关键字候选。"""
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
    active_threshold = max(
        1e-12, float(np.max(vertex_energy)) * 1e-6)
    active = vertex_energy >= active_threshold
    active_count = int(np.count_nonzero(active))
    if active_count < minimum_active_vertices:
        return None

    left_mask, right_mask = _fbsf_side_masks(
        basis_positions, left_is_positive)
    left_active = active & left_mask
    right_active = active & right_mask
    left_count = int(np.count_nonzero(left_active))
    right_count = int(np.count_nonzero(right_active))
    side_count = left_count + right_count
    side_vertex_coverage = side_count / active_count
    if (
            side_count < minimum_active_vertices
            or side_vertex_coverage < _FBSF_KEYWORD_MIN_SIDE_VERTEX_COVERAGE):
        return None

    left_energy = float(np.sum(
        vertex_energy[left_active], dtype=np.float64))
    right_energy = float(np.sum(
        vertex_energy[right_active], dtype=np.float64))
    side_energy = left_energy + right_energy
    if side_energy / total_energy < _FBSF_KEYWORD_MIN_SIDE_ENERGY_COVERAGE:
        return None

    left_count_fraction = left_count / side_count
    left_energy_fraction = left_energy / side_energy
    right_count_limit = 1.0 - _FBSF_KEYWORD_SIDE_COUNT_DOMINANCE
    right_energy_limit = 1.0 - _FBSF_KEYWORD_SIDE_ENERGY_DOMINANCE
    if (
            left_count_fraction >= _FBSF_KEYWORD_SIDE_COUNT_DOMINANCE
            and left_energy_fraction >= _FBSF_KEYWORD_SIDE_ENERGY_DOMINANCE):
        return 'LEFT_EYE'
    if (
            left_count_fraction <= right_count_limit
            and left_energy_fraction <= right_energy_limit):
        return 'RIGHT_EYE'
    if (
            _FBSF_KEYWORD_BILATERAL_LOWER
            <= left_count_fraction
            <= _FBSF_KEYWORD_BILATERAL_UPPER
            and _FBSF_KEYWORD_BILATERAL_LOWER
            <= left_energy_fraction
            <= _FBSF_KEYWORD_BILATERAL_UPPER):
        return 'BOTH_EYES'
    return None


def _fbsf_keyword_eye_preset(
        shape_name, delta, basis_positions, left_is_positive=True,
        context=None):
    """根据名称和形变几何推断未知的 wink/blink 键。"""
    exact = _fbsf_auto_preset(shape_name, context=context)
    if (
            exact.function_tag != 'OTHERS'
            or exact.reference_tag != 'OTHERS'
            or exact.standards):
        return None
    name_evidence = _fbsf_keyword_eye_name(shape_name)
    if name_evidence is None:
        return None
    action, explicitly_sided = name_evidence
    geometry_tag = _fbsf_keyword_eye_geometry_tag(
        delta, basis_positions, left_is_positive)
    if geometry_tag is None:
        return None
    if geometry_tag == 'BOTH_EYES' and (
            action == 'WINK' or explicitly_sided):
        return None
    return _FBSFShapePreset(
        geometry_tag,
        geometry_tag,
        frozenset({'KEYWORD_GEOMETRY'}),
        'EYELID',
    )


def _fbsf_resolve_mmd_side_tag(
        shape_name, function_tag, reference_tag, delta, basis_positions,
        left_is_positive=True, context=None):
    """导出器左右约定不同时，根据几何解析 MMD wink 的语义侧。"""
    preset = _fbsf_auto_preset(shape_name, context=context)
    if (
            'MMD' not in preset.standards
            or preset.semantic != 'EYELID'
            or function_tag not in {'LEFT_EYE', 'RIGHT_EYE'}
            or (function_tag, reference_tag)
            != (preset.function_tag, preset.reference_tag)):
        return function_tag, reference_tag
    geometric_tag = _fbsf_dominant_eye_side_tag(
        delta, basis_positions, left_is_positive)
    if geometric_tag is None:
        return function_tag, reference_tag
    if reference_tag in {'LEFT_EYE', 'RIGHT_EYE'}:
        reference_tag = geometric_tag
    return geometric_tag, reference_tag


def _fbsf_infer_left_is_positive(
        tagged_deltas, basis_positions, fallback=True, dominance=0.8):
    """用单眼键的位移能量推断角色左眼位于局部 X 的哪一侧。"""
    positive_mask = basis_positions[:, 0] > 0.0
    negative_mask = basis_positions[:, 0] < 0.0
    minimum_bias = dominance * 2.0 - 1.0
    evidence = set()
    for function_tag, delta in tagged_deltas:
        channels = _fbsf_tag_channels(function_tag)
        eye_channels = channels & {'LEFT_EYE', 'RIGHT_EYE'}
        if len(eye_channels) != 1:
            continue
        positive_energy = float(np.sum(
            delta[positive_mask] * delta[positive_mask], dtype=np.float64))
        negative_energy = float(np.sum(
            delta[negative_mask] * delta[negative_mask], dtype=np.float64))
        total_energy = positive_energy + negative_energy
        if total_energy < 1e-10:
            continue
        direction = (positive_energy - negative_energy) / total_energy
        semantic_direction = (
            direction if 'LEFT_EYE' in eye_channels else -direction)
        if abs(semantic_direction) + 1e-12 < minimum_bias:
            continue
        evidence.add(semantic_direction > 0.0)

    # 弱证据、缺失证据或相互冲突的来源不能覆盖已知标准。
    if len(evidence) != 1:
        return fallback
    return evidence.pop()


def _fbsf_resolve_target_side_tags(
        target_tags, source_orientation, basis_positions, context,
        target_delta, resolve_mmd=True, orientation_override=None):
    """推断角色左右，并可在 UI 预处理阶段解析 MMD 单眼名称。"""
    left_is_positive = orientation_override
    if left_is_positive is None:
        left_is_positive = _fbsf_infer_left_is_positive(
            source_orientation, basis_positions, fallback=None)
        if left_is_positive is None:
            standard_orientation = []
            for shape_name, (_function_tag, reference_tag) in target_tags.items():
                reference_eye_channels = (
                    _fbsf_tag_channels(reference_tag)
                    & {'LEFT_EYE', 'RIGHT_EYE'}
                )
                if len(reference_eye_channels) != 1:
                    continue
                preset = _fbsf_auto_preset(shape_name, context=context)
                if not preset.side_reliable:
                    continue
                standard_orientation.append(
                    (reference_tag, target_delta(shape_name)))
            left_is_positive = _fbsf_infer_left_is_positive(
                standard_orientation, basis_positions, fallback=True)

    resolved_tags = dict(target_tags)
    if not resolve_mmd:
        return left_is_positive, resolved_tags
    for shape_name, (function_tag, reference_tag) in target_tags.items():
        preset = _fbsf_auto_preset(shape_name, context=context)
        if (
                'MMD' not in preset.standards
                or preset.semantic != 'EYELID'
                or function_tag not in {'LEFT_EYE', 'RIGHT_EYE'}
                or (function_tag, reference_tag)
                != (preset.function_tag, preset.reference_tag)):
            continue
        resolved_tags[shape_name] = _fbsf_resolve_mmd_side_tag(
            shape_name,
            function_tag,
            reference_tag,
            target_delta(shape_name),
            basis_positions,
            left_is_positive,
            context,
        )
    return left_is_positive, resolved_tags


def _fbsf_resolve_keyword_eye_tags(
        target_tags, basis_positions, left_is_positive, context,
        target_delta):
    """应用受几何约束的关键字预设，不改变精确匹配结果。"""
    resolved_tags = dict(target_tags)
    for shape_name, (function_tag, reference_tag) in target_tags.items():
        if (function_tag, reference_tag) != ('OTHERS', 'OTHERS'):
            continue
        if _fbsf_keyword_eye_name(shape_name) is None:
            continue
        exact = _fbsf_auto_preset(shape_name, context=context)
        if exact.standards:
            continue
        preset = _fbsf_keyword_eye_preset(
            shape_name,
            target_delta(shape_name),
            basis_positions,
            left_is_positive,
            context,
        )
        if preset is None:
            continue
        resolved_tags[shape_name] = (
            preset.function_tag,
            preset.reference_tag,
        )
    return resolved_tags


def _fbsf_split_side_weights(
        left_score, right_score, basis_positions,
        smooth_width, left_is_positive=True):
    """把语义左右分数映射到局部 X，并在中线处保持对称。"""
    x = basis_positions[:, 0]
    positive_score, negative_score = (
        (left_score, right_score)
        if left_is_positive else (right_score, left_score)
    )
    if smooth_width <= 0.0:
        center_score = (left_score + right_score) * 0.5
        return np.where(
            x > 0.0,
            positive_score,
            np.where(x < 0.0, negative_score, center_score),
        )

    positive_factor = np.clip(
        (x + smooth_width) / (2.0 * smooth_width), 0.0, 1.0)
    return (
        negative_score * (1.0 - positive_factor)
        + positive_score * positive_factor
    )


def _fbsf_source_definition(
        source_delta, references, basis_positions, source_function_tag=None,
        left_is_positive=True):
    """根据同类参考键，生成一个合并来源的左右眼和嘴部定义。"""
    left_mask, right_mask = _fbsf_side_masks(
        basis_positions, left_is_positive)
    left_eye = 0.0
    right_eye = 0.0
    mouth = 0.0
    for function_tag, reference_delta in references:
        channels = _fbsf_tag_channels(function_tag)
        if 'LEFT_EYE' in channels:
            left_eye = max(
                left_eye,
                _fbsf_side_similarity(reference_delta, source_delta, left_mask),
            )
        if 'RIGHT_EYE' in channels:
            right_eye = max(
                right_eye,
                _fbsf_side_similarity(reference_delta, source_delta, right_mask),
            )
        if 'MOUTH' in channels:
            mouth = max(mouth, _fbsf_similarity(reference_delta, source_delta))
    if source_function_tag is None:
        return left_eye, right_eye, mouth
    source_channels = _fbsf_tag_channels(source_function_tag)
    return (
        left_eye if 'LEFT_EYE' in source_channels else 0.0,
        right_eye if 'RIGHT_EYE' in source_channels else 0.0,
        mouth if 'MOUTH' in source_channels else 0.0,
    )


def _fbsf_definition_weights(
        function_tag, definition, basis_positions,
        smooth_width, correction_strength, left_is_positive=True):
    """按目标键功能解析源仓库 ShapeType 对应的逐顶点修正权重。"""
    left_eye, right_eye, mouth = definition
    channels = _fbsf_tag_channels(function_tag)
    has_left = 'LEFT_EYE' in channels
    has_right = 'RIGHT_EYE' in channels
    has_mouth = 'MOUTH' in channels
    if has_left and has_right:
        left_score, right_score = left_eye, right_eye
        split_sides = abs(left_score - right_score) > 0.1
    elif has_left:
        left_score, right_score, split_sides = left_eye, 0.0, True
    elif has_right:
        left_score, right_score, split_sides = 0.0, right_eye, True
    else:
        left_score, right_score, split_sides = 0.0, 0.0, False

    weights = np.zeros(len(basis_positions), dtype=np.float32)
    if has_left or has_right:
        if split_sides:
            eye_weights = _fbsf_split_side_weights(
                left_score,
                right_score,
                basis_positions,
                smooth_width,
                left_is_positive,
            )
        else:
            eye_weights = np.full(
                len(basis_positions),
                (left_score + right_score) * 0.5,
                dtype=np.float32,
            )
        weights = np.maximum(weights, eye_weights)
    if has_mouth:
        weights = np.maximum(weights, mouth)
        left_score = max(left_score, mouth)
        right_score = max(right_score, mouth)
    return (
        np.asarray(weights, dtype=np.float32) * correction_strength,
        left_score,
        right_score,
        split_sides,
    )


def _validate_shape_key_rebase_data(obj, minimum_keys=2):
    """校验所有破坏性变基流程共用的网格与相对键数据前置条件。"""
    if obj is None or obj.type != 'MESH':
        raise ShapeKeyRebaseError("活动对象不是网格")
    if obj.data.library is not None:
        raise ShapeKeyRebaseError("链接库网格不可直接变基，请先建立本地副本")
    if obj.data.users > 1:
        raise ShapeKeyRebaseError("网格数据被多个物体共享，请先转为单用户")

    shape_keys = obj.data.shape_keys
    if shape_keys is None or len(shape_keys.key_blocks) < minimum_keys:
        raise ShapeKeyRebaseError("对象没有足够的形态键")
    if not shape_keys.use_relative:
        raise ShapeKeyRebaseError("只支持相对形态键；请先切换为相对模式")

    basis = shape_keys.reference_key
    if basis is None:
        raise ShapeKeyRebaseError("形态键数据缺少基型")
    try:
        shapekey_utils.validate_shape_key_vertex_counts(
            shape_keys, len(basis.data))
    except shapekey_utils.ShapeKeyUtilsError as exc:
        raise ShapeKeyRebaseError(str(exc)) from exc
    for key in shape_keys.key_blocks:
        if key != basis and key.relative_key is None:
            raise ShapeKeyRebaseError(f"形态键 {key.name} 缺少相对键")
    return shape_keys, basis


def _validate_shape_key_rebase_object(obj):
    shape_keys, basis = _validate_shape_key_rebase_data(obj)
    active_key = obj.active_shape_key
    if basis is None or active_key is None or active_key == basis:
        raise ShapeKeyRebaseError("请选择一个作为新基型来源的非基型形态键")
    if active_key.relative_key != basis:
        raise ShapeKeyRebaseError("活动捏脸键必须直接相对于基型")

    nonzero_keys = [
        key.name for key in shape_keys.key_blocks
        if key not in {basis, active_key} and abs(key.value) > 1e-6
    ]
    if nonzero_keys:
        preview = "、".join(nonzero_keys[:4])
        suffix = "等" if len(nonzero_keys) > 4 else ""
        raise ShapeKeyRebaseError(f"请先把其他形态键权重归零：{preview}{suffix}")

    return shape_keys, basis, active_key


def _rewrite_rebased_shape_key_sources(
        obj, shape_keys, basis, weighted_sources, correction_source,
        rewrite_key):
    """原子烘焙一个或多个来源键，并按相对依赖树重写剩余形态键。"""
    weighted_sources = tuple(weighted_sources)
    sources = {source for source, _weight in weighted_sources}
    if not weighted_sources or correction_source not in sources:
        raise ShapeKeyRebaseError("变基来源键配置无效")
    try:
        ordered_keys = shapekey_utils.relative_shape_key_order(
            shape_keys, excluded=sources)
    except shapekey_utils.ShapeKeyDependencyError as exc:
        raise ShapeKeyRebaseError(str(exc)) from exc

    old_basis = shapekey_utils.read_shape_key_positions(basis)
    source_positions = {
        source.name: shapekey_utils.read_shape_key_positions(source)
        for source, _weight in weighted_sources
    }
    new_basis = old_basis.copy()
    for source, weight in weighted_sources:
        if not np.isfinite(weight) or weight <= 0.0:
            raise ShapeKeyRebaseError(f"来源键 {source.name} 的变基权重无效")
        new_basis += (source_positions[source.name] - old_basis) * weight
    correction_positions = source_positions[correction_source.name]

    child_counts = {key.name: 0 for key in ordered_keys}
    for key in ordered_keys:
        relative = key.relative_key
        if relative != basis and relative not in sources:
            child_counts[relative.name] += 1

    cached_old = {}
    cached_new = {}
    planned_positions = []
    for key in ordered_keys:
        relative = key.relative_key
        if relative == basis:
            old_relative = old_basis
            new_relative = new_basis
        elif relative in sources:
            old_relative = source_positions[relative.name]
            new_relative = new_basis
        else:
            old_relative = cached_old[relative.name]
            new_relative = cached_new[relative.name]

        old_key = shapekey_utils.read_shape_key_positions(key)
        new_key = rewrite_key(
            key, old_key, old_relative, new_relative,
            old_basis, correction_positions, new_basis)
        new_key = np.asarray(new_key, dtype=np.float32)
        if new_key.shape != old_key.shape:
            raise ShapeKeyRebaseError(
                f"形态键 {key.name} 的重建坐标形状无效：{new_key.shape}")
        if not np.all(np.isfinite(new_key)):
            raise ShapeKeyRebaseError(
                f"形态键 {key.name} 的重建坐标包含 NaN 或无穷值")
        planned_positions.append((key, new_key))

        if child_counts[key.name] > 0:
            cached_old[key.name] = old_key
            cached_new[key.name] = new_key
        if relative != basis and relative not in sources:
            child_counts[relative.name] -= 1
            if child_counts[relative.name] == 0:
                cached_old.pop(relative.name, None)
                cached_new.pop(relative.name, None)

    for key, new_key in planned_positions:
        shapekey_utils.write_shape_key_positions(key, new_key)
    for key in ordered_keys:
        if key.relative_key in sources:
            key.relative_key = basis
    shapekey_utils.write_shape_key_positions(basis, new_basis)

    source_names = tuple(source.name for source, _weight in weighted_sources)
    source_order = sorted(
        sources,
        key=lambda key: shape_keys.key_blocks.find(key.name),
        reverse=True,
    )
    for source in source_order:
        obj.shape_key_remove(source)
    obj.active_shape_key_index = 0
    obj.show_only_shape_key = False
    obj.data.update()
    return source_names, len(ordered_keys)


def _rewrite_rebased_shape_key_tree(obj, factor, rewrite_key):
    """兼容单活动来源键的 FBSF 重写入口。"""
    shape_keys, basis, active_key = _validate_shape_key_rebase_object(obj)
    if factor <= 0.0:
        raise ShapeKeyRebaseError("变基权重必须大于 0")
    source_names, key_count = _rewrite_rebased_shape_key_sources(
        obj,
        shape_keys,
        basis,
        ((active_key, factor),),
        active_key,
        rewrite_key,
    )
    return source_names[0], key_count


def _resolve_fbsf_sources(obj, source_specs):
    """解析勾选的合并键，并限制它们直接相对 Basis。"""
    shape_keys, basis = _validate_shape_key_rebase_data(obj)
    shape_names = tuple(key.name for key in shape_keys.key_blocks if key != basis)
    context = _fbsf_classification_context(shape_names)
    tagged_sources = []
    seen = set()
    for source_spec in source_specs:
        if len(source_spec) == 2:
            source_name, factor = source_spec
            function_tag = _fbsf_auto_function_tag(
                source_name, context=context)
        elif len(source_spec) == 3:
            source_name, factor, function_tag = source_spec
        else:
            raise ShapeKeyRebaseError("FBSF 合并键配置格式无效")
        if not source_name or source_name in seen:
            continue
        source = shape_keys.key_blocks.get(source_name)
        if source is None:
            raise ShapeKeyRebaseError(f"找不到合并键：{source_name}")
        if source == basis:
            raise ShapeKeyRebaseError("Basis 不能作为合并键")
        if source.relative_key != basis:
            raise ShapeKeyRebaseError(
                f"合并键 {source.name} 必须直接相对于 Basis")
        if not np.isfinite(factor) or factor <= 0.0:
            raise ShapeKeyRebaseError(
                f"合并键 {source.name} 的变基权重必须大于 0")
        if function_tag not in FBSF_FUNCTION_TAGS:
            raise ShapeKeyRebaseError(
                f"合并键 {source.name} 的功能标签无效：{function_tag}")
        seen.add(source_name)
        tagged_sources.append((source, float(factor), function_tag))
    if not tagged_sources:
        raise ShapeKeyRebaseError("请至少勾选一个合并键")
    return shape_keys, basis, tuple(tagged_sources)


def _fbsf_current_source_specs(obj):
    """为脚本直接执行收集当前非零合并键及其自动功能标签。"""
    shape_keys, basis = _validate_shape_key_rebase_data(obj)
    shape_names = tuple(key.name for key in shape_keys.key_blocks if key != basis)
    context = _fbsf_classification_context(shape_names)
    return tuple(
        (
            key.name,
            float(key.value),
            _fbsf_auto_function_tag(key.name, context=context),
        )
        for key in shape_keys.key_blocks
        if (
            key != basis
            and key.relative_key == basis
            and key.value > 1e-6
        )
    )


def _fbsf_auto_target_specs(shape_keys, basis, source_names=()):
    """给非来源键生成可由弹窗覆盖的初始功能分类。"""
    source_names = set(source_names)
    shape_names = tuple(key.name for key in shape_keys.key_blocks if key != basis)
    context = _fbsf_classification_context(shape_names)
    specs = []
    for key in shape_keys.key_blocks:
        if key == basis or key.name in source_names:
            continue
        preset = _fbsf_auto_preset(key.name, context=context)
        specs.append((key.name, preset.function_tag, preset.reference_tag))
    return tuple(specs)


def _resolve_fbsf_target_tags(shape_keys, basis, sources, target_specs):
    """验证手工标签，并为脚本没有传入的目标键补自动分类。"""
    source_names = {source.name for source, _factor, _tag in sources}
    target_tags = {
        shape_name: (function_tag, reference_tag)
        for shape_name, function_tag, reference_tag in (
            _fbsf_auto_target_specs(shape_keys, basis, source_names))
    }
    if target_specs is None:
        return target_tags

    for target_spec in target_specs:
        if len(target_spec) == 2:
            shape_name, function_tag = target_spec
            reference_tag = function_tag
        elif len(target_spec) == 3:
            shape_name, function_tag, reference_tag = target_spec
        else:
            raise ShapeKeyRebaseError("FBSF 目标键配置格式无效")
        if not shape_name or shape_name in source_names:
            continue
        if shape_keys.key_blocks.get(shape_name) is None:
            raise ShapeKeyRebaseError(f"找不到已分类的形态键：{shape_name}")
        if function_tag not in FBSF_FUNCTION_TAGS:
            raise ShapeKeyRebaseError(
                f"形态键 {shape_name} 的 FBSF 功能标签无效：{function_tag}")
        if reference_tag not in FBSF_FUNCTION_TAGS:
            raise ShapeKeyRebaseError(
                f"形态键 {shape_name} 的定义标签无效：{reference_tag}")
        target_tags[shape_name] = (function_tag, reference_tag)
    return target_tags


def _rebase_shape_keys_fbsf(
        obj, source_specs, correction_strength, side_smooth_width,
        target_specs=None, orientation_override=None):
    resolve_automatic_sides = target_specs is None
    shape_keys, basis, tagged_sources = _resolve_fbsf_sources(
        obj, source_specs)
    target_tags = _resolve_fbsf_target_tags(
        shape_keys, basis, tagged_sources, target_specs)
    weighted_sources = tuple(
        (source, factor) for source, factor, _tag in tagged_sources)
    old_basis = shapekey_utils.read_shape_key_positions(basis)
    source_deltas = tuple(
        (
            source,
            factor,
            function_tag,
            shapekey_utils.read_shape_key_positions(source) - old_basis,
        )
        for source, factor, function_tag in tagged_sources
    )
    source_set = {source for source, _factor, _tag in tagged_sources}
    shape_names = tuple(
        key.name for key in shape_keys.key_blocks if key != basis)
    context = _fbsf_classification_context(shape_names)
    source_orientation = tuple(
        (function_tag, source_delta)
        for _source, _factor, function_tag, source_delta in source_deltas
        if len(
            _fbsf_tag_channels(function_tag)
            & {'LEFT_EYE', 'RIGHT_EYE'}) == 1
    )
    keys_by_name = {
        key.name: key
        for key in shape_keys.key_blocks
        if key != basis and key not in source_set
    }
    target_delta_cache = {}

    def target_delta(shape_name):
        cached = target_delta_cache.get(shape_name)
        if cached is not None:
            return cached
        key = keys_by_name[shape_name]
        relative_positions = (
            old_basis
            if key.relative_key == basis
            else shapekey_utils.read_shape_key_positions(key.relative_key)
        )
        delta = (
            shapekey_utils.read_shape_key_positions(key)
            - relative_positions
        )
        target_delta_cache[shape_name] = delta
        return delta

    left_is_positive, target_tags = _fbsf_resolve_target_side_tags(
        target_tags,
        source_orientation,
        old_basis,
        context,
        target_delta,
        resolve_mmd=resolve_automatic_sides,
        orientation_override=orientation_override,
    )
    if resolve_automatic_sides:
        target_tags = _fbsf_resolve_keyword_eye_tags(
            target_tags,
            old_basis,
            left_is_positive,
            context,
            target_delta,
        )
    references = tuple(
        (
            target_tags[key.name][1],
            target_delta(key.name),
        )
        for key in shape_keys.key_blocks
        if (
            key != basis
            and key not in source_set
            and _fbsf_tag_channels(
                target_tags.get(key.name, ('OTHERS', 'OTHERS'))[1])
        )
    )
    source_definitions = tuple(
        (
            source,
            factor,
            source_delta,
            _fbsf_source_definition(
                source_delta,
                references,
                old_basis,
                function_tag,
                left_is_positive,
            ),
        )
        for source, factor, function_tag, source_delta in source_deltas
    )
    # 定义已经压缩为标量，进入原子规划前释放参考位移。
    del references
    target_delta_cache.clear()
    corrected_keys = 0
    applied_links = 0
    split_links = 0
    weight_sum = 0.0

    def rewrite_key(
            _key, old_key, old_relative, new_relative,
            old_basis, _old_active, _new_basis):
        nonlocal corrected_keys, applied_links, split_links, weight_sum
        relative_shift = new_relative - old_relative
        global_rebase = old_key + relative_shift
        correction = np.zeros_like(global_rebase, dtype=np.float32)
        key_corrected = False
        function_tag = target_tags.get(
            _key.name, ('OTHERS', 'OTHERS'))[0]
        for _source, factor, source_delta, definition in source_definitions:
            weights, left_score, right_score, split_sides = (
                _fbsf_definition_weights(
                    function_tag,
                    definition,
                    old_basis,
                    side_smooth_width,
                    correction_strength,
                    left_is_positive,
                )
            )
            mapping_weight = max(left_score, right_score) * correction_strength
            if mapping_weight <= 1e-6:
                continue
            correction += source_delta * (factor * weights[:, None])
            key_corrected = True
            applied_links += 1
            weight_sum += (
                (left_score + right_score) * 0.5 * correction_strength)
            if split_sides:
                split_links += 1
        if key_corrected:
            corrected_keys += 1
        return global_rebase - correction

    source_names, key_count = _rewrite_rebased_shape_key_sources(
        obj,
        shape_keys,
        basis,
        weighted_sources,
        weighted_sources[0][0],
        rewrite_key,
    )
    average_weight = weight_sum / applied_links if applied_links else 0.0
    return (
        source_names,
        key_count,
        corrected_keys,
        applied_links,
        split_links,
        average_weight,
    )



_EXPORT_NAMES = {
    'ShapeKeyRebaseError',
    'FBSF_FUNCTION_ITEMS',
    'FBSF_FUNCTION_TAGS',
    '_rebase_shape_keys_fbsf',
}
_EXPORT_PREFIXES = (
    '_FBSF',
    '_fbsf_',
    '_resolve_fbsf_',
    '_rewrite_rebased_shape_key',
    '_validate_shape_key_rebase',
)
__all__ = tuple(
    name for name in globals()
    if name in _EXPORT_NAMES or name.startswith(_EXPORT_PREFIXES)
)
