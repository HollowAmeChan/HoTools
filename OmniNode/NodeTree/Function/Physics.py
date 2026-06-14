from ..OmniNodeSocketMapping import _OmniBone, _OmniCache
from ..FunctionNodeCore import omni
from . import _Color

import typing
import bpy
import mathutils


def _require_armature_object(obj, label: str) -> bpy.types.Object:
    if obj is None or not isinstance(obj, bpy.types.Object) or obj.type != "ARMATURE":
        raise ValueError(f"{label} is not an armature object")
    return obj


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


def _scene_delta_time() -> float:
    render = bpy.context.scene.render
    fps_base = float(render.fps_base) if render.fps_base else 1.0
    fps = float(render.fps) / fps_base
    if fps <= 0.0:
        return 0.0
    return 1.0 / fps


def _cache_frame(cache):
    if not isinstance(cache, dict) or "frame" not in cache:
        return None

    try:
        return int(cache.get("frame"))
    except Exception:
        return None


def _matrix_from_cache(value):
    if isinstance(value, mathutils.Matrix):
        return value.copy()

    try:
        return mathutils.Matrix(value)
    except Exception:
        return None


def _quaternion_from_cache(value, fallback: mathutils.Quaternion) -> mathutils.Quaternion:
    if isinstance(value, mathutils.Quaternion):
        return value.copy()

    try:
        values = tuple(value)
    except Exception:
        return fallback.copy()

    if len(values) != 4:
        return fallback.copy()

    try:
        return mathutils.Quaternion(values)
    except Exception:
        return fallback.copy()


def _bone_children(pose_bone):
    return list(getattr(pose_bone, "children", []) or [])


def _collect_bone_names(root_pose_bone, include_branches: bool) -> list[str]:
    names = []

    def visit(pose_bone):
        names.append(pose_bone.name)
        children = _bone_children(pose_bone)
        if not children:
            return

        if include_branches:
            for child in children:
                visit(child)
        else:
            visit(children[0])

    visit(root_pose_bone)
    return names


def _chain_is_valid(chain) -> bool:
    return (
        isinstance(chain, dict)
        and isinstance(chain.get("armature"), bpy.types.Object)
        and chain.get("armature").type == "ARMATURE"
        and isinstance(chain.get("bones"), list)
        and bool(chain.get("bones"))
    )


def _resolve_bone_value(value):
    if not isinstance(value, dict):
        raise ValueError("bone input is empty")

    armature_obj = value.get("armature")
    bone_name = str(value.get("bone") or "").strip()
    armature_obj = _require_armature_object(armature_obj, "armature")
    if not bone_name:
        raise ValueError("bone name is empty")
    return armature_obj, bone_name


def _pose_bone_head_tail(pose_bone) -> tuple[mathutils.Vector, mathutils.Vector]:
    return pose_bone.head.copy(), pose_bone.tail.copy()


def _pose_bone_head_tail_world(
    armature_obj: bpy.types.Object,
    pose_bone,
) -> tuple[mathutils.Vector, mathutils.Vector]:
    matrix_world = armature_obj.matrix_world
    return matrix_world @ pose_bone.head.copy(), matrix_world @ pose_bone.tail.copy()


def _armature_direction_to_world(
    armature_obj: bpy.types.Object,
    direction: mathutils.Vector,
) -> mathutils.Vector:
    if direction.length <= 0.000001:
        return mathutils.Vector((0.0, 0.0, 1.0))
    world_direction = armature_obj.matrix_world.to_3x3() @ direction
    if world_direction.length <= 0.000001:
        return direction.normalized()
    return world_direction.normalized()


def _world_direction_to_armature(
    armature_obj: bpy.types.Object,
    direction: mathutils.Vector,
) -> mathutils.Vector:
    if direction.length <= 0.000001:
        return mathutils.Vector((0.0, 0.0, 1.0))
    local_direction = armature_obj.matrix_world.inverted().to_3x3() @ direction
    if local_direction.length <= 0.000001:
        return direction.normalized()
    return local_direction.normalized()


def _simulated_bone_names(chain) -> list[str]:
    return list(chain["bones"])[1:]


def _parent_axis_from_pose_axis(pose_bone, axis: mathutils.Vector) -> mathutils.Vector:
    parent = getattr(pose_bone, "parent", None)
    if parent is None:
        return axis.normalized()

    parent_rotation = parent.matrix.to_quaternion()
    return (parent_rotation.inverted() @ axis).normalized()


def _rest_axis_world(
    armature_obj: bpy.types.Object,
    pose_bone,
    joint,
) -> mathutils.Vector:
    fallback = pose_bone.tail.copy() - pose_bone.head.copy()
    fallback_axis = fallback.normalized() if fallback.length > 0.000001 else mathutils.Vector((0.0, 0.0, 1.0))
    parent_axis = _vector3(joint.get("init_axis_parent"), fallback_axis)

    parent = getattr(pose_bone, "parent", None)
    if parent is not None:
        axis_pose = parent.matrix.to_quaternion() @ parent_axis
    else:
        axis_pose = parent_axis

    return _armature_direction_to_world(armature_obj, axis_pose)


def _init_joint_state(armature_obj: bpy.types.Object, bone_name: str):
    pose_bone = armature_obj.pose.bones.get(bone_name)
    if pose_bone is None:
        return None

    head, tail = _pose_bone_head_tail(pose_bone)
    axis_local = tail - head
    head_world, tail_world = _pose_bone_head_tail_world(armature_obj, pose_bone)
    axis_world = tail_world - head_world
    length = axis_world.length
    if length <= 0.000001:
        return None

    matrix = pose_bone.matrix.copy()
    init_axis_local = (
        axis_local.normalized()
        if axis_local.length > 0.000001
        else _world_direction_to_armature(armature_obj, axis_world)
    )
    init_axis_parent = _parent_axis_from_pose_axis(pose_bone, init_axis_local)
    return {
        "bone": bone_name,
        "current_tail": tail_world.copy(),
        "prev_tail": tail_world.copy(),
        "init_axis": axis_world.normalized(),
        "init_axis_local": init_axis_local,
        "init_axis_parent": init_axis_parent,
        "length": float(length),
        "init_rotation": matrix.to_quaternion().copy(),
        "init_scale": matrix.to_scale().copy(),
        "init_matrix_basis": pose_bone.matrix_basis.copy(),
    }


def _build_initial_cache(chain):
    armature_obj = chain["armature"]
    joints = {}
    for bone_name in _simulated_bone_names(chain):
        joint = _init_joint_state(armature_obj, bone_name)
        if joint is not None:
            joints[bone_name] = joint

    return {
        "version": 2,
        "space": "WORLD",
        "root_as_center": True,
        "armature_name": armature_obj.name_full,
        "root_bone": chain.get("root_bone", ""),
        "bones": list(chain["bones"]),
        "joints": joints,
    }


def _cache_matches_chain(cache, chain) -> bool:
    if not isinstance(cache, dict):
        return False
    return (
        cache.get("version") == 2
        and cache.get("space") == "WORLD"
        and cache.get("root_as_center") is True
        and cache.get("armature_name") == chain["armature"].name_full
        and cache.get("root_bone") == chain.get("root_bone", "")
        and cache.get("bones") == list(chain["bones"])
        and isinstance(cache.get("joints"), dict)
    )


def _restore_initial_pose(armature_obj: bpy.types.Object, cache):
    if not isinstance(cache, dict):
        return

    joints = cache.get("joints")
    if not isinstance(joints, dict):
        return

    for bone_name, joint in joints.items():
        pose_bone = armature_obj.pose.bones.get(bone_name)
        if pose_bone is None or not isinstance(joint, dict):
            continue

        matrix_basis = _matrix_from_cache(joint.get("init_matrix_basis"))
        if matrix_basis is not None:
            pose_bone.matrix_basis = matrix_basis


def _joint_state_from_cache(joint, fallback_tail: mathutils.Vector):
    if not isinstance(joint, dict):
        return fallback_tail.copy(), fallback_tail.copy()

    current_tail = _vector3(joint.get("current_tail"), fallback_tail)
    prev_tail = _vector3(joint.get("prev_tail"), fallback_tail)
    return current_tail, prev_tail


def _write_pose_bone_tail_world(
    armature_obj: bpy.types.Object,
    bone_name: str,
    joint,
    next_tail_world: mathutils.Vector,
) -> bool:
    pose_bone = armature_obj.pose.bones.get(bone_name)
    if pose_bone is None:
        return False

    head_world, fallback_tail_world = _pose_bone_head_tail_world(armature_obj, pose_bone)
    direction_world = next_tail_world - head_world
    if direction_world.length <= 0.000001:
        return False

    fallback_axis_local = _world_direction_to_armature(
        armature_obj,
        fallback_tail_world - head_world,
    )
    init_axis_local = _vector3(joint.get("init_axis_local"), fallback_axis_local)
    if init_axis_local.length <= 0.000001:
        return False
    init_axis_local.normalize()

    init_rotation = _quaternion_from_cache(
        joint.get("init_rotation"),
        pose_bone.matrix.to_quaternion(),
    )
    init_scale = _vector3(joint.get("init_scale"), pose_bone.matrix.to_scale())

    desired_direction_local = _world_direction_to_armature(
        armature_obj,
        direction_world.normalized(),
    )
    rotation_delta = init_axis_local.rotation_difference(desired_direction_local)
    pose_bone.matrix = mathutils.Matrix.LocRotScale(
        pose_bone.head.copy(),
        rotation_delta @ init_rotation,
        init_scale,
    )
    return True


@omni(
    enable=True,
    bl_label="从根获取骨链",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["根骨骼", "包含分支"],
    _OUTPUT_NAME=["骨链"],
    omni_description="""
    从 Bone socket 选择的根骨骼生成骨链数据。

    包含分支开启时，会递归收集根骨下面的全部子骨。
    关闭时，只沿每层第一个子骨生成一条单链。
    输出接物理类节点的骨链输入。
    """,
)
def boneChainFromRoot(
    root_bone: _OmniBone,
    include_branches: bool = True,
) -> typing.Any:
    armature_obj, root_name = _resolve_bone_value(root_bone)

    root_pose_bone = armature_obj.pose.bones.get(root_name)
    if root_pose_bone is None:
        raise ValueError(f"bone not found: {root_name}")

    return {
        "armature": armature_obj,
        "root_bone": root_name,
        "bones": _collect_bone_names(root_pose_bone, include_branches),
    }


@omni(
    enable=True,
    bl_label="无碰撞SpringBone",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "骨链",
        "缓存状态",
        "启用",
        "刚性",
        "阻力",
        "重力方向",
        "重力强度",
    ],
    input_init={
        "stiffness_force": {
            "description": "UniVRM stiffnessForce. 越大越倾向回到初始方向。",
            "min_value": 0.0,
        },
        "drag_force": {
            "description": "UniVRM dragForce. 0 保留惯性，1 直接消除上一帧速度。",
            "min_value": 0.0,
            "max_value": 1.0,
        },
        "gravity_power": {
            "description": "沿重力方向施加的外力强度。",
            "min_value": 0.0,
        },
    },
    _OUTPUT_NAME=["缓存状态", "骨架物体"],
    omni_description="""
    无碰撞 SpringBone，参考 UniVRM 的 Verlet 推进。

    接法：
    1. 用“从根获取骨链”生成骨链，接到本节点。
    2. 缓存读取和缓存写入使用同一个缓存名，读到的缓存接本节点，输出缓存再写回。
    3. 每次执行只计算一帧，不做子步补算；时间步长自动使用当前场景输出设置的真实帧率。
       内部按 render.fps / render.fps_base 计算真实帧率，再取 1 / fps 作为 dt。

    规则：
    骨链第一根骨骼只作为 center/锚点，不参与模拟；从第二根骨骼开始模拟。
    本节点在世界空间读取 head/tail 并推进模拟，因此移动整个 Armature 也会产生惯性效果。
    模拟结果会转换回 Armature pose 空间，直接写回 pose bone 旋转。
    Blender 写父 PoseBone 后不会立刻刷新子骨 head/tail；本节点会逐骨写入并刷新依赖图后再处理下一根。
    重力方向按世界空间理解，默认 0,0,-1。
    跳帧时会恢复 cache 中记录的初始 pose，并输出空 cache，防止旧速度残留。
    目前不处理碰撞、运行时缩放补偿和多子步。
    """,
)
def springBoneNoCollision(
    bone_chain: typing.Any,
    cache_state: _OmniCache,
    enabled: bool = True,
    stiffness_force: float = 1.0,
    drag_force: float = 0.4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 0.0,
) -> tuple[_OmniCache, bpy.types.Object]:
    if not _chain_is_valid(bone_chain):
        raise ValueError("bone_chain is invalid")

    armature_obj = bone_chain["armature"]
    current_frame = bpy.context.scene.frame_current
    cached_frame = _cache_frame(cache_state)

    if cached_frame is not None and current_frame != cached_frame + 1:
        _restore_initial_pose(armature_obj, cache_state)
        return None, armature_obj

    if not _cache_matches_chain(cache_state, bone_chain):
        cache_state = _build_initial_cache(bone_chain)

    if not enabled:
        next_cache = dict(cache_state)
        next_cache["frame"] = int(current_frame)
        return next_cache, armature_obj

    dt = _scene_delta_time()
    stiffness_force = max(float(stiffness_force), 0.0)
    drag_force = max(0.0, min(1.0, float(drag_force)))
    gravity_power = max(float(gravity_power), 0.0)
    gravity = _vector3(gravity_dir, mathutils.Vector((0.0, 0.0, -1.0)))
    if gravity.length > 0.000001:
        gravity.normalize()

    old_joints = cache_state.get("joints", {})
    next_joints = {}

    for bone_name in _simulated_bone_names(bone_chain):
        pose_bone = armature_obj.pose.bones.get(bone_name)
        joint = old_joints.get(bone_name) if isinstance(old_joints, dict) else None
        if pose_bone is None or not isinstance(joint, dict):
            continue

        head, fallback_tail = _pose_bone_head_tail_world(armature_obj, pose_bone)
        current_tail, prev_tail = _joint_state_from_cache(joint, fallback_tail)

        length = float(joint.get("length", (fallback_tail - head).length))
        if length <= 0.000001:
            continue

        rest_axis = _rest_axis_world(armature_obj, pose_bone, joint)
        rest_force = rest_axis * stiffness_force * dt
        external_force = gravity * gravity_power * dt
        inertia = (current_tail - prev_tail) * (1.0 - drag_force)
        next_tail = current_tail + inertia + rest_force + external_force

        direction = next_tail - head
        if direction.length <= 0.000001:
            next_tail = fallback_tail.copy()
        else:
            next_tail = head + direction.normalized() * length

        if _write_pose_bone_tail_world(armature_obj, bone_name, joint, next_tail):
            bpy.context.view_layer.update()

        next_joint = dict(joint)
        next_joint["prev_tail"] = current_tail.copy()
        next_joint["current_tail"] = next_tail.copy()
        next_joints[bone_name] = next_joint

    next_cache = dict(cache_state)
    next_cache["frame"] = int(current_frame)
    next_cache["joints"] = next_joints
    armature_obj.update_tag()
    return next_cache, armature_obj
