from ..OmniNodeSocketMapping import _OmniVertexGroup
from ..FunctionNodeCore import omni
from . import _Color

import bpy


def _require_object(obj) -> bpy.types.Object:
    if obj is None or not isinstance(obj, bpy.types.Object):
        raise ValueError("物体输入未连接或无效")
    if obj.type != "MESH":
        raise ValueError(f"object '{obj.name}' is not a mesh object")
    return obj


def _require_vertex_group(vertex_group) -> bpy.types.VertexGroup:
    if vertex_group is None or not isinstance(vertex_group, bpy.types.VertexGroup):
        raise ValueError("顶点组输入未连接或无效")
    return vertex_group


def _require_vertex_group_name(group_name: str) -> str:
    group_name = str(group_name or "").strip()
    if not group_name:
        raise ValueError("顶点组名称不能为空")
    return group_name


def _get_vertex_groups(obj: bpy.types.Object):
    return _require_object(obj).vertex_groups


def _vertex_group_owner(vertex_group: bpy.types.VertexGroup) -> bpy.types.Object:
    owner = getattr(vertex_group, "id_data", None)
    if owner is None or not isinstance(owner, bpy.types.Object):
        raise ValueError("顶点组没有有效的所属物体")
    if owner.type != "MESH":
        raise ValueError(f"vertex group owner '{owner.name}' is not a mesh object")
    return owner


def _get_vertex_group_by_name(obj: bpy.types.Object, group_name: str) -> bpy.types.VertexGroup:
    vertex_groups = _get_vertex_groups(obj)
    group_name = _require_vertex_group_name(group_name)
    vertex_group = vertex_groups.get(group_name)
    if vertex_group is None:
        raise ValueError(f"物体 '{obj.name}' 上找不到顶点组 '{group_name}'")
    return vertex_group


def _get_vertex_group_by_index(obj: bpy.types.Object, group_index: int) -> bpy.types.VertexGroup:
    vertex_groups = _get_vertex_groups(obj)
    if len(vertex_groups) == 0:
        raise ValueError(f"物体 '{obj.name}' 没有任何顶点组")

    group_index = int(group_index)
    if group_index < 0 or group_index >= len(vertex_groups):
        raise ValueError(
            f"顶点组索引超出范围: {group_index}，有效范围是 0 到 {len(vertex_groups) - 1}"
        )
    return vertex_groups[group_index]


@omni(
    enable=True,
    bl_label="创建顶点组",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "顶点组名称"],
    _OUTPUT_NAME=["物体", "顶点组", "顶点组名称"],
    omni_description="""
    在目标物体上创建一个顶点组。
    如果同名顶点组已经存在，则直接返回已有顶点组。
    """,
)
def objectCreateVertexGroup(
    obj: bpy.types.Object,
    group_name: str,
) -> tuple[bpy.types.Object, _OmniVertexGroup, str]:
    vertex_groups = _get_vertex_groups(obj)
    group_name = _require_vertex_group_name(group_name)
    vertex_group = vertex_groups.get(group_name)
    if vertex_group is None:
        vertex_group = vertex_groups.new(name=group_name)
    return obj, vertex_group, vertex_group.name


@omni(
    enable=True,
    bl_label="按名称获取顶点组",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "顶点组名称"],
    _OUTPUT_NAME=["顶点组"],
)
def objectGetVertexGroupByName(
    obj: bpy.types.Object,
    group_name: str,
) -> _OmniVertexGroup:
    return _get_vertex_group_by_name(obj, group_name)


@omni(
    enable=True,
    bl_label="按索引获取顶点组",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "顶点组索引"],
    _OUTPUT_NAME=["顶点组"],
)
def objectGetVertexGroupByIndex(
    obj: bpy.types.Object,
    group_index: int,
) -> _OmniVertexGroup:
    return _get_vertex_group_by_index(obj, group_index)


@omni(
    enable=True,
    bl_label="获取活动顶点组",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体"],
    _OUTPUT_NAME=["顶点组"],
)
def objectGetActiveVertexGroup(
    obj: bpy.types.Object,
) -> _OmniVertexGroup:
    vertex_groups = _get_vertex_groups(obj)
    vertex_group = vertex_groups.active
    if vertex_group is None:
        raise ValueError(f"物体 '{obj.name}' 没有活动顶点组")
    return vertex_group


@omni(
    enable=True,
    bl_label="获取顶点组名称",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["顶点组"],
    _OUTPUT_NAME=["顶点组名称"],
)
def vertexGroupGetName(
    vertex_group: _OmniVertexGroup,
) -> str:
    vertex_group = _require_vertex_group(vertex_group)
    return vertex_group.name


@omni(
    enable=True,
    bl_label="获取顶点组索引",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["顶点组"],
    _OUTPUT_NAME=["顶点组索引"],
)
def vertexGroupGetIndex(
    vertex_group: _OmniVertexGroup,
) -> int:
    vertex_group = _require_vertex_group(vertex_group)
    return vertex_group.index


@omni(
    enable=True,
    bl_label="获取顶点组物体",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["顶点组"],
    _OUTPUT_NAME=["物体"],
)
def vertexGroupGetObject(
    vertex_group: _OmniVertexGroup,
) -> bpy.types.Object:
    vertex_group = _require_vertex_group(vertex_group)
    return _vertex_group_owner(vertex_group)


@omni(
    enable=True,
    bl_label="重命名顶点组",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["顶点组", "新名称"],
    _OUTPUT_NAME=["顶点组", "顶点组名称"],
)
def vertexGroupRename(
    vertex_group: _OmniVertexGroup,
    new_name: str,
) -> tuple[_OmniVertexGroup, str]:
    vertex_group = _require_vertex_group(vertex_group)
    new_name = _require_vertex_group_name(new_name)
    vertex_group.name = new_name
    return vertex_group, vertex_group.name


@omni(
    enable=True,
    bl_label="设置活动顶点组",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "顶点组"],
    _OUTPUT_NAME=["物体", "顶点组"],
)
def objectSetActiveVertexGroup(
    obj: bpy.types.Object,
    vertex_group: _OmniVertexGroup,
) -> tuple[bpy.types.Object, _OmniVertexGroup]:
    vertex_group = _require_vertex_group(vertex_group)
    owner = _vertex_group_owner(vertex_group)
    obj = _require_object(obj)
    if owner != obj:
        raise ValueError(f"顶点组 '{vertex_group.name}' 不属于物体 '{obj.name}'")
    obj.vertex_groups.active_index = vertex_group.index
    return obj, obj.vertex_groups.active


@omni(
    enable=True,
    bl_label="设置活动顶点组索引",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "顶点组索引"],
    _OUTPUT_NAME=["物体", "顶点组"],
)
def objectSetActiveVertexGroupByIndex(
    obj: bpy.types.Object,
    group_index: int,
) -> tuple[bpy.types.Object, _OmniVertexGroup]:
    obj = _require_object(obj)
    vertex_group = _get_vertex_group_by_index(obj, group_index)
    obj.vertex_groups.active_index = int(group_index)
    return obj, vertex_group


@omni(
    enable=True,
    bl_label="删除顶点组对象",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["顶点组"],
    _OUTPUT_NAME=["物体"],
)
def vertexGroupRemove(
    vertex_group: _OmniVertexGroup,
) -> bpy.types.Object:
    vertex_group = _require_vertex_group(vertex_group)
    obj = _vertex_group_owner(vertex_group)
    obj.vertex_groups.remove(vertex_group)
    return obj
