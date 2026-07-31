# OmniNode Custom Functions

这个目录用于放置用户自定义的 Function 节点。新增模块后不需要修改
`OmniNodeRegister.py`；重新启用 OmniNode 或重启 Blender 时会自动递归发现。

## 新建节点

1. 复制 `Example.py`，并改成唯一的 Python 文件名，例如
   `StudioCharacter.py`。文件名和子目录名只能使用合法 Python 标识符。
2. 修改 `OMNI_NODE_REGISTRATION`。同一个 `category.id` 下的 `label` 和
   `category.order` 必须完全一致；`menu_path` 可以声明任意深度的子菜单。
3. 将示例函数替换为自己的函数，并用 `@omni(enable=True, ...)` 暴露节点。
4. 函数名在全部 OmniNode 中必须唯一。它会生成持久化 ID
   `HO_OmniNode_<函数名>`；节点发布后不要改函数名，否则旧 `.blend` 无法找到该节点类型。

最小模板：

```python
OMNI_NODE_REGISTRATION = {
    "category": {"id": "CUSTOM", "label": "Custom", "order": 1000},
    "menu_path": ("Character", "Face"),
    "order": 10,
}

from HoTools.OmniNode.FunctionNodeCore import omni


@omni(
    enable=True,
    bl_label="我的节点",
    _INPUT_NAME=["输入"],
    _OUTPUT_NAME=["输出"],
    mute_passthrough={"_OUTPUT0": "value"},
)
def studioUniqueNodeName(value: float = 0.0) -> float:
    return value
```

只包含 helper、不应生成节点的 `.py` 文件也必须声明：

```python
OMNI_NODE_REGISTRATION = {"enabled": False}
```

声明缺失、模块导入失败、分类合同冲突、没有启用节点或节点 ID 重复时，
OmniNode 会拒绝整批注册并报告具体文件，避免出现只注册了一部分节点的状态。
