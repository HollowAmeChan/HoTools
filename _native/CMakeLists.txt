cmake_minimum_required(VERSION 3.24)

project(hotools_native LANGUAGES CXX)

option(HOTOOLS_BUILD_NATIVE "Build the hotools_native (PropertyCurve) extension" ON)
option(HOTOOLS_BUILD_BOOLEAN "Build the CGAL outer-hull extension" OFF)
if(NOT HOTOOLS_BUILD_NATIVE AND NOT HOTOOLS_BUILD_BOOLEAN)
    message(FATAL_ERROR "At least one native extension must be enabled")
endif()

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
    CACHE PATH "FetchContent 源码缓存目录（build 目录无关）" FORCE)

# Reuse extracted dependency sources after build directories are cleaned or
# caches are moved. FetchContent otherwise stores absolute paths in its
# generated subbuild metadata, making that metadata non-portable.
foreach(_hotools_dependency nanobind libigl cgal eigen boost)
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
# Exact outer-hull boolean dependencies. libigl and CGAL are header-only for
# this target, so only the templates reached by outer_hull() enter the module.
# GMP is disabled: Boost.Multiprecision keeps the .pyd self-contained.
# ---------------------------------------------------------------------------
if(HOTOOLS_BUILD_BOOLEAN)
    set(HOTOOLS_LIBIGL_VERSION "2.6.0" CACHE STRING
        "Pinned libigl version for the exact outer-hull module")
    set(HOTOOLS_BOOLEAN_BOOST_VERSION "1.86.0" CACHE STRING
        "Boost archive version pinned by libigl v2.6.0")
    set(HOTOOLS_BOOLEAN_BOOST_MD5 "ac857d73bb754b718a039830b07b9624"
        CACHE STRING "Expected Boost source archive MD5")
    set(LIBIGL_BUILD_TESTS OFF CACHE BOOL "" FORCE)
    set(LIBIGL_BUILD_TUTORIALS OFF CACHE BOOL "" FORCE)
    set(LIBIGL_INSTALL OFF CACHE BOOL "" FORCE)
    set(LIBIGL_USE_STATIC_LIBRARY OFF CACHE BOOL "" FORCE)
    set(LIBIGL_COPYLEFT_CGAL ON CACHE BOOL "" FORCE)
    set(LIBIGL_COPYLEFT_CORE OFF CACHE BOOL "" FORCE)
    set(LIBIGL_COPYLEFT_COMISO OFF CACHE BOOL "" FORCE)
    set(LIBIGL_COPYLEFT_TETGEN OFF CACHE BOOL "" FORCE)
    set(LIBIGL_RESTRICTED_MATLAB OFF CACHE BOOL "" FORCE)
    set(LIBIGL_RESTRICTED_MOSEK OFF CACHE BOOL "" FORCE)
    set(LIBIGL_RESTRICTED_TRIANGLE OFF CACHE BOOL "" FORCE)
    set(CGAL_CMAKE_EXACT_NT_BACKEND "BOOST_BACKEND" CACHE STRING "" FORCE)
    set(CGAL_DISABLE_GMP ON CACHE BOOL "" FORCE)

    set(_hotools_boost_archive
        "${CMAKE_CURRENT_LIST_DIR}/extern/archives/boost_1_86_0.tar.gz")
    if(EXISTS "${_hotools_boost_archive}")
        message(STATUS "[HoTools] Boost: using checksum-verified local archive")
        FetchContent_Declare(
            Boost
            URL "${_hotools_boost_archive}"
            URL_HASH MD5=${HOTOOLS_BOOLEAN_BOOST_MD5}
        )
    endif()

    FetchContent_Declare(
        libigl
        GIT_REPOSITORY https://github.com/libigl/libigl.git
        GIT_TAG        v${HOTOOLS_LIBIGL_VERSION}
        GIT_SHALLOW    TRUE
    )
    FetchContent_MakeAvailable(libigl)
endif()

# ---------------------------------------------------------------------------
# JoltPhysics 与物理世界原生模块已迁出本工程
#
# hotools_jolt 与 hotools_physics 由 OmniNode/PhysicsWorld/native/CMakeLists.txt
# 编译，产物落在该目录的 runtime/<abi>/ 下。Jolt 的 FetchContent 与
# Blender 兼容补丁（Mutex.h 替换为 Win32 CRITICAL_SECTION/SRWLOCK）也随之迁移。
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# hotools_native CPython API module
#
# 只包含 PropertyCurve（父仓贮藏内容）需要的采样内核。物理世界
# （MC2 / Field / XPBD / SpringVRM / RigidWriteback）的原生实现已迁至
# OmniNode/PhysicsWorld/native/，由该目录的独立 CMake 工程编译为
# hotools_physics（另有 hotools_jolt）；物理侧只是 PropertyCurve 的调用方。
# ---------------------------------------------------------------------------
if(HOTOOLS_BUILD_NATIVE)
nanobind_add_module(hotools_native
    NB_STATIC
    src/hotools_property_curve.cpp
    src/property_curve.cpp
)

target_include_directories(hotools_native PRIVATE
    "${CMAKE_CURRENT_LIST_DIR}/include"
)

target_compile_definitions(
    hotools_native
    PRIVATE
        PY_SSIZE_T_CLEAN
)

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
endif()

# ---------------------------------------------------------------------------
# hotools_boolean: isolated CGAL/libigl outer-hull module
# ---------------------------------------------------------------------------
if(HOTOOLS_BUILD_BOOLEAN)
nanobind_add_module(hotools_boolean
    NB_STATIC
    src/boolean_outer_hull.cpp
)

target_link_libraries(hotools_boolean PRIVATE igl_copyleft::cgal)
target_compile_definitions(
    hotools_boolean
    PRIVATE
        PY_SSIZE_T_CLEAN
        $<$<CXX_COMPILER_ID:MSVC>:_DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR>
)

if(MSVC)
    target_compile_options(hotools_boolean PRIVATE /W4 /permissive- /utf-8 /bigobj)
else()
    target_compile_options(hotools_boolean PRIVATE -Wall -Wextra -Wpedantic)
endif()

set_target_properties(hotools_boolean PROPERTIES
    PREFIX ""
    SUFFIX "${HOTOOLS_PYTHON_EXTENSION_SUFFIX}"
    RUNTIME_OUTPUT_DIRECTORY "${HOTOOLS_RUNTIME_DIR}"
    LIBRARY_OUTPUT_DIRECTORY "${HOTOOLS_RUNTIME_DIR}"
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib"
)

foreach(config DEBUG RELEASE RELWITHDEBINFO MINSIZEREL)
    set_target_properties(hotools_boolean PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY_${config} "${HOTOOLS_RUNTIME_DIR}"
        LIBRARY_OUTPUT_DIRECTORY_${config} "${HOTOOLS_RUNTIME_DIR}"
        ARCHIVE_OUTPUT_DIRECTORY_${config} "${CMAKE_BINARY_DIR}/lib"
    )
endforeach()
endif()

# ---------------------------------------------------------------------------
# hotools_jolt / hotools_physics / Jolt 线程池探针
#
# 以上目标全部已迁至 OmniNode/PhysicsWorld/native/CMakeLists.txt：
#   hotools_jolt                     物理世界 rigid 后端的 nanobind 绑定
#   hotools_physics                  MC2 / Field / XPBD / SpringVRM / RigidWriteback
#   hotools_jolt_thread_probe        独立线程池探针（不链接 Python）
#   hotools_jolt_threadpool_experiment  隔离线程数实验 pyd
# ---------------------------------------------------------------------------

