"""Physics World 共享的 Geometry Nodes 顶点 offset 输出。

所有 mesh solver 最终都写入同一个点域 ``FLOAT_VECTOR`` 属性。solver 不得
自定义属性名、修改器名或混合模式；需要组合多个中间 offset 时，应先通过
``world.exchange`` 完成归并，再发布一个对象局部空间的最终 offset result。
"""

from __future__ import annotations

import hashlib

import bpy
import numpy as np

from .names import (
    GN_CACHE_MODIFIER_NAME,
    GN_CACHE_NODE_GROUP_NAME,
    GN_OFFSET_ATTRIBUTE_NAME,
    GN_OFFSET_MODIFIER_NAME,
    GN_OFFSET_NODE_GROUP_NAME,
    PC2_CACHE_MODIFIER_NAME,
)


_NODE_GROUP_OWNER_KEY = "hotools_physics_offset_owner"
_NODE_GROUP_SCHEMA_KEY = "hotools_physics_offset_schema"
_NODE_GROUP_CONTRACT_KEY = "hotools_physics_offset_contract"
_MESH_OWNER_KEY = "hotools_physics_offset_owner"
_MESH_SCHEMA_KEY = "hotools_physics_offset_schema"
_NODE_GROUP_OWNER = "physicsWorld.writeback"
_CACHE_GROUP_OWNER = "physicsWorld.bake"
_NODE_GROUP_SCHEMA = 3
_CACHE_GROUP_SCHEMA = 1
_BAKE_NODE_NAME = "HoTools Physics Bake"
_BAKE_NODE_LABEL = "Physics Post-Displacement Cache"
_EXPECTED_GROUP_CONTRACTS = {}
_NODE_PRESENTATION_PROPERTIES = {
    "rna_type",
    "name",
    "label",
    "location",
    "width",
    "width_hidden",
    "height",
    "dimensions",
    "parent",
    "select",
    "show_options",
    "show_preview",
    "show_texture",
    "hide",
    "use_custom_color",
    "color",
    "color_tag",
    "warning_propagation",
}


def _freeze_rna_value(value):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_rna_value(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_freeze_rna_value(item) for item in value), key=repr))
    try:
        return tuple(_freeze_rna_value(item) for item in value)
    except (TypeError, ReferenceError):
        return (type(value).__name__, str(getattr(value, "name", "") or ""))


def _simple_rna_properties(value, excluded=()) -> tuple:
    excluded = set(excluded)
    properties = []
    for prop in value.bl_rna.properties:
        name = str(prop.identifier)
        if (
            name in excluded
            or bool(getattr(prop, "is_readonly", False))
            or str(getattr(prop, "type", "")) not in {
                "BOOLEAN", "INT", "FLOAT", "STRING", "ENUM",
            }
        ):
            continue
        try:
            item = getattr(value, name)
        except (AttributeError, TypeError, ReferenceError):
            continue
        properties.append((name, _freeze_rna_value(item)))
    return tuple(properties)


def _socket_contract(socket):
    try:
        default = _freeze_rna_value(socket.default_value)
    except (AttributeError, TypeError, ReferenceError):
        default = None
    return (
        str(getattr(socket, "name", "") or ""),
        str(getattr(socket, "bl_idname", "") or ""),
        default,
        _simple_rna_properties(
            socket,
            {"rna_type", "name", "default_value", "hide", "hide_value"},
        ),
    )


def _node_contract(node):
    return (
        str(getattr(node, "name", "") or ""),
        str(getattr(node, "bl_idname", "") or ""),
        str(getattr(node, "label", "") or ""),
        _simple_rna_properties(node, _NODE_PRESENTATION_PROPERTIES),
        tuple(sorted(
            (str(key), _freeze_rna_value(node[key]))
            for key in node.keys()
            if str(key) != "_RNA_UI"
        )),
        tuple(_socket_contract(socket) for socket in node.inputs),
        tuple(_socket_contract(socket) for socket in node.outputs),
    )


def _interface_contract(group):
    interface = getattr(group, "interface", None)
    if interface is None:
        return (
            tuple((socket.name, socket.bl_idname, "INPUT") for socket in group.inputs),
            tuple((socket.name, socket.bl_idname, "OUTPUT") for socket in group.outputs),
        )
    return tuple(
        (
            str(getattr(item, "item_type", "") or ""),
            str(getattr(item, "name", "") or ""),
            str(getattr(item, "in_out", "") or ""),
            str(getattr(item, "socket_type", "") or ""),
            _simple_rna_properties(
                item,
                {
                    "rna_type", "name", "identifier", "item_type", "in_out",
                    "socket_type", "index", "position", "parent",
                },
            ),
        )
        for item in interface.items_tree
    )


def _group_contract(group) -> tuple:
    nodes = tuple(sorted((_node_contract(node) for node in group.nodes), key=repr))
    links = tuple(sorted((
        (
            str(link.from_node.name),
            str(link.from_socket.name),
            str(link.to_node.name),
            str(link.to_socket.name),
        )
        for link in group.links
    )))
    return _interface_contract(group), nodes, links


def _contract_digest(contract: tuple) -> str:
    return hashlib.sha256(repr(contract).encode("utf-8")).hexdigest()


def _expected_group_contract(kind: str) -> tuple[tuple, str]:
    cached = _EXPECTED_GROUP_CONTRACTS.get(kind)
    if cached is not None:
        return cached
    temporary = bpy.data.node_groups.new(
        f"__HoTools_Physics_{kind}_Contract__",
        "GeometryNodeTree",
    )
    try:
        if kind == "offset":
            _build_node_group(temporary)
        elif kind == "cache":
            _build_cache_node_group(temporary)
        else:
            raise ValueError(f"未知 GN contract kind: {kind}")
        contract = _group_contract(temporary)
        cached = (contract, _contract_digest(contract))
        _EXPECTED_GROUP_CONTRACTS[kind] = cached
        return cached
    finally:
        bpy.data.node_groups.remove(temporary)


def _notify_group_refresh(group) -> None:
    group.update_tag()
    for obj in bpy.data.objects:
        if any(
            modifier.type == "NODES" and modifier.node_group == group
            for modifier in obj.modifiers
        ):
            obj.update_tag()
    view_layer = getattr(bpy.context, "view_layer", None)
    if view_layer is not None:
        view_layer.update()


def _ensure_group_structure(
    group,
    kind: str,
    *,
    preserve_bake_node=None,
    force_check: bool = False,
) -> bool:
    expected, digest = _expected_group_contract(kind)
    if not force_check and str(group.get(_NODE_GROUP_CONTRACT_KEY, "") or "") == digest:
        return False
    if _group_contract(group) == expected:
        group[_NODE_GROUP_CONTRACT_KEY] = digest
        return False
    if kind == "offset":
        _build_node_group(group)
    else:
        bake_node = preserve_bake_node
        if bake_node is None:
            candidate = group.nodes.get(_BAKE_NODE_NAME)
            if getattr(candidate, "bl_idname", "") == "GeometryNodeBake":
                bake_node = candidate
        _build_cache_node_group(group, preserve_bake_node=bake_node)
    actual = _group_contract(group)
    if actual != expected:
        raise RuntimeError(f"受管 GN {kind} 节点组刷新后仍不符合当前 contract")
    group[_NODE_GROUP_CONTRACT_KEY] = digest
    _notify_group_refresh(group)
    return True


def _require_mesh_object(obj) -> None:
    if obj is None or getattr(obj, "type", None) != "MESH" or getattr(obj, "data", None) is None:
        raise ValueError("GN 物理 offset 只能写入有效 Mesh 对象")
    try:
        if int(obj.as_pointer()) <= 0 or int(obj.data.as_pointer()) <= 0:
            raise ValueError("GN 物理 offset 目标已经失效")
    except ReferenceError as exc:
        raise ValueError("GN 物理 offset 目标已经失效") from exc


def _reset_geometry_interface(group) -> None:
    if hasattr(group, "interface"):
        group.interface.clear()
        group.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    else:
        group.inputs.clear()
        group.outputs.clear()
        group.inputs.new("NodeSocketGeometry", "Geometry")
        group.outputs.new("NodeSocketGeometry", "Geometry")


def _build_node_group(group) -> None:
    group.nodes.clear()
    _reset_geometry_interface(group)

    input_node = group.nodes.new("NodeGroupInput")
    output_node = group.nodes.new("NodeGroupOutput")
    named_attr = group.nodes.new("GeometryNodeInputNamedAttribute")
    set_position = group.nodes.new("GeometryNodeSetPosition")
    input_node.location = (-600, 0)
    named_attr.location = (-600, -180)
    set_position.location = (-260, 0)
    output_node.location = (80, 0)
    named_attr.data_type = "FLOAT_VECTOR"
    named_attr.inputs["Name"].default_value = GN_OFFSET_ATTRIBUTE_NAME
    group.links.new(input_node.outputs["Geometry"], set_position.inputs["Geometry"])
    group.links.new(named_attr.outputs["Attribute"], set_position.inputs["Offset"])
    group.links.new(set_position.outputs["Geometry"], output_node.inputs["Geometry"])
    group[_NODE_GROUP_OWNER_KEY] = _NODE_GROUP_OWNER
    group[_NODE_GROUP_SCHEMA_KEY] = _NODE_GROUP_SCHEMA


def _ensure_bake_geometry_item(bake_node) -> None:
    """Blender 5.2 的裸 Bake 节点只带 virtual socket，需显式声明 Geometry。"""

    if bake_node.inputs.get("Geometry") and bake_node.outputs.get("Geometry"):
        return
    bake_items = getattr(bake_node, "bake_items", None)
    if bake_items is None:
        raise RuntimeError("共享 GN 物理 Bake 节点不能创建 Geometry socket")
    existing = bake_items.get("Geometry")
    if existing is None:
        bake_items.new("GEOMETRY", "Geometry")
    if not bake_node.inputs.get("Geometry") or not bake_node.outputs.get("Geometry"):
        raise RuntimeError("共享 GN 物理 Bake 节点缺少 Geometry socket")


def _build_cache_node_group(group, *, preserve_bake_node=None) -> None:
    bake_node = preserve_bake_node
    for node in tuple(group.nodes):
        if node != bake_node:
            group.nodes.remove(node)
    _reset_geometry_interface(group)
    input_node = group.nodes.new("NodeGroupInput")
    output_node = group.nodes.new("NodeGroupOutput")
    if bake_node is None:
        bake_node = group.nodes.new("GeometryNodeBake")
    _ensure_bake_geometry_item(bake_node)
    bake_node.name = _BAKE_NODE_NAME
    bake_node.label = _BAKE_NODE_LABEL
    input_node.location = (-340, 0)
    bake_node.location = (0, 0)
    output_node.location = (340, 0)
    group.links.new(input_node.outputs["Geometry"], bake_node.inputs["Geometry"])
    group.links.new(bake_node.outputs["Geometry"], output_node.inputs["Geometry"])
    group[_NODE_GROUP_OWNER_KEY] = _CACHE_GROUP_OWNER
    group[_NODE_GROUP_SCHEMA_KEY] = _CACHE_GROUP_SCHEMA


def _migrate_combined_v2_group(group):
    """Split schema 2 without replacing its Bake node or modifier entries."""
    bake_node = group.nodes.get(_BAKE_NODE_NAME)
    if bake_node is None or getattr(bake_node, "bl_idname", "") != "GeometryNodeBake":
        raise RuntimeError("共享 GN 物理节点组 schema 2 已损坏，不能安全迁移 Bake")
    existing_cache_group = bpy.data.node_groups.get(GN_CACHE_NODE_GROUP_NAME)
    if existing_cache_group is not None and existing_cache_group != group:
        raise RuntimeError("GN 物理缓存节点组已存在，不能自动接管旧 schema 2")

    affected = []
    for obj in bpy.data.objects:
        for modifier in obj.modifiers:
            if modifier.type == "NODES" and modifier.node_group == group:
                affected.append((obj, modifier, obj.modifiers.find(modifier.name)))

    group.name = GN_CACHE_NODE_GROUP_NAME
    _build_cache_node_group(group, preserve_bake_node=bake_node)
    offset_group = bpy.data.node_groups.new(GN_OFFSET_NODE_GROUP_NAME, "GeometryNodeTree")
    _build_node_group(offset_group)

    for obj, cache_modifier, old_index in affected:
        cache_modifier.name = GN_CACHE_MODIFIER_NAME
        live_modifier = obj.modifiers.get(GN_OFFSET_MODIFIER_NAME)
        if live_modifier is None or live_modifier == cache_modifier:
            live_modifier = obj.modifiers.new(GN_OFFSET_MODIFIER_NAME, "NODES")
        live_modifier.node_group = offset_group
        current_index = obj.modifiers.find(live_modifier.name)
        target_index = max(0, min(old_index, len(obj.modifiers) - 1))
        if current_index != target_index:
            obj.modifiers.move(current_index, target_index)
    _ensure_group_structure(group, "cache", preserve_bake_node=bake_node)
    _ensure_group_structure(offset_group, "offset")
    _notify_group_refresh(group)
    _notify_group_refresh(offset_group)
    return offset_group


def ensure_gn_offset_node_group(*, force_contract_check: bool = False):
    group = bpy.data.node_groups.get(GN_OFFSET_NODE_GROUP_NAME)
    if group is None:
        group = bpy.data.node_groups.new(GN_OFFSET_NODE_GROUP_NAME, "GeometryNodeTree")
        _build_node_group(group)
        _ensure_group_structure(group, "offset")
        return group
    if getattr(group, "bl_idname", "") != "GeometryNodeTree":
        bpy.data.node_groups.remove(group)
        group = bpy.data.node_groups.new(GN_OFFSET_NODE_GROUP_NAME, "GeometryNodeTree")
        _build_node_group(group)
        _ensure_group_structure(group, "offset")
        return group
    owner = str(group.get(_NODE_GROUP_OWNER_KEY, "") or "")
    schema = int(group.get(_NODE_GROUP_SCHEMA_KEY, 0) or 0)
    if owner == _NODE_GROUP_OWNER and schema == 2:
        return _migrate_combined_v2_group(group)
    if owner == _NODE_GROUP_OWNER and schema > _NODE_GROUP_SCHEMA:
        raise RuntimeError(f"共享 GN 物理节点组 schema 来自更高版本：{schema}")
    if owner != _NODE_GROUP_OWNER or schema < _NODE_GROUP_SCHEMA:
        _build_node_group(group)
        _notify_group_refresh(group)
    _ensure_group_structure(group, "offset", force_check=force_contract_check)
    return group


def ensure_gn_cache_node_group(*, force_contract_check: bool = False):
    group = bpy.data.node_groups.get(GN_CACHE_NODE_GROUP_NAME)
    if group is None:
        group = bpy.data.node_groups.new(GN_CACHE_NODE_GROUP_NAME, "GeometryNodeTree")
        _build_cache_node_group(group)
        _ensure_group_structure(group, "cache")
        return group
    owner = str(group.get(_NODE_GROUP_OWNER_KEY, "") or "")
    schema = int(group.get(_NODE_GROUP_SCHEMA_KEY, 0) or 0)
    if getattr(group, "bl_idname", "") != "GeometryNodeTree":
        bpy.data.node_groups.remove(group)
        group = bpy.data.node_groups.new(GN_CACHE_NODE_GROUP_NAME, "GeometryNodeTree")
        _build_cache_node_group(group)
        _ensure_group_structure(group, "cache")
        return group
    if owner == _CACHE_GROUP_OWNER and schema > _CACHE_GROUP_SCHEMA:
        raise RuntimeError(f"GN 物理缓存节点组 schema 来自更高版本：{schema}")
    if owner != _CACHE_GROUP_OWNER or schema < _CACHE_GROUP_SCHEMA:
        _build_cache_node_group(group)
        _notify_group_refresh(group)
    _ensure_group_structure(group, "cache", force_check=force_contract_check)
    return group


def _place_live_modifier(obj, modifier) -> None:
    cache_modifier = obj.modifiers.get(GN_CACHE_MODIFIER_NAME)
    pc2_modifier = obj.modifiers.get(PC2_CACHE_MODIFIER_NAME)
    ordered = [modifier]
    if (
        cache_modifier is not None
        and cache_modifier != modifier
        and cache_modifier.type == "NODES"
    ):
        ordered.append(cache_modifier)
    if (
        pc2_modifier is not None
        and pc2_modifier != modifier
        and pc2_modifier.type == "MESH_CACHE"
    ):
        ordered.append(pc2_modifier)
    for item in ordered:
        index = obj.modifiers.find(item.name)
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
    _place_live_modifier(obj, modifier)
    return modifier


def ensure_gn_cache_modifier(obj):
    _require_mesh_object(obj)
    live_modifier = ensure_gn_offset_modifier(obj)
    group = ensure_gn_cache_node_group()
    modifier = obj.modifiers.get(GN_CACHE_MODIFIER_NAME)
    if modifier is not None and modifier.type != "NODES":
        obj.modifiers.remove(modifier)
        modifier = None
    if modifier is None:
        modifier = obj.modifiers.new(GN_CACHE_MODIFIER_NAME, "NODES")
        modifier.show_viewport = False
        modifier.show_render = False
    modifier.node_group = group
    live_index = obj.modifiers.find(live_modifier.name)
    cache_index = obj.modifiers.find(modifier.name)
    target_index = live_index + 1
    if cache_index != target_index:
        obj.modifiers.move(cache_index, target_index)
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
    group = group or ensure_gn_cache_node_group()
    bake_node = group.nodes.get(_BAKE_NODE_NAME)
    if bake_node is None or getattr(bake_node, "bl_idname", "") != "GeometryNodeBake":
        raise RuntimeError("共享 GN 物理缓存组缺少受管 Bake 节点")
    _ensure_bake_geometry_item(bake_node)
    return bake_node


def get_gn_offset_bake_entry(modifier):
    if modifier is None or getattr(modifier, "type", None) != "NODES":
        raise ValueError("GN 物理 Bake 需要有效的 Nodes modifier")
    bake_node = get_gn_offset_bake_node(getattr(modifier, "node_group", None))
    for entry in getattr(modifier, "bakes", ()):
        if getattr(entry, "node", None) == bake_node:
            return entry
    raise RuntimeError("Nodes modifier 尚未生成 GN 物理 Bake entry")


def is_gn_offset_cache_enabled(obj) -> bool:
    _require_mesh_object(obj)
    modifier = obj.modifiers.get(GN_CACHE_MODIFIER_NAME)
    return bool(
        modifier is not None
        and modifier.type == "NODES"
        and modifier.show_viewport
    )


def set_gn_offset_cache_enabled(obj, enabled: bool):
    """Select cached or live post-displacement geometry for one object only."""
    modifier = ensure_gn_cache_modifier(obj)
    modifier.show_viewport = bool(enabled)
    modifier.show_render = bool(enabled)
    obj.update_tag()
    view_layer = getattr(bpy.context, "view_layer", None)
    if view_layer is not None:
        view_layer.update()
    return modifier


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

    modifier = ensure_gn_cache_modifier(obj)
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


def _group_is_current(group, kind: str, owner: str, schema: int) -> bool:
    if group is None or getattr(group, "bl_idname", "") != "GeometryNodeTree":
        return False
    if str(group.get(_NODE_GROUP_OWNER_KEY, "") or "") != owner:
        return False
    if int(group.get(_NODE_GROUP_SCHEMA_KEY, 0) or 0) != schema:
        return False
    expected, _digest = _expected_group_contract(kind)
    return _group_contract(group) == expected


def refresh_managed_gn_node_groups() -> dict:
    """Refresh existing HoTools GN resources after addon/module reload.

    The desired structure is generated from the current builders, so changing a
    builder is detected even when a developer forgets to bump the integer schema.
    """
    live_objects = [
        obj for obj in bpy.data.objects
        if obj.type == "MESH" and obj.modifiers.get(GN_OFFSET_MODIFIER_NAME) is not None
    ]
    cache_objects = [
        obj for obj in bpy.data.objects
        if obj.type == "MESH" and obj.modifiers.get(GN_CACHE_MODIFIER_NAME) is not None
    ]
    live_group = bpy.data.node_groups.get(GN_OFFSET_NODE_GROUP_NAME)
    cache_group = bpy.data.node_groups.get(GN_CACHE_NODE_GROUP_NAME)
    refreshed_groups = 0
    refreshed_modifiers = 0

    if live_group is not None or live_objects:
        was_current = _group_is_current(
            live_group, "offset", _NODE_GROUP_OWNER, _NODE_GROUP_SCHEMA
        )
        live_group = ensure_gn_offset_node_group(force_contract_check=True)
        refreshed_groups += int(not was_current)
        cache_group = bpy.data.node_groups.get(GN_CACHE_NODE_GROUP_NAME)
        cache_objects = [
            obj for obj in bpy.data.objects
            if obj.type == "MESH"
            and obj.modifiers.get(GN_CACHE_MODIFIER_NAME) is not None
        ]
    if cache_group is not None or cache_objects:
        was_current = _group_is_current(
            cache_group, "cache", _CACHE_GROUP_OWNER, _CACHE_GROUP_SCHEMA
        )
        cache_group = ensure_gn_cache_node_group(force_contract_check=True)
        refreshed_groups += int(not was_current)

    managed_objects = tuple(dict.fromkeys((*live_objects, *cache_objects)))
    for obj in managed_objects:
        before = tuple(
            (item.name, item.type, item.node_group if item.type == "NODES" else None)
            for item in obj.modifiers
        )
        if obj.modifiers.get(GN_OFFSET_MODIFIER_NAME) is not None:
            ensure_gn_offset_modifier(obj)
        if obj.modifiers.get(GN_CACHE_MODIFIER_NAME) is not None:
            ensure_gn_cache_modifier(obj)
        after = tuple(
            (item.name, item.type, item.node_group if item.type == "NODES" else None)
            for item in obj.modifiers
        )
        if before != after:
            refreshed_modifiers += 1
            obj.update_tag()

    if refreshed_modifiers:
        view_layer = getattr(bpy.context, "view_layer", None)
        if view_layer is not None:
            view_layer.update()
    live_group = bpy.data.node_groups.get(GN_OFFSET_NODE_GROUP_NAME)
    cache_group = bpy.data.node_groups.get(GN_CACHE_NODE_GROUP_NAME)
    return {
        "group_count": int(live_group is not None) + int(cache_group is not None),
        "refreshed_group_count": refreshed_groups,
        "modifier_count": len(managed_objects),
        "refreshed_modifier_count": refreshed_modifiers,
    }


__all__ = [
    "clear_gn_local_offsets",
    "configure_gn_offset_disk_bake",
    "ensure_gn_cache_modifier",
    "ensure_gn_cache_node_group",
    "ensure_gn_offset_attribute",
    "ensure_gn_offset_modifier",
    "ensure_gn_offset_node_group",
    "ensure_gn_offset_output",
    "get_gn_offset_bake_entry",
    "get_gn_offset_bake_node",
    "is_gn_offset_cache_enabled",
    "normalize_local_offsets",
    "refresh_managed_gn_node_groups",
    "remove_gn_offset_output",
    "set_gn_offset_cache_enabled",
    "write_gn_local_offsets",
]
