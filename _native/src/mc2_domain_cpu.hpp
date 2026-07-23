#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace hotools {
class Mc2WholeDomainSelfEngine;
struct Mc2WholeDomainSelfDebugSnapshot;
struct Mc2ExternalCollisionDebugRecord;
}

namespace hotools::mc2_domain_cpu {

enum ConstraintDebugMaskV1 : std::uint32_t {
    kConstraintDebugAngle = 1u,
    kConstraintDebugMotion = 2u,
    kConstraintDebugDistance = 4u,
    kConstraintDebugTether = 8u,
    kConstraintDebugBending = 16u,
    kConstraintDebugExternalCollision = 32u,
    kConstraintDebugWholeDomainSelf = 64u,
};

struct ProgramViewV1 {
    std::uint32_t schema_version = 0;
    std::size_t particle_count = 0;
    std::size_t partition_count = 0;
    const float* bind_positions = nullptr;
    const float* bind_rotations = nullptr;
    const std::uint32_t* particle_partition_index = nullptr;
    const std::uint32_t* particle_attribute_flags = nullptr;
    const float* partition_center_local_positions = nullptr;
    const float* partition_initial_local_gravity_directions = nullptr;
    const char* domain_signature = nullptr;
    const char* layout_signature = nullptr;
};

struct FrameViewV1 {
    std::size_t particle_count = 0;
    std::size_t partition_count = 0;
    const float* world_positions = nullptr;
    const float* world_rotations = nullptr;
    const float* world_normals = nullptr;
    const float* partition_world_positions = nullptr;
    const float* partition_world_rotations = nullptr;
    const float* partition_world_scales = nullptr;
    const float* partition_world_linear = nullptr;
    const float* anchor_world_positions = nullptr;
    const float* anchor_world_rotations = nullptr;
    const std::uint32_t* anchor_present = nullptr;
    const std::uint32_t* partition_frame_flags = nullptr;
    const float* velocity_weights = nullptr;
    const float* gravity_ratios = nullptr;
    std::int64_t frame = 0;
    std::int64_t generation = 0;
    const char* domain_signature = nullptr;
    const char* layout_signature = nullptr;
    float frame_delta_time = 0.0f;
    float simulation_delta_time = 0.0f;
    float time_scale = 1.0f;
    std::int64_t skip_count = 0;
    bool is_running = false;
};

class DomainV1 {
public:
    explicit DomainV1(const ProgramViewV1& program);
    ~DomainV1();

    DomainV1(const DomainV1&) = delete;
    DomainV1& operator=(const DomainV1&) = delete;

    std::unique_ptr<DomainV1> create_parameter_staging_domain() const;
    void swap_parameter_configuration(DomainV1& staging);

    void update_frame(const FrameViewV1& frame);
    void step();
    void begin_constraint_debug(std::uint32_t mask);
    void end_constraint_debug();
    void clear_constraint_debug();
    void configure_distance(
        const std::int32_t* starts,
        const std::int32_t* counts,
        const std::int32_t* neighbors,
        const float* rest_lengths,
        const float* stiffness_values,
        const float* depth_values,
        const float* friction_values,
        const float* velocity_attenuation_values,
        std::size_t neighbor_count
    );
    void configure_baseline(
        const std::int32_t* parent_indices,
        const std::int32_t* line_starts,
        const std::int32_t* line_counts,
        std::size_t line_count,
        const std::int32_t* line_data,
        std::size_t data_count
    );
    void configure_baseline_pose(
        const float* vertex_local_positions,
        const float* vertex_local_rotations
    );
    void prepare_step_basic_pose(float animation_pose_ratio);
    void prepare_step_basic_pose_partitioned(const float* animation_pose_ratios);
    void step_angle(
        const float* step_basic_positions,
        const float* step_basic_rotations,
        const float* restoration_values,
        const float* limit_values,
        float restoration_velocity_attenuation,
        float restoration_gravity_falloff,
        float limit_stiffness,
        bool restoration_enabled,
        bool limit_enabled
    );
    void step_angle_partitioned(
        const float* step_basic_positions,
        const float* step_basic_rotations,
        const float* restoration_values,
        const float* limit_values,
        const float* restoration_velocity_attenuation_values,
        const float* restoration_gravity_falloff_values,
        const float* limit_stiffness_values,
        const std::uint32_t* restoration_enabled_values,
        const std::uint32_t* limit_enabled_values
    );
    void step_motion(
        const float* base_positions,
        const float* base_rotations,
        const float* max_distances,
        const float* stiffness_values,
        const float* backstop_radii,
        const float* backstop_distances,
        std::int32_t normal_axis,
        bool max_distance_enabled,
        bool backstop_enabled
    );
    void step_motion_partitioned(
        const float* base_positions,
        const float* base_rotations,
        const float* max_distances,
        const float* stiffness_values,
        const float* backstop_radii,
        const float* backstop_distances,
        const std::int32_t* normal_axis_values,
        const std::uint32_t* max_distance_enabled_values,
        const std::uint32_t* backstop_enabled_values
    );
    void step_external_collision(
        const float* base_positions,
        const float* collision_radii,
        const float* friction,
        std::int32_t collided_by_groups,
        const std::int32_t* collider_types,
        const std::int32_t* collider_group_bits,
        const float* collider_centers,
        const float* collider_segment_a,
        const float* collider_segment_b,
        const float* collider_old_centers,
        const float* collider_old_segment_a,
        const float* collider_old_segment_b,
        const float* collider_radii,
        std::size_t collider_count
    );
    void step_self_collision(
        const float* old_positions,
        const std::int32_t* edges,
        std::size_t edge_count,
        const std::int32_t* triangles,
        std::size_t triangle_count,
        const float* friction,
        float surface_thickness
    );
    void configure_whole_domain_self(
        const std::int32_t* points,
        std::size_t point_count,
        const std::int32_t* edges,
        std::size_t edge_count,
        const std::int32_t* triangles,
        std::size_t triangle_count,
        const std::uint32_t* partition_self_collision_modes,
        const std::uint32_t* partition_collision_groups,
        const std::uint32_t* partition_collision_masks,
        const float* particle_friction,
        const float* particle_thickness,
        const float* particle_cloth_mass
    );
    void step_whole_domain_self(const float* old_positions);
    void step_whole_domain_self_owned();
    void configure_compiled_external_collision(
        const std::int32_t* edges,
        std::size_t edge_count,
        const std::uint32_t* partition_collision_modes,
        const std::uint32_t* partition_collided_by_groups,
        const float* particle_radii,
        const float* particle_friction
    );
    void step_compiled_external_collision(
        const std::int32_t* collider_types,
        const std::int32_t* collider_group_bits,
        const float* collider_centers,
        const float* collider_segment_a,
        const float* collider_segment_b,
        const float* collider_old_centers,
        const float* collider_old_segment_a,
        const float* collider_old_segment_b,
        const float* collider_radii,
        std::size_t collider_count
    );
    void step_external_edge_collision(
        const float* collision_radii,
        const std::int32_t* edges,
        std::size_t edge_count,
        const float* friction,
        std::int32_t collided_by_groups,
        const std::int32_t* collider_types,
        const std::int32_t* collider_group_bits,
        const float* collider_centers,
        const float* collider_segment_a,
        const float* collider_segment_b,
        const float* collider_old_centers,
        const float* collider_old_segment_a,
        const float* collider_old_segment_b,
        const float* collider_radii,
        std::size_t collider_count
    );
    void step_distance(float simulation_power = 1.0f, std::int32_t debug_phase = -1);
    void configure_tether(const std::int32_t* root_indices);
    void step_tether(
        const float* step_basic_positions,
        float compression,
        float stretch
    );
    void step_tether_partitioned(
        const float* step_basic_positions,
        const float* compression_values,
        const float* stretch_values
    );
    void configure_bending(
        const std::int32_t* dihedral_pairs,
        const float* dihedral_rest_angles,
        const std::int32_t* dihedral_signs,
        std::size_t dihedral_count,
        const std::int32_t* volume_pairs,
        const float* volume_rest,
        std::size_t volume_count,
        const float* stiffness_values
    );
    void step_bending(float simulation_power = 1.0f);
    void configure_inertia(
        const float* depths,
        const float* inv_masses
    );
    void configure_constraint_friction(const float* friction_values);
    void configure_center(
        const float* local_inertia,
        const float* local_movement_speed_limits,
        const float* local_rotation_speed_limits,
        const float* depth_inertia,
        const float* gravity,
        const float* gravity_directions,
        const float* gravity_falloff,
        const float* stabilization_time,
        const float* blend_weight
    );
    void configure_center_frame_shift(
        const float* anchor_inertia,
        const float* world_inertia,
        const float* movement_inertia_smoothing,
        const float* movement_speed_limits,
        const float* rotation_speed_limits,
        const std::int32_t* teleport_modes,
        const float* teleport_distances,
        const float* teleport_rotations
    );
    void step_center_frame_shift(const float* anchor_component_local_positions);
    void step_center(
        float dt,
        float frame_interpolation,
        const float* distance_weights
    );
    void step_center_inertia();
    void step_inertia(
        const float* old_world_position,
        const float* step_vector,
        const float* step_rotation,
        const float* inertia_vector,
        const float* inertia_rotation,
        float depth_inertia
    );
    void configure_integration(const float* damping_values);
    void step_integration(
        float dt,
        float simulation_power,
        float velocity_weight,
        const float* gravity
    );
    void step_integration_partitioned(
        float dt,
        float simulation_power
    );
    void step_post(
        const float* old_positions,
        float dt,
        float dynamic_friction,
        float static_friction_speed,
        float particle_speed_limit,
        float velocity_weight
    );
    void step_post_owned(
        float dt,
        float dynamic_friction,
        float static_friction_speed,
        float particle_speed_limit,
        float velocity_weight
    );
    void step_post_owned_partitioned(
        float dt,
        const float* dynamic_friction_values,
        const float* static_friction_speed_values,
        const float* particle_speed_limit_values
    );
    void dispose() noexcept;

    bool disposed() const noexcept { return disposed_; }
    std::size_t particle_count() const noexcept { return particle_count_; }
    std::size_t partition_count() const noexcept { return partition_count_; }
    std::int64_t frame() const noexcept { return frame_; }
    std::int64_t generation() const noexcept { return generation_; }
    float frame_delta_time() const noexcept { return frame_delta_time_; }
    float simulation_delta_time() const noexcept { return simulation_delta_time_; }
    float time_scale() const noexcept { return time_scale_; }
    std::int64_t skip_count() const noexcept { return skip_count_; }
    bool is_running() const noexcept { return is_running_; }
    std::int64_t step_count() const noexcept { return step_count_; }
    std::int64_t angle_solve_count() const noexcept { return angle_solve_count_; }
    std::int64_t motion_solve_count() const noexcept { return motion_solve_count_; }
    const std::string& domain_signature() const noexcept { return domain_signature_; }
    const std::string& layout_signature() const noexcept { return layout_signature_; }
    const std::vector<float>& world_positions() const noexcept { return world_positions_; }
    const std::vector<float>& world_rotations() const noexcept { return world_rotations_; }
    const std::vector<float>& world_normals() const noexcept { return world_normals_; }
    const std::vector<float>& real_velocities() const noexcept { return real_velocities_; }
    const std::vector<float>& partition_world_positions() const noexcept {
        return partition_world_positions_;
    }
    const std::vector<float>& partition_center_local_positions() const noexcept {
        return partition_center_local_positions_;
    }
    const std::vector<float>& partition_initial_local_gravity_directions() const noexcept {
        return partition_initial_local_gravity_directions_;
    }
    const std::vector<std::int64_t>& partition_reset_counts() const noexcept {
        return partition_reset_counts_;
    }
    const std::vector<std::int64_t>& partition_keep_counts() const noexcept {
        return partition_keep_counts_;
    }
    const std::vector<float>& center_step_vectors() const noexcept {
        return center_step_vectors_;
    }
    const std::vector<float>& center_inertia_vectors() const noexcept {
        return center_inertia_vectors_;
    }
    const std::vector<float>& center_frame_world_positions() const noexcept {
        return center_frame_world_positions_;
    }
    const std::vector<float>& center_frame_world_rotations() const noexcept {
        return center_frame_world_rotations_;
    }
    const std::vector<float>& center_shift_vectors() const noexcept {
        return center_shift_vectors_;
    }
    const std::vector<float>& center_shift_rotations() const noexcept {
        return center_shift_rotations_;
    }
    const std::vector<float>& center_shift_now_positions() const noexcept {
        return center_shift_now_positions_;
    }
    const std::vector<float>& center_shift_now_rotations() const noexcept {
        return center_shift_now_rotations_;
    }
    const std::vector<float>& center_shift_old_frame_positions() const noexcept {
        return center_shift_old_frame_positions_;
    }
    const std::vector<float>& center_shift_old_frame_rotations() const noexcept {
        return center_shift_old_frame_rotations_;
    }
    const std::vector<std::int32_t>& center_teleport_modes() const noexcept {
        return center_teleport_modes_;
    }
    const std::vector<float>& center_teleport_rotations() const noexcept {
        return center_teleport_rotations_;
    }
    const std::vector<std::uint32_t>& center_shift_teleport_flags() const noexcept {
        return center_shift_teleport_flags_;
    }
    const std::vector<float>& center_debug_raw_component_deltas() const noexcept {
        return center_debug_raw_component_deltas_;
    }
    const std::vector<float>& center_debug_anchor_shift_vectors() const noexcept {
        return center_debug_anchor_shift_vectors_;
    }
    const std::vector<float>& center_debug_smoothing_shift_vectors() const noexcept {
        return center_debug_smoothing_shift_vectors_;
    }
    const std::vector<float>& center_debug_world_shift_vectors() const noexcept {
        return center_debug_world_shift_vectors_;
    }
    const std::vector<float>& center_debug_teleport_rotation_axes() const noexcept {
        return center_debug_teleport_rotation_axes_;
    }
    const std::vector<float>& center_debug_teleport_measured_distances() const noexcept {
        return center_debug_teleport_measured_distances_;
    }
    const std::vector<float>& center_debug_teleport_distance_thresholds() const noexcept {
        return center_debug_teleport_distance_thresholds_;
    }
    const std::vector<float>& center_debug_teleport_measured_rotation_degrees() const noexcept {
        return center_debug_teleport_measured_rotation_degrees_;
    }
    const std::vector<std::uint8_t>& center_debug_movement_speed_limited() const noexcept {
        return center_debug_movement_speed_limited_;
    }
    const std::vector<std::uint8_t>& center_debug_rotation_speed_limited() const noexcept {
        return center_debug_rotation_speed_limited_;
    }
    const std::vector<float>& center_gravity_ratios() const noexcept {
        return center_gravity_ratios_;
    }
    std::int64_t center_shift_count() const noexcept { return center_shift_count_; }
    std::int64_t center_step_count() const noexcept { return center_step_count_; }
    bool baseline_ready() const noexcept { return baseline_ready_; }
    std::size_t baseline_line_count() const noexcept { return baseline_line_starts_.size(); }
    std::size_t baseline_data_count() const noexcept { return baseline_line_data_.size(); }
    bool baseline_pose_ready() const noexcept { return baseline_pose_ready_; }
    bool whole_domain_self_ready() const noexcept { return whole_domain_self_ready_; }
    bool compiled_external_ready() const noexcept { return compiled_external_ready_; }
    std::size_t compiled_external_edge_count() const noexcept {
        return compiled_external_edges_.size() / 2;
    }
    std::int64_t compiled_external_step_count() const noexcept {
        return compiled_external_step_count_;
    }
    std::size_t whole_domain_self_edge_count() const noexcept {
        return whole_domain_self_edges_.size() / 2;
    }
    std::size_t whole_domain_self_point_count() const noexcept {
        return whole_domain_self_points_.size();
    }
    std::size_t whole_domain_self_triangle_count() const noexcept {
        return whole_domain_self_triangles_.size() / 3;
    }
    std::int64_t whole_domain_self_step_count() const noexcept {
        return whole_domain_self_step_count_;
    }
    std::int64_t whole_domain_self_last_contact_count() const noexcept {
        return whole_domain_self_last_contact_count_;
    }
    std::int64_t whole_domain_self_last_candidate_count() const noexcept {
        return whole_domain_self_last_candidate_count_;
    }
    const std::vector<float>& step_basic_positions() const noexcept {
        return step_basic_positions_;
    }
    const std::vector<float>& step_basic_rotations() const noexcept {
        return step_basic_rotations_;
    }
    const std::vector<std::uint32_t>& particle_partition_index() const noexcept {
        return particle_partition_index_;
    }
    const std::vector<std::int32_t>& baseline_parent_indices() const noexcept {
        return baseline_parent_indices_;
    }
    const std::vector<std::int32_t>& baseline_line_data() const noexcept {
        return baseline_line_data_;
    }
    std::uint32_t constraint_debug_active_mask() const noexcept {
        return constraint_debug_active_mask_;
    }
    std::uint32_t constraint_debug_captured_mask() const noexcept {
        return constraint_debug_captured_mask_;
    }
    const std::vector<float>& motion_debug_origins() const noexcept { return motion_debug_origins_; }
    const std::vector<float>& motion_debug_targets() const noexcept { return motion_debug_targets_; }
    const std::vector<float>& motion_debug_corrections() const noexcept { return motion_debug_corrections_; }
    const std::vector<float>& motion_debug_limits() const noexcept { return motion_debug_limits_; }
    const std::vector<std::uint8_t>& motion_debug_valid() const noexcept { return motion_debug_valid_; }
    const std::vector<float>& angle_debug_origins() const noexcept { return angle_debug_origins_; }
    const std::vector<float>& angle_debug_targets() const noexcept { return angle_debug_targets_; }
    const std::vector<float>& angle_debug_target_vectors() const noexcept { return angle_debug_target_vectors_; }
    const std::vector<float>& angle_debug_corrections() const noexcept { return angle_debug_corrections_; }
    const std::vector<float>& angle_debug_currents() const noexcept { return angle_debug_currents_; }
    const std::vector<float>& angle_debug_limits() const noexcept { return angle_debug_limits_; }
    const std::vector<std::uint8_t>& angle_debug_valid() const noexcept { return angle_debug_valid_; }
    const std::vector<std::int32_t>& distance_starts() const noexcept { return distance_starts_; }
    const std::vector<std::int32_t>& distance_counts() const noexcept { return distance_counts_; }
    const std::vector<std::int32_t>& distance_neighbors() const noexcept { return distance_neighbors_; }
    const std::vector<float>& distance_debug_origins() const noexcept { return distance_debug_origins_; }
    const std::vector<float>& distance_debug_target_origins() const noexcept { return distance_debug_target_origins_; }
    const std::vector<float>& distance_debug_corrections() const noexcept { return distance_debug_corrections_; }
    const std::vector<float>& distance_debug_lengths() const noexcept { return distance_debug_lengths_; }
    const std::vector<float>& distance_debug_rests() const noexcept { return distance_debug_rests_; }
    const std::vector<float>& distance_debug_stiffnesses() const noexcept { return distance_debug_stiffnesses_; }
    const std::vector<std::uint8_t>& distance_debug_valid() const noexcept { return distance_debug_valid_; }
    const std::vector<std::uint8_t>& distance_debug_hit() const noexcept { return distance_debug_hit_; }
    const std::vector<std::int32_t>& tether_root_indices() const noexcept { return tether_root_indices_; }
    const std::vector<float>& tether_debug_origins() const noexcept { return tether_debug_origins_; }
    const std::vector<float>& tether_debug_root_origins() const noexcept { return tether_debug_root_origins_; }
    const std::vector<float>& tether_debug_corrections() const noexcept { return tether_debug_corrections_; }
    const std::vector<float>& tether_debug_lengths() const noexcept { return tether_debug_lengths_; }
    const std::vector<float>& tether_debug_rests() const noexcept { return tether_debug_rests_; }
    const std::vector<float>& tether_debug_minimums() const noexcept { return tether_debug_minimums_; }
    const std::vector<float>& tether_debug_maximums() const noexcept { return tether_debug_maximums_; }
    const std::vector<float>& tether_debug_stiffnesses() const noexcept { return tether_debug_stiffnesses_; }
    const std::vector<std::int8_t>& tether_debug_branches() const noexcept { return tether_debug_branches_; }
    const std::vector<std::uint8_t>& tether_debug_valid() const noexcept { return tether_debug_valid_; }
    const std::vector<std::uint8_t>& tether_debug_hit() const noexcept { return tether_debug_hit_; }
    const std::vector<std::int32_t>& bending_dihedral_pairs() const noexcept { return bending_dihedral_pairs_; }
    const std::vector<std::int32_t>& bending_dihedral_signs() const noexcept { return bending_dihedral_signs_; }
    const std::vector<std::int32_t>& bending_volume_pairs() const noexcept { return bending_volume_pairs_; }
    const std::vector<float>& bending_debug_origins() const noexcept { return bending_debug_origins_; }
    const std::vector<float>& bending_debug_corrections() const noexcept { return bending_debug_corrections_; }
    const std::vector<float>& bending_debug_currents() const noexcept { return bending_debug_currents_; }
    const std::vector<float>& bending_debug_rests() const noexcept { return bending_debug_rests_; }
    const std::vector<float>& bending_debug_stiffnesses() const noexcept { return bending_debug_stiffnesses_; }
    const std::vector<std::uint8_t>& bending_debug_valid() const noexcept { return bending_debug_valid_; }
    const std::vector<std::uint8_t>& bending_debug_hit() const noexcept { return bending_debug_hit_; }
    const std::vector<hotools::Mc2ExternalCollisionDebugRecord>& external_debug_contacts() const noexcept { return external_debug_contacts_; }
    const std::vector<float>& external_debug_friction_before() const noexcept { return external_debug_friction_before_; }
    const std::vector<float>& external_debug_friction_after() const noexcept { return external_debug_friction_after_; }
    const std::vector<float>& external_debug_radii() const noexcept { return external_debug_radii_; }
    const std::vector<std::uint32_t>& compiled_external_modes() const noexcept { return compiled_external_modes_; }
    const std::vector<std::uint32_t>& compiled_external_masks() const noexcept { return compiled_external_masks_; }
    const std::vector<float>& compiled_external_radii() const noexcept { return compiled_external_radii_; }
    const std::vector<float>& compiled_external_friction() const noexcept { return compiled_external_friction_; }
    const std::vector<std::int32_t>& compiled_external_edges() const noexcept { return compiled_external_edges_; }
    const hotools::Mc2WholeDomainSelfDebugSnapshot& whole_domain_self_debug_snapshot() const;

private:
    void ensure_live() const;
    void validate_identity(const char* domain_signature, const char* layout_signature) const;
    void prepare_prediction_state();
    void step_whole_domain_self_impl(const float* old_positions, bool reset_friction);

    std::size_t particle_count_ = 0;
    std::size_t partition_count_ = 0;
    std::string domain_signature_;
    std::string layout_signature_;
    std::vector<float> bind_positions_;
    std::vector<float> bind_rotations_;
    std::vector<std::uint32_t> particle_partition_index_;
    std::vector<std::uint32_t> particle_attribute_flags_;
    std::vector<float> partition_center_local_positions_;
    std::vector<float> partition_initial_local_gravity_directions_;
    std::vector<float> animated_base_world_positions_;
    std::vector<float> animated_base_world_rotations_;
    std::vector<float> world_positions_;
    std::vector<float> world_rotations_;
    std::vector<float> world_normals_;
    std::vector<float> velocity_positions_;
    std::vector<float> state_velocities_;
    std::vector<float> real_velocities_;
    std::vector<float> static_friction_;
    std::vector<float> post_old_positions_;
    std::vector<float> substep_old_positions_;
    std::vector<float> partition_world_positions_;
    std::vector<float> partition_previous_world_positions_;
    std::vector<float> partition_world_rotations_;
    std::vector<float> partition_previous_world_rotations_;
    std::vector<float> partition_previous_world_scales_;
    std::vector<float> partition_world_scales_;
    std::vector<float> partition_world_linear_;
    std::vector<float> anchor_world_positions_;
    std::vector<float> anchor_world_rotations_;
    std::vector<float> anchor_previous_world_positions_;
    std::vector<float> anchor_previous_world_rotations_;
    std::vector<std::uint32_t> anchor_present_;
    std::vector<std::uint32_t> partition_frame_flags_;
    std::vector<float> velocity_weights_;
    std::vector<float> gravity_ratios_;
    std::vector<float> center_local_inertia_;
    std::vector<float> center_local_movement_speed_limits_;
    std::vector<float> center_local_rotation_speed_limits_;
    std::vector<float> center_depth_inertia_;
    std::vector<float> center_gravity_;
    std::vector<float> center_gravity_directions_;
    std::vector<float> center_gravity_falloff_;
    std::vector<float> center_stabilization_time_;
    std::vector<float> center_blend_weight_;
    std::vector<float> center_initial_scales_;
    std::vector<float> center_old_world_positions_;
    std::vector<float> center_old_world_rotations_;
    std::vector<float> center_inertia_old_world_positions_;
    std::vector<float> center_previous_frame_world_positions_;
    std::vector<float> center_previous_frame_world_rotations_;
    std::vector<float> center_frame_world_positions_;
    std::vector<float> center_frame_world_rotations_;
    std::vector<float> center_now_world_positions_;
    std::vector<float> center_now_world_rotations_;
    std::vector<float> center_shift_vectors_;
    std::vector<float> center_shift_rotations_;
    std::vector<float> center_shift_old_frame_positions_;
    std::vector<float> center_shift_old_frame_rotations_;
    std::vector<float> center_shift_now_positions_;
    std::vector<float> center_shift_now_rotations_;
    std::vector<float> center_shift_smoothing_velocities_;
    std::vector<std::uint32_t> center_shift_teleport_flags_;
    std::vector<float> center_debug_raw_component_deltas_;
    std::vector<float> center_debug_anchor_shift_vectors_;
    std::vector<float> center_debug_smoothing_shift_vectors_;
    std::vector<float> center_debug_world_shift_vectors_;
    std::vector<float> center_debug_teleport_rotation_axes_;
    std::vector<float> center_debug_teleport_measured_distances_;
    std::vector<float> center_debug_teleport_distance_thresholds_;
    std::vector<float> center_debug_teleport_measured_rotation_degrees_;
    std::vector<std::uint8_t> center_debug_movement_speed_limited_;
    std::vector<std::uint8_t> center_debug_rotation_speed_limited_;
    std::vector<float> center_anchor_inertia_;
    std::vector<float> center_world_inertia_;
    std::vector<float> center_movement_inertia_smoothing_;
    std::vector<float> center_movement_speed_limits_;
    std::vector<float> center_rotation_speed_limits_;
    std::vector<std::int32_t> center_teleport_modes_;
    std::vector<float> center_teleport_distances_;
    std::vector<float> center_teleport_rotations_;
    bool center_frame_shift_ready_ = false;
    bool center_frame_shift_consumed_ = false;
    std::int64_t center_shift_count_ = 0;
    std::vector<float> center_step_vectors_;
    std::vector<float> center_step_rotations_;
    std::vector<float> center_inertia_vectors_;
    std::vector<float> center_inertia_rotations_;
    std::vector<float> center_rotation_axes_;
    std::vector<float> center_gravity_ratios_;
    std::vector<float> center_velocity_weights_;
    bool center_ready_ = false;
    bool center_inertia_pending_ = false;
    bool prediction_state_ready_ = false;
    bool substep_snapshot_ready_ = false;
    std::int64_t center_step_count_ = 0;
    std::vector<std::int64_t> partition_reset_counts_;
    std::vector<std::int64_t> partition_keep_counts_;
    std::vector<std::int32_t> distance_starts_;
    std::vector<std::int32_t> distance_counts_;
    std::vector<std::int32_t> distance_neighbors_;
    std::vector<float> distance_rest_lengths_;
    std::vector<float> distance_stiffness_values_;
    std::vector<float> distance_inverse_masses_;
    std::vector<float> distance_velocity_attenuation_values_;
    bool distance_ready_ = false;
    std::vector<std::int32_t> baseline_parent_indices_;
    std::vector<std::int32_t> baseline_line_starts_;
    std::vector<std::int32_t> baseline_line_counts_;
    std::vector<std::int32_t> baseline_line_data_;
    bool baseline_ready_ = false;
    std::vector<float> baseline_vertex_local_positions_;
    std::vector<float> baseline_vertex_local_rotations_;
    std::vector<float> step_basic_positions_;
    std::vector<float> step_basic_rotations_;
    bool baseline_pose_ready_ = false;
    std::uint32_t constraint_debug_active_mask_ = 0u;
    std::uint32_t constraint_debug_captured_mask_ = 0u;
    std::vector<float> motion_debug_origins_;
    std::vector<float> motion_debug_targets_;
    std::vector<float> motion_debug_corrections_;
    std::vector<float> motion_debug_limits_;
    std::vector<std::uint8_t> motion_debug_valid_;
    std::vector<float> angle_debug_origins_;
    std::vector<float> angle_debug_targets_;
    std::vector<float> angle_debug_target_vectors_;
    std::vector<float> angle_debug_corrections_;
    std::vector<float> angle_debug_currents_;
    std::vector<float> angle_debug_limits_;
    std::vector<std::uint8_t> angle_debug_valid_;
    std::vector<float> distance_debug_origins_;
    std::vector<float> distance_debug_target_origins_;
    std::vector<float> distance_debug_corrections_;
    std::vector<float> distance_debug_lengths_;
    std::vector<float> distance_debug_rests_;
    std::vector<float> distance_debug_stiffnesses_;
    std::vector<std::uint8_t> distance_debug_valid_;
    std::vector<std::uint8_t> distance_debug_hit_;
    std::vector<std::int32_t> tether_root_indices_;
    std::vector<float> tether_debug_origins_;
    std::vector<float> tether_debug_root_origins_;
    std::vector<float> tether_debug_corrections_;
    std::vector<float> tether_debug_lengths_;
    std::vector<float> tether_debug_rests_;
    std::vector<float> tether_debug_minimums_;
    std::vector<float> tether_debug_maximums_;
    std::vector<float> tether_debug_stiffnesses_;
    std::vector<std::int8_t> tether_debug_branches_;
    std::vector<std::uint8_t> tether_debug_valid_;
    std::vector<std::uint8_t> tether_debug_hit_;
    bool tether_ready_ = false;
    std::vector<std::int32_t> bending_dihedral_pairs_;
    std::vector<float> bending_dihedral_rest_angles_;
    std::vector<std::int32_t> bending_dihedral_signs_;
    std::vector<std::int32_t> bending_volume_pairs_;
    std::vector<float> bending_volume_rest_;
    std::vector<float> bending_stiffness_values_;
    std::vector<float> bending_debug_origins_;
    std::vector<float> bending_debug_corrections_;
    std::vector<float> bending_debug_currents_;
    std::vector<float> bending_debug_rests_;
    std::vector<float> bending_debug_stiffnesses_;
    std::vector<std::uint8_t> bending_debug_valid_;
    std::vector<std::uint8_t> bending_debug_hit_;
    std::vector<hotools::Mc2ExternalCollisionDebugRecord> external_debug_contacts_;
    std::vector<float> external_debug_friction_before_;
    std::vector<float> external_debug_friction_after_;
    std::vector<float> external_debug_radii_;
    bool bending_ready_ = false;
    std::vector<float> inertia_depths_;
    std::vector<float> inertia_inv_masses_;
    bool inertia_ready_ = false;
    std::vector<float> angle_inverse_masses_;
    std::vector<float> bending_inverse_masses_;
    bool constraint_friction_ready_ = false;
    std::vector<float> integration_damping_values_;
    bool integration_ready_ = false;
    std::vector<float> collision_friction_;
    bool collision_state_ready_ = false;
    std::vector<std::int32_t> compiled_external_edges_;
    std::vector<std::uint32_t> compiled_external_modes_;
    std::vector<std::uint32_t> compiled_external_masks_;
    std::vector<float> compiled_external_radii_;
    std::vector<float> compiled_external_friction_;
    bool compiled_external_ready_ = false;
    std::int64_t compiled_external_step_count_ = 0;
    std::vector<std::int32_t> whole_domain_self_edges_;
    std::vector<std::int32_t> whole_domain_self_points_;
    std::vector<std::int32_t> whole_domain_self_triangles_;
    std::vector<std::uint32_t> whole_domain_self_modes_;
    std::vector<std::uint32_t> whole_domain_collision_groups_;
    std::vector<std::uint32_t> whole_domain_collision_masks_;
    std::vector<float> whole_domain_self_friction_;
    std::vector<float> whole_domain_self_thickness_;
    std::vector<float> whole_domain_self_cloth_mass_;
    std::vector<float> whole_domain_self_scaled_thickness_;
    std::vector<float> whole_domain_self_partition_scale_ratios_;
    std::unique_ptr<hotools::Mc2WholeDomainSelfEngine> whole_domain_self_engine_;
    bool whole_domain_self_ready_ = false;
    std::int64_t whole_domain_self_step_count_ = 0;
    std::int64_t whole_domain_self_last_contact_count_ = 0;
    std::int64_t whole_domain_self_last_candidate_count_ = 0;
    std::int64_t frame_ = -1;
    std::int64_t generation_ = -1;
    float frame_delta_time_ = 0.0f;
    float simulation_delta_time_ = 0.0f;
    float time_scale_ = 1.0f;
    std::int64_t skip_count_ = 0;
    bool is_running_ = false;
    std::int64_t step_count_ = 0;
    std::int64_t angle_solve_count_ = 0;
    std::int64_t motion_solve_count_ = 0;
    bool disposed_ = false;
};

}  // namespace hotools::mc2_domain_cpu
