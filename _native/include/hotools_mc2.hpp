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
    const float* collider_old_centers = nullptr;
    const float* collider_old_segment_a = nullptr;
    const float* collider_old_segment_b = nullptr;
    const float* collider_radii = nullptr;
    std::int64_t vertex_count = 0;
    std::int64_t collider_count = 0;
    std::int32_t collided_by_groups = 0;
};

struct Mc2TriangleBendingView {
    float* positions = nullptr;
    const float* inv_masses = nullptr;
    const float* stiffness_values = nullptr;
    const std::int32_t* dihedral_pairs = nullptr;
    const float* dihedral_rest_angles = nullptr;
    const std::int32_t* dihedral_signs = nullptr;
    const std::int32_t* volume_pairs = nullptr;
    const float* volume_rest = nullptr;
    std::int64_t vertex_count = 0;
    std::int64_t dihedral_count = 0;
    std::int64_t volume_count = 0;
};

struct Mc2AngleConstraintView {
    float* positions = nullptr;
    const float* inv_masses = nullptr;
    const std::int32_t* parent_indices = nullptr;
    const std::int32_t* baseline_start = nullptr;
    const std::int32_t* baseline_count = nullptr;
    const std::int32_t* baseline_data = nullptr;
    const float* step_basic_positions = nullptr;
    const float* step_basic_rotations = nullptr;
    const float* restoration_values = nullptr;
    const float* limit_values = nullptr;
    float* velocity_positions = nullptr;
    std::int64_t vertex_count = 0;
    std::int64_t line_count = 0;
    std::int64_t baseline_data_count = 0;
    float restoration_velocity_attenuation = 0.0f;
    float restoration_gravity_falloff = 0.0f;
    float limit_stiffness = 0.0f;
};

struct Mc2StepBasicPoseView {
    const float* base_positions = nullptr;
    const float* base_rotations = nullptr;
    const std::int32_t* parent_indices = nullptr;
    const std::int32_t* baseline_start = nullptr;
    const std::int32_t* baseline_count = nullptr;
    const std::int32_t* baseline_data = nullptr;
    const float* vertex_local_positions = nullptr;
    const float* vertex_local_rotations = nullptr;
    float* step_positions = nullptr;
    float* step_rotations = nullptr;
    std::int64_t vertex_count = 0;
    std::int64_t line_count = 0;
    std::int64_t baseline_data_count = 0;
    float animation_pose_ratio = 0.0f;
};

struct Mc2SubstepInertiaView {
    float* old_positions = nullptr;
    float* velocities = nullptr;
    const float* depths = nullptr;
    const float* inv_masses = nullptr;
    std::int64_t vertex_count = 0;
    float old_world_position[3] = {};
    float step_vector[3] = {};
    float step_rotation[4] = {};
    float inertia_vector[3] = {};
    float inertia_rotation[4] = {};
    float depth_inertia = 0.0f;
};

struct Mc2CentrifugalView {
    const float* positions = nullptr;
    float* velocities = nullptr;
    const float* depths = nullptr;
    const float* inv_masses = nullptr;
    std::int64_t vertex_count = 0;
    float now_world_position[3] = {};
    float rotation_axis[3] = {};
    float angular_velocity = 0.0f;
    float centrifugal = 0.0f;
};

struct Mc2DisplayPredictionView {
    const float* positions = nullptr;
    const float* real_velocities = nullptr;
    const std::int32_t* root_indices = nullptr;
    float* display_positions = nullptr;
    std::int64_t vertex_count = 0;
    float frame_dt = 0.0f;
    float max_distance_ratio = 1.3f;
};

struct Mc2MeshClothSolveView {
    float* positions = nullptr;
    float* old_positions = nullptr;
    float* velocity_positions = nullptr;
    float* velocities = nullptr;
    float* real_velocities = nullptr;
    float* friction = nullptr;
    float* static_friction = nullptr;
    float* collision_normals = nullptr;
    float* inv_masses = nullptr;
    float* step_basic_positions = nullptr;
    float* step_basic_rotations = nullptr;
    float* display_positions = nullptr;

    const float* base_positions = nullptr;
    const float* base_normals = nullptr;
    const float* base_rotations = nullptr;
    const std::uint8_t* attributes = nullptr;
    const float* depths = nullptr;
    const std::int32_t* root_indices = nullptr;
    const float* tether_rest_lengths = nullptr;
    const std::int32_t* parent_indices = nullptr;
    const std::int32_t* baseline_start = nullptr;
    const std::int32_t* baseline_count = nullptr;
    const std::int32_t* baseline_data = nullptr;
    const float* vertex_local_positions = nullptr;
    const float* vertex_local_rotations = nullptr;

    const std::int32_t* distance_start = nullptr;
    const std::int32_t* distance_count = nullptr;
    const std::int32_t* distance_data = nullptr;
    const float* distance_rest = nullptr;
    const float* distance_stiffness_values = nullptr;

    const std::int32_t* bend_distance_start = nullptr;
    const std::int32_t* bend_distance_count = nullptr;
    const std::int32_t* bend_distance_data = nullptr;
    const float* bend_distance_rest = nullptr;
    const float* bend_stiffness_values = nullptr;

    const std::int32_t* dihedral_pairs = nullptr;
    const float* dihedral_rest_angles = nullptr;
    const std::int32_t* dihedral_signs = nullptr;
    const std::int32_t* volume_pairs = nullptr;
    const float* volume_rest = nullptr;

    const float* angle_restoration_values = nullptr;
    const float* angle_limit_values = nullptr;
    const float* max_distances = nullptr;
    const float* motion_stiffness_values = nullptr;
    const float* backstop_radii = nullptr;
    const float* backstop_distances = nullptr;

    const float* collision_radii = nullptr;
    const std::int32_t* collider_types = nullptr;
    const std::int32_t* collider_group_bits = nullptr;
    const float* collider_centers = nullptr;
    const float* collider_segment_a = nullptr;
    const float* collider_segment_b = nullptr;
    const float* collider_old_centers = nullptr;
    const float* collider_old_segment_a = nullptr;
    const float* collider_old_segment_b = nullptr;
    const float* collider_radii = nullptr;

    const float* substep_old_world_positions = nullptr;
    const float* substep_step_vectors = nullptr;
    const float* substep_step_rotations = nullptr;
    const float* substep_inertia_vectors = nullptr;
    const float* substep_inertia_rotations = nullptr;
    const float* substep_now_world_positions = nullptr;
    const float* substep_rotation_axes = nullptr;
    const float* substep_angular_velocities = nullptr;

    std::int64_t vertex_count = 0;
    std::int64_t line_count = 0;
    std::int64_t baseline_data_count = 0;
    std::int64_t distance_count_total = 0;
    std::int64_t bend_distance_count_total = 0;
    std::int64_t dihedral_count = 0;
    std::int64_t volume_count = 0;
    std::int64_t collider_count = 0;

    int substeps = 1;
    int iterations = 0;
    float frame_dt = 0.0f;
    float step_dt = 0.0f;
    float gravity[3] = {};
    float substep_damping = 0.0f;
    float depth_inertia = 0.0f;
    float centrifugal = 0.0f;
    float tether_compression = 0.0f;
    float tether_stretch = 0.0f;
    float dynamic_friction = 0.0f;
    float static_friction_speed = 0.0f;
    float particle_speed_limit = -1.0f;
    float angle_limit_stiffness = 0.0f;
    float display_max_distance_ratio = 1.3f;
    float animation_pose_ratio = 0.0f;
    std::int32_t collided_by_groups = 0;
};

void project_neighbor_constraints_mc2(Mc2NeighborConstraintView& view);
void project_tether_mc2(Mc2TetherConstraintView& view);
void project_motion_constraints_mc2(Mc2MotionConstraintView& view);
void apply_post_step_mc2(Mc2PostStepView& view);
void project_collisions_mc2(Mc2CollisionView& view);
void project_triangle_bending_mc2(Mc2TriangleBendingView& view);
void project_angle_constraints_mc2(Mc2AngleConstraintView& view);
void update_step_basic_pose_mc2(Mc2StepBasicPoseView& view);
void apply_substep_inertia_mc2(Mc2SubstepInertiaView& view);
void apply_centrifugal_velocity_mc2(Mc2CentrifugalView& view);
void calculate_display_positions_mc2(Mc2DisplayPredictionView& view);
void solve_meshcloth_mc2(Mc2MeshClothSolveView& view);

}  // namespace hotools
