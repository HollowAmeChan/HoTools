#pragma once

#include <cstdint>
#include <vector>

namespace hotools {

constexpr int kMc2AngleIterationCount = 3;

struct Mc2ExternalCollisionDebugRecord {
    std::int32_t primitive_kind = 0;
    std::int32_t primitive_index = -1;
    std::int32_t collider_index = -1;
    float position[3] {};
    float normal[3] {};
    float correction[3] {};
};

struct Mc2NeighborConstraintView {
    float* positions = nullptr;
    const float* base_positions = nullptr;
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
    float animation_pose_ratio = 0.0f;
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
    const float* base_rotations = nullptr;
    const float* inv_masses = nullptr;
    const float* max_distances = nullptr;
    const float* stiffness_values = nullptr;
    const float* backstop_radii = nullptr;
    const float* backstop_distances = nullptr;
    float* velocity_positions = nullptr;
    std::int64_t vertex_count = 0;
    int normal_axis = 1;
    bool explicit_enable_flags = false;
    bool max_distance_enabled = false;
    bool backstop_enabled = false;
    float* debug_record_origins = nullptr;
    float* debug_record_corrections = nullptr;
    std::uint8_t* debug_record_valid = nullptr;
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
    float velocity_weight = 1.0f;
};

struct Mc2CollisionView {
    float* positions = nullptr;
    const float* base_positions = nullptr;
    float* velocity_positions = nullptr;
    const float* inv_masses = nullptr;
    const float* collision_radii = nullptr;
    const float* max_lengths = nullptr;
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
    bool soft_sphere = false;
    std::vector<Mc2ExternalCollisionDebugRecord>* debug_contacts = nullptr;
};

struct Mc2EdgeCollisionView {
    float* positions = nullptr;
    const std::int32_t* edges = nullptr;
    const std::uint8_t* attributes = nullptr;
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
    std::int64_t edge_count = 0;
    std::int64_t collider_count = 0;
    std::int32_t collided_by_groups = 0;
    std::uint8_t move_attribute_mask = 1u << 2u;
    std::vector<Mc2ExternalCollisionDebugRecord>* debug_contacts = nullptr;
};

struct Mc2SelfCollisionView {
    float* positions = nullptr;
    const float* old_positions = nullptr;
    const float* inv_masses = nullptr;
    const std::int32_t* edges = nullptr;
    const std::int32_t* triangles = nullptr;
    const std::uint8_t* attributes = nullptr;
    float* collision_normals = nullptr;
    float* friction = nullptr;
    std::int64_t vertex_count = 0;
    std::int64_t edge_count = 0;
    std::int64_t triangle_count = 0;
    float surface_thickness = 0.0f;
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
    const float* restoration_velocity_attenuation_values = nullptr;
    const float* restoration_gravity_falloff_values = nullptr;
    const float* limit_values = nullptr;
    float* velocity_positions = nullptr;
    std::int64_t vertex_count = 0;
    std::int64_t line_count = 0;
    std::int64_t baseline_data_count = 0;
    float restoration_velocity_attenuation = 0.0f;
    float restoration_gravity_falloff = 0.0f;
    float limit_stiffness = 0.0f;
    bool explicit_enable_flags = false;
    bool restoration_enabled = false;
    bool limit_enabled = false;
    float* debug_record_origins = nullptr;
    float* debug_record_corrections = nullptr;
    float* debug_record_currents = nullptr;
    float* debug_record_limits = nullptr;
    std::uint8_t* debug_record_valid = nullptr;
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

struct Mc2BasePoseFromPoseView {
    const float* base_positions = nullptr;
    const float* base_normals = nullptr;
    const std::int32_t* parent_indices = nullptr;
    const std::int32_t* baseline_start = nullptr;
    const std::int32_t* baseline_count = nullptr;
    const std::int32_t* baseline_data = nullptr;
    const float* vertex_local_positions = nullptr;
    const float* vertex_local_rotations = nullptr;
    float* base_rotations = nullptr;
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

struct Mc2ParticleIntegrationView {
    float* positions = nullptr;
    float* velocities = nullptr;
    const float* depths = nullptr;
    const float* inv_masses = nullptr;
    const std::uint8_t* attributes = nullptr;
    const float* damping_values = nullptr;
    const float* damping_curve16 = nullptr;
    std::int64_t vertex_count = 0;
    std::uint8_t move_attribute_mask = 0;
    float dt = 0.0f;
    float simulation_power = 0.0f;
    float velocity_weight = 1.0f;
    float gravity[3] = {};
};

struct Mc2PartitionKeepTransformView {
    float* positions = nullptr;
    float* velocities = nullptr;
    const std::uint32_t* particle_partition_index = nullptr;
    const std::uint32_t* particle_attribute_flags = nullptr;
    const std::uint32_t* partition_frame_flags = nullptr;
    const float* old_partition_positions = nullptr;
    const float* old_partition_rotations = nullptr;
    const float* old_partition_linear = nullptr;
    const float* new_partition_positions = nullptr;
    const float* new_partition_rotations = nullptr;
    const float* new_partition_linear = nullptr;
    std::int64_t particle_count = 0;
    std::int64_t partition_count = 0;
    std::uint32_t fixed_attribute_mask = 1u;
    std::uint32_t keep_frame_mask = 2u;
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

void project_neighbor_constraints_mc2(Mc2NeighborConstraintView& view);
void project_tether_mc2(Mc2TetherConstraintView& view);
void project_motion_constraints_mc2(Mc2MotionConstraintView& view);
void apply_post_step_mc2(Mc2PostStepView& view);
void project_collisions_mc2(Mc2CollisionView& view);
void project_edge_collisions_mc2(Mc2EdgeCollisionView& view);
void project_self_collisions_mc2(Mc2SelfCollisionView& view);
void project_triangle_bending_mc2(Mc2TriangleBendingView& view);
void project_angle_constraints_mc2(Mc2AngleConstraintView& view);
void update_step_basic_pose_mc2(Mc2StepBasicPoseView& view);
void update_base_pose_from_pose_mc2(Mc2BasePoseFromPoseView& view);
void apply_substep_inertia_mc2(Mc2SubstepInertiaView& view);
void integrate_particles_mc2(Mc2ParticleIntegrationView& view);
void apply_partition_keep_transform_mc2(Mc2PartitionKeepTransformView& view);
void apply_centrifugal_velocity_mc2(Mc2CentrifugalView& view);
void calculate_display_positions_mc2(Mc2DisplayPredictionView& view);

}  // namespace hotools
