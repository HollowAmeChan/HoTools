"""BoneCloth MC2 预设——直接从 MC2 官方 JSON 文件解析，不手写参数。

复用 physicsMC2MeshCloth/presets.py 的解析逻辑，通过 JSON 文件生成与
网格布料-MC2 完全一致的预设值（Skirt/SoftSkirt/LongHair/ShortHair/
FrontHair/Tail/Cape/Accessory/MiddleSpring/SoftSpring/HardSpring）。
"""

from __future__ import annotations

import json
import pathlib

from ..physicsMC2MeshCloth.constants import MC2SystemConstants

_PRESET_DIR = pathlib.Path(__file__).parent.parent / "mc2_presets"

_PRESET_FILES = (
    ("裙摆",        "MC2_Preset_Skirt.json"),
    ("软裙摆",      "MC2_Preset_SoftSkirt.json"),
    ("长发",        "MC2_Preset_LongHair.json"),
    ("短发",        "MC2_Preset_ShortHair.json"),
    ("刘海",        "MC2_Preset_FrontHair.json"),
    ("尾巴",        "MC2_Preset_Tail.json"),
    ("披肩",        "MC2_Preset_Cape.json"),
    ("配件",        "MC2_Preset_Accessory.json"),
    ("中弹簧",      "MC2_Preset_MiddleSpring.json"),
    ("软弹簧",      "MC2_Preset_SoftSpring.json"),
    ("硬弹簧",      "MC2_Preset_HardSpring.json"),
)


def _f(v, fb: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(fb)


def _i(v, fb: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(fb)


def _b(v, fb: bool = False) -> bool:
    if v is None:
        return bool(fb)
    return bool(v)


def _cv(data, fb: float = 0.0) -> float:
    """从 {value: X, useCurve: bool, curve: ...} 提取 scalar 值。"""
    if isinstance(data, dict):
        return _f(data.get("value"), fb)
    return _f(data, fb)


def _slider(data, fb: float) -> float:
    """use==false 时返回 -1（禁用哨兵值），对应 HoTools 的 -1 = 不限制。"""
    if not isinstance(data, dict):
        return _f(fb)
    if not _b(data.get("use"), True):
        return -1.0
    return _f(data.get("value"), fb)


def _convert_preset(label: str, source: dict) -> dict:
    """把 MC2 JSON 顶层 dict 转成 BoneCloth 节点的 preset values dict。"""
    inertia = source.get("inertiaConstraint", {})
    ar      = source.get("angleRestorationConstraint", {})
    dist    = source.get("distanceConstraint", {})
    bend    = source.get("triangleBendingConstraint", {})
    tether  = source.get("tetherConstraint", {})
    motion  = source.get("motionConstraint", {})
    collider = source.get("colliderCollisionConstraint", {})
    collider_mode = _i(collider.get("mode"), 0)

    return {
        "name": label,
        "values": {
            # ── 重力 ──────────────────────────────────────────────
            "gravity_power":  _f(source.get("gravity"), 9.8),
            "gravity_falloff": _f(source.get("gravityFalloff"), 0.0),
            # ── 基础 ──────────────────────────────────────────────
            "stablization_time_after_reset": _f(
                source.get("stablizationTimeAfterReset"), 0.1,
            ),
            "blend_weight": _f(source.get("blendWeight"), 1.0),
            "damping": _cv(source.get("damping"), 0.2),
            # ── Tether ────────────────────────────────────────────
            "use_tether": "tetherConstraint" in source,
            "tether_compression": _f(
                tether.get("distanceCompression"),
                MC2SystemConstants.TETHER_COMPRESSION_LIMIT,
            ),
            # ── Distance ──────────────────────────────────────────
            "use_distance": "distanceConstraint" in source,
            "distance_stiffness": _cv(dist.get("stiffness"), 1.0),
            # ── Bend ──────────────────────────────────────────────
            "use_bend": "triangleBendingConstraint" in source,
            "bend_stiffness": _f(bend.get("stiffness"), 0.5),
            # ── Angle restoration ─────────────────────────────────
            "use_angle_restoration": _b(ar.get("useAngleRestoration"), False),
            "angle_restoration_stiffness": _cv(ar.get("restorationStiffness"), 0.2),
            "angle_restoration_velocity_attenuation": _f(
                ar.get("velocityAttenuation"),
                MC2SystemConstants.ANGLE_RESTORATION_VELOCITY_ATTENUATION,
            ),
            "angle_restoration_gravity_falloff": _f(
                ar.get("gravityFalloff"),
                MC2SystemConstants.ANGLE_RESTORATION_GRAVITY_FALLOFF,
            ),
            # ── Angle limit ───────────────────────────────────────
            "use_angle_limit": _b(ar.get("useAngleLimit"), False),
            "angle_limit": _cv(ar.get("limitAngle"), 0.0),
            "angle_limit_stiffness": _f(ar.get("limitStiffness"), 1.0),
            # ── Inertia ───────────────────────────────────────────
            "anchor_inertia": _f(
                inertia.get("anchorInertia"),
                MC2SystemConstants.ANCHOR_INERTIA,
            ),
            "world_inertia": _f(
                inertia.get("worldInertia"),
                MC2SystemConstants.WORLD_INERTIA,
            ),
            "movement_inertia_smoothing": _f(
                inertia.get("movementInertiaSmoothing"),
                MC2SystemConstants.MOVEMENT_INERTIA_SMOOTHING,
            ),
            "local_inertia": _f(
                inertia.get("localInertia"),
                MC2SystemConstants.LOCAL_INERTIA,
            ),
            "depth_inertia": _f(
                inertia.get("depthInertia"),
                MC2SystemConstants.DEPTH_INERTIA,
            ),
            "centrifugal": _f(
                inertia.get("centrifualAcceleration"),
                MC2SystemConstants.CENTRIFUGAL_ACCELERATION,
            ),
            # ── Speed limits ──────────────────────────────────────
            "movement_speed_limit": _slider(
                inertia.get("movementSpeedLimit"),
                MC2SystemConstants.MOVEMENT_SPEED_LIMIT,
            ),
            "rotation_speed_limit": _slider(
                inertia.get("rotationSpeedLimit"),
                MC2SystemConstants.ROTATION_SPEED_LIMIT,
            ),
            "local_movement_speed_limit": _slider(
                inertia.get("localMovementSpeedLimit"),
                MC2SystemConstants.LOCAL_MOVEMENT_SPEED_LIMIT,
            ),
            "local_rotation_speed_limit": _slider(
                inertia.get("localRotationSpeedLimit"),
                MC2SystemConstants.LOCAL_ROTATION_SPEED_LIMIT,
            ),
            "particle_speed_limit": _slider(
                inertia.get("particleSpeedLimit"),
                MC2SystemConstants.PARTICLE_SPEED_LIMIT,
            ),
            # ── Teleport ──────────────────────────────────────────
            "teleport_mode": _i(inertia.get("teleportMode"), 0),
            "teleport_distance": _f(
                inertia.get("teleportDistance"),
                MC2SystemConstants.TELEPORT_DISTANCE,
            ),
            "teleport_rotation": _f(
                inertia.get("teleportRotation"),
                MC2SystemConstants.TELEPORT_ROTATION,
            ),
            # ── Animation ─────────────────────────────────────────
            "animation_pose_ratio": _f(
                source.get("animationPoseRatio", source.get("animationBlendRatio")),
                0.0,
            ),
            # ── Motion (max distance / backstop) ──────────────────
            "use_max_distance": _b(motion.get("useMaxDistance"), False),
            "max_distance": _cv(motion.get("maxDistance"), 0.0),
            "use_backstop": _b(motion.get("useBackstop"), False),
            "backstop_radius": _f(motion.get("backstopRadius"), 0.0),
            "backstop_distance": _cv(motion.get("backstopDistance"), 0.0),
            "motion_stiffness": _f(motion.get("stiffness"), 1.0),
            # ── 法线轴 ────────────────────────────────────────────
            "normal_axis": _i(source.get("normalAxis"), 1),
            # ── Collider ──────────────────────────────────────────
            "use_collider_collision": collider_mode != 0,
            "collider_collision_mode": collider_mode,
            "collider_friction": _f(collider.get("friction"), 0.05),
        },
    }


def _load_presets() -> list[dict]:
    presets = []
    for label, filename in _PRESET_FILES:
        path = _PRESET_DIR / filename
        if not path.exists():
            continue
        try:
            source = json.loads(path.read_text(encoding="utf-8"))
            presets.append(_convert_preset(label, source))
        except Exception:
            pass
    return presets


BONE_CLOTH_PRESETS: list[dict] = _load_presets()
