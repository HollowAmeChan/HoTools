# HoTools native 后端

`_native` 是 HoTools 的原生加速层，提供三个 Python 扩展模块：

- **`hotools_native`**：CPython 扩展，MC2 风格布料/弹簧骨骼求解管线
- **`hotools_jolt`**：nanobind 扩展，Jolt Physics 刚体/约束模拟后端
- **`hotools_boolean`**：nanobind + CGAL/libigl 精确外壳/自身并集重构

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

### Linux x86_64

Linux 使用 Ninja，并为每个 ABI/模块使用独立构建目录。传入的 Python 必须包含
匹配版本的开发头文件；Blender 自带 Python 若未附带头文件，可用同 ABI 的
standalone CPython 编译，再在对应 Blender 中验收。

```bash
# 可重复 --module；省略时依次构建全部三个模块
python3.11 tools/build_linux_native.py \
  --abi py311 --python /path/to/python3.11 \
  --module native --module jolt --module boolean --jobs 4

python3.13 tools/build_linux_native.py \
  --abi py313 --python /path/to/python3.13 \
  --module native --module jolt --module boolean --jobs 4
```

产物位于 `_Lib/<abi>/linux-x86_64/HotoolsPackage/`。驱动会检查扩展名、
x86_64 ELF 头、`file`、`ldd`、RPATH/RUNPATH 与实际 Python 导入，并写入
`_hotools_native_manifest.json`。FetchContent 源码与构建输出均为可再生缓存。

### 快速编译（推荐）

双击或在 `_native/` 下运行 `build.bat`。默认构建
`hotools_native`，不会配置、生成或编译 Jolt 工程：

```bat
:: 编译 hotools_native 的 py311 + py313（默认）
build.bat

:: 显式编译两个Python版本的全部模块
build.bat all

:: 只编译 hotools_native 的 Blender 4.5 / py311
build.bat 311

:: MC2 日常开发：只增量编译 py313 的 hotools_native
build.bat 313

:: 只编译 py313 的 hotools_jolt
build.bat 313 jolt

:: 只编译 Blender 4.5 的精确外壳布尔模块
build.bat 311 boolean

:: 显式构建 py313 的两个模块
build.bat 313 all
```

`native`、`jolt` 和组合模式使用独立的 CMake build 目录。普通实现改动会复用
对应的 `CMakeCache.txt` 和对象文件；切换模块也不会改写另一模块的 cache。
`mc2_frame_orientations.hpp`、`mc2_domain_cpu.hpp` 或 `field_runtime.hpp` 比当前
ABI 的布局戳更新时，`hotools_native` 会自动执行一次 `--clean-first`，防止嵌入
`FieldSampleScratchV1` 等共享结构的对象文件新旧布局混用；组合 `all` 模式会对
该 ABI 的全部模块执行 clean rebuild。显式的
`build.bat 313 native` 与 `build.bat 313` 等价。

### 产物路径

```
_Lib\py311\HotoolsPackage\hotools_jolt.cp311-win_amd64.pyd
_Lib\py311\HotoolsPackage\hotools_native.cp311-win_amd64.pyd
_Lib\py311\HotoolsPackage\hotools_boolean.cp311-win_amd64.pyd
_Lib\py313\HotoolsPackage\hotools_jolt.cp313-win_amd64.pyd
_Lib\py313\HotoolsPackage\hotools_native.cp313-win_amd64.pyd
```

### 首次初始化 / 重新 configure

cmake 通过 VS2022 内置的可执行文件调用（见上方路径表），用 PowerShell 执行：

```powershell
$cmake = 'D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
$src   = '..\_native'   # 在 _native/ 同级目录时调整相对路径

& $cmake --preset vs2022-py311-native -S $src
& $cmake --preset vs2022-py313-native -S $src
```

之后直接用 `build.bat` 编译即可，无需重复 configure。

只有需要 Jolt 时才配置对应的 `vs2022-py311-jolt` 或
`vs2022-py313-jolt` preset；`vs2022-py311/313` 保留给显式
`all` 组合构建。

### 依赖获取策略

- **nanobind**：优先使用 `extern/nanobind/`（git submodule），无则 FetchContent 拉取并缓存至 `.fetch-cache/`
- **JoltPhysics**：优先使用 `extern/JoltPhysics/`（git submodule），无则 FetchContent 缓存
- **outer-hull**：CMake 固定 libigl v2.6.0；其配方固定 CGAL 6.0.1、Eigen 5.0.1、Boost 1.86.0
- `.fetch-cache/` 强制放在 `_native/` 下，独立于 `build/` 目录，清 build 不重新下载
- Boost 大包可先运行 `fetch_boolean_dependencies.ps1` 下载到 `extern/archives/` 并校验 MD5

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
├── docs/           # Native 后端专题文档
├── extern/         # git submodule（nanobind / JoltPhysics，可选）
│   └── archives/   # 可重新下载的大型依赖压缩包（不进 git）
├── .fetch-cache/   # FetchContent 源码缓存（不进 git）
├── build/
│   ├── vs2022-py311-native/  # Blender 4.5 hotools_native
│   ├── vs2022-py311-jolt/    # Blender 4.5 hotools_jolt
│   ├── vs2022-py313-native/  # Blender 5.x hotools_native
│   ├── vs2022-py313-jolt/    # Blender 5.x hotools_jolt
│   ├── vs2022-py311/         # 显式 all 组合构建
│   └── vs2022-py313/         # 显式 all 组合构建
├── CMakeLists.txt
├── CMakePresets.json
├── fetch_boolean_dependencies.ps1
└── build.bat
```

---

## 设计分工

**Python 侧**：读 Blender 数据 → 整理连续数组 → 管理缓存和脏标记 → 写回场景对象

**Native 侧**：MC2 CPU 约束迭代、Jolt 刚体步进和高频碰撞内核；可选 GPU provider 必须与 CPU owner 独立。保持 ABI 稳定，字段/数组形状改动必须通知 Python 侧同步

---

## 测试

`tests/` 下覆盖核心单元测试和场景对拍，建议按顺序跑：核心数值 → 场景回写。

---

## 相关文档

- `_native/docs/BOOLEAN_OUTER_HULL.md`
- `_native/docs/JOLT_BLENDER_COMPAT.md`
- `OmniNode/doc/JOLT_PHYSICS_BACKGROUND_ANALYSIS.md`
- `OmniNode/PhysicsWorld/rigid/docs/README.md`
- `OmniNode/doc/PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`
- `OmniNode/doc/PHYSICS_WORLD_IMPLEMENTATION_STATUS.md`
- `OmniNode/doc/MC2_BLUEPRINT.md`
- `OmniNode/doc/MC2_GPU_BACKEND_DESIGN.md`
- `OmniNode/ARCHITECTURE.md`
