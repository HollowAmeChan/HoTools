from ..FunctionCore import meta
from bpy.types import NodeSocketColor
from . import _COLOR


@meta(enable=True,
      base_color=_COLOR.colorCat["Math"],)
def lerp(a: NodeSocketColor, b: NodeSocketColor, weight: float) -> NodeSocketColor:
    return a*(1-weight)+b*weight


@meta(enable=True,
      base_color=_COLOR.colorCat["Math"],)
def smoothStep(x: float) -> float:
    out = x*x*(3 - 2*x)
    if out >= 1:
        out = 1
    elif out <= 0:
        out = 0
    return out

@meta(enable=True,
      bl_label="Float加法",
      base_color=_COLOR.colorCat["Math"],
      color_tag = "CONVERTER",
      )
def floatAdd(a: float, b: float) -> float:
    return a+b