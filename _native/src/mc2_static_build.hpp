#pragma once

#include <cstddef>
#include <cstdint>

namespace hotools {

void mc2_optimize_triangle_direction(
    const double* positions,
    std::size_t vertex_count,
    std::int32_t* triangles,
    std::size_t triangle_count,
    double* triangle_normals
);

}  // namespace hotools
