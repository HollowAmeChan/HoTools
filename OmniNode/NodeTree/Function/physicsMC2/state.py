"""MeshCloth 缓存状态与 Python/C++ ABI 形状守卫。

这里维护的是求解器真实运行状态。Blender 对象、shape key 与场景生命周期仍由
节点入口调度；本模块只负责把当前 mesh 输入整理成可复用的数组状态。
"""

import bpy
import numpy as np

from . import baseline, blender_io, inertia, math_utils, mesh_build
from .constants import (
    MC2_ATTR_MOVE,
    MC2_BEND_KIND_DISTANCE_APPROX,
    MC2_BEND_KIND_DIRECTION_DIHEDRAL,
    MC2_CACHE_KIND,
    MC2_CURVE_READY_PARAMETERS,
    MC2_SOLVER_VERSION,
    MC2SystemConstants,
)


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
    shape_key_name: str,
    mesh_light_key: tuple,
    mesh_signature_key: tuple,
    config_key: tuple,
    collision_radius: float,
) -> dict:
    rest_local = blender_io.read_rest_positions(obj)
    rest_world = blender_io.local_positions_to_world(obj, rest_local)
    rest_local_normals = mesh_build.rest_local_normals(obj)
    rest_world_normals = math_utils.transform_directions(math_utils.matrix_to_numpy(obj.matrix_world), rest_local_normals)
    edges, triangles = mesh_build.mesh_connectivity_arrays(obj.data)
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
        "shape_key_name": shape_key_name,
        "mesh_light_key": mesh_light_key,
        "mesh_signature_key": mesh_signature_key,
        "config_key": config_key,
        "object_matrix_world_key": math_utils.matrix_world_key(obj),
        "object_matrix_world_3x3_key": math_utils.matrix_world_3x3_key(obj),
        "object_matrix_world": math_utils.matrix_to_numpy(obj.matrix_world),
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
            "bonecloth": None,
            "curves": {},
            "self_collision": None,
            "native": None,
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

    next_state = dict(state)
    new_world = math_utils.matrix_to_numpy(obj.matrix_world)
    rest_local = np.ascontiguousarray(next_state["rest_local_positions"], dtype=np.float32)
    rest_world = blender_io.local_positions_to_world(obj, rest_local)
    rest_local_normals = np.ascontiguousarray(next_state.get("rest_local_normals"), dtype=np.float32)
    if rest_local_normals.shape != rest_world.shape:
        rest_local_normals = mesh_build.rest_local_normals(obj)
    rest_world_normals = math_utils.transform_directions(new_world, rest_local_normals)
    next_state["object_matrix_world_key"] = matrix_key
    next_state["object_matrix_world"] = new_world

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


def state_matches(
    state,
    obj: bpy.types.Object,
    shape_key_name: str,
    mesh_light_key: tuple,
) -> bool:
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
        and state.get("shape_key_name") == shape_key_name
        and state.get("mesh_light_key") == mesh_light_key
        and state.get("vertex_count") == vertex_count
    )
