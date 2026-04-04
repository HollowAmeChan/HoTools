from ..FunctionCore import meta
from bpy.types import NodeSocketVector, NodeSocketColor
import bpy
import typing
from typing import Any
import time
import mathutils
from . import _COLOR


@meta(enable=True,
      bl_label="设置物体位置",
      base_color=_COLOR.colorCat["SetBlenderProp"],
      is_output_node=True,
      color_tag = "GEOMETRY",
      bl_icon = "OBJECT_DATAMODE",
      )
def objectSetPosition(obj: bpy.types.Object, pos: NodeSocketVector) -> bpy.types.Object:
    obj.location = pos
    return obj


@meta(enable=True,
      bl_label="Float加法",
      base_color=_COLOR.colorCat["BaseMathFunction"],
      color_tag = "CONVERTER",
      )
def floatAdd(a: float, b: float) -> float:
    return a+b


@meta(enable=True,
      bl_label="物体输入",
      bl_icon = "OBJECT_DATAMODE",
      color_tag = "GEOMETRY",
      base_color=_COLOR.colorCat["GetBlenderProp/BaseProp"],
      )
def objectInput(obj: bpy.types.Object) -> bpy.types.Object:
    return obj


@meta(enable=True,
      bl_label="图像输入",
      base_color=_COLOR.colorCat["GetBlenderProp/BaseProp"],
      )
def imageInput(img: bpy.types.Image) -> bpy.types.Image:
    return img


@meta(enable=True,
      bl_label="颜色输入",
      base_color=_COLOR.colorCat["GetBlenderProp/BaseProp"],
      )
def colorInput(color: mathutils.Color) -> mathutils.Color:
    return color


@meta(enable=True,
      bl_label="设置纯色图像",
      base_color=_COLOR.colorCat["SetBlenderProp"],
      is_output_node=True,
      img={"name": "图像输入"},
      )
def imgSetPureColor(img: bpy.types.Image, color: mathutils.Color) -> bpy.types.Image:
    length = len(img.pixels)//4
    col = list(color)*length
    img.pixels = col
    return img


@meta(enable=True,
      bl_label="矢量输入",
      base_color=_COLOR.colorCat["GetBlenderProp/BaseProp"],
      )
def vectorInput(vec: NodeSocketVector) -> NodeSocketVector:
    return vec
