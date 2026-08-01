import csv
import sys
import tempfile
from pathlib import Path


ADDON_DIR = Path(__file__).resolve().parents[1]
SHAPEKEY_TOOLS_DIR = ADDON_DIR / "ShapekeyTools"
if str(SHAPEKEY_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(SHAPEKEY_TOOLS_DIR))

import shapekey_catalog as catalog


assert not any(name.startswith('_') for name in catalog.__all__)
assert 'SHAPE_KEY_SPECS' not in catalog.__all__
assert 'STANDARD_INFOS' not in catalog.__all__

standards = catalog.list_standards()
standard_ids = tuple(info.identifier for info in standards)
assert len(standards) == 13
assert tuple(item[0] for item in catalog.get_standard_items()) == standard_ids
assert catalog.get_standard('QUEST_PRO').family == 'META'
assert catalog.get_standard('MISSING') is None
assert {
    info.identifier for info in catalog.list_standards('FACE_TRACKING')
} >= {'ARKIT', 'QUEST_PRO', 'PICO', 'VIVE_OPENXR'}

record_count = sum(
    len(catalog.get_standard_specs(standard_id))
    for standard_id in standard_ids
)
assert record_count == 585

# 扁平事实直接保存在 Excel 友好的 UTF-8 BOM CSV 中。
catalog_path = SHAPEKEY_TOOLS_DIR / 'shapekey_catalog.csv'
assert catalog.get_catalog_path() == catalog_path
assert catalog_path.read_bytes().startswith(b'\xef\xbb\xbf')
with catalog_path.open('r', encoding='utf-8-sig', newline='') as stream:
    csv_reader = csv.DictReader(stream, strict=True)
    catalog_fields = tuple(csv_reader.fieldnames)
    assert catalog_fields == (
        'standard', 'name', 'role', 'region', 'side', 'semantic',
        'canonical', 'context', 'tags', 'note',
    )
    csv_rows = list(csv_reader)
assert len(csv_rows) == record_count
for csv_row in csv_rows:
    assert None not in csv_row
    assert all(
        csv_row[field]
        for field in ('standard', 'name', 'role', 'region', 'side', 'semantic')
    )

assert not (SHAPEKEY_TOOLS_DIR / 'shapekey_catalog_data.py').exists()
assert not (SHAPEKEY_TOOLS_DIR / 'rebase_presets.py').exists()

# 模板保留原始顺序和大小写；别名是独立记录，不进入模板。
pico_names = catalog.get_template_names('PICO')
assert len(pico_names) == 72
for lower, upper in (('o', 'O'), ('u', 'U'), ('e', 'E'), ('i', 'I')):
    assert lower in pico_names and upper in pico_names

pico_case_facts = {
    name: catalog.find_shape_keys(name, 'PICO')[0]
    for name in ('o', 'O', 'I', 'u', 'i', 'U', 'e', 'E')
}
assert {
    name: spec.canonical
    for name, spec in pico_case_facts.items()
} == {
    'o': 'pico.viseme.o',
    'O': 'pico.viseme.ou',
    'I': 'pico.viseme.i_back',
    'u': 'pico.viseme.u',
    'i': 'pico.viseme.i_front',
    'U': 'pico.viseme.uw',
    'e': 'pico.viseme.e',
    'E': 'pico.viseme.ei',
}
assert all(spec.note.startswith('PICO 枚举：')
           for spec in pico_case_facts.values())

assert catalog.find_shape_keys(
    'vrc.blink (3.0)', 'VRCHAT')[0].role == 'ALIAS'
assert catalog.find_shape_keys('ジト目', 'MMD')[0].role == 'ALIAS'
assert catalog.find_shape_keys('口横狭め', 'MMD')[0].role == 'ALIAS'
assert 'vrc.blink (3.0)' not in catalog.get_template_names('VRCHAT')
assert 'ジト目' not in catalog.get_template_names('MMD')

# 精确大小写优先；只有没有精确结果时才使用兼容索引。
assert {
    spec.standard for spec in catalog.find_shape_keys('eyeLookUpLeft')
} == {'ARKIT'}
assert {
    spec.standard for spec in catalog.find_shape_keys('EyeLookUpLeft')
} == {'UNIFIED_EXPRESSIONS_BASE'}
assert catalog.find_shape_keys(
    'eyeLookUpLeft', 'UNIFIED_EXPRESSIONS_BASE')[0].name == 'EyeLookUpLeft'
assert catalog.find_shape_keys(
    'EyeLookUpLeft', 'ARKIT')[0].name == 'eyeLookUpLeft'
assert catalog.find_shape_keys(
    'eyeLookUpLeft', 'UNIFIED_EXPRESSIONS_BASE',
    casefold_fallback=False,
) == ()
assert {
    spec.standard for spec in catalog.find_shape_keys('Aa')
} == {'VRM1'}
assert {
    spec.standard for spec in catalog.find_shape_keys('aA')
} >= {'VRM1', 'META_VISEME', 'PICO'}

# 每条记录直接携带最终事实，不依赖查询阶段再猜名称语义。
blink_left = catalog.find_shape_keys('eyeBlinkLeft', 'ARKIT')[0]
assert (
    blink_left.region,
    blink_left.side,
    blink_left.semantic,
    blink_left.canonical,
) == ('EYE', 'LEFT', 'EYELID', 'eye.closed.left')
assert blink_left.side_reliable
assert 'FACE_TRACKING' in blink_left.tags
assert blink_left.source_urls

classification = catalog.classify_shape_key('eyeBlinkLeft')
assert (
    classification.region,
    classification.side,
    classification.semantic,
) == ('EYE', 'LEFT', 'EYELID')
assert classification.known and not classification.ambiguous
assert classification.families == frozenset({'ARKIT'})

# VRM、PICO 和 Meta 短音素只在对应整套模型上下文中生效。
assert catalog.classify_shape_key('A').semantic == 'OTHER'
vrm_context = ('A', 'I', 'U', 'E', 'O', 'Blink', 'LookLeft')
assert catalog.classify_shape_key('A', vrm_context).semantic == 'VISEME'

pico_specs = catalog.get_standard_specs('PICO', templates_only=True)
pico_context = tuple(spec.name for spec in pico_specs)
assert catalog.classify_shape_key('XX').semantic == 'OTHER'
assert catalog.classify_shape_key('XX', pico_context).semantic == 'VISEME'

meta_context = (
    catalog.get_template_names('QUEST_PRO')
    + catalog.get_template_names('META_VISEME')
)
assert catalog.classify_shape_key('AA').semantic == 'OTHER'
assert catalog.classify_shape_key('AA', meta_context).semantic == 'VISEME'

# 不同标准把大小写用于不同键名，不能通过 casefold 合并成同一事实。
for name in ('Aa', 'Ih', 'Ou', 'Oh'):
    assert catalog.classify_shape_key(name).semantic == 'VISEME'
for name in ('AA', 'aa', 'IH', 'OU', 'OH'):
    assert catalog.classify_shape_key(name).semantic == 'OTHER'
for name in ('AA', 'IH', 'OU', 'OH'):
    assert catalog.classify_shape_key(name, meta_context).semantic == 'VISEME'
assert catalog.classify_shape_key('aa', pico_context).semantic == 'VISEME'

# canonical 只负责明确的跨标准等价查询。
closed_left = catalog.find_equivalent_specs(
    'eye.closed.left', templates_only=True)
assert {
    'ARKIT', 'VRM', 'VRM1', 'QUEST_PRO', 'PICO',
    'VIVE_SRANIPAL', 'VIVE_OPENXR', 'UNIFIED_EXPRESSIONS_BASE',
}.issubset({spec.standard for spec in closed_left})
assert 'eyeBlinkLeft' in catalog.find_equivalent_names(
    'eye.closed.left', 'ARKIT')
assert 'EyeClosedLeft' in catalog.find_equivalent_names(
    'eye.closed.left', 'UNIFIED_EXPRESSIONS_BASE')

# 查询统一处理 Unicode、前导标记与连续 Blender 数字后缀。
assert catalog.normalize_shape_key_name(
    '＋＠ＥｙｅＢｌｉｎｋＬｅｆｔ．００１.1000') == 'eyeblinkleft'
assert catalog.normalize_shape_key_exact(
    '＋＠ＥｙｅＢｌｉｎｋＬｅｆｔ．００１.1000') == 'EyeBlinkLeft'
assert catalog.find_shape_keys(
    'ｷﾘｯ.001', 'MMD') == catalog.find_shape_keys('キリッ', 'MMD')
assert catalog.normalize_shape_key_name('Blink.01') == 'blink.01'
assert catalog.find_shape_keys('Blink.01') == ()

# CSV 可以显式重载；非法表不会破坏上一份有效索引。
probe_row = {
    'standard': 'ARKIT',
    'name': 'CsvReloadProbe',
    'role': 'ALIAS',
    'region': 'EYE',
    'side': 'BOTH',
    'semantic': 'EYELID',
    'canonical': 'eye.csv_probe',
    'context': '',
    'tags': 'CSV_TEST|SECOND_TAG',
    'note': '逗号, "引号"\n换行',
}
with tempfile.TemporaryDirectory(prefix='hotools_catalog_') as temp_dir:
    temp_path = Path(temp_dir)
    valid_path = temp_path / 'valid.csv'
    invalid_path = temp_path / 'invalid.csv'
    with valid_path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=catalog_fields)
        writer.writeheader()
        writer.writerow(probe_row)
    with invalid_path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=catalog_fields)
        writer.writeheader()
        writer.writerow({**probe_row, 'note': ''})
        writer.writerow({**probe_row, 'note': ''})

    try:
        assert catalog.reload_catalog(valid_path) == 1
        probe = catalog.find_shape_keys('CsvReloadProbe', 'ARKIT')[0]
        assert probe.note == probe_row['note']
        assert {'CSV_TEST', 'SECOND_TAG'}.issubset(probe.tags)

        try:
            catalog.reload_catalog(invalid_path)
        except catalog.ShapeKeyCatalogError as exc:
            message = str(exc)
            assert '第 3 行' in message and '重复名称' in message
        else:
            raise AssertionError('重复 CSV 记录没有触发校验错误')
        assert catalog.find_shape_keys(
            'CsvReloadProbe', 'ARKIT')[0] == probe
    finally:
        assert catalog.reload_catalog() == 585

print('shape key catalog tests passed')
