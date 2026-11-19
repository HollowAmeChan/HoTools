"""Add CopyMesh to HoAssets/GN.blend using Blender's Python interpreter.

Run: blender --background --factory-startup --disable-autoexec \
    --python-exit-code 1 --python tools/build_copy_mesh_asset.py
"""

from pathlib import Path

import bpy


ASSET_PATH = Path(__file__).resolve().parents[1] / "HoAssets" / "GN.blend"
CATALOG_ID = "b48222de-168c-4553-b6ff-032d3f992197"


def build_copy_mesh():
    """Build a modifier asset that replaces the incoming geometry."""
    group = bpy.data.node_groups.get("CopyMesh")
    if group is None:
        group = bpy.data.node_groups.new("CopyMesh", "GeometryNodeTree")
    elif group.bl_idname != "GeometryNodeTree":
        raise TypeError("CopyMesh already exists as a different node tree type")
    group.nodes.clear()
    group.interface.clear()
    group.is_modifier = True
    group.use_fake_user = True
    group.description = (
        "使用源物体或集合的几何体替换当前物体网格。"
        "“集合模式”关闭时使用物体，开启时使用集合。"
        "默认保留实例，开启“非实例”后实现全部实例。"
    )

    group.interface.new_socket(
        name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )
    geometry = group.interface.new_socket(
        name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
    )
    geometry.description = "当前物体的原始几何体，将被源物体或集合的几何体替换"
    mode = group.interface.new_socket(
        name="集合模式", in_out="INPUT", socket_type="NodeSocketBool"
    )
    mode.default_value = False
    mode.description = "关闭：物体模式，使用物体输入；开启：集合模式，使用集合输入"
    mode.force_non_field = True
    source = group.interface.new_socket(
        name="物体", in_out="INPUT", socket_type="NodeSocketObject"
    )
    source.description = "物体模式下复制该物体的求值后几何体，忽略物体变换"
    collection = group.interface.new_socket(
        name="集合", in_out="INPUT", socket_type="NodeSocketCollection"
    )
    collection.description = "集合模式下复制该集合，保留集合内各物体的变换"
    realize = group.interface.new_socket(
        name="非实例", in_out="INPUT", socket_type="NodeSocketBool"
    )
    realize.default_value = False
    realize.description = "将全部嵌套实例转为实际几何体，供后续网格节点及修改器处理"
    realize.force_non_field = True

    def node(node_type, name, location, width=180):
        result = group.nodes.new(node_type)
        result.name = name
        result.label = name
        result.location = location
        result.width = width
        return result

    inputs = node("NodeGroupInput", "输入参数", (-620, 100))
    object_info = node("GeometryNodeObjectInfo", "读取源物体", (-360, 250))
    object_info.transform_space = "ORIGINAL"
    object_info.inputs["As Instance"].default_value = True
    collection_info = node(
        "GeometryNodeCollectionInfo", "读取源集合", (-360, -100)
    )
    collection_info.transform_space = "ORIGINAL"
    collection_info.inputs["Separate Children"].default_value = False
    collection_info.inputs["Reset Children"].default_value = False
    choose = node("GeometryNodeSwitch", "集合模式：关闭物体 / 开启集合", (-80, 100), 230)
    choose.input_type = "GEOMETRY"
    realize_node = node(
        "GeometryNodeRealizeInstances", "非实例：实现全部实例", (220, 100), 210
    )
    realize_node.inputs["Realize All"].default_value = True
    output = node("NodeGroupOutput", "替换网格", (500, 100))
    output.is_active_output = True

    link = group.links.new
    link(inputs.outputs["物体"], object_info.inputs["Object"])
    link(inputs.outputs["集合"], collection_info.inputs["Collection"])
    link(inputs.outputs["集合模式"], choose.inputs["Switch"])
    link(object_info.outputs["Geometry"], choose.inputs["False"])
    link(collection_info.outputs["Instances"], choose.inputs["True"])
    link(choose.outputs["Output"], realize_node.inputs["Geometry"])
    link(inputs.outputs["非实例"], realize_node.inputs["Selection"])
    link(realize_node.outputs["Geometry"], output.inputs["Geometry"])

    group.asset_mark()
    group.asset_data.catalog_id = CATALOG_ID
    group.asset_data.description = group.description
    return group


def main():
    bpy.ops.wm.open_mainfile(filepath=str(ASSET_PATH), load_ui=True)
    build_copy_mesh()
    # Keep the library's existing .blend1 backup intact.
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(ASSET_PATH))
    print(f"Saved CopyMesh to {ASSET_PATH}")


if __name__ == "__main__":
    main()
