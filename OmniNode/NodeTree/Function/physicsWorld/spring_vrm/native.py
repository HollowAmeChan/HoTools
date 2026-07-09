"""VRM SpringBone 的 native C++ 调用包装。

设计模型（双调用 native context）
──────────────────────────────────────────────────────────────
每条链对应一个 SpringVRMNativeContext 实例，生命周期如下：

  topology/restart 变化时：
    ctx.rebuild(spec, records)
      → 捕获静态数组（init_axis / init_rotation / topology）
      → is_context_api_available() 为 True 时调用 spring_vrm_create_context()
        把静态数组上传到 C++ 侧，拿到 self._handle

  每帧：
    ctx.fill_dynamic(armature, chain_state, records)
      → 从当前 pose 填充动态数组（head/tail/matrix）

    ctx.step_and_publish(module, world, armature, chain, chain_state, dt, substeps)
      → self._handle 有效：走 _step_via_context_api
        （spring_vrm_update_dynamic → [reset_state] → spring_vrm_step →
         spring_vrm_read_results → publish）
      → 否则回退 _step_via_legacy_bridge（旧 35 参数单次调用）

  dispose 时：
    ctx.dispose()
      → free_spring_vrm_context(self._handle)（若有）+ 清空 numpy/bpy 引用

调用路径由 native 模块是否导出 dual-call symbol 决定：
  is_available()            → 有 solve_spring_bone_vrm_cpp（35 参数 bridge，最低要求）
  is_context_api_available() → 有 spring_vrm_create_context（新 dual-call API）

Python 侧 dual-call 路径已完整实现并在 handle 有效时激活；当前发布的 native
产物是否编译进 dual-call symbol 决定实际走哪条路。_step_via_legacy_bridge 作为
未编译 dual-call 时的兼容回退保留，等新 ABI 成为唯一发布目标后可删除。
"""

from __future__ import annotations

import importlib
import time

import mathutils
import numpy as np

from ..names import (
    COLLIDER_TYPE_BOX,
    COLLIDER_TYPE_CAPSULE,
    COLLIDER_TYPE_PLANE,
    COLLIDER_TYPE_SPHERE,
)
from ..utils.geometry import (
    clamp_int,
    matrix_scale_radius,
    numpy_vec3,
    signed_third_axis_length,
    vec3_length,
)
from ..utils.values import matrix16
from ..utils.writeback_pose import matrix_basis_from_pose_matrix
from .bone_collision import resolve_bone_collision_fields, resolve_bone_pin
from .results import publish_spring_vrm_pose_result


_NATIVE_MODULE = None


def native_module():
    global _NATIVE_MODULE
    if _NATIVE_MODULE is None:
        _NATIVE_MODULE = importlib.import_module("hotools_native")
    return _NATIVE_MODULE


def is_available() -> bool:
    try:
        module = native_module()
    except Exception:
        return False
    return hasattr(module, "solve_spring_bone_vrm_cpp")


def is_context_api_available() -> bool:
    """新 dual-call API 是否已编译进当前 native 模块。"""
    try:
        module = native_module()
    except Exception:
        return False
    return hasattr(module, "spring_vrm_create_context")


# ─────────────────────────────────────────────────────────────────────────────
# SpringVRMNativeContext — 单条链的 native context holder
# ─────────────────────────────────────────────────────────────────────────────

class SpringVRMNativeContext:
    """
    单条 VRM SpringBone 链的 native context。

    持有：
      _static  — topology/restart 变化时从 pose 一次性捕获的静态数组
      _dynamic — 每帧预分配并重填的动态数组
      _result  — C++ 原地写入的结果 basis buffer（直接给 foreach_set 消费）
      _handle  — 未来 C++ context capsule（当前为 None，新 API 就绪后填充）

    update_policy（参考 PHYSICS_SIMULATION_PIPELINE_CONTRACT.md）：
      restart_only  → _static 数组
      every_frame   → _dynamic 数组
    """

    SCHEMA = "spring_vrm_native_context_v2"

    def __init__(self, root_bone: str) -> None:
        self.root_bone = root_bone
        self._topology_signature: tuple | None = None
        self._bone_count: int = 0
        self._step_count: int = 0
        self._last_frame: int = -1
        self._last_collider_count: int = 0

        self._static: dict[str, np.ndarray] | None = None
        self._dynamic: dict[str, np.ndarray] | None = None
        self._result: np.ndarray | None = None       # (N*16,) float32，target_matrices
        self._result_quat: np.ndarray | None = None  # (N*4,)  float32，target_quaternions

        # records 在 rebuild 时存储，bridge 路径读取
        self._records: list[dict] = []

        # rebuild 时存储的 spec 级信息（bridge 路径用）
        # TODO: 新 C++ API 落地后 bridge 整段删除，届时连同此字段一起清理。
        #       当前 bridge 不再读取 self._armature（改由调用方传入），此字段已是死字段。
        self._armature = None
        self._slot_id: str = ""
        self._armature_ptr: int = 0
        self._armature_data_ptr: int = 0

        # TODO: 新 C++ API 就绪后由 create_spring_vrm_context() 填充
        self._handle = None

    # ── 生命周期 ──────────────────────────────────────────────────────────────

    def needs_rebuild(self, records: list[dict]) -> bool:
        """topology 签名变化或首次使用时需要 rebuild。"""
        return (
            self._topology_signature is None
            or self._topology_signature != _records_signature(records)
        )

    def rebuild(self, spec, records: list[dict]) -> None:
        """
        topology dirty / restart 时调用。
        捕获静态数组，存储 spec 级引用，并在新 API 可用时创建 C++ context。

        注意：rebuild 时从当前 armature pose 捕获 init_rotations / init_scales。
        这是有意设计——init 值是解算起始状态，重建时重新采样，而不是从 bind pose 固定。
        """
        self._dispose_handle()

        n = len(records)
        self._topology_signature = _records_signature(records)
        self._bone_count = n
        self._records = records

        # spec 级信息（bridge 路径和 publish 共用）
        self._armature = spec.armature
        self._slot_id = str(getattr(spec, "slot_id", "") or "")
        self._armature_ptr = int(getattr(spec, "armature_ptr", 0) or 0)
        self._armature_data_ptr = int(getattr(spec, "armature_data_ptr", 0) or 0)

        self._static = _alloc_static(n)
        _fill_static(self._static, records)

        self._dynamic = _alloc_dynamic(n)
        self._result = np.zeros(n * 16, dtype=np.float32)
        self._result_quat = np.zeros(n * 4, dtype=np.float32)

        # 创建 C++ context（新 dual-call API）
        if is_context_api_available():
            try:
                s = self._static
                self._handle = native_module().spring_vrm_create_context(
                    1,  # schema
                    n,
                    np.ascontiguousarray(s["lengths"],          dtype=np.float32),
                    np.ascontiguousarray(s["init_axis_local"],  dtype=np.float32).ravel(),
                    np.ascontiguousarray(s["init_axis_parent"], dtype=np.float32).ravel(),
                    np.ascontiguousarray(s["init_rotations"],   dtype=np.float32).ravel(),
                    np.ascontiguousarray(s["init_scales"],      dtype=np.float32).ravel(),
                    np.ascontiguousarray(s["parent_indices"],   dtype=np.int32),
                    np.ascontiguousarray(s["pinned"],           dtype=np.uint8),
                    np.ascontiguousarray(s["use_connect"],      dtype=np.uint8),
                )
            except Exception:
                self._handle = None

    def fill_dynamic(self, armature, chain_state: dict, records: list[dict]) -> None:
        """每帧从当前 pose 采样动态数组（预分配 buffer，复用不重新分配）。"""
        if self._dynamic is None:
            return
        _fill_dynamic(self._dynamic, armature, chain_state, records)

    def step_and_publish(
        self,
        module,
        world,
        armature,
        chain,
        chain_state: dict,
        dt: float,
        substeps: int,
        restart: bool = False,
    ) -> int:
        """
        推进解算，把结果发布到 world.result_streams，返回写回骨骼数。

        armature 由调用方传入（来自已经过 _get_valid_armature 验证的引用），
        而不是用 self._armature，避免 _get_valid_armature 刷新引用但未 rebuild 时
        bridge 内部使用了过期 bpy 指针。

        当 self._handle 有效时走新 dual-call 路径；
        否则退回旧 35 参数 bridge（_step_via_legacy_bridge）。
        """
        if self._static is None or self._dynamic is None or self._result is None:
            return 0
        if self._handle is not None:
            return self._step_via_context_api(module, world, armature, chain, chain_state, dt, substeps, restart)
        return self._step_via_legacy_bridge(module, world, armature, chain, chain_state, dt, substeps, restart)

    def dispose(self) -> None:
        """释放 C++ handle 和 numpy buffer，清空所有 bpy 对象引用。"""
        self._dispose_handle()
        self._static = None
        self._dynamic = None
        self._result = None
        self._result_quat = None
        self._topology_signature = None
        # 清空 bpy 引用，避免 Blender 对象被 GC 延迟释放
        self._records = []
        self._armature = None

    # ── 内部工具 ──────────────────────────────────────────────────────────────

    def _dispose_handle(self) -> None:
        if self._handle is not None:
            try:
                native_module().free_spring_vrm_context(self._handle)
            except Exception:
                pass
            self._handle = None

    def _step_via_context_api(
        self,
        module,
        world,
        armature,
        chain,
        chain_state: dict,
        dt: float,
        substeps: int,
        restart: bool = False,
    ) -> int:
        """新 dual-call 路径：update_dynamic → (reset_state) → step → read_results → publish。
        static 数组已在 rebuild 时上传到 C++ handle，这里只需每帧 dynamic 数据。
        restart=True 时在 update_dynamic 之后、step 之前调用 reset_state，
        使 C++ 侧的 current/prev tails 从当前 pose tail 重新开始。
        """
        d = self._dynamic

        (
            collider_types, collider_groups, collider_centers,
            collider_segment_a, collider_segment_b, collider_radii,
        ) = _collision_arrays_from_world(world, armature, chain)
        hit_radii, collided_by_groups = _bone_collision_profiles(armature, self._records)

        arm_world     = np.ascontiguousarray(matrix16(armature.matrix_world),            dtype=np.float32)
        arm_world_inv = np.ascontiguousarray(matrix16(armature.matrix_world.inverted()),  dtype=np.float32)
        root_quat     = np.ascontiguousarray([0., 0., 0., 1.],                            dtype=np.float32)
        root_tail     = np.zeros(3, dtype=np.float32)
        gravity_dir   = np.ascontiguousarray(chain.gravity_dir,                           dtype=np.float32)

        self._last_collider_count = len(collider_types)

        module.spring_vrm_update_dynamic(
            self._handle,
            np.ascontiguousarray(d["current_heads"],            dtype=np.float32).ravel(),
            np.ascontiguousarray(d["current_pose_matrices"],    dtype=np.float32).ravel(),
            np.ascontiguousarray(d["current_pose_quaternions"], dtype=np.float32).ravel(),
            np.ascontiguousarray(d["parent_pose_quaternions"],  dtype=np.float32).ravel(),
            np.ascontiguousarray(d["current_pose_tails"],       dtype=np.float32).ravel(),
            arm_world,
            arm_world_inv,
            root_quat,
            root_tail,
            gravity_dir,
            np.ascontiguousarray(hit_radii,           dtype=np.float32),
            np.ascontiguousarray(collided_by_groups,  dtype=np.int32),
            np.ascontiguousarray(collider_types,      dtype=np.int32),
            np.ascontiguousarray(collider_groups,     dtype=np.int32),
            np.ascontiguousarray(collider_centers,    dtype=np.float32).ravel(),
            np.ascontiguousarray(collider_segment_a,  dtype=np.float32).ravel(),
            np.ascontiguousarray(collider_segment_b,  dtype=np.float32).ravel(),
            np.ascontiguousarray(collider_radii,      dtype=np.float32),
        )
        # restart 时（跳帧/重置）：pose tails 已上传，在 step 前把 current/prev tails 重置到当前 pose 位置
        if restart:
            module.spring_vrm_reset_state(self._handle)
            self._reset_dynamic_tails_to_pose()
            frame = int(getattr(world.frame_context, "frame", 0) or 0)
            self._last_frame = frame
            return self._publish_current_pose(world, chain, chain_state, frame)
        module.spring_vrm_step(
            self._handle,
            float(dt),
            max(1, int(substeps)),
            float(chain.stiffness_force),
            float(chain.drag_force),
            float(chain.gravity_power),
        )

        # result_quat 是中间量，只用于 publish；target_matrices 写入预分配 self._result
        if self._result_quat is None or len(self._result_quat) != self._bone_count * 4:
            self._result_quat = np.zeros(self._bone_count * 4, dtype=np.float32)
        module.spring_vrm_read_results(self._handle, self._result, self._result_quat)

        frame = int(getattr(world.frame_context, "frame", 0) or 0)
        self._step_count += 1
        self._last_frame = frame

        return self._publish_from_result_buffers(world, chain, chain_state, frame)

    def _reset_dynamic_tails_to_pose(self) -> None:
        d = self._dynamic
        if d is None:
            return
        np.copyto(d["current_tails"], d["current_pose_tails"])
        np.copyto(d["prev_tails"], d["current_pose_tails"])
        np.copyto(d["target_matrices"], d["current_pose_matrices"])
        np.copyto(d["target_quaternions"], d["current_pose_quaternions"])

    def _publish_current_pose(
        self, world, chain, chain_state: dict, frame: int
    ) -> int:
        target_pose_matrices: dict[str, mathutils.Matrix] = {}
        published = 0
        tails = chain_state.setdefault("tails", {})
        last_results = []

        d = self._dynamic
        if d is None:
            return 0

        for index, record in enumerate(self._records):
            bone_name = record["bone_name"]
            target_matrix = _matrix_from_row(d["current_pose_matrices"][index])
            target_pose_matrices[bone_name] = target_matrix
            basis_matrix = matrix_basis_from_pose_matrix(
                record["pose_bone"], target_matrix, target_pose_matrices
            )
            current_tail = _tuple3(d["current_pose_tails"][index])
            tails[bone_name] = {
                "current_tail": current_tail,
                "prev_tail":    current_tail,
            }
            result = publish_spring_vrm_pose_result(
                world,
                slot_id=self._slot_id,
                armature_ptr=self._armature_ptr,
                armature_data_ptr=self._armature_data_ptr,
                frame=frame,
                generation=world.generation,
                bone_name=bone_name,
                pose_index=int(record["pose_index"]),
                matrix_basis=basis_matrix,
                target_pose_matrix=target_matrix,
                current_tail=current_tail,
                chain_root=chain.root_bone,
                backend="cpp",
            )
            if result is not None:
                last_results.append(result)
                published += 1

        chain_state["last_results"] = last_results
        return published

    def _publish_from_result_buffers(
        self, world, chain, chain_state: dict, frame: int
    ) -> int:
        """从 self._result (matrices) 和 self._result_quat 发布结果。"""
        target_pose_matrices: dict[str, mathutils.Matrix] = {}
        published = 0
        tails = chain_state.setdefault("tails", {})
        last_results = []

        d = self._dynamic
        mat_arr = self._result.reshape((self._bone_count, 16))

        for index, record in enumerate(self._records):
            bone_name = record["bone_name"]
            target_matrix = _matrix_from_row(mat_arr[index])
            target_pose_matrices[bone_name] = target_matrix
            basis_matrix = matrix_basis_from_pose_matrix(
                record["pose_bone"], target_matrix, target_pose_matrices
            )
            tails[bone_name] = {
                "current_tail": _tuple3(d["current_tails"][index]),
                "prev_tail":    _tuple3(d["prev_tails"][index]),
            }
            result = publish_spring_vrm_pose_result(
                world,
                slot_id=self._slot_id,
                armature_ptr=self._armature_ptr,
                armature_data_ptr=self._armature_data_ptr,
                frame=frame,
                generation=world.generation,
                bone_name=bone_name,
                pose_index=int(record["pose_index"]),
                matrix_basis=basis_matrix,
                target_pose_matrix=target_matrix,
                current_tail=_tuple3(d["current_tails"][index]),
                chain_root=chain.root_bone,
                backend="cpp",
            )
            if result is not None:
                last_results.append(result)
                published += 1

        chain_state["last_results"] = last_results
        return published

    def debug_dict(self) -> dict:
        arrays = {}
        for source in (self._static, self._dynamic):
            if isinstance(source, dict):
                arrays.update(source)
        return {
            "schema": self.SCHEMA,
            "root_bone": self.root_bone,
            "bone_count": self._bone_count,
            "step_count": self._step_count,
            "last_frame": self._last_frame,
            "cpp_handle": self._handle is not None,
            "static_ready": self._static is not None,
            "buffer_shapes": {
                k: list(v.shape)
                for k, v in arrays.items()
                if isinstance(v, np.ndarray)
            },
            "last_collider_count": self._last_collider_count,
        }

    # ── TRANSITIONAL 桥接（35 参数旧 ABI，新 API 就绪后整段删除）────────────

    def _step_via_legacy_bridge(
        self,
        module,
        world,
        armature,
        chain,
        chain_state: dict,
        dt: float,
        substeps: int,
        restart: bool = False,
    ) -> int:
        """
        TRANSITIONAL — 桥接到现有 solve_spring_bone_vrm_cpp (35 参数)。

        armature 由调用方传入（已过 _get_valid_armature 验证），不使用 self._armature。

        新 C++ API（create/update_dynamic/step/read_results）就绪后：
          1. 用 step_and_publish 里的新路径替换
          2. 删除此方法
        """
        d = self._dynamic
        s = self._static
        (
            collider_types,
            collider_groups,
            collider_centers,
            collider_segment_a,
            collider_segment_b,
            collider_radii,
        ) = _collision_arrays_from_world(world, armature, chain)

        armature_world     = np.asarray(matrix16(armature.matrix_world),            dtype=np.float32)
        armature_world_inv = np.asarray(matrix16(armature.matrix_world.inverted()),  dtype=np.float32)
        root_quaternion    = np.asarray((0.0, 0.0, 0.0, 1.0),                       dtype=np.float32)
        root_tail_world    = np.zeros(3, dtype=np.float32)
        gravity_dir        = np.asarray(chain.gravity_dir,                           dtype=np.float32)
        hit_radii, collided_by_groups = _bone_collision_profiles(armature, self._records)

        self._last_collider_count = len(collider_types)

        if restart:
            self._reset_dynamic_tails_to_pose()
            frame = int(getattr(world.frame_context, "frame", 0) or 0)
            self._last_frame = frame
            return self._publish_current_pose(world, chain, chain_state, frame)

        module.solve_spring_bone_vrm_cpp(
            d["current_tails"],
            d["prev_tails"],
            d["target_matrices"],
            d["target_quaternions"],
            d["current_heads"],
            d["current_pose_matrices"],
            d["current_pose_quaternions"],
            d["parent_pose_quaternions"],
            d["current_pose_tails"],
            s["lengths"],
            s["init_axis_local"],
            s["init_axis_parent"],
            s["init_rotations"],
            s["init_scales"],
            s["parent_indices"],
            s["pinned"],
            s["use_connect"],
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
            float(dt),
            max(1, int(substeps)),
            float(chain.stiffness_force),
            float(chain.drag_force),
            float(chain.gravity_power),
        )

        frame = int(getattr(world.frame_context, "frame", 0) or 0)
        self._step_count += 1
        self._last_frame = frame

        target_pose_matrices: dict[str, mathutils.Matrix] = {}
        published = 0
        tails = chain_state.setdefault("tails", {})
        last_results = []

        for index, record in enumerate(self._records):
            bone_name = record["bone_name"]
            target_matrix = _matrix_from_row(d["target_matrices"][index])
            target_pose_matrices[bone_name] = target_matrix
            basis_matrix = matrix_basis_from_pose_matrix(
                record["pose_bone"], target_matrix, target_pose_matrices
            )
            tails[bone_name] = {
                "current_tail": _tuple3(d["current_tails"][index]),
                "prev_tail":    _tuple3(d["prev_tails"][index]),
            }
            result = publish_spring_vrm_pose_result(
                world,
                slot_id=self._slot_id,
                armature_ptr=self._armature_ptr,
                armature_data_ptr=self._armature_data_ptr,
                frame=frame,
                generation=world.generation,
                bone_name=bone_name,
                pose_index=int(record["pose_index"]),
                matrix_basis=basis_matrix,
                target_pose_matrix=target_matrix,
                current_tail=_tuple3(d["current_tails"][index]),
                chain_root=chain.root_bone,
                backend="cpp",
            )
            if result is not None:
                last_results.append(result)
                published += 1

        chain_state["last_results"] = last_results
        return published


# ─────────────────────────────────────────────────────────────────────────────
# 拓扑签名
# ─────────────────────────────────────────────────────────────────────────────

def _records_signature(records: list[dict]) -> tuple:
    """骨骼拓扑签名：骨骼名、父骨名、pose 索引、连接状态。"""
    return tuple(
        (
            str(record.get("bone_name") or ""),
            str(record.get("parent_name") or ""),
            int(record.get("pose_index", -1)),
            bool(getattr(getattr(record.get("pose_bone"), "bone", None), "use_connect", False)),
        )
        for record in records
    )


# ─────────────────────────────────────────────────────────────────────────────
# 静态数组（topology / restart 变化时重建）
# ─────────────────────────────────────────────────────────────────────────────

def _alloc_static(n: int) -> dict[str, np.ndarray]:
    """分配静态数组（一次性，topology dirty 才重新分配）。"""
    return {
        "parent_indices":  np.full(n, -1,  dtype=np.int32),
        "use_connect":     np.zeros(n,     dtype=np.uint8),
        "pinned":          np.zeros(n,     dtype=np.uint8),
        "init_axis_local": np.empty((n, 3), dtype=np.float32),
        "init_axis_parent":np.empty((n, 3), dtype=np.float32),
        "init_rotations":  np.empty((n, 4), dtype=np.float32),
        "init_scales":     np.empty((n, 3), dtype=np.float32),
        "lengths":         np.empty(n,     dtype=np.float32),
    }


def _fill_static(s: dict[str, np.ndarray], records: list[dict]) -> None:
    """
    从当前 pose 填充静态数组。

    update_policy: restart_only
      init_axis / init_rotation / init_scale 捕获解算起始姿态，
      topology 不变时不重填——直到 restart 或 topology dirty。
    """
    parent_lookup = {r["bone_name"]: i for i, r in enumerate(records)}
    for i, rec in enumerate(records):
        pb = rec["pose_bone"]

        s["parent_indices"][i] = int(parent_lookup.get(rec["parent_name"], -1))
        s["use_connect"][i] = (
            1 if bool(getattr(getattr(pb, "bone", None), "use_connect", False)) else 0
        )
        s["pinned"][i] = 1 if _record_is_effectively_pinned(rec) else 0

        axis = pb.tail - pb.head
        if axis.length <= 1.0e-8:
            axis = mathutils.Vector((0.0, 0.0, 1.0))
        else:
            axis.normalize()

        init_axis_parent = axis.copy()
        parent = rec.get("parent")
        if parent is not None:
            try:
                init_axis_parent = parent.matrix.to_quaternion().inverted() @ axis
            except Exception:
                init_axis_parent = axis.copy()
            if init_axis_parent.length <= 1.0e-8:
                init_axis_parent = axis.copy()
            else:
                init_axis_parent.normalize()

        s["init_axis_local"][i]  = (float(axis.x), float(axis.y), float(axis.z))
        s["init_axis_parent"][i] = (
            float(init_axis_parent.x),
            float(init_axis_parent.y),
            float(init_axis_parent.z),
        )

        q = pb.matrix.to_quaternion()
        s["init_rotations"][i] = (float(q.x), float(q.y), float(q.z), float(q.w))

        sc = pb.matrix.to_scale()
        s["init_scales"][i] = (float(sc.x), float(sc.y), float(sc.z))

        # rest 骨长：用 edit-mode 定义的 bone.head/tail_local（rest pose 坐标），
        # 乘 armature world scale 得到世界空间骨长。
        # 不能用 pb.head/pb.tail（这是 POSED 坐标，受动画影响），
        # 否则第一帧若有动画压缩/拉伸，rest length 会被错误捕获。
        bone = pb.bone
        rest_vec = bone.tail_local - bone.head_local
        world_scale = pb.id_data.matrix_world.to_scale()
        avg_scale = (abs(world_scale.x) + abs(world_scale.y) + abs(world_scale.z)) / 3.0
        s["lengths"][i] = max(float(rest_vec.length) * avg_scale, 0.0)


def _record_is_effectively_pinned(record: dict) -> bool:
    bone_name = str(record.get("bone_name") or "")
    root_name = str(record.get("root_name") or "")
    if bone_name and bone_name == root_name:
        return True

    pb = record.get("pose_bone")
    armature = getattr(pb, "id_data", None)
    if armature is None or not bone_name:
        return False
    return resolve_bone_pin(armature, bone_name)


# ─────────────────────────────────────────────────────────────────────────────
# 动态数组（每帧重填，预分配 buffer 复用）
# ─────────────────────────────────────────────────────────────────────────────

def _alloc_dynamic(n: int) -> dict[str, np.ndarray]:
    """分配动态数组（bone count 不变时跨帧复用同一块内存）。"""
    return {
        "current_tails":           np.empty((n, 3),  dtype=np.float32),
        "prev_tails":              np.empty((n, 3),  dtype=np.float32),
        "target_matrices":         np.empty((n, 16), dtype=np.float32),
        "target_quaternions":      np.empty((n, 4),  dtype=np.float32),
        "current_heads":           np.empty((n, 3),  dtype=np.float32),
        "current_pose_matrices":   np.empty((n, 16), dtype=np.float32),
        "current_pose_quaternions":np.empty((n, 4),  dtype=np.float32),
        "parent_pose_quaternions": np.empty((n, 4),  dtype=np.float32),
        "current_pose_tails":      np.empty((n, 3),  dtype=np.float32),
    }


def _fill_dynamic(
    d: dict[str, np.ndarray],
    armature,
    chain_state: dict,
    records: list[dict],
) -> None:
    """每帧从当前 pose 采样动态数组。"""
    arm_world = armature.matrix_world
    tails = chain_state.setdefault("tails", {})

    for i, rec in enumerate(records):
        pb = rec["pose_bone"]
        parent = rec["parent"]

        head = arm_world @ pb.head
        tail = arm_world @ pb.tail

        tail_state   = tails.get(rec["bone_name"]) if isinstance(tails, dict) else None
        cur_tail     = _vector_from_state(tail_state, "current_tail", tail)
        prev_tail    = _vector_from_state(tail_state, "prev_tail",    cur_tail)

        _write_vec3(d["current_tails"],   i, cur_tail)
        _write_vec3(d["prev_tails"],      i, prev_tail)
        _write_vec3(d["current_heads"],   i, head)
        _write_vec3(d["current_pose_tails"], i, tail)
        _write_matrix(d["current_pose_matrices"],   i, pb.matrix)
        _write_matrix(d["target_matrices"],         i, pb.matrix)
        q = pb.matrix.to_quaternion()
        _write_quat(d["current_pose_quaternions"],  i, q)
        _write_quat(d["target_quaternions"],        i, q)
        _write_quat(d["parent_pose_quaternions"],   i,
                    parent.matrix.to_quaternion() if parent is not None else None)


# ─────────────────────────────────────────────────────────────────────────────
# 低级数组工具
# ─────────────────────────────────────────────────────────────────────────────

def _vector_from_state(state, key: str, fallback: mathutils.Vector) -> mathutils.Vector:
    if isinstance(state, dict):
        value = state.get(key)
        if value is not None:
            try:
                return mathutils.Vector((float(value[0]), float(value[1]), float(value[2])))
            except Exception:
                pass
    return fallback.copy()


def _write_vec3(arr: np.ndarray, i: int, v) -> None:
    arr[i, 0] = float(v[0]); arr[i, 1] = float(v[1]); arr[i, 2] = float(v[2])


def _write_quat(arr: np.ndarray, i: int, q) -> None:
    if q is None:
        arr[i] = (0.0, 0.0, 0.0, 1.0)
    else:
        arr[i, 0] = float(q.x); arr[i, 1] = float(q.y)
        arr[i, 2] = float(q.z); arr[i, 3] = float(q.w)


def _write_matrix(arr: np.ndarray, i: int, m) -> None:
    arr[i] = np.asarray(matrix16(m), dtype=np.float32)


def _matrix_from_row(row) -> mathutils.Matrix:
    v = [float(x) for x in row]
    return mathutils.Matrix((
        (v[0],  v[1],  v[2],  v[3]),
        (v[4],  v[5],  v[6],  v[7]),
        (v[8],  v[9],  v[10], v[11]),
        (v[12], v[13], v[14], v[15]),
    ))


def _tuple3(value) -> tuple[float, float, float]:
    return (float(value[0]), float(value[1]), float(value[2]))


# ─────────────────────────────────────────────────────────────────────────────
# Collision 辅助
# ─────────────────────────────────────────────────────────────────────────────

def _empty_collision_arrays() -> tuple:
    z3 = np.empty((0, 3), dtype=np.float32)
    return (
        np.empty(0, dtype=np.int32),
        np.empty(0, dtype=np.int32),
        z3.copy(), z3.copy(), z3.copy(),
        np.empty(0, dtype=np.float32),
    )


def _collision_arrays_from_world(world, armature, chain) -> tuple:
    snapshot = getattr(world, "collider_snapshot", None)
    colliders = snapshot.get("colliders") if isinstance(snapshot, dict) else None
    if not colliders:
        return _empty_collision_arrays()

    chain_bones = set(str(n or "") for n in getattr(chain, "bones", ()) or ())
    types, groups, centers, seg_a, seg_b, radii = [], [], [], [], [], []
    zero = np.zeros(3, dtype=np.float32)

    for c in colliders:
        if not isinstance(c, dict):
            continue
        if _is_self_chain_collider(c, armature, chain_bones):
            continue

        ctype = str(c.get("type", "SPHERE") or "SPHERE")
        center = numpy_vec3(c.get("center"))

        if ctype == "SPHERE":
            if center is None:
                continue
            r = max(float(c.get("radius", 0.0) or 0.0), 0.0)
            if r <= 1e-8:
                continue
            sa, sb, tc = center, center, COLLIDER_TYPE_SPHERE
        elif ctype == "CAPSULE":
            sa = numpy_vec3(c.get("segment_a"))
            sb = numpy_vec3(c.get("segment_b"))
            if sa is None or sb is None:
                continue
            center = center if center is not None else (sa + sb) * 0.5
            r = max(float(c.get("radius", 0.0) or 0.0), 0.0)
            if r <= 1e-8:
                continue
            tc = COLLIDER_TYPE_CAPSULE
        elif ctype == "PLANE":
            if center is None:
                continue
            normal = numpy_vec3(c.get("normal"))
            if normal is None or vec3_length(normal) <= 1e-8:
                continue
            sa, sb, r, tc = normal, zero, 0.0, COLLIDER_TYPE_PLANE
        elif ctype == "BOX":
            if center is None:
                continue
            ax = numpy_vec3(c.get("box_axis_x"))
            ay = numpy_vec3(c.get("box_axis_y"))
            az = numpy_vec3(c.get("box_axis_z"))
            hz = signed_third_axis_length(ax, ay, az)
            if ax is None or ay is None or hz is None:
                continue
            sa, sb, r, tc = ax, ay, hz, COLLIDER_TYPE_BOX
        else:
            continue

        types.append(tc)
        groups.append(max(1, min(16, int(c.get("primary_group", 1) or 1))))
        centers.append(center)
        seg_a.append(sa)
        seg_b.append(sb)
        radii.append(r)

    if not types:
        return _empty_collision_arrays()

    return (
        np.ascontiguousarray(types,   dtype=np.int32),
        np.ascontiguousarray(groups,  dtype=np.int32),
        np.ascontiguousarray(centers, dtype=np.float32).reshape((-1, 3)),
        np.ascontiguousarray(seg_a,   dtype=np.float32).reshape((-1, 3)),
        np.ascontiguousarray(seg_b,   dtype=np.float32).reshape((-1, 3)),
        np.ascontiguousarray(radii,   dtype=np.float32),
    )


def _is_self_chain_collider(c: dict, armature, chain_bones: set[str]) -> bool:
    if c.get("owner_type") != "BONE":
        return False
    if c.get("owner") is not armature:
        return False
    return str(c.get("bone") or "") in chain_bones


def _bone_collision_profiles(armature, records: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    n = len(records)
    radii  = np.zeros(n, dtype=np.float32)
    masks  = np.zeros(n, dtype=np.int32)
    for i, rec in enumerate(records):
        r, m = _bone_collision_profile(armature, str(rec.get("bone_name") or ""))
        radii[i] = r
        masks[i] = m
    return radii, masks


def _bone_collision_profile(armature, bone_name: str) -> tuple[float, int]:
    profile = resolve_bone_collision_fields(armature, bone_name)
    if str(profile.collision_type or "NONE") not in {"SPHERE", "CAPSULE"}:
        return 0.0, 0
    name = str(bone_name or "")
    bone = getattr(getattr(armature, "data", None), "bones", {}).get(name)
    if bone is None:
        return 0.0, 0
    pb     = getattr(getattr(armature, "pose", None), "bones", {}).get(name)
    lmat   = pb.matrix if pb is not None else bone.matrix_local
    radius = max(float(profile.radius or 0.0), 0.0)
    radius *= matrix_scale_radius(armature.matrix_world @ lmat)
    if radius <= 1e-8:
        return 0.0, 0
    return radius, clamp_int(profile.collided_by_groups, 0, 0xFFFF, 0)


# ─────────────────────────────────────────────────────────────────────────────
# Armature 引用校验 + chain records 构建
# ─────────────────────────────────────────────────────────────────────────────

def _chain_records(armature, chain) -> list[dict]:
    pose_bones = armature.pose.bones
    pose_index = {pb.name: i for i, pb in enumerate(pose_bones)}
    records = []
    for bone_name in chain.simulated_bones:
        pb = pose_bones.get(bone_name)
        if pb is None:
            continue
        parent = getattr(pb, "parent", None)
        records.append({
            "bone_name":   bone_name,
            "root_name":   str(getattr(chain, "root_bone", "") or ""),
            "pose_bone":   pb,
            "parent":      parent,
            "parent_name": parent.name if parent is not None else "",
            "pose_index":  int(pose_index.get(bone_name, -1)),
        })
    return records


def _get_valid_armature(spec):
    """
    获取 spec 上有效的 armature bpy 引用。

    渲染时 Blender 可能释放评估资源；先尝试校验现有引用，
    失败时按 armature_ptr + armature_data_ptr 双指针重新解析。
    """
    armature = getattr(spec, "armature", None)
    if armature is not None:
        try:
            if armature.pose is not None:
                ptr      = int(getattr(spec, "armature_ptr", 0) or 0)
                data_ptr = int(getattr(spec, "armature_data_ptr", 0) or 0)
                if ptr > 0 and armature.as_pointer() == ptr:
                    data = getattr(armature, "data", None)
                    if data is not None and data.as_pointer() == data_ptr:
                        return armature
        except ReferenceError:
            pass
        except Exception:
            return armature

    try:
        from ....render_safety import resolve_armature_by_ptr
        ptr      = int(getattr(spec, "armature_ptr", 0) or 0)
        data_ptr = int(getattr(spec, "armature_data_ptr", 0) or 0)
        fresh = resolve_armature_by_ptr(ptr, data_ptr)
        if fresh is not None:
            try:
                spec.armature = fresh
            except Exception:
                pass
            for chain in getattr(spec, "chains", ()) or ():
                try:
                    chain.armature = fresh
                except Exception:
                    pass
        return fresh
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 主入口：step_spring_vrm_slot
# ─────────────────────────────────────────────────────────────────────────────

def step_spring_vrm_slot(world, slot, dt: float, substeps: int, restart: bool) -> tuple[int, float, list[str]]:
    """
    推进单个 solver slot 的所有 SpringBone 链。

    对每条链：
      1. 若 restart 或 topology 变化 → ctx.rebuild(spec, records)
      2. ctx.fill_dynamic(armature, chain_state, records)
      3. ctx.step_and_publish(module, world, spec, chain, chain_state, dt, substeps)

    返回 (published_count, elapsed_ms, errors)。
    """
    spec = slot.data.get("spec")
    if spec is None:
        return 0, 0.0, ["slot missing spec"]

    try:
        module = native_module()
    except Exception as exc:
        return 0, 0.0, [f"hotools_native 不可用: {exc}"]
    if not hasattr(module, "solve_spring_bone_vrm_cpp"):
        return 0, 0.0, ["hotools_native 缺少 solve_spring_bone_vrm_cpp"]

    # restart 时清空 frame_state（tails）
    frame_state = slot.data.setdefault("frame_state", {})
    if restart or frame_state.get("spec_hash") != spec.spec_hash:
        frame_state.clear()
        frame_state["spec_hash"] = spec.spec_hash
        frame_state["chains"] = {}

    armature = _get_valid_armature(spec)
    if armature is None:
        return 0, 0.0, ["armature 无效或已被 Blender 释放"]

    native_ctxs: dict[str, SpringVRMNativeContext] = slot.data.setdefault("_native_ctxs", {})
    chain_states = frame_state.setdefault("chains", {})
    published = 0
    errors: list[str] = []
    started = time.perf_counter()

    for chain in spec.chains:
        root = chain.root_bone
        try:
            records = _chain_records(armature, chain)
            if not records or not bool(chain.enabled):
                continue

            ctx = native_ctxs.get(root)
            if not isinstance(ctx, SpringVRMNativeContext):
                ctx = SpringVRMNativeContext(root)
                native_ctxs[root] = ctx

            # rebuild: topology 变化 OR restart（需重新捕获 init 姿态）
            if restart or ctx.needs_rebuild(records):
                ctx.rebuild(spec, records)

            chain_state = chain_states.setdefault(root, {})
            ctx.fill_dynamic(armature, chain_state, records)
            count = ctx.step_and_publish(module, world, armature, chain, chain_state, dt, substeps, restart)
            published += count
        except Exception as exc:
            errors.append(f"{root}: {exc}")

    # 清理已不在 spec 里的 stale context（骨链减少时回收资源）
    active_roots = {c.root_bone for c in spec.chains}
    for stale in list(native_ctxs):
        if stale not in active_roots:
            try:
                native_ctxs.pop(stale).dispose()
            except Exception:
                pass

    return published, (time.perf_counter() - started) * 1000.0, errors


# ─────────────────────────────────────────────────────────────────────────────
# Debug / stats（供 solver.py 的 _install_slot_debug_snapshot 调用）
# ─────────────────────────────────────────────────────────────────────────────

def native_context_debug_dict(native_ctxs) -> dict:
    """把 slot.data['_native_ctxs'] 转换成可 JSON 序列化的调试字典。"""
    if not isinstance(native_ctxs, dict):
        return {"available": False}
    chains = []
    for _, ctx in sorted(native_ctxs.items()):
        if isinstance(ctx, SpringVRMNativeContext):
            chains.append(ctx.debug_dict())
    return {
        "available": bool(chains),
        "schema": SpringVRMNativeContext.SCHEMA,
        "chain_count": len(chains),
        "chains": chains,
    }


def native_context_stats_dict(native_ctxs) -> dict:
    """精简版统计，供 publish_spring_vrm_stats_result 使用。"""
    debug = native_context_debug_dict(native_ctxs)
    chain_items = debug.get("chains") or []
    return {
        "available":       bool(debug.get("available", False)),
        "schema":          str(debug.get("schema") or ""),
        "chain_count":     int(debug.get("chain_count", 0)),
        "step_count":      sum(int(c.get("step_count", 0)) for c in chain_items),
        "cpp_handle_count":sum(1 for c in chain_items if c.get("cpp_handle")),
        "static_ready_count": sum(1 for c in chain_items if c.get("static_ready")),
        "buffer_count":    sum(len(c.get("buffer_shapes") or {}) for c in chain_items),
    }
