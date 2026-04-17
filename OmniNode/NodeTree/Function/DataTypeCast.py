from ..OmniNodeSocketMapping import _OmniFolderPath, _OmniImageFormat,_OmniRegex, _OmniGlob
from ..FunctionNodeCore import omni
from bpy.types import NodeSocketVector
import bpy
from typing import Any
import mathutils
from . import _Color


@omni(enable=True,
      bl_label="整数 → 浮点",
      base_color=_Color.colorCat["Convert"],
      )
def int2float(v: int) -> float:
    return float(v)

@omni(enable=True,
      bl_label="浮点 → 整数",
      base_color=_Color.colorCat["Convert"],
      )
def float2int(v: float) -> int:
    return int(v)

@omni(enable=True,
      bl_label="布尔 → 整数",
      base_color=_Color.colorCat["Convert"],
      )
def bool2int(v: bool) -> int:
    return int(v)

@omni(enable=True,
      bl_label="整数 → 布尔",
      base_color=_Color.colorCat["Convert"],
      )
def int2bool(v: int) -> bool:
    return bool(v)


@omni(enable=True,
      bl_label="任意 → 字符串",
      base_color=_Color.colorCat["Convert"],
      )
def any2string(v: Any) -> str:
    return str(v)

@omni(enable=True,
      bl_label="字符串 → 整数",
      base_color=_Color.colorCat["Convert"],
      )
def string2int(v: str) -> int:
    try:
        return int(v)
    except:
        return 0

@omni(enable=True,
      bl_label="字符串 → 浮点",
      base_color=_Color.colorCat["Convert"],
      )
def string2float(v: str) -> float:
    try:
        return float(v)
    except:
        return 0.0
    

@omni(enable=True,
      bl_label="整数 → 向量",
      base_color=_Color.colorCat["Convert"],
      )
def int2vector(v: int) -> mathutils.Vector:
    return mathutils.Vector((v, v, v))

@omni(enable=True,
      bl_label="浮点 → 向量",
      base_color=_Color.colorCat["Convert"],
      )
def float2vector(v: float) -> mathutils.Vector:
    return mathutils.Vector((v, v, v))

@omni(enable=True,
      bl_label="向量 → 浮点(长度)",
      base_color=_Color.colorCat["Convert"],
      )
def vector2float(vec: mathutils.Vector) -> float:
    return vec.length

@omni(enable=True,
      bl_label="向量 → 整数(长度)",
      base_color=_Color.colorCat["Convert"],
      )
def vector2int(vec: mathutils.Vector) -> int:
    return int(vec.length)

@omni(enable=True,
      bl_label="向量 → 颜色",
      base_color=_Color.colorCat["Convert"],
      )
def vector2color(vec: mathutils.Vector) -> mathutils.Color:
    return mathutils.Color((vec[0], vec[1], vec[2]))

@omni(enable=True,
      bl_label="颜色 → 向量",
      base_color=_Color.colorCat["Convert"],
      )
def color2vector(col: mathutils.Color) -> mathutils.Vector:
    return mathutils.Vector((col[0], col[1], col[2]))

@omni(enable=True,
      bl_label="浮点 → 颜色(灰度)",
      base_color=_Color.colorCat["Convert"],
      )
def float2color(v: float) -> mathutils.Color:
    return mathutils.Color((v, v, v))


@omni(enable=True,
      bl_label="向量 → 位移矩阵",
      base_color=_Color.colorCat["Convert"],
      )
def vector2matrix(vec: mathutils.Vector) -> mathutils.Matrix:
    return mathutils.Matrix.Translation(vec)

@omni(enable=True,
      bl_label="矩阵 → 位移向量",
      base_color=_Color.colorCat["Convert"],
      )
def matrix2vector(m: mathutils.Matrix) -> mathutils.Vector:
    return m.to_translation()