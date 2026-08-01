"""模板添加与 FBSF 共用的标准形态键目录。"""

from dataclasses import dataclass


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
# https://docs.vrcft.io/docs/tutorial-avatars/tutorial-avatars-extras/unified-blendshapes

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
# https://developers.meta.com/horizon/documentation/unity/move-face-tracking/

META_VISEME_SHAPEKEYS = [
    "SIL", "PP", "FF", "TH", "DD", "KK", "CH", "SS", "NN", "RR",
    "AA", "E", "IH", "OH", "OU",
]
# https://developers.meta.com/horizon/documentation/unity/move-face-tracking/

# VRM 1.0 将眨眼、视线、口型等程序表情与艺术表情分开；这里仍列出艺术
# 表情，使 FBSF 能明确将它们保留为“其他”。
VRM1_SHAPEKEYS = [
    "Neutral", "Happy", "Angry", "Sad", "Relaxed", "Surprised",
    "Aa", "Ih", "Ou", "Ee", "Oh",
    "Blink", "BlinkLeft", "BlinkRight",
    "LookUp", "LookDown", "LookLeft", "LookRight",
]
# https://vrm.dev/vrm1/expression/

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
# https://developer-cn.picoxr.com/document/unity/face-tracking/

OCULUS_VISEME_TOKENS = [
    "sil", "PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR",
    "aa", "E", "I", "O", "U",
]
OCULUS_VISEME_SHAPEKEYS = [
    f"viseme_{token}" for token in OCULUS_VISEME_TOKENS
]
# https://developers.meta.com/horizon/documentation/unity/audio-ovrlipsync-viseme-reference/

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
# https://docs.vrcft.io/docs/tutorial-avatars/tutorial-avatars-extras/compatibility/vive-sranipal

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
# https://hub.vive.com/apidoc/api/VIVE.OpenXR.FacialTracking.html

@dataclass(frozen=True)
class ShapeKeyStandardSpec:
    identifier: str
    label: str
    description: str
    template_names: tuple
    classifier_id: str
    recognized_aliases: tuple = ()

    @property
    def recognized_names(self):
        return self.template_names + self.recognized_aliases


SHAPEKEY_STANDARD_SPECS = (
    ShapeKeyStandardSpec(
        'ARKIT', "ARKit", "ARKit 形态键列表",
        tuple(ARKIT_SHAPEKEYS), 'ARKIT'),
    ShapeKeyStandardSpec(
        'VRCHAT', "VRChat", "VRChat 形态键列表",
        tuple(VRCHAT_SHAPEKEYS), 'VRCHAT', tuple(VRCHAT_SHAPEKEY_ALIASES)),
    ShapeKeyStandardSpec(
        'MMD', "MMD", "MMD 形态键列表",
        tuple(MMD_SHAPEKEYS), 'MMD', tuple(MMD_SHAPEKEY_ALIASES)),
    ShapeKeyStandardSpec(
        'VRM', "VRM 0.x", "VRM 0.x 形态键列表",
        tuple(VRM_SHAPEKEYS), 'VRM'),
    ShapeKeyStandardSpec(
        'VRM1', "VRM 1.0", "VRM 1.0 表情预设列表",
        tuple(VRM1_SHAPEKEYS), 'VRM1'),
    ShapeKeyStandardSpec(
        'QUEST_PRO', "Meta Movement", "Meta Movement 形态键列表",
        tuple(QUEST_PRO_SHAPEKEYS), 'META'),
    ShapeKeyStandardSpec(
        'META_VISEME', "Meta Viseme", "Meta Movement 15 音素列表",
        tuple(META_VISEME_SHAPEKEYS), 'META_VISEME'),
    ShapeKeyStandardSpec(
        'PICO', "PICO", "PICO 52 形态键和 20 音素列表",
        tuple(PICO_SHAPEKEYS), 'PICO'),
    ShapeKeyStandardSpec(
        'OCULUS_VISEME', "Oculus Viseme", "Oculus/Meta 15 音素列表",
        tuple(OCULUS_VISEME_SHAPEKEYS), 'OCULUS_VISEME'),
    ShapeKeyStandardSpec(
        'VIVE_SRANIPAL', "VIVE SRanipal", "VIVE SRanipal 眼部和唇部列表",
        tuple(VIVE_SRANIPAL_SHAPEKEYS), 'VIVE_SRANIPAL'),
    ShapeKeyStandardSpec(
        'VIVE_OPENXR', "VIVE OpenXR", "XR_HTC_facial_tracking 表情列表",
        tuple(VIVE_OPENXR_SHAPEKEYS), 'VIVE_OPENXR'),
    ShapeKeyStandardSpec(
        'UNIFIED_EXPRESSIONS_BASE', "Unified-base",
        "Unified 基础形态键列表", tuple(UNIFIED_EXPRESSIONS_BASE_SHAPEKEYS),
        'UNIFIED_BASE'),
    ShapeKeyStandardSpec(
        'UNIFIED_EXPRESSIONS_BLEND', "Unified-blend",
        "Unified 混合形态键列表", tuple(UNIFIED_EXPRESSIONS_BLEND_SHAPEKEYS),
        'UNIFIED_BLEND'),
)
SHAPEKEY_TEMPLATE_MAP = {
    spec.identifier: spec.template_names
    for spec in SHAPEKEY_STANDARD_SPECS
}
SHAPEKEY_TEMPLATE_ITEMS = tuple(
    (spec.identifier, spec.label, spec.description)
    for spec in SHAPEKEY_STANDARD_SPECS
)

__all__ = tuple(
    name for name in globals()
    if name.isupper() or name == 'ShapeKeyStandardSpec'
)
