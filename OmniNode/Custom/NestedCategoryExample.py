OMNI_NODE_REGISTRATION = {
    "category": {"id": "CUSTOM", "label": "自定义", "order": 1000},
    "menu_path": ("示例", "嵌套分类", "数值工具"),
    "order": 10,
}

from ..FunctionNodeCore import omni


@omni(
    enable=True,
    bl_label="嵌套分类示例-数值偏移",
    base_color=(0.18, 0.30, 0.38),
    omni_description="三层 UI 分类示例：为输入数值增加指定偏移。",
    _INPUT_NAME=["数值", "偏移"],
    _OUTPUT_NAME=["结果"],
    mute_passthrough={"_OUTPUT0": "value"},
)
def customNestedCategoryOffset(
    value: float = 0.0,
    offset: float = 1.0,
) -> float:
    return value + offset
