# HoTools native 后端

`_native` 是 HoTools 的原生加速层，提供两个 Python 扩展模块：

- **`hotools_native`**：CPython 扩展，MC2 风格布料/弹簧骨骼求解管线
- **`hotools_jolt`**：nanobind 扩展，Jolt Physics 刚体/约束模拟后端

C++ 侧只处理数组、上下文、约束求解和碰撞内核，不直接碰 Blender 场景对象。Python 侧负责场景采集、缓存管理、节点状态同步和结果回写。

---

## 本机路径（常用）

> 路径有变动时同步更新 `build.bat` 顶部和 `CMakePresets.json`。

| 用途 | 路径 |
|------|------|
| **插件根目录** | `C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools` |
| **Blender 4.5** | `D:\Blender\Blender 4.5\` |
| **Blender 4.5 Python（py311）** | `D:\Blender\Blender 4.5\4.5\python\bin\python.exe` |
| **Blender 5.x** | `D:\Blender\blender-5.1.0-windows-x64\` |
| **Blender 5.x Python（py313）** | `D:\Blender\blender-5.1.0-windows-x64\5.1\python\bin\python.exe` |
| **Visual Studio 2022** | `D:\Microsoft Visual Studio\2022\Community` |
| **MSBuild** | `D:\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe` |
| **cmake（VS 内置）** | `D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe` |

---

## 构建

### 快速编译（推荐）

双击或在 `_native/` 下运行 `build.bat`，**默认同时发布两个版本**：

```bat
:: 编译 py311 + py313（默认）
build.bat

:: 只编译 Blender 4.5 / py311
build.bat 311

:: 只编译 Blender 5.x / py313
build.bat 313
```

### 产物路径

```
_Lib\py311\HotoolsPackage\hotools_jolt.cp311-win_amd64.pyd
_Lib\py311\HotoolsPackage\hotools_native.cp311-win_amd64.pyd
_Lib\py313\HotoolsPackage\hotools_jolt.cp313-win_amd64.pyd
_Lib\py313\HotoolsPackage\hotools_native.cp313-win_amd64.pyd
```

### 首次初始化 / 重新 configure

cmake 通过 VS2022 内置的可执行文件调用（见上方路径表），用 PowerShell 执行：

```powershell
$cmake = 'D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
$src   = '..\_native'   # 在 _native/ 同级目录时调整相对路径

& $cmake --preset vs2022-py311 -S $src
& $cmake --preset vs2022-py313 -S $src
```

之后直接用 `build.bat` 编译即可，无需重复 configure。

### 依赖获取策略

- **nanobind**：优先使用 `extern/nanobind/`（git submodule），无则 FetchContent 拉取并缓存至 `.fetch-cache/`
- **JoltPhysics**：优先使用 `extern/JoltPhysics/`（git submodule），无则 FetchContent 缓存
- `.fetch-cache/` 放在 `_native/` 下，独立于 `build/` 目录，清 build 不重新下载

配置 git submodule（可选，提供稳定的本地源码路径）：

```bat
setup_extern.bat
```

---

## 目录结构

```
_native/
├── src/            # C++ 源码（hotools_native + hotools_jolt）
├── include/        # 对外 C++ 头文件
├── tests/          # 回归测试
├── extern/         # git submodule（nanobind / JoltPhysics，可选）
├── .fetch-cache/   # FetchContent 源码缓存（不进 git）
├── build/
│   ├── vs2022-py311/   # Blender 4.5 构建目录
│   └── vs2022-py313/   # Blender 5.x 构建目录
├── CMakeLists.txt
├── CMakePresets.json
└── build.bat
```

---

## 设计分工

**Python 侧**：读 Blender 数据 → 整理连续数组 → 管理缓存和脏标记 → 写回场景对象

**C++ 侧**：MC2 约束迭代、Jolt 刚体步进、高频碰撞内核；保持 ABI 稳定，字段/数组形状改动必须通知 Python 侧同步

---

## 测试

`tests/` 下覆盖核心单元测试和场景对拍，建议按顺序跑：核心数值 → 场景回写。

---

## 相关文档

- `OmniNode/doc/UNIFIED_PHYSICS_WORLD_NODE_SYSTEM_DESIGN.md`
- `OmniNode/doc/MC2_DESIGN_AND_WORKSHEET.md`
- `OmniNode/ARCHITECTURE.md`
