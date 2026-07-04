# HoTools native 后端

`_native` 是 HoTools 的原生加速层，对应 `hotools_native` 扩展模块和 MC2 风格的核心求解管线。

这一层只处理数组、上下文、约束求解和碰撞内核，不直接碰 Blender 场景对象，也不自己挂全局刷新。Python 侧负责场景数据采集、缓存管理、节点状态同步和结果回写；C++ 侧负责高频数值计算。

## 目录

- `include/`：对外暴露的 C++ 头文件。
- `src/`：native 实现代码，包含求解器、上下文封装、碰撞内核和导出接口。
- `tests/`：native 回归测试和对拍测试。
- `build/`：CMake 生成目录，按 Python 版本和预设分开。

## 当前职责

- `hotools_native` 作为 Python 扩展入口，提供曲线编译/采样、MC2 求解、上下文创建与释放、各类约束投影接口。
- MC2 风格的上下文把静态拓扑、参数样本和运行时缓存拆开，减少每帧重复搬运。
- 自碰撞和碰撞内核持续补齐中，当前已经有统一网格 broadphase 的雏形，后续会继续补 contact 生命周期、去重和更完整的 narrowphase。
- 这一层不处理 Blender UI、Outliner、Handler 注册之类的东西，避免把场景刷新压力塞到 native 层。

## 设计分工

### Python 侧

- 负责读取 Blender 数据。
- 负责总缓存、节点缓存、参数缓存和脏标记。
- 负责把 Mesh、Bone、BasePose、Collider、Curve 等数据整理成连续数组。
- 负责把 native 结果写回对象、网格属性和节点缓存。

### C++ 侧

- 负责 MC2 约束迭代和数组级投影。
- 负责 point / edge / triangle / self-collision 等高频计算。
- 负责上下文内复用静态数据和参数数据，避免重复分配。
- 负责保持 ABI 稳定，字段顺序、数组形状和类型一旦改动，Python 侧必须同步更新。

## 构建

### 快速编译（推荐）

直接双击或在终端运行 `_native/build.bat`：

```bat
:: 编译 Blender 4.5 / py311（默认）
build.bat

:: 编译 Blender 5.x / py313
build.bat 313

:: 同时编译两个
build.bat all
```

脚本内部路径变量（如需修改直接编辑 build.bat 顶部）：

| 变量 | 当前值 |
|------|--------|
| `MSBUILD_EXE` | `D:\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe` |
| `BUILD_DIR_311` | `_native\build\vs2022-py311` |
| `BUILD_DIR_313` | `_native\build\vs2022-py313` |

### 环境说明

- **编译器**：Visual Studio 2022 Community，安装路径 `D:\Microsoft Visual Studio\2022\Community`
- **Blender 4.5 Python**：`D:/Blender/Blender 4.5/4.5/python/bin/python.exe`（py311）
- **Blender 5.x Python**：`D:/Blender/blender-5.1.0-windows-x64/5.1/python/bin/python.exe`（py313）

如果 VS 或 Blender 路径有变动：
1. 更新 `build.bat` 顶部的 `MSBUILD_EXE`
2. 更新 `CMakePresets.json` 里对应预设的 `HOTOOLS_PYTHON_EXECUTABLE`
3. 重新 configure：`cmake --preset vs2022-py311`，再用 build.bat 编译

### 手动 cmake 命令（首次初始化或重新 configure 时用）

```powershell
# 在 _native/ 目录下执行
cmake --preset vs2022-py311
cmake --build --preset vs2022-py311-release

cmake --preset vs2022-py313
cmake --build --preset vs2022-py313-release
```

### 产物路径

- `_Lib/py311/HotoolsPackage/hotools_native.cp311-win_amd64.pyd`
- `_Lib/py313/HotoolsPackage/hotools_native.cp313-win_amd64.pyd`

## 测试

测试脚本都在 `_native/tests/` 下，主要覆盖：

- `test_property_curve_native.py`
- `test_mesh_xpbd_native.py`
- `test_mc2_solver_core_native.py`
- `test_mc2_neighbor_native.py`
- `test_mc2_collision_native.py`
- `test_mc2_self_collision_native.py`
- `test_mc2_tether_native.py`
- `test_mc2_motion_native.py`
- `test_mc2_inertia_native.py`
- `test_mc2_angle_native.py`
- `test_mc2_triangle_bending_native.py`
- `test_mc2_display_native.py`
- `test_mc2_post_step_native.py`
- `test_mc2_baseline_native.py`
- `test_mc2_blender_scene_parity.py`

建议按“核心单元测试 -> 场景对拍”顺序跑，先确认 native 数值逻辑，再看 Blender 侧回写结果。

## 现状备注

- 旧版 README 里偏 XPBD 的说明已经不再代表当前主线，保留内容只作为历史参考。
- 当前主线以 MC2 管线为主，`solve_meshcloth_mc2`、`solve_meshcloth_mc2_context`、`solve_meshcloth_mc2_context_cached_params` 是主要入口。
- `project_self_collisions_mc2` 已接入自碰撞投影，后续重点仍然是减少卡住、穿插和重复 contact。

## 相关文档

- `OmniNode/doc/MC2_DESIGN_AND_WORKSHEET.md`
- `OmniNode/ARCHITECTURE.md`
