# OmniNode / PhysicsWorld 拆分与新仓库规划（评估 + 方案，未动工）

> 状态：**Phase A（原生分家）已完成并实测通过**，详细进度见 §14；本文件不描述未落地的改动。
> 所有数字来自本机仓库实测（`git ls-files`、文件扫描），非估算的部分均已标注。
> 决策摘要：D1 各仓自持 pyd（`hotools_physics` 新名）· D2 嵌套目录 + `.gitignore`（非 submodule）· D3 父仓包不含扩展、扩展独立安装 · D4 只拆物理世界 · D5 **原生分家优先（Phase A）**。
> 边界补充（D4 细化）：**PropertyCurve 是父仓贮藏内容，物理世界只是调用方**——`hotools_native`（PropertyCurve 采样内核）永远留在父仓，物理侧只通过 Python 公开 API 使用它，不复制、不扩展。

---

## 0. 结论速览

| 问题 | 结论 |
| --- | --- |
| 值得拆吗？ | **值得，且代价比预想小**。OmniNode 已经把 PhysicsWorld 做成了"扩展"（`OmniNodeExtensionSpec` + `omninode_registration.py` 自动发现），物理世界在目录、注册、原生模块、测试四个层面都已基本自洽。 |
| 能拆干净吗？ | **能**，但必须处理 5 个硬耦合点（见 §3），其中 2 个是"必须改代码"，3 个是"必须切包"。 |
| "本机保持目录结构，内部套一个仓库"可行吗？ | **可行**，且是风险最低的做法（嵌套布局 = 零 symlink、零 CI 特例、单机可直接跑）。但嵌套目录**不能是 git submodule**（否则从压缩包安装的用户 Blender 里会出现 git 元数据 + 更新冲突）。建议：`.gitignore` 嵌套目录，用 `tools/link_extension.ps1` 在两仓之间同步。 |
| "安装/卸载/启用/禁用开关" | **能做，而且比普通插件更容易**：因为扩展是单独一层，启用/禁用走 `OmniNodeRegister` 的扩展白名单即可，不需要重新注册整棵树。 |
| 最大风险 | ①`hotools_native` 是一个 pyd，同时装着 PropertyCurve（父仓必需）和 MC2/XPBD/SpringVRM/Field（物理必需）→ **必须按 TU 切开并重命名**（见 §8，已确认可行）；②`hotools_jolt` 在发布包里是**必需文件**校验项；③5 个父仓测试硬依赖 PhysicsWorld 目录与节点。 |
| 施工顺序 | **原生 pyd 分家优先（Phase A）**，之后才是 Python/文档搬迁；详见 §7 决策 D5 与 §9。 |
| 总工期 | **约 8–11.5 个工作日**（含原生分家、扩展机制、搬家、安装/卸载闭环、双版本实机验证），见 §12。 |

---

## 1. 现状实测

### 1.1 规模

| 范围 | 跟踪文件数 | 备注 |
| --- | --- | --- |
| 仓库总计 | 1682 | `_Lib` 572、`OmniNode` 673 |
| `OmniNode/` 全部 | 673 | Python 411 个文件、约 13.3 万行 |
| `OmniNode/PhysicsWorld/` | 606 | 占 OmniNode 的 90%，其中 `mc2` 223、`rigid` 193、`xpbd` 49、`test` 44 |
| `OmniNode/` 核心（图编辑器本体） | 67 | `OmniNode*.py` 21 + `Function/`+`Custom/` 21 + `config/` 2 + `ARCHITECTURE.md` + 物理文档 13 + 测试 11 |
| `_native/` | 80 | 其中物理相关 C++/测试 **约 60**，非物理（`boolean_outer_hull`、`property_curve`、构建脚本）约 20 |
| `tools/` | 13 | `mc2_unity_oracle/*`（Unity）、`run_mc2_v1_acceptance.ps1`、`audit_mc2_architecture.py`、`build_release_zip.py`（**通用，留父仓**） |

### 1.2 "物理世界"的完整散布清单（也就是"要搬走的东西"）

**A. 物理 Python（全新仓库主体）**
- `OmniNode/PhysicsWorld/**`（606 文件，含 `mc2/ rigid/ rigid_fracture/ xpbd/ spring_vrm/ field/ collision/ bake/ simple_cloth/ ui/ utils/ test/` 与 28 个顶层模块）
- `OmniNode/doc/*` 共 **13 篇全是物理文档**（MC2、JOLT、XPBD、SPRINGBONE、PHYSICS_*、BONE_XPBD）→ 全搬

**B. 物理原生源码**（`_native/` 内）
- `src/jolt_rigid.cpp`、`include/hotools_mesh_xpbd.hpp`、`include/hotools_spring_bone_vrm.hpp`
- `src/mc2_*.{cpp,hpp}`（10 个）、`src/field_runtime*.{cpp,hpp}`、`src/mesh_xpbd*.{cpp,hpp}`、`src/spring_bone_vrm*.{cpp,hpp}`、`src/rigid_writeback*.{cpp,hpp}`
- 对应测试：`_native/tests/*mc2*`、`*jolt*`、`*mesh_xpbd*`、`*spring_bone*`、`*rigid_writeback*`、`benchmark_field_runtime_native.py`
- ⚠️ **共享头文件**：`src/field_runtime.hpp`、`src/python_buffer_utils.hpp` 同时被物理 TU 与父仓 TU 使用 → 需要"共享原生区"或同步校验

**C. 物理构建/发布/CI**
- `_native/CMakeLists.txt` 中 `HOTOOLS_BUILD_JOLT`、`HOTOOLS_BUILD_NATIVE` 内的 MC2/XPBD/Spring/Field/Rigid 源列表
- `tools/build_release_zip.py` L102 把 `hotools_jolt.*.pyd` 列为**必需文件**
- `.github/workflows/release.yml`（需拆成两条发布线）
- `.gitignore` L4 的 `!OmniNode/PhysicsWorld/rigid/test/assets/jolt_fracture_user_project.blend` 例外、L28-34 的 MagicaCloth2 规则（全部属于新仓）

**D. 物理文档 / 研究 / 外部工具**
- `OmniNode/doc/**`（13 篇）、`OmniNode/ARCHITECTURE.md` 中的物理章节
- `tools/mc2_unity_oracle/**`（Unity 工程 + 自有 `.gitignore`）、`tools/run_mc2_v1_acceptance.ps1`、`tools/audit_mc2_architecture.py`

**E. 物理测试（父仓根 `tests/`）**
- 根 `tests/` 43 个文件经扫描 **无物理测试**（全是骨骼/形态键/FBX/UV/Checker 等）→ 好消息，根测试不用搬。
- 但 `OmniNode/tests/` 11 个里有 **7 个硬依赖 PhysicsWorld**（见 §3.3）。

### 1.3 不是物理、不要搬的东西

- `_Lib/py311|py313/HotoolsPackage/hotools_native.*.pyd`：**同时**含 PropertyCurve 符号（父仓 `PropertyCurve/sampling.py` 用 `hotools_native`）与 MC2/XPBD/Spring/Field 符号 → 见 §3.1 决策
- `hotools_boolean.*.pyd` + `_native/src/boolean_outer_hull.cpp`：父仓专用
- `PropertyCurve/`（99 文件）、`HoTab/`、其余全部模块

---

## 2. 目标形态

### 2.1 本机目录（保持现状 + 内嵌一个仓库）

```
.../Blender/4.5/scripts/addons/HoTools/          ← 父仓（HoTools）
├─ __init__.py                                   ← 增加"扩展启用/禁用"逻辑
├─ OmniNode/                                     ← OmniNode 核心（图编辑器）
│  ├─ OmniNodeRegister.py                        ← 改动：扩展发现支持外部路径 + 白名单
│  ├─ Function/ Custom/ config/ OmniNode*.py
│  └─ extensions/
│     └─ Hotools-Omninode-Physics/               ← 新仓库（独立 .git）
│        └─ PhysicsWorld/                        ← 原 606 文件
│           └─ native/                           ← C++ 直接放物理世界目录下（决策 D5）
│              ├─ CMakeLists.txt                 ← 独立工程，产 hotools_physics + hotools_jolt
│              ├─ src/ include/
│              ├─ build.bat  CMakePresets.json   ← 含 layout stamp 重建保护
│              └─ runtime/py311|py313/           ← 扩展自持的 pyd 落点
│        ├─ docs/**  unity/**  tools/**
│        ├─ extension.json                       ← id/版本/兼容范围/原生需求
│        └─ .git/                                ← 只有它有 git 元数据，父仓 .gitignore 掉
├─ _native/                                      ← 只服务父仓：property_curve + boolean（Jolt 与物理 TU 已迁出）
├─ _Lib/  tools/  tests/  PropertyCurve/ ...
```

- 打包时（`build_release_zip.py`）产出**纯 HoTools 包**（D3：不含扩展），扩展走新仓独立发布。
- 开发时用 `tools/link_extension.ps1` 把外部 clone 链接到 `OmniNode/extensions/`（junction），或反过来从嵌套仓 push 到外部仓。

**为什么推荐嵌套而不是 submodule**：ZIP 安装的用户机器上没有 git，submodule 在源码 clone 场景才有意义；而你的分发主线是 ZIP + 内置 `updater.py`。submodule 还会让"扩展独立发版"与父仓 tag 互相牵制。

### 2.2 新仓库 `HoTools-Omninode-Physics`（建议名：`HoTools-Physics`）

```
HoTools-Omninode-Physics/
├─ PhysicsWorld/                     ← 保持现包名与相对导入（见 §3.2）
│  └─ native/                        ← C++：jolt_rigid / mc2_* / field_runtime* / mesh_xpbd* / spring_bone_vrm* / rigid_writeback*
│     ├─ CMakeLists.txt              ← 产 hotools_physics + hotools_jolt（py311/py313 双 ABI）
│     ├─ CMakePresets.json  build.bat
│     ├─ include/  src/  tests/       ← include/hotools_mesh_xpbd.hpp、hotools_spring_bone_vrm.hpp；src/python_buffer_utils.hpp
│     └─ runtime/py311|py313/         ← 扩展自持 pyd 落点
├─ docs/              13 篇蓝图/契约
├─ tests/             从 OmniNode/PhysicsWorld/*/test 与 OmniNode/tests 物理项迁入
├─ tools/             unity_oracle/、run_mc2_v1_acceptance.ps1、audit_mc2_architecture.py
├─ extension.json
└─ .github/workflows/release.yml    扩展独立发布（zip + pyd）
```

---

## 3. 五个硬耦合点与对策（这是整个计划的重点）

### 3.1 `hotools_native` 是一个 pyd，跨了两个仓

现状：`_native/CMakeLists.txt` L251-279 把 `field_runtime`、`mc2_*`、`mesh_xpbd`、`spring_bone_vrm`、`property_curve`、`rigid_writeback` **编成同一个 `hotools_native` 模块**。而 `PropertyCurve/sampling.py`（父仓）用它的 curve sampler，物理侧用它的 MC2/XPBD/Spring/Field。

> **已确认决策（决策 D1/D5）**：走"物理 C++ 直接搬进物理世界目录、各仓自持 pyd"的彻底分家路线，物理侧新模块命名 `hotools_physics`。完整的切分清单、可行性与风险见 **§8 原生归属**；此处不再保留方案对比。

关键可行性依据（实测）：
- `hotools_native.cpp` 的 PropertyCurve 绑定用 raw `PyObject*` + capsule，物理绑定才用 nanobind 类型 → **切分后跨模块零 nanobind 类型共享**。
- `python_buffer_utils.hpp` 只被物理 TU 包含，父仓 `property_curve`/`boolean` 都不用 → 随物理走即可。
- 父仓 Python 对 `hotools_native` 的唯一依赖是 `PropertyCurve/sampling.py` L464/L736 的默认模块名，只要求 2 个 curve 采样符号。

### 3.2 包名 `HoTools.OmniNode.PhysicsWorld` 的归属

物理侧代码里全是 `from ...names import ...` 这类相对导入，且注册器用 `f"{package}.{directory_name}.{path.stem}"` 拼绝对模块名（`OmniNodeRegister.py` L285）。因此移动目录后必须让"物理包"仍然以某个父包下的子目录形式出现。

对策（一期）：扩展发现改成**支持显式路径**：

```python
# OmniNodeRegister._discover_omninode_extensions(..., search_roots=(...))
# 目录 <root>/extensions/Hotools-Omninode-Physics/PhysicsWorld/omninode_registration.py
#   → 模块名 HoTools.OmniNode.extensions.Hotools_Omninode_Physics.PhysicsWorld.omninode_registration
```

用 `importlib.util.spec_from_file_location` 或临时 `sys.path` 注入 + `import_module` 完成装载，避免依赖目录名是合法标识符（现 L281 会因 `-` 报错）。

同时提供 **API 版本契约**：扩展声明 `omninode_api: ">=1,<2"`，父仓启动时校验，不匹配就禁用并提示（不要抛异常炸掉整个插件——现在 L289 是 `raise RuntimeError`，一个坏扩展会让 OmniNode 无法注册）。

### 3.3 父仓测试与断言硬依赖 PhysicsWorld

| 文件 | 依赖 |
| --- | --- |
| `OmniNode/tests/test_blender_package_layout.py` | L19 断言 `OmniNode/PhysicsWorld` 目录存在；L21 导入 `...PhysicsWorld.mc2.native` |
| `OmniNode/tests/test_blender_function_registration.py` | L113 断言扩展列表 `== ["PhysicsWorld"]`；L150-164 断言物理节点 bl_idname 全部存在 |
| `OmniNode/tests/test_blender_mute_passthrough_contract.py` | 大量物理节点/回归 |
| `OmniNode/tests/test_blender_node_rebuild_name.py` | 物理节点重建 |
| `OmniNode/tests/test_blender_reference_guard.py` | 物理引用门禁 |
| `OmniNode/tests/test_mc2_hotspot_timing.py` / `test_mc2_source_observation.py` | MC2 源码观测 |
| `.releaseignore` / `build_release_zip.py` | 会把 `test(s)/` 排除，但物理测试若留在父仓仍需保证"扩展缺失时跳过" |

对策：
1. 物理相关测试**迁到新仓**（它们本来就应该跟代码走）；
2. 父仓保留"扩展机制"测试：用一个 `tests/fixtures/dummy_extension/` 存根验证发现/启用/禁用/版本校验；
3. `test_blender_function_registration.py` 改为"核心节点集合"断言 + "扩展节点集合"由扩展自测覆盖。

### 3.4 `__init__.py` 生命周期是硬编码的

现状（父仓 `__init__.py`）：
- L26 `from . import OmniNode, HoTab` **无条件导入**（关掉开关也会加载整个 OmniNode 包）
- L442-443 无条件 `from .OmniNode.PhysicsWorld.blender import register as register_physics_world; register_physics_world()` → **即使 OmniNode 开关是关的，PhysicsWorld 也会注册**（这是个既存 bug/不一致，正好一起修）
- L463-464 开关打开才 `OmniNode.register()`
- L484-485、L494 反注册

对策（改动很小）：
- 用 `importlib.util.find_spec` 探测扩展是否存在 → 不存在时 UI 显示"未安装"而不是崩溃；
- 把 `register_physics_world()` 从 `__init__.py` 移除，改由 `OmniNodeRegister.register()` 在**扩展通过白名单**后调用扩展自己的 `register_blender()` 钩子（扩展契约里新增一个可选钩子）；
- 关闭开关时走完整 `unregister()`，并确保 `sys.modules` 里物理模块被清理干净（`test_blender_package_layout.py` 已有类似 `sys.modules` 断言的传统，可复用为"禁用后无残留"测试）。

### 3.5 其他接触点（都很轻）

| 位置 | 现状 | 对策 |
| --- | --- | --- |
| `HoTab/__init__.py` L266-267 | `from ..OmniNode import OmniNodeRegister` 取节点列表 | 加 try/except + 空列表兜底（OmniNode 关闭/HoTab 单独启用时） |
| `PropertyCurve/__init__.py` | 由 `OmniNode.register()` 触发注册 | 保持（PropertyCurve 属父仓核心） |
| `OmniNode/__init__.py` L40-42 | 反注册时顺带清理 PhysicsWorld 调试绘制 handler | 改为调用扩展钩子；父仓不 import 物理模块 |
| `OmniNode/Function/Physics.py` | 分类为 PHYSICS 的通用骨骼节点，**不 import PhysicsWorld** | **留父仓**（它不依赖物理世界） |

---

## 4. 扩展开关（启用/禁用）设计

`OmniNodeRegister` 已有 `OmniNodeExtensionSpec`（identifier/order/node_classes/categories），天然就是开关粒度。

- **启用/禁用（不删文件）**：新增偏好 `hoTools_omninode_disabled_extensions: StringVectorProperty`（存禁用 id，默认空）。
  - `Enabled` → 扩展节点出现在"添加节点"菜单 + 可执行；
  - `Disabled` → 不加入节点菜单、`OmniCompiler` 遇到该扩展节点直接报"该扩展已禁用"而不是 KeyError；已存在文件里的节点**不再执行**但保留在树里（关键：不能静默丢用户数据）。
  - 切换后重建注册表（`_rebuild_registry()` 已有），无需重载 Blender。
- **安装/卸载**：
  - **禁用 ≠ 卸载**。卸载 = 从磁盘移除扩展目录（`shutil.rmtree` + 清 `__pycache__` + 清 `sys.modules`）。
  - Windows 下文件被占用：采用"复制到 `.trash/<timestamp>/` 再重启时清理"的两段式删除，避免 pyd 被进程锁住导致删除失败。
  - 安装 = 支持两种来源：本地 ZIP/目录、GitHub Release 资产（`omni_physics-<ver>-py<abi>.zip`）。父仓已有 `updater.py` 的下载/替换/重启机制，可直接复用其模式。
  - Blender 偏好里显示：扩展名 / 版本 / 兼容范围 / 原生模块是否可用（`hotools_jolt` 缺失时明确提示"刚性物理不可用，其余可用"——现有代码已经是静默降级，见 `rigid/nodes.py` L170-177）。
- **偏好落盘与"默认值"**：扩展默认**开启**（行为不变）或默认关闭（更干净但会让老用户困惑）。建议：内置发布包含时装默认开启，独立下载安装时默认开启，只有用户手动禁用才记忆为禁用。

---

## 5. 施工顺序与验收（阶段顺序已并入 §9；此处只保留总览）

> 阶段内容、文件级清单与验收标准见 **§9 执行方案**；工时见 **§12**。本节仅保留"什么算做完"的判据：

| 阶段 | 内容 | 验收标准 |
| --- | --- | --- |
| Phase A | **原生分家（最高优先级）** | 父仓 `hotools_native` 不再含物理符号且 PropertyCurve 原生后端可用；新仓自带 `hotools_physics` + `hotools_jolt` 并跑通物理原生测试 |
| Phase 0 | 基线冻结与备份 | 基线 SHA + 前后可对比的测试通过清单；`git clone --mirror` 备份就位 |
| Phase 1 | 父仓扩展机制（改代码，不搬目录） | 存根扩展能装/能发现/能启用禁用；坏扩展只禁用它自己；物理世界仍在原地且行为不变 |
| Phase 2 | 搬家 + 两仓各自跑绿 | 新仓独立跑通物理测试；父仓在"扩展缺失 / 存在 / 禁用"三种状态下都正常 |
| Phase 3 | 安装/卸载闭环 + 打包与发布线分离 | 父仓 ZIP 经内容白名单校验后**不含**任何物理路径；扩展 ZIP 可独立安装 |
| Phase 4 | 4.5 + 5.2 实机安装/禁用/卸载 | §9 Phase 4 的 5 个场景全部通过，且不污染现有 `5.2/config` |

> 沙箱说明：写 `…/Blender/5.2/…` 与 `…/addons/`（除本仓外）会被文件沙箱拦截，Phase 4 需要一次性更高权限；也可以全程在临时 `BLENDER_USER_CONFIG` 下进行，完全不碰你现有配置。
> 编译说明：Phase A 的原生构建需要你在普通终端执行 `build.bat`（沙箱内无 cmake/MSBuild，且重型编译不适合由我代跑）。

---

## 6. 风险登记表（已并入 §11）

> 风险清单见 **§11 风险登记表**（含新增的 R1/R2/R3/R4 原生分家风险）。回滚方案：Phase A 在分支上做，回滚 = `git reset --hard <基线 SHA>` + 恢复 `_Lib` 下两个 pyd（构建产物不入库，需保留备份副本）。

---

## 7. 已确认决策

| # | 决策 | 取值 | 对方案的影响 |
| --- | --- | --- | --- |
| D1 | 原生策略 | **各仓自持 pyd（原 N2 路线），且 C++ 直接放进物理世界目录下** | 一期就要动 CMake；解决了首版"双来源兜底"的临时态，见 §8 |
| D2 | 嵌套形态 | **嵌套目录 + `.gitignore` + link 脚本**（非 submodule） | ZIP 安装用户无 git 痕迹；两仓互不牵制 |
| D3 | 发布形态 | **父仓单包不含扩展，扩展一律独立安装** | 必须新做"扩展安装/卸载"闭环，否则用户拿不到物理功能 |
| D4 | 拆分范围 | **只拆物理世界**，OmniNode 核心留父仓 | 接口按"将来可外置"设计，但本次不做 |
| D5 | 优先级 | **原生 pyd 独立持有 = 最高优先级，先做** | 排在 Python/文档搬迁之前，成为独立的 Phase A |

**D5 的理由（成立）**：一旦"父仓不编译任何物理 TU、物理仓自带 `hotools_physics` + `hotools_jolt`"，后面所有 Python/文档/测试搬迁都只是搬文件，不再需要在加载器里写"两处兜底"的临时逻辑；反之若先搬 Python，会留下一层终将被删掉的过渡代码。

> 关于首版 N1 的取舍说明：N1 的价值是"零 C++ 返工"，但代价是物理仓不完整、原生加载器要维护双来源。D5 明确了这个代价不划算——**原生拆分前置**，`hotools_native` 的物理 pyd 与父仓彻底分家。

---

## 8. 原生归属：pyd 分家（本计划的地基）

### 8.1 现状问题

`_native/CMakeLists.txt` L251-279 把**物理与非物理编进同一个 `hotools_native`**：

| 归属 | 现有 translation unit |
| --- | --- |
| **父仓（PropertyCurve 用）** | `hotools_native.cpp`（注册壳）、`property_curve.cpp`、`include/hotools_property_curve.hpp` |
| **物理世界** | `field_runtime*`、`mc2_*`(10)、`mesh_xpbd*`、`spring_bone_vrm*`、`rigid_writeback*` |
| **物理世界（独立模块）** | `jolt_rigid.cpp` → `hotools_jolt` |
| **父仓（独立模块）** | `boolean_outer_hull.cpp` → `hotools_boolean` |

实测确认的**好消息**：
- 父仓 Python 对 `hotools_native` 的唯一依赖是 `PropertyCurve/sampling.py` L464/L736 的默认参数 `module_name="hotools_native"`，只要求 `sample_property_float_curve` / `sample_property_color_curve` 两个符号（`PropertyCurve/__init__.py` L16 调用 `try_use_native_curve_sampler_backend()`）。
- `hotools_native.cpp` 的注册壳里，PropertyCurve 部分用的是 **raw `PyObject*` + capsule**（`hotools::*_object`），物理部分才用 nanobind 类型（`field_runtime`/`mc2`/`mesh_xpbd`/`rigid_writeback` + 手写的 `spring_vrm_*` C-API）。→ **切开后跨模块没有任何 nanobind 类型需要共享**，这是最关键的可行性依据。
- `python_buffer_utils.hpp` 只被物理 TU 包含（`mc2_bindings/mc2_fingerprint/mc2_frame_orientations/spring_bone_vrm_bindings`），父仓的 `property_curve`/`boolean` 都不用。

### 8.2 目标切分

| | 父仓 HoTools | 新仓 HoTools-Omninode-Physics |
| --- | --- | --- |
| 扩展模块 | `hotools_native`（**瘦身：只留 property_curve**）、`hotools_boolean` | `hotools_physics`（**新名：field+mc2+xpbd+spring_vrm+rigid_writeback**）、`hotools_jolt` |
| 编译单元 | `hotools_native.cpp`（裁到只剩 property_curve 注册）、`property_curve.cpp`、`boolean_outer_hull.cpp` | `hotools_physics.cpp`（原 `hotools_native.cpp` 的物理部分）、全部物理 TU、`jolt_rigid.cpp` |
| 共享头 | `include/hotools_property_curve.hpp` | `include/hotools_mesh_xpbd.hpp`、`include/hotools_spring_bone_vrm.hpp`、`src/*.hpp`、**`src/python_buffer_utils.hpp`（随物理走）** |
| 构建入口 | `_native/` CMake（裁掉 Jolt 块与物理源） | `<物理世界目录>/native/` 独立 CMake 工程 |
| 产物落点 | `_Lib/<abi>/HotoolsPackage/` | 扩展自带 `native/runtime/<abi>/`（开发期可 junction 到父仓 `_Lib` 便于调试） |
| 布局保护 | — | **`build.bat` 里那段 layout stamp 必须整体搬走**：`FRAME/DOMAIN/FIELD_LAYOUT_HEADER` 变更即强制重建 `hotools_physics`（CMakeLists L284-306 的 `OBJECT_DEPENDS` 注释明确说这是防"陈旧生产者 + 新消费者"ABI 错配） |

**命名决策**：物理侧新 pyd 用 **`hotools_physics`**，明确不叫 `hotools_native`。理由：两者同名时只能靠 `sys.path` 顺序保证加载到正确的那一个，而父仓 `__init__.py` 先插入了 `_Lib/<abi>/HotoolsPackage`，路径顺序随时可能被改坏；同名还会让"加载器静默拿到瘦身模块 → 符号校验失败"变成难查的故障。改名的代价只是物理侧加载器换一个 import 名（3 个文件，见 §9.3）。

### 8.3 共享第三方源码缓存（避免重复下载）

`_native/.fetch-cache/` 里已有 nanobind / joltphysics / libigl / cgal / eigen / boost 的解压源码（`_native/CMakeLists.txt` L60-77 的机制）。新仓集成方式：

- 新仓自己的 CMake 增加 `HOTOOLS_FETCH_CACHE` 变量，默认 `<新仓>/native/.fetch-cache`；设置时复用父仓缓存目录，避免 nanobind（+ 物理仓用不到的 Jolt）重复拉取。
- **`build/` 目录不复用**：CMake 生成物内含绝对路径，target 名也会冲突。
- 该缓存目录在两仓 `.gitignore` 中均已忽略，不进仓库。

---

## 9. 执行方案（Phase 级，含文件清单）

### Phase A — 原生分家（**最高优先级**，2.5–3.5 天）

> 先做这一步，父仓此时仍是完整功能（两套 pyd 并存可用），可独立验收、独立回滚。

**A1 父仓瘦身 `hotools_native`**
- `_native/src/hotools_native.cpp`：**重写为只有 property_curve 的注册壳**（原文件里那批 `spring_vrm_*` 手写绑定与 `bind_field_runtime/bind_mc2/bind_mc2_domain_cpu/bind_mesh_xpbd/bind_rigid_writeback` 全部挪到新仓的 hub）。
- `_native/CMakeLists.txt`：`hotools_native` 源列表裁到 `hotools_native.cpp` + `property_curve.cpp`；删除物理 TU 的 `OBJECT_DEPENDS` 段（物理仓自带）。
- 需要重点验证的**共享 `PyObject`/capsule 边界**：`bind_rigid_writeback` 与 property_curve 都用 raw C-API，切分时确认 `include/hotools_property_curve.hpp` 不反向依赖物理头。

**A2 父仓移除 Jolt**
- 删 `HOTOOLS_BUILD_JOLT` / `HOTOOLS_BUILD_JOLT_THREAD_PROBE` / `HOTOOLS_BUILD_JOLT_THREADPOOL_EXPERIMENT` 三个 option，与 L144-243（FetchContent + `Mutex.h` 补丁）、L395-430、L433-467 三段 target。
- `_native/src/jolt_rigid.cpp`、`_native/tests/test_jolt_*.py`、`_native/tests/test_jolt_thread_pool.cpp` 迁新仓。
- `build.bat` / `CMakePresets.json`：移除 jolt 相关分支与 preset（`jolt`/`jolt-final` 等）。
- 副作用（正向）：父仓原生构建不再拉 JoltPhysics，冷构建明显变快。

**A3 新仓原生工程**
- `<物理世界目录>/native/`：`CMakeLists.txt`（复用父仓的 nanobind 获取方式、`HOTOOLS_PYTHON_EXECUTABLE`/`HOTOOLS_RUNTIME_DIR`/ABI 双目标 py311+py313 约定）、`CMakePresets.json`、`build.bat`（含 layout stamp 保护）、`src/`、`include/`。
- 新 hub 文件（如 `src/hotools_physics.cpp`）：聚合 `bind_field_runtime`/`bind_mc2`/`bind_mc2_domain_cpu`/`bind_mesh_xpbd`/`bind_rigid_writeback` + 手写 `spring_vrm_*`。
- 产物写入扩展自带 `native/runtime/<abi>/`。

**A4 物理侧加载器改造（关键正确性点）**
- `rigid/backends/jolt.py` L37-41：`_load_native()` 目前是**裸** `importlib.import_module("hotools_jolt")`，无任何路径兜底 → 改为走统一的扩展原生解析：
  1. `HOTOOLS_NATIVE_TEST_DIR`（测试覆盖，保留现有语义）
  2. 扩展自带 `native/runtime/<abi>/`
  3. 父仓 `_Lib/<abi>/HotoolsPackage/`（开发/过渡期）
  4. `HOTOOLS_LEGACY_NATIVE=1` 时额外尝试父仓 `hotools_native`（过渡逃生门，默认关）
- `mc2/native.py`、`field/native.py`、`xpbd/native.py`：`import_module("hotools_native")` → `hotools_physics`；**严格模式**（探针符号缺失就视为"模块不存在"并继续找下一个候选），避免静默拿到瘦身版 `hotools_native`。
- `_native/tests/*mc2*`、`*mesh_xpbd*`、`*spring_bone*`、`*rigid_writeback*`、`benchmark_field_runtime_native.py` 的模块名同步改为 `hotools_physics`（约 30 个文件 + `_native/tests/run_all.py`）。
- `rigid/nodes.py` L170-177 / `rigid/solver.py` L774 的中文提示文案由"请先编译 native binding（build.bat）"改为指引扩展原生构建。

**A5 父仓 PropertyCurve 加固（防"将来物理仓意外提供同名模块"）**
- `PropertyCurve/sampling.py` L464/L736：`try_use_native_backend` 支持传入**模块对象**；父仓自己用 `importlib.util` 从自身 `_Lib` 定位 `hotools_native` 后把对象传进去，不再依赖 `sys.path` 顺序与模块名解析。
- 保留 `module_name=` 参数签名以兼容既有调用方（仅 `PropertyCurve/__init__.py` L16 一处）。

**A6 父仓打包/验证脚本**
- `tools/build_release_zip.py` L102：`hotools_jolt` 从必需文件**移除**（父仓不再产它）；L105 `hotools_native` 保留必需。
- `tools/verify_release_install.py` L40-41/L67-68：改为校验瘦身后的 `hotools_native` 具备 property_curve 符号。
- `.releaseignore` / `.gitignore`：清物理专属规则。

**Phase A 验收标准**
1. 父仓 `build.bat 313 native boolean` 成功，且 `hotools_native` 体积明显下降、不再含物理符号（`hasattr` 断言）。
2. 新仓 `build.bat` 产出 `hotools_physics` + `hotools_jolt`（py311/py313 各一套）。
3. **两套 pyd 同时在场**时：`PropertyCurve` 走原生后端正常采样；物理 MC2/XPBD/Spring/刚性全部可用；两模块各加载各自的符号，无类型串味。
4. 物理原生测试（`_native/tests` 迁走后在新仓跑）全绿。

> ⚠️ **工具链提醒**：本机 cmake 在 `D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe`，MSBuild 在 `…\MSBuild\Current\Bin\MSBuild.exe`。沙箱内 `cmake`/`ninja` 不在 PATH，且编译这类重型原生工程不适合由我直接执行——**Phase A 的编译验证需要你在普通终端运行 `build.bat`**，我负责准备好脚本、CRT/ABI 参数与断言，并解读输出。

---

### Phase 0 — 基线冻结（0.5 天）
- `git rev-parse HEAD` 存档；`git clone --mirror` 备份父仓（`filter-repo` 只在副本上操作）。
- 现状冒烟：4.5(py311)/5.2(py313) 各跑一次导入 + 注册；记录 `OmniNode/tests` 与物理测试通过清单作为对比基线。

### Phase 1 — 父仓扩展机制（1.5–2 天，不动物理代码）

| 文件 | 改动 |
| --- | --- |
| `OmniNode/OmniNodeRegister.py` | ①`_discover_omninode_extensions` 增加 `search_roots`（`OmniNode/extensions/`、用户数据目录）+ `extension.json` 清单驱动；②支持非标识符目录名（`HoTools-Omninode-Physics`）；③**单扩展失败隔离**（不再 L289 `raise` 掉整棵树）；④API 版本校验；⑤禁用列表过滤 |
| `OmniNode/__init__.py` | L40-42 的物理调试 handler 清理改为走扩展钩子，父仓不 import 物理模块 |
| `__init__.py`（父仓根） | L26 改条件导入；**删除 L442-443 / L484-485 硬编码 `register_physics_world`**；L463 开关逻辑保留；偏好面板加扩展区块（状态/版本/启用/禁用/安装/卸载） |
| `OmniNode/OmniNodePanel.py` 或偏好 UI | 新增扩展管理 UI（沿用现有 `_draw_module_box` 风格） |
| `HoTab/__init__.py` | L266-267 包 try/except + 空列表兜底 |
| 契约新增 | 可选钩子 `register_blender() / unregister_blender()`；`extension.json` schema（id/version/omninode_api/requires_hotools/native 需求） |
| `OmniNode/tests/fixtures/dummy_extension/` | 存根扩展：发现 / 启用 / 禁用 / 版本不匹配 / 加载失败隔离 的回归测试 |

### Phase 2 — 搬家（1.5–2.5 天）

**新仓创建**
- `git filter-repo --path OmniNode/PhysicsWorld --path OmniNode/doc ...`（保留历史；父仓不动，只在 mirror 副本上跑）。
- 迁入：`PhysicsWorld/**`(606) · `doc/**`(13) · `tools/mc2_unity_oracle/**` · `run_mc2_v1_acceptance.ps1` · `audit_mc2_architecture.py` · PhysicsWorld/MagicaCloth2 的 ignore 规则。
- 注意：原生 C++/CMake 在 Phase A 已就位在新仓，本阶段只做 Python/文档/工具搬迁。

**父仓清理**（逐项）
- 删 `OmniNode/PhysicsWorld/**`、13 篇物理文档、物理测试；`OmniNode/tests/test_blender_package_layout.py` L19-21 改断言；`test_blender_function_registration.py` L113/L150-164 改为"扩展存在时断言，缺失时跳过"。
- 新增 `tools/link_extension.ps1`（junction 双向链接/解除）。

### Phase 3 — 安装/卸载闭环 + 打包与发布线（1.5–2 天）
- 扩展安装器：本地 ZIP / 本地目录 / GitHub Release 资产；落点 `OmniNode/extensions/<name>/` → 失败退到用户可写目录；两段式卸载（规避 Windows pyd 占用）。
- 父仓 `release.yml` 只出 HoTools（py311/py313），无物理内容。
- 新仓 `release.yml`：产出含 `hotools_physics` + `hotools_jolt` 的扩展 ZIP（py311/py313 各一）。
- ZIP 内容白名单断言扩展（复用 `validate_archive` 思路）。

### Phase 4 — 实机验证（0.5–1 天）：4.5 + 5.2 双版本
在**独立配置目录**（`--env BLENDER_USER_CONFIG=<临时目录>`，不污染现有 5.2 配置）验证：
1. 仅装父仓包 → OmniNode 正常、物理菜单不出现、UI 提示"未安装"，无异常日志，PropertyCurve 原生后端可用；
2. 装扩展 ZIP → 物理节点出现、`hotools_jolt` 可用（刚性求解可执行）、MC2/XPBD/SpringVRM 节点可用；
3. 禁用扩展 → 菜单消失、已有工程含物理节点时给出明确提示且不丢数据；
4. 卸载扩展 → 文件删除成功（两段式）、无 `sys.modules` 残留、重启后仍干净；
5. 版本不匹配（父仓 API 与扩展声明冲突）→ 扩展被禁用并给出可读提示，OmniNode 核心不受影响。

---

## 10. 扩展开关（启用/禁用）设计

`OmniNodeRegister` 已有 `OmniNodeExtensionSpec`（identifier/order/node_classes/categories），天然就是开关粒度。

- **启用/禁用（不删文件）**：新增偏好 `hoTools_omninode_disabled_extensions: StringVectorProperty`（存禁用 id，默认空）。
  - `Enabled` → 扩展节点出现在"添加节点"菜单 + 可执行；
  - `Disabled` → 不加入节点菜单、`OmniCompiler` 遇到该扩展节点直接报"该扩展已禁用"而不是 KeyError；已存在文件里的节点**不再执行**但保留在树里（关键：不能静默丢用户数据）。
  - 切换后重建注册表（`_rebuild_registry()` 已有），无需重载 Blender。
- **安装/卸载**：
  - **禁用 ≠ 卸载**。卸载 = 从磁盘移除扩展目录（`shutil.rmtree` + 清 `__pycache__` + 清 `sys.modules`）。
  - Windows 下文件被占用：采用"复制到 `.trash/<timestamp>/` 再重启时清理"的两段式删除，避免 pyd 被进程锁住导致删除失败。
  - 安装 = 支持两种来源：本地 ZIP/目录、GitHub Release 资产（`omni_physics-<ver>-py<abi>.zip`）。父仓已有 `updater.py` 的下载/替换/重启机制，可直接复用其模式。
  - Blender 偏好里显示：扩展名 / 版本 / 兼容范围 / 原生模块是否可用（`hotools_physics`、`hotools_jolt` 缺失时分别给出明确提示——现有代码是静默降级，见 `rigid/nodes.py` L170-177）。
- **偏好落盘与"默认值"**：D3 下"未安装"是常态，安装后建议**默认启用**；只有用户手动禁用才记忆为禁用。

---

## 11. 风险登记表

| # | 风险 | 等级 | 缓解 |
| --- | --- | --- | --- |
| R1 | 拆 `hotools_native` 时漏搬 TU／符号，导致物理或 PropertyCurve 静默降级 | **高（Phase A 核心风险）** | ①父仓断言：瘦身模块**必须不含**物理符号；②物理侧断言：11 个 MC2 必需符号 + XPBD/Field/Spring/Rigid 探针齐全；③两套 pyd 同时在场的联调测试；④`git grep` 全量核对 import 名 |
| R2 | 两 pyd 共享同一 Python 解释器（都静态链 nanobind `NB_STATIC`）出现类型/CRT 冲突 | 中 | 跨模块零 nanobind 类型共享（已实测确认）；都按同一 ABI 构建且构建期校验 `sys.version_info`；附录记录实测结论 |
| R3 | 物理 pyd 重命名后**遗漏**某处 `import hotools_native` → 运行期才发现 | 中 | `git grep hotools_native` 全仓核对；CI 加"父仓不得出现 hotools_physics / 物理仓不得出现 hotools_native 裸引用"的双向断言 |
| R4 | 物理 TU 搬走后父仓 `build.bat` 的 layout stamp 逻辑带走了/漏带，重现"陈旧生产者 + 新消费者"ABI 错配 | 中 | layout stamp 整体随物理仓走，并在父仓删除对应段落；新仓保留 `.mc2_native_layout.stamp` 机制 |
| R5 | 用户已有工程含物理节点，禁用/卸载扩展后打开 → 报错或丢数据 | 高 | 禁用只"不执行+不显示"，不删节点；编译器对未知/禁用节点给明确报错；卸载前提示 |
| R6 | 父仓不含扩展 + 用户不知道要单独装 → 以为物理功能"丢了" | 中 | 偏好面板明确状态与一键安装入口；发布说明标注；面板给"未安装"提示而非静默缺失 |
| R7 | 两仓版本漂移（父仓改 API，扩展没跟上） | 中 | `extension.json` 声明 API/父仓版本范围，启动校验 + 明确提示 |
| R8 | 扩展加载失败导致整个 OmniNode 注册失败（现状 L289 raise） | 中 | 改为隔离失败 + 状态可见（Phase 1 必做项） |
| R9 | 测试与 `.releaseignore` 规则漏改导致发布包混入物理测试/Unity 大文件 | 中 | CI 加"ZIP 内容白名单"断言（现有 `validate_archive` 已有雏形） |
| R10 | 历史迁移把父仓 git 弄乱 | 中 | mirror 备份 + `filter-repo` 只在副本上操作 + 父仓 main 可回滚 |
| R11 | git 仓库嵌套在 `scripts/addons/` 下被 Blender 扫描 | 低 | Blender 只扫描一级目录；嵌套 `.git` 无影响 |

**回滚方案**：Phase A 在分支上做，回滚 = `git reset --hard <基线 SHA>` + 恢复 `_Lib` 下两个 pyd（构建产物不入库，需保留备份副本）；Phase 2 的搬家失败同样可回到基线，物理代码在父仓历史里始终存在。

---

## 12. 工作量估算（按已确认决策，含原生前置）

| 阶段 | 内容 | 估时 |
| --- | --- | --- |
| Phase 0 | 基线冻结 + mirror 备份 | 0.5 天 |
| **Phase A** | **原生分家：父仓 pyd 瘦身 + Jolt 迁出 + 新仓 CMake/build.bat + 加载器改造 + 符号断言** | **2.5–3.5 天** |
| Phase 1 | 扩展机制 + 启用/禁用 + 存根测试（含"坏扩展隔离"） | 1.5–2 天 |
| Phase 2 | 历史切分 + Python/文档/工具搬迁 + 测试重排 + 两仓跑绿 | 1.5–2.5 天 |
| Phase 3 | 安装/卸载 UI 闭环 + 打包/CI/link 脚本 | 1.5–2 天 |
| Phase 4 | 4.5 + 5.2 实机安装/禁用/卸载验证 | 0.5–1 天 |
| 合计 | 一期（D1=各仓自持 pyd、D3 单包不含扩展） | **约 8–11.5 个工作日** |

> 相比首版（3.5–6 天）上浮的两个来源：**D3** 让"安装/卸载闭环"成为必需（+1 天），**D5** 把原生彻底分家前置（+2.5–3.5 天）。换来的是物理仓真正自包含、父仓不再背 Jolt 与物理 TU、没有过渡态代码。

---

## 13. 待定小项（不阻塞开工，执行中确认）

1. 物理仓最终仓名：`HoTools-Omninode-Physics`（默认）还是 `HoTools-Physics`？
2. 物理侧新 pyd 名确认用 `hotools_physics`（本计划默认）还是别的名字？
3. 扩展安装后是否默认启用（建议是）。
4. 是否保留 git 历史（建议保留；新仓首次 push 体积较大，含测试资产与 blend 夹具）。
5. `tools/mc2_unity_oracle/Library/**`（Unity 缓存，约 3GB 本机、git 已忽略）在新仓是否彻底 `.gitignore`（建议是）。
6. 开发期是否用 junction 把扩展 `native/runtime/<abi>/` 链到父仓 `_Lib/<abi>/HotoolsPackage/`（便于 Blender 内直接调试）；建议**不用**，避免又把两套 pyd 混在一个目录里，改为让加载器优先读扩展自带目录。

---

## 14. 进度日志

### Phase 0（完成）

- 基线冻结：父仓 HEAD `df49d71e`；`git clone --mirror` 备份到 `D:\HoTools-backup-mirror.git`（pack 219 MiB）。
- 基线冒烟（Blender 4.5.8/py311 与 5.2.0/py313 结果一致）：旧 `hotools_native` 为**合并模块**——property_curve 8 符号 + MC2 81 + field_runtime 6 + xpbd 1 + spring_vrm 6 + rigid_writeback 1；`hotools_jolt` 可用；PropertyCurve 原生后端可用；MC2 必需符号 22/22 齐全。
- 工具链确认：cmake 在 VS2022 内置路径、MSBuild 可用；`git filter-repo` **未安装**（Phase 2 需要先装或改用 `git subtree`）。

### Phase A（完成，commit `934cd3b4`）

**父仓侧**
- `hotools_native` 瘦身为只含 PropertyCurve：入口 `hotools_native.cpp` → `hotools_property_curve.cpp`；TU 只留入口 + `property_curve.cpp`。
- 移除全部 Jolt 相关：`HOTOOLS_BUILD_JOLT` / 线程池探针 / 隔离 pyd 三个 option 与 target、JoltPhysics FetchContent、Blender 兼容 `Mutex.h` 补丁。
- 物理 TU 与测试迁出（31 个源文件 + 28 个测试 + `python_buffer_utils.hpp` + `JOLT_BLENDER_COMPAT.md`）。
- `build.bat` / `CMakePresets.json` 去掉 jolt 分支；布局戳改为守护 `include/hotools_property_curve.hpp`；传 `jolt` 会提示改用物理工程。

**物理世界侧（`OmniNode/PhysicsWorld/native/`）**
- 自持独立 CMake 工程 + `build.bat`（含 MC2/Field 三头文件的整体重建保护）+ `CMakePresets.json`（py311/py313 × all/physics/jolt）。
- 新模块入口 `src/hotools_physics.cpp`（nanobind），源文件按 `src/mc2|field|xpbd|spring_vrm` 分组，共享头放 `include/`。
- 产物落 `native/runtime/<abi>/`：`hotools_physics.cp313-win_amd64.pyd`（0.88 MB）、`hotools_jolt.cp313-win_amd64.pyd`（1.27 MB）。

**加载边界**
- 新增 `PhysicsWorld/native_runtime.py`：解析顺序 = 环境覆盖（`HOTOOLS_PHYSICS_NATIVE_DIR` / `HOTOOLS_NATIVE_TEST_DIR`）→ 扩展自持 runtime → 父仓 `_Lib`（过渡回退，命中打 warning）→ 显式 `HOTOOLS_LEGACY_NATIVE_FALLBACK=1` 逃生门；以**探针符号齐全**为接受标准；插入路径时 `invalidate_caches()`（否则刚构建出的 pyd 永远发现不了）。
- 加载点改造：`mc2/native.py`、`field/native.py`、`xpbd/native.py`、`xpbd/bone_xpbd/native.py`、`spring_vrm/native.py`、`writeback.py`、`rigid/backends/jolt.py`。
- `PropertyCurve/_native_backend.py`：按自身路径解析父仓 `hotools_native` 并传**模块对象**，不再依赖 `sys.path` 顺序；`sampling.try_use_native_backend()` 同时接受模块对象与旧模块名（向后兼容）。
- 打包/校验：`build_release_zip` 不再要求 `hotools_jolt`；`verify_release_install` 断言 `hotools_native` 只有 PropertyCurve 符号且**不含**物理符号。

**实测结论**

| 验证项 | 结果 |
| --- | --- |
| py313 父仓 `hotools_native` | 8 符号（PropertyCurve）；MC2/Field/XPBD/Spring/Rigid **均为 0** |
| py313 扩展 `hotools_physics` | 111 符号：MC2 81 + Field 6 + XPBD 1 + Spring 6 + Rigid 1；PropertyCurve 0 |
| py311 父仓瘦身版 | 8 符号 / 0 物理符号（122 KB，旧版 965 KB）；已在临时目录验证，**待替换**（见遗留 1） |
| 同进程共存 | 两者各取所需：PropertyCurve 走父仓模块、物理走扩展模块，无符号串味 |
| 物理原生测试 | 17/17 通过（py313，Blender 5.2 Python） |
| Blender 5.2 端到端注册 | 通过：275 节点类、扩展 `PhysicsWorld`、56 个物理节点、`HO_OmniNode_physicsWorldBegin`/`physicsMC2Step` 可建实例、Jolt 可实例化 `JoltWorld` |

**遗留待办（Phase A 收尾）**

1. **py311 的 `_Lib/py311/HotoolsPackage/hotools_native.cp311-win_amd64.pyd` 仍是旧合并版**（DLL 被运行中的 Blender 4.5 占用）。关闭 4.5 后执行 `_native\build.bat 311 native`，或用已构建好的 `D:\HoTools-build\py311-native-probe\runtime\hotools_native.cp311-win_amd64.pyd` 直接替换。
2. 父仓 `_Lib/py311|py313/HotoolsPackage/hotools_jolt.*.pyd` 属迁移前遗留，最终态应由扩展自持。py313 已从 5.2 副本移除并验证扩展路径；4.5 副本待关闭 Blender 后清理。
3. 5.2 安装副本已按“本机保持目录结构”覆盖同步（robocopy 排除 `_native`，物理工程内容单独拷贝）。这是本机实验；Phase 2 会换成正式的嵌套仓库。

### Phase 1（完成）：父仓扩展机制与启用/禁用开关

**注册器（`OmniNode/OmniNodeRegister.py`）**
- 扩展发现改为**描述符驱动**：新增 `OmniNodeExtensionDescriptor`（identifier / order / source / version / omninode_api / requires_hotools / error / disabled_by_user），`_registry.extensions` 由“纯 spec”变为“描述符”，UI 因此能展示状态与错误原因。
- 两种扩展形态：
  - `builtin`：`<root>/<目录名>/omninode_registration.py` 就地注册（如 `PhysicsWorld`）；
  - `manifest`：`<root>/<目录名>/extension.json` + 包目录（外置仓库），清单声明稳定身份、包路径、版本契约。
  - 搜索根 = `OmniNode/`（内置）+ `OmniNode/extensions/`（外置安装位，Phase 3 使用）。
- **失败隔离**：清单 JSON 非法 / 缺注册模块 / 导入抛异常 / identifier 不一致 / `omninode_api` 不兼容 / `requires_hotools` 不满足 / order 非法 —— 全部收敛为 `descriptor.error`，**不再中断整个 OmniNode 注册**。版本契约在导入代码之前校验。
- **目录名不再要求是合法 Python 标识符**（`Some-Ext.Dir` 可被定位）；身份以 identifier 为准，禁用列表不受目录改名影响。
- **同名 identifier**：清单来源优先于内置来源，被压制的那个标记为重复错误供 UI 展示。
- **扩展 Blender 生命周期钩子**：扩展可实现 `register_blender()` / `unregister_blender()`；父仓不再硬编码任何扩展的注册入口。钩子失败只打印警告，不影响节点树。
- 新增查询 API：`iter_extension_descriptors()`、`find_extension_descriptor()`、`find_extension_spec()`、`active_extension_specs()`、`set_disabled_extensions()`、`extension_failures()`、`extension_status_text()`。
- 契约常量 `OMNINODE_EXTENSION_API_VERSION = "1.0"`。

**父仓 `__init__.py`**
- **删除两处硬编码物理注册**（原 L442-443 `register_physics_world()`、L484-485 `unregister_physics_world()`）——顺带修掉“OmniNode 关着但物理世界照样注册”的既存不一致。
- 新增 `_sync_omninode_registration()`：总开关 + 禁用列表统一驱动注册/反注册。
- 新增偏好 `hoTools_omninode_disabled_extensions`（`|` 分隔的 identifier 字符串；`bpy.props` 没有字符串数组属性）与其 update 回调：切换后整体反注册→再注册，无需重启 Blender。
- 新增算子 `ho.omninode_toggle_extension`；偏好面板 OmniNode 区块现在列出每个扩展的状态、版本、来源与错误，并可勾选启用/禁用。

**物理扩展侧**
- `PhysicsWorld/extension.json`：`identifier=PhysicsWorld`、`version=0.1.0`、`omninode_api=">=1.0,<2"`、`native_modules=[hotools_physics, hotools_jolt]`。
- `PhysicsWorld/omninode_registration.py`：新增 `register_blender()` / `unregister_blender()` 钩子；入口自举把插件根挂到 `sys.path`。
- `PhysicsWorld/ui/utils.py`：`Utils` 解析改为双路（显式绝对包名 → 顶层名），不再让整棵 UI 子树依赖宿主恰好挂了插件根。

**实测**

| 验证项 | 结果 |
| --- | --- |
| 新回归测试 `OmniNode/tests/test_blender_extension_mechanism.py` | **10/10 通过**（发现/清单/失败隔离/版本契约/identifier 冲突/开关可逆/禁用保留元数据） |
| 端到端偏好开关（合成探针） | 启用：275 节点类 / 56 物理节点 / 物理生命周期已注册；禁用：219 / 0 / 未注册且 `status=disabled, error=""`；再启用：完整恢复 |
| OmniNode 测试全集 | **10/10 文件通过**（新增文件计入；`test_mc2_hotspot_timing.py` 为**既有失败**，在基线 `df49d71e` 的纯净副本上同样复现，且该文件不在任何 Phase A/1 commit 中） |
| 坏扩展鲁棒性 | API 不兼容 / 导入异常 / JSON 非法 / identifier 不一致 四类全部隔离，核心快照节点数不变 |

**Phase 1 顺带修掉的真实脆弱点**：`PhysicsWorld` 里 `from Utils...` 的绝对导入在“插件根不在 sys.path”时必须失败——这直接关系到“扩展可独立安装/加载”的目标；已改为双路解析。

> Phase 1 的设计约束（已确认）：**扩展身份是 identifier 而非目录名**；**禁用 ≠ 卸载**（磁盘文件不动、元数据可读）；**PropertyCurve 属父仓贮藏内容，物理侧只是调用方**，其注册归属仍随 OmniNode 开关（当前行为，未改变）。

### Phase 2a/2b（完成）：嵌套仓库建立 + 文档迁移

**关键约束（实测）**：物理包内有 **283 处父级相对导入**（`from ..names import ...`、`from ... import ...`），
因此仓库**不能**搬到文件系统根部——那样 `HoTools.OmniNode.PhysicsWorld` 包路径与插件结构都会断裂。
最终采用你设想的形态：**仓库嵌套在 `OmniNode/PhysicsWorld/` 内**，路径不变、导入不变。

**父仓**
- `.gitignore` 新增 `OmniNode/PhysicsWorld/`：父仓不再跟踪物理世界文件（文件留在本机同一路径）。
- 父仓跟踪文件数 1682 → **1019**；物理世界 673 个文件整体移交。
- `_native/README.md` 的物理文档引用改为新路径。

**新仓 `OmniNode/PhysicsWorld/`（HoTools-Omninode-Physics）**
- `git init -b main`，首次提交 **674 文件**（含 `native/`、`native/tests/`、各域 `test/`、fixtures、断裂测试 blend 夹具）。
- 新增 `README.md`：内容清单、原生构建用法、与父仓的三条契约（扩展发现路径、原生解析顺序、PropertyCurve 归属）。
- 新增 `.gitignore`：原生 runtime/build/fetch-cache 不入库；`*.blend*` 忽略但保留 `jolt_fracture_user_project.blend` 夹具；Unity oracle 的 Library/Logs/Temp 等忽略。
- 新增 `.gitattributes`：C++/Python LF、`.bat`/`.ps1` CRLF、blend/pyd 二进制。
- 13 篇物理文档从 `OmniNode/doc/` 迁入 `docs/`；父仓 `OmniNode/doc/` 随之清空。

**两仓状态**：父仓 4 commit、物理仓 2 commit，工作树均干净。

**历史说明（待你定）**：本机 `git filter-repo` 未安装，且物理包必须嵌套（见上），因此新仓采用**全新历史**
（原父仓历史完整保留在 `D:\HoTools-backup-mirror.git` 与父仓提交 `fe659321` 之前的历史中）。
若需要把物理子树的历史接续到新仓，可安装 `git filter-repo` 后用 `--path OmniNode/PhysicsWorld` 切分再
merge；由于路径与包结构必须保持嵌套，这一步收益有限（历史里的路径前缀无法直接复用）。

### Phase 2 剩余工作

1. `tools/` 下的物理工具未迁：`mc2_unity_oracle/**`（Unity 工程）、`run_mc2_v1_acceptance.ps1`、`audit_mc2_architecture.py`。
2. 父仓 `OmniNode/tests/` 里仍有物理相关测试（`test_mc2_hotspot_timing.py`、`test_mc2_source_observation.py`）与
   引用物理扩展的测试（`test_blender_reference_guard.py` 等），需决定迁出还是保留并加"扩展缺失即跳过"。
3. 发布流程适配：父仓 `release.yml` / `build_release_zip.py` 尚未感知"扩展存在于嵌套仓库"这一形态。

### Phase 3/4（未开始）

见 §9 的 Phase 3（安装/卸载闭环 + 发布线分离）与 Phase 4（4.5 + 5.2 实机验证）。



