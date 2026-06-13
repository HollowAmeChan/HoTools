from typing import Any

from ..FunctionNodeCore import omni


@omni(
    enable=True,
    bl_label="Debug打印",
    bl_icon="CONSOLE",
    base_color=(0.12, 0.12, 0.12),
    _INPUT_NAME=["value"],
    _OUTPUT_NAME=["value"],
)
def debug_print_any(value: Any) -> Any:
    print(f"[OmniNode Debug] {type(value).__name__}: {value!r}")
    return value
