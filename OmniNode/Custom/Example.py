OMNI_NODE_REGISTRATION = {
    "category": {"id": "CUSTOM", "label": "Custom", "order": 1000},
    "menu_path": ("Examples", "Math"),
    "order": 0,
}

from ..FunctionNodeCore import omni


@omni(
    enable=True,
    bl_label="Custom示例-数值缩放",
    base_color=(0.16, 0.32, 0.22),
    omni_description="用户自定义 Function 节点示例：将输入数值乘以倍率。",
    _INPUT_NAME=["数值", "倍率"],
    _OUTPUT_NAME=["结果"],
    mute_passthrough={"_OUTPUT0": "value"},
)
def customExampleScale(value: float = 1.0, scale: float = 2.0) -> float:
    return value * scale
