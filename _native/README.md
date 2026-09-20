# HoTools 本体原生后端（_native）

`_native` 只服务 **HoTools 本体**，提供两个 Python 扩展模块：

- **`hotools_native`**：nanobind 扩展，仅含 **PropertyCurve 采样内核**（float/color 曲线编译与采样）
- **`hotools_boolean`**：nanobind + CGAL/libigl 精确外壳/自身并集重构

C++ 侧只处理数组与内核计算，不直接碰 Blender 场景对象。Python 侧负责场景采集、缓存管理、节点状态同步和结果回写。

---

## 物理世界原生模块已迁出本目录

MC2 / Field / XPBD / SpringVRM / RigidWriteback 的 C++ 与 `hotools_jolt`（Jolt Physics 绑定）随物理世界拆分，构建工程位于：

```
OmniNode/PhysicsWorld/native/
├── CMakeLists.txt      独立 CMake 工程，产出 hotools_physics + hotools_jolt
├── CMakePresets.json   vs2022-py311|py313(-physics|-jolt)
├── build.bat           物理原生构建入口（含 MC2/Field 共享布局头的整体重建保护）
├── src/ include/       物理 TU 与私有头（python_buffer_utils.hpp 已随迁）
├── tests/              物理原生测试
├── docs/               JOLT_BLENDER_COMPAT.md
└── runtime/py311|py313 自持 pyd 落点
```

物理扩展的 pyd **不写入本插件的 `_Lib/`**。运行时由 `OmniNode/PhysicsWorld/native_runtime.py`
按“环境覆盖 → 扩展自带 `runtime/<abi>/` → 父仓 `_Lib`（开发过渡期）”解析，并以**探针符号是否齐全**
作为接受标准；`hotools_native` 与 `hotools_physics` 模块名不同，避免依赖 `sys.path` 顺序。

> 迁移背景、决策与完整方案见 `_research/OMNINODE_PHYSICS_SPLIT_PLAN.md`。

---

## 本机路径（常用）

> 路径有变动时同步更新 `build.bat` 顶部和 `CMakePresets.json`。

| 用途 | 路径 |
|------|------|
| **插件根目录** | `C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools` |
| **Blender 4.5.8** | `D:\Blender\blender-4.5.8-windows-x64\` |
| **Blender 4.5 Python（py311）** | `D:\Blender\blender-4.5.8-windows-x64\4.5\python\bin\python.exe` |
| **Blender 5.2.0** | `D:\Blender\blender-5.2.0-windows-x64\` |
| **Blender 5.2 Python（py313）** | `D:\Blender\blender-5.2.0-windows-x64\5.2\python\bin\python.exe` |
| **Visual Studio 2022** | `D:\Microsoft Visual Studio\2022\Community` |
| **MSBuild** | `D:\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe` |
| **cmake（VS 内置）** | `D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe` |

---

## 构建

### 快速编译（推荐）

双击或在 `_native/` 下运行 `build.bat`。默认构建 `hotools_native` 的 py311 + py313：

```bat
:: 编译 hotools_native 的 py311 + py313（默认）
build.bat

:: 编译 hotools_native + hotools_boolean 的 py311 + py313
build.bat all

:: 只编译 hotools_native 的 Blender 4.5 / py311
build.bat 311

:: PropertyCurve 日常开发：只增量编译 py313 的 hotools_native
build.bat 313

:: 只编译 Blender 4.5 的精确外壳布尔模块
build.bat 311 boolean

:: 显式构建 py313 的两个模块
build.bat 313 all
```

`native`、`boolean` 和组合模式使用独立的 CMake build 目录。普通实现改动会复用对应的
`CMakeCache.txt` 和对象文件；切换模块也不会改写另一模块的 cache。
`include/hotools_property_curve.hpp` 比当前 ABI 的布局戳更新时，`hotools_native` 会自动执行一次
`--clean-first`，防止 capsule/结构体布局新旧混用。

> 物理模块（`hotools_jolt` / `hotools_physics`）已不在本工程内。需要时运行
> `OmniNode\PhysicsWorld\native\build.bat`；在本工程里传 `jolt` 会给出提示并退出。

### 产物路径

```
_Lib\py311\HotoolsPackage\hotools_native.cp311-win_amd64.pyd
_Lib\py311\HotoolsPackage\hotools_boolean.cp311-win_amd64.pyd
_Lib\py313\HotoolsPackage\hotools_native.cp313-win_amd64.pyd
_Lib\py313\HotoolsPackage\hotools_boolean.cp313-win_amd64.pyd
```

### 首次初始化 / 重新 configure

cmake 通过 VS2022 内置的可执行文件调用（见上方路径表），用 PowerShell 执行：

```powershell
$cmake = 'D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
$src   = '..\_native'   # 在 _native/ 同级目录时调整相对路径

& $cmake --preset vs2022-py311-native -S $src
& $cmake --preset vs2022-py313-native -S $src
```

之后直接用 `build.bat` 编译即可，无需重复 configure。`vs2022-py311/313` 保留给显式 `all` 组合构建。

### 依赖获取策略

- **nanobind**：优先使用 `extern/nanobind/`（git submodule），无则 FetchContent 拉取并缓存至 `.fetch-cache/`
- **outer-hull**：CMake 固定 libigl v2.6.0；其配方固定 CGAL 6.0.1、Eigen 5.0.1、Boost 1.86.0
- `.fetch-cache/` 强制放在 `_native/` 下，独立于 `build/` 目录，清 build 不重新下载
- Boost 大包可先运行 `fetch_boolean_dependencies.ps1` 下载到 `extern/archives/` 并校验 MD5
- 物理工程可在配置时传 `-DHOTOOLS_PHYSICS_FETCH_CACHE=<本目录>\.fetch-cache` 复用 nanobind 源码；
  `build/` 目录**不可**跨仓共用（生成物含绝对路径，target 名会冲突）

配置 git submodule（可选，提供稳定的本地源码路径）：

```bat
setup_extern.bat
```

---

## 目录结构

```
_native/
├── src/            # C++ 源码（hotools_native + hotools_boolean）
├── include/        # 对外 C++ 头文件（hotools_property_curve.hpp）
├── tests/          # 回归测试（property curve / boolean）
├── docs/           # Native 后端专题文档
├── extern/         # git submodule（nanobind，可选）
│   └── archives/   # 可重新下载的大型依赖压缩包（不进 git）
├── .fetch-cache/   # FetchContent 源码缓存（不进 git）
├── build/
│   ├── vs2022-py311-native/   # Blender 4.5 hotools_native
│   ├── vs2022-py311-boolean/  # Blender 4.5 hotools_boolean
│   ├── vs2022-py313-native/   # Blender 5.x hotools_native
│   ├── vs2022-py313-boolean/  # Blender 5.x hotools_boolean
│   ├── vs2022-py311/          # 显式 all 组合构建
│   └── vs2022-py313/          # 显式 all 组合构建
├── CMakeLists.txt
├── CMakePresets.json
├── fetch_boolean_dependencies.ps1
└── build.bat
```

---

## 设计分工

**Python 侧**：读 Blender 数据 → 整理连续数组 → 管理缓存和脏标记 → 写回场景对象

**Native 侧**：PropertyCurve 采样内核；可选 GPU provider 必须与 CPU owner 独立。保持 ABI 稳定，字段/数组形状改动必须通知 Python 侧同步

物理世界的原生分工（MC2 CPU 约束迭代、Jolt 刚体步进与高频碰撞内核）见
`OmniNode/PhysicsWorld/native/` 与 `OmniNode/PhysicsWorld/docs/PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`
（物理文档已随扩展迁入其独立仓库）。

---

## 测试

`tests/` 下覆盖 PropertyCurve 与 boolean 的核心单元测试，建议按顺序跑：核心数值 → Blender 集成。

---

## 相关文档

- `_native/docs/BOOLEAN_OUTER_HULL.md`
- `OmniNode/ARCHITECTURE.md`
- `_research/OMNINODE_PHYSICS_SPLIT_PLAN.md`

物理世界文档（蓝图/契约/Jolt 兼容）已随物理模块迁至 `OmniNode/PhysicsWorld/`（文档目录见拆分规划）。
