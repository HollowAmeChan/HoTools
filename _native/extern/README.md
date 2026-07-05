# extern/ 目录存放 git submodule 依赖
#
# 初始化方式（在 _native/ 目录下执行）：
#
#   git submodule add --depth 1 https://github.com/wjakob/nanobind.git extern/nanobind
#   git submodule add --depth 1 https://github.com/jrouwe/JoltPhysics.git extern/JoltPhysics
#   git submodule update --init --recursive
#
# 或者在已有 .gitmodules 的情况下：
#   git submodule update --init --recursive --depth 1
#
# IDE 头文件引用：
#   extern/nanobind/include/
#   extern/JoltPhysics/Jolt/
#
# cmake 在检测到本地目录时直接 add_subdirectory，
# 不存在时自动 FetchContent（见 CMakeLists.txt）。
