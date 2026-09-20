#pragma once

#include <cstddef>
#include <cstdint>

namespace hotools {

struct Mc2MeshFrameOrientationView {
    std::size_t vertex_count = 0;
    const float* positions = nullptr;
    const std::int32_t* triangles = nullptr;
    std::size_t triangle_count = 0;
    const float* proxy_uvs = nullptr;
    std::size_t proxy_uv_count = 0;
    const float* triangle_uvs = nullptr;
    std::size_t triangle_uv_count = 0;
    const std::int32_t* triangle_ranges = nullptr;
    std::size_t triangle_range_count = 0;
    const std::int32_t* triangle_records = nullptr;
    std::size_t triangle_record_count = 0;
    const float* normal_adjustment_rotations = nullptr;
    float* output_rotations = nullptr;
};

bool derive_mesh_frame_orientations(const Mc2MeshFrameOrientationView& view);

bool derive_bone_frame_orientations(
    const float* matrix_values,
    const float* component_rotation_values,
    const float* vertex_to_transform_values,
    std::size_t vertex_count,
    float* output_values,
    const char* matrix_name
);

}  // namespace hotools
