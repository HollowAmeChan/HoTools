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


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_unit_float(value, default: float = 0.0) -> float:
    return max(0.0, min(1.0, _safe_float(value, default)))


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return bool(default)
    return bool(value)


def _safe_direction3(value, default: tuple[int, int, int] = (1, 1, 1)) -> tuple[int, int, int]:
    if isinstance(value, np.ndarray):
        value = value.reshape(-1)
    if isinstance(value, (list, tuple, np.ndarray)) and len(value) >= 3:
        result = []
        for item in value[:3]:
            sign = _safe_int(item, 1)
            result.append(sign if sign != 0 else 1)
        return (result[0], result[1], result[2])
    return default


def _safe_tuple3(value, default: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    if isinstance(value, np.ndarray):
        value = value.reshape(-1)
    if isinstance(value, (list, tuple, np.ndarray)) and len(value) >= 3:
        return (
            _safe_float(value[0], default[0]),
            _safe_float(value[1], default[1]),
            _safe_float(value[2], default[2]),
        )
    return default


def _safe_vector_length(value, default: float = 0.0) -> float:
    try:
        vector = np.asarray(value, dtype=np.float32).reshape(-1)
        if len(vector) < 3:
            return float(default)
        return float(np.linalg.norm(vector[:3]))
    except Exception:
        return float(default)


def _safe_vector3_array(value, default=None) -> np.ndarray:
    if default is None:
        default = np.zeros(3, dtype=np.float32)
    try:
        vector = np.asarray(value, dtype=np.float32).reshape(-1)
        if len(vector) >= 3:
            return np.ascontiguousarray(vector[:3], dtype=np.float32)
    except Exception:
        pass
    return np.ascontiguousarray(np.asarray(default, dtype=np.float32).reshape(-1)[:3], dtype=np.float32)


def _safe_quat_array(value, default=None) -> np.ndarray:
    if default is None:
        default = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    try:
        quat = np.asarray(value, dtype=np.float32).reshape(-1)
        if len(quat) >= 4:
            return np.ascontiguousarray(quat[:4], dtype=np.float32)
    except Exception:
        pass
    return np.ascontiguousarray(np.asarray(default, dtype=np.float32).reshape(-1)[:4], dtype=np.float32)


def _safe_matrix4_array(value, default=None) -> np.ndarray:
    if default is None:
        default = np.eye(4, dtype=np.float32)
    try:
        matrix = np.asarray(value, dtype=np.float32)
        if matrix.shape == (4, 4):
            return np.ascontiguousarray(matrix, dtype=np.float32)
        flat = matrix.reshape(-1)
        if len(flat) >= 16:
            return np.ascontiguousarray(flat[:16].reshape(4, 4), dtype=np.float32)
    except Exception:
        pass
    return np.ascontiguousarray(np.asarray(default, dtype=np.float32).reshape(4, 4), dtype=np.float32)


def _tuple3_for_debug(value) -> tuple[float, float, float]:
    vector = _safe_vector3_array(value)
    return (float(vector[0]), float(vector[1]), float(vector[2]))


def _safe_shaped_array(value, shape: tuple[int, ...], dtype=np.float32, default=None) -> np.ndarray:
    shape = tuple(max(0, int(dim)) for dim in shape)
    expected_size = int(np.prod(shape, dtype=np.int64)) if shape else 1

    def coerce(candidate) -> np.ndarray | None:
        if candidate is None:
            return None
        try:
            array = np.asarray(candidate, dtype=dtype)
            if array.shape == shape:
                return np.ascontiguousarray(array, dtype=dtype)
            flat = array.reshape(-1)
            if int(flat.size) == expected_size:
                return np.ascontiguousarray(flat.reshape(shape), dtype=dtype)
        except Exception:
            return None
        return None

    result = coerce(value)
    if result is not None:
        return result
    result = coerce(default)
    if result is not None:
        return result
    return np.zeros(shape, dtype=dtype)


def _safe_flat_array(value, dtype=np.float32, default=None) -> np.ndarray:
    def coerce(candidate) -> np.ndarray | None:
        if candidate is None:
            return None
        try:
            return np.ascontiguousarray(np.asarray(candidate, dtype=dtype).reshape(-1), dtype=dtype)
        except Exception:
            return None

    result = coerce(value)
    if result is not None:
        return result
    result = coerce(default)
    if result is not None:
        return result
    return np.empty(0, dtype=dtype)


def _safe_tailed_array(value, tail: tuple[int, ...], dtype=np.float32, default=None) -> np.ndarray:
    tail = tuple(max(0, int(dim)) for dim in tail)
    tail_size = int(np.prod(tail, dtype=np.int64)) if tail else 1

    def empty() -> np.ndarray:
        return np.empty((0, *tail), dtype=dtype) if tail else np.empty(0, dtype=dtype)

    def coerce(candidate) -> np.ndarray | None:
        if candidate is None:
            return None
        try:
            array = np.asarray(candidate, dtype=dtype)
            if not tail:
                return np.ascontiguousarray(array.reshape(-1), dtype=dtype)
            if array.ndim >= len(tail) + 1 and array.shape[-len(tail):] == tail:
                return np.ascontiguousarray(array.reshape((-1, *tail)), dtype=dtype)
            flat = array.reshape(-1)
            if tail_size > 0 and int(flat.size) % tail_size == 0:
                return np.ascontiguousarray(flat.reshape((-1, *tail)), dtype=dtype)
        except Exception:
            return None
        return None

    result = coerce(value)
    if result is not None:
        return result
    result = coerce(default)
    if result is not None:
        return result
    return empty()


def _safe_particle_array(value, count: int, width: int = 3, default=None) -> np.ndarray:
    return _safe_shaped_array(value, (count, width), np.float32, default)


def _safe_particle_scalar_array(value, count: int, default=None) -> np.ndarray:
    return _safe_shaped_array(value, (count,), np.float32, default)


def _identity_quat_array(count: int) -> np.ndarray:
    quats = np.zeros((max(0, int(count)), 4), dtype=np.float32)
    if len(quats):
        quats[:, 3] = 1.0
    return quats


@dataclass
class MC2NativeContext:
    """未来 C++ persistent context 的 Python 生命周期占位。"""

    topology_key: tuple | None = None
    config_key: tuple | None = None
    param_key: tuple | None = None
    vertex_count: int = 0
    distance_count: int = 0
    bend_count: int = 0
    collider_radius_count: int = 0
    handle: object | None = None
    static_arrays: dict | None = None
    param_slots: dict | None = None
    param_arrays: dict | None = None
    param_arrays_key: tuple | None = None
    native_info: dict | None = None
    native_static_ready: bool = False
    native_params_ready: bool = False
    topology_dirty: bool = True
    params_dirty: bool = True
    frame_serial: int = 0

    @staticmethod
    def _safe_len(value) -> int:
        try:
            return int(len(value))
        except Exception:
            return 0

    @staticmethod
    def _normalize_key(value):
        if isinstance(value, np.ndarray):
            value = value.reshape(-1).tolist()
        if isinstance(value, (list, tuple)):
            return tuple(MC2NativeContext._normalize_key(item) for item in value)
        return value

    def update_static_keys(self, topology_state) -> None:
        if topology_state is None:
            raise RuntimeError("MC2 native context requires MC2TopologyState")
        topology_key = (
            getattr(topology_state, "mesh_signature_key", None),
            getattr(topology_state, "object_matrix_world_3x3_key", None),
        )
        config_key = getattr(topology_state, "config_key", None)
        next_vertex_count = int(getattr(topology_state, "vertex_count", 0) or 0)
        next_distance_count = self._safe_len(getattr(topology_state, "distance_data", None))
        next_bend_count = self._safe_len(getattr(topology_state, "bend_distance_data", None))
        next_collider_radius_count = self._safe_len(getattr(topology_state, "collision_local_radii", None))
        next_topology_key = self._normalize_key(topology_key)
        next_config_key = self._normalize_key(config_key)
        topology_dirty = (
            self.topology_key != next_topology_key
            or self.config_key != next_config_key
            or self.vertex_count != next_vertex_count
            or self.distance_count != next_distance_count
            or self.bend_count != next_bend_count
            or self.collider_radius_count != next_collider_radius_count
        )
        self.topology_key = next_topology_key
        self.config_key = next_config_key
        self.vertex_count = next_vertex_count
        self.distance_count = next_distance_count
        self.bend_count = next_bend_count
        self.collider_radius_count = next_collider_radius_count
        self.topology_dirty = bool(topology_dirty)
        if self.handle is None:
            self.handle = native_bridge.create_meshcloth_context(
                self.vertex_count,
                self.distance_count,
                self.bend_count,
                self.collider_radius_count,
            )
            self.native_static_ready = False
            self.native_params_ready = False
        elif self.topology_dirty:
            native_bridge.update_meshcloth_context_static(
                self.handle,
                self.vertex_count,
                self.distance_count,
                self.bend_count,
                self.collider_radius_count,
            )
            self.native_static_ready = False
            self.native_params_ready = False
            self.param_arrays = None
            self.param_arrays_key = None
        self.native_info = native_bridge.meshcloth_context_info(self.handle)

    def upload_static_arrays(self, topology_state=None, base_pose_state=None) -> dict:
        if self.topology_dirty or not isinstance(self.static_arrays, dict):
            if topology_state is not None and hasattr(topology_state, "to_native_static_arrays"):
                self.static_arrays = topology_state.to_native_static_arrays(base_pose_state)
            else:
                raise RuntimeError("MC2 native static arrays require MC2TopologyState")
            self.native_static_ready = False
        if self.handle is not None and not self.native_static_ready:
            self.native_static_ready = native_bridge.update_meshcloth_context_static_arrays(
                self.handle,
                self.static_arrays,
            )
            self.native_info = native_bridge.meshcloth_context_info(self.handle)
        return self.static_arrays

    def update_param_key(self, param_key: tuple | None, param_slots: dict | None = None) -> None:
        next_key = tuple(param_key) if isinstance(param_key, (list, tuple)) else param_key
        self.params_dirty = self.param_key != next_key
        self.param_key = next_key
        if param_slots is not None:
            self.param_slots = param_slots
        if self.handle is not None and self.params_dirty:
            self.native_params_ready = False
            self.param_arrays = None
            self.param_arrays_key = None
            native_bridge.update_meshcloth_context_params(
                self.handle,
                len(self.param_slots) if isinstance(self.param_slots, dict) else 0,
            )
            self.native_info = native_bridge.meshcloth_context_info(self.handle)
        self.frame_serial += 1

    def upload_param_arrays(self, arrays: dict) -> bool:
        next_key = _native_param_arrays_key(arrays)
        arrays_dirty = self.param_arrays_key != next_key
        self.param_arrays_key = next_key
        self.param_arrays = arrays
        if self.handle is None:
            self.native_params_ready = False
            return False
        if arrays_dirty:
            self.native_params_ready = False
        if self.params_dirty or not self.native_params_ready:
            self.native_params_ready = native_bridge.update_meshcloth_context_param_arrays(
                self.handle,
                arrays,
            )
            self.native_info = native_bridge.meshcloth_context_info(self.handle)
        return bool(self.native_params_ready)

    def debug_snapshot(self) -> dict:
        return {
            "has_handle": self.handle is not None,
            "native_static_ready": self.native_static_ready,
            "native_params_ready": self.native_params_ready,
            "topology_dirty": self.topology_dirty,
            "params_dirty": self.params_dirty,
            "frame_serial": self.frame_serial,
            "verts": self.vertex_count,
            "distance_items": self.distance_count,
            "bend_items": self.bend_count,
            "collision_radii": self.collider_radius_count,
            "param_slots": len(self.param_slots) if isinstance(self.param_slots, dict) else 0,
            "param_arrays": len(self.param_arrays) if isinstance(self.param_arrays, dict) else 0,
            "has_param_arrays_key": self.param_arrays_key is not None,
            "native_info": self.native_info,
        }

    def dispose(self) -> None:
        native_bridge.free_meshcloth_context(self.handle)
        self.handle = None
        self.static_arrays = None
        self.native_static_ready = False
        self.param_slots = None
        self.param_arrays = None
        self.param_arrays_key = None
        self.native_params_ready = False
        self.native_info = None


@dataclass
class MC2ParticleState:
    vertex_count: int = 0
    next_positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.float32))
    old_positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.float32))
    velocity_positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.float32))
    display_positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.float32))
    velocity: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.float32))
    real_velocity: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.float32))
    friction: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    static_friction: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    collision_normals: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.float32))
    inv_masses: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))

    def replace_from_state(self, state: dict, vertex_count: int | None = None) -> None:
        if not isinstance(state, dict):
            return
        count = int(vertex_count if vertex_count is not None else state.get("vertex_count", self.vertex_count) or 0)
        self.vertex_count = max(0, count)
        self.next_positions = _safe_particle_array(state.get("next_positions"), self.vertex_count, 3, self.next_positions)
        self.old_positions = _safe_particle_array(state.get("old_positions"), self.vertex_count, 3, self.old_positions)
        self.velocity_positions = _safe_particle_array(
            state.get("velocity_positions"),
            self.vertex_count,
            3,
            self.velocity_positions,
        )
        self.display_positions = _safe_particle_array(
            state.get("display_positions"),
            self.vertex_count,
            3,
            self.display_positions,
        )
        self.velocity = _safe_particle_array(state.get("velocity"), self.vertex_count, 3, self.velocity)
        self.real_velocity = _safe_particle_array(state.get("real_velocity"), self.vertex_count, 3, self.real_velocity)
        self.friction = _safe_particle_scalar_array(state.get("friction"), self.vertex_count, self.friction)
        self.static_friction = _safe_particle_scalar_array(
            state.get("static_friction"),
            self.vertex_count,
            self.static_friction,
        )
        self.collision_normals = _safe_particle_array(
            state.get("collision_normals"),
            self.vertex_count,
            3,
            self.collision_normals,
        )
        self.inv_masses = _safe_particle_scalar_array(state.get("inv_masses"), self.vertex_count, self.inv_masses)

    def mirror_to_state(self, state: dict | None) -> None:
        if not isinstance(state, dict):
            return
        state["next_positions"] = np.ascontiguousarray(self.next_positions, dtype=np.float32)
        state["old_positions"] = np.ascontiguousarray(self.old_positions, dtype=np.float32)
        state["velocity_positions"] = np.ascontiguousarray(self.velocity_positions, dtype=np.float32)
        state["display_positions"] = np.ascontiguousarray(self.display_positions, dtype=np.float32)
        state["velocity"] = np.ascontiguousarray(self.velocity, dtype=np.float32)
        state["real_velocity"] = np.ascontiguousarray(self.real_velocity, dtype=np.float32)
        state["friction"] = np.ascontiguousarray(self.friction, dtype=np.float32)
        state["static_friction"] = np.ascontiguousarray(self.static_friction, dtype=np.float32)
        state["collision_normals"] = np.ascontiguousarray(self.collision_normals, dtype=np.float32)
        state["inv_masses"] = np.ascontiguousarray(self.inv_masses, dtype=np.float32)

    def update_from_arrays(
        self,
        *,
        next_positions,
        old_positions,
        velocity_positions,
        display_positions,
        velocity,
        real_velocity,
        friction,
        static_friction,
        collision_normals,
        inv_masses,
    ) -> None:
        count = int(len(next_positions))
        self.vertex_count = max(0, count)
        self.next_positions = _safe_particle_array(next_positions, self.vertex_count, 3, self.next_positions)
        self.old_positions = _safe_particle_array(old_positions, self.vertex_count, 3, self.old_positions)
        self.velocity_positions = _safe_particle_array(velocity_positions, self.vertex_count, 3, self.velocity_positions)
        self.display_positions = _safe_particle_array(display_positions, self.vertex_count, 3, self.display_positions)
        self.velocity = _safe_particle_array(velocity, self.vertex_count, 3, self.velocity)
        self.real_velocity = _safe_particle_array(real_velocity, self.vertex_count, 3, self.real_velocity)
        self.friction = _safe_particle_scalar_array(friction, self.vertex_count, self.friction)
        self.static_friction = _safe_particle_scalar_array(static_friction, self.vertex_count, self.static_friction)
        self.collision_normals = _safe_particle_array(collision_normals, self.vertex_count, 3, self.collision_normals)
        self.inv_masses = _safe_particle_scalar_array(inv_masses, self.vertex_count, self.inv_masses)

    def debug_snapshot(self) -> dict:
        velocity_max = 0.0
        real_velocity_max = 0.0
        if self.velocity.size:
            velocity_max = float(np.max(np.linalg.norm(self.velocity.reshape((-1, 3)), axis=1)))
        if self.real_velocity.size:
            real_velocity_max = float(np.max(np.linalg.norm(self.real_velocity.reshape((-1, 3)), axis=1)))
        return {
            "verts": self.vertex_count,
            "next_positions": tuple(self.next_positions.shape),
            "old_positions": tuple(self.old_positions.shape),
            "display_positions": tuple(self.display_positions.shape),
            "velocity_max": velocity_max,
            "real_velocity_max": real_velocity_max,
            "friction_max": float(np.max(self.friction)) if self.friction.size else 0.0,
            "static_friction_max": float(np.max(self.static_friction)) if self.static_friction.size else 0.0,
            "collision_normal_max": (
                float(np.max(np.linalg.norm(self.collision_normals.reshape((-1, 3)), axis=1)))
                if self.collision_normals.size
                else 0.0
            ),
        }


@dataclass
class MC2BasePoseState:
    vertex_count: int = 0
    base_positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.float32))
    base_normals: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.float32))
    base_rotations: np.ndarray = field(default_factory=lambda: np.zeros((0, 4), dtype=np.float32))
    step_basic_positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.float32))
    step_basic_rotations: np.ndarray = field(default_factory=lambda: np.zeros((0, 4), dtype=np.float32))
    proxy_ptr: int = 0
    proxy_name: str = ""
    proxy_frame: int | None = None

    def replace_from_state(self, state: dict, vertex_count: int | None = None) -> None:
        if not isinstance(state, dict):
            return
        count = int(vertex_count if vertex_count is not None else state.get("vertex_count", self.vertex_count) or 0)
        self.vertex_count = max(0, count)
        rest_positions = state.get("rest_world_positions", self.base_positions)
        rest_normals = state.get("rest_world_normals", self.base_normals)
        self.base_positions = _safe_particle_array(
            state.get("base_positions"),
            self.vertex_count,
            3,
            rest_positions,
        )
        self.base_normals = _safe_particle_array(
            state.get("base_normals"),
            self.vertex_count,
            3,
            rest_normals,
        )
        self.base_rotations = _safe_particle_array(
            state.get("base_rotations"),
            self.vertex_count,
            4,
            self.base_rotations if len(self.base_rotations) else _identity_quat_array(self.vertex_count),
        )
        self.step_basic_positions = _safe_particle_array(
            state.get("step_basic_positions"),
            self.vertex_count,
            3,
            self.base_positions,
        )
        self.step_basic_rotations = _safe_particle_array(
            state.get("step_basic_rotations"),
            self.vertex_count,
            4,
            self.base_rotations,
        )
        self.proxy_ptr = _safe_int(state.get("base_pose_proxy_ptr", self.proxy_ptr), self.proxy_ptr)
        self.proxy_name = str(state.get("base_pose_proxy_name", self.proxy_name) or "")
        self.proxy_frame = state.get("base_pose_proxy_frame", self.proxy_frame)

    def mirror_to_state(self, state: dict | None) -> None:
        if not isinstance(state, dict):
            return
        state["base_positions"] = np.ascontiguousarray(self.base_positions, dtype=np.float32)
        state["base_normals"] = np.ascontiguousarray(self.base_normals, dtype=np.float32)
        state["base_rotations"] = np.ascontiguousarray(self.base_rotations, dtype=np.float32)
        state["step_basic_positions"] = np.ascontiguousarray(self.step_basic_positions, dtype=np.float32)
        state["step_basic_rotations"] = np.ascontiguousarray(self.step_basic_rotations, dtype=np.float32)
        state["base_pose_proxy_ptr"] = int(self.proxy_ptr)
        state["base_pose_proxy_name"] = str(self.proxy_name or "")
        state["base_pose_proxy_frame"] = self.proxy_frame

    def update_from_arrays(
        self,
        *,
        base_positions=None,
        base_normals=None,
        base_rotations=None,
        step_basic_positions=None,
        step_basic_rotations=None,
        proxy_ptr=None,
        proxy_name=None,
        proxy_frame=None,
    ) -> None:
        count_source = base_positions if base_positions is not None else self.base_positions
        self.vertex_count = max(0, int(len(count_source)))
        self.base_positions = _safe_particle_array(base_positions, self.vertex_count, 3, self.base_positions)
        self.base_normals = _safe_particle_array(base_normals, self.vertex_count, 3, self.base_normals)
        self.base_rotations = _safe_particle_array(
            base_rotations,
            self.vertex_count,
            4,
            self.base_rotations if len(self.base_rotations) else _identity_quat_array(self.vertex_count),
        )
        self.step_basic_positions = _safe_particle_array(
            step_basic_positions,
            self.vertex_count,
            3,
            self.step_basic_positions if len(self.step_basic_positions) else self.base_positions,
        )
        self.step_basic_rotations = _safe_particle_array(
            step_basic_rotations,
            self.vertex_count,
            4,
            self.step_basic_rotations if len(self.step_basic_rotations) else self.base_rotations,
        )
        if proxy_ptr is not None:
            self.proxy_ptr = _safe_int(proxy_ptr, self.proxy_ptr)
        if proxy_name is not None:
            self.proxy_name = str(proxy_name or "")
        if proxy_frame is not None or self.proxy_ptr == 0:
            self.proxy_frame = proxy_frame

    def debug_snapshot(self) -> dict:
        return {
            "verts": self.vertex_count,
            "base_positions": tuple(self.base_positions.shape),
            "base_normals": tuple(self.base_normals.shape),
            "base_rotations": tuple(self.base_rotations.shape),
            "step_basic_positions": tuple(self.step_basic_positions.shape),
            "step_basic_rotations": tuple(self.step_basic_rotations.shape),
            "proxy_ptr": int(self.proxy_ptr),
            "proxy_name": self.proxy_name,
            "proxy_frame": self.proxy_frame,
        }


@dataclass
class MC2TopologyState:
    vertex_count: int = 0
    mesh_signature_key: object | None = None
    config_key: object | None = None
    object_matrix_world_3x3_key: object | None = None
    bend_kind: str = MC2_BEND_KIND_DISTANCE_APPROX
    collided_by_groups: int = 0
    self_collision_enabled: bool = False
    self_collision_surface_thickness: float = 0.0
    self_collision_mass: float = 0.0
    rest_world_positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.float32))
    rest_world_normals: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.float32))
    attributes: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.uint8))
    depths: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32))
    root_indices: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    parent_indices: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    root_rest_lengths: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32))
    baseline_start: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    baseline_count: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    baseline_data: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    baseline_flags: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.uint8))
    vertex_local_positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.float32))
    vertex_local_rotations: np.ndarray = field(default_factory=lambda: np.zeros((0, 4), dtype=np.float32))
    tether_rest_lengths: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32))
    edges: np.ndarray = field(default_factory=lambda: np.empty((0, 2), dtype=np.int32))
    triangles: np.ndarray = field(default_factory=lambda: np.empty((0, 3), dtype=np.int32))
    edge_i: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    edge_j: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    edge_rest: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32))
    edge_type: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    bend_i: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    bend_j: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    bend_rest: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32))
    bend_type: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    triangle_pairs: np.ndarray = field(default_factory=lambda: np.empty((0, 4), dtype=np.int32))
    dihedral_pairs: np.ndarray = field(default_factory=lambda: np.empty((0, 4), dtype=np.int32))
    dihedral_rest_angles: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32))
    dihedral_signs: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int8))
    volume_pairs: np.ndarray = field(default_factory=lambda: np.empty((0, 4), dtype=np.int32))
    volume_rest: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32))
    bend_distance_i: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    bend_distance_j: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    bend_distance_rest: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32))
    bend_distance_type: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    distance_start: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    distance_count: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    distance_data: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    distance_rest: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32))
    bend_start: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    bend_count: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    bend_data: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    bend_neighbor_rest: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32))
    bend_distance_start: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    bend_distance_count: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    bend_distance_data: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int32))
    bend_distance_neighbor_rest: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32))
    collision_local_radii: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32))
    collision_radii: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32))
    self_collision_inv_masses: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32))

    @staticmethod
    def _key_equal(left, right) -> bool:
        return MC2NativeContext._normalize_key(left) == MC2NativeContext._normalize_key(right)

    def matches_state_header(self, state: dict, vertex_count: int | None = None) -> bool:
        if not isinstance(state, dict):
            return False
        count = int(vertex_count if vertex_count is not None else state.get("vertex_count", self.vertex_count) or 0)
        if self.vertex_count != max(0, count):
            return False
        if not self._key_equal(self.mesh_signature_key, state.get("mesh_signature_key")):
            return False
        if not self._key_equal(self.config_key, state.get("config_key")):
            return False
        if not self._key_equal(self.object_matrix_world_3x3_key, state.get("object_matrix_world_3x3_key")):
            return False
        expected = {
            "attributes": (self.vertex_count,),
            "depths": (self.vertex_count,),
            "distance_start": (self.vertex_count,),
            "distance_count": (self.vertex_count,),
            "bend_distance_start": (self.vertex_count,),
            "bend_distance_count": (self.vertex_count,),
            "collision_local_radii": (self.vertex_count,),
            "collision_radii": (self.vertex_count,),
            "self_collision_inv_masses": (self.vertex_count,),
        }
        for key, shape in expected.items():
            value = state.get(key)
            current = getattr(self, key)
            if not isinstance(value, np.ndarray) or not isinstance(current, np.ndarray):
                return False
            if value.shape != shape or current.shape != shape:
                return False
        counted = {
            "distance_data": self.distance_data,
            "bend_distance_data": self.bend_distance_data,
            "baseline_data": self.baseline_data,
            "edge_i": self.edge_i,
            "bend_distance_i": self.bend_distance_i,
            "dihedral_pairs": self.dihedral_pairs,
            "volume_pairs": self.volume_pairs,
            "edges": self.edges,
        }
        for key, current in counted.items():
            value = state.get(key)
            if not isinstance(value, np.ndarray) or not isinstance(current, np.ndarray):
                return False
            if value.shape != current.shape:
                return False
        return True

    def replace_from_state(self, state: dict, vertex_count: int | None = None) -> None:
        if not isinstance(state, dict):
            return
        count = int(vertex_count if vertex_count is not None else state.get("vertex_count", self.vertex_count) or 0)
        self.vertex_count = max(0, count)
        self.mesh_signature_key = state.get("mesh_signature_key", self.mesh_signature_key)
        self.config_key = state.get("config_key", self.config_key)
        self.object_matrix_world_3x3_key = state.get(
            "object_matrix_world_3x3_key",
            self.object_matrix_world_3x3_key,
        )
        raw_bend_kind = str(state.get("bend_kind", self.bend_kind) or "")
        self.bend_kind = (
            raw_bend_kind
            if raw_bend_kind in {MC2_BEND_KIND_DISTANCE_APPROX, MC2_BEND_KIND_DIRECTION_DIHEDRAL}
            else MC2_BEND_KIND_DISTANCE_APPROX
        )
        self.collided_by_groups = _safe_int(state.get("collided_by_groups", self.collided_by_groups), 0)
        self.self_collision_enabled = _safe_bool(
            state.get("self_collision_enabled", self.self_collision_enabled),
            self.self_collision_enabled,
        )
        self.self_collision_surface_thickness = max(
            0.0,
            _safe_float(
                state.get("self_collision_surface_thickness", self.self_collision_surface_thickness),
                self.self_collision_surface_thickness,
            ),
        )
        self.self_collision_mass = max(
            0.0,
            _safe_float(state.get("self_collision_mass", self.self_collision_mass), self.self_collision_mass),
        )
        self.rest_world_positions = _safe_particle_array(
            state.get("rest_world_positions"),
            self.vertex_count,
            3,
            self.rest_world_positions,
        )
        self.rest_world_normals = _safe_particle_array(
            state.get("rest_world_normals"),
            self.vertex_count,
            3,
            self.rest_world_normals,
        )
        self.attributes = _safe_shaped_array(state.get("attributes"), (self.vertex_count,), np.uint8, self.attributes)
        self.depths = _safe_shaped_array(state.get("depths"), (self.vertex_count,), np.float32, self.depths)
        self.root_indices = _safe_shaped_array(
            state.get("root_indices"),
            (self.vertex_count,),
            np.int32,
            self.root_indices,
        )
        self.parent_indices = _safe_shaped_array(
            state.get("parent_indices"),
            (self.vertex_count,),
            np.int32,
            self.parent_indices,
        )
        self.root_rest_lengths = _safe_shaped_array(
            state.get("root_rest_lengths"),
            (self.vertex_count,),
            np.float32,
            self.root_rest_lengths,
        )
        self.baseline_start = _safe_flat_array(state.get("baseline_start"), np.int32, self.baseline_start)
        self.baseline_count = _safe_flat_array(state.get("baseline_count"), np.int32, self.baseline_count)
        self.baseline_data = _safe_flat_array(state.get("baseline_data"), np.int32, self.baseline_data)
        self.baseline_flags = _safe_flat_array(state.get("baseline_flags"), np.uint8, self.baseline_flags)
        self.vertex_local_positions = _safe_particle_array(
            state.get("vertex_local_positions"),
            self.vertex_count,
            3,
            self.vertex_local_positions,
        )
        self.vertex_local_rotations = _safe_particle_array(
            state.get("vertex_local_rotations"),
            self.vertex_count,
            4,
            self.vertex_local_rotations if len(self.vertex_local_rotations) else _identity_quat_array(self.vertex_count),
        )
        self.tether_rest_lengths = _safe_shaped_array(
            state.get("tether_rest_lengths"),
            (self.vertex_count,),
            np.float32,
            self.tether_rest_lengths,
        )
        self.edges = _safe_tailed_array(state.get("edges"), (2,), np.int32, self.edges)
        self.triangles = _safe_tailed_array(state.get("triangles"), (3,), np.int32, self.triangles)
        self.edge_i = _safe_flat_array(state.get("edge_i"), np.int32, self.edge_i)
        self.edge_j = _safe_flat_array(state.get("edge_j"), np.int32, self.edge_j)
        self.edge_rest = _safe_flat_array(state.get("edge_rest"), np.float32, self.edge_rest)
        self.edge_type = _safe_flat_array(state.get("edge_type"), np.int32, self.edge_type)
        self.bend_i = _safe_flat_array(state.get("bend_i"), np.int32, self.bend_i)
        self.bend_j = _safe_flat_array(state.get("bend_j"), np.int32, self.bend_j)
        self.bend_rest = _safe_flat_array(state.get("bend_rest"), np.float32, self.bend_rest)
        self.bend_type = _safe_flat_array(state.get("bend_type"), np.int32, self.bend_type)
        self.triangle_pairs = _safe_tailed_array(state.get("triangle_pairs"), (4,), np.int32, self.triangle_pairs)
        self.dihedral_pairs = _safe_tailed_array(state.get("dihedral_pairs"), (4,), np.int32, self.dihedral_pairs)
        self.dihedral_rest_angles = _safe_flat_array(
            state.get("dihedral_rest_angles"),
            np.float32,
            self.dihedral_rest_angles,
        )
        self.dihedral_signs = _safe_flat_array(state.get("dihedral_signs"), np.int8, self.dihedral_signs)
        self.volume_pairs = _safe_tailed_array(state.get("volume_pairs"), (4,), np.int32, self.volume_pairs)
        self.volume_rest = _safe_flat_array(state.get("volume_rest"), np.float32, self.volume_rest)
        self.bend_distance_i = _safe_flat_array(state.get("bend_distance_i"), np.int32, self.bend_distance_i)
        self.bend_distance_j = _safe_flat_array(state.get("bend_distance_j"), np.int32, self.bend_distance_j)
        self.bend_distance_rest = _safe_flat_array(
            state.get("bend_distance_rest"),
            np.float32,
            self.bend_distance_rest,
        )
        self.bend_distance_type = _safe_flat_array(
            state.get("bend_distance_type"),
            np.int32,
            self.bend_distance_type,
        )
        self.distance_start = _safe_shaped_array(
            state.get("distance_start"),
            (self.vertex_count,),
            np.int32,
            self.distance_start,
        )
        self.distance_count = _safe_shaped_array(
            state.get("distance_count"),
            (self.vertex_count,),
            np.int32,
            self.distance_count,
        )
        self.distance_data = _safe_flat_array(state.get("distance_data"), np.int32, self.distance_data)
        self.distance_rest = _safe_flat_array(state.get("distance_rest"), np.float32, self.distance_rest)
        self.bend_start = _safe_shaped_array(
            state.get("bend_start"),
            (self.vertex_count,),
            np.int32,
            self.bend_start,
        )
        self.bend_count = _safe_shaped_array(
            state.get("bend_count"),
            (self.vertex_count,),
            np.int32,
            self.bend_count,
        )
        self.bend_data = _safe_flat_array(state.get("bend_data"), np.int32, self.bend_data)
        self.bend_neighbor_rest = _safe_flat_array(
            state.get("bend_neighbor_rest"),
            np.float32,
            self.bend_neighbor_rest,
        )
        self.bend_distance_start = _safe_shaped_array(
            state.get("bend_distance_start"),
            (self.vertex_count,),
            np.int32,
            self.bend_distance_start,
        )
        self.bend_distance_count = _safe_shaped_array(
            state.get("bend_distance_count"),
            (self.vertex_count,),
            np.int32,
            self.bend_distance_count,
        )
        self.bend_distance_data = _safe_flat_array(
            state.get("bend_distance_data"),
            np.int32,
            self.bend_distance_data,
        )
        self.bend_distance_neighbor_rest = _safe_flat_array(
            state.get("bend_distance_neighbor_rest"),
            np.float32,
            self.bend_distance_neighbor_rest,
        )
        self.collision_local_radii = _safe_shaped_array(
            state.get("collision_local_radii"),
            (self.vertex_count,),
            np.float32,
            self.collision_local_radii,
        )
        self.collision_radii = _safe_shaped_array(
            state.get("collision_radii"),
            (self.vertex_count,),
            np.float32,
            self.collision_radii,
        )
        self.self_collision_inv_masses = _safe_shaped_array(
            state.get("self_collision_inv_masses"),
            (self.vertex_count,),
            np.float32,
            self.self_collision_inv_masses,
        )
    def mirror_to_state(self, state: dict | None) -> None:
        if not isinstance(state, dict):
            return
        state["mesh_signature_key"] = self.mesh_signature_key
        state["config_key"] = self.config_key
        state["object_matrix_world_3x3_key"] = self.object_matrix_world_3x3_key
        state["vertex_count"] = int(self.vertex_count)
        state["bend_kind"] = self.bend_kind
        state["collided_by_groups"] = int(self.collided_by_groups)
        state["self_collision_enabled"] = bool(self.self_collision_enabled)
        state["self_collision_surface_thickness"] = float(self.self_collision_surface_thickness)
        state["self_collision_mass"] = float(self.self_collision_mass)
        for key in (
            "rest_world_positions",
            "rest_world_normals",
            "attributes",
            "depths",
            "root_indices",
            "parent_indices",
            "root_rest_lengths",
            "baseline_start",
            "baseline_count",
            "baseline_data",
            "baseline_flags",
            "vertex_local_positions",
            "vertex_local_rotations",
            "tether_rest_lengths",
            "edges",
            "triangles",
            "edge_i",
            "edge_j",
            "edge_rest",
            "edge_type",
            "bend_i",
            "bend_j",
            "bend_rest",
            "bend_type",
            "triangle_pairs",
            "dihedral_pairs",
            "dihedral_rest_angles",
            "dihedral_signs",
            "volume_pairs",
            "volume_rest",
            "bend_distance_i",
            "bend_distance_j",
            "bend_distance_rest",
            "bend_distance_type",
            "distance_start",
            "distance_count",
            "distance_data",
            "distance_rest",
            "bend_start",
            "bend_count",
            "bend_data",
            "bend_neighbor_rest",
            "bend_distance_start",
            "bend_distance_count",
            "bend_distance_data",
            "bend_distance_neighbor_rest",
            "collision_local_radii",
            "collision_radii",
            "self_collision_inv_masses",
        ):
            state[key] = np.ascontiguousarray(getattr(self, key))

    def to_legacy_state(self, base_pose_state: MC2BasePoseState | None = None) -> dict:
        state = {}
        self.mirror_to_state(state)
        if base_pose_state is not None:
            base_pose_state.mirror_to_state(state)
        else:
            state["base_rotations"] = _identity_quat_array(self.vertex_count)
            state["step_basic_positions"] = np.ascontiguousarray(self.rest_world_positions.copy(), dtype=np.float32)
            state["step_basic_rotations"] = _identity_quat_array(self.vertex_count)
        return state

    def to_native_static_arrays(self, base_pose_state: MC2BasePoseState | None = None) -> dict:
        return native_bridge.static_topology_arrays_for_native(self, base_pose_state)

    def debug_snapshot(self) -> dict:
        return {
            "verts": self.vertex_count,
            "mesh_signature_key": self.mesh_signature_key,
            "config_key": self.config_key,
            "rest_world_positions": tuple(self.rest_world_positions.shape),
            "attributes": tuple(self.attributes.shape),
            "edges": tuple(self.edges.shape),
            "triangles": tuple(self.triangles.shape),
            "distance_items": int(len(self.distance_data)),
            "bend_items": int(len(self.bend_distance_data)),
            "dihedral_pairs": tuple(self.dihedral_pairs.shape),
            "volume_pairs": tuple(self.volume_pairs.shape),
            "collision_radii": int(len(self.collision_local_radii)),
            "self_collision_inv_masses": int(len(self.self_collision_inv_masses)),
            "bend_kind": self.bend_kind,
            "collided_by_groups": int(self.collided_by_groups),
            "self_collision_enabled": bool(self.self_collision_enabled),
            "self_collision_surface_thickness": float(self.self_collision_surface_thickness),
            "self_collision_mass": float(self.self_collision_mass),
        }


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
    native_context: MC2NativeContext | object | None = None
    topology_state: MC2TopologyState = field(default_factory=MC2TopologyState)
    particle_state: MC2ParticleState = field(default_factory=MC2ParticleState)
    base_pose_state: MC2BasePoseState = field(default_factory=MC2BasePoseState)
    inertia_state: dict = field(default_factory=dict)
    init_local_gravity_direction: tuple[float, float, float] = (0.0, 0.0, -1.0)
    object_name: str = ""
    frame: int | None = None
    vertex_count: int = 0
    solver_version: int | None = None
    mesh_signature_key: object | None = None
    config_key: object | None = None
    scale_ratio: float = 1.0
    negative_scale_sign: int = 1
    negative_scale_direction: tuple[int, int, int] = (1, 1, 1)
    negative_scale_changed: bool = False
    anchor_active: bool = False
    anchor_name: str = ""
    teleport_state: int = 0
    old_component_position: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    old_component_rotation: np.ndarray = field(default_factory=lambda: np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32))
    now_world_position: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    now_world_rotation: np.ndarray = field(default_factory=lambda: np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32))
    old_world_position: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    old_world_rotation: np.ndarray = field(default_factory=lambda: np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32))
    old_component_matrix: np.ndarray = field(default_factory=lambda: np.eye(4, dtype=np.float32))
    now_component_matrix: np.ndarray = field(default_factory=lambda: np.eye(4, dtype=np.float32))
    shift_pivot_position: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    smoothing_velocity: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    frame_component_shift_vector: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    frame_component_shift_rotation: np.ndarray = field(default_factory=lambda: np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32))
    anchor_position: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    anchor_rotation: np.ndarray = field(default_factory=lambda: np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32))
    old_anchor_position: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    old_anchor_rotation: np.ndarray = field(default_factory=lambda: np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32))
    anchor_component_local_position: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    step_vector: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    step_rotation: np.ndarray = field(default_factory=lambda: np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32))
    inertia_vector: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    inertia_rotation: np.ndarray = field(default_factory=lambda: np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32))
    rotation_axis: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    frame_shift_length: float = 0.0
    step_vector_length: float = 0.0
    inertia_vector_length: float = 0.0
    angular_velocity: float = 0.0
    previous_collider_snapshot: object | None = None

    def replace_legacy_state(self, state: dict) -> None:
        self.legacy_state = state if isinstance(state, dict) else {}
        self.sync_runtime_fields_from_legacy()
        extension_slots = self._extension_slots()
        extension_slots[MC2_RUNTIME_CACHE_SLOT] = self.runtime_cache_slots()
        self.legacy_state["extension_slots"] = extension_slots

    def sync_runtime_fields_from_legacy(self) -> None:
        """把当前仍存放在 legacy dict 里的 CenterData 字段同步到正式容器。"""

        if isinstance(self.legacy_state, dict):
            self.object_name = str(self.legacy_state.get("object_name", self.object_name) or "")
            raw_frame = self.legacy_state.get("frame", self.frame)
            self.frame = None if raw_frame is None else _safe_int(raw_frame, self.frame or 0)
            self.vertex_count = max(0, _safe_int(self.legacy_state.get("vertex_count", self.vertex_count), self.vertex_count))
            raw_solver_version = self.legacy_state.get("solver_version", self.solver_version)
            self.solver_version = (
                None
                if raw_solver_version is None
                else _safe_int(raw_solver_version, self.solver_version or 0)
            )
            self.mesh_signature_key = self.legacy_state.get("mesh_signature_key", self.mesh_signature_key)
            self.config_key = self.legacy_state.get("config_key", self.config_key)
        inertia_state = self.legacy_state.get("inertia_state") if isinstance(self.legacy_state, dict) else None
        self.inertia_state = inertia_state if isinstance(inertia_state, dict) else {}
        if isinstance(self.legacy_state, dict) and "previous_collider_snapshot" in self.legacy_state:
            self.previous_collider_snapshot = self.legacy_state.get("previous_collider_snapshot")
        self._sync_inertia_summary_from_state()
        self.topology_state.replace_from_state(self.legacy_state, self.vertex_count)
        self.base_pose_state.replace_from_state(self.legacy_state, self.vertex_count)
        self.particle_state.replace_from_state(self.legacy_state, self.vertex_count)

    def _sync_inertia_summary_from_state(self) -> None:
        state = self.legacy_state if isinstance(self.legacy_state, dict) else {}
        inertia_state = self.inertia_state if isinstance(self.inertia_state, dict) else {}
        self.scale_ratio = max(
            0.0,
            _safe_float(inertia_state.get("scale_ratio", state.get("scale_ratio", self.scale_ratio)), self.scale_ratio),
        )
        self.negative_scale_sign = _safe_int(
            inertia_state.get("negative_scale_sign", state.get("negative_scale_sign", self.negative_scale_sign)),
            self.negative_scale_sign,
        )
        if self.negative_scale_sign == 0:
            self.negative_scale_sign = 1
        self.negative_scale_direction = _safe_direction3(
            inertia_state.get("negative_scale_direction", state.get("negative_scale_direction")),
            self.negative_scale_direction,
        )
        self.negative_scale_changed = _safe_bool(
            inertia_state.get("negative_scale_changed"),
            self.negative_scale_changed,
        )
        direction = state.get("init_local_gravity_direction")
        if direction is None:
            direction = inertia_state.get("init_local_gravity_direction")
        self.init_local_gravity_direction = _safe_tuple3(
            direction,
            self.init_local_gravity_direction,
        )
        self.anchor_active = _safe_bool(inertia_state.get("anchor_active"), self.anchor_active)
        self.anchor_name = str(inertia_state.get("anchor_name", self.anchor_name) or "")
        self.teleport_state = _safe_int(inertia_state.get("teleport_state", self.teleport_state), self.teleport_state)
        self.old_component_position = _safe_vector3_array(
            inertia_state.get("old_component_position"),
            self.old_component_position,
        )
        self.old_component_rotation = _safe_quat_array(
            inertia_state.get("old_component_rotation"),
            self.old_component_rotation,
        )
        self.now_world_position = _safe_vector3_array(inertia_state.get("now_world_position"), self.now_world_position)
        self.now_world_rotation = _safe_quat_array(inertia_state.get("now_world_rotation"), self.now_world_rotation)
        self.old_world_position = _safe_vector3_array(inertia_state.get("old_world_position"), self.old_world_position)
        self.old_world_rotation = _safe_quat_array(inertia_state.get("old_world_rotation"), self.old_world_rotation)
        self.old_component_matrix = _safe_matrix4_array(
            inertia_state.get("old_component_matrix"),
            self.old_component_matrix,
        )
        self.now_component_matrix = _safe_matrix4_array(
            inertia_state.get("now_component_matrix"),
            self.now_component_matrix,
        )
        self.shift_pivot_position = _safe_vector3_array(
            inertia_state.get("shift_pivot_position"),
            self.shift_pivot_position,
        )
        self.smoothing_velocity = _safe_vector3_array(
            inertia_state.get("smoothing_velocity"),
            self.smoothing_velocity,
        )
        self.frame_component_shift_vector = _safe_vector3_array(
            inertia_state.get("frame_component_shift_vector"),
            self.frame_component_shift_vector,
        )
        self.frame_component_shift_rotation = _safe_quat_array(
            inertia_state.get("frame_component_shift_rotation"),
            self.frame_component_shift_rotation,
        )
        self.anchor_position = _safe_vector3_array(inertia_state.get("anchor_position"), self.anchor_position)
        self.anchor_rotation = _safe_quat_array(inertia_state.get("anchor_rotation"), self.anchor_rotation)
        self.old_anchor_position = _safe_vector3_array(
            inertia_state.get("old_anchor_position"),
            self.old_anchor_position,
        )
        self.old_anchor_rotation = _safe_quat_array(
            inertia_state.get("old_anchor_rotation"),
            self.old_anchor_rotation,
        )
        self.anchor_component_local_position = _safe_vector3_array(
            inertia_state.get("anchor_component_local_position"),
            self.anchor_component_local_position,
        )
        self.step_vector = _safe_vector3_array(inertia_state.get("step_vector"), self.step_vector)
        self.step_rotation = _safe_quat_array(inertia_state.get("step_rotation"), self.step_rotation)
        self.inertia_vector = _safe_vector3_array(inertia_state.get("inertia_vector"), self.inertia_vector)
        self.inertia_rotation = _safe_quat_array(inertia_state.get("inertia_rotation"), self.inertia_rotation)
        self.rotation_axis = _safe_vector3_array(inertia_state.get("rotation_axis"), self.rotation_axis)
        self.frame_shift_length = _safe_vector_length(self.frame_component_shift_vector, self.frame_shift_length)
        self.step_vector_length = _safe_vector_length(self.step_vector, self.step_vector_length)
        self.inertia_vector_length = _safe_vector_length(self.inertia_vector, self.inertia_vector_length)
        self.angular_velocity = _safe_float(
            inertia_state.get("angular_velocity", self.angular_velocity),
            self.angular_velocity,
        )

    def ensure_inertia_state(self, obj: bpy.types.Object | None = None) -> dict:
        """返回 CenterState 权威 inertia 字段，并镜像到 legacy dict。"""

        if not isinstance(self.inertia_state, dict) or not self.inertia_state:
            legacy_value = self.legacy_state.get("inertia_state") if isinstance(self.legacy_state, dict) else None
            if isinstance(legacy_value, dict) and legacy_value:
                self.inertia_state = legacy_value
            elif obj is not None:
                self.inertia_state = inertia.make_runtime_state(obj)
            else:
                self.inertia_state = {}
        self._mirror_inertia_to_legacy()
        return self.inertia_state

    def set_inertia_state(self, value: dict | None) -> dict:
        """更新 CenterState 权威 inertia 字段，并保持 legacy state 兼容。"""

        self.inertia_state = value if isinstance(value, dict) else {}
        self._mirror_inertia_to_legacy()
        return self.inertia_state

    def refresh_inertia_summary(self) -> None:
        self._sync_inertia_summary_from_state()
        self._mirror_center_fields_to_inertia_state()
        if isinstance(self.legacy_state, dict):
            self.legacy_state["scale_ratio"] = self.scale_ratio
            self.legacy_state["negative_scale_sign"] = self.negative_scale_sign
            self.legacy_state["negative_scale_direction"] = self.negative_scale_direction
            self.legacy_state["init_local_gravity_direction"] = self.init_local_gravity_direction

    def sync_particle_state_from_legacy(self) -> MC2ParticleState:
        self.particle_state.replace_from_state(self.legacy_state, self.vertex_count)
        return self.particle_state

    def commit_particle_state(self, legacy_state: dict | None = None, **arrays) -> MC2ParticleState:
        self.particle_state.update_from_arrays(**arrays)
        target = legacy_state if isinstance(legacy_state, dict) else self.legacy_state
        self.particle_state.mirror_to_state(target)
        return self.particle_state

    def sync_base_pose_state_from_legacy(self) -> MC2BasePoseState:
        self.base_pose_state.replace_from_state(self.legacy_state, self.vertex_count)
        return self.base_pose_state

    def commit_base_pose_state(self, legacy_state: dict | None = None, **arrays) -> MC2BasePoseState:
        self.base_pose_state.update_from_arrays(**arrays)
        target = legacy_state if isinstance(legacy_state, dict) else self.legacy_state
        self.base_pose_state.mirror_to_state(target)
        return self.base_pose_state

    def sync_topology_state_from_legacy(self) -> MC2TopologyState:
        if isinstance(self.legacy_state, dict):
            self.vertex_count = max(0, _safe_int(self.legacy_state.get("vertex_count", self.vertex_count), self.vertex_count))
            self.mesh_signature_key = self.legacy_state.get("mesh_signature_key", self.mesh_signature_key)
            self.config_key = self.legacy_state.get("config_key", self.config_key)
        if self.topology_state.matches_state_header(self.legacy_state, self.vertex_count):
            return self.topology_state
        self.topology_state.replace_from_state(self.legacy_state, self.vertex_count)
        return self.topology_state

    def commit_topology_state(self, legacy_state: dict | None = None) -> MC2TopologyState:
        target = legacy_state if isinstance(legacy_state, dict) else self.legacy_state
        if isinstance(target, dict):
            self.vertex_count = max(0, _safe_int(target.get("vertex_count", self.vertex_count), self.vertex_count))
            self.mesh_signature_key = target.get("mesh_signature_key", self.mesh_signature_key)
            self.config_key = target.get("config_key", self.config_key)
        self.topology_state.replace_from_state(target, self.vertex_count)
        self.topology_state.mirror_to_state(target)
        return self.topology_state

    def get_previous_collider_snapshot(self, legacy_state: dict | None = None):
        target = legacy_state if isinstance(legacy_state, dict) else self.legacy_state
        if self.previous_collider_snapshot is None and isinstance(target, dict):
            self.previous_collider_snapshot = target.get("previous_collider_snapshot")
        return self.previous_collider_snapshot

    def set_previous_collider_snapshot(self, legacy_state: dict | None, snapshot) -> None:
        self.previous_collider_snapshot = snapshot
        target = legacy_state if isinstance(legacy_state, dict) else self.legacy_state
        if isinstance(target, dict):
            target["previous_collider_snapshot"] = snapshot

    def _mirror_center_fields_to_inertia_state(self) -> None:
        if not isinstance(self.inertia_state, dict):
            return
        self.inertia_state["init_local_gravity_direction"] = np.ascontiguousarray(
            self.init_local_gravity_direction,
            dtype=np.float32,
        )
        self.inertia_state["scale_ratio"] = float(self.scale_ratio)
        self.inertia_state["negative_scale_sign"] = int(self.negative_scale_sign)
        self.inertia_state["negative_scale_direction"] = np.ascontiguousarray(
            self.negative_scale_direction,
            dtype=np.float32,
        )
        self.inertia_state["negative_scale_changed"] = bool(self.negative_scale_changed)
        self.inertia_state["anchor_active"] = bool(self.anchor_active)
        self.inertia_state["anchor_name"] = self.anchor_name
        self.inertia_state["teleport_state"] = int(self.teleport_state)
        for key in (
            "old_component_position",
            "old_component_rotation",
            "now_world_position",
            "now_world_rotation",
            "old_world_position",
            "old_world_rotation",
            "old_component_matrix",
            "now_component_matrix",
            "shift_pivot_position",
            "smoothing_velocity",
            "frame_component_shift_vector",
            "frame_component_shift_rotation",
            "anchor_position",
            "anchor_rotation",
            "old_anchor_position",
            "old_anchor_rotation",
            "anchor_component_local_position",
            "step_vector",
            "step_rotation",
            "inertia_vector",
            "inertia_rotation",
            "rotation_axis",
        ):
            self.inertia_state[key] = np.ascontiguousarray(getattr(self, key), dtype=np.float32)
        self.inertia_state["angular_velocity"] = float(self.angular_velocity)

    def _mirror_inertia_to_legacy(self) -> None:
        if not isinstance(self.legacy_state, dict):
            return
        self.legacy_state["inertia_state"] = self.inertia_state
        if not isinstance(self.inertia_state, dict):
            return
        self._sync_inertia_summary_from_state()
        self._mirror_center_fields_to_inertia_state()
        self.legacy_state["scale_ratio"] = self.scale_ratio
        self.legacy_state["negative_scale_sign"] = self.negative_scale_sign
        self.legacy_state["negative_scale_direction"] = self.negative_scale_direction
        self.legacy_state["init_local_gravity_direction"] = self.init_local_gravity_direction

    def _extension_slots(self) -> dict:
        extension_slots = self.legacy_state.get("extension_slots")
        if not isinstance(extension_slots, dict):
            extension_slots = {}
        return dict(extension_slots)

    def ensure_native_context(self) -> MC2NativeContext:
        if not isinstance(self.native_context, MC2NativeContext):
            self.native_context = MC2NativeContext()
        return self.native_context

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
            "object": self.object_name or state.get("object_name", ""),
            "frame": self.frame if self.frame is not None else state.get("frame"),
            "verts": self.vertex_count or state.get("vertex_count", 0),
            "solver_version": self.solver_version if self.solver_version is not None else state.get("solver_version"),
            "mesh_signature_key": self.mesh_signature_key,
            "config_key": self.config_key,
            "scale_ratio": self.scale_ratio,
            "negative_scale_sign": self.negative_scale_sign,
            "negative_scale_direction": self.negative_scale_direction,
            "negative_scale_changed": self.negative_scale_changed,
            "init_local_gravity_direction": self.init_local_gravity_direction,
            "anchor_active": self.anchor_active,
            "anchor_name": self.anchor_name,
            "teleport_state": self.teleport_state,
            "old_component_position": _tuple3_for_debug(self.old_component_position),
            "now_world_position": _tuple3_for_debug(self.now_world_position),
            "old_world_position": _tuple3_for_debug(self.old_world_position),
            "shift_pivot_position": _tuple3_for_debug(self.shift_pivot_position),
            "smoothing_velocity": _tuple3_for_debug(self.smoothing_velocity),
            "frame_component_shift_vector": _tuple3_for_debug(self.frame_component_shift_vector),
            "anchor_position": _tuple3_for_debug(self.anchor_position),
            "old_anchor_position": _tuple3_for_debug(self.old_anchor_position),
            "anchor_component_local_position": _tuple3_for_debug(self.anchor_component_local_position),
            "step_vector": _tuple3_for_debug(self.step_vector),
            "inertia_vector": _tuple3_for_debug(self.inertia_vector),
            "rotation_axis": _tuple3_for_debug(self.rotation_axis),
            "frame_shift_length": self.frame_shift_length,
            "step_vector_length": self.step_vector_length,
            "inertia_vector_length": self.inertia_vector_length,
            "angular_velocity": self.angular_velocity,
            "topology_state": self.topology_state.debug_snapshot(),
            "base_pose_state": self.base_pose_state.debug_snapshot(),
            "particle_state": self.particle_state.debug_snapshot(),
            "has_inertia_state": bool(self.inertia_state),
            "curve_cache": len(self.curve_cache),
            "topology_cache": len(self.topology_cache),
            "io_cache": len(self.io_cache),
            "native_cache": len(self.native_cache),
            "has_native_context": self.native_context is not None,
            "native_context": (
                self.native_context.debug_snapshot()
                if isinstance(self.native_context, MC2NativeContext)
                else None
            ),
        }

    def dispose(self) -> None:
        if isinstance(self.native_context, MC2NativeContext):
            self.native_context.dispose()
        self.native_context = None
        self.curve_cache.clear()
        self.topology_cache.clear()
        self.io_cache.clear()
        self.native_cache.clear()
        self.topology_state = MC2TopologyState()
        self.base_pose_state = MC2BasePoseState()
        self.particle_state = MC2ParticleState()


@dataclass
class MC2TeamState:
    """per-node TeamState。

    它不是 MC2 全局 TeamManager，只是 OmniNode cache 中的运行期 schema。
    """

    centers: dict[str, MC2CenterState] = field(default_factory=dict)
    frame_delta_time: float = 0.0
    step_delta_time: float = 0.0
    update_count: int = 0
    skip_count: int = 0
    substep_count: int = 1
    frame_interpolation: float = 1.0
    time_scale: float = 1.0
    skip_writing: bool = False
    culling: bool = False
    sync: bool = True
    scale_suspend: bool = False
    scale_ratio: float = 1.0
    negative_scale_sign: int = 1
    negative_scale_direction: tuple[int, int, int] = (1, 1, 1)
    animation_pose_ratio: float = 0.0
    gravity_dot: float = 1.0
    gravity_ratio: float = 1.0
    velocity_weight: float = 1.0
    distance_weight: float = 1.0
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
        self.frame_delta_time = max(
            0.0,
            _safe_float(legacy_state.get("frame_delta_time", self.frame_delta_time), self.frame_delta_time),
        )
        self.step_delta_time = max(
            0.0,
            _safe_float(legacy_state.get("step_delta_time", self.step_delta_time), self.step_delta_time),
        )
        self.update_count = max(
            0,
            _safe_int(legacy_state.get("update_count", self.update_count), self.update_count),
        )
        self.skip_count = max(
            0,
            _safe_int(legacy_state.get("skip_count", self.skip_count), self.skip_count),
        )
        self.substep_count = max(
            1,
            _safe_int(legacy_state.get("substep_count", self.substep_count), self.substep_count),
        )
        self.frame_interpolation = max(
            0.0,
            min(
                1.0,
                _safe_float(
                    legacy_state.get("frame_interpolation", self.frame_interpolation),
                    self.frame_interpolation,
                ),
            ),
        )
        self.time_scale = _safe_unit_float(legacy_state.get("time_scale", self.time_scale), self.time_scale)
        self.skip_writing = _safe_bool(
            legacy_state.get("skip_writing", legacy_state.get("skipWriting")),
            self.skip_writing,
        )
        self.culling = _safe_bool(legacy_state.get("culling"), self.culling)
        self.sync = _safe_bool(legacy_state.get("sync"), self.sync)
        self.scale_suspend = _safe_bool(
            legacy_state.get("scale_suspend", legacy_state.get("scaleSuspend")),
            self.scale_suspend,
        )
        self.scale_ratio = _safe_float(legacy_state.get("scale_ratio", self.scale_ratio), self.scale_ratio)
        self.negative_scale_sign = _safe_int(
            legacy_state.get("negative_scale_sign", self.negative_scale_sign),
            self.negative_scale_sign,
        )
        if self.negative_scale_sign == 0:
            self.negative_scale_sign = 1
        self.negative_scale_direction = _safe_direction3(
            legacy_state.get("negative_scale_direction"),
            self.negative_scale_direction,
        )
        self.animation_pose_ratio = max(
            0.0,
            min(
                1.0,
                _safe_float(
                    legacy_state.get("animation_pose_ratio", self.animation_pose_ratio),
                    self.animation_pose_ratio,
                ),
            ),
        )
        self.gravity_dot = max(
            0.0,
            min(1.0, _safe_float(legacy_state.get("gravity_dot", self.gravity_dot), self.gravity_dot)),
        )
        self.gravity_ratio = max(
            0.0,
            _safe_float(legacy_state.get("gravity_ratio", self.gravity_ratio), self.gravity_ratio),
        )
        self.velocity_weight = max(
            0.0,
            min(1.0, _safe_float(legacy_state.get("velocity_weight", self.velocity_weight), self.velocity_weight)),
        )
        self.distance_weight = max(
            0.0,
            min(1.0, _safe_float(legacy_state.get("distance_weight", self.distance_weight), self.distance_weight)),
        )
        self.blend_weight = max(
            0.0,
            min(1.0, _safe_float(legacy_state.get("blend_weight", self.blend_weight), self.blend_weight)),
        )

    def apply_frame_context(
        self,
        frame_delta_time: float,
        step_delta_time: float,
        update_count: int,
        skip_count: int,
        frame_interpolation: float,
        legacy_state: dict | None,
        substep_count: int | None = None,
    ) -> None:
        self.frame_delta_time = max(0.0, _safe_float(frame_delta_time, self.frame_delta_time))
        self.step_delta_time = max(0.0, _safe_float(step_delta_time, self.step_delta_time))
        self.update_count = max(0, _safe_int(update_count, self.update_count))
        self.skip_count = max(0, _safe_int(skip_count, self.skip_count))
        if substep_count is not None:
            self.substep_count = max(1, _safe_int(substep_count, self.substep_count))
        self.frame_interpolation = max(0.0, min(1.0, _safe_float(frame_interpolation, self.frame_interpolation)))
        if isinstance(legacy_state, dict):
            legacy_state["frame_delta_time"] = self.frame_delta_time
            legacy_state["step_delta_time"] = self.step_delta_time
            legacy_state["update_count"] = self.update_count
            legacy_state["skip_count"] = self.skip_count
            legacy_state["substep_count"] = self.substep_count
            legacy_state["frame_interpolation"] = self.frame_interpolation

    def apply_lifecycle_context(
        self,
        legacy_state: dict | None,
        *,
        skip_writing=None,
        culling=None,
        sync=None,
        scale_suspend=None,
        time_scale=None,
    ) -> None:
        if skip_writing is not None:
            self.skip_writing = _safe_bool(skip_writing, self.skip_writing)
        if culling is not None:
            self.culling = _safe_bool(culling, self.culling)
        if sync is not None:
            self.sync = _safe_bool(sync, self.sync)
        if scale_suspend is not None:
            self.scale_suspend = _safe_bool(scale_suspend, self.scale_suspend)
        if time_scale is not None:
            self.time_scale = _safe_unit_float(time_scale, self.time_scale)
        if isinstance(legacy_state, dict):
            legacy_state["skip_writing"] = self.skip_writing
            legacy_state["culling"] = self.culling
            legacy_state["sync"] = self.sync
            legacy_state["scale_suspend"] = self.scale_suspend
            legacy_state["time_scale"] = self.time_scale

    def apply_solver_inputs(self, animation_pose_ratio: float, blend_weight: float, legacy_state: dict | None) -> None:
        self.animation_pose_ratio = max(0.0, min(1.0, _safe_float(animation_pose_ratio, self.animation_pose_ratio)))
        self.blend_weight = max(0.0, min(1.0, _safe_float(blend_weight, self.blend_weight)))
        if isinstance(legacy_state, dict):
            legacy_state["animation_pose_ratio"] = self.animation_pose_ratio
            legacy_state["blend_weight"] = self.blend_weight

    def apply_blend_context(
        self,
        velocity_weight: float,
        blend_weight: float,
        legacy_state: dict | None,
    ) -> None:
        self.velocity_weight = max(0.0, min(1.0, _safe_float(velocity_weight, self.velocity_weight)))
        self.blend_weight = max(0.0, min(1.0, _safe_float(blend_weight, self.blend_weight)))
        if isinstance(legacy_state, dict):
            legacy_state["velocity_weight"] = self.velocity_weight
            legacy_state["blend_weight"] = self.blend_weight

    def apply_gravity_context(self, gravity_dot: float, gravity_ratio: float, legacy_state: dict | None) -> None:
        self.gravity_dot = max(0.0, min(1.0, _safe_float(gravity_dot, self.gravity_dot)))
        self.gravity_ratio = max(0.0, _safe_float(gravity_ratio, self.gravity_ratio))
        if isinstance(legacy_state, dict):
            legacy_state["gravity_dot"] = self.gravity_dot
            legacy_state["gravity_ratio"] = self.gravity_ratio

    def apply_scale_context(
        self,
        scale_ratio: float,
        negative_scale_sign: int,
        legacy_state: dict | None,
        negative_scale_direction=None,
    ) -> None:
        self.scale_ratio = max(0.0, _safe_float(scale_ratio, self.scale_ratio))
        self.negative_scale_sign = _safe_int(negative_scale_sign, self.negative_scale_sign)
        if self.negative_scale_sign == 0:
            self.negative_scale_sign = 1
        if negative_scale_direction is not None:
            self.negative_scale_direction = _safe_direction3(
                negative_scale_direction,
                self.negative_scale_direction,
            )
        if isinstance(legacy_state, dict):
            legacy_state["scale_ratio"] = self.scale_ratio
            legacy_state["negative_scale_sign"] = self.negative_scale_sign
            legacy_state["negative_scale_direction"] = self.negative_scale_direction

    def mirror_to_legacy(self, legacy_state: dict | None) -> None:
        if not isinstance(legacy_state, dict):
            return
        legacy_state["frame_delta_time"] = self.frame_delta_time
        legacy_state["step_delta_time"] = self.step_delta_time
        legacy_state["update_count"] = self.update_count
        legacy_state["skip_count"] = self.skip_count
        legacy_state["substep_count"] = self.substep_count
        legacy_state["frame_interpolation"] = self.frame_interpolation
        legacy_state["time_scale"] = self.time_scale
        legacy_state["skip_writing"] = self.skip_writing
        legacy_state["culling"] = self.culling
        legacy_state["sync"] = self.sync
        legacy_state["scale_suspend"] = self.scale_suspend
        legacy_state["animation_pose_ratio"] = self.animation_pose_ratio
        legacy_state["gravity_dot"] = self.gravity_dot
        legacy_state["gravity_ratio"] = self.gravity_ratio
        legacy_state["velocity_weight"] = self.velocity_weight
        legacy_state["distance_weight"] = self.distance_weight
        legacy_state["blend_weight"] = self.blend_weight
        legacy_state["scale_ratio"] = self.scale_ratio
        legacy_state["negative_scale_sign"] = self.negative_scale_sign
        legacy_state["negative_scale_direction"] = self.negative_scale_direction

    def debug_snapshot(self) -> dict:
        return {
            "frame_delta_time": self.frame_delta_time,
            "step_delta_time": self.step_delta_time,
            "update_count": self.update_count,
            "skip_count": self.skip_count,
            "substep_count": self.substep_count,
            "frame_interpolation": self.frame_interpolation,
            "time_scale": self.time_scale,
            "skip_writing": self.skip_writing,
            "culling": self.culling,
            "sync": self.sync,
            "scale_suspend": self.scale_suspend,
            "animation_pose_ratio": self.animation_pose_ratio,
            "gravity_dot": self.gravity_dot,
            "gravity_ratio": self.gravity_ratio,
            "velocity_weight": self.velocity_weight,
            "distance_weight": self.distance_weight,
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


def coerce_center_state(value=None) -> MC2CenterState | None:
    if isinstance(value, MC2CenterState):
        return value
    if isinstance(value, MC2RuntimeOwner):
        return value.center_state
    return None


def coerce_team_state(value=None) -> MC2TeamState | None:
    if isinstance(value, MC2TeamState):
        return value
    if isinstance(value, MC2RuntimeOwner):
        return value.team_state
    return None


def team_state_for_solver(state: dict, team_state: MC2TeamState | MC2RuntimeOwner | None = None) -> MC2TeamState:
    team = coerce_team_state(team_state)
    if team is None:
        team = MC2TeamState()
    team.sync_from_legacy_state(state)
    return team


def mirror_team_state_to_legacy(state: dict, team_state: MC2TeamState | MC2RuntimeOwner | None = None) -> MC2TeamState:
    team = team_state_for_solver(state, team_state)
    team.mirror_to_legacy(state)
    return team


def inertia_state_for_center(
    state: dict,
    center_state: MC2CenterState | MC2RuntimeOwner | None = None,
    obj: bpy.types.Object | None = None,
) -> dict:
    center = coerce_center_state(center_state)
    if center is not None:
        inertia_state = center.ensure_inertia_state(obj)
        if isinstance(state, dict):
            state["inertia_state"] = inertia_state
        return inertia_state

    inertia_state = state.get("inertia_state") if isinstance(state, dict) else None
    if isinstance(inertia_state, dict) and inertia_state:
        return inertia_state
    inertia_state = inertia.make_runtime_state(obj) if obj is not None else {}
    if isinstance(state, dict):
        state["inertia_state"] = inertia_state
    return inertia_state


def set_inertia_state_for_center(
    state: dict,
    inertia_state: dict,
    center_state: MC2CenterState | MC2RuntimeOwner | None = None,
) -> dict:
    center = coerce_center_state(center_state)
    if center is not None:
        inertia_state = center.set_inertia_state(inertia_state)
        if isinstance(state, dict):
            state["inertia_state"] = inertia_state
            state["scale_ratio"] = center.scale_ratio
            state["negative_scale_sign"] = center.negative_scale_sign
            state["negative_scale_direction"] = center.negative_scale_direction
            state["init_local_gravity_direction"] = center.init_local_gravity_direction
        return inertia_state
    if isinstance(state, dict):
        state["inertia_state"] = inertia_state
        if isinstance(inertia_state, dict):
            for key in ("scale_ratio", "negative_scale_sign", "negative_scale_direction"):
                if key in inertia_state:
                    state[key] = inertia_state[key]
    return inertia_state


def commit_inertia_state_for_center(
    state: dict,
    inertia_state: dict,
    obj: bpy.types.Object,
    center_state: MC2CenterState | MC2RuntimeOwner | None = None,
) -> dict:
    committed = inertia.commit_frame(inertia_state, obj)
    return set_inertia_state_for_center(state, committed, center_state)


def particle_state_for_center(
    state: dict,
    center_state: MC2CenterState | MC2RuntimeOwner | None = None,
) -> MC2ParticleState | None:
    center = coerce_center_state(center_state)
    if center is None:
        return None
    if isinstance(state, dict) and state is not center.legacy_state:
        center.legacy_state = state
    return center.sync_particle_state_from_legacy()


def commit_particle_state_for_center(
    state: dict,
    center_state: MC2CenterState | MC2RuntimeOwner | None = None,
    **arrays,
) -> MC2ParticleState | None:
    center = coerce_center_state(center_state)
    if center is None:
        return None
    if isinstance(state, dict) and state is not center.legacy_state:
        center.legacy_state = state
    return center.commit_particle_state(state, **arrays)


def base_pose_state_for_center(
    state: dict,
    center_state: MC2CenterState | MC2RuntimeOwner | None = None,
) -> MC2BasePoseState | None:
    center = coerce_center_state(center_state)
    if center is None:
        return None
    if isinstance(state, dict) and state is not center.legacy_state:
        center.legacy_state = state
    return center.sync_base_pose_state_from_legacy()


def commit_base_pose_state_for_center(
    state: dict,
    center_state: MC2CenterState | MC2RuntimeOwner | None = None,
    **arrays,
) -> MC2BasePoseState | None:
    center = coerce_center_state(center_state)
    if center is None:
        return None
    if isinstance(state, dict) and state is not center.legacy_state:
        center.legacy_state = state
    return center.commit_base_pose_state(state, **arrays)


def topology_state_for_center(
    state: dict,
    center_state: MC2CenterState | MC2RuntimeOwner | None = None,
) -> MC2TopologyState | None:
    center = coerce_center_state(center_state)
    if center is None:
        return None
    if isinstance(state, dict) and state is not center.legacy_state:
        center.legacy_state = state
    return center.sync_topology_state_from_legacy()


def commit_topology_state_for_center(
    state: dict,
    center_state: MC2CenterState | MC2RuntimeOwner | None = None,
) -> MC2TopologyState | None:
    center = coerce_center_state(center_state)
    if center is None:
        return None
    if isinstance(state, dict) and state is not center.legacy_state:
        center.legacy_state = state
    return center.commit_topology_state(state)


def base_pose_proxy_active(
    state: dict,
    base_pose_state: MC2BasePoseState | MC2RuntimeOwner | None = None,
) -> bool:
    if isinstance(base_pose_state, MC2RuntimeOwner):
        base_pose_state = base_pose_state.center_state.base_pose_state
    if isinstance(base_pose_state, MC2BasePoseState):
        return int(base_pose_state.proxy_ptr or 0) != 0
    return int(state.get("base_pose_proxy_ptr", 0) or 0) != 0


def base_pose_proxy_metadata(
    state: dict,
    base_pose_state: MC2BasePoseState | MC2RuntimeOwner | None = None,
) -> tuple[int, str, int | None]:
    if isinstance(base_pose_state, MC2RuntimeOwner):
        base_pose_state = base_pose_state.center_state.base_pose_state
    if isinstance(base_pose_state, MC2BasePoseState):
        return (
            int(base_pose_state.proxy_ptr or 0),
            str(base_pose_state.proxy_name or ""),
            base_pose_state.proxy_frame,
        )
    return (
        int(state.get("base_pose_proxy_ptr", 0) or 0),
        str(state.get("base_pose_proxy_name", "") or ""),
        state.get("base_pose_proxy_frame"),
    )


def previous_collider_snapshot_for_center(
    state: dict,
    center_state: MC2CenterState | MC2RuntimeOwner | None = None,
):
    center = coerce_center_state(center_state)
    if center is None:
        return state.get("previous_collider_snapshot") if isinstance(state, dict) else None
    if isinstance(state, dict) and state is not center.legacy_state:
        center.legacy_state = state
    return center.get_previous_collider_snapshot(state)


def set_previous_collider_snapshot_for_center(
    state: dict,
    snapshot,
    center_state: MC2CenterState | MC2RuntimeOwner | None = None,
) -> None:
    center = coerce_center_state(center_state)
    if center is None:
        if isinstance(state, dict):
            state["previous_collider_snapshot"] = snapshot
        return
    if isinstance(state, dict) and state is not center.legacy_state:
        center.legacy_state = state
    center.set_previous_collider_snapshot(state, snapshot)


def _extension_slots(state: dict) -> dict:
    extension_slots = state.get("extension_slots")
    if not isinstance(extension_slots, dict):
        extension_slots = {}
        state["extension_slots"] = extension_slots
    return extension_slots


def runtime_cache_slots(state: dict) -> dict:
    """返回当前 center 的 runtime cache namespace。"""
    extension_slots = _extension_slots(state)
    runtime_slots = extension_slots.get(MC2_RUNTIME_CACHE_SLOT)
    if not isinstance(runtime_slots, dict):
        runtime_slots = {}
        extension_slots[MC2_RUNTIME_CACHE_SLOT] = runtime_slots
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


def ensure_native_context_for_center(
    state: dict,
    center_state: MC2CenterState | MC2RuntimeOwner | None = None,
) -> MC2NativeContext:
    center = coerce_center_state(center_state)
    if center is not None:
        context = center.ensure_native_context()
        if isinstance(state, dict):
            set_native_context(state, context)
        return context
    context = native_context(state)
    if not isinstance(context, MC2NativeContext):
        context = MC2NativeContext()
        set_native_context(state, context)
    return context


def _native_param_slot_key(name: str, slot: dict) -> tuple:
    samples = slot.get("samples")
    if samples is None:
        sample_key = None
    else:
        array = np.ascontiguousarray(samples, dtype=np.float32).reshape(-1)
        sample_key = (str(array.dtype), tuple(array.shape), bytes(array.tobytes()))
    return (
        str(name),
        slot.get("cache_key"),
        slot.get("mode"),
        slot.get("value"),
        slot.get("base_value"),
        slot.get("minimum"),
        slot.get("maximum"),
        int(slot.get("sample_count", 0) or 0),
        sample_key,
    )


def _native_param_array_key(name: str, value) -> tuple:
    array = np.ascontiguousarray(value, dtype=np.float32).reshape(-1)
    return (str(name), str(array.dtype), tuple(array.shape), bytes(array.tobytes()))


def _native_param_arrays_key(arrays: dict) -> tuple:
    if not isinstance(arrays, dict):
        return ()
    return tuple(
        _native_param_array_key(name, arrays[name])
        for name in sorted(arrays.keys())
    )


def update_native_context_keys(
    state: dict,
    runtime=None,
    center_state: MC2CenterState | MC2RuntimeOwner | None = None,
    topology_state: MC2TopologyState | None = None,
) -> MC2NativeContext:
    context = ensure_native_context_for_center(state, center_state)
    topology_ref = topology_state if topology_state is not None else topology_state_for_center(state, center_state)
    context.update_static_keys(topology_ref)
    param_key = None
    param_slots = None
    if runtime is not None:
        try:
            param_slots = runtime.param_slots()
            param_key = tuple(
                _native_param_slot_key(name, slot)
                for name, slot in sorted(param_slots.items())
                if isinstance(slot, dict)
            )
        except Exception:
            param_key = None
            param_slots = None
    context.update_param_key(param_key, param_slots)
    return context


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


def calc_self_collision_inverse_masses(
    attributes: np.ndarray,
    depths: np.ndarray,
    friction: np.ndarray | None = None,
    cloth_mass: float = 0.0,
) -> np.ndarray:
    _ = depths
    count = len(attributes)
    fr = np.zeros(count, dtype=np.float32) if friction is None else np.ascontiguousarray(friction, dtype=np.float32)
    fixed = (np.ascontiguousarray(attributes, dtype=np.uint8) & MC2_ATTR_MOVE) == 0
    mass = np.where(
        fixed,
        MC2SystemConstants.SELF_COLLISION_FIXED_MASS,
        1.0 + fr * MC2SystemConstants.SELF_COLLISION_FRICTION_MASS + float(cloth_mass) * MC2SystemConstants.SELF_COLLISION_CLOTH_MASS,
    )
    inv = np.ascontiguousarray(1.0 / np.maximum(mass, MC2SystemConstants.EPSILON), dtype=np.float32)
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
    mesh_collision_props = mesh_build.mesh_collision_props(obj)
    self_collision_enabled = bool(mesh_collision_props is not None and getattr(mesh_collision_props, "self_collision_enabled", False))
    self_collision_surface_thickness = (
        max(float(getattr(mesh_collision_props, "self_collision_surface_thickness", 0.0)), 0.0)
        if mesh_collision_props is not None
        else 0.0
    )
    self_collision_mass = (
        max(float(getattr(mesh_collision_props, "mass", 0.0)), 0.0)
        if mesh_collision_props is not None
        else 0.0
    )
    self_collision_inv_masses = calc_self_collision_inverse_masses(
        attributes,
        depths,
        friction,
        self_collision_mass,
    )
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
        "update_count": 0,
        "skip_count": 0,
        "substep_count": 1,
        "frame_interpolation": 1.0,
        "time_scale": 1.0,
        "skip_writing": False,
        "culling": False,
        "sync": True,
        "scale_suspend": False,
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
        "self_collision_inv_masses": self_collision_inv_masses,
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
        "self_collision_enabled": bool(self_collision_enabled),
        "self_collision_surface_thickness": float(self_collision_surface_thickness),
        "self_collision_mass": float(self_collision_mass),
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


def sync_state_to_object_transform(
    state: dict,
    obj: bpy.types.Object,
    center_state: MC2CenterState | MC2RuntimeOwner | None = None,
) -> dict:
    matrix_key = math_utils.matrix_world_key(obj)
    matrix_3x3_key = math_utils.matrix_world_3x3_key(obj)
    if (
        state.get("object_matrix_world_key") == matrix_key
        and state.get("object_matrix_world_3x3_key") == matrix_3x3_key
    ):
        topology_state_for_center(state, center_state)
        base_pose_state_for_center(state, center_state)
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
        mesh_collision_props = mesh_build.mesh_collision_props(obj)
        next_state["self_collision_enabled"] = bool(
            mesh_collision_props is not None and getattr(mesh_collision_props, "self_collision_enabled", False)
        )
        next_state["self_collision_surface_thickness"] = (
            max(float(getattr(mesh_collision_props, "self_collision_surface_thickness", 0.0)), 0.0)
            if mesh_collision_props is not None
            else 0.0
        )
        next_state["self_collision_mass"] = (
            max(float(getattr(mesh_collision_props, "mass", 0.0)), 0.0)
            if mesh_collision_props is not None
            else 0.0
        )
        next_state["inv_masses"] = calc_inverse_masses(
            next_state["attributes"],
            next_state["depths"],
            next_state["friction"],
        )
        next_state["self_collision_inv_masses"] = calc_self_collision_inverse_masses(
            next_state["attributes"],
            next_state["depths"],
            next_state["friction"],
            next_state.get("self_collision_mass", 0.0),
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

    commit_base_pose_state_for_center(
        next_state,
        center_state,
        base_positions=next_state["base_positions"],
        base_normals=next_state["base_normals"],
        base_rotations=next_state["base_rotations"],
        step_basic_positions=next_state["step_basic_positions"],
        step_basic_rotations=next_state["step_basic_rotations"],
        proxy_ptr=0,
        proxy_name="",
        proxy_frame=None,
    )
    commit_topology_state_for_center(next_state, center_state)
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
    center_state: MC2CenterState | MC2RuntimeOwner | None = None,
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
    commit_base_pose_state_for_center(
        next_state,
        center_state,
        base_positions=next_state["base_positions"],
        base_normals=next_state["base_normals"],
        base_rotations=next_state["base_rotations"],
        step_basic_positions=next_state["step_basic_positions"],
        step_basic_rotations=next_state["step_basic_rotations"],
        proxy_ptr=proxy_ptr,
        proxy_name=proxy_name,
        proxy_frame=frame,
    )
    return next_state


def sync_state_to_base_pose_proxy(
    state: dict,
    obj: bpy.types.Object,
    base_pose_proxy: bpy.types.Object | None,
    current_frame: int,
    timing: dict | None = None,
    cache: dict | None = None,
    center_state: MC2CenterState | MC2RuntimeOwner | None = None,
) -> dict:
    if base_pose_proxy is None:
        if int(state.get("base_pose_proxy_ptr", 0) or 0) == 0:
            base_pose_state_for_center(state, center_state)
            return state
        return _apply_base_pose_arrays(
            state,
            state["rest_world_positions"],
            state["rest_world_normals"],
            0,
            "",
            None,
            center_state,
        )

    vertex_count = int(state.get("vertex_count", len(obj.data.vertices)))
    if len(base_pose_proxy.data.vertices) != vertex_count:
        raise ValueError("MC2 BasePose只读对象顶点数必须与当前物理对象一致")

    proxy_ptr = int(base_pose_proxy.as_pointer())
    if (
        int(state.get("base_pose_proxy_ptr", 0) or 0) == proxy_ptr
        and state.get("base_pose_proxy_frame") == current_frame
    ):
        base_pose_state_for_center(state, center_state)
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
        center_state,
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
    config_key: tuple | None = None,
) -> bool:
    try:
        object_ptr = int(obj.as_pointer())
        mesh_ptr = int(obj.data.as_pointer())
        vertex_count = len(obj.data.vertices)
    except ReferenceError:
        return False
    except Exception:
        return False

    owner = state if isinstance(state, MC2RuntimeOwner) else None
    if owner is None:
        return False
    state = owner.state
    if not isinstance(state, dict):
        return False

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
    if owner is not None:
        topology_state = owner.center_state.topology_state
        topology_shapes = {
            "rest_world_positions": (vertex_count, 3),
            "rest_world_normals": (vertex_count, 3),
            "attributes": (vertex_count,),
            "depths": (vertex_count,),
            "root_indices": (vertex_count,),
            "parent_indices": (vertex_count,),
            "root_rest_lengths": (vertex_count,),
            "vertex_local_positions": (vertex_count, 3),
            "vertex_local_rotations": (vertex_count, 4),
            "tether_rest_lengths": (vertex_count,),
            "distance_start": (vertex_count,),
            "distance_count": (vertex_count,),
            "bend_start": (vertex_count,),
            "bend_count": (vertex_count,),
            "bend_distance_start": (vertex_count,),
            "bend_distance_count": (vertex_count,),
            "collision_local_radii": (vertex_count,),
            "collision_radii": (vertex_count,),
        }
        for key, shape in topology_shapes.items():
            value = getattr(topology_state, key)
            if not isinstance(value, np.ndarray) or value.shape != shape:
                return False
        base_pose_state = owner.center_state.base_pose_state
        base_pose_shapes = {
            "base_positions": (vertex_count, 3),
            "base_normals": (vertex_count, 3),
            "base_rotations": (vertex_count, 4),
            "step_basic_positions": (vertex_count, 3),
            "step_basic_rotations": (vertex_count, 4),
        }
        for key, shape in base_pose_shapes.items():
            value = getattr(base_pose_state, key)
            if not isinstance(value, np.ndarray) or value.shape != shape:
                return False
        particle_state = owner.center_state.particle_state
        particle_shapes = {
            "next_positions": (vertex_count, 3),
            "old_positions": (vertex_count, 3),
            "velocity_positions": (vertex_count, 3),
            "display_positions": (vertex_count, 3),
            "velocity": (vertex_count, 3),
            "real_velocity": (vertex_count, 3),
            "friction": (vertex_count,),
            "static_friction": (vertex_count,),
            "collision_normals": (vertex_count, 3),
            "inv_masses": (vertex_count,),
        }
        for key, shape in particle_shapes.items():
            value = getattr(particle_state, key)
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
        and state.get("object_ptr") == object_ptr
        and state.get("mesh_ptr") == mesh_ptr
        and state.get("output_key") == output_key
        and state.get("mesh_light_key") == mesh_light_key
        and (config_key is None or state.get("config_key") == config_key)
        and state.get("vertex_count") == vertex_count
    )
