from ..OmniNodeSocketMapping import _OmniCache
from ..FunctionNodeCore import omni
from . import _Color

import math
import bpy
import mathutils


def _require_object(obj, label: str) -> bpy.types.Object:
    if obj is None or not isinstance(obj, bpy.types.Object):
        raise ValueError(f"{label} is empty")
    return obj


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _vector3(value, fallback: mathutils.Vector) -> mathutils.Vector:
    if value is None or value == "":
        return fallback.copy()

    try:
        vec = mathutils.Vector(value)
    except Exception:
        return fallback.copy()

    if len(vec) == 0:
        return fallback.copy()
    if len(vec) == 1:
        return mathutils.Vector((vec[0], fallback[1], fallback[2]))
    if len(vec) == 2:
        return mathutils.Vector((vec[0], vec[1], fallback[2]))
    return vec.to_3d()


def _cache_vector(cache, key: str, fallback: mathutils.Vector) -> mathutils.Vector:
    if isinstance(cache, dict):
        return _vector3(cache.get(key), fallback)
    return fallback.copy()


def _cache_vector_any(cache, keys, fallback: mathutils.Vector) -> mathutils.Vector:
    if isinstance(cache, dict):
        for key in keys:
            if key in cache:
                return _vector3(cache.get(key), fallback)
    return fallback.copy()


def _cache_frame(cache):
    if not isinstance(cache, dict) or "frame" not in cache:
        return None

    try:
        return int(cache.get("frame"))
    except Exception:
        return None


def _euler_vector(euler) -> mathutils.Vector:
    return mathutils.Vector((euler.x, euler.y, euler.z))


def _quaternion_to_euler_vector(quat: mathutils.Quaternion) -> mathutils.Vector:
    return _euler_vector(quat.to_euler("XYZ"))


def _quaternion_from_value(value, fallback: mathutils.Quaternion) -> mathutils.Quaternion:
    if value is None or value == "":
        return fallback.copy()

    if isinstance(value, mathutils.Quaternion):
        return value.copy()

    try:
        values = tuple(value)
    except Exception:
        return fallback.copy()

    if len(values) == 4:
        try:
            return mathutils.Quaternion(values)
        except Exception:
            return fallback.copy()

    euler = _vector3(values, _quaternion_to_euler_vector(fallback))
    return mathutils.Euler(euler, "XYZ").to_quaternion()


def _cache_quaternion(cache, key: str, fallback: mathutils.Quaternion) -> mathutils.Quaternion:
    if isinstance(cache, dict):
        return _quaternion_from_value(cache.get(key), fallback)
    return fallback.copy()


def _lerp_vector(a: mathutils.Vector, b: mathutils.Vector, t: float) -> mathutils.Vector:
    t = _clamp01(t)
    return a + (b - a) * t


def _slerp_quaternion(a: mathutils.Quaternion, b: mathutils.Quaternion, t: float) -> mathutils.Quaternion:
    return a.slerp(b, _clamp01(t))


def _wrap_angle(value: float) -> float:
    return (float(value) + math.pi) % (math.pi * 2.0) - math.pi


def _smooth_damp_vector(
    current: mathutils.Vector,
    target: mathutils.Vector,
    velocity: mathutils.Vector,
    smooth_time: float,
    max_speed: float,
    delta_time: float,
) -> tuple[mathutils.Vector, mathutils.Vector]:
    if delta_time <= 0.0:
        return target.copy(), mathutils.Vector((0.0, 0.0, 0.0))

    smooth_time = max(0.0001, float(smooth_time))
    omega = 2.0 / smooth_time
    x = omega * delta_time
    exp = 1.0 / (1.0 + x + 0.48 * x * x + 0.235 * x * x * x)

    change = current - target
    original_target = target.copy()

    if max_speed > 0.0:
        max_change = max_speed * smooth_time
        if change.length > max_change and change.length > 0.0:
            change = change.normalized() * max_change

    target = current - change
    temp = (velocity + omega * change) * delta_time
    next_velocity = (velocity - omega * temp) * exp
    output = target + (change + temp) * exp

    if (original_target - current).dot(output - original_target) > 0.0:
        output = original_target
        next_velocity = (output - original_target) / delta_time

    return output, next_velocity


def _component_multiply(a: mathutils.Vector, b: mathutils.Vector) -> mathutils.Vector:
    return mathutils.Vector((a.x * b.x, a.y * b.y, a.z * b.z))


def _is_triangle_wave(value) -> bool:
    if isinstance(value, (int, float)):
        return int(value) == 1
    text = str(value or "").strip().lower()
    return text in {"1", "triangle", "tri", "t", "三角", "三角波"}


def _scene_time_seconds() -> float:
    scene = bpy.context.scene
    render = scene.render
    fps_base = getattr(render, "fps_base", 1.0) or 1.0
    fps = max(float(getattr(render, "fps", 24.0)) / float(fps_base), 0.0001)
    return float(scene.frame_current) / fps


def _triangle_wave(time_value: float) -> float:
    repeated = (time_value * 2.0) % 4.0
    pingpong = 2.0 - abs(repeated - 2.0)
    return pingpong - 1.0


def _evaluate_waveform(waveform, frequency: float, phase: float, time_seconds: float) -> float:
    time_value = time_seconds * max(float(frequency), 0.0) + float(phase)
    if _is_triangle_wave(waveform):
        return _triangle_wave(time_value)
    return math.sin(time_value * math.pi * 2.0)


def _hash01(value: float) -> float:
    hashed = math.sin(value * 12.9898 + 78.233) * 43758.5453
    return hashed - math.floor(hashed)


def _signed_noise(seed: int, time_seconds: float, frequency: float) -> float:
    time_value = time_seconds * max(float(frequency), 0.0)
    left = math.floor(time_value)
    blend = time_value - left
    blend = blend * blend * (3.0 - 2.0 * blend)
    seed_offset = float(seed) * 19.193
    a = _hash01(float(left) + seed_offset)
    b = _hash01(float(left + 1) + seed_offset)
    return (a + (b - a) * blend) * 2.0 - 1.0


def _signed_noise3(seed: int, frequency: float, time_seconds: float) -> mathutils.Vector:
    return mathutils.Vector(
        (
            _signed_noise(seed, time_seconds, frequency),
            _signed_noise(seed + 17, time_seconds + 19.0, frequency),
            _signed_noise(seed + 31, time_seconds + 37.0, frequency),
        )
    )


def _degrees_vector_to_quaternion(value) -> mathutils.Quaternion:
    vec = _vector3(value, mathutils.Vector((0.0, 0.0, 0.0)))
    return mathutils.Euler(
        (
            math.radians(vec.x),
            math.radians(vec.y),
            math.radians(vec.z),
        ),
        "XYZ",
    ).to_quaternion()


@omni(
    enable=True,
    bl_label="软跟随",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "目标物体",
        "缓存状态",
        "位置跟随",
        "旋转跟随",
        "响应",
        "超调",
        "最大速度",
        "最大角速度",
        "时间步长",
    ],
    _OUTPUT_NAME=[
        "缓存状态",
        "位置",
        "旋转",
    ],
    omni_presets=[
        {
            "name": "缓慢跟随",
            "values": {
                "position_follow": 1.0,
                "rotation_follow": 1.0,
                "response": 0.1,
                "overshoot": 0.0,
                "max_velocity": 0.0,
                "max_angular_velocity": 0.0,
            },
        },
        {
            "name": "柔和跟随",
            "values": {
                "position_follow": 1.0,
                "rotation_follow": 1.0,
                "response": 0.3,
                "overshoot": 0.05,
                "max_velocity": 0.0,
                "max_angular_velocity": 0.0,
            },
        },
        {
            "name": "快速跟随",
            "values": {
                "position_follow": 1.0,
                "rotation_follow": 1.0,
                "response": 0.9,
                "overshoot": 0.08,
                "max_velocity": 0.0,
                "max_angular_velocity": 0.0,
            },
        },
        {
            "name": "明显超调",
            "values": {
                "position_follow": 1.0,
                "rotation_follow": 1.0,
                "response": 0.6,
                "overshoot": 0.35,
                "max_velocity": 0.0,
                "max_angular_velocity": 0.0,
            },
        },
    ],
    omni_description="""
    从 000 空变换出发，缓慢追向目标物体的世界位置/旋转。
    输出的是可写入控制器的累计变换，不是本帧增量。

    推荐接法：
    1. 让目标输入接一个 TargetProbe 空物体。
    2. 缓存读取和缓存写入使用同一个缓存名，读到的缓存接本节点，输出缓存再写回。
    3. 只做跟随时，把位置/旋转接写入物体完整变换，缩放用 1,1,1，写入 FollowCtrl。
    4. 要叠加漂浮时，先把软跟随和漂浮接到变换合成，再把合成结果写入 FollowCtrl。

    使用习惯：
    TargetProbe 和 FollowCtrl 建议初始 local 变换都是 0。
    TargetProbe 是需要追踪的物体的子级
    FollowCtrl  是一个裸物体接收变换，需要追踪的物体/骨骼使用【子级】约束跟随 FollowCtrl
    子级约束中可以配置每个轴的权重和影响。
    """,
)
def softFollow(
    target_obj: bpy.types.Object,
    cache_state: _OmniCache,
    position_follow: float = 0.9,
    rotation_follow: float = 0.8,
    response: float = 4.0,
    overshoot: float = 0.15,
    max_velocity: float = 0.0,
    max_angular_velocity: float = 0.0,
    delta_time: float = 1.0 / 24.0,
) -> tuple[
    _OmniCache,
    mathutils.Vector,
    mathutils.Vector,
]:
    target_obj = _require_object(target_obj, "target_obj")

    dt = max(float(delta_time), 0.0)
    zero_vector = mathutils.Vector((0.0, 0.0, 0.0))
    identity_rotation = mathutils.Quaternion((1.0, 0.0, 0.0, 0.0))

    target_matrix = target_obj.matrix_world.copy()
    target_position = target_matrix.translation.copy()
    target_rotation = target_matrix.to_quaternion()
    current_frame = bpy.context.scene.frame_current
    cached_frame = _cache_frame(cache_state)

    if cached_frame is not None and current_frame != cached_frame + 1:
        return (
            None,
            zero_vector.copy(),
            zero_vector.copy(),
        )

    base_position = zero_vector.copy()
    base_rotation = identity_rotation.copy()
    state_position = _cache_vector(cache_state, "position", base_position)
    state_rotation = _cache_quaternion(cache_state, "rotation", base_rotation)
    state_velocity = _cache_vector_any(cache_state, ("velocity", "position_velocity"), zero_vector)
    previous_euler = _cache_vector(
        cache_state,
        "previous_euler",
        _quaternion_to_euler_vector(state_rotation),
    )

    position_follow = _clamp01(position_follow)
    rotation_follow = _clamp01(rotation_follow)
    response = max(float(response), 0.0)
    overshoot = _clamp01(overshoot)
    max_velocity = max(float(max_velocity), 0.0)
    max_angular_velocity = max(float(max_angular_velocity), 0.0)

    if position_follow <= 0.0:
        next_position = base_position.copy()
        next_velocity = zero_vector.copy()
    elif dt <= 0.0:
        next_position = _lerp_vector(base_position, target_position, position_follow)
        next_velocity = zero_vector.copy()
    else:
        follow_target = _lerp_vector(base_position, target_position, position_follow)
        smooth_time = 1.0 / max(0.01, response)
        old_position = state_position.copy()
        next_position, next_velocity = _smooth_damp_vector(
            state_position,
            follow_target,
            state_velocity,
            smooth_time,
            max_velocity,
            dt,
        )

        if overshoot > 0.0:
            next_position += next_velocity * (overshoot * dt)

        if max_velocity > 0.0:
            position_delta = next_position - old_position
            max_delta = max_velocity * dt
            if position_delta.length_squared > max_delta * max_delta and position_delta.length > 0.0:
                next_position = old_position + position_delta.normalized() * max_delta
                next_velocity = (next_position - old_position) / dt

    if rotation_follow <= 0.0:
        next_rotation = base_rotation.copy()
        angular_velocity = zero_vector.copy()
        next_previous_euler = _quaternion_to_euler_vector(next_rotation)
    elif dt <= 0.0:
        next_rotation = _slerp_quaternion(base_rotation, target_rotation, rotation_follow)
        angular_velocity = zero_vector.copy()
        next_previous_euler = _quaternion_to_euler_vector(next_rotation)
    else:
        follow_target_rotation = _slerp_quaternion(base_rotation, target_rotation, rotation_follow)
        rotate_t = 1.0 - math.exp(-response * dt)
        rotate_t = _clamp01(rotate_t * (1.0 + overshoot))
        old_rotation = state_rotation.copy()
        next_rotation = _slerp_quaternion(state_rotation, follow_target_rotation, rotate_t)

        if max_angular_velocity > 0.0:
            angle = old_rotation.rotation_difference(next_rotation).angle
            max_angle = math.radians(max_angular_velocity) * dt
            if angle > max_angle and angle > 0.0001:
                next_rotation = _slerp_quaternion(old_rotation, next_rotation, max_angle / angle)

        next_previous_euler = _quaternion_to_euler_vector(next_rotation)
        angular_velocity = mathutils.Vector(
            (
                _wrap_angle(next_previous_euler.x - previous_euler.x) / dt,
                _wrap_angle(next_previous_euler.y - previous_euler.y) / dt,
                _wrap_angle(next_previous_euler.z - previous_euler.z) / dt,
            )
        )

    next_rotation_euler = _quaternion_to_euler_vector(next_rotation)

    next_cache_state = {
        "frame": int(current_frame),
        "position": next_position.copy(),
        "rotation": next_rotation.copy(),
        "velocity": next_velocity.copy(),
        "angular_velocity": angular_velocity.copy(),
        "previous_euler": next_previous_euler.copy(),
    }

    return (
        next_cache_state,
        next_position,
        next_rotation_euler,
    )


@omni(
    enable=True,
    bl_label="漂浮",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "启用波动",
        "波动倍率",
        "波形",
        "波动频率",
        "波动相位",
        "波动位置幅度",
        "波动旋转幅度",
        "波动缩放幅度",
        "波动轴权重",
        "启用噪波",
        "噪波倍率",
        "噪波频率",
        "噪波种子",
        "噪波位置幅度",
        "噪波旋转幅度",
        "噪波缩放幅度",
    ],
    input_init={
        "oscillation_waveform": {
            "description": "0 = Sin, 1 = Triangle",
            "min_value": 0,
            "max_value": 1,
        },
    },
    _OUTPUT_NAME=[
        "位置",
        "旋转",
        "缩放",
    ],
    omni_presets=[
        {
            "name": "清空",
            "values": {
                "oscillation_enabled": False,
                "oscillation_multiplier": 1.0,
                "oscillation_waveform": 0,
                "oscillation_frequency": 0.35,
                "oscillation_phase": 0.0,
                "oscillation_position_amplitude": (0.0, 0.0, 0.0),
                "oscillation_rotation_amplitude": (0.0, 0.0, 0.0),
                "oscillation_scale_amplitude": (0.0, 0.0, 0.0),
                "oscillation_axis_weight": (1.0, 1.0, 1.0),
                "noise_enabled": False,
                "noise_multiplier": 1.0,
                "noise_frequency": 0.75,
                "noise_seed": 1,
                "noise_position_amplitude": (0.0, 0.0, 0.0),
                "noise_rotation_amplitude": (0.0, 0.0, 0.0),
                "noise_scale_amplitude": (0.0, 0.0, 0.0),
            },
        },
        {
            "name": "光环",
            "values": {
                "oscillation_enabled": True,
                "oscillation_multiplier": 1.0,
                "oscillation_waveform": 0,
                "oscillation_frequency": 0.35,
                "oscillation_phase": 0.0,
                "oscillation_position_amplitude": (0.0, 0.025, 0.0),
                "oscillation_rotation_amplitude": (0.0, 0.3, 0.0),
                "oscillation_scale_amplitude": (0.0, 0.0, 0.0),
                "oscillation_axis_weight": (1.0, 1.0, 1.0),
                "noise_enabled": False,
                "noise_multiplier": 1.0,
                "noise_frequency": 0.75,
                "noise_seed": 1,
                "noise_position_amplitude": (0.0, 0.0, 0.0),
                "noise_rotation_amplitude": (0.0, 0.0, 0.0),
                "noise_scale_amplitude": (0.0, 0.0, 0.0),
            },
        },
        {
            "name": "武器",
            "values": {
                "oscillation_enabled": False,
                "oscillation_multiplier": 1.0,
                "oscillation_waveform": 0,
                "oscillation_frequency": 0.35,
                "oscillation_phase": 0.0,
                "oscillation_position_amplitude": (0.0, 0.0, 0.0),
                "oscillation_rotation_amplitude": (0.0, 0.0, 0.0),
                "oscillation_scale_amplitude": (0.0, 0.0, 0.0),
                "oscillation_axis_weight": (1.0, 1.0, 1.0),
                "noise_enabled": True,
                "noise_multiplier": 1.0,
                "noise_frequency": 0.75,
                "noise_seed": 1,
                "noise_position_amplitude": (0.012, 0.012, 0.012),
                "noise_rotation_amplitude": (0.35, 0.35, 0.35),
                "noise_scale_amplitude": (0.0, 0.0, 0.0),
            },
        },
        {
            "name": "背包",
            "values": {
                "oscillation_enabled": False,
                "oscillation_multiplier": 1.0,
                "oscillation_waveform": 0,
                "oscillation_frequency": 0.35,
                "oscillation_phase": 0.0,
                "oscillation_position_amplitude": (0.0, 0.0, 0.0),
                "oscillation_rotation_amplitude": (0.0, 0.0, 0.0),
                "oscillation_scale_amplitude": (0.0, 0.0, 0.0),
                "oscillation_axis_weight": (1.0, 1.0, 1.0),
                "noise_enabled": True,
                "noise_multiplier": 1.0,
                "noise_frequency": 0.75,
                "noise_seed": 1,
                "noise_position_amplitude": (0.018, 0.018, 0.018),
                "noise_rotation_amplitude": (0.25, 0.25, 0.25),
                "noise_scale_amplitude": (0.0, 0.0, 0.0),
            },
        },
        {
            "name": "无人机",
            "values": {
                "oscillation_enabled": False,
                "oscillation_multiplier": 1.0,
                "oscillation_waveform": 0,
                "oscillation_frequency": 0.35,
                "oscillation_phase": 0.0,
                "oscillation_position_amplitude": (0.0, 0.0, 0.0),
                "oscillation_rotation_amplitude": (0.0, 0.0, 0.0),
                "oscillation_scale_amplitude": (0.0, 0.0, 0.0),
                "oscillation_axis_weight": (1.0, 1.0, 1.0),
                "noise_enabled": True,
                "noise_multiplier": 1.0,
                "noise_frequency": 0.75,
                "noise_seed": 1,
                "noise_position_amplitude": (0.02, 0.02, 0.02),
                "noise_rotation_amplitude": (0.0, 0.45, 0.0),
                "noise_scale_amplitude": (0.0, 0.0, 0.0),
            },
        },
    ],
    omni_description="""
    从 000 空变换出发，生成一个漂浮附加变换。
    默认位置 0,0,0，旋转 0,0,0，缩放 1,1,1；不读物体，也不需要 cache。

    推荐接法：
    1. 单独使用时，位置/旋转/缩放直接接写入物体完整变换。
    2. 和软跟随一起用时，把软跟随接变换合成的基础变换，把漂浮接附加变换。
    3. 想让漂浮沿跟随旋转后的本地轴移动，就在变换合成里启用“附加位置使用基础旋转”。

    使用习惯：
    FollowCtrl  是一个裸物体接收变换，需要追踪的物体/骨骼使用【子级】约束跟随 FollowCtrl
    子级约束中可以配置每个轴的权重和影响。
    """,
)
def floating(
    oscillation_enabled: bool = False,
    oscillation_multiplier: float = 1.0,
    oscillation_waveform: int = 0,
    oscillation_frequency: float = 0.35,
    oscillation_phase: float = 0.0,
    oscillation_position_amplitude: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
    oscillation_rotation_amplitude: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
    oscillation_scale_amplitude: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
    oscillation_axis_weight: mathutils.Vector = mathutils.Vector((1.0, 1.0, 1.0)),
    noise_enabled: bool = False,
    noise_multiplier: float = 1.0,
    noise_frequency: float = 0.75,
    noise_seed: int = 1,
    noise_position_amplitude: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
    noise_rotation_amplitude: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
    noise_scale_amplitude: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0)),
) -> tuple[
    mathutils.Vector,
    mathutils.Vector,
    mathutils.Vector,
]:
    zero_vector = mathutils.Vector((0.0, 0.0, 0.0))
    one_vector = mathutils.Vector((1.0, 1.0, 1.0))
    time_value = _scene_time_seconds()
    final_position = zero_vector.copy()
    final_rotation = mathutils.Quaternion((1.0, 0.0, 0.0, 0.0))
    final_scale = one_vector.copy()

    if oscillation_enabled:
        wave = _evaluate_waveform(oscillation_waveform, oscillation_frequency, oscillation_phase, time_value)
        scaled_wave = wave * max(float(oscillation_multiplier), 0.0)
        weighted_position_amplitude = _component_multiply(
            _vector3(oscillation_position_amplitude, zero_vector),
            _vector3(oscillation_axis_weight, one_vector),
        )
        final_position += weighted_position_amplitude * scaled_wave
        final_rotation = final_rotation @ _degrees_vector_to_quaternion(
            _vector3(oscillation_rotation_amplitude, zero_vector) * scaled_wave
        )
        final_scale += _vector3(oscillation_scale_amplitude, zero_vector) * scaled_wave

    if noise_enabled:
        noise = _signed_noise3(int(noise_seed), noise_frequency, time_value)
        noise_scale = max(float(noise_multiplier), 0.0)
        position_noise = _component_multiply(
            _vector3(noise_position_amplitude, zero_vector),
            noise,
        ) * noise_scale
        rotation_noise = _component_multiply(
            _vector3(noise_rotation_amplitude, zero_vector),
            _signed_noise3(int(noise_seed) + 17, noise_frequency, time_value),
        ) * noise_scale
        scale_noise = _component_multiply(
            _vector3(noise_scale_amplitude, zero_vector),
            _signed_noise3(int(noise_seed) + 31, noise_frequency, time_value),
        ) * noise_scale

        final_position += position_noise
        final_rotation = final_rotation @ _degrees_vector_to_quaternion(rotation_noise)
        final_scale += scale_noise

    final_rotation_euler = _quaternion_to_euler_vector(final_rotation)

    return (
        final_position,
        final_rotation_euler,
        final_scale,
    )
