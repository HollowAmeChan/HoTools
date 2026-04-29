from ..OmniNodeSocketMapping import _OmniFolderPath, _OmniImageFormat,_OmniRegex, _OmniGlob
from ..FunctionNodeCore import omni
from bpy.types import NodeSocketColor
import math
import mathutils
from . import _Color


@omni(enable=True,
    bl_label="Lerp",
    base_color=_Color.colorCat["Math"],)
def lerp(a: NodeSocketColor, b: NodeSocketColor, weight: float) -> NodeSocketColor:
    return a*(1-weight)+b*weight


@omni(enable=True,
    bl_label="SmoothStep",
    base_color=_Color.colorCat["Math"],)
def smoothStep(x: float) -> float:
    out = x*x*(3 - 2*x)
    if out >= 1:
        out = 1
    elif out <= 0:
        out = 0
    return out

@omni(enable=True,
    bl_label="Float加法",
    base_color=_Color.colorCat["Math"],
    color_tag = "CONVERTER",
    )
def floatAdd(a: float, b: float) -> float:
    return a+b


@omni(enable=True,
    bl_label="Float减法",
    base_color=_Color.colorCat["Math"],
    )
def floatSubtract(a: float, b: float) -> float:
    return a - b


@omni(enable=True,
    bl_label="Float乘法",
    base_color=_Color.colorCat["Math"],
    )
def floatMultiply(a: float, b: float) -> float:
    return a * b


@omni(enable=True,
    bl_label="Float除法",
    base_color=_Color.colorCat["Math"],
    )
def floatDivide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("除数不能为0")
    return a / b


@omni(enable=True,
    bl_label="Clamp",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["值", "最小值", "最大值"],
    _OUTPUT_NAME=["结果"],
    )
def clamp(x: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    if min_value > max_value:
        min_value, max_value = max_value, min_value
    return max(min_value, min(x, max_value))


@omni(enable=True,
    bl_label="Remap",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["值", "输入最小", "输入最大", "输出最小", "输出最大", "钳制结果"],
    _OUTPUT_NAME=["结果"],
    )
def remap(
    x: float,
    in_min: float,
    in_max: float,
    out_min: float,
    out_max: float,
    clamp_result: bool = False,
) -> float:
    if in_min == in_max:
        raise ValueError("输入范围不能为0")

    t = (x - in_min) / (in_max - in_min)
    result = out_min + (out_max - out_min) * t

    if clamp_result:
        low = min(out_min, out_max)
        high = max(out_min, out_max)
        result = max(low, min(result, high))
    return result


@omni(enable=True,
    bl_label="Float绝对值",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["值"],
    _OUTPUT_NAME=["结果"],
    )
def floatAbs(x: float) -> float:
    return abs(x)


@omni(enable=True,
    bl_label="Float最小值",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["值A", "值B"],
    _OUTPUT_NAME=["结果"],
    )
def floatMin(a: float, b: float) -> float:
    return min(a, b)


@omni(enable=True,
    bl_label="Float最大值",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["值A", "值B"],
    _OUTPUT_NAME=["结果"],
    )
def floatMax(a: float, b: float) -> float:
    return max(a, b)


@omni(enable=True,
    bl_label="Float幂",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["底数", "指数"],
    _OUTPUT_NAME=["结果"],
    )
def floatPower(base: float, exponent: float) -> float:
    return base ** exponent


@omni(enable=True,
    bl_label="Float开方",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["值"],
    _OUTPUT_NAME=["结果"],
    )
def floatSqrt(x: float) -> float:
    if x < 0:
        raise ValueError("开方输入不能小于0")
    return math.sqrt(x)


@omni(enable=True,
    bl_label="Float取整",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["值", "小数位"],
    _OUTPUT_NAME=["结果"],
    )
def floatRound(x: float, digits: int = 0) -> float:
    return round(x, digits)


@omni(enable=True,
    bl_label="Float向下取整",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["值"],
    _OUTPUT_NAME=["结果"],
    )
def floatFloor(x: float) -> int:
    return math.floor(x)


@omni(enable=True,
    bl_label="Float向上取整",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["值"],
    _OUTPUT_NAME=["结果"],
    )
def floatCeil(x: float) -> int:
    return math.ceil(x)


@omni(enable=True,
    bl_label="Sin",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["弧度"],
    _OUTPUT_NAME=["结果"],
    )
def sinValue(x: float) -> float:
    return math.sin(x)


@omni(enable=True,
    bl_label="Cos",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["弧度"],
    _OUTPUT_NAME=["结果"],
    )
def cosValue(x: float) -> float:
    return math.cos(x)


@omni(enable=True,
    bl_label="向量加法",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["向量A", "向量B"],
    _OUTPUT_NAME=["结果"],
    )
def vectorAdd(a: mathutils.Vector, b: mathutils.Vector) -> mathutils.Vector:
    return a + b


@omni(enable=True,
    bl_label="向量减法",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["向量A", "向量B"],
    _OUTPUT_NAME=["结果"],
    )
def vectorSubtract(a: mathutils.Vector, b: mathutils.Vector) -> mathutils.Vector:
    return a - b


@omni(enable=True,
    bl_label="向量缩放",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["向量", "缩放"],
    _OUTPUT_NAME=["结果"],
    )
def vectorScale(vec: mathutils.Vector, scale: float) -> mathutils.Vector:
    return vec * scale


@omni(enable=True,
    bl_label="向量点乘",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["向量A", "向量B"],
    _OUTPUT_NAME=["结果"],
    )
def vectorDot(a: mathutils.Vector, b: mathutils.Vector) -> float:
    return a.dot(b)


@omni(enable=True,
    bl_label="向量叉乘",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["向量A", "向量B"],
    _OUTPUT_NAME=["结果"],
    )
def vectorCross(a: mathutils.Vector, b: mathutils.Vector) -> mathutils.Vector:
    return a.to_3d().cross(b.to_3d())


@omni(enable=True,
    bl_label="向量长度",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["向量"],
    _OUTPUT_NAME=["长度"],
    )
def vectorLength(vec: mathutils.Vector) -> float:
    return vec.length


@omni(enable=True,
    bl_label="向量归一化",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["向量"],
    _OUTPUT_NAME=["结果"],
    )
def vectorNormalize(vec: mathutils.Vector) -> mathutils.Vector:
    if vec.length == 0:
        return mathutils.Vector((0.0, 0.0, 0.0))
    return vec.normalized()


@omni(enable=True,
    bl_label="拆分向量",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["向量"],
    _OUTPUT_NAME=["X", "Y", "Z"],
    )
def separateVector(vec: mathutils.Vector) -> tuple[float, float, float]:
    vec3 = vec.to_3d()
    return vec3.x, vec3.y, vec3.z


@omni(enable=True,
    bl_label="拆分颜色",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["颜色"],
    _OUTPUT_NAME=["R", "G", "B"],
    )
def separateColor(color: mathutils.Color) -> tuple[float, float, float]:
    return color[0], color[1], color[2]


@omni(enable=True,
    bl_label="Float求和",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["浮点列表"],
    _OUTPUT_NAME=["结果"],
    )
def sumFloat(values: list[float]) -> float:
    return sum(values)


@omni(enable=True,
    bl_label="Float平均值",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["浮点列表"],
    _OUTPUT_NAME=["结果"],
    )
def averageFloat(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


@omni(enable=True,
    bl_label="向量求和",
    base_color=_Color.colorCat["Math"],
    _INPUT_NAME=["向量列表"],
    _OUTPUT_NAME=["结果"],
    )
def sumVector(values: list[mathutils.Vector]) -> mathutils.Vector:
    result = mathutils.Vector((0.0, 0.0, 0.0))
    for value in values:
        result += value.to_3d()
    return result

@omni(
    enable=True,
    bl_label="整数加合",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["整数列表"],
    _OUTPUT_NAME=["和"],
    )
def sumInt(ints: list[int])->int:
    return sum(ints)