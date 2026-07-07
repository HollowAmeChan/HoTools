from ..OmniNodeSocketMapping import (
    _OmniBone,
    _OmniCache,
)
from ..OmniRuntimeState import OmniCacheOwnerDict, cache_visible_value
from ....PhysicsTools.deltaOutput import PhysicsDeltaOutputSpec
from ....PhysicsTools.deltaOutput import clear_delta_attribute as _clear_delta_attribute
from ....PhysicsTools.deltaOutput import ensure_delta_output as _ensure_delta_output
from ....PhysicsTools.deltaOutput import write_world_delta_attribute as _write_world_delta_attribute
from ..OmniDebug import OmniDebug
from ..FunctionNodeCore import omni
from . import _Color

import bpy
import hashlib
import importlib
import mathutils
import numpy as np
import time
import typing


def _as_cache_owner(payload):
    """
    把物理 state payload 规范成零拷贝缓存 owner。

    - None 原样返回（表示清空缓存，走正常 replace/删除路径）。
    - 已经是 OmniCacheOwnerDict 的原样返回。
    - 普通 dict 就地包成 OmniCacheOwnerDict（浅包装，不深拷贝内部）。

    只作用于物理节点的缓存产出边界，不改动全局缓存语义。
    """
    if payload is None or isinstance(payload, OmniCacheOwnerDict):
        return payload
    if isinstance(payload, dict):
        return OmniCacheOwnerDict(payload)
    return payload


_MESH_XPBD_PRESETS = [
    {
        "name": "高速预览",
        "values": {
            "enabled": True,
            "substeps": 1,
            "iterations": 3,
            "gravity_dir": (0.0, 0.0, -1.0),
            "gravity_power": 9.8,
            "damping": 0.02,
            "stretch_compliance": 0.00192494408,
            "bend_compliance": 0.01439117011,
        },
    },
    {
        "name": "柔软形变",
        "values": {
            "enabled": True,
            "substeps": 2,
            "iterations": 5,
            "gravity_dir": (0.0, 0.0, -1.0),
            "gravity_power": 9.8,
            "damping": 0.015,
            "stretch_compliance": 0.00193348828,
            "bend_compliance": 0.01529983597,
        },
    },
    {
        "name": "通用布料",
        "values": {
            "enabled": True,
            "substeps": 2,
            "iterations": 6,
            "gravity_dir": (0.0, 0.0, -1.0),
            "gravity_power": 9.8,
            "damping": 0.04,
            "stretch_compliance": 0.001325804863,
            "bend_compliance": 0.006076554066,
        },
    },
    {
        "name": "碰撞稳定",
        "values": {
            "enabled": True,
            "substeps": 4,
            "iterations": 8,
            "gravity_dir": (0.0, 0.0, -1.0),
            "gravity_power": 9.8,
            "damping": 0.08,
            "stretch_compliance": 0.0007713117649,
            "bend_compliance": 0.003137045928,
        },
    },
    {
        "name": "硬约束",
        "values": {
            "enabled": True,
            "substeps": 4,
            "iterations": 10,
            "gravity_dir": (0.0, 0.0, -1.0),
            "gravity_power": 9.8,
            "damping": 0.06,
            "stretch_compliance": 0.0007368023751,
            "bend_compliance": 0.002343968898,
        },
    },
]


_SPRING_BONE_VRM_PRESETS = [
    {
        "name": "标准",
        "values": {
            "enabled": True,
            "reset": False,
            "substeps": 1,
        },
    },
    {
        "name": "高稳定",
        "values": {
            "enabled": True,
            "reset": False,
            "substeps": 4,
        },
    },
    {
        "name": "重置缓存",
        "values": {
            "enabled": True,
            "reset": True,
            "substeps": 1,
        },
    },
]


class _BonePhysics:
    EPSILON = 0.000001

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
    def scene_delta_time(scene: bpy.types.Scene = None) -> float:
        """
        从场景输出设置读取真实帧间隔。
        SpringBone 不暴露 dt 输入，统一跟随 render.fps / render.fps_base。
        """
        scene = scene or bpy.context.scene
        render = scene.render
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
    def bone_is_effectively_pinned(cls, armature_obj: bpy.types.Object, bone_name: str, root_name: str = "") -> bool:
        """
        判断骨骼是否在当前物理链中固定。
        链 root（即 root_name，来自节点输入的骨链根，非骨骼上的持久标记）是硬 Pin；
        非 root 只在 cache 构建时读取 hotools_collision.pin，不在模拟中热更新。
        """
        if bone_name and bone_name == root_name:
            return True

        bone = armature_obj.data.bones.get(bone_name) if armature_obj.data is not None else None
        props = getattr(bone, "hotools_collision", None) if bone is not None else None
        return bool(props is not None and getattr(props, "pin", False))

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
    def bone_socket_values_from_chain(cls, chain, include_root: bool = False) -> list[dict]:
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
    def spring_joint_from_pose(cls, armature_obj: bpy.types.Object, bone_name: str, pinned: bool = False):
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
            "pinned": bool(pinned),
        }

    @classmethod
    def build_spring_cache(cls, chain):
        """
        为整条骨链创建 SpringBone cache。
        cache 记录链结构和每个模拟骨的初始状态，链结构变化时会重新生成。
        """
        armature_obj = chain["armature"]
        joints = {}
        root_name = str(chain.get("root_bone") or "")
        for bone_name in cls.simulated_bone_names(chain):
            joint = cls.spring_joint_from_pose(
                armature_obj,
                bone_name,
                pinned=cls.bone_is_effectively_pinned(armature_obj, bone_name, root_name),
            )
            if joint is not None:
                joints[bone_name] = joint

        return {
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
        Armature、root、骨骼列表或必要字段任一变化都需要丢弃旧物理状态。
        """
        if not isinstance(cache, dict):
            return False
        return (
            cache.get("space") == "WORLD"
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
    def pinned_joint_state(cls, armature_obj: bpy.types.Object, pose_bone, joint) -> tuple[mathutils.Matrix, mathutils.Vector, dict]:
        """
        生成固定骨骼本帧应该使用的姿态和 joint 状态。
        Pin 固定的是当前输入姿态，不做 Verlet 推进，并清掉速度残留。
        """
        _, tail_world = cls.pose_head_tail_world(armature_obj, pose_bone)
        next_joint = dict(joint)
        next_joint["current_tail"] = tail_world.copy()
        next_joint["prev_tail"] = tail_world.copy()
        return pose_bone.matrix.copy(), tail_world.copy(), next_joint

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
            if (
                isinstance(value, dict)
                and isinstance(value.get("armature"), bpy.types.Object)
                and isinstance(value.get("bones"), list)
                and str(value.get("root_bone") or "")
            ):
                result.append(value)
        return result

    @classmethod
    def bone_chains_from_bone_values(cls, values) -> list[dict]:
        result = []
        if values is None:
            return result

        bone_values = []
        stack = list(values) if isinstance(values, (list, tuple)) else [values]
        while stack:
            value = stack.pop(0)
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                stack[0:0] = list(value)
                continue

            cls.resolve_bone_value(value)
            bone_values.append(value)

        metadata_keys = set()
        direct_values = []
        for value in bone_values:
            armature_obj, bone_name = cls.resolve_bone_value(value)
            collection_root = str(value.get("bone_collection_root") or "").strip()
            collection_value = value.get("bone_collection")
            if collection_root and isinstance(collection_value, list):
                collection_bones = [str(name).strip() for name in collection_value if str(name).strip()]
                if collection_bones:
                    key = (int(armature_obj.as_pointer()), collection_root, tuple(collection_bones))
                    if key not in metadata_keys:
                        metadata_keys.add(key)
                        result.append(cls._chain_from_bone_names(armature_obj, collection_root, collection_bones))
                    continue
            direct_values.append((armature_obj, bone_name))

        result.extend(cls._chains_from_direct_bone_values(direct_values))
        return result

    @classmethod
    def bone_chain_from_bone_values(cls, values) -> dict:
        chains = cls.bone_chains_from_bone_values(values)
        if not chains:
            raise ValueError("bone input is empty")
        if len(chains) > 1:
            raise ValueError("expected exactly one bone chain")
        chain = chains[0]
        if not cls.chain_is_valid(chain):
            raise ValueError("bone chain is invalid")
        return chain

    @classmethod
    def _chain_bone_names_from_root(cls, armature_obj: bpy.types.Object, root_name: str) -> list[str]:
        root_pose_bone = armature_obj.pose.bones.get(root_name)
        if root_pose_bone is None:
            raise ValueError(f"bone not found: {root_name}")
        return cls.collect_bone_names(root_pose_bone)

    @classmethod
    def _chain_from_bone_names(cls, armature_obj: bpy.types.Object, root_name: str, bone_names: list[str]) -> dict:
        chain_bones = []
        seen = set()
        for bone_name in bone_names:
            bone_name = str(bone_name or "").strip()
            if not bone_name or bone_name in seen:
                continue
            if armature_obj.pose.bones.get(bone_name) is None:
                continue
            seen.add(bone_name)
            chain_bones.append(bone_name)
        if root_name and root_name not in seen and armature_obj.pose.bones.get(root_name) is not None:
            chain_bones.insert(0, root_name)
        if not chain_bones:
            chain_bones = cls._chain_bone_names_from_root(armature_obj, root_name)
        return {
            "armature": armature_obj,
            "root_bone": str(root_name or ""),
            "bones": chain_bones,
        }

    @classmethod
    def _bone_is_descendant_or_self(cls, armature_obj: bpy.types.Object, bone_name: str, root_name: str) -> bool:
        pose_bone = armature_obj.pose.bones.get(bone_name)
        while pose_bone is not None:
            if pose_bone.name == root_name:
                return True
            pose_bone = getattr(pose_bone, "parent", None)
        return False

    @classmethod
    def _chains_from_direct_bone_values(cls, values: list[tuple[bpy.types.Object, str]]) -> list[dict]:
        if not values:
            return []

        groups = []
        group_index = {}
        for armature_obj, bone_name in values:
            key = int(armature_obj.as_pointer())
            if key not in group_index:
                group_index[key] = len(groups)
                groups.append((armature_obj, []))
            groups[group_index[key]][1].append(bone_name)

        result = []
        for armature_obj, bone_names in groups:
            ordered_names = []
            seen = set()
            for bone_name in bone_names:
                if bone_name not in seen:
                    seen.add(bone_name)
                    ordered_names.append(bone_name)

            provided = set(ordered_names)
            has_parent_link = False
            for bone_name in ordered_names:
                pose_bone = armature_obj.pose.bones.get(bone_name)
                parent = getattr(pose_bone, "parent", None) if pose_bone is not None else None
                if parent is not None and parent.name in provided:
                    has_parent_link = True
                    break

            if not has_parent_link:
                for bone_name in ordered_names:
                    result.append(cls._chain_from_bone_names(
                        armature_obj,
                        bone_name,
                        cls._chain_bone_names_from_root(armature_obj, bone_name),
                    ))
                continue

            roots = []
            for bone_name in ordered_names:
                pose_bone = armature_obj.pose.bones.get(bone_name)
                parent = getattr(pose_bone, "parent", None) if pose_bone is not None else None
                if parent is None or parent.name not in provided:
                    roots.append(bone_name)
            if not roots and ordered_names:
                roots.append(ordered_names[0])

            for root_name in roots:
                chain_bones = [
                    bone_name
                    for bone_name in ordered_names
                    if cls._bone_is_descendant_or_self(armature_obj, bone_name, root_name)
                ]
                result.append(cls._chain_from_bone_names(armature_obj, root_name, chain_bones))
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

        # 包成零拷贝缓存 owner：读/写/提交均不深拷贝，逐帧原地滚动。
        return OmniCacheOwnerDict({
            "frame": None,
            "armature_name": armature_obj.name_full,
            "topology_key": topology_key,
            "chains": chains,
            "write_records": cls.build_vrm_spring_bone_write_records(armature_obj, settings),
        })

    @classmethod
    def build_vrm_spring_bone_write_records(cls, armature_obj: bpy.types.Object, settings: list[dict]) -> list[dict]:
        records = []
        seen = set()
        pose_bone_collection = armature_obj.pose.bones
        pose_bones = list(pose_bone_collection)
        pose_index_by_name = {pose_bone.name: index for index, pose_bone in enumerate(pose_bones)}
        for setting in settings:
            chain = {
                "armature": armature_obj,
                "root_bone": setting.get("root_bone", ""),
                "bones": list(setting.get("bones") or []),
            }
            for bone_name in cls.simulated_bone_names(chain):
                if bone_name in seen:
                    continue
                pose_bone = pose_bone_collection.get(bone_name)
                if pose_bone is None:
                    continue
                parent = getattr(pose_bone, "parent", None)
                bone_rest = pose_bone.bone.matrix_local.copy()
                records.append(
                    {
                        "bone_name": bone_name,
                        "pose_bone": pose_bone,
                        "pose_index": int(pose_index_by_name.get(bone_name, -1)),
                        "parent": parent,
                        "parent_name": parent.name if parent is not None else "",
                        "bone_rest": bone_rest,
                        "bone_rest_inv": bone_rest.inverted(),
                        "parent_rest_inv": parent.bone.matrix_local.inverted() if parent is not None else None,
                    }
                )
                seen.add(bone_name)
        return records

    @classmethod
    def vrm_spring_bone_write_records_match(
        cls,
        armature_obj: bpy.types.Object,
        settings: list[dict],
        records,
    ) -> bool:
        if not isinstance(records, list) or armature_obj.pose is None:
            return False

        def same_bpy_ref(left, right) -> bool:
            if left is right:
                return True
            if left is None or right is None:
                return False
            left_pointer = getattr(left, "as_pointer", None)
            right_pointer = getattr(right, "as_pointer", None)
            if callable(left_pointer) and callable(right_pointer):
                return int(left_pointer()) == int(right_pointer())
            return False

        pose_bone_collection = armature_obj.pose.bones
        pose_bones = list(pose_bone_collection)
        expected_names = []
        seen = set()
        for setting in settings:
            chain = {
                "armature": armature_obj,
                "root_bone": setting.get("root_bone", ""),
                "bones": list(setting.get("bones") or []),
            }
            for bone_name in cls.simulated_bone_names(chain):
                if bone_name in seen:
                    continue
                if pose_bone_collection.get(bone_name) is not None:
                    expected_names.append(bone_name)
                    seen.add(bone_name)

        if [str(record.get("bone_name") or "") for record in records if isinstance(record, dict)] != expected_names:
            return False

        for record in records:
            if not isinstance(record, dict):
                return False
            bone_name = str(record.get("bone_name") or "")
            pose_bone = pose_bone_collection.get(bone_name)
            if pose_bone is None or not same_bpy_ref(record.get("pose_bone"), pose_bone):
                return False
            pose_index = int(record.get("pose_index", -1))
            if pose_index < 0 or pose_index >= len(pose_bones) or pose_bones[pose_index].name != bone_name:
                return False
            parent = getattr(pose_bone, "parent", None)
            parent_name = parent.name if parent is not None else ""
            if not same_bpy_ref(record.get("parent"), parent) or str(record.get("parent_name") or "") != parent_name:
                return False
        return True

    @classmethod
    def vrm_spring_bone_cache_matches(cls, cache, armature_obj: bpy.types.Object, topology_key: tuple) -> bool:
        if not isinstance(cache, dict):
            return False
        return (
            cache.get("armature_name") == armature_obj.name_full
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
        """
        旧蓝本碰撞快照消费类型：SPHERE、CAPSULE。
        数据来源是 PhysicsTools 挂在 Object 上的 hotools_object_collision，以及 Armature Bone 上的 hotools_collision。
        SPHERE 读取 collision_type、radius、offset、primary_collision_group；CAPSULE 额外读取 length，并沿局部 Y 轴生成世界线段。
        """
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
        # 快照枚举场景中的 Object 与 Armature Bone；可消费类型和字段集中由 collider_from_matrix 声明。
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
        """
        旧 SpringBone 蓝本的骨骼 hit radius 消费类型：SPHERE、CAPSULE。
        数据来自模拟骨骼自身的 hotools_collision，读取 radius 和 collided_by_groups。
        """
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
        """
        对 SpringBone tail 投影被动碰撞；当前只识别快照中的 SPHERE/CAPSULE。
        快照来自 build_collision_snapshot_from_scene，读取 Object.hotools_object_collision 和 Bone.hotools_collision。
        """
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
    CACHE_KIND = "MESH_PHYSICS_XPBD"
    DEBUG_PRINT_INTERVAL = 1.0
    OUTPUT_KEY = "XPBDDelta"
    DELTA_ATTRIBUTE_NAME = "xpbd_delta"
    DELTA_MODIFIER_NAME = "XPBD 后置位移"
    DELTA_NODE_GROUP_NAME = "HoTools_XPBD_ApplyDelta"
    DELTA_OUTPUT_SPEC = PhysicsDeltaOutputSpec(
        attribute_name=DELTA_ATTRIBUTE_NAME,
        modifier_name=DELTA_MODIFIER_NAME,
        node_group_name=DELTA_NODE_GROUP_NAME,
        label="XPBD 后置位移",
    )
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
        output_key: str,
        frame: int,
        vertex_count: int,
        constraint_count: int,
        backend_tag: str,
        timing: dict | None,
    ) -> None:
        if timing is None:
            return

        now = time.perf_counter()
        stages = dict(timing.get("stages") or {})
        stages["total"] = max(now - float(timing.get("start", now)), 0.0)

        key = (int(obj.as_pointer()), str(output_key), str(backend_tag))
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
            "colliders",
            "solve_setup",
            "collision_setup",
            "predict",
            "pin",
            "stretch",
            "bend",
            "collision",
            "native",
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
            f"[MeshPhysicsXPBD:{backend_tag}] "
            f"obj={obj.name_full} key={output_key} frame={profile['frame']} "
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

    @staticmethod
    def read_reference_key_positions(key: bpy.types.ShapeKey, vertex_count: int) -> np.ndarray:
        values = np.empty(vertex_count * 3, dtype=np.float32)
        key.data.foreach_get("co", values)
        return values.reshape((vertex_count, 3))

    @classmethod
    def read_rest_positions(cls, obj: bpy.types.Object) -> np.ndarray:
        mesh = obj.data
        vertex_count = len(mesh.vertices)
        shape_keys = mesh.shape_keys
        if shape_keys is not None and shape_keys.reference_key is not None:
            return cls.read_reference_key_positions(shape_keys.reference_key, vertex_count)

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

    @classmethod
    def ensure_delta_output(cls, obj: bpy.types.Object) -> None:
        _ensure_delta_output(obj, cls.DELTA_OUTPUT_SPEC)

    @classmethod
    def clear_delta_attribute(cls, obj: bpy.types.Object) -> None:
        _clear_delta_attribute(obj, cls.DELTA_OUTPUT_SPEC)

    @classmethod
    def write_world_delta_attribute(
        cls,
        obj: bpy.types.Object,
        positions: np.ndarray,
        base_positions: np.ndarray,
    ) -> None:
        _write_world_delta_attribute(obj, cls.DELTA_OUTPUT_SPEC, positions, base_positions)

    @staticmethod
    def topology_signature(obj: bpy.types.Object) -> tuple:
        """廉价拓扑签名：仅指针 + 顶点/边/面数量，不拉边索引、不算 SHA1。
        播放期间拓扑不变，这个签名逐帧稳定，用来跳过昂贵的 edge_hash 重算。"""
        mesh = obj.data
        return (
            int(obj.as_pointer()),
            int(mesh.as_pointer()),
            len(mesh.vertices),
            len(mesh.edges),
            len(mesh.polygons),
        )

    @staticmethod
    def topology_key(obj: bpy.types.Object, prev_state=None) -> tuple:
        sig = _MeshPhysics.topology_signature(obj)
        # 复用上一帧已算好的完整 key：廉价签名一致就直接沿用，跳过 SHA1。
        # 拓扑只在用户编辑网格时变，播放期间每帧重算 SHA1 是纯浪费。
        if isinstance(prev_state, dict):
            prev_key = prev_state.get("topology_key")
            if isinstance(prev_key, tuple) and len(prev_key) == 6 and prev_key[:5] == sig:
                return prev_key
        mesh = obj.data
        edge_values = np.empty(len(mesh.edges) * 2, dtype=np.int32)
        if len(edge_values) > 0:
            mesh.edges.foreach_get("vertices", edge_values)
        edge_hash = hashlib.sha1(edge_values.tobytes()).hexdigest()
        return sig + (edge_hash,)

    @staticmethod
    def mesh_pin_config(obj: bpy.types.Object) -> tuple[bool, str]:
        props = getattr(obj, "hotools_mesh_collision", None)
        if props is None or not bool(getattr(props, "pin_enabled", False)):
            return False, ""
        return True, str(getattr(props, "pin_vertex_group", "") or "")

    @staticmethod
    def vertex_group_weights(obj: bpy.types.Object, group_name: str) -> np.ndarray:
        weights = np.zeros(len(obj.data.vertices), dtype=np.float32)
        if not group_name:
            weights.fill(1.0)
            return weights

        vertex_group = obj.vertex_groups.get(group_name)
        if vertex_group is None:
            return weights

        group_index = int(vertex_group.index)
        for vertex in obj.data.vertices:
            for group in vertex.groups:
                if group.group == group_index:
                    weights[vertex.index] = max(0.0, min(1.0, float(group.weight)))
                    break
        return weights

    @classmethod
    def build_inv_masses(cls, obj: bpy.types.Object) -> np.ndarray:
        inv_masses = np.ones(len(obj.data.vertices), dtype=np.float32)
        pin_enabled, pin_group_name = cls.mesh_pin_config(obj)
        if not pin_enabled:
            return inv_masses

        if not pin_group_name:
            inv_masses.fill(0.0)
            return inv_masses

        inv_masses[cls.vertex_group_weights(obj, pin_group_name) > 0.0] = 0.0
        return inv_masses

    @classmethod
    def build_self_collision_inv_masses(cls, obj: bpy.types.Object) -> np.ndarray:
        props = cls.mesh_collision_props(obj)
        inv_masses = np.ones(len(obj.data.vertices), dtype=np.float32)
        if props is None:
            return inv_masses
        if not bool(getattr(props, "self_collision_enabled", False)):
            return inv_masses

        friction = np.zeros(len(obj.data.vertices), dtype=np.float32)
        cloth_mass = max(float(getattr(props, "mass", 0.0)), 0.0)
        fixed = cls.build_inv_masses(obj) <= cls.EPSILON
        inv_masses[fixed] = 0.0
        movable = ~fixed
        inv_masses[movable] = 1.0 / np.maximum(
            1.0 + friction[movable] * 10.0 + cloth_mass * 50.0,
            cls.EPSILON,
        )
        return inv_masses

    @staticmethod
    def mesh_collision_props(obj: bpy.types.Object):
        return getattr(obj, "hotools_mesh_collision", None)

    @classmethod
    def build_collision_profile(cls, obj: bpy.types.Object) -> tuple[np.ndarray, int]:
        props = cls.mesh_collision_props(obj)
        radii = np.zeros(len(obj.data.vertices), dtype=np.float32)
        if props is None or not bool(getattr(props, "enabled", False)):
            return radii, 0

        radius = max(float(getattr(props, "radius", 0.0)), 0.0)
        if radius <= cls.EPSILON:
            return radii, 0

        weights = cls.vertex_group_weights(obj, str(getattr(props, "radius_vertex_group", "") or ""))
        radii = np.ascontiguousarray(weights * radius, dtype=np.float32)
        mask = _BonePhysics.clamp_group_mask(getattr(props, "collided_by_groups", 0))
        return radii, mask

    @classmethod
    def collision_radii_to_world(cls, obj: bpy.types.Object, local_radii: np.ndarray) -> np.ndarray:
        scale = _BonePhysics.matrix_scale_radius(obj.matrix_world)
        return np.ascontiguousarray(local_radii * scale, dtype=np.float32)

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
        topology_key: tuple,
    ) -> dict:
        rest_local_positions = cls.read_rest_positions(obj)
        rest_positions = cls.local_positions_to_world(obj, rest_local_positions)
        edge_i, edge_j, edge_rest = cls.build_edge_constraints(obj.data, rest_positions)
        bend_i, bend_j, bend_rest = cls.build_bend_constraints(obj.data, rest_positions)
        pin_enabled, pin_group_name = cls.mesh_pin_config(obj)
        inv_masses = cls.build_inv_masses(obj)
        collision_local_radii, collision_mask = cls.build_collision_profile(obj)
        return {
            "kind": cls.CACHE_KIND,
            "frame": None,
            "object_name": obj.name_full,
            "object_ptr": int(obj.as_pointer()),
            "mesh_ptr": int(obj.data.as_pointer()),
            "pin_enabled": bool(pin_enabled),
            "pin_group_name": pin_group_name,
            "collision_local_radii": collision_local_radii,
            "collision_radii": cls.collision_radii_to_world(obj, collision_local_radii),
            "collided_by_groups": int(collision_mask),
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
            next_state["collision_radii"] = cls.collision_radii_to_world(obj, next_state["collision_local_radii"])
            next_state["object_matrix_world_3x3_key"] = matrix_3x3_key

        return next_state

    @classmethod
    def state_matches(
        cls,
        state,
        obj: bpy.types.Object,
        topology_key: tuple,
    ) -> bool:
        if not isinstance(state, dict):
            return False
        vertex_count = len(obj.data.vertices)
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
            "collision_local_radii",
            "collision_radii",
        )
        if not all(isinstance(state.get(key), np.ndarray) for key in required):
            return False
        return (
            state.get("kind") == cls.CACHE_KIND
            and state.get("object_ptr") == int(obj.as_pointer())
            and state.get("mesh_ptr") == int(obj.data.as_pointer())
            and state.get("topology_key") == topology_key
            and state.get("vertex_count") == vertex_count
            and state["rest_local_positions"].shape == (vertex_count, 3)
            and state["rest_positions"].shape == (vertex_count, 3)
            and state["positions"].shape == (vertex_count, 3)
            and state["prev_positions"].shape == (vertex_count, 3)
            and state["inv_masses"].shape == (vertex_count,)
            and state["collision_local_radii"].shape == (vertex_count,)
            and state["collision_radii"].shape == (vertex_count,)
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

    @staticmethod
    def vector_to_numpy(value) -> np.ndarray | None:
        if value is None:
            return None
        if isinstance(value, np.ndarray):
            return np.asarray(value, dtype=np.float32).reshape(3)
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return np.asarray((float(value[0]), float(value[1]), float(value[2])), dtype=np.float32)
        return np.asarray((float(value.x), float(value.y), float(value.z)), dtype=np.float32)

    @staticmethod
    def matrix4_to_numpy(matrix: mathutils.Matrix) -> np.ndarray:
        return np.asarray(
            [[float(matrix[row][col]) for col in range(4)] for row in range(4)],
            dtype=np.float32,
        )

    @staticmethod
    def quaternion_to_numpy(quat: mathutils.Quaternion) -> np.ndarray:
        return np.asarray((float(quat.x), float(quat.y), float(quat.z), float(quat.w)), dtype=np.float32)

    @classmethod
    def closest_point_on_segment_np(cls, point: np.ndarray, segment_a, segment_b) -> np.ndarray | None:
        a = cls.vector_to_numpy(segment_a)
        b = cls.vector_to_numpy(segment_b)
        if a is None or b is None:
            return None

        segment = b - a
        denom = float(np.dot(segment, segment))
        if denom <= cls.EPSILON:
            return a

        t = float(np.dot(point - a, segment) / denom)
        t = max(0.0, min(1.0, t))
        return a + segment * t

    @classmethod
    def safe_normal_np(cls, delta: np.ndarray, fallback: np.ndarray) -> np.ndarray:
        length = float(np.linalg.norm(delta))
        if length > cls.EPSILON:
            return delta / length

        fallback_length = float(np.linalg.norm(fallback))
        if fallback_length > cls.EPSILON:
            return fallback / fallback_length

        return np.asarray((0.0, 0.0, 1.0), dtype=np.float32)

    @classmethod
    def project_vertex_collision(
        cls,
        position: np.ndarray,
        hit_radius: float,
        collided_by_groups: int,
        colliders: list[dict],
        owner_obj: bpy.types.Object,
        fallback: np.ndarray,
    ) -> np.ndarray:
        """
        Python 版网格 XPBD 的被动碰撞投影。
        消费类型：build_collision_snapshot_from_scene 生成的 SPHERE、CAPSULE。
        """
        if hit_radius <= cls.EPSILON or not collided_by_groups:
            return position

        projected = position.copy()
        for collider in colliders:
            if not isinstance(collider, dict):
                continue
            if collider.get("owner") is owner_obj:
                continue
            if not collided_by_groups & _BonePhysics.collision_group_bit(collider.get("primary_group", 1)):
                continue

            collider_radius = max(float(collider.get("radius", 0.0)), 0.0)
            radius = float(hit_radius) + collider_radius
            if radius <= cls.EPSILON:
                continue

            if collider.get("type") == "CAPSULE":
                center = cls.closest_point_on_segment_np(
                    projected,
                    collider.get("segment_a"),
                    collider.get("segment_b"),
                )
            else:
                center = cls.vector_to_numpy(collider.get("center"))
            if center is None:
                continue

            delta = projected - center
            if float(np.dot(delta, delta)) >= radius * radius:
                continue

            normal = cls.safe_normal_np(delta, fallback)
            projected = center + normal * radius

        return projected

    @classmethod
    def project_collisions(
        cls,
        positions: np.ndarray,
        rest_positions: np.ndarray,
        inv_masses: np.ndarray,
        collision_radii: np.ndarray,
        collided_by_groups: int,
        colliders: list[dict] | None,
        owner_obj: bpy.types.Object,
    ) -> None:
        if not colliders or not collided_by_groups:
            return

        for vertex_index in range(len(positions)):
            if float(inv_masses[vertex_index]) <= cls.EPSILON:
                continue
            hit_radius = float(collision_radii[vertex_index])
            if hit_radius <= cls.EPSILON:
                continue

            positions[vertex_index] = cls.project_vertex_collision(
                positions[vertex_index],
                hit_radius,
                collided_by_groups,
                colliders,
                owner_obj,
                positions[vertex_index] - rest_positions[vertex_index],
            )

    @classmethod
    def solve(
        cls,
        state: dict,
        obj: bpy.types.Object,
        scene: bpy.types.Scene,
        substeps: int,
        iterations: int,
        gravity_dir,
        gravity_power: float,
        damping: float,
        stretch_compliance: float,
        bend_compliance: float,
        timing: dict | None = None,
        colliders: list[dict] | None = None,
    ) -> dict:
        stage_start = time.perf_counter() if timing is not None else None
        positions = np.ascontiguousarray(state["positions"], dtype=np.float32)
        prev_positions = np.ascontiguousarray(state["prev_positions"], dtype=np.float32)
        rest_positions = np.ascontiguousarray(state["rest_positions"], dtype=np.float32)
        inv_masses = np.ascontiguousarray(state["inv_masses"], dtype=np.float32)
        collision_radii = np.ascontiguousarray(state["collision_radii"], dtype=np.float32)
        collided_by_groups = _BonePhysics.clamp_group_mask(state.get("collided_by_groups", 0))
        has_collision = bool(colliders) and bool(collided_by_groups) and bool(np.any(collision_radii > cls.EPSILON))
        pinned = inv_masses <= cls.EPSILON
        has_pinned = bool(np.any(pinned))

        dt = _BonePhysics.scene_delta_time(scene)
        substep_count = max(1, min(16, int(substeps)))
        iteration_count = max(0, min(64, int(iterations)))
        step_dt = dt / substep_count if substep_count > 0 else dt
        gravity = cls.world_gravity(gravity_dir) * max(float(gravity_power), 0.0)
        damping = max(0.0, min(1.0, float(damping)))
        substep_damping = 1.0 - ((1.0 - damping) ** (1.0 / substep_count))
        if timing is not None:
            cls.add_timing(timing, "solve_setup", time.perf_counter() - stage_start)

        for _ in range(substep_count):
            stage_start = time.perf_counter() if timing is not None else None
            old_positions = positions.copy()
            inertia = (positions - prev_positions) * (1.0 - substep_damping)
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

            if has_collision:
                stage_start = time.perf_counter() if timing is not None else None
                cls.project_collisions(
                    positions,
                    rest_positions,
                    inv_masses,
                    collision_radii,
                    collided_by_groups,
                    colliders,
                    obj,
                )
                if timing is not None:
                    cls.add_timing(timing, "collision", time.perf_counter() - stage_start)

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

                if has_collision:
                    stage_start = time.perf_counter() if timing is not None else None
                    cls.project_collisions(
                        positions,
                        rest_positions,
                        inv_masses,
                        collision_radii,
                        collided_by_groups,
                        colliders,
                        obj,
                    )
                    if timing is not None:
                        cls.add_timing(timing, "collision", time.perf_counter() - stage_start)

        next_state = dict(state)
        next_state["positions"] = np.ascontiguousarray(positions, dtype=np.float32)
        next_state["prev_positions"] = np.ascontiguousarray(prev_positions, dtype=np.float32)
        return next_state

class _MeshPhysicsCppBackend:
    _native_module = None

    @classmethod
    def native_module(cls):
        if cls._native_module is None:
            cls._native_module = importlib.import_module("hotools_native")
        return cls._native_module

    @classmethod
    def is_available(cls) -> bool:
        try:
            module = cls.native_module()
        except Exception:
            return False
        return hasattr(module, "solve_mesh_delta_xpbd")

    @classmethod
    def solve_mesh_delta_xpbd(cls, *args) -> None:
        module = cls.native_module()
        if hasattr(module, "solve_mesh_delta_xpbd"):
            module.solve_mesh_delta_xpbd(*args)
            return
        raise NotImplementedError("native backend missing solve_mesh_delta_xpbd")

    @staticmethod
    def empty_collision_arrays(collision_radii: np.ndarray, collided_by_groups: int) -> tuple:
        return (
            collision_radii,
            int(collided_by_groups),
            np.empty(0, dtype=np.int32),
            np.empty(0, dtype=np.int32),
            np.empty((0, 3), dtype=np.float32),
            np.empty((0, 3), dtype=np.float32),
            np.empty((0, 3), dtype=np.float32),
            np.empty(0, dtype=np.float32),
        )

    @classmethod
    def collision_arrays(cls, state: dict, obj: bpy.types.Object, colliders: list[dict] | None) -> tuple:
        """
        C++ 后端桥接数组当前编码类型：0=SPHERE，1=CAPSULE。
        SPHERE/CAPSULE 的 native 输入由 collider_from_matrix 生成，字段包括类型、组、中心、胶囊线段和半径。
        """
        collision_radii = np.ascontiguousarray(state["collision_radii"], dtype=np.float32)
        collided_by_groups = _BonePhysics.clamp_group_mask(state.get("collided_by_groups", 0))
        if not colliders or not collided_by_groups or not bool(np.any(collision_radii > _MeshPhysics.EPSILON)):
            return cls.empty_collision_arrays(collision_radii, collided_by_groups)

        collider_types = []
        collider_groups = []
        collider_centers = []
        collider_segment_a = []
        collider_segment_b = []
        collider_radii = []

        for collider in colliders:
            if collider.get("owner") is obj:
                continue

            group = max(1, min(16, int(collider.get("primary_group", 1))))
            if not collided_by_groups & _BonePhysics.collision_group_bit(group):
                continue

            radius = max(float(collider.get("radius", 0.0)), 0.0)
            if radius <= _MeshPhysics.EPSILON:
                continue

            collider_type = str(collider.get("type", "SPHERE") or "SPHERE")
            center = _MeshPhysics.vector_to_numpy(collider.get("center"))
            if collider_type == "CAPSULE":
                segment_a = _MeshPhysics.vector_to_numpy(collider.get("segment_a"))
                segment_b = _MeshPhysics.vector_to_numpy(collider.get("segment_b"))
                if segment_a is None or segment_b is None:
                    continue
                if center is None:
                    center = (segment_a + segment_b) * 0.5
                collider_types.append(1)
                collider_segment_a.append(segment_a)
                collider_segment_b.append(segment_b)
            elif collider_type == "SPHERE":
                if center is None:
                    continue
                collider_types.append(0)
                collider_segment_a.append(center)
                collider_segment_b.append(center)
            else:
                continue

            collider_groups.append(group)
            collider_centers.append(center)
            collider_radii.append(radius)

        if not collider_types:
            return cls.empty_collision_arrays(collision_radii, collided_by_groups)

        return (
            collision_radii,
            int(collided_by_groups),
            np.ascontiguousarray(collider_types, dtype=np.int32),
            np.ascontiguousarray(collider_groups, dtype=np.int32),
            np.ascontiguousarray(collider_centers, dtype=np.float32).reshape((-1, 3)),
            np.ascontiguousarray(collider_segment_a, dtype=np.float32).reshape((-1, 3)),
            np.ascontiguousarray(collider_segment_b, dtype=np.float32).reshape((-1, 3)),
            np.ascontiguousarray(collider_radii, dtype=np.float32),
        )

    @classmethod
    def solve(
        cls,
        state: dict,
        obj: bpy.types.Object,
        scene: bpy.types.Scene,
        substeps: int,
        iterations: int,
        gravity_dir,
        gravity_power: float,
        damping: float,
        stretch_compliance: float,
        bend_compliance: float,
        timing: dict | None = None,
        colliders: list[dict] | None = None,
    ) -> dict:
        stage_start = time.perf_counter() if timing is not None else None
        positions = np.ascontiguousarray(state["positions"], dtype=np.float32)
        prev_positions = np.ascontiguousarray(state["prev_positions"], dtype=np.float32)
        rest_positions = np.ascontiguousarray(state["rest_positions"], dtype=np.float32)
        inv_masses = np.ascontiguousarray(state["inv_masses"], dtype=np.float32)
        edge_i = np.ascontiguousarray(state["edge_i"], dtype=np.int32)
        edge_j = np.ascontiguousarray(state["edge_j"], dtype=np.int32)
        edge_rest = np.ascontiguousarray(state["edge_rest"], dtype=np.float32)
        bend_i = np.ascontiguousarray(state["bend_i"], dtype=np.int32)
        bend_j = np.ascontiguousarray(state["bend_j"], dtype=np.int32)
        bend_rest = np.ascontiguousarray(state["bend_rest"], dtype=np.float32)

        dt = _BonePhysics.scene_delta_time(scene)
        substep_count = max(1, min(16, int(substeps)))
        iteration_count = max(0, min(64, int(iterations)))
        gravity = np.ascontiguousarray(
            _MeshPhysics.world_gravity(gravity_dir) * max(float(gravity_power), 0.0),
            dtype=np.float32,
        )
        damping = max(0.0, min(1.0, float(damping)))
        stretch_compliance = max(float(stretch_compliance), 0.0)
        bend_compliance = max(float(bend_compliance), 0.0)
        if timing is not None:
            _MeshPhysics.add_timing(timing, "solve_setup", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        (
            collision_radii,
            collided_by_groups,
            collider_types,
            collider_groups,
            collider_centers,
            collider_segment_a,
            collider_segment_b,
            collider_radii,
        ) = cls.collision_arrays(state, obj, colliders)
        if timing is not None:
            _MeshPhysics.add_timing(timing, "collision_setup", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        cls.solve_mesh_delta_xpbd(
            positions,
            prev_positions,
            rest_positions,
            inv_masses,
            edge_i,
            edge_j,
            edge_rest,
            bend_i,
            bend_j,
            bend_rest,
            gravity,
            float(dt),
            float(damping),
            int(substep_count),
            int(iteration_count),
            float(stretch_compliance),
            float(bend_compliance),
            collision_radii,
            int(collided_by_groups),
            collider_types,
            collider_groups,
            collider_centers,
            collider_segment_a,
            collider_segment_b,
            collider_radii,
        )
        if timing is not None:
            _MeshPhysics.add_timing(timing, "native", time.perf_counter() - stage_start)

        next_state = dict(state)
        next_state["positions"] = np.ascontiguousarray(positions, dtype=np.float32)
        next_state["prev_positions"] = np.ascontiguousarray(prev_positions, dtype=np.float32)
        return next_state


class _SpringBoneVRMCppBackend:
    _native_module = None

    @classmethod
    def native_module(cls):
        if cls._native_module is None:
            cls._native_module = importlib.import_module("hotools_native")
        return cls._native_module

    @classmethod
    def is_available(cls) -> bool:
        try:
            module = cls.native_module()
        except Exception:
            return False
        return hasattr(module, "solve_spring_bone_vrm_cpp")

    @classmethod
    def solve_spring_bone_vrm_cpp(
        cls,
        current_tails: np.ndarray,
        prev_tails: np.ndarray,
        target_matrices: np.ndarray,
        target_quaternions: np.ndarray,
        current_heads: np.ndarray,
        current_pose_matrices: np.ndarray,
        current_pose_quaternions: np.ndarray,
        parent_pose_quaternions: np.ndarray,
        current_pose_tails: np.ndarray,
        lengths: np.ndarray,
        init_axis_local: np.ndarray,
        init_axis_parent: np.ndarray,
        init_rotations: np.ndarray,
        init_scales: np.ndarray,
        parent_indices: np.ndarray,
        pinned: np.ndarray,
        use_connect: np.ndarray,
        root_quaternion: np.ndarray,
        root_tail_world: np.ndarray,
        armature_world: np.ndarray,
        armature_world_inv: np.ndarray,
        gravity_dir: np.ndarray,
        hit_radii: np.ndarray,
        collided_by_groups: np.ndarray,
        collider_types: np.ndarray,
        collider_groups: np.ndarray,
        collider_centers: np.ndarray,
        collider_segment_a: np.ndarray,
        collider_segment_b: np.ndarray,
        collider_radii: np.ndarray,
        dt: float,
        substeps: int,
        stiffness_force: float,
        drag_force: float,
        gravity_power: float,
    ) -> None:
        cls.native_module().solve_spring_bone_vrm_cpp(
            current_tails,
            prev_tails,
            target_matrices,
            target_quaternions,
            current_heads,
            current_pose_matrices,
            current_pose_quaternions,
            parent_pose_quaternions,
            current_pose_tails,
            lengths,
            init_axis_local,
            init_axis_parent,
            init_rotations,
            init_scales,
            parent_indices,
            pinned,
            use_connect,
            root_quaternion,
            root_tail_world,
            armature_world,
            armature_world_inv,
            gravity_dir,
            hit_radii,
            collided_by_groups,
            collider_types,
            collider_groups,
            collider_centers,
            collider_segment_a,
            collider_segment_b,
            collider_radii,
            dt,
            substeps,
            stiffness_force,
            drag_force,
            gravity_power,
        )

    @staticmethod
    def matrix_from_numpy(matrix: np.ndarray) -> mathutils.Matrix:
        values = matrix.reshape(16) if isinstance(matrix, np.ndarray) else np.asarray(matrix, dtype=np.float32).reshape(16)
        return mathutils.Matrix(
            (
                (float(values[0]), float(values[1]), float(values[2]), float(values[3])),
                (float(values[4]), float(values[5]), float(values[6]), float(values[7])),
                (float(values[8]), float(values[9]), float(values[10]), float(values[11])),
                (float(values[12]), float(values[13]), float(values[14]), float(values[15])),
            )
        )

    @staticmethod
    def vector_from_numpy3(values: np.ndarray) -> mathutils.Vector:
        return mathutils.Vector((float(values[0]), float(values[1]), float(values[2])))

    @staticmethod
    def write_vector3_row(array: np.ndarray, index: int, value) -> None:
        array[index, 0] = float(value.x)
        array[index, 1] = float(value.y)
        array[index, 2] = float(value.z)

    @staticmethod
    def write_vector3_value_row(array: np.ndarray, index: int, value, fallback) -> None:
        if value is None or (isinstance(value, str) and value == ""):
            value = fallback
        try:
            array[index, 0] = float(value.x)
            array[index, 1] = float(value.y)
            array[index, 2] = float(value.z)
            return
        except Exception:
            pass
        try:
            value_len = len(value)
            if value_len >= 3:
                array[index, 0] = float(value[0])
                array[index, 1] = float(value[1])
                array[index, 2] = float(value[2])
                return
            if value_len == 2:
                array[index, 0] = float(value[0])
                array[index, 1] = float(value[1])
                array[index, 2] = float(fallback.z)
                return
            if value_len == 1:
                array[index, 0] = float(value[0])
                array[index, 1] = float(fallback.y)
                array[index, 2] = float(fallback.z)
                return
        except Exception:
            pass
        array[index, 0] = float(fallback.x)
        array[index, 1] = float(fallback.y)
        array[index, 2] = float(fallback.z)

    @staticmethod
    def write_matrix4_row(array: np.ndarray, index: int, value: mathutils.Matrix) -> None:
        row = array[index]
        row[0] = float(value[0][0])
        row[1] = float(value[0][1])
        row[2] = float(value[0][2])
        row[3] = float(value[0][3])
        row[4] = float(value[1][0])
        row[5] = float(value[1][1])
        row[6] = float(value[1][2])
        row[7] = float(value[1][3])
        row[8] = float(value[2][0])
        row[9] = float(value[2][1])
        row[10] = float(value[2][2])
        row[11] = float(value[2][3])
        row[12] = float(value[3][0])
        row[13] = float(value[3][1])
        row[14] = float(value[3][2])
        row[15] = float(value[3][3])

    @staticmethod
    def write_quaternion_row(array: np.ndarray, index: int, value) -> None:
        array[index, 0] = float(value.x)
        array[index, 1] = float(value.y)
        array[index, 2] = float(value.z)
        array[index, 3] = float(value.w)

    @staticmethod
    def copy_quaternion_row(array: np.ndarray, index: int, values: np.ndarray) -> None:
        array[index, 0] = float(values[0])
        array[index, 1] = float(values[1])
        array[index, 2] = float(values[2])
        array[index, 3] = float(values[3])

    @classmethod
    def empty_collision_arrays(cls) -> tuple:
        return (
            np.empty(0, dtype=np.int32),
            np.empty(0, dtype=np.int32),
            np.empty((0, 3), dtype=np.float32),
            np.empty((0, 3), dtype=np.float32),
            np.empty((0, 3), dtype=np.float32),
            np.empty(0, dtype=np.float32),
        )

    @classmethod
    def collision_arrays(cls, colliders: list[dict] | None) -> tuple:
        if not colliders:
            return cls.empty_collision_arrays()

        collider_types = []
        collider_groups = []
        collider_centers = []
        collider_segment_a = []
        collider_segment_b = []
        collider_radii = []

        for collider in colliders:
            if not isinstance(collider, dict):
                continue

            collider_type = str(collider.get("type", "SPHERE") or "SPHERE")
            center = _MeshPhysics.vector_to_numpy(collider.get("center"))
            if collider_type == "CAPSULE":
                segment_a = _MeshPhysics.vector_to_numpy(collider.get("segment_a"))
                segment_b = _MeshPhysics.vector_to_numpy(collider.get("segment_b"))
                if segment_a is None or segment_b is None:
                    continue
                if center is None:
                    center = (segment_a + segment_b) * 0.5
                collider_types.append(1)
                collider_segment_a.append(segment_a)
                collider_segment_b.append(segment_b)
            elif collider_type == "SPHERE":
                if center is None:
                    continue
                collider_types.append(0)
                collider_segment_a.append(center)
                collider_segment_b.append(center)
            else:
                continue

            group = max(1, min(16, int(collider.get("primary_group", 1))))
            radius = max(float(collider.get("radius", 0.0)), 0.0)
            collider_groups.append(group)
            collider_centers.append(center)
            collider_radii.append(radius)

        if not collider_types:
            return cls.empty_collision_arrays()

        return (
            np.ascontiguousarray(collider_types, dtype=np.int32),
            np.ascontiguousarray(collider_groups, dtype=np.int32),
            np.ascontiguousarray(collider_centers, dtype=np.float32).reshape((-1, 3)),
            np.ascontiguousarray(collider_segment_a, dtype=np.float32).reshape((-1, 3)),
            np.ascontiguousarray(collider_segment_b, dtype=np.float32).reshape((-1, 3)),
            np.ascontiguousarray(collider_radii, dtype=np.float32),
        )


def _run_mesh_xpbd_node(
    use_cpp: bool,
    cache_state: _OmniCache,
    obj: bpy.types.Object,
    scene: bpy.types.Scene,
    enabled: bool,
    reset: bool,
    substeps: int,
    iterations: int,
    gravity_dir,
    gravity_power: float,
    damping: float,
    stretch_compliance: float,
    bend_compliance: float,
    debug_output: bool,
) -> tuple[_OmniCache, bpy.types.Object, int, int]:
    timing = _MeshPhysics.begin_timing() if debug_output else None
    backend_tag = "cpp" if use_cpp else "py"
    stage_start = time.perf_counter() if timing is not None else None
    obj = _MeshPhysics.require_mesh_object(obj, "obj")
    scene = scene or bpy.context.scene
    output_key = _MeshPhysics.OUTPUT_KEY
    _MeshPhysics.ensure_delta_output(obj)
    if timing is not None:
        _MeshPhysics.add_timing(timing, "validate", time.perf_counter() - stage_start)

    stage_start = time.perf_counter() if timing is not None else None
    topology_key = _MeshPhysics.topology_key(obj, prev_state=cache_state)
    vertex_count = len(obj.data.vertices)
    state = cache_state if _MeshPhysics.state_matches(cache_state, obj, topology_key) else None
    cached_frame = _BonePhysics.cache_frame(state)
    current_frame = int(getattr(scene, "frame_current", 0) or 0)
    if timing is not None:
        _MeshPhysics.add_timing(timing, "cache", time.perf_counter() - stage_start)

    if cached_frame is not None and current_frame != cached_frame + 1:
        stage_start = time.perf_counter() if timing is not None else None
        _MeshPhysics.clear_delta_attribute(obj)
        if timing is not None:
            _MeshPhysics.add_timing(timing, "restore", time.perf_counter() - stage_start)
            _MeshPhysics.publish_debug_timing(
                obj,
                output_key,
                current_frame,
                vertex_count,
                0,
                backend_tag,
                timing,
            )
        return _OmniCache(None), obj, vertex_count, 0

    if reset or not isinstance(state, dict):
        stage_start = time.perf_counter() if timing is not None else None
        _MeshPhysics.clear_delta_attribute(obj)
        if timing is not None:
            _MeshPhysics.add_timing(timing, "restore", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        state = _MeshPhysics.build_state(obj, topology_key)
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
        _MeshPhysics.clear_delta_attribute(obj)
        _MeshPhysics.publish_debug_timing(
            obj,
            output_key,
            current_frame,
            vertex_count,
            constraint_count,
            backend_tag,
            timing,
        )
        return _OmniCache(_as_cache_owner(next_state)), obj, vertex_count, constraint_count

    stage_start = time.perf_counter() if timing is not None else None
    backend = _MeshPhysicsCppBackend if use_cpp else _MeshPhysics
    if use_cpp:
        if not _MeshPhysicsCppBackend.is_available():
            raise ImportError("hotools_native is not available; build the native backend first")

    stage_start = time.perf_counter() if timing is not None else None
    collision_snapshot = _BonePhysics.build_collision_snapshot_from_scene(scene, True, True, False)
    colliders = list(collision_snapshot.get("colliders") or []) if isinstance(collision_snapshot, dict) else []
    if timing is not None:
        _MeshPhysics.add_timing(timing, "colliders", time.perf_counter() - stage_start)

    stage_start = time.perf_counter() if timing is not None else None
    next_state = backend.solve(
        state,
        obj,
        scene,
        substeps,
        iterations,
        gravity_dir,
        gravity_power,
        damping,
        stretch_compliance,
        bend_compliance,
        timing,
        colliders=colliders,
    )
    if timing is not None:
        _MeshPhysics.add_timing(timing, "solve_total", time.perf_counter() - stage_start)
    next_state["frame"] = current_frame
    stage_start = time.perf_counter() if timing is not None else None
    _MeshPhysics.write_world_delta_attribute(obj, next_state["positions"], next_state["rest_positions"])
    if timing is not None:
        _MeshPhysics.add_timing(timing, "write", time.perf_counter() - stage_start)
        _MeshPhysics.publish_debug_timing(
            obj,
            output_key,
            current_frame,
            vertex_count,
            constraint_count,
            backend_tag,
            timing,
        )
    return _OmniCache(_as_cache_owner(next_state)), obj, vertex_count, constraint_count


@omni(
    enable=True,
    bl_label="弹簧骨-VRM链设置",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "骨骼",
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
    为一个或多个骨骼输入生成 VRM SpringBone 解算所需的弹簧和重力参数。

    接入单根骨骼时会把它当作 root 递归收集；接入“从根获取骨骼”的列表时会按该列表解释为链/集合。
    本节点不写姿态、不推进时间，只打包参数；真正的模拟、缓存读写和碰撞处理都在解算器里完成。

    碰撞半径、碰撞体类型和碰撞组不在这里重复配置。
    解算器会直接读取每根模拟骨骼上的 hotools_collision 设置；当前只消费 SPHERE/CAPSULE 的 radius、offset、length、primary_collision_group、collided_by_groups。
    Object 级外部碰撞体来自场景中可见对象的 hotools_object_collision；当前旧 SpringBone 蓝本消费类型为 SPHERE、CAPSULE。
    """,
)
def springBoneVRMChainSetting(
    bone_chain: list[_OmniBone],
    enabled: bool = True,
    stiffness_force: float = 1.0,
    drag_force: float = 0.4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 0.0,
) -> list[typing.Any]:
    bone_chains = _BonePhysics.bone_chains_from_bone_values(bone_chain)
    if not bone_chains:
        raise ValueError("root bone input is empty")

    gravity = _BonePhysics.vector3(gravity_dir, mathutils.Vector((0.0, 0.0, -1.0)))
    if gravity.length > _BonePhysics.EPSILON:
        gravity.normalize()

    return [
        {
            "armature": bone_chain_value["armature"],
            "root_bone": str(bone_chain_value.get("root_bone") or ""),
            "bones": list(bone_chain_value.get("bones") or []),
            "enabled": bool(enabled),
            "stiffness_force": max(float(stiffness_force), 0.0),
            "drag_force": max(0.0, min(1.0, float(drag_force))),
            "gravity_dir": gravity,
            "gravity_power": max(float(gravity_power), 0.0),
        }
        for bone_chain_value in bone_chains
    ]


class _SpringBoneVRM:
    DEBUG_PRINT_INTERVAL = 1.0
    _collision_snapshot_cache = {}
    _collision_array_snapshot_cache = {}
    _collision_source_cache = {}
    _TIMING_PHASE_STAGES = {
        "cache",
        "restore",
        "rebuild",
        "colliders",
        "targets",
        "solve",
        "solve_total",
        "write",
        "write_basis",
        "write_tag",
        "total",
    }
    _TIMING_INNER_STAGES = {
        "collision_setup",
        "runtime_refresh",
        "pack",
        "native_core",
        "unpack",
        "unpack_tail",
        "unpack_matrix",
        "unpack_state",
    }
    _debug_profiles = {}

    @staticmethod
    def settings_for_armature(
        armature_obj: bpy.types.Object,
        vrm_chain_settings: list[typing.Any],
    ) -> tuple[list[dict], list[_OmniBone]]:
        settings = [
            setting
            for setting in _BonePhysics.flatten_vrm_spring_bone_chain_settings(vrm_chain_settings)
            if setting.get("armature") is armature_obj
        ]
        settings.sort(key=lambda item: str(item.get("root_bone") or ""))

        roots = set()
        affected_bones = []
        seen_affected = set()
        expected_bones = set()

        for setting in settings:
            root = str(setting.get("root_bone") or "")
            if not root:
                raise ValueError("chain setting root_bone is empty")
            if root in roots:
                raise ValueError(f"duplicate VRM SpringBone root: {root}")
            roots.add(root)

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
            for bone_name in _BonePhysics.simulated_bone_names(chain):
                if bone_name in expected_bones:
                    raise ValueError(f"duplicate simulated bone across chains: {bone_name}")
                expected_bones.add(bone_name)

        return settings, affected_bones

    @staticmethod
    def initial_targets(
        armature_obj: bpy.types.Object,
        settings: list[dict],
    ) -> tuple[dict[str, mathutils.Matrix], dict[str, mathutils.Vector]]:
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

        return target_pose_matrices, target_tail_worlds

    @classmethod
    def prepare(
        cls,
        backend_tag: str,
        cache_state: _OmniCache,
        armature_obj: bpy.types.Object,
        vrm_chain_settings: list[typing.Any],
        scene: bpy.types.Scene = None,
        enabled: bool = True,
        reset: bool = False,
        substeps: int = 1,
        timing: dict | None = None,
    ) -> dict:
        stage_start = time.perf_counter() if timing is not None else None
        armature_obj = _BonePhysics.require_armature(armature_obj, "armature_obj")
        scene = scene or bpy.context.scene
        current_frame = int(getattr(scene, "frame_current", bpy.context.scene.frame_current))
        settings, affected_bones = cls.settings_for_armature(armature_obj, vrm_chain_settings)
        if timing is not None:
            cls._add_timing(timing, "validate", time.perf_counter() - stage_start)

        runtime = {
            "backend_tag": backend_tag,
            "armature_obj": armature_obj,
            "scene": scene,
            "current_frame": current_frame,
            "settings": settings,
            "affected_bones": affected_bones,
            "substep_count": max(1, min(16, int(substeps))),
            "timing": timing,
        }

        if not settings:
            runtime["early_result"] = (_OmniCache(_as_cache_owner(cache_state)), affected_bones, armature_obj, 0, 0)
            return runtime

        stage_start = time.perf_counter() if timing is not None else None
        topology_key = _BonePhysics.vrm_spring_bone_topology_key(armature_obj, settings)
        state = cache_state if _BonePhysics.vrm_spring_bone_cache_matches(cache_state, armature_obj, topology_key) else None
        needs_reset = bool(reset) or not isinstance(state, dict)
        if isinstance(state, dict) and not _BonePhysics.vrm_spring_bone_write_records_match(
            armature_obj,
            settings,
            state.get("write_records"),
        ):
            state["write_records"] = _BonePhysics.build_vrm_spring_bone_write_records(armature_obj, settings)
            state.pop("write_runtime", None)
            state.pop("cpp_runtime", None)
        if timing is not None:
            cls._add_timing(timing, "cache", time.perf_counter() - stage_start)

        if isinstance(state, dict) and state.get("frame") is not None:
            try:
                last_frame = int(state.get("frame"))
                if current_frame not in {last_frame, last_frame + 1}:
                    stage_start = time.perf_counter() if timing is not None else None
                    _BonePhysics.restore_vrm_spring_bone_initial_pose(armature_obj, state)
                    if timing is not None:
                        cls._add_timing(timing, "restore", time.perf_counter() - stage_start)
                    runtime["early_result"] = (_OmniCache(None), affected_bones, armature_obj, len(settings), 0)
                    return runtime
            except Exception:
                stage_start = time.perf_counter() if timing is not None else None
                _BonePhysics.restore_vrm_spring_bone_initial_pose(armature_obj, state)
                if timing is not None:
                    cls._add_timing(timing, "restore", time.perf_counter() - stage_start)
                runtime["early_result"] = (_OmniCache(None), affected_bones, armature_obj, len(settings), 0)
                return runtime

        if needs_reset:
            stage_start = time.perf_counter() if timing is not None else None
            _BonePhysics.restore_vrm_spring_bone_initial_pose(armature_obj, state)
            state = _BonePhysics.build_vrm_spring_bone_state(armature_obj, settings, topology_key)
            if timing is not None:
                cls._add_timing(timing, "rebuild", time.perf_counter() - stage_start)

        if not enabled:
            state["frame"] = current_frame
            runtime["early_result"] = (_OmniCache(_as_cache_owner(state)), affected_bones, armature_obj, len(settings), 0)
            return runtime

        stage_start = time.perf_counter() if timing is not None else None
        use_cpp_backend = str(backend_tag or "").lower() in {"cpp", "c++", "native"}
        collider_arrays = None
        collider_group_bits = None
        collider_self_bones = []
        if use_cpp_backend:
            collision_snapshot = cls.collision_snapshot_cpp(scene)
            colliders = []
            collider_arrays = collision_snapshot.get("collider_arrays") if isinstance(collision_snapshot, dict) else None
            collider_group_bits = collision_snapshot.get("collider_group_bits") if isinstance(collision_snapshot, dict) else None
            collider_self_bones = (
                list(collision_snapshot.get("self_bones") or [])
                if isinstance(collision_snapshot, dict)
                else []
            )
            collider_self_owners = (
                list(collision_snapshot.get("self_owners") or [])
                if isinstance(collision_snapshot, dict)
                else []
            )
            collider_count = int(collision_snapshot.get("collider_count", 0)) if isinstance(collision_snapshot, dict) else 0
        else:
            collision_snapshot = cls.collision_snapshot(scene)
            colliders = list(collision_snapshot.get("colliders") or []) if isinstance(collision_snapshot, dict) else []
            collider_self_owners = []
            collider_count = len(colliders)
        if timing is not None:
            cls._add_timing(timing, "colliders", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        target_pose_matrices, target_tail_worlds = cls.initial_targets(armature_obj, settings)
        if timing is not None:
            cls._add_timing(timing, "targets", time.perf_counter() - stage_start)

        runtime.update(
            {
                "state": state,
                "colliders": colliders,
                "collider_arrays": collider_arrays,
                "collider_group_bits": collider_group_bits,
                "collider_self_bones": collider_self_bones,
                "collider_self_owners": collider_self_owners,
                "collider_count": collider_count,
                "dt": _BonePhysics.scene_delta_time(scene),
                "target_pose_matrices": target_pose_matrices,
                "target_tail_worlds": target_tail_worlds,
            }
        )
        return runtime

    @classmethod
    def collision_snapshot(cls, scene) -> dict:
        scene = scene or bpy.context.scene
        frame = int(getattr(scene, "frame_current", 0) or 0)
        scene_key = cls._scene_key(scene)
        cache_key = (scene_key, frame)
        snapshot = cls._collision_snapshot_cache.get(cache_key)
        if isinstance(snapshot, dict):
            return snapshot
        snapshot = cls._build_collision_snapshot_from_cached_sources(scene)
        cls._collision_snapshot_cache.clear()
        cls._collision_snapshot_cache[cache_key] = snapshot
        return snapshot

    @classmethod
    def collision_snapshot_cpp(cls, scene) -> dict:
        scene = scene or bpy.context.scene
        frame = int(getattr(scene, "frame_current", 0) or 0)
        scene_key = cls._scene_key(scene)
        cache_key = (scene_key, frame)
        snapshot = cls._collision_array_snapshot_cache.get(cache_key)
        if isinstance(snapshot, dict):
            return snapshot
        snapshot = cls._build_collision_array_snapshot_from_cached_sources(scene)
        cls._collision_array_snapshot_cache.clear()
        cls._collision_array_snapshot_cache[cache_key] = snapshot
        return snapshot

    @staticmethod
    def _scene_key(scene) -> int:
        return int(scene.as_pointer()) if hasattr(scene, "as_pointer") else id(scene)

    @staticmethod
    def _collider_props_enabled(props) -> bool:
        if props is None:
            return False
        collision_type = str(getattr(props, "collision_type", "NONE") or "NONE")
        if collision_type not in {"SPHERE", "CAPSULE"}:
            return False
        try:
            return max(float(getattr(props, "radius", 0.0)), 0.0) > _BonePhysics.EPSILON
        except Exception:
            return False

    @staticmethod
    def _collider_source_record(owner, owner_type: str, props, bone_name: str = "", bone_ref=None, pose_bone_ref=None) -> dict | None:
        collision_type = str(getattr(props, "collision_type", "NONE") or "NONE")
        if collision_type not in {"SPHERE", "CAPSULE"}:
            return None
        radius = max(float(getattr(props, "radius", 0.0)), 0.0)
        if radius <= _BonePhysics.EPSILON:
            return None
        offset = _BonePhysics.vector3(getattr(props, "offset", None), mathutils.Vector((0.0, 0.0, 0.0)))
        group = max(1, min(16, int(getattr(props, "primary_collision_group", 1))))
        return {
            "owner": owner,
            "owner_type": owner_type,
            "props": props,
            "bone": str(bone_name or ""),
            "bone_ref": bone_ref,
            "pose_bone_ref": pose_bone_ref,
            "type": collision_type,
            "type_code": 1 if collision_type == "CAPSULE" else 0,
            "radius": radius,
            "offset": offset,
            "group": group,
            "group_bit": _BonePhysics.collision_group_bit(group),
            "half_length": max(float(getattr(props, "length", 0.0)), 0.0) * 0.5 if collision_type == "CAPSULE" else 0.0,
        }

    @classmethod
    def _collision_sources(cls, scene) -> list[dict]:
        """枚举场景中所有碰撞源（Object 和 Bone）。

        缓存策略：按 (scene_key, frame) 缓存，每帧重新枚举一次碰撞源列表，
        确保新增/删除/修改的碰撞体能被及时检测到。同一帧内多次调用复用缓存。
        """
        scene = scene or bpy.context.scene
        frame = int(getattr(scene, "frame_current", 0) or 0)
        scene_key = cls._scene_key(scene)
        cache_key = (scene_key, frame)

        cached = cls._collision_source_cache.get(cache_key)
        if isinstance(cached, list):
            return cached

        sources = []
        for obj in _BonePhysics.scene_objects(scene):
            props = getattr(obj, "hotools_object_collision", None)
            if cls._collider_props_enabled(props):
                source = cls._collider_source_record(obj, "OBJECT", props)
                if source is not None:
                    sources.append(source)

            if getattr(obj, "type", None) == "ARMATURE":
                for bone in obj.data.bones:
                    props = getattr(bone, "hotools_collision", None)
                    if not cls._collider_props_enabled(props):
                        continue
                    source = cls._collider_source_record(
                        obj,
                        "BONE",
                        props,
                        bone.name,
                        bone,
                        obj.pose.bones.get(bone.name) if obj.pose else None,
                    )
                    if source is not None:
                        sources.append(source)

        # 只保留当前帧的缓存，清除过期的旧帧数据
        cls._collision_source_cache.clear()
        cls._collision_source_cache[cache_key] = sources
        return sources

    @classmethod
    def _build_collision_snapshot_from_cached_sources(cls, scene) -> dict:
        scene = scene or bpy.context.scene
        sources = cls._collision_sources(scene)
        colliders = []
        invalid_sources = False
        owner_visibility = {}

        for source in sources:
            owner = source.get("owner")
            if owner is None:
                invalid_sources = True
                break
            try:
                owner_pointer = int(owner.as_pointer()) if hasattr(owner, "as_pointer") else id(owner)
                visible = owner_visibility.get(owner_pointer)
                if visible is None:
                    visible = bool(owner.visible_get())
                    owner_visibility[owner_pointer] = visible
                if not visible:
                    continue
            except ReferenceError:
                invalid_sources = True
                break
            except Exception:
                pass

            owner_type = str(source.get("owner_type") or "")
            props = source.get("props")
            bone_name = str(source.get("bone") or "")
            try:
                if owner_type == "OBJECT":
                    matrix = owner.matrix_world
                elif owner_type == "BONE" and getattr(owner, "type", None) == "ARMATURE":
                    pose_bone = owner.pose.bones.get(bone_name) if owner.pose else None
                    bone = owner.data.bones.get(bone_name) if owner.data else None
                    if bone is None:
                        invalid_sources = True
                        break
                    local_matrix = pose_bone.matrix if pose_bone is not None else bone.matrix_local
                    matrix = owner.matrix_world @ local_matrix
                else:
                    continue

                collider = _BonePhysics.collider_from_matrix(
                    matrix,
                    props,
                    owner,
                    owner_type,
                    bone_name,
                )
            except ReferenceError:
                invalid_sources = True
                break
            except Exception:
                continue

            if collider is not None:
                colliders.append(collider)

        if invalid_sources:
            # 源失效时清除当前帧的缓存，下次调用会重新枚举
            frame = int(getattr(scene, "frame_current", 0) or 0)
            cache_key = (cls._scene_key(scene), frame)
            cls._collision_source_cache.pop(cache_key, None)
            return _BonePhysics.build_collision_snapshot_from_scene(scene, True, True, False)

        return {
            "frame": int(getattr(scene, "frame_current", 0) or 0),
            "colliders": colliders,
        }

    @classmethod
    def _build_collision_array_snapshot_from_cached_sources(cls, scene) -> dict:
        scene = scene or bpy.context.scene
        sources = cls._collision_sources(scene)
        source_count = len(sources)
        collider_types = np.empty(source_count, dtype=np.int32)
        collider_groups = np.empty(source_count, dtype=np.int32)
        collider_centers = np.empty((source_count, 3), dtype=np.float32)
        collider_segment_a = np.empty((source_count, 3), dtype=np.float32)
        collider_segment_b = np.empty((source_count, 3), dtype=np.float32)
        collider_radii = np.empty(source_count, dtype=np.float32)
        collider_group_bits = np.empty(source_count, dtype=np.int32)
        self_bones = []
        self_owners = []
        invalid_sources = False
        collider_count = 0
        owner_visibility = {}
        owner_pointers = {}

        for source in sources:
            owner = source.get("owner")
            if owner is None:
                invalid_sources = True
                break
            try:
                owner_key = id(owner)
                owner_pointer = owner_pointers.get(owner_key)
                if owner_pointer is None:
                    owner_pointer = int(owner.as_pointer()) if hasattr(owner, "as_pointer") else owner_key
                    owner_pointers[owner_key] = owner_pointer
                visible = owner_visibility.get(owner_pointer)
                if visible is None:
                    visible = bool(owner.visible_get())
                    owner_visibility[owner_pointer] = visible
                if not visible:
                    continue
            except ReferenceError:
                invalid_sources = True
                break
            except Exception:
                pass

            owner_type = str(source.get("owner_type") or "")
            props = source.get("props")
            bone_name = str(source.get("bone") or "")
            try:
                if owner_type == "OBJECT":
                    matrix = owner.matrix_world
                elif owner_type == "BONE" and getattr(owner, "type", None) == "ARMATURE":
                    pose_bone = source.get("pose_bone_ref")
                    bone = source.get("bone_ref")
                    if bone is None:
                        invalid_sources = True
                        break
                    local_matrix = pose_bone.matrix if pose_bone is not None else bone.matrix_local
                    matrix = owner.matrix_world @ local_matrix
                else:
                    continue

                type_code = int(source.get("type_code", -1))
                if type_code not in {0, 1}:
                    continue

                radius = max(float(source.get("radius", 0.0)), 0.0) * _BonePhysics.matrix_scale_radius(matrix)
                if radius <= _BonePhysics.EPSILON:
                    continue

                offset = source.get("offset")
                if offset is None:
                    continue
                center = matrix @ offset
                center_x = float(center.x)
                center_y = float(center.y)
                center_z = float(center.z)
                if type_code == 1:
                    half_length = max(float(source.get("half_length", 0.0)), 0.0)
                    axis = mathutils.Vector((0.0, 1.0, 0.0))
                    segment_a = matrix @ (offset - axis * half_length)
                    segment_b = matrix @ (offset + axis * half_length)
                    collider_types[collider_count] = type_code
                    collider_segment_a[collider_count, 0] = float(segment_a.x)
                    collider_segment_a[collider_count, 1] = float(segment_a.y)
                    collider_segment_a[collider_count, 2] = float(segment_a.z)
                    collider_segment_b[collider_count, 0] = float(segment_b.x)
                    collider_segment_b[collider_count, 1] = float(segment_b.y)
                    collider_segment_b[collider_count, 2] = float(segment_b.z)
                else:
                    collider_types[collider_count] = 0
                    collider_segment_a[collider_count, 0] = center_x
                    collider_segment_a[collider_count, 1] = center_y
                    collider_segment_a[collider_count, 2] = center_z
                    collider_segment_b[collider_count, 0] = center_x
                    collider_segment_b[collider_count, 1] = center_y
                    collider_segment_b[collider_count, 2] = center_z

                group = int(source.get("group", 1))
                collider_groups[collider_count] = group
                collider_group_bits[collider_count] = int(source.get("group_bit", _BonePhysics.collision_group_bit(group)))
                collider_centers[collider_count, 0] = center_x
                collider_centers[collider_count, 1] = center_y
                collider_centers[collider_count, 2] = center_z
                collider_radii[collider_count] = float(radius)
                self_bones.append(bone_name if owner_type == "BONE" else "")
                self_owners.append(owner_pointer if owner_type == "BONE" else 0)
                collider_count += 1
            except ReferenceError:
                invalid_sources = True
                break
            except Exception:
                continue

        if invalid_sources:
            # 源失效时清除当前帧的缓存，下次调用会重新枚举
            frame = int(getattr(scene, "frame_current", 0) or 0)
            cache_key = (cls._scene_key(scene), frame)
            cls._collision_source_cache.pop(cache_key, None)
            snapshot = _BonePhysics.build_collision_snapshot_from_scene(scene, True, True, False)
            colliders = list(snapshot.get("colliders") or []) if isinstance(snapshot, dict) else []
            collider_arrays = _SpringBoneVRMCppBackend.collision_arrays(colliders)
            return {
                "frame": int(getattr(scene, "frame_current", 0) or 0),
                "collider_count": len(colliders),
                "collider_arrays": collider_arrays,
                "collider_group_bits": np.ascontiguousarray(
                    [_BonePhysics.collision_group_bit(group) for group in collider_arrays[1]],
                    dtype=np.int32,
                ),
                "self_bones": [
                    str(collider.get("bone") or "")
                    if isinstance(collider, dict) and collider.get("owner_type") == "BONE"
                    else ""
                    for collider in colliders
                ],
                "self_owners": [
                    int(collider.get("owner").as_pointer())
                    if (
                        isinstance(collider, dict)
                        and collider.get("owner_type") == "BONE"
                        and hasattr(collider.get("owner"), "as_pointer")
                    )
                    else 0
                    for collider in colliders
                ],
            }

        if collider_count <= 0:
            collider_arrays = _SpringBoneVRMCppBackend.empty_collision_arrays()
            collider_group_bits_array = np.empty(0, dtype=np.int32)
        else:
            collider_arrays = (
                collider_types[:collider_count],
                collider_groups[:collider_count],
                collider_centers[:collider_count],
                collider_segment_a[:collider_count],
                collider_segment_b[:collider_count],
                collider_radii[:collider_count],
            )
            collider_group_bits_array = collider_group_bits[:collider_count]

        return {
            "frame": int(getattr(scene, "frame_current", 0) or 0),
            "collider_count": collider_count,
            "collider_arrays": collider_arrays,
            "collider_group_bits": collider_group_bits_array,
            "self_bones": self_bones,
            "self_owners": self_owners,
        }

    @staticmethod
    def _add_timing(timing: dict | None, stage: str, seconds: float) -> None:
        if timing is None:
            return
        stages = timing.setdefault("stages", {})
        stages[stage] = stages.get(stage, 0.0) + max(float(seconds), 0.0)

    @classmethod
    def _begin_timing(cls) -> dict:
        return {"start": time.perf_counter(), "stages": {}}

    @classmethod
    def _timing_stage_role(cls, stage: str) -> str:
        stage = str(stage)
        if stage in cls._TIMING_PHASE_STAGES:
            return "phase"
        if stage in cls._TIMING_INNER_STAGES:
            return "inner"
        return "step"

    @classmethod
    def _timing_role_label(cls, stage: str) -> str:
        role = cls._timing_stage_role(stage)
        if role == "phase":
            return OmniDebug.str_color("[phase]", 96)
        if role == "inner":
            return OmniDebug.str_color("[inner]", 93)
        return OmniDebug.str_color("[step]", 95)

    @classmethod
    def _timing_stage_label(cls, stage: str) -> str:
        role = cls._timing_stage_role(stage)
        if role == "phase":
            return OmniDebug.str_color(stage, 96)
        if role == "inner":
            return OmniDebug.str_color(stage, 93)
        return OmniDebug.func_label(stage)

    @classmethod
    def _timing_value_label(cls, stage: str, text: str) -> str:
        role = cls._timing_stage_role(stage)
        if role == "phase":
            return OmniDebug.str_color(text, 96)
        if role == "inner":
            return OmniDebug.str_color(text, 93)
        return OmniDebug.value_label(text)

    @classmethod
    def _format_debug_timing_report(
        cls,
        backend_tag: str,
        obj_name: str,
        frame: int,
        chain_count: int,
        collider_count: int,
        elapsed: float,
        sample_count: int,
        totals: dict,
    ) -> list[str]:
        elapsed_ms = max(float(elapsed), 0.000001) * 1000.0
        hz = sample_count / max(float(elapsed), 0.000001)
        total_ms = totals.get("total", 0.0) / sample_count * 1000.0
        divider = OmniDebug.str_color("-" * 72, 90)
        title = (
            f"{OmniDebug.str_color('OMNI DEBUG TIMING', 97)}"
            f"  |  {OmniDebug.section_label('SpringBoneVRM')} "
            f"{OmniDebug.func_label(str(backend_tag).upper())}"
        )

        lines = [
            "",
            divider,
            title,
            divider,
            f"  {OmniDebug.section_label('Summary')}: "
            f"interval={OmniDebug.value_label(f'{elapsed_ms:.1f}ms')}  "
            f"samples={OmniDebug.value_label(sample_count)}  "
            f"hz={OmniDebug.value_label(f'{hz:.2f}')}  "
            f"total={OmniDebug.func_label(f'{total_ms:.3f}ms')}",
            f"  {OmniDebug.section_label('Context')}: "
            f"obj={OmniDebug.node_label(obj_name)}  "
            f"frame={OmniDebug.value_label(frame)}  "
            f"chains={OmniDebug.value_label(chain_count)}  "
            f"colliders={OmniDebug.value_label(collider_count)}",
        ]

        step_stages = [stage for stage in totals if stage != "total"]
        step_stages.sort(key=lambda stage: totals[stage], reverse=True)
        if step_stages:
            lines.append(f"  {OmniDebug.section_label('Slow Steps')}:")
            for index, stage in enumerate(step_stages, start=1):
                avg_ms = totals[stage] / sample_count * 1000.0
                lines.append(
                    f"    {OmniDebug.value_label(f'{index:02d}.')} "
                    f"{cls._timing_role_label(stage)} "
                    f"{cls._timing_stage_label(stage)} = "
                    f"{cls._timing_value_label(stage, f'{avg_ms:.3f}ms')}"
                )

        return lines

    @classmethod
    def _publish_debug_timing(
        cls,
        armature_obj: bpy.types.Object,
        current_frame: int,
        chain_count: int,
        collider_count: int,
        backend_tag: str,
        timing: dict | None,
    ) -> None:
        if timing is None:
            return
        now = time.perf_counter()
        stages = dict(timing.get("stages") or {})
        stages["total"] = max(now - float(timing.get("start", now)), 0.0)
        key = (int(armature_obj.as_pointer()), "SpringBoneVRM", str(backend_tag))
        profile = cls._debug_profiles
        entry = profile.get(key)
        first_publish = entry is None
        if entry is None:
            entry = {
                "last_print": now,
                "frames": 0,
                "stages": {},
                "frame": current_frame,
                "chain_count": chain_count,
                "collider_count": collider_count,
            }
            profile[key] = entry
        entry["frames"] += 1
        entry["frame"] = current_frame
        entry["chain_count"] = chain_count
        entry["collider_count"] = collider_count
        for stage, seconds in stages.items():
            entry["stages"][stage] = entry["stages"].get(stage, 0.0) + float(seconds)
        if not first_publish and now - float(entry["last_print"]) < cls.DEBUG_PRINT_INTERVAL:
            return

        sample_count = max(int(entry["frames"]), 1)
        elapsed = (
            max(float(entry["stages"].get("total", 0.0)) / sample_count, 0.000001)
            if first_publish
            else max(now - float(entry["last_print"]), 0.000001)
        )
        print(
            "\n".join(
                cls._format_debug_timing_report(
                    backend_tag,
                    armature_obj.name_full,
                    int(entry["frame"]),
                    int(entry["chain_count"]),
                    int(entry["collider_count"]),
                    elapsed,
                    sample_count,
                    entry["stages"],
                )
            )
        )

        cls._debug_profiles[key] = {
            "last_print": now,
            "frames": 0,
            "stages": {},
        }

    @classmethod
    def write_pose(
        cls,
        armature_obj: bpy.types.Object,
        settings: list[dict],
        target_pose_matrices: dict[str, mathutils.Matrix],
        write_records: list[dict] | None = None,
        timing: dict | None = None,
        write_runtime: dict | None = None,
    ) -> None:
        stage_start = time.perf_counter() if timing is not None else None
        if isinstance(write_records, list):
            pose_bones = armature_obj.pose.bones
            basis_value_count = len(pose_bones) * 16
            if isinstance(write_runtime, dict):
                basis_values = write_runtime.get("basis_values")
                if not isinstance(basis_values, list) or len(basis_values) != basis_value_count:
                    basis_values = [0.0] * basis_value_count
                    write_runtime["basis_values"] = basis_values
            else:
                basis_values = [0.0] * basis_value_count
            try:
                pose_bones.foreach_get("matrix_basis", basis_values)
                can_foreach_set = True
            except Exception:
                can_foreach_set = False
            fallback_updates = [] if not can_foreach_set else None
            for record in write_records:
                pose_bone = record.get("pose_bone")
                bone_name = str(record.get("bone_name") or "")
                target_matrix = target_pose_matrices.get(bone_name)
                if pose_bone is None or target_matrix is None:
                    continue

                parent = record.get("parent")
                if parent is None:
                    basis_matrix = record["bone_rest_inv"] @ target_matrix
                else:
                    parent_matrix = target_pose_matrices.get(str(record.get("parent_name") or ""))
                    if parent_matrix is None:
                        parent_matrix = parent.matrix
                    parent_space = parent_matrix @ record["parent_rest_inv"] @ record["bone_rest"]
                    basis_matrix = parent_space.inverted() @ target_matrix
                if can_foreach_set:
                    pose_index = int(record.get("pose_index", -1))
                    if pose_index >= 0:
                        offset = pose_index * 16
                        basis_values[offset + 0] = float(basis_matrix[0][0])
                        basis_values[offset + 1] = float(basis_matrix[1][0])
                        basis_values[offset + 2] = float(basis_matrix[2][0])
                        basis_values[offset + 3] = float(basis_matrix[3][0])
                        basis_values[offset + 4] = float(basis_matrix[0][1])
                        basis_values[offset + 5] = float(basis_matrix[1][1])
                        basis_values[offset + 6] = float(basis_matrix[2][1])
                        basis_values[offset + 7] = float(basis_matrix[3][1])
                        basis_values[offset + 8] = float(basis_matrix[0][2])
                        basis_values[offset + 9] = float(basis_matrix[1][2])
                        basis_values[offset + 10] = float(basis_matrix[2][2])
                        basis_values[offset + 11] = float(basis_matrix[3][2])
                        basis_values[offset + 12] = float(basis_matrix[0][3])
                        basis_values[offset + 13] = float(basis_matrix[1][3])
                        basis_values[offset + 14] = float(basis_matrix[2][3])
                        basis_values[offset + 15] = float(basis_matrix[3][3])
                elif fallback_updates is not None:
                    fallback_updates.append((pose_bone, basis_matrix))

            if can_foreach_set:
                try:
                    pose_bones.foreach_set("matrix_basis", basis_values)
                    cls._add_timing(timing, "write_basis", time.perf_counter() - stage_start if timing is not None else 0.0)
                    return
                except Exception:
                    fallback_updates = []
                    for record in write_records:
                        pose_bone = record.get("pose_bone")
                        bone_name = str(record.get("bone_name") or "")
                        target_matrix = target_pose_matrices.get(bone_name)
                        if pose_bone is None or target_matrix is None:
                            continue
                        parent = record.get("parent")
                        if parent is None:
                            basis_matrix = record["bone_rest_inv"] @ target_matrix
                        else:
                            parent_matrix = target_pose_matrices.get(str(record.get("parent_name") or ""))
                            if parent_matrix is None:
                                parent_matrix = parent.matrix
                            parent_space = parent_matrix @ record["parent_rest_inv"] @ record["bone_rest"]
                            basis_matrix = parent_space.inverted() @ target_matrix
                        fallback_updates.append((pose_bone, basis_matrix))

            for pose_bone, basis_matrix in fallback_updates or []:
                pose_bone.matrix_basis = basis_matrix
            cls._add_timing(timing, "write_basis", time.perf_counter() - stage_start if timing is not None else 0.0)
            return

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
        cls._add_timing(timing, "write_basis", time.perf_counter() - stage_start if timing is not None else 0.0)

    @staticmethod
    def solve_py(runtime: dict) -> dict:
        armature_obj = runtime["armature_obj"]
        settings = runtime["settings"]
        colliders = runtime["colliders"]
        substep_count = runtime["substep_count"]
        step_dt = runtime["dt"] / substep_count if substep_count > 0 else runtime["dt"]
        target_pose_matrices = runtime["target_pose_matrices"]
        target_tail_worlds = runtime["target_tail_worlds"]
        chains_state = runtime["state"].get("chains", {})

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

                    if bool(joint.get("pinned", False)):
                        target_matrix, pinned_tail, next_joint = _BonePhysics.pinned_joint_state(
                            armature_obj,
                            pose_bone,
                            joint,
                        )
                        next_joints[bone_name] = next_joint
                        target_pose_matrices[bone_name] = target_matrix
                        target_tail_worlds[bone_name] = pinned_tail.copy()
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

        return chains_state

    @classmethod
    def build_cpp_chain_runtime(cls, armature_obj: bpy.types.Object, settings: list[dict], chains_state: dict) -> dict:
        chain_runtime_by_root = {}
        for setting in settings:
            root_name = str(setting.get("root_bone") or "")
            chain_state = chains_state.get(root_name)
            if not isinstance(chain_state, dict):
                continue
            bones = list(chain_state.get("bones") or [])
            joints = chain_state.get("joints") if isinstance(chain_state.get("joints"), dict) else {}
            simulated_names = _BonePhysics.simulated_bone_names(
                {
                    "armature": armature_obj,
                    "root_bone": root_name,
                    "bones": bones,
                }
            )

            static_records = []
            for bone_name in simulated_names:
                pose_bone = armature_obj.pose.bones.get(bone_name)
                joint = joints.get(bone_name) if isinstance(joints, dict) else None
                if pose_bone is None or not isinstance(joint, dict):
                    continue

                pinned_value = bool(joint.get("pinned", False))
                current_head, fallback_tail = _BonePhysics.pose_head_tail_world(armature_obj, pose_bone)
                length = float(joint.get("length", (fallback_tail - current_head).length))
                if not pinned_value and length <= _BonePhysics.EPSILON:
                    continue

                fallback_axis = pose_bone.tail.copy() - pose_bone.head.copy()
                fallback_axis = (
                    fallback_axis.normalized()
                    if fallback_axis.length > _BonePhysics.EPSILON
                    else mathutils.Vector((0.0, 0.0, 1.0))
                )
                init_axis_local_value = _BonePhysics.vector3(joint.get("init_axis_local"), fallback_axis)
                if not pinned_value and init_axis_local_value.length <= _BonePhysics.EPSILON:
                    continue

                parent = getattr(pose_bone, "parent", None)
                hit_radius, collided_by_group = _BonePhysics.vrm_spring_bone_collision_profile(armature_obj, bone_name)
                joint_template = dict(joint)
                joint_template.pop("prev_tail", None)
                joint_template.pop("current_tail", None)
                static_records.append(
                    {
                        "bone_name": bone_name,
                        "pose_bone": pose_bone,
                        "pinned": pinned_value,
                        "joint_template": joint_template,
                        "fallback_tail": fallback_tail,
                        "length": max(length, 0.0),
                        "init_axis_local_np": _MeshPhysics.vector_to_numpy(init_axis_local_value),
                        "init_axis_parent_np": _MeshPhysics.vector_to_numpy(
                            _BonePhysics.vector3(joint.get("init_axis_parent"), fallback_axis)
                        ),
                        "init_rotation_np": _MeshPhysics.quaternion_to_numpy(
                            _BonePhysics.quaternion_from_value(
                                joint.get("init_rotation"),
                                pose_bone.matrix.to_quaternion(),
                            )
                        ),
                        "init_scale_np": _MeshPhysics.vector_to_numpy(
                            _BonePhysics.vector3(joint.get("init_scale"), pose_bone.matrix.to_scale())
                        ),
                        "parent": parent,
                        "parent_name": parent.name if parent is not None else "",
                        "use_connect": bool(getattr(getattr(pose_bone, "bone", None), "use_connect", False)),
                        "hit_radius": float(hit_radius),
                        "collided_by_group": int(collided_by_group),
                    }
                )

            batches = []
            batch = []
            batch_names = set()
            for record in static_records:
                if batch and record["parent_name"] in batch_names and not record["use_connect"]:
                    batches.append(batch)
                    batch = []
                    batch_names = set()
                batch.append(record)
                batch_names.add(record["bone_name"])
            if batch:
                batches.append(batch)

            batch_runtimes = []
            chain_collision_mask = 0
            for batch in batches:
                bone_count = len(batch)
                if bone_count <= 0:
                    continue
                batch_indices = {record["bone_name"]: index for index, record in enumerate(batch)}
                current_pose_matrices = np.empty((bone_count, 16), dtype=np.float32)
                current_pose_quaternions = np.empty((bone_count, 4), dtype=np.float32)
                current_pose_tails = np.empty((bone_count, 3), dtype=np.float32)
                lengths = np.empty(bone_count, dtype=np.float32)
                init_axis_local = np.empty((bone_count, 3), dtype=np.float32)
                init_axis_parent = np.empty((bone_count, 3), dtype=np.float32)
                init_rotations = np.empty((bone_count, 4), dtype=np.float32)
                init_scales = np.empty((bone_count, 3), dtype=np.float32)
                parent_indices = np.full(bone_count, -1, dtype=np.int32)
                pinned = np.zeros(bone_count, dtype=np.uint8)
                use_connect = np.zeros(bone_count, dtype=np.uint8)
                hit_radii = np.empty(bone_count, dtype=np.float32)
                collided_by_groups = np.empty(bone_count, dtype=np.int32)

                for index, record in enumerate(batch):
                    parent_indices[index] = int(batch_indices.get(record["parent_name"], -1))
                    pinned[index] = 1 if record["pinned"] else 0
                    use_connect[index] = 1 if record["use_connect"] else 0
                    lengths[index] = float(record["length"])
                    init_axis_local[index] = record["init_axis_local_np"]
                    init_axis_parent[index] = record["init_axis_parent_np"]
                    init_rotations[index] = record["init_rotation_np"]
                    init_scales[index] = record["init_scale_np"]
                    hit_radii[index] = float(record["hit_radius"])
                    collided_by_groups[index] = int(record["collided_by_group"])
                    if record["hit_radius"] > _BonePhysics.EPSILON:
                        chain_collision_mask |= int(record["collided_by_group"])
                    pose_bone = record["pose_bone"]
                    matrix = pose_bone.matrix
                    _SpringBoneVRMCppBackend.write_matrix4_row(current_pose_matrices, index, matrix)
                    _SpringBoneVRMCppBackend.write_quaternion_row(current_pose_quaternions, index, matrix.to_quaternion())
                    _SpringBoneVRMCppBackend.write_vector3_row(current_pose_tails, index, record["fallback_tail"])

                batch_runtimes.append(
                    {
                        "records": batch,
                        "pose_refresh_indices": tuple(
                            index
                            for index, record in enumerate(batch)
                            if bool(record["pinned"]) or float(record["length"]) <= _BonePhysics.EPSILON
                        ),
                        "current_pose_matrices": current_pose_matrices,
                        "current_pose_quaternions": current_pose_quaternions,
                        "current_pose_tails": current_pose_tails,
                        "lengths": lengths,
                        "init_axis_local": init_axis_local,
                        "init_axis_parent": init_axis_parent,
                        "init_rotations": init_rotations,
                        "init_scales": init_scales,
                        "parent_indices": parent_indices,
                        "pinned": pinned,
                        "use_connect": use_connect,
                        "hit_radii": hit_radii,
                        "collided_by_groups": collided_by_groups,
                        "current_tails": np.empty((bone_count, 3), dtype=np.float32),
                        "prev_tails": np.empty((bone_count, 3), dtype=np.float32),
                        "target_matrices": np.empty((bone_count, 16), dtype=np.float32),
                        "target_quaternions": np.empty((bone_count, 4), dtype=np.float32),
                        "current_heads": np.empty((bone_count, 3), dtype=np.float32),
                        "parent_pose_quaternions": np.empty((bone_count, 4), dtype=np.float32),
                    }
                )

            chain_runtime_by_root[root_name] = {
                "bones": bones,
                "simulated_names": simulated_names,
                "chain_bones": set(bones),
                "chain_collision_mask": int(chain_collision_mask),
                "batches": batch_runtimes,
                "collider_arrays": _SpringBoneVRMCppBackend.empty_collision_arrays(),
            }

        return chain_runtime_by_root

    @classmethod
    def refresh_cpp_chain_runtime(cls, armature_obj: bpy.types.Object, chain_runtime_by_root: dict) -> None:
        armature_world_matrix = armature_obj.matrix_world
        for chain_runtime in chain_runtime_by_root.values():
            if not isinstance(chain_runtime, dict):
                continue
            for batch_runtime in chain_runtime.get("batches", []):
                records = batch_runtime.get("records", []) if isinstance(batch_runtime, dict) else []
                current_pose_matrices = batch_runtime["current_pose_matrices"]
                current_pose_quaternions = batch_runtime["current_pose_quaternions"]
                current_pose_tails = batch_runtime["current_pose_tails"]

                for index in batch_runtime.get("pose_refresh_indices", ()):
                    record = records[index]
                    pose_bone = record.get("pose_bone")
                    if pose_bone is None:
                        continue
                    matrix = pose_bone.matrix
                    fallback_tail = armature_world_matrix @ pose_bone.tail
                    record["fallback_tail"] = fallback_tail
                    _SpringBoneVRMCppBackend.write_matrix4_row(current_pose_matrices, index, matrix)
                    _SpringBoneVRMCppBackend.write_quaternion_row(current_pose_quaternions, index, matrix.to_quaternion())
                    _SpringBoneVRMCppBackend.write_vector3_row(current_pose_tails, index, fallback_tail)

    @classmethod
    def solve_cpp(cls, runtime: dict) -> dict:
        armature_obj = runtime["armature_obj"]
        settings = runtime["settings"]
        colliders = runtime["colliders"]
        collider_arrays = runtime.get("collider_arrays")
        collider_group_bits = runtime.get("collider_group_bits")
        collider_self_bones = runtime.get("collider_self_bones")
        collider_self_owners = runtime.get("collider_self_owners")
        substep_count = runtime["substep_count"]
        step_dt = runtime["dt"] / substep_count if substep_count > 0 else runtime["dt"]
        chains_state = runtime["state"].get("chains", {})
        target_pose_matrices = runtime["target_pose_matrices"]
        target_tail_worlds = runtime["target_tail_worlds"]
        target_pose_quaternions = {}
        timing = runtime.get("timing")
        armature_world = _MeshPhysics.matrix4_to_numpy(armature_obj.matrix_world).reshape(16)
        armature_world_inv = _MeshPhysics.matrix4_to_numpy(armature_obj.matrix_world.inverted()).reshape(16)
        root_quaternion = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
        root_tail_world = np.zeros(3, dtype=np.float32)
        if isinstance(collider_arrays, tuple) and len(collider_arrays) == 6:
            (
                all_collider_types,
                all_collider_groups,
                all_collider_centers,
                all_collider_segment_a,
                all_collider_segment_b,
                all_collider_radii,
            ) = collider_arrays
        else:
            (
                all_collider_types,
                all_collider_groups,
                all_collider_centers,
                all_collider_segment_a,
                all_collider_segment_b,
                all_collider_radii,
            ) = _SpringBoneVRMCppBackend.collision_arrays(colliders)
        if isinstance(collider_group_bits, np.ndarray) and collider_group_bits.shape[0] == all_collider_groups.shape[0]:
            all_collider_group_bits = collider_group_bits
        else:
            all_collider_group_bits = np.asarray(
                [_BonePhysics.collision_group_bit(group) for group in all_collider_groups],
                dtype=np.int32,
            )
        if not isinstance(collider_self_bones, list):
            collider_self_bones = [
                str(collider.get("bone") or "")
                if (
                    isinstance(collider, dict)
                    and collider.get("owner_type") == "BONE"
                    and collider.get("owner") is armature_obj
                )
                else ""
                for collider in colliders
            ]
        if not isinstance(collider_self_owners, list):
            collider_self_owners = [
                int(collider.get("owner").as_pointer())
                if (
                    isinstance(collider, dict)
                    and collider.get("owner_type") == "BONE"
                    and hasattr(collider.get("owner"), "as_pointer")
                )
                else 0
                for collider in colliders
            ]
        armature_pointer = int(armature_obj.as_pointer()) if hasattr(armature_obj, "as_pointer") else 0

        def select_collider_arrays(chain_bones: set[str], chain_collision_mask: int) -> tuple:
            if all_collider_types.size == 0 or chain_collision_mask == 0:
                return _SpringBoneVRMCppBackend.empty_collision_arrays()
            mask = (all_collider_group_bits & int(chain_collision_mask)) != 0
            if np.any(mask):
                for index, bone_name in enumerate(collider_self_bones):
                    owner_pointer = int(collider_self_owners[index]) if index < len(collider_self_owners) else 0
                    if bone_name and owner_pointer == armature_pointer and bone_name in chain_bones:
                        mask[index] = False
            if not np.any(mask):
                return _SpringBoneVRMCppBackend.empty_collision_arrays()
            return (
                np.ascontiguousarray(all_collider_types[mask], dtype=np.int32),
                np.ascontiguousarray(all_collider_groups[mask], dtype=np.int32),
                np.ascontiguousarray(all_collider_centers[mask], dtype=np.float32).reshape((-1, 3)),
                np.ascontiguousarray(all_collider_segment_a[mask], dtype=np.float32).reshape((-1, 3)),
                np.ascontiguousarray(all_collider_segment_b[mask], dtype=np.float32).reshape((-1, 3)),
                np.ascontiguousarray(all_collider_radii[mask], dtype=np.float32),
            )

        state = runtime["state"]
        cpp_runtime = state.get("cpp_runtime") if isinstance(state, dict) else None
        cpp_runtime_key = (
            "spring_bone_vrm_cpp",
            state.get("topology_key") if isinstance(state, dict) else None,
            tuple((str(setting.get("root_bone") or ""), tuple(setting.get("bones") or [])) for setting in settings),
            tuple(
                (str(root_name), tuple((chain_state.get("bones") or []) if isinstance(chain_state, dict) else ()))
                for root_name, chain_state in sorted(chains_state.items())
            ),
        )
        if not isinstance(cpp_runtime, dict) or cpp_runtime.get("key") != cpp_runtime_key:
            stage_start = time.perf_counter() if timing is not None else None
            chain_runtime_by_root = cls.build_cpp_chain_runtime(armature_obj, settings, chains_state)
            cpp_runtime = {
                "key": cpp_runtime_key,
                "chains": chain_runtime_by_root,
            }
            if isinstance(state, dict):
                state["cpp_runtime"] = cpp_runtime
            if timing is not None:
                cls._add_timing(timing, "cpp_runtime", time.perf_counter() - stage_start)
        else:
            chain_runtime_by_root = cpp_runtime.get("chains", {})

        stage_start = time.perf_counter() if timing is not None else None
        cls.refresh_cpp_chain_runtime(armature_obj, chain_runtime_by_root)
        if timing is not None:
            cls._add_timing(timing, "runtime_refresh", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        for chain_runtime in chain_runtime_by_root.values():
            if not isinstance(chain_runtime, dict):
                continue
            chain_runtime["collider_arrays"] = select_collider_arrays(
                chain_runtime.get("chain_bones", set()),
                int(chain_runtime.get("chain_collision_mask", 0)),
            )
        if timing is not None:
            cls._add_timing(timing, "collision_setup", time.perf_counter() - stage_start)

        for _ in range(substep_count):
            next_chains_state = {}

            for setting in settings:
                root_name = str(setting.get("root_bone") or "")
                chain_state = chains_state.get(root_name)
                if not isinstance(chain_state, dict):
                    continue

                chain_runtime = chain_runtime_by_root.get(root_name)
                bones = list(chain_state.get("bones") or [])
                joints = chain_state.get("joints") if isinstance(chain_state.get("joints"), dict) else {}
                next_joints = {}

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

                (
                    collider_types,
                    collider_groups,
                    collider_centers,
                    collider_segment_a,
                    collider_segment_b,
                    collider_radii,
                ) = chain_runtime["collider_arrays"] if isinstance(chain_runtime, dict) else _SpringBoneVRMCppBackend.empty_collision_arrays()

                for batch_runtime in (chain_runtime.get("batches", []) if isinstance(chain_runtime, dict) else []):
                    stage_start = time.perf_counter() if timing is not None else None
                    source_records = batch_runtime.get("records", []) if isinstance(batch_runtime, dict) else []
                    batch_parent_indices = batch_runtime["parent_indices"]
                    active_entries = []
                    all_records_active = True
                    for source_index, record in enumerate(source_records):
                        joint = joints.get(record["bone_name"]) if isinstance(joints, dict) else None
                        if not isinstance(joint, dict):
                            all_records_active = False
                            continue
                        parent_source_index = int(batch_parent_indices[source_index])
                        parent_is_active = (
                            parent_source_index >= 0
                            and parent_source_index < len(source_records)
                            and isinstance(joints.get(source_records[parent_source_index]["bone_name"]), dict)
                        )
                        if record["use_connect"] and parent_is_active:
                            # C++ replaces connected child heads with the solved parent tail.
                            head = record["fallback_tail"]
                        else:
                            head = _BonePhysics.target_head_world(
                                armature_obj,
                                record["pose_bone"],
                                target_pose_matrices,
                                target_tail_worlds,
                            )
                        current_tail = _BonePhysics.vector3(joint.get("current_tail"), record["fallback_tail"])
                        prev_tail_value = joint.get("prev_tail")
                        active_entries.append((source_index, record, head, current_tail, prev_tail_value))
                    bone_count = len(active_entries)
                    if bone_count <= 0:
                        continue

                    current_tails = batch_runtime["current_tails"]
                    prev_tails = batch_runtime["prev_tails"]
                    target_matrices = batch_runtime["target_matrices"]
                    target_quaternions = batch_runtime["target_quaternions"]
                    current_heads = batch_runtime["current_heads"]
                    parent_pose_quaternions = batch_runtime["parent_pose_quaternions"]
                    gravity_dir = np.asarray(gravity, dtype=np.float32)
                    if all_records_active and bone_count == len(source_records):
                        current_pose_matrices = batch_runtime["current_pose_matrices"]
                        current_pose_quaternions = batch_runtime["current_pose_quaternions"]
                        current_pose_tails = batch_runtime["current_pose_tails"]
                        lengths = batch_runtime["lengths"]
                        init_axis_local = batch_runtime["init_axis_local"]
                        init_axis_parent = batch_runtime["init_axis_parent"]
                        init_rotations = batch_runtime["init_rotations"]
                        init_scales = batch_runtime["init_scales"]
                        parent_indices = batch_runtime["parent_indices"]
                        pinned = batch_runtime["pinned"]
                        use_connect = batch_runtime["use_connect"]
                        hit_radii = batch_runtime["hit_radii"]
                        collided_by_groups = batch_runtime["collided_by_groups"]
                    else:
                        source_to_packed = {int(entry[0]): index for index, entry in enumerate(active_entries)}
                        source_indices = np.fromiter((int(entry[0]) for entry in active_entries), dtype=np.int32, count=bone_count)
                        current_pose_matrices = batch_runtime["current_pose_matrices"][source_indices]
                        current_pose_quaternions = batch_runtime["current_pose_quaternions"][source_indices]
                        current_pose_tails = batch_runtime["current_pose_tails"][source_indices]
                        lengths = batch_runtime["lengths"][source_indices]
                        init_axis_local = batch_runtime["init_axis_local"][source_indices]
                        init_axis_parent = batch_runtime["init_axis_parent"][source_indices]
                        init_rotations = batch_runtime["init_rotations"][source_indices]
                        init_scales = batch_runtime["init_scales"][source_indices]
                        parent_indices = batch_runtime["parent_indices"][source_indices].copy()
                        for index in range(bone_count):
                            parent_source_index = int(parent_indices[index])
                            parent_indices[index] = int(source_to_packed.get(parent_source_index, -1))
                        pinned = batch_runtime["pinned"][source_indices]
                        use_connect = batch_runtime["use_connect"][source_indices]
                        hit_radii = batch_runtime["hit_radii"][source_indices]
                        collided_by_groups = batch_runtime["collided_by_groups"][source_indices]
                    target_matrices[:] = current_pose_matrices

                    for index, (_source_index, record, head, current_tail, prev_tail_value) in enumerate(active_entries):
                        parent = record["parent"]
                        parent_index = int(parent_indices[index])

                        parent_quaternion = mathutils.Quaternion((1.0, 0.0, 0.0, 0.0)) if parent_index < 0 else None
                        parent_target_quaternion = None
                        if parent_index < 0 and parent is not None:
                            parent_target_quaternion = target_pose_quaternions.get(parent.name)
                            if parent_target_quaternion is None:
                                parent_target_matrix = target_pose_matrices.get(parent.name)
                                if parent_target_matrix is not None:
                                    parent_quaternion = parent_target_matrix.to_quaternion()
                                else:
                                    parent_quaternion = parent.matrix.to_quaternion()

                        _SpringBoneVRMCppBackend.write_vector3_row(current_tails, index, current_tail)
                        _SpringBoneVRMCppBackend.write_vector3_value_row(prev_tails, index, prev_tail_value, record["fallback_tail"])
                        _SpringBoneVRMCppBackend.write_vector3_row(current_heads, index, head)
                        if parent_target_quaternion is not None:
                            _SpringBoneVRMCppBackend.copy_quaternion_row(parent_pose_quaternions, index, parent_target_quaternion)
                        elif parent_quaternion is not None:
                            _SpringBoneVRMCppBackend.write_quaternion_row(parent_pose_quaternions, index, parent_quaternion)
                    if timing is not None:
                        cls._add_timing(timing, "pack", time.perf_counter() - stage_start)

                    stage_start = time.perf_counter() if timing is not None else None
                    _SpringBoneVRMCppBackend.solve_spring_bone_vrm_cpp(
                        current_tails,
                        prev_tails,
                        target_matrices,
                        target_quaternions,
                        current_heads,
                        current_pose_matrices,
                        current_pose_quaternions,
                        parent_pose_quaternions,
                        current_pose_tails,
                        lengths,
                        init_axis_local,
                        init_axis_parent,
                        init_rotations,
                        init_scales,
                        parent_indices,
                        pinned,
                        use_connect,
                        root_quaternion,
                        root_tail_world,
                        armature_world,
                        armature_world_inv,
                        gravity_dir,
                        hit_radii,
                        collided_by_groups,
                        collider_types,
                        collider_groups,
                        collider_centers,
                        collider_segment_a,
                        collider_segment_b,
                        collider_radii,
                        step_dt,
                        1,
                        stiffness_force,
                        drag_force,
                        gravity_power,
                    )
                    if timing is not None:
                        cls._add_timing(timing, "native_core", time.perf_counter() - stage_start)

                    stage_start = time.perf_counter() if timing is not None else None
                    tail_stage_start = time.perf_counter() if timing is not None else None
                    valid_updates = []
                    for index, (_source_index, record, head, current_tail, _prev_tail) in enumerate(active_entries):
                        bone_name = record["bone_name"]
                        parent_index = int(parent_indices[index])
                        update_head = head
                        if record["use_connect"] and parent_index >= 0:
                            update_head = _SpringBoneVRMCppBackend.vector_from_numpy3(current_tails[parent_index])
                        next_tail = _SpringBoneVRMCppBackend.vector_from_numpy3(current_tails[index])
                        if (next_tail - update_head).length <= _BonePhysics.EPSILON:
                            continue
                        valid_updates.append((index, record, bone_name, next_tail, current_tail))
                    if timing is not None:
                        cls._add_timing(timing, "unpack_tail", time.perf_counter() - tail_stage_start)

                    state_stage_start = time.perf_counter() if timing is not None else None
                    for index, record, bone_name, next_tail, current_tail in valid_updates:
                        next_joint = dict(record["joint_template"])
                        next_joint["prev_tail"] = current_tail
                        next_joint["current_tail"] = next_tail
                        next_joints[bone_name] = next_joint
                        target_tail_worlds[bone_name] = next_tail
                    if timing is not None:
                        cls._add_timing(timing, "unpack_state", time.perf_counter() - state_stage_start)

                    matrix_stage_start = time.perf_counter() if timing is not None else None
                    for index, _record, bone_name, _next_tail, _current_tail in valid_updates:
                        target_pose_matrices[bone_name] = _SpringBoneVRMCppBackend.matrix_from_numpy(target_matrices[index])
                        target_pose_quaternions[bone_name] = target_quaternions[index].copy()
                    if timing is not None:
                        cls._add_timing(timing, "unpack_matrix", time.perf_counter() - matrix_stage_start)
                        cls._add_timing(timing, "unpack", time.perf_counter() - stage_start)

                next_chains_state[root_name] = {
                    "bones": bones,
                    "joints": next_joints,
                }

            chains_state = next_chains_state

        return chains_state

    @classmethod
    def run(
        cls,
        backend_tag: str,
        cache_state: _OmniCache,
        armature_obj: bpy.types.Object,
        vrm_chain_settings: list[typing.Any],
        scene: bpy.types.Scene = None,
        enabled: bool = True,
        reset: bool = False,
        substeps: int = 1,
        debug_output: bool = False,
    ) -> tuple[_OmniCache, list[_OmniBone], bpy.types.Object, int, int]:
        timing = cls._begin_timing() if debug_output else None
        backend_tag = str(backend_tag or "py").lower()
        runtime = cls.prepare(
            backend_tag=backend_tag,
            cache_state=cache_state,
            armature_obj=armature_obj,
            vrm_chain_settings=vrm_chain_settings,
            scene=scene,
            enabled=enabled,
            reset=reset,
            substeps=substeps,
            timing=timing,
        )
        early_result = runtime.get("early_result")
        if early_result is not None:
            if timing is not None:
                collider_count = int(runtime.get("collider_count", 0) or 0)
                cls._publish_debug_timing(
                    runtime["armature_obj"],
                    runtime["current_frame"],
                    len(runtime["settings"]),
                    collider_count,
                    backend_tag,
                    timing,
                )
            return early_result

        stage_start = time.perf_counter() if timing is not None else None
        if backend_tag in {"cpp", "c++", "native"}:
            if not _SpringBoneVRMCppBackend.is_available():
                raise ImportError("hotools_native is not available; build the native backend first")
            chains_state = cls.solve_cpp(runtime)
        elif backend_tag in {"py", "python"}:
            chains_state = cls.solve_py(runtime)
        else:
            raise ValueError(f"unsupported VRM SpringBone backend: {backend_tag}")
        if timing is not None:
            cls._add_timing(timing, "solve", time.perf_counter() - stage_start)

        state = runtime["state"]
        state["frame"] = runtime["current_frame"]
        state["chains"] = chains_state
        stage_start = time.perf_counter() if timing is not None else None
        cls.write_pose(
            runtime["armature_obj"],
            runtime["settings"],
            runtime["target_pose_matrices"],
            state.get("write_records"),
            timing,
            state.setdefault("write_runtime", {}),
        )
        if timing is not None:
            cls._add_timing(timing, "write", time.perf_counter() - stage_start)
        stage_start = time.perf_counter() if timing is not None else None
        runtime["armature_obj"].update_tag()
        if timing is not None:
            cls._add_timing(timing, "write_tag", time.perf_counter() - stage_start)
        if timing is not None:
            collider_count = int(runtime.get("collider_count", len(runtime.get("colliders") or [])) or 0)
            cls._publish_debug_timing(
                runtime["armature_obj"],
                runtime["current_frame"],
                len(runtime["settings"]),
                collider_count,
                backend_tag,
                timing,
            )
        return (
            _OmniCache(_as_cache_owner(state)),
            runtime["affected_bones"],
            runtime["armature_obj"],
            len(runtime["settings"]),
            int(runtime.get("collider_count", len(runtime.get("colliders") or [])) or 0),
        )


# TODO(batch-backend): 将多骨架解算提升到 C++ 层真正批量处理
#   当前是逐骨架串行分发，性能瓶颈在骨架数量很大（20+）且需要跨骨架内碰撞时才会显现。
#   改动要点：
#   1. solve_spring_bone_vrm_cpp 签名改为接受 armature_world_per_bone (N,16) 和
#      armature_world_inv_per_bone (N,16)，替换单骨架的两个 4x4 矩阵。
#   2. 自碰撞过滤从"属于本骨架"改为按 armature_id_per_bone (N,) 匹配，
#      否则骨架 A 的骨骼会错误排除骨架 B 的碰撞体。
#   3. hotools_native 侧对应增加批量接口，Python 桥接层打包多骨架数组后一次调用。
def _run_spring_bone_vrm_node(
    backend_tag: str,
    cache_state: _OmniCache,
    vrm_chain_settings: list[typing.Any],
    scene: bpy.types.Scene = None,
    enabled: bool = True,
    reset: bool = False,
    substeps: int = 1,
    debug_output: bool = False,
) -> tuple[_OmniCache, list[_OmniBone], list[bpy.types.Object], int, int]:
    """
    多骨架批量弹簧骨解算入口。

    从 vrm_chain_settings 自动提取所有涉及的骨架并按出现顺序去重，
    对每个骨架独立调用 _SpringBoneVRM.run()，共享同一个节点缓存入口。
    缓存结构：{"armatures": {arm_name_full: per_arm_cache, ...}}
    """
    # 从 vrm_chain_settings 展平并按骨架分组，保持出现顺序
    flat_settings = _BonePhysics.flatten_vrm_spring_bone_chain_settings(vrm_chain_settings)
    armature_order: list[int] = []
    armature_settings_map: dict[int, tuple[bpy.types.Object, list]] = {}
    for setting in flat_settings:
        arm = setting.get("armature")
        if arm is None:
            continue
        key = int(arm.as_pointer())
        if key not in armature_settings_map:
            armature_settings_map[key] = (arm, [])
            armature_order.append(key)
        armature_settings_map[key][1].append(setting)

    # 提取各骨架子缓存；兼容旧的单骨架缓存（不含 "armatures" 键时视为空）
    cache_state = cache_visible_value(cache_state)
    if isinstance(cache_state, dict) and isinstance(cache_state.get("armatures"), dict):
        armature_caches: dict = cache_state["armatures"]
    else:
        armature_caches = {}

    all_affected_bones: list = []
    all_armatures: list[bpy.types.Object] = []
    total_chains = 0
    total_colliders = 0
    next_armature_caches: dict = {}

    for key in armature_order:
        arm_obj, arm_settings = armature_settings_map[key]
        arm_name = arm_obj.name_full
        arm_cache = cache_visible_value(armature_caches.get(arm_name))

        next_cache, affected_bones, _arm, chains, colliders = _SpringBoneVRM.run(
            backend_tag=backend_tag,
            cache_state=arm_cache,
            armature_obj=arm_obj,
            vrm_chain_settings=arm_settings,
            scene=scene,
            enabled=enabled,
            reset=reset,
            substeps=substeps,
            debug_output=debug_output,
        )
        next_armature_caches[arm_name] = cache_visible_value(next_cache)
        all_affected_bones.extend(affected_bones)
        all_armatures.append(arm_obj)
        total_chains += chains
        total_colliders += colliders

    combined_cache = _OmniCache(_as_cache_owner({"armatures": next_armature_caches}))
    return combined_cache, all_affected_bones, all_armatures, total_chains, total_colliders

@omni(
    enable=True,
    always_run=True,   # 物理解算器，每帧推进Verlet状态
    bl_label="弹簧骨-VRM",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "缓存",
        "VRM链设置",
        "场景",
        "启用",
        "重置",
        "子步数",
        "调试输出",
    ],
    input_init={
        "substeps": {"min_value": 1, "max_value": 16},
        "debug_output": {"description": "开启后按 MC2 风格在控制台打印本节点各阶段平均耗时。"},
    },
    omni_presets=_SPRING_BONE_VRM_PRESETS,
    _OUTPUT_NAME=["缓存", "骨骼", "骨架列表", "链数量", "碰撞体数量"],
    omni_description="""
    多骨架批量 VRM SpringBone 解算器，自动从 VRM链设置 中提取所有涉及的骨架并分别解算。

    接法：
    1. 缓存读取节点接到本节点”缓存”，本节点输出”缓存”再接缓存写入节点。
    2. 来自任意多个骨架的”弹簧骨-VRM链设置”直接接到”VRM链设置”多重输入，无需额外指定骨架。
    3. 场景直接作为唯一的外部碰撞来源；解算器会在内部枚举可见 Object.hotools_object_collision 和 Armature Bone.hotools_collision 生成碰撞快照。

    运行规则：
    解算器按链设置中出现的顺序对每个骨架独立维护缓存和解算状态，多骨架共享同一节点缓存入口。
    每个骨架按 root 名排序设置，拒绝重复 root 或重复模拟同一根骨骼。
    缓存按骨架 name_full 分区存储，拓扑变化或打开”重置”时对该骨架重建状态。
    当前消费类型：SPHERE、CAPSULE。球体读取 radius、offset、primary_collision_group；胶囊额外读取 length，并沿局部 Y 轴生成线段。
    模拟骨骼自身的 hit radius 和 collided_by_groups 来自该骨骼 hotools_collision；外部被动碰撞体来自场景快照。
    链 root 恒为硬 Pin；非 root 骨骼的 Pin 属性（hotools_collision.pin）只在 cache 重建时读取，模拟中修改不会立即生效。
    检测到跳帧或倒放时会先恢复初始姿态，并输出空缓存，让缓存写入节点清掉旧速度。

    输出”骨骼”是所有骨架中受影响的模拟骨集合，可继续接到”骨骼姿态K帧”。
    “骨架列表”是本帧参与解算的骨架对象列表。
    “链数量”和”碰撞体数量”是所有骨架的汇总值，用于快速确认本帧实际参与解算的数据规模。
    """,
    mute_passthrough={"_OUTPUT0": "cache_state"},
)
def springBoneVRM(
    cache_state: _OmniCache,
    vrm_chain_settings: list[typing.Any],
    scene: bpy.types.Scene = None,
    enabled: bool = True,
    reset: bool = False,
    substeps: int = 1,
    debug_output: bool = False,
) -> tuple[_OmniCache, list[_OmniBone], list[bpy.types.Object], int, int]:
    return _run_spring_bone_vrm_node(
        backend_tag="py",
        cache_state=cache_state,
        vrm_chain_settings=vrm_chain_settings,
        scene=scene,
        enabled=enabled,
        reset=reset,
        substeps=substeps,
        debug_output=debug_output,
    )


@omni(
    enable=True,
    always_run=True,   # 物理解算器，每帧推进Verlet状态
    bl_label="弹簧骨-VRM-CPP",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "缓存",
        "VRM链设置",
        "场景",
        "启用",
        "重置",
        "子步数",
        "调试输出",
    ],
    input_init={
        "substeps": {"min_value": 1, "max_value": 16},
        "debug_output": {"description": "开启后按 MC2 风格在控制台打印本节点各阶段平均耗时。"},
    },
    omni_presets=_SPRING_BONE_VRM_PRESETS,
    _OUTPUT_NAME=["缓存", "骨骼", "骨架列表", "链数量", "碰撞体数量"],
    omni_description="""
    “弹簧骨-VRM”的 C++ 后端版本，同样支持多骨架批量解算。

    注意：由于数据交互传输开销，C++ 后端在最简场景中会比 Python 后端慢，但在碰撞复杂时可能更有优势。
    具体选择需要自行通过打开 tree 的 debug 运行时长查看，对比开销选择合适的后端。

    节点输入、输出、缓存协议、跳帧规则和姿态写回方式与 Python 版保持一致。
    Python 层只负责收集 Blender 数据、维护 cache、生成 native 数组和写回 PoseBone；弹簧积分、长度约束、碰撞投影和子步循环由 hotools_native 执行。
    """,
    mute_passthrough={"_OUTPUT0": "cache_state"},
)
def springBoneVRM_CPP(
    cache_state: _OmniCache,
    vrm_chain_settings: list[typing.Any],
    scene: bpy.types.Scene = None,
    enabled: bool = True,
    reset: bool = False,
    substeps: int = 1,
    debug_output: bool = False,
) -> tuple[_OmniCache, list[_OmniBone], list[bpy.types.Object], int, int]:
    return _run_spring_bone_vrm_node(
        backend_tag="cpp",
        cache_state=cache_state,
        vrm_chain_settings=vrm_chain_settings,
        scene=scene,
        enabled=enabled,
        reset=reset,
        substeps=substeps,
        debug_output=debug_output,
    )


@omni(
    enable=True,
    always_run=True,   # 物理解算器，每帧推进XPBD状态
    bl_label="网格物理-XPBD",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "缓存",
        "物体",
        "场景",
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
        "damping": {
            "description": "每个 Blender 场景帧的速度阻尼；求解器会按子步数换算到每个子步。",
            "min_value": 0.0,
            "max_value": 1.0,
        },
        "stretch_compliance": {"min_value": 0.0},
        "bend_compliance": {"min_value": 0.0},
        "debug_output": {"description": "开启后每隔约 1 秒在控制台打印本节点各阶段平均耗时。"},
    },
    omni_presets=_MESH_XPBD_PRESETS,
    _OUTPUT_NAME=["缓存", "物体", "顶点数", "约束数"],
    omni_description="""
    Python 参考实现。用于定义网格 XPBD 的输入、输出、cache 协议、跳帧规则与 CPP 后端对齐基准。

    I/O 约定：
    缓存必须通过同名缓存读写节点闭环；节点只写 `xpbd_delta` 点域属性，并由自身创建的 GN 后置位移修改器消费；不修改 Basis 或 mesh 顶点。
    场景输入提供 frame_current、render.fps / fps_base，并作为骨骼/Object 被动碰撞体的枚举范围。
    被动碰撞体来自可见 Object.hotools_object_collision 和 Armature Bone.hotools_collision；当前旧 XPBD 蓝本消费类型为 SPHERE、CAPSULE。
    球体读取 collision_type、radius、offset、primary_collision_group；胶囊额外读取 length，并沿局部 Y 轴生成线段。
    Pin、逐顶点碰撞半径、主碰撞组和被碰撞组来自物体属性“HoTools简单布料”；输出属性与 GN 修改器由本 solver 自己维护。

    求解模型：
    rest 顶点取自 Basis/reference key；mesh edge 生成拉伸距离约束，共边三角面的 opposite 顶点生成弯曲距离约束。
    每次执行推进一个 Blender 场景帧：Verlet 预测，按迭代次数投影 pin、stretch、bend 与被动碰撞约束，再批量写回 `xpbd_delta`。
    damping 是“每场景帧速度阻尼”，内部按 substeps 换算为子步阻尼；stretch_compliance / bend_compliance 为 XPBD 顺从度，0 表示硬约束。

    坐标空间：
    Blender mesh 坐标与 `xpbd_delta` 属性为物体局部空间；XPBD cache 与求解阶段使用世界空间。
    cache 重建流程：rest_local_positions = Basis/reference local；rest_positions = matrix_world * rest_local_positions。
    写回流程：world_delta = positions - rest_positions；xpbd_delta = matrix_world.inverted().to_3x3() * world_delta。
    重力方向、被动球/胶囊碰撞体、逐顶点碰撞半径均在世界空间参与求解；局部半径会按 matrix_world 最大轴缩放转换。

    数据生命周期：
    编译期固定节点函数、socket 连线与常量输入；不固化场景状态、mesh 顶点、碰撞体或 Blender 指针。
    每帧读取运行时 socket 值、scene frame/fps、object matrix_world、可见碰撞体及其当前变换。
    cache 重建时固定 rest_local_positions、topology、约束索引、pin 权重、局部碰撞半径和碰撞组。
    cache 运行态只推进 positions、prev_positions、frame。matrix_world 变化时重新派生 rest_positions；3x3 部分变化时重算约束长度和世界空间半径。
    positions / prev_positions 保持世界空间惯性，不随物体变换整体迁移。

    失效规则：
    仅接受 current_frame == cached_frame + 1。跳帧、倒放、同帧重复或 reset 时清空 `xpbd_delta` 并清空连续速度。
    topology、pin、碰撞半径或碰撞组配置变化后，需要 reset、跳帧保护或 cache 重建路径生效。
    当前被动碰撞消费范围包括骨骼/Object 球体与胶囊。
    """,
    mute_passthrough={"_OUTPUT0": "cache_state", "_OUTPUT1": "obj"},
)
def meshPhysicsXPBD(
    cache_state: _OmniCache,
    obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
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
    return _run_mesh_xpbd_node(
        use_cpp=False,
        cache_state=cache_state,
        obj=obj,
        scene=scene,
        enabled=enabled,
        reset=reset,
        substeps=substeps,
        iterations=iterations,
        gravity_dir=gravity_dir,
        gravity_power=gravity_power,
        damping=damping,
        stretch_compliance=stretch_compliance,
        bend_compliance=bend_compliance,
        debug_output=debug_output,
    )


@omni(
    enable=True,
    always_run=True,   # 物理解算器，每帧推进XPBD状态
    bl_label="网格物理-XPBD-CPP",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "缓存",
        "物体",
        "场景",
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
        "damping": {
            "description": "每个 Blender 场景帧的速度阻尼；求解器会按子步数换算到每个子步。",
            "min_value": 0.0,
            "max_value": 1.0,
        },
        "stretch_compliance": {"min_value": 0.0},
        "bend_compliance": {"min_value": 0.0},
        "debug_output": {"description": "开启后每隔约 1 秒在控制台打印本节点各阶段平均耗时。"},
    },
    omni_presets=_MESH_XPBD_PRESETS,
    _OUTPUT_NAME=["缓存", "物体", "顶点数", "约束数"],
    omni_description="""
    C++ 求解后端。与“网格物理-XPBD”共享输入、输出、cache 协议、跳帧规则和 Blender 侧数据生命周期。

    职责划分：
    Python 层负责 Blender 数据读取、校验、`xpbd_delta`/GN 输出、cache 管理、对象变换同步和碰撞体快照。
    C++ 层负责预测、pin、stretch、bend、被动碰撞投影和子步/迭代循环。
    native 不访问 bpy，不保存 Blender 指针，不维护跨帧全局状态。
    当前传入 native 的被动碰撞数组类型为 SPHERE、CAPSULE。

    坐标空间：
    Blender mesh 坐标与 `xpbd_delta` 属性为物体局部空间；传入 native 的 rest_positions、positions、prev_positions、约束长度、碰撞半径和 collider 数组均为世界空间。
    Python 桥接流程：Basis/reference local -> matrix_world -> world-space arrays -> native solve -> world delta -> xpbd_delta。
    reset、跳帧、倒放或同帧重复执行时不调用 native，直接清空 `xpbd_delta`。

    数据生命周期：
    编译期固定节点函数、socket 连线与常量输入；不固化场景状态、mesh 顶点、碰撞体或 Blender 指针。
    每帧读取运行时 socket 值、scene frame/fps、object matrix_world、可见碰撞体及其当前变换。
    cache 重建时固定 rest_local_positions、topology、约束索引、pin 权重、局部碰撞半径和碰撞组。
    cache 运行态只推进 positions、prev_positions、frame。matrix_world 变化时重新派生 rest_positions；3x3 部分变化时重算约束长度和世界空间半径。
    positions / prev_positions 保持世界空间惯性，不随物体变换整体迁移。

    对齐要求：
    Python 版是行为参考；CPP 版只能替换求解热路径，不改变节点使用方式、cache 语义、碰撞过滤或跳帧行为。
    两端结果不一致时，优先检查 Python 桥接层生成的 native 输入数组。
    """,
    mute_passthrough={"_OUTPUT0": "cache_state", "_OUTPUT1": "obj"},
)
def meshPhysicsXPBDCpp(
    cache_state: _OmniCache,
    obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
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
    return _run_mesh_xpbd_node(
        use_cpp=True,
        cache_state=cache_state,
        obj=obj,
        scene=scene,
        enabled=enabled,
        reset=reset,
        substeps=substeps,
        iterations=iterations,
        gravity_dir=gravity_dir,
        gravity_power=gravity_power,
        damping=damping,
        stretch_compliance=stretch_compliance,
        bend_compliance=bend_compliance,
        debug_output=debug_output,
    )


@omni(
    enable=True,
    always_run=True,   # 物理解算器，每帧推进弹簧骨状态
    bl_label="弹簧骨",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "缓存",
        "骨骼",
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
    1. 用“从根获取骨骼”生成骨骼列表，接到本节点。
    2. 缓存读取和缓存写入使用同一个缓存名，读到的缓存接本节点，输出缓存再写回。
    3. 每次执行只计算一帧，不做子步补算；dt 自动使用 render.fps / render.fps_base 的真实帧间隔。

    工作原理：
    骨链第一根骨骼只作为 center/锚点，不参与模拟；从第二根骨骼开始模拟。
    链 root 由骨骼输入解析得到，永远视为 Pin；非 root 骨骼的 Pin 属性（hotools_collision.pin）会在 cache 构建时记录，模拟中修改不会热更新。
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
    mute_passthrough={"_OUTPUT0": "cache_state", "_OUTPUT1": "bone_chain"},
)
def springBoneBase(
    cache_state: _OmniCache,
    bone_chain: list[_OmniBone],
    enabled: bool = True,
    stiffness_force: float = 1.0,
    drag_force: float = 0.4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 0.0,
) -> tuple[_OmniCache, list[_OmniBone], bpy.types.Object,]:
    bone_chain = _BonePhysics.bone_chain_from_bone_values(bone_chain)

    armature_obj = bone_chain["armature"]
    affected_bones = _BonePhysics.bone_socket_values_from_chain(bone_chain)
    current_frame = bpy.context.scene.frame_current
    cached_frame = _BonePhysics.cache_frame(cache_state)

    if cached_frame is not None and current_frame != cached_frame + 1:
        _BonePhysics.restore_initial_pose(armature_obj, cache_state)
        return _OmniCache(None), affected_bones, armature_obj

    if not _BonePhysics.spring_cache_matches(cache_state, bone_chain):
        cache_state = _BonePhysics.build_spring_cache(bone_chain)

    if not enabled:
        next_cache = dict(cache_state)
        next_cache["frame"] = int(current_frame)
        return _OmniCache(_as_cache_owner(next_cache)), affected_bones, armature_obj

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

        if bool(joint.get("pinned", False)):
            target_matrix, pinned_tail, next_joint = _BonePhysics.pinned_joint_state(
                armature_obj,
                pose_bone,
                joint,
            )
            next_joints[bone_name] = next_joint
            target_pose_matrices[bone_name] = target_matrix
            target_tail_worlds[bone_name] = pinned_tail.copy()
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
    return _OmniCache(_as_cache_owner(next_cache)), affected_bones, armature_obj


@omni(
    enable=True,
    always_run=True,   # 写入 bpy keyframe，有副作用
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
    mute_passthrough={"_OUTPUT0": "bones"},
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
