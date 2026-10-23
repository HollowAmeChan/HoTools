"""Humanoid 手指自动映射的回归测试（纯 Python，不需要 Blender）。

覆盖：
* Root/Hips/Left shoulder/Left arm/Left Wrist/LittleFinger1_L 这一套命名的完整映射；
* 手指 1/2/3 必须稳定对应 proximal/intermediate/distal，左右手都不串位；
* 大小写、分隔符、Blender 重名后缀等写法变体；
* Forearm / SpringBone / PinkyToe 这类名字不能被手指规则抢走；
* Toe_Thumb_Proximal_L 等脚趾不能抢占真正的手指，也不能在缺少手指时补位；
* MMD（親指0/1/2 是 0 基）与 VRoid（1 基）两套约定保持原样。
"""

import importlib.util
import sys
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = ADDON_DIR / "BoneTools" / "humanoid_auto_mapping.py"

_spec = importlib.util.spec_from_file_location("hotools_humanoid_auto_mapping", MODULE_PATH)
_module = importlib.util.module_from_spec(_spec)
# dataclasses 要求模块先登记在 sys.modules 里（BoneTools/__init__ 会 import bpy，不能直接 import）
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)

auto_map_source_names_to_humanoid = _module.auto_map_source_names_to_humanoid
_finger_key = _module._finger_key


def mapping_for(source_names):
    result = auto_map_source_names_to_humanoid(source_names)
    return {match.source_name: match.target_name for match in result.matches}


def assert_mapping(source_names, expected, label):
    mapping = mapping_for(source_names)
    problems = [
        f"{name}: 期望 {target}，实际 {mapping.get(name, '(unmatched)')}"
        for name, target in expected.items()
        if mapping.get(name) != target
    ]
    assert not problems, f"[{label}]\n" + "\n".join(problems)


# ---------------------------------------------------------------------------
# 1. 完整的一套命名（手掌被手改名为 Left Wrist / Right Wrist）
# ---------------------------------------------------------------------------
FINGER_LABELS = {
    "LittleFinger": "little",
    "RingFinger": "ring",
    "MiddleFinger": "middle",
    "IndexFinger": "index",
    "Thumb": "thumb",
}
FINGER_SEGMENTS = {1: "proximal", 2: "intermediate", 3: "distal"}

LAYOUT_EXPECTED = {
    "Hips": "hips",
    "Spine": "spine",
    "Chest": "chest",
    "Neck": "neck",
    "Head": "head",
}

for _side, _side_word in (("L", "Left"), ("R", "Right")):
    LAYOUT_EXPECTED.update({
        f"{_side_word} shoulder": f"shoulder.{_side}",
        f"{_side_word} arm": f"upper_arm.{_side}",
        f"{_side_word} elbow": f"lower_arm.{_side}",
        f"{_side_word} Wrist": f"hand.{_side}",
        f"{_side_word} leg": f"upper_leg.{_side}",
        f"{_side_word} knee": f"lower_leg.{_side}",
        f"{_side_word} ankle": f"foot.{_side}",
        f"{_side_word} toe": f"toes.{_side}",
    })
    for _finger_label, _family in FINGER_LABELS.items():
        for _number, _segment in FINGER_SEGMENTS.items():
            LAYOUT_EXPECTED[f"{_finger_label}{_number}_{_side}"] = f"{_family}_{_segment}.{_side}"

layout_result = auto_map_source_names_to_humanoid(["Root"] + list(LAYOUT_EXPECTED) + ["Breast_L", "Breast_R"])
layout_mapping = {match.source_name: match.target_name for match in layout_result.matches}

_layout_problems = [
    f"{name}: 期望 {target}，实际 {layout_mapping.get(name, '(unmatched)')}"
    for name, target in LAYOUT_EXPECTED.items()
    if layout_mapping.get(name) != target
]
assert not _layout_problems, "[layout]\n" + "\n".join(_layout_problems)

# Breast_L/Breast_R 没有 Humanoid 目标（Unity Humanoid 也没有 Breast 骨头）
# Root 也不在 Humanoid 目标列表中。
assert sorted(layout_result.unmatched_sources) == ["Breast_L", "Breast_R", "Root"], layout_result.unmatched_sources
# 全部落到高分别名/结构匹配，不应再出现低置信度提示
assert not layout_result.low_confidence_matches, [
    (match.source_name, match.target_name, match.score) for match in layout_result.low_confidence_matches
]
# 一个目标只能被一根骨骼占用
assert len(set(layout_mapping.values())) == len(layout_mapping)


# ---------------------------------------------------------------------------
# 2. 手指 1/2/3 -> proximal/intermediate/distal（左右手、单手小指单独验证）
# ---------------------------------------------------------------------------
for _side in ("L", "R"):
    LITTLE_ONLY = {
        f"LittleFinger{number}_{_side}": f"little_{segment}.{_side}"
        for number, segment in FINGER_SEGMENTS.items()
    }
    assert_mapping(list(LITTLE_ONLY), LITTLE_ONLY, f"little finger {_side}")

HAND_ONLY = {
    f"{label}{number}_{side}": f"{family}_{segment}.{side}"
    for side in ("L", "R")
    for label, family in FINGER_LABELS.items()
    for number, segment in FINGER_SEGMENTS.items()
}
assert_mapping(list(HAND_ONLY), HAND_ONLY, "both hands")


# ---------------------------------------------------------------------------
# 3. 写法变体：大小写、分隔符、重名后缀、Left hand/Left Wrist
# ---------------------------------------------------------------------------
VARIANT_CASES = (
    ("little_finger_1_L", "little_proximal.L"),
    ("LittleFinger.2.L", "little_intermediate.L"),
    ("LittleFinger3_L.001", "little_distal.L"),
    ("LITTLE_FINGER_2_L", "little_intermediate.L"),
    ("pinky01_L", "little_proximal.L"),
    ("Pinky2.L", "little_intermediate.L"),
    ("Ring Finger 1 L", "ring_proximal.L"),
    ("l_ring_03", "ring_distal.L"),
    ("middlefinger2.L", "middle_intermediate.L"),
    ("Index_Finger_3_L", "index_distal.L"),
    ("LeftFingerIndex1", "index_proximal.L"),
    ("Thumb_1_L", "thumb_proximal.L"),
    ("Left Hand Thumb1", "thumb_proximal.L"),
    ("小指_2_L", "little_intermediate.L"),
    ("左人指3", "index_distal.L"),
    ("右手小指2", "little_intermediate.R"),
    ("J_Bip_L_Little1", "little_proximal.L"),
    ("Left Wrist", "hand.L"),
    ("Right Wrist", "hand.R"),
    ("Left hand", "hand.L"),
    ("Right hand", "hand.R"),
    ("LeftShoulder", "shoulder.L"),
    ("Left arm", "upper_arm.L"),
    ("Left elbow", "lower_arm.L"),
    ("Left leg", "upper_leg.L"),
    ("Left knee", "lower_leg.L"),
    ("Left ankle", "foot.L"),
    ("Left toe", "toes.L"),
    ("LeftForeArm", "lower_arm.L"),
    ("Bip01 L Forearm", "lower_arm.L"),
    ("PinkyToe_L", "toes.L"),
    ("LeftToeBase", "toes.L"),
)

for _source_name, _target in VARIANT_CASES:
    _mapping = mapping_for([_source_name])
    assert _mapping.get(_source_name) == _target, (
        f"{_source_name}: 期望 {_target}，实际 {_mapping.get(_source_name, '(unmatched)')}"
    )

# 手指提示词不能把非手指名字变成手指
assert mapping_for(["LeftMetacarpal_L"]) == {}, mapping_for(["LeftMetacarpal_L"])
# Breast 没有 Humanoid 目标，保持未匹配
assert mapping_for(["Breast_L"]) == {}, mapping_for(["Breast_L"])
assert _finger_key("LeftForeArm") is None
assert _finger_key("SpringBone1_L") is None
assert _finger_key("PinkyToe_L") is None
assert _finger_key("LeftHand") is None
assert _finger_key("LittleFinger1_L") == ("little", 1)
assert _finger_key("左小指3") == ("little", 3)


# ---------------------------------------------------------------------------
# 4. 其它命名约定保持原样
# ---------------------------------------------------------------------------
# MMD：親指 是 0 基序号（0/1/2），别名表优先于结构推断
MMD_HAND = {
    "左手首": "hand.L",
    "左親指0": "thumb_proximal.L",
    "左親指1": "thumb_intermediate.L",
    "左親指2": "thumb_distal.L",
    "左人指1": "index_proximal.L",
    "左人指2": "index_intermediate.L",
    "左人指3": "index_distal.L",
    "左中指1": "middle_proximal.L",
    "左中指2": "middle_intermediate.L",
    "左中指3": "middle_distal.L",
    "左薬指1": "ring_proximal.L",
    "左薬指2": "ring_intermediate.L",
    "左薬指3": "ring_distal.L",
    "左小指1": "little_proximal.L",
    "左小指2": "little_intermediate.L",
    "左小指3": "little_distal.L",
}
assert_mapping(list(MMD_HAND), MMD_HAND, "MMD 0-based thumb")

# VRoid/VRM：1 基序号
VROID_HAND = {
    "J_Bip_L_Hand": "hand.L",
    "J_Bip_L_Thumb1": "thumb_proximal.L",
    "J_Bip_L_Thumb2": "thumb_intermediate.L",
    "J_Bip_L_Thumb3": "thumb_distal.L",
    "J_Bip_L_Index1": "index_proximal.L",
    "J_Bip_L_Index2": "index_intermediate.L",
    "J_Bip_L_Index3": "index_distal.L",
    "J_Bip_L_Middle1": "middle_proximal.L",
    "J_Bip_L_Middle2": "middle_intermediate.L",
    "J_Bip_L_Middle3": "middle_distal.L",
    "J_Bip_L_Ring1": "ring_proximal.L",
    "J_Bip_L_Ring2": "ring_intermediate.L",
    "J_Bip_L_Ring3": "ring_distal.L",
    "J_Bip_L_Little1": "little_proximal.L",
    "J_Bip_L_Little2": "little_intermediate.L",
    "J_Bip_L_Little3": "little_distal.L",
}
assert_mapping(list(VROID_HAND), VROID_HAND, "VRoid 1-based")


# ---------------------------------------------------------------------------
# 5. 手指与 Toe_* 脚趾同名竞争（包含用户提供的整套骨骼及其顺序）
# ---------------------------------------------------------------------------
TOE_LAYOUT = """Hips
Spine
Chest
Neck
Head
Eye_L
Eye_R
Tongue.001
Tongue.002
Tongue.003
Tongue.004
Cheek1_L
Cheek2_L
Cheek1_R
Cheek2_R
Left shoulder
Left arm
Left elbow
Left wrist
Thumb_Proximal_L
Thumb_Intermediate_L
Thumb_Distal_L
Index_Proximal_L
Index_Intermediate_L
Index_Distal_L
Middle_Proximal_L
Middle_Intermediate_L
Middle_Distal_L
Ring_Proximal_L
Ring_Intermediate_L
Ring_Distal_L
Little_Proximal_L
Little_Intermediate_L
Little_Distal_L
Twist wrist_L
Twist elbow_L
Right shoulder
Right arm
Right elbow
Right wrist
Middle_Proximal_R
Middle_Intermediate_R
Middle_Distal_R
Ring_Proximal_R
Ring_Intermediate_R
Ring_Distal_R
Little_Proximal_R
Little_Intermediate_R
Little_Distal_R
Thumb_Proximal_R
Thumb_Intermediate_R
Thumb_Distal_R
Index_Proximal_R
Index_Intermediate_R
Index_Distal_R
Twist wrist_R
Bracelet.000
Bracelet.001
Bracelet.002
Twist elbow_R
breast_L
breast_L.001
breast_L.002
breast_R
breast_R.001
breast_R.002
Left leg
Left knee
Left ankle
Left Toe
Toe_Thumb_Proximal_L
Toe_Thumb_Intermediate_L
Toe_Thumb_Distal_L
Toe_Index_Proximal_L
Toe_Index_Intermediate_L
Toe_Index_Distal_L
Toe_Middle_Proximal_L
Toe_Middle_Intermediate_L
Toe_Middle_Distal_L
Toe_Ring_Proximal_L
Toe_Ring_Intermediate_L
Toe_Ring_Distal_L
Toe_Little_Proximal_L
Toe_Little_Intermediate_L
Toe_Little_Distal_L
Right leg
Right knee
Right ankle
Right Toe
Toe_Thumb_Proximal_R
Toe_Thumb_Intermediate_R
Toe_Thumb_Distal_R
Toe_Index_Proximal_R
Toe_Index_Intermediate_R
Toe_Index_Distal_R
Toe_Middle_Proximal_R
Toe_Middle_Intermediate_R
Toe_Middle_Distal_R
Toe_Ring_Proximal_R
Toe_Ring_Intermediate_R
Toe_Ring_Distal_R
Toe_Little_Proximal_R
Toe_Little_Intermediate_R
Toe_Little_Distal_R
Hips_L
Hips_L.001
Hips_R
Hips_R.001""".splitlines()

TOE_LAYOUT_EXPECTED = {
    name: target for name, target in LAYOUT_EXPECTED.items()
    if not any(name.startswith(label) for label in FINGER_LABELS)
    and not name.endswith((" Wrist", " toe"))
}
TOE_LAYOUT_EXPECTED.update({"Eye_L": "eye.L", "Eye_R": "eye.R"})
NAMED_HAND = {
    f"{family.title()}_{segment.title()}_{side}": f"{family}_{segment}.{side}"
    for side in ("L", "R")
    for family in FINGER_LABELS.values()
    for segment in FINGER_SEGMENTS.values()
}
TOE_LAYOUT_EXPECTED.update(NAMED_HAND)
for _side, _side_word in (("L", "Left"), ("R", "Right")):
    TOE_LAYOUT_EXPECTED[f"{_side_word} wrist"] = f"hand.{_side}"
    TOE_LAYOUT_EXPECTED[f"{_side_word} Toe"] = f"toes.{_side}"

_mapping = mapping_for(TOE_LAYOUT)
assert _mapping == TOE_LAYOUT_EXPECTED, _mapping
assert_mapping(
    list(reversed(TOE_LAYOUT)),
    {**NAMED_HAND, "Left Toe": "toes.L", "Right Toe": "toes.R"},
    "reversed toe layout fingers and toes",
)

# 缺少真正手指时，脚趾仍不能通过模糊匹配补入手指目标。
TOE_NAMES = [f"Toe_{name}" for name in NAMED_HAND]
TOE_VARIANTS = [
    "toe_thumb_proximal_l", "TOE_INDEX_INTERMEDIATE_R", "ToeMiddleDistal_L",
    "Ring_Proximal_Toe_L", "LittleToeDistal_R", "toethumbproximal_L",
    "ThumbToe1_L.001", "PinkyToe2_R",
]
for _name in TOE_NAMES + TOE_VARIANTS:
    assert _finger_key(_name) is None, _name
    _mapping = mapping_for([_name])
    assert not any(target in NAMED_HAND.values() for target in _mapping.values()), (_name, _mapping)

for _names in (TOE_NAMES, TOE_NAMES + list(NAMED_HAND)):
    _mapping = mapping_for(_names)
    assert not any(_name in _mapping and _mapping[_name] in NAMED_HAND.values() for _name in TOE_NAMES), _mapping
    if len(_names) > len(TOE_NAMES):
        assert_mapping(_names, NAMED_HAND, "toes before real fingers")

print("HUMANOID_AUTO_MAPPING_UNIT_OK")
