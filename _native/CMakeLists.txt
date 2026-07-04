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

execute_process(
    COMMAND "${Python3_EXECUTABLE}" -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX') or '.pyd', end='')"
    OUTPUT_VARIABLE HOTOOLS_PYTHON_EXTENSION_SUFFIX
    RESULT_VARIABLE HOTOOLS_EXTENSION_SUFFIX_RESULT
)
if(NOT HOTOOLS_EXTENSION_SUFFIX_RESULT EQUAL 0 OR NOT HOTOOLS_PYTHON_EXTENSION_SUFFIX)
    set(HOTOOLS_PYTHON_EXTENSION_SUFFIX ".pyd")
endif()

add_library(hotools_native MODULE
    src/hotools_native.cpp
    src/mc2_context.cpp
    src/mc2.cpp
    src/mc2_bonecloth_io.cpp
    src/mc2_self_collision.cpp
    src/mesh_xpbd.cpp
    src/spring_bone_vrm.cpp
    src/spring_bone_vrm_bindings.cpp
    src/property_curve.cpp
)

target_include_directories(hotools_native PRIVATE
    "${CMAKE_CURRENT_LIST_DIR}/include"
)

target_link_libraries(hotools_native PRIVATE Python3::Module)
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
