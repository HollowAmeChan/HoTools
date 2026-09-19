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


def active_relative_shape_key(obj):
    """返回活动形态键直接引用的相对键；Basis 或无效状态返回 ``None``。"""
    if obj is None or getattr(obj, "type", None) != 'MESH':
        return None
    shape_keys = getattr(obj.data, "shape_keys", None)
    active_key = getattr(obj, "active_shape_key", None)
    if shape_keys is None or active_key is None:
        return None
    relative_key = getattr(active_key, "relative_key", None)
    if relative_key is None or relative_key == active_key:
        return None
    return relative_key


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


def _is_bake_modifier(modifier, *, include_render_only: bool, keep_armature: bool) -> bool:
    """判断某个修改器是否要被“保持形态键地应用”。"""
    if keep_armature and modifier.type == 'ARMATURE':
        return False
    if bool(getattr(modifier, "show_viewport", True)):
        return True
    return include_render_only and bool(getattr(modifier, "show_render", False))


def bake_modifiers_keeping_shape_keys(
    objects,
    *,
    include_render_only: bool = False,
    keep_armature: bool = False,
) -> tuple[list[str], list[tuple[str, str]], list[tuple[str, Exception]]]:
    """就地应用修改器并保持形态键，返回 (已处理, 已跳过, 失败)。

    共用实现：修改器面板的「保持形态键应用」按钮与 FBX 导出前的隐式烘焙都调用这里，
    差别只在参数：

    - ``include_render_only``：False 只烘焙视图显示中的修改器（按钮语义，即“应用视图
      显示中的修改器”）；True 连只在渲染中显示的也一起烘焙（FBX 导出的评估口径）；
    - ``keep_armature``：False 连骨架修改器一起烘焙（按钮语义）；True 保留骨架修改器，
      交给导出做蒙皮。

    原理：Blender 不允许给带形态键的网格应用修改器，而求值网格又不带形态键
    （``bpy.data.meshes.new_from_object``，见 Blender 议题 #104714），所以：
    逐个形态键单独置 1、其余置 0，各求值一遍修改器栈，拿到该键形变后的顶点位置；
    再用基础键的求值结果替换基础网格，按原名称/相对键/设置重建全部形态键；
    最后移除已烘焙的修改器。就地完成，不新建或删除物体，物体身份与名称保持不变。

    返回：
    - 已处理：每个物体一条说明文本；
    - 已跳过：(物体名, 原因)，例如网格数据被共用、没有需要应用的修改器、各键求值后
      顶点数不一致（说明修改器拓扑依赖形态键，无法烘焙成同一套形态键）；
    - 失败：(物体名, 异常)，抛出前形态键取值与网格都已恢复原状。
    """
    baked: list[str] = []
    skipped: list[tuple[str, str]] = []
    failed: list[tuple[str, Exception]] = []

    for obj in objects:
        if obj is None or getattr(obj, "type", None) != 'MESH':
            continue
        if obj.name not in bpy.context.view_layer.objects:
            continue

        mesh = obj.data
        shape_keys = getattr(mesh, "shape_keys", None)
        if shape_keys is None or len(shape_keys.key_blocks) < 2:
            continue

        bake_modifiers = [
            modifier
            for modifier in obj.modifiers
            if _is_bake_modifier(
                modifier,
                include_render_only=include_render_only,
                keep_armature=keep_armature,
            )
        ]
        if not bake_modifiers:
            skipped.append((obj.name, "没有需要应用的修改器"))
            continue
        if mesh.users > 1:
            skipped.append((obj.name, f"网格数据被 {mesh.users} 个物体共用，无法就地替换"))
            continue

        key_blocks = list(shape_keys.key_blocks)
        key_states = [
            {
                "name": block.name,
                "value": block.value,
                "mute": block.mute,
                "relative_key": getattr(getattr(block, "relative_key", None), "name", None),
            }
            for block in key_blocks
        ]
        use_relative = bool(getattr(shape_keys, "use_relative", True))
        active_index = getattr(shape_keys, "active_index", None)
        replaced_mesh = False
        base_mesh = None

        def restore_key_values():
            """把被求值过程改动的形态键取值恢复原样。"""
            if replaced_mesh:
                return
            for block, state in zip(key_blocks, key_states):
                if block.name != state["name"]:
                    continue
                block.value = state["value"]
                block.mute = state["mute"]

        try:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            positions: dict[str, np.ndarray] = {}
            vertex_counts = set()

            for index, block in enumerate(key_blocks):
                for other_index, other in enumerate(key_blocks):
                    other.value = 1.0 if other_index == index else 0.0
                bpy.context.view_layer.update()

                eval_mesh = bpy.data.meshes.new_from_object(
                    obj.evaluated_get(depsgraph),
                    preserve_all_data_layers=True,
                    depsgraph=depsgraph,
                )
                coords = np.empty(len(eval_mesh.vertices) * 3, dtype=np.float32)
                eval_mesh.vertices.foreach_get("co", coords)
                positions[block.name] = coords
                vertex_counts.add(len(eval_mesh.vertices))
                if index == 0:
                    base_mesh = eval_mesh  # 基础键的求值结果直接作为新基础网格
                elif eval_mesh.users == 0:
                    bpy.data.meshes.remove(eval_mesh)

            restore_key_values()

            if len(vertex_counts) != 1:
                if base_mesh is not None and base_mesh.users == 0:
                    bpy.data.meshes.remove(base_mesh)
                skipped.append((
                    obj.name,
                    "各形态键求值后的顶点数不一致 "
                    f"{sorted(vertex_counts)}（修改器拓扑依赖形态键，点序/点数对不上）",
                ))
                continue

            # 用求值结果替换基础网格，并按原名重建形态键
            obj.data = base_mesh
            replaced_mesh = True
            for state in key_states:
                new_block = obj.shape_key_add(name=state["name"], from_mix=False)
                write_shape_key_positions(
                    new_block, positions[state["name"]].reshape((-1, 3))
                )
            new_shape_keys = obj.data.shape_keys
            for source, state in zip(key_blocks, key_states):
                target = new_shape_keys.key_blocks.get(state["name"])
                if source is None or target is None:
                    continue
                copy_shape_key_settings(source, target, include_relative_key=False)
                target.value = state["value"]
                target.mute = state["mute"]
            try:
                new_shape_keys.use_relative = use_relative
            except (AttributeError, TypeError):
                pass
            # 相对键要在全部键都建好之后再按名字连回去
            for state in key_states:
                relative_name = state["relative_key"]
                if not relative_name or relative_name == state["name"]:
                    continue
                target = new_shape_keys.key_blocks.get(state["name"])
                relative = new_shape_keys.key_blocks.get(relative_name)
                if target is not None and relative is not None:
                    target.relative_key = relative
            if active_index is not None and hasattr(new_shape_keys, "active_index"):
                try:
                    new_shape_keys.active_index = min(
                        int(active_index), len(key_states) - 1
                    )
                except (AttributeError, TypeError, ValueError):
                    pass

            # 移除已烘焙的修改器（隐藏的、以及 keep_armature 保留的骨架修改器不动）
            removed_names = []
            for modifier in bake_modifiers:
                name = getattr(modifier, "name", None)
                current = obj.modifiers.get(name) if name else None
                if current is None:
                    continue
                try:
                    obj.modifiers.remove(current)
                except (ReferenceError, RuntimeError):
                    continue
                removed_names.append(name)

            baked.append(
                f"{obj.name}（顶点 {len(obj.data.vertices)}，形态键 {len(key_states)}，"
                f"已应用修改器 {removed_names or '无'}）"
            )
        except Exception as exc:
            restore_key_values()
            if not replaced_mesh and base_mesh is not None and base_mesh.users == 0:
                bpy.data.meshes.remove(base_mesh)
            failed.append((obj.name, exc))

    return baked, skipped, failed
