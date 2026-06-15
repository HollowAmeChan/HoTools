from ..OmniNodeSocketMapping import _OmniFolderPath, _OmniImageFormat,_OmniRegex, _OmniGlob, _OmniDatablock, _OmniModifierType, _OmniModifier, _OmniMaterialSlot, _OmniUVLayer, _OmniColorAttribute, _OmniVertexGroup, _OmniShapeKey
from ..FunctionNodeCore import omni
from bpy.types import NodeSocketVector
import ast
import bpy
from datetime import datetime
from typing import Any
import mathutils
from . import _Color


def _parse_custom_property_token(token: str):
    token = str(token or "").strip()
    if len(token) < 4 or token[0] != "[" or token[-1] != "]":
        return None

    try:
        key = ast.literal_eval(token[1:-1].strip())
    except Exception:
        return None
    return key if isinstance(key, str) else None


def _parse_datablock_property_path(property_name: str):
    property_name = str(property_name or "").strip()
    if property_name.startswith("."):
        property_name = property_name[1:]
    if not property_name:
        return []

    segments = []
    index = 0
    while index < len(property_name):
        if property_name[index] == ".":
            index += 1
            continue

        if property_name[index] == "[":
            end = property_name.find("]", index)
            if end < 0:
                return []
            key = _parse_custom_property_token(property_name[index:end + 1])
            if key is None:
                return []
            segments.append(("key", key))
            index = end + 1
            continue

        start = index
        while index < len(property_name) and property_name[index] not in ".[":
            index += 1
        name = property_name[start:index].strip()
        if not name:
            return []
        segments.append(("attr", name))

    return segments


def _resolve_datablock_property_owner(datablock, property_name: str):
    segments = _parse_datablock_property_path(property_name)
    if not segments:
        return None, None

    owner = datablock
    for access_type, access_name in segments[:-1]:
        if owner is None:
            return None, None
        try:
            owner = getattr(owner, access_name) if access_type == "attr" else owner[access_name]
        except Exception:
            return None, None

    return owner, segments[-1]


def _read_datablock_property(datablock, property_name: str):
    property_name = str(property_name or "").strip()
    if datablock is None or not property_name:
        return None

    owner, last_segment = _resolve_datablock_property_owner(datablock, property_name)
    if owner is None or last_segment is None:
        return None

    access_type, access_name = last_segment
    try:
        return owner[access_name] if access_type == "key" else getattr(owner, access_name)
    except Exception:
        return None

@omni(enable=True,
      bl_label="颜色",
      base_color=_Color.colorCat["GetData"],
      )
def colorInput(color: mathutils.Color) -> mathutils.Color:
    return color


@omni(enable=True,
      bl_label="矢量",
      base_color=_Color.colorCat["GetData"],
      )
def vectorInput(vec: NodeSocketVector) -> NodeSocketVector:
    return vec

@omni(enable=True,
      bl_label="整数",
      base_color=_Color.colorCat["GetData"],)
def intInput(v: int) -> int:
    return v

@omni(enable=True,
      bl_label="浮点数",
      base_color=_Color.colorCat["GetData"],)
def floatInput(v: float) -> float:
    return v

@omni(enable=True, 
      bl_label="布尔",
      base_color=_Color.colorCat["GetData"],)
def boolInput(v: bool) -> bool:
    return v

@omni(enable=True, 
      bl_label="字符串",
      base_color=_Color.colorCat["GetData"],)
def stringInput(v: str) -> str:
    return v

@omni(enable=True,
      bl_label="当前时间",
      base_color=_Color.colorCat["GetData"],
      omni_description="输出当前系统本地时间，以及拆分后的年月日时分秒。",
      _OUTPUT_NAME=["时间", "年", "月", "日", "时", "分", "秒"],
      )
def currentTime() -> tuple[str, int, int, int, int, int, int]:
    now = datetime.now()
    return (
        now.strftime("%Y-%m-%d %H:%M:%S"),
        now.year,
        now.month,
        now.day,
        now.hour,
        now.minute,
        now.second,
    )

@omni(enable=True,
      bl_label="当前帧",
      base_color=_Color.colorCat["GetData"],
      omni_description="""
      输出当前场景的当前帧、帧范围和预览范围设置。
      在每帧运行模式下，OmniNode 会在 Blender 完成帧切换后运行，
      因此这里读到的是已经切换后的帧
      从起始帧 1 开始播放时，首次运行通常会读到第 2 帧。
      """,
      _OUTPUT_NAME=["当前帧", "帧开始", "帧结束", "预览开始", "预览结束", "启用预览范围"],
      )
def currentFrame() -> tuple[int, int, int, int, int, bool]:
    scene = bpy.context.scene
    return (
        scene.frame_current,
        scene.frame_start,
        scene.frame_end,
        scene.frame_preview_start,
        scene.frame_preview_end,
        scene.use_preview_range,
    )

@omni(enable=True,
      bl_label="场景帧率",
      base_color=_Color.colorCat["GetData"],
      omni_description="输出当前场景的实际帧率，以及每帧对应的秒数。",
      _OUTPUT_NAME=["帧率", "帧间隔"],
      )
def sceneFrameRate() -> tuple[float, float]:
    render = bpy.context.scene.render
    fps_base = render.fps_base if render.fps_base else 1.0
    fps = render.fps / fps_base
    return (
        fps,
        1.0 / fps if fps else 0.0,
    )

@omni(enable=True, 
      bl_label="文件路径",
      base_color=_Color.colorCat["GetData"],)
def filepathInput(v: _OmniFolderPath) -> _OmniFolderPath:
    return v

@omni(enable=True,
      bl_label="图像格式",
      base_color=_Color.colorCat["GetData"],)
def imageFormatInput(v:_OmniImageFormat) -> _OmniImageFormat:
    return v

@omni(enable=True,
      bl_label="Modifier Type",
      base_color=_Color.colorCat["GetData"],)
def modifierTypeInput(v: _OmniModifierType) -> _OmniModifierType:
    return v

@omni(enable=True,
      bl_label="修改器",
      base_color=_Color.colorCat["GetData"],)
def modifierInput(v: _OmniModifier) -> _OmniModifier:
    return v

@omni(enable=True,
      bl_label="Material Slot",
      base_color=_Color.colorCat["GetData"],)
def materialSlotInput(v: _OmniMaterialSlot) -> _OmniMaterialSlot:
    return v

@omni(enable=True,
      bl_label="UV槽",
      base_color=_Color.colorCat["GetData"],)
def uvLayerInput(v: _OmniUVLayer) -> _OmniUVLayer:
    return v

@omni(enable=True,
      bl_label="顶点色属性",
      base_color=_Color.colorCat["GetData"],)
def colorAttributeInput(v: _OmniColorAttribute) -> _OmniColorAttribute:
    return v

@omni(enable=True,
      bl_label="顶点组",
      base_color=_Color.colorCat["GetData"],)
def vertexGroupInput(v: _OmniVertexGroup) -> _OmniVertexGroup:
    if v is None or not isinstance(v, bpy.types.VertexGroup):
        raise ValueError("vertex group input is empty or invalid")
    return v

@omni(enable=True,
      bl_label="形态键",
      base_color=_Color.colorCat["GetData"],)
def shapeKeyInput(v: _OmniShapeKey) -> _OmniShapeKey:
    if not isinstance(v, dict):
        raise ValueError("shape key input is empty or invalid")
    obj = v.get("object")
    shape_key_name = str(v.get("shape_key") or "").strip()
    if obj is None or not isinstance(obj, bpy.types.Object) or obj.type != "MESH" or not shape_key_name:
        raise ValueError("shape key input is empty or invalid")
    return v

@omni(enable=True,
      bl_label="Datablock",
      base_color=_Color.colorCat["GetData"],)
def datablockInput(v: _OmniDatablock) -> _OmniDatablock:
    return v

@omni(enable=True,
      bl_label="获取Datablock数据",
      base_color=_Color.colorCat["GetData"],
      _INPUT_NAME=["数据块","属性名称"],
      )
def getDatablockProperty(datablock: _OmniDatablock, prop_name: str) -> Any:
    return _read_datablock_property(datablock, prop_name)

@omni(enable=True,
      bl_label="物体",
      bl_icon = "OBJECT_DATAMODE",
      base_color=_Color.colorCat["GetData"],
      )
def objectInput(obj: bpy.types.Object) -> bpy.types.Object:
    return obj

@omni(enable=True, 
      bl_label="集合",
      base_color=_Color.colorCat["GetData"],)
def collectionInput(col: bpy.types.Collection) -> bpy.types.Collection:
    return col

@omni(enable=True, 
      bl_label="材质",
      base_color=_Color.colorCat["GetData"],)
def materialInput(mat: bpy.types.Material) -> bpy.types.Material:
    return mat

@omni(enable=True,
      bl_label="图像",
      base_color=_Color.colorCat["GetData"],
      )
def imageInput(img: bpy.types.Image) -> bpy.types.Image:
    return img

@omni(enable=True, 
      bl_label="纹理",
      base_color=_Color.colorCat["GetData"],)
def textureInput(tex: bpy.types.Texture) -> bpy.types.Texture:
    return tex

# @meta(enable=True, 
#       bl_label="Mesh",
#       base_color=_Color.colorCat["GetData"],)
# def meshInput(mesh: bpy.types.Mesh) -> bpy.types.Mesh:
#     return mesh


# @meta(enable=True, 
#       bl_label="曲线",
#       base_color=_Color.colorCat["GetData"],)
# def curveInput(curve: bpy.types.Curve) -> bpy.types.Curve:
#     return curve


@omni(enable=True, 
      bl_label="骨架",
      base_color=_Color.colorCat["GetData"],)
def armatureInput(arm: bpy.types.Armature) -> bpy.types.Armature:
    return arm


@omni(enable=True, 
      bl_label="矩阵",
      base_color=_Color.colorCat["GetData"],)
def matrixInput(m: mathutils.Matrix) -> mathutils.Matrix:
    return m

@omni(enable=True,
      bl_label="正则表达式"
      ,base_color=_Color.colorCat["GetData"],)
def regexInput(r: _OmniRegex) -> _OmniRegex:
      return r

@omni(enable=True,
      bl_label="Glob表达式"
      ,base_color=_Color.colorCat["GetData"],)
def globInput(g: _OmniGlob) -> _OmniGlob:
      return g
