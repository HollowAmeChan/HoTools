"""MeshCloth 缓存状态与 Python/C++ ABI 形状守卫。

这里维护的是求解器真实运行状态。Blender 对象、GN delta 输出与场景生命周期仍由
节点入口调度；本模块只负责把当前 mesh 输入整理成可复用的数组状态。
"""

import bpy
import numpy as np
import time
from collections.abc import MutableMapping
from dataclasses import dataclass, field

from . import baseline, blender_io, inertia, math_utils, mesh_build, native_bridge
from .constants import (
    MC2_ATTR_MOVE,
    MC2_BEND_KIND_DISTANCE_APPROX,
    MC2_BEND_KIND_DIRECTION_DIHEDRAL,
    MC2_CACHE_KIND,
    MC2_CURVE_READY_PARAMETERS,
    MC2_SOLVER_VERSION,
    MC2SystemConstants,
)


MC2_RUNTIME_CACHE_SLOT = "runtime_cache"
MC2_RUNTIME_CACHE_NAMES = (
    "curve_cache",
    "topology_cache",
    "io_cache",
    "native_cache",
    "native_context",
)


@dataclass
class MC2CenterState:
    """单个 MeshCloth center 的运行状态容器。

    当前仍以 legacy_state 承载既有 dict，后续逐步把拓扑、粒子、曲线缓存拆成明确字段。
    """

    legacy_state: dict = field(default_factory=dict)
    curve_cache: dict = field(default_factory=dict)
    topology_cache: dict = field(default_factory=dict)
    io_cache: dict = field(default_factory=dict)
    native_cache: dict = field(default_factory=dict)
    native_context: object | None = None
    inertia_state: dict = field(default_factory=dict)
    init_local_gravity_direction: tuple[float, float, float] = (0.0, 0.0, -1.0)

    def replace_legacy_state(self, state: dict) -> None:
        self.legacy_state = state if isinstance(state, dict) else {}
        self.sync_runtime_fields_from_legacy()
        self._migrate_flat_runtime_cache()
        extension_slots = self._extension_slots()
        extension_slots[MC2_RUNTIME_CACHE_SLOT] = self.runtime_cache_slots()
        self.legacy_state["extension_slots"] = extension_slots

    def sync_runtime_fields_from_legacy(self) -> None:
        """把当前仍存放在 legacy dict 里的 CenterData 字段同步到正式容器。"""

        inertia_state = self.legacy_state.get("inertia_state") if isinstance(self.legacy_state, dict) else None
        self.inertia_state = inertia_state if isinstance(inertia_state, dict) else {}
        direction = self.legacy_state.get("init_local_gravity_direction") if isinstance(self.legacy_state, dict) else None
        if isinstance(direction, (list, tuple)) and len(direction) >= 3:
            self.init_local_gravity_direction = (
                float(direction[0]),
                float(direction[1]),
                float(direction[2]),
            )

    def _extension_slots(self) -> dict:
        extension_slots = self.legacy_state.get("extension_slots")
        if not isinstance(extension_slots, dict):
            extension_slots = {}
        return dict(extension_slots)

    def _migrate_flat_runtime_cache(self) -> None:
        extension_slots = self._extension_slots()
        runtime_slots = extension_slots.get(MC2_RUNTIME_CACHE_SLOT)
        if isinstance(runtime_slots, dict):
            self.curve_cache = runtime_slots.get("curve_cache") if isinstance(runtime_slots.get("curve_cache"), dict) else self.curve_cache
            self.topology_cache = runtime_slots.get("topology_cache") if isinstance(runtime_slots.get("topology_cache"), dict) else self.topology_cache
            self.io_cache = runtime_slots.get("io_cache") if isinstance(runtime_slots.get("io_cache"), dict) else self.io_cache
            self.native_cache = runtime_slots.get("native_cache") if isinstance(runtime_slots.get("native_cache"), dict) else self.native_cache
            if "native_context" in runtime_slots:
                self.native_context = runtime_slots.get("native_context")
        else:
            # 旧过渡版本曾把 runtime cache 平铺在 extension_slots 下；这里只迁移，不再继续写回平铺 key。
            self.curve_cache = extension_slots.get("curve_cache") if isinstance(extension_slots.get("curve_cache"), dict) else self.curve_cache
            self.topology_cache = extension_slots.get("topology_cache") if isinstance(extension_slots.get("topology_cache"), dict) else self.topology_cache
            self.io_cache = extension_slots.get("io_cache") if isinstance(extension_slots.get("io_cache"), dict) else self.io_cache
            self.native_cache = extension_slots.get("native_cache") if isinstance(extension_slots.get("native_cache"), dict) else self.native_cache
            if "native_context" in extension_slots:
                self.native_context = extension_slots.get("native_context")

    def runtime_cache_slots(self) -> dict:
        return {
            "curve_cache": self.curve_cache,
            "topology_cache": self.topology_cache,
            "io_cache": self.io_cache,
            "native_cache": self.native_cache,
            "native_context": self.native_context,
        }

    def runtime_cache(self, name: str) -> dict:
        value = self.runtime_cache_slots().get(name)
        if isinstance(value, dict):
            return value
        cache = {}
        setattr(self, name, cache)
        return cache

    def debug_snapshot(self) -> dict:
        state = self.legacy_state if isinstance(self.legacy_state, dict) else {}
        return {
            "object": state.get("object_name", ""),
            "frame": state.get("frame"),
            "verts": state.get("vertex_count", 0),
            "solver_version": state.get("solver_version"),
            "scale_ratio": state.get("scale_ratio", 1.0),
            "negative_scale_sign": state.get("negative_scale_sign", 1),
            "has_inertia_state": bool(self.inertia_state),
            "curve_cache": len(self.curve_cache),
            "topology_cache": len(self.topology_cache),
            "io_cache": len(self.io_cache),
            "native_cache": len(self.native_cache),
            "has_native_context": self.native_context is not None,
        }

    def dispose(self) -> None:
        self.native_context = None
        self.curve_cache.clear()
        self.topology_cache.clear()
        self.io_cache.clear()
        self.native_cache.clear()


@dataclass
class MC2TeamState:
    """per-node TeamState。

    它不是 MC2 全局 TeamManager，只是 OmniNode cache 中的运行期 schema。
    """

    centers: dict[str, MC2CenterState] = field(default_factory=dict)
    frame_interpolation: float = 1.0
    scale_ratio: float = 1.0
    negative_scale_sign: int = 1
    negative_scale_direction: tuple[int, int, int] = (1, 1, 1)
    animation_pose_ratio: float = 0.0
    gravity_dot: float = 1.0
    gravity_ratio: float = 1.0
    velocity_weight: float = 1.0
    blend_weight: float = 1.0

    def ensure_center(self, key: str = "main") -> MC2CenterState:
        key = str(key or "main")
        center = self.centers.get(key)
        if center is None:
            center = MC2CenterState()
            self.centers[key] = center
        return center

    def dispose(self) -> None:
        for center in self.centers.values():
            center.dispose()
        self.centers.clear()

    def sync_from_legacy_state(self, legacy_state: dict) -> None:
        """从 legacy state 提取源码 TeamData 对应字段，便于逐步迁移调用点。"""

        if not isinstance(legacy_state, dict):
            return
        self.scale_ratio = float(legacy_state.get("scale_ratio", self.scale_ratio))
        self.negative_scale_sign = int(legacy_state.get("negative_scale_sign", self.negative_scale_sign))
        direction = legacy_state.get("negative_scale_direction")
        if isinstance(direction, (list, tuple)) and len(direction) >= 3:
            self.negative_scale_direction = (
                int(direction[0]) if int(direction[0]) != 0 else 1,
                int(direction[1]) if int(direction[1]) != 0 else 1,
                int(direction[2]) if int(direction[2]) != 0 else 1,
            )
        self.animation_pose_ratio = max(
            0.0,
            min(1.0, float(legacy_state.get("animation_pose_ratio", self.animation_pose_ratio))),
        )
        self.gravity_dot = max(0.0, min(1.0, float(legacy_state.get("gravity_dot", self.gravity_dot))))
        self.gravity_ratio = max(0.0, float(legacy_state.get("gravity_ratio", self.gravity_ratio)))
        self.velocity_weight = max(0.0, min(1.0, float(legacy_state.get("velocity_weight", self.velocity_weight))))
        self.blend_weight = max(0.0, min(1.0, float(legacy_state.get("blend_weight", self.blend_weight))))

    def debug_snapshot(self) -> dict:
        return {
            "animation_pose_ratio": self.animation_pose_ratio,
            "gravity_dot": self.gravity_dot,
            "gravity_ratio": self.gravity_ratio,
            "velocity_weight": self.velocity_weight,
            "blend_weight": self.blend_weight,
            "scale_ratio": self.scale_ratio,
            "negative_scale_sign": self.negative_scale_sign,
            "centers": {name: center.debug_snapshot() for name, center in self.centers.items()},
        }


class MC2RuntimeOwner(MutableMapping):
    """MC2 运行期缓存 owner。

    当前仍对外表现得像 dict，内部已经按 TeamState/CenterState 承载。
    该对象必须作为 OmniNode cache 的实际 payload 保存，连续帧才能使用 mutate 模式。
    """

    def __init__(self, state: dict | None = None):
        self.team_state = MC2TeamState()
        self.center_key = "main"
        self.center_state.replace_legacy_state(state if isinstance(state, dict) else {})
        self.team_state.sync_from_legacy_state(self.state)

    def __getitem__(self, key):
        return self.state[key]

    def __setitem__(self, key, value) -> None:
        self.state[key] = value

    def __delitem__(self, key) -> None:
        del self.state[key]

    def __iter__(self):
        return iter(self.state)

    def __len__(self) -> int:
        return len(self.state)

    @property
    def center_state(self) -> MC2CenterState:
        return self.team_state.ensure_center(self.center_key)

    @property
    def state(self) -> dict:
        return self.center_state.legacy_state

    @state.setter
    def state(self, value: dict) -> None:
        self.center_state.replace_legacy_state(value)

    def replace_state(self, state: dict) -> None:
        self.center_state.replace_legacy_state(state)
        self.team_state.sync_from_legacy_state(self.state)

    def runtime_cache(self, name: str) -> dict:
        return self.center_state.runtime_cache(name)

    def runtime_cache_slots(self) -> dict:
        return self.center_state.runtime_cache_slots()

    @property
    def curve_cache(self) -> dict:
        return self.center_state.curve_cache

    @property
    def topology_cache(self) -> dict:
        return self.center_state.topology_cache

    @property
    def io_cache(self) -> dict:
        return self.center_state.io_cache

    @property
    def native_cache(self) -> dict:
        return self.center_state.native_cache

    @property
    def native_context(self):
        return self.center_state.native_context

    @native_context.setter
    def native_context(self, value) -> None:
        self.center_state.native_context = value

    def omni_cache_dispose(self, reason: str = "") -> None:
        # 后续 persistent native context 挂在 CenterState 上，由这里统一释放。
        self.team_state.dispose()

    def omni_cache_debug_snapshot(self) -> dict:
        center_snapshot = self.center_state.debug_snapshot()
        return {
            "kind": "MC2RuntimeOwner",
            "active_center": self.center_key,
            "center": center_snapshot,
            "team": self.team_state.debug_snapshot(),
        }


def unwrap_state(value) -> dict | None:
    if isinstance(value, MC2RuntimeOwner):
        return value.state if isinstance(value.state, dict) else None
    if isinstance(value, dict):
        return value
    return None


def ensure_runtime_owner(value=None) -> MC2RuntimeOwner:
    if isinstance(value, MC2RuntimeOwner):
        return value
    return MC2RuntimeOwner(unwrap_state(value))


def _extension_slots(state: dict) -> dict:
    extension_slots = state.get("extension_slots")
    if not isinstance(extension_slots, dict):
        extension_slots = {}
        state["extension_slots"] = extension_slots
    return extension_slots


def runtime_cache_slots(state: dict) -> dict:
    """返回当前 center 的 runtime cache namespace。

    新路径只在 extension_slots["runtime_cache"] 下暴露 cache；旧平铺 key 会被迁移进来，避免
    后续 Team/Center 扩展继续把 cache 和 solver feature slot 混在同一层。
    """
    extension_slots = _extension_slots(state)
    runtime_slots = extension_slots.get(MC2_RUNTIME_CACHE_SLOT)
    if not isinstance(runtime_slots, dict):
        runtime_slots = {}
        extension_slots[MC2_RUNTIME_CACHE_SLOT] = runtime_slots
    for name in MC2_RUNTIME_CACHE_NAMES:
        if name in runtime_slots:
            continue
        legacy_value = extension_slots.get(name)
        if isinstance(legacy_value, dict) or name == "native_context":
            runtime_slots[name] = legacy_value
    return runtime_slots


def extension_cache(state: dict, name: str) -> dict:
    runtime_slots = runtime_cache_slots(state)
    cache = runtime_slots.get(name)
    if not isinstance(cache, dict):
        cache = {}
        runtime_slots[name] = cache
    return cache


def set_runtime_cache_value(state: dict, name: str, value) -> None:
    runtime_cache_slots(state)[name] = value


def native_context(state: dict):
    return runtime_cache_slots(state).get("native_context")


def set_native_context(state: dict, value) -> None:
    set_runtime_cache_value(state, "native_context", value)


def feature_slots(state: dict) -> dict:
    extension_slots = _extension_slots(state)
    feature = extension_slots.get("features")
    if not isinstance(feature, dict):
        feature = {}
        extension_slots["features"] = feature
    for name in ("bonecloth", "curves", "self_collision", "native"):
        if name in feature:
            continue
        legacy_value = extension_slots.get(name)
        if isinstance(legacy_value, dict):
            feature[name] = legacy_value
        elif legacy_value is not None:
            feature[name] = {"value": legacy_value}
    return feature


def feature_slot(state: dict, name: str) -> dict:
    slots = feature_slots(state)
    slot = slots.get(name)
    if not isinstance(slot, dict):
        slot = {}
        slots[name] = slot
    return slot


def inherit_runtime_slots(source: dict, target: dict) -> dict:
    if not isinstance(source, dict) or not isinstance(target, dict):
        return target
    source_extension = source.get("extension_slots")
    if not isinstance(source_extension, dict):
        return target
    target_extension = _extension_slots(target)
    runtime_slots = source_extension.get(MC2_RUNTIME_CACHE_SLOT)
    if isinstance(runtime_slots, dict):
        target_extension[MC2_RUNTIME_CACHE_SLOT] = runtime_slots
    features = source_extension.get("features")
    if isinstance(features, dict):
        target_extension["features"] = features
    target["extension_slots"] = target_extension
    return target


def curve_cache(state: dict) -> dict:
    return extension_cache(state, "curve_cache")


def topology_cache(state: dict) -> dict:
    return extension_cache(state, "topology_cache")


def io_cache(state: dict) -> dict:
    return extension_cache(state, "io_cache")


def native_cache(state: dict) -> dict:
    return extension_cache(state, "native_cache")


def calc_inverse_masses(
    attributes: np.ndarray,
    depths: np.ndarray,
    friction: np.ndarray | None = None,
) -> np.ndarray:
    count = len(attributes)
    fr = np.zeros(count, dtype=np.float32) if friction is None else np.ascontiguousarray(friction, dtype=np.float32)
    dep = np.clip(np.ascontiguousarray(depths, dtype=np.float32), 0.0, 1.0)
    mass = 1.0 + fr * MC2SystemConstants.FRICTION_MASS + ((1.0 - dep) ** 2) * MC2SystemConstants.DEPTH_MASS
    inv = np.ascontiguousarray(1.0 / np.maximum(mass, MC2SystemConstants.EPSILON), dtype=np.float32)
    fixed = (np.ascontiguousarray(attributes, dtype=np.uint8) & MC2_ATTR_MOVE) == 0
    inv[fixed] = 0.0
    return inv


def build_state(
    obj: bpy.types.Object,
    output_key: str,
    mesh_light_key: tuple,
    mesh_signature_key: tuple,
    config_key: tuple,
    collision_radius: float,
    cache: dict | None = None,
) -> dict:
    rest_local = blender_io.read_rest_positions(obj)
    rest_world = blender_io.local_positions_to_world(obj, rest_local)
    rest_local_normals = mesh_build.rest_local_normals(obj)
    rest_world_normals = math_utils.transform_directions(math_utils.matrix_to_numpy(obj.matrix_world), rest_local_normals)
    edges, triangles = mesh_build.cached_connectivity_arrays(obj.data, mesh_signature_key, cache)
    attributes = mesh_build.build_attributes(obj)
    baseline_data = baseline.build_mesh_baseline(
        edges,
        rest_world,
        rest_world_normals,
        attributes,
    )
    depths = baseline_data["depths"]
    root_indices = baseline_data["root_indices"]
    parent_indices = baseline_data["parent_indices"]
    root_rest_lengths = baseline_data["root_rest_lengths"]
    friction = np.zeros(len(obj.data.vertices), dtype=np.float32)
    static_friction = np.zeros(len(obj.data.vertices), dtype=np.float32)
    inv_masses = calc_inverse_masses(attributes, depths, friction)
    edge_i, edge_j, edge_rest = mesh_build.build_edge_constraints(edges, rest_world)
    edge_type = mesh_build.structural_constraint_types(edge_i, edge_j, parent_indices)
    edge_i, edge_j, edge_rest, edge_type = mesh_build.append_shear_distance_constraints(
        edge_i,
        edge_j,
        edge_rest,
        edge_type,
        triangles,
        rest_world,
        attributes,
    )
    bend_i, bend_j, bend_rest, triangle_pairs = mesh_build.build_bend_constraints(triangles, rest_world)
    bend_type = mesh_build.bend_distance_constraint_types(bend_i)
    (
        dihedral_pairs,
        dihedral_rest_angles,
        dihedral_signs,
        volume_pairs,
        volume_rest,
    ) = mesh_build.build_dihedral_constraints(triangles, rest_world)
    distance_start, distance_count, distance_data, distance_rest = mesh_build.build_neighbor_table(
        len(obj.data.vertices),
        edge_i,
        edge_j,
        edge_rest,
        edge_type,
    )
    bend_start, bend_count, bend_data, bend_neighbor_rest = mesh_build.build_neighbor_table(
        len(obj.data.vertices),
        bend_i,
        bend_j,
        bend_rest,
        bend_type,
    )
    collision_local_radii, collision_mask = mesh_build.build_collision_profile(obj, collision_radius)
    zeros3 = np.zeros((len(obj.data.vertices), 3), dtype=np.float32)

    return {
        "kind": MC2_CACHE_KIND,
        "solver_version": MC2_SOLVER_VERSION,
        "frame": None,
        "object_name": obj.name_full,
        "object_ptr": int(obj.as_pointer()),
        "mesh_ptr": int(obj.data.as_pointer()),
        "output_key": output_key,
        "mesh_light_key": mesh_light_key,
        "mesh_signature_key": mesh_signature_key,
        "config_key": config_key,
        "object_matrix_world_key": math_utils.matrix_world_key(obj),
        "object_matrix_world_3x3_key": math_utils.matrix_world_3x3_key(obj),
        "object_matrix_world": math_utils.matrix_to_numpy(obj.matrix_world),
        "init_scale_radius": math_utils.matrix_scale_radius(obj.matrix_world),
        "scale_ratio": 1.0,
        "negative_scale_sign": math_utils.object_negative_scale_sign(obj),
        "velocity_weight": 0.0,
        "blend_weight": 0.0,
        "distance_weight": 1.0,
        "vertex_count": len(obj.data.vertices),
        "frame_delta_time": 0.0,
        "step_delta_time": 0.0,
        "substep_damping": 0.0,
        "rest_local_positions": np.ascontiguousarray(rest_local, dtype=np.float32),
        "rest_world_positions": np.ascontiguousarray(rest_world, dtype=np.float32),
        "rest_local_normals": np.ascontiguousarray(rest_local_normals, dtype=np.float32),
        "rest_world_normals": np.ascontiguousarray(rest_world_normals, dtype=np.float32),
        "base_positions": np.ascontiguousarray(rest_world.copy(), dtype=np.float32),
        "base_normals": np.ascontiguousarray(rest_world_normals.copy(), dtype=np.float32),
        "base_pose_proxy_ptr": 0,
        "base_pose_proxy_name": "",
        "base_pose_proxy_frame": None,
        "base_rotations": baseline_data["base_rotations"],
        "step_basic_positions": baseline_data["step_basic_positions"],
        "step_basic_rotations": baseline_data["step_basic_rotations"],
        "next_positions": np.ascontiguousarray(rest_world.copy(), dtype=np.float32),
        "old_positions": np.ascontiguousarray(rest_world.copy(), dtype=np.float32),
        "velocity_positions": zeros3.copy(),
        "display_positions": np.ascontiguousarray(rest_world.copy(), dtype=np.float32),
        "velocity": zeros3.copy(),
        "real_velocity": zeros3.copy(),
        "friction": friction,
        "static_friction": static_friction,
        "collision_normals": zeros3.copy(),
        "inertia_state": inertia.make_runtime_state(obj),
        "attributes": attributes,
        "depths": depths,
        "root_indices": root_indices,
        "parent_indices": parent_indices,
        "root_rest_lengths": root_rest_lengths,
        "baseline_start": baseline_data["baseline_start"],
        "baseline_count": baseline_data["baseline_count"],
        "baseline_data": baseline_data["baseline_data"],
        "baseline_flags": baseline_data["baseline_flags"],
        "vertex_local_positions": baseline_data["vertex_local_positions"],
        "vertex_local_rotations": baseline_data["vertex_local_rotations"],
        "tether_rest_lengths": mesh_build.build_tether_rest_lengths(rest_world, root_indices),
        "inv_masses": inv_masses,
        "edges": edges,
        "triangles": triangles,
        "edge_i": edge_i,
        "edge_j": edge_j,
        "edge_rest": edge_rest,
        "edge_type": edge_type,
        "bend_i": bend_i,
        "bend_j": bend_j,
        "bend_rest": bend_rest,
        "bend_type": bend_type,
        "triangle_pairs": triangle_pairs,
        "dihedral_pairs": dihedral_pairs,
        "dihedral_rest_angles": dihedral_rest_angles,
        "dihedral_signs": dihedral_signs,
        "volume_pairs": volume_pairs,
        "volume_rest": volume_rest,
        "bend_kind": (
            MC2_BEND_KIND_DIRECTION_DIHEDRAL
            if len(dihedral_pairs) > 0 or len(volume_pairs) > 0
            else MC2_BEND_KIND_DISTANCE_APPROX
        ),
        "bend_distance_i": bend_i,
        "bend_distance_j": bend_j,
        "bend_distance_rest": bend_rest,
        "bend_distance_type": bend_type,
        "distance_start": distance_start,
        "distance_count": distance_count,
        "distance_data": distance_data,
        "distance_rest": distance_rest,
        "bend_start": bend_start,
        "bend_count": bend_count,
        "bend_data": bend_data,
        "bend_neighbor_rest": bend_neighbor_rest,
        "bend_distance_start": bend_start,
        "bend_distance_count": bend_count,
        "bend_distance_data": bend_data,
        "bend_distance_neighbor_rest": bend_neighbor_rest,
        "collision_local_radii": collision_local_radii,
        "collision_radii": mesh_build.collision_radii_to_world(obj, collision_local_radii),
        "collided_by_groups": int(collision_mask),
        "param_slots": {name: None for name in MC2_CURVE_READY_PARAMETERS},
        "extension_slots": {
            MC2_RUNTIME_CACHE_SLOT: {},
            "features": {
                "bonecloth": {},
                "curves": {},
                "self_collision": {},
                "native": {},
            },
        },
    }


def sync_state_to_object_transform(state: dict, obj: bpy.types.Object) -> dict:
    matrix_key = math_utils.matrix_world_key(obj)
    matrix_3x3_key = math_utils.matrix_world_3x3_key(obj)
    if (
        state.get("object_matrix_world_key") == matrix_key
        and state.get("object_matrix_world_3x3_key") == matrix_3x3_key
    ):
        return state

    next_state = inherit_runtime_slots(state, dict(state))
    new_world = math_utils.matrix_to_numpy(obj.matrix_world)
    rest_local = np.ascontiguousarray(next_state["rest_local_positions"], dtype=np.float32)
    rest_world = blender_io.local_positions_to_world(obj, rest_local)
    rest_local_normals = np.ascontiguousarray(next_state.get("rest_local_normals"), dtype=np.float32)
    if rest_local_normals.shape != rest_world.shape:
        rest_local_normals = mesh_build.rest_local_normals(obj)
    rest_world_normals = math_utils.transform_directions(new_world, rest_local_normals)
    next_state["object_matrix_world_key"] = matrix_key
    next_state["object_matrix_world"] = new_world
    next_state["scale_ratio"] = math_utils.matrix_scale_ratio(
        obj.matrix_world,
        next_state.get("init_scale_radius", math_utils.matrix_scale_radius(obj.matrix_world)),
    )
    next_state["negative_scale_sign"] = math_utils.object_negative_scale_sign(obj)

    if next_state.get("object_matrix_world_3x3_key") != matrix_3x3_key:
        edge_i, edge_j, edge_rest = mesh_build.build_edge_constraints(next_state["edges"], rest_world)
        baseline_data = baseline.build_mesh_baseline(
            next_state["edges"],
            rest_world,
            rest_world_normals,
            next_state["attributes"],
        )
        next_state["depths"] = baseline_data["depths"]
        next_state["root_indices"] = baseline_data["root_indices"]
        next_state["parent_indices"] = baseline_data["parent_indices"]
        next_state["root_rest_lengths"] = baseline_data["root_rest_lengths"]
        next_state["baseline_start"] = baseline_data["baseline_start"]
        next_state["baseline_count"] = baseline_data["baseline_count"]
        next_state["baseline_data"] = baseline_data["baseline_data"]
        next_state["baseline_flags"] = baseline_data["baseline_flags"]
        next_state["base_rotations"] = baseline_data["base_rotations"]
        next_state["vertex_local_positions"] = baseline_data["vertex_local_positions"]
        next_state["vertex_local_rotations"] = baseline_data["vertex_local_rotations"]
        next_state["step_basic_positions"] = baseline_data["step_basic_positions"]
        next_state["step_basic_rotations"] = baseline_data["step_basic_rotations"]
        edge_type = mesh_build.structural_constraint_types(
            edge_i,
            edge_j,
            next_state["parent_indices"],
        )
        edge_i, edge_j, edge_rest, edge_type = mesh_build.append_shear_distance_constraints(
            edge_i,
            edge_j,
            edge_rest,
            edge_type,
            next_state["triangles"],
            rest_world,
            next_state["attributes"],
        )
        next_state["edge_i"] = edge_i
        next_state["edge_j"] = edge_j
        next_state["edge_rest"] = edge_rest
        next_state["edge_type"] = edge_type
        bend_i = next_state.get("bend_distance_i", next_state["bend_i"])
        bend_j = next_state.get("bend_distance_j", next_state["bend_j"])
        next_state["bend_distance_rest"] = mesh_build.constraint_lengths(rest_world, bend_i, bend_j)
        next_state["bend_distance_type"] = mesh_build.bend_distance_constraint_types(bend_i)
        (
            next_state["dihedral_pairs"],
            next_state["dihedral_rest_angles"],
            next_state["dihedral_signs"],
            next_state["volume_pairs"],
            next_state["volume_rest"],
        ) = mesh_build.build_dihedral_constraints(next_state["triangles"], rest_world)
        next_state["bend_kind"] = (
            MC2_BEND_KIND_DIRECTION_DIHEDRAL
            if len(next_state["dihedral_pairs"]) > 0 or len(next_state["volume_pairs"]) > 0
            else MC2_BEND_KIND_DISTANCE_APPROX
        )
        next_state["bend_i"] = bend_i
        next_state["bend_j"] = bend_j
        next_state["bend_rest"] = next_state["bend_distance_rest"]
        next_state["bend_type"] = next_state["bend_distance_type"]
        (
            next_state["distance_start"],
            next_state["distance_count"],
            next_state["distance_data"],
            next_state["distance_rest"],
        ) = mesh_build.build_neighbor_table(
            int(next_state["vertex_count"]),
            edge_i,
            edge_j,
            edge_rest,
            edge_type,
        )
        (
            next_state["bend_start"],
            next_state["bend_count"],
            next_state["bend_data"],
            next_state["bend_neighbor_rest"],
        ) = mesh_build.build_neighbor_table(
            int(next_state["vertex_count"]),
            bend_i,
            bend_j,
            next_state["bend_distance_rest"],
            next_state["bend_distance_type"],
        )
        next_state["bend_distance_start"] = next_state["bend_start"]
        next_state["bend_distance_count"] = next_state["bend_count"]
        next_state["bend_distance_data"] = next_state["bend_data"]
        next_state["bend_distance_neighbor_rest"] = next_state["bend_neighbor_rest"]
        next_state["tether_rest_lengths"] = mesh_build.build_tether_rest_lengths(rest_world, next_state["root_indices"])
        next_state["collision_radii"] = mesh_build.collision_radii_to_world(obj, next_state["collision_local_radii"])
        next_state["inv_masses"] = calc_inverse_masses(
            next_state["attributes"],
            next_state["depths"],
            next_state["friction"],
        )
        next_state["object_matrix_world_3x3_key"] = matrix_3x3_key

    next_state["rest_world_positions"] = np.ascontiguousarray(rest_world, dtype=np.float32)
    next_state["rest_local_normals"] = np.ascontiguousarray(rest_local_normals, dtype=np.float32)
    next_state["rest_world_normals"] = np.ascontiguousarray(rest_world_normals, dtype=np.float32)
    next_state["base_positions"] = np.ascontiguousarray(rest_world.copy(), dtype=np.float32)
    next_state["base_normals"] = np.ascontiguousarray(rest_world_normals.copy(), dtype=np.float32)
    next_state["base_pose_proxy_ptr"] = 0
    next_state["base_pose_proxy_name"] = ""
    next_state["base_pose_proxy_frame"] = None
    if next_state.get("object_matrix_world_3x3_key") == matrix_3x3_key:
        (
            next_state["step_basic_positions"],
            next_state["step_basic_rotations"],
        ) = baseline.update_step_basic_pose(
            next_state["base_positions"],
            next_state["base_rotations"],
            next_state["parent_indices"],
            next_state["baseline_start"],
            next_state["baseline_count"],
            next_state["baseline_data"],
            next_state["vertex_local_positions"],
            next_state["vertex_local_rotations"],
        )

    return next_state


def sync_state_to_base_pose_write_container(state: dict, obj: bpy.types.Object) -> dict:
    matrix_key = math_utils.matrix_world_key(obj)
    matrix_3x3_key = math_utils.matrix_world_3x3_key(obj)
    if (
        state.get("object_matrix_world_key") == matrix_key
        and state.get("object_matrix_world_3x3_key") == matrix_3x3_key
    ):
        return state

    # BasePose 模式下，当前物体只是 GN delta 写入容器。
    # 动画姿态来自 BasePose 只读对象，不能在这里用写入容器的对象矩阵重建 rest/约束，
    # 否则移动骨架对象会触发整套约束热重算，并且和 BasePose evaluated 坐标形成双重变换。
    next_state = inherit_runtime_slots(state, dict(state))
    next_state["object_matrix_world_key"] = matrix_key
    next_state["object_matrix_world_3x3_key"] = matrix_3x3_key
    next_state["object_matrix_world"] = math_utils.matrix_to_numpy(obj.matrix_world)
    next_state["scale_ratio"] = math_utils.matrix_scale_ratio(
        obj.matrix_world,
        next_state.get("init_scale_radius", math_utils.matrix_scale_radius(obj.matrix_world)),
    )
    next_state["negative_scale_sign"] = math_utils.object_negative_scale_sign(obj)
    next_state["collision_radii"] = mesh_build.collision_radii_to_world(obj, next_state["collision_local_radii"])
    return next_state


def _apply_base_pose_arrays(
    state: dict,
    positions: np.ndarray,
    normals: np.ndarray,
    proxy_ptr: int,
    proxy_name: str,
    frame: int | None,
) -> dict:
    vertex_count = int(state.get("vertex_count", 0))
    base_positions = np.ascontiguousarray(positions, dtype=np.float32)
    base_normals = np.ascontiguousarray(normals, dtype=np.float32)
    if base_positions.shape != (vertex_count, 3) or base_normals.shape != (vertex_count, 3):
        raise ValueError("MC2 BasePose只读对象顶点数必须与当前物理对象一致")

    next_state = inherit_runtime_slots(state, dict(state))
    native_base_pose = native_bridge.update_base_pose_from_pose(
        base_positions,
        base_normals,
        next_state["parent_indices"],
        next_state["baseline_start"],
        next_state["baseline_count"],
        next_state["baseline_data"],
        next_state["vertex_local_positions"],
        next_state["vertex_local_rotations"],
    )
    next_state["base_positions"] = base_positions
    next_state["base_normals"] = base_normals
    if native_base_pose is not None:
        base_rotations, step_positions, step_rotations = native_base_pose
        next_state["base_rotations"] = base_rotations
        next_state["step_basic_positions"] = step_positions
        next_state["step_basic_rotations"] = step_rotations
    else:
        # 旧 native 后端不存在 update_base_pose_from_pose_mc2 时的降级路径。
        # 不在 Python 热路径里重算整套四元数链，避免回到 20ms+ 的卡顿/崩溃风险。
        next_state["step_basic_positions"] = base_positions.copy()
    next_state["base_pose_proxy_ptr"] = int(proxy_ptr)
    next_state["base_pose_proxy_name"] = str(proxy_name or "")
    next_state["base_pose_proxy_frame"] = frame
    return next_state


def sync_state_to_base_pose_proxy(
    state: dict,
    obj: bpy.types.Object,
    base_pose_proxy: bpy.types.Object | None,
    current_frame: int,
    timing: dict | None = None,
    cache: dict | None = None,
) -> dict:
    if base_pose_proxy is None:
        if int(state.get("base_pose_proxy_ptr", 0) or 0) == 0:
            return state
        return _apply_base_pose_arrays(
            state,
            state["rest_world_positions"],
            state["rest_world_normals"],
            0,
            "",
            None,
        )

    vertex_count = int(state.get("vertex_count", len(obj.data.vertices)))
    if len(base_pose_proxy.data.vertices) != vertex_count:
        raise ValueError("MC2 BasePose只读对象顶点数必须与当前物理对象一致")

    proxy_ptr = int(base_pose_proxy.as_pointer())
    if (
        int(state.get("base_pose_proxy_ptr", 0) or 0) == proxy_ptr
        and state.get("base_pose_proxy_frame") == current_frame
    ):
        return state

    stage_start = time.perf_counter() if timing is not None else None
    pose_cache = cache if isinstance(cache, dict) else io_cache(state)
    if len(pose_cache) > 12:
        pose_cache.clear()
    positions, normals = blender_io.read_cached_base_pose_world_pose(
        obj,
        base_pose_proxy,
        current_frame,
        cache=pose_cache,
    )
    if timing is not None:
        stage_name = "base_pose_sync.proxy_read"
        timing["stages"][stage_name] = timing["stages"].get(stage_name, 0.0) + (
            time.perf_counter() - stage_start
        )
    if positions.shape != (vertex_count, 3) or normals.shape != (vertex_count, 3):
        raise ValueError("MC2 BasePose只读对象 evaluated mesh 顶点数必须与当前物理对象一致")

    stage_start = time.perf_counter() if timing is not None else None
    next_state = _apply_base_pose_arrays(
        state,
        positions,
        normals,
        proxy_ptr,
        base_pose_proxy.name_full,
        current_frame,
    )
    if timing is not None:
        stage_name = "base_pose_sync.apply"
        timing["stages"][stage_name] = timing["stages"].get(stage_name, 0.0) + (
            time.perf_counter() - stage_start
        )
    return next_state


def state_matches(
    state,
    obj: bpy.types.Object,
    output_key: str,
    mesh_light_key: tuple,
) -> bool:
    state = unwrap_state(state)
    if not isinstance(state, dict):
        return False

    vertex_count = len(obj.data.vertices)
    required_shapes = {
        "rest_local_positions": (vertex_count, 3),
        "rest_world_positions": (vertex_count, 3),
        "rest_local_normals": (vertex_count, 3),
        "rest_world_normals": (vertex_count, 3),
        "base_positions": (vertex_count, 3),
        "base_normals": (vertex_count, 3),
        "base_rotations": (vertex_count, 4),
        "step_basic_positions": (vertex_count, 3),
        "step_basic_rotations": (vertex_count, 4),
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
        "vertex_local_positions": (vertex_count, 3),
        "vertex_local_rotations": (vertex_count, 4),
        "tether_rest_lengths": (vertex_count,),
        "inv_masses": (vertex_count,),
        "collision_local_radii": (vertex_count,),
        "collision_radii": (vertex_count,),
        "distance_start": (vertex_count,),
        "distance_count": (vertex_count,),
        "bend_start": (vertex_count,),
        "bend_count": (vertex_count,),
        "bend_distance_start": (vertex_count,),
        "bend_distance_count": (vertex_count,),
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
    dihedral_pairs = array_ndim_shape("dihedral_pairs", 2, (4,))
    volume_pairs = array_ndim_shape("volume_pairs", 2, (4,))
    if edges is None or triangles is None or triangle_pairs is None or dihedral_pairs is None or volume_pairs is None:
        return False
    if int(edges.size) and (int(np.min(edges)) < 0 or int(np.max(edges)) >= vertex_count):
        return False
    if int(triangles.size) and (int(np.min(triangles)) < 0 or int(np.max(triangles)) >= vertex_count):
        return False
    if int(triangle_pairs.size) and (int(np.min(triangle_pairs)) < 0 or int(np.max(triangle_pairs)) >= vertex_count):
        return False
    if int(dihedral_pairs.size) and (int(np.min(dihedral_pairs)) < 0 or int(np.max(dihedral_pairs)) >= vertex_count):
        return False
    if int(volume_pairs.size) and (int(np.min(volume_pairs)) < 0 or int(np.max(volume_pairs)) >= vertex_count):
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

    if not same_1d_length(("edge_i", "edge_j", "edge_rest", "edge_type")):
        return False
    if not same_1d_length(("bend_i", "bend_j", "bend_rest", "bend_type")):
        return False
    if not same_1d_length(("bend_distance_i", "bend_distance_j", "bend_distance_rest", "bend_distance_type")):
        return False
    if not same_1d_length(("distance_data", "distance_rest")):
        return False
    if not same_1d_length(("bend_data", "bend_neighbor_rest")):
        return False
    if not same_1d_length(("bend_distance_data", "bend_distance_neighbor_rest")):
        return False
    if not same_1d_length(("dihedral_rest_angles", "dihedral_signs")):
        return False
    if not same_1d_length(("volume_rest",)):
        return False
    if not same_1d_length(("baseline_start", "baseline_count", "baseline_flags")):
        return False
    baseline_data = state.get("baseline_data")
    if not isinstance(baseline_data, np.ndarray) or baseline_data.ndim != 1:
        return False
    if len(baseline_data) > 0 and (int(np.min(baseline_data)) < 0 or int(np.max(baseline_data)) >= vertex_count):
        return False
    for start, count in zip(state["baseline_start"], state["baseline_count"]):
        start_i = int(start)
        count_i = int(count)
        if start_i < 0 or count_i < 0 or start_i + count_i > len(baseline_data):
            return False
    if len(state["edge_i"]) < len(edges):
        return False
    if len(state["bend_i"]) != len(triangle_pairs):
        return False
    if len(state["bend_distance_i"]) != len(triangle_pairs):
        return False
    if len(state["dihedral_rest_angles"]) != len(dihedral_pairs):
        return False
    if len(state["volume_rest"]) != len(volume_pairs):
        return False

    if state.get("bend_kind") not in {MC2_BEND_KIND_DISTANCE_APPROX, MC2_BEND_KIND_DIRECTION_DIHEDRAL}:
        return False

    for index_key in (
        "edge_i",
        "edge_j",
        "bend_i",
        "bend_j",
        "bend_distance_i",
        "bend_distance_j",
        "distance_data",
        "bend_data",
        "bend_distance_data",
    ):
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

    inertia_state = state.get("inertia_state")
    if not isinstance(inertia_state, dict):
        return False

    return (
        state.get("kind") == MC2_CACHE_KIND
        and state.get("solver_version") == MC2_SOLVER_VERSION
        and state.get("object_ptr") == int(obj.as_pointer())
        and state.get("mesh_ptr") == int(obj.data.as_pointer())
        and state.get("output_key") == output_key
        and state.get("mesh_light_key") == mesh_light_key
        and state.get("vertex_count") == vertex_count
    )
