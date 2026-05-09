from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher


TARGET_LAYOUT = [
    ("root", None, None, "root"),
    ("hips", "root", None, "hips"),
    ("spine", "hips", None, "spine"),
    ("chest", "spine", None, "spine"),
    ("neck", "chest", None, "head"),
    ("head", "neck", None, "head"),
    ("eye.L", "head", "L", "eye"),
    ("eye.R", "head", "R", "eye"),
    ("shoulder.L", "chest", "L", "arm"),
    ("upper_arm.L", "shoulder.L", "L", "arm"),
    ("lower_arm.L", "upper_arm.L", "L", "arm"),
    ("hand.L", "lower_arm.L", "L", "hand"),
    ("thumb_proximal.L", "hand.L", "L", "finger"),
    ("thumb_intermediate.L", "thumb_proximal.L", "L", "finger"),
    ("thumb_distal.L", "thumb_intermediate.L", "L", "finger"),
    ("index_proximal.L", "hand.L", "L", "finger"),
    ("index_intermediate.L", "index_proximal.L", "L", "finger"),
    ("index_distal.L", "index_intermediate.L", "L", "finger"),
    ("middle_proximal.L", "hand.L", "L", "finger"),
    ("middle_intermediate.L", "middle_proximal.L", "L", "finger"),
    ("middle_distal.L", "middle_intermediate.L", "L", "finger"),
    ("ring_proximal.L", "hand.L", "L", "finger"),
    ("ring_intermediate.L", "ring_proximal.L", "L", "finger"),
    ("ring_distal.L", "ring_intermediate.L", "L", "finger"),
    ("little_proximal.L", "hand.L", "L", "finger"),
    ("little_intermediate.L", "little_proximal.L", "L", "finger"),
    ("little_distal.L", "little_intermediate.L", "L", "finger"),
    ("shoulder.R", "chest", "R", "arm"),
    ("upper_arm.R", "shoulder.R", "R", "arm"),
    ("lower_arm.R", "upper_arm.R", "R", "arm"),
    ("hand.R", "lower_arm.R", "R", "hand"),
    ("thumb_proximal.R", "hand.R", "R", "finger"),
    ("thumb_intermediate.R", "thumb_proximal.R", "R", "finger"),
    ("thumb_distal.R", "thumb_intermediate.R", "R", "finger"),
    ("index_proximal.R", "hand.R", "R", "finger"),
    ("index_intermediate.R", "index_proximal.R", "R", "finger"),
    ("index_distal.R", "index_intermediate.R", "R", "finger"),
    ("middle_proximal.R", "hand.R", "R", "finger"),
    ("middle_intermediate.R", "middle_proximal.R", "R", "finger"),
    ("middle_distal.R", "middle_intermediate.R", "R", "finger"),
    ("ring_proximal.R", "hand.R", "R", "finger"),
    ("ring_intermediate.R", "ring_proximal.R", "R", "finger"),
    ("ring_distal.R", "ring_intermediate.R", "R", "finger"),
    ("little_proximal.R", "hand.R", "R", "finger"),
    ("little_intermediate.R", "little_proximal.R", "R", "finger"),
    ("little_distal.R", "little_intermediate.R", "R", "finger"),
    ("upper_leg.L", "hips", "L", "leg"),
    ("lower_leg.L", "upper_leg.L", "L", "leg"),
    ("foot.L", "lower_leg.L", "L", "foot"),
    ("toes.L", "foot.L", "L", "foot"),
    ("upper_leg.R", "hips", "R", "leg"),
    ("lower_leg.R", "upper_leg.R", "R", "leg"),
    ("foot.R", "lower_leg.R", "R", "foot"),
    ("toes.R", "foot.R", "R", "foot"),
]


MANUAL_ALIASES = {
    "root": (
        "center", "centre", "master", "global", "origin", "allroot", "all_root",
        "root_ref", "root_ref.x",
        "センター", "全ての親",
    ),

    "hips": (
        "pelvis", "hip", "waist", "cog",
        "pelvis_ref", "pelvis_ref.x", "hips_ref", "hips_ref.x",
        "腰", "骨盤",
    ),

    "spine": (
        "abdomen", "torso", "spine1", "spine01",
        "spine_01_ref", "spine_01_ref.x",
        "上半身", "胴",
    ),

    "chest": (
        "ribcage", "upperchest", "spine2", "spine02",
        "spine_02_ref", "spine_02_ref.x",
        "上半身2", "胸",
    ),

    "neck": (
        "cervical",
        "neck_ref", "neck_ref.x",
        "首",
    ),

    "head": (
        "skull", "headtop",
        "head_ref", "head_ref.x",
        "頭",
    ),

    "eye.L": ("l_eye", "eye_l", "lefteye", "left_eye", "左目"),
    "eye.R": ("r_eye", "eye_r", "righteye", "right_eye", "右目"),

    "shoulder.L": (
        "clavicle", "collar", "sholder",
        "shoulder_ref.l",
        "左肩",
    ),
    "shoulder.R": (
        "clavicle", "collar", "sholder",
        "shoulder_ref.r",
        "右肩",
    ),

    "upper_arm.L": (
        "arm", "upperarm", "uparm",
        "arm_ref.l",
        "c_arm_twist_offset.l",
        "左腕", "腕",
    ),
    "upper_arm.R": (
        "arm", "upperarm", "uparm",
        "arm_ref.r",
        "c_arm_twist_offset.r",
        "右腕", "腕",
    ),

    "lower_arm.L": (
        "forearm", "elbow", "lowerarm",
        "forearm_ref.l",
        "forearm_stretch.l",
        "左ひじ", "ひじ",
    ),
    "lower_arm.R": (
        "forearm", "elbow", "lowerarm",
        "forearm_ref.r",
        "forearm_stretch.r",
        "右ひじ", "ひじ",
    ),

    "hand.L": (
        "wrist", "palm", "lefthand",
        "hand_ref.l",
        "左手首", "手首",
    ),
    "hand.R": (
        "wrist", "palm", "righthand",
        "hand_ref.r",
        "右手首", "手首",
    ),

    "thumb_proximal.L": (
        "thumb1", "thumb01", "thumba", "thumbproximal",
        "thumb1_ref.l",
        "左親指0", "親指0",
    ),
    "thumb_proximal.R": (
        "thumb1", "thumb01", "thumba", "thumbproximal",
        "thumb1_ref.r",
        "右親指0", "親指0",
    ),

    "thumb_intermediate.L": (
        "thumb2", "thumb02", "thumbb", "thumbintermediate",
        "thumb2_ref.l",
        "左親指1", "親指1",
    ),
    "thumb_intermediate.R": (
        "thumb2", "thumb02", "thumbb", "thumbintermediate",
        "thumb2_ref.r",
        "右親指1", "親指1",
    ),

    "thumb_distal.L": (
        "thumb3", "thumb03", "thumbc", "thumbdistal",
        "thumb3_ref.l",
        "左親指2", "親指2",
    ),
    "thumb_distal.R": (
        "thumb3", "thumb03", "thumbc", "thumbdistal",
        "thumb3_ref.r",
        "右親指2", "親指2",
    ),

    "index_proximal.L": (
        "index1", "index01", "indexfinger1", "forefinger1",
        "index1_ref.l",
        "左人指1", "人指1",
    ),
    "index_proximal.R": (
        "index1", "index01", "indexfinger1", "forefinger1",
        "index1_ref.r",
        "右人指1", "人指1",
    ),

    "index_intermediate.L": (
        "index2", "index02", "indexfinger2", "forefinger2",
        "index2_ref.l",
        "左人指2", "人指2",
    ),
    "index_intermediate.R": (
        "index2", "index02", "indexfinger2", "forefinger2",
        "index2_ref.r",
        "右人指2", "人指2",
    ),

    "index_distal.L": (
        "index3", "index03", "indexfinger3", "forefinger3",
        "index3_ref.l",
        "左人指3", "人指3",
    ),
    "index_distal.R": (
        "index3", "index03", "indexfinger3", "forefinger3",
        "index3_ref.r",
        "右人指3", "人指3",
    ),

    "middle_proximal.L": (
        "middle1", "middle01", "middlefinger1",
        "middle1_ref.l",
        "左中指1", "中指1",
    ),
    "middle_proximal.R": (
        "middle1", "middle01", "middlefinger1",
        "middle1_ref.r",
        "右中指1", "中指1",
    ),

    "middle_intermediate.L": (
        "middle2", "middle02", "middlefinger2",
        "middle2_ref.l",
        "左中指2", "中指2",
    ),
    "middle_intermediate.R": (
        "middle2", "middle02", "middlefinger2",
        "middle2_ref.r",
        "右中指2", "中指2",
    ),

    "middle_distal.L": (
        "middle3", "middle03", "middlefinger3",
        "middle3_ref.l",
        "左中指3", "中指3",
    ),
    "middle_distal.R": (
        "middle3", "middle03", "middlefinger3",
        "middle3_ref.r",
        "右中指3", "中指3",
    ),

    "ring_proximal.L": (
        "ring1", "ring01", "ringfinger1",
        "ring1_ref.l",
        "左薬指1", "薬指1",
    ),
    "ring_proximal.R": (
        "ring1", "ring01", "ringfinger1",
        "ring1_ref.r",
        "右薬指1", "薬指1",
    ),

    "ring_intermediate.L": (
        "ring2", "ring02", "ringfinger2",
        "ring2_ref.l",
        "左薬指2", "薬指2",
    ),
    "ring_intermediate.R": (
        "ring2", "ring02", "ringfinger2",
        "ring2_ref.r",
        "右薬指2", "薬指2",
    ),

    "ring_distal.L": (
        "ring3", "ring03", "ringfinger3",
        "ring3_ref.l",
        "左薬指3", "薬指3",
    ),
    "ring_distal.R": (
        "ring3", "ring03", "ringfinger3",
        "ring3_ref.r",
        "右薬指3", "薬指3",
    ),

    "little_proximal.L": (
        "little1", "little01", "pinky1", "pinkie1",
        "pinky1_ref.l",
        "左小指1", "小指1",
    ),
    "little_proximal.R": (
        "little1", "little01", "pinky1", "pinkie1",
        "pinky1_ref.r",
        "右小指1", "小指1",
    ),

    "little_intermediate.L": (
        "little2", "little02", "pinky2", "pinkie2",
        "pinky2_ref.l",
        "左小指2", "小指2",
    ),
    "little_intermediate.R": (
        "little2", "little02", "pinky2", "pinkie2",
        "pinky2_ref.r",
        "右小指2", "小指2",
    ),

    "little_distal.L": (
        "little3", "little03", "pinky3", "pinkie3",
        "pinky3_ref.l",
        "左小指3", "小指3",
    ),
    "little_distal.R": (
        "little3", "little03", "pinky3", "pinkie3",
        "pinky3_ref.r",
        "右小指3", "小指3",
    ),

    "upper_leg.L": (
        "thigh", "upleg", "leg",
        "thigh_ref.l",
        "左足", "足",
    ),
    "upper_leg.R": (
        "thigh", "upleg", "leg",
        "thigh_ref.r",
        "右足", "足",
    ),

    "lower_leg.L": (
        "calf", "shin", "knee", "lowerleg",
        "leg_ref.l",
        "左ひざ", "ひざ",
    ),
    "lower_leg.R": (
        "calf", "shin", "knee", "lowerleg",
        "leg_ref.r",
        "右ひざ", "ひざ",
    ),

    "foot.L": (
        "ankle", "leftfoot",
        "foot_ref.l",
        "左足首", "足首",
    ),
    "foot.R": (
        "ankle", "rightfoot",
        "foot_ref.r",
        "右足首", "足首",
    ),

    "toes.L": (
        "toe", "toebase", "ball",
        "toes_ref.l",
        "左足先", "足先", "足先ex",
    ),
    "toes.R": (
        "toe", "toebase", "ball",
        "toes_ref.r",
        "右足先", "足先", "足先ex",
    ),
}

HELPER_MARKERS = (
    "ik",
    "pole",
    "target",
    "ctrl",
    "controller",
    "socket",
    "weapon",
    "attach",
    "end",
    "nub",

    # ARP / foot helpers
    "bank",
    "heel",
    "roll",
    "pivot",
    "reverse",
)

@dataclass(frozen=True)
class HumanoidBoneSpec:
    name: str
    parent: str | None
    side: str | None
    group: str
    depth: int
    aliases: tuple[str, ...]


@dataclass
class SourceBoneInfo:
    name: str
    parent: str | None
    children: tuple[str, ...]
    side: str | None
    depth: int
    use_deform: bool
    x: float
    normalized: str
    normalized_core: str
    tokens: tuple[str, ...]


@dataclass
class MatchResult:
    target_name: str
    source_name: str
    score: float
    reason: str


@dataclass
class AutoMappingResult:
    matches: list[MatchResult]
    # 未匹配的源骨骼
    unmatched_sources: list[str]
    # 低置信度匹配
    low_confidence_matches: list[MatchResult]


def _compute_depth(target_name: str, parent_map: dict[str, str | None]) -> int:
    depth = 0
    current = parent_map.get(target_name)
    while current is not None:
        depth += 1
        current = parent_map.get(current)
    return depth


def _split_camel_case(text: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", text)
    return text


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = _split_camel_case(text)
    text = text.lower().strip()
    text = re.sub(r"[\-_/\\.:]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _detect_side(name: str, x_value: float = 0.0) -> str | None:
    normalized = _normalize_text(name)
    if "左" in name or re.search(r"(^| )left( |$)", normalized) or re.search(r"(^| )l( |$)", normalized):
        return "L"
    if "右" in name or re.search(r"(^| )right( |$)", normalized) or re.search(r"(^| )r( |$)", normalized):
        return "R"
    if x_value > 0.0001:
        return "L"
    if x_value < -0.0001:
        return "R"
    return None


def _strip_side_markers(name: str) -> str:
    text = _normalize_text(name)
    text = text.replace("左", " ").replace("右", " ")
    text = re.sub(r"(^| )left( |$)", " ", text)
    text = re.sub(r"(^| )right( |$)", " ", text)
    text = re.sub(r"(^| )l( |$)", " ", text)
    text = re.sub(r"(^| )r( |$)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokenize(name: str) -> tuple[str, ...]:
    core = _strip_side_markers(name)
    if not core:
        return ()
    return tuple(token for token in core.split(" ") if token)


def load_humanoid_specs() -> list[HumanoidBoneSpec]:
    parent_map = {name: parent for name, parent, _, _ in TARGET_LAYOUT}
    specs: list[HumanoidBoneSpec] = []

    for name, parent, side, group in TARGET_LAYOUT:
        aliases = {name}
        aliases.update(MANUAL_ALIASES.get(name, ()))
        aliases.add(name)
        specs.append(
            HumanoidBoneSpec(
                name=name,
                parent=parent,
                side=side,
                group=group,
                depth=_compute_depth(name, parent_map),
                aliases=tuple(sorted(aliases)),
            )
        )

    return specs


def _name_similarity_score(spec: HumanoidBoneSpec, bone: SourceBoneInfo) -> tuple[float, str]:
    best_score = 0.0
    best_reason = "name"
    bone_token_set = set(bone.tokens)

    for alias in spec.aliases:
        alias_core = _strip_side_markers(alias)
        alias_tokens = set(_tokenize(alias))
        if not alias_core:
            continue
        if alias_core == bone.normalized_core:
            return 100.0, f"exact:{alias}"

        sequence_ratio = SequenceMatcher(None, alias_core, bone.normalized_core).ratio()
        token_overlap = 0.0
        if alias_tokens and bone_token_set:
            token_overlap = len(alias_tokens & bone_token_set) / len(alias_tokens | bone_token_set)

        score = sequence_ratio * 55.0 + token_overlap * 35.0
        if alias_core in bone.normalized_core or bone.normalized_core in alias_core:
            score += 10.0

        if score > best_score:
            best_score = score
            best_reason = f"alias:{alias}"

    return best_score, best_reason


def _has_helper_marker(bone: SourceBoneInfo) -> bool:
    token_set = set(bone.tokens)
    return any(marker in token_set for marker in HELPER_MARKERS)


def _ancestor_distance(source_infos: dict[str, SourceBoneInfo], bone_name: str, ancestor_name: str, max_hops: int = 6) -> int | None:
    current_name = bone_name
    hops = 0
    while hops < max_hops:
        current = source_infos.get(current_name)
        if current is None or current.parent is None:
            return None
        hops += 1
        if current.parent == ancestor_name:
            return hops
        current_name = current.parent
    return None


def _topology_score(
    spec: HumanoidBoneSpec,
    bone: SourceBoneInfo,
    matched_sources: dict[str, str],
    source_infos: dict[str, SourceBoneInfo],
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if spec.side is not None:
        if bone.side == spec.side:
            score += 12.0
            reasons.append("side")
        elif bone.side is not None:
            score -= 18.0
            reasons.append("side-mismatch")

    if bone.use_deform:
        score += 4.0
    else:
        score -= 6.0
        reasons.append("non-deform")

    if _has_helper_marker(bone):
        score -= 22.0
        reasons.append("helper")

    score += max(0.0, 10.0 - abs(spec.depth - bone.depth) * 3.0)

    if spec.parent is None:
        if bone.parent is None:
            score += 8.0
            reasons.append("root-depth")
        return score, reasons

    parent_source = matched_sources.get(spec.parent)
    if not parent_source:
        return score, reasons

    distance = _ancestor_distance(source_infos, bone.name, parent_source)
    if distance == 1:
        score += 36.0
        reasons.append("parent")
    elif distance == 2:
        score += 26.0
        reasons.append("ancestor2")
    elif distance == 3:
        score += 18.0
        reasons.append("ancestor3")
    else:
        score -= 16.0
        reasons.append("branch")

    return score, reasons


def _score_candidate(
    spec: HumanoidBoneSpec,
    bone: SourceBoneInfo,
    matched_sources: dict[str, str],
    source_infos: dict[str, SourceBoneInfo],
) -> tuple[float, str]:
    if _has_helper_marker(bone):
        return -999.0, "helper-blocked"

    # 左右硬过滤，避免左右手互抢
    if spec.side is not None and bone.side is not None and spec.side != bone.side:
        return -999.0, "side-blocked"

    name_score, name_reason = _name_similarity_score(spec, bone)
    topology_bonus, topology_reasons = _topology_score(
        spec,
        bone,
        matched_sources,
        source_infos,
    )

    total = name_score + topology_bonus

    reasons = [name_reason]
    reasons.extend(topology_reasons)
    return total, ",".join(reasons)


def _acceptance_threshold(spec: HumanoidBoneSpec) -> float:
    if spec.group == "finger":
        return 48.0
    if spec.group in {"eye", "foot"}:
        return 45.0
    return 52.0


def auto_map_source_names_to_humanoid(source_names: list[str]) -> AutoMappingResult:
    """
    自动将给定的源骨骼名称列表映射到Humanoid标准骨骼名称。
    使用全局候选排序，避免左右手/手指一起选时互相抢target。
    """
    specs = load_humanoid_specs()

    source_infos: dict[str, SourceBoneInfo] = {}
    for index, source_name in enumerate(source_names):
        source_infos[source_name] = SourceBoneInfo(
            name=source_name,
            parent=None,
            children=(),
            side=_detect_side(source_name, 0.0),
            depth=index,
            use_deform=True,
            x=0.0,
            normalized=_normalize_text(source_name),
            normalized_core=_strip_side_markers(source_name),
            tokens=_tokenize(source_name),
        )

    # 先生成所有 source -> target 候选
    all_candidates: list[tuple[float, str, str, str]] = []
    # score, source_name, target_name, reason

    for source_name in source_names:
        bone_info = source_infos[source_name]

        for spec in specs:
            score, reason = _score_candidate(
                spec,
                bone_info,
                matched_sources={},
                source_infos=source_infos,
            )

            if score < _acceptance_threshold(spec):
                continue

            all_candidates.append(
                (score, source_name, spec.name, reason)
            )

    # 分数高的先占位，避免低分候选抢走正确target
    all_candidates.sort(key=lambda item: item[0], reverse=True)

    used_sources: set[str] = set()
    used_targets: set[str] = set()
    matches: list[MatchResult] = []

    for score, source_name, target_name, reason in all_candidates:
        if source_name in used_sources:
            continue

        if target_name in used_targets:
            continue

        used_sources.add(source_name)
        used_targets.add(target_name)

        matches.append(
            MatchResult(
                target_name=target_name,
                source_name=source_name,
                score=score,
                reason=reason,
            )
        )

    # 按原 source_names 顺序输出，方便UI和调试
    match_by_source = {
        match.source_name: match
        for match in matches
    }

    final_matches = [
        match_by_source[name]
        for name in source_names
        if name in match_by_source
    ]

    unmatched_sources = [
        name for name in source_names
        if name not in used_sources
    ]

    low_confidence_matches = [
        match for match in final_matches
        if match.score < 75.0
    ]

    return AutoMappingResult(
        matches=final_matches,
        unmatched_sources=unmatched_sources,
        low_confidence_matches=low_confidence_matches,
    )