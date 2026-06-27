#pragma once

#include <cstdint>

namespace hotools {

struct SpringBoneVrmChainView {
    float* current_tails = nullptr;
    float* prev_tails = nullptr;
    float* target_matrices = nullptr;

    const float* current_heads = nullptr;
    const float* current_pose_matrices = nullptr;
    const float* current_pose_quaternions = nullptr;
    const float* parent_pose_quaternions = nullptr;
    const float* current_pose_tails = nullptr;
    const float* lengths = nullptr;
    const float* init_axis_local = nullptr;
    const float* init_axis_parent = nullptr;
    const float* init_rotations = nullptr;
    const float* init_scales = nullptr;
    const std::int32_t* parent_indices = nullptr;
    const std::uint8_t* pinned = nullptr;
    const std::uint8_t* use_connect = nullptr;

    const float* root_quaternion = nullptr;
    const float* root_tail_world = nullptr;
    const float* armature_world = nullptr;
    const float* armature_world_inv = nullptr;
    const float* gravity_dir = nullptr;

    const float* hit_radii = nullptr;
    const std::int32_t* collided_by_groups = nullptr;
    const std::int32_t* collider_types = nullptr;
    const std::int32_t* collider_groups = nullptr;
    const float* collider_centers = nullptr;
    const float* collider_segment_a = nullptr;
    const float* collider_segment_b = nullptr;
    const float* collider_radii = nullptr;

    std::int64_t bone_count = 0;
    std::int64_t collider_count = 0;

    int substeps = 1;
    float dt = 0.0f;
    float stiffness_force = 0.0f;
    float drag_force = 0.0f;
    float gravity_power = 0.0f;
};

void solve_spring_bone_vrm_cpp(SpringBoneVrmChainView& view);

}  // namespace hotools
