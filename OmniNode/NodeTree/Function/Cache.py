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


def _object_rotation_quaternion(obj: bpy.types.Object) -> mathutils.Quaternion:
    mode = getattr(obj, "rotation_mode", "XYZ")
    if mode == "QUATERNION":
        return obj.rotation_quaternion.copy()
    if mode == "AXIS_ANGLE":
        return mathutils.Quaternion(obj.rotation_axis_angle[1:], obj.rotation_axis_angle[0])
    return obj.rotation_euler.to_quaternion()


def _lerp_vector(a: mathutils.Vector, b: mathutils.Vector, t: float) -> mathutils.Vector:
    t = _clamp01(t)
    return a + (b - a) * t


def _slerp_quaternion(a: mathutils.Quaternion, b: mathutils.Quaternion, t: float) -> mathutils.Quaternion:
    return a.slerp(b, _clamp01(t))


def _wrap_angle(value: float) -> float:
    return (float(value) + math.pi) % (math.pi * 2.0) - math.pi


def _matrix_in_parent_space(obj: bpy.types.Object, parent: bpy.types.Object | None) -> mathutils.Matrix:
    if parent is None:
        return obj.matrix_world.copy()
    return parent.matrix_world.inverted_safe() @ obj.matrix_world


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


@omni(
    enable=True,
    bl_label="软跟随",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "目标物体",
        "跟随控制器",
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
        "跟随控制器",
        "缓存状态",
        "位置",
        "旋转",
    ],
    omni_description="""
    使用一个打包的 runtime cache 状态做软跟随。
    参数命名和核心行为对齐 Unity HoFollowConstraint 的 Follow 分组。
    本节点只保留基础软跟随，不包含 Unity 版本里的呼吸、噪波、相对偏移、限制和轴锁扩展。

    推荐搭建方式：
    1. 在目标物体下创建 TargetProbe 空物体，并保持 local 位置/旋转为 0。
    2. 在跟随侧创建一个偏移父级空物体，用它摆放人工偏移空间。
    3. 在偏移父级下创建 FollowCtrl 空物体，并保持 local 位置/旋转为 0。
    4. 实际要动的物体通过父子关系、Copy Transforms 或 Child Of 等方式跟随 FollowCtrl。
    5. 节点的目标物体输入接 TargetProbe，跟随控制器输入接 FollowCtrl。
    6. 用缓存读取节点读取一个缓存名，接到本节点缓存状态输入。
    7. 本节点缓存状态输出接缓存写入节点，写回同一个缓存名。
    8. 本节点位置/旋转输出接写入物体变换节点，写入 FollowCtrl。

    空间规则：
    节点以 FollowCtrl 的父级空间作为模拟空间。
    TargetProbe 的世界变换会被转换到 FollowCtrl 父级空间中参与计算。
    本节点输出的是 FollowCtrl 可直接使用的累计 local 位置/旋转，不是本帧增量。
    如果 FollowCtrl 没有父级，模拟空间等同世界空间。

    缓存规则：
    Cache 输入应来自缓存读取节点；缓存缺失时会用 FollowCtrl 当前 local 变换和零速度初始化。
    输出的 Cache 状态应写回同一个缓存名，供下一帧继续读取。
    缓存状态内部包含 frame、anchor_position、anchor_rotation、position、rotation、velocity、angular_velocity、previous_euler。
    节点只用缓存状态推进模拟，不会每帧反读写回后的控制器位置作为连续状态。

    跳帧规则：
    如果当前帧不是缓存帧的下一帧，会输出零位置/零旋转，并输出空缓存状态。
    这样可以防止旧速度跨跳帧残留；用户也可以对 FollowCtrl 使用 Alt+G / Alt+R 手动归零。

    参数规则：
    位置跟随/旋转跟随范围为 0 到 1，0 表示回到初始化锚点，1 表示跟到目标。
    响应越大越快，内部等价于 Unity 的 smoothTime = 1 / max(0.01, response)。
    超调范围为 0 到 1，会根据当前速度向前追加一段惯性。
    最大速度为位置单位/秒，0 表示不限制。
    最大角速度按 Unity 习惯为度/秒，0 表示不限制。
    时间步长应接场景帧率节点输出的帧间隔；未连接时默认按 24fps 计算。
    输出旋转单位为弧度，可直接接写入物体变换节点。
    """,
)
def softFollow(
    target_obj: bpy.types.Object,
    follow_controller: bpy.types.Object,
    cache_state: _OmniCache,
    position_follow: float = 0.9,
    rotation_follow: float = 0.8,
    response: float = 4.0,
    overshoot: float = 0.15,
    max_velocity: float = 0.0,
    max_angular_velocity: float = 0.0,
    delta_time: float = 1.0 / 24.0,
) -> tuple[
    bpy.types.Object,
    _OmniCache,
    mathutils.Vector,
    mathutils.Vector,
]:
    target_obj = _require_object(target_obj, "target_obj")
    follow_controller = _require_object(follow_controller, "follow_controller")

    dt = max(float(delta_time), 0.0)
    zero_vector = mathutils.Vector((0.0, 0.0, 0.0))

    current_position = _vector3(follow_controller.location, zero_vector)
    current_rotation = _object_rotation_quaternion(follow_controller)
    target_matrix = _matrix_in_parent_space(target_obj, follow_controller.parent)
    target_position = target_matrix.translation.copy()
    target_rotation = target_matrix.to_quaternion()
    current_frame = bpy.context.scene.frame_current
    cached_frame = _cache_frame(cache_state)

    if cached_frame is not None and current_frame != cached_frame + 1:
        return (
            follow_controller,
            None,
            zero_vector.copy(),
            zero_vector.copy(),
        )

    anchor_position = _cache_vector(cache_state, "anchor_position", current_position)
    anchor_rotation = _cache_quaternion(cache_state, "anchor_rotation", current_rotation)
    state_position = _cache_vector(cache_state, "position", anchor_position)
    state_rotation = _cache_quaternion(cache_state, "rotation", anchor_rotation)
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
        next_position = anchor_position.copy()
        next_velocity = zero_vector.copy()
    elif dt <= 0.0:
        next_position = _lerp_vector(anchor_position, target_position, position_follow)
        next_velocity = zero_vector.copy()
    else:
        follow_target = _lerp_vector(anchor_position, target_position, position_follow)
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
        next_rotation = anchor_rotation.copy()
        angular_velocity = zero_vector.copy()
        next_previous_euler = _quaternion_to_euler_vector(next_rotation)
    elif dt <= 0.0:
        next_rotation = _slerp_quaternion(anchor_rotation, target_rotation, rotation_follow)
        angular_velocity = zero_vector.copy()
        next_previous_euler = _quaternion_to_euler_vector(next_rotation)
    else:
        follow_target_rotation = _slerp_quaternion(anchor_rotation, target_rotation, rotation_follow)
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
        "anchor_position": anchor_position.copy(),
        "anchor_rotation": anchor_rotation.copy(),
        "position": next_position.copy(),
        "rotation": next_rotation.copy(),
        "velocity": next_velocity.copy(),
        "angular_velocity": angular_velocity.copy(),
        "previous_euler": next_previous_euler.copy(),
    }

    return (
        follow_controller,
        next_cache_state,
        next_position,
        next_rotation_euler,
    )
