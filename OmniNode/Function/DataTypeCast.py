from ..OmniNodeSocketMapping import _OmniFolderPath, _OmniImageFormat,_OmniRegex, _OmniGlob, _OmniColorRGBA
from ..FunctionNodeCore import omni
from bpy.types import NodeSocketVector
import bpy
from typing import Any
import mathutils
import fnmatch
from . import _Color
import re


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
def int2vector(x: int, y: int, z: int) -> mathutils.Vector:
    return mathutils.Vector((x, y, z))

@omni(enable=True,
      bl_label="浮点 → 向量",
      base_color=_Color.colorCat["Convert"],
      )
def float2vector(x: float, y: float, z: float) -> mathutils.Vector:
    return mathutils.Vector((x, y, z))

@omni(enable=True,
      bl_label="向量 → 颜色",
      base_color=_Color.colorCat["Convert"],
      )
def vector2color(vec: mathutils.Vector) -> _OmniColorRGBA:
    return mathutils.Color((vec[0], vec[1], vec[2]))

@omni(enable=True,
      bl_label="颜色 → 向量",
      base_color=_Color.colorCat["Convert"],
      )
def color2vector(col: mathutils.Color) -> mathutils.Vector:
    return mathutils.Vector((col[0], col[1], col[2]))

@omni(enable=True,
      bl_label="浮点 → 颜色",
      base_color=_Color.colorCat["Convert"],
      )
def float2color(v: float) -> _OmniColorRGBA:
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


@omni(enable=True,
    bl_label="glob → 正则",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["glob表达式"],
    _OUTPUT_NAME=["正则表达式"],
    omni_description="""
    该节点用于将glob表达式转换为正则表达式
    规则：
    *  匹配任意字符，但不包含 _
    ** 匹配任意字符，包含 _
    ?  匹配单个字符，但不包含 _
    """
)
def glob2regex(pattern: _OmniGlob) -> _OmniRegex:
    if not pattern:
        raise ValueError("glob表达式不能为空")

    regex = []
    i = 0

    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            # ** 表示允许跨 _
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                regex.append(".*")
                i += 2
            else:
                regex.append("[^_]*")
                i += 1
        elif c == "?":
            regex.append("[^_]")
            i += 1
        else:
            regex.append(re.escape(c))
            i += 1

    return "^" + "".join(regex) + "$"
