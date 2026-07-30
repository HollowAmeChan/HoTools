# 布尔模块依赖压缩包

该目录用于存放可以重新下载的大型依赖压缩包，内容默认被 Git 忽略。运行
`_native/fetch_boolean_dependencies.ps1` 可以下载并校验 Boost 1.86.0。
CMake 检测到本地压缩包时优先使用；否则自动回退到 libigl 固定版本的
FetchContent 下载配方。

libigl、CGAL、Eigen、Boost 和 nanobind 解压后的源码统一放在
`_native/.fetch-cache`。该目录同样不进入 Git，并且独立于各个 CMake build 目录。
