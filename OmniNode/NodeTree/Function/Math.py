from ..FunctionNodeCore import omni
from bpy.types import NodeSocketColor
from . import _Color2


@omni(enable=True,
      base_color=_Color2.colorCat["Math"],)
def lerp(a: NodeSocketColor, b: NodeSocketColor, weight: float) -> NodeSocketColor:
    return a*(1-weight)+b*weight


@omni(enable=True,
      base_color=_Color2.colorCat["Math"],)
def smoothStep(x: float) -> float:
    out = x*x*(3 - 2*x)
    if out >= 1:
        out = 1
    elif out <= 0:
        out = 0
    return out

@omni(enable=True,
      bl_label="Float加法",
      base_color=_Color2.colorCat["Math"],
      color_tag = "CONVERTER",
      )
def floatAdd(a: float, b: float) -> float:
    return a+b