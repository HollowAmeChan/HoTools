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


def _cache_frame(cache):
    if not isinstance(cache, dict) or "frame" not in cache:
        return None

    try:
        return int(cache.get("frame"))
    except Exception:
        return None


def _euler_vector(euler) -> mathutils.Vector:
    return mathutils.Vector((euler.x, euler.y, euler.z))


def _wrap_angle(value: float) -> float:
    return (float(value) + math.pi) % (math.pi * 2.0) - math.pi


def _wrap_rotation(vec: mathutils.Vector) -> mathutils.Vector:
    return mathutils.Vector((_wrap_angle(vec.x), _wrap_angle(vec.y), _wrap_angle(vec.z)))


def _rotation_delta(target: mathutils.Vector, current: mathutils.Vector) -> mathutils.Vector:
    return _wrap_rotation(target - current)


def _limit_vector(vec: mathutils.Vector, max_length: float) -> mathutils.Vector:
    max_length = float(max_length)
    if max_length <= 0.0:
        return vec.copy()

    length = vec.length
    if length <= max_length or length == 0.0:
        return vec.copy()
    return vec.normalized() * max_length


def _object_rotation_vector(obj: bpy.types.Object) -> mathutils.Vector:
    mode = getattr(obj, "rotation_mode", "XYZ")
    if mode == "QUATERNION":
        return _euler_vector(obj.rotation_quaternion.to_euler("XYZ"))
    if mode == "AXIS_ANGLE":
        quat = mathutils.Quaternion(obj.rotation_axis_angle[1:], obj.rotation_axis_angle[0])
        return _euler_vector(quat.to_euler("XYZ"))
    return _euler_vector(obj.rotation_euler)


def _matrix_in_parent_space(obj: bpy.types.Object, parent: bpy.types.Object | None) -> mathutils.Matrix:
    if parent is None:
        return obj.matrix_world.copy()
    return parent.matrix_world.inverted_safe() @ obj.matrix_world


@omni(
    enable=True,
    bl_label="软跟随",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "目标物体",
        "跟随控制器",
        "缓存状态",
        "位置弹性",
        "位置阻尼",
        "旋转弹性",
        "旋转阻尼",
        "时间步长",
        "最大移动",
        "最大旋转",
    ],
    _OUTPUT_NAME=[
        "跟随控制器",
        "缓存状态",
        "位置",
        "旋转",
    ],
    omni_description="""
    使用一个打包的 runtime cache 状态做弹簧阻尼跟随。

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
    缓存状态内部包含 frame、position、rotation、position_velocity、rotation_velocity 五项。
    节点只用缓存状态推进模拟，不会每帧反读写回后的控制器位置作为连续状态。

    跳帧规则：
    如果当前帧不是缓存帧的下一帧，会输出零位置/零旋转，并输出空缓存状态。
    这样可以防止旧速度跨跳帧残留；用户也可以对 FollowCtrl 使用 Alt+G / Alt+R 手动归零。

    参数规则：
    位置弹性/旋转弹性越大，追向目标越快。
    位置阻尼/旋转阻尼越大，速度衰减越强。
    阻尼较低时会保留速度惯性，因此可以越过目标后再回弹。
    旋转单位为弧度。
    """,
)
def softFollow(
    target_obj: bpy.types.Object,
    follow_controller: bpy.types.Object,
    cache_state: _OmniCache,
    position_stiffness: float = 0.25,
    position_damping: float = 0.12,
    rotation_stiffness: float = 0.25,
    rotation_damping: float = 0.12,
    delta_time: float = 1.0,
    max_move: float = 0.0,
    max_rotate: float = 0.0,
) -> tuple[
    bpy.types.Object,
    _OmniCache,
    mathutils.Vector,
    mathutils.Vector,
]:
    target_obj = _require_object(target_obj, "target_obj")
    follow_controller = _require_object(follow_controller, "follow_controller")

    dt = max(float(delta_time), 0.0)
    if dt == 0.0:
        dt = 1.0

    current_position = _vector3(follow_controller.location, mathutils.Vector((0.0, 0.0, 0.0)))
    current_rotation = _object_rotation_vector(follow_controller)
    target_matrix = _matrix_in_parent_space(target_obj, follow_controller.parent)
    target_position = target_matrix.translation.copy()
    target_rotation = _euler_vector(target_matrix.to_euler("XYZ"))
    current_frame = bpy.context.scene.frame_current
    cached_frame = _cache_frame(cache_state)
    zero_vector = mathutils.Vector((0.0, 0.0, 0.0))

    if cached_frame is not None and current_frame != cached_frame + 1:
        return (
            follow_controller,
            None,
            zero_vector.copy(),
            zero_vector.copy(),
        )

    state_position = _cache_vector(cache_state, "position", current_position)
    state_rotation = _cache_vector(cache_state, "rotation", current_rotation)
    state_position_velocity = _cache_vector(cache_state, "position_velocity", zero_vector)
    state_rotation_velocity = _cache_vector(cache_state, "rotation_velocity", zero_vector)

    position_stiffness = max(float(position_stiffness), 0.0)
    rotation_stiffness = max(float(rotation_stiffness), 0.0)
    position_retention = 1.0 - _clamp01(position_damping)
    rotation_retention = 1.0 - _clamp01(rotation_damping)

    position_accel = (target_position - state_position) * position_stiffness
    next_position_velocity = (state_position_velocity + position_accel * dt) * position_retention
    move_delta = _limit_vector(next_position_velocity * dt, max_move)
    if dt != 0.0:
        next_position_velocity = move_delta / dt
    next_position = state_position + move_delta

    rotation_accel = _rotation_delta(target_rotation, state_rotation) * rotation_stiffness
    next_rotation_velocity = (state_rotation_velocity + rotation_accel * dt) * rotation_retention
    rotate_delta = _limit_vector(next_rotation_velocity * dt, max_rotate)
    if dt != 0.0:
        next_rotation_velocity = rotate_delta / dt
    next_rotation = _wrap_rotation(state_rotation + rotate_delta)

    next_cache_state = {
        "frame": int(current_frame),
        "position": next_position.copy(),
        "rotation": next_rotation.copy(),
        "position_velocity": next_position_velocity.copy(),
        "rotation_velocity": next_rotation_velocity.copy(),
    }

    return (
        follow_controller,
        next_cache_state,
        next_position,
        next_rotation,
    )
