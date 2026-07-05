"""MeshCloth 多 proxy 聚合拓扑。

把多个独立 proxy 的粒子数组、约束索引表合并成一个统一的 state dict，
送入 solver 做单次解算，解算后按头标/尾标拆分 display_positions 写回各自 mesh。

自碰撞检测（self_collision_enabled）在合并状态下对全部粒子生效，
因此不同 proxy 的粒子天然互相推挤，无需额外碰撞器配置。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import bpy

# 合并 state 使用的特殊 kind 标记，便于外部区分
MC2_MERGED_CACHE_KIND = "mc2_merged_cloth"


# ---------------------------------------------------------------------------
# ProxyChunk：单个 proxy 在合并数组中的头标/尾标描述符
# ---------------------------------------------------------------------------

@dataclass
class ProxyChunk:
    """描述一个 proxy 在合并粒子数组中的位置及其 per-proxy 属性。

    start / end 是左闭右开区间，merged_array[start:end] 对应该 proxy 的粒子。
    """

    start: int
    end: int
    proxy_obj: object                   # bpy.types.Object
    output_key: str
    base_pose_proxy: object             # ensure_base_pose_proxy 的结果，可为 None
    blend_weight: float = 1.0

    # ---- 每帧由 build_per_proxy_runtime_arrays 填充 ----
    # 这些是已按 depth 曲线展开的 per-particle float32 数组，
    # 合并时直接 concatenate，无需 depth 插值。
    substep_damping_values: np.ndarray = field(default_factory=lambda: np.empty(0, np.float32))
    distance_stiffness_values: np.ndarray = field(default_factory=lambda: np.empty(0, np.float32))
    bend_stiffness_values: np.ndarray = field(default_factory=lambda: np.empty(0, np.float32))
    angle_restoration_values: np.ndarray = field(default_factory=lambda: np.empty(0, np.float32))
    angle_restoration_velocity_attenuation_values: np.ndarray = field(default_factory=lambda: np.empty(0, np.float32))
    angle_restoration_gravity_falloff_values: np.ndarray = field(default_factory=lambda: np.empty(0, np.float32))
    angle_limit_values: np.ndarray = field(default_factory=lambda: np.empty(0, np.float32))

    @property
    def count(self) -> int:
        return self.end - self.start


# ---------------------------------------------------------------------------
# 内部工具：数组拼接
# ---------------------------------------------------------------------------

def _concat(arrays: list, dtype=np.float32) -> np.ndarray:
    """拼接一组同类型 numpy 数组，返回 contiguous 数组。"""
    if not arrays:
        return np.empty(0, dtype=dtype)
    return np.ascontiguousarray(np.concatenate(arrays, axis=0), dtype=dtype)


def _concat_particle(states: list[dict], field_name: str, dtype=np.float32) -> np.ndarray:
    """拼接各 proxy state 中相同字段的 per-particle 数组（无需偏移）。"""
    arrays = []
    for s in states:
        val = s.get(field_name)
        if val is not None:
            arrays.append(np.asarray(val, dtype=dtype))
    return _concat(arrays, dtype=dtype)


def _concat_index_1d(states: list[dict], field_name: str, offsets: list[int]) -> np.ndarray:
    """拼接 1D 索引数组并加粒子偏移（-1 的 sentinel 不加偏移，用于 parent_indices 中的根节点）。"""
    arrays = []
    for s, offset in zip(states, offsets):
        val = s.get(field_name)
        if val is None:
            continue
        arr = np.asarray(val, dtype=np.int32).reshape(-1)
        if offset > 0:
            # -1 是"无父节点"sentinel，不加偏移
            shifted = np.where(arr >= 0, arr + offset, arr)
            arrays.append(shifted)
        else:
            arrays.append(arr)
    return _concat(arrays, dtype=np.int32)


def _concat_index_2d(states: list[dict], field_name: str, offsets: list[int]) -> np.ndarray:
    """拼接 2D 索引数组并加粒子偏移，支持 (E,2) / (E,3) / (E,4) 等形状。"""
    arrays = []
    for s, offset in zip(states, offsets):
        val = s.get(field_name)
        if val is None or len(val) == 0:
            continue
        arr = np.asarray(val, dtype=np.int32)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        arrays.append(arr + offset if offset > 0 else arr)
    if not arrays:
        return np.empty((0, 2), dtype=np.int32)
    return np.ascontiguousarray(np.concatenate(arrays, axis=0), dtype=np.int32)


def _concat_flat_indexed(states: list[dict], field_name: str, offsets: list[int]) -> np.ndarray:
    """拼接扁平化索引数组（每个元素是顶点索引）并加偏移。"""
    arrays = []
    for s, offset in zip(states, offsets):
        val = s.get(field_name)
        if val is None:
            continue
        arr = np.asarray(val, dtype=np.int32).reshape(-1)
        arrays.append(arr + offset if offset > 0 else arr)
    return _concat(arrays, dtype=np.int32)


# ---------------------------------------------------------------------------
# CSR（压缩稀疏行）邻居表合并
# ---------------------------------------------------------------------------

def _merge_csr_table(
    states: list[dict],
    start_field: str,
    count_field: str,
    data_field: str,
    rest_field: str,
    particle_offsets: list[int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """合并多个 proxy 的 CSR 邻居表。

    CSR 格式：
      start[i]  →  data 数组里顶点 i 的邻居列表起始下标
      count[i]  →  邻居数量
      data[start[i]:start[i]+count[i]]  →  邻居顶点索引
      rest[start[i]:start[i]+count[i]]  →  对应约束静息值

    合并时：
      - start 需加"已累积的 data 长度"偏移
      - data 中存储的顶点索引需加粒子偏移
      - count、rest 直接拼接
    """
    merged_starts = []
    merged_counts = []
    merged_data = []
    merged_rest = []
    data_offset = 0

    for s, p_off in zip(states, particle_offsets):
        st = s.get(start_field)
        ct = s.get(count_field)
        da = s.get(data_field)
        re = s.get(rest_field)
        if st is None or ct is None or da is None:
            # 该 proxy 没有这张表，跳过（下游 solver 对空数组安全）
            continue

        st_arr = np.asarray(st, dtype=np.int32).reshape(-1)
        ct_arr = np.asarray(ct, dtype=np.int32).reshape(-1)
        da_arr = np.asarray(da, dtype=np.int32).reshape(-1)
        re_arr = np.asarray(re, dtype=np.float32).reshape(-1) if re is not None else np.zeros(len(da_arr), np.float32)

        # start 加 data 累积偏移
        merged_starts.append(st_arr + data_offset)
        merged_counts.append(ct_arr)
        # data 中的顶点索引加粒子偏移
        merged_data.append(da_arr + p_off if p_off > 0 else da_arr)
        merged_rest.append(re_arr)
        data_offset += len(da_arr)

    return (
        _concat(merged_starts, np.int32),
        _concat(merged_counts, np.int32),
        _concat(merged_data, np.int32),
        _concat(merged_rest, np.float32),
    )


# ---------------------------------------------------------------------------
# baseline 数组合并
# ---------------------------------------------------------------------------

def _merge_baseline(
    states: list[dict],
    particle_offsets: list[int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """合并各 proxy 的 baseline（角度约束参考链）。

    baseline_start[i]  →  baseline_data 中顶点 i 的参考段起始下标
    baseline_count[i]  →  参考段数量（不变）
    baseline_data      →  参考约束数据（直接拼接）
    baseline_flags     →  与 baseline_data 等长的标志位（直接拼接）

    合并时 baseline_start 加"已累积 baseline_data 长度"偏移。
    """
    merged_start = []
    merged_count = []
    merged_data = []
    merged_flags = []
    data_offset = 0

    for s, p_off in zip(states, particle_offsets):
        bs = s.get("baseline_start")
        bc = s.get("baseline_count")
        bd = s.get("baseline_data")
        bf = s.get("baseline_flags")
        if bs is None or bc is None or bd is None:
            continue

        bs_arr = np.asarray(bs, dtype=np.int32).reshape(-1)
        bc_arr = np.asarray(bc, dtype=np.int32).reshape(-1)
        bd_arr = np.asarray(bd, dtype=np.int32).reshape(-1)
        bf_arr = (
            np.asarray(bf, dtype=np.int32).reshape(-1)
            if bf is not None
            else np.zeros(len(bd_arr), dtype=np.int32)
        )

        merged_start.append(bs_arr + data_offset)
        merged_count.append(bc_arr)
        # baseline_data 存储顶点索引，需加粒子偏移，否则 chunk1 以后的 proxy
        # 角度约束会错误引用 chunk0 的粒子位置，导致约束失效（软、飞）
        merged_data.append(bd_arr + p_off if p_off > 0 else bd_arr)
        merged_flags.append(bf_arr)
        data_offset += len(bd_arr)

    return (
        _concat(merged_start, np.int32),
        _concat(merged_count, np.int32),
        _concat(merged_data, np.int32),
        _concat(merged_flags, np.int32),
    )


# ---------------------------------------------------------------------------
# build_merged_state：把多个 per-proxy state 合并成单个解算 state
# ---------------------------------------------------------------------------

def build_chunks(per_proxy_states: list[dict]) -> list[ProxyChunk]:
    """根据已有 per-proxy state 计算各 proxy 的粒子范围，返回 ProxyChunk 列表。

    只计算 start/end，其余字段由调用方填充。
    """
    chunks: list[ProxyChunk] = []
    cursor = 0
    for s in per_proxy_states:
        n = int(s.get("vertex_count", 0))
        chunks.append(ProxyChunk(
            start=cursor,
            end=cursor + n,
            proxy_obj=None,
            output_key="",
            base_pose_proxy=None,
        ))
        cursor += n
    return chunks


def build_merged_state(
    per_proxy_states: list[dict],
    chunks: list[ProxyChunk],
) -> dict:
    """把多个独立 proxy 的 state dict 合并成一个供 solver 使用的 merged state dict。

    per_proxy_states[i] 对应 chunks[i]，顺序必须一致。
    各 proxy 的粒子在 merged 数组里的位置由 chunks[i].start / end 决定。

    调用方须保证每次拓扑变化（任意 proxy 顶点数改变）时重新调用本函数。
    """
    if not per_proxy_states:
        raise ValueError("per_proxy_states 不能为空")

    offsets: list[int] = [ch.start for ch in chunks]
    first = per_proxy_states[0]
    total_n = sum(ch.count for ch in chunks)

    # ---- 纯 per-particle 位置/速度数组（直接拼接）----
    attributes    = _concat_particle(per_proxy_states, "attributes",    np.uint8)
    rest_world    = _concat_particle(per_proxy_states, "rest_world_positions")
    rest_local    = _concat_particle(per_proxy_states, "rest_local_positions")
    rest_local_n  = _concat_particle(per_proxy_states, "rest_local_normals")
    rest_world_n  = _concat_particle(per_proxy_states, "rest_world_normals")
    base_pos      = _concat_particle(per_proxy_states, "base_positions")
    base_nor      = _concat_particle(per_proxy_states, "base_normals")
    base_rot      = _concat_particle(per_proxy_states, "base_rotations")
    step_basic_p  = _concat_particle(per_proxy_states, "step_basic_positions")
    step_basic_r  = _concat_particle(per_proxy_states, "step_basic_rotations")
    next_pos      = _concat_particle(per_proxy_states, "next_positions")
    old_pos       = _concat_particle(per_proxy_states, "old_positions")
    vel_pos       = _concat_particle(per_proxy_states, "velocity_positions")
    disp_pos      = _concat_particle(per_proxy_states, "display_positions")
    velocity      = _concat_particle(per_proxy_states, "velocity")
    real_vel      = _concat_particle(per_proxy_states, "real_velocity")
    friction      = _concat_particle(per_proxy_states, "friction")
    static_fric   = _concat_particle(per_proxy_states, "static_friction")
    coll_normals  = _concat_particle(per_proxy_states, "collision_normals")
    sc_inv_masses = _concat_particle(per_proxy_states, "self_collision_inv_masses")
    depths        = _concat_particle(per_proxy_states, "depths")
    root_rest_len = _concat_particle(per_proxy_states, "root_rest_lengths")
    tether_rest   = _concat_particle(per_proxy_states, "tether_rest_lengths")
    inv_masses    = _concat_particle(per_proxy_states, "inv_masses")
    vtx_local_p   = _concat_particle(per_proxy_states, "vertex_local_positions")
    vtx_local_r   = _concat_particle(per_proxy_states, "vertex_local_rotations")

    # ---- per-particle 索引数组（需加粒子偏移）----
    root_indices   = _concat_index_1d(per_proxy_states, "root_indices",   offsets)
    parent_indices = _concat_index_1d(per_proxy_states, "parent_indices", offsets)

    # ---- 约束索引（二维，需加粒子偏移）----
    edges         = _concat_index_2d(per_proxy_states, "edges",         offsets)
    triangles     = _concat_index_2d(per_proxy_states, "triangles",     offsets)
    dihedral_pairs = _concat_index_2d(per_proxy_states, "dihedral_pairs", offsets)
    volume_pairs  = _concat_index_2d(per_proxy_states, "volume_pairs",  offsets)
    tri_pairs     = _concat_index_2d(per_proxy_states, "triangle_pairs", offsets)

    # ---- 约束 1D 索引对（edge_i / edge_j 分开存储）----
    edge_i   = _concat_flat_indexed(per_proxy_states, "edge_i",   offsets)
    edge_j   = _concat_flat_indexed(per_proxy_states, "edge_j",   offsets)
    edge_rest = _concat_particle(per_proxy_states, "edge_rest")
    edge_type = _concat_particle(per_proxy_states, "edge_type",   np.int32)

    bend_i    = _concat_flat_indexed(per_proxy_states, "bend_i",   offsets)
    bend_j    = _concat_flat_indexed(per_proxy_states, "bend_j",   offsets)
    bend_rest = _concat_particle(per_proxy_states, "bend_rest")
    bend_type = _concat_particle(per_proxy_states, "bend_type",   np.int32)

    # ---- 约束标量（直接拼接）----
    dihedral_rest   = _concat_particle(per_proxy_states, "dihedral_rest_angles")
    dihedral_signs  = _concat_particle(per_proxy_states, "dihedral_signs",  np.int32)
    volume_rest_arr = _concat_particle(per_proxy_states, "volume_rest")

    # ---- CSR 邻居表 ----
    (dist_start, dist_count, dist_data, dist_rest) = _merge_csr_table(
        per_proxy_states, "distance_start", "distance_count", "distance_data", "distance_rest", offsets
    )
    (bend_start, bend_count, bend_data, bend_n_rest) = _merge_csr_table(
        per_proxy_states, "bend_start", "bend_count", "bend_data", "bend_neighbor_rest", offsets
    )

    # ---- baseline（角度约束参考链）----
    bl_start, bl_count, bl_data, bl_flags = _merge_baseline(per_proxy_states, offsets)

    # ---- self_collision 属性：OR 合并布尔，max 合并厚度/质量 ----
    sc_enabled   = any(bool(s.get("self_collision_enabled", False)) for s in per_proxy_states)
    sc_thickness = max((float(s.get("self_collision_surface_thickness", 0.0)) for s in per_proxy_states), default=0.0)
    sc_mass      = max((float(s.get("self_collision_mass", 0.0)) for s in per_proxy_states), default=0.0)
    # collision_local_radii / collision_radii 直接拼接（已是 per-particle 标量）
    coll_local_r = _concat_particle(per_proxy_states, "collision_local_radii")
    coll_r       = _concat_particle(per_proxy_states, "collision_radii")
    # collided_by_groups：按位 OR
    collided_mask = 0
    for s in per_proxy_states:
        collided_mask |= int(s.get("collided_by_groups", 0))

    # bend_kind：如果任意 proxy 有 dihedral，整体走 dihedral 路径
    from .constants import (
        MC2_BEND_KIND_DIRECTION_DIHEDRAL,
        MC2_BEND_KIND_DISTANCE_APPROX,
        MC2_CACHE_KIND,
        MC2_CURVE_READY_PARAMETERS,
    )
    bend_kind = (
        MC2_BEND_KIND_DIRECTION_DIHEDRAL
        if any(s.get("bend_kind") == MC2_BEND_KIND_DIRECTION_DIHEDRAL for s in per_proxy_states)
        else MC2_BEND_KIND_DISTANCE_APPROX
    )

    return {
        "kind": MC2_CACHE_KIND,   # 必须与标准 state 相同，solver 会校验这个字段
        "solver_version": first.get("solver_version"),
        "frame": first.get("frame"),
        # 合并状态没有单一 object，元数据字段留空；per-proxy 信息存在 ProxyChunk 里
        "object_name": "__merged__",
        "object_ptr": 0,
        "mesh_ptr": 0,
        "output_key": "__merged__",
        "mesh_light_key": None,
        "mesh_signature_key": None,
        "config_key": None,
        "object_matrix_world_key": None,
        "object_matrix_world_3x3_key": None,
        "object_matrix_world": first.get("object_matrix_world"),
        "init_scale_radius": first.get("init_scale_radius", 1.0),
        "scale_ratio": first.get("scale_ratio", 1.0),
        "negative_scale_sign": first.get("negative_scale_sign", 1),
        # 解算标量状态（从第一个 proxy 继承，由 solver 每帧更新）
        "velocity_weight": float(first.get("velocity_weight", 0.0)),
        "blend_weight": float(first.get("blend_weight", 0.0)),
        "distance_weight": float(first.get("distance_weight", 1.0)),
        "vertex_count": total_n,
        "frame_delta_time": float(first.get("frame_delta_time", 0.0)),
        "step_delta_time": float(first.get("step_delta_time", 0.0)),
        "update_count": int(first.get("update_count", 0)),
        "skip_count": int(first.get("skip_count", 0)),
        "substep_count": int(first.get("substep_count", 1)),
        "frame_interpolation": float(first.get("frame_interpolation", 1.0)),
        "time_scale": float(first.get("time_scale", 1.0)),
        "skip_writing": bool(first.get("skip_writing", False)),
        "culling": bool(first.get("culling", False)),
        "sync": bool(first.get("sync", True)),
        "scale_suspend": bool(first.get("scale_suspend", False)),
        "substep_damping": float(first.get("substep_damping", 0.0)),
        # ---- per-particle 数组 ----
        "rest_local_positions":  rest_local,
        "rest_world_positions":  rest_world,
        "rest_local_normals":    rest_local_n,
        "rest_world_normals":    rest_world_n,
        "base_positions":        base_pos,
        "base_normals":          base_nor,
        "base_rotations":        base_rot,
        "step_basic_positions":  step_basic_p,
        "step_basic_rotations":  step_basic_r,
        "next_positions":        next_pos,
        "old_positions":         old_pos,
        "velocity_positions":    vel_pos,
        "display_positions":     disp_pos,
        "velocity":              velocity,
        "real_velocity":         real_vel,
        "friction":              friction,
        "static_friction":       static_fric,
        "collision_normals":     coll_normals,
        "self_collision_inv_masses": sc_inv_masses,
        "depths":                depths,
        "root_indices":          root_indices,
        "parent_indices":        parent_indices,
        "root_rest_lengths":     root_rest_len,
        "tether_rest_lengths":   tether_rest,
        "inv_masses":            inv_masses,
        "vertex_local_positions": vtx_local_p,
        "vertex_local_rotations": vtx_local_r,
        # ---- 约束 ----
        "edges":         edges,
        "triangles":     triangles,
        "edge_i":        edge_i,
        "edge_j":        edge_j,
        "edge_rest":     edge_rest,
        "edge_type":     edge_type,
        "bend_i":        bend_i,
        "bend_j":        bend_j,
        "bend_rest":     bend_rest,
        "bend_type":     bend_type,
        "triangle_pairs": tri_pairs,
        "dihedral_pairs": dihedral_pairs,
        "dihedral_rest_angles": dihedral_rest,
        "dihedral_signs": dihedral_signs,
        "volume_pairs":  volume_pairs,
        "volume_rest":   volume_rest_arr,
        "bend_kind":     bend_kind,
        "bend_distance_i":    bend_i,
        "bend_distance_j":    bend_j,
        "bend_distance_rest": bend_rest,
        "bend_distance_type": bend_type,
        # ---- CSR 邻居表 ----
        "distance_start":  dist_start,
        "distance_count":  dist_count,
        "distance_data":   dist_data,
        "distance_rest":   dist_rest,
        "bend_start":              bend_start,
        "bend_count":              bend_count,
        "bend_data":               bend_data,
        "bend_neighbor_rest":      bend_n_rest,
        "bend_distance_start":     bend_start,
        "bend_distance_count":     bend_count,
        "bend_distance_data":      bend_data,
        "bend_distance_neighbor_rest": bend_n_rest,
        # ---- baseline ----
        "baseline_start":  bl_start,
        "baseline_count":  bl_count,
        "baseline_data":   bl_data,
        "baseline_flags":  bl_flags,
        # ---- 碰撞 ----
        "collision_local_radii":           coll_local_r,
        "collision_radii":                 coll_r,
        "collided_by_groups":              collided_mask,
        "self_collision_enabled":          sc_enabled,
        "self_collision_surface_thickness": sc_thickness,
        "self_collision_mass":             sc_mass,
        # ---- 运行时槽位（从第一个 proxy 继承 inertia_state / attributes，按需）----
        "inertia_state":  first.get("inertia_state"),
        "attributes":     attributes,
        "param_slots":    {name: None for name in MC2_CURVE_READY_PARAMETERS},
        "extension_slots": {
            "runtime_cache": {},
            "features": {
                "bonecloth": {},
                "curves": {},
                "self_collision": {},
                "native": {},
            },
        },
    }


# ---------------------------------------------------------------------------
# 每帧更新：把单个 proxy 的 per-particle 数组写入 merged state 的对应切片
# ---------------------------------------------------------------------------

# 每帧需要从 per-proxy state 同步到 merged state 的 per-particle 字段列表。
# 这些字段在 sync_state_to_base_pose_proxy / sync_state_to_base_pose_write_container
# 被更新，必须反映到合并数组里。
_SYNC_PARTICLE_FIELDS_3D = (
    "base_positions",
    "base_normals",
    "base_rotations",
    "step_basic_positions",
    "step_basic_rotations",
    "rest_world_positions",
    "rest_world_normals",
)

_SYNC_PARTICLE_FIELDS_VELOCITY = (
    "next_positions",
    "old_positions",
    "velocity_positions",
    "display_positions",
    "velocity",
    "real_velocity",
    "collision_normals",
)


def update_merged_particle_slice(
    merged_state: dict,
    proxy_state: dict,
    chunk: ProxyChunk,
) -> None:
    """把一个 proxy 的 per-particle 数组写入 merged_state 对应切片（原地修改）。

    在每帧 sync 之后、solve 之前调用，确保 base_positions / step_basic_positions 等
    反映了最新的 base pose proxy 数据。

    不复制约束索引表（这些只在拓扑变化时重建）。
    """
    sl = slice(chunk.start, chunk.end)
    for field_name in _SYNC_PARTICLE_FIELDS_3D + _SYNC_PARTICLE_FIELDS_VELOCITY:
        src = proxy_state.get(field_name)
        if src is None:
            continue
        dst = merged_state.get(field_name)
        if dst is None:
            continue
        try:
            dst[sl] = np.asarray(src, dtype=dst.dtype)
        except (ValueError, TypeError):
            # 形状不匹配（拓扑已变但合并 state 未重建），静默跳过
            pass


def copy_merged_slice_to_proxy(
    merged_state: dict,
    proxy_state: dict,
    chunk: ProxyChunk,
) -> None:
    """解算完成后，把 merged_state 里的粒子数据回写到 per-proxy state（原地修改）。

    这样 per-proxy state 保持最新的 display_positions 与 velocity，
    方便下一帧的连续性检查与 cache 匹配。
    """
    sl = slice(chunk.start, chunk.end)
    for field_name in ("display_positions", "next_positions", "old_positions",
                       "velocity", "real_velocity", "velocity_positions",
                       "collision_normals", "friction", "static_friction"):
        src = merged_state.get(field_name)
        if src is None:
            continue
        dst = proxy_state.get(field_name)
        if dst is None:
            continue
        try:
            proxy_state[field_name] = np.ascontiguousarray(src[sl], dtype=dst.dtype)
        except (ValueError, TypeError):
            pass


# ---------------------------------------------------------------------------
# 解算后拆分：从 merged display_positions 取出各 proxy 的切片
# ---------------------------------------------------------------------------

def split_display_positions(
    merged_state: dict,
    chunks: list[ProxyChunk],
) -> list[np.ndarray]:
    """从 merged_state["display_positions"] 按 chunk 切片，返回每个 proxy 的位置数组。

    返回列表与 chunks 等长，每个元素是 [Ni, 3] float32 contiguous array。
    """
    disp = merged_state.get("display_positions")
    if disp is None:
        return [np.empty((0, 3), np.float32) for _ in chunks]
    result = []
    for ch in chunks:
        sl = disp[ch.start:ch.end]
        result.append(np.ascontiguousarray(sl, dtype=np.float32))
    return result


def split_base_positions(
    merged_state: dict,
    chunks: list[ProxyChunk],
) -> list[np.ndarray]:
    """从 merged_state["base_positions"] 按 chunk 切片，用于写回时的 delta 计算基准。"""
    base = merged_state.get("base_positions")
    if base is None:
        return [np.empty((0, 3), np.float32) for _ in chunks]
    return [np.ascontiguousarray(base[ch.start:ch.end], dtype=np.float32) for ch in chunks]


# ---------------------------------------------------------------------------
# merge_runtime_params：把多个 per-proxy MC2RuntimeParams 合并成一个
# ---------------------------------------------------------------------------

def merge_runtime_params(
    per_proxy_runtimes,          # list[MC2RuntimeParams]
    chunks: list[ProxyChunk],
    global_runtime,              # MC2RuntimeParams（来自 solver 节点，持有 anchor/inertia 参数）
):
    """把各 proxy 的 MC2RuntimeParams 合并为单个，per-particle 数组字段直接拼接，
    全局标量字段取 global_runtime（gravity、inertia、speed limit 等由 solver 节点统一控制）。

    per-particle 数组（damping_values / distance_stiffness_values 等）来自各 proxy
    自己的 build_runtime_params，按 chunk 顺序拼接后包装为 per_particle_param dict，
    由 solver 按粒子下标直接索引，不再做 depth 曲线插值。

    返回一个新的 MC2RuntimeParams dataclass 实例。
    """
    from . import params as mc2_params
    from .runtime_params import MC2RuntimeParams, substep_damping_values as _substep_damp

    def _concat_values(attr_name: str) -> np.ndarray:
        arrays = []
        for rp in per_proxy_runtimes:
            val = getattr(rp, attr_name, None)
            if val is not None:
                arrays.append(np.asarray(val, dtype=np.float32).reshape(-1))
        return np.ascontiguousarray(np.concatenate(arrays) if arrays else np.empty(0, np.float32), dtype=np.float32)

    def _pp(attr_name: str, minimum=None, maximum=None) -> dict:
        """把拼接后的 per-particle 数组包装成 per_particle_param dict。"""
        return mc2_params.per_particle_param(_concat_values(attr_name), minimum=minimum, maximum=maximum)

    # per-proxy 物理参数 → per-particle
    merged_substep_damping     = _concat_values("substep_damping_values")
    merged_distance_stiffness  = _concat_values("distance_stiffness_values")
    merged_bend_stiffness      = _concat_values("bend_stiffness_values")
    merged_angle_restoration   = _concat_values("angle_restoration_values")
    merged_angle_rest_vel_att  = _concat_values("angle_restoration_velocity_attenuation_values")
    merged_angle_rest_grav     = _concat_values("angle_restoration_gravity_falloff_values")
    merged_angle_limit         = _concat_values("angle_limit_values")

    # blend_weight：per-proxy 标量 → per-particle 数组
    bw_arrays = []
    for rp, ch in zip(per_proxy_runtimes, chunks):
        bw_arrays.append(np.full(ch.count, float(getattr(rp, "blend_weight", 1.0)), dtype=np.float32))
    merged_blend_weight = np.ascontiguousarray(np.concatenate(bw_arrays) if bw_arrays else np.empty(0, np.float32), dtype=np.float32)

    # 全局标量字段直接取 global_runtime（重力、惯性、速度限制等由 solver 节点决定）
    g = global_runtime
    return MC2RuntimeParams(
        animation_pose_ratio  = g.animation_pose_ratio,
        gravity_dot           = g.gravity_dot,
        gravity_ratio         = g.gravity_ratio,
        velocity_weight       = g.velocity_weight,
        blend_weight          = float(merged_blend_weight.mean()) if len(merged_blend_weight) > 0 else 1.0,
        normal_axis           = g.normal_axis,
        motion_enabled        = g.motion_enabled,
        collision_mode        = g.collision_mode,
        angle_limit_stiffness = g.angle_limit_stiffness,
        movement_speed_limit  = g.movement_speed_limit,
        rotation_speed_limit  = g.rotation_speed_limit,
        local_movement_speed_limit  = g.local_movement_speed_limit,
        local_rotation_speed_limit  = g.local_rotation_speed_limit,
        particle_speed_limit  = g.particle_speed_limit,
        dynamic_friction      = g.dynamic_friction,
        static_friction_speed = g.static_friction_speed,
        # per-proxy 参数 → per_particle_param
        damping_param                       = mc2_params.per_particle_param(merged_substep_damping, 0.0, 1.0),
        distance_stiffness_param            = mc2_params.per_particle_param(merged_distance_stiffness, 0.0, 1.0),
        bend_stiffness_param                = mc2_params.per_particle_param(merged_bend_stiffness, 0.0, 1.0),
        angle_restoration_param             = mc2_params.per_particle_param(merged_angle_restoration, 0.0, 1.0),
        angle_restoration_velocity_attenuation_param = mc2_params.per_particle_param(merged_angle_rest_vel_att, 0.0, 1.0),
        angle_restoration_gravity_falloff_param      = mc2_params.per_particle_param(merged_angle_rest_grav, 0.0, 1.0),
        angle_limit_param                   = mc2_params.per_particle_param(merged_angle_limit, 0.0, 180.0),
        # 全局 param dicts 直接复用 global_runtime（不分 proxy）
        angle_limit_stiffness_param         = g.angle_limit_stiffness_param,
        anchor_inertia_param                = g.anchor_inertia_param,
        world_inertia_param                 = g.world_inertia_param,
        movement_inertia_smoothing_param    = g.movement_inertia_smoothing_param,
        local_inertia_param                 = g.local_inertia_param,
        depth_inertia_param                 = g.depth_inertia_param,
        centrifugal_param                   = g.centrifugal_param,
        movement_speed_limit_param          = g.movement_speed_limit_param,
        rotation_speed_limit_param          = g.rotation_speed_limit_param,
        local_movement_speed_limit_param    = g.local_movement_speed_limit_param,
        local_rotation_speed_limit_param    = g.local_rotation_speed_limit_param,
        particle_speed_limit_param          = g.particle_speed_limit_param,
        max_distance_param                  = g.max_distance_param,
        tether_compression_param            = g.tether_compression_param,
        tether_stretch_param                = g.tether_stretch_param,
        motion_stiffness_param              = g.motion_stiffness_param,
        backstop_radius_param               = g.backstop_radius_param,
        backstop_distance_param             = g.backstop_distance_param,
        collider_friction_param             = g.collider_friction_param,
        collider_collision_mode_param       = g.collider_collision_mode_param,
        use_tether_param                    = g.use_tether_param,
        use_distance_param                  = g.use_distance_param,
        use_bend_param                      = g.use_bend_param,
        use_angle_restoration_param         = g.use_angle_restoration_param,
        use_angle_limit_param               = g.use_angle_limit_param,
        use_max_distance_param              = g.use_max_distance_param,
        use_backstop_param                  = g.use_backstop_param,
        use_collider_collision_param        = g.use_collider_collision_param,
        # per-particle 数组（合并后直接使用）
        substep_damping_values              = merged_substep_damping,
        distance_stiffness_values           = merged_distance_stiffness,
        bend_stiffness_values               = merged_bend_stiffness,
        angle_restoration_values            = merged_angle_restoration,
        angle_restoration_velocity_attenuation_values = merged_angle_rest_vel_att,
        angle_restoration_gravity_falloff_values      = merged_angle_rest_grav,
        angle_limit_values                  = merged_angle_limit,
    )
