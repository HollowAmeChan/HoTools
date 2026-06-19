"""MC2 Python 后端的 Blender I/O 边界。"""

import bpy
import numpy as np
from bpy.app.handlers import persistent

from .....PhysicsTools.collisionBasePose import (
    DELTA_ATTRIBUTE_NAME,
    ensure_delta_attribute,
    ensure_delta_output,
    validate_base_pose_proxy,
)
from . import math_utils

_BASE_POSE_FRAME_CACHE = {}
_BASE_POSE_CACHE_HANDLER_REGISTERED = False


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
    if obj is None or not isinstance(obj, bpy.types.Object) or obj.type != "MESH":
        raise ValueError(f"{label} 不是 Mesh 对象")
    if obj.data is None or len(obj.data.vertices) == 0:
        raise ValueError(f"{label} mesh 没有顶点")
    return obj


def output_shape_key_name(obj: bpy.types.Object) -> str:
    props = getattr(obj, "hotools_mesh_collision", None)
    name = str(getattr(props, "output_shape_key", "") or "").strip()
    return name or "MC2MeshCloth"


def base_pose_proxy_object(obj: bpy.types.Object) -> bpy.types.Object | None:
    props = getattr(obj, "hotools_mesh_collision", None)
    proxy = getattr(props, "mc2_base_pose_proxy", None) if props is not None else None
    if proxy is None:
        return None
    if proxy == obj:
        raise ValueError("MC2 BasePose只读对象不能指向当前物理写入对象")
    if not isinstance(proxy, bpy.types.Object) or proxy.type != "MESH" or proxy.data is None:
        raise ValueError("MC2 BasePose只读对象必须是Mesh对象")
    if len(proxy.data.vertices) == 0:
        raise ValueError("MC2 BasePose只读对象没有顶点")
    if getattr(proxy, "mode", "OBJECT") != "OBJECT":
        raise ValueError("MC2 BasePose只读对象必须处于Object模式")
    validate_base_pose_proxy(obj, proxy)
    return proxy


def _base_pose_cache_key(obj: bpy.types.Object, proxy: bpy.types.Object, frame: int) -> tuple[int, int, int]:
    return (int(obj.as_pointer()), int(proxy.as_pointer()), int(frame))


def cached_base_pose_world_pose(
    obj: bpy.types.Object,
    proxy: bpy.types.Object,
    frame: int,
) -> tuple[np.ndarray, np.ndarray] | None:
    value = _BASE_POSE_FRAME_CACHE.get(_base_pose_cache_key(obj, proxy, frame))
    if value is None:
        return None
    positions, normals = value
    return positions.copy(), normals.copy()


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


def _trim_base_pose_cache(frame: int) -> None:
    old_keys = [key for key in _BASE_POSE_FRAME_CACHE if abs(int(key[2]) - int(frame)) > 3]
    for key in old_keys:
        _BASE_POSE_FRAME_CACHE.pop(key, None)


@persistent
def _cache_base_pose_on_frame_change(scene, depsgraph=None):
    frame = int(getattr(scene, "frame_current", 0) or 0)
    depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
    for obj in tuple(getattr(scene, "objects", ()) or ()):
        if obj is None or obj.type != "MESH":
            continue
        props = getattr(obj, "hotools_mesh_collision", None)
        proxy = getattr(props, "mc2_base_pose_proxy", None) if props is not None else None
        if proxy is None or proxy == obj or proxy.type != "MESH":
            continue
        try:
            validate_base_pose_proxy(obj, proxy)
            _BASE_POSE_FRAME_CACHE[_base_pose_cache_key(obj, proxy, frame)] = read_evaluated_mesh_world_pose(
                proxy,
                depsgraph,
            )
        except Exception:
            continue
    _trim_base_pose_cache(frame)


def ensure_base_pose_cache_handler() -> None:
    global _BASE_POSE_CACHE_HANDLER_REGISTERED
    handlers = bpy.app.handlers.frame_change_post
    for handler in list(handlers):
        if (
            getattr(handler, "__name__", "") == "_cache_base_pose_on_frame_change"
            and getattr(handler, "__module__", "") == __name__
            and handler is not _cache_base_pose_on_frame_change
        ):
            handlers.remove(handler)
    if _cache_base_pose_on_frame_change not in handlers:
        handlers.append(_cache_base_pose_on_frame_change)
    _BASE_POSE_CACHE_HANDLER_REGISTERED = True


def ensure_target_shape_key(obj: bpy.types.Object, shape_key_name: str) -> bpy.types.ShapeKey:
    mesh = obj.data
    if mesh.shape_keys is None:
        obj.shape_key_add(name="Basis", from_mix=False)

    shape_keys = mesh.shape_keys
    key = shape_keys.key_blocks.get(shape_key_name)
    if key is None:
        key = obj.shape_key_add(name=shape_key_name, from_mix=False)

    if key == shape_keys.reference_key:
        raise ValueError("目标 shape key 不能是 Basis/reference key")

    key.value = 1.0
    return key


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


def write_shape_key_positions(
    obj: bpy.types.Object,
    shape_key: bpy.types.ShapeKey,
    positions: np.ndarray,
) -> None:
    flat = np.ascontiguousarray(positions, dtype=np.float32).reshape(-1)
    shape_key.data.foreach_set("co", flat)
    obj.data.update()
    obj.update_tag()


def write_world_positions_to_shape_key(
    obj: bpy.types.Object,
    shape_key: bpy.types.ShapeKey,
    positions: np.ndarray,
) -> None:
    write_shape_key_positions(obj, shape_key, world_positions_to_local(obj, positions))


def clear_delta_attribute(obj: bpy.types.Object) -> None:
    attr = obj.data.attributes.get(DELTA_ATTRIBUTE_NAME) if obj is not None and obj.type == "MESH" else None
    if attr is None or attr.domain != "POINT" or attr.data_type != "FLOAT_VECTOR":
        return
    zeros = np.zeros(len(obj.data.vertices) * 3, dtype=np.float32)
    attr.data.foreach_set("vector", zeros)
    obj.data.update()
    obj.update_tag()


def write_world_delta_attribute(
    obj: bpy.types.Object,
    display_positions: np.ndarray,
    base_positions: np.ndarray,
) -> None:
    ensure_delta_output(obj)
    attr = ensure_delta_attribute(obj)
    vertex_count = len(obj.data.vertices)
    display = np.ascontiguousarray(display_positions, dtype=np.float32)
    base = np.ascontiguousarray(base_positions, dtype=np.float32)
    if display.shape != (vertex_count, 3) or base.shape != (vertex_count, 3):
        raise ValueError("MC2 后置位移写入要求 display/base 顶点数量一致")
    world_delta = np.ascontiguousarray(display - base, dtype=np.float32)
    inv_basis = math_utils.matrix_to_numpy(obj.matrix_world.inverted())[:3, :3]
    delta = np.ascontiguousarray(world_delta @ inv_basis.T, dtype=np.float32)
    attr.data.foreach_set("vector", delta.reshape(-1))
    obj.data.update()
    obj.update_tag()


def ensure_shape_key_rest(obj: bpy.types.Object, shape_key: bpy.types.ShapeKey, state=None) -> None:
    vertex_count = len(obj.data.vertices)
    if isinstance(state, dict):
        cached_rest = state.get("rest_local_positions")
        if isinstance(cached_rest, np.ndarray) and cached_rest.shape == (vertex_count, 3):
            rest_positions = cached_rest
        else:
            rest_positions = read_rest_positions(obj)
    else:
        rest_positions = read_rest_positions(obj)
    current = read_key_positions(shape_key, vertex_count)
    if current.shape == rest_positions.shape and np.allclose(current, rest_positions, rtol=0.0, atol=1e-7):
        return
    write_shape_key_positions(obj, shape_key, rest_positions)


def restore_rest_to_shape_key(obj: bpy.types.Object, shape_key: bpy.types.ShapeKey, state=None) -> None:
    rest_positions = None
    if isinstance(state, dict):
        cached_rest = state.get("rest_local_positions")
        if isinstance(cached_rest, np.ndarray) and cached_rest.shape == (len(obj.data.vertices), 3):
            rest_positions = cached_rest
    if rest_positions is None:
        rest_positions = read_rest_positions(obj)
    write_shape_key_positions(obj, shape_key, rest_positions)
    clear_delta_attribute(obj)


def cache_frame(cache) -> int | None:
    if not isinstance(cache, dict) or "frame" not in cache:
        return None
    try:
        return int(cache.get("frame"))
    except Exception:
        return None
