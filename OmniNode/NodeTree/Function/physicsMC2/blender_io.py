"""MC2 Python 后端的 Blender I/O 边界。"""

import bpy
import numpy as np

from . import math_utils


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


def restore_rest_to_shape_key(obj: bpy.types.Object, shape_key: bpy.types.ShapeKey, state=None) -> None:
    rest_positions = None
    if isinstance(state, dict):
        cached_rest = state.get("rest_local_positions")
        if isinstance(cached_rest, np.ndarray) and cached_rest.shape == (len(obj.data.vertices), 3):
            rest_positions = cached_rest
    if rest_positions is None:
        rest_positions = read_rest_positions(obj)
    write_shape_key_positions(obj, shape_key, rest_positions)


def cache_frame(cache) -> int | None:
    if not isinstance(cache, dict) or "frame" not in cache:
        return None
    try:
        return int(cache.get("frame"))
    except Exception:
        return None
