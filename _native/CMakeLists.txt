cmake_minimum_required(VERSION 3.24)

project(hotools_native LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

get_filename_component(HOTOOLS_DEFAULT_PLUGIN_ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
set(HOTOOLS_PLUGIN_ROOT "${HOTOOLS_DEFAULT_PLUGIN_ROOT}" CACHE PATH "HoTools plugin root")
set(HOTOOLS_RUNTIME_DIR "${HOTOOLS_PLUGIN_ROOT}/_Lib/py311/HotoolsPackage" CACHE PATH "Runtime output directory")
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
# FetchContent 缓存目录（放在 _native/.fetch-cache/，清build目录不重新拉）
# ---------------------------------------------------------------------------
include(FetchContent)
set(FETCHCONTENT_BASE_DIR "${CMAKE_CURRENT_LIST_DIR}/.fetch-cache"
    CACHE PATH "FetchContent 源码缓存目录（build 目录无关）")

# ---------------------------------------------------------------------------
# nanobind：本地 extern/ 优先，无则 FetchContent
# ---------------------------------------------------------------------------
set(_nb_local "${CMAKE_CURRENT_LIST_DIR}/extern/nanobind")
if(EXISTS "${_nb_local}/CMakeLists.txt")
    message(STATUS "[HoTools] nanobind: 使用本地 extern/nanobind")
    add_subdirectory("${_nb_local}" nanobind EXCLUDE_FROM_ALL)
else()
    message(STATUS "[HoTools] nanobind: 从 GitHub 拉取（FetchContent，缓存到 .fetch-cache/）")
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
# ---------------------------------------------------------------------------
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
    message(STATUS "[HoTools] JoltPhysics: 使用本地 extern/JoltPhysics")
    add_subdirectory("${_jolt_local}/Build" JoltPhysics EXCLUDE_FROM_ALL)
else()
    message(STATUS "[HoTools] JoltPhysics: 从 GitHub 拉取（FetchContent，缓存到 .fetch-cache/）")
    set(HOTOOLS_JOLT_VERSION "5.2.0" CACHE STRING "JoltPhysics version tag")
    FetchContent_Declare(
        JoltPhysics
        GIT_REPOSITORY https://github.com/jrouwe/JoltPhysics.git
        GIT_TAG        v${HOTOOLS_JOLT_VERSION}
        GIT_SHALLOW    TRUE
        SOURCE_SUBDIR  Build
    )
    FetchContent_MakeAvailable(JoltPhysics)
endif()

# ---------------------------------------------------------------------------
# hotools_native CPython API module
# ---------------------------------------------------------------------------
nanobind_add_module(hotools_native
    NB_STATIC
    src/hotools_native.cpp
    src/mc2_context.cpp
    src/mc2_context_v0.cpp
    src/mc2.cpp
    src/mc2_bonecloth_io.cpp
    src/mc2_self_collision.cpp
    src/spring_bone_vrm.cpp
    src/spring_bone_vrm_bindings.cpp
    src/property_curve.cpp
)

target_include_directories(hotools_native PRIVATE
    "${CMAKE_CURRENT_LIST_DIR}/include"
)

target_compile_definitions(hotools_native PRIVATE PY_SSIZE_T_CLEAN)

if(MSVC)
    target_compile_options(hotools_native PRIVATE /W4 /permissive- /utf-8)
else()
    target_compile_options(hotools_native PRIVATE -Wall -Wextra -Wpedantic)
endif()

set_target_properties(hotools_native PROPERTIES
    PREFIX ""
    SUFFIX "${HOTOOLS_PYTHON_EXTENSION_SUFFIX}"
    RUNTIME_OUTPUT_DIRECTORY "${HOTOOLS_RUNTIME_DIR}"
    LIBRARY_OUTPUT_DIRECTORY "${HOTOOLS_RUNTIME_DIR}"
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib"
)

foreach(config DEBUG RELEASE RELWITHDEBINFO MINSIZEREL)
    set_target_properties(hotools_native PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY_${config} "${HOTOOLS_RUNTIME_DIR}"
        LIBRARY_OUTPUT_DIRECTORY_${config} "${HOTOOLS_RUNTIME_DIR}"
        ARCHIVE_OUTPUT_DIRECTORY_${config} "${CMAKE_BINARY_DIR}/lib"
    )
endforeach()

# ---------------------------------------------------------------------------
# hotools_jolt（nanobind 模块）
# ---------------------------------------------------------------------------
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
