# hotools_jolt — Blender 兼容性踩坑记录

> 本文档记录将 Jolt Physics 集成进 Blender 插件（nanobind .pyd）时遇到的所有崩溃问题、根本原因及修复方案。
> 每次清空 build 目录重新配置后，**必须重新应用这些 patch**。

---

## 崩溃现象

- Blender 里调用任何 `hotools_jolt` 相关节点时，Blender 直接闪退
- 错误码：`EXCEPTION_ACCESS_VIOLATION`，崩溃模块：`MSVCP140.dll`
- 调用栈：`hotools_jolt.pyd → Mtx_trylock → Thrd_yield → 崩溃`
- 独立 Python（`D:\Blender\Blender 4.5\4.5\python\bin\python.exe`）里完全正常

---

## 根本原因

### tbbmalloc_proxy.dll 破坏 MSVCP140 TLS

Blender 4.5 在进程启动时加载了 `tbbmalloc_proxy.dll`（Intel TBB 内存代理）。  
该 DLL 在 **我们的 .pyd 加载之前** 就已经替换了进程级别的全局 `malloc/free/new/delete`。  
这一替换操作破坏了 `MSVCP140.dll` 的 **TLS（线程本地存储）初始化状态**。

后果：`std::mutex::lock()` 在 MSVCP140 里的实现路径为：

```
std::mutex::lock()
  → _Mtx_lock() / Mtx_trylock()     [MSVCP140 内部，spin 等待时调用 yield]
    → Thrd_yield()                   [访问已损坏的 TLS]
      → EXCEPTION_ACCESS_VIOLATION   [读取 NULL 指针]
```

**受影响的所有 MSVCP140 STL 类型：**
- `std::mutex` — 直接崩溃
- `std::shared_mutex` — 同上
- `std::call_once` / `std::once_flag` — 内部使用 mutex，同上
- `std::this_thread::get_id()` — 使用 TLS，在 assert 里调用时崩溃
- `std::this_thread::yield()` — 同 `Thrd_yield`，直接崩溃

---

## 修复清单

### 修复 1：Jolt Mutex.h — 替换为 Win32 原生实现 ⚠️ 最关键

**文件：** `_native/build/vs2022-py311/_deps/joltphysics-src/Jolt/Core/Mutex.h`  
（py313 同理：`_native/build/vs2022-py313/_deps/joltphysics-src/Jolt/Core/Mutex.h`）

在 `#ifdef JPH_PLATFORM_BLUE` 的 `#else` 分支前，插入 `#elif defined(_WIN32)` 块：

```cpp
#elif defined(_WIN32)

// HoTools patch: Blender loads tbbmalloc_proxy.dll which corrupts MSVCP140.dll TLS state.
// Any std::mutex::lock() call crashes via Mtx_trylock -> Thrd_yield accessing invalid TLS.
// Use Win32 CRITICAL_SECTION (Mutex) and SRWLOCK (SharedMutex) to bypass MSVCP140 entirely.
#ifndef WIN32_LEAN_AND_MEAN
#  define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

class MutexBase : public NonCopyable
{
public:
    MutexBase()                             { InitializeCriticalSection(&mCS); }
    ~MutexBase()                            { DeleteCriticalSection(&mCS); }
    inline void     lock()                  { EnterCriticalSection(&mCS); }
    inline bool     try_lock()              { return TryEnterCriticalSection(&mCS) != 0; }
    inline void     unlock()               { LeaveCriticalSection(&mCS); }
private:
    CRITICAL_SECTION mCS;
};

class SharedMutexBase : public NonCopyable
{
public:
    SharedMutexBase()                       { mSRW = SRWLOCK_INIT; }
    inline void     lock()                  { AcquireSRWLockExclusive(&mSRW); }
    inline bool     try_lock()              { return TryAcquireSRWLockExclusive(&mSRW) != 0; }
    inline void     unlock()               { ReleaseSRWLockExclusive(&mSRW); }
    inline void     lock_shared()           { AcquireSRWLockShared(&mSRW); }
    inline bool     try_lock_shared()       { return TryAcquireSRWLockShared(&mSRW) != 0; }
    inline void     unlock_shared()         { ReleaseSRWLockShared(&mSRW); }
private:
    SRWLOCK         mSRW;
};

#else
```

> **注意：** 注释必须用英文。Jolt 的 `.vcxproj` 没有 `/utf-8` 选项，中文注释在代码页 936 下
> 会触发 warning C4819（视为 error）导致编译失败。

**为什么有效：** `CRITICAL_SECTION` 和 `SRWLOCK` 是 Win32 内核原语，完全不经过 MSVCP140，不涉及 TLS。

---

### 修复 2：CMakeLists.txt — 禁用 Profiler 和 DebugRenderer

**文件：** `_native/CMakeLists.txt`

在 Jolt `add_subdirectory` 之前加入：

```cmake
# Blender 进程中 tbbmalloc_proxy 干扰 MSVCP140 的 std::mutex 初始化。
# Profiler（Profiler::mLock）和 DebugRenderer 均包含 std::mutex 成员，
# PhysicsSystem::Init() 首次锁该 mutex 时会崩溃。
# Jolt 的实际选项名：PROFILER_IN_DEBUG_AND_RELEASE / DEBUG_RENDERER_IN_DEBUG_AND_RELEASE
set(PROFILER_IN_DEBUG_AND_RELEASE       OFF CACHE BOOL "" FORCE)
set(DEBUG_RENDERER_IN_DEBUG_AND_RELEASE OFF CACHE BOOL "" FORCE)
```

> **注意：** cmake CACHE 机制复杂，仅修改 CMakeLists.txt 不够——还需要手动编辑
> `build/vs2022-py311/CMakeCache.txt`（见下方流程），并注释掉 `Jolt.cmake` 里的
> 对应 `target_compile_definitions` 行（因为 cmake 不会重新生成 vcxproj）。

---

### 修复 3：jolt_rigid.cpp — 替换 std::call_once 为 std::atomic

**文件：** `_native/src/jolt_rigid.cpp`

```cpp
// 不使用 std::call_once / std::once_flag（内部依赖 MSVCP140 mutex，在 Blender 里崩溃）
// 改用 lock-free atomic：0=未初始化 1=初始化中 2=已完成
static std::atomic<int> g_jolt_init_state{0};

static void ensure_jolt_initialized() {
    if (g_jolt_init_state.load(std::memory_order_acquire) == 2)
        return;
    int expected = 0;
    if (g_jolt_init_state.compare_exchange_strong(
            expected, 1, std::memory_order_acq_rel)) {
        RegisterDefaultAllocator();
        Factory::sInstance = new Factory();
        RegisterTypes();
        g_jolt_init_state.store(2, std::memory_order_release);
    } else {
        while (g_jolt_init_state.load(std::memory_order_acquire) < 2) {}
    }
}
```

在 `NB_MODULE` 里提前调用（不要等到 JoltWorld 构造时）：

```cpp
NB_MODULE(hotools_jolt, m) {
#ifdef _WIN32
    // tbbmalloc_proxy warmup: ensure Win32 thread primitives are initialized
    {
        CRITICAL_SECTION cs;
        InitializeCriticalSection(&cs);
        EnterCriticalSection(&cs);
        LeaveCriticalSection(&cs);
        DeleteCriticalSection(&cs);
    }
#endif
    ensure_jolt_initialized();
    // ... 注册类 ...
}
```

---

## ⚠️ 重建流程（清空 build 目录后）

每次 `cmake --preset` 重新配置后，**fetch-cache 里的 Jolt 源码会被重新下载/解压**，
所有手动 patch 都会丢失。必须按以下顺序重新应用：

### 第 1 步：cmake 配置

```powershell
$cmake = 'D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
$src   = 'C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools\_native'
& $cmake --preset vs2022-py311 -S $src
& $cmake --preset vs2022-py313 -S $src
```

### 第 2 步：修改 CMakeCache.txt（两个 build 目录各一次）

```
build/vs2022-py311/CMakeCache.txt
build/vs2022-py313/CMakeCache.txt
```

将以下两行从 `ON` 改为 `OFF`：

```
DEBUG_RENDERER_IN_DEBUG_AND_RELEASE:BOOL=OFF
PROFILER_IN_DEBUG_AND_RELEASE:BOOL=OFF
```

### 第 3 步：注释掉 Jolt.cmake 里的 compile_definitions（两份各操作）

**文件：** `build/vs2022-py311/_deps/joltphysics-src/Jolt/Jolt.cmake`（第 572–583 行附近）

```cmake
# Enable the debug renderer
if (DEBUG_RENDERER_IN_DISTRIBUTION)
    # target_compile_definitions(Jolt PUBLIC "JPH_DEBUG_RENDERER")  # HoTools: disabled
elseif (DEBUG_RENDERER_IN_DEBUG_AND_RELEASE)
    # target_compile_definitions(...)  # HoTools: disabled
endif()

# Enable the profiler
if (PROFILER_IN_DISTRIBUTION)
    # target_compile_definitions(Jolt PUBLIC "JPH_PROFILE_ENABLED")  # HoTools: disabled
elseif (PROFILER_IN_DEBUG_AND_RELEASE)
    # target_compile_definitions(...)  # HoTools: disabled
endif()
```

### 第 4 步：应用 Mutex.h patch（两份各操作）

按修复 1 的说明修改 `Mutex.h`。

### 第 5 步：从 Jolt.vcxproj 里删除 JPH_PROFILE_ENABLED / JPH_DEBUG_RENDERER 宏

用 Python 脚本（见下方）或手动删除两个 vcxproj 里 `PreprocessorDefinitions` 中的这两个宏。

```python
import re
files = [
    r"build\vs2022-py311\hotools_jolt.vcxproj",
    r"build\vs2022-py311\_deps\joltphysics-build\Jolt.vcxproj",
    r"build\vs2022-py313\hotools_jolt.vcxproj",
    r"build\vs2022-py313\_deps\joltphysics-build\Jolt.vcxproj",
]
for path in files:
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    content = re.sub(r';JPH_PROFILE_ENABLED(?=;|")', '', content)
    content = re.sub(r';JPH_DEBUG_RENDERER(?=;|")', '', content)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Updated:", path)
```

### 第 6 步：全量重编

```powershell
$msbuild = 'D:\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe'

# 先全量重编 Jolt.lib（因为 Mutex.h 是头文件，需要 /t:Rebuild）
& $msbuild "build\vs2022-py311\_deps\joltphysics-build\Jolt.vcxproj" /p:Configuration=Release /p:Platform=x64 /v:minimal /m /t:Rebuild
& $msbuild "build\vs2022-py313\_deps\joltphysics-build\Jolt.vcxproj" /p:Configuration=Release /p:Platform=x64 /v:minimal /m /t:Rebuild

# 再编译 hotools_jolt.pyd
& $msbuild "build\vs2022-py311\hotools_jolt.vcxproj" /p:Configuration=Release /p:Platform=x64 /v:minimal /m
& $msbuild "build\vs2022-py313\hotools_jolt.vcxproj" /p:Configuration=Release /p:Platform=x64 /v:minimal /m
```

---

## 测试验证

无头 Blender 运行测试脚本（位于插件根目录）：

```bat
"D:\Blender\Blender 4.5\blender.exe" --background --python _test_jolt_headless.py
```

期望输出（最后几行）：

```
[TEST] JoltWorld OK: <hotools_jolt.JoltWorld object at 0x...>
[TEST] add_body OK, handle = 1
[TEST] step OK, X.XXX ms
[TEST] body pos after 1 step: [0.0, 4.9973, 0.0]
[TEST] 全部通过！
```

---

## 其他踩坑

### AVX2 导致崩溃

Python 调用栈不保证 32 字节对齐，`vmovaps` 指令对不对齐的内存读写会触发 `EXCEPTION_ILLEGAL_INSTRUCTION`。

**修复：** `CMakeLists.txt` 中：

```cmake
set(USE_AVX2 OFF CACHE BOOL "" FORCE)
set(USE_AVX  OFF CACHE BOOL "" FORCE)
```

### HoTools import 路径错误

`physicsWorld/rigid/nodes.py` 原来有 `from ..solver import step_rigid_bodies`（双点），
应为 `from .solver import step_rigid_bodies`（单点），因为 `solver.py` 就在 `rigid/` 目录下。

### build.bat 只编译 hotools_native

`build.bat` 调用的解决方案 `hotools_native.sln` 包含全部 target，但因为路径问题在某些
shell 环境下无输出。直接用 PowerShell + MSBuild 更可靠（见上方重编流程）。

### cmake 不重新生成 vcxproj

cmake 检测 Jolt 是 FetchContent 子目录时，对 `CMakeCache.txt` 的修改不会自动触发
vcxproj 重新生成。需要手动修改 vcxproj 里的 `PreprocessorDefinitions`（见步骤 5）。

---

## 文件改动速查

| 文件 | 改动类型 | 内容 |
|------|---------|------|
| `_native/CMakeLists.txt` | 永久 | 禁用 AVX2/AVX、Profiler、DebugRenderer |
| `_native/src/jolt_rigid.cpp` | 永久 | lock-free init、Win32 warmup、NB_MODULE 提前初始化 |
| `build/.../Jolt/Core/Mutex.h` | **每次重建后重新 patch** | Win32 CRITICAL_SECTION + SRWLOCK |
| `build/.../Jolt/Jolt.cmake` | **每次重建后重新 patch** | 注释掉 Profiler/DebugRenderer compile_definitions |
| `build/.../Jolt.vcxproj` | **每次重建后重新 patch** | 删除 JPH_PROFILE_ENABLED / JPH_DEBUG_RENDERER 宏 |
| `build/.../hotools_jolt.vcxproj` | **每次重建后重新 patch** | 同上 |
