from ..OmniNodeSocketMapping import _OmniFolderPath, _OmniImageFormat,_OmniRegex, _OmniGlob,_OmniColorRGBA,_OmniDatablock
from ..FunctionNodeCore import omni
from . import _Color

from bpy.types import NodeSocketVector, NodeSocketColor
import ast
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


def _write_datablock_property(datablock, property_name: str, value: Any):
    property_name = str(property_name or "").strip()
    if datablock is None or not property_name:
        return

    owner, last_segment = _resolve_datablock_property_owner(datablock, property_name)
    if owner is None or last_segment is None:
        return

    access_type, access_name = last_segment
    try:
        if access_type == "key":
            owner[access_name] = value
        else:
            setattr(owner, access_name, value)
    except Exception:
        pass


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
      bl_label="设置Datablock数据",
      base_color=_Color.colorCat["Operator"],
      is_output_node=False,
      _INPUT_NAME=["数据块","属性名称","属性值"],
      )
def setDatablockProperty(datablock: _OmniDatablock, prop_name: str, value: Any) -> Any:
    _write_datablock_property(datablock, prop_name, value)
    return value


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


