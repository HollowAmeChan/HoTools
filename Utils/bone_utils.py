"""HoTools 各骨骼模块共用的命名、对称与 Blender 状态工具。"""

import bpy
from mathutils import Matrix, Vector

from .bone_selection import select_bones, selected_bone_names, selected_mode_bones


# 保留原有语义名，直接引用选择兼容层的函数对象，不再转发调用。
selected_bones = selected_mode_bones


def clear_edit_bone_local_rotations(edit_bones, bone_names) -> int:
    """Make selected rest orientations match their final parents for FBX export."""
    bones = [edit_bones.get(name) for name in bone_names]
    bones = [bone for bone in bones if bone is not None]

    def ancestor_depth(bone):
        depth = 0
        parent = bone.parent
        while parent is not None:
            depth += 1
            parent = parent.parent
        return depth

    # A selected parent must reach its final orientation before its child copies it.
    bones.sort(key=ancestor_depth)
    changed = 0
    for bone in bones:
        for child in bone.children:
            child.use_connect = False

        original_length = bone.length
        if original_length <= 1e-8:
            continue

        parent = bone.parent
        parent_direction = parent.tail - parent.head if parent is not None else None
        if parent_direction is not None and parent_direction.length > 1e-8:
            # Equal armature-space orientations produce an identity parent-relative
            # rest rotation, which is the local bone rotation serialized by FBX.
            bone.tail = bone.head + parent_direction.normalized() * original_length
            bone.roll = parent.roll
        else:
            # Preserve the established vertical convention for roots.
            bone.tail = bone.head + Vector((0.0, 0.0, original_length))
            bone.roll = 0.0
        changed += 1
    return changed


def clear_pose_bone_transform(pose_bone) -> None:
    """Reset one pose bone's local location, rotation, and scale."""
    pose_bone.location = (0.0, 0.0, 0.0)
    pose_bone.scale = (1.0, 1.0, 1.0)
    if pose_bone.rotation_mode == 'QUATERNION':
        pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    elif pose_bone.rotation_mode == 'AXIS_ANGLE':
        pose_bone.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
    else:
        pose_bone.rotation_euler = (0.0, 0.0, 0.0)
    pose_bone.matrix_basis = Matrix.Identity(4)


def clear_pose_bone_transforms(armature, bone_names) -> int:
    """Reset pose transforms by bone name and return the number changed."""
    if armature.pose is None:
        return 0
    count = 0
    for bone_name in bone_names:
        pose_bone = armature.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        clear_pose_bone_transform(pose_bone)
        count += 1
    return count


_SIDE_SEPARATORS = "._-"
_SIDE_LETTERS = "LRlr"

# 所有 HoTools 辅助骨约束都使用这个前缀。
AUX_CONSTRAINT_PREFIX = "HoTools"


def aux_constraint_name(aux_type: str, kind: str) -> str:
    """按 HoTools_<AUX>_<KIND> 格式生成辅助骨约束名。"""
    return f"{AUX_CONSTRAINT_PREFIX}_{aux_type}_{kind}"


def split_side_suffix(name: str) -> tuple[str, str]:
    """把骨名拆成（主干，方向后缀），无后缀时返回空字符串。"""
    if (
        len(name) >= 2
        and name[-2] in _SIDE_SEPARATORS
        and name[-1] in _SIDE_LETTERS
    ):
        return name[:-2], name[-2:]
    return name, ""


def has_side_suffix(name: str) -> bool:
    """骨名是否带 .L、_R 或 -l 这类方向后缀。"""
    return split_side_suffix(name)[1] != ""


def pair_side_suffix(*names: str) -> str:
    """返回一组骨名中第一个有效的方向后缀。"""
    for name in names:
        suffix = split_side_suffix(name)[1]
        if suffix:
            return suffix
    return ""


def require_same_side(*names: str, expected: str | None = None) -> str:
    """严格解析多根骨的 L/R 后缀，并要求全部属于同一侧。"""
    if len(names) < 2:
        raise ValueError("左右判定至少需要两根骨")

    sides = []
    for name in names:
        _stem, suffix = split_side_suffix(name)
        if not suffix:
            raise ValueError(
                f"无法从骨骼 {name} 判定左右；名称必须以 .L/.R、_L/_R 或 -L/-R 结尾"
            )
        sides.append(suffix[-1].upper())

    if len(set(sides)) != 1:
        detail = ", ".join(
            f"{name}={side}" for name, side in zip(names, sides)
        )
        raise ValueError(f"角色骨左右侧不一致：{detail}")

    side = sides[0]
    if expected is not None and expected != side:
        raise ValueError(
            f"传入侧别 {expected} 与角色骨解析结果 {side} 不一致"
        )
    return side


def mirrored_role_names(armature_data, *names: str) -> tuple[str, ...]:
    """严格取得一组角色骨的对侧名称，缺失或无法翻转时报错。"""
    source_side = require_same_side(*names)
    mirrored = []
    for name in names:
        flipped = bpy.utils.flip_name(name)
        if flipped == name:
            raise ValueError(f"骨骼 {name} 无法翻转到对称侧")
        if armature_data.bones.get(flipped) is None:
            raise ValueError(f"找不到对称骨 {flipped}")
        mirrored.append(flipped)

    mirrored_side = require_same_side(*mirrored)
    if mirrored_side == source_side:
        raise ValueError("镜像角色骨没有切换到对侧")
    return tuple(mirrored)


def find_suffixless(bone_names) -> list[str]:
    """按原顺序返回不带方向后缀的骨名。"""
    return [name for name in bone_names if not has_side_suffix(name)]


def get_mirrored_bone(bone_name: str, armature_data) -> list[str]:
    """返回 [本骨] 或 [本骨, 镜像骨]，镜像骨必须真实存在。"""
    names = [bone_name]
    mirrored_name = bpy.utils.flip_name(bone_name)
    bone_container = getattr(armature_data, "bones", armature_data)
    if mirrored_name != bone_name and bone_container.get(mirrored_name):
        names.append(mirrored_name)
    return names


def mirror_pair(armature: bpy.types.Object, pair_names) -> list[str] | None:
    """将一对骨名整体翻转到对侧，无合法镜像对时返回 None。"""
    if armature.mode == "EDIT":

        def bone_exists(name):
            return armature.data.edit_bones.get(name) is not None

    else:

        def bone_exists(name):
            return armature.pose.bones.get(name) is not None

    mirrored = []
    for name in pair_names:
        flipped = bpy.utils.flip_name(name)
        if flipped == name or not bone_exists(flipped):
            return None
        mirrored.append(flipped)

    if len(set(mirrored)) != 2:
        return None
    if set(mirrored) == set(pair_names):
        return None
    return mirrored


def set_object_mode(obj, mode):
    """设置物体模式，并在可用时通过 VIEW_3D 上下文调用操作符。"""
    context = bpy.context
    view3d_context = context.copy()
    screen = context.screen
    if screen is not None:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for region in area.regions:
                if region.type == "WINDOW":
                    view3d_context = {
                        "area": area,
                        "region": region,
                        "window": context.window,
                        "screen": screen,
                        "active_object": obj,
                    }

    if "area" in view3d_context and "region" in view3d_context:
        if hasattr(context, "temp_override"):
            with context.temp_override(**view3d_context):
                bpy.ops.object.mode_set(mode=mode)
        else:
            bpy.ops.object.mode_set(view3d_context, mode=mode)
    else:
        bpy.ops.object.mode_set(mode=mode)


def find_deforming_armatures_for_object(
    obj: bpy.types.Object,
) -> tuple[bpy.types.Object, ...]:
    """查找真正形变该物体的骨架，可能返回多个修改器目标。"""
    if obj is None:
        return ()
    if obj.type == "ARMATURE":
        return (obj,)

    # 修改器是明确绑定关系，优先于场景层级；保留修改器栈顺序并去重。
    armatures = []
    seen = set()
    for modifier in obj.modifiers:
        if modifier.type != "ARMATURE":
            continue
        armature = modifier.object
        if armature is None or armature.type != "ARMATURE":
            continue
        pointer = armature.as_pointer()
        if pointer in seen:
            continue
        seen.add(pointer)
        armatures.append(armature)
    parent = obj.parent
    if (
        parent is not None
        and obj.parent_type == "ARMATURE"
        and parent.type == "ARMATURE"
    ):
        pointer = parent.as_pointer()
        if pointer not in seen:
            armatures.append(parent)
    return tuple(armatures)


def find_armatures_for_object(obj: bpy.types.Object) -> tuple[bpy.types.Object, ...]:
    """查找物体所属的骨架，显式形变关系优先于父级资产层级。"""
    if obj is None:
        return ()

    armatures = find_deforming_armatures_for_object(obj)
    if armatures:
        return armatures

    # 游戏资产常在骨架与网格之间插入多层 LOD Empty，内置 find_armature 不会穿透它们。
    parent = obj.parent
    visited = set()
    while parent is not None:
        pointer = parent.as_pointer()
        if pointer in visited:
            break
        visited.add(pointer)
        if parent.type == "ARMATURE":
            return (parent,)
        parent = parent.parent
    return ()


def find_armature_for_object(obj: bpy.types.Object) -> bpy.types.Object | None:
    """仅在物体能唯一确定一个骨架时返回它，歧义时返回 None。"""
    armatures = find_armatures_for_object(obj)
    return armatures[0] if len(armatures) == 1 else None


def find_deforming_armature_for_object(
    obj: bpy.types.Object,
) -> bpy.types.Object | None:
    """仅在物体能唯一确定一个形变骨架时返回它，歧义时返回 None。"""
    armatures = find_deforming_armatures_for_object(obj)
    return armatures[0] if len(armatures) == 1 else None


def deform_group_indices_for_object(obj: bpy.types.Object) -> set[int]:
    """获取对象所有形变骨架驱动的顶点组索引。

    Blender 4.5 不再提供顶点组算子的 ``BONE_DEFORM`` 子集，因此这里按
    实际骨架关联和 ``Bone.use_deform`` 重建同样的过滤范围，不能仅凭名称
    匹配就把顶点组认定为形变组。
    """
    if obj is None or obj.type != "MESH":
        return set()

    deform_bone_names = {
        bone.name
        for armature in find_deforming_armatures_for_object(obj)
        for bone in armature.data.bones
        if bone.use_deform
    }
    return {
        group.index
        for group in obj.vertex_groups
        if group.name in deform_bone_names
    }


def limit_deform_weights(
    obj: bpy.types.Object,
    limit: int,
    *,
    selected_only: bool = False,
) -> int:
    """每个顶点最多保留 ``limit`` 个形变权重，并返回删除数量。

    非形变组和锁定组保持不变；同时支持物体模式和编辑模式，用于替代
    Blender 4.5 中已移除的 ``group_select_mode='BONE_DEFORM'``。
    """
    if obj is None or obj.type != "MESH":
        return 0
    group_indices = deform_group_indices_for_object(obj)
    if not group_indices:
        return 0
    limit = max(1, int(limit))
    locked = {
        group.index for group in obj.vertex_groups
        if group.lock_weight and group.index in group_indices
    }

    if obj.mode == "EDIT":
        import bmesh

        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        deform_layer = bm.verts.layers.deform.verify()
        vertices = (vert for vert in bm.verts if not selected_only or vert.select)
        removed = 0
        for vert in vertices:
            weights = vert[deform_layer]
            candidates = [
                (group_index, weight)
                for group_index, weight in weights.items()
                if group_index in group_indices and group_index not in locked
            ]
            keep_count = sum(group_index in locked for group_index in weights)
            remove_count = max(0, keep_count + len(candidates) - limit)
            for group_index, _weight in sorted(candidates, key=lambda item: item[1])[:remove_count]:
                del weights[group_index]
                removed += 1
        bmesh.update_edit_mesh(mesh)
        return removed

    removed = 0
    vertices = (vert for vert in obj.data.vertices if not selected_only or vert.select)
    for vert in vertices:
        candidates = [
            (assignment.group, assignment.weight)
            for assignment in vert.groups
            if assignment.group in group_indices and assignment.group not in locked
        ]
        keep_count = sum(
            assignment.group in locked and assignment.group in group_indices
            for assignment in vert.groups
        )
        remove_count = max(0, keep_count + len(candidates) - limit)
        for group_index, _weight in sorted(candidates, key=lambda item: item[1])[:remove_count]:
            obj.vertex_groups[group_index].remove([vert.index])
            removed += 1
    return removed


def object_uses_armature(
    obj: bpy.types.Object,
    armature_obj: bpy.types.Object,
) -> bool:
    """判断物体是否按统一解析规则关联到指定骨架。"""
    return armature_obj in find_armatures_for_object(obj)


def object_is_deformed_by_armature(
    obj: bpy.types.Object,
    armature_obj: bpy.types.Object,
) -> bool:
    """判断物体是否确实通过修改器或 Armature Parenting 被指定骨架形变。"""
    return armature_obj in find_deforming_armatures_for_object(obj)


def collect_mesh_objects_for_armature(
    armature_obj: bpy.types.Object,
) -> list[bpy.types.Object]:
    """收集由指定骨架真正形变的所有网格物体。"""
    return [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH" and object_is_deformed_by_armature(obj, armature_obj)
    ]


def set_temp_mesh_mirror_off(obj: bpy.types.Object) -> dict:
    """临时关闭网格的 X/Y/Z 镜像，并返回可恢复的原状态。"""
    mirror_state = {}
    for property_name in (
        "use_mesh_mirror_x",
        "use_mesh_mirror_y",
        "use_mesh_mirror_z",
    ):
        owner = None
        if hasattr(obj, property_name):
            owner = obj
        elif getattr(obj, "data", None) is not None and hasattr(
            obj.data,
            property_name,
        ):
            owner = obj.data

        if owner is None:
            continue

        mirror_state[property_name] = (owner, getattr(owner, property_name))
        setattr(owner, property_name, False)
    return mirror_state


def restore_mesh_mirror_state(mirror_state: dict) -> None:
    """恢复 set_temp_mesh_mirror_off 保存的网格镜像状态。"""
    for property_name, (owner, value) in mirror_state.items():
        setattr(owner, property_name, value)


def set_temp_armature_mirror_off(armature: bpy.types.Object) -> dict:
    """临时关闭骨架数据和姿态的 X 轴镜像，并返回原状态。"""
    mirror_state = {}

    data = getattr(armature, "data", None)
    if data is not None and hasattr(data, "use_mirror_x"):
        mirror_state["data.use_mirror_x"] = (data, data.use_mirror_x)
        data.use_mirror_x = False

    pose = getattr(armature, "pose", None)
    if pose is not None and hasattr(pose, "use_mirror_x"):
        mirror_state["pose.use_mirror_x"] = (pose, pose.use_mirror_x)
        pose.use_mirror_x = False

    return mirror_state


def restore_armature_mirror_state(mirror_state: dict) -> None:
    """恢复 set_temp_armature_mirror_off 保存的骨架镜像状态。"""
    for _key, (owner, value) in mirror_state.items():
        owner.use_mirror_x = value


def ensure_bone_collection(armature: bpy.types.Object, collection_name: str):
    """取得或创建骨骼集合，集合名为空或版本不支持时返回 None。"""
    if not collection_name:
        return None

    collections = getattr(armature.data, "collections", None)
    if collections is None:
        return None

    collection = collections.get(collection_name)
    if collection is None:
        collection = collections.new(collection_name)
    return collection


def assign_bones_to_collection(
    armature: bpy.types.Object,
    bone_names,
    collection_name: str,
) -> None:
    """在编辑模式下将指定骨骼从原集合移至目标集合。"""
    collection = ensure_bone_collection(armature, collection_name)
    if collection is None:
        return

    edit_bones = armature.data.edit_bones
    for bone_name in bone_names:
        bone = edit_bones.get(bone_name)
        if bone is None:
            continue
        replace_bone_collections(bone, [collection])


def replace_bone_collections(target_bone, collections) -> None:
    """清除骨骼当前集合，并精确替换为给定集合。"""
    target_collections = getattr(target_bone, "collections", None)
    if target_collections is None:
        return

    new_collections = list(collections)
    for collection in list(target_collections):
        collection.unassign(target_bone)
    for collection in new_collections:
        collection.assign(target_bone)


def inherit_bone_collections(source_bone, target_bone) -> None:
    """清除目标骨的默认集合，并完整继承源骨的集合成员关系。"""
    if source_bone is None or source_bone == target_bone:
        return

    replace_bone_collections(
        target_bone,
        getattr(source_bone, "collections", ()) or (),
    )


def bone_head_tail(bone):
    """返回 EditBone 或 PoseBone 的 head/tail 坐标副本。"""
    if hasattr(bone, "head") and hasattr(bone, "tail"):
        return bone.head.copy(), bone.tail.copy()
    if hasattr(bone, "bone") and hasattr(bone, "matrix"):
        rest_bone = bone.bone
        head = bone.matrix.translation.copy()
        tail = bone.matrix @ Vector((0.0, rest_bone.length, 0.0))
        return head, tail
    raise Exception("不支持的骨骼类型")


__all__ = [
    "AUX_CONSTRAINT_PREFIX",
    "assign_bones_to_collection",
    "aux_constraint_name",
    "bone_head_tail",
    "collect_mesh_objects_for_armature",
    "ensure_bone_collection",
    "find_armature_for_object",
    "find_armatures_for_object",
    "deform_group_indices_for_object",
    "find_deforming_armature_for_object",
    "find_deforming_armatures_for_object",
    "find_suffixless",
    "get_mirrored_bone",
    "has_side_suffix",
    "inherit_bone_collections",
    "limit_deform_weights",
    "mirror_pair",
    "mirrored_role_names",
    "object_is_deformed_by_armature",
    "object_uses_armature",
    "pair_side_suffix",
    "replace_bone_collections",
    "require_same_side",
    "restore_armature_mirror_state",
    "restore_mesh_mirror_state",
    "select_bones",
    "selected_bone_names",
    "selected_bones",
    "selected_mode_bones",
    "set_object_mode",
    "set_temp_armature_mirror_off",
    "set_temp_mesh_mirror_off",
    "split_side_suffix",
]
