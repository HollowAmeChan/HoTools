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

struct Mc2MeshBaselineDerived {
    std::vector<std::uint8_t> vertex_attributes;
    std::vector<std::int32_t> parent_indices;
    std::vector<std::int32_t> child_ranges;
    std::vector<std::int32_t> child_data;
    std::vector<std::uint8_t> baseline_flags;
    std::vector<std::int32_t> baseline_ranges;
    std::vector<std::int32_t> baseline_data;
    std::vector<std::int32_t> root_indices;
    std::vector<double> depths;
    std::vector<double> vertex_local_positions;
    std::vector<double> vertex_local_rotations;
};

struct Mc2BaselinePoseDepthDerived {
    std::vector<std::uint8_t> vertex_attributes;
    std::vector<std::int32_t> root_indices;
    std::vector<double> depths;
    std::vector<double> vertex_local_positions;
    std::vector<double> vertex_local_rotations;
};

Mc2BaselinePoseDepthDerived mc2_build_baseline_pose_depth_derived(
    const double* positions,
    const double* local_normals,
    const double* local_tangents,
    const std::uint8_t* vertex_attributes,
    const std::int32_t* parent_indices,
    std::size_t vertex_count,
    const std::int32_t* baseline_data,
    std::size_t baseline_data_count
);

Mc2MeshBaselineDerived mc2_build_mesh_baseline_derived(
    const double* positions,
    const double* local_normals,
    const double* local_tangents,
    const std::uint8_t* vertex_attributes,
    std::size_t vertex_count,
    const std::int32_t* edges,
    std::size_t edge_count
);

struct Mc2DistanceDerived {
    std::vector<std::int32_t> ranges;
    std::vector<std::int32_t> targets;
    std::vector<float> rest_signed;
};

Mc2DistanceDerived mc2_build_distance_derived(
    const double* positions,
    const std::uint8_t* vertex_attributes,
    const std::int32_t* parent_indices,
    std::size_t vertex_count,
    const std::int32_t* edges,
    std::size_t edge_count,
    const std::int32_t* triangles,
    std::size_t triangle_count,
    const std::int32_t* adjacency_ranges,
    const std::int32_t* adjacency_data,
    std::size_t adjacency_data_count
);

struct Mc2BendingDerived {
    std::vector<std::int32_t> quads;
    std::vector<float> rest_angle_or_volume;
    std::vector<std::int8_t> sign_or_volume;
};

Mc2BendingDerived mc2_build_bending_derived(
    const float* positions,
    const std::uint8_t* vertex_attributes,
    std::size_t vertex_count,
    const std::int32_t* edges,
    std::size_t edge_count,
    const std::int32_t* triangles,
    std::size_t triangle_count,
    const float* initial_local_to_world_columns
);

}  // namespace hotools
