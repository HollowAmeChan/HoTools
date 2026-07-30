"""HoTools 各模块共用的形态键数据、顺序与依赖关系工具。"""

from collections.abc import Iterable, Sequence

import bpy
import numpy as np


class ShapeKeyUtilsError(ValueError):
    """形态键公共操作收到无效对象、数据或顺序时抛出。"""


class ShapeKeyDependencyError(ShapeKeyUtilsError):
    """相对形态键依赖缺失或形成循环时抛出。"""


_COPYABLE_SETTINGS = (
    "slider_min",
    "slider_max",
    "value",
    "mute",
    "lock_shape",
    "vertex_group",
    "interpolation",
)


def require_shape_keys(obj, minimum: int = 1):
    """取得网格物体的形态键数据，不满足要求时给出统一异常。"""
    if obj is None or getattr(obj, "type", None) != 'MESH':
        raise ShapeKeyUtilsError("对象不是网格")
    shape_keys = getattr(obj.data, "shape_keys", None)
    if shape_keys is None or len(shape_keys.key_blocks) < minimum:
        raise ShapeKeyUtilsError(f"对象至少需要 {minimum} 个形态键")
    return shape_keys


def ensure_basis_shape_key(obj, name: str = "Basis"):
    """确保网格物体存在 Basis，并返回真实的参考形态键。"""
    if obj is None or getattr(obj, "type", None) != 'MESH':
        raise ShapeKeyUtilsError("对象不是网格")
    shape_keys = getattr(obj.data, "shape_keys", None)
    if shape_keys is None:
        obj.shape_key_add(name=name, from_mix=False)
        shape_keys = obj.data.shape_keys
    basis = shape_keys.reference_key
    if basis is None:
        raise ShapeKeyUtilsError("形态键数据缺少参考键")
    return basis


def read_shape_key_positions(key_block, dtype=np.float32) -> np.ndarray:
    """批量读取形态键坐标，返回独立的 ``(顶点数, 3)`` 数组。"""
    if key_block is None or not hasattr(key_block, "data"):
        raise ShapeKeyUtilsError("形态键数据块无效")
    positions = np.empty(len(key_block.data) * 3, dtype=dtype)
    key_block.data.foreach_get("co", positions)
    return positions.reshape((-1, 3))


def write_shape_key_positions(key_block, positions) -> int:
    """校验并批量写入形态键坐标，返回写入的顶点数。"""
    if key_block is None or not hasattr(key_block, "data"):
        raise ShapeKeyUtilsError("形态键数据块无效")
    array = np.asarray(positions, dtype=np.float32)
    expected_shape = (len(key_block.data), 3)
    if array.shape != expected_shape:
        raise ShapeKeyUtilsError(
            f"形态键坐标形状应为 {expected_shape}，实际为 {array.shape}"
        )
    if not np.all(np.isfinite(array)):
        raise ShapeKeyUtilsError("形态键坐标包含 NaN 或无穷值")
    key_block.data.foreach_set("co", np.ascontiguousarray(array).reshape(-1))
    return len(array)


def copy_shape_key_positions(source, target) -> int:
    """批量复制两个等长形态键的全部坐标。"""
    if source is None or target is None:
        raise ShapeKeyUtilsError("源形态键或目标形态键无效")
    if len(source.data) != len(target.data):
        raise ShapeKeyUtilsError(
            f"形态键顶点数不一致：{len(source.data)} != {len(target.data)}"
        )
    return write_shape_key_positions(target, read_shape_key_positions(source))


def copy_shape_key_settings(
        source, target, *, include_relative_key: bool = True) -> tuple[str, ...]:
    """复制通用设置；跨形态键数据块时不会复制无效的相对键引用。"""
    if source is None or target is None:
        raise ShapeKeyUtilsError("源形态键或目标形态键无效")

    copied = []
    # 先扩张目标范围再收缩到源范围，避免 Blender 在赋值中途钳制 value。
    if all(hasattr(key, "slider_min") and hasattr(key, "slider_max")
           for key in (source, target)):
        target.slider_min = min(target.slider_min, source.slider_min)
        target.slider_max = max(target.slider_max, source.slider_max)

    for attribute in _COPYABLE_SETTINGS:
        if not hasattr(source, attribute) or not hasattr(target, attribute):
            continue
        try:
            setattr(target, attribute, getattr(source, attribute))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ShapeKeyUtilsError(
                f"无法复制形态键设置 {attribute}：{exc}"
            ) from exc
        copied.append(attribute)

    if (
        include_relative_key
        and getattr(source, "id_data", None) == getattr(target, "id_data", None)
        and hasattr(source, "relative_key")
        and hasattr(target, "relative_key")
    ):
        target.relative_key = source.relative_key
        copied.append("relative_key")
    return tuple(copied)


def _move_active_shape_key(obj, target_index: int) -> None:
    current_index = obj.active_shape_key_index
    while current_index < target_index:
        result = bpy.ops.object.shape_key_move(type='DOWN')
        if result != {'FINISHED'}:
            raise ShapeKeyUtilsError("向下移动形态键失败")
        current_index += 1
    while current_index > target_index:
        result = bpy.ops.object.shape_key_move(type='UP')
        if result != {'FINISHED'}:
            raise ShapeKeyUtilsError("向上移动形态键失败")
        current_index -= 1


def move_shape_key_to_index(obj, key_name: str, target_index: int) -> bool:
    """把指定形态键移动到目标索引，并让它保持活动。"""
    shape_keys = require_shape_keys(obj)
    key_blocks = shape_keys.key_blocks
    current_index = key_blocks.find(key_name)
    if current_index < 0:
        return False

    target_index = max(0, min(int(target_index), len(key_blocks) - 1))
    basis = shape_keys.reference_key
    key = key_blocks[current_index]
    if key == basis and target_index != 0:
        raise ShapeKeyUtilsError("参考形态键必须保持在第一个位置")
    if key != basis and target_index == 0:
        raise ShapeKeyUtilsError("普通形态键不能移动到参考键之前")
    with bpy.context.temp_override(object=obj, active_object=obj):
        obj.active_shape_key_index = current_index
        _move_active_shape_key(obj, target_index)
    obj.active_shape_key_index = target_index
    return True


def reorder_shape_keys(
        obj, ordered_names: Sequence[str], *, active_key_name: str | None = None,
) -> None:
    """严格按名称重排全部形态键，并默认恢复原活动键。"""
    shape_keys = require_shape_keys(obj)
    key_blocks = shape_keys.key_blocks
    requested = list(ordered_names)
    current = [key.name for key in key_blocks]
    if len(requested) != len(set(requested)):
        raise ShapeKeyUtilsError("目标形态键顺序包含重名")
    if set(requested) != set(current) or len(requested) != len(current):
        missing = [name for name in current if name not in requested]
        unknown = [name for name in requested if name not in current]
        details = []
        if missing:
            details.append(f"缺少：{'、'.join(missing)}")
        if unknown:
            details.append(f"不存在：{'、'.join(unknown)}")
        raise ShapeKeyUtilsError("目标形态键顺序不完整；" + "；".join(details))
    basis = shape_keys.reference_key
    if basis is None or requested[0] != basis.name:
        raise ShapeKeyUtilsError("参考形态键必须保持在第一个位置")

    if active_key_name is None:
        active_key = obj.active_shape_key
        active_key_name = active_key.name if active_key is not None else None
    elif active_key_name not in current:
        raise ShapeKeyUtilsError(f"要恢复的活动形态键不存在：{active_key_name}")

    with bpy.context.temp_override(object=obj, active_object=obj):
        for target_index, target_name in enumerate(requested):
            current_index = key_blocks.find(target_name)
            if current_index == target_index:
                continue
            obj.active_shape_key_index = current_index
            _move_active_shape_key(obj, target_index)

    if active_key_name is not None:
        obj.active_shape_key_index = key_blocks.find(active_key_name)


def validate_shape_key_vertex_counts(shape_keys, expected_count: int | None = None) -> int:
    """校验同一组形态键顶点数一致，并返回统一的顶点数。"""
    if shape_keys is None or not hasattr(shape_keys, "key_blocks"):
        raise ShapeKeyUtilsError("形态键数据无效")
    key_blocks = shape_keys.key_blocks
    if len(key_blocks) == 0:
        raise ShapeKeyUtilsError("形态键数据为空")
    if expected_count is None:
        expected_count = len(key_blocks[0].data)
    for key in key_blocks:
        if len(key.data) != expected_count:
            raise ShapeKeyUtilsError(
                f"形态键 {key.name} 的顶点数应为 {expected_count}，实际为 {len(key.data)}"
            )
    return expected_count


def relative_shape_key_order(
        shape_keys, excluded: Iterable = (),
) -> tuple:
    """按父相对键在前的顺序返回非 Basis 形态键，并检测缺失和循环。"""
    if shape_keys is None or not hasattr(shape_keys, "key_blocks"):
        raise ShapeKeyDependencyError("形态键数据无效")
    keys = list(shape_keys.key_blocks)
    keys_by_name = {key.name: key for key in keys}
    excluded_names = {key.name for key in excluded if key is not None}
    basis = shape_keys.reference_key
    if basis is not None:
        excluded_names.add(basis.name)

    state = {}
    result = []

    def visit(key):
        if key.name in excluded_names:
            return
        current_state = state.get(key.name, 0)
        if current_state == 2:
            return
        if current_state == 1:
            raise ShapeKeyDependencyError(f"形态键相对关系存在循环：{key.name}")

        state[key.name] = 1
        relative = key.relative_key
        if relative is None:
            raise ShapeKeyDependencyError(f"形态键 {key.name} 缺少相对键")
        relative_in_group = keys_by_name.get(relative.name)
        same_relative = relative_in_group is not None
        if same_relative and hasattr(relative_in_group, "as_pointer"):
            same_relative = (
                relative_in_group.as_pointer() == relative.as_pointer()
            )
        if not same_relative:
            raise ShapeKeyDependencyError(f"找不到 {key.name} 的相对键 {relative.name}")
        visit(relative)
        state[key.name] = 2
        result.append(key)

    for key in keys:
        visit(key)
    return tuple(result)


def mesh_triangle_indices(mesh) -> np.ndarray:
    """返回网格循环三角面的 ``(三角面数, 3)`` 顶点索引数组。"""
    if mesh is None or not hasattr(mesh, "calc_loop_triangles"):
        raise ShapeKeyUtilsError("网格数据无效")
    mesh.calc_loop_triangles()
    triangles = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    if len(triangles) > 0:
        mesh.loop_triangles.foreach_get("vertices", triangles)
    return triangles.reshape((-1, 3))
