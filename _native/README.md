# HoTools 原生后端约定

本目录用于 HoTools 的 C++ / nanobind 原生后端。第一阶段目标是把 `网格物理-XPBD` / `meshPhysicsXPBD` 节点里最耗时的 XPBD solve 阶段移到 C++，Python 侧继续负责 Blender 数据准备、cache 管理、shape key 写回和节点接口。

这里借鉴的是 HoCloth 的“构建层 / 运行时层 / 发布层”分离思路，不是迁移它的业务代码。

## 版本化运行时目录

HoTools 已经天然按 Python 版本划分了 `_Lib`：

```text
_Lib/py311
_Lib/py313
```

当前约定是：

- `py311` 对应 Blender 4.1+ 这一支，也就是 Python 3.11 ABI。
- `py313` 对应 Blender 5.1+ 这一支，也就是 Python 3.13 ABI。

原生产物不要再单独放 `_bin`，也不要直接混放在 `_Lib/py311` 或 `_Lib/py313` 根目录。那些目录里已经有第三方包，native 后端统一放进专门的 `HotoolsPackage` 子目录：

```text
_Lib/py311/HotoolsPackage
_Lib/py313/HotoolsPackage
```

例如：

```text
_Lib/py311/HotoolsPackage/hotools_native.cp311-win_amd64.pyd
_Lib/py313/HotoolsPackage/hotools_native.cp313-win_amd64.pyd
```

插件启动时会按当前 Python 版本把对应的 `HotoolsPackage` 加到 `sys.path` 前面，因此 Python 侧可以稳定 `import hotools_native`，同时不会污染已有的 `_Lib/py311` / `_Lib/py313` 包集合。

## 目录约定

```text
HoTools/
  _Lib/
    py311/
      HotoolsPackage/       Blender 4.1+ / Python 3.11 的 native runtime
    py313/
      HotoolsPackage/       Blender 5.1+ / Python 3.13 的 native runtime
  _build/                   发布 staging 或临时构建目录，不提交
  _dist/                    本地临时输出目录，不提交
  _native/
    include/                C++ 头文件
    src/                    C++ 实现
    tests/                  smoke test / benchmark
    build/                  CMake 本地构建目录，不提交
```

约定很简单：

- `_native` 只放源码和构建工程，不放最终发布物。
- `_Lib/py311/HotoolsPackage` 和 `_Lib/py313/HotoolsPackage` 是 native runtime 的唯一发布入口。
- `build`、`cmake-build-*`、`.vs`、`.vscode`、`_build`、`_dist` 都是开发期内容，不进发布包。

## 固定输出位置

所有编译后的 runtime 产物都应该输出到对应版本的 `HotoolsPackage` 目录，例如：

```text
_Lib/py311/HotoolsPackage/hotools_native.cp311-win_amd64.pyd
_Lib/py311/HotoolsPackage/hotools_native.pdb
_Lib/py313/HotoolsPackage/hotools_native.cp313-win_amd64.pyd
_Lib/py313/HotoolsPackage/hotools_native.pdb
```

Python 侧只需要把对应版本的 `HotoolsPackage` 目录加入模块搜索路径，就能稳定访问这些产物。

建议 CMake 做法：

```cmake
set(HOTOOLS_RUNTIME_DIR "${HOTOOLS_PLUGIN_ROOT}/_Lib/py311/HotoolsPackage" CACHE PATH "Runtime output directory for Python 3.11")
```

或者：

```cmake
set(HOTOOLS_RUNTIME_DIR "${HOTOOLS_PLUGIN_ROOT}/_Lib/py313/HotoolsPackage" CACHE PATH "Runtime output directory for Python 3.13")
```

并且把：

```cmake
CMAKE_RUNTIME_OUTPUT_DIRECTORY
CMAKE_LIBRARY_OUTPUT_DIRECTORY
```

都指向该版本的 `HotoolsPackage` 目录。`CMAKE_ARCHIVE_OUTPUT_DIRECTORY` 则应指向 `_native/build` 这一类已忽略目录，避免 `.lib` / `.exp` 这类中间产物进发布包。

## 本机工具路径

当前机器上已经验证过这些路径存在：

```powershell
$Repo = "C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
$CMake = "D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
$VsDevCmd = "D:\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat"
$MSBuild = "D:\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe"
$BlenderPython311 = "D:\Blender\Blender 4.5\4.5\python\bin\python.exe"
```

注意：

- 不要依赖默认 `python` 或 `py -3.11`。
- Blender 4.5 使用 Python 3.11，`.pyd` 必须按 Blender 自带 Python ABI 编译。
- 如果以后还要打 3.13 版，就再准备一个对应的 Blender 5.1+ / Python 3.13 路径。

## nanobind 绑定架构

建议拆成三层。

### 1. Python 节点层

文件：

```text
OmniNode/NodeTree/Function/Physics.py
```

职责：

- 校验 Blender mesh object、shape key、pin group 和 frame continuity。
- 用 `foreach_get` 批量读取 Basis / shape key 坐标。
- 维护 runtime cache，保存 `positions`、`prev_positions`、`inv_masses` 和约束数组。
- 优先调用 C++ solve，native 不可用时回退 Python solver。
- 用 `foreach_set` 批量写回目标 shape key。

Python 层不要逐点调用 Blender setter，也不要让 C++ 直接访问 `bpy`。

### 2. nanobind 桥接层

建议模块名：

```text
hotools_native
```

建议接口先保持窄而直接：

```cpp
solve_mesh_shape_key_xpbd(
    positions,
    prev_positions,
    inv_masses,
    edge_i,
    edge_j,
    edge_rest,
    bend_i,
    bend_j,
    bend_rest,
    gravity,
    dt,
    damping,
    substeps,
    iterations,
    stretch_compliance,
    bend_compliance
)
```

约定：

- `positions` / `prev_positions` 使用 `float32`，shape 为 `(vertex_count, 3)`。
- `inv_masses` 使用 `float32`，shape 为 `(vertex_count,)`。
- 约束索引用 `int32`。
- rest length 用 `float32`。
- C++ 原地更新 `positions` 和 `prev_positions`。
- C++ 不保存 Blender 对象指针，不保存全局 solver 状态。

### 3. C++ solver 层

职责：

- prediction
- pin 修正
- stretch distance constraint
- bend distance constraint
- substep / iteration 循环
- smoke test / benchmark

目标是把当前日志里的 solve 热点移走：

```text
stretch=10.527ms bend=14.451ms solve_total=25.090ms
```

## 构建约定

### 本地编译

补上 `CMakeLists.txt` 和 `CMakePresets.json` 后，建议分别为 3.11 和 3.13 编译到不同目录：

```powershell
# Blender 4.1+ / Python 3.11
& "D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" `
  -S "_native" `
  -B "_native\build\vs2022-py311" `
  -G "Visual Studio 17 2022" `
  -A x64 `
  -T v143 `
  -DHOTOOLS_PLUGIN_ROOT="$PWD" `
  -DHOTOOLS_PYTHON_EXECUTABLE="D:\Blender\Blender 4.5\4.5\python\bin\python.exe" `
  -DHOTOOLS_RUNTIME_DIR="$PWD\_Lib\py311\HotoolsPackage"

# Blender 5.1+ / Python 3.13
& "D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" `
  -S "_native" `
  -B "_native\build\vs2022-py313" `
  -G "Visual Studio 17 2022" `
  -A x64 `
  -T v143 `
  -DHOTOOLS_PLUGIN_ROOT="$PWD" `
  -DHOTOOLS_PYTHON_EXECUTABLE="D:\Blender\Blender 5.1\5.1\python\bin\python.exe" `
  -DHOTOOLS_RUNTIME_DIR="$PWD\_Lib\py313\HotoolsPackage"
```

编译时要带：

```powershell
--config Release
```

否则 Visual Studio 多配置生成器不会把 Release 产物放到正确的运行时目录。

### 导入验证

```powershell
& "D:\Blender\Blender 4.5\4.5\python\bin\python.exe" -c "import sys; sys.path.insert(0, r'C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools\_Lib\py311\HotoolsPackage'); import hotools_native; print(hotools_native)"
```

3.13 版本同理，只是把路径换成 `_Lib\py313\HotoolsPackage` 和对应的 Python 3.13 解释器。

## 发布约定

发布给 Blender 用户安装的 zip 由 GitHub Actions workflow 生成，不在本机手动压缩。

正确流程是：

1. native build 把最终运行时产物放进 `_Lib/py311/HotoolsPackage` 或 `_Lib/py313/HotoolsPackage`。
2. 需要跟随发布的 `.pyd` / `.dll` / 必要 `.pdb` 确认在固定目录里。
3. GitHub Actions 创建临时 `HoTools/` staging 目录。
4. workflow 用 `rsync` 排除 `.git`、`.github`、IDE 目录、Python 缓存、CMake 构建目录、`_native` 源码目录等开发内容。
5. workflow 生成 `HoTools-YYYYMMDD-HHMMSS.zip`，创建 GitHub Release，并上传这个干净安装包。

GitHub Release 页面仍会自动显示 `Source code (zip)` / `Source code (tar.gz)`，但那两个是 GitHub 自动源码归档，不是给 Blender 用户安装的干净包。用户安装应下载 workflow 上传的 `HoTools-*.zip`。

`.gitignore` 和 release workflow 的职责不同：

- `.gitignore` 防止本地开发期中间产物误提交。
- `release.yml` 的 `rsync --exclude` 决定用户安装 zip 里排除哪些内容。
- `_Lib/*/HotoolsPackage` 里的最终 runtime 产物不能被 release workflow 排除。

如果后面补 `package_addon.ps1`，建议它只做：

- 配置 CMake。
- 编译 native。
- 运行 smoke test。
- 检查对应 `HotoolsPackage` 目录里的产物是否存在。

不要再加 `-CreateZip` 这类本地压缩参数；安装包压缩统一交给 GitHub Actions。

## 清理约定

```powershell
Remove-Item -LiteralPath "_native\build" -Recurse -Force
Remove-Item -LiteralPath "_build" -Recurse -Force
Remove-Item -LiteralPath "_dist" -Recurse -Force
```

## 下一步

1. 补 `CMakeLists.txt`。
2. 补 `CMakePresets.json`。
3. 接入 `nanobind`。
4. 让 `hotools_native` 分别输出到 `_Lib/py311/HotoolsPackage` 和 `_Lib/py313/HotoolsPackage`。
5. 用 release workflow 生成面向 Blender 用户安装的干净 zip。
