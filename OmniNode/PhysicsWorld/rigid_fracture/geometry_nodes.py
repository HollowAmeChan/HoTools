"""Managed Geometry Nodes generators for rigid-fracture authoring."""

from __future__ import annotations

import bpy


FRACTURE_GENERATOR_VERSION = 2
FRACTURE_PIECE_ID_ATTRIBUTE = "hotools_piece_id"
DEFAULT_GRID_COUNTS = (5, 5, 5)
DEFAULT_GRID_GAP = 0.025


def _new_vector_math(nodes, operation: str, location, label: str):
    node = nodes.new("ShaderNodeVectorMath")
    node.operation = operation
    node.location = location
    node.label = label
    return node


def _axis_vector_math(nodes, source_socket, vector, location, label, links):
    node = _new_vector_math(nodes, "MULTIPLY", location, label)
    node.inputs[1].default_value = vector
    links.new(source_socket, node.inputs[0])
    return node.outputs[0]


def _add_grid_interface(group) -> None:
    group.interface.new_socket(
        name="Geometry",
        in_out="INPUT",
        socket_type="NodeSocketGeometry",
    )
    for name, default in zip(("X 切块", "Y 切块", "Z 切块"), DEFAULT_GRID_COUNTS):
        socket = group.interface.new_socket(
            name=name,
            in_out="INPUT",
            socket_type="NodeSocketInt",
        )
        socket.default_value = default
        socket.min_value = 1
        socket.max_value = 64
    gap = group.interface.new_socket(
        name="碎块间隙",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    gap.default_value = DEFAULT_GRID_GAP
    gap.min_value = 0.001
    gap.max_value = 0.25
    group.interface.new_socket(
        name="Geometry",
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )


def build_grid_fracture_group(group) -> None:
    """Replace *group* with the managed grid/boolean fracture graph."""
    group.nodes.clear()
    group.interface.clear()
    _add_grid_interface(group)

    nodes = group.nodes
    links = group.links
    group_input = nodes.new("NodeGroupInput")
    group_input.location = (-1120.0, 180.0)
    group_output = nodes.new("NodeGroupOutput")
    group_output.location = (1120.0, 180.0)

    bounds = nodes.new("GeometryNodeBoundBox")
    bounds.location = (-1120.0, -80.0)
    links.new(group_input.outputs["Geometry"], bounds.inputs["Geometry"])

    size = _new_vector_math(nodes, "SUBTRACT", (-900.0, -80.0), "包围盒尺寸")
    links.new(bounds.outputs["Max"], size.inputs[0])
    links.new(bounds.outputs["Min"], size.inputs[1])

    counts = nodes.new("ShaderNodeCombineXYZ")
    counts.location = (-900.0, -300.0)
    for axis, name in zip(("X", "Y", "Z"), ("X 切块", "Y 切块", "Z 切块")):
        links.new(group_input.outputs[name], counts.inputs[axis])

    cell_size = _new_vector_math(nodes, "DIVIDE", (-680.0, -80.0), "单元尺寸")
    links.new(size.outputs[0], cell_size.inputs[0])
    links.new(counts.outputs["Vector"], cell_size.inputs[1])

    gap_factor = nodes.new("ShaderNodeMath")
    gap_factor.operation = "SUBTRACT"
    gap_factor.location = (-680.0, -300.0)
    gap_factor.inputs[0].default_value = 1.0
    links.new(group_input.outputs["碎块间隙"], gap_factor.inputs[1])

    cutter_size = _new_vector_math(nodes, "SCALE", (-450.0, -80.0), "应用间隙")
    links.new(cell_size.outputs[0], cutter_size.inputs[0])
    links.new(gap_factor.outputs[0], cutter_size.inputs[3])

    center_add = _new_vector_math(nodes, "ADD", (-900.0, 120.0), "包围盒中心")
    links.new(bounds.outputs["Min"], center_add.inputs[0])
    links.new(bounds.outputs["Max"], center_add.inputs[1])
    center = _new_vector_math(nodes, "SCALE", (-680.0, 120.0), "中心 / 2")
    center.inputs[3].default_value = 0.5
    links.new(center_add.outputs[0], center.inputs[0])

    relative_min = _new_vector_math(nodes, "SUBTRACT", (-450.0, -300.0), "相对最小点")
    links.new(bounds.outputs["Min"], relative_min.inputs[0])
    links.new(center.outputs[0], relative_min.inputs[1])
    half_cell = _new_vector_math(nodes, "SCALE", (-450.0, -440.0), "半单元")
    half_cell.inputs[3].default_value = 0.5
    links.new(cell_size.outputs[0], half_cell.inputs[0])
    first_center = _new_vector_math(nodes, "ADD", (-230.0, -300.0), "首单元中心")
    links.new(relative_min.outputs[0], first_center.inputs[0])
    links.new(half_cell.outputs[0], first_center.inputs[1])

    cube = nodes.new("GeometryNodeMeshCube")
    cube.location = (-220.0, -40.0)
    cube.inputs["Vertices X"].default_value = 2
    cube.inputs["Vertices Y"].default_value = 2
    cube.inputs["Vertices Z"].default_value = 2
    links.new(cutter_size.outputs[0], cube.inputs["Size"])

    previous_geometry = cube.outputs["Mesh"]
    for column, (axis_name, mask) in enumerate((
        ("Z", (0.0, 0.0, 1.0)),
        ("Y", (0.0, 1.0, 0.0)),
        ("X", (1.0, 0.0, 0.0)),
    )):
        x = -10.0 + column * 230.0
        start = _axis_vector_math(
            nodes, first_center.outputs[0], mask, (x, -520.0),
            f"{axis_name} 起点", links,
        )
        offset = _axis_vector_math(
            nodes, cell_size.outputs[0], mask, (x, -680.0),
            f"{axis_name} 步长", links,
        )
        line = nodes.new("GeometryNodeMeshLine")
        line.location = (x, -350.0)
        line.mode = "OFFSET"
        links.new(group_input.outputs[f"{axis_name} 切块"], line.inputs["Count"])
        links.new(start, line.inputs["Start Location"])
        links.new(offset, line.inputs["Offset"])

        instance = nodes.new("GeometryNodeInstanceOnPoints")
        instance.location = (x + 120.0, -120.0)
        links.new(line.outputs["Mesh"], instance.inputs["Points"])
        links.new(previous_geometry, instance.inputs["Instance"])
        previous_geometry = instance.outputs["Instances"]

    realize = nodes.new("GeometryNodeRealizeInstances")
    realize.location = (720.0, -100.0)
    links.new(previous_geometry, realize.inputs["Geometry"])

    transform = nodes.new("GeometryNodeTransform")
    transform.location = (720.0, 60.0)
    links.new(realize.outputs["Geometry"], transform.inputs["Geometry"])
    links.new(center.outputs[0], transform.inputs["Translation"])

    boolean = nodes.new("GeometryNodeMeshBoolean")
    boolean.location = (900.0, 180.0)
    boolean.operation = "INTERSECT"
    if hasattr(boolean, "solver"):
        boolean.solver = "EXACT"
    links.new(group_input.outputs["Geometry"], boolean.inputs[0])
    links.new(transform.outputs["Geometry"], boolean.inputs[1])

    island = nodes.new("GeometryNodeInputMeshIsland")
    island.location = (900.0, -80.0)
    store_id = nodes.new("GeometryNodeStoreNamedAttribute")
    store_id.location = (1100.0, 180.0)
    store_id.data_type = "INT"
    store_id.domain = "FACE"
    store_id.inputs["Name"].default_value = FRACTURE_PIECE_ID_ATTRIBUTE
    links.new(boolean.outputs["Mesh"], store_id.inputs["Geometry"])
    links.new(island.outputs["Island Index"], store_id.inputs["Value"])
    links.new(store_id.outputs["Geometry"], group_output.inputs["Geometry"])

    group["hotools_generator"] = "rigid_fracture_grid"
    group["hotools_generator_version"] = FRACTURE_GENERATOR_VERSION
    group["hotools_piece_id_attribute"] = FRACTURE_PIECE_ID_ATTRIBUTE


def is_managed_fracture_group(group) -> bool:
    return bool(
        group is not None
        and getattr(group, "bl_idname", "") == "GeometryNodeTree"
        and str(group.get("hotools_generator", "")) == "rigid_fracture_grid"
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


def set_grid_modifier_inputs(modifier, *, counts=None, gap=None) -> None:
    """Set managed grid controls by interface name, independent of socket identifiers."""
    group = getattr(modifier, "node_group", None)
    if not is_managed_fracture_group(group):
        raise ValueError("修改器不是 HoTools 规则切块节点")
    values = {}
    if counts is not None:
        values.update(zip(("X 切块", "Y 切块", "Z 切块"), counts))
    if gap is not None:
        values["碎块间隙"] = gap
    for item in group.interface.items_tree:
        if (
            getattr(item, "item_type", "") == "SOCKET"
            and getattr(item, "in_out", "") == "INPUT"
            and item.name in values
        ):
            socket_properties = getattr(modifier.properties.inputs, item.identifier)
            socket_properties.value = values[item.name]


def new_grid_fracture_group(name: str):
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    build_grid_fracture_group(group)
    return group


__all__ = [
    "DEFAULT_GRID_COUNTS",
    "DEFAULT_GRID_GAP",
    "FRACTURE_GENERATOR_VERSION",
    "FRACTURE_PIECE_ID_ATTRIBUTE",
    "build_grid_fracture_group",
    "is_legacy_passthrough_group",
    "is_managed_fracture_group",
    "new_grid_fracture_group",
    "set_grid_modifier_inputs",
]
