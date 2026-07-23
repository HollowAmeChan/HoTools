#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

namespace hotools {

struct Mc2WholeDomainSelfDebugSnapshot {
    std::int64_t frame = -1;
    std::int64_t generation = -1;
    std::int64_t point_primitive_count = 0;
    std::int64_t edge_primitive_count = 0;
    std::int64_t triangle_primitive_count = 0;
    std::int64_t point_grid_count = 0;
    std::int64_t edge_grid_count = 0;
    std::int64_t triangle_grid_count = 0;
    float max_primitive_size = 0.0f;
    float grid_size = 0.0f;
    std::vector<std::uint32_t> primitive_flags;
    std::vector<std::int32_t> particle_indices;
    std::vector<float> primitive_depths;
    std::vector<float> inverse_masses;
    std::vector<float> aabb_min;
    std::vector<float> aabb_max;
    std::vector<float> thickness;
    std::vector<std::int32_t> owner_indices;
    std::vector<std::int32_t> owner_group_bits;
    std::vector<std::int32_t> owner_collision_masks;
    std::vector<std::int32_t> primitive_grids;
    std::vector<std::int32_t> grid_hashes;
    std::vector<std::int32_t> grid_starts;
    std::vector<std::int32_t> grid_counts;
    std::vector<std::int32_t> candidates;
    std::vector<std::int32_t> contact_indices;
    std::vector<std::int32_t> contact_types;
    std::vector<std::uint8_t> contact_enabled;
    std::vector<float> contact_thickness;
    std::vector<float> contact_s;
    std::vector<float> contact_t;
    std::vector<float> contact_normals;
    std::vector<float> contact_corrections;
    std::vector<std::int32_t> intersect_records;
};

class Mc2WholeDomainSelfEngine {
public:
    Mc2WholeDomainSelfEngine();
    ~Mc2WholeDomainSelfEngine();

    Mc2WholeDomainSelfEngine(const Mc2WholeDomainSelfEngine&) = delete;
    Mc2WholeDomainSelfEngine& operator=(const Mc2WholeDomainSelfEngine&) = delete;

    void configure(
        std::size_t vertex_count,
        const std::int32_t* points,
        std::size_t point_count,
        const std::int32_t* edges,
        std::size_t edge_count,
        const std::int32_t* triangles,
        std::size_t triangle_count,
        const std::uint32_t* particle_partition_indices,
        const std::uint32_t* particle_attribute_flags,
        const std::uint32_t* partition_self_collision_modes,
        const std::uint32_t* partition_collision_groups,
        const std::uint32_t* partition_collision_masks,
        std::size_t partition_count
    );

    void solve(
        float* positions,
        const float* old_positions,
        const float* particle_thickness,
        const float* particle_friction,
        const float* particle_cloth_mass,
        std::int64_t frame,
        std::int64_t generation,
        std::int64_t& candidate_count,
        std::int64_t& contact_count
    );

    void request_debug_capture();
    void invalidate_history() noexcept;
    void clear_debug_capture() noexcept;
    bool debug_capture_ready() const noexcept;
    const Mc2WholeDomainSelfDebugSnapshot& debug_snapshot() const noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace hotools
