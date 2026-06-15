#pragma once

#include <cstdint>

namespace hotools {

struct MeshXpbdView {
    float* positions = nullptr;
    float* prev_positions = nullptr;
    const float* rest_positions = nullptr;
    const float* inv_masses = nullptr;
    std::int64_t vertex_count = 0;

    const std::int32_t* edge_i = nullptr;
    const std::int32_t* edge_j = nullptr;
    const float* edge_rest = nullptr;
    std::int64_t edge_count = 0;

    const std::int32_t* bend_i = nullptr;
    const std::int32_t* bend_j = nullptr;
    const float* bend_rest = nullptr;
    std::int64_t bend_count = 0;

    float gravity[3] = {0.0f, 0.0f, 0.0f};
    float dt = 0.0f;
    float damping = 0.0f;
    int substeps = 1;
    int iterations = 0;
    float stretch_compliance = 0.0f;
    float bend_compliance = 0.0f;
};

void solve_mesh_shape_key_xpbd(MeshXpbdView& view);

}  // namespace hotools
