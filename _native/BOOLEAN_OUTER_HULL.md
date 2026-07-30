# HoTools exact outer-hull reconstruction

## What it does

`hotools_boolean.outer_hull()` computes the boundary adjacent to the unbounded
ambient cell of a self-intersecting triangle mesh. It locally remeshes exact
intersection curves, classifies the resulting volumetric cells, and discards
all faces that do not border the ambient cell. This removes both intersecting
internal sheets and completely enclosed cavity shells.

This is intentionally not CGAL's ordinary two-input mesh union. The
implementation instantiates libigl's `igl::copyleft::cgal::outer_hull`, whose
pipeline is:

1. `remesh_self_intersections` with CGAL exact predicates/constructions.
2. Stitch coincident vertices and extract cells from the resolved arrangement.
3. Keep only facets adjacent to cell 0, the unbounded ambient cell.
4. Return each output facet's source triangle and orientation.

References:

- https://libigl.github.io/dox/outer__hull_8h.html
- https://github.com/libigl/libigl/blob/v2.6.0/include/igl/copyleft/cgal/outer_hull.cpp
- https://doc.cgal.org/latest/Polygon_mesh_processing/index.html

## Non-triangle input

Blender performs a temporary tessellation through `Mesh.loop_triangles`. The
native call also receives the original polygon loops and the mapping from each
temporary triangle to its source polygon.

An original polygon is restored when every one of its temporary triangles:

- survives exactly once,
- contains no newly inserted intersection vertex, and
- has one consistent output orientation.

Therefore untouched quads and n-gons remain quads and n-gons. Only polygons
cut by the boolean intersection, or otherwise changed by cell extraction,
remain triangulated.

## Build and package size

Build Blender 4.5 / Python 3.11 independently:

```bat
_native\build.bat 311 boolean
```

The local build uses libigl v2.6.0, CGAL 6.0.1, Eigen, and Boost 1.86.0.
CGAL/libigl are template/header dependencies here; the source trees are build
inputs and are not copied into the addon. Only code reached by the single
`outer_hull()` instantiation is linked into `hotools_boolean.pyd`.

The verified Python 3.11 Release module is 1,117,696 bytes. Its PE imports are
limited to Python, Windows, and the MSVC/UCRT runtimes. GMP and MPFR are not
runtime dependencies because `CGAL_CMAKE_EXACT_NT_BACKEND=BOOST_BACKEND` and
`CGAL_DISABLE_GMP=ON` are fixed in CMake.

If present, `_research/download/boost_1_86_0.tar.gz` is used as a checksum-
verified local archive. Otherwise libigl's normal Boost download recipe is
used.

## Blender compatibility

The target defines `_DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR` on MSVC. CGAL and
libigl use `std::mutex` in self-intersection handling; runtime initialization
is required inside Blender 4.5 because its bundled MSVC runtime and
`tbbmalloc_proxy` are incompatible with mutex objects constexpr-initialized by
newer MSVC headers.

The Blender operator preserves polygon material indices and smooth shading.
UV layers, color attributes, vertex weights, and shape keys are not currently
reconstructed on newly created intersection geometry.

## License

The `igl_copyleft::cgal` path is a copyleft dependency. Distributing the binary
requires compliance with libigl/CGAL's applicable open-source terms, or a CGAL
commercial license where appropriate. This must be resolved before shipping a
closed-source addon build.
