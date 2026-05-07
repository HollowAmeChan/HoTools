from ..OmniNodeSocketMapping import _OmniUVLayer
from ..FunctionNodeCore import omni
from . import _Color

import bpy


def _require_object(obj) -> bpy.types.Object:
    if obj is None or not isinstance(obj, bpy.types.Object):
        raise ValueError("物体输入未连接或无效")
    return obj


def _require_mesh_object(obj) -> bpy.types.Object:
    obj = _require_object(obj)
    if obj.type != "MESH" or obj.data is None:
        raise ValueError("目标物体不是有效的 Mesh")
    return obj


def _require_uv_layer(uv_layer) -> bpy.types.MeshUVLoopLayer:
    if uv_layer is None or not isinstance(uv_layer, bpy.types.MeshUVLoopLayer):
        raise ValueError("UV槽输入未连接或无效")
    return uv_layer


def _get_uv_layer_by_name(obj: bpy.types.Object, uv_name: str) -> bpy.types.MeshUVLoopLayer:
    obj = _require_mesh_object(obj)
    uv_name = str(uv_name or "").strip()
    if not uv_name:
        raise ValueError("UV槽名称为空")

    uv_layer = obj.data.uv_layers.get(uv_name)
    if uv_layer is None:
        raise ValueError(f"物体 '{obj.name}' 上找不到 UV 槽 '{uv_name}'")
    return uv_layer


def _get_uv_layer_by_index(obj: bpy.types.Object, uv_index: int) -> bpy.types.MeshUVLoopLayer:
    obj = _require_mesh_object(obj)
    uv_layers = obj.data.uv_layers
    if len(uv_layers) == 0:
        raise ValueError(f"物体 '{obj.name}' 没有任何 UV 槽")

    uv_index = int(uv_index)
    if uv_index < 0 or uv_index >= len(uv_layers):
        raise ValueError(
            f"UV 槽索引超出范围: {uv_index}，有效范围是 0 到 {len(uv_layers) - 1}"
        )
    return uv_layers[uv_index]


def _find_uv_layer_index(obj: bpy.types.Object, uv_layer: bpy.types.MeshUVLoopLayer) -> int:
    obj = _require_mesh_object(obj)
    for index, layer in enumerate(obj.data.uv_layers):
        if layer == uv_layer:
            return index
    return -1


@omni(
    enable=True,
    bl_label="创建UV槽",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "UV槽名称"],
    _OUTPUT_NAME=["物体", "UV槽", "UV槽名称"],
    bl_icon="GROUP_UVS",
    omni_description="""
    在目标 Mesh 上创建一个 UV 槽。
    如果同名 UV 槽已经存在，则直接返回已有的 UV 槽。
    """,
)
def objectCreateUVLayer(
    obj: bpy.types.Object,
    uv_name: str,
) -> tuple[bpy.types.Object, bpy.types.MeshUVLoopLayer, str]:
    obj = _require_mesh_object(obj)
    uv_name = str(uv_name or "").strip()
    if not uv_name:
        raise ValueError("UV槽名称为空")

    uv_layer = obj.data.uv_layers.get(uv_name)
    if uv_layer is None:
        uv_layer = obj.data.uv_layers.new(name=uv_name)
    return obj, uv_layer, uv_layer.name


@omni(
    enable=True,
    bl_label="按名称获取UV槽",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "UV槽名称"],
    _OUTPUT_NAME=["UV槽"],
    bl_icon="GROUP_UVS",
)
def objectGetUVLayerByName(
    obj: bpy.types.Object,
    uv_name: str,
) -> bpy.types.MeshUVLoopLayer:
    return _get_uv_layer_by_name(obj, uv_name)


@omni(
    enable=True,
    bl_label="按索引获取UV槽",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "UV槽索引"],
    _OUTPUT_NAME=["UV槽"],
    bl_icon="GROUP_UVS",
)
def objectGetUVLayerByIndex(
    obj: bpy.types.Object,
    uv_index: int,
) -> bpy.types.MeshUVLoopLayer:
    return _get_uv_layer_by_index(obj, uv_index)


@omni(
    enable=True,
    bl_label="获取激活UV槽",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体"],
    _OUTPUT_NAME=["UV槽"],
    bl_icon="GROUP_UVS",
)
def objectGetActiveUVLayer(
    obj: bpy.types.Object,
) -> bpy.types.MeshUVLoopLayer:
    obj = _require_mesh_object(obj)
    uv_layer = obj.data.uv_layers.active
    if uv_layer is None:
        raise ValueError(f"物体 '{obj.name}' 没有激活 UV 槽")
    return uv_layer


@omni(
    enable=True,
    bl_label="获取渲染UV槽",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体"],
    _OUTPUT_NAME=["UV槽"],
    bl_icon="GROUP_UVS",
)
def objectGetRenderUVLayer(
    obj: bpy.types.Object,
) -> bpy.types.MeshUVLoopLayer:
    obj = _require_mesh_object(obj)
    for uv_layer in obj.data.uv_layers:
        if uv_layer.active_render:
            return uv_layer
    raise ValueError(f"物体 '{obj.name}' 没有标记为渲染的 UV 槽")


@omni(
    enable=True,
    bl_label="获取UV槽名称",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["UV槽"],
    _OUTPUT_NAME=["UV槽名称"],
    bl_icon="GROUP_UVS",
)
def uvLayerGetName(
    uv_layer: _OmniUVLayer,
) -> str:
    uv_layer = _require_uv_layer(uv_layer)
    return uv_layer.name


@omni(
    enable=True,
    bl_label="获取UV槽索引",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "UV槽"],
    _OUTPUT_NAME=["UV槽索引"],
    bl_icon="GROUP_UVS",
)
def objectGetUVLayerIndex(
    obj: bpy.types.Object,
    uv_layer: _OmniUVLayer,
) -> int:
    obj = _require_mesh_object(obj)
    uv_layer = _require_uv_layer(uv_layer)
    index = _find_uv_layer_index(obj, uv_layer)
    if index < 0:
        raise ValueError(f"物体 '{obj.name}' 上找不到指定的 UV 槽")
    return index


@omni(
    enable=True,
    bl_label="重命名UV槽",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["UV槽", "新名称"],
    _OUTPUT_NAME=["UV槽", "UV槽名称"],
    bl_icon="GROUP_UVS",
)
def uvLayerRename(
    uv_layer: _OmniUVLayer,
    new_name: str,
) -> tuple[bpy.types.MeshUVLoopLayer, str]:
    uv_layer = _require_uv_layer(uv_layer)
    new_name = str(new_name or "").strip()
    if not new_name:
        raise ValueError("新UV槽名称为空")
    uv_layer.name = new_name
    return uv_layer, uv_layer.name


@omni(
    enable=True,
    bl_label="设置激活UV槽",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "UV槽"],
    _OUTPUT_NAME=["物体", "UV槽"],
    bl_icon="GROUP_UVS",
)
def objectSetActiveUVLayer(
    obj: bpy.types.Object,
    uv_layer: _OmniUVLayer,
) -> tuple[bpy.types.Object, bpy.types.MeshUVLoopLayer]:
    obj = _require_mesh_object(obj)
    uv_layer = _require_uv_layer(uv_layer)
    index = _find_uv_layer_index(obj, uv_layer)
    if index < 0:
        raise ValueError(f"物体 '{obj.name}' 上找不到指定的 UV 槽")
    obj.data.uv_layers.active_index = index
    return obj, obj.data.uv_layers.active


@omni(
    enable=True,
    bl_label="设置激活UV槽索引",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "UV槽索引"],
    _OUTPUT_NAME=["物体", "UV槽"],
    bl_icon="GROUP_UVS",
)
def objectSetActiveUVLayerByIndex(
    obj: bpy.types.Object,
    uv_index: int,
) -> tuple[bpy.types.Object, bpy.types.MeshUVLoopLayer]:
    obj = _require_mesh_object(obj)
    uv_layer = _get_uv_layer_by_index(obj, uv_index)
    obj.data.uv_layers.active_index = int(uv_index)
    return obj, uv_layer


@omni(
    enable=True,
    bl_label="设置渲染UV槽",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "UV槽"],
    _OUTPUT_NAME=["物体", "UV槽"],
    bl_icon="GROUP_UVS",
)
def objectSetRenderUVLayer(
    obj: bpy.types.Object,
    uv_layer: _OmniUVLayer,
) -> tuple[bpy.types.Object, bpy.types.MeshUVLoopLayer]:
    obj = _require_mesh_object(obj)
    uv_layer = _require_uv_layer(uv_layer)
    index = _find_uv_layer_index(obj, uv_layer)
    if index < 0:
        raise ValueError(f"物体 '{obj.name}' 上找不到指定的 UV 槽")
    for layer in obj.data.uv_layers:
        layer.active_render = False
    obj.data.uv_layers[index].active_render = True
    return obj, obj.data.uv_layers[index]


@omni(
    enable=True,
    bl_label="删除UV槽对象",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "UV槽"],
    _OUTPUT_NAME=["物体"],
    bl_icon="GROUP_UVS",
)
def objectRemoveUVLayer(
    obj: bpy.types.Object,
    uv_layer: _OmniUVLayer,
) -> bpy.types.Object:
    obj = _require_mesh_object(obj)
    uv_layer = _require_uv_layer(uv_layer)
    index = _find_uv_layer_index(obj, uv_layer)
    if index < 0:
        raise ValueError(f"物体 '{obj.name}' 上找不到指定的 UV 槽")
    obj.data.uv_layers.remove(obj.data.uv_layers[index])
    return obj
