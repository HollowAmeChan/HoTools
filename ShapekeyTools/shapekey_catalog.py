"""形态键标准的只读查询入口。"""

from dataclasses import dataclass
import re
import unicodedata

try:
    from .shapekey_catalog_data import (
        SHAPE_KEY_SPECS as _SHAPE_KEY_SPECS,
        STANDARD_INFOS as _STANDARD_INFOS,
        ShapeKeySpec,
        ShapeKeyStandardInfo,
    )
except ImportError:  # 兼容直接导入脚本
    from shapekey_catalog_data import (
        SHAPE_KEY_SPECS as _SHAPE_KEY_SPECS,
        STANDARD_INFOS as _STANDARD_INFOS,
        ShapeKeySpec,
        ShapeKeyStandardInfo,
    )


_BLENDER_NUMERIC_SUFFIX = re.compile(r"\.\d{3,}$")


def _normalized_names(shape_name, *, casefold):
    normalized = unicodedata.normalize('NFKC', shape_name)
    normalized = normalized.strip().lstrip('@+').strip()
    if casefold:
        normalized = normalized.casefold()
    names = {normalized}
    while _BLENDER_NUMERIC_SUFFIX.search(normalized):
        normalized = _BLENDER_NUMERIC_SUFFIX.sub('', normalized)
        names.add(normalized)
    return names


def normalized_shape_key_names(shape_name):
    """返回大小写折叠后的规范名和 Blender 后缀候选。"""
    return _normalized_names(shape_name, casefold=True)


def normalize_shape_key_name(shape_name):
    """返回兼容查询使用的最短大小写折叠规范名。"""
    return min(normalized_shape_key_names(shape_name), key=len)


def normalize_shape_key_exact(shape_name):
    """规范 Unicode 和 Blender 后缀，但保留原始大小写。"""
    return min(_normalized_names(shape_name, casefold=False), key=len)


def _append_index(index, key, value):
    index.setdefault(key, []).append(value)


_STANDARD_BY_ID = {
    info.identifier: info
    for info in _STANDARD_INFOS
}
_BY_EXACT_NAME = {}
_BY_FOLDED_NAME = {}
_BY_STANDARD = {}
_BY_CANONICAL = {}
for _spec in _SHAPE_KEY_SPECS:
    _exact_name = normalize_shape_key_exact(_spec.name)
    _append_index(_BY_EXACT_NAME, _exact_name, _spec)
    _append_index(_BY_FOLDED_NAME, _exact_name.casefold(), _spec)
    _append_index(_BY_STANDARD, _spec.standard, _spec)
    if _spec.canonical is not None:
        _append_index(_BY_CANONICAL, _spec.canonical, _spec)

_CONTEXT_NAMES = {}
_TAG_NAMES = {}
for _spec in _SHAPE_KEY_SPECS:
    folded_name = normalize_shape_key_name(_spec.name)
    if _spec.context is not None:
        _CONTEXT_NAMES.setdefault(_spec.context, set()).add(folded_name)
    for _tag in _spec.tags:
        _TAG_NAMES.setdefault(_tag, set()).add(folded_name)
_CONTEXT_NAMES = {
    key: frozenset(names)
    for key, names in _CONTEXT_NAMES.items()
}
_TAG_NAMES = {
    key: frozenset(names)
    for key, names in _TAG_NAMES.items()
}


@dataclass(frozen=True)
class ShapeKeyContext:
    """一次模型级名称分析的可复用结果。"""

    normalized_names: frozenset
    active_contexts: frozenset


@dataclass(frozen=True)
class ShapeKeyClassification:
    """多个精确记录合并后的保守语义结论。"""

    name: str
    known: bool = False
    ambiguous: bool = False
    region: str = 'OTHER'
    side: str = 'NONE'
    semantic: str = 'OTHER'
    canonical: str | None = None
    standard_ids: frozenset = frozenset()
    families: frozenset = frozenset()
    side_reliable: bool = False
    tags: frozenset = frozenset()
    source_urls: tuple = ()
    specs: tuple = ()


def list_standards(category=None):
    """按 UI 顺序返回标准；可按类别筛选。"""
    if category is None:
        return _STANDARD_INFOS
    return tuple(
        info for info in _STANDARD_INFOS
        if category in info.categories
    )


def get_standard(standard_id):
    """获取一个标准的信息；未知 ID 返回 None。"""
    return _STANDARD_BY_ID.get(standard_id)


def get_standard_items(category=None):
    """返回可直接用于 Blender EnumProperty 的标准项目。"""
    return tuple(
        (info.identifier, info.label, info.description)
        for info in list_standards(category)
    )


def get_standard_specs(standard_id, *, templates_only=False):
    """按声明顺序返回一个标准的全部键记录。"""
    specs = tuple(_BY_STANDARD.get(standard_id, ()))
    if templates_only:
        return tuple(spec for spec in specs if spec.is_template)
    return specs


def get_template_names(standard_id):
    """返回一键添加所需的原始模板名称。"""
    return tuple(
        spec.name
        for spec in get_standard_specs(standard_id, templates_only=True)
    )


def find_shape_keys(shape_name, standard=None, *, casefold_fallback=True):
    """在指定标准内优先精确查找，再进行大小写兼容匹配。"""
    exact_name = normalize_shape_key_exact(shape_name)
    specs = tuple(_BY_EXACT_NAME.get(exact_name, ()))
    if standard is not None:
        specs = tuple(spec for spec in specs if spec.standard == standard)
    if not specs and casefold_fallback:
        specs = tuple(_BY_FOLDED_NAME.get(exact_name.casefold(), ()))
        if standard is not None:
            specs = tuple(
                spec for spec in specs
                if spec.standard == standard
            )
    return specs


def find_equivalent_specs(canonical, standard=None, *, templates_only=False):
    """按 canonical ID 查找跨标准等价记录。"""
    specs = tuple(_BY_CANONICAL.get(canonical, ()))
    if standard is not None:
        specs = tuple(spec for spec in specs if spec.standard == standard)
    if templates_only:
        specs = tuple(spec for spec in specs if spec.is_template)
    return specs


def find_equivalent_names(canonical, standard=None, *, templates_only=False):
    """按 canonical ID 返回去重后的原始名称。"""
    names = []
    for spec in find_equivalent_specs(
            canonical, standard, templates_only=templates_only):
        if spec.name not in names:
            names.append(spec.name)
    return tuple(names)


def build_shape_key_context(shape_names):
    """检测只在整套标准中才能确定语义的短音素。"""
    normalized = frozenset(
        normalize_shape_key_name(name)
        for name in (shape_names or ())
    )
    active = set()

    vrm_visemes = _CONTEXT_NAMES.get('VRM0_VISEME', frozenset())
    vrm_markers = _TAG_NAMES.get('VRM0_MARKER', frozenset())
    vrm_count = len(normalized & vrm_visemes)
    if (
            vrm_count == len(vrm_visemes)
            or (vrm_count >= 3 and bool(normalized & vrm_markers))):
        active.add('VRM0_VISEME')

    pico_visemes = _CONTEXT_NAMES.get('PICO_VISEME', frozenset())
    pico_long = _TAG_NAMES.get('PICO_LONG', frozenset())
    pico_count = len(normalized & pico_visemes)
    if (
            len(normalized & pico_long) >= 4
            or ('xx' in normalized and pico_count >= 5)):
        active.add('PICO_VISEME')

    meta_visemes = _CONTEXT_NAMES.get('META_VISEME', frozenset())
    meta_long = _TAG_NAMES.get('META_LONG', frozenset())
    if (
            len(normalized & meta_long) >= 4
            or len(normalized & meta_visemes) >= 5):
        active.add('META_VISEME')

    return ShapeKeyContext(normalized, frozenset(active))


def _ordered_sources(specs):
    urls = []
    for spec in specs:
        for url in spec.source_urls:
            if url not in urls:
                urls.append(url)
    return tuple(urls)


def classify_shape_key(
        shape_name, shape_names=None, *, context=None,
        standard=None, casefold_fallback=True):
    """查询一个键的语义；冲突候选保守返回 Other。"""
    specs = find_shape_keys(
        shape_name,
        standard,
        casefold_fallback=casefold_fallback,
    )
    if context is None:
        context = build_shape_key_context(shape_names)

    standard_ids = frozenset(spec.standard for spec in specs)
    families = frozenset(spec.family for spec in specs)
    tags = frozenset(tag for spec in specs for tag in spec.tags)
    active_specs = tuple(
        spec for spec in specs
        if spec.context is None or spec.context in context.active_contexts
    )
    meaningful = tuple(
        spec for spec in active_specs
        if spec.semantic != 'OTHER'
    )
    if not meaningful:
        return ShapeKeyClassification(
            name=shape_name,
            known=bool(specs),
            standard_ids=standard_ids,
            families=families,
            tags=tags,
            source_urls=_ordered_sources(specs),
            specs=specs,
        )

    meanings = {
        (spec.region, spec.side, spec.semantic)
        for spec in meaningful
    }
    if len(meanings) != 1:
        return ShapeKeyClassification(
            name=shape_name,
            known=True,
            ambiguous=True,
            standard_ids=standard_ids,
            families=families,
            tags=tags,
            source_urls=_ordered_sources(specs),
            specs=specs,
        )

    region, side, semantic = next(iter(meanings))
    canonicals = {
        spec.canonical
        for spec in meaningful
        if spec.canonical is not None
    }
    canonical = next(iter(canonicals)) if len(canonicals) == 1 else None
    return ShapeKeyClassification(
        name=shape_name,
        known=True,
        region=region,
        side=side,
        semantic=semantic,
        canonical=canonical,
        standard_ids=standard_ids,
        families=families,
        side_reliable=any(spec.side_reliable for spec in meaningful),
        tags=tags,
        source_urls=_ordered_sources(specs),
        specs=specs,
    )


def get_sources(record):
    """统一读取标准、键记录或分类结果的来源。"""
    return tuple(getattr(record, 'source_urls', ()))


__all__ = (
    'ShapeKeyClassification',
    'ShapeKeyContext',
    'ShapeKeySpec',
    'ShapeKeyStandardInfo',
    'build_shape_key_context',
    'classify_shape_key',
    'find_equivalent_names',
    'find_equivalent_specs',
    'find_shape_keys',
    'get_sources',
    'get_standard',
    'get_standard_items',
    'get_standard_specs',
    'get_template_names',
    'list_standards',
    'normalize_shape_key_exact',
    'normalize_shape_key_name',
    'normalized_shape_key_names',
)
