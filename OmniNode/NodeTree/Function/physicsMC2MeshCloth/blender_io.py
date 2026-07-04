"""MC2 Python 后端的 Blender I/O 边界。"""

import bpy
import numpy as np

from .....PhysicsTools.meshClothBasePose import MC2_DELTA_SPEC, validate_base_pose_proxy
from .....PhysicsTools.deltaOutput import clear_delta_attribute as _clear_delta_attribute
from .....PhysicsTools.deltaOutput import write_world_delta_attribute as _write_world_delta_attribute
from . import math_utils

_BASE_POSE_CACHE_PREFIX = "mc2_base_pose_world_pose"


def is_live_id(value) -> bool:
    if value is None:
        return False
    try:
        value.as_pointer()
        return True
    except ReferenceError:
        return False
    except Exception:
        return False


def is_live_mesh_object(value) -> bool:
    if not is_live_id(value) or not isinstance(value, bpy.types.Object):
        return False
    try:
        return value.type == "MESH" and value.data is not None and is_live_id(value.data)
    except ReferenceError:
        return False


def scene_delta_time(scene: bpy.types.Scene = None) -> float:
    scene = scene or bpy.context.scene
    render = scene.render
    fps_base = float(render.fps_base) if render.fps_base else 1.0
    fps = float(render.fps) / fps_base
    return 1.0 / fps if fps > 0.0 else 0.0


def substep_damping(frame_damping: float, substeps: int) -> float:
    """把每场景帧阻尼换算成每子步阻尼。"""
    damping = max(0.0, min(1.0, float(frame_damping)))
    substep_count = max(1, int(substeps))
    return 1.0 - ((1.0 - damping) ** (1.0 / substep_count))


def require_mesh_object(obj, label: str) -> bpy.types.Object:
    if not is_live_mesh_object(obj):
        raise ValueError(f"{label} 不是 Mesh 对象")
    try:
        vertex_count = len(obj.data.vertices)
    except ReferenceError as exc:
        raise ValueError(f"{label} 不是 Mesh 对象") from exc
    if vertex_count == 0:
        raise ValueError(f"{label} mesh 没有顶点")
    return obj


def output_key_name(obj: bpy.types.Object) -> str:
    return "MC2Delta"


def base_pose_proxy_object(obj: bpy.types.Object) -> bpy.types.Object | None:
    props = getattr(obj, "hotools_mesh_collision", None)
    try:
        proxy = getattr(props, "mc2_base_pose_proxy", None) if props is not None else None
    except ReferenceError:
        proxy = None
    if proxy is None:
        return None
    if proxy == obj:
        raise ValueError("MC2 BasePose只读对象不能指向当前物理写入对象")
    if not is_live_mesh_object(proxy):
        raise ValueError("MC2 BasePose只读对象必须是Mesh对象")
    if len(proxy.data.vertices) == 0:
        raise ValueError("MC2 BasePose只读对象没有顶点")
    if getattr(proxy, "mode", "OBJECT") != "OBJECT":
        raise ValueError("MC2 BasePose只读对象必须处于Object模式")
    validate_base_pose_proxy(obj, proxy)
    return proxy


def _base_pose_cache_key(obj: bpy.types.Object, proxy: bpy.types.Object, frame: int) -> tuple[str, int, int, int]:
    return (_BASE_POSE_CACHE_PREFIX, int(obj.as_pointer()), int(proxy.as_pointer()), int(frame))


def cached_base_pose_world_pose(
    obj: bpy.types.Object,
    proxy: bpy.types.Object,
    frame: int,
    cache: dict | None = None,
) -> tuple[np.ndarray, np.ndarray] | None:
    if not isinstance(cache, dict):
        return None
    key = _base_pose_cache_key(obj, proxy, frame)
    value = cache.get(key)
    if value is None:
        return None
    positions, normals = value
    return positions.copy(), normals.copy()


def read_cached_base_pose_world_pose(
    obj: bpy.types.Object,
    proxy: bpy.types.Object,
    frame: int,
    depsgraph=None,
    cache: dict | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    cached = cached_base_pose_world_pose(obj, proxy, frame, cache)
    if cached is not None:
        return cached

    validate_base_pose_proxy(obj, proxy)
    positions, normals = read_evaluated_mesh_world_pose(proxy, depsgraph)
    if isinstance(cache, dict):
        cache[_base_pose_cache_key(obj, proxy, frame)] = (positions, normals)
        _trim_base_pose_cache(cache, frame)
        return positions.copy(), normals.copy()
    return positions, normals


def read_evaluated_mesh_world_pose(
    obj: bpy.types.Object,
    depsgraph=None,
) -> tuple[np.ndarray, np.ndarray]:
    depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    # 不直接读取 eval_obj.data：选择物体/刷新依赖图时，depsgraph 持有的 evaluated data 生命周期更敏感。
    # 这里用 to_mesh() 拷贝出本帧快照，成本略高，但能避免 UI 交互刷新时读到失效 evaluated mesh。
    mesh = eval_obj.to_mesh()
    if mesh is None:
        raise ValueError(f"{obj.name} evaluated mesh 读取失败")
    try:
        return _mesh_world_pose_from_data(eval_obj, mesh)
    finally:
        eval_obj.to_mesh_clear()


def _mesh_world_pose_from_data(eval_obj: bpy.types.Object, mesh: bpy.types.Mesh) -> tuple[np.ndarray, np.ndarray]:
    vertex_count = len(mesh.vertices)
    positions = np.empty(vertex_count * 3, dtype=np.float32)
    normals = np.empty(vertex_count * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", positions)
    mesh.vertices.foreach_get("normal", normals)
    local_positions = positions.reshape((vertex_count, 3))
    local_normals = normals.reshape((vertex_count, 3))
    matrix = math_utils.matrix_to_numpy(eval_obj.matrix_world)
    world_positions = local_positions @ matrix[:3, :3].T + matrix[:3, 3]
    world_normals = math_utils.transform_directions(matrix, local_normals)
    return (
        np.ascontiguousarray(world_positions, dtype=np.float32),
        np.ascontiguousarray(world_normals, dtype=np.float32),
    )


def _trim_base_pose_cache(cache: dict, frame: int) -> None:
    old_keys = []
    for key in cache:
        if not isinstance(key, tuple) or len(key) != 4 or key[0] != _BASE_POSE_CACHE_PREFIX:
            continue
        if abs(int(key[3]) - int(frame)) > 3:
            old_keys.append(key)
    for key in old_keys:
        cache.pop(key, None)


def read_key_positions(key: bpy.types.ShapeKey, vertex_count: int) -> np.ndarray:
    values = np.empty(vertex_count * 3, dtype=np.float32)
    key.data.foreach_get("co", values)
    return values.reshape((vertex_count, 3))


def read_rest_positions(obj: bpy.types.Object) -> np.ndarray:
    mesh = obj.data
    vertex_count = len(mesh.vertices)
    shape_keys = mesh.shape_keys
    if shape_keys is not None and shape_keys.reference_key is not None:
        return read_key_positions(shape_keys.reference_key, vertex_count)

    values = np.empty(vertex_count * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", values)
    return values.reshape((vertex_count, 3))


def local_positions_to_world(obj: bpy.types.Object, positions: np.ndarray) -> np.ndarray:
    matrix = math_utils.matrix_to_numpy(obj.matrix_world)
    values = np.ascontiguousarray(positions, dtype=np.float32)
    return np.ascontiguousarray(values @ matrix[:3, :3].T + matrix[:3, 3], dtype=np.float32)


def world_positions_to_local(obj: bpy.types.Object, positions: np.ndarray) -> np.ndarray:
    matrix = math_utils.matrix_to_numpy(obj.matrix_world.inverted())
    values = np.ascontiguousarray(positions, dtype=np.float32)
    return np.ascontiguousarray(values @ matrix[:3, :3].T + matrix[:3, 3], dtype=np.float32)


def clear_delta_attribute(obj: bpy.types.Object) -> None:
    _clear_delta_attribute(obj, MC2_DELTA_SPEC)


def write_world_delta_attribute(
    obj: bpy.types.Object,
    display_positions: np.ndarray,
    base_positions: np.ndarray,
) -> None:
    _write_world_delta_attribute(obj, MC2_DELTA_SPEC, display_positions, base_positions)


def cache_frame(cache) -> int | None:
    state = getattr(cache, "state", cache)
    cache = state if isinstance(state, dict) else cache
    if not isinstance(cache, dict) or "frame" not in cache:
        return None
    try:
        return int(cache.get("frame"))
    except Exception:
        return None
