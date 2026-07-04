"""BoneCloth 骨骼采样与拓扑构建。

本模块负责把一组骨链采样成 MC2 solver 可直接消费的粒子 + 约束数组。
核心复用点：拓扑无关的 `baseline.build_mesh_baseline` 和 `mesh_build.*` 构建器
只吃 edges / rest_world / rest_world_normals / attributes，不关心来源是 mesh 还是骨骼。
因此 BoneCloth 只需产出骨骼版的这几个输入数组，其余全部走 MeshCloth 同一套地基。

连接模式（对应 MC2 RenderSetupData.BoneConnectionMode，去掉 AutomaticMesh）：
  0 = Line              仅纵向父子边
  1 = SequentialNonLoop 按 root 列表顺序连接相邻链，首尾不成环（默认）
  2 = SequentialLoop    同上但首末链额外成环
"""

from __future__ import annotations

import bpy
import mathutils
import numpy as np

from ..physicsMC2 import baseline, mesh_build, math_utils, inertia
from ..physicsMC2 import state as mc2_state
from ..physicsMC2.constants import (
    MC2_ATTR_FIXED,
    MC2_ATTR_MOTION,
    MC2_ATTR_MOVE,
    MC2_BEND_KIND_DISTANCE_APPROX,
    MC2_CACHE_KIND,
    MC2_CURVE_READY_PARAMETERS,
    MC2_SOLVER_VERSION,
    MC2SystemConstants,
)

# BoneCloth 三角连接角度阈值，对应 MC2 SystemDefine.ProxyMeshBoneClothTriangleAngle。
BONECLOTH_TRIANGLE_ANGLE = 120.0

CONNECTION_MODE_LINE = 0
CONNECTION_MODE_SEQUENTIAL = 1
CONNECTION_MODE_SEQUENTIAL_LOOP = 2

MC2_RUNTIME_CACHE_SLOT = mc2_state.MC2_RUNTIME_CACHE_SLOT


# ---------------------------------------------------------------------------
# 骨链采集
# ---------------------------------------------------------------------------
def _pose_bone_chain_names(root_pose_bone) -> list[str]:
    """从根 PoseBone 沿单主干收集骨链名。

    与 SpringBone 的 collect_bone_names 不同，这里遇到分叉只跟随第一个子骨，
    因为 BoneCloth 的横向连接依赖“每条链是一条清晰的纵向序列”。
    分叉应由用户在建模阶段拆成多条 root 或分别填入 root 列表。
    """
    names: list[str] = []
    current = root_pose_bone
    guard = 0
    while current is not None and guard < 4096:
        names.append(current.name)
        children = list(getattr(current, "children", []) or [])
        current = children[0] if children else None
        guard += 1
    return names


def collect_bone_chains(armature_obj: bpy.types.Object, root_bone_names: list[str]) -> list[dict]:
    """对每条 root 骨链做纵向遍历，返回骨链列表。

    每条链: {"root": str, "bones": [骨名,...]}，顺序从 root 到 leaf。
    无效 root（找不到骨骼）会被跳过，不阻断其他链。
    """
    chains: list[dict] = []
    if armature_obj is None or armature_obj.type != "ARMATURE":
        return chains
    pose_bones = armature_obj.pose.bones
    seen_roots: set[str] = set()
    for raw_name in root_bone_names:
        name = str(raw_name or "").strip()
        if not name or name in seen_roots:
            continue
        root_pose_bone = pose_bones.get(name)
        if root_pose_bone is None:
            continue
        seen_roots.add(name)
        bone_names = _pose_bone_chain_names(root_pose_bone)
        if bone_names:
            chains.append({"root": name, "bones": bone_names})
    return chains


def flatten_chain_bone_names(chains: list[dict]) -> list[str]:
    """把骨链列表展平成粒子顺序的骨名列表（粒子索引 = 该列表下标）。"""
    names: list[str] = []
    for chain in chains:
        names.extend(chain.get("bones") or [])
    return names


# ---------------------------------------------------------------------------
# 粒子采样
# ---------------------------------------------------------------------------
def sample_bone_head_world(armature_obj: bpy.types.Object, bone_names: list[str]) -> np.ndarray:
    """采样每根骨骼 head 的世界坐标作为粒子位置。"""
    matrix_world = armature_obj.matrix_world
    positions = np.zeros((len(bone_names), 3), dtype=np.float32)
    pose_bones = armature_obj.pose.bones
    for index, name in enumerate(bone_names):
        pose_bone = pose_bones.get(name)
        if pose_bone is None:
            continue
        head_world = matrix_world @ pose_bone.head
        positions[index] = (head_world.x, head_world.y, head_world.z)
    return np.ascontiguousarray(positions, dtype=np.float32)


def sample_bone_directions_world(armature_obj: bpy.types.Object, bone_names: list[str]) -> np.ndarray:
    """采样每根骨骼的世界朝向（head→tail 单位向量），作为粒子法线的替代。

    mesh 有顶点法线，骨骼没有；base_rotations 依赖法线，这里用骨向充当。
    """
    matrix_world = armature_obj.matrix_world
    normals = np.zeros((len(bone_names), 3), dtype=np.float32)
    pose_bones = armature_obj.pose.bones
    for index, name in enumerate(bone_names):
        pose_bone = pose_bones.get(name)
        if pose_bone is None:
            normals[index] = (0.0, 0.0, 1.0)
            continue
        head_world = matrix_world @ pose_bone.head
        tail_world = matrix_world @ pose_bone.tail
        direction = mathutils.Vector(tail_world) - mathutils.Vector(head_world)
        if direction.length <= MC2SystemConstants.EPSILON:
            normals[index] = (0.0, 0.0, 1.0)
        else:
            direction.normalize()
            normals[index] = (direction.x, direction.y, direction.z)
    return np.ascontiguousarray(normals, dtype=np.float32)


# ---------------------------------------------------------------------------
# 拓扑构建
# ---------------------------------------------------------------------------
def _chain_particle_layout(chains: list[dict]) -> tuple[list[list[int]], np.ndarray, np.ndarray]:
    """返回按骨链组织的粒子索引布局。

    - chain_indices: 每条链的粒子索引列表（从 root 到 leaf）
    - depth_by_particle: 每个粒子在其链中的深度（root=0）
    - chain_by_particle:  每个粒子所属链的下标
    """
    chain_indices: list[list[int]] = []
    depths: list[int] = []
    chains_of: list[int] = []
    cursor = 0
    for chain_index, chain in enumerate(chains):
        bones = chain.get("bones") or []
        indices = list(range(cursor, cursor + len(bones)))
        chain_indices.append(indices)
        for depth in range(len(bones)):
            depths.append(depth)
            chains_of.append(chain_index)
        cursor += len(bones)
    return (
        chain_indices,
        np.asarray(depths, dtype=np.int32),
        np.asarray(chains_of, dtype=np.int32),
    )


def _longitudinal_edges(chain_indices: list[list[int]]) -> tuple[list[tuple[int, int]], set[tuple[int, int]]]:
    """纵向父子边（主边）。返回边列表和主边集合（无向、小索引在前）。"""
    edges: list[tuple[int, int]] = []
    main_edges: set[tuple[int, int]] = set()
    for indices in chain_indices:
        for k in range(len(indices) - 1):
            i = indices[k]
            j = indices[k + 1]
            edges.append((i, j))
            main_edges.add((i, j) if i < j else (j, i))
    return edges, main_edges


def _lateral_edges(
    chain_indices: list[list[int]],
    connection_mode: int,
) -> list[tuple[int, int]]:
    """横向顺序连接边：按 root 列表下标顺序，配对相邻链的同深度粒子。

    不做任何距离查找——列表顺序就是横向连接顺序。
    SequentialLoop 额外连接首末链。
    """
    lateral: list[tuple[int, int]] = []
    chain_count = len(chain_indices)
    if chain_count < 2:
        return lateral

    def connect_pair(a: list[int], b: list[int]) -> None:
        common = min(len(a), len(b))
        for depth in range(common):
            i = a[depth]
            j = b[depth]
            lateral.append((i, j) if i < j else (j, i))

    for chain_index in range(chain_count - 1):
        connect_pair(chain_indices[chain_index], chain_indices[chain_index + 1])

    if connection_mode == CONNECTION_MODE_SEQUENTIAL_LOOP and chain_count >= 3:
        connect_pair(chain_indices[-1], chain_indices[0])
    return lateral


def _build_triangles(
    edges: list[tuple[int, int]],
    main_edges: set[tuple[int, int]],
    chain_by_particle: np.ndarray,
    positions: np.ndarray,
) -> np.ndarray:
    """从顶点邻接关系枚举三角形，规则对齐 MC2 SequentialMesh：

    - 每个顶点枚举其邻居对，无需第三条边存在于 edge set
      （MC2 source: VirtualMeshInputOutput.cs L799-846，不检查 link[j]↔link[k]）
    - 角度 < 120°（以枚举顶点为中心测量）
    - 至少含 1 条主边（枚举顶点到任一邻居的边为主边）
    - 不允许三顶点跨三条不同链
    """
    adjacency: dict[int, list[int]] = {}
    for i, j in edges:
        adjacency.setdefault(i, []).append(j)
        adjacency.setdefault(j, []).append(i)

    def is_main(a: int, b: int) -> bool:
        return ((a, b) if a < b else (b, a)) in main_edges

    angle_cos_limit = float(np.cos(np.deg2rad(BONECLOTH_TRIANGLE_ANGLE)))
    triangle_set: set[tuple[int, int, int]] = set()

    for i, neighbors in adjacency.items():
        if len(neighbors) < 2:
            continue
        ci = int(chain_by_particle[i])
        pi = positions[i]
        sorted_nbrs = sorted(neighbors)
        for a_pos in range(len(sorted_nbrs)):
            j = sorted_nbrs[a_pos]
            # 枚举顶点到 j 必须是主边（确保三角至少含一条纵向骨链边）
            ij_is_main = is_main(i, j)
            for b_pos in range(a_pos + 1, len(sorted_nbrs)):
                k = sorted_nbrs[b_pos]
                ik_is_main = is_main(i, k)
                # 至少一条主边
                if not ij_is_main and not ik_is_main:
                    continue
                # 不跨三条链
                cj = int(chain_by_particle[j])
                ck = int(chain_by_particle[k])
                if ci != cj and ci != ck and cj != ck:
                    continue
                # 角度阈值（以 i 为顶点）
                v1 = positions[j] - pi
                v2 = positions[k] - pi
                n1 = float(np.linalg.norm(v1))
                n2 = float(np.linalg.norm(v2))
                if n1 <= MC2SystemConstants.EPSILON or n2 <= MC2SystemConstants.EPSILON:
                    continue
                cos_angle = float(np.dot(v1, v2) / (n1 * n2))
                if cos_angle <= angle_cos_limit:
                    continue
                tri = tuple(sorted((int(i), int(j), int(k))))
                triangle_set.add(tri)

    if not triangle_set:
        return np.empty((0, 3), dtype=np.int32)
    return np.ascontiguousarray(sorted(triangle_set), dtype=np.int32)


def build_bone_topology(
    chains: list[dict],
    connection_mode: int,
    positions: np.ndarray,
) -> dict:
    """构建 BoneCloth 拓扑：edges（line 约束）、triangles、main_edges。"""
    chain_indices, _depth_by_particle, chain_by_particle = _chain_particle_layout(chains)
    longitudinal, main_edges = _longitudinal_edges(chain_indices)

    if connection_mode == CONNECTION_MODE_LINE:
        lateral: list[tuple[int, int]] = []
    else:
        lateral = _lateral_edges(chain_indices, connection_mode)

    all_edges = list(longitudinal) + list(lateral)

    if connection_mode == CONNECTION_MODE_LINE or not lateral:
        triangles = np.empty((0, 3), dtype=np.int32)
    else:
        triangles = _build_triangles(all_edges, main_edges, chain_by_particle, positions)

    if all_edges:
        edges = np.ascontiguousarray(all_edges, dtype=np.int32)
    else:
        edges = np.empty((0, 2), dtype=np.int32)

    return {
        "edges": edges,
        "triangles": triangles,
        "chain_by_particle": np.ascontiguousarray(chain_by_particle, dtype=np.int32),
    }


# ---------------------------------------------------------------------------
# attributes / collision
# ---------------------------------------------------------------------------
def build_bone_attributes(chains: list[dict]) -> np.ndarray:
    """每条链的 root（第一根）设为 FIXED（pin），其余设为 MOVE|MOTION。"""
    attributes: list[int] = []
    for chain in chains:
        bones = chain.get("bones") or []
        for depth in range(len(bones)):
            if depth == 0:
                attributes.append(MC2_ATTR_FIXED)
            else:
                attributes.append(MC2_ATTR_MOVE | MC2_ATTR_MOTION)
    return np.ascontiguousarray(attributes, dtype=np.uint8)


def build_bone_collision_radii(
    armature_obj: bpy.types.Object,
    bone_names: list[str],
    fallback_radius: float,
) -> np.ndarray:
    """每根骨骼的碰撞半径。优先读 hotools_collision.radius，否则用 fallback。"""
    count = len(bone_names)
    radii = np.full(count, max(float(fallback_radius), 0.0), dtype=np.float32)
    data_bones = armature_obj.data.bones if armature_obj.data is not None else None
    if data_bones is None:
        return radii
    for index, name in enumerate(bone_names):
        bone = data_bones.get(name)
        props = getattr(bone, "hotools_collision", None) if bone is not None else None
        if props is None:
            continue
        radius = getattr(props, "radius", None)
        if radius is not None and float(radius) > 0.0:
            radii[index] = float(radius)
    return radii


def sync_bone_state_to_pose(
    state: dict,
    armature_obj: bpy.types.Object,
    chains: list[dict],
    center_state=None,
) -> dict:
    """连续帧把骨架世界变换同步到 base pose / 约束静态量。

    设计约定（对齐 MC2 sync_state_to_object_transform 的安全路径）：
    - 约束静态量（edge_rest / baseline / tether）由 rest_local_positions + matrix_world 派生，
      不重采样实际骨骼 head 位置——避免物理写回 matrix_basis 后头位移回馈成新的静止长度。
    - 当 matrix_world 3x3 未变化时跳过约束重建，只更新位置和 base_positions。
    - root 骨（FIXED）的 base_positions 直接从当前骨头采样，保证 pin 粒子随动画移动。
    - 非 root 骨的 base_positions 由 rest_local + matrix_world 派生，无反馈。

    Per-bone animation 跟随（非 root 骨随动画移动）属于后续扩展，当前版本不实现。
    """
    matrix_key = math_utils.matrix_world_key(armature_obj)
    matrix_3x3_key = math_utils.matrix_world_3x3_key(armature_obj)
    next_state = mc2_state.inherit_runtime_slots(state, dict(state))

    # 从存储的 rest_local 派生当前 rest_world（安全，无反馈）
    new_world_mat = math_utils.matrix_to_numpy(armature_obj.matrix_world)
    rest_local = np.ascontiguousarray(next_state["rest_local_positions"], dtype=np.float32)
    rest_world = math_utils.transform_positions(new_world_mat, rest_local)
    rest_local_normals = np.ascontiguousarray(next_state.get("rest_local_normals"), dtype=np.float32)
    if rest_local_normals.shape != rest_world.shape:
        rest_local_normals = np.tile([0.0, 1.0, 0.0], (len(rest_world), 1)).astype(np.float32)
    rest_world_normals = math_utils.transform_directions(new_world_mat, rest_local_normals)

    edges = next_state["edges"]
    attributes = next_state["attributes"]
    triangles = next_state["triangles"]

    # 仅当旋转/缩放变化时重建约束，避免每帧重算 edge_rest 导致距离约束失效
    if next_state.get("object_matrix_world_3x3_key") != matrix_3x3_key:
        baseline_data = baseline.build_mesh_baseline(edges, rest_world, rest_world_normals, attributes)
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

        edge_i, edge_j, edge_rest = mesh_build.build_edge_constraints(edges, rest_world)
        edge_type = mesh_build.structural_constraint_types(edge_i, edge_j, next_state["parent_indices"])
        edge_i, edge_j, edge_rest, edge_type = mesh_build.append_shear_distance_constraints(
            edge_i, edge_j, edge_rest, edge_type, triangles, rest_world, attributes,
        )
        next_state["edge_i"] = edge_i
        next_state["edge_j"] = edge_j
        next_state["edge_rest"] = edge_rest
        next_state["edge_type"] = edge_type
        (
            next_state["distance_start"],
            next_state["distance_count"],
            next_state["distance_data"],
            next_state["distance_rest"],
        ) = mesh_build.build_neighbor_table(int(next_state["vertex_count"]), edge_i, edge_j, edge_rest, edge_type)

        bend_i = next_state.get("bend_distance_i", next_state["bend_i"])
        bend_j = next_state.get("bend_distance_j", next_state["bend_j"])
        bend_rest = mesh_build.constraint_lengths(rest_world, bend_i, bend_j)
        bend_type = mesh_build.bend_distance_constraint_types(bend_i)
        next_state["bend_i"] = bend_i
        next_state["bend_j"] = bend_j
        next_state["bend_rest"] = bend_rest
        next_state["bend_type"] = bend_type
        next_state["bend_distance_rest"] = bend_rest
        next_state["bend_distance_type"] = bend_type
        (
            next_state["bend_start"],
            next_state["bend_count"],
            next_state["bend_data"],
            next_state["bend_neighbor_rest"],
        ) = mesh_build.build_neighbor_table(int(next_state["vertex_count"]), bend_i, bend_j, bend_rest, bend_type)
        next_state["bend_distance_start"] = next_state["bend_start"]
        next_state["bend_distance_count"] = next_state["bend_count"]
        next_state["bend_distance_data"] = next_state["bend_data"]
        next_state["bend_distance_neighbor_rest"] = next_state["bend_neighbor_rest"]
        next_state["tether_rest_lengths"] = mesh_build.build_tether_rest_lengths(
            rest_world, next_state["root_indices"]
        )
        next_state["inv_masses"] = mc2_state.calc_inverse_masses(
            attributes, next_state["depths"], next_state["friction"]
        )
        next_state["object_matrix_world_3x3_key"] = matrix_3x3_key
    else:
        # 3x3 不变：step_basic_pose 仍需每帧刷新（pin 粒子位置可能随整体移动）
        next_state["step_basic_positions"], next_state["step_basic_rotations"] = (
            baseline.update_step_basic_pose(
                rest_world,
                next_state["base_rotations"],
                next_state["parent_indices"],
                next_state["baseline_start"],
                next_state["baseline_count"],
                next_state["baseline_data"],
                next_state["vertex_local_positions"],
                next_state["vertex_local_rotations"],
            )
        )

    # base_positions：root 骨直接读当前 head 保证 pin 粒子随动画移动
    # 非 root 由 rest_local + matrix_world 派生，无反馈环
    base_positions = np.ascontiguousarray(rest_world.copy(), dtype=np.float32)
    bone_names_list = list(next_state.get("bone_names") or flatten_chain_bone_names(chains))
    attributes_arr = np.ascontiguousarray(attributes, dtype=np.uint8)
    fixed_mask = (attributes_arr & MC2_ATTR_MOVE) == 0
    if np.any(fixed_mask):
        root_world = sample_bone_head_world(armature_obj, bone_names_list)
        base_positions[fixed_mask] = root_world[fixed_mask]

    next_state["rest_local_positions"] = np.ascontiguousarray(rest_local, dtype=np.float32)
    next_state["rest_world_positions"] = np.ascontiguousarray(rest_world, dtype=np.float32)
    next_state["rest_local_normals"] = np.ascontiguousarray(rest_local_normals, dtype=np.float32)
    next_state["rest_world_normals"] = np.ascontiguousarray(rest_world_normals, dtype=np.float32)
    next_state["base_positions"] = base_positions
    next_state["base_normals"] = np.ascontiguousarray(rest_world_normals.copy(), dtype=np.float32)
    next_state["object_matrix_world"] = new_world_mat
    next_state["object_matrix_world_key"] = matrix_key
    next_state["scale_ratio"] = math_utils.matrix_scale_ratio(
        armature_obj.matrix_world,
        next_state.get("init_scale_radius", math_utils.matrix_scale_radius(armature_obj.matrix_world)),
    )
    next_state["negative_scale_sign"] = math_utils.object_negative_scale_sign(armature_obj)

    mc2_state.commit_base_pose_state_for_center(
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
    mc2_state.commit_topology_state_for_center(next_state, center_state)
    return next_state


# ---------------------------------------------------------------------------
# 缓存 key
# ---------------------------------------------------------------------------
def bone_topology_key(
    armature_obj: bpy.types.Object,
    bone_names: list[str],
    connection_mode: int,
) -> tuple:
    """拓扑缓存 key：骨架身份 + 骨名序列 + 连接模式。

    骨骼增删或列表顺序改变都会失效重建，与 MeshCloth 拓扑变化需 reset 的约定一致。
    """
    return (
        armature_obj.name_full,
        int(armature_obj.as_pointer()),
        tuple(bone_names),
        int(connection_mode),
    )


# ---------------------------------------------------------------------------
# 完整 state 构建
# ---------------------------------------------------------------------------
def build_bone_state(
    armature_obj: bpy.types.Object,
    chains: list[dict],
    connection_mode: int,
    output_key: str,
    topology_key: tuple,
    collision_radius: float,
) -> dict:
    """构建 MC2 solver 可直接消费的 BoneCloth state dict。

    复用 MeshCloth 的全部拓扑无关构建器；mesh 特有的 shear/dihedral/volume
    因为 triangles 可能为空而自动 no-op，bend 自动落到 distance-approx。
    """
    bone_names = flatten_chain_bone_names(chains)
    vertex_count = len(bone_names)

    rest_world = sample_bone_head_world(armature_obj, bone_names)
    rest_world_normals = sample_bone_directions_world(armature_obj, bone_names)
    # BoneCloth 不做 object-local rest；直接把世界坐标经 armature 逆矩阵转成 local 存储，
    # 供 sync_state_to_object_transform 在 armature 移动时重建世界坐标。
    world_to_local = math_utils.matrix_to_numpy(armature_obj.matrix_world.inverted())
    rest_local = math_utils.transform_positions(world_to_local, rest_world)
    rest_local_normals = math_utils.transform_directions(world_to_local, rest_world_normals)

    attributes = build_bone_attributes(chains)
    topology = build_bone_topology(chains, connection_mode, rest_world)
    edges = topology["edges"]
    triangles = topology["triangles"]

    baseline_data = baseline.build_mesh_baseline(edges, rest_world, rest_world_normals, attributes)
    depths = baseline_data["depths"]
    root_indices = baseline_data["root_indices"]
    parent_indices = baseline_data["parent_indices"]
    root_rest_lengths = baseline_data["root_rest_lengths"]

    friction = np.zeros(vertex_count, dtype=np.float32)
    static_friction = np.zeros(vertex_count, dtype=np.float32)
    inv_masses = mc2_state.calc_inverse_masses(attributes, depths, friction)

    edge_i, edge_j, edge_rest = mesh_build.build_edge_constraints(edges, rest_world)
    edge_type = mesh_build.structural_constraint_types(edge_i, edge_j, parent_indices)
    edge_i, edge_j, edge_rest, edge_type = mesh_build.append_shear_distance_constraints(
        edge_i, edge_j, edge_rest, edge_type, triangles, rest_world, attributes,
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
        vertex_count, edge_i, edge_j, edge_rest, edge_type,
    )
    bend_start, bend_count, bend_data, bend_neighbor_rest = mesh_build.build_neighbor_table(
        vertex_count, bend_i, bend_j, bend_rest, bend_type,
    )

    collision_radii_local = build_bone_collision_radii(armature_obj, bone_names, collision_radius)
    self_collision_inv_masses = mc2_state.calc_self_collision_inverse_masses(
        attributes, depths, friction, 0.0,
    )
    zeros3 = np.zeros((vertex_count, 3), dtype=np.float32)

    return {
        "kind": MC2_CACHE_KIND,
        "solver_version": MC2_SOLVER_VERSION,
        "frame": None,
        "object_name": armature_obj.name_full,
        "object_ptr": int(armature_obj.as_pointer()),
        "mesh_ptr": 0,
        "output_key": output_key,
        # BoneCloth 专属缓存维度
        "bone_names": tuple(bone_names),
        "bone_topology_key": topology_key,
        "connection_mode": int(connection_mode),
        "chain_by_particle": topology["chain_by_particle"],
        # MeshCloth 兼容占位（缓存匹配用）
        "mesh_light_key": topology_key,
        "mesh_signature_key": topology_key,
        "config_key": topology_key,
        "object_matrix_world_key": math_utils.matrix_world_key(armature_obj),
        "object_matrix_world_3x3_key": math_utils.matrix_world_3x3_key(armature_obj),
        "object_matrix_world": math_utils.matrix_to_numpy(armature_obj.matrix_world),
        "init_scale_radius": math_utils.matrix_scale_radius(armature_obj.matrix_world),
        "scale_ratio": 1.0,
        "negative_scale_sign": math_utils.object_negative_scale_sign(armature_obj),
        "velocity_weight": 0.0,
        "blend_weight": 0.0,
        "distance_weight": 1.0,
        "vertex_count": vertex_count,
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
        "inertia_state": inertia.make_runtime_state(armature_obj),
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
        "bend_kind": MC2_BEND_KIND_DISTANCE_APPROX,
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
        "collision_local_radii": np.ascontiguousarray(collision_radii_local, dtype=np.float32),
        "collision_radii": np.ascontiguousarray(collision_radii_local, dtype=np.float32),
        "collided_by_groups": 0,
        "self_collision_enabled": False,
        "self_collision_surface_thickness": 0.0,
        "self_collision_mass": 0.0,
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
