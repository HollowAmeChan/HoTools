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

## 3. 物理世界是扩展，源码在独立仓库

物理世界的源码由独立仓库 **HoTools-Omninode-Physics** 管理，本机以嵌套仓库形式
安装到扩展安装位：

```
OmniNode/extensions/Hotools-Omninode-Physics/     ← 独立仓库（含 .git）
    extension.json
    PhysicsWorld/                                 ← 扩展包
```

- 主仓 `.gitignore` 忽略 `OmniNode/extensions/`，绝不跟踪扩展文件；
- 扩展包有 700+ 处父级相对导入（`from ..names import ...`），所以注册时由
  `OmniNodeRegister._register_canonical_extension_package()` 把包目录登记成规范
  包名 `HoTools.OmniNode.PhysicsWorld`——**安装位置随便变，包内代码一行都不用改**；
- 物理的原生模块（`hotools_physics` / `hotools_jolt`）由该仓库自持，产物在其
  `native/runtime/<abi>/` 下，运行时由 `PhysicsWorld/native_runtime.py` 解析。

## 扩展契约

扩展通过清单声明身份与版本要求：

```json
{
  "identifier": "PhysicsWorld",
  "display_name": "物理世界",
  "version": "0.1.0",
  "package": "PhysicsWorld",
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

## 启用/禁用的实现约束（踩过的坑，勿回退）

运行期切换扩展走 `OmniNodeRegister.apply_extension_switch()`，它**只重建 Add 菜单
分类与扩展钩子，永不反注册已经注册过的节点类**。原因：

1. 一旦从 Blender 类型表里撤掉某个 `Node` 类型，**已有工程里该类型的活实例就悬空**，
   之后任何访问——绘制、求值，甚至只是读 `tree.nodes`——都是
   `EXCEPTION_ACCESS_VIOLATION` 硬崩溃（实测必崩，与是否在 UI 回调里无关）。
2. 权重也太大：每次重建都要重新 import 并注册整个物理包（数百个类、含 socket 与
   RNA），只是切个复选框不值得。
3. 重复 `bl_idname` 的类会被 Blender 自动"反注册旧的"（控制台打印
   `has been registered before, unregistering previous`），旧类对象随即失效，
   因此 `_register_node_classes()` **按 bl_idname 去重**，`_rollback_registration()`
   对失效类只跳过不中断。

禁用的语义因此是：扩展分类从 Add 菜单消失、扩展 Blender 钩子不加载；**但工程里
已经存在的该扩展节点仍然可用**（否则打开旧文件就会崩）。真正撤销类型注册只发生在
插件整体卸载（`OmniNode.unregister()`）时。

开关的偏好写入本身也不当场重建：`StringProperty.update` 里做注册表重建会在 UI 绘制
过程中触发反注册，所以 `__init__.py` 把重建推迟到 `bpy.app.timers`（同一事件内的
多次切换按最后一次为准）。
