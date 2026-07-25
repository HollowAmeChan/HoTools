"""跨 Blender 版本的骨骼选择兼容工具。

Blender 5.0 将姿态骨骼的选择状态从 ``Bone.select`` 移到了
``PoseBone.select``。context 中的选择集合还会受到模式与区域上下文影响，因此这里只
把它们当作快速读取路径，底层选择状态仍会作为必要的回退来源。
"""

from __future__ import annotations


def _is_armature(armature) -> bool:
    return armature is not None and getattr(armature, "type", None) == "ARMATURE"


def _append_unique(items, seen_names, bone) -> None:
    name = getattr(bone, "name", None)
    if name and name not in seen_names:
        seen_names.add(name)
        items.append(bone)


def _belongs_to_armature(bone, armature) -> bool:
    owner = getattr(bone, "id_data", None)
    if owner is None or owner is armature or owner is armature.data:
        return True
    owner_pointer = getattr(owner, "as_pointer", None)
    if not callable(owner_pointer):
        return False
    for target in (armature, armature.data):
        target_pointer = getattr(target, "as_pointer", None)
        if callable(target_pointer) and owner_pointer() == target_pointer():
            return True
    return False


def selected_edit_bones(context, armature) -> list:
    """按稳定顺序返回 ``armature`` 中选中的 EditBone，并去除重复项。"""
    if not _is_armature(armature) or armature.mode != "EDIT":
        return []

    result = []
    seen_names = set()
    edit_bones = armature.data.edit_bones

    for attr in ("selected_editable_bones", "selected_bones"):
        for candidate in getattr(context, attr, None) or []:
            if not _belongs_to_armature(candidate, armature):
                continue
            bone = edit_bones.get(getattr(candidate, "name", ""))
            if bone is not None:
                _append_unique(result, seen_names, bone)

    for bone in edit_bones:
        if (
            getattr(bone, "select", False)
            or getattr(bone, "select_head", False)
            or getattr(bone, "select_tail", False)
        ):
            _append_unique(result, seen_names, bone)
    return result


def _pose_bone_is_selected(pose_bone) -> bool:
    # Blender 5.0+ 使用 PoseBone.select，Blender 4.x 使用 Bone.select。
    if hasattr(pose_bone, "select"):
        return bool(pose_bone.select)
    return bool(getattr(getattr(pose_bone, "bone", None), "select", False))


def selected_pose_bones(context, armature) -> list:
    """返回选中的 PoseBone，并支持读取切到 Object 模式后保留的选择状态。"""
    if not _is_armature(armature) or armature.pose is None:
        return []

    result = []
    seen_names = set()
    pose_bones = armature.pose.bones

    for attr in ("selected_pose_bones_from_active_object", "selected_pose_bones"):
        for candidate in getattr(context, attr, None) or []:
            if not _belongs_to_armature(candidate, armature):
                continue
            bone = pose_bones.get(getattr(candidate, "name", ""))
            if bone is not None:
                _append_unique(result, seen_names, bone)

    for bone in pose_bones:
        if _pose_bone_is_selected(bone):
            _append_unique(result, seen_names, bone)
    return result


def selected_bone_names(context, armature) -> list[str]:
    """返回编辑、姿态或物体模式下选中的骨骼名称。"""
    if not _is_armature(armature):
        return []
    if armature.mode == "EDIT":
        return [bone.name for bone in selected_edit_bones(context, armature)]

    names = [bone.name for bone in selected_pose_bones(context, armature)]
    seen_names = set(names)

    # Blender 4.x 切到 Object 模式后，保留的姿态选择仍存放在 Bone.select。
    for bone in armature.data.bones:
        if getattr(bone, "select", False) and bone.name not in seen_names:
            seen_names.add(bone.name)
            names.append(bone.name)
    return names


def selected_mode_bones(context, armature) -> list:
    """编辑模式返回 EditBone，姿态模式返回 PoseBone。"""
    if not _is_armature(armature):
        return []
    if armature.mode == "EDIT":
        return selected_edit_bones(context, armature)
    if armature.mode == "POSE":
        return selected_pose_bones(context, armature)
    return []


def selected_armature_bones(context, armature) -> list:
    """返回可重命名的 EditBone，或与选择对应的骨架数据 Bone。"""
    if not _is_armature(armature):
        return []
    if armature.mode == "EDIT":
        return selected_edit_bones(context, armature)
    return [
        bone
        for name in selected_bone_names(context, armature)
        if (bone := armature.data.bones.get(name)) is not None
    ]


def _set_pose_bone_selected(pose_bone, selected: bool) -> None:
    if hasattr(pose_bone, "select"):
        pose_bone.select = selected
        return

    bone = pose_bone.bone
    bone.select = selected
    if hasattr(bone, "select_head"):
        bone.select_head = selected
    if hasattr(bone, "select_tail"):
        bone.select_tail = selected


def select_bones(armature, names, *, extend: bool = False) -> None:
    """按名称选择骨骼，并自动使用当前 Blender 版本可用的 API。"""
    if not _is_armature(armature):
        return

    names = [name for name in names if name]
    if armature.mode == "EDIT":
        bones = armature.data.edit_bones
        if not extend:
            for bone in bones:
                bone.select = bone.select_head = bone.select_tail = False
        last = None
        for name in names:
            bone = bones.get(name)
            if bone is not None:
                bone.select = bone.select_head = bone.select_tail = True
                last = bone
        if last is not None:
            bones.active = last
        return

    pose_bones = armature.pose.bones if armature.pose is not None else []
    if not extend:
        for pose_bone in pose_bones:
            _set_pose_bone_selected(pose_bone, False)

    last_name = None
    for name in names:
        pose_bone = pose_bones.get(name) if hasattr(pose_bones, "get") else None
        if pose_bone is not None:
            _set_pose_bone_selected(pose_bone, True)
            last_name = name

    if last_name is not None:
        active = armature.data.bones.get(last_name)
        if active is not None:
            armature.data.bones.active = active


__all__ = [
    "select_bones",
    "selected_armature_bones",
    "selected_bone_names",
    "selected_edit_bones",
    "selected_mode_bones",
    "selected_pose_bones",
]
