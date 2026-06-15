from ..OmniNodeSocketMapping import (
    _OmniBone,
    _OmniBoneChain,
    _OmniCache,
    _OmniShapeKey,
    _OmniVertexGroup,
)
from ..FunctionNodeCore import omni
from . import _Color

import bpy
import hashlib
import mathutils
import numpy as np
import time
import typing

class _BonePhysics:
    EPSILON = 0.000001
    SPRING_CACHE_VERSION = 3
    VRM_SPRING_BONE_CACHE_VERSION = 1
    COLLISION_SNAPSHOT_VERSION = 1

    @staticmethod
    def require_armature(obj, label: str) -> bpy.types.Object:
        """
        校验输入对象确实是 Armature。
        后续物理逻辑会直接访问 pose bones，提前失败比在中途读到 None 更容易定位。
        """
        if obj is None or not isinstance(obj, bpy.types.Object) or obj.type != "ARMATURE":
            raise ValueError(f"{label} is not an armature object")
        return obj

    @classmethod
    def vector3(cls, value, fallback: mathutils.Vector) -> mathutils.Vector:
        """
        把缓存、socket 或默认值统一转成 3D Vector。
        解析失败或维度不足时用 fallback 补齐，避免旧 cache / 空输入把模拟打断。
        """
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

    @staticmethod
    def scene_delta_time() -> float:
        """
        从场景输出设置读取真实帧间隔。
        SpringBone 不暴露 dt 输入，统一跟随 render.fps / render.fps_base。
        """
        render = bpy.context.scene.render
        fps_base = float(render.fps_base) if render.fps_base else 1.0
        fps = float(render.fps) / fps_base
        return 1.0 / fps if fps > 0.0 else 0.0

    @staticmethod
    def cache_frame(cache):
        """
        从 runtime cache 中安全读取上一帧帧号。
        读不到或类型不对时返回 None，让调用方按新 cache 初始化处理。
        """
        if not isinstance(cache, dict) or "frame" not in cache:
            return None

        try:
            return int(cache.get("frame"))
        except Exception:
            return None

    @staticmethod
    def matrix_from_value(value):
        """
        把 cache 内保存的矩阵值恢复为 mathutils.Matrix。
        cache 可能跨运行周期保留为 Matrix 或序列，因此这里做宽松恢复。
        """
        if isinstance(value, mathutils.Matrix):
            return value.copy()

        try:
            return mathutils.Matrix(value)
        except Exception:
            return None

    @staticmethod
    def quaternion_from_value(value, fallback: mathutils.Quaternion) -> mathutils.Quaternion:
        """
        把 cache 内保存的四元数恢复为 mathutils.Quaternion。
        数据缺失或长度不对时返回 fallback，避免姿态恢复产生非法旋转。
        """
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

    @staticmethod
    def bone_socket_value(armature_obj: bpy.types.Object, bone_name: str):
        """
        生成 Bone socket 在运行时传递的轻量值。
        这里不直接传 PoseBone，因为 PoseBone 更容易被模式切换和依赖图刷新影响。
        """
        return {
            "armature": armature_obj,
            "bone": bone_name,
        }

    @classmethod
    def resolve_bone_value(cls, value):
        """
        从 Bone socket 值中解析出 Armature 和骨骼名。
        所有使用 Bone socket 的节点都走这里，保证错误信息和校验行为一致。
        """
        if not isinstance(value, dict):
            raise ValueError("bone input is empty")

        armature_obj = cls.require_armature(value.get("armature"), "armature")
        bone_name = str(value.get("bone") or "").strip()
        if not bone_name:
            raise ValueError("bone name is empty")
        return armature_obj, bone_name

    @classmethod
    def flatten_bone_socket_values(cls, values) -> list[dict]:
        """
        展平 bake 节点可能收到的多重 Bone 输入。
        无效项会被跳过，避免一条物理链失效时阻断其他链 K 帧。
        """
        result = []
        if values is None:
            return result

        stack = list(values) if isinstance(values, (list, tuple)) else [values]
        while stack:
            value = stack.pop(0)
            if isinstance(value, (list, tuple)):
                stack[0:0] = list(value)
                continue

            try:
                armature_obj, bone_name = cls.resolve_bone_value(value)
            except Exception:
                continue
            result.append(cls.bone_socket_value(armature_obj, bone_name))
        return result

    @staticmethod
    def chain_is_valid(chain) -> bool:
        """
        判断骨链运行时数据是否可用于物理节点。
        骨链必须包含 Armature 对象和至少一根骨骼名。
        """
        return (
            isinstance(chain, dict)
            and isinstance(chain.get("armature"), bpy.types.Object)
            and chain.get("armature").type == "ARMATURE"
            and isinstance(chain.get("bones"), list)
            and bool(chain.get("bones"))
        )

    @staticmethod
    def collect_bone_names(root_pose_bone) -> list[str]:
        """
        从根 PoseBone 收集骨链名称。
        VRM SpringBone root 应规避分叉或由建模阶段拆成多条明确链，这里不做主干猜测。
        """
        names = []

        def visit(pose_bone):
            names.append(pose_bone.name)
            children = list(getattr(pose_bone, "children", []) or [])
            for child in children:
                visit(child)

        visit(root_pose_bone)
        return names

    @staticmethod
    def simulated_bone_names(chain) -> list[str]:
        """
        返回真正参与模拟的骨骼名。
        骨链第一根只作为 center/锚点，不参与 SpringBone Verlet 推进。
        """
        return list(chain["bones"])[1:]

    @classmethod
    def bone_socket_values_from_chain(cls, chain, *, include_root: bool = False) -> list[dict]:
        """
        把骨链转换成 Bone socket 列表，主要给 bake 节点消费。
        默认排除 root，因为 root 只是 center，不应该被 SpringBone bake 输出包含。
        """
        if not cls.chain_is_valid(chain):
            return []

        armature_obj = chain["armature"]
        bone_names = list(chain["bones"]) if include_root else cls.simulated_bone_names(chain)
        return [
            cls.bone_socket_value(armature_obj, bone_name)
            for bone_name in bone_names
            if armature_obj.pose.bones.get(bone_name) is not None
        ]

    @classmethod
    def pose_head_tail_world(
        cls,
        armature_obj: bpy.types.Object,
        pose_bone,
    ) -> tuple[mathutils.Vector, mathutils.Vector]:
        """
        读取 PoseBone head/tail 的世界空间位置。
        Blender 的 PoseBone 坐标在 Armature object space，需要乘 armature.matrix_world。
        """
        matrix_world = armature_obj.matrix_world
        return matrix_world @ pose_bone.head.copy(), matrix_world @ pose_bone.tail.copy()

    @classmethod
    def direction_to_world(cls, armature_obj: bpy.types.Object, direction: mathutils.Vector) -> mathutils.Vector:
        """
        把 Armature object space 方向转成世界方向。
        只使用 3x3 旋转/缩放部分，不引入位置平移。
        """
        if direction.length <= cls.EPSILON:
            return mathutils.Vector((0.0, 0.0, 1.0))

        world_direction = armature_obj.matrix_world.to_3x3() @ direction
        if world_direction.length <= cls.EPSILON:
            return direction.normalized()
        return world_direction.normalized()

    @classmethod
    def direction_to_armature(cls, armature_obj: bpy.types.Object, direction: mathutils.Vector) -> mathutils.Vector:
        """
        把世界方向转回 Armature object space。
        用于把模拟得到的世界方向写回 PoseBone 的目标姿态矩阵。
        """
        if direction.length <= cls.EPSILON:
            return mathutils.Vector((0.0, 0.0, 1.0))

        local_direction = armature_obj.matrix_world.inverted().to_3x3() @ direction
        if local_direction.length <= cls.EPSILON:
            return direction.normalized()
        return local_direction.normalized()

    @classmethod
    def spring_joint_from_pose(cls, armature_obj: bpy.types.Object, bone_name: str):
        """
        从当前 PoseBone 建立 SpringBone 单节初始状态。
        缓存 tail、长度、初始轴、初始旋转/缩放和 matrix_basis，供跳帧恢复和连续模拟使用。
        """
        pose_bone = armature_obj.pose.bones.get(bone_name)
        if pose_bone is None:
            return None

        axis_local = pose_bone.tail.copy() - pose_bone.head.copy()
        head_world, tail_world = cls.pose_head_tail_world(armature_obj, pose_bone)
        axis_world = tail_world - head_world
        length = axis_world.length
        if length <= cls.EPSILON:
            return None

        matrix = pose_bone.matrix.copy()
        init_axis_local = (
            axis_local.normalized()
            if axis_local.length > cls.EPSILON
            else cls.direction_to_armature(armature_obj, axis_world)
        )

        parent = getattr(pose_bone, "parent", None)
        init_axis_parent = init_axis_local.normalized()
        if parent is not None:
            init_axis_parent = (parent.matrix.to_quaternion().inverted() @ init_axis_local).normalized()

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

    @classmethod
    def build_spring_cache(cls, chain):
        """
        为整条骨链创建 SpringBone cache。
        cache 记录链结构和每个模拟骨的初始状态，链或版本变化时会重新生成。
        """
        armature_obj = chain["armature"]
        joints = {}
        for bone_name in cls.simulated_bone_names(chain):
            joint = cls.spring_joint_from_pose(armature_obj, bone_name)
            if joint is not None:
                joints[bone_name] = joint

        return {
            "version": cls.SPRING_CACHE_VERSION,
            "space": "WORLD",
            "root_as_center": True,
            "armature_name": armature_obj.name_full,
            "root_bone": chain.get("root_bone", ""),
            "bones": list(chain["bones"]),
            "joints": joints,
        }

    @classmethod
    def spring_cache_matches(cls, cache, chain) -> bool:
        """
        判断已有 cache 是否仍然匹配当前骨链。
        版本、Armature、root 和骨骼列表任一变化都需要丢弃旧物理状态。
        """
        if not isinstance(cache, dict):
            return False
        return (
            cache.get("version") == cls.SPRING_CACHE_VERSION
            and cache.get("space") == "WORLD"
            and cache.get("root_as_center") is True
            and cache.get("armature_name") == chain["armature"].name_full
            and cache.get("root_bone") == chain.get("root_bone", "")
            and cache.get("bones") == list(chain["bones"])
            and isinstance(cache.get("joints"), dict)
        )

    @classmethod
    def restore_initial_pose(cls, armature_obj: bpy.types.Object, cache):
        """
        把 cache 中记录的初始 matrix_basis 写回 PoseBone。
        跳帧时调用它清掉旧速度残留，避免从不连续帧继续模拟造成爆炸。
        """
        if not isinstance(cache, dict):
            return

        joints = cache.get("joints")
        if not isinstance(joints, dict):
            return

        for bone_name, joint in joints.items():
            pose_bone = armature_obj.pose.bones.get(bone_name)
            if pose_bone is None or not isinstance(joint, dict):
                continue

            matrix_basis = cls.matrix_from_value(joint.get("init_matrix_basis"))
            if matrix_basis is not None:
                pose_bone.matrix_basis = matrix_basis

    @classmethod
    def joint_tail_state(cls, joint, fallback_tail: mathutils.Vector):
        """
        从 joint cache 中读取 current/previous tail。
        这是 Verlet 速度的来源，缺失时退回当前骨骼 tail 作为静止状态。
        """
        if not isinstance(joint, dict):
            return fallback_tail.copy(), fallback_tail.copy()

        current_tail = cls.vector3(joint.get("current_tail"), fallback_tail)
        prev_tail = cls.vector3(joint.get("prev_tail"), fallback_tail)
        return current_tail, prev_tail

    @classmethod
    def rest_axis_world(cls, armature_obj: bpy.types.Object, pose_bone, joint, target_pose_matrices) -> mathutils.Vector:
        """
        计算当前父级目标姿态下的休止方向。
        父骨可能还没写回 Blender，所以优先使用本帧已经算出的 target_pose_matrices。
        """
        fallback = pose_bone.tail.copy() - pose_bone.head.copy()
        fallback_axis = fallback.normalized() if fallback.length > cls.EPSILON else mathutils.Vector((0.0, 0.0, 1.0))
        parent_axis = cls.vector3(joint.get("init_axis_parent"), fallback_axis)

        parent = getattr(pose_bone, "parent", None)
        if parent is not None:
            parent_matrix = target_pose_matrices.get(parent.name)
            if parent_matrix is None:
                parent_matrix = parent.matrix
            axis_pose = parent_matrix.to_quaternion() @ parent_axis
        else:
            axis_pose = parent_axis

        return cls.direction_to_world(armature_obj, axis_pose)

    @classmethod
    def target_head_world(
        cls,
        armature_obj: bpy.types.Object,
        pose_bone,
        target_pose_matrices: dict[str, mathutils.Matrix],
        target_tail_worlds: dict[str, mathutils.Vector],
    ) -> mathutils.Vector:
        """
        计算本帧模拟时当前骨骼应该使用的 head 世界位置。
        connected 子骨优先使用父骨本帧目标 tail，避免逐骨写回依赖图导致抽搐。
        """
        current_head, _ = cls.pose_head_tail_world(armature_obj, pose_bone)
        parent = getattr(pose_bone, "parent", None)
        if parent is None:
            return current_head

        if getattr(getattr(pose_bone, "bone", None), "use_connect", False):
            parent_tail = target_tail_worlds.get(parent.name)
            if parent_tail is not None:
                return parent_tail.copy()

        parent_matrix = target_pose_matrices.get(parent.name)
        if parent_matrix is None:
            return current_head

        parent_rest = parent.bone.matrix_local
        bone_rest = pose_bone.bone.matrix_local
        head_pose = (parent_matrix @ parent_rest.inverted() @ bone_rest).translation
        return armature_obj.matrix_world @ head_pose

    @classmethod
    def pose_matrix_from_tail_world(
        cls,
        armature_obj: bpy.types.Object,
        pose_bone,
        joint,
        head_world: mathutils.Vector,
        next_tail_world: mathutils.Vector,
    ) -> mathutils.Matrix | None:
        """
        根据模拟后的世界 tail 生成目标 PoseBone matrix。
        只改变骨骼方向，保留 cache 中记录的初始旋转基准和缩放。
        """
        direction_world = next_tail_world - head_world
        if direction_world.length <= cls.EPSILON:
            return None

        _, fallback_tail_world = cls.pose_head_tail_world(armature_obj, pose_bone)
        fallback_axis_local = cls.direction_to_armature(
            armature_obj,
            fallback_tail_world - head_world,
        )
        init_axis_local = cls.vector3(joint.get("init_axis_local"), fallback_axis_local)
        if init_axis_local.length <= cls.EPSILON:
            return None
        init_axis_local.normalize()

        init_rotation = cls.quaternion_from_value(
            joint.get("init_rotation"),
            pose_bone.matrix.to_quaternion(),
        )
        init_scale = cls.vector3(joint.get("init_scale"), pose_bone.matrix.to_scale())
        desired_direction_pose = cls.direction_to_armature(
            armature_obj,
            direction_world.normalized(),
        )
        rotation_delta = init_axis_local.rotation_difference(desired_direction_pose)
        head_pose = armature_obj.matrix_world.inverted() @ head_world
        return mathutils.Matrix.LocRotScale(
            head_pose,
            rotation_delta @ init_rotation,
            init_scale,
        )

    @staticmethod
    def matrix_basis_from_pose_matrix(
        pose_bone,
        target_matrix: mathutils.Matrix,
        target_pose_matrices: dict[str, mathutils.Matrix],
    ) -> mathutils.Matrix:
        """
        把目标 pose-space matrix 转换成可写入的 matrix_basis。
        connected 子骨不能直接批量写 PoseBone.matrix，所以统一在最后写 matrix_basis。
        """
        bone_rest = pose_bone.bone.matrix_local
        parent = getattr(pose_bone, "parent", None)
        if parent is None:
            return bone_rest.inverted() @ target_matrix

        parent_matrix = target_pose_matrices.get(parent.name)
        if parent_matrix is None:
            parent_matrix = parent.matrix
        parent_rest = parent.bone.matrix_local
        parent_space = parent_matrix @ parent_rest.inverted() @ bone_rest
        return parent_space.inverted() @ target_matrix

    @staticmethod
    def clamp_group_mask(value) -> int:
        try:
            return max(0, min(0xFFFF, int(value)))
        except Exception:
            return 0

    @staticmethod
    def collision_group_bit(group) -> int:
        try:
            group_index = max(1, min(16, int(group)))
        except Exception:
            group_index = 1
        return 1 << (group_index - 1)

    @classmethod
    def flatten_vrm_spring_bone_chain_settings(cls, values) -> list[dict]:
        result = []
        if values is None:
            return result

        stack = list(values) if isinstance(values, (list, tuple)) else [values]
        while stack:
            value = stack.pop(0)
            if isinstance(value, (list, tuple)):
                stack[0:0] = list(value)
                continue
            if isinstance(value, dict) and value.get("version") == cls.VRM_SPRING_BONE_CACHE_VERSION:
                result.append(value)
        return result

    @classmethod
    def vrm_spring_bone_topology_key(cls, armature_obj: bpy.types.Object, settings: list[dict]) -> tuple:
        return (
            int(armature_obj.as_pointer()),
            tuple(
                (str(setting.get("root_bone") or ""), tuple(setting.get("bones") or []))
                for setting in settings
            ),
        )

    @classmethod
    def build_vrm_spring_bone_state(
        cls,
        armature_obj: bpy.types.Object,
        settings: list[dict],
        topology_key: tuple,
    ) -> dict:
        chains = {}
        for setting in settings:
            chain = {
                "armature": armature_obj,
                "root_bone": setting.get("root_bone", ""),
                "bones": list(setting.get("bones") or []),
            }
            chain_cache = cls.build_spring_cache(chain)
            chains[setting["root_bone"]] = {
                "bones": list(chain_cache.get("bones") or []),
                "joints": dict(chain_cache.get("joints") or {}),
            }

        return {
            "version": cls.VRM_SPRING_BONE_CACHE_VERSION,
            "frame": None,
            "armature_name": armature_obj.name_full,
            "topology_key": topology_key,
            "chains": chains,
        }

    @classmethod
    def vrm_spring_bone_cache_matches(cls, cache, armature_obj: bpy.types.Object, topology_key: tuple) -> bool:
        if not isinstance(cache, dict):
            return False
        return (
            cache.get("version") == cls.VRM_SPRING_BONE_CACHE_VERSION
            and cache.get("armature_name") == armature_obj.name_full
            and cache.get("topology_key") == topology_key
            and isinstance(cache.get("chains"), dict)
        )

    @classmethod
    def restore_vrm_spring_bone_initial_pose(cls, armature_obj: bpy.types.Object, state):
        if not isinstance(state, dict):
            return
        chains = state.get("chains")
        if not isinstance(chains, dict):
            return

        for chain in chains.values():
            joints = chain.get("joints") if isinstance(chain, dict) else None
            if not isinstance(joints, dict):
                continue
            for bone_name, joint in joints.items():
                pose_bone = armature_obj.pose.bones.get(bone_name)
                if pose_bone is None or not isinstance(joint, dict):
                    continue
                matrix_basis = cls.matrix_from_value(joint.get("init_matrix_basis"))
                if matrix_basis is not None:
                    pose_bone.matrix_basis = matrix_basis

    @staticmethod
    def scene_objects(scene):
        if scene is None:
            scene = bpy.context.scene
        if scene is None:
            return []
        return list(getattr(scene, "objects", []) or [])

    @staticmethod
    def matrix_scale_radius(matrix: mathutils.Matrix) -> float:
        try:
            scale = matrix.to_scale()
            return max(abs(float(scale.x)), abs(float(scale.y)), abs(float(scale.z)))
        except Exception:
            return 1.0

    @classmethod
    def collider_from_matrix(cls, matrix, props, owner, owner_type: str, bone_name: str = ""):
        collision_type = str(getattr(props, "collision_type", "NONE") or "NONE")
        if collision_type not in {"SPHERE", "CAPSULE"}:
            return None

        radius = max(float(getattr(props, "radius", 0.0)), 0.0) * cls.matrix_scale_radius(matrix)
        if radius <= cls.EPSILON:
            return None

        offset = cls.vector3(getattr(props, "offset", None), mathutils.Vector((0.0, 0.0, 0.0)))
        center = matrix @ offset
        group = max(1, min(16, int(getattr(props, "primary_collision_group", 1))))
        collider = {
            "type": collision_type,
            "owner": owner,
            "owner_type": owner_type,
            "bone": bone_name,
            "primary_group": group,
            "center": center,
            "radius": radius,
        }

        if collision_type == "CAPSULE":
            half_length = max(float(getattr(props, "length", 0.0)), 0.0) * 0.5
            axis = mathutils.Vector((0.0, 1.0, 0.0))
            collider["segment_a"] = matrix @ (offset - axis * half_length)
            collider["segment_b"] = matrix @ (offset + axis * half_length)

        return collider

    @classmethod
    def build_collision_snapshot_from_scene(
        cls,
        scene,
        include_bone_colliders: bool,
        include_object_colliders: bool,
        include_hidden: bool,
    ) -> dict:
        colliders = []
        for obj in cls.scene_objects(scene):
            if not include_hidden:
                try:
                    if not obj.visible_get():
                        continue
                except Exception:
                    pass

            if include_object_colliders:
                props = getattr(obj, "hotools_object_collision", None)
                collider = cls.collider_from_matrix(
                    obj.matrix_world,
                    props,
                    obj,
                    "OBJECT",
                ) if props is not None else None
                if collider is not None:
                    colliders.append(collider)

            if include_bone_colliders and getattr(obj, "type", None) == "ARMATURE":
                for bone in obj.data.bones:
                    props = getattr(bone, "hotools_collision", None)
                    if props is None:
                        continue
                    pose_bone = obj.pose.bones.get(bone.name) if obj.pose else None
                    local_matrix = pose_bone.matrix if pose_bone is not None else bone.matrix_local
                    collider = cls.collider_from_matrix(
                        obj.matrix_world @ local_matrix,
                        props,
                        obj,
                        "BONE",
                        bone.name,
                    )
                    if collider is not None:
                        colliders.append(collider)

        frame = int(getattr(scene or bpy.context.scene, "frame_current", 0) or 0)
        return {
            "version": cls.COLLISION_SNAPSHOT_VERSION,
            "frame": frame,
            "colliders": colliders,
        }

    @classmethod
    def closest_point_on_segment(
        cls,
        point: mathutils.Vector,
        segment_a: mathutils.Vector,
        segment_b: mathutils.Vector,
    ) -> mathutils.Vector:
        segment = segment_b - segment_a
        denom = segment.length_squared
        if denom <= cls.EPSILON:
            return segment_a.copy()
        t = (point - segment_a).dot(segment) / denom
        t = max(0.0, min(1.0, t))
        return segment_a + segment * t

    @classmethod
    def safe_normal(cls, value: mathutils.Vector, fallback: mathutils.Vector) -> mathutils.Vector:
        if value.length > cls.EPSILON:
            return value.normalized()
        if fallback.length > cls.EPSILON:
            return fallback.normalized()
        return mathutils.Vector((0.0, 0.0, 1.0))

    @classmethod
    def project_tail_to_length(
        cls,
        head: mathutils.Vector,
        tail: mathutils.Vector,
        length: float,
        fallback_axis: mathutils.Vector,
    ) -> mathutils.Vector:
        direction = tail - head
        if direction.length <= cls.EPSILON:
            return head + cls.safe_normal(fallback_axis, mathutils.Vector((0.0, 0.0, 1.0))) * length
        return head + direction.normalized() * length

    @classmethod
    def vrm_spring_bone_collision_profile(cls, armature_obj: bpy.types.Object, bone_name: str) -> tuple[float, int]:
        bone = armature_obj.data.bones.get(bone_name) if armature_obj.data is not None else None
        props = getattr(bone, "hotools_collision", None) if bone is not None else None
        if props is None:
            return 0.0, 0

        collision_type = str(getattr(props, "collision_type", "NONE") or "NONE")
        if collision_type not in {"SPHERE", "CAPSULE"}:
            return 0.0, 0

        pose_bone = armature_obj.pose.bones.get(bone_name) if armature_obj.pose is not None else None
        local_matrix = pose_bone.matrix if pose_bone is not None else bone.matrix_local
        radius = max(float(getattr(props, "radius", 0.0)), 0.0)
        radius *= cls.matrix_scale_radius(armature_obj.matrix_world @ local_matrix)
        mask = cls.clamp_group_mask(getattr(props, "collided_by_groups", 0))
        return radius, mask

    @classmethod
    def project_collision(
        cls,
        hit_radius: float,
        collided_by_groups: int,
        armature_obj: bpy.types.Object,
        chain_bones: set[str],
        colliders: list[dict],
        head: mathutils.Vector,
        tail: mathutils.Vector,
        length: float,
        fallback_axis: mathutils.Vector,
    ) -> mathutils.Vector:
        mask = cls.clamp_group_mask(collided_by_groups)
        if not mask:
            return tail

        hit_radius = max(float(hit_radius), 0.0)
        projected = tail.copy()

        for collider in colliders:
            if not isinstance(collider, dict):
                continue
            if not mask & cls.collision_group_bit(collider.get("primary_group", 1)):
                continue
            if collider.get("owner_type") == "BONE" and collider.get("owner") is armature_obj:
                if str(collider.get("bone") or "") in chain_bones:
                    continue

            radius = hit_radius + max(float(collider.get("radius", 0.0)), 0.0)
            if radius <= cls.EPSILON:
                continue

            if collider.get("type") == "CAPSULE":
                segment_a = collider.get("segment_a")
                segment_b = collider.get("segment_b")
                if segment_a is None or segment_b is None:
                    continue
                center = cls.closest_point_on_segment(projected, segment_a, segment_b)
            else:
                center = collider.get("center")
                if center is None:
                    continue

            delta = projected - center
            if delta.length_squared >= radius * radius:
                continue

            normal = cls.safe_normal(delta, fallback_axis)
            pushed = center + normal * radius
            projected = cls.project_tail_to_length(head, pushed, length, fallback_axis)

        return projected


class _MeshPhysics:
    EPSILON = 0.000001
    CACHE_VERSION = 2
    CACHE_KIND = "MESH_SHAPE_KEY_XPBD"
    DEBUG_PRINT_INTERVAL = 1.0
    _debug_profiles = {}

    @staticmethod
    def begin_timing() -> dict:
        return {"start": time.perf_counter(), "stages": {}}

    @staticmethod
    def add_timing(timing: dict | None, stage: str, seconds: float) -> None:
        if timing is None:
            return
        stages = timing.setdefault("stages", {})
        stages[stage] = stages.get(stage, 0.0) + max(float(seconds), 0.0)

    @classmethod
    def publish_debug_timing(
        cls,
        obj: bpy.types.Object,
        shape_key_name: str,
        frame: int,
        vertex_count: int,
        constraint_count: int,
        timing: dict | None,
    ) -> None:
        if timing is None:
            return

        now = time.perf_counter()
        stages = dict(timing.get("stages") or {})
        stages["total"] = max(now - float(timing.get("start", now)), 0.0)

        key = (int(obj.as_pointer()), str(shape_key_name))
        profile = cls._debug_profiles.setdefault(
            key,
            {
                "last_print": now,
                "frames": 0,
                "stages": {},
            },
        )
        profile["frames"] += 1
        profile["frame"] = int(frame)
        profile["vertex_count"] = int(vertex_count)
        profile["constraint_count"] = int(constraint_count)

        totals = profile["stages"]
        for stage, seconds in stages.items():
            totals[stage] = totals.get(stage, 0.0) + float(seconds)

        if now - float(profile["last_print"]) < cls.DEBUG_PRINT_INTERVAL:
            return

        sample_count = max(int(profile["frames"]), 1)
        ordered_stages = (
            "validate",
            "cache",
            "transform",
            "restore",
            "rebuild",
            "solve_setup",
            "predict",
            "pin",
            "stretch",
            "bend",
            "solve_total",
            "write",
            "total",
        )
        used = set()
        stage_text = []
        for stage in ordered_stages:
            if stage in totals:
                used.add(stage)
                stage_text.append(f"{stage}={totals[stage] / sample_count * 1000.0:.3f}ms")
        for stage in sorted(set(totals.keys()) - used):
            stage_text.append(f"{stage}={totals[stage] / sample_count * 1000.0:.3f}ms")

        print(
            "[MeshShapeKeyXPBD] "
            f"obj={obj.name_full} key={shape_key_name} frame={profile['frame']} "
            f"samples={sample_count} verts={profile['vertex_count']} "
            f"constraints={profile['constraint_count']} "
            + " ".join(stage_text)
        )

        cls._debug_profiles[key] = {
            "last_print": now,
            "frames": 0,
            "stages": {},
        }

    @staticmethod
    def require_mesh_object(obj, label: str) -> bpy.types.Object:
        if obj is None or not isinstance(obj, bpy.types.Object) or obj.type != "MESH":
            raise ValueError(f"{label} is not a mesh object")
        if obj.data is None or len(obj.data.vertices) == 0:
            raise ValueError(f"{label} mesh has no vertices")
        return obj

    @classmethod
    def resolve_shape_key_value(cls, value, fallback_obj: bpy.types.Object) -> tuple[bpy.types.Object, str]:
        if isinstance(value, dict):
            obj = value.get("object") or fallback_obj
            shape_key_name = str(value.get("shape_key") or value.get("shape_key_name") or "").strip()
            obj = cls.require_mesh_object(obj, "shape key object")
            if not shape_key_name:
                raise ValueError("shape key name is empty")
            return obj, shape_key_name

        if isinstance(value, bpy.types.ShapeKey):
            key_data = getattr(value, "id_data", None)
            for obj in bpy.data.objects:
                if getattr(obj, "type", None) == "MESH" and getattr(obj.data, "shape_keys", None) == key_data:
                    return obj, value.name
            raise ValueError("shape key owner object not found")

        raise ValueError("shape key input is empty or invalid")

    @staticmethod
    def vertex_group_owner(vertex_group: bpy.types.VertexGroup) -> bpy.types.Object:
        owner = getattr(vertex_group, "id_data", None)
        if owner is None or not isinstance(owner, bpy.types.Object) or owner.type != "MESH":
            raise ValueError("pin vertex group owner is not a mesh object")
        return owner

    @classmethod
    def validate_pin_group(cls, obj: bpy.types.Object, pin_group) -> bpy.types.VertexGroup | None:
        if pin_group is None:
            return None
        if not isinstance(pin_group, bpy.types.VertexGroup):
            raise ValueError("pin vertex group input is invalid")
        owner = cls.vertex_group_owner(pin_group)
        if owner != obj:
            raise ValueError(f"pin vertex group '{pin_group.name}' does not belong to object '{obj.name}'")
        return pin_group

    @staticmethod
    def ensure_target_shape_key(obj: bpy.types.Object, shape_key_name: str) -> bpy.types.ShapeKey:
        mesh = obj.data
        if mesh.shape_keys is None:
            obj.shape_key_add(name="Basis", from_mix=False)

        shape_keys = mesh.shape_keys
        key = shape_keys.key_blocks.get(shape_key_name)
        if key is None:
            key = obj.shape_key_add(name=shape_key_name, from_mix=False)

        if key == shape_keys.reference_key:
            raise ValueError("target shape key cannot be Basis/reference key")

        key.value = 1.0
        return key

    @staticmethod
    def read_key_positions(key: bpy.types.ShapeKey, vertex_count: int) -> np.ndarray:
        values = np.empty(vertex_count * 3, dtype=np.float32)
        key.data.foreach_get("co", values)
        return values.reshape((vertex_count, 3))

    @classmethod
    def read_rest_positions(cls, obj: bpy.types.Object) -> np.ndarray:
        mesh = obj.data
        vertex_count = len(mesh.vertices)
        shape_keys = mesh.shape_keys
        if shape_keys is not None and shape_keys.reference_key is not None:
            return cls.read_key_positions(shape_keys.reference_key, vertex_count)

        values = np.empty(vertex_count * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", values)
        return values.reshape((vertex_count, 3))

    @staticmethod
    def matrix_to_numpy(matrix: mathutils.Matrix) -> np.ndarray:
        return np.asarray(
            [[float(matrix[row][col]) for col in range(4)] for row in range(4)],
            dtype=np.float32,
        )

    @classmethod
    def local_positions_to_world(cls, obj: bpy.types.Object, positions: np.ndarray) -> np.ndarray:
        matrix = cls.matrix_to_numpy(obj.matrix_world)
        values = np.ascontiguousarray(positions, dtype=np.float32)
        return np.ascontiguousarray(values @ matrix[:3, :3].T + matrix[:3, 3], dtype=np.float32)

    @classmethod
    def world_positions_to_local(cls, obj: bpy.types.Object, positions: np.ndarray) -> np.ndarray:
        matrix = cls.matrix_to_numpy(obj.matrix_world.inverted())
        values = np.ascontiguousarray(positions, dtype=np.float32)
        return np.ascontiguousarray(values @ matrix[:3, :3].T + matrix[:3, 3], dtype=np.float32)

    @staticmethod
    def matrix_world_key(obj: bpy.types.Object) -> tuple:
        matrix = obj.matrix_world
        return tuple(round(float(matrix[row][col]), 8) for row in range(4) for col in range(4))

    @staticmethod
    def matrix_world_3x3_key(obj: bpy.types.Object) -> tuple:
        matrix = obj.matrix_world
        return tuple(round(float(matrix[row][col]), 8) for row in range(3) for col in range(3))

    @staticmethod
    def write_shape_key_positions(
        obj: bpy.types.Object,
        shape_key: bpy.types.ShapeKey,
        positions: np.ndarray,
    ) -> None:
        flat = np.ascontiguousarray(positions, dtype=np.float32).reshape(-1)
        shape_key.data.foreach_set("co", flat)
        obj.data.update()
        obj.update_tag()

    @classmethod
    def write_world_positions_to_shape_key(
        cls,
        obj: bpy.types.Object,
        shape_key: bpy.types.ShapeKey,
        positions: np.ndarray,
    ) -> None:
        cls.write_shape_key_positions(obj, shape_key, cls.world_positions_to_local(obj, positions))

    @classmethod
    def restore_rest_to_shape_key(cls, obj: bpy.types.Object, shape_key: bpy.types.ShapeKey, state=None) -> None:
        rest_positions = None
        if isinstance(state, dict):
            cached_rest = state.get("rest_local_positions")
            if isinstance(cached_rest, np.ndarray) and cached_rest.shape == (len(obj.data.vertices), 3):
                rest_positions = cached_rest
        if rest_positions is None:
            rest_positions = cls.read_rest_positions(obj)
        cls.write_shape_key_positions(obj, shape_key, rest_positions)

    @staticmethod
    def topology_key(obj: bpy.types.Object) -> tuple:
        mesh = obj.data
        edge_values = np.empty(len(mesh.edges) * 2, dtype=np.int32)
        if len(edge_values) > 0:
            mesh.edges.foreach_get("vertices", edge_values)
        edge_hash = hashlib.sha1(edge_values.tobytes()).hexdigest()
        return (
            int(obj.as_pointer()),
            int(mesh.as_pointer()),
            len(mesh.vertices),
            len(mesh.edges),
            len(mesh.polygons),
            edge_hash,
        )

    @staticmethod
    def build_inv_masses(obj: bpy.types.Object, pin_group: bpy.types.VertexGroup | None) -> np.ndarray:
        inv_masses = np.ones(len(obj.data.vertices), dtype=np.float32)
        if pin_group is None:
            return inv_masses

        group_index = int(pin_group.index)
        for vertex in obj.data.vertices:
            for group in vertex.groups:
                if group.group == group_index and float(group.weight) > 0.0:
                    inv_masses[vertex.index] = 0.0
                    break
        return inv_masses

    @staticmethod
    def build_edge_constraints(mesh: bpy.types.Mesh, rest_positions: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        edge_count = len(mesh.edges)
        if edge_count == 0:
            empty_i = np.empty(0, dtype=np.int32)
            empty_f = np.empty(0, dtype=np.float32)
            return empty_i, empty_i.copy(), empty_f

        edges = np.empty(edge_count * 2, dtype=np.int32)
        mesh.edges.foreach_get("vertices", edges)
        edges = edges.reshape((edge_count, 2))
        edge_i = np.ascontiguousarray(edges[:, 0], dtype=np.int32)
        edge_j = np.ascontiguousarray(edges[:, 1], dtype=np.int32)
        delta = rest_positions[edge_i] - rest_positions[edge_j]
        edge_rest = np.ascontiguousarray(np.linalg.norm(delta, axis=1), dtype=np.float32)
        return edge_i, edge_j, edge_rest

    @staticmethod
    def constraint_lengths(
        positions: np.ndarray,
        index_i: np.ndarray,
        index_j: np.ndarray,
    ) -> np.ndarray:
        if len(index_i) == 0:
            return np.empty(0, dtype=np.float32)
        delta = positions[index_i] - positions[index_j]
        return np.ascontiguousarray(np.linalg.norm(delta, axis=1), dtype=np.float32)

    @staticmethod
    def build_bend_constraints(mesh: bpy.types.Mesh, rest_positions: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        edge_to_opposites = {}
        try:
            mesh.calc_loop_triangles()
        except Exception:
            pass

        for triangle in mesh.loop_triangles:
            verts = tuple(int(v) for v in triangle.vertices)
            if len(verts) != 3:
                continue
            a, b, c = verts
            for i, j, opposite in ((a, b, c), (b, c, a), (c, a, b)):
                key = (i, j) if i < j else (j, i)
                edge_to_opposites.setdefault(key, []).append(opposite)

        pairs = []
        seen = set()
        for opposites in edge_to_opposites.values():
            unique = []
            for vertex_index in opposites:
                if vertex_index not in unique:
                    unique.append(vertex_index)
            if len(unique) < 2:
                continue
            i, j = unique[0], unique[1]
            key = (i, j) if i < j else (j, i)
            if i == j or key in seen:
                continue
            pairs.append((i, j))
            seen.add(key)

        if not pairs:
            empty_i = np.empty(0, dtype=np.int32)
            empty_f = np.empty(0, dtype=np.float32)
            return empty_i, empty_i.copy(), empty_f

        pair_array = np.asarray(pairs, dtype=np.int32)
        bend_i = np.ascontiguousarray(pair_array[:, 0], dtype=np.int32)
        bend_j = np.ascontiguousarray(pair_array[:, 1], dtype=np.int32)
        delta = rest_positions[bend_i] - rest_positions[bend_j]
        bend_rest = np.ascontiguousarray(np.linalg.norm(delta, axis=1), dtype=np.float32)
        return bend_i, bend_j, bend_rest

    @classmethod
    def build_state(
        cls,
        obj: bpy.types.Object,
        shape_key_name: str,
        pin_group: bpy.types.VertexGroup | None,
        topology_key: tuple,
    ) -> dict:
        rest_local_positions = cls.read_rest_positions(obj)
        rest_positions = cls.local_positions_to_world(obj, rest_local_positions)
        edge_i, edge_j, edge_rest = cls.build_edge_constraints(obj.data, rest_positions)
        bend_i, bend_j, bend_rest = cls.build_bend_constraints(obj.data, rest_positions)
        inv_masses = cls.build_inv_masses(obj, pin_group)
        return {
            "version": cls.CACHE_VERSION,
            "kind": cls.CACHE_KIND,
            "frame": None,
            "object_name": obj.name_full,
            "object_ptr": int(obj.as_pointer()),
            "mesh_ptr": int(obj.data.as_pointer()),
            "shape_key_name": shape_key_name,
            "pin_group_name": pin_group.name if pin_group is not None else "",
            "topology_key": topology_key,
            "object_matrix_world_key": cls.matrix_world_key(obj),
            "object_matrix_world_3x3_key": cls.matrix_world_3x3_key(obj),
            "vertex_count": len(obj.data.vertices),
            "rest_local_positions": rest_local_positions.copy(),
            "rest_positions": rest_positions.copy(),
            "positions": rest_positions.copy(),
            "prev_positions": rest_positions.copy(),
            "inv_masses": inv_masses,
            "edge_i": edge_i,
            "edge_j": edge_j,
            "edge_rest": edge_rest,
            "bend_i": bend_i,
            "bend_j": bend_j,
            "bend_rest": bend_rest,
        }

    @classmethod
    def sync_state_to_object_transform(cls, state: dict, obj: bpy.types.Object) -> dict:
        matrix_key = cls.matrix_world_key(obj)
        matrix_3x3_key = cls.matrix_world_3x3_key(obj)
        if (
            state.get("object_matrix_world_key") == matrix_key
            and state.get("object_matrix_world_3x3_key") == matrix_3x3_key
        ):
            return state

        next_state = dict(state)
        rest_local_positions = np.ascontiguousarray(next_state["rest_local_positions"], dtype=np.float32)
        rest_positions = cls.local_positions_to_world(obj, rest_local_positions)
        next_state["rest_positions"] = rest_positions
        next_state["object_matrix_world_key"] = matrix_key

        if next_state.get("object_matrix_world_3x3_key") != matrix_3x3_key:
            next_state["edge_rest"] = cls.constraint_lengths(rest_positions, next_state["edge_i"], next_state["edge_j"])
            next_state["bend_rest"] = cls.constraint_lengths(rest_positions, next_state["bend_i"], next_state["bend_j"])
            next_state["object_matrix_world_3x3_key"] = matrix_3x3_key

        return next_state

    @classmethod
    def state_matches(
        cls,
        state,
        obj: bpy.types.Object,
        shape_key_name: str,
        pin_group: bpy.types.VertexGroup | None,
        topology_key: tuple,
    ) -> bool:
        if not isinstance(state, dict):
            return False
        vertex_count = len(obj.data.vertices)
        pin_name = pin_group.name if pin_group is not None else ""
        required = (
            "rest_local_positions",
            "rest_positions",
            "positions",
            "prev_positions",
            "inv_masses",
            "edge_i",
            "edge_j",
            "edge_rest",
            "bend_i",
            "bend_j",
            "bend_rest",
        )
        if not all(isinstance(state.get(key), np.ndarray) for key in required):
            return False
        return (
            state.get("version") == cls.CACHE_VERSION
            and state.get("kind") == cls.CACHE_KIND
            and state.get("object_ptr") == int(obj.as_pointer())
            and state.get("mesh_ptr") == int(obj.data.as_pointer())
            and state.get("shape_key_name") == shape_key_name
            and state.get("pin_group_name") == pin_name
            and state.get("topology_key") == topology_key
            and state.get("vertex_count") == vertex_count
            and state["rest_local_positions"].shape == (vertex_count, 3)
            and state["rest_positions"].shape == (vertex_count, 3)
            and state["positions"].shape == (vertex_count, 3)
            and state["prev_positions"].shape == (vertex_count, 3)
            and state["inv_masses"].shape == (vertex_count,)
        )

    @staticmethod
    def world_gravity(gravity_dir) -> np.ndarray:
        gravity = _BonePhysics.vector3(gravity_dir, mathutils.Vector((0.0, 0.0, -1.0)))
        if gravity.length <= _MeshPhysics.EPSILON:
            return np.zeros(3, dtype=np.float32)

        gravity.normalize()
        return np.asarray((gravity.x, gravity.y, gravity.z), dtype=np.float32)

    @classmethod
    def project_distance_constraints(
        cls,
        positions: np.ndarray,
        inv_masses: np.ndarray,
        index_i: np.ndarray,
        index_j: np.ndarray,
        rest_lengths: np.ndarray,
        compliance: float,
        dt: float,
    ) -> None:
        alpha = max(float(compliance), 0.0) / (dt * dt) if dt > cls.EPSILON else 0.0
        for constraint_index in range(len(index_i)):
            i = int(index_i[constraint_index])
            j = int(index_j[constraint_index])
            wi = float(inv_masses[i])
            wj = float(inv_masses[j])
            wsum = wi + wj
            if wsum <= cls.EPSILON:
                continue

            delta = positions[i] - positions[j]
            length = float(np.linalg.norm(delta))
            if length <= cls.EPSILON:
                continue

            c = length - float(rest_lengths[constraint_index])
            dlambda = -c / (wsum + alpha)
            normal = delta / length
            if wi > 0.0:
                positions[i] += wi * dlambda * normal
            if wj > 0.0:
                positions[j] -= wj * dlambda * normal

    @classmethod
    def solve(
        cls,
        state: dict,
        obj: bpy.types.Object,
        substeps: int,
        iterations: int,
        gravity_dir,
        gravity_power: float,
        damping: float,
        stretch_compliance: float,
        bend_compliance: float,
        timing: dict | None = None,
    ) -> dict:
        stage_start = time.perf_counter() if timing is not None else None
        positions = np.ascontiguousarray(state["positions"], dtype=np.float32)
        prev_positions = np.ascontiguousarray(state["prev_positions"], dtype=np.float32)
        rest_positions = np.ascontiguousarray(state["rest_positions"], dtype=np.float32)
        inv_masses = np.ascontiguousarray(state["inv_masses"], dtype=np.float32)
        pinned = inv_masses <= cls.EPSILON
        has_pinned = bool(np.any(pinned))

        dt = _BonePhysics.scene_delta_time()
        substep_count = max(1, min(16, int(substeps)))
        iteration_count = max(0, min(64, int(iterations)))
        step_dt = dt / substep_count if substep_count > 0 else dt
        gravity = cls.world_gravity(gravity_dir) * max(float(gravity_power), 0.0)
        damping = max(0.0, min(1.0, float(damping)))
        if timing is not None:
            cls.add_timing(timing, "solve_setup", time.perf_counter() - stage_start)

        for _ in range(substep_count):
            stage_start = time.perf_counter() if timing is not None else None
            old_positions = positions.copy()
            inertia = (positions - prev_positions) * (1.0 - damping)
            positions += inertia + gravity * (step_dt * step_dt)
            prev_positions = old_positions
            if timing is not None:
                cls.add_timing(timing, "predict", time.perf_counter() - stage_start)

            if has_pinned:
                stage_start = time.perf_counter() if timing is not None else None
                positions[pinned] = rest_positions[pinned]
                prev_positions[pinned] = rest_positions[pinned]
                if timing is not None:
                    cls.add_timing(timing, "pin", time.perf_counter() - stage_start)

            for _iteration in range(iteration_count):
                stage_start = time.perf_counter() if timing is not None else None
                cls.project_distance_constraints(
                    positions,
                    inv_masses,
                    state["edge_i"],
                    state["edge_j"],
                    state["edge_rest"],
                    stretch_compliance,
                    step_dt,
                )
                if timing is not None:
                    cls.add_timing(timing, "stretch", time.perf_counter() - stage_start)

                stage_start = time.perf_counter() if timing is not None else None
                cls.project_distance_constraints(
                    positions,
                    inv_masses,
                    state["bend_i"],
                    state["bend_j"],
                    state["bend_rest"],
                    bend_compliance,
                    step_dt,
                )
                if timing is not None:
                    cls.add_timing(timing, "bend", time.perf_counter() - stage_start)

                if has_pinned:
                    stage_start = time.perf_counter() if timing is not None else None
                    positions[pinned] = rest_positions[pinned]
                    prev_positions[pinned] = rest_positions[pinned]
                    if timing is not None:
                        cls.add_timing(timing, "pin", time.perf_counter() - stage_start)

        next_state = dict(state)
        next_state["positions"] = np.ascontiguousarray(positions, dtype=np.float32)
        next_state["prev_positions"] = np.ascontiguousarray(prev_positions, dtype=np.float32)
        return next_state


@omni(
    enable=True,
    bl_label="从根获取骨链",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["根骨骼"],
    _OUTPUT_NAME=["骨链"],
    omni_description="""
    从 Bone socket 选择的根骨骼生成骨链数据。

    会递归收集根骨下面的全部子骨，不提供主干猜测或排除规则。
    如果 VRM SpringBone 需要多条独立链，应在骨架制作时拆成多个明确 root。
    输出接物理类节点的骨链输入。
    """,
)
def boneChainFromRoot(
    root_bone: _OmniBone,
) -> _OmniBoneChain:
    armature_obj, root_name = _BonePhysics.resolve_bone_value(root_bone)

    root_pose_bone = armature_obj.pose.bones.get(root_name)
    if root_pose_bone is None:
        raise ValueError(f"bone not found: {root_name}")

    return {
        "armature": armature_obj,
        "root_bone": root_name,
        "bones": _BonePhysics.collect_bone_names(root_pose_bone),
    }


@omni(
    enable=True,
    bl_label="弹簧骨-VRM链设置",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "骨链",
        "启用",
        "刚性",
        "阻力",
        "重力方向",
        "重力强度",
    ],
    input_init={
        "stiffness_force": {"min_value": 0.0, "max_value": 100.0},
        "drag_force": {"min_value": 0.0, "max_value": 1.0},
        "gravity_power": {"min_value": 0.0, "max_value": 10.0},
    },
    _OUTPUT_NAME=["VRM链设置"],
    omni_presets=[
        {
            "name": "极软拖尾",
            "values": {
                "enabled": True,
                "stiffness_force": 1.0,
                "drag_force": 0.15,
                "gravity_dir": (0.0, 0.0, -1.0),
                "gravity_power": 0.0,
            },
        },
        {
            "name": "柔软头发",
            "values": {
                "enabled": True,
                "stiffness_force": 8.0,
                "drag_force": 0.28,
                "gravity_dir": (0.0, 0.0, -1.0),
                "gravity_power": 0.08,
            },
        },
        {
            "name": "布条裙摆",
            "values": {
                "enabled": True,
                "stiffness_force": 18.0,
                "drag_force": 0.38,
                "gravity_dir": (0.0, 0.0, -1.0),
                "gravity_power": 0.35,
            },
        },
        {
            "name": "硬质挂件",
            "values": {
                "enabled": True,
                "stiffness_force": 55.0,
                "drag_force": 0.55,
                "gravity_dir": (0.0, 0.0, -1.0),
                "gravity_power": 0.15,
            },
        },
        {
            "name": "强回弹测试",
            "values": {
                "enabled": True,
                "stiffness_force": 100.0,
                "drag_force": 0.18,
                "gravity_dir": (0.0, 0.0, -1.0),
                "gravity_power": 0.0,
            },
        },
    ],
    omni_description="""
    为单条骨链生成 VRM SpringBone 解算所需的弹簧和重力参数。

    推荐一条 spring chain 对应一个本节点，再把多个“VRM链设置”输出接到“弹簧骨-VRM”的多重输入。
    本节点不写姿态、不推进时间，只打包参数；真正的模拟、缓存读写和碰撞处理都在解算器里完成。

    碰撞半径、碰撞体类型和碰撞组不在这里重复配置。
    解算器会直接读取每根模拟骨骼上的 hotools_collision 设置。
    """,
)
def springBoneVRMChainSetting(
    bone_chain: _OmniBoneChain,
    enabled: bool = True,
    stiffness_force: float = 1.0,
    drag_force: float = 0.4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 0.0,
) -> typing.Any:
    if not _BonePhysics.chain_is_valid(bone_chain):
        raise ValueError("bone_chain is invalid")

    gravity = _BonePhysics.vector3(gravity_dir, mathutils.Vector((0.0, 0.0, -1.0)))
    if gravity.length > _BonePhysics.EPSILON:
        gravity.normalize()

    return {
        "version": _BonePhysics.VRM_SPRING_BONE_CACHE_VERSION,
        "armature": bone_chain["armature"],
        "root_bone": str(bone_chain.get("root_bone") or ""),
        "bones": list(bone_chain.get("bones") or []),
        "enabled": bool(enabled),
        "stiffness_force": max(float(stiffness_force), 0.0),
        "drag_force": max(0.0, min(1.0, float(drag_force))),
        "gravity_dir": gravity,
        "gravity_power": max(float(gravity_power), 0.0),
    }


@omni(
    enable=True,
    bl_label="弹簧骨-VRM",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "缓存",
        "骨架",
        "VRM链设置",
        "场景",
        "启用",
        "重置",
        "子步数",
    ],
    input_init={
        "substeps": {"min_value": 1, "max_value": 16},
    },
    _OUTPUT_NAME=["缓存", "骨骼", "骨架", "链数量", "碰撞体数量"],
    omni_description="""
    骨架级 VRM SpringBone 解算器，统一处理多条骨链的弹簧、重力、碰撞和姿态写回。

    接法：
    1. 缓存读取节点接到本节点“缓存”，本节点输出“缓存”再接缓存写入节点。
    2. 一个 Armature 接一个“弹簧骨-VRM”；多条“弹簧骨-VRM链设置”直接接到“VRM链设置”多重输入。
    3. 场景直接作为唯一的外部碰撞来源；解算器会在内部从场景生成碰撞快照。

    运行规则：
    解算器会按 root 名排序设置，拒绝重复 root 或重复模拟同一根骨骼。
    缓存只保存这个骨架的 VRM SpringBone 状态，拓扑变化或打开“重置”时会重建状态。
    检测到跳帧或倒放时会先恢复初始姿态，并输出空缓存，让缓存写入节点清掉旧速度。
    同一帧同一骨架只允许一个不同配置的解算器写入，避免多个节点互相覆盖姿态。

    输出“骨骼”是受影响的模拟骨集合，可继续接到“骨骼姿态K帧”。
    “链数量”和“碰撞体数量”用于快速确认本帧实际参与解算的数据规模。
    """,
)
def springBoneVRM(
    cache_state: _OmniCache,
    armature_obj: bpy.types.Object,
    vrm_chain_settings: list[typing.Any],
    scene: bpy.types.Scene = None,
    enabled: bool = True,
    reset: bool = False,
    substeps: int = 1,
) -> tuple[_OmniCache, list[_OmniBone], bpy.types.Object, int, int]:
    armature_obj = _BonePhysics.require_armature(armature_obj, "armature_obj")
    scene = scene or bpy.context.scene
    current_frame = int(getattr(scene, "frame_current", bpy.context.scene.frame_current))

    settings = [
        setting
        for setting in _BonePhysics.flatten_vrm_spring_bone_chain_settings(vrm_chain_settings)
        if setting.get("armature") is armature_obj
    ]
    settings.sort(key=lambda item: str(item.get("root_bone") or ""))

    roots = set()
    for setting in settings:
        root = str(setting.get("root_bone") or "")
        if not root:
            raise ValueError("chain setting root_bone is empty")
        if root in roots:
            raise ValueError(f"duplicate VRM SpringBone root: {root}")
        roots.add(root)

    affected_bones = []
    seen_affected = set()
    for setting in settings:
        chain = {
            "armature": armature_obj,
            "root_bone": setting.get("root_bone", ""),
            "bones": list(setting.get("bones") or []),
        }
        for value in _BonePhysics.bone_socket_values_from_chain(chain):
            key = (int(armature_obj.as_pointer()), value["bone"])
            if key not in seen_affected:
                affected_bones.append(value)
                seen_affected.add(key)

    expected_bones = set()
    for setting in settings:
        chain = {
            "armature": armature_obj,
            "root_bone": setting.get("root_bone", ""),
            "bones": list(setting.get("bones") or []),
        }
        for bone_name in _BonePhysics.simulated_bone_names(chain):
            if bone_name in expected_bones:
                raise ValueError(f"duplicate simulated bone across chains: {bone_name}")
            expected_bones.add(bone_name)

    if not settings:
        return cache_state, affected_bones, armature_obj, 0, 0

    topology_key = _BonePhysics.vrm_spring_bone_topology_key(armature_obj, settings)
    state = cache_state if _BonePhysics.vrm_spring_bone_cache_matches(cache_state, armature_obj, topology_key) else None
    needs_reset = bool(reset) or not isinstance(state, dict)

    if isinstance(state, dict) and state.get("frame") is not None:
        try:
            last_frame = int(state.get("frame"))
            if current_frame not in {last_frame, last_frame + 1}:
                _BonePhysics.restore_vrm_spring_bone_initial_pose(armature_obj, state)
                return None, affected_bones, armature_obj, len(settings), 0
        except Exception:
            _BonePhysics.restore_vrm_spring_bone_initial_pose(armature_obj, state)
            return None, affected_bones, armature_obj, len(settings), 0

    if needs_reset:
        _BonePhysics.restore_vrm_spring_bone_initial_pose(armature_obj, state)
        state = _BonePhysics.build_vrm_spring_bone_state(armature_obj, settings, topology_key)

    if not enabled:
        state["frame"] = current_frame
        return state, affected_bones, armature_obj, len(settings), 0

    collision_snapshot = _BonePhysics.build_collision_snapshot_from_scene(scene, True, True, False)
    colliders = list(collision_snapshot.get("colliders") or []) if isinstance(collision_snapshot, dict) else []
    dt = _BonePhysics.scene_delta_time()
    substep_count = max(1, min(16, int(substeps)))
    step_dt = dt / substep_count if substep_count > 0 else dt

    chains_state = state.get("chains", {})
    target_pose_matrices = {}
    target_tail_worlds = {}

    for setting in settings:
        root_name = str(setting.get("root_bone") or "")
        root_pose_bone = armature_obj.pose.bones.get(root_name)
        if root_pose_bone is None:
            continue
        target_pose_matrices[root_name] = root_pose_bone.matrix.copy()
        _, root_tail_world = _BonePhysics.pose_head_tail_world(armature_obj, root_pose_bone)
        target_tail_worlds[root_name] = root_tail_world.copy()

    for _ in range(substep_count):
        next_chains_state = {}

        for setting in settings:
            root_name = str(setting.get("root_bone") or "")
            chain_state = chains_state.get(root_name)
            if not isinstance(chain_state, dict):
                continue

            bones = list(chain_state.get("bones") or [])
            joints = chain_state.get("joints") if isinstance(chain_state.get("joints"), dict) else {}
            next_joints = {}
            chain_bones = set(bones)

            if not bool(setting.get("enabled", True)):
                next_chains_state[root_name] = {
                    "bones": bones,
                    "joints": joints,
                }
                continue

            stiffness_force = max(float(setting.get("stiffness_force", 0.0)), 0.0)
            drag_force = max(0.0, min(1.0, float(setting.get("drag_force", 0.0))))
            gravity_power = max(float(setting.get("gravity_power", 0.0)), 0.0)
            gravity = _BonePhysics.vector3(setting.get("gravity_dir"), mathutils.Vector((0.0, 0.0, -1.0)))
            if gravity.length > _BonePhysics.EPSILON:
                gravity.normalize()

            chain = {
                "armature": armature_obj,
                "root_bone": root_name,
                "bones": bones,
            }
            for bone_name in _BonePhysics.simulated_bone_names(chain):
                pose_bone = armature_obj.pose.bones.get(bone_name)
                joint = joints.get(bone_name) if isinstance(joints, dict) else None
                if pose_bone is None or not isinstance(joint, dict):
                    continue

                current_head, fallback_tail = _BonePhysics.pose_head_tail_world(armature_obj, pose_bone)
                head = _BonePhysics.target_head_world(
                    armature_obj,
                    pose_bone,
                    target_pose_matrices,
                    target_tail_worlds,
                )
                current_tail, prev_tail = _BonePhysics.joint_tail_state(joint, fallback_tail)

                length = float(joint.get("length", (fallback_tail - current_head).length))
                if length <= _BonePhysics.EPSILON:
                    continue

                hit_radius, collided_by_groups = _BonePhysics.vrm_spring_bone_collision_profile(armature_obj, bone_name)
                rest_axis = _BonePhysics.rest_axis_world(
                    armature_obj,
                    pose_bone,
                    joint,
                    target_pose_matrices,
                )
                inertia = (current_tail - prev_tail) * (1.0 - drag_force)
                next_tail = (
                    current_tail
                    + inertia
                    + rest_axis * stiffness_force * step_dt
                    + gravity * gravity_power * step_dt
                )
                next_tail = _BonePhysics.project_tail_to_length(head, next_tail, length, rest_axis)
                next_tail = _BonePhysics.project_collision(
                    hit_radius,
                    collided_by_groups,
                    armature_obj,
                    chain_bones,
                    colliders,
                    head,
                    next_tail,
                    length,
                    rest_axis,
                )

                target_matrix = _BonePhysics.pose_matrix_from_tail_world(
                    armature_obj,
                    pose_bone,
                    joint,
                    head,
                    next_tail,
                )
                if target_matrix is None:
                    continue

                next_joint = dict(joint)
                next_joint["prev_tail"] = current_tail.copy()
                next_joint["current_tail"] = next_tail.copy()
                next_joints[bone_name] = next_joint
                target_pose_matrices[bone_name] = target_matrix
                target_tail_worlds[bone_name] = next_tail.copy()

            next_chains_state[root_name] = {
                "bones": bones,
                "joints": next_joints,
            }

        chains_state = next_chains_state

    for setting in settings:
        chain = {
            "armature": armature_obj,
            "root_bone": setting.get("root_bone", ""),
            "bones": list(setting.get("bones") or []),
        }
        for bone_name in _BonePhysics.simulated_bone_names(chain):
            pose_bone = armature_obj.pose.bones.get(bone_name)
            target_matrix = target_pose_matrices.get(bone_name)
            if pose_bone is None or target_matrix is None:
                continue
            pose_bone.matrix_basis = _BonePhysics.matrix_basis_from_pose_matrix(
                pose_bone,
                target_matrix,
                target_pose_matrices,
            )

    state["frame"] = current_frame
    state["chains"] = chains_state
    armature_obj.update_tag()
    return state, affected_bones, armature_obj, len(settings), len(colliders)


@omni(
    enable=True,
    bl_label="网格形态键XPBD",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "缓存",
        "物体",
        "Pin顶点组",
        "目标形态键",
        "启用",
        "重置",
        "子步数",
        "迭代",
        "重力方向",
        "重力强度",
        "阻尼",
        "拉伸顺从度",
        "弯曲顺从度",
        "调试输出",
    ],
    input_init={
        "substeps": {"min_value": 1, "max_value": 16},
        "iterations": {"min_value": 0, "max_value": 64},
        "gravity_power": {"min_value": 0.0, "max_value": 100.0},
        "damping": {"min_value": 0.0, "max_value": 1.0},
        "stretch_compliance": {"min_value": 0.0},
        "bend_compliance": {"min_value": 0.0},
        "debug_output": {"description": "开启后每隔约 1 秒在控制台打印本节点各阶段平均耗时。"},
    },
    _OUTPUT_NAME=["缓存", "物体", "顶点数", "约束数"],
    omni_description="""
    第一版无碰撞 mesh 物理节点。节点只写入指定形态键，不直接修改网格顶点。

    接法：
    1. 缓存读取节点接到本节点“缓存”，本节点输出“缓存”再写回同名缓存。
    2. “目标形态键”使用形态键 socket 选择 Mesh Object + shape key 名称；如果目标 key 不存在会自动创建。
    3. “Pin顶点组”可以为空；权重大于 0 的顶点会固定在 Basis/rest 坐标。

    跳帧规则：
    与基础弹簧骨一致，只接受 current_frame == cached_frame + 1。跳帧、倒放或同帧重复执行时，会把目标形态键恢复到 rest 坐标并输出空缓存。
    """,
)
def meshShapeKeyXPBD(
    cache_state: _OmniCache,
    obj: bpy.types.Object,
    pin_group: _OmniVertexGroup,
    target_shape_key: _OmniShapeKey,
    enabled: bool = True,
    reset: bool = False,
    substeps: int = 1,
    iterations: int = 6,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 9.8,
    damping: float = 0.02,
    stretch_compliance: float = 0.0,
    bend_compliance: float = 0.001,
    debug_output: bool = False,
) -> tuple[_OmniCache, bpy.types.Object, int, int]:
    timing = _MeshPhysics.begin_timing() if debug_output else None
    stage_start = time.perf_counter() if timing is not None else None
    obj = _MeshPhysics.require_mesh_object(obj, "obj")
    shape_obj, shape_key_name = _MeshPhysics.resolve_shape_key_value(target_shape_key, obj)
    if shape_obj != obj:
        raise ValueError("target shape key object must be the same as obj")

    pin_group = _MeshPhysics.validate_pin_group(obj, pin_group)
    target_key = _MeshPhysics.ensure_target_shape_key(obj, shape_key_name)
    if timing is not None:
        _MeshPhysics.add_timing(timing, "validate", time.perf_counter() - stage_start)

    stage_start = time.perf_counter() if timing is not None else None
    topology_key = _MeshPhysics.topology_key(obj)
    vertex_count = len(obj.data.vertices)
    state = cache_state if _MeshPhysics.state_matches(cache_state, obj, shape_key_name, pin_group, topology_key) else None
    cached_frame = _BonePhysics.cache_frame(state)
    current_frame = int(getattr(bpy.context.scene, "frame_current", 0) or 0)
    if timing is not None:
        _MeshPhysics.add_timing(timing, "cache", time.perf_counter() - stage_start)

    if cached_frame is not None and current_frame != cached_frame + 1:
        stage_start = time.perf_counter() if timing is not None else None
        _MeshPhysics.restore_rest_to_shape_key(obj, target_key, state)
        if timing is not None:
            _MeshPhysics.add_timing(timing, "restore", time.perf_counter() - stage_start)
            _MeshPhysics.publish_debug_timing(obj, shape_key_name, current_frame, vertex_count, 0, timing)
        return None, obj, vertex_count, 0

    if reset or not isinstance(state, dict):
        stage_start = time.perf_counter() if timing is not None else None
        _MeshPhysics.restore_rest_to_shape_key(obj, target_key, state)
        if timing is not None:
            _MeshPhysics.add_timing(timing, "restore", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        state = _MeshPhysics.build_state(obj, shape_key_name, pin_group, topology_key)
        if timing is not None:
            _MeshPhysics.add_timing(timing, "rebuild", time.perf_counter() - stage_start)
    else:
        stage_start = time.perf_counter() if timing is not None else None
        state = _MeshPhysics.sync_state_to_object_transform(state, obj)
        if timing is not None:
            _MeshPhysics.add_timing(timing, "transform", time.perf_counter() - stage_start)

    constraint_count = len(state["edge_i"]) + len(state["bend_i"])

    if not enabled:
        next_state = dict(state)
        next_state["frame"] = current_frame
        _MeshPhysics.publish_debug_timing(obj, shape_key_name, current_frame, vertex_count, constraint_count, timing)
        return next_state, obj, vertex_count, constraint_count

    stage_start = time.perf_counter() if timing is not None else None
    next_state = _MeshPhysics.solve(
        state,
        obj,
        substeps,
        iterations,
        gravity_dir,
        gravity_power,
        damping,
        stretch_compliance,
        bend_compliance,
        timing,
    )
    if timing is not None:
        _MeshPhysics.add_timing(timing, "solve_total", time.perf_counter() - stage_start)
    next_state["frame"] = current_frame
    stage_start = time.perf_counter() if timing is not None else None
    _MeshPhysics.write_world_positions_to_shape_key(obj, target_key, next_state["positions"])
    if timing is not None:
        _MeshPhysics.add_timing(timing, "write", time.perf_counter() - stage_start)
        _MeshPhysics.publish_debug_timing(obj, shape_key_name, current_frame, vertex_count, constraint_count, timing)
    return next_state, obj, vertex_count, constraint_count


@omni(
    enable=True,
    bl_label="弹簧骨",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "缓存",
        "骨链",
        "启用",
        "刚性",
        "阻力",
        "重力方向",
        "重力强度",
    ],
    input_init={
        "stiffness_force": {
            "description": "回弹刚性。公式里会乘以 dt，常用量级约 0/1/10/30/100。",
            "min_value": 0.0,
            "max_value": 100.0,
        },
        "drag_force": {
            "description": "UniVRM dragForce. 0 保留惯性，1 直接消除上一帧速度。",
            "min_value": 0.0,
            "max_value": 1.0,
        },
        "gravity_dir": {
            "description": "世界空间重力方向。默认 0,0,-1。",
        },
        "gravity_power": {
            "description": "沿重力方向施加的外力强度。",
            "min_value": 0.0,
            "max_value": 10.0,
        },
    },
    omni_presets=[
        {
            "name": "极软拖尾",
            "values": {
                "stiffness_force": 1.0,
                "drag_force": 0.15,
                "gravity_dir": (0.0, 0.0, -1.0),
                "gravity_power": 0.0,
            },
        },
        {
            "name": "柔软头发",
            "values": {
                "stiffness_force": 8.0,
                "drag_force": 0.28,
                "gravity_dir": (0.0, 0.0, -1.0),
                "gravity_power": 0.08,
            },
        },
        {
            "name": "布条裙摆",
            "values": {
                "stiffness_force": 18.0,
                "drag_force": 0.38,
                "gravity_dir": (0.0, 0.0, -1.0),
                "gravity_power": 0.35,
            },
        },
        {
            "name": "硬质挂件",
            "values": {
                "stiffness_force": 55.0,
                "drag_force": 0.55,
                "gravity_dir": (0.0, 0.0, -1.0),
                "gravity_power": 0.15,
            },
        },
        {
            "name": "强回弹测试",
            "values": {
                "stiffness_force": 100.0,
                "drag_force": 0.18,
                "gravity_dir": (0.0, 0.0, -1.0),
                "gravity_power": 0.0,
            },
        },
    ],
    _OUTPUT_NAME=["缓存", "骨骼", "骨架"],
    omni_description="""
    最简无碰撞 SpringBone，也是后续物理节点的范本。

    接法：
    1. 用“从根获取骨链”生成骨链，接到本节点。
    2. 缓存读取和缓存写入使用同一个缓存名，读到的缓存接本节点，输出缓存再写回。
    3. 每次执行只计算一帧，不做子步补算；dt 自动使用 render.fps / render.fps_base 的真实帧间隔。

    工作原理：
    骨链第一根骨骼只作为 center/锚点，不参与模拟；从第二根骨骼开始模拟。
    每根模拟骨在世界空间保存 tail 的 current/previous 状态，用 Verlet 推进：
    next = current + (current - previous) * (1 - drag) + rest_axis * stiffness * dt + gravity * gravity_power * dt。
    stiffness 会乘以 dt，所以它不是 0-1 参数，常用量级会落在 1、10、30、100 这种范围。
    计算后按骨长把 next tail 约束回固定长度，再为整条链生成目标 pose-space matrix。
    最后统一转换并批量写回 PoseBone.matrix_basis。

    Blender 踩坑：
    Blender 的骨骼不是 Unity Transform。PoseBone 是 head/tail 段，PoseBone.matrix 是 armature object space 的最终矩阵。
    connected 子骨的 head 由父骨 tail 推导，不能把 Unity 那套逐 Transform 写法直接搬过来。
    不要在每根骨写完后调用 view_layer.update；播放和姿态模式交互时容易撞上 viewport/selection 读 pose 数据。
    也不要批量直接写 PoseBone.matrix；connected 子骨会用旧父级求值，最终会跑偏。
    当前做法是先一次性算完整链的目标 pose matrix，再根据 parent/rest 关系转换成 matrix_basis 批量写入。

    升级版注意：
    跳帧判定保持 current_frame == cached_frame + 1，失配时清空输出 cache，避免旧速度残留。
    之后加碰撞、center、缩放补偿、多子步时，都应保持“先模拟完整链，最后批量写 matrix_basis”的结构。
    若要在 Pose Mode 下交互调试，播放期间同时写同一套 PoseBone 仍可能触发 Blender C 层崩溃，应考虑主动跳过写入或暂停每帧运行。
    """,
)
def springBoneBase(
    cache_state: _OmniCache,
    bone_chain: _OmniBoneChain,
    enabled: bool = True,
    stiffness_force: float = 1.0,
    drag_force: float = 0.4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 0.0,
) -> tuple[_OmniCache, list[_OmniBone], bpy.types.Object,]:
    if not _BonePhysics.chain_is_valid(bone_chain):
        raise ValueError("bone_chain is invalid")

    armature_obj = bone_chain["armature"]
    affected_bones = _BonePhysics.bone_socket_values_from_chain(bone_chain)
    current_frame = bpy.context.scene.frame_current
    cached_frame = _BonePhysics.cache_frame(cache_state)

    if cached_frame is not None and current_frame != cached_frame + 1:
        _BonePhysics.restore_initial_pose(armature_obj, cache_state)
        return None, affected_bones, armature_obj

    if not _BonePhysics.spring_cache_matches(cache_state, bone_chain):
        cache_state = _BonePhysics.build_spring_cache(bone_chain)

    if not enabled:
        next_cache = dict(cache_state)
        next_cache["frame"] = int(current_frame)
        return next_cache, affected_bones, armature_obj

    dt = _BonePhysics.scene_delta_time()
    stiffness_force = max(float(stiffness_force), 0.0)
    drag_force = max(0.0, min(1.0, float(drag_force)))
    gravity_power = max(float(gravity_power), 0.0)
    gravity = _BonePhysics.vector3(gravity_dir, mathutils.Vector((0.0, 0.0, -1.0)))
    if gravity.length > _BonePhysics.EPSILON:
        gravity.normalize()

    old_joints = cache_state.get("joints", {})
    next_joints = {}
    target_pose_matrices = {}
    target_tail_worlds = {}

    root_pose_bone = armature_obj.pose.bones.get(bone_chain.get("root_bone", ""))
    if root_pose_bone is not None:
        target_pose_matrices[root_pose_bone.name] = root_pose_bone.matrix.copy()
        _, root_tail_world = _BonePhysics.pose_head_tail_world(armature_obj, root_pose_bone)
        target_tail_worlds[root_pose_bone.name] = root_tail_world

    for bone_name in _BonePhysics.simulated_bone_names(bone_chain):
        pose_bone = armature_obj.pose.bones.get(bone_name)
        joint = old_joints.get(bone_name) if isinstance(old_joints, dict) else None
        if pose_bone is None or not isinstance(joint, dict):
            continue

        current_head, fallback_tail = _BonePhysics.pose_head_tail_world(armature_obj, pose_bone)
        head = _BonePhysics.target_head_world(
            armature_obj,
            pose_bone,
            target_pose_matrices,
            target_tail_worlds,
        )
        current_tail, prev_tail = _BonePhysics.joint_tail_state(joint, fallback_tail)

        length = float(joint.get("length", (fallback_tail - current_head).length))
        if length <= _BonePhysics.EPSILON:
            continue

        rest_axis = _BonePhysics.rest_axis_world(armature_obj, pose_bone, joint, target_pose_matrices)
        rest_force = rest_axis * stiffness_force * dt
        external_force = gravity * gravity_power * dt
        inertia = (current_tail - prev_tail) * (1.0 - drag_force)
        next_tail = current_tail + inertia + rest_force + external_force

        direction = next_tail - head
        if direction.length <= _BonePhysics.EPSILON:
            next_tail = fallback_tail.copy()
        else:
            next_tail = head + direction.normalized() * length

        target_matrix = _BonePhysics.pose_matrix_from_tail_world(
            armature_obj,
            pose_bone,
            joint,
            head,
            next_tail,
        )
        if target_matrix is None:
            continue

        next_joint = dict(joint)
        next_joint["prev_tail"] = current_tail.copy()
        next_joint["current_tail"] = next_tail.copy()
        next_joints[bone_name] = next_joint
        target_pose_matrices[bone_name] = target_matrix
        target_tail_worlds[bone_name] = next_tail.copy()

    for bone_name in _BonePhysics.simulated_bone_names(bone_chain):
        pose_bone = armature_obj.pose.bones.get(bone_name)
        target_matrix = target_pose_matrices.get(bone_name)
        if pose_bone is None or target_matrix is None:
            continue
        pose_bone.matrix_basis = _BonePhysics.matrix_basis_from_pose_matrix(
            pose_bone,
            target_matrix,
            target_pose_matrices,
        )

    next_cache = dict(cache_state)
    next_cache["frame"] = int(current_frame)
    next_cache["joints"] = next_joints
    armature_obj.update_tag()
    return next_cache, affected_bones, armature_obj


@omni(
    enable=True,
    bl_label="骨骼姿态K帧",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["骨骼", "启用"],
    _OUTPUT_NAME=["骨骼", "写入数量"],
    omni_description="""
    给输入 Bone 集合中的 PoseBone 在当前帧插入姿态关键帧。

    接法：
    1. SpringBone 的“骨骼”输出接到本节点“骨骼”输入。
    2. 本节点的“骨骼”输入是多重输入，可以接一条或多条物理链。
    3. 启用为 False 时只透传骨骼列表，不写关键帧。

    写入内容：
    对每根 PoseBone 插入 location、rotation、scale。
    rotation 会根据当前 rotation_mode 选择 rotation_quaternion、rotation_axis_angle 或 rotation_euler。

    注意：
    本节点只负责把当前已经写入 PoseBone 的姿态 K 到当前帧。
    bake 时建议用稳定的逐帧播放/运行流程，不要在同一帧手动反复执行。
    """,
)
def keyframePoseBones(
    bones: list[_OmniBone],
    enabled: bool = True,
) -> tuple[list[_OmniBone], int]:
    bone_values = _BonePhysics.flatten_bone_socket_values(bones)
    if not enabled:
        return bone_values, 0

    frame = bpy.context.scene.frame_current
    inserted = 0
    for value in bone_values:
        try:
            armature_obj, bone_name = _BonePhysics.resolve_bone_value(value)
        except Exception:
            continue

        pose_bone = armature_obj.pose.bones.get(bone_name)
        if pose_bone is None:
            continue

        pose_bone.keyframe_insert(data_path="location", frame=frame)
        if pose_bone.rotation_mode == "QUATERNION":
            pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
        elif pose_bone.rotation_mode == "AXIS_ANGLE":
            pose_bone.keyframe_insert(data_path="rotation_axis_angle", frame=frame)
        else:
            pose_bone.keyframe_insert(data_path="rotation_euler", frame=frame)
        pose_bone.keyframe_insert(data_path="scale", frame=frame)
        inserted += 1

    return bone_values, inserted
