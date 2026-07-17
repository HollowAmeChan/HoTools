"""MC2 的纯参数规格与 Unity ClothParameters 归一化边界。

本模块不接触 bpy、PhysicsWorld slot、旧 MC2 runtime 或写回设施。粒子节点产生
``MC2ParticleProfileSpec``；模拟步在被懒求值时规范化 ``MC2SolverSettingsSpec``；
Tier A effective parameter oracle只组合profile与setup。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math

from .names import (
    MC2_SETUP_BONE_CLOTH,
    MC2_SETUP_BONE_SPRING,
    MC2_SETUP_MESH_CLOTH,
    MC2_SETUP_TYPES,
)
from .scheduler import (
    MC2_DEFAULT_MAX_SIMULATION_COUNT_PER_FRAME,
    MC2_DEFAULT_SIMULATION_FREQUENCY,
    MC2_MAX_SIMULATION_COUNT_PER_FRAME,
    MC2_MAX_SIMULATION_FREQUENCY,
    MC2_MIN_SIMULATION_COUNT_PER_FRAME,
    MC2_MIN_SIMULATION_FREQUENCY,
)


# MagicaCloth2/Runtime/Define/SystemDefine.cs
MC2_TETHER_STRETCH_LIMIT = 0.03
MC2_DISTANCE_VELOCITY_ATTENUATION = 0.3
MC2_SELF_COLLISION_RADIUS_RATIO = 0.25
MC2_BONE_SPRING_DISTANCE_STIFFNESS = 0.5
MC2_BONE_SPRING_TETHER_COMPRESSION = 0.8
MC2_BONE_SPRING_COLLISION_FRICTION = 0.5


def _number(value: object, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} 必须是有限数值") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} 必须是有限数值")
    return result


def _clamp(value: object, name: str, minimum: float, maximum: float) -> float:
    return min(max(_number(value, name), minimum), maximum)


def _non_negative(value: object, name: str) -> float:
    return max(_number(value, name), 0.0)


def _vector3(value: object, name: str) -> tuple[float, float, float]:
    if all(hasattr(value, axis) for axis in ("x", "y", "z")):
        values = (getattr(value, "x"), getattr(value, "y"), getattr(value, "z"))
    else:
        try:
            values = tuple(value)  # type: ignore[arg-type]
        except TypeError as exc:
            raise TypeError(f"{name} 必须是三维向量") from exc
    if len(values) != 3:
        raise ValueError(f"{name} 必须是三维向量")
    xyz = tuple(_number(component, name) for component in values)
    length = math.sqrt(sum(component * component for component in xyz))
    if length <= 1.0e-8:
        return (0.0, 0.0, 0.0)
    return tuple(component / length for component in xyz)


def _freeze(value: object):
    """把曲线 payload 冻结为确定性的 JSON 子集，保留点、切线和 handle。"""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("MC2 曲线不能包含 NaN/Inf")
        return value
    if isinstance(value, dict):
        return tuple((str(key), _freeze(item)) for key, item in sorted(value.items(), key=lambda pair: str(pair[0])))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    raise TypeError(f"MC2 曲线包含不可序列化值: {type(value).__name__}")


def thaw_mc2_value(value):
    if isinstance(value, tuple):
        if all(isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str) for item in value):
            return {key: thaw_mc2_value(item) for key, item in value}
        return [thaw_mc2_value(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _signature(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MC2CurveSpec:
    """Unity ``CurveSerializeData`` 的不可变等价物。

    ``value`` 是基础值；``curve_payload`` 是 0..1 depth multiplier 曲线快照。
    """

    value: float
    curve_payload: tuple | None = None

    def __post_init__(self) -> None:
        _number(self.value, "curve.value")
        if self.curve_payload is not None and not isinstance(self.curve_payload, tuple):
            raise TypeError("curve_payload 必须是已冻结的 tuple")

    @property
    def use_curve(self) -> bool:
        return self.curve_payload is not None

    @property
    def signature(self) -> str:
        return _signature(self.debug_dict())

    def debug_dict(self) -> dict:
        return {
            "value": self.value,
            "use_curve": self.use_curve,
            "curve": thaw_mc2_value(self.curve_payload),
        }


def make_mc2_curve_spec(
    value: object,
    curve=None,
    *,
    minimum: float,
    maximum: float,
    name: str,
) -> MC2CurveSpec:
    base_value = _clamp(value, name, minimum, maximum)
    if isinstance(curve, MC2CurveSpec):
        return MC2CurveSpec(base_value, curve.curve_payload)
    if curve is None:
        return MC2CurveSpec(base_value)
    if not isinstance(curve, dict):
        raise TypeError(f"{name} 曲线必须是 float_curve payload")
    kind = str(curve.get("kind") or "").strip().lower()
    if kind and kind != "float_curve":
        raise ValueError(f"{name} 只接受 float_curve，得到 {kind!r}")
    return MC2CurveSpec(base_value, _freeze(curve))


def _default_curve(value: float) -> MC2CurveSpec:
    return MC2CurveSpec(value)


@dataclass(frozen=True)
class MC2ParticleProfileSpec:
    """三种 setup 共用的 MC2 粒子/约束模型。"""

    blend_weight: float = 1.0
    gravity: float = 5.0
    gravity_direction: tuple[float, float, float] = (0.0, 0.0, -1.0)
    gravity_falloff: float = 0.0
    stabilization_time_after_reset: float = 0.1
    normal_axis: int = 1
    animation_pose_ratio: float = 0.0
    distance_culling_enabled: bool = False
    distance_culling_length: float = 30.0
    distance_culling_fade_ratio: float = 0.2
    anchor_inertia: float = 0.0
    world_inertia: float = 1.0
    movement_inertia_smoothing: float = 0.4
    movement_speed_limit: float = 5.0
    rotation_speed_limit: float = 720.0
    local_inertia: float = 1.0
    local_movement_speed_limit: float = -1.0
    local_rotation_speed_limit: float = -1.0
    depth_inertia: float = 0.0
    centrifugal_acceleration: float = 0.0
    particle_speed_limit: float = 4.0
    teleport_mode: int = 0
    teleport_distance: float = 0.5
    teleport_rotation: float = 90.0
    damping: MC2CurveSpec = field(default_factory=lambda: _default_curve(0.05))
    radius: MC2CurveSpec = field(default_factory=lambda: _default_curve(0.02))
    tether_compression: float = 0.4
    distance_stiffness: MC2CurveSpec = field(default_factory=lambda: _default_curve(1.0))
    bending_stiffness: float = 1.0
    angle_restoration_enabled: bool = True
    angle_restoration_stiffness: MC2CurveSpec = field(default_factory=lambda: _default_curve(0.2))
    angle_restoration_velocity_attenuation: float = 0.8
    angle_restoration_gravity_falloff: float = 0.0
    angle_limit_enabled: bool = False
    angle_limit: MC2CurveSpec = field(default_factory=lambda: _default_curve(60.0))
    angle_limit_stiffness: float = 1.0
    max_distance_enabled: bool = False
    max_distance: MC2CurveSpec = field(default_factory=lambda: _default_curve(0.3))
    backstop_enabled: bool = False
    backstop_radius: float = 10.0
    backstop_distance: MC2CurveSpec = field(default_factory=lambda: _default_curve(0.0))
    motion_stiffness: float = 1.0
    collision_mode: int = 1
    collision_friction: float = 0.05
    collision_limit_distance: MC2CurveSpec = field(default_factory=lambda: _default_curve(0.05))
    self_collision_mode: int = 0
    self_collision_sync_mode: int = 0
    self_collision_thickness: MC2CurveSpec = field(default_factory=lambda: _default_curve(0.005))
    cloth_mass: float = 0.0
    spring_enabled: bool = True
    spring_power: float = 0.04
    spring_limit_distance: float = 0.1
    spring_normal_limit_ratio: float = 1.0
    spring_noise: float = 0.0
    wind_influence: float = 1.0
    wind_frequency: float = 1.0
    wind_turbulence: float = 1.0
    wind_blend: float = 0.7
    wind_synchronization: float = 0.7
    wind_depth_weight: float = 0.0
    moving_wind: float = 0.0

    def __post_init__(self) -> None:
        curve_fields = (
            "damping", "radius", "distance_stiffness", "angle_restoration_stiffness",
            "angle_limit", "max_distance", "backstop_distance", "collision_limit_distance",
            "self_collision_thickness",
        )
        for name in curve_fields:
            if not isinstance(getattr(self, name), MC2CurveSpec):
                raise TypeError(f"{name} 必须是 MC2CurveSpec")
        if self.collision_mode not in (0, 1, 2):
            raise ValueError("collision_mode 必须是 0、1 或 2")
        if self.self_collision_mode not in (0, 2):
            raise ValueError("self_collision_mode 必须是 0 或 2")
        if self.self_collision_sync_mode not in (0, 2):
            raise ValueError("self_collision_sync_mode 必须是 0 或 2")
        if self.normal_axis not in range(6):
            raise ValueError("normal_axis 必须位于 0..5")
        if self.teleport_mode not in (0, 1, 2):
            raise ValueError("teleport_mode 必须是 0、1 或 2")

    @property
    def signature(self) -> str:
        return _signature(self.debug_dict())

    def debug_dict(self) -> dict:
        result = {}
        for key, value in self.__dict__.items():
            result[key] = value.debug_dict() if isinstance(value, MC2CurveSpec) else value
        return result


def make_mc2_particle_profile(
    *,
    blend_weight=1.0,
    gravity=5.0,
    gravity_direction=(0.0, 0.0, -1.0),
    gravity_falloff=0.0,
    stabilization_time_after_reset=0.1,
    normal_axis=1,
    animation_pose_ratio=0.0,
    distance_culling_enabled=False,
    distance_culling_length=30.0,
    distance_culling_fade_ratio=0.2,
    anchor_inertia=0.0,
    world_inertia=1.0,
    movement_inertia_smoothing=0.4,
    movement_speed_limit=5.0,
    rotation_speed_limit=720.0,
    local_inertia=1.0,
    local_movement_speed_limit=-1.0,
    local_rotation_speed_limit=-1.0,
    depth_inertia=0.0,
    centrifugal_acceleration=0.0,
    particle_speed_limit=4.0,
    teleport_mode=0,
    teleport_distance=0.5,
    teleport_rotation=90.0,
    damping=0.05,
    damping_curve=None,
    radius=0.02,
    radius_curve=None,
    tether_compression=0.4,
    distance_stiffness=1.0,
    distance_stiffness_curve=None,
    bending_stiffness=1.0,
    angle_restoration_enabled=True,
    angle_restoration_stiffness=0.2,
    angle_restoration_curve=None,
    angle_restoration_velocity_attenuation=0.8,
    angle_restoration_gravity_falloff=0.0,
    angle_limit_enabled=False,
    angle_limit=60.0,
    angle_limit_curve=None,
    angle_limit_stiffness=1.0,
    max_distance_enabled=False,
    max_distance=0.3,
    max_distance_curve=None,
    backstop_enabled=False,
    backstop_radius=10.0,
    backstop_distance=0.0,
    backstop_distance_curve=None,
    motion_stiffness=1.0,
    collision_mode=1,
    collision_friction=0.05,
    collision_limit_distance=0.05,
    collision_limit_curve=None,
    self_collision_mode=0,
    self_collision_sync_mode=0,
    self_collision_thickness=0.005,
    self_collision_curve=None,
    cloth_mass=0.0,
    spring_enabled=True,
    spring_power=0.04,
    spring_limit_distance=0.1,
    spring_normal_limit_ratio=1.0,
    spring_noise=0.0,
    wind_influence=1.0,
    wind_frequency=1.0,
    wind_turbulence=1.0,
    wind_blend=0.7,
    wind_synchronization=0.7,
    wind_depth_weight=0.0,
    moving_wind=0.0,
) -> MC2ParticleProfileSpec:
    normal_axis = int(normal_axis)
    teleport_mode = int(teleport_mode)
    if normal_axis not in range(6):
        raise ValueError("normal_axis 必须位于 0..5")
    if teleport_mode not in (0, 1, 2):
        raise ValueError("teleport_mode 必须是 0(None)、1(Reset) 或 2(Keep)")
    collision_mode = int(collision_mode)
    if collision_mode not in (0, 1, 2):
        raise ValueError("collision_mode 必须是 0(None)、1(Point) 或 2(Edge)")
    self_collision_mode = int(self_collision_mode)
    if self_collision_mode not in (0, 2):
        raise ValueError("self_collision_mode 必须是 0(None) 或 2(FullMesh)")
    self_collision_sync_mode = int(self_collision_sync_mode)
    if self_collision_sync_mode not in (0, 2):
        raise ValueError("self_collision_sync_mode 必须是 0(None) 或 2(FullMesh)")
    return MC2ParticleProfileSpec(
        blend_weight=_clamp(blend_weight, "blend_weight", 0.0, 1.0),
        gravity=_clamp(gravity, "gravity", 0.0, 20.0),
        gravity_direction=_vector3(gravity_direction, "gravity_direction"),
        gravity_falloff=_clamp(gravity_falloff, "gravity_falloff", 0.0, 1.0),
        stabilization_time_after_reset=_clamp(stabilization_time_after_reset, "stabilization_time_after_reset", 0.0, 1.0),
        normal_axis=normal_axis,
        animation_pose_ratio=_clamp(animation_pose_ratio, "animation_pose_ratio", 0.0, 1.0),
        distance_culling_enabled=bool(distance_culling_enabled),
        distance_culling_length=_non_negative(distance_culling_length, "distance_culling_length"),
        distance_culling_fade_ratio=_clamp(distance_culling_fade_ratio, "distance_culling_fade_ratio", 0.0, 1.0),
        anchor_inertia=_clamp(anchor_inertia, "anchor_inertia", 0.0, 1.0),
        world_inertia=_clamp(world_inertia, "world_inertia", 0.0, 1.0),
        movement_inertia_smoothing=_clamp(movement_inertia_smoothing, "movement_inertia_smoothing", 0.0, 1.0),
        movement_speed_limit=_speed_limit(movement_speed_limit, "movement_speed_limit", 10.0),
        rotation_speed_limit=_speed_limit(rotation_speed_limit, "rotation_speed_limit", 1440.0),
        local_inertia=_clamp(local_inertia, "local_inertia", 0.0, 1.0),
        local_movement_speed_limit=_speed_limit(local_movement_speed_limit, "local_movement_speed_limit", 10.0),
        local_rotation_speed_limit=_speed_limit(local_rotation_speed_limit, "local_rotation_speed_limit", 1440.0),
        depth_inertia=_clamp(depth_inertia, "depth_inertia", 0.0, 1.0),
        centrifugal_acceleration=_clamp(centrifugal_acceleration, "centrifugal_acceleration", 0.0, 1.0),
        particle_speed_limit=_speed_limit(particle_speed_limit, "particle_speed_limit", 10.0),
        teleport_mode=teleport_mode,
        teleport_distance=_non_negative(teleport_distance, "teleport_distance"),
        teleport_rotation=_non_negative(teleport_rotation, "teleport_rotation"),
        damping=make_mc2_curve_spec(damping, damping_curve, minimum=0.0, maximum=1.0, name="damping"),
        radius=make_mc2_curve_spec(radius, radius_curve, minimum=0.001, maximum=1.0, name="radius"),
        tether_compression=_clamp(tether_compression, "tether_compression", 0.0, 1.0),
        distance_stiffness=make_mc2_curve_spec(distance_stiffness, distance_stiffness_curve, minimum=0.0, maximum=1.0, name="distance_stiffness"),
        bending_stiffness=_clamp(bending_stiffness, "bending_stiffness", 0.0, 1.0),
        angle_restoration_enabled=bool(angle_restoration_enabled),
        angle_restoration_stiffness=make_mc2_curve_spec(angle_restoration_stiffness, angle_restoration_curve, minimum=0.0, maximum=1.0, name="angle_restoration_stiffness"),
        angle_restoration_velocity_attenuation=_clamp(angle_restoration_velocity_attenuation, "angle_restoration_velocity_attenuation", 0.0, 1.0),
        angle_restoration_gravity_falloff=_clamp(angle_restoration_gravity_falloff, "angle_restoration_gravity_falloff", 0.0, 1.0),
        angle_limit_enabled=bool(angle_limit_enabled),
        angle_limit=make_mc2_curve_spec(angle_limit, angle_limit_curve, minimum=0.0, maximum=180.0, name="angle_limit"),
        angle_limit_stiffness=_clamp(angle_limit_stiffness, "angle_limit_stiffness", 0.0, 1.0),
        max_distance_enabled=bool(max_distance_enabled),
        max_distance=make_mc2_curve_spec(max_distance, max_distance_curve, minimum=0.0, maximum=5.0, name="max_distance"),
        backstop_enabled=bool(backstop_enabled),
        backstop_radius=_clamp(backstop_radius, "backstop_radius", 0.0, 10.0),
        backstop_distance=make_mc2_curve_spec(backstop_distance, backstop_distance_curve, minimum=0.0, maximum=1.0, name="backstop_distance"),
        motion_stiffness=_clamp(motion_stiffness, "motion_stiffness", 0.0, 1.0),
        collision_mode=collision_mode,
        collision_friction=_clamp(collision_friction, "collision_friction", 0.0, 0.5),
        collision_limit_distance=make_mc2_curve_spec(collision_limit_distance, collision_limit_curve, minimum=0.0, maximum=1.0, name="collision_limit_distance"),
        self_collision_mode=self_collision_mode,
        self_collision_sync_mode=self_collision_sync_mode,
        self_collision_thickness=make_mc2_curve_spec(self_collision_thickness, self_collision_curve, minimum=0.001, maximum=0.05, name="self_collision_thickness"),
        cloth_mass=_clamp(cloth_mass, "cloth_mass", 0.0, 1.0),
        spring_enabled=bool(spring_enabled),
        spring_power=_clamp(spring_power, "spring_power", 0.001, 1.0),
        spring_limit_distance=_non_negative(spring_limit_distance, "spring_limit_distance"),
        spring_normal_limit_ratio=_clamp(spring_normal_limit_ratio, "spring_normal_limit_ratio", 0.0, 1.0),
        spring_noise=_clamp(spring_noise, "spring_noise", 0.0, 1.0),
        wind_influence=_clamp(wind_influence, "wind_influence", 0.0, 2.0),
        wind_frequency=_clamp(wind_frequency, "wind_frequency", 0.0, 2.0),
        wind_turbulence=_clamp(wind_turbulence, "wind_turbulence", 0.0, 2.0),
        wind_blend=_clamp(wind_blend, "wind_blend", 0.0, 1.0),
        wind_synchronization=_clamp(wind_synchronization, "wind_synchronization", 0.0, 1.0),
        wind_depth_weight=_clamp(wind_depth_weight, "wind_depth_weight", 0.0, 1.0),
        moving_wind=_clamp(moving_wind, "moving_wind", 0.0, 10.0),
    )


@dataclass(frozen=True)
class MC2SolverSettingsSpec:
    """一次 MC2 step 共享的源码调度；物理参数全部留在 per-task profile。"""

    time_scale: float = 1.0
    simulation_frequency: int = MC2_DEFAULT_SIMULATION_FREQUENCY
    max_simulation_count_per_frame: int = (
        MC2_DEFAULT_MAX_SIMULATION_COUNT_PER_FRAME
    )

    def __post_init__(self) -> None:
        if (
            isinstance(self.time_scale, bool)
            or not math.isfinite(float(self.time_scale))
            or not 0.0 <= float(self.time_scale) <= 1.0
        ):
            raise ValueError("time_scale must be finite and in 0..1")
        if (
            isinstance(self.simulation_frequency, bool)
            or int(self.simulation_frequency) != self.simulation_frequency
        ):
            raise ValueError("simulation_frequency must be an integer")
        if (
            isinstance(self.max_simulation_count_per_frame, bool)
            or int(self.max_simulation_count_per_frame)
            != self.max_simulation_count_per_frame
        ):
            raise ValueError("max_simulation_count_per_frame must be an integer")
        if not (
            MC2_MIN_SIMULATION_FREQUENCY
            <= self.simulation_frequency
            <= MC2_MAX_SIMULATION_FREQUENCY
        ):
            raise ValueError("simulation_frequency must be in 30..150")
        if not (
            MC2_MIN_SIMULATION_COUNT_PER_FRAME
            <= self.max_simulation_count_per_frame
            <= MC2_MAX_SIMULATION_COUNT_PER_FRAME
        ):
            raise ValueError("max_simulation_count_per_frame must be in 1..5")

    @property
    def signature(self) -> str:
        return _signature(self.debug_dict())

    def debug_dict(self) -> dict:
        return dict(self.__dict__)


def _speed_limit(value: object, name: str, maximum: float) -> float:
    number = _number(value, name)
    return -1.0 if number < 0.0 else min(number, maximum)


def make_mc2_solver_settings(
    *,
    time_scale=1.0,
    simulation_frequency=MC2_DEFAULT_SIMULATION_FREQUENCY,
    max_simulation_count_per_frame=MC2_DEFAULT_MAX_SIMULATION_COUNT_PER_FRAME,
) -> MC2SolverSettingsSpec:
    if (
        isinstance(simulation_frequency, bool)
        or int(simulation_frequency) != simulation_frequency
    ):
        raise ValueError("simulation_frequency must be an integer")
    if (
        isinstance(max_simulation_count_per_frame, bool)
        or int(max_simulation_count_per_frame)
        != max_simulation_count_per_frame
    ):
        raise ValueError("max_simulation_count_per_frame must be an integer")
    simulation_frequency = int(simulation_frequency)
    max_simulation_count_per_frame = int(max_simulation_count_per_frame)
    if not (
        MC2_MIN_SIMULATION_FREQUENCY
        <= simulation_frequency
        <= MC2_MAX_SIMULATION_FREQUENCY
    ):
        raise ValueError("simulation_frequency must be in 30..150")
    if not (
        MC2_MIN_SIMULATION_COUNT_PER_FRAME
        <= max_simulation_count_per_frame
        <= MC2_MAX_SIMULATION_COUNT_PER_FRAME
    ):
        raise ValueError("max_simulation_count_per_frame must be in 1..5")
    return MC2SolverSettingsSpec(
        time_scale=_clamp(time_scale, "time_scale", 0.0, 1.0),
        simulation_frequency=simulation_frequency,
        max_simulation_count_per_frame=max_simulation_count_per_frame,
    )


@dataclass(frozen=True)
class MC2SetupOptionsSpec:
    """只描述 setup/topology 与骨骼写回差异。"""

    setup_type: str
    connection_mode: int = 0
    connection_model: str = "mc2_source"
    self_collision_radius_model: str = "source_separate"
    rotational_interpolation: float = 0.5
    root_rotation: float = 0.5
    collided_by_groups: int = 0

    def __post_init__(self) -> None:
        if self.setup_type not in MC2_SETUP_TYPES:
            raise ValueError(f"未知 MC2 setup_type: {self.setup_type!r}")
        if self.connection_model not in ("mc2_source", "hotools_product"):
            raise ValueError("connection_model 必须是 mc2_source 或 hotools_product")
        if self.self_collision_radius_model not in ("source_separate", "derived_radius"):
            raise ValueError(
                "self_collision_radius_model 必须是 source_separate 或 derived_radius"
            )
        if (
            self.self_collision_radius_model == "derived_radius"
            and self.setup_type != MC2_SETUP_MESH_CLOTH
        ):
            raise ValueError("derived_radius self collision model is MeshCloth-only")
        allowed_modes = (0, 1, 2) if self.connection_model == "hotools_product" else (0, 1, 2, 3)
        if self.connection_mode not in allowed_modes:
            raise ValueError(f"connection_mode 必须位于 {allowed_modes}")
        if self.setup_type in (MC2_SETUP_MESH_CLOTH, MC2_SETUP_BONE_SPRING) and self.connection_mode != 0:
            raise ValueError("MeshCloth/BoneSpring connection_mode 必须是 Line(0)")
        if self.collided_by_groups < 0 or self.collided_by_groups > 0xFFFF:
            raise ValueError("collided_by_groups 必须位于 0..65535")

    @property
    def signature(self) -> str:
        return _signature(self.debug_dict())

    def debug_dict(self) -> dict:
        return dict(self.__dict__)


def make_mc2_setup_options(
    setup_type: object,
    *,
    connection_mode=0,
    connection_model="mc2_source",
    self_collision_radius_model="source_separate",
    rotational_interpolation=0.5,
    root_rotation=0.5,
    collided_by_groups=0,
) -> MC2SetupOptionsSpec:
    setup_type = str(setup_type or "").strip().lower()
    if setup_type not in MC2_SETUP_TYPES:
        raise ValueError(f"未知 MC2 setup_type: {setup_type!r}")
    connection_mode = int(connection_mode)
    connection_model = str(connection_model or "mc2_source").strip().lower()
    if connection_model not in ("mc2_source", "hotools_product"):
        raise ValueError("connection_model 必须是 mc2_source 或 hotools_product")
    allowed_modes = (0, 1, 2) if connection_model == "hotools_product" else (0, 1, 2, 3)
    if connection_mode not in allowed_modes:
        raise ValueError(f"connection_mode 必须位于 {allowed_modes}")
    self_collision_radius_model = str(
        self_collision_radius_model or "source_separate"
    ).strip().lower()
    if self_collision_radius_model not in ("source_separate", "derived_radius"):
        raise ValueError(
            "self_collision_radius_model 必须是 source_separate 或 derived_radius"
        )
    if self_collision_radius_model == "derived_radius" and setup_type != MC2_SETUP_MESH_CLOTH:
        raise ValueError("derived_radius self collision model is MeshCloth-only")
    if setup_type in (MC2_SETUP_MESH_CLOTH, MC2_SETUP_BONE_SPRING):
        # Unity MeshCloth 不消费该字段；BoneSpring 强制 Line。
        connection_mode = 0
        connection_model = "mc2_source"
    return MC2SetupOptionsSpec(
        setup_type=setup_type,
        connection_mode=connection_mode,
        connection_model=connection_model,
        self_collision_radius_model=self_collision_radius_model,
        rotational_interpolation=_clamp(rotational_interpolation, "rotational_interpolation", 0.0, 1.0),
        root_rotation=_clamp(root_rotation, "root_rotation", 0.0, 1.0),
        collided_by_groups=max(0, min(0xFFFF, int(collided_by_groups))),
    )


@dataclass(frozen=True)
class MC2EffectiveParametersSpec:
    """等价于 Unity ``GetClothParameters()`` 后的 solver 输入快照。"""

    setup_type: str
    profile_signature: str
    setup_options_signature: str
    payload: tuple
    parameter_signature: str

    def debug_dict(self) -> dict:
        return thaw_mc2_value(self.payload)


def make_mc2_effective_parameters(
    profile: MC2ParticleProfileSpec,
    setup_options: MC2SetupOptionsSpec,
) -> MC2EffectiveParametersSpec:
    if not isinstance(profile, MC2ParticleProfileSpec):
        raise TypeError("profile 必须是 MC2ParticleProfileSpec")
    if not isinstance(setup_options, MC2SetupOptionsSpec):
        raise TypeError("setup_options 必须是 MC2SetupOptionsSpec")
    setup_type = setup_options.setup_type
    is_spring = setup_type == MC2_SETUP_BONE_SPRING

    def curve(curve_spec: MC2CurveSpec, scale: float = 1.0) -> dict:
        result = curve_spec.debug_dict()
        result["value"] *= scale
        return result

    payload = {
        "setup_type": setup_type,
        "gravity": 0.0 if is_spring else profile.gravity,
        "gravity_direction": profile.gravity_direction,
        "gravity_falloff": profile.gravity_falloff,
        "stabilization_time_after_reset": profile.stabilization_time_after_reset,
        "blend_weight": profile.blend_weight,
        "culling": {
            "enabled": profile.distance_culling_enabled,
            "length": profile.distance_culling_length,
            "fade_ratio": profile.distance_culling_fade_ratio,
        },
        # Unity GetClothParameters(): damping and angle restoration power use 20%.
        "damping": curve(profile.damping, 0.2),
        "radius": curve(profile.radius),
        "normal_axis": profile.normal_axis,
        "animation_pose_ratio": profile.animation_pose_ratio,
        "rotational_interpolation": setup_options.rotational_interpolation,
        "root_rotation": setup_options.root_rotation,
        "inertia": {
            "anchor_inertia": profile.anchor_inertia,
            "world_inertia": profile.world_inertia,
            "movement_inertia_smoothing": profile.movement_inertia_smoothing,
            "movement_speed_limit": profile.movement_speed_limit,
            "rotation_speed_limit": profile.rotation_speed_limit,
            "local_inertia": profile.local_inertia,
            "local_movement_speed_limit": profile.local_movement_speed_limit,
            "local_rotation_speed_limit": profile.local_rotation_speed_limit,
            "depth_inertia": profile.depth_inertia,
            "centrifugal_acceleration": profile.centrifugal_acceleration,
            "particle_speed_limit": profile.particle_speed_limit,
            "teleport_mode": profile.teleport_mode,
            "teleport_distance": profile.teleport_distance,
            "teleport_rotation": profile.teleport_rotation,
        },
        "tether": {
            "compression_limit": MC2_BONE_SPRING_TETHER_COMPRESSION if is_spring else profile.tether_compression,
            "stretch_limit": MC2_TETHER_STRETCH_LIMIT,
        },
        "distance": {
            "stiffness": curve(MC2CurveSpec(MC2_BONE_SPRING_DISTANCE_STIFFNESS)) if is_spring else curve(profile.distance_stiffness),
            "velocity_attenuation": MC2_DISTANCE_VELOCITY_ATTENUATION,
        },
        "bending": {"stiffness": profile.bending_stiffness},
        "angle": {
            "restoration_enabled": profile.angle_restoration_enabled,
            "restoration_stiffness": curve(profile.angle_restoration_stiffness, 0.2),
            "restoration_velocity_attenuation": profile.angle_restoration_velocity_attenuation,
            "restoration_gravity_falloff": profile.angle_restoration_gravity_falloff,
            "limit_enabled": profile.angle_limit_enabled,
            "limit": curve(profile.angle_limit),
            "limit_stiffness": profile.angle_limit_stiffness,
        },
        "motion": {
            "max_distance_enabled": False if is_spring else profile.max_distance_enabled,
            "max_distance": curve(profile.max_distance),
            "backstop_enabled": False if is_spring else profile.backstop_enabled,
            "backstop_radius": profile.backstop_radius,
            "backstop_distance": curve(profile.backstop_distance),
            "stiffness": profile.motion_stiffness,
        },
        "collision": {
            "mode": 1 if is_spring else profile.collision_mode,
            "dynamic_friction": MC2_BONE_SPRING_COLLISION_FRICTION if is_spring else profile.collision_friction,
            "static_friction": MC2_BONE_SPRING_COLLISION_FRICTION if is_spring else profile.collision_friction,
            "limit_distance": curve(profile.collision_limit_distance) if is_spring else None,
        },
        "self_collision": {
            "mode": 0 if is_spring else profile.self_collision_mode,
            "sync_mode": 0 if is_spring else profile.self_collision_sync_mode,
            "thickness": curve(
                profile.radius,
                MC2_SELF_COLLISION_RADIUS_RATIO,
            ) if setup_options.self_collision_radius_model == "derived_radius" else curve(
                profile.self_collision_thickness
            ),
            "radius_model": setup_options.self_collision_radius_model,
            "cloth_mass": profile.cloth_mass,
        },
        "wind": {
            "influence": profile.wind_influence,
            "frequency": profile.wind_frequency,
            "turbulence": profile.wind_turbulence,
            "blend": profile.wind_blend,
            "synchronization": profile.wind_synchronization,
            "depth_weight": profile.wind_depth_weight,
            "moving_wind": profile.moving_wind,
        },
        "spring": {
            "power": profile.spring_power if is_spring and profile.spring_enabled else 0.0,
            "limit_distance": profile.spring_limit_distance,
            "normal_limit_ratio": profile.spring_normal_limit_ratio,
            "noise": profile.spring_noise,
        },
    }
    frozen = _freeze(payload)
    return MC2EffectiveParametersSpec(
        setup_type=setup_type,
        profile_signature=profile.signature,
        setup_options_signature=setup_options.signature,
        payload=frozen,
        parameter_signature=_signature(payload),
    )


__all__ = [
    "MC2CurveSpec",
    "MC2EffectiveParametersSpec",
    "MC2ParticleProfileSpec",
    "MC2SetupOptionsSpec",
    "MC2SolverSettingsSpec",
    "make_mc2_curve_spec",
    "make_mc2_effective_parameters",
    "make_mc2_particle_profile",
    "make_mc2_setup_options",
    "make_mc2_solver_settings",
    "thaw_mc2_value",
]
