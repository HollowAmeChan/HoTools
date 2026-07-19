"""Physics World 共享的 Geometry Nodes 顶点 offset 输出。

所有 mesh solver 最终都写入同一个点域 ``FLOAT_VECTOR`` 属性。solver 不得
自定义属性名、修改器名或混合模式；需要组合多个中间 offset 时，应先通过
``world.exchange`` 完成归并，再发布一个对象局部空间的最终 offset result。
"""

from __future__ import annotations

import bpy
import numpy as np

from .names import (
    GN_OFFSET_ATTRIBUTE_NAME,
    GN_OFFSET_MODIFIER_NAME,
    GN_OFFSET_NODE_GROUP_NAME,
)


_NODE_GROUP_OWNER_KEY = "hotools_physics_offset_owner"
_NODE_GROUP_SCHEMA_KEY = "hotools_physics_offset_schema"
_MESH_OWNER_KEY = "hotools_physics_offset_owner"
_MESH_SCHEMA_KEY = "hotools_physics_offset_schema"
_NODE_GROUP_OWNER = "physicsWorld.writeback"
_NODE_GROUP_SCHEMA = 2
_BAKE_NODE_NAME = "HoTools Physics Bake"
_BAKE_NODE_LABEL = "Physics Post-Displacement Cache"


def _require_mesh_object(obj) -> None:
    if obj is None or getattr(obj, "type", None) != "MESH" or getattr(obj, "data", None) is None:
        raise ValueError("GN 物理 offset 只能写入有效 Mesh 对象")
    try:
        if int(obj.as_pointer()) <= 0 or int(obj.data.as_pointer()) <= 0:
            raise ValueError("GN 物理 offset 目标已经失效")
    except ReferenceError as exc:
        raise ValueError("GN 物理 offset 目标已经失效") from exc


def _build_node_group(group) -> None:
    group.nodes.clear()
    if hasattr(group, "interface"):
        group.interface.clear()
        group.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    else:
        group.inputs.clear()
        group.outputs.clear()
        group.inputs.new("NodeSocketGeometry", "Geometry")
        group.outputs.new("NodeSocketGeometry", "Geometry")

    input_node = group.nodes.new("NodeGroupInput")
    output_node = group.nodes.new("NodeGroupOutput")
    named_attr = group.nodes.new("GeometryNodeInputNamedAttribute")
    set_position = group.nodes.new("GeometryNodeSetPosition")
    bake_node = group.nodes.new("GeometryNodeBake")
    bake_node.name = _BAKE_NODE_NAME
    bake_node.label = _BAKE_NODE_LABEL
    input_node.location = (-600, 0)
    named_attr.location = (-600, -180)
    set_position.location = (-260, 0)
    bake_node.location = (80, 0)
    output_node.location = (420, 0)
    named_attr.data_type = "FLOAT_VECTOR"
    named_attr.inputs["Name"].default_value = GN_OFFSET_ATTRIBUTE_NAME
    group.links.new(input_node.outputs["Geometry"], set_position.inputs["Geometry"])
    group.links.new(named_attr.outputs["Attribute"], set_position.inputs["Offset"])
    group.links.new(set_position.outputs["Geometry"], bake_node.inputs["Geometry"])
    group.links.new(bake_node.outputs["Geometry"], output_node.inputs["Geometry"])
    group[_NODE_GROUP_OWNER_KEY] = _NODE_GROUP_OWNER
    group[_NODE_GROUP_SCHEMA_KEY] = _NODE_GROUP_SCHEMA


def ensure_gn_offset_node_group():
    group = bpy.data.node_groups.get(GN_OFFSET_NODE_GROUP_NAME)
    if group is None:
        group = bpy.data.node_groups.new(GN_OFFSET_NODE_GROUP_NAME, "GeometryNodeTree")
        _build_node_group(group)
        return group
    if getattr(group, "bl_idname", "") != "GeometryNodeTree":
        bpy.data.node_groups.remove(group)
        group = bpy.data.node_groups.new(GN_OFFSET_NODE_GROUP_NAME, "GeometryNodeTree")
        _build_node_group(group)
        return group
    owner = str(group.get(_NODE_GROUP_OWNER_KEY, "") or "")
    schema = int(group.get(_NODE_GROUP_SCHEMA_KEY, 0) or 0)
    if owner != _NODE_GROUP_OWNER or schema != _NODE_GROUP_SCHEMA:
        _build_node_group(group)
    return group


def _move_modifier_to_bottom(obj, modifier) -> None:
    index = obj.modifiers.find(modifier.name)
    if 0 <= index < len(obj.modifiers) - 1:
        obj.modifiers.move(index, len(obj.modifiers) - 1)


def ensure_gn_offset_modifier(obj):
    _require_mesh_object(obj)
    group = ensure_gn_offset_node_group()
    modifier = obj.modifiers.get(GN_OFFSET_MODIFIER_NAME)
    if modifier is not None and modifier.type != "NODES":
        obj.modifiers.remove(modifier)
        modifier = None
    if modifier is None:
        modifier = obj.modifiers.new(GN_OFFSET_MODIFIER_NAME, "NODES")
    modifier.node_group = group
    _move_modifier_to_bottom(obj, modifier)
    return modifier


def ensure_gn_offset_attribute(obj):
    _require_mesh_object(obj)
    mesh = obj.data
    attribute = mesh.attributes.get(GN_OFFSET_ATTRIBUTE_NAME)
    if attribute is not None and (
        attribute.domain != "POINT" or attribute.data_type != "FLOAT_VECTOR"
    ):
        mesh.attributes.remove(attribute)
        attribute = None
    if attribute is None:
        attribute = mesh.attributes.new(GN_OFFSET_ATTRIBUTE_NAME, "FLOAT_VECTOR", "POINT")
    mesh[_MESH_OWNER_KEY] = _NODE_GROUP_OWNER
    mesh[_MESH_SCHEMA_KEY] = _NODE_GROUP_SCHEMA
    return attribute


def ensure_gn_offset_output(obj):
    attribute = ensure_gn_offset_attribute(obj)
    modifier = ensure_gn_offset_modifier(obj)
    return attribute, modifier


def get_gn_offset_bake_node(group=None):
    group = group or ensure_gn_offset_node_group()
    bake_node = group.nodes.get(_BAKE_NODE_NAME)
    if bake_node is None or getattr(bake_node, "bl_idname", "") != "GeometryNodeBake":
        raise RuntimeError("共享 GN 物理后置位移缺少受管 Bake 节点")
    if not bake_node.inputs.get("Geometry") or not bake_node.outputs.get("Geometry"):
        raise RuntimeError("共享 GN 物理 Bake 节点缺少 Geometry socket")
    return bake_node


def get_gn_offset_bake_entry(modifier):
    if modifier is None or getattr(modifier, "type", None) != "NODES":
        raise ValueError("GN 物理 Bake 需要有效的 Nodes modifier")
    bake_node = get_gn_offset_bake_node(getattr(modifier, "node_group", None))
    for entry in getattr(modifier, "bakes", ()):
        if getattr(entry, "node", None) == bake_node:
            return entry
    raise RuntimeError("Nodes modifier 尚未生成 GN 物理 Bake entry")


def configure_gn_offset_disk_bake(
    obj,
    directory: str,
    frame_start: int,
    frame_end: int,
):
    """Configure the managed post-displacement Bake entry without running it."""
    start = int(frame_start)
    end = int(frame_end)
    if end < start:
        raise ValueError("GN 物理 Bake 结束帧不能小于开始帧")
    path = str(directory or "").strip()
    if not path:
        raise ValueError("GN 物理 Bake 磁盘目录不能为空")

    modifier = ensure_gn_offset_modifier(obj)
    entry = get_gn_offset_bake_entry(modifier)
    modifier.bake_target = "DISK"
    modifier.bake_directory = path
    entry.use_custom_simulation_frame_range = True
    entry.frame_start = start
    entry.frame_end = end
    entry.bake_mode = "ANIMATION"
    entry.bake_target = "DISK"
    entry.use_custom_path = True
    entry.directory = path
    return modifier, entry


def normalize_local_offsets(offsets, vertex_count: int | None = None, *, copy: bool = True) -> np.ndarray:
    values = np.asarray(offsets, dtype=np.float32)
    if values.ndim == 1:
        if values.size % 3:
            raise ValueError("GN 物理 offset 一维 buffer 长度必须是 3 的倍数")
        values = values.reshape((-1, 3))
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError("GN 物理 offset 必须是 float32[N,3]")
    if vertex_count is not None and len(values) != int(vertex_count):
        raise ValueError(
            f"GN 物理 offset 顶点数不一致：buffer={len(values)} target={int(vertex_count)}"
        )
    if not np.isfinite(values).all():
        raise ValueError("GN 物理 offset 不能包含 NaN 或 Inf")
    if copy:
        return np.array(values, dtype=np.float32, order="C", copy=True)
    return np.ascontiguousarray(values, dtype=np.float32)


def write_gn_local_offsets(obj, offsets) -> None:
    _require_mesh_object(obj)
    if int(getattr(obj.data, "users", 1) or 1) != 1:
        raise ValueError("GN 物理 offset 要求目标 Mesh 数据单用户，避免共享数据串写")
    values = normalize_local_offsets(offsets, len(obj.data.vertices), copy=False)
    attribute, _modifier = ensure_gn_offset_output(obj)
    attribute.data.foreach_set("vector", values.reshape(-1))
    obj.data.update()
    obj.update_tag()


def clear_gn_local_offsets(obj) -> bool:
    try:
        _require_mesh_object(obj)
    except ValueError:
        return False
    attribute = obj.data.attributes.get(GN_OFFSET_ATTRIBUTE_NAME)
    if attribute is None:
        return False
    if attribute.domain != "POINT" or attribute.data_type != "FLOAT_VECTOR":
        return False
    zeros = np.zeros(len(obj.data.vertices) * 3, dtype=np.float32)
    attribute.data.foreach_set("vector", zeros)
    obj.data.update()
    obj.update_tag()
    return True


def remove_gn_offset_output(obj) -> bool:
    """Remove the reserved shared offset modifier and attribute from one object."""
    try:
        _require_mesh_object(obj)
    except ValueError:
        return False
    removed = False
    modifier = obj.modifiers.get(GN_OFFSET_MODIFIER_NAME)
    if modifier is not None:
        obj.modifiers.remove(modifier)
        removed = True
    attribute = obj.data.attributes.get(GN_OFFSET_ATTRIBUTE_NAME)
    if attribute is not None:
        obj.data.attributes.remove(attribute)
        removed = True
    if removed:
        obj.data.update()
        obj.update_tag()
    return removed


__all__ = [
    "clear_gn_local_offsets",
    "configure_gn_offset_disk_bake",
    "ensure_gn_offset_attribute",
    "ensure_gn_offset_modifier",
    "ensure_gn_offset_node_group",
    "ensure_gn_offset_output",
    "get_gn_offset_bake_entry",
    "get_gn_offset_bake_node",
    "normalize_local_offsets",
    "remove_gn_offset_output",
    "write_gn_local_offsets",
]
