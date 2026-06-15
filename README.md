# HoTools

反馈 QQ 群：1017402879。进群问题请填写自己的 B 站昵称，问题和建议尽量在群里集中反馈。

本人 B 站：空洞 Hollow，相关教程会发布在空间：

```text
https://space.bilibili.com/60340452
```

插件文档：

```text
https://hollowamechan.github.io/HotoolsDoc-Quartz/
```

文档不定期更新，最新功能通常会先在群内快速演示。

## 安装说明

Release 页面里上传的 `HoTools-*.zip` 是给 Blender 用户安装的干净插件包。安装时使用这个 zip，不要优先使用 GitHub 自动生成的 `Source code (zip)` / `Source code (tar.gz)`。

如果下载的是 GitHub 自动生成的源码压缩包，需要确认解压后的主目录名是 `HoTools`，否则 Blender 无法按插件包名正常加载。

如果某个 Release 版本出现严重问题，可以临时回退到至少前一天的版本。

## 当前 native 后端规划状态

仓库正在搭建新的 C++ / nanobind 原生后端流程，目前还只是目录、发布和加载路径的架子，并不是已经完成 C++ solver。

第一阶段目标是把 `MeshShapeKeyXPBD` 节点里最耗时的 XPBD solve 阶段移动到 C++，Python 侧继续负责 Blender 数据读取、cache 管理、shape key 写回和 OmniNode 接口。

这里参考的是 HoCloth 已经跑通的发布流程和 native 构建分层，不是迁移 HoCloth 的业务代码。

## 本机路径

当前机器上已经确认存在的工具路径如下。

```powershell
$Repo = "C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"

$Blender = "D:\Blender\Blender 4.5\blender.exe"
$BlenderPython311 = "D:\Blender\Blender 4.5\4.5\python\bin\python.exe"

$VsDevCmd = "D:\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat"
$MSBuild = "D:\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe"
$CMake = "D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
```

注意事项：

- 编译 Blender 可加载的 `.pyd` 时，不要依赖系统默认 `python` 或 `py -3.11`。
- Blender 4.5 使用 Python 3.11 ABI，所以 3.11 产物必须用 Blender 自带 Python 路径参与配置。
- 后续如果支持 Blender 5.1+ / Python 3.13，需要再补对应的 Blender Python 3.13 路径和构建 preset。

## Python 版本和产物目录

HoTools 已经按 Python 版本划分第三方依赖目录：

```text
_Lib/
  py311/
  py313/
```

native runtime 不直接混放在 `py311` 或 `py313` 根目录，统一放到单独的 `HotoolsPackage` 子目录：

```text
_Lib/py311/HotoolsPackage/
_Lib/py313/HotoolsPackage/
```

约定：

- `_Lib/py311/HotoolsPackage` 放 Blender 4.1+ / Python 3.11 ABI 的 native 产物。
- `_Lib/py313/HotoolsPackage` 放 Blender 5.1+ / Python 3.13 ABI 的 native 产物。
- `HotoolsPackage` 目录只放运行时需要的 `.pyd`、`.dll`、必要的 `.pdb` 等文件。
- CMake / Visual Studio / Ninja 的中间产物不放进 `HotoolsPackage`。

典型产物示例：

```text
_Lib/py311/HotoolsPackage/hotools_native.cp311-win_amd64.pyd
_Lib/py313/HotoolsPackage/hotools_native.cp313-win_amd64.pyd
```

插件启动时，[`__init__.py`](./__init__.py) 会按当前 Python 版本把对应的 `HotoolsPackage` 插入到 `sys.path` 前面，因此 Python 代码可以稳定：

```python
import hotools_native
```

## 目录约定

```text
HoTools/
  _Lib/
    py311/
      HotoolsPackage/       Python 3.11 native runtime
    py313/
      HotoolsPackage/       Python 3.13 native runtime
  _native/
    include/                C++ 头文件
    src/                    C++ / nanobind 实现
    tests/                  smoke test / benchmark
    build/                  本地 CMake 构建目录，不提交
  _build/                   本地 staging 或临时构建目录，不提交
  _dist/                    本地临时输出目录，不提交
```

核心规则：

- `_native` 是 C++ 开发工程目录。
- `_Lib/*/HotoolsPackage` 是 Blender 运行时加载目录。
- Release zip 需要包含 `_Lib/*/HotoolsPackage` 里的最终运行时产物。
- Release zip 不应该包含 `_native`、`.github`、`.git`、`.vscode`、`.vs`、`_build`、`_dist`、`build`、`cmake-build-*` 等开发目录。

## nanobind 绑定架构

建议拆成三层，避免 C++ 层直接依赖 Blender API。

### 1. Python 节点层

主要位置：

```text
OmniNode/NodeTree/Function/Physics.py
```

职责：

- 校验 Blender mesh object、shape key、pin group、frame continuity。
- 用 `foreach_get` 批量读取 Basis / shape key 坐标。
- 维护 runtime cache，例如 `positions`、`prev_positions`、`inv_masses`、约束数组。
- 优先调用 C++ solver，native 不可用时回退 Python solver。
- 用 `foreach_set` 批量写回目标 shape key。

Python 层负责和 `bpy` 交互，C++ 层不要保存 Blender 对象指针，也不要直接访问 `bpy`。

### 2. nanobind 桥接层

建议模块名：

```text
hotools_native
```

建议第一阶段只暴露窄接口，例如：

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

数据约定：

- `positions` / `prev_positions` 使用 `float32`，shape 为 `(vertex_count, 3)`。
- `inv_masses` 使用 `float32`，shape 为 `(vertex_count,)`。
- 约束索引使用 `int32`。
- rest length 使用 `float32`。
- C++ 原地更新 `positions` 和 `prev_positions`。
- C++ 不保存全局 solver 状态，所有跨帧状态由 Python cache 管理。

### 3. C++ solver 层

职责：

- prediction。
- pin 修正。
- stretch distance constraint。
- bend distance constraint。
- substep / iteration 循环。
- smoke test / benchmark。

第一阶段重点是迁移 solve 热点，而不是重写整个节点系统。

## 构建流程

目前还没有正式的 `CMakeLists.txt` / `CMakePresets.json`。补齐以后，手动编译流程建议按下面的方式执行。

### 1. 打开 VS 构建环境

```powershell
cmd /k "D:\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" -arch=x64
```

也可以直接在 PowerShell 里显式调用 VS 自带 CMake，避免依赖 PATH。

### 2. 配置 Python 3.11 构建

```powershell
cd "C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"

& "D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" `
  -S "_native" `
  -B "_native\build\vs2022-py311" `
  -G "Visual Studio 17 2022" `
  -A x64 `
  -T v143 `
  -DHOTOOLS_PLUGIN_ROOT="$PWD" `
  -DHOTOOLS_PYTHON_EXECUTABLE="D:\Blender\Blender 4.5\4.5\python\bin\python.exe" `
  -DHOTOOLS_RUNTIME_DIR="$PWD\_Lib\py311\HotoolsPackage"
```

### 3. 编译 Python 3.11 产物

```powershell
& "D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" `
  --build "_native\build\vs2022-py311" `
  --config Release
```

编译完成后，目标产物应该出现在：

```text
_Lib/py311/HotoolsPackage/
```

### 4. 配置 Python 3.13 构建

等本机准备好 Blender 5.1+ / Python 3.13 后，再使用同样流程配置 3.13：

```powershell
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

```powershell
& "D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" `
  --build "_native\build\vs2022-py313" `
  --config Release
```

## 导入验证

Python 3.11：

```powershell
& "D:\Blender\Blender 4.5\4.5\python\bin\python.exe" -c "import sys; sys.path.insert(0, r'C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools\_Lib\py311\HotoolsPackage'); import hotools_native; print(hotools_native)"
```

Python 3.13 同理，把 Python 路径和 `HotoolsPackage` 路径切到 `_Lib\py313\HotoolsPackage`。

## 发布流程

发布给用户安装的包由 GitHub Actions workflow 生成，不用开发者手动在本机压缩。

当前约定：

1. 本机或 CI 先把 native 最终运行时产物放入 `_Lib/py311/HotoolsPackage`、`_Lib/py313/HotoolsPackage`。
2. GitHub Actions 创建一个临时 `HoTools/` staging 目录。
3. workflow 用 `rsync` 复制仓库内容，同时排除 `.git`、`.github`、IDE 目录、Python 缓存、CMake 构建目录、`_native` 源码目录等开发内容。
4. workflow 把 staging 后的 `HoTools/` 压缩成 `HoTools-YYYYMMDD-HHMMSS.zip`。
5. workflow 创建 GitHub Release 并上传这个 zip。

Release 页面仍会显示 GitHub 自动生成的 `Source code (zip)` 和 `Source code (tar.gz)`，但那两个不是面向 Blender 用户安装的干净包。用户安装应下载 workflow 上传的 `HoTools-*.zip`。

## gitignore 和发布包关系

`.gitignore` 只决定哪些本地文件默认不进入 Git，不等于发布 zip 的排除规则。

发布 zip 的排除规则在：

```text
.github/workflows/release.yml
```

因此需要同时满足两件事：

- 开发期中间产物通过 `.gitignore` 排除，避免误提交。
- 用户安装包通过 `release.yml` 的 `rsync --exclude` 排除开发目录，避免 zip 里带上不必要文件。

`HotoolsPackage` 目录里后续如果放入真正需要发布的 `.pyd` / `.dll`，必须确保它们没有被 `.gitignore` 排除，并且能被 release workflow 复制进安装包。

## 本地清理

清理开发期构建缓存：

```powershell
Remove-Item -LiteralPath "_native\build" -Recurse -Force
Remove-Item -LiteralPath "_build" -Recurse -Force
Remove-Item -LiteralPath "_dist" -Recurse -Force
```

不要清理 `_Lib/py311/HotoolsPackage` 和 `_Lib/py313/HotoolsPackage` 里的正式运行时产物，除非你确定要重新编译替换。

## 下一步

当前还只是流程架子，后续开发顺序建议：

1. 在 `_native` 下补 `CMakeLists.txt`。
2. 补 `CMakePresets.json` 或等价的 PowerShell 构建脚本。
3. 接入 nanobind。
4. 先实现最小 `hotools_native` 导入 smoke test。
5. 再迁移 `MeshShapeKeyXPBD` 的 XPBD solve 核心。
6. 最后把 workflow 的发布 zip 规则和真实产物再跑一轮验证。
