"""Managed Geometry Nodes previews for rigid-fracture authoring."""

from __future__ import annotations

import bpy


FRACTURE_GENERATOR_VERSION = 4
FRACTURE_PIECE_ID_ATTRIBUTE = "hotools_piece_id"
FRACTURE_METHOD_VORONOI_UNIFORM = "VORONOI_UNIFORM"
FRACTURE_METHOD_ITEMS = (
    (
        FRACTURE_METHOD_VORONOI_UNIFORM,
        "均匀 Voronoi",
        "在物体包围盒中均匀布点并生成封闭的三维 Voronoi 碎块",
    ),
)

DEFAULT_VORONOI_DENSITY = 6
DEFAULT_VORONOI_SEED = 0
DEFAULT_VORONOI_RANDOMNESS = 0.72
DEFAULT_VORONOI_GAP = 0.045

_GENERATOR_ID_BY_METHOD = {
    FRACTURE_METHOD_VORONOI_UNIFORM: "rigid_fracture_voronoi_uniform",
}
_LEGACY_GENERATOR_IDS = {"rigid_fracture_grid"}
_CUTTER_NODE_NAME = "HoTools Voronoi Cutter"


def _add_interface_socket(
    group,
    *,
    name: str,
    socket_type: str,
    default,
    minimum=None,
    maximum=None,
    description: str = "",
):
    socket = group.interface.new_socket(
        name=name,
        in_out="INPUT",
        socket_type=socket_type,
    )
    socket.default_value = default
    if minimum is not None:
        socket.min_value = minimum
    if maximum is not None:
        socket.max_value = maximum
    socket.description = description
    return socket


def _add_voronoi_interface(group) -> None:
    group.interface.new_socket(
        name="Geometry",
        in_out="INPUT",
        socket_type="NodeSocketGeometry",
    )
    _add_interface_socket(
        group,
        name="碎块密度",
        socket_type="NodeSocketInt",
        default=DEFAULT_VORONOI_DENSITY,
        minimum=2,
        maximum=30,
        description="最长轴上的平均单元数量；其他轴按物体比例自动换算",
    )
    _add_interface_socket(
        group,
        name="随机种子",
        socket_type="NodeSocketInt",
        default=DEFAULT_VORONOI_SEED,
        minimum=0,
        maximum=10000,
        description="生成另一组确定性的 Voronoi 种子",
    )
    _add_interface_socket(
        group,
        name="随机度",
        socket_type="NodeSocketFloat",
        default=DEFAULT_VORONOI_RANDOMNESS,
        minimum=0.0,
        maximum=1.0,
        description="0 为均匀晶格，1 为单元中心的最大安全扰动",
    )
    _add_interface_socket(
        group,
        name="裂缝宽度",
        socket_type="NodeSocketFloat",
        default=DEFAULT_VORONOI_GAP,
        minimum=0.0,
        maximum=0.25,
        description="相对于平均单元尺寸的碎块间隙",
    )
    group.interface.new_socket(
        name="Geometry",
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )


def build_voronoi_uniform_group(group, cutter_object=None) -> None:
    """Build the GN boolean stage for a baked, closed Voronoi cell cutter."""
    group.nodes.clear()
    group.interface.clear()
    _add_voronoi_interface(group)

    nodes = group.nodes
    links = group.links
    group_input = nodes.new("NodeGroupInput")
    group_input.location = (-520.0, 120.0)
    group_output = nodes.new("NodeGroupOutput")
    group_output.location = (560.0, 120.0)

    cutter = nodes.new("GeometryNodeObjectInfo")
    cutter.name = _CUTTER_NODE_NAME
    cutter.label = "封闭 Voronoi 单元"
    cutter.location = (-520.0, -100.0)
    cutter.transform_space = "RELATIVE"
    cutter.inputs["Object"].default_value = cutter_object
    cutter.inputs["As Instance"].default_value = False

    boolean = nodes.new("GeometryNodeMeshBoolean")
    boolean.location = (-180.0, 120.0)
    boolean.operation = "INTERSECT"
    if hasattr(boolean, "solver"):
        boolean.solver = "EXACT"
    boolean.inputs[2].default_value = False
    boolean.inputs[3].default_value = False
    links.new(group_input.outputs["Geometry"], boolean.inputs[0])
    links.new(cutter.outputs["Geometry"], boolean.inputs[1])

    island = nodes.new("GeometryNodeInputMeshIsland")
    island.location = (-80.0, -80.0)
    store_id = nodes.new("GeometryNodeStoreNamedAttribute")
    store_id.location = (160.0, 120.0)
    store_id.data_type = "INT"
    store_id.domain = "FACE"
    store_id.inputs["Name"].default_value = FRACTURE_PIECE_ID_ATTRIBUTE
    links.new(boolean.outputs["Mesh"], store_id.inputs["Geometry"])
    links.new(island.outputs["Island Index"], store_id.inputs["Value"])
    links.new(store_id.outputs["Geometry"], group_output.inputs["Geometry"])

    group["hotools_generator"] = _GENERATOR_ID_BY_METHOD[FRACTURE_METHOD_VORONOI_UNIFORM]
    group["hotools_generator_version"] = FRACTURE_GENERATOR_VERSION
    group["hotools_fracture_method"] = FRACTURE_METHOD_VORONOI_UNIFORM
    group["hotools_piece_id_attribute"] = FRACTURE_PIECE_ID_ATTRIBUTE


def set_fracture_cutter_object(group, cutter_object) -> None:
    if group is None:
        raise ValueError("碎块预览缺少 Geometry Nodes 节点组")
    node = group.nodes.get(_CUTTER_NODE_NAME)
    if node is None or node.bl_idname != "GeometryNodeObjectInfo":
        raise ValueError("碎块预览缺少 HoTools Voronoi 切割器节点")
    node.inputs["Object"].default_value = cutter_object


def fracture_method_from_group(group) -> str:
    if group is None:
        return ""
    method = str(group.get("hotools_fracture_method", ""))
    if method in _GENERATOR_ID_BY_METHOD:
        return method
    return ""


def is_managed_fracture_group(group) -> bool:
    if group is None or getattr(group, "bl_idname", "") != "GeometryNodeTree":
        return False
    generator_id = str(group.get("hotools_generator", ""))
    return generator_id in set(_GENERATOR_ID_BY_METHOD.values()) | _LEGACY_GENERATOR_IDS


def is_current_fracture_group(group, method: str) -> bool:
    return bool(
        is_managed_fracture_group(group)
        and fracture_method_from_group(group) == method
        and int(group.get("hotools_generator_version", 0)) == FRACTURE_GENERATOR_VERSION
    )


def is_legacy_passthrough_group(group) -> bool:
    if group is None or getattr(group, "bl_idname", "") != "GeometryNodeTree":
        return False
    nodes = tuple(group.nodes)
    return (
        len(nodes) == 2
        and {node.bl_idname for node in nodes} == {"NodeGroupInput", "NodeGroupOutput"}
        and len(group.links) == 1
    )


def build_fracture_group(group, method: str, cutter_object=None) -> None:
    method = str(method or FRACTURE_METHOD_VORONOI_UNIFORM)
    if method == FRACTURE_METHOD_VORONOI_UNIFORM:
        build_voronoi_uniform_group(group, cutter_object)
        return
    raise ValueError(f"未知碎块切割算法: {method}")


def new_fracture_group(name: str, method: str, cutter_object=None):
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    try:
        build_fracture_group(group, method, cutter_object)
    except Exception:
        bpy.data.node_groups.remove(group)
        raise
    return group


def _managed_input_sockets(modifier):
    group = getattr(modifier, "node_group", None)
    interface = getattr(group, "interface", None)
    for item in getattr(interface, "items_tree", ()):
        if (
            getattr(item, "item_type", "") == "SOCKET"
            and getattr(item, "in_out", "") == "INPUT"
            and item.name != "Geometry"
        ):
            yield item


def _modifier_input_get(modifier, item):
    """Read a GN modifier socket across Blender 4.5 and 5.2 APIs."""
    properties = getattr(modifier, "properties", None)
    inputs = getattr(properties, "inputs", None)
    if inputs is not None:
        try:
            return getattr(inputs, item.identifier).value
        except (AttributeError, KeyError, TypeError):
            pass
    try:
        return modifier[item.identifier]
    except (KeyError, TypeError):
        return item.default_value


def _modifier_input_set(modifier, item, value) -> None:
    """Write a GN modifier socket across Blender 4.5 and 5.2 APIs."""
    properties = getattr(modifier, "properties", None)
    inputs = getattr(properties, "inputs", None)
    if inputs is not None:
        try:
            getattr(inputs, item.identifier).value = value
            return
        except (AttributeError, KeyError, TypeError):
            pass
    modifier[item.identifier] = value


def modifier_input_values(modifier) -> dict:
    """Read managed preview values by interface name, independent of identifiers."""
    return {
        item.name: _modifier_input_get(modifier, item)
        for item in _managed_input_sockets(modifier)
    }


def set_modifier_input_values(modifier, values: dict) -> None:
    """Set managed preview inputs by stable interface names."""
    for item in _managed_input_sockets(modifier):
        if item.name in values and values[item.name] is not None:
            _modifier_input_set(modifier, item, values[item.name])


def set_voronoi_modifier_inputs(
    modifier,
    *,
    density=None,
    seed=None,
    randomness=None,
    gap=None,
    resolution=None,
) -> None:
    """Set preview controls; ``resolution`` remains accepted for v3 callers."""
    group = getattr(modifier, "node_group", None)
    if fracture_method_from_group(group) != FRACTURE_METHOD_VORONOI_UNIFORM:
        raise ValueError("修改器不是 HoTools 均匀 Voronoi 碎块预览")
    values = {
        "碎块密度": density,
        "随机种子": seed,
        "随机度": randomness,
        "裂缝宽度": gap,
    }
    set_modifier_input_values(modifier, values)


__all__ = [
    "DEFAULT_VORONOI_DENSITY",
    "DEFAULT_VORONOI_GAP",
    "DEFAULT_VORONOI_RANDOMNESS",
    "DEFAULT_VORONOI_SEED",
    "FRACTURE_GENERATOR_VERSION",
    "FRACTURE_METHOD_ITEMS",
    "FRACTURE_METHOD_VORONOI_UNIFORM",
    "FRACTURE_PIECE_ID_ATTRIBUTE",
    "build_fracture_group",
    "build_voronoi_uniform_group",
    "fracture_method_from_group",
    "is_current_fracture_group",
    "is_legacy_passthrough_group",
    "is_managed_fracture_group",
    "modifier_input_values",
    "new_fracture_group",
    "set_fracture_cutter_object",
    "set_modifier_input_values",
    "set_voronoi_modifier_inputs",
]
