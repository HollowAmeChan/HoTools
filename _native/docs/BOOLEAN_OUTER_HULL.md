# HoTools 精确外壳重构

## 功能说明

`hotools_boolean.outer_hull()` 用于计算自相交三角网格中与无限外部空间相邻的边界。
算法会精确切分局部交线、对产生的空间单元进行分类，并删除所有不与无限外部空间
相邻的面。因此，相交物体内部的面和完全封闭的内部空腔都会被删除。

这里使用的不是 CGAL 常规的双输入网格并集，而是 libigl 的
`igl::copyleft::cgal::outer_hull`。其主要流程如下：

1. 使用 CGAL 精确谓词和精确构造执行 `remesh_self_intersections`。
2. 缝合重合顶点，从切分后的网格排列中提取空间单元。
3. 仅保留与编号 0 的无限外部单元相邻的面片。
4. 返回每个输出面片对应的输入三角面及其朝向变化。

参考资料：

- https://libigl.github.io/dox/outer__hull_8h.html
- https://github.com/libigl/libigl/blob/v2.6.0/include/igl/copyleft/cgal/outer_hull.cpp
- https://doc.cgal.org/latest/Polygon_mesh_processing/index.html

## 非三角面输入

Blender 通过 `Mesh.loop_triangles` 对原始多边形进行临时三角化。原生模块同时接收
原始多边形顶点环，以及每个临时三角面到原始多边形的来源映射。

一个原始多边形只有在其全部临时三角面满足以下条件时才会被恢复：

- 每个临时三角面在输出中恰好保留一次；
- 没有插入新的交点顶点；
- 所有临时三角面的输出朝向一致。

因此，未被交线影响的四边面和 n-gon 会保持原始拓扑。只有被布尔交线切割、或在
空间单元提取过程中发生变化的区域才会保留为三角面。

## 构建与包体

单独构建 Blender 4.5 / Python 3.11 版本：

```bat
_native\build.bat 311 boolean
```

当前固定使用 libigl v2.6.0、CGAL 6.0.1、Eigen 5.0.1 和 Boost 1.86.0。
CGAL 和 libigl 在这里属于模板/头文件依赖，源码目录只参与编译，不会复制到插件发布包。
最终二进制只包含 `outer_hull()` 这条调用路径实际实例化的代码。

已经验证的 Python 3.11 Release 模块大小为 1,117,184 字节。PE 导入表只包含
Python、Windows 和 MSVC/UCRT 运行库。CMake 固定设置
`CGAL_CMAKE_EXACT_NT_BACKEND=BOOST_BACKEND` 和 `CGAL_DISABLE_GMP=ON`，
因此运行时不依赖 GMP 或 MPFR DLL。

依赖版本和获取方式都在 `CMakeLists.txt` 中显式声明。FetchContent 下载的源码统一
存放在 `_native/.fetch-cache`，不依赖具体 build 目录。全新克隆可以先执行：

```powershell
powershell -ExecutionPolicy Bypass -File _native\fetch_boolean_dependencies.ps1
```

该脚本会把体积较大的 Boost 1.86.0 压缩包下载到
`_native/extern/archives`，并校验 MD5。若本地没有该压缩包，CMake 仍会使用
libigl 固定版本中的下载配方作为自动回退。libigl v2.6.0 的 CMake 配方固定了
CGAL 6.0.1、Eigen 5.0.1 和 Boost 1.86.0。

## Blender 兼容处理

MSVC 构建会定义 `_DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR`。CGAL/libigl 的自交处理
使用了 `std::mutex`；Blender 4.5 自带的 MSVC 运行库和 `tbbmalloc_proxy` 与新版
MSVC 头文件生成的 constexpr mutex 初始化方式不兼容，因此必须改用运行时初始化。

当前 Blender 操作器会保留多边形材质索引和平滑设置。新生成的交线几何暂不重建
UV、颜色属性、顶点权重和形态键。

## 许可证

`igl_copyleft::cgal` 属于 copyleft 依赖路径。分发二进制时必须遵守 libigl/CGAL
对应的开源许可证，或者在适用情况下取得 CGAL 商业许可证。闭源插件正式发布前必须
先解决这一许可证问题。
