#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace hotools {

void mc2_optimize_triangle_direction(
    const double* positions,
    std::size_t vertex_count,
    std::int32_t* triangles,
    std::size_t triangle_count,
    double* triangle_normals
);

struct Mc2MeshFinalProxyDerived {
    std::vector<double> local_normals;
    std::vector<double> local_tangents;
    std::vector<std::uint8_t> vertex_attributes;
    std::vector<std::int32_t> edges;
    std::vector<std::int32_t> vertex_to_vertex_ranges;
    std::vector<std::int32_t> vertex_to_vertex_data;
    std::vector<std::int32_t> vertex_to_triangle_ranges;
    std::vector<std::int32_t> vertex_to_triangle_data;
    std::vector<double> bind_positions;
    std::vector<double> bind_rotations;
};

Mc2MeshFinalProxyDerived mc2_build_mesh_final_proxy_derived(
    const double* positions,
    const double* local_normals,
    const double* local_tangents,
    const double* uvs,
    const std::uint8_t* vertex_attributes,
    std::size_t vertex_count,
    const std::int32_t* triangles,
    const double* triangle_normals,
    std::size_t triangle_count,
    const std::int32_t* lines,
    std::size_t line_count
);

}  // namespace hotools
