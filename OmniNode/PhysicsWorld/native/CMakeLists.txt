cmake_minimum_required(VERSION 3.24)

project(hotools_physics LANGUAGES CXX)

# ---------------------------------------------------------------------------
# HoTools-Omninode-Physics 原生工程
#
# 产出两个 Python 扩展模块（自持 pyd，不写入父仓 HoTools/_Lib）：
#   hotools_physics  MC2 / Field / XPBD / SpringVRM / RigidWriteback 内核
#   hotools_jolt     Jolt Physics 刚体/约束后端（含 Blender 兼容补丁）
#
# 产物落点：<本目录>/runtime/<abi>/，由 __init__ 侧 native.py 的解析顺序优先加载。
# 本工程与父仓 _native 工程完全独立；两者不共享构建目录。
# ---------------------------------------------------------------------------

option(HOTOOLS_PHYSICS_BUILD_PHYSICS "Build the hotools_physics extension" ON)
option(HOTOOLS_PHYSICS_BUILD_JOLT "Build the hotools_jolt extension" ON)
option(HOTOOLS_PHYSICS_BUILD_JOLT_THREAD_PROBE "Build the standalone Jolt thread-pool probe" OFF)
option(HOTOOLS_PHYSICS_BUILD_JOLT_THREADPOOL_EXPERIMENT "Build an isolated threaded hotools_jolt pyd" OFF)
if(NOT HOTOOLS_PHYSICS_BUILD_PHYSICS AND NOT HOTOOLS_PHYSICS_BUILD_JOLT)
    message(FATAL_ERROR "At least one physics native extension must be enabled")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

get_filename_component(HOTOOLS_PHYSICS_ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
set(HOTOOLS_RUNTIME_DIR "${HOTOOLS_PHYSICS_ROOT}/native/runtime/py311" CACHE PATH "Runtime output directory (python ABI specific)")
set(HOTOOLS_PYTHON_EXECUTABLE "" CACHE FILEPATH "Blender Python executable")

if(HOTOOLS_PYTHON_EXECUTABLE)
    set(Python3_EXECUTABLE "${HOTOOLS_PYTHON_EXECUTABLE}" CACHE FILEPATH "Python executable" FORCE)
endif()

find_package(Python3 REQUIRED COMPONENTS Interpreter Development.Module)

# 用 Python3 查找结果指引无版本号的 find_package(Python)，确保它也走 Blender Python。
# 这样 Python::Module 在顶层全局作用域创建，FetchContent 子作用域里的 nanobind
# 看到 Python::Module 后直接跳过自己的 find_package，generate 阶段也能正确解析。
if(Python3_FOUND)
    set(Python_EXECUTABLE    "${Python3_EXECUTABLE}"   CACHE FILEPATH "" FORCE)
    set(Python_INCLUDE_DIR   "${Python3_INCLUDE_DIRS}" CACHE PATH     "" FORCE)
    if(Python3_LIBRARIES)
        set(Python_LIBRARY         "${Python3_LIBRARIES}" CACHE FILEPATH "" FORCE)
        set(Python_LIBRARY_RELEASE "${Python3_LIBRARIES}" CACHE FILEPATH "" FORCE)
    endif()
    set(Python_FIND_REGISTRY  NEVER CACHE STRING "" FORCE)
    set(Python_FIND_FRAMEWORK NEVER CACHE STRING "" FORCE)
endif()

# 在顶层调用，确保 Python::Module 在全局作用域注册（而不是在 FetchContent 子作用域）
find_package(Python 3.8 REQUIRED COMPONENTS Interpreter Development.Module
    OPTIONAL_COMPONENTS Development.SABIModule)

execute_process(
    COMMAND "${Python3_EXECUTABLE}" -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX') or '.pyd', end='')"
    OUTPUT_VARIABLE HOTOOLS_PYTHON_EXTENSION_SUFFIX
    RESULT_VARIABLE HOTOOLS_EXTENSION_SUFFIX_RESULT
)
if(NOT HOTOOLS_EXTENSION_SUFFIX_RESULT EQUAL 0 OR NOT HOTOOLS_PYTHON_EXTENSION_SUFFIX)
    set(HOTOOLS_PYTHON_EXTENSION_SUFFIX ".pyd")
endif()

# ---------------------------------------------------------------------------
# FetchContent 缓存目录
#
# 默认放在本工程 .fetch-cache/ 下，清 build 目录不会重新拉依赖。
# 若希望与父仓 _native/.fetch-cache/ 共用 nanobind 源码（省一次下载），
# 配置时传 -DHOTOOLS_PHYSICS_FETCH_CACHE=<父仓>/_native/.fetch-cache 即可。
# build/ 目录**不可**共用：CMake 生成物内含绝对路径，target 名也会冲突。
# ---------------------------------------------------------------------------
include(FetchContent)

set(HOTOOLS_PHYSICS_FETCH_CACHE "${CMAKE_CURRENT_LIST_DIR}/.fetch-cache"
    CACHE PATH "FetchContent 源码缓存目录（可指向父仓 _native/.fetch-cache 复用 nanobind）")
set(FETCHCONTENT_BASE_DIR "${HOTOOLS_PHYSICS_FETCH_CACHE}"
    CACHE PATH "FetchContent 源码缓存目录（build 目录无关）" FORCE)

# Reuse extracted dependency sources after build directories are cleaned or
# caches are moved. FetchContent otherwise stores absolute paths in its
# generated subbuild metadata, making that metadata non-portable.
foreach(_hotools_dependency nanobind joltphysics)
    string(TOUPPER "${_hotools_dependency}" _hotools_dependency_upper)
    set(_hotools_dependency_source
        "${FETCHCONTENT_BASE_DIR}/${_hotools_dependency}-src")
    if(EXISTS "${_hotools_dependency_source}")
        set(
            FETCHCONTENT_SOURCE_DIR_${_hotools_dependency_upper}
            "${_hotools_dependency_source}"
            CACHE PATH "Local extracted ${_hotools_dependency} source" FORCE
        )
    endif()
endforeach()

# ---------------------------------------------------------------------------
# nanobind：本地 extern/ 优先，无则 FetchContent
# ---------------------------------------------------------------------------
set(_nb_local "${CMAKE_CURRENT_LIST_DIR}/extern/nanobind")
if(EXISTS "${_nb_local}/CMakeLists.txt")
    message(STATUS "[HoToolsPhysics] nanobind: 使用本地 extern/nanobind")
    add_subdirectory("${_nb_local}" nanobind EXCLUDE_FROM_ALL)
else()
    message(STATUS "[HoToolsPhysics] nanobind: 从 GitHub 拉取（FetchContent，缓存到 .fetch-cache/）")
    FetchContent_Declare(
        nanobind
        GIT_REPOSITORY https://github.com/wjakob/nanobind.git
        GIT_TAG        v2.2.0
        GIT_SHALLOW    TRUE
    )
    FetchContent_MakeAvailable(nanobind)
endif()

# ---------------------------------------------------------------------------
# JoltPhysics：本地 extern/ 优先，无则 FetchContent
#
# Blender 进程中 tbbmalloc_proxy.dll 会破坏 MSVCP140.dll 的 TLS 状态，
# 任何 std::mutex::lock() 都会经 Mtx_trylock → Thrd_yield 访问非法 TLS 崩溃。
# 因此把 Jolt 的 Mutex.h 在 Windows 下替换为 Win32 CRITICAL_SECTION / SRWLOCK。
# ---------------------------------------------------------------------------
function(hotools_patch_jolt_mutex _jolt_root)
    set(_mutex_header "${_jolt_root}/Jolt/Core/Mutex.h")
    if(NOT EXISTS "${_mutex_header}")
        message(FATAL_ERROR "[HoToolsPhysics] Jolt Mutex.h not found: ${_mutex_header}")
    endif()

    file(READ "${_mutex_header}" _mutex_text)
    string(REPLACE "\r\n" "\n" _mutex_text "${_mutex_text}")
    string(FIND "${_mutex_text}" "HoTools patch: Blender loads tbbmalloc_proxy.dll" _patch_index)
    if(NOT _patch_index EQUAL -1)
        return()
    endif()

    set(_mutex_needle "#else\n\n// On other platforms just use the STL implementation")
    set(_mutex_replacement [=[#elif defined(_WIN32)

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

// On other platforms just use the STL implementation]=])
    string(FIND "${_mutex_text}" "${_mutex_needle}" _needle_index)
    if(_needle_index EQUAL -1)
        message(FATAL_ERROR "[HoToolsPhysics] Unsupported Jolt Mutex.h layout; refusing an unpatched Blender build")
    endif()

    string(REPLACE "${_mutex_needle}" "${_mutex_replacement}" _mutex_text "${_mutex_text}")
    file(WRITE "${_mutex_header}" "${_mutex_text}")
    message(STATUS "[HoToolsPhysics] Applied Blender-safe Jolt Mutex.h patch")
endfunction()

if(HOTOOLS_PHYSICS_BUILD_JOLT)
    set(_jolt_local "${CMAKE_CURRENT_LIST_DIR}/extern/JoltPhysics")
    set(BUILD_SHARED_LIBS              OFF CACHE BOOL "" FORCE)
    set(GENERATE_DEBUG_SYMBOLS         OFF CACHE BOOL "" FORCE)
    set(OVERRIDE_CXX_FLAGS             OFF CACHE BOOL "" FORCE)
    # Python 扩展必须用 /MD（动态CRT）；告诉 Jolt 不要用 /MT（静态CRT）
    set(USE_STATIC_MSVC_RUNTIME_LIBRARY OFF CACHE BOOL "" FORCE)
    # Python 调用栈不保证 32 字节对齐，禁用 AVX/AVX2 避免 vmovaps 崩溃
    set(USE_AVX2  OFF CACHE BOOL "" FORCE)
    set(USE_AVX   OFF CACHE BOOL "" FORCE)
    # Blender 进程中 tbbmalloc_proxy 干扰 MSVCP140 的 std::mutex 初始化。
    # Jolt Profiler（JPH_PROFILE_ENABLED）和 DebugRenderer（JPH_DEBUG_RENDERER）
    # 均包含 std::mutex 成员，PhysicsSystem::Init() 首次锁该 mutex 时
    # 触发 Mtx_trylock → Thrd_yield → EXCEPTION_ACCESS_VIOLATION。
    # Jolt 的实际选项名为 PROFILER_IN_DEBUG_AND_RELEASE / DEBUG_RENDERER_IN_DEBUG_AND_RELEASE。
    set(PROFILER_IN_DEBUG_AND_RELEASE    OFF CACHE BOOL "" FORCE)
    set(DEBUG_RENDERER_IN_DEBUG_AND_RELEASE OFF CACHE BOOL "" FORCE)

    if(EXISTS "${_jolt_local}/Build/CMakeLists.txt")
        message(STATUS "[HoToolsPhysics] JoltPhysics: 使用本地 extern/JoltPhysics")
        hotools_patch_jolt_mutex("${_jolt_local}")
        add_subdirectory("${_jolt_local}/Build" JoltPhysics EXCLUDE_FROM_ALL)
    else()
        message(STATUS "[HoToolsPhysics] JoltPhysics: 从 GitHub 拉取（FetchContent，缓存到 .fetch-cache/）")
        set(HOTOOLS_JOLT_VERSION "5.2.0" CACHE STRING "JoltPhysics version tag")
        FetchContent_Declare(
            JoltPhysics
            GIT_REPOSITORY https://github.com/jrouwe/JoltPhysics.git
            GIT_TAG        v${HOTOOLS_JOLT_VERSION}
            GIT_SHALLOW    TRUE
            SOURCE_SUBDIR  Build
        )
        FetchContent_MakeAvailable(JoltPhysics)
        get_filename_component(_jolt_fetched_root "${JoltPhysics_SOURCE_DIR}/.." ABSOLUTE)
        hotools_patch_jolt_mutex("${_jolt_fetched_root}")
    endif()
endif()

# 所有物理目标共同包含的头文件目录（python_buffer_utils.hpp 等）。
set(HOTOOLS_PHYSICS_PUBLIC_INCLUDE "${CMAKE_CURRENT_LIST_DIR}/include")

# ---------------------------------------------------------------------------
# hotools_physics：MC2 / Field / XPBD / SpringVRM / RigidWriteback
# ---------------------------------------------------------------------------
if(HOTOOLS_PHYSICS_BUILD_PHYSICS)
nanobind_add_module(hotools_physics
    NB_STATIC
    src/hotools_physics.cpp
    src/field/field_runtime.cpp
    src/field/field_runtime.hpp
    src/field/field_runtime_bindings.cpp
    src/field/field_runtime_bindings.hpp
    src/mc2/mc2_bindings.cpp
    src/mc2/mc2_fingerprint.cpp
    src/mc2/mc2_frame_orientations.cpp
    src/mc2/mc2_static_build.cpp
    src/mc2/mc2_kernels.cpp
    src/mc2/mc2_self_collision.cpp
    src/mc2/mc2_whole_domain_self.cpp
    src/mc2/mc2_domain_cpu.cpp
    src/mc2/mc2_domain_cpu_bindings.cpp
    src/mc2/mc2_domain_cpu.hpp
    src/mc2/mc2_frame_orientations.hpp
    src/mc2/mc2_kernels.hpp
    src/mc2/mc2_whole_domain_self.hpp
    src/xpbd/mesh_xpbd.cpp
    src/xpbd/mesh_xpbd_bindings.cpp
    src/xpbd/mesh_xpbd_bindings.hpp
    src/spring_vrm/spring_bone_vrm.cpp
    src/spring_vrm/spring_bone_vrm_bindings.cpp
    src/rigid_writeback.cpp
    src/rigid_writeback.hpp
)

# These translation units construct shared native view structs. Keep their
# object files tied to the headers so ABI/layout edits cannot leave a stale
# producer paired with a freshly compiled kernel consumer.
set_source_files_properties(
    src/mc2/mc2_frame_orientations.cpp
    src/mc2/mc2_kernels.cpp
    src/mc2/mc2_domain_cpu.cpp
    src/mc2/mc2_domain_cpu_bindings.cpp
    PROPERTIES OBJECT_DEPENDS
        "${CMAKE_CURRENT_LIST_DIR}/src/field/field_runtime.hpp;${CMAKE_CURRENT_LIST_DIR}/src/mc2/mc2_domain_cpu.hpp;${CMAKE_CURRENT_LIST_DIR}/src/mc2/mc2_frame_orientations.hpp;${CMAKE_CURRENT_LIST_DIR}/src/mc2/mc2_kernels.hpp"
)

set_source_files_properties(
    src/field/field_runtime.cpp
    src/field/field_runtime_bindings.cpp
    PROPERTIES OBJECT_DEPENDS
        "${CMAKE_CURRENT_LIST_DIR}/src/field/field_runtime.hpp;${CMAKE_CURRENT_LIST_DIR}/src/field/field_runtime_bindings.hpp"
)

# Context 类布局由公共头文件定义；实现与 nanobind 必须作为同一 ABI 批次重编译。
set_source_files_properties(
    src/xpbd/mesh_xpbd.cpp
    src/xpbd/mesh_xpbd_bindings.cpp
    PROPERTIES OBJECT_DEPENDS
        "${CMAKE_CURRENT_LIST_DIR}/include/hotools_mesh_xpbd.hpp;${CMAKE_CURRENT_LIST_DIR}/src/xpbd/mesh_xpbd_bindings.hpp"
)

target_include_directories(hotools_physics PRIVATE
    "${CMAKE_CURRENT_LIST_DIR}/src"
    "${CMAKE_CURRENT_LIST_DIR}/src/field"
    "${CMAKE_CURRENT_LIST_DIR}/src/mc2"
    "${CMAKE_CURRENT_LIST_DIR}/src/xpbd"
    "${CMAKE_CURRENT_LIST_DIR}/src/spring_vrm"
    "${CMAKE_CURRENT_LIST_DIR}/include"
)

target_compile_definitions(
    hotools_physics
    PRIVATE
        PY_SSIZE_T_CLEAN
)

if(MSVC)
    target_compile_options(hotools_physics PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(hotools_physics PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(hotools_mesh_xpbd_core_test EXCLUDE_FROM_ALL
    tests/test_mesh_xpbd_core.cpp
    src/xpbd/mesh_xpbd.cpp
)
target_include_directories(hotools_mesh_xpbd_core_test PRIVATE
    "${CMAKE_CURRENT_LIST_DIR}/src/xpbd"
    "${CMAKE_CURRENT_LIST_DIR}/include"
)
if(MSVC)
    target_compile_options(hotools_mesh_xpbd_core_test PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(hotools_mesh_xpbd_core_test PRIVATE -Wall -Wextra -Wpedantic)
endif()

set_target_properties(hotools_physics PROPERTIES
    PREFIX ""
    SUFFIX "${HOTOOLS_PYTHON_EXTENSION_SUFFIX}"
    RUNTIME_OUTPUT_DIRECTORY "${HOTOOLS_RUNTIME_DIR}"
    LIBRARY_OUTPUT_DIRECTORY "${HOTOOLS_RUNTIME_DIR}"
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib"
)

foreach(config DEBUG RELEASE RELWITHDEBINFO MINSIZEREL)
    set_target_properties(hotools_physics PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY_${config} "${HOTOOLS_RUNTIME_DIR}"
        LIBRARY_OUTPUT_DIRECTORY_${config} "${HOTOOLS_RUNTIME_DIR}"
        ARCHIVE_OUTPUT_DIRECTORY_${config} "${CMAKE_BINARY_DIR}/lib"
    )
endforeach()
endif()

# ---------------------------------------------------------------------------
# hotools_jolt（nanobind 模块）
# ---------------------------------------------------------------------------
if(HOTOOLS_PHYSICS_BUILD_JOLT)
nanobind_add_module(hotools_jolt
    NB_STATIC
    src/jolt_rigid.cpp
)

target_include_directories(hotools_jolt PRIVATE
    "${CMAKE_CURRENT_LIST_DIR}/include"
)

target_link_libraries(hotools_jolt PRIVATE Jolt)

if(MSVC)
    target_compile_options(hotools_jolt PRIVATE /utf-8 /permissive-)
else()
    target_compile_options(hotools_jolt PRIVATE -frtti -fexceptions)
endif()

set_target_properties(hotools_jolt PROPERTIES
    PREFIX ""
    SUFFIX "${HOTOOLS_PYTHON_EXTENSION_SUFFIX}"
    RUNTIME_OUTPUT_DIRECTORY "${HOTOOLS_RUNTIME_DIR}"
    LIBRARY_OUTPUT_DIRECTORY "${HOTOOLS_RUNTIME_DIR}"
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib"
)

foreach(config DEBUG RELEASE RELWITHDEBINFO MINSIZEREL)
    set_target_properties(hotools_jolt PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY_${config} "${HOTOOLS_RUNTIME_DIR}"
        LIBRARY_OUTPUT_DIRECTORY_${config} "${HOTOOLS_RUNTIME_DIR}"
        ARCHIVE_OUTPUT_DIRECTORY_${config} "${CMAKE_BINARY_DIR}/lib"
    )
endforeach()
endif()

# ---------------------------------------------------------------------------
# 独立 Jolt 线程池探针：不链接 Python/nanobind，也不覆盖运行时 pyd。
# 只有显式开启 HOTOOLS_PHYSICS_BUILD_JOLT_THREAD_PROBE 时才生成。
# ---------------------------------------------------------------------------
if(HOTOOLS_PHYSICS_BUILD_JOLT AND HOTOOLS_PHYSICS_BUILD_JOLT_THREAD_PROBE)
add_executable(hotools_jolt_thread_probe
    tests/test_jolt_thread_pool.cpp
)
target_link_libraries(hotools_jolt_thread_probe PRIVATE Jolt)
if(MSVC)
    target_compile_options(hotools_jolt_thread_probe PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(hotools_jolt_thread_probe PRIVATE -Wall -Wextra -Wpedantic)
endif()
endif()

# ---------------------------------------------------------------------------
# 隔离 pyd 实验：输出到 build 目录，不覆盖运行时 pyd；线程数由 JoltWorld.worker_threads 控制。
# ---------------------------------------------------------------------------
if(HOTOOLS_PHYSICS_BUILD_JOLT AND HOTOOLS_PHYSICS_BUILD_JOLT_THREADPOOL_EXPERIMENT)
nanobind_add_module(hotools_jolt_threadpool_experiment
    NB_STATIC
    src/jolt_rigid.cpp
)
target_include_directories(hotools_jolt_threadpool_experiment PRIVATE
    "${CMAKE_CURRENT_LIST_DIR}/include"
)
target_link_libraries(hotools_jolt_threadpool_experiment PRIVATE Jolt)
if(MSVC)
    target_compile_options(hotools_jolt_threadpool_experiment PRIVATE /utf-8 /permissive-)
else()
    target_compile_options(hotools_jolt_threadpool_experiment PRIVATE -frtti -fexceptions)
endif()
set_target_properties(hotools_jolt_threadpool_experiment PROPERTIES
    PREFIX ""
    OUTPUT_NAME "hotools_jolt"
    SUFFIX "${HOTOOLS_PYTHON_EXTENSION_SUFFIX}"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/threadpool-experiment"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/threadpool-experiment"
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib"
)
endif()
