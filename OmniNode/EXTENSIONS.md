# OmniNode 目录结构：内置模块 vs 扩展

本目录是 OmniNode 图编辑器的包根。**两类内容的归属与生命周期完全不同**，改东西
或提交代码前请先看清自己在动哪一类。

## 1. 插件自带的内置模块 —— 随主仓跟踪

直接位于本目录下，是 HoTools 插件本体的一部分：

| 目录 | 说明 |
| --- | --- |
| `Function/`、`Custom/` | 函数节点模块声明（`OMNI_NODE_REGISTRATION`） |
| `config/` | 节点配色等静态配置 |
| `tests/` | OmniNode 核心回归测试 |
| `PhysicsWorld/` | 物理世界扩展（**独立仓库**：见下） |
| `OmniNode*.py`、`GraphNode.py`、`FunctionNodeCore.py` 等 | 图编辑器内核 |

这类目录由主仓跟踪，**不可卸载**（偏好面板里不提供卸载按钮），也**不进扩展发布包**。

## 2. 用户安装的扩展 —— 绝不进主仓

| 位置 | 路径 | 说明 |
| --- | --- | --- |
| 插件内安装位 | `OmniNode/extensions/<目录>/` | 偏好面板「安装扩展…」的默认落点 |
| 用户目录安装位 | `<Blender 用户目录>/extensions/HoTools-Omninode/<目录>/` | 插件目录只读时的回退落点 |

`OmniNode/extensions/` 已被 `.gitignore` 与 `.releaseignore` 双重排除：
**用户安装的扩展不会进主仓，也不会进父仓发布包**。发布包只含第 1 类内置模块。

安装/卸载入口在 Blender 偏好设置 → HoTools → OmniNode 区块：

- 「安装扩展…」接受扩展 ZIP 或包含扩展的目录；
- 每行的 `X` 按钮卸载该扩展（目录移入 `.trash/`，被占用的 pyd 重启后清理）；
- 「回收站」按钮清理上次卸载残留。

## 3. 物理世界是内置扩展，但代码在独立仓库

`OmniNode/PhysicsWorld/` 是**内置模块**（随插件加载、不可卸载），但它的源码由独立
仓库 **HoTools-Omninode-Physics** 管理，本机以嵌套仓库形式放在同一路径下，因此：

- 主仓 `.gitignore` 忽略 `OmniNode/PhysicsWorld/`，不再跟踪其文件；
- 物理包有 283 处父级相对导入（`from ..names import ...`），所以仓库必须保持这个
  嵌套位置，不能搬到文件系统根部；
- 物理的原生模块（`hotools_physics` / `hotools_jolt`）由该仓库自持，产物在其
  `native/runtime/<abi>/` 下，运行时由 `PhysicsWorld/native_runtime.py` 解析。

## 扩展契约

扩展通过清单声明身份与版本要求：

```json
{
  "identifier": "PhysicsWorld",
  "display_name": "物理世界",
  "version": "0.1.0",
  "package": ".",
  "omninode_api": ">=1.0,<2",
  "requires_hotools": ""
}
```

- `identifier` 是稳定身份（禁用列表按它记忆），**不是**目录名；
- `package` 是注册模块所在的包相对路径，省略或取目录同名时用 `.`；
- `omninode_api` 与 `requires_hotools` 在**导入任何扩展代码之前**校验，不兼容时
  只禁用该扩展并给出可读原因，不会中断整棵节点树注册；
- 注册模块必须提供 `build_omninode_registration()`，可选提供
  `register_blender()` / `unregister_blender()` 生命周期钩子。

契约常量：`OmniNodeRegister.OMNINODE_EXTENSION_API_VERSION`。
