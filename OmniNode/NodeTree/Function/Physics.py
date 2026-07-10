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
    always_run=True,   # 写入 bpy keyframe，有副作用
    bl_label="骨骼姿态K帧",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["骨骼", "启用"],
    _OUTPUT_NAME=["骨骼", "写入数量"],
    omni_description="""
    给输入 Bone 集合中的 PoseBone 在当前帧插入姿态关键帧。

    接法：
    1. 把需要记录姿态的 Bone 集合接到本节点“骨骼”输入。
    2. 本节点的“骨骼”输入是多重输入，可以接一条或多条骨链。
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
