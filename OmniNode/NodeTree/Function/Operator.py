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
      base_color=_COLOR.colorCat["Operator"],
      is_output_node=True,
      color_tag = "GEOMETRY",
      bl_icon = "OBJECT_DATAMODE",
      )
def objectSetPosition(obj: bpy.types.Object, pos: NodeSocketVector) -> bpy.types.Object:
    obj.location = pos
    return obj


@meta(enable=True,
      bl_label="设置图像颜色",
      base_color=_COLOR.colorCat["Operator"],
      is_output_node=True,
      img={"name": "图像输入"},
      )
def imgSetPureColor(img: bpy.types.Image, color: mathutils.Color) -> bpy.types.Image:
    length = len(img.pixels)//4
    col = list(color)*length
    img.pixels = col
    return img

@meta(enable=True,
      bl_label="创建UV层",
      base_color=_COLOR.colorCat["Operator"],
      is_output_node=False,
      omni_description="""
      在输入的Mesh上创建一个UV层，返回Mesh和UV层名称
      如果已经存在同名UV层，则不创建，直接返回已有的层
      """,
      )
def meshCreateUVLayer(obj: bpy.types.Object, uv_layer_name: str) -> tuple[bpy.types.Mesh,str]:
    mesh = obj.data
    if uv_layer_name in mesh.uv_layers:
        return mesh, uv_layer_name
    mesh.uv_layers.new(name=uv_layer_name)
    return mesh, uv_layer_name