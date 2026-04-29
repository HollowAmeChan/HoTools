from ..OmniNodeSocketMapping import _OmniFolderPath, _OmniImageFormat,_OmniRegex, _OmniGlob,_OmniColorRGBA
from ..FunctionNodeCore import omni
from . import _Color

from bpy.types import NodeSocketVector, NodeSocketColor
import bpy
import bmesh
import typing
from types import SimpleNamespace
from typing import Any
import time
import mathutils
from mathutils import Vector
import numpy as np
import re

import os
import sys
if sys.version_info >= (3, 13):
    from ...._Lib.py313.PIL import Image, ImageDraw
elif sys.version_info >= (3, 11):
    from ...._Lib.py311.PIL import Image, ImageDraw

@omni(enable=True,
      bl_label="设置物体位置",
      base_color=_Color.colorCat["Operator"],
      is_output_node=False,
      color_tag = "GEOMETRY",
      bl_icon = "OBJECT_DATAMODE",
      )
def objectSetPosition(obj: bpy.types.Object, pos: NodeSocketVector) -> bpy.types.Object:
    obj.location = pos
    return obj


@omni(enable=True,
    bl_label="创建UV层",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体","UV层"],
    _OUTPUT_NAME=["物体","UV层"],
    omni_description="""
    在输入的Mesh上创建一个UV层，返回Mesh和UV层名称
    如果已经存在同名UV层，则不创建，直接返回已有的层
    """,
    )
def meshCreateUVLayer(obj: bpy.types.Object, uv_layer_name: str) -> tuple[bpy.types.Object,str]:
    mesh = obj.data
    if uv_layer_name in mesh.uv_layers:
        return obj, uv_layer_name
    mesh.uv_layers.new(name=uv_layer_name)
    return obj, uv_layer_name

@omni(
    enable=True,
    bl_label="加合",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["整数列表"],
    _OUTPUT_NAME=["和"],
    )
def sumInt(ints: list[int])->int:
    return sum(ints)

@omni(enable=True,
    bl_label="获取集合中的物体",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["集合"],
    _OUTPUT_NAME=["物体列表"],
    )
def getObjectsInCollection(col: bpy.types.Collection) -> list[bpy.types.Object]:
    return [o for o in col.objects]


@omni(
    enable=True,
    bl_label="文件路径识别(正则)",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["文件夹路径", "正则表达式"],
    _OUTPUT_NAME=["文件路径列表"],
    omni_description="""
    该节点用于扫描指定文件夹下所有符合正则表达式的文件路径，返回一个列表
    """
)
def scanFilePath(
    folderPath: _OmniFolderPath,
    pattern: _OmniRegex,
) -> list[_OmniFolderPath]:

    # 路径解析
    folderPath = bpy.path.abspath(folderPath)

    if not folderPath:
        raise ValueError("[scanFilePath] folderPath is empty")

    if not os.path.isdir(folderPath):
        raise FileNotFoundError(f"[scanFilePath] folder not found: {folderPath}")
    # 正则编译
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        raise ValueError(f"[scanFilePath] Invalid regex: {pattern} -> {e}")


    result = []
    for root, dirs, files in os.walk(folderPath):
        for f in files:
            if regex.search(f):
                result.append(os.path.join(root, f))
    # 稳定顺序
    result.sort()

    return result


@omni(enable=True,
    bl_label="字符串连接",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["字符串1","字符串2"],
    _OUTPUT_NAME=["字符串"],
    )
def combineStrs(str1: str, str2: str) -> str:
    return str1 + str2


