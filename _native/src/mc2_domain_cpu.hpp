#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace hotools::mc2_domain_cpu {

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
    ~DomainV1() = default;

    DomainV1(const DomainV1&) = delete;
    DomainV1& operator=(const DomainV1&) = delete;

    void update_frame(const FrameViewV1& frame);
    void step();
    void configure_distance(
        const std::int32_t* starts,
        const std::int32_t* counts,
        const std::int32_t* neighbors,
        const float* rest_lengths,
        const float* stiffness_values,
        std::size_t neighbor_count
    );
    void step_distance();
    void configure_tether(const std::int32_t* root_indices);
    void step_tether(
        const float* step_basic_positions,
        float compression,
        float stretch
    );
    void configure_inertia(
        const float* depths,
        const float* inv_masses
    );
    void configure_center(
        const float* local_inertia,
        const float* local_movement_speed_limits,
        const float* local_rotation_speed_limits,
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
    const std::string& domain_signature() const noexcept { return domain_signature_; }
    const std::string& layout_signature() const noexcept { return layout_signature_; }
    const std::vector<float>& world_positions() const noexcept { return world_positions_; }
    const std::vector<float>& world_rotations() const noexcept { return world_rotations_; }
    const std::vector<float>& world_normals() const noexcept { return world_normals_; }
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
    const std::vector<std::uint32_t>& center_shift_teleport_flags() const noexcept {
        return center_shift_teleport_flags_;
    }
    std::int64_t center_shift_count() const noexcept { return center_shift_count_; }
    std::int64_t center_step_count() const noexcept { return center_step_count_; }

private:
    void ensure_live() const;
    void validate_identity(const char* domain_signature, const char* layout_signature) const;

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
    std::vector<float> center_gravity_;
    std::vector<float> center_gravity_directions_;
    std::vector<float> center_gravity_falloff_;
    std::vector<float> center_stabilization_time_;
    std::vector<float> center_blend_weight_;
    std::vector<float> center_initial_scales_;
    std::vector<float> center_old_world_positions_;
    std::vector<float> center_old_world_rotations_;
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
    std::vector<float> center_anchor_inertia_;
    std::vector<float> center_world_inertia_;
    std::vector<float> center_movement_inertia_smoothing_;
    std::vector<float> center_movement_speed_limits_;
    std::vector<float> center_rotation_speed_limits_;
    std::vector<std::int32_t> center_teleport_modes_;
    std::vector<float> center_teleport_distances_;
    std::vector<float> center_teleport_rotations_;
    bool center_frame_shift_ready_ = false;
    std::int64_t center_shift_count_ = 0;
    std::vector<float> center_step_vectors_;
    std::vector<float> center_step_rotations_;
    std::vector<float> center_inertia_vectors_;
    std::vector<float> center_inertia_rotations_;
    std::vector<float> center_rotation_axes_;
    std::vector<float> center_gravity_ratios_;
    std::vector<float> center_velocity_weights_;
    bool center_ready_ = false;
    std::int64_t center_step_count_ = 0;
    std::vector<std::int64_t> partition_reset_counts_;
    std::vector<std::int64_t> partition_keep_counts_;
    std::vector<std::int32_t> distance_starts_;
    std::vector<std::int32_t> distance_counts_;
    std::vector<std::int32_t> distance_neighbors_;
    std::vector<float> distance_rest_lengths_;
    std::vector<float> distance_stiffness_values_;
    bool distance_ready_ = false;
    std::vector<std::int32_t> tether_root_indices_;
    bool tether_ready_ = false;
    std::vector<float> inertia_depths_;
    std::vector<float> inertia_inv_masses_;
    bool inertia_ready_ = false;
    std::vector<float> integration_damping_values_;
    bool integration_ready_ = false;
    std::int64_t frame_ = -1;
    std::int64_t generation_ = -1;
    float frame_delta_time_ = 0.0f;
    float simulation_delta_time_ = 0.0f;
    float time_scale_ = 1.0f;
    std::int64_t skip_count_ = 0;
    bool is_running_ = false;
    std::int64_t step_count_ = 0;
    bool disposed_ = false;
};

}  // namespace hotools::mc2_domain_cpu
