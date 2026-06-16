"""OmniNode 的 MagicaCloth2 风格布料解算节点。

本模块刻意独立于 Physics.py。Physics.py 中现有解算器继续作为隔离蓝本；
MC2 在此文件内自行管理 Blender I/O、cache、solver 数组和碰撞快照。

当前启用目标是 MeshCloth。它直接模拟用户提供的低模代理 mesh，并把结果
写回 shape key。减面、高低模映射永久不属于此解算器边界。
"""

from collections import deque
import time

from ...FunctionNodeCore import omni
from ...OmniNodeSocketMapping import _OmniCache
from .. import _Color
from . import blender_io, collision, math_utils, params
from .constants import (
    MC2_ATTR_FIXED,
    MC2_ATTR_INVALID,
    MC2_ATTR_MOTION,
    MC2_ATTR_MOVE,
    MC2_CACHE_KIND,
    MC2_CURVE_READY_PARAMETERS,
    MC2_SOLVER_VERSION,
    MC2SystemConstants,
)

import bpy
import mathutils
import numpy as np


class _MC2Common:
    """MeshCloth 与未来 BoneCloth 共用的 MC2 风格数据准备工具。"""

    EPSILON = MC2SystemConstants.EPSILON
    DEBUG_PRINT_INTERVAL = 1.0
    FRICTION_MASS = MC2SystemConstants.FRICTION_MASS
    DEPTH_MASS = MC2SystemConstants.DEPTH_MASS
    TETHER_COMPRESSION_LIMIT = MC2SystemConstants.TETHER_COMPRESSION_LIMIT
    TETHER_STRETCH_LIMIT = MC2SystemConstants.TETHER_STRETCH_LIMIT
    TETHER_STIFFNESS_WIDTH = MC2SystemConstants.TETHER_STIFFNESS_WIDTH
    TETHER_COMPRESSION_STIFFNESS = MC2SystemConstants.TETHER_COMPRESSION_STIFFNESS
    TETHER_STRETCH_STIFFNESS = MC2SystemConstants.TETHER_STRETCH_STIFFNESS
    TETHER_COMPRESSION_VELOCITY_ATTENUATION = MC2SystemConstants.TETHER_COMPRESSION_VELOCITY_ATTENUATION
    TETHER_STRETCH_VELOCITY_ATTENUATION = MC2SystemConstants.TETHER_STRETCH_VELOCITY_ATTENUATION
    MOTION_VELOCITY_ATTENUATION = MC2SystemConstants.MOTION_VELOCITY_ATTENUATION
    COLLIDER_COLLISION_DYNAMIC_FRICTION_RATIO = MC2SystemConstants.COLLIDER_COLLISION_DYNAMIC_FRICTION_RATIO
    COLLIDER_COLLISION_STATIC_FRICTION_RATIO = MC2SystemConstants.COLLIDER_COLLISION_STATIC_FRICTION_RATIO
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

        cls.add_timing(timing, "total", time.perf_counter() - float(timing.get("start", time.perf_counter())))
        key = (int(obj.as_pointer()), str(shape_key_name), "mc2_py")
        now = time.perf_counter()
        profile = cls._debug_profiles.get(key)
        if profile is None:
            profile = {
                "last_print": now,
                "frames": 0,
                "frame": frame,
                "vertex_count": vertex_count,
                "constraint_count": constraint_count,
                "stages": {},
            }
            cls._debug_profiles[key] = profile

        profile["frames"] += 1
        profile["frame"] = frame
        profile["vertex_count"] = vertex_count
        profile["constraint_count"] = constraint_count
        totals = profile["stages"]
        for stage, seconds in timing.get("stages", {}).items():
            totals[stage] = totals.get(stage, 0.0) + float(seconds)

        if now - float(profile["last_print"]) < cls.DEBUG_PRINT_INTERVAL:
            return

        sample_count = max(int(profile["frames"]), 1)
        ordered_stages = (
            "validate",
            "cache",
            "restore",
            "rebuild",
            "transform",
            "colliders",
            "solve_setup",
            "predict",
            "pin",
            "tether",
            "distance",
            "bend",
            "collision",
            "motion",
            "post",
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
            f"[MeshClothMC2:py] obj={obj.name_full} key={shape_key_name} "
            f"frame={profile['frame']} samples={sample_count} verts={profile['vertex_count']} "
            f"constraints={profile['constraint_count']} "
            + " ".join(stage_text)
        )

        cls._debug_profiles[key] = {
            "last_print": now,
            "frames": 0,
            "stages": {},
        }

    @staticmethod
    def scene_delta_time(scene: bpy.types.Scene = None) -> float:
        return blender_io.scene_delta_time(scene)

    @staticmethod
    def substep_damping(frame_damping: float, substeps: int) -> float:
        return blender_io.substep_damping(frame_damping, substeps)

    @staticmethod
    def vector3(value, fallback: mathutils.Vector) -> mathutils.Vector:
        return math_utils.vector3(value, fallback)

    @staticmethod
    def require_mesh_object(obj, label: str) -> bpy.types.Object:
        return blender_io.require_mesh_object(obj, label)

    @staticmethod
    def output_shape_key_name(obj: bpy.types.Object) -> str:
        return blender_io.output_shape_key_name(obj)

    @staticmethod
    def ensure_target_shape_key(obj: bpy.types.Object, shape_key_name: str) -> bpy.types.ShapeKey:
        return blender_io.ensure_target_shape_key(obj, shape_key_name)

    @staticmethod
    def read_key_positions(key: bpy.types.ShapeKey, vertex_count: int) -> np.ndarray:
        return blender_io.read_key_positions(key, vertex_count)

    @classmethod
    def read_rest_positions(cls, obj: bpy.types.Object) -> np.ndarray:
        return blender_io.read_rest_positions(obj)

    @staticmethod
    def matrix_to_numpy(matrix: mathutils.Matrix) -> np.ndarray:
        return math_utils.matrix_to_numpy(matrix)

    @classmethod
    def transform_positions(cls, matrix: np.ndarray, positions: np.ndarray) -> np.ndarray:
        return math_utils.transform_positions(matrix, positions)

    @classmethod
    def local_positions_to_world(cls, obj: bpy.types.Object, positions: np.ndarray) -> np.ndarray:
        return blender_io.local_positions_to_world(obj, positions)

    @classmethod
    def world_positions_to_local(cls, obj: bpy.types.Object, positions: np.ndarray) -> np.ndarray:
        return blender_io.world_positions_to_local(obj, positions)

    @staticmethod
    def matrix_world_key(obj: bpy.types.Object) -> tuple:
        return math_utils.matrix_world_key(obj)

    @staticmethod
    def matrix_world_3x3_key(obj: bpy.types.Object) -> tuple:
        return math_utils.matrix_world_3x3_key(obj)

    @staticmethod
    def matrix_scale_radius(matrix: mathutils.Matrix) -> float:
        return math_utils.matrix_scale_radius(matrix)

    @staticmethod
    def write_shape_key_positions(
        obj: bpy.types.Object,
        shape_key: bpy.types.ShapeKey,
        positions: np.ndarray,
    ) -> None:
        blender_io.write_shape_key_positions(obj, shape_key, positions)

    @classmethod
    def write_world_positions_to_shape_key(
        cls,
        obj: bpy.types.Object,
        shape_key: bpy.types.ShapeKey,
        positions: np.ndarray,
    ) -> None:
        blender_io.write_world_positions_to_shape_key(obj, shape_key, positions)

    @classmethod
    def restore_rest_to_shape_key(cls, obj: bpy.types.Object, shape_key: bpy.types.ShapeKey, state=None) -> None:
        blender_io.restore_rest_to_shape_key(obj, shape_key, state)

    @staticmethod
    def cache_frame(cache) -> int | None:
        return blender_io.cache_frame(cache)

    @staticmethod
    def array_hash(values: np.ndarray) -> str:
        return math_utils.array_hash(values)

    @staticmethod
    def clamp_group_mask(value) -> int:
        return math_utils.clamp_group_mask(value)

    @staticmethod
    def collision_group_bit(group) -> int:
        return math_utils.collision_group_bit(group)

    @staticmethod
    def scene_objects(scene) -> list:
        return collision.scene_objects(scene)

    @classmethod
    def collider_from_matrix(cls, matrix, props, owner, owner_type: str, bone_name: str = ""):
        return collision.collider_from_matrix(matrix, props, owner, owner_type, bone_name)

    @classmethod
    def build_collision_snapshot_from_scene(
        cls,
        scene,
        include_bone_colliders: bool = True,
        include_object_colliders: bool = True,
        include_hidden: bool = False,
    ) -> dict:
        return collision.build_collision_snapshot_from_scene(
            scene,
            include_bone_colliders,
            include_object_colliders,
            include_hidden,
        )

    @staticmethod
    def vector_to_numpy(value) -> np.ndarray | None:
        return math_utils.vector_to_numpy(value)

    @classmethod
    def closest_point_on_segment_np(cls, point: np.ndarray, segment_a, segment_b) -> np.ndarray | None:
        return math_utils.closest_point_on_segment_np(point, segment_a, segment_b)

    @classmethod
    def safe_normal_np(cls, delta: np.ndarray, fallback: np.ndarray) -> np.ndarray:
        return math_utils.safe_normal_np(delta, fallback)

    @staticmethod
    def scalar_param(value) -> dict:
        return params.scalar_param(value)

    @staticmethod
    def sample_param(param: dict, depths: np.ndarray) -> np.ndarray:
        return params.sample_param(param, depths)

    @staticmethod
    def world_gravity(gravity_dir) -> np.ndarray:
        return math_utils.world_gravity(gravity_dir)

    @classmethod
    def calc_inverse_masses(
        cls,
        attributes: np.ndarray,
        depths: np.ndarray,
        friction: np.ndarray | None = None,
    ) -> np.ndarray:
        count = len(attributes)
        fr = np.zeros(count, dtype=np.float32) if friction is None else np.ascontiguousarray(friction, dtype=np.float32)
        dep = np.clip(np.ascontiguousarray(depths, dtype=np.float32), 0.0, 1.0)
        mass = 1.0 + fr * cls.FRICTION_MASS + ((1.0 - dep) ** 2) * cls.DEPTH_MASS
        inv = np.ascontiguousarray(1.0 / np.maximum(mass, cls.EPSILON), dtype=np.float32)
        fixed = (np.ascontiguousarray(attributes, dtype=np.uint8) & MC2_ATTR_MOVE) == 0
        inv[fixed] = 0.0
        return inv


class _MC2MeshCloth:
    """MeshCloth 的 Python 参考实现。

    解算状态统一保存在世界空间。只有读取低模代理 rest pose 和写回输出
    shape key 时才做 local/world 转换。
    """

    @staticmethod
    def mesh_collision_props(obj: bpy.types.Object):
        return getattr(obj, "hotools_mesh_collision", None)

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
    def mesh_pin_config(cls, obj: bpy.types.Object) -> tuple[bool, str]:
        props = cls.mesh_collision_props(obj)
        if props is None or not bool(getattr(props, "pin_enabled", False)):
            return False, ""
        return True, str(getattr(props, "pin_vertex_group", "") or "")

    @classmethod
    def build_attributes(cls, obj: bpy.types.Object) -> np.ndarray:
        vertex_count = len(obj.data.vertices)
        attributes = np.full(vertex_count, MC2_ATTR_MOVE | MC2_ATTR_MOTION, dtype=np.uint8)
        pin_enabled, pin_group_name = cls.mesh_pin_config(obj)
        if not pin_enabled:
            return attributes

        if not pin_group_name:
            attributes.fill(MC2_ATTR_FIXED)
            return attributes

        weights = cls.vertex_group_weights(obj, pin_group_name)
        fixed = weights > 0.0
        attributes[fixed] = MC2_ATTR_FIXED
        attributes[~fixed] = MC2_ATTR_MOVE | MC2_ATTR_MOTION
        return attributes

    @classmethod
    def build_collision_profile(cls, obj: bpy.types.Object, fallback_radius: float) -> tuple[np.ndarray, int]:
        props = cls.mesh_collision_props(obj)
        radii = np.zeros(len(obj.data.vertices), dtype=np.float32)
        fallback_radius = max(float(fallback_radius), 0.0)

        if props is not None and bool(getattr(props, "enabled", False)):
            radius = max(float(getattr(props, "radius", 0.0)), 0.0)
            if radius <= _MC2Common.EPSILON:
                return radii, 0

            weights = cls.vertex_group_weights(obj, str(getattr(props, "radius_vertex_group", "") or ""))
            radii = np.ascontiguousarray(weights * radius, dtype=np.float32)
            mask = _MC2Common.clamp_group_mask(getattr(props, "collided_by_groups", 0))
            return radii, mask

        if fallback_radius <= _MC2Common.EPSILON:
            return radii, 0

        radii.fill(fallback_radius)
        return radii, 0xFFFF

    @staticmethod
    def collision_radii_to_world(obj: bpy.types.Object, local_radii: np.ndarray) -> np.ndarray:
        scale = _MC2Common.matrix_scale_radius(obj.matrix_world)
        return np.ascontiguousarray(local_radii * scale, dtype=np.float32)

    @classmethod
    def collider_arrays_for_native(
        cls,
        state: dict,
        obj: bpy.types.Object,
        colliders: list[dict] | None,
    ) -> dict:
        return collision.collider_arrays_for_native(state, obj, colliders)

    @staticmethod
    def mesh_connectivity_arrays(mesh: bpy.types.Mesh) -> tuple[np.ndarray, np.ndarray]:
        """只读取现有 mesh 连接关系；永远不修改、不减面、不重映射。"""
        edge_values = np.empty(len(mesh.edges) * 2, dtype=np.int32)
        if len(edge_values) > 0:
            mesh.edges.foreach_get("vertices", edge_values)
        edges = edge_values.reshape((len(mesh.edges), 2)) if len(mesh.edges) else np.empty((0, 2), dtype=np.int32)

        try:
            mesh.calc_loop_triangles()
        except Exception:
            pass

        triangles = []
        for triangle in mesh.loop_triangles:
            verts = tuple(int(v) for v in triangle.vertices)
            if len(verts) == 3:
                triangles.append(verts)
        triangle_array = (
            np.asarray(triangles, dtype=np.int32).reshape((-1, 3))
            if triangles
            else np.empty((0, 3), dtype=np.int32)
        )
        return np.ascontiguousarray(edges, dtype=np.int32), np.ascontiguousarray(triangle_array, dtype=np.int32)

    @classmethod
    def mesh_signature_key(cls, obj: bpy.types.Object) -> tuple:
        mesh = obj.data
        edges, triangles = cls.mesh_connectivity_arrays(mesh)
        return (
            int(obj.as_pointer()),
            int(mesh.as_pointer()),
            len(mesh.vertices),
            len(mesh.edges),
            len(mesh.polygons),
            _MC2Common.array_hash(edges),
            _MC2Common.array_hash(triangles),
        )

    @classmethod
    def config_key(
        cls,
        obj: bpy.types.Object,
        shape_key_name: str,
        mesh_signature_key: tuple,
        collision_radius: float,
    ) -> tuple:
        pin_enabled, pin_group = cls.mesh_pin_config(obj)
        pin_weights = cls.vertex_group_weights(obj, pin_group) if pin_enabled and pin_group else np.empty(0, dtype=np.float32)
        props = cls.mesh_collision_props(obj)
        collision_enabled = bool(props is not None and getattr(props, "enabled", False))
        radius_group = str(getattr(props, "radius_vertex_group", "") or "") if props is not None else ""
        radius_weights = cls.vertex_group_weights(obj, radius_group) if radius_group else np.empty(0, dtype=np.float32)
        configured_radius = (
            float(getattr(props, "radius", 0.0))
            if collision_enabled
            else float(collision_radius)
        )
        configured_mask = (
            _MC2Common.clamp_group_mask(getattr(props, "collided_by_groups", 0))
            if collision_enabled
            else (0xFFFF if float(collision_radius) > _MC2Common.EPSILON else 0)
        )
        return (
            MC2_SOLVER_VERSION,
            shape_key_name,
            mesh_signature_key,
            bool(pin_enabled),
            pin_group,
            _MC2Common.array_hash(pin_weights),
            collision_enabled,
            round(configured_radius, 8),
            radius_group,
            _MC2Common.array_hash(radius_weights),
            configured_mask,
        )

    @staticmethod
    def build_edge_constraints(
        edges: np.ndarray,
        rest_positions: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if len(edges) == 0:
            empty_i = np.empty(0, dtype=np.int32)
            empty_f = np.empty(0, dtype=np.float32)
            return empty_i, empty_i.copy(), empty_f

        edge_i = np.ascontiguousarray(edges[:, 0], dtype=np.int32)
        edge_j = np.ascontiguousarray(edges[:, 1], dtype=np.int32)
        delta = rest_positions[edge_i] - rest_positions[edge_j]
        rest = np.ascontiguousarray(np.linalg.norm(delta, axis=1), dtype=np.float32)
        return edge_i, edge_j, rest

    @staticmethod
    def build_bend_constraints(
        triangles: np.ndarray,
        rest_positions: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        edge_to_opposites = {}
        for triangle in triangles:
            a, b, c = (int(triangle[0]), int(triangle[1]), int(triangle[2]))
            for i, j, opposite in ((a, b, c), (b, c, a), (c, a, b)):
                key = (i, j) if i < j else (j, i)
                edge_to_opposites.setdefault(key, []).append(opposite)

        pairs = []
        triangle_pairs = []
        seen = set()
        for edge, opposites in edge_to_opposites.items():
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
            triangle_pairs.append((edge[0], edge[1], i, j))
            seen.add(key)

        if not pairs:
            empty_i = np.empty(0, dtype=np.int32)
            empty_f = np.empty(0, dtype=np.float32)
            return empty_i, empty_i.copy(), empty_f, np.empty((0, 4), dtype=np.int32)

        pair_array = np.asarray(pairs, dtype=np.int32)
        bend_i = np.ascontiguousarray(pair_array[:, 0], dtype=np.int32)
        bend_j = np.ascontiguousarray(pair_array[:, 1], dtype=np.int32)
        delta = rest_positions[bend_i] - rest_positions[bend_j]
        bend_rest = np.ascontiguousarray(np.linalg.norm(delta, axis=1), dtype=np.float32)
        return (
            bend_i,
            bend_j,
            bend_rest,
            np.ascontiguousarray(np.asarray(triangle_pairs, dtype=np.int32).reshape((-1, 4)), dtype=np.int32),
        )

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
    def build_neighbor_table(
        vertex_count: int,
        index_i: np.ndarray,
        index_j: np.ndarray,
        rest_lengths: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        adjacency = [[] for _ in range(vertex_count)]
        for constraint_index in range(len(index_i)):
            i = int(index_i[constraint_index])
            j = int(index_j[constraint_index])
            rest = float(rest_lengths[constraint_index])
            if i < 0 or j < 0 or i >= vertex_count or j >= vertex_count or i == j:
                continue
            adjacency[i].append((j, rest))
            adjacency[j].append((i, rest))

        counts = np.asarray([len(items) for items in adjacency], dtype=np.int32)
        starts = np.zeros(vertex_count, dtype=np.int32)
        if vertex_count > 1:
            starts[1:] = np.cumsum(counts[:-1], dtype=np.int32)
        total = int(np.sum(counts))
        data = np.empty(total, dtype=np.int32)
        rests = np.empty(total, dtype=np.float32)
        cursor = 0
        for items in adjacency:
            for neighbor, rest in items:
                data[cursor] = int(neighbor)
                rests[cursor] = float(rest)
                cursor += 1
        return starts, counts, np.ascontiguousarray(data, dtype=np.int32), np.ascontiguousarray(rests, dtype=np.float32)

    @staticmethod
    def build_adjacency(vertex_count: int, edges: np.ndarray) -> list[list[tuple[int, float]]]:
        adjacency = [[] for _ in range(vertex_count)]
        for edge in edges:
            i = int(edge[0])
            j = int(edge[1])
            if i < 0 or j < 0 or i >= vertex_count or j >= vertex_count or i == j:
                continue
            adjacency[i].append(j)
            adjacency[j].append(i)
        return adjacency

    @classmethod
    def build_depth_and_roots(
        cls,
        edges: np.ndarray,
        rest_positions: np.ndarray,
        attributes: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        vertex_count = len(rest_positions)
        adjacency = cls.build_adjacency(vertex_count, edges)
        fixed = (attributes & MC2_ATTR_MOVE) == 0
        roots = np.full(vertex_count, -1, dtype=np.int32)
        parents = np.full(vertex_count, -1, dtype=np.int32)
        root_lengths = np.zeros(vertex_count, dtype=np.float32)
        distance_from_root = np.full(vertex_count, np.inf, dtype=np.float32)
        queue = deque()

        for index in np.nonzero(fixed)[0]:
            roots[index] = int(index)
            distance_from_root[index] = 0.0
            queue.append(int(index))

        while queue:
            current = queue.popleft()
            current_pos = rest_positions[current]
            for neighbor in adjacency[current]:
                segment = float(np.linalg.norm(rest_positions[neighbor] - current_pos))
                candidate = float(distance_from_root[current]) + segment
                if candidate + _MC2Common.EPSILON >= float(distance_from_root[neighbor]):
                    continue
                roots[neighbor] = roots[current] if roots[current] >= 0 else current
                parents[neighbor] = current
                distance_from_root[neighbor] = candidate
                queue.append(neighbor)

        finite = np.isfinite(distance_from_root)
        if bool(np.any(finite)):
            root_lengths[finite] = np.ascontiguousarray(distance_from_root[finite], dtype=np.float32)
        else:
            root_lengths.fill(0.0)

        move_reached = finite & ((attributes & MC2_ATTR_MOVE) != 0)
        max_length = float(np.max(root_lengths[move_reached])) if bool(np.any(move_reached)) else 0.0
        depths = np.ones(vertex_count, dtype=np.float32)
        if max_length > _MC2Common.EPSILON:
            depths[finite] = np.clip(root_lengths[finite] / max_length, 0.0, 1.0)
            depths[fixed] = 0.0
        elif bool(np.any(fixed)):
            depths[fixed] = 0.0

        return (
            np.ascontiguousarray(depths, dtype=np.float32),
            np.ascontiguousarray(roots, dtype=np.int32),
            np.ascontiguousarray(parents, dtype=np.int32),
            np.ascontiguousarray(root_lengths, dtype=np.float32),
        )

    @staticmethod
    def build_tether_rest_lengths(positions: np.ndarray, root_indices: np.ndarray) -> np.ndarray:
        lengths = np.zeros(len(positions), dtype=np.float32)
        for vertex_index in range(len(positions)):
            root_index = int(root_indices[vertex_index])
            if root_index < 0 or root_index >= len(positions):
                continue
            lengths[vertex_index] = float(np.linalg.norm(positions[vertex_index] - positions[root_index]))
        return np.ascontiguousarray(lengths, dtype=np.float32)

    @classmethod
    def build_state(
        cls,
        obj: bpy.types.Object,
        shape_key_name: str,
        mesh_signature_key: tuple,
        config_key: tuple,
        collision_radius: float,
    ) -> dict:
        rest_local = _MC2Common.read_rest_positions(obj)
        rest_world = _MC2Common.local_positions_to_world(obj, rest_local)
        edges, triangles = cls.mesh_connectivity_arrays(obj.data)
        attributes = cls.build_attributes(obj)
        depths, root_indices, parent_indices, root_rest_lengths = cls.build_depth_and_roots(edges, rest_world, attributes)
        friction = np.zeros(len(obj.data.vertices), dtype=np.float32)
        static_friction = np.zeros(len(obj.data.vertices), dtype=np.float32)
        inv_masses = _MC2Common.calc_inverse_masses(attributes, depths, friction)
        edge_i, edge_j, edge_rest = cls.build_edge_constraints(edges, rest_world)
        bend_i, bend_j, bend_rest, triangle_pairs = cls.build_bend_constraints(triangles, rest_world)
        distance_start, distance_count, distance_data, distance_rest = cls.build_neighbor_table(
            len(obj.data.vertices),
            edge_i,
            edge_j,
            edge_rest,
        )
        bend_start, bend_count, bend_data, bend_neighbor_rest = cls.build_neighbor_table(
            len(obj.data.vertices),
            bend_i,
            bend_j,
            bend_rest,
        )
        collision_local_radii, collision_mask = cls.build_collision_profile(obj, collision_radius)
        zeros3 = np.zeros((len(obj.data.vertices), 3), dtype=np.float32)

        return {
            "kind": MC2_CACHE_KIND,
            "solver_version": MC2_SOLVER_VERSION,
            "frame": None,
            "object_name": obj.name_full,
            "object_ptr": int(obj.as_pointer()),
            "mesh_ptr": int(obj.data.as_pointer()),
            "shape_key_name": shape_key_name,
            "mesh_signature_key": mesh_signature_key,
            "config_key": config_key,
            "object_matrix_world_key": _MC2Common.matrix_world_key(obj),
            "object_matrix_world_3x3_key": _MC2Common.matrix_world_3x3_key(obj),
            "object_matrix_world": _MC2Common.matrix_to_numpy(obj.matrix_world),
            "vertex_count": len(obj.data.vertices),
            "frame_delta_time": 0.0,
            "step_delta_time": 0.0,
            "substep_damping": 0.0,
            "rest_local_positions": np.ascontiguousarray(rest_local, dtype=np.float32),
            "rest_world_positions": np.ascontiguousarray(rest_world, dtype=np.float32),
            "base_positions": np.ascontiguousarray(rest_world.copy(), dtype=np.float32),
            "next_positions": np.ascontiguousarray(rest_world.copy(), dtype=np.float32),
            "old_positions": np.ascontiguousarray(rest_world.copy(), dtype=np.float32),
            "velocity_positions": zeros3.copy(),
            "display_positions": np.ascontiguousarray(rest_world.copy(), dtype=np.float32),
            "velocity": zeros3.copy(),
            "real_velocity": zeros3.copy(),
            "friction": friction,
            "static_friction": static_friction,
            "collision_normals": zeros3.copy(),
            "attributes": attributes,
            "depths": depths,
            "root_indices": root_indices,
            "parent_indices": parent_indices,
            "root_rest_lengths": root_rest_lengths,
            "tether_rest_lengths": cls.build_tether_rest_lengths(rest_world, root_indices),
            "inv_masses": inv_masses,
            "edges": edges,
            "triangles": triangles,
            "edge_i": edge_i,
            "edge_j": edge_j,
            "edge_rest": edge_rest,
            "bend_i": bend_i,
            "bend_j": bend_j,
            "bend_rest": bend_rest,
            "triangle_pairs": triangle_pairs,
            "distance_start": distance_start,
            "distance_count": distance_count,
            "distance_data": distance_data,
            "distance_rest": distance_rest,
            "bend_start": bend_start,
            "bend_count": bend_count,
            "bend_data": bend_data,
            "bend_neighbor_rest": bend_neighbor_rest,
            "collision_local_radii": collision_local_radii,
            "collision_radii": cls.collision_radii_to_world(obj, collision_local_radii),
            "collided_by_groups": int(collision_mask),
            "param_slots": {name: None for name in MC2_CURVE_READY_PARAMETERS},
            "extension_slots": {
                "bonecloth": None,
                "curves": {},
                "self_collision": None,
                "native": None,
            },
        }

    @classmethod
    def sync_state_to_object_transform(cls, state: dict, obj: bpy.types.Object) -> dict:
        matrix_key = _MC2Common.matrix_world_key(obj)
        matrix_3x3_key = _MC2Common.matrix_world_3x3_key(obj)
        if (
            state.get("object_matrix_world_key") == matrix_key
            and state.get("object_matrix_world_3x3_key") == matrix_3x3_key
        ):
            return state

        next_state = dict(state)
        new_world = _MC2Common.matrix_to_numpy(obj.matrix_world)
        rest_local = np.ascontiguousarray(next_state["rest_local_positions"], dtype=np.float32)
        rest_world = _MC2Common.local_positions_to_world(obj, rest_local)
        next_state["object_matrix_world_key"] = matrix_key
        next_state["object_matrix_world"] = new_world

        if next_state.get("object_matrix_world_3x3_key") != matrix_3x3_key:
            next_state["edge_rest"] = cls.constraint_lengths(rest_world, next_state["edge_i"], next_state["edge_j"])
            next_state["bend_rest"] = cls.constraint_lengths(rest_world, next_state["bend_i"], next_state["bend_j"])
            (
                next_state["distance_start"],
                next_state["distance_count"],
                next_state["distance_data"],
                next_state["distance_rest"],
            ) = cls.build_neighbor_table(
                int(next_state["vertex_count"]),
                next_state["edge_i"],
                next_state["edge_j"],
                next_state["edge_rest"],
            )
            (
                next_state["bend_start"],
                next_state["bend_count"],
                next_state["bend_data"],
                next_state["bend_neighbor_rest"],
            ) = cls.build_neighbor_table(
                int(next_state["vertex_count"]),
                next_state["bend_i"],
                next_state["bend_j"],
                next_state["bend_rest"],
            )
            (
                next_state["depths"],
                next_state["root_indices"],
                next_state["parent_indices"],
                next_state["root_rest_lengths"],
            ) = cls.build_depth_and_roots(next_state["edges"], rest_world, next_state["attributes"])
            next_state["tether_rest_lengths"] = cls.build_tether_rest_lengths(rest_world, next_state["root_indices"])
            next_state["collision_radii"] = cls.collision_radii_to_world(obj, next_state["collision_local_radii"])
            next_state["inv_masses"] = _MC2Common.calc_inverse_masses(
                next_state["attributes"],
                next_state["depths"],
                next_state["friction"],
            )
            next_state["object_matrix_world_3x3_key"] = matrix_3x3_key

        next_state["rest_world_positions"] = np.ascontiguousarray(rest_world, dtype=np.float32)
        next_state["base_positions"] = np.ascontiguousarray(rest_world.copy(), dtype=np.float32)

        return next_state

    @classmethod
    def state_matches(
        cls,
        state,
        obj: bpy.types.Object,
        shape_key_name: str,
        mesh_signature_key: tuple,
        config_key: tuple,
    ) -> bool:
        if not isinstance(state, dict):
            return False

        vertex_count = len(obj.data.vertices)
        required_shapes = {
            "rest_local_positions": (vertex_count, 3),
            "rest_world_positions": (vertex_count, 3),
            "base_positions": (vertex_count, 3),
            "next_positions": (vertex_count, 3),
            "old_positions": (vertex_count, 3),
            "velocity_positions": (vertex_count, 3),
            "display_positions": (vertex_count, 3),
            "velocity": (vertex_count, 3),
            "real_velocity": (vertex_count, 3),
            "friction": (vertex_count,),
            "static_friction": (vertex_count,),
            "collision_normals": (vertex_count, 3),
            "attributes": (vertex_count,),
            "depths": (vertex_count,),
            "root_indices": (vertex_count,),
            "parent_indices": (vertex_count,),
            "root_rest_lengths": (vertex_count,),
            "tether_rest_lengths": (vertex_count,),
            "inv_masses": (vertex_count,),
            "collision_local_radii": (vertex_count,),
            "collision_radii": (vertex_count,),
            "distance_start": (vertex_count,),
            "distance_count": (vertex_count,),
            "bend_start": (vertex_count,),
            "bend_count": (vertex_count,),
            "object_matrix_world": (4, 4),
        }
        for key, shape in required_shapes.items():
            value = state.get(key)
            if not isinstance(value, np.ndarray) or value.shape != shape:
                return False

        try:
            matrix_3x3_key = tuple(state.get("object_matrix_world_3x3_key"))
        except Exception:
            matrix_3x3_key = ()
        if len(matrix_3x3_key) != 9:
            return False

        def array_ndim_shape(key: str, ndim: int, tail: tuple[int, ...] = ()) -> np.ndarray | None:
            value = state.get(key)
            if not isinstance(value, np.ndarray) or value.ndim != ndim:
                return None
            if tail and value.shape[-len(tail):] != tail:
                return None
            return value

        edges = array_ndim_shape("edges", 2, (2,))
        triangles = array_ndim_shape("triangles", 2, (3,))
        triangle_pairs = array_ndim_shape("triangle_pairs", 2, (4,))
        if edges is None or triangles is None or triangle_pairs is None:
            return False
        if int(edges.size) and (int(np.min(edges)) < 0 or int(np.max(edges)) >= vertex_count):
            return False
        if int(triangles.size) and (int(np.min(triangles)) < 0 or int(np.max(triangles)) >= vertex_count):
            return False
        if int(triangle_pairs.size) and (int(np.min(triangle_pairs)) < 0 or int(np.max(triangle_pairs)) >= vertex_count):
            return False

        def same_1d_length(keys: tuple[str, ...]) -> bool:
            length = None
            for key in keys:
                value = state.get(key)
                if not isinstance(value, np.ndarray) or value.ndim != 1:
                    return False
                if length is None:
                    length = len(value)
                elif len(value) != length:
                    return False
            return True

        if not same_1d_length(("edge_i", "edge_j", "edge_rest")):
            return False
        if not same_1d_length(("bend_i", "bend_j", "bend_rest")):
            return False
        if not same_1d_length(("distance_data", "distance_rest")):
            return False
        if not same_1d_length(("bend_data", "bend_neighbor_rest")):
            return False
        if len(state["edge_i"]) != len(edges):
            return False
        if len(state["bend_i"]) != len(triangle_pairs):
            return False

        for index_key in ("edge_i", "edge_j", "bend_i", "bend_j", "distance_data", "bend_data"):
            indices = state.get(index_key)
            if not isinstance(indices, np.ndarray) or len(indices) == 0:
                continue
            if int(np.min(indices)) < 0 or int(np.max(indices)) >= vertex_count:
                return False

        param_slots = state.get("param_slots")
        if not isinstance(param_slots, dict):
            return False
        for name in MC2_CURVE_READY_PARAMETERS:
            if name not in param_slots:
                return False

        return (
            state.get("kind") == MC2_CACHE_KIND
            and state.get("solver_version") == MC2_SOLVER_VERSION
            and state.get("object_ptr") == int(obj.as_pointer())
            and state.get("mesh_ptr") == int(obj.data.as_pointer())
            and state.get("shape_key_name") == shape_key_name
            and state.get("mesh_signature_key") == mesh_signature_key
            and state.get("config_key") == config_key
            and state.get("vertex_count") == vertex_count
        )

    @classmethod
    def project_neighbor_constraints(
        cls,
        positions: np.ndarray,
        inv_masses: np.ndarray,
        starts: np.ndarray,
        counts: np.ndarray,
        neighbors: np.ndarray,
        rest_lengths: np.ndarray,
        stiffness: float,
    ) -> None:
        stiffness = max(0.0, min(1.0, float(stiffness)))
        if stiffness <= _MC2Common.EPSILON or len(neighbors) == 0:
            return

        vertex_count = len(positions)
        for vertex_index in range(vertex_count):
            wi = float(inv_masses[vertex_index])
            if wi <= _MC2Common.EPSILON:
                continue

            start = int(starts[vertex_index])
            count = int(counts[vertex_index])
            if count <= 0:
                continue

            add = np.zeros(3, dtype=np.float32)
            add_count = 0
            current = positions[vertex_index]
            for offset in range(count):
                data_index = start + offset
                neighbor_index = int(neighbors[data_index])
                rest = abs(float(rest_lengths[data_index]))
                wj = float(inv_masses[neighbor_index])
                wsum = wi + wj
                if wsum <= _MC2Common.EPSILON:
                    continue

                delta = positions[neighbor_index] - current
                distance = float(np.linalg.norm(delta))
                if distance <= _MC2Common.EPSILON:
                    continue

                normal = delta / distance
                correction = ((distance - rest) * stiffness / wsum) * wi * normal
                add += correction
                add_count += 1

            if add_count > 0:
                positions[vertex_index] = current + add / float(add_count)

    @classmethod
    def project_tether(
        cls,
        positions: np.ndarray,
        inv_masses: np.ndarray,
        root_indices: np.ndarray,
        root_rest_lengths: np.ndarray,
        stiffness: float,
        compression: float,
        stretch: float,
    ) -> None:
        stiffness = max(0.0, min(1.0, float(stiffness)))
        if stiffness <= _MC2Common.EPSILON:
            return

        compression_limit = 1.0 - max(0.0, min(1.0, float(compression)))
        stretch_limit = 1.0 + max(0.0, float(stretch))
        stiffness_width = max(float(_MC2Common.TETHER_STIFFNESS_WIDTH), _MC2Common.EPSILON)

        for vertex_index in range(len(positions)):
            if float(inv_masses[vertex_index]) <= _MC2Common.EPSILON:
                continue
            root_index = int(root_indices[vertex_index])
            if root_index < 0:
                continue
            rest_length = float(root_rest_lengths[vertex_index])
            if rest_length <= _MC2Common.EPSILON:
                continue

            delta = positions[root_index] - positions[vertex_index]
            distance = float(np.linalg.norm(delta))
            if distance <= _MC2Common.EPSILON:
                continue

            ratio = distance / rest_length
            dist = 0.0
            solve_stiffness = 0.0
            if ratio < compression_limit:
                dist = distance - compression_limit * rest_length
                fade = max(0.0, min(1.0, (compression_limit - ratio) / stiffness_width))
                solve_stiffness = stiffness * _MC2Common.TETHER_COMPRESSION_STIFFNESS * fade
            elif ratio > stretch_limit:
                dist = distance - stretch_limit * rest_length
                fade = max(0.0, min(1.0, (ratio - stretch_limit) / stiffness_width))
                solve_stiffness = stiffness * _MC2Common.TETHER_STRETCH_STIFFNESS * fade

            if solve_stiffness <= _MC2Common.EPSILON:
                continue

            positions[vertex_index] += (delta / distance) * (dist * solve_stiffness)

    @classmethod
    def project_motion_constraint(
        cls,
        positions: np.ndarray,
        base_positions: np.ndarray,
        inv_masses: np.ndarray,
        depths: np.ndarray,
        max_distance_param: dict,
        motion_stiffness_param: dict,
        world_scale: float,
    ) -> None:
        motion_depths = np.clip(np.ascontiguousarray(depths, dtype=np.float32) ** 2, 0.0, 1.0)
        max_distances = _MC2Common.sample_param(max_distance_param, motion_depths) * max(float(world_scale), 0.0)
        stiffness_values = np.clip(_MC2Common.sample_param(motion_stiffness_param, motion_depths), 0.0, 1.0)
        if not bool(np.any(max_distances > _MC2Common.EPSILON)):
            return
        if not bool(np.any(stiffness_values > _MC2Common.EPSILON)):
            return

        for vertex_index in range(len(positions)):
            if float(inv_masses[vertex_index]) <= _MC2Common.EPSILON:
                continue
            limit = float(max_distances[vertex_index])
            if limit <= _MC2Common.EPSILON:
                continue
            stiffness = float(stiffness_values[vertex_index])
            if stiffness <= _MC2Common.EPSILON:
                continue
            original_position = positions[vertex_index].copy()
            delta = original_position - base_positions[vertex_index]
            distance = float(np.linalg.norm(delta))
            if distance > limit and distance > _MC2Common.EPSILON:
                constrained = base_positions[vertex_index] + (delta / distance) * limit
                positions[vertex_index] = original_position * (1.0 - stiffness) + constrained * stiffness

    @classmethod
    def project_vertex_collision(
        cls,
        position: np.ndarray,
        hit_radius: float,
        collided_by_groups: int,
        colliders: list[dict],
        owner_obj: bpy.types.Object,
        fallback: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        return collision.project_vertex_collision(
            position,
            hit_radius,
            collided_by_groups,
            colliders,
            owner_obj,
            fallback,
        )

    @classmethod
    def project_collisions(
        cls,
        positions: np.ndarray,
        base_positions: np.ndarray,
        inv_masses: np.ndarray,
        collision_radii: np.ndarray,
        collided_by_groups: int,
        colliders: list[dict] | None,
        owner_obj: bpy.types.Object,
        collision_normals: np.ndarray,
    ) -> None:
        collision.project_collisions(
            positions,
            base_positions,
            inv_masses,
            collision_radii,
            collided_by_groups,
            colliders,
            owner_obj,
            collision_normals,
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
        distance_stiffness: float,
        bend_stiffness: float,
        max_distance: float,
        timing: dict | None = None,
        colliders: list[dict] | None = None,
    ) -> dict:
        stage_start = time.perf_counter() if timing is not None else None
        positions = np.ascontiguousarray(state["next_positions"], dtype=np.float32)
        old_positions = np.ascontiguousarray(state["old_positions"], dtype=np.float32)
        base_positions = np.ascontiguousarray(state["base_positions"], dtype=np.float32)
        attributes = np.ascontiguousarray(state["attributes"], dtype=np.uint8)
        depths = np.ascontiguousarray(state["depths"], dtype=np.float32)
        friction = np.ascontiguousarray(state["friction"], dtype=np.float32)
        inv_masses = _MC2Common.calc_inverse_masses(attributes, depths, friction)
        collision_radii = np.ascontiguousarray(state["collision_radii"], dtype=np.float32)
        collided_by_groups = _MC2Common.clamp_group_mask(state.get("collided_by_groups", 0))
        collision_normals = np.zeros_like(positions, dtype=np.float32)
        movable = inv_masses > _MC2Common.EPSILON
        fixed = ~movable

        dt = _MC2Common.scene_delta_time(scene)
        substep_count = max(1, min(16, int(substeps)))
        iteration_count = max(0, min(64, int(iterations)))
        step_dt = dt / substep_count if substep_count > 0 else dt
        gravity = _MC2Common.world_gravity(gravity_dir) * max(float(gravity_power), 0.0)
        substep_damping = _MC2Common.substep_damping(damping, substep_count)
        distance_stiffness = max(0.0, min(1.0, float(distance_stiffness)))
        bend_stiffness = max(0.0, min(1.0, float(bend_stiffness)))
        max_distance_param = _MC2Common.scalar_param(max(float(max_distance), 0.0))
        tether_compression_param = _MC2Common.scalar_param(_MC2Common.TETHER_COMPRESSION_LIMIT)
        tether_stretch_param = _MC2Common.scalar_param(_MC2Common.TETHER_STRETCH_LIMIT)
        motion_stiffness_param = _MC2Common.scalar_param(1.0)
        world_scale = _MC2Common.matrix_scale_radius(obj.matrix_world)
        has_collision = bool(colliders) and bool(collided_by_groups) and bool(np.any(collision_radii > _MC2Common.EPSILON))
        if timing is not None:
            _MC2Common.add_timing(timing, "solve_setup", time.perf_counter() - stage_start)

        for _ in range(substep_count):
            stage_start = time.perf_counter() if timing is not None else None
            previous = positions.copy()
            # 帧长使用 Blender render.fps/fps_base。阻尼按每场景帧输入，
            # 在 Verlet 风格 mesh 预测前换算成每子步阻尼。
            inertia = (positions - old_positions) * (1.0 - substep_damping)
            positions[movable] += inertia[movable] + gravity * (step_dt * step_dt)
            old_positions = previous
            if timing is not None:
                _MC2Common.add_timing(timing, "predict", time.perf_counter() - stage_start)

            if bool(np.any(fixed)):
                stage_start = time.perf_counter() if timing is not None else None
                positions[fixed] = base_positions[fixed]
                old_positions[fixed] = base_positions[fixed]
                if timing is not None:
                    _MC2Common.add_timing(timing, "pin", time.perf_counter() - stage_start)

            stage_start = time.perf_counter() if timing is not None else None
            cls.project_tether(
                positions,
                inv_masses,
                state["root_indices"],
                state["tether_rest_lengths"],
                1.0,
                float(tether_compression_param["value"]),
                float(tether_stretch_param["value"]),
            )
            if timing is not None:
                _MC2Common.add_timing(timing, "tether", time.perf_counter() - stage_start)

            if has_collision:
                stage_start = time.perf_counter() if timing is not None else None
                cls.project_collisions(
                    positions,
                    base_positions,
                    inv_masses,
                    collision_radii,
                    collided_by_groups,
                    colliders,
                    obj,
                    collision_normals,
                )
                if timing is not None:
                    _MC2Common.add_timing(timing, "collision", time.perf_counter() - stage_start)

            for _iteration in range(iteration_count):
                stage_start = time.perf_counter() if timing is not None else None
                cls.project_neighbor_constraints(
                    positions,
                    inv_masses,
                    state["distance_start"],
                    state["distance_count"],
                    state["distance_data"],
                    state["distance_rest"],
                    distance_stiffness,
                )
                if timing is not None:
                    _MC2Common.add_timing(timing, "distance", time.perf_counter() - stage_start)

                stage_start = time.perf_counter() if timing is not None else None
                cls.project_neighbor_constraints(
                    positions,
                    inv_masses,
                    state["bend_start"],
                    state["bend_count"],
                    state["bend_data"],
                    state["bend_neighbor_rest"],
                    bend_stiffness,
                )
                if timing is not None:
                    _MC2Common.add_timing(timing, "bend", time.perf_counter() - stage_start)

                if bool(np.any(fixed)):
                    stage_start = time.perf_counter() if timing is not None else None
                    positions[fixed] = base_positions[fixed]
                    old_positions[fixed] = base_positions[fixed]
                    if timing is not None:
                        _MC2Common.add_timing(timing, "pin", time.perf_counter() - stage_start)

                if has_collision:
                    stage_start = time.perf_counter() if timing is not None else None
                    cls.project_collisions(
                        positions,
                        base_positions,
                        inv_masses,
                        collision_radii,
                        collided_by_groups,
                        colliders,
                        obj,
                        collision_normals,
                    )
                    if timing is not None:
                        _MC2Common.add_timing(timing, "collision", time.perf_counter() - stage_start)

            stage_start = time.perf_counter() if timing is not None else None
            cls.project_motion_constraint(
                positions,
                base_positions,
                inv_masses,
                depths,
                max_distance_param,
                motion_stiffness_param,
                world_scale,
            )
            if timing is not None:
                _MC2Common.add_timing(timing, "motion", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        velocity_positions = np.ascontiguousarray(positions - old_positions, dtype=np.float32)
        velocity = velocity_positions / step_dt if step_dt > _MC2Common.EPSILON else np.zeros_like(positions)
        next_state = dict(state)
        next_state["frame_delta_time"] = float(dt)
        next_state["step_delta_time"] = float(step_dt)
        next_state["substep_damping"] = float(substep_damping)
        next_state["next_positions"] = np.ascontiguousarray(positions, dtype=np.float32)
        next_state["old_positions"] = np.ascontiguousarray(old_positions, dtype=np.float32)
        next_state["display_positions"] = np.ascontiguousarray(positions.copy(), dtype=np.float32)
        next_state["velocity_positions"] = velocity_positions
        next_state["velocity"] = np.ascontiguousarray(velocity, dtype=np.float32)
        next_state["real_velocity"] = np.ascontiguousarray(velocity, dtype=np.float32)
        next_state["collision_normals"] = np.ascontiguousarray(collision_normals, dtype=np.float32)
        next_state["inv_masses"] = np.ascontiguousarray(inv_masses, dtype=np.float32)
        next_state["param_slots"] = dict(next_state.get("param_slots") or {})
        next_state["param_slots"]["distance_stiffness"] = _MC2Common.scalar_param(distance_stiffness)
        next_state["param_slots"]["bend_stiffness"] = _MC2Common.scalar_param(bend_stiffness)
        next_state["param_slots"]["max_distance"] = max_distance_param
        next_state["param_slots"]["tether_compression"] = tether_compression_param
        next_state["param_slots"]["tether_stretch"] = tether_stretch_param
        next_state["param_slots"]["motion_stiffness"] = motion_stiffness_param
        next_state["param_slots"]["damping"] = _MC2Common.scalar_param(damping)
        next_state["param_slots"]["backstop_radius"] = _MC2Common.scalar_param(10.0)
        next_state["param_slots"]["backstop_distance"] = _MC2Common.scalar_param(0.0)
        next_state["param_slots"]["collider_friction"] = _MC2Common.scalar_param(0.05)

        extension_slots = dict(next_state.get("extension_slots") or {})
        native_slot = dict(extension_slots.get("native") or {})
        native_slot["collider_arrays"] = cls.collider_arrays_for_native(next_state, obj, colliders)
        extension_slots["native"] = native_slot
        next_state["extension_slots"] = extension_slots
        if timing is not None:
            _MC2Common.add_timing(timing, "post", time.perf_counter() - stage_start)
        return next_state


def _run_mesh_cloth_mc2_node(
    cache_state: _OmniCache,
    proxy_obj: bpy.types.Object,
    scene: bpy.types.Scene,
    enabled: bool,
    reset: bool,
    substeps: int,
    iterations: int,
    gravity_dir,
    gravity_power: float,
    damping: float,
    distance_stiffness: float,
    bend_stiffness: float,
    max_distance: float,
    collision_radius: float,
    debug_output: bool,
) -> tuple[_OmniCache, bpy.types.Object, int, int]:
    timing = _MC2Common.begin_timing() if debug_output else None
    stage_start = time.perf_counter() if timing is not None else None
    obj = _MC2Common.require_mesh_object(proxy_obj, "proxy_obj")
    scene = scene or bpy.context.scene
    shape_key_name = _MC2Common.output_shape_key_name(obj)
    target_key = _MC2Common.ensure_target_shape_key(obj, shape_key_name)
    if timing is not None:
        _MC2Common.add_timing(timing, "validate", time.perf_counter() - stage_start)

    stage_start = time.perf_counter() if timing is not None else None
    mesh_signature_key = _MC2MeshCloth.mesh_signature_key(obj)
    config_key = _MC2MeshCloth.config_key(obj, shape_key_name, mesh_signature_key, collision_radius)
    vertex_count = len(obj.data.vertices)
    state = cache_state if _MC2MeshCloth.state_matches(cache_state, obj, shape_key_name, mesh_signature_key, config_key) else None
    cached_frame = _MC2Common.cache_frame(state)
    current_frame = int(getattr(scene, "frame_current", 0) or 0)
    if timing is not None:
        _MC2Common.add_timing(timing, "cache", time.perf_counter() - stage_start)

    if not reset and cached_frame is not None and current_frame != cached_frame + 1:
        stage_start = time.perf_counter() if timing is not None else None
        _MC2Common.restore_rest_to_shape_key(obj, target_key, state)
        if timing is not None:
            _MC2Common.add_timing(timing, "restore", time.perf_counter() - stage_start)
            _MC2Common.publish_debug_timing(obj, shape_key_name, current_frame, vertex_count, 0, timing)
        return None, obj, vertex_count, 0

    if reset or not isinstance(state, dict):
        stage_start = time.perf_counter() if timing is not None else None
        _MC2Common.restore_rest_to_shape_key(obj, target_key, state)
        if timing is not None:
            _MC2Common.add_timing(timing, "restore", time.perf_counter() - stage_start)

        stage_start = time.perf_counter() if timing is not None else None
        state = _MC2MeshCloth.build_state(obj, shape_key_name, mesh_signature_key, config_key, collision_radius)
        if timing is not None:
            _MC2Common.add_timing(timing, "rebuild", time.perf_counter() - stage_start)
    else:
        stage_start = time.perf_counter() if timing is not None else None
        state = _MC2MeshCloth.sync_state_to_object_transform(state, obj)
        if timing is not None:
            _MC2Common.add_timing(timing, "transform", time.perf_counter() - stage_start)

    constraint_count = len(state["edge_i"]) + len(state["bend_i"])

    if not enabled:
        next_state = dict(state)
        next_state["frame"] = current_frame
        _MC2Common.publish_debug_timing(obj, shape_key_name, current_frame, vertex_count, constraint_count, timing)
        return next_state, obj, vertex_count, constraint_count

    stage_start = time.perf_counter() if timing is not None else None
    collision_snapshot = _MC2Common.build_collision_snapshot_from_scene(scene, True, True, False)
    colliders = list(collision_snapshot.get("colliders") or []) if isinstance(collision_snapshot, dict) else []
    if timing is not None:
        _MC2Common.add_timing(timing, "colliders", time.perf_counter() - stage_start)

    stage_start = time.perf_counter() if timing is not None else None
    next_state = _MC2MeshCloth.solve(
        state,
        obj,
        scene,
        substeps,
        iterations,
        gravity_dir,
        gravity_power,
        damping,
        distance_stiffness,
        bend_stiffness,
        max_distance,
        timing,
        colliders=colliders,
    )
    if timing is not None:
        _MC2Common.add_timing(timing, "solve_total", time.perf_counter() - stage_start)

    next_state["frame"] = current_frame
    stage_start = time.perf_counter() if timing is not None else None
    _MC2Common.write_world_positions_to_shape_key(obj, target_key, next_state["display_positions"])
    if timing is not None:
        _MC2Common.add_timing(timing, "write", time.perf_counter() - stage_start)
        _MC2Common.publish_debug_timing(obj, shape_key_name, current_frame, vertex_count, constraint_count, timing)
    return next_state, obj, vertex_count, constraint_count


@omni(
    enable=True,
    bl_label="网格布料-MC2",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "缓存",
        "低模代理",
        "场景",
        "启用",
        "重置",
        "子步数",
        "迭代",
        "重力方向",
        "重力强度",
        "阻尼",
        "距离刚度",
        "弯曲刚度",
        "最大距离",
        "碰撞半径",
        "调试输出",
    ],
    input_init={
        "substeps": {"min_value": 1, "max_value": 16},
        "iterations": {"min_value": 0, "max_value": 64},
        "gravity_power": {"min_value": 0.0, "max_value": 100.0},
        "damping": {"min_value": 0.0, "max_value": 1.0},
        "distance_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "bend_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "max_distance": {"min_value": 0.0},
        "collision_radius": {"min_value": 0.0},
    },
    _OUTPUT_NAME=["缓存", "低模代理", "顶点数", "约束数"],
    omni_description="""
    MC2 风格 MeshCloth Python 参考解算器。
    输入 mesh 永远就是被直接驱动的低模代理；解算器永远不做减面或高低模
    映射。状态在世界空间中计算，并沿用 SpringBone 风格的连续帧语义：
    只有下一连续帧可以继承 cache 中的速度继续推进。
    """,
)
def meshClothMC2(
    cache_state: _OmniCache,
    proxy_obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
    enabled: bool = True,
    reset: bool = False,
    substeps: int = 1,
    iterations: int = 4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 9.8,
    damping: float = 0.04,
    distance_stiffness: float = 1.0,
    bend_stiffness: float = 0.5,
    max_distance: float = 0.0,
    collision_radius: float = 0.0,
    debug_output: bool = False,
) -> tuple[_OmniCache, bpy.types.Object, int, int]:
    return _run_mesh_cloth_mc2_node(
        cache_state,
        proxy_obj,
        scene,
        enabled,
        reset,
        substeps,
        iterations,
        gravity_dir,
        gravity_power,
        damping,
        distance_stiffness,
        bend_stiffness,
        max_distance,
        collision_radius,
        debug_output,
    )
