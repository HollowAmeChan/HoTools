from ..OmniNodeSocketMapping import _OmniFolderPath, _OmniImageFormat,_OmniRegex, _OmniGlob,_OmniColorRGBA,_OmniDatablock, _OmniFloatCurve, _OmniColorCurve
from ....PropertyCurve import sample_color_curve, sample_float_curve
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
if sys.version_info[:2] == (3, 13):
    from ...._Lib.py313.PIL import Image, ImageDraw
elif sys.version_info[:2] == (3, 11):
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


def _require_object(obj, label: str) -> bpy.types.Object:
    if obj is None or not isinstance(obj, bpy.types.Object):
        raise ValueError(f"{label} is empty")
    return obj


def _to_vector3(value) -> mathutils.Vector:
    try:
        vec = mathutils.Vector(value)
    except Exception:
        return mathutils.Vector((0.0, 0.0, 0.0))

    if len(vec) == 0:
        return mathutils.Vector((0.0, 0.0, 0.0))
    if len(vec) == 1:
        return mathutils.Vector((vec[0], 0.0, 0.0))
    if len(vec) == 2:
        return mathutils.Vector((vec[0], vec[1], 0.0))
    return vec.to_3d()


def _to_vector3_default(value, fallback: mathutils.Vector) -> mathutils.Vector:
    try:
        vec = mathutils.Vector(value)
    except Exception:
        return fallback.copy()

    if len(vec) == 0:
        return fallback.copy()
    if len(vec) == 1:
        return mathutils.Vector((vec[0], fallback[1], fallback[2]))
    if len(vec) == 2:
        return mathutils.Vector((vec[0], vec[1], fallback[2]))
    return vec.to_3d()


def _component_multiply(a: mathutils.Vector, b: mathutils.Vector) -> mathutils.Vector:
    return mathutils.Vector((a.x * b.x, a.y * b.y, a.z * b.z))


def _rotation_quaternion(value) -> mathutils.Quaternion:
    return mathutils.Euler(_to_vector3(value), "XYZ").to_quaternion()


def _quaternion_to_euler_vector(quat: mathutils.Quaternion) -> mathutils.Vector:
    euler = quat.to_euler("XYZ")
    return mathutils.Vector((euler.x, euler.y, euler.z))


def _euler_order(obj: bpy.types.Object) -> str:
    mode = getattr(obj, "rotation_mode", "XYZ")
    if mode in {"QUATERNION", "AXIS_ANGLE"}:
        obj.rotation_mode = "XYZ"
        return "XYZ"
    return mode


@omni(enable=True,
      always_run=True,   # 写入 bpy 变换，有副作用
      bl_label="写入物体变换",
      base_color=_Color.colorCat["Operator"],
      is_output_node=False,
      color_tag="GEOMETRY",
      bl_icon="OBJECT_DATAMODE",
      _INPUT_NAME=["物体", "移动", "旋转", "缩放"],
      _OUTPUT_NAME=["物体"],
      omni_description="""
      将移动、旋转、缩放写入物体的普通 Transform。
      移动写入 object.location，旋转写入 object.rotation_euler，缩放写入 object.scale。
      旋转单位为弧度；如果物体当前使用四元数或轴角旋转，会切换到 XYZ 欧拉旋转。
      """,
      mute_passthrough={"_OUTPUT0": "obj"},
      )
def objectWriteFullTransform(
    obj: bpy.types.Object,
    location: NodeSocketVector,
    rotation: NodeSocketVector,
    scale: NodeSocketVector = mathutils.Vector((1.0, 1.0, 1.0)),
) -> bpy.types.Object:
    obj = _require_object(obj, "obj")
    obj.location = _to_vector3(location)
    obj.rotation_euler = mathutils.Euler(_to_vector3(rotation), _euler_order(obj))
    obj.scale = _to_vector3_default(scale, mathutils.Vector((1.0, 1.0, 1.0)))
    return obj


@omni(enable=True,
      bl_label="采样浮点曲线",
      base_color=_Color.colorCat["Operator"],
      is_output_node=False,
      color_tag="CONVERTER",
      bl_icon="IPO_BEZIER",
      _INPUT_NAME=["采样位置", "浮点曲线"],
      _OUTPUT_NAME=["数值"],
      omni_description="""
      在浮点曲线上按位置采样并输出数值。
      越界方式使用曲线自身设置。
      """,
      )
def sampleFloatCurve(
    sample_position: float,
    curve: _OmniFloatCurve,
) -> float:
    return float(sample_float_curve(curve, sample_position))


@omni(enable=True,
      bl_label="采样颜色曲线",
      base_color=_Color.colorCat["Operator"],
      is_output_node=False,
      color_tag="CONVERTER",
      bl_icon="IPO_BEZIER",
      _INPUT_NAME=["采样位置", "颜色曲线"],
      _OUTPUT_NAME=["颜色", "向量", "R", "G", "B", "A"],
      omni_description="""
      在颜色曲线上按位置采样，输出颜色、RGB 向量和 RGBA 拆分值。
      越界方式使用曲线自身设置。
      """,
      )
def sampleColorCurve(
    sample_position: float,
    curve: _OmniColorCurve,
) -> tuple[_OmniColorRGBA, mathutils.Vector, float, float, float, float]:
    color = sample_color_curve(curve, sample_position)
    rgba = (float(color[0]), float(color[1]), float(color[2]), float(color[3]))
    return (
        rgba,
        mathutils.Vector((rgba[0], rgba[1], rgba[2])),
        rgba[0],
        rgba[1],
        rgba[2],
        rgba[3],
    )


@omni(enable=False,
      bl_label="按曲线设置位置",
      base_color=_Color.colorCat["Operator"],
      is_output_node=False,
      color_tag="GEOMETRY",
      bl_icon="OBJECT_DATAMODE",
      _INPUT_NAME=["物体", "采样位置", "颜色曲线", "越界方式"],
      _OUTPUT_NAME=["物体", "位置"],
      omni_description="""
      在颜色曲线上采样 RGB，并把 RGB 写入 object.location 的 XYZ。
      越界方式为空时使用曲线设置；也可输入 钳制/重复/镜像 或 CLAMP/REPEAT/MIRROR。
      颜色 Alpha 暂不使用。
      """,
      )
def objectSetLocationByColorCurve(
    obj: bpy.types.Object,
    sample_position: float,
    curve: _OmniColorCurve,
    extend_mode: str = "",
) -> tuple[bpy.types.Object, mathutils.Vector]:
    obj = _require_object(obj, "obj")
    color = sample_color_curve(curve, sample_position, extend=extend_mode)
    location = mathutils.Vector((color[0], color[1], color[2]))
    obj.location = location
    return obj, location


@omni(enable=True,
      bl_label="变换合成",
      base_color=_Color.colorCat["Operator"],
      is_output_node=False,
      color_tag="GEOMETRY",
      bl_icon="OBJECT_DATAMODE",
      _INPUT_NAME=[
          "基础位置",
          "基础旋转",
          "基础缩放",
          "附加位置",
          "附加旋转",
          "附加缩放",
          "附加位置使用基础旋转",
          "缩放相乘",
      ],
      _OUTPUT_NAME=["位置", "旋转", "缩放"],
      omni_description="""
      合成两个局部变换，常用于把软跟随输出和漂浮输出合成为同一个控制器的最终变换。

      默认规则：
      位置 = 基础位置 + 附加位置。
      旋转 = 基础旋转 @ 附加旋转。
      缩放 = 基础缩放 * 附加缩放。

      如果启用“附加位置使用基础旋转”，附加位置会先被基础旋转和基础缩放变换，再加到基础位置。
      旋转输入/输出单位都是弧度，可直接接写入物体完整变换节点。
      漂浮节点默认缩放输出为 1,1,1，因此缩放相乘时不会改变基础缩放。
      """,
      mute_passthrough={
          "_OUTPUT0": "base_location",
          "_OUTPUT1": "base_rotation",
          "_OUTPUT2": "base_scale",
      },
      )
def composeTransform(
    base_location: NodeSocketVector,
    base_rotation: NodeSocketVector,
    base_scale: NodeSocketVector = mathutils.Vector((1.0, 1.0, 1.0)),
    overlay_location: NodeSocketVector = mathutils.Vector((0.0, 0.0, 0.0)),
    overlay_rotation: NodeSocketVector = mathutils.Vector((0.0, 0.0, 0.0)),
    overlay_scale: NodeSocketVector = mathutils.Vector((1.0, 1.0, 1.0)),
    overlay_location_in_base_rotation: bool = False,
    multiply_scale: bool = True,
) -> tuple[mathutils.Vector, mathutils.Vector, mathutils.Vector]:
    base_location = _to_vector3(base_location)
    base_rotation_quat = _rotation_quaternion(base_rotation)
    base_scale = _to_vector3_default(base_scale, mathutils.Vector((1.0, 1.0, 1.0)))
    overlay_location = _to_vector3(overlay_location)
    overlay_rotation_quat = _rotation_quaternion(overlay_rotation)
    overlay_scale = _to_vector3_default(overlay_scale, mathutils.Vector((1.0, 1.0, 1.0)))

    if overlay_location_in_base_rotation:
        location_delta = base_rotation_quat @ _component_multiply(base_scale, overlay_location)
    else:
        location_delta = overlay_location

    result_location = base_location + location_delta
    result_rotation = _quaternion_to_euler_vector(base_rotation_quat @ overlay_rotation_quat)
    if multiply_scale:
        result_scale = _component_multiply(base_scale, overlay_scale)
    else:
        result_scale = base_scale + overlay_scale

    return result_location, result_rotation, result_scale


@omni(enable=True,
      always_run=True,   # 写入 bpy delta 变换，有副作用
      bl_label="写入增量变换",
      base_color=_Color.colorCat["Operator"],
      is_output_node=False,
      color_tag="GEOMETRY",
      bl_icon="OBJECT_DATAMODE",
      _INPUT_NAME=["物体", "移动", "旋转"],
      _OUTPUT_NAME=["物体"],
      omni_description="""
      将移动和旋转向量写入物体的 Delta Transform。
      移动写入 object.delta_location，旋转写入 object.delta_rotation_euler，旋转单位为弧度。
      该节点不会修改普通 location/rotation_euler。
      """,
      mute_passthrough={"_OUTPUT0": "obj"},
      )
def objectWriteDeltaTransform(
    obj: bpy.types.Object,
    location: NodeSocketVector,
    rotation: NodeSocketVector,
) -> bpy.types.Object:
    obj = _require_object(obj, "obj")
    obj.delta_location = _to_vector3(location)
    obj.delta_rotation_euler = mathutils.Euler(_to_vector3(rotation), _euler_order(obj))
    return obj


@omni(enable=True,
      always_run=True,   # 写入 bpy 属性，有副作用
      bl_label="设置Datablock数据",
      base_color=_Color.colorCat["Operator"],
      is_output_node=False,
      _INPUT_NAME=["数据块","属性名称","属性值"],
      mute_passthrough={"_OUTPUT0": "value"},
      )
def setDatablockProperty(datablock: _OmniDatablock, prop_name: str, value: Any) -> Any:
    _write_datablock_property(datablock, prop_name, value)
    return value


@omni(enable=True,
    always_run=True,   # 修改 bpy mesh UV层，有副作用
    bl_label="创建UV层",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体","UV层"],
    _OUTPUT_NAME=["物体","UV层"],
    omni_description="""
    在输入的Mesh上创建一个UV层，返回Mesh和UV层名称
    如果已经存在同名UV层，则不创建，直接返回已有的层
    """,
    mute_passthrough={"_OUTPUT0": "obj", "_OUTPUT1": "uv_layer_name"},
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
    mute_passthrough={"_OUTPUT0": "str1"},
    )
def combineStrs(str1: str, str2: str) -> str:
    return str1 + str2
