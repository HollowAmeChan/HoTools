#pragma once

#include <cstdint>

namespace hotools {

struct Mc2NeighborConstraintView {
    float* positions = nullptr;
    const float* inv_masses = nullptr;
    const std::int32_t* starts = nullptr;
    const std::int32_t* counts = nullptr;
    const std::int32_t* neighbors = nullptr;
    const float* rest_lengths = nullptr;
    const float* stiffness_values = nullptr;
    float* velocity_positions = nullptr;
    std::int64_t vertex_count = 0;
    std::int64_t neighbor_count = 0;
    float velocity_attenuation = 0.0f;
};

struct Mc2TetherConstraintView {
    float* positions = nullptr;
    const float* inv_masses = nullptr;
    const std::int32_t* root_indices = nullptr;
    const float* root_rest_lengths = nullptr;
    float* velocity_positions = nullptr;
    std::int64_t vertex_count = 0;
    float stiffness = 0.0f;
    float compression = 0.0f;
    float stretch = 0.0f;
};

struct Mc2MotionConstraintView {
    float* positions = nullptr;
    const float* base_positions = nullptr;
    const float* base_normals = nullptr;
    const float* inv_masses = nullptr;
    const float* max_distances = nullptr;
    const float* stiffness_values = nullptr;
    const float* backstop_radii = nullptr;
    const float* backstop_distances = nullptr;
    float* velocity_positions = nullptr;
    std::int64_t vertex_count = 0;
};

struct Mc2PostStepView {
    float* positions = nullptr;
    float* old_positions = nullptr;
    float* velocity_positions = nullptr;
    float* velocities = nullptr;
    float* real_velocities = nullptr;
    float* friction = nullptr;
    float* static_friction = nullptr;
    const float* collision_normals = nullptr;
    const float* inv_masses = nullptr;
    std::int64_t vertex_count = 0;
    float step_dt = 0.0f;
    float dynamic_friction = 0.0f;
    float static_friction_speed = 0.0f;
    float particle_speed_limit = -1.0f;
};

struct Mc2CollisionView {
    float* positions = nullptr;
    const float* base_positions = nullptr;
    const float* inv_masses = nullptr;
    const float* collision_radii = nullptr;
    float* collision_normals = nullptr;
    float* friction = nullptr;
    const std::int32_t* collider_types = nullptr;
    const std::int32_t* collider_group_bits = nullptr;
    const float* collider_centers = nullptr;
    const float* collider_segment_a = nullptr;
    const float* collider_segment_b = nullptr;
    const float* collider_radii = nullptr;
    std::int64_t vertex_count = 0;
    std::int64_t collider_count = 0;
    std::int32_t collided_by_groups = 0;
};

void project_neighbor_constraints_mc2(Mc2NeighborConstraintView& view);
void project_tether_mc2(Mc2TetherConstraintView& view);
void project_motion_constraints_mc2(Mc2MotionConstraintView& view);
void apply_post_step_mc2(Mc2PostStepView& view);
void project_collisions_mc2(Mc2CollisionView& view);

}  // namespace hotools
