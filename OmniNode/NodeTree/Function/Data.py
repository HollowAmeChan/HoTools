from ..OmniNodeSocketMapping import _OmniFolderPath, _OmniImageFormat,_OmniRegex, _OmniGlob
from ..FunctionNodeCore import omni
from bpy.types import NodeSocketVector
import bpy
from typing import Any
import mathutils
from . import _Color

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

