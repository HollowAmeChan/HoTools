#include "mc2_whole_domain_self.hpp"

#include "mc2_context_helpers.hpp"
#include "mc2_context_internal.hpp"

#include <memory>

namespace hotools {

struct Mc2WholeDomainSelfEngine::Impl {
    mc2_internal::Mc2ContextV0 context;
};

Mc2WholeDomainSelfEngine::Mc2WholeDomainSelfEngine()
    : impl_(std::make_unique<Impl>()) {}

Mc2WholeDomainSelfEngine::~Mc2WholeDomainSelfEngine() = default;

void Mc2WholeDomainSelfEngine::configure(
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
) {
    mc2_internal::configure_whole_domain_self_engine(
        impl_->context,
        vertex_count,
        points,
        point_count,
        edges,
        edge_count,
        triangles,
        triangle_count,
        particle_partition_indices,
        particle_attribute_flags,
        partition_self_collision_modes,
        partition_collision_groups,
        partition_collision_masks,
        partition_count
    );
}

void Mc2WholeDomainSelfEngine::solve(
    float* positions,
    const float* old_positions,
    const float* particle_thickness,
    const float* particle_friction,
    const float* particle_cloth_mass,
    std::int64_t frame,
    std::int64_t generation,
    std::int64_t& candidate_count,
    std::int64_t& contact_count
) {
    mc2_internal::solve_whole_domain_self_engine(
        impl_->context,
        positions,
        old_positions,
        particle_thickness,
        particle_friction,
        particle_cloth_mass,
        frame,
        generation,
        candidate_count,
        contact_count
    );
}

}  // namespace hotools
