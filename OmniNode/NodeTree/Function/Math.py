from ..FunctionCore import meta
from bpy.types import NodeSocketColor
from . import _COLOR


@meta(enable=True,
      base_color=_COLOR.colorCat["BaseMathFunction"],)
def lerp(a: NodeSocketColor, b: NodeSocketColor, weight: float) -> NodeSocketColor:
    return a*(1-weight)+b*weight


@meta(enable=True,
      base_color=_COLOR.colorCat["BaseMathFunction"],)
def smoothStep(x: float) -> float:
    out = x*x*(3 - 2*x)
    if out >= 1:
        out = 1
    elif out <= 0:
        out = 0
    return out
