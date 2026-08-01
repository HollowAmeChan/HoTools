"""形态键标准 CSV 的校验、索引与查询入口。"""

import csv
from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata


class ShapeKeyCatalogError(RuntimeError):
    """形态键 CSV 无法完整读取时抛出的错误。"""


@dataclass(frozen=True)
class ShapeKeyStandardInfo:
    """一个标准的 UI 信息和共享属性。"""

    identifier: str
    family: str
    label: str
    description: str
    categories: frozenset = frozenset()
    source_urls: tuple = ()
    side_reliable: bool = False


@dataclass(frozen=True)
class ShapeKeySpec:
    """CSV 中的一条原始形态键事实。"""

    standard: str
    family: str
    name: str
    role: str
    region: str
    side: str
    semantic: str
    canonical: str | None
    context: str | None
    side_reliable: bool
    tags: frozenset
    source_urls: tuple
    note: str

    @property
    def is_template(self):
        return self.role == 'TEMPLATE'


_STANDARD_INFOS = (
    ShapeKeyStandardInfo(
        identifier='ARKIT',
        family='ARKIT',
        label='ARKit',
        description='ARKit 形态键列表',
        categories=frozenset(['FACE_TRACKING']),
        source_urls=('https://arkit-face-blendshapes.com/',),
        side_reliable=True,
    ),
    ShapeKeyStandardInfo(
        identifier='VRCHAT',
        family='VRCHAT',
        label='VRChat',
        description='VRChat 形态键列表',
        categories=frozenset(['AVATAR', 'LIP_SYNC']),
    ),
    ShapeKeyStandardInfo(
        identifier='MMD',
        family='MMD',
        label='MMD',
        description='MMD 形态键列表',
        categories=frozenset(['AVATAR', 'MMD']),
    ),
    ShapeKeyStandardInfo(
        identifier='VRM',
        family='VRM',
        label='VRM 0.x',
        description='VRM 0.x 形态键列表',
        categories=frozenset(['AVATAR', 'VRM']),
        side_reliable=True,
    ),
    ShapeKeyStandardInfo(
        identifier='VRM1',
        family='VRM1',
        label='VRM 1.0',
        description='VRM 1.0 表情预设列表',
        categories=frozenset(['AVATAR', 'VRM']),
        source_urls=('https://vrm.dev/vrm1/expression/',),
        side_reliable=True,
    ),
    ShapeKeyStandardInfo(
        identifier='QUEST_PRO',
        family='META',
        label='Meta Movement',
        description='Meta Movement 形态键列表',
        categories=frozenset(['FACE_TRACKING']),
        source_urls=(
            'https://developers.meta.com/horizon/documentation/unity/'
            'move-face-tracking/',
        ),
        side_reliable=True,
    ),
    ShapeKeyStandardInfo(
        identifier='META_VISEME',
        family='META_VISEME',
        label='Meta Viseme',
        description='Meta Movement 15 音素列表',
        categories=frozenset(['LIP_SYNC']),
        source_urls=(
            'https://developers.meta.com/horizon/documentation/unity/'
            'move-face-tracking/',
        ),
    ),
    ShapeKeyStandardInfo(
        identifier='PICO',
        family='PICO',
        label='PICO',
        description='PICO 52 形态键和 20 音素列表',
        categories=frozenset(['FACE_TRACKING', 'LIP_SYNC']),
        source_urls=(
            'https://developer-cn.picoxr.com/document/unity/face-tracking/',
        ),
        side_reliable=True,
    ),
    ShapeKeyStandardInfo(
        identifier='OCULUS_VISEME',
        family='OCULUS_VISEME',
        label='Oculus Viseme',
        description='Oculus/Meta 15 音素列表',
        categories=frozenset(['LIP_SYNC']),
        source_urls=(
            'https://developers.meta.com/horizon/documentation/unity/'
            'audio-ovrlipsync-viseme-reference/',
        ),
    ),
    ShapeKeyStandardInfo(
        identifier='VIVE_SRANIPAL',
        family='VIVE_SRANIPAL',
        label='VIVE SRanipal',
        description='VIVE SRanipal 眼部和唇部列表',
        categories=frozenset(['FACE_TRACKING']),
        source_urls=(
            'https://docs.vrcft.io/docs/tutorial-avatars/'
            'tutorial-avatars-extras/compatibility/vive-sranipal',
        ),
        side_reliable=True,
    ),
    ShapeKeyStandardInfo(
        identifier='VIVE_OPENXR',
        family='VIVE_OPENXR',
        label='VIVE OpenXR',
        description='XR_HTC_facial_tracking 表情列表',
        categories=frozenset(['FACE_TRACKING']),
        source_urls=(
            'https://hub.vive.com/apidoc/api/'
            'VIVE.OpenXR.FacialTracking.html',
        ),
        side_reliable=True,
    ),
    ShapeKeyStandardInfo(
        identifier='UNIFIED_EXPRESSIONS_BASE',
        family='UNIFIED_BASE',
        label='Unified-base',
        description='Unified 基础形态键列表',
        categories=frozenset(['FACE_TRACKING']),
        source_urls=(
            'https://docs.vrcft.io/docs/tutorial-avatars/'
            'tutorial-avatars-extras/unified-blendshapes',
        ),
        side_reliable=True,
    ),
    ShapeKeyStandardInfo(
        identifier='UNIFIED_EXPRESSIONS_BLEND',
        family='UNIFIED_BLEND',
        label='Unified-blend',
        description='Unified 混合形态键列表',
        categories=frozenset(['FACE_TRACKING']),
        source_urls=(
            'https://docs.vrcft.io/docs/tutorial-avatars/'
            'tutorial-avatars-extras/unified-blendshapes',
        ),
    ),
)

_STANDARD_BY_ID = {
    info.identifier: info
    for info in _STANDARD_INFOS
}
_CATALOG_COLUMNS = (
    'standard',
    'name',
    'role',
    'region',
    'side',
    'semantic',
    'canonical',
    'context',
    'tags',
    'note',
)
_VALID_ROLES = frozenset({'TEMPLATE', 'ALIAS'})
_VALID_REGIONS = frozenset({'OTHER', 'EYE', 'MOUTH'})
_VALID_SIDES = frozenset({'NONE', 'BOTH', 'LEFT', 'RIGHT'})
_SEMANTIC_REGIONS = {
    'OTHER': 'OTHER',
    'MOUTH': 'MOUTH',
    'VISEME': 'MOUTH',
    'EYELID': 'EYE',
    'EYE_GAZE': 'EYE',
    'EYE_ORBIT': 'EYE',
}
_VALID_CONTEXTS = frozenset({
    'VRM0_VISEME',
    'PICO_VISEME',
    'META_VISEME',
})


def get_catalog_path():
    """返回用户可直接编辑的内置 CSV 路径。"""
    return Path(__file__).with_name('shapekey_catalog.csv')


def _catalog_row_error(path, line_number, field, value, message):
    raise ShapeKeyCatalogError(
        f"{path} 第 {line_number} 行，字段 {field}={value!r}：{message}"
    )


def _validate_enum(path, line_number, field, value, allowed):
    if value not in allowed:
        choices = ', '.join(sorted(allowed))
        _catalog_row_error(
            path,
            line_number,
            field,
            value,
            f"只能填写 {choices}",
        )


def _load_shape_key_specs(csv_path=None):
    """完整读取并校验 CSV；不根据名称推断任何事实。"""
    path = Path(csv_path) if csv_path is not None else get_catalog_path()
    try:
        stream = path.open('r', encoding='utf-8-sig', newline='')
    except OSError as exc:
        raise ShapeKeyCatalogError(f"无法读取形态键目录 {path}：{exc}") from exc

    specs = []
    seen = set()
    try:
        with stream:
            reader = csv.DictReader(stream, strict=True)
            header = tuple(reader.fieldnames or ())
            if header != _CATALOG_COLUMNS:
                expected = ','.join(_CATALOG_COLUMNS)
                actual = ','.join(header)
                raise ShapeKeyCatalogError(
                    f"{path} 表头不正确；应为 {expected}，实际为 {actual}"
                )

            for row in reader:
                line_number = reader.line_num
                if None in row or any(value is None for value in row.values()):
                    raise ShapeKeyCatalogError(
                        f"{path} 第 {line_number} 行的列数与表头不一致"
                    )
                if all(value == '' for value in row.values()):
                    continue

                standard = row['standard'].strip().upper()
                name = row['name']
                role = row['role'].strip().upper()
                region = row['region'].strip().upper()
                side = row['side'].strip().upper()
                semantic = row['semantic'].strip().upper()
                canonical = row['canonical'].strip() or None
                context = row['context'].strip().upper() or None
                note = row['note'].strip()
                tags = frozenset(
                    tag.strip().upper()
                    for tag in row['tags'].split('|')
                    if tag.strip()
                )

                if not standard:
                    _catalog_row_error(
                        path, line_number, 'standard', standard, '不能为空')
                info = _STANDARD_BY_ID.get(standard)
                if info is None:
                    _catalog_row_error(
                        path, line_number, 'standard', standard, '未知标准')
                if not name:
                    _catalog_row_error(
                        path, line_number, 'name', name, '不能为空')
                _validate_enum(
                    path, line_number, 'role', role, _VALID_ROLES)
                _validate_enum(
                    path, line_number, 'region', region, _VALID_REGIONS)
                _validate_enum(
                    path, line_number, 'side', side, _VALID_SIDES)
                _validate_enum(
                    path,
                    line_number,
                    'semantic',
                    semantic,
                    _SEMANTIC_REGIONS,
                )
                if context is not None:
                    _validate_enum(
                        path,
                        line_number,
                        'context',
                        context,
                        _VALID_CONTEXTS,
                    )

                expected_region = _SEMANTIC_REGIONS[semantic]
                if region != expected_region:
                    _catalog_row_error(
                        path,
                        line_number,
                        'region',
                        region,
                        f"语义 {semantic} 必须属于 {expected_region}",
                    )
                if region == 'EYE' and side == 'NONE':
                    _catalog_row_error(
                        path,
                        line_number,
                        'side',
                        side,
                        '眼睛记录必须填写 BOTH、LEFT 或 RIGHT',
                    )
                if region != 'EYE' and side != 'NONE':
                    _catalog_row_error(
                        path,
                        line_number,
                        'side',
                        side,
                        '非眼睛记录必须填写 NONE',
                    )

                identity = (standard, name)
                if identity in seen:
                    _catalog_row_error(
                        path,
                        line_number,
                        'name',
                        name,
                        f"标准 {standard} 中存在重复名称",
                    )
                seen.add(identity)
                specs.append(ShapeKeySpec(
                    standard=standard,
                    family=info.family,
                    name=name,
                    role=role,
                    region=region,
                    side=side,
                    semantic=semantic,
                    canonical=canonical,
                    context=context,
                    side_reliable=info.side_reliable,
                    tags=info.categories | tags,
                    source_urls=info.source_urls,
                    note=note,
                ))
    except (csv.Error, UnicodeDecodeError) as exc:
        raise ShapeKeyCatalogError(
            f"无法解析形态键目录 {path}：{exc}"
        ) from exc
    return tuple(specs)


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


def _freeze_index(index):
    return {
        key: tuple(values)
        for key, values in index.items()
    }


def _build_catalog_indexes(specs):
    by_exact_name = {}
    by_folded_name = {}
    by_standard = {}
    by_canonical = {}
    context_names = {}
    tag_names = {}
    for spec in specs:
        exact_name = normalize_shape_key_exact(spec.name)
        _append_index(by_exact_name, exact_name, spec)
        _append_index(by_folded_name, exact_name.casefold(), spec)
        _append_index(by_standard, spec.standard, spec)
        if spec.canonical is not None:
            _append_index(by_canonical, spec.canonical, spec)

        folded_name = normalize_shape_key_name(spec.name)
        if spec.context is not None:
            context_names.setdefault(spec.context, set()).add(folded_name)
        for tag in spec.tags:
            tag_names.setdefault(tag, set()).add(folded_name)

    return (
        _freeze_index(by_exact_name),
        _freeze_index(by_folded_name),
        _freeze_index(by_standard),
        _freeze_index(by_canonical),
        {
            key: frozenset(names)
            for key, names in context_names.items()
        },
        {
            key: frozenset(names)
            for key, names in tag_names.items()
        },
    )


_SHAPE_KEY_SPECS = ()
_BY_EXACT_NAME = {}
_BY_FOLDED_NAME = {}
_BY_STANDARD = {}
_BY_CANONICAL = {}
_CONTEXT_NAMES = {}
_TAG_NAMES = {}


def reload_catalog(csv_path=None):
    """原子重载 CSV；失败时保留当前可用目录。"""
    specs = _load_shape_key_specs(csv_path)
    indexes = _build_catalog_indexes(specs)

    global _SHAPE_KEY_SPECS
    global _BY_EXACT_NAME, _BY_FOLDED_NAME
    global _BY_STANDARD, _BY_CANONICAL
    global _CONTEXT_NAMES, _TAG_NAMES
    _SHAPE_KEY_SPECS = specs
    (
        _BY_EXACT_NAME,
        _BY_FOLDED_NAME,
        _BY_STANDARD,
        _BY_CANONICAL,
        _CONTEXT_NAMES,
        _TAG_NAMES,
    ) = indexes
    return len(specs)


reload_catalog()


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
    'ShapeKeyCatalogError',
    'ShapeKeyClassification',
    'ShapeKeyContext',
    'ShapeKeySpec',
    'ShapeKeyStandardInfo',
    'build_shape_key_context',
    'classify_shape_key',
    'find_equivalent_names',
    'find_equivalent_specs',
    'find_shape_keys',
    'get_catalog_path',
    'get_sources',
    'get_standard',
    'get_standard_items',
    'get_standard_specs',
    'get_template_names',
    'list_standards',
    'normalize_shape_key_exact',
    'normalize_shape_key_name',
    'normalized_shape_key_names',
    'reload_catalog',
)
