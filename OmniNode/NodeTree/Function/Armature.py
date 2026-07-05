from ..FunctionNodeCore import omni
from ..OmniNodeSocketMapping import _OmniBone, _OmniGlob
from . import _Color

import bpy
import re


def _bone_socket_value(
    armature_obj: bpy.types.Object,
    bone_name: str,
    collection_root: str = "",
    collection_bones: list[str] = None,
):
    value = {
        "armature": armature_obj,
        "bone": bone_name,
    }
    if collection_root and collection_bones:
        value["bone_collection_root"] = str(collection_root)
        value["bone_collection"] = list(collection_bones)
    return value


def _resolve_bone_value(value):
    if not isinstance(value, dict):
        raise ValueError("bone input is empty or invalid")
    armature_obj = value.get("armature")
    bone_name = str(value.get("bone") or "").strip()
    if (
        not isinstance(armature_obj, bpy.types.Object)
        or armature_obj.type != "ARMATURE"
        or not bone_name
    ):
        raise ValueError("bone input is empty or invalid")
    if armature_obj.pose is None or armature_obj.pose.bones.get(bone_name) is None:
        raise ValueError(f"bone not found: {bone_name}")
    return armature_obj, bone_name


def _collect_bone_names(root_pose_bone, include_all_bones: bool) -> list[str]:
    names: list[str] = []

    if include_all_bones:
        def visit(pose_bone):
            names.append(pose_bone.name)
            for child in list(getattr(pose_bone, "children", []) or []):
                visit(child)

        visit(root_pose_bone)
        return names

    pose_bone = root_pose_bone
    while pose_bone is not None:
        names.append(pose_bone.name)
        children = list(getattr(pose_bone, "children", []) or [])
        pose_bone = children[0] if children else None
    return names


def _armature_objects_from_input(values) -> list[bpy.types.Object]:
    result: list[bpy.types.Object] = []
    seen = set()
    stack = list(values) if isinstance(values, (list, tuple)) else [values]
    while stack:
        value = stack.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            stack[0:0] = list(value)
            continue
        if not isinstance(value, bpy.types.Object) or value.type != "ARMATURE":
            continue
        key = int(value.as_pointer())
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _uses_glob_syntax(pattern: str) -> bool:
    return "*" in pattern or "?" in pattern


def _hotools_glob_to_regex(pattern: str) -> str:
    regex = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                regex.append(".*")
                index += 2
            else:
                regex.append("[^_]*")
                index += 1
        elif char == "?":
            regex.append("[^_]")
            index += 1
        else:
            regex.append(re.escape(char))
            index += 1
    return "^" + "".join(regex) + "$"


def _append_bone_value(result: list, seen: set, armature_obj: bpy.types.Object, bone_name: str) -> None:
    key = (int(armature_obj.as_pointer()), bone_name)
    if key in seen:
        return
    seen.add(key)
    result.append(_bone_socket_value(armature_obj, bone_name))


@omni(
    enable=True,
    bl_label="从根获取骨骼",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["根骨骼", "包含全部骨"],
    _OUTPUT_NAME=["骨骼"],
    omni_description="""
    从根骨骼收集一组 Bone socket 值。

    “包含全部骨”开启时递归输出根骨下的全部子骨；关闭时遇到分叉只沿第一个子骨走到底。
    输出仍是普通骨骼列表，物理节点如果需要链结构会在内部自行解释。
    """,
)
def bonesFromRoot(
    root_bone: _OmniBone,
    include_all_bones: bool = True,
) -> list[_OmniBone]:
    armature_obj, root_name = _resolve_bone_value(root_bone)
    root_pose_bone = armature_obj.pose.bones.get(root_name)
    if root_pose_bone is None:
        raise ValueError(f"bone not found: {root_name}")

    bone_names = _collect_bone_names(root_pose_bone, include_all_bones)
    return [
        _bone_socket_value(armature_obj, bone_name, root_name, bone_names)
        for bone_name in bone_names
    ]


@omni(
    enable=True,
    bl_label="寻找骨骼",
    base_color=_Color.colorCat["GetData"],
    is_output_node=False,
    _INPUT_NAME=["物体", "Glob表达式"],
    _OUTPUT_NAME=["骨骼"],
    omni_description="""
    在一个或多个 Armature 物体中查找骨骼。

    “Glob表达式”输入如果包含 glob 语法则按 HoTools glob 规则匹配；纯明文按骨骼名称精确匹配。
    """,
)
def findBones(
    objects: list[bpy.types.Object],
    pattern: _OmniGlob,
) -> list[_OmniBone]:
    pattern = str(pattern or "").strip()
    if not pattern:
        return []

    armature_objects = _armature_objects_from_input(objects)
    exact_result = []
    exact_seen = set()
    for obj in armature_objects:
        bones = getattr(getattr(obj, "data", None), "bones", None)
        if bones is None:
            continue
        for bone in bones:
            bone_name = str(getattr(bone, "name", "") or "")
            if bone_name == pattern:
                _append_bone_value(exact_result, exact_seen, obj, bone_name)
    if exact_result or not _uses_glob_syntax(pattern):
        return exact_result

    regex = re.compile(_hotools_glob_to_regex(pattern))
    result = []
    seen = set()
    for obj in armature_objects:
        bones = getattr(getattr(obj, "data", None), "bones", None)
        if bones is None:
            continue
        for bone in bones:
            bone_name = str(getattr(bone, "name", "") or "")
            if regex.match(bone_name) is not None:
                _append_bone_value(result, seen, obj, bone_name)
    return result
