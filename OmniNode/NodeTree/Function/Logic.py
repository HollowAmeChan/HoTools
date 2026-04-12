from ..FunctionNodeCore import omni , _OmniFolderPath, _OmniImageFormat,_OmniRegex, _OmniGlob
from bpy.types import NodeSocketVector
import bpy
from typing import Any
import mathutils
from . import _Color


@omni(enable=True,
    bl_label="且",
    base_color=_Color.colorCat["Logic"],
    _INPUT_NAME=["条件A","条件B"],
    _OUTPUT_NAME=["结果"],
)
def logic_and(a: bool, b: bool) -> bool:
    return a and b


@omni(enable=True,
    bl_label="或",
    base_color=_Color.colorCat["Logic"],
    _INPUT_NAME=["条件A","条件B"],
    _OUTPUT_NAME=["结果"],
)
def logic_or(a: bool, b: bool) -> bool:
    return a or b


@omni(enable=True,
    bl_label="非",
    base_color=_Color.colorCat["Logic"],
    _INPUT_NAME=["条件"],
    _OUTPUT_NAME=["结果"],
)
def logic_not(a: bool) -> bool:
    return not a




@omni(enable=True,
    bl_label="等于",
    base_color=_Color.colorCat["Logic"],
    is_output_node=False,
    _INPUT_NAME=["值A","值B"],
    _OUTPUT_NAME=["结果"],
    )
def equal(a: Any, b: Any) -> bool:
    return a == b

@omni(enable=True,
    bl_label="不等于",
    base_color=_Color.colorCat["Logic"],
    _INPUT_NAME=["值A","值B"],
    _OUTPUT_NAME=["结果"],
)
def not_equal(a: Any, b: Any) -> bool:
    return a != b

@omni(enable=True,
    bl_label="大于等于",
    base_color=_Color.colorCat["Logic"],
    _INPUT_NAME=["值A","值B"],
    _OUTPUT_NAME=["结果"],
)
def bigger_equal(a: Any, b: Any) -> bool:
    return a >= b

@omni(enable=True,
    bl_label="小于等于",
    base_color=_Color.colorCat["Logic"],
    _INPUT_NAME=["值A","值B"],
    _OUTPUT_NAME=["结果"],
)
def smaller_equal(a: Any, b: Any) -> bool:
    return a <= b

@omni(enable=True,
    bl_label="大于",
    base_color=_Color.colorCat["Logic"],
    is_output_node=False,
    _INPUT_NAME=["值A","值B"],
    _OUTPUT_NAME=["结果"],
    )
def bigger(a: Any, b: Any) -> bool:
    return a > b

@omni(enable=True,
    bl_label="小于",
    base_color=_Color.colorCat["Logic"],
    is_output_node=False,
    _INPUT_NAME=["值A","值B"],
    _OUTPUT_NAME=["结果"],
    )
def smaller(a: Any, b: Any) -> bool:
    return a < b




@omni(enable=True,
    bl_label="在列表中",
    base_color=_Color.colorCat["Logic"],
    is_output_node=False,
    _INPUT_NAME=["项目","列表"],
    _OUTPUT_NAME=["结果"],
    )
def inList(item: Any, lst: list[Any]) -> bool:
    return item in lst

@omni(enable=True,
    bl_label="列表是否为空",
    base_color=_Color.colorCat["Logic"],
    _INPUT_NAME=["列表"],
    _OUTPUT_NAME=["结果"],
)
def list_is_empty(lst: list[Any]) -> bool:
    return len(lst) == 0


@omni(enable=True,
    bl_label="列表长度",
    base_color=_Color.colorCat["Logic"],
    _INPUT_NAME=["列表"],
    _OUTPUT_NAME=["长度"],
)
def list_length(lst: list[Any]) -> int:
    return len(lst)




@omni(enable=True,
    bl_label="在范围内",
    base_color=_Color.colorCat["Logic"],
    _INPUT_NAME=["值","最小值","最大值"],
    _OUTPUT_NAME=["结果"],
)
def in_range(x: Any, min_val: Any, max_val: Any) -> bool:
    return min_val <= x <= max_val



@omni(enable=True,
    bl_label="是否为空",
    base_color=_Color.colorCat["Logic"],
    _INPUT_NAME=["值"],
    _OUTPUT_NAME=["结果"],
)
def is_none(x: Any) -> bool:
    return x is None


@omni(enable=True,
    bl_label="是否非空",
    base_color=_Color.colorCat["Logic"],
    _INPUT_NAME=["值"],
    _OUTPUT_NAME=["结果"],
)
def is_not_none(x: Any) -> bool:
    return x is not None



@omni(enable=True,
    bl_label="条件选择",
    base_color=_Color.colorCat["Logic"],
    is_output_node=False,
    _INPUT_NAME=["条件","值1","值2"],
    _OUTPUT_NAME=["结果"],
    )
def switch(condition: bool, value1: Any, value2: Any) -> Any:
    return value1 if condition else value2
