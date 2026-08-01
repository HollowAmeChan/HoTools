"""跨工具共用的形态键标准、名称与语义目录。"""

from dataclasses import dataclass
import re
import unicodedata


ARKIT_SHAPEKEYS = [
    "browInnerUp",
    "browDownLeft",
    "browDownRight",
    "browOuterUpLeft",
    "browOuterUpRight",
    "eyeLookUpLeft",
    "eyeLookUpRight",
    "eyeLookDownLeft",
    "eyeLookDownRight",
    "eyeLookInLeft",
    "eyeLookInRight",
    "eyeLookOutLeft",
    "eyeLookOutRight",
    "eyeBlinkLeft",
    "eyeBlinkRight",
    "eyeSquintLeft",
    "eyeSquintRight",
    "eyeWideLeft",
    "eyeWideRight",
    "cheekPuff",
    "cheekSquintLeft",
    "cheekSquintRight",
    "noseSneerLeft",
    "noseSneerRight",
    "jawOpen",
    "jawForward",
    "jawLeft",
    "jawRight",
    "mouthFunnel",
    "mouthPucker",
    "mouthLeft",
    "mouthRight",
    "mouthRollUpper",
    "mouthRollLower",
    "mouthShrugUpper",
    "mouthShrugLower",
    "mouthClose",
    "mouthSmileLeft",
    "mouthSmileRight",
    "mouthFrownLeft",
    "mouthFrownRight",
    "mouthDimpleLeft",
    "mouthDimpleRight",
    "mouthUpperUpLeft",
    "mouthUpperUpRight",
    "mouthLowerDownLeft",
    "mouthLowerDownRight",
    "mouthPressLeft",
    "mouthPressRight",
    "mouthStretchLeft",
    "mouthStretchRight",
    "tongueOut",
]
VRCHAT_SHAPEKEYS = [
    "vrc.v_aa",
    "vrc.v_ih",
    "vrc.v_ou",
    "vrc.v_e",
    "vrc.v_oh",

    "vrc.v_sil",
    "vrc.v_pp",
    "vrc.v_ff",
    "vrc.v_th",
    "vrc.v_dd",
    "vrc.v_kk",
    "vrc.v_ch",
    "vrc.v_ss",
    "vrc.v_nn",
    "vrc.v_rr",

    "vrc.looking_up",
    "vrc.looking_down",
    "vrc.blink",
]
VRCHAT_SHAPEKEY_ALIASES = [
    "vrc.blink (3.0)",
]
MMD_SHAPEKEYS = [
    "まばたき", "笑い", "ウィンク", "ウィンク右", "ウィンク２", "ｳｨﾝｸ２右", "なごみ", "はぅ",
    "びっくり", "じと目", "ｷﾘｯ", "はちゅ目", "星目", "はぁと", "瞳小", "瞳縦潰れ",
    "光下", "恐ろしい子！", "ハイライト消", "映り込み消", "喜び", "わぉ?!", "なごみω",
    "悲しむ", "敵意",
    "あ", "い", "う", "え", "お", "あ２", "ん", "▲", "∧", "□",
    "ワ", "ω", "ω□", "にやり", "にやり２", "にっこり", "ぺろっ", "てへぺろ", "てへぺろ２",
    "口角上げ", "口角下げ", "口横広げ", "歯無し上", "歯無し下",
    "真面目", "困る", "にこり",
    "怒り", "上", "下"
]
MMD_EYE_SHAPEKEY_ALIASES = (
    "ジト目",
)
MMD_MOUTH_SHAPEKEY_ALIASES = (
    "えー", "はんっ！", "口横狭め", "口上", "口下",
)
MMD_SHAPEKEY_ALIASES = (
    MMD_EYE_SHAPEKEY_ALIASES + MMD_MOUTH_SHAPEKEY_ALIASES
)
VRM_SHAPEKEYS = [
    "A", "I", "U", "E", "O",
    "Blink", "Joy", "Angry", "Sorrow", "Fun",
    "LookUp", "LookDown", "LookLeft", "LookRight",
    "Blink_L", "Blink_R"
]

UNIFIED_EXPRESSIONS_BASE_SHAPEKEYS = [
    "EyeLookOutRight",
    "EyeLookInRight",
    "EyeLookUpRight",
    "EyeLookDownRight",
    "EyeLookOutLeft",
    "EyeLookInLeft",
    "EyeLookUpLeft",
    "EyeLookDownLeft",
    "EyeClosedRight",
    "EyeClosedLeft",
    "EyeSquintRight",
    "EyeSquintLeft",
    "EyeWideRight",
    "EyeWideLeft",
    "EyeDilationRight",
    "EyeDilationLeft",
    "EyeConstrictRight",
    "EyeConstrictLeft",
    "BrowPinchRight",
    "BrowPinchLeft",
    "BrowLowererRight",
    "BrowLowererLeft",
    "BrowInnerUpRight",
    "BrowInnerUpLeft",
    "BrowOuterUpRight",
    "BrowOuterUpLeft",
    "NoseSneerRight",
    "NoseSneerLeft",
    "NasalDilationRight",
    "NasalDilationLeft",
    "NasalConstrictRight",
    "NasalConstrictLeft",
    "CheekSquintRight",
    "CheekSquintLeft",
    "CheekPuffRight",
    "CheekPuffLeft",
    "CheekSuckRight",
    "CheekSuckLeft",
    "JawOpen",
    "MouthClosed",
    "JawRight",
    "JawLeft",
    "JawForward",
    "JawBackward",
    "JawClench",
    "JawMandibleRaise",
    "LipSuckUpperRight",
    "LipSuckUpperLeft",
    "LipSuckLowerRight",
    "LipSuckLowerLeft",
    "LipSuckCornerRight",
    "LipSuckCornerLeft",
    "LipFunnelUpperRight",
    "LipFunnelUpperLeft",
    "LipFunnelLowerRight",
    "LipFunnelLowerLeft",
    "LipPuckerUpperRight",
    "LipPuckerUpperLeft",
    "LipPuckerLowerRight",
    "LipPuckerLowerLeft",
    "MouthUpperUpRight",
    "MouthUpperUpLeft",
    "MouthLowerDownRight",
    "MouthLowerDownLeft",
    "MouthUpperDeepenRight",
    "MouthUpperDeepenLeft",
    "MouthUpperRight",
    "MouthUpperLeft",
    "MouthLowerRight",
    "MouthLowerLeft",
    "MouthCornerPullRight",
    "MouthCornerPullLeft",
    "MouthCornerSlantRight",
    "MouthCornerSlantLeft",
    "MouthFrownRight",
    "MouthFrownLeft",
    "MouthStretchRight",
    "MouthStretchLeft",
    "MouthDimpleRight",
    "MouthDimpleLeft",
    "MouthRaiserUpper",
    "MouthRaiserLower",
    "MouthPressRight",
    "MouthPressLeft",
    "MouthTightenerRight",
    "MouthTightenerLeft",
    "TongueOut",
    "TongueUp",
    "TongueDown",
    "TongueRight",
    "TongueLeft",
    "TongueRoll",
    "TongueBendDown",
    "TongueCurlUp",
    "TongueSquish",
    "TongueFlat",
    "TongueTwistRight",
    "TongueTwistLeft",
    "SoftPalateClose",
    "ThroatSwallow",
    "NeckFlexRight",
    "NeckFlexLeft",
]
UNIFIED_EXPRESSIONS_BLEND_SHAPEKEYS =[
    "EyeClosed",
    "EyeWide",
    "EyeSquint",
    "EyeDilation",
    "EyeConstrict",
    "BrowDownRight",
    "BrowDownLeft",
    "BrowDown",
    "BrowInnerUp",
    "BrowUpRight",
    "BrowUpLeft",
    "BrowUp",
    "NoseSneer",
    "NasalDilation",
    "NasalConstrict",
    "CheekPuff",
    "CheekSuck",
    "CheekSquint",
    "LipSuckUpper",
    "LipSuckLower",
    "LipSuck",
    "LipFunnelUpper",
    "LipFunnelLower",
    "LipFunnel",
    "LipPuckerUpper",
    "LipPuckerLower",
    "LipPucker",
    "MouthUpperUp",
    "MouthLowerDown",
    "MouthOpen",
    "MouthRight",
    "MouthLeft",
    "MouthSmileRight",
    "MouthSmileLeft",
    "MouthSmile",
    "MouthSadRight",
    "MouthSadLeft",
    "MouthSad",
    "MouthStretch",
    "MouthDimple",
    "MouthTightener",
    "MouthPress"
]
QUEST_PRO_SHAPEKEYS = [
    "EYES_LOOK_UP_R",
    "EYES_LOOK_DOWN_R",
    "EYES_LOOK_LEFT_R",
    "EYES_LOOK_RIGHT_R",
    "EYES_LOOK_UP_L",
    "EYES_LOOK_DOWN_L",
    "EYES_LOOK_LEFT_L",
    "EYES_LOOK_RIGHT_L",
    "EYES_CLOSED_R",
    "EYES_CLOSED_L",
    "LID_TIGHTENER_R",
    "LID_TIGHTENER_L",
    "UPPER_LID_RAISER_R",
    "UPPER_LID_RAISER_L",
    "BROW_LOWERER_R",
    "BROW_LOWERER_L",
    "INNER_BROW_RAISER_R",
    "INNER_BROW_RAISER_L",
    "OUTER_BROW_RAISER_R",
    "OUTER_BROW_RAISER_L",
    "NOSE_WRINKLER_R",
    "NOSE_WRINKLER_L",
    "CHEEK_RAISER_R",
    "CHEEK_RAISER_L",
    "CHEEK_PUFF_R",
    "CHEEK_PUFF_L",
    "CHEEK_SUCK_R",
    "CHEEK_SUCK_L",
    "JAW_DROP",
    "LIPS_TOWARD",
    "JAW_SIDEWAYS_RIGHT",
    "JAW_SIDEWAYS_LEFT",
    "JAW_THRUST",
    "LIP_SUCK_RT",
    "LIP_SUCK_LT",
    "LIP_SUCK_RB",
    "LIP_SUCK_LB",
    "LIP_FUNNELER_RT",
    "LIP_FUNNELER_LT",
    "LIP_FUNNELER_RB",
    "LIP_FUNNELER_LB",
    "LIP_PUCKER_R",
    "LIP_PUCKER_L",
    "UPPER_LIP_RAISER_R",
    "UPPER_LIP_RAISER_L",
    "LOWER_LIP_DEPRESSOR_R",
    "LOWER_LIP_DEPRESSOR_L",
    "LIP_CORNER_PULLER_R",
    "LIP_CORNER_PULLER_L",
    "LIP_CORNER_DEPRESSOR_R",
    "LIP_CORNER_DEPRESSOR_L",
    "LIP_STRETCHER_R",
    "LIP_STRETCHER_L",
    "DIMPLER_R",
    "DIMPLER_L",
    "CHIN_RAISER_T",
    "CHIN_RAISER_B",
    "LIP_PRESSOR_R",
    "LIP_PRESSOR_L",
    "LIP_TIGHTENER_R",
    "LIP_TIGHTENER_L",
    "MOUTH_RIGHT",
    "MOUTH_LEFT",
    "TONGUE_TIP_INTERDENTAL",
    "TONGUE_TIP_ALVEOLAR",
    "TONGUE_FRONT_DORSAL_PALATE",
    "TONGUE_MID_DORSAL_PALATE",
    "TONGUE_BACK_DORSAL_VELAR",
    "TONGUE_OUT",
    "TONGUE_RETREAT",
]
META_VISEME_SHAPEKEYS = [
    "SIL", "PP", "FF", "TH", "DD", "KK", "CH", "SS", "NN", "RR",
    "AA", "E", "IH", "OH", "OU",
]
# VRM 1.0 将眨眼、视线、口型等程序表情与艺术表情分开；这里仍列出艺术
# 表情，使 FBSF 能明确将它们保留为“其他”。
VRM1_SHAPEKEYS = [
    "Neutral", "Happy", "Angry", "Sad", "Relaxed", "Surprised",
    "Aa", "Ih", "Ou", "Ee", "Oh",
    "Blink", "BlinkLeft", "BlinkRight",
    "LookUp", "LookDown", "LookLeft", "LookRight",
]
PICO_EYE_SHAPEKEYS = [
    f"Eye{action}_{side}"
    for action in ("LookDown", "LookIn", "LookOut", "LookUp",
                   "Blink", "Squint", "Wide")
    for side in ("L", "R")
]
PICO_MOUTH_SHAPEKEYS = [
    "JawForward", "JawLeft", "JawOpen", "JawRight", "MouthClose",
    "MouthFunnel", "MouthLeft", "MouthPucker", "MouthRight",
    "MouthRollLower", "MouthRollUpper", "MouthShrugLower",
    "MouthShrugUpper", "TongueOut",
] + [
    f"Mouth{action}_{side}"
    for action in (
        "Dimple", "Frown", "LowerDown", "Press", "Smile", "Stretch",
        "UpperUp",
    )
    for side in ("L", "R")
]
PICO_OTHER_SHAPEKEYS = [
    "BrowInnerUp", "CheekPuff",
] + [
    f"{feature}_{side}"
    for feature in ("BrowDown", "BrowOuterUp", "CheekSquint", "NoseSneer")
    for side in ("L", "R")
]
PICO_VISEME_SHAPEKEYS = [
    "PP", "CH", "o", "O", "I", "u", "RR", "XX", "aa", "i",
    "FF", "U", "TH", "kk", "SS", "e", "DD", "E", "nn", "sil",
]
PICO_SHAPEKEYS = (
    PICO_EYE_SHAPEKEYS
    + PICO_MOUTH_SHAPEKEYS
    + PICO_OTHER_SHAPEKEYS
    + PICO_VISEME_SHAPEKEYS
)
OCULUS_VISEME_TOKENS = [
    "sil", "PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR",
    "aa", "E", "I", "O", "U",
]
OCULUS_VISEME_SHAPEKEYS = [
    f"viseme_{token}" for token in OCULUS_VISEME_TOKENS
]
VIVE_SRANIPAL_EYE_SHAPEKEYS = [
    f"Eye_{side}_{action}"
    for side in ("Left", "Right")
    for action in ("Blink", "Wide", "Right", "Left", "Up", "Down", "Squeeze")
] + ["Eye_Frown"]
VIVE_SRANIPAL_LIP_SHAPEKEYS = [
    "Jaw_Right", "Jaw_Left", "Jaw_Forward", "Jaw_Open",
    "Mouth_Ape_Shape", "Mouth_Upper_Right", "Mouth_Upper_Left",
    "Mouth_Lower_Right", "Mouth_Lower_Left", "Mouth_Upper_Overturn",
    "Mouth_Lower_Overturn", "Mouth_Pout", "Mouth_Smile_Right",
    "Mouth_Smile_Left", "Mouth_Sad_Right", "Mouth_Sad_Left",
    "Cheek_Puff_Right", "Cheek_Puff_Left", "Cheek_Suck",
    "Mouth_Upper_UpRight", "Mouth_Upper_UpLeft",
    "Mouth_Lower_DownRight", "Mouth_Lower_DownLeft",
    "Mouth_Upper_Inside", "Mouth_Lower_Inside", "Mouth_Lower_Overlay",
    "Tongue_LongStep1", "Tongue_LongStep2", "Tongue_Down", "Tongue_Up",
    "Tongue_Right", "Tongue_Left", "Tongue_Roll",
    "Tongue_UpLeft_Morph", "Tongue_UpRight_Morph",
    "Tongue_DownLeft_Morph", "Tongue_DownRight_Morph",
]
VIVE_SRANIPAL_SHAPEKEYS = (
    VIVE_SRANIPAL_EYE_SHAPEKEYS + VIVE_SRANIPAL_LIP_SHAPEKEYS
)
VIVE_OPENXR_EYE_SHAPEKEYS = [
    f"XR_EYE_EXPRESSION_{side}_{action}_HTC"
    for side in ("LEFT", "RIGHT")
    for action in ("BLINK", "DOWN", "IN", "OUT", "SQUEEZE", "UP", "WIDE")
]
VIVE_OPENXR_LIP_SHAPEKEYS = [
    "XR_LIP_EXPRESSION_CHEEK_PUFF_LEFT_HTC",
    "XR_LIP_EXPRESSION_CHEEK_PUFF_RIGHT_HTC",
    "XR_LIP_EXPRESSION_CHEEK_SUCK_HTC",
    "XR_LIP_EXPRESSION_JAW_FORWARD_HTC",
    "XR_LIP_EXPRESSION_JAW_LEFT_HTC",
    "XR_LIP_EXPRESSION_JAW_OPEN_HTC",
    "XR_LIP_EXPRESSION_JAW_RIGHT_HTC",
    "XR_LIP_EXPRESSION_MOUTH_APE_SHAPE_HTC",
    "XR_LIP_EXPRESSION_MOUTH_LOWER_DOWNLEFT_HTC",
    "XR_LIP_EXPRESSION_MOUTH_LOWER_DOWNRIGHT_HTC",
    "XR_LIP_EXPRESSION_MOUTH_LOWER_INSIDE_HTC",
    "XR_LIP_EXPRESSION_MOUTH_LOWER_LEFT_HTC",
    "XR_LIP_EXPRESSION_MOUTH_LOWER_OVERLAY_HTC",
    "XR_LIP_EXPRESSION_MOUTH_LOWER_OVERTURN_HTC",
    "XR_LIP_EXPRESSION_MOUTH_LOWER_RIGHT_HTC",
    "XR_LIP_EXPRESSION_MOUTH_POUT_HTC",
    "XR_LIP_EXPRESSION_MOUTH_RAISER_LEFT_HTC",
    "XR_LIP_EXPRESSION_MOUTH_RAISER_RIGHT_HTC",
    "XR_LIP_EXPRESSION_MOUTH_STRETCHER_LEFT_HTC",
    "XR_LIP_EXPRESSION_MOUTH_STRETCHER_RIGHT_HTC",
    "XR_LIP_EXPRESSION_MOUTH_UPPER_INSIDE_HTC",
    "XR_LIP_EXPRESSION_MOUTH_UPPER_LEFT_HTC",
    "XR_LIP_EXPRESSION_MOUTH_UPPER_OVERTURN_HTC",
    "XR_LIP_EXPRESSION_MOUTH_UPPER_RIGHT_HTC",
    "XR_LIP_EXPRESSION_MOUTH_UPPER_UPLEFT_HTC",
    "XR_LIP_EXPRESSION_MOUTH_UPPER_UPRIGHT_HTC",
    "XR_LIP_EXPRESSION_TONGUE_DOWNLEFT_MORPH_HTC",
    "XR_LIP_EXPRESSION_TONGUE_DOWNRIGHT_MORPH_HTC",
    "XR_LIP_EXPRESSION_TONGUE_DOWN_HTC",
    "XR_LIP_EXPRESSION_TONGUE_LEFT_HTC",
    "XR_LIP_EXPRESSION_TONGUE_LONGSTEP1_HTC",
    "XR_LIP_EXPRESSION_TONGUE_LONGSTEP2_HTC",
    "XR_LIP_EXPRESSION_TONGUE_RIGHT_HTC",
    "XR_LIP_EXPRESSION_TONGUE_ROLL_HTC",
    "XR_LIP_EXPRESSION_TONGUE_UPLEFT_MORPH_HTC",
    "XR_LIP_EXPRESSION_TONGUE_UPRIGHT_MORPH_HTC",
    "XR_LIP_EXPRESSION_TONGUE_UP_HTC",
]
VIVE_OPENXR_SHAPEKEYS = (
    VIVE_OPENXR_EYE_SHAPEKEYS + VIVE_OPENXR_LIP_SHAPEKEYS
)
@dataclass(frozen=True)
class ShapeKeyStandardSpec:
    """一个可识别、可添加的形态键规范。"""

    identifier: str
    label: str
    description: str
    template_names: tuple
    classifier_id: str
    recognized_aliases: tuple = ()
    source_urls: tuple = ()
    reliable_side: bool = False

    @property
    def recognized_names(self):
        return self.template_names + self.recognized_aliases


SHAPEKEY_STANDARD_SPECS = (
    ShapeKeyStandardSpec(
        'ARKIT', "ARKit", "ARKit 形态键列表",
        tuple(ARKIT_SHAPEKEYS), 'ARKIT',
        source_urls=(
            'https://arkit-face-blendshapes.com/',
        ),
        reliable_side=True),
    ShapeKeyStandardSpec(
        'VRCHAT', "VRChat", "VRChat 形态键列表",
        tuple(VRCHAT_SHAPEKEYS), 'VRCHAT',
        tuple(VRCHAT_SHAPEKEY_ALIASES)),
    ShapeKeyStandardSpec(
        'MMD', "MMD", "MMD 形态键列表",
        tuple(MMD_SHAPEKEYS), 'MMD', tuple(MMD_SHAPEKEY_ALIASES)),
    ShapeKeyStandardSpec(
        'VRM', "VRM 0.x", "VRM 0.x 形态键列表",
        tuple(VRM_SHAPEKEYS), 'VRM', reliable_side=True),
    ShapeKeyStandardSpec(
        'VRM1', "VRM 1.0", "VRM 1.0 表情预设列表",
        tuple(VRM1_SHAPEKEYS), 'VRM1',
        source_urls=('https://vrm.dev/vrm1/expression/',),
        reliable_side=True),
    ShapeKeyStandardSpec(
        'QUEST_PRO', "Meta Movement", "Meta Movement 形态键列表",
        tuple(QUEST_PRO_SHAPEKEYS), 'META',
        source_urls=(
            'https://developers.meta.com/horizon/documentation/unity/'
            'move-face-tracking/',
        ),
        reliable_side=True),
    ShapeKeyStandardSpec(
        'META_VISEME', "Meta Viseme", "Meta Movement 15 音素列表",
        tuple(META_VISEME_SHAPEKEYS), 'META_VISEME',
        source_urls=(
            'https://developers.meta.com/horizon/documentation/unity/'
            'move-face-tracking/',
        )),
    ShapeKeyStandardSpec(
        'PICO', "PICO", "PICO 52 形态键和 20 音素列表",
        tuple(PICO_SHAPEKEYS), 'PICO',
        source_urls=(
            'https://developer-cn.picoxr.com/document/unity/face-tracking/',
        ),
        reliable_side=True),
    ShapeKeyStandardSpec(
        'OCULUS_VISEME', "Oculus Viseme", "Oculus/Meta 15 音素列表",
        tuple(OCULUS_VISEME_SHAPEKEYS), 'OCULUS_VISEME',
        source_urls=(
            'https://developers.meta.com/horizon/documentation/unity/'
            'audio-ovrlipsync-viseme-reference/',
        )),
    ShapeKeyStandardSpec(
        'VIVE_SRANIPAL', "VIVE SRanipal", "VIVE SRanipal 眼部和唇部列表",
        tuple(VIVE_SRANIPAL_SHAPEKEYS), 'VIVE_SRANIPAL',
        source_urls=(
            'https://docs.vrcft.io/docs/tutorial-avatars/'
            'tutorial-avatars-extras/compatibility/vive-sranipal',
        ),
        reliable_side=True),
    ShapeKeyStandardSpec(
        'VIVE_OPENXR', "VIVE OpenXR", "XR_HTC_facial_tracking 表情列表",
        tuple(VIVE_OPENXR_SHAPEKEYS), 'VIVE_OPENXR',
        source_urls=(
            'https://hub.vive.com/apidoc/api/'
            'VIVE.OpenXR.FacialTracking.html',
        ),
        reliable_side=True),
    ShapeKeyStandardSpec(
        'UNIFIED_EXPRESSIONS_BASE', "Unified-base",
        "Unified 基础形态键列表", tuple(UNIFIED_EXPRESSIONS_BASE_SHAPEKEYS),
        'UNIFIED_BASE',
        source_urls=(
            'https://docs.vrcft.io/docs/tutorial-avatars/'
            'tutorial-avatars-extras/unified-blendshapes',
        ),
        reliable_side=True),
    ShapeKeyStandardSpec(
        'UNIFIED_EXPRESSIONS_BLEND', "Unified-blend",
        "Unified 混合形态键列表", tuple(UNIFIED_EXPRESSIONS_BLEND_SHAPEKEYS),
        'UNIFIED_BLEND',
        source_urls=(
            'https://docs.vrcft.io/docs/tutorial-avatars/'
            'tutorial-avatars-extras/unified-blendshapes',
        )),
)

# 字典是其他工具读取标准元数据的主入口；元组保留稳定的 UI 排序。
SHAPEKEY_STANDARDS = {
    spec.identifier: spec
    for spec in SHAPEKEY_STANDARD_SPECS
}
SHAPEKEY_TEMPLATE_MAP = {
    identifier: spec.template_names
    for identifier, spec in SHAPEKEY_STANDARDS.items()
}
SHAPEKEY_TEMPLATE_ITEMS = tuple(
    (spec.identifier, spec.label, spec.description)
    for spec in SHAPEKEY_STANDARD_SPECS
)


_BLENDER_NUMERIC_SUFFIX = re.compile(r"\.\d{3,}$")


def normalized_shape_key_names(shape_name):
    """返回规范名，以及逐层移除 Blender 数字后缀后的候选。"""
    normalized = unicodedata.normalize('NFKC', shape_name)
    normalized = normalized.strip().lstrip('@+').strip().casefold()
    names = {normalized}
    while _BLENDER_NUMERIC_SUFFIX.search(normalized):
        normalized = _BLENDER_NUMERIC_SUFFIX.sub('', normalized)
        names.add(normalized)
    return names


def normalize_shape_key_name(shape_name):
    """返回适合精确目录查询的最短规范名。"""
    return min(normalized_shape_key_names(shape_name), key=len)


@dataclass(frozen=True)
class ShapeKeyCatalogEntry:
    """同一规范名在全部标准中的合并记录。"""

    canonical_name: str
    normalized_name: str
    names: tuple
    template_names: tuple
    aliases: tuple
    standard_ids: frozenset
    standards: frozenset
    region: str = 'OTHER'
    side: str = 'NONE'
    semantic: str = 'OTHER'

    @property
    def is_template(self):
        return bool(self.template_names)

    @property
    def source_urls(self):
        urls = []
        for spec in SHAPEKEY_STANDARD_SPECS:
            if spec.identifier not in self.standard_ids:
                continue
            for url in spec.source_urls:
                if url not in urls:
                    urls.append(url)
        return tuple(urls)


@dataclass
class _ShapeKeyCatalogBuilder:
    names: list
    template_names: list
    aliases: list
    standard_ids: set
    standards: set
    region: str = 'OTHER'
    side: str = 'NONE'
    semantic: str = 'OTHER'


_SHAPEKEY_CATALOG_BUILDERS = {}


def _catalog_builder(name):
    normalized = normalize_shape_key_name(name)
    builder = _SHAPEKEY_CATALOG_BUILDERS.get(normalized)
    if builder is None:
        builder = _ShapeKeyCatalogBuilder([], [], [], set(), set())
        _SHAPEKEY_CATALOG_BUILDERS[normalized] = builder
    if name not in builder.names:
        builder.names.append(name)
    return normalized, builder


def _register_standard_names(spec):
    for name in spec.template_names:
        _normalized, builder = _catalog_builder(name)
        if name not in builder.template_names:
            builder.template_names.append(name)
        builder.standard_ids.add(spec.identifier)
        builder.standards.add(spec.classifier_id)
    for name in spec.recognized_aliases:
        _normalized, builder = _catalog_builder(name)
        if name not in builder.aliases:
            builder.aliases.append(name)
        builder.standard_ids.add(spec.identifier)
        builder.standards.add(spec.classifier_id)


def _register_semantics(
        names, region, side='NONE', semantic='OTHER', standard='GENERIC'):
    """给语义明确的标准名称补充区域与侧别，并检查冲突。"""
    for name in names:
        _normalized, builder = _catalog_builder(name)
        builder.standards.add(standard)
        incoming = (region, side, semantic)
        existing = (builder.region, builder.side, builder.semantic)
        if builder.semantic != 'OTHER' and existing != incoming:
            raise RuntimeError(
                f"Conflicting shape key catalog entry for {name}: "
                f"{existing} vs {incoming}")
        builder.region, builder.side, builder.semantic = incoming


for _standard_spec in SHAPEKEY_STANDARD_SPECS:
    _register_standard_names(_standard_spec)

for _side_name, _side in (('Left', 'LEFT'), ('Right', 'RIGHT')):
    _register_semantics(
        (f"eyeBlink{_side_name}", f"eyeSquint{_side_name}",
         f"eyeWide{_side_name}"),
        'EYE', _side, 'EYELID', 'ARKIT')
    _register_semantics(
        tuple(
            f"eyeLook{direction}{_side_name}"
            for direction in ('Up', 'Down', 'In', 'Out')
        ),
        'EYE', _side, 'EYE_GAZE', 'ARKIT')
    _register_semantics(
        (f"cheekSquint{_side_name}",),
        'EYE', _side, 'EYE_ORBIT', 'ARKIT')

_register_semantics(
    tuple(
        name for name in ARKIT_SHAPEKEYS
        if name.startswith(('jaw', 'mouth', 'tongue'))
    ),
    'MOUTH', semantic='MOUTH', standard='ARKIT')

_register_semantics(
    ('vrc.blink',) + tuple(VRCHAT_SHAPEKEY_ALIASES),
    'EYE', 'BOTH', 'EYELID', 'VRCHAT')
_register_semantics(
    ('vrc.looking_up', 'vrc.looking_down'),
    'EYE', 'BOTH', 'EYE_GAZE', 'VRCHAT')
_register_semantics(
    tuple(name for name in VRCHAT_SHAPEKEYS if name.startswith('vrc.v_')),
    'MOUTH', semantic='VISEME', standard='VRCHAT')

_register_semantics(
    ('まばたき', '笑い', 'なごみ', 'はぅ', 'びっくり', 'じと目',
     'ｷﾘｯ', 'はちゅ目', '恐ろしい子！', '喜び', '悲しむ')
    + MMD_EYE_SHAPEKEY_ALIASES,
    'EYE', 'BOTH', 'EYELID', 'MMD')
_register_semantics(
    ('ウィンク', 'ウィンク２'),
    'EYE', 'LEFT', 'EYELID', 'MMD')
_register_semantics(
    ('ウィンク右', 'ウィンク２右', 'ｳｨﾝｸ２右'),
    'EYE', 'RIGHT', 'EYELID', 'MMD')
_register_semantics(
    ('あ', 'い', 'う', 'え', 'お', 'あ２', 'ん', '▲', '∧', 'ワ', '□',
     'ω', 'ω□', 'にやり', 'にやり２', 'にっこり',
     'ぺろっ', 'てへぺろ', 'てへぺろ２', '口角上げ', '口角下げ',
     '口横広げ', '歯無し上', '歯無し下')
    + MMD_MOUTH_SHAPEKEY_ALIASES,
    'MOUTH', semantic='MOUTH', standard='MMD')

_register_semantics(
    ('blink',), 'EYE', 'BOTH', 'EYELID', 'VRM')
_register_semantics(
    ('blink_l',), 'EYE', 'LEFT', 'EYELID', 'VRM')
_register_semantics(
    ('blink_r',), 'EYE', 'RIGHT', 'EYELID', 'VRM')
_register_semantics(
    ('lookup', 'lookdown', 'lookleft', 'lookright'),
    'EYE', 'BOTH', 'EYE_GAZE', 'VRM')
_register_semantics(
    ('BlinkLeft',), 'EYE', 'LEFT', 'EYELID', 'VRM1')
_register_semantics(
    ('BlinkRight',), 'EYE', 'RIGHT', 'EYELID', 'VRM1')
_register_semantics(
    ('Aa', 'Ih', 'Ou', 'Ee', 'Oh'),
    'MOUTH', semantic='VISEME', standard='VRM1')

for _side_name, _side in (('Left', 'LEFT'), ('Right', 'RIGHT')):
    _register_semantics(
        (f"EyeClosed{_side_name}", f"EyeSquint{_side_name}",
         f"EyeWide{_side_name}"),
        'EYE', _side, 'EYELID', 'UNIFIED_BASE')
    _register_semantics(
        tuple(
            f"EyeLook{direction}{_side_name}"
            for direction in ('Out', 'In', 'Up', 'Down')
        ),
        'EYE', _side, 'EYE_GAZE', 'UNIFIED_BASE')
    _register_semantics(
        (f"CheekSquint{_side_name}",),
        'EYE', _side, 'EYE_ORBIT', 'UNIFIED_BASE')

_register_semantics(
    tuple(
        name for name in UNIFIED_EXPRESSIONS_BASE_SHAPEKEYS
        if name.startswith(('Jaw', 'Lip', 'Mouth', 'Tongue'))
    ) + ('SoftPalateClose',),
    'MOUTH', semantic='MOUTH', standard='UNIFIED_BASE')
_register_semantics(
    ('EyeClosed', 'EyeWide', 'EyeSquint'),
    'EYE', 'BOTH', 'EYELID', 'UNIFIED_BLEND')
_register_semantics(
    ('CheekSquint',),
    'EYE', 'BOTH', 'EYE_ORBIT', 'UNIFIED_BLEND')
_register_semantics(
    tuple(
        name for name in UNIFIED_EXPRESSIONS_BLEND_SHAPEKEYS
        if name.startswith(('Lip', 'Mouth'))
    ),
    'MOUTH', semantic='MOUTH', standard='UNIFIED_BLEND')

for _suffix, _side in (('_L', 'LEFT'), ('_R', 'RIGHT')):
    _register_semantics(
        tuple(
            name for name in QUEST_PRO_SHAPEKEYS
            if name.endswith(_suffix) and name.startswith((
                'EYES_CLOSED_', 'LID_TIGHTENER_',
                'UPPER_LID_RAISER_',
            ))
        ),
        'EYE', _side, 'EYELID', 'META')
    _register_semantics(
        tuple(
            name for name in QUEST_PRO_SHAPEKEYS
            if name.endswith(_suffix) and name.startswith('EYES_LOOK_')
        ),
        'EYE', _side, 'EYE_GAZE', 'META')
    _register_semantics(
        (f"CHEEK_RAISER{_suffix}",),
        'EYE', _side, 'EYE_ORBIT', 'META')

_register_semantics(
    tuple(
        name for name in QUEST_PRO_SHAPEKEYS
        if name.startswith((
            'CHIN_', 'DIMPLER_', 'JAW_', 'LIP_', 'LIPS_', 'LOWER_LIP_',
            'MOUTH_', 'TONGUE_', 'UPPER_LIP_',
        ))
    ),
    'MOUTH', semantic='MOUTH', standard='META')

_PICO_EYE_ANCHORS = tuple(
    name for name in PICO_EYE_SHAPEKEYS
    if any(token in name for token in ('Blink', 'Squint', 'Wide'))
)
_PICO_EYE_GAZE = tuple(
    name for name in PICO_EYE_SHAPEKEYS if 'Look' in name
)
for _suffix, _side in (('_L', 'LEFT'), ('_R', 'RIGHT')):
    _register_semantics(
        tuple(name for name in _PICO_EYE_ANCHORS if name.endswith(_suffix)),
        'EYE', _side, 'EYELID', 'PICO')
    _register_semantics(
        tuple(name for name in _PICO_EYE_GAZE if name.endswith(_suffix)),
        'EYE', _side, 'EYE_GAZE', 'PICO')
    _register_semantics(
        (f"CheekSquint{_suffix}",),
        'EYE', _side, 'EYE_ORBIT', 'PICO')
_register_semantics(
    PICO_MOUTH_SHAPEKEYS,
    'MOUTH', semantic='MOUTH', standard='PICO')

_register_semantics(
    OCULUS_VISEME_SHAPEKEYS,
    'MOUTH', semantic='VISEME', standard='OCULUS_VISEME')

for _side_name, _side in (('Left', 'LEFT'), ('Right', 'RIGHT')):
    _register_semantics(
        tuple(
            name for name in VIVE_SRANIPAL_EYE_SHAPEKEYS
            if name.startswith(f'Eye_{_side_name}_')
            and name.endswith(('Blink', 'Wide', 'Squeeze'))
        ),
        'EYE', _side, 'EYELID', 'VIVE_SRANIPAL')
    _register_semantics(
        tuple(
            name for name in VIVE_SRANIPAL_EYE_SHAPEKEYS
            if name.startswith(f'Eye_{_side_name}_')
            and not name.endswith(('Blink', 'Wide', 'Squeeze'))
        ),
        'EYE', _side, 'EYE_GAZE', 'VIVE_SRANIPAL')
_register_semantics(
    ('Eye_Frown',),
    'EYE', 'BOTH', 'EYE_ORBIT', 'VIVE_SRANIPAL')
_register_semantics(
    tuple(
        name for name in VIVE_SRANIPAL_LIP_SHAPEKEYS
        if name.startswith(('Jaw_', 'Mouth_', 'Tongue_'))
    ),
    'MOUTH', semantic='MOUTH', standard='VIVE_SRANIPAL')

for _side_name, _side in (('LEFT', 'LEFT'), ('RIGHT', 'RIGHT')):
    _register_semantics(
        tuple(
            name for name in VIVE_OPENXR_EYE_SHAPEKEYS
            if f'_{_side_name}_' in name
            and any(token in name for token in (
                '_BLINK_', '_SQUEEZE_', '_WIDE_'))
        ),
        'EYE', _side, 'EYELID', 'VIVE_OPENXR')
    _register_semantics(
        tuple(
            name for name in VIVE_OPENXR_EYE_SHAPEKEYS
            if f'_{_side_name}_' in name
            and not any(token in name for token in (
                '_BLINK_', '_SQUEEZE_', '_WIDE_'))
        ),
        'EYE', _side, 'EYE_GAZE', 'VIVE_OPENXR')
_register_semantics(
    tuple(
        name for name in VIVE_OPENXR_LIP_SHAPEKEYS
        if '_CHEEK_' not in name
    ),
    'MOUTH', semantic='MOUTH', standard='VIVE_OPENXR')


def _freeze_catalog_entry(normalized, builder):
    canonical_name = (
        builder.template_names[0]
        if builder.template_names
        else builder.names[0]
    )
    return ShapeKeyCatalogEntry(
        canonical_name=canonical_name,
        normalized_name=normalized,
        names=tuple(builder.names),
        template_names=tuple(builder.template_names),
        aliases=tuple(builder.aliases),
        standard_ids=frozenset(builder.standard_ids),
        standards=frozenset(builder.standards),
        region=builder.region,
        side=builder.side,
        semantic=builder.semantic,
    )


SHAPEKEY_CATALOG = {
    normalized: _freeze_catalog_entry(normalized, builder)
    for normalized, builder in _SHAPEKEY_CATALOG_BUILDERS.items()
}


def get_shape_key_catalog_entry(shape_name):
    """按名称查询标准目录；自动兼容 Blender 的数字后缀。"""
    return SHAPEKEY_CATALOG.get(normalize_shape_key_name(shape_name))


__all__ = tuple(
    name for name in globals()
    if (name.isupper() and not name.startswith('_')) or name in {
        'ShapeKeyCatalogEntry',
        'ShapeKeyStandardSpec',
        'get_shape_key_catalog_entry',
        'normalize_shape_key_name',
        'normalized_shape_key_names',
    }
)
