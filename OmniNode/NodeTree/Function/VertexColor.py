from ..OmniNodeSocketMapping import _OmniColorAttribute
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


def _require_color_attribute(color_attribute) -> bpy.types.Attribute:
    if color_attribute is None or not isinstance(color_attribute, bpy.types.Attribute):
        raise ValueError("顶点色属性输入未连接或无效")
    return color_attribute


def _require_color_attribute_name(attribute_name: str) -> str:
    attribute_name = str(attribute_name or "").strip()
    if not attribute_name:
        raise ValueError("顶点色属性名称不能为空")
    return attribute_name


def _get_color_attributes(obj: bpy.types.Object):
    return _require_mesh_object(obj).data.color_attributes


def _ensure_color_attribute(color_attribute: bpy.types.Attribute) -> bpy.types.Attribute:
    color_attribute = _require_color_attribute(color_attribute)
    if color_attribute.data_type not in {"BYTE_COLOR", "FLOAT_COLOR"}:
        raise ValueError(f"属性 '{color_attribute.name}' 不是颜色属性")
    return color_attribute


def _get_color_attribute_by_name(obj: bpy.types.Object, attribute_name: str) -> bpy.types.Attribute:
    color_attributes = _get_color_attributes(obj)
    attribute_name = _require_color_attribute_name(attribute_name)
    color_attribute = color_attributes.get(attribute_name)
    if color_attribute is None:
        raise ValueError(f"物体 '{obj.name}' 上找不到顶点色属性 '{attribute_name}'")
    return _ensure_color_attribute(color_attribute)


def _get_color_attribute_by_index(obj: bpy.types.Object, attribute_index: int) -> bpy.types.Attribute:
    color_attributes = _get_color_attributes(obj)
    if len(color_attributes) == 0:
        raise ValueError(f"物体 '{obj.name}' 没有任何顶点色属性")

    attribute_index = int(attribute_index)
    if attribute_index < 0 or attribute_index >= len(color_attributes):
        raise ValueError(
            f"顶点色属性索引超出范围: {attribute_index}，有效范围是 0 到 {len(color_attributes) - 1}"
        )
    return _ensure_color_attribute(color_attributes[attribute_index])


def _find_color_attribute_index(obj: bpy.types.Object, color_attribute: bpy.types.Attribute) -> int:
    color_attributes = _get_color_attributes(obj)
    for index, attribute in enumerate(color_attributes):
        if attribute == color_attribute:
            return index
    return -1


def _get_active_color_attribute(obj: bpy.types.Object) -> bpy.types.Attribute:
    color_attributes = _get_color_attributes(obj)
    if len(color_attributes) == 0:
        raise ValueError(f"物体 '{obj.name}' 没有任何顶点色属性")

    active_name = getattr(color_attributes, "active_color_name", "")
    if active_name:
        color_attribute = color_attributes.get(active_name)
        if color_attribute is not None:
            return _ensure_color_attribute(color_attribute)

    active_index = getattr(color_attributes, "active_color_index", -1)
    if 0 <= active_index < len(color_attributes):
        return _ensure_color_attribute(color_attributes[active_index])

    raise ValueError(f"物体 '{obj.name}' 没有活动顶点色属性")


def _get_render_color_attribute(obj: bpy.types.Object) -> bpy.types.Attribute:
    color_attributes = _get_color_attributes(obj)
    if len(color_attributes) == 0:
        raise ValueError(f"物体 '{obj.name}' 没有任何顶点色属性")

    render_name = getattr(color_attributes, "default_color_name", "")
    if render_name:
        color_attribute = color_attributes.get(render_name)
        if color_attribute is not None:
            return _ensure_color_attribute(color_attribute)

    render_index = getattr(color_attributes, "render_color_index", -1)
    if 0 <= render_index < len(color_attributes):
        return _ensure_color_attribute(color_attributes[render_index])

    raise ValueError(f"物体 '{obj.name}' 没有渲染顶点色属性")


@omni(
    enable=True,
    bl_label="创建顶点色属性",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "属性名称", "颜色类型", "属性域"],
    _OUTPUT_NAME=["物体", "顶点色属性", "属性名称"],
    bl_icon="GROUP_VCOL",
    omni_description="""
    在目标 Mesh 上创建一个顶点色属性。
    如果同名属性已经存在，则直接返回已有属性。
    """,
)
def objectCreateColorAttribute(
    obj: bpy.types.Object,
    attribute_name: str,
    data_type: str = "BYTE_COLOR",
    domain: str = "CORNER",
) -> tuple[bpy.types.Object, bpy.types.Attribute, str]:
    color_attributes = _get_color_attributes(obj)
    attribute_name = _require_color_attribute_name(attribute_name)
    color_attribute = color_attributes.get(attribute_name)
    if color_attribute is None:
        color_attribute = color_attributes.new(
            name=attribute_name,
            type=str(data_type or "BYTE_COLOR"),
            domain=str(domain or "CORNER"),
        )
    color_attribute = _ensure_color_attribute(color_attribute)
    return obj, color_attribute, color_attribute.name


@omni(
    enable=True,
    bl_label="按名称获取顶点色属性",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "属性名称"],
    _OUTPUT_NAME=["顶点色属性"],
    bl_icon="GROUP_VCOL",
)
def objectGetColorAttributeByName(
    obj: bpy.types.Object,
    attribute_name: str,
) -> bpy.types.Attribute:
    return _get_color_attribute_by_name(obj, attribute_name)


@omni(
    enable=True,
    bl_label="按索引获取顶点色属性",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "属性索引"],
    _OUTPUT_NAME=["顶点色属性"],
    bl_icon="GROUP_VCOL",
)
def objectGetColorAttributeByIndex(
    obj: bpy.types.Object,
    attribute_index: int,
) -> bpy.types.Attribute:
    return _get_color_attribute_by_index(obj, attribute_index)


@omni(
    enable=True,
    bl_label="获取活动顶点色属性",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体"],
    _OUTPUT_NAME=["顶点色属性"],
    bl_icon="GROUP_VCOL",
)
def objectGetActiveColorAttribute(
    obj: bpy.types.Object,
) -> bpy.types.Attribute:
    return _get_active_color_attribute(obj)


@omni(
    enable=True,
    bl_label="获取渲染顶点色属性",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体"],
    _OUTPUT_NAME=["顶点色属性"],
    bl_icon="GROUP_VCOL",
)
def objectGetRenderColorAttribute(
    obj: bpy.types.Object,
) -> bpy.types.Attribute:
    return _get_render_color_attribute(obj)


@omni(
    enable=True,
    bl_label="获取顶点色属性名称",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["顶点色属性"],
    _OUTPUT_NAME=["属性名称"],
    bl_icon="GROUP_VCOL",
)
def colorAttributeGetName(
    color_attribute: _OmniColorAttribute,
) -> str:
    color_attribute = _ensure_color_attribute(color_attribute)
    return color_attribute.name


@omni(
    enable=True,
    bl_label="获取顶点色属性类型",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["顶点色属性"],
    _OUTPUT_NAME=["颜色类型"],
    bl_icon="GROUP_VCOL",
)
def colorAttributeGetType(
    color_attribute: _OmniColorAttribute,
) -> str:
    color_attribute = _ensure_color_attribute(color_attribute)
    return color_attribute.data_type


@omni(
    enable=True,
    bl_label="获取顶点色属性域",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["顶点色属性"],
    _OUTPUT_NAME=["属性域"],
    bl_icon="GROUP_VCOL",
)
def colorAttributeGetDomain(
    color_attribute: _OmniColorAttribute,
) -> str:
    color_attribute = _ensure_color_attribute(color_attribute)
    return color_attribute.domain


@omni(
    enable=True,
    bl_label="获取顶点色属性索引",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "顶点色属性"],
    _OUTPUT_NAME=["属性索引"],
    bl_icon="GROUP_VCOL",
)
def objectGetColorAttributeIndex(
    obj: bpy.types.Object,
    color_attribute: _OmniColorAttribute,
) -> int:
    color_attribute = _ensure_color_attribute(color_attribute)
    index = _find_color_attribute_index(obj, color_attribute)
    if index < 0:
        raise ValueError(f"物体 '{obj.name}' 上找不到指定的顶点色属性")
    return index


@omni(
    enable=True,
    bl_label="重命名顶点色属性",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["顶点色属性", "新名称"],
    _OUTPUT_NAME=["顶点色属性", "属性名称"],
    bl_icon="GROUP_VCOL",
)
def colorAttributeRename(
    color_attribute: _OmniColorAttribute,
    new_name: str,
) -> tuple[bpy.types.Attribute, str]:
    color_attribute = _ensure_color_attribute(color_attribute)
    new_name = _require_color_attribute_name(new_name)
    color_attribute.name = new_name
    return color_attribute, color_attribute.name


@omni(
    enable=True,
    bl_label="设置活动顶点色属性",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "顶点色属性"],
    _OUTPUT_NAME=["物体", "顶点色属性"],
    bl_icon="GROUP_VCOL",
)
def objectSetActiveColorAttribute(
    obj: bpy.types.Object,
    color_attribute: _OmniColorAttribute,
) -> tuple[bpy.types.Object, bpy.types.Attribute]:
    color_attribute = _ensure_color_attribute(color_attribute)
    color_attributes = _get_color_attributes(obj)
    index = _find_color_attribute_index(obj, color_attribute)
    if index < 0:
        raise ValueError(f"物体 '{obj.name}' 上找不到指定的顶点色属性")
    color_attributes.active_color_index = index
    return obj, color_attributes[index]


@omni(
    enable=True,
    bl_label="设置活动顶点色属性索引",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "属性索引"],
    _OUTPUT_NAME=["物体", "顶点色属性"],
    bl_icon="GROUP_VCOL",
)
def objectSetActiveColorAttributeByIndex(
    obj: bpy.types.Object,
    attribute_index: int,
) -> tuple[bpy.types.Object, bpy.types.Attribute]:
    color_attributes = _get_color_attributes(obj)
    color_attribute = _get_color_attribute_by_index(obj, attribute_index)
    color_attributes.active_color_index = int(attribute_index)
    return obj, color_attribute


@omni(
    enable=True,
    bl_label="设置渲染顶点色属性",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "顶点色属性"],
    _OUTPUT_NAME=["物体", "顶点色属性"],
    bl_icon="GROUP_VCOL",
)
def objectSetRenderColorAttribute(
    obj: bpy.types.Object,
    color_attribute: _OmniColorAttribute,
) -> tuple[bpy.types.Object, bpy.types.Attribute]:
    color_attribute = _ensure_color_attribute(color_attribute)
    color_attributes = _get_color_attributes(obj)
    index = _find_color_attribute_index(obj, color_attribute)
    if index < 0:
        raise ValueError(f"物体 '{obj.name}' 上找不到指定的顶点色属性")

    if hasattr(color_attributes, "render_color_index"):
        color_attributes.render_color_index = index
    if hasattr(color_attributes, "default_color_name"):
        try:
            color_attributes.default_color_name = color_attributes[index].name
        except Exception:
            pass
    return obj, color_attributes[index]


@omni(
    enable=True,
    bl_label="删除顶点色属性对象",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "顶点色属性"],
    _OUTPUT_NAME=["物体"],
    bl_icon="GROUP_VCOL",
)
def objectRemoveColorAttribute(
    obj: bpy.types.Object,
    color_attribute: _OmniColorAttribute,
) -> bpy.types.Object:
    color_attribute = _ensure_color_attribute(color_attribute)
    color_attributes = _get_color_attributes(obj)
    index = _find_color_attribute_index(obj, color_attribute)
    if index < 0:
        raise ValueError(f"物体 '{obj.name}' 上找不到指定的顶点色属性")
    color_attributes.remove(color_attributes[index])
    return obj
