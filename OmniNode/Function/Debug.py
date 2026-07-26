from typing import Any

from ..FunctionNodeCore import omni


@omni(
    enable=True,
    always_run=True,   # print 副作用
    bl_label="Debug打印",
    bl_icon="CONSOLE",
    base_color=(0.12, 0.12, 0.12),
    omni_description="打印输入值并原样输出。标题输入用于区分多个 Debug 节点；标题为空时使用默认前缀。",
    _INPUT_NAME=["值", "标题"],
    _OUTPUT_NAME=["value"],
    mute_passthrough={"_OUTPUT0": "value"},
)
def debug_print_any(value: Any, title: str = "") -> Any:
    title_text = str(title).strip() if title is not None else ""
    prefix = f"[OmniNode Debug][{title_text}]" if title_text else "[OmniNode Debug]"
    print(f"{prefix} {type(value).__name__}: {value!r}")
    return value
