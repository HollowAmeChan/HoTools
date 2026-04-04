from ..FunctionCore import meta
from bpy.types import NodeSocketVector
import bpy
from typing import Any
import mathutils
from . import _COLOR

@meta(enable=True,
      bl_label="颜色",
      base_color=_COLOR.colorCat["GetData"],
      )
def colorInput(color: mathutils.Color) -> mathutils.Color:
    return color


@meta(enable=True,
      bl_label="矢量",
      base_color=_COLOR.colorCat["GetData"],
      )
def vectorInput(vec: NodeSocketVector) -> NodeSocketVector:
    return vec

@meta(enable=True,
      bl_label="整数",
      base_color=_COLOR.colorCat["GetData"],)
def intInput(v: int) -> int:
    return v

@meta(enable=True,
      bl_label="浮点数",
      base_color=_COLOR.colorCat["GetData"],)
def floatInput(v: float) -> float:
    return v

@meta(enable=True, 
      bl_label="布尔",
      base_color=_COLOR.colorCat["GetData"],)
def boolInput(v: bool) -> bool:
    return v

@meta(enable=True, 
      bl_label="字符串",
      base_color=_COLOR.colorCat["GetData"],)
def stringInput(v: str) -> str:
    return v

# @meta(enable=True, 
#       bl_label="文件路径",
#       base_color=_COLOR.colorCat["GetData"],)
# def filepathInput(v: str) -> str:
#     return v

@meta(enable=True,
      bl_label="物体",
      bl_icon = "OBJECT_DATAMODE",
      base_color=_COLOR.colorCat["GetData"],
      )
def objectInput(obj: bpy.types.Object) -> bpy.types.Object:
    return obj

@meta(enable=True, 
      bl_label="集合",
      base_color=_COLOR.colorCat["GetData"],)
def collectionInput(col: bpy.types.Collection) -> bpy.types.Collection:
    return col

@meta(enable=True, 
      bl_label="材质",
      base_color=_COLOR.colorCat["GetData"],)
def materialInput(mat: bpy.types.Material) -> bpy.types.Material:
    return mat

@meta(enable=True,
      bl_label="图像",
      base_color=_COLOR.colorCat["GetData"],
      )
def imageInput(img: bpy.types.Image) -> bpy.types.Image:
    return img

@meta(enable=True, 
      bl_label="纹理",
      base_color=_COLOR.colorCat["GetData"],)
def textureInput(tex: bpy.types.Texture) -> bpy.types.Texture:
    return tex

# @meta(enable=True, 
#       bl_label="Mesh",
#       base_color=_COLOR.colorCat["GetData"],)
# def meshInput(mesh: bpy.types.Mesh) -> bpy.types.Mesh:
#     return mesh


# @meta(enable=True, 
#       bl_label="曲线",
#       base_color=_COLOR.colorCat["GetData"],)
# def curveInput(curve: bpy.types.Curve) -> bpy.types.Curve:
#     return curve


@meta(enable=True, 
      bl_label="骨架",
      base_color=_COLOR.colorCat["GetData"],)
def armatureInput(arm: bpy.types.Armature) -> bpy.types.Armature:
    return arm


@meta(enable=True, 
      bl_label="矩阵",
      base_color=_COLOR.colorCat["GetData"],)
def matrixInput(m: mathutils.Matrix) -> mathutils.Matrix:
    return m