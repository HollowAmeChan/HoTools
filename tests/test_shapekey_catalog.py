import sys
from pathlib import Path


ADDON_DIR = Path(__file__).resolve().parents[1]
SHAPEKEY_TOOLS_DIR = ADDON_DIR / "ShapekeyTools"
if str(SHAPEKEY_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(SHAPEKEY_TOOLS_DIR))

import rebase_presets as legacy_catalog
import shapekey_catalog as catalog


# 旧入口必须只是同一份目录的转发层，不能再维护第二份数据。
assert legacy_catalog.SHAPEKEY_STANDARD_SPECS is catalog.SHAPEKEY_STANDARD_SPECS
assert legacy_catalog.SHAPEKEY_STANDARDS is catalog.SHAPEKEY_STANDARDS
assert legacy_catalog.SHAPEKEY_TEMPLATE_MAP is catalog.SHAPEKEY_TEMPLATE_MAP
assert legacy_catalog.SHAPEKEY_CATALOG is catalog.SHAPEKEY_CATALOG
assert not any(name.startswith('_') for name in catalog.__all__)

assert tuple(catalog.SHAPEKEY_STANDARDS) == tuple(
    spec.identifier for spec in catalog.SHAPEKEY_STANDARD_SPECS)
assert tuple(catalog.SHAPEKEY_TEMPLATE_MAP) == tuple(
    catalog.SHAPEKEY_STANDARDS)
assert tuple(item[0] for item in catalog.SHAPEKEY_TEMPLATE_ITEMS) == tuple(
    catalog.SHAPEKEY_STANDARDS)

# 模板保留原始拼写；不能从 casefold 后的目录反向生成。
assert len(catalog.SHAPEKEY_TEMPLATE_MAP['PICO']) == 72
for lower, upper in (('o', 'O'), ('u', 'U'), ('e', 'E'), ('i', 'I')):
    pico_names = catalog.SHAPEKEY_TEMPLATE_MAP['PICO']
    assert lower in pico_names and upper in pico_names

for standard_id, spec in catalog.SHAPEKEY_STANDARDS.items():
    assert catalog.SHAPEKEY_TEMPLATE_MAP[standard_id] is spec.template_names
    for shape_name in spec.template_names:
        entry = catalog.get_shape_key_catalog_entry(shape_name)
        assert entry is not None, (standard_id, shape_name)
        assert standard_id in entry.standard_ids, (standard_id, shape_name)
        assert shape_name in entry.template_names, (standard_id, shape_name)
    for shape_name in spec.recognized_aliases:
        entry = catalog.get_shape_key_catalog_entry(shape_name)
        assert entry is not None, (standard_id, shape_name)
        assert standard_id in entry.standard_ids, (standard_id, shape_name)
        assert shape_name in entry.aliases, (standard_id, shape_name)

# 模板归属和分类归属是两套 ID，并允许一个规范名属于多个标准。
look_up_left = catalog.get_shape_key_catalog_entry('eyeLookUpLeft')
assert look_up_left.standard_ids == frozenset({
    'ARKIT', 'UNIFIED_EXPRESSIONS_BASE',
})
assert look_up_left.standards == frozenset({'ARKIT', 'UNIFIED_BASE'})
assert (look_up_left.region, look_up_left.side, look_up_left.semantic) == (
    'EYE', 'LEFT', 'EYE_GAZE')
assert look_up_left.source_urls

aa = catalog.get_shape_key_catalog_entry('Aa')
assert {'VRM1', 'META_VISEME', 'PICO'}.issubset(aa.standard_ids)
assert {'VRM1', 'META_VISEME', 'PICO'}.issubset(aa.standards)
assert (aa.region, aa.side, aa.semantic) == ('MOUTH', 'NONE', 'VISEME')

# 别名可识别但不会污染一键添加模板。
assert not catalog.get_shape_key_catalog_entry('vrc.blink (3.0)').is_template
assert not catalog.get_shape_key_catalog_entry('ジト目').is_template
assert not catalog.get_shape_key_catalog_entry('口横狭め').is_template

# 目录查询统一处理 Unicode、前导标记与连续 Blender 数字后缀。
assert catalog.normalize_shape_key_name(
    '＋＠ＥｙｅＢｌｉｎｋＬｅｆｔ．００１.1000') == 'eyeblinkleft'
assert catalog.get_shape_key_catalog_entry(
    '＋＠ＥｙｅＢｌｉｎｋＬｅｆｔ．００１.1000'
) is catalog.get_shape_key_catalog_entry('eyeBlinkLeft')
assert catalog.get_shape_key_catalog_entry(
    'ｷﾘｯ.001') is catalog.get_shape_key_catalog_entry('キリッ')
assert catalog.normalize_shape_key_name('Blink.01') == 'blink.01'
assert catalog.get_shape_key_catalog_entry('Blink.01') is None

assert len(catalog.SHAPEKEY_CATALOG) == 496
assert {
    spec.classifier_id
    for spec in catalog.SHAPEKEY_STANDARD_SPECS
    if spec.reliable_side
} == {
    'ARKIT', 'META', 'PICO', 'UNIFIED_BASE', 'VRM', 'VRM1',
    'VIVE_SRANIPAL', 'VIVE_OPENXR',
}

print('shape key catalog tests passed')
