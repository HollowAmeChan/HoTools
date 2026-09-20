# `hotools_jolt` Blender 兼容约束

本文记录仍然影响构建、升级和运行时设计的长期约束。历史崩溃调查、手工编辑生成工程和逐次修复过程只保留在 Git；当前构建不得要求开发者修改 `build/` 下的 Jolt 源码、CMake cache 或 `.vcxproj`。

## 资源导航

- 永久构建配置：`_native/CMakeLists.txt`
- 构建入口：`_native/build.bat`
- CMake presets：`_native/CMakePresets.json`
- Jolt binding：`_native/src/jolt_rigid.cpp`
- Native 回归：`_native/tests/test_jolt_rigid_native.py`
- 三层语义测试：`OmniNode/PhysicsWorld/rigid/test/`
- 测试策略：`OmniNode/PhysicsWorld/rigid/docs/JOLT_TEST_STRATEGY.md`
- 产品路线：`OmniNode/doc/JOLT_PHYSICS_BACKGROUND_ANALYSIS.md`
- 固定 Jolt 版本：`5.2.0`

Jolt 源码优先来自 `_native/extern/JoltPhysics`，否则由 FetchContent 放入 `_native/.fetch-cache` / build 依赖目录。生成目录不是永久修改源。

## 已确认的 Blender 进程边界

在目标 Windows Blender 进程中，早期集成曾稳定复现以下调用栈：

```text
hotools_jolt.pyd
  -> MSVCP140 Mtx_trylock / Thrd_yield
  -> EXCEPTION_ACCESS_VIOLATION
```

独立 Blender Python 进程正常，而加载完整 Blender 后失败；项目内调查把它定位到 Blender 的 `tbbmalloc_proxy.dll`、MSVC runtime TLS 与 STL thread primitive 的组合。HoTools 因此把以下约束视为产品事实，而不是每次升级重新碰运气：

- Jolt Windows `Mutex` / `SharedMutex` 使用 Win32 `CRITICAL_SECTION` / `SRWLOCK` patch。
- Jolt Profiler 和 DebugRenderer 在 extension 构建中关闭。
- 初始化不使用 `std::call_once`；binding 使用原子状态完成 Jolt 全局注册。
- 模块加载时预热 Win32 critical section，再初始化 Jolt types。
- Jolt extension 关闭 AVX/AVX2，并使用与 Python extension 一致的动态 CRT。

这些约束不表示整个项目永远不能使用多线程。当前 `JoltWorld` 已支持 `JobSystemSingleThreaded` 和 Jolt 原生 `JobSystemThreadPool`；线程池内部使用的是上述已修补的 Jolt 同步原语。新增独立 registry、worker 或异步任务仍需单独通过 Blender 进程测试，不能推断普通 `std::mutex` 自动安全。

## 自动化所有权

| 约束 | 永久 owner | 行为 |
|---|---|---|
| Win32 Jolt mutex patch | `_native/CMakeLists.txt::hotools_patch_jolt_mutex` | 配置阶段幂等应用；Jolt 源布局不匹配时直接失败 |
| Profiler / DebugRenderer | `_native/CMakeLists.txt` cache options | 在添加 Jolt target 前强制关闭 |
| AVX / AVX2 | `_native/CMakeLists.txt` | Jolt extension 构建强制关闭 |
| 动态 CRT | `_native/CMakeLists.txt` | extension 与 Blender Python ABI 保持一致 |
| 全局初始化 | `_native/src/jolt_rigid.cpp` | 原子状态、幂等注册、模块加载时执行 |
| 线程策略 | `JoltWorld` constructor | `worker_threads=0` 单线程，正数为 Jolt thread pool |

禁止恢复以下旧流程：

- 手工改 `build/*/CMakeCache.txt`；
- 注释 FetchContent 中的 `Jolt.cmake`；
- 手工删除 `.vcxproj` 宏；
- 把 patch 直接提交到 `build/*/_deps/joltphysics-src`；
- 用一次成功的独立 Python import 替代 Blender 进程验证。

若自动 patch 失效，正确修复是更新 `hotools_patch_jolt_mutex()` 对固定 Jolt 版本的布局识别并增加配置测试，不是恢复生成目录手工步骤。

## 构建

在 `_native/` 下使用模块化构建：

```bat
build.bat 311 jolt
build.bat 313 jolt
```

产物：

```text
_Lib/py311/HotoolsPackage/hotools_jolt.cp311-win_amd64.pyd
_Lib/py313/HotoolsPackage/hotools_jolt.cp313-win_amd64.pyd
```

需要重新 configure 时使用 `CMakePresets.json` 中的 `vs2022-py311-jolt` / `vs2022-py313-jolt`。普通增量实现改动不需要手工操作 Jolt 工程。

## 验证门槛

兼容性改动至少验证：

1. py311 与 py313 `hotools_jolt` 可在目标 Blender 进程 import、构造和 dispose。
2. 单线程与至少一个正数 `worker_threads` 的 world 可创建、step 和清理。
3. Native rigid 回归和三层 semantic fixture 通过。
4. Blender background smoke 覆盖 body、contact、constraint 和 world rebuild。
5. 插件 unregister、load/undo、Cache Delete 和 world replacement 后没有仍运行的 Jolt job 或陈旧 handle。

独立 Python 测试只覆盖 ABI/binding，不覆盖 Blender allocator、已加载 DLL、frame handler 或 depsgraph 环境。

## 升级 Jolt

升级固定版本时按以下顺序：

1. 审核 `Jolt/Core/Mutex.h` 布局和 patch 命中；不匹配必须配置失败。
2. 审核 Profiler、DebugRenderer、CRT、SIMD 和 job system 选项名是否变化。
3. 双 ABI clean configure/build，不复用旧 Jolt object files。
4. 运行单线程/线程池 Blender smoke、完整 semantic/golden、soak 和性能门禁。
5. 只有上述结果通过后更新本页版本与产品文档；不要在文档中追加升级流水账。
