"""
MC2 MeshCloth setup 的后置 delta 输出工具。

这是旧 MC2 运行路径的兼容工具，只管理其既有 ``mc2_delta`` 输出：
1. 它不构成新 Physics World 的公开写回契约，也不得被新 solver 用来创建私有属性槽。
2. 新路径统一发布对象局部最终 offset，由 ``physicsWorld.gn_offset`` 写入共享属性。
3. 旧路径仍以 world display position - world base position 转换本地 offset，直到迁移完成。
4. 修改器位于 Armature/基础变形之后，保证旧 MC2 当前行为不漂移。
"""

from dataclasses import dataclass

import bpy
import numpy as np


@dataclass(frozen=True)
class PhysicsDeltaOutputSpec:
    attribute_name: str
    modifier_name: str
    node_group_name: str
    label: str = "物理后置位移"


def matrix_to_numpy(matrix) -> np.ndarray:
    return np.asarray(
        [[float(matrix[row][col]) for col in range(4)] for row in range(4)],
        dtype=np.float32,
    )


def _new_geometry_nodes_group(spec: PhysicsDeltaOutputSpec) -> bpy.types.NodeTree:
    group = bpy.data.node_groups.new(spec.node_group_name, "GeometryNodeTree")
    if hasattr(group, "interface"):
        group.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    else:
        group.inputs.new("NodeSocketGeometry", "Geometry")
        group.outputs.new("NodeSocketGeometry", "Geometry")

    nodes = group.nodes
    links = group.links
    input_node = nodes.new("NodeGroupInput")
    output_node = nodes.new("NodeGroupOutput")
    named_attr = nodes.new("GeometryNodeInputNamedAttribute")
    set_position = nodes.new("GeometryNodeSetPosition")

    input_node.location = (-600, 0)
    named_attr.location = (-600, -180)
    set_position.location = (-260, 0)
    output_node.location = (80, 0)

    named_attr.data_type = "FLOAT_VECTOR"
    if "Name" in named_attr.inputs:
        named_attr.inputs["Name"].default_value = spec.attribute_name

    links.new(input_node.outputs["Geometry"], set_position.inputs["Geometry"])
    links.new(named_attr.outputs["Attribute"], set_position.inputs["Offset"])
    links.new(set_position.outputs["Geometry"], output_node.inputs["Geometry"])
    return group


def ensure_delta_node_group(spec: PhysicsDeltaOutputSpec) -> bpy.types.NodeTree:
    group = bpy.data.node_groups.get(spec.node_group_name)
    if group is not None and getattr(group, "bl_idname", "") == "GeometryNodeTree":
        return group
    return _new_geometry_nodes_group(spec)


def _move_modifier_to_bottom(obj: bpy.types.Object, modifier) -> None:
    modifiers = obj.modifiers
    index = modifiers.find(modifier.name)
    if index < 0 or index >= len(modifiers) - 1:
        return
    if hasattr(modifiers, "move"):
        modifiers.move(index, len(modifiers) - 1)
        return
    active = bpy.context.view_layer.objects.active
    try:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_move_to_index(modifier=modifier.name, index=len(modifiers) - 1)
    finally:
        bpy.context.view_layer.objects.active = active


def ensure_delta_modifier(obj: bpy.types.Object, spec: PhysicsDeltaOutputSpec) -> bpy.types.Modifier:
    if obj is None or obj.type != "MESH":
        raise ValueError(f"{spec.label}只能添加到 Mesh 对象")
    group = ensure_delta_node_group(spec)
    modifier = obj.modifiers.get(spec.modifier_name)
    if modifier is None:
        modifier = obj.modifiers.new(spec.modifier_name, "NODES")
    modifier.node_group = group
    _move_modifier_to_bottom(obj, modifier)
    return modifier


def ensure_delta_attribute(obj: bpy.types.Object, spec: PhysicsDeltaOutputSpec) -> bpy.types.Attribute:
    if obj is None or obj.type != "MESH" or obj.data is None:
        raise ValueError(f"{spec.label}属性只能写入 Mesh 对象")
    mesh = obj.data
    attr = mesh.attributes.get(spec.attribute_name)
    if attr is not None and (attr.domain != "POINT" or attr.data_type != "FLOAT_VECTOR"):
        mesh.attributes.remove(attr)
        attr = None
    if attr is None:
        attr = mesh.attributes.new(spec.attribute_name, "FLOAT_VECTOR", "POINT")
    return attr


def ensure_delta_output(obj: bpy.types.Object, spec: PhysicsDeltaOutputSpec) -> None:
    ensure_delta_attribute(obj, spec)
    ensure_delta_modifier(obj, spec)


def clear_delta_attribute(obj: bpy.types.Object, spec: PhysicsDeltaOutputSpec) -> None:
    attr = obj.data.attributes.get(spec.attribute_name) if obj is not None and obj.type == "MESH" else None
    if attr is None or attr.domain != "POINT" or attr.data_type != "FLOAT_VECTOR":
        return
    zeros = np.zeros(len(obj.data.vertices) * 3, dtype=np.float32)
    attr.data.foreach_set("vector", zeros)
    # 不需要刷新 刷新拖累性能
    # obj.data.update()
    # obj.update_tag()


def write_world_delta_attribute(
    obj: bpy.types.Object,
    spec: PhysicsDeltaOutputSpec,
    display_positions: np.ndarray,
    base_positions: np.ndarray,
) -> None:
    ensure_delta_output(obj, spec)
    attr = ensure_delta_attribute(obj, spec)
    vertex_count = len(obj.data.vertices)
    display = np.ascontiguousarray(display_positions, dtype=np.float32)
    base = np.ascontiguousarray(base_positions, dtype=np.float32)
    if display.shape != (vertex_count, 3) or base.shape != (vertex_count, 3):
        raise ValueError(f"{spec.label}写入要求 display/base 顶点数量一致")
    world_delta = np.ascontiguousarray(display - base, dtype=np.float32)
    inv_basis = matrix_to_numpy(obj.matrix_world.inverted())[:3, :3]
    delta = np.ascontiguousarray(world_delta @ inv_basis.T, dtype=np.float32)
    attr.data.foreach_set("vector", delta.reshape(-1))
    obj.data.update()
    obj.update_tag()


def remove_delta_output(obj: bpy.types.Object, spec: PhysicsDeltaOutputSpec) -> None:
    if obj is None or obj.type != "MESH":
        return
    modifier = obj.modifiers.get(spec.modifier_name)
    if modifier is not None:
        obj.modifiers.remove(modifier)
    if obj.data is not None:
        attr = obj.data.attributes.get(spec.attribute_name)
        if attr is not None:
            obj.data.attributes.remove(attr)
