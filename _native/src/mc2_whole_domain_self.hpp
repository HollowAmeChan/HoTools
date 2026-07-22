#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>

namespace hotools {

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

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace hotools
