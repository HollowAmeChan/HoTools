import importlib
import sys
import types
from pathlib import Path

import bpy
import numpy as np


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))
package = types.ModuleType("HoTools")
package.__path__ = [str(ADDON_DIR)]
sys.modules.setdefault("HoTools", package)
shapekey_package = types.ModuleType("HoTools.ShapekeyTools")
shapekey_package.__path__ = [str(ADDON_DIR / "ShapekeyTools")]
sys.modules.setdefault("HoTools.ShapekeyTools", shapekey_package)

module = importlib.import_module("HoTools.ShapekeyTools.operators")


def activate(obj):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def make_mesh(name, vertex_count=5):
    data = bpy.data.meshes.new(f"{name}Data")
    data.from_pydata([(float(index), 0.0, 0.0) for index in range(vertex_count)], [], [])
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    activate(obj)
    return obj


def positions(key):
    return np.array([point.co[:] for point in key.data], dtype=np.float32)


def assert_position(key, index, expected):
    actual = np.array(key.data[index].co[:], dtype=np.float32)
    assert np.allclose(actual, expected, atol=1e-6), (key.name, index, actual, expected)


# 本地 FBSF 近似权重按左右半脸分别比较目标表情与捏脸 delta。
# 同向位移得到 1，正交位移得到 0；左右过渡只在分数确实不同时启用。
fbsf_basis = np.array(
    [(-1.0, 0.0, 0.0), (-0.05, 0.0, 0.0),
     (0.05, 0.0, 0.0), (1.0, 0.0, 0.0)],
    dtype=np.float32,
)
fbsf_edit = np.array([(0.0, 1.0, 0.0)] * 4, dtype=np.float32)
fbsf_target = np.array(
    [(0.0, 0.0, 1.0), (0.0, 0.0, 1.0),
     (0.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
    dtype=np.float32,
)
left_mask, right_mask = module._fbsf_side_masks(fbsf_basis)
left_score = module._fbsf_side_similarity(
    fbsf_target, fbsf_edit, left_mask)
right_score = module._fbsf_side_similarity(
    fbsf_target, fbsf_edit, right_mask)
hard_weights = module._fbsf_split_side_weights(
    left_score, right_score, fbsf_basis, 0.0)
assert left_score == 1.0
assert right_score == 0.0
assert np.allclose(hard_weights, (0.0, 0.0, 1.0, 1.0), atol=1e-6)

smooth_weights = module._fbsf_split_side_weights(
    left_score, right_score, fbsf_basis, 0.1)
assert np.allclose(smooth_weights, (0.0, 0.25, 0.75, 1.0), atol=1e-6)

# 本地早期实现把反向内积按一半强度计入相似度，这个行为必须保持兼容。
left_score = module._fbsf_side_similarity(
    -fbsf_edit, fbsf_edit, left_mask)
right_score = module._fbsf_side_similarity(
    -fbsf_edit, fbsf_edit, right_mask)
assert left_score == 0.5
assert right_score == 0.5
assert module._fbsf_threshold_map(0.05) == 0.0
assert module._fbsf_threshold_map(0.95) == 1.0
assert module._fbsf_auto_function_tag("@vrc.blink.001") == 'BOTH_EYES'
assert module._fbsf_auto_function_tag("eyeBlinkLeft") == 'LEFT_EYE'
assert module._fbsf_auto_function_tag("eyeBlinkRight.001") == 'RIGHT_EYE'
assert module._fbsf_auto_function_tag("眼眶Left") == 'OTHERS'
assert module._fbsf_auto_function_tag("眼眶Right") == 'OTHERS'
assert module._fbsf_auto_function_tag("左眼眶") == 'OTHERS'
assert module._fbsf_auto_function_tag("右眼眶.001") == 'OTHERS'
assert module._fbsf_auto_function_tag("vrc.v_aa") == 'MOUTH'
assert module._fbsf_auto_function_tag("MouthOpen") == 'MOUTH'
assert module._fbsf_auto_function_tag("CheekPuff") == 'OTHERS'

# 标准精确词表必须覆盖完整列表；Left/Right 只按各标准的语法解释。
for shape_name in module.ARKIT_SHAPEKEYS:
    if shape_name.startswith(('jaw', 'mouth', 'tongue')):
        expected = 'MOUTH'
    elif shape_name.startswith('eye') or shape_name.startswith('cheekSquint'):
        expected = 'LEFT_EYE' if shape_name.endswith('Left') else 'RIGHT_EYE'
    else:
        expected = 'OTHERS'
    assert module._fbsf_auto_function_tag(shape_name) == expected, shape_name

for shape_name in module.UNIFIED_EXPRESSIONS_BASE_SHAPEKEYS:
    if (
            shape_name.startswith(('Jaw', 'Lip', 'Mouth', 'Tongue'))
            or shape_name == 'SoftPalateClose'):
        expected = 'MOUTH'
    elif shape_name.startswith(('EyeLook', 'EyeClosed', 'EyeSquint', 'EyeWide')):
        expected = 'LEFT_EYE' if shape_name.endswith('Left') else 'RIGHT_EYE'
    elif shape_name.startswith('CheekSquint'):
        expected = 'LEFT_EYE' if shape_name.endswith('Left') else 'RIGHT_EYE'
    else:
        expected = 'OTHERS'
    assert module._fbsf_auto_function_tag(shape_name) == expected, shape_name
assert len(module.UNIFIED_EXPRESSIONS_BASE_SHAPEKEYS) == 102
assert module.UNIFIED_EXPRESSIONS_BASE_SHAPEKEYS[-4:] == [
    'SoftPalateClose', 'ThroatSwallow', 'NeckFlexRight', 'NeckFlexLeft',
]

for shape_name in module.UNIFIED_EXPRESSIONS_BLEND_SHAPEKEYS:
    if shape_name.startswith(('Lip', 'Mouth')):
        expected = 'MOUTH'
    elif shape_name in {'EyeClosed', 'EyeWide', 'EyeSquint', 'CheekSquint'}:
        expected = 'BOTH_EYES'
    else:
        expected = 'OTHERS'
    assert module._fbsf_auto_function_tag(shape_name) == expected, shape_name

meta_mouth_prefixes = (
    'CHIN_', 'DIMPLER_', 'JAW_', 'LIP_', 'LIPS_', 'LOWER_LIP_',
    'MOUTH_', 'TONGUE_', 'UPPER_LIP_',
)
for shape_name in module.QUEST_PRO_SHAPEKEYS:
    if shape_name.startswith(meta_mouth_prefixes):
        expected = 'MOUTH'
    elif shape_name.startswith((
            'EYES_CLOSED_', 'LID_TIGHTENER_', 'UPPER_LID_RAISER_')):
        expected = 'LEFT_EYE' if shape_name.endswith('_L') else 'RIGHT_EYE'
    elif shape_name.startswith('EYES_LOOK_'):
        expected = 'LEFT_EYE' if shape_name.endswith('_L') else 'RIGHT_EYE'
    elif shape_name.startswith('CHEEK_RAISER_'):
        expected = 'LEFT_EYE' if shape_name.endswith('_L') else 'RIGHT_EYE'
    else:
        expected = 'OTHERS'
    assert module._fbsf_auto_function_tag(shape_name) == expected, shape_name
assert len(module.QUEST_PRO_SHAPEKEYS) == 70
assert len(module.QUEST_PRO_SHAPEKEYS) == len(set(module.QUEST_PRO_SHAPEKEYS))
assert 'EYES_LOOK_LEFT_L' in module.QUEST_PRO_SHAPEKEYS
assert 'EYES_LOOK_RIGHT_R' in module.QUEST_PRO_SHAPEKEYS
assert 'LOWER_LIP_DEPRESSOR_L' in module.QUEST_PRO_SHAPEKEYS
assert 'LOWER_LIP_DEPRESSER_L' not in module.QUEST_PRO_SHAPEKEYS
for shape_name in (
        'EYES_LOOK_IN_L', 'EYES_LOOK_OUT_R',
        'EYES_SQUINT_L', 'EYES_WIDEN_R'):
    assert module._fbsf_auto_function_tag(shape_name) == 'OTHERS', shape_name

vrm1_expected = {
    'Aa': 'MOUTH', 'Ih': 'MOUTH', 'Ou': 'MOUTH',
    'Ee': 'MOUTH', 'Oh': 'MOUTH',
    'Blink': 'BOTH_EYES', 'BlinkLeft': 'LEFT_EYE',
    'BlinkRight': 'RIGHT_EYE',
    'LookUp': 'BOTH_EYES', 'LookDown': 'BOTH_EYES',
    'LookLeft': 'BOTH_EYES', 'LookRight': 'BOTH_EYES',
}
for shape_name in module.VRM1_SHAPEKEYS:
    assert module._fbsf_auto_function_tag(shape_name) == (
        vrm1_expected.get(shape_name, 'OTHERS'))

for shape_name in module.OCULUS_VISEME_SHAPEKEYS:
    assert module._fbsf_auto_function_tag(shape_name) == 'MOUTH', shape_name

for shape_name in module.VIVE_SRANIPAL_EYE_SHAPEKEYS:
    if shape_name == 'Eye_Frown':
        expected = 'BOTH_EYES'
    else:
        expected = 'LEFT_EYE' if '_Left_' in shape_name else 'RIGHT_EYE'
    assert module._fbsf_auto_function_tag(shape_name) == expected, shape_name
for shape_name in module.VIVE_SRANIPAL_LIP_SHAPEKEYS:
    expected = (
        'OTHERS' if shape_name.startswith('Cheek_') else 'MOUTH')
    assert module._fbsf_auto_function_tag(shape_name) == expected, shape_name

for shape_name in module.VIVE_OPENXR_EYE_SHAPEKEYS:
    expected = 'LEFT_EYE' if '_LEFT_' in shape_name else 'RIGHT_EYE'
    assert module._fbsf_auto_function_tag(shape_name) == expected, shape_name
for shape_name in module.VIVE_OPENXR_LIP_SHAPEKEYS:
    expected = 'OTHERS' if '_CHEEK_' in shape_name else 'MOUTH'
    assert module._fbsf_auto_function_tag(shape_name) == expected, shape_name

assert {
    'VRM1', 'META_VISEME', 'PICO', 'OCULUS_VISEME',
    'VIVE_SRANIPAL', 'VIVE_OPENXR',
}.issubset(module.SHAPEKEY_TEMPLATE_MAP)
assert tuple(module.SHAPEKEY_TEMPLATE_MAP) == tuple(
    spec.identifier for spec in module.SHAPEKEY_STANDARD_SPECS)
assert tuple(item[0] for item in module.SHAPEKEY_TEMPLATE_ITEMS) == tuple(
    module.SHAPEKEY_TEMPLATE_MAP)
for template_name, shape_names in module.SHAPEKEY_TEMPLATE_MAP.items():
    assert len(shape_names) == len(set(shape_names)), template_name
assert tuple(module.SHAPEKEY_STANDARDS) == tuple(
    module.SHAPEKEY_TEMPLATE_MAP)
assert set(module._FBSF_EXACT_PRESETS) == set(module.SHAPEKEY_CATALOG)
eye_side_tags = {
    'BOTH': 'BOTH_EYES',
    'LEFT': 'LEFT_EYE',
    'RIGHT': 'RIGHT_EYE',
}
for normalized, entry in module.SHAPEKEY_CATALOG.items():
    preset = module._FBSF_EXACT_PRESETS[normalized]
    if entry.region == 'MOUTH':
        expected_function = expected_reference = 'MOUTH'
    elif entry.region == 'EYE':
        expected_function = eye_side_tags[entry.side]
        expected_reference = (
            expected_function if entry.semantic == 'EYELID' else 'OTHERS')
    else:
        expected_function = expected_reference = 'OTHERS'
    assert preset.function_tag == expected_function, normalized
    assert preset.reference_tag == expected_reference, normalized
    assert preset.standards == entry.standards, normalized
    assert preset.semantic == entry.semantic, normalized
assert module._FBSF_STRONG_SIDE_STANDARDS == frozenset({
    'ARKIT', 'META', 'PICO', 'UNIFIED_BASE', 'VRM', 'VRM1',
    'VIVE_SRANIPAL', 'VIVE_OPENXR',
})
recognized_normalized_names = {
    module._fbsf_normalized_name(shape_name)
    for spec in module.SHAPEKEY_STANDARD_SPECS
    for shape_name in spec.recognized_names
}
assert set(module._FBSF_EXACT_PRESETS) <= recognized_normalized_names
assert 'vrc.blink (3.0)' not in module.SHAPEKEY_TEMPLATE_MAP['VRCHAT']
assert 'ジト目' not in module.SHAPEKEY_TEMPLATE_MAP['MMD']
assert module._fbsf_auto_function_tag('vrc.blink (3.0)') == 'BOTH_EYES'
assert module._fbsf_auto_function_tag('ジト目') == 'BOTH_EYES'
assert module._fbsf_auto_function_tag('口横狭め') == 'MOUTH'
assert {
    'ARKIT', 'UNIFIED_BASE',
}.issubset(module._fbsf_auto_preset('eyeLookUpLeft').standards)
assert {
    'VRM1', 'META_VISEME', 'PICO',
}.issubset(module._fbsf_auto_preset('Aa').standards)

for shape_name in module._FBSF_PICO_EYE_ANCHORS + module._FBSF_PICO_EYE_GAZE:
    expected = 'LEFT_EYE' if shape_name.endswith('_L') else 'RIGHT_EYE'
    assert module._fbsf_auto_function_tag(shape_name) == expected, shape_name
for shape_name in module._FBSF_PICO_MOUTH:
    assert module._fbsf_auto_function_tag(shape_name) == 'MOUTH', shape_name
for shape_name in module._FBSF_PICO_OTHER:
    if shape_name.startswith('CheekSquint_'):
        expected = 'LEFT_EYE' if shape_name.endswith('_L') else 'RIGHT_EYE'
    else:
        expected = 'OTHERS'
    assert module._fbsf_auto_function_tag(shape_name) == expected, shape_name
assert len(module._FBSF_PICO_SHAPEKEYS) == 52
assert len(module._FBSF_PICO_VISEMES) == 20
assert len(module.PICO_SHAPEKEYS) == 72
pico_context = module._FBSF_PICO_SHAPEKEYS + module._FBSF_PICO_VISEMES
for shape_name in module._FBSF_PICO_VISEMES:
    assert module._fbsf_auto_function_tag(
        shape_name, pico_context) == 'MOUTH', shape_name

# 323 个 PMX 的类别统计支持这些 MMD 眼皮和嘴部名称；眉毛、瞳孔保持其他。
for shape_name in (
        'まばたき', '笑い', 'なごみ', 'はぅ', 'びっくり', 'じと目', 'ジト目',
        'ｷﾘｯ', 'はちゅ目'):
    assert module._fbsf_auto_function_tag(shape_name) == 'BOTH_EYES'
for shape_name in ('ウィンク', 'ウィンク２'):
    assert module._fbsf_auto_function_tag(shape_name) == 'LEFT_EYE'
for shape_name in ('ウィンク右', 'ウィンク２右', 'ｳｨﾝｸ２右.001'):
    assert module._fbsf_auto_function_tag(shape_name) == 'RIGHT_EYE'
for shape_name in (
        'あ', 'い', 'う', 'え', 'お', 'にやり', 'にっこり',
        '口角上げ', '口横狭め', '口上', '口下'):
    assert module._fbsf_auto_function_tag(shape_name) == 'MOUTH'
for shape_name in ('真面目', '困る', '怒り', 'にこり', '瞳小', '星目'):
    assert module._fbsf_auto_function_tag(shape_name) == 'OTHERS'

directional_eye_names = ('eye_left', 'eye_right', 'eye_up', 'eye_down')
for shape_name in directional_eye_names:
    assert module._fbsf_auto_function_tag(
        shape_name, directional_eye_names) == 'OTHERS'
assert module._fbsf_auto_function_tag('eye_left') == 'OTHERS'
assert module._fbsf_auto_function_tag('EyeLook_Left') == 'OTHERS'
assert module._fbsf_auto_function_tag('eye_close_L') == 'OTHERS'
assert module._fbsf_auto_function_tag('Eyelid_close_R') == 'OTHERS'
assert module._fbsf_auto_function_tag('vrc.lowerlid_left') == 'OTHERS'
for shape_name in (
        'EyeMaterial', 'Eyebrow', '目線材質', 'MouthMask',
        'EyeSculptLeft', 'Eyelid_Anger', 'mouth_morph_wide',
        'EyeLook_Yori', 'Mouth_Smile'):
    assert module._fbsf_auto_function_tag(shape_name) == 'OTHERS'

vrm_context = ('A', 'I', 'U', 'E', 'O', 'Blink', 'LookLeft')
for shape_name in ('A', 'I', 'U', 'E', 'O'):
    assert module._fbsf_auto_function_tag(
        shape_name, vrm_context) == 'MOUTH'
assert module._fbsf_auto_function_tag('A') == 'OTHERS'
meta_context = tuple(module.QUEST_PRO_SHAPEKEYS + module.META_VISEME_SHAPEKEYS)
for shape_name in module.META_VISEME_SHAPEKEYS:
    assert module._fbsf_auto_function_tag(
        shape_name, meta_context) == 'MOUTH', shape_name
assert module._fbsf_auto_function_tag('XX', meta_context) == 'OTHERS'

assert module._fbsf_auto_preset('eyeLookUpLeft').reference_tag == 'OTHERS'
assert module._fbsf_auto_preset('EyeDilationLeft').function_tag == 'OTHERS'
assert module._fbsf_auto_preset('eyeBlinkLeft').reference_tag == 'LEFT_EYE'
assert module._fbsf_auto_preset('Eyelid_Anger').function_tag == 'OTHERS'
assert module._fbsf_auto_preset('Eyelid_Anger').reference_tag == 'OTHERS'
assert module._fbsf_auto_preset('Eyelid_close').reference_tag == 'OTHERS'
assert module._fbsf_auto_preset('mouth_morph_wide').function_tag == 'OTHERS'
assert module._fbsf_auto_preset('mouth_morph_wide').reference_tag == 'OTHERS'
assert module._fbsf_auto_preset('Mouth_Smile').reference_tag == 'OTHERS'
assert 'eyeblinkleft' in module._fbsf_normalized_names(
    '@eyeBlinkLeft.001.1000')

keyword_basis = np.array(
    [
        (-4.0, 0.0, 0.0), (-3.0, 0.0, 0.0),
        (-2.0, 0.0, 0.0), (-1.0, 0.0, 0.0),
        (1.0, 0.0, 0.0), (2.0, 0.0, 0.0),
        (3.0, 0.0, 0.0), (4.0, 0.0, 0.0),
    ],
    dtype=np.float32,
)
keyword_left = np.zeros_like(keyword_basis)
keyword_left[4:, 1] = 1.0
keyword_right = np.zeros_like(keyword_basis)
keyword_right[:4, 1] = 1.0
keyword_both = keyword_left + keyword_right
keyword_noisy_left = keyword_left.copy()
keyword_noisy_left[0, 1] = 0.1
keyword_noisy_right = keyword_right.copy()
keyword_noisy_right[4, 1] = 0.1
keyword_disagreement = np.zeros_like(keyword_basis)
keyword_disagreement[:4, 1] = 1.0
keyword_disagreement[4, 1] = 10.0

assert module._fbsf_auto_function_tag('custom_wink') == 'OTHERS'
assert module._fbsf_normalized_name(
    'custom_wink') not in module._FBSF_EXACT_PRESETS
assert module._fbsf_keyword_eye_name('FaceWinkLeft') == ('WINK', True)
assert module._fbsf_keyword_eye_name('faceblinkleft') == ('BLINK', True)
assert module._fbsf_keyword_eye_name('auto_blink') == ('BLINK', False)
assert module._fbsf_keyword_eye_name('Twinkle') is None
assert module._fbsf_keyword_eye_name('For_Blink_1') is None
assert module._fbsf_keyword_eye_name('joy_wink') is None
assert module._fbsf_keyword_eye_name('EyeMaterialBlink') is None
assert module._fbsf_keyword_eye_geometry_tag(
    keyword_left, keyword_basis) == 'LEFT_EYE'
assert module._fbsf_keyword_eye_geometry_tag(
    keyword_right, keyword_basis) == 'RIGHT_EYE'
assert module._fbsf_keyword_eye_geometry_tag(
    keyword_both, keyword_basis) == 'BOTH_EYES'
assert module._fbsf_keyword_eye_geometry_tag(
    keyword_noisy_left, keyword_basis) == 'LEFT_EYE'
assert module._fbsf_keyword_eye_geometry_tag(
    keyword_noisy_right, keyword_basis) == 'RIGHT_EYE'
assert module._fbsf_keyword_eye_geometry_tag(
    keyword_disagreement, keyword_basis) is None
assert module._fbsf_keyword_eye_geometry_tag(
    np.empty((0, 3), dtype=np.float32),
    np.empty((0, 3), dtype=np.float32),
) is None

for shape_name, delta, expected in (
        ('custom_wink', keyword_left, 'LEFT_EYE'),
        ('custom_wink.L', keyword_right, 'RIGHT_EYE'),
        ('vrc.blink_left', keyword_left, 'LEFT_EYE'),
        ('ウィンク.VRC', keyword_left, 'LEFT_EYE'),
        ('まばたき.VRC', keyword_both, 'BOTH_EYES'),
        ('角色眨眼', keyword_both, 'BOTH_EYES'),
        ('auto_blink', keyword_both, 'BOTH_EYES')):
    preset = module._fbsf_keyword_eye_preset(
        shape_name, delta, keyword_basis)
    assert preset is not None, shape_name
    assert preset.function_tag == expected, shape_name
    assert preset.reference_tag == expected, shape_name
    assert preset.standards == frozenset({'KEYWORD_GEOMETRY'}), shape_name

for shape_name, delta in (
        ('custom_wink', keyword_both),
        ('custom_blink_left', keyword_both),
        ('custom_wink', np.zeros_like(keyword_basis)),
        ('custom_wink', keyword_disagreement),
        ('For_Blink_1', keyword_both),
        ('joy_wink', keyword_right),
        ('Blink', keyword_both)):
    assert module._fbsf_keyword_eye_preset(
        shape_name, delta, keyword_basis) is None, shape_name

keyword_tags = {
    'custom_wink': ('OTHERS', 'OTHERS'),
    'auto_blink': ('OTHERS', 'OTHERS'),
    'joy_wink': ('OTHERS', 'OTHERS'),
}
keyword_deltas = {
    'custom_wink': keyword_left,
    'auto_blink': keyword_both,
    'joy_wink': keyword_right,
}
resolved_keyword_tags = module._fbsf_resolve_keyword_eye_tags(
    keyword_tags,
    keyword_basis,
    True,
    module._fbsf_classification_context(keyword_tags),
    keyword_deltas.__getitem__,
)
assert resolved_keyword_tags == {
    'custom_wink': ('LEFT_EYE', 'LEFT_EYE'),
    'auto_blink': ('BOTH_EYES', 'BOTH_EYES'),
    'joy_wink': ('OTHERS', 'OTHERS'),
}

negative_x_wink = np.zeros_like(fbsf_edit)
negative_x_wink[:2, 1] = 1.0
positive_x_wink = np.zeros_like(fbsf_edit)
positive_x_wink[2:, 1] = 1.0
assert module._fbsf_resolve_mmd_side_tag(
    'ウィンク', 'LEFT_EYE', 'LEFT_EYE', negative_x_wink, fbsf_basis,
) == ('RIGHT_EYE', 'RIGHT_EYE')
assert module._fbsf_resolve_mmd_side_tag(
    'ウィンク', 'LEFT_EYE', 'LEFT_EYE', positive_x_wink, fbsf_basis,
) == ('LEFT_EYE', 'LEFT_EYE')
assert module._fbsf_resolve_mmd_side_tag(
    'eyeBlinkLeft', 'LEFT_EYE', 'LEFT_EYE', negative_x_wink, fbsf_basis,
) == ('LEFT_EYE', 'LEFT_EYE')
assert module._fbsf_infer_left_is_positive(
    (('LEFT_EYE', np.zeros_like(fbsf_edit)),),
    fbsf_basis,
    fallback=None,
) is None

weak_positive_wink = np.zeros_like(fbsf_edit)
weak_positive_wink[:2, 1] = np.sqrt(3.0)
weak_positive_wink[2:, 1] = np.sqrt(5.0)
assert module._fbsf_infer_left_is_positive(
    (('LEFT_EYE', weak_positive_wink),),
    fbsf_basis,
    fallback=None,
) is None
assert module._fbsf_infer_left_is_positive(
    (
        ('LEFT_EYE', positive_x_wink),
        ('LEFT_EYE', positive_x_wink),
        ('LEFT_EYE', negative_x_wink),
    ),
    fbsf_basis,
    fallback=None,
) is None
assert module._fbsf_infer_left_is_positive(
    (
        ('LEFT_EYE', positive_x_wink),
        ('RIGHT_EYE', negative_x_wink),
    ),
    fbsf_basis,
)
assert not module._fbsf_infer_left_is_positive(
    (
        ('LEFT_EYE', negative_x_wink),
        ('RIGHT_EYE', positive_x_wink),
    ),
    fbsf_basis,
)


def unexpected_standard_delta(_shape_name):
    raise AssertionError("standard delta should be lazy")


left_is_positive, _resolved_side_tags = (
    module._fbsf_resolve_target_side_tags(
        {'eyeBlinkLeft': ('LEFT_EYE', 'LEFT_EYE')},
        (('LEFT_EYE', positive_x_wink),),
        fbsf_basis,
        module._fbsf_classification_context(('eyeBlinkLeft',)),
        unexpected_standard_delta,
        resolve_mmd=False,
    )
)
assert left_is_positive

side_target_tags = {
    'eyeBlinkLeft': ('LEFT_EYE', 'LEFT_EYE'),
    'ウィンク': ('LEFT_EYE', 'LEFT_EYE'),
}
side_context = module._fbsf_classification_context(side_target_tags)
negative_side_deltas = {
    'eyeBlinkLeft': negative_x_wink,
    'ウィンク': negative_x_wink,
}
left_is_positive, resolved_side_tags = (
    module._fbsf_resolve_target_side_tags(
        side_target_tags,
        (('LEFT_EYE', np.zeros_like(fbsf_edit)),),
        fbsf_basis,
        side_context,
        negative_side_deltas.__getitem__,
        resolve_mmd=True,
    )
)
assert not left_is_positive
assert resolved_side_tags['ウィンク'] == ('LEFT_EYE', 'LEFT_EYE')

left_is_positive, _resolved_side_tags = (
    module._fbsf_resolve_target_side_tags(
        side_target_tags,
        (('LEFT_EYE', weak_positive_wink),),
        fbsf_basis,
        side_context,
        negative_side_deltas.__getitem__,
        resolve_mmd=True,
    )
)
assert not left_is_positive

left_is_positive, _resolved_side_tags = (
    module._fbsf_resolve_target_side_tags(
        side_target_tags,
        (('LEFT_EYE', positive_x_wink),),
        fbsf_basis,
        side_context,
        negative_side_deltas.__getitem__,
        resolve_mmd=True,
    )
)
assert left_is_positive

mixed_side_deltas = {
    'eyeBlinkLeft': positive_x_wink,
    'ウィンク': negative_x_wink,
}
left_is_positive, automatic_side_tags = (
    module._fbsf_resolve_target_side_tags(
        side_target_tags,
        (),
        fbsf_basis,
        side_context,
        mixed_side_deltas.__getitem__,
        resolve_mmd=True,
    )
)
assert left_is_positive
assert automatic_side_tags['ウィンク'] == ('RIGHT_EYE', 'RIGHT_EYE')
snapshot_left_is_positive, snapshot_side_tags = (
    module._fbsf_resolve_target_side_tags(
        automatic_side_tags,
        (('LEFT_EYE', negative_x_wink),),
        fbsf_basis,
        side_context,
        mixed_side_deltas.__getitem__,
        resolve_mmd=False,
        orientation_override=left_is_positive,
    )
)
assert snapshot_left_is_positive
assert snapshot_side_tags == automatic_side_tags
_left_is_positive, explicit_side_tags = (
    module._fbsf_resolve_target_side_tags(
        side_target_tags,
        (),
        fbsf_basis,
        side_context,
        mixed_side_deltas.__getitem__,
        resolve_mmd=False,
    )
)
assert explicit_side_tags['ウィンク'] == ('LEFT_EYE', 'LEFT_EYE')

fbsf_references = (
    ('BOTH_EYES', fbsf_target),
    ('MOUTH', np.array([(0.0, 0.0, 1.0)] * 4, dtype=np.float32)),
)
eye_definition = module._fbsf_source_definition(
    fbsf_edit, fbsf_references, fbsf_basis)
assert eye_definition == (1.0, 0.0, 0.0)
assert module._fbsf_infer_left_is_positive(
    (('LEFT_EYE', fbsf_target),), fbsf_basis)
mirrored_left_target = np.array(
    [(0.0, 1.0, 0.0), (0.0, 1.0, 0.0),
     (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)],
    dtype=np.float32,
)
assert not module._fbsf_infer_left_is_positive(
    (('LEFT_EYE', mirrored_left_target),), fbsf_basis)
left_only_weights, left_score, right_score, split_sides = (
    module._fbsf_definition_weights(
        'LEFT_EYE', eye_definition, fbsf_basis, 0.0, 1.0))
assert (left_score, right_score, split_sides) == (1.0, 0.0, True)
assert np.allclose(left_only_weights, (0.0, 0.0, 1.0, 1.0))
legacy_left_weights, *_legacy_details = module._fbsf_definition_weights(
    'LEFT_EYE', eye_definition, fbsf_basis, 0.0, 1.0, False)
assert np.allclose(legacy_left_weights, (1.0, 1.0, 0.0, 0.0))
other_weights, left_score, right_score, split_sides = (
    module._fbsf_definition_weights(
        'OTHERS', eye_definition, fbsf_basis, 0.0, 1.0))
assert (left_score, right_score, split_sides) == (0.0, 0.0, False)
assert not np.any(other_weights)
assert module.OP_ShapekeyTools_RebaseFBSF.bl_label == "全键局部变基-FBSF"
assert "function_tag" in module.PG_ShapekeyTools_FBSFSource.__annotations__
assert "auto_function_tag" in module.PG_ShapekeyTools_FBSFSource.__annotations__
assert "reference_tag" in module.PG_ShapekeyTools_FBSFSource.__annotations__
assert "merge" in module.PG_ShapekeyTools_FBSFSource.__annotations__
assert "mergeable" in module.PG_ShapekeyTools_FBSFSource.__annotations__
assert "enabled" not in module.PG_ShapekeyTools_FBSFSource.__annotations__
assert 'SOURCE' not in module.FBSF_FUNCTION_TAGS
assert module.FBSF_FUNCTION_TAGS == {
    'BOTH_EYES', 'LEFT_EYE', 'RIGHT_EYE', 'MOUTH', 'OTHERS',
}
assert "factor" not in module.OP_ShapekeyTools_RebaseFBSF.__annotations__
assert {
    "sources", "source_index", "side_orientation_snapshot",
    "correction_strength", "side_smooth_width",
}.issubset(module.OP_ShapekeyTools_RebaseFBSF.__annotations__)
assert not hasattr(module, "OP_ShapekeyTools_RebasePreserveExpressions")

registered = (
    module.PG_ShapekeyTools_FBSFSource,
    module.HO_UL_ShapekeyTools_FBSFSources,
    module.OP_ShapekeyTools_Apply_ActiveShapekey2Basis,
    module.OP_ShapekeyTools_RebaseFBSF,
)
for operator in registered:
    bpy.utils.register_class(operator)

try:
    # 任一后续键求解失败时，规划阶段不得提前写入已经处理过的键。
    obj = make_mesh("AtomicRebase", vertex_count=3)
    basis = obj.shape_key_add(name="Basis", from_mix=False)
    source = obj.shape_key_add(name="Source", from_mix=False)
    first_target = obj.shape_key_add(name="FirstTarget", from_mix=False)
    second_target = obj.shape_key_add(name="SecondTarget", from_mix=False)
    source.data[0].co.y += 1.0
    first_target.data[1].co.z += 1.0
    second_target.data[2].co.x += 1.0
    obj.active_shape_key_index = obj.data.shape_keys.key_blocks.find(source.name)
    before_transaction = {
        key.name: positions(key).copy()
        for key in obj.data.shape_keys.key_blocks
    }
    calls = [0]

    def fail_after_first(
            _key, old_key, old_relative, new_relative,
            _old_basis, _old_active, _new_basis):
        calls[0] += 1
        if calls[0] > 1:
            raise RuntimeError("planned failure")
        return old_key + (new_relative - old_relative)

    try:
        module._rewrite_rebased_shape_key_tree(obj, 0.5, fail_after_first)
    except RuntimeError as exc:
        assert str(exc) == "planned failure"
    else:
        raise AssertionError("规划阶段异常未向上传递")
    for key in obj.data.shape_keys.key_blocks:
        assert np.array_equal(positions(key), before_transaction[key.name])
    assert obj.data.shape_keys.key_blocks.get("Source") is not None

    # 两个非零捏脸键会作为 FBSF 来源列表一起烘焙，并按左右权能修正。
    fbsf = make_mesh("FBSFRebase", vertex_count=4)
    x_positions = (-1.0, -0.5, 0.5, 1.0)
    for index, x in enumerate(x_positions):
        fbsf.data.vertices[index].co.x = x
    fbsf_basis_key = fbsf.shape_key_add(name="Basis", from_mix=False)
    fbsf_sculpt = fbsf.shape_key_add(name="EyeSculptLeft", from_mix=False)
    for index in (2, 3):
        fbsf_sculpt.data[index].co.z += 1.0

    fbsf_sculpt_z = fbsf.shape_key_add(name="EyeSculptRight", from_mix=False)
    for index in (0, 1):
        fbsf_sculpt_z.data[index].co.y += 1.0

    fbsf_expression = fbsf.shape_key_add(name="Blink", from_mix=False)
    for index in (0, 1):
        fbsf_expression.data[index].co.y += 1.0
    for index in (2, 3):
        fbsf_expression.data[index].co.z += 1.0

    fbsf_mouth = fbsf.shape_key_add(name="MouthOpen", from_mix=False)
    for point in fbsf_mouth.data:
        point.co.z += 1.0

    fbsf_other = fbsf.shape_key_add(name="CheekPuff", from_mix=False)
    for point in fbsf_other.data:
        point.co.x += 0.1

    fbsf_child = fbsf.shape_key_add(name="RelativeToSculpt", from_mix=False)
    fbsf_child.relative_key = fbsf_sculpt
    for index, point in enumerate(fbsf_child.data):
        point.co = fbsf_sculpt.data[index].co.copy()
        point.co.x += 0.25

    fbsf_sculpt.value = 0.5
    fbsf_sculpt_z.value = 0.25
    module._rebase_shape_keys_fbsf(
        fbsf,
        (
            (fbsf_sculpt.name, 0.5, 'LEFT_EYE'),
            (fbsf_sculpt_z.name, 0.25, 'RIGHT_EYE'),
        ),
        1.0,
        0.0,
    )

    fbsf_keys = fbsf.data.shape_keys.key_blocks
    assert fbsf_keys.get("EyeSculptLeft") is None
    assert fbsf_keys.get("EyeSculptRight") is None
    fbsf_basis_key = fbsf_keys[0]
    fbsf_expression = fbsf_keys["Blink"]
    fbsf_mouth = fbsf_keys["MouthOpen"]
    fbsf_other = fbsf_keys["CheekPuff"]
    fbsf_child = fbsf_keys["RelativeToSculpt"]
    assert fbsf_child.relative_key == fbsf_basis_key
    for index in (0, 1):
        assert_position(fbsf_basis_key, index, (x_positions[index], 0.25, 0.0))
    for index in (2, 3):
        assert_position(fbsf_basis_key, index, (x_positions[index], 0.0, 0.5))
    for index in (0, 1):
        assert_position(fbsf_expression, index, (x_positions[index], 1.0, 0.0))
    for index in (2, 3):
        assert_position(fbsf_expression, index, (x_positions[index], 0.0, 1.0))
    for index in (0, 1):
        assert_position(fbsf_mouth, index, (x_positions[index], 0.25, 1.0))
    for index in (2, 3):
        assert_position(fbsf_mouth, index, (x_positions[index], 0.0, 1.5))
    for index in (0, 1):
        assert_position(fbsf_other, index, (x_positions[index] + 0.1, 0.25, 0.0))
    for index in (2, 3):
        assert_position(fbsf_other, index, (x_positions[index] + 0.1, 0.0, 0.5))
    for index in (0, 1):
        assert_position(fbsf_child, index, (x_positions[index] + 0.25, 0.25, 0.0))
    for index in (2, 3):
        assert_position(fbsf_child, index, (x_positions[index] + 0.25, 0.0, 0.5))

    # 未知名称可以通过弹窗的手工功能标签进入眼睛流程。
    manual = make_mesh("FBSFManualTag", vertex_count=2)
    manual.data.vertices[0].co.x = -1.0
    manual.data.vertices[1].co.x = 1.0
    manual_basis = manual.shape_key_add(name="Basis", from_mix=False)
    manual_source = manual.shape_key_add(name="Sculpt", from_mix=False)
    manual_target = manual.shape_key_add(name="CustomExpression", from_mix=False)
    for point in manual_source.data:
        point.co.y += 1.0
    for point in manual_target.data:
        point.co.y += 1.0
    module._rebase_shape_keys_fbsf(
        manual,
        ((manual_source.name, 1.0, 'BOTH_EYES'),),
        1.0,
        0.0,
        ((manual_target.name, 'BOTH_EYES'),),
    )
    for index, x in enumerate((-1.0, 1.0)):
        assert_position(
            manual.data.shape_keys.key_blocks["CustomExpression"],
            index,
            (x, 1.0, 0.0),
        )

    # 未命中的 wink 只在全自动预处理路径按名称和形变几何进入单眼流程。
    keyword_auto = make_mesh("FBSFKeywordAuto", vertex_count=8)
    for index, x in enumerate((-4.0, -3.0, -2.0, -1.0,
                               1.0, 2.0, 3.0, 4.0)):
        keyword_auto.data.vertices[index].co.x = x
    keyword_auto_basis = keyword_auto.shape_key_add(
        name="Basis", from_mix=False)
    keyword_auto_source = keyword_auto.shape_key_add(
        name="EyeSculpt", from_mix=False)
    keyword_auto_wink = keyword_auto.shape_key_add(
        name="custom_wink", from_mix=False)
    for index in range(4, 8):
        keyword_auto_source.data[index].co.z += 1.0
        keyword_auto_wink.data[index].co.z += 1.0
    module._rebase_shape_keys_fbsf(
        keyword_auto,
        ((keyword_auto_source.name, 1.0, 'LEFT_EYE'),),
        1.0,
        0.0,
        target_specs=None,
    )
    keyword_auto_keys = keyword_auto.data.shape_keys.key_blocks
    for index, x in enumerate((-4.0, -3.0, -2.0, -1.0)):
        assert_position(keyword_auto_keys[0], index, (x, 0.0, 0.0))
        assert_position(
            keyword_auto_keys["custom_wink"], index, (x, 0.0, 0.0))
    for index, x in enumerate((1.0, 2.0, 3.0, 4.0), start=4):
        assert_position(keyword_auto_keys[0], index, (x, 0.0, 1.0))
        assert_position(
            keyword_auto_keys["custom_wink"], index, (x, 0.0, 1.0))

    # 显式标签代表用户确认后的最终值，不能在执行时再次触发关键字推断。
    keyword_manual = make_mesh("FBSFKeywordManual", vertex_count=8)
    for index, x in enumerate((-4.0, -3.0, -2.0, -1.0,
                               1.0, 2.0, 3.0, 4.0)):
        keyword_manual.data.vertices[index].co.x = x
    keyword_manual.shape_key_add(name="Basis", from_mix=False)
    keyword_manual_source = keyword_manual.shape_key_add(
        name="EyeSculpt", from_mix=False)
    keyword_manual_wink = keyword_manual.shape_key_add(
        name="custom_wink", from_mix=False)
    for index in range(4, 8):
        keyword_manual_source.data[index].co.z += 1.0
        keyword_manual_wink.data[index].co.z += 1.0
    module._rebase_shape_keys_fbsf(
        keyword_manual,
        ((keyword_manual_source.name, 1.0, 'LEFT_EYE'),),
        1.0,
        0.0,
        ((keyword_manual_wink.name, 'OTHERS'),),
        orientation_override=True,
    )
    keyword_manual_keys = keyword_manual.data.shape_keys.key_blocks
    for index, x in enumerate((1.0, 2.0, 3.0, 4.0), start=4):
        assert_position(keyword_manual_keys[0], index, (x, 0.0, 1.0))
        assert_position(
            keyword_manual_keys["custom_wink"], index, (x, 0.0, 2.0))

    # “合并”与“功能”相互独立：未选键必须保留；其他来源只做全局变基，
    # 即使它与眼睛目标位移完全同向，也不能触发 FBSF 回弹。
    roles = make_mesh("FBSFSourceRoles", vertex_count=2)
    roles.data.vertices[0].co.x = -1.0
    roles.data.vertices[1].co.x = 1.0
    roles_basis = roles.shape_key_add(name="Basis", from_mix=False)
    roles_global = roles.shape_key_add(name="FaceSculpt", from_mix=False)
    roles_unchecked = roles.shape_key_add(name="EyeSculptLeft", from_mix=False)
    roles_blink = roles.shape_key_add(name="Blink", from_mix=False)
    for point in roles_global.data:
        point.co.y += 1.0
    for point in roles_unchecked.data:
        point.co.z += 1.0
    for point in roles_blink.data:
        point.co.y += 1.0
    source_names, *_details = module._rebase_shape_keys_fbsf(
        roles,
        ((roles_global.name, 0.5, 'OTHERS'),),
        1.0,
        0.0,
        (
            (roles_unchecked.name, 'LEFT_EYE'),
            (roles_blink.name, 'BOTH_EYES'),
        ),
    )
    roles_keys = roles.data.shape_keys.key_blocks
    assert source_names == ("FaceSculpt",)
    assert roles_keys.get("FaceSculpt") is None
    assert roles_keys.get("EyeSculptLeft") is not None
    for index, x in enumerate((-1.0, 1.0)):
        assert_position(roles_keys[0], index, (x, 0.5, 0.0))
        assert_position(roles_keys["Blink"], index, (x, 1.5, 0.0))
        assert_position(roles_keys["EyeSculptLeft"], index, (x, 0.5, 1.0))

    # 原有全键变基算子保持独立并维持原行为。
    legacy = make_mesh("FullRebase", vertex_count=2)
    legacy_basis = legacy.shape_key_add(name="Basis", from_mix=False)
    legacy_source = legacy.shape_key_add(name="Source", from_mix=False)
    legacy_expression = legacy.shape_key_add(name="Expression", from_mix=False)
    for point in legacy_source.data:
        point.co.y += 1.0
    legacy_expression.data[0].co.z += 1.0
    legacy_source.value = 0.5
    legacy.active_shape_key_index = 1

    result = bpy.ops.ho.apply_active_shapekey_to_basis("EXEC_DEFAULT")
    assert result == {'FINISHED'}
    legacy_keys = legacy.data.shape_keys.key_blocks
    assert legacy_keys.get("Source") is None
    assert_position(legacy_keys[0], 0, (0.0, 0.5, 0.0))
    assert_position(legacy_keys[0], 1, (1.0, 0.5, 0.0))
    assert_position(legacy_keys["Expression"], 0, (0.0, 0.5, 1.0))
    assert_position(legacy_keys["Expression"], 1, (1.0, 0.5, 0.0))
finally:
    for operator in reversed(registered):
        bpy.utils.unregister_class(operator)


# 覆盖正式注册列表，确保保留 FBSF 并且不再暴露旧 HO 算子。
module.register()
try:
    assert hasattr(bpy.ops.ho, "apply_active_shapekey_to_basis")
    assert hasattr(bpy.ops.ho, "rebase_shapekeys_fbsf")
    assert "rebase_shapekeys_preserve_expressions" not in dir(bpy.ops.ho)

    template_obj = make_mesh("CatalogTemplate", vertex_count=2)
    result = bpy.ops.ho.add_shapekeys_by_template(
        "EXEC_DEFAULT", shapekey_list='VRCHAT')
    assert result == {'FINISHED'}
    template_keys = template_obj.data.shape_keys.key_blocks
    for shape_name in module.SHAPEKEY_TEMPLATE_MAP['VRCHAT']:
        assert template_keys.get(shape_name) is not None, shape_name
    assert template_keys.get('vrc.blink (3.0)') is None
finally:
    module.unregister()


print("SHAPEKEY_REBASE_OK", bpy.app.version_string)
