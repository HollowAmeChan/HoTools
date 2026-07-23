#include "mc2_domain_cpu.hpp"

#include "mc2_kernels.hpp"
#include "mc2_whole_domain_self.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace hotools::mc2_domain_cpu {
namespace {

constexpr float kDistanceFrictionMass = 3.0f;

void require_finite(const float* values, std::size_t count, const char* name) {
    if (values == nullptr && count != 0) {
        throw std::invalid_argument(std::string(name) + " cannot be null");
    }
    for (std::size_t index = 0; index < count; ++index) {
        if (!std::isfinite(values[index])) {
            throw std::invalid_argument(std::string(name) + " must be finite");
        }
    }
}

void require_identity(const char* value, const char* name) {
    if (value == nullptr || *value == '\0') {
        throw std::invalid_argument(std::string(name) + " cannot be empty");
    }
}

void require_unit_quaternions(const float* values, std::size_t count, const char* name) {
    require_finite(values, count * 4, name);
    for (std::size_t index = 0; index < count; ++index) {
        const auto offset = index * 4;
        float length_squared = 0.0f;
        for (std::size_t component = 0; component < 4; ++component) {
            length_squared += values[offset + component] * values[offset + component];
        }
        if (std::fabs(length_squared - 1.0f) > 0.00002f) {
            throw std::invalid_argument(std::string(name) + " must be unit quaternions");
        }
    }
}

}  // namespace

DomainV1::DomainV1(const ProgramViewV1& program)
    : particle_count_(program.particle_count),
      partition_count_(program.partition_count),
      domain_signature_(program.domain_signature != nullptr ? program.domain_signature : ""),
      layout_signature_(program.layout_signature != nullptr ? program.layout_signature : ""),
      bind_positions_(program.particle_count * 3),
      bind_rotations_(program.particle_count * 4),
      baseline_vertex_local_positions_(program.particle_count * 3, 0.0f),
      baseline_vertex_local_rotations_(program.particle_count * 4, 0.0f),
      step_basic_positions_(program.particle_count * 3, 0.0f),
      step_basic_rotations_(program.particle_count * 4, 0.0f),
      particle_partition_index_(program.particle_count),
      particle_attribute_flags_(program.particle_count),
      partition_center_local_positions_(program.partition_count * 3),
      partition_initial_local_gravity_directions_(program.partition_count * 3),
      animated_base_world_positions_(program.particle_count * 3),
      animated_base_world_rotations_(program.particle_count * 4),
      world_positions_(program.particle_count * 3),
      world_rotations_(program.particle_count * 4),
      world_normals_(program.particle_count * 3, 0.0f),
      velocity_positions_(program.particle_count * 3, 0.0f),
      state_velocities_(program.particle_count * 3, 0.0f),
      real_velocities_(program.particle_count * 3, 0.0f),
      static_friction_(program.particle_count, 0.0f),
      post_old_positions_(program.particle_count * 3, 0.0f),
      substep_old_positions_(program.particle_count * 3, 0.0f),
      partition_world_positions_(program.partition_count * 3, 0.0f),
      partition_previous_world_positions_(program.partition_count * 3, 0.0f),
      partition_world_rotations_(program.partition_count * 4, 0.0f),
      partition_previous_world_rotations_(program.partition_count * 4, 0.0f),
      partition_previous_world_scales_(program.partition_count * 3, 1.0f),
      partition_world_scales_(program.partition_count * 3, 1.0f),
      partition_world_linear_(program.partition_count * 9, 0.0f),
      anchor_world_positions_(program.partition_count * 3, 0.0f),
      anchor_world_rotations_(program.partition_count * 4, 0.0f),
      anchor_previous_world_positions_(program.partition_count * 3, 0.0f),
      anchor_previous_world_rotations_(program.partition_count * 4, 0.0f),
      anchor_present_(program.partition_count, 0u),
      partition_frame_flags_(program.partition_count, 0u),
      velocity_weights_(program.partition_count, 1.0f),
      gravity_ratios_(program.partition_count, 1.0f),
      center_local_inertia_(program.partition_count, 0.0f),
      center_local_movement_speed_limits_(program.partition_count, -1.0f),
      center_local_rotation_speed_limits_(program.partition_count, -1.0f),
      center_depth_inertia_(program.partition_count, 0.0f),
      center_gravity_(program.partition_count, 0.0f),
      center_gravity_directions_(program.partition_count * 3, 0.0f),
      center_gravity_falloff_(program.partition_count, 0.0f),
      center_stabilization_time_(program.partition_count, 0.0f),
      center_blend_weight_(program.partition_count, 1.0f),
      center_initial_scales_(program.partition_count * 3, 1.0f),
      center_old_world_positions_(program.partition_count * 3, 0.0f),
      center_old_world_rotations_(program.partition_count * 4, 0.0f),
      center_inertia_old_world_positions_(program.partition_count * 3, 0.0f),
      center_previous_frame_world_positions_(program.partition_count * 3, 0.0f),
      center_previous_frame_world_rotations_(program.partition_count * 4, 0.0f),
      center_frame_world_positions_(program.partition_count * 3, 0.0f),
      center_frame_world_rotations_(program.partition_count * 4, 0.0f),
      center_now_world_positions_(program.partition_count * 3, 0.0f),
      center_now_world_rotations_(program.partition_count * 4, 0.0f),
      center_shift_vectors_(program.partition_count * 3, 0.0f),
      center_shift_rotations_(program.partition_count * 4, 0.0f),
      center_shift_old_frame_positions_(program.partition_count * 3, 0.0f),
      center_shift_old_frame_rotations_(program.partition_count * 4, 0.0f),
      center_shift_now_positions_(program.partition_count * 3, 0.0f),
      center_shift_now_rotations_(program.partition_count * 4, 0.0f),
      center_shift_smoothing_velocities_(program.partition_count * 3, 0.0f),
      center_shift_teleport_flags_(program.partition_count, 0u),
      center_debug_raw_component_deltas_(program.partition_count * 3, 0.0f),
      center_debug_anchor_shift_vectors_(program.partition_count * 3, 0.0f),
      center_debug_smoothing_shift_vectors_(program.partition_count * 3, 0.0f),
      center_debug_world_shift_vectors_(program.partition_count * 3, 0.0f),
      center_debug_teleport_rotation_axes_(program.partition_count * 3, 0.0f),
      center_debug_teleport_measured_distances_(program.partition_count, 0.0f),
      center_debug_teleport_distance_thresholds_(program.partition_count, 0.0f),
      center_debug_teleport_measured_rotation_degrees_(program.partition_count, 0.0f),
      center_debug_movement_speed_limited_(program.partition_count, 0u),
      center_debug_rotation_speed_limited_(program.partition_count, 0u),
      center_anchor_inertia_(program.partition_count, 0.0f),
      center_world_inertia_(program.partition_count, 0.0f),
      center_movement_inertia_smoothing_(program.partition_count, 0.0f),
      center_movement_speed_limits_(program.partition_count, -1.0f),
      center_rotation_speed_limits_(program.partition_count, -1.0f),
      center_teleport_modes_(program.partition_count, 0),
      center_teleport_distances_(program.partition_count, 0.5f),
      center_teleport_rotations_(program.partition_count, 90.0f),
      center_step_vectors_(program.partition_count * 3, 0.0f),
      center_step_rotations_(program.partition_count * 4, 0.0f),
      center_inertia_vectors_(program.partition_count * 3, 0.0f),
      center_inertia_rotations_(program.partition_count * 4, 0.0f),
      center_rotation_axes_(program.partition_count * 3, 0.0f),
      center_gravity_ratios_(program.partition_count, 1.0f),
      center_velocity_weights_(program.partition_count, 1.0f),
      partition_reset_counts_(program.partition_count, 0),
      partition_keep_counts_(program.partition_count, 0) {
    if (program.schema_version != 1) {
        throw std::invalid_argument("unsupported MC2 CPU domain schema version");
    }
    if (particle_count_ == 0) {
        throw std::invalid_argument("MC2 CPU domain requires particles");
    }
    if (partition_count_ == 0) {
        throw std::invalid_argument("MC2 CPU domain requires partitions");
    }
    require_identity(program.domain_signature, "domain_signature");
    require_identity(program.layout_signature, "layout_signature");
    require_finite(program.bind_positions, particle_count_ * 3, "bind_positions");
    require_finite(program.bind_rotations, particle_count_ * 4, "bind_rotations");
    if (program.particle_partition_index == nullptr || program.particle_attribute_flags == nullptr) {
        throw std::invalid_argument("MC2 CPU particle metadata cannot be null");
    }
    require_finite(
        program.partition_center_local_positions,
        partition_count_ * 3,
        "partition_center_local_positions"
    );
    require_finite(
        program.partition_initial_local_gravity_directions,
        partition_count_ * 3,
        "partition_initial_local_gravity_directions"
    );
    for (std::size_t index = 0; index < particle_count_; ++index) {
        if (program.particle_partition_index[index] >= partition_count_) {
            throw std::invalid_argument("MC2 CPU particle partition is out of range");
        }
    }
    std::copy(
        program.bind_positions,
        program.bind_positions + particle_count_ * 3,
        bind_positions_.begin()
    );
    std::copy(
        program.bind_rotations,
        program.bind_rotations + particle_count_ * 4,
        bind_rotations_.begin()
    );
    std::copy(
        program.particle_partition_index,
        program.particle_partition_index + particle_count_,
        particle_partition_index_.begin()
    );
    std::copy(
        program.particle_attribute_flags,
        program.particle_attribute_flags + particle_count_,
        particle_attribute_flags_.begin()
    );
    std::copy(
        program.partition_center_local_positions,
        program.partition_center_local_positions + partition_count_ * 3,
        partition_center_local_positions_.begin()
    );
    std::copy(
        program.partition_initial_local_gravity_directions,
        program.partition_initial_local_gravity_directions + partition_count_ * 3,
        partition_initial_local_gravity_directions_.begin()
    );
    animated_base_world_positions_ = bind_positions_;
    animated_base_world_rotations_ = bind_rotations_;
    world_positions_ = bind_positions_;
    world_rotations_ = bind_rotations_;
    velocity_positions_ = world_positions_;
    whole_domain_self_engine_ = std::make_unique<hotools::Mc2WholeDomainSelfEngine>();
}

DomainV1::~DomainV1() = default;

std::unique_ptr<DomainV1> DomainV1::create_parameter_staging_domain() const {
    ensure_live();
    ProgramViewV1 program {
        1u,
        particle_count_,
        partition_count_,
        bind_positions_.data(),
        bind_rotations_.data(),
        particle_partition_index_.data(),
        particle_attribute_flags_.data(),
        partition_center_local_positions_.data(),
        partition_initial_local_gravity_directions_.data(),
        domain_signature_.c_str(),
        layout_signature_.c_str(),
    };
    return std::make_unique<DomainV1>(program);
}

void DomainV1::swap_parameter_configuration(DomainV1& staging) {
    ensure_live();
    staging.ensure_live();
    if (&staging == this || particle_count_ != staging.particle_count_ ||
        partition_count_ != staging.partition_count_ ||
        domain_signature_ != staging.domain_signature_ ||
        layout_signature_ != staging.layout_signature_) {
        throw std::invalid_argument("MC2 CPU parameter staging identity mismatch");
    }

    using std::swap;
    swap(center_local_inertia_, staging.center_local_inertia_);
    swap(center_local_movement_speed_limits_, staging.center_local_movement_speed_limits_);
    swap(center_local_rotation_speed_limits_, staging.center_local_rotation_speed_limits_);
    swap(center_depth_inertia_, staging.center_depth_inertia_);
    swap(center_gravity_, staging.center_gravity_);
    swap(center_gravity_directions_, staging.center_gravity_directions_);
    swap(center_gravity_falloff_, staging.center_gravity_falloff_);
    swap(center_stabilization_time_, staging.center_stabilization_time_);
    swap(center_blend_weight_, staging.center_blend_weight_);
    swap(center_anchor_inertia_, staging.center_anchor_inertia_);
    swap(center_world_inertia_, staging.center_world_inertia_);
    swap(center_movement_inertia_smoothing_, staging.center_movement_inertia_smoothing_);
    swap(center_movement_speed_limits_, staging.center_movement_speed_limits_);
    swap(center_rotation_speed_limits_, staging.center_rotation_speed_limits_);
    swap(center_teleport_modes_, staging.center_teleport_modes_);
    swap(center_teleport_distances_, staging.center_teleport_distances_);
    swap(center_teleport_rotations_, staging.center_teleport_rotations_);
    swap(center_ready_, staging.center_ready_);

    swap(distance_starts_, staging.distance_starts_);
    swap(distance_counts_, staging.distance_counts_);
    swap(distance_neighbors_, staging.distance_neighbors_);
    swap(distance_rest_lengths_, staging.distance_rest_lengths_);
    swap(distance_stiffness_values_, staging.distance_stiffness_values_);
    swap(distance_inverse_masses_, staging.distance_inverse_masses_);
    swap(distance_velocity_attenuation_values_, staging.distance_velocity_attenuation_values_);
    swap(distance_ready_, staging.distance_ready_);
    swap(baseline_parent_indices_, staging.baseline_parent_indices_);
    swap(baseline_line_starts_, staging.baseline_line_starts_);
    swap(baseline_line_counts_, staging.baseline_line_counts_);
    swap(baseline_line_data_, staging.baseline_line_data_);
    swap(baseline_ready_, staging.baseline_ready_);
    swap(baseline_vertex_local_positions_, staging.baseline_vertex_local_positions_);
    swap(baseline_vertex_local_rotations_, staging.baseline_vertex_local_rotations_);
    swap(baseline_pose_ready_, staging.baseline_pose_ready_);
    swap(tether_root_indices_, staging.tether_root_indices_);
    swap(tether_ready_, staging.tether_ready_);
    swap(bending_dihedral_pairs_, staging.bending_dihedral_pairs_);
    swap(bending_dihedral_rest_angles_, staging.bending_dihedral_rest_angles_);
    swap(bending_dihedral_signs_, staging.bending_dihedral_signs_);
    swap(bending_volume_pairs_, staging.bending_volume_pairs_);
    swap(bending_volume_rest_, staging.bending_volume_rest_);
    swap(bending_stiffness_values_, staging.bending_stiffness_values_);
    swap(bending_ready_, staging.bending_ready_);
    swap(inertia_depths_, staging.inertia_depths_);
    swap(inertia_inv_masses_, staging.inertia_inv_masses_);
    swap(inertia_ready_, staging.inertia_ready_);
    swap(angle_inverse_masses_, staging.angle_inverse_masses_);
    swap(bending_inverse_masses_, staging.bending_inverse_masses_);
    swap(constraint_friction_ready_, staging.constraint_friction_ready_);
    swap(integration_damping_values_, staging.integration_damping_values_);
    swap(integration_ready_, staging.integration_ready_);
    swap(collision_friction_, staging.collision_friction_);
    swap(collision_state_ready_, staging.collision_state_ready_);

    swap(compiled_external_edges_, staging.compiled_external_edges_);
    swap(compiled_external_modes_, staging.compiled_external_modes_);
    swap(compiled_external_masks_, staging.compiled_external_masks_);
    swap(compiled_external_radii_, staging.compiled_external_radii_);
    swap(compiled_external_friction_, staging.compiled_external_friction_);
    swap(compiled_external_ready_, staging.compiled_external_ready_);
    swap(whole_domain_self_edges_, staging.whole_domain_self_edges_);
    swap(whole_domain_self_points_, staging.whole_domain_self_points_);
    swap(whole_domain_self_triangles_, staging.whole_domain_self_triangles_);
    swap(whole_domain_self_modes_, staging.whole_domain_self_modes_);
    swap(whole_domain_collision_groups_, staging.whole_domain_collision_groups_);
    swap(whole_domain_collision_masks_, staging.whole_domain_collision_masks_);
    swap(whole_domain_self_friction_, staging.whole_domain_self_friction_);
    swap(whole_domain_self_thickness_, staging.whole_domain_self_thickness_);
    swap(whole_domain_self_cloth_mass_, staging.whole_domain_self_cloth_mass_);
    swap(whole_domain_self_scaled_thickness_, staging.whole_domain_self_scaled_thickness_);
    swap(
        whole_domain_self_partition_scale_ratios_,
        staging.whole_domain_self_partition_scale_ratios_
    );
    swap(whole_domain_self_engine_, staging.whole_domain_self_engine_);
    swap(whole_domain_self_ready_, staging.whole_domain_self_ready_);
}

void DomainV1::update_frame(const FrameViewV1& frame) {
    ensure_live();
    if (frame.particle_count != particle_count_) {
        throw std::invalid_argument("MC2 CPU frame particle count mismatch");
    }
    if (frame.partition_count != partition_count_) {
        throw std::invalid_argument("MC2 CPU frame partition count mismatch");
    }
    if (frame.frame < 0 || frame.generation < 0) {
        throw std::invalid_argument("MC2 CPU frame identity must be non-negative");
    }
    if (!std::isfinite(frame.frame_delta_time) || frame.frame_delta_time < 0.0f ||
        !std::isfinite(frame.simulation_delta_time) || frame.simulation_delta_time < 0.0f ||
        !std::isfinite(frame.time_scale) || frame.time_scale < 0.0f ||
        frame.skip_count < 0) {
        throw std::invalid_argument("MC2 CPU frame timing values are invalid");
    }
    validate_identity(frame.domain_signature, frame.layout_signature);
    require_finite(frame.world_positions, particle_count_ * 3, "world_positions");
    require_unit_quaternions(
        frame.world_rotations, particle_count_, "world_rotations"
    );
    require_finite(frame.world_normals, particle_count_ * 3, "world_normals");
    require_finite(
        frame.partition_world_positions, partition_count_ * 3,
        "partition_world_positions"
    );
    require_unit_quaternions(
        frame.partition_world_rotations, partition_count_,
        "partition_world_rotations"
    );
    require_finite(frame.partition_world_scales, partition_count_ * 3, "partition_world_scales");
    require_finite(frame.partition_world_linear, partition_count_ * 9, "partition_world_linear");
    require_finite(frame.anchor_world_positions, partition_count_ * 3, "anchor_world_positions");
    require_unit_quaternions(
        frame.anchor_world_rotations, partition_count_, "anchor_world_rotations"
    );
    require_finite(frame.velocity_weights, partition_count_, "velocity_weights");
    require_finite(frame.gravity_ratios, partition_count_, "gravity_ratios");
    if (frame.anchor_present == nullptr || frame.partition_frame_flags == nullptr) {
        throw std::invalid_argument("MC2 CPU partition flags cannot be null");
    }
    for (std::size_t index = 0; index < partition_count_; ++index) {
        if (frame.anchor_present[index] > 1u ||
            (frame.partition_frame_flags[index] & 3u) == 3u ||
            frame.velocity_weights[index] < 0.0f || frame.velocity_weights[index] > 1.0f ||
            frame.gravity_ratios[index] < 0.0f || frame.gravity_ratios[index] > 1.0f) {
            throw std::invalid_argument("MC2 CPU partition frame values are invalid");
        }
        for (std::size_t component = 0; component < 3; ++component) {
            if (std::fabs(frame.partition_world_scales[index * 3 + component]) <= 0.000000000001f) {
                throw std::invalid_argument("MC2 CPU partition scale cannot contain zero");
            }
        }
        const float* linear = frame.partition_world_linear + index * 9;
        const float determinant =
            linear[0] * (linear[4] * linear[8] - linear[5] * linear[7]) -
            linear[1] * (linear[3] * linear[8] - linear[5] * linear[6]) +
            linear[2] * (linear[3] * linear[7] - linear[4] * linear[6]);
        if (std::fabs(determinant) <= 0.000000000001f) {
            throw std::invalid_argument("MC2 CPU partition linear transform is singular");
        }
    }
    const bool reset_history = frame_ < 0 || generation_ != frame.generation;
    std::vector<float> next_animated_positions(
        frame.world_positions, frame.world_positions + particle_count_ * 3
    );
    std::vector<float> next_animated_rotations(
        frame.world_rotations, frame.world_rotations + particle_count_ * 4
    );
    std::vector<float> next_positions = world_positions_;
    std::vector<float> next_rotations = world_rotations_;
    std::vector<float> next_velocity_positions = velocity_positions_;
    std::vector<float> next_state_velocities = state_velocities_;
    std::vector<float> next_normals(
        frame.world_normals, frame.world_normals + particle_count_ * 3
    );
    std::vector<float> next_partition_positions(
        frame.partition_world_positions, frame.partition_world_positions + partition_count_ * 3
    );
    std::vector<float> next_partition_rotations(
        frame.partition_world_rotations, frame.partition_world_rotations + partition_count_ * 4
    );
    std::vector<float> next_partition_scales(
        frame.partition_world_scales, frame.partition_world_scales + partition_count_ * 3
    );
    std::vector<float> next_partition_linear(
        frame.partition_world_linear, frame.partition_world_linear + partition_count_ * 9
    );
    std::vector<float> next_center_frame_positions(partition_count_ * 3, 0.0f);
    std::vector<float> next_center_frame_rotations(partition_count_ * 4, 0.0f);
    std::vector<float> next_anchor_positions(
        frame.anchor_world_positions, frame.anchor_world_positions + partition_count_ * 3
    );
    std::vector<float> next_anchor_rotations(
        frame.anchor_world_rotations, frame.anchor_world_rotations + partition_count_ * 4
    );
    std::vector<float> next_previous_anchor_positions = reset_history
        ? next_anchor_positions : anchor_world_positions_;
    std::vector<float> next_previous_anchor_rotations = reset_history
        ? next_anchor_rotations : anchor_world_rotations_;
    std::vector<std::uint32_t> next_anchor_present(
        frame.anchor_present, frame.anchor_present + partition_count_
    );
    std::vector<std::uint32_t> next_frame_flags(
        frame.partition_frame_flags, frame.partition_frame_flags + partition_count_
    );
    std::vector<float> next_velocity_weights(
        frame.velocity_weights, frame.velocity_weights + partition_count_
    );
    std::vector<float> next_gravity_ratios(
        frame.gravity_ratios, frame.gravity_ratios + partition_count_
    );
    std::vector<std::int64_t> next_reset_counts = partition_reset_counts_;
    std::vector<std::int64_t> next_keep_counts = partition_keep_counts_;
    bool has_keep = false;
    for (std::size_t index = 0; index < partition_count_; ++index) {
        if ((frame.partition_frame_flags[index] & 1u) != 0u) ++next_reset_counts[index];
        if ((frame.partition_frame_flags[index] & 2u) != 0u) {
            ++next_keep_counts[index];
            has_keep = true;
        }
    }
    for (std::size_t partition = 0; partition < partition_count_; ++partition) {
        hotools::Mc2CenterPoseView center_view;
        center_view.world_positions = next_animated_positions.data();
        center_view.world_rotations = next_animated_rotations.data();
        center_view.bind_rotations = bind_rotations_.data();
        center_view.particle_partition_index = particle_partition_index_.data();
        center_view.particle_attribute_flags = particle_attribute_flags_.data();
        center_view.particle_count = static_cast<std::int64_t>(particle_count_);
        center_view.partition_index = static_cast<std::int64_t>(partition);
        std::copy_n(
            next_partition_positions.data() + partition * 3,
            3,
            center_view.component_position
        );
        std::copy_n(
            next_partition_rotations.data() + partition * 4,
            4,
            center_view.component_rotation
        );
        std::copy_n(
            next_partition_scales.data() + partition * 3,
            3,
            center_view.component_scale
        );
        if (!hotools::derive_center_world_pose_mc2(center_view)) {
            throw std::invalid_argument("MC2 CPU Center frame pose is degenerate");
        }
        std::copy_n(
            center_view.center_position,
            3,
            next_center_frame_positions.data() + partition * 3
        );
        std::copy_n(
            center_view.center_rotation,
            4,
            next_center_frame_rotations.data() + partition * 4
        );
    }
    for (std::size_t particle = 0; particle < particle_count_; ++particle) {
        const auto partition = particle_partition_index_[particle];
        const bool partition_reset =
            (frame.partition_frame_flags[partition] & 1u) != 0u;
        if (!reset_history && !partition_reset) continue;
        const auto offset = particle * 3;
        for (std::size_t component = 0; component < 3; ++component) {
            next_positions[offset + component] = next_animated_positions[offset + component];
            next_velocity_positions[offset + component] = next_animated_positions[offset + component];
            next_state_velocities[offset + component] = 0.0f;
        }
        const auto rotation_offset = particle * 4;
        std::copy_n(
            next_animated_rotations.data() + rotation_offset,
            4,
            next_rotations.data() + rotation_offset
        );
    }
    if (!reset_history && has_keep) {
        hotools::Mc2PartitionKeepTransformView keep_view;
        keep_view.positions = next_positions.data();
        keep_view.rotations = next_rotations.data();
        keep_view.velocities = next_state_velocities.data();
        keep_view.particle_partition_index = particle_partition_index_.data();
        keep_view.particle_attribute_flags = particle_attribute_flags_.data();
        keep_view.partition_frame_flags = next_frame_flags.data();
        keep_view.old_partition_positions = partition_world_positions_.data();
        keep_view.old_partition_rotations = partition_world_rotations_.data();
        keep_view.old_partition_linear = partition_world_linear_.data();
        keep_view.new_partition_positions = next_partition_positions.data();
        keep_view.new_partition_rotations = next_partition_rotations.data();
        keep_view.new_partition_linear = next_partition_linear.data();
        keep_view.particle_count = static_cast<std::int64_t>(particle_count_);
        keep_view.partition_count = static_cast<std::int64_t>(partition_count_);
        hotools::apply_partition_keep_transform_mc2(keep_view);
    }
    std::vector<float> next_previous_positions = reset_history
        ? next_partition_positions : partition_world_positions_;
    std::vector<float> next_previous_rotations = reset_history
        ? next_partition_rotations : partition_world_rotations_;
    std::vector<float> next_previous_scales = reset_history
        ? next_partition_scales : partition_world_scales_;
    std::vector<float> next_center_previous_positions = reset_history
        ? next_center_frame_positions : center_frame_world_positions_;
    std::vector<float> next_center_previous_rotations = reset_history
        ? next_center_frame_rotations : center_frame_world_rotations_;
    world_positions_.swap(next_positions);
    world_rotations_.swap(next_rotations);
    velocity_positions_.swap(next_velocity_positions);
    state_velocities_.swap(next_state_velocities);
    animated_base_world_positions_.swap(next_animated_positions);
    animated_base_world_rotations_.swap(next_animated_rotations);
    world_normals_.swap(next_normals);
    partition_previous_world_positions_.swap(next_previous_positions);
    partition_previous_world_rotations_.swap(next_previous_rotations);
    partition_previous_world_scales_.swap(next_previous_scales);
    partition_world_positions_.swap(next_partition_positions);
    partition_world_rotations_.swap(next_partition_rotations);
    partition_world_scales_.swap(next_partition_scales);
    partition_world_linear_.swap(next_partition_linear);
    center_previous_frame_world_positions_.swap(next_center_previous_positions);
    center_previous_frame_world_rotations_.swap(next_center_previous_rotations);
    center_frame_world_positions_.swap(next_center_frame_positions);
    center_frame_world_rotations_.swap(next_center_frame_rotations);
    anchor_world_positions_.swap(next_anchor_positions);
    anchor_world_rotations_.swap(next_anchor_rotations);
    anchor_previous_world_positions_.swap(next_previous_anchor_positions);
    anchor_previous_world_rotations_.swap(next_previous_anchor_rotations);
    anchor_present_.swap(next_anchor_present);
    partition_frame_flags_.swap(next_frame_flags);
    velocity_weights_.swap(next_velocity_weights);
    gravity_ratios_.swap(next_gravity_ratios);
    center_frame_shift_ready_ = false;
    center_frame_shift_consumed_ = false;
    center_inertia_pending_ = false;
    prediction_state_ready_ = false;
    substep_snapshot_ready_ = false;
    collision_state_ready_ = false;
    frame_delta_time_ = frame.frame_delta_time;
    simulation_delta_time_ = frame.simulation_delta_time;
    time_scale_ = frame.time_scale;
    skip_count_ = frame.skip_count;
    is_running_ = frame.is_running;
    if (reset_history) {
        center_initial_scales_ = partition_world_scales_;
        center_old_world_positions_ = center_frame_world_positions_;
        center_now_world_positions_ = center_frame_world_positions_;
        center_old_world_rotations_ = center_frame_world_rotations_;
        center_now_world_rotations_ = center_frame_world_rotations_;
        std::fill(center_shift_smoothing_velocities_.begin(), center_shift_smoothing_velocities_.end(), 0.0f);
        std::fill(center_shift_teleport_flags_.begin(), center_shift_teleport_flags_.end(), 0u);
        center_velocity_weights_ = velocity_weights_;
        center_ready_ = true;
    }
    partition_reset_counts_.swap(next_reset_counts);
    partition_keep_counts_.swap(next_keep_counts);
    frame_ = frame.frame;
    generation_ = frame.generation;
}

void DomainV1::configure_center(
    const float* local_inertia,
    const float* local_movement_speed_limits,
    const float* local_rotation_speed_limits,
    const float* depth_inertia,
    const float* gravity,
    const float* gravity_directions,
    const float* gravity_falloff,
    const float* stabilization_time,
    const float* blend_weight
) {
    ensure_live();
    require_finite(local_inertia, partition_count_, "local_inertia");
    require_finite(local_movement_speed_limits, partition_count_, "local_movement_speed_limits");
    require_finite(local_rotation_speed_limits, partition_count_, "local_rotation_speed_limits");
    require_finite(depth_inertia, partition_count_, "depth_inertia");
    require_finite(gravity, partition_count_, "gravity");
    require_finite(gravity_directions, partition_count_ * 3, "gravity_directions");
    require_finite(gravity_falloff, partition_count_, "gravity_falloff");
    require_finite(stabilization_time, partition_count_, "stabilization_time");
    require_finite(blend_weight, partition_count_, "blend_weight");
    for (std::size_t index = 0; index < partition_count_; ++index) {
        if (local_inertia[index] < 0.0f || local_inertia[index] > 1.0f ||
            depth_inertia[index] < 0.0f || depth_inertia[index] > 1.0f ||
            gravity[index] < 0.0f || gravity_falloff[index] < 0.0f ||
            stabilization_time[index] < 0.0f || blend_weight[index] < 0.0f ||
            blend_weight[index] > 1.0f) {
            throw std::invalid_argument("MC2 CPU Center parameters are invalid");
        }
    }
    std::copy(local_inertia, local_inertia + partition_count_, center_local_inertia_.begin());
    std::copy(
        local_movement_speed_limits,
        local_movement_speed_limits + partition_count_,
        center_local_movement_speed_limits_.begin()
    );
    std::copy(
        local_rotation_speed_limits,
        local_rotation_speed_limits + partition_count_,
        center_local_rotation_speed_limits_.begin()
    );
    std::copy(depth_inertia, depth_inertia + partition_count_, center_depth_inertia_.begin());
    std::copy(gravity, gravity + partition_count_, center_gravity_.begin());
    std::copy(
        gravity_directions,
        gravity_directions + partition_count_ * 3,
        center_gravity_directions_.begin()
    );
    std::copy(gravity_falloff, gravity_falloff + partition_count_, center_gravity_falloff_.begin());
    std::copy(stabilization_time, stabilization_time + partition_count_, center_stabilization_time_.begin());
    std::copy(blend_weight, blend_weight + partition_count_, center_blend_weight_.begin());
    center_ready_ = true;
}

void DomainV1::configure_center_frame_shift(
    const float* anchor_inertia,
    const float* world_inertia,
    const float* movement_inertia_smoothing,
    const float* movement_speed_limits,
    const float* rotation_speed_limits,
    const std::int32_t* teleport_modes,
    const float* teleport_distances,
    const float* teleport_rotations
) {
    ensure_live();
    require_finite(anchor_inertia, partition_count_, "Center anchor inertia");
    require_finite(world_inertia, partition_count_, "Center world inertia");
    require_finite(
        movement_inertia_smoothing, partition_count_, "Center movement smoothing"
    );
    require_finite(movement_speed_limits, partition_count_, "Center movement speed limits");
    require_finite(rotation_speed_limits, partition_count_, "Center rotation speed limits");
    require_finite(teleport_distances, partition_count_, "Center teleport distances");
    require_finite(teleport_rotations, partition_count_, "Center teleport rotations");
    if (anchor_inertia == nullptr || world_inertia == nullptr ||
        movement_inertia_smoothing == nullptr || movement_speed_limits == nullptr ||
        rotation_speed_limits == nullptr || teleport_modes == nullptr ||
        teleport_distances == nullptr || teleport_rotations == nullptr) {
        throw std::invalid_argument("MC2 CPU Center frame-shift parameters cannot be null");
    }
    for (std::size_t partition = 0; partition < partition_count_; ++partition) {
        if (anchor_inertia[partition] < 0.0f || anchor_inertia[partition] > 1.0f ||
            world_inertia[partition] < 0.0f || world_inertia[partition] > 1.0f ||
            movement_inertia_smoothing[partition] < 0.0f ||
            movement_inertia_smoothing[partition] > 1.0f ||
            teleport_modes[partition] < 0 || teleport_modes[partition] > 2 ||
            teleport_distances[partition] < 0.0f || teleport_rotations[partition] < 0.0f) {
            throw std::invalid_argument("MC2 CPU Center frame-shift parameters are invalid");
        }
    }
    std::copy(anchor_inertia, anchor_inertia + partition_count_, center_anchor_inertia_.begin());
    std::copy(world_inertia, world_inertia + partition_count_, center_world_inertia_.begin());
    std::copy(
        movement_inertia_smoothing,
        movement_inertia_smoothing + partition_count_,
        center_movement_inertia_smoothing_.begin()
    );
    std::copy(
        movement_speed_limits,
        movement_speed_limits + partition_count_,
        center_movement_speed_limits_.begin()
    );
    std::copy(
        rotation_speed_limits,
        rotation_speed_limits + partition_count_,
        center_rotation_speed_limits_.begin()
    );
    std::copy(teleport_modes, teleport_modes + partition_count_, center_teleport_modes_.begin());
    std::copy(
        teleport_distances,
        teleport_distances + partition_count_,
        center_teleport_distances_.begin()
    );
    std::copy(
        teleport_rotations,
        teleport_rotations + partition_count_,
        center_teleport_rotations_.begin()
    );
}

void DomainV1::step_center_frame_shift(const float* anchor_component_local_positions) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0 || !center_ready_) {
        throw std::logic_error("MC2 CPU Center frame shift requires frame and configuration");
    }
    require_finite(
        anchor_component_local_positions,
        partition_count_ * 3,
        "Center anchor component local positions"
    );
    if (anchor_component_local_positions == nullptr) {
        throw std::invalid_argument("MC2 CPU Center anchor local positions cannot be null");
    }
    if (center_frame_shift_consumed_) {
        return;
    }
    std::vector<float> next_shift_vectors(partition_count_ * 3, 0.0f);
    std::vector<float> next_shift_rotations(partition_count_ * 4, 0.0f);
    std::vector<float> next_shift_old_frame_positions(partition_count_ * 3, 0.0f);
    std::vector<float> next_shift_old_frame_rotations(partition_count_ * 4, 0.0f);
    std::vector<float> next_shift_now_positions(partition_count_ * 3, 0.0f);
    std::vector<float> next_shift_now_rotations(partition_count_ * 4, 0.0f);
    std::vector<float> next_smoothing_velocities = center_shift_smoothing_velocities_;
    std::vector<std::uint32_t> next_teleport_flags(partition_count_, 0u);
    std::vector<float> next_raw_component_deltas(partition_count_ * 3, 0.0f);
    std::vector<float> next_anchor_shift_vectors(partition_count_ * 3, 0.0f);
    std::vector<float> next_smoothing_shift_vectors(partition_count_ * 3, 0.0f);
    std::vector<float> next_world_shift_vectors(partition_count_ * 3, 0.0f);
    std::vector<float> next_teleport_rotation_axes(partition_count_ * 3, 0.0f);
    std::vector<float> next_teleport_measured_distances(partition_count_, 0.0f);
    std::vector<float> next_teleport_distance_thresholds(partition_count_, 0.0f);
    std::vector<float> next_teleport_measured_rotation_degrees(partition_count_, 0.0f);
    std::vector<std::uint8_t> next_movement_speed_limited(partition_count_, 0u);
    std::vector<std::uint8_t> next_rotation_speed_limited(partition_count_, 0u);
    for (std::size_t partition = 0; partition < partition_count_; ++partition) {
        const auto position_offset = partition * 3;
        const auto rotation_offset = partition * 4;
        hotools::Mc2CenterFrameShiftView view;
        view.old_component_position = partition_previous_world_positions_.data() + position_offset;
        view.component_position = partition_world_positions_.data() + position_offset;
        view.old_component_rotation = partition_previous_world_rotations_.data() + rotation_offset;
        view.component_rotation = partition_world_rotations_.data() + rotation_offset;
        view.component_scale = partition_world_scales_.data() + position_offset;
        view.initial_scale = center_initial_scales_.data() + position_offset;
        view.frame_world_position = center_frame_world_positions_.data() + position_offset;
        view.frame_world_rotation = center_frame_world_rotations_.data() + rotation_offset;
        view.old_frame_world_position = center_previous_frame_world_positions_.data() + position_offset;
        view.old_frame_world_rotation = center_previous_frame_world_rotations_.data() + rotation_offset;
        view.now_world_position = center_now_world_positions_.data() + position_offset;
        view.now_world_rotation = center_now_world_rotations_.data() + rotation_offset;
        view.old_anchor_position = anchor_previous_world_positions_.data() + position_offset;
        view.old_anchor_rotation = anchor_previous_world_rotations_.data() + rotation_offset;
        view.anchor_position = anchor_world_positions_.data() + position_offset;
        view.anchor_rotation = anchor_world_rotations_.data() + rotation_offset;
        view.anchor_component_local_position = anchor_component_local_positions + position_offset;
        view.smoothing_velocity = center_shift_smoothing_velocities_.data() + position_offset;
        view.use_anchor = anchor_present_[partition] != 0u;
        view.is_running = is_running_;
        view.anchor_inertia = center_anchor_inertia_[partition];
        view.world_inertia = center_world_inertia_[partition];
        view.movement_speed_limit = center_movement_speed_limits_[partition];
        view.rotation_speed_limit = center_rotation_speed_limits_[partition];
        view.movement_inertia_smoothing = center_movement_inertia_smoothing_[partition];
        view.frame_delta_time = frame_delta_time_;
        view.simulation_delta_time = simulation_delta_time_;
        view.time_scale = time_scale_;
        view.skip_count = skip_count_;
        view.velocity_weight = velocity_weights_[partition];
        view.teleport_mode = center_teleport_modes_[partition];
        view.teleport_distance = center_teleport_distances_[partition];
        view.teleport_rotation = center_teleport_rotations_[partition];
        if (!hotools::evaluate_center_frame_shift_mc2(view)) {
            throw std::runtime_error("MC2 CPU Center frame shift rejected the frame");
        }
        std::copy_n(view.frame_component_shift_vector, 3, next_shift_vectors.data() + position_offset);
        std::copy_n(view.frame_component_shift_rotation, 4, next_shift_rotations.data() + rotation_offset);
        std::copy_n(view.shifted_old_frame_position, 3, next_shift_old_frame_positions.data() + position_offset);
        std::copy_n(view.shifted_old_frame_rotation, 4, next_shift_old_frame_rotations.data() + rotation_offset);
        std::copy_n(view.shifted_now_position, 3, next_shift_now_positions.data() + position_offset);
        std::copy_n(view.shifted_now_rotation, 4, next_shift_now_rotations.data() + rotation_offset);
        std::copy_n(view.smoothing_velocity_output, 3, next_smoothing_velocities.data() + position_offset);
        std::copy_n(view.raw_component_delta, 3, next_raw_component_deltas.data() + position_offset);
        std::copy_n(view.anchor_shift_vector, 3, next_anchor_shift_vectors.data() + position_offset);
        std::copy_n(view.smoothing_shift_vector, 3, next_smoothing_shift_vectors.data() + position_offset);
        std::copy_n(view.world_shift_vector, 3, next_world_shift_vectors.data() + position_offset);
        std::copy_n(view.teleport_rotation_axis, 3, next_teleport_rotation_axes.data() + position_offset);
        next_teleport_measured_distances[partition] = view.teleport_measured_distance;
        next_teleport_distance_thresholds[partition] = view.teleport_distance_threshold;
        next_teleport_measured_rotation_degrees[partition] =
            view.teleport_measured_rotation_degrees;
        next_movement_speed_limited[partition] =
            view.movement_speed_limited ? 1u : 0u;
        next_rotation_speed_limited[partition] =
            view.rotation_speed_limited ? 1u : 0u;
        next_teleport_flags[partition] =
            (view.teleport_triggered ? 1u : 0u) |
            (view.keep_teleport ? 2u : 0u) |
            (view.reset_teleport ? 4u : 0u);
    }
    std::vector<float> next_world_positions = world_positions_;
    std::vector<float> next_world_rotations = world_rotations_;
    std::vector<float> next_velocity_positions = velocity_positions_;
    std::vector<float> next_state_velocities = state_velocities_;
    std::vector<std::uint8_t> partition_apply_flags(partition_count_, 1u);
    for (std::size_t partition = 0; partition < partition_count_; ++partition) {
        if ((next_teleport_flags[partition] & 4u) != 0u) {
            partition_apply_flags[partition] = 0u;
        }
    }
    hotools::Mc2ParticleFrameShiftView particle_shift;
    particle_shift.positions = next_world_positions.data();
    particle_shift.rotations = next_world_rotations.data();
    particle_shift.velocity_positions = next_velocity_positions.data();
    particle_shift.velocities = next_state_velocities.data();
    particle_shift.particle_partition_index = particle_partition_index_.data();
    particle_shift.partition_apply_flags = partition_apply_flags.data();
    particle_shift.pivots = partition_previous_world_positions_.data();
    particle_shift.shift_vectors = next_shift_vectors.data();
    particle_shift.shift_rotations = next_shift_rotations.data();
    particle_shift.vertex_count = static_cast<std::int64_t>(particle_count_);
    particle_shift.partition_count = static_cast<std::int64_t>(partition_count_);
    if (!hotools::apply_particle_frame_shift_mc2(particle_shift)) {
        throw std::runtime_error("MC2 CPU Center particle frame shift rejected the domain state");
    }
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        const auto partition = static_cast<std::size_t>(particle_partition_index_[vertex]);
        if ((next_teleport_flags[partition] & 4u) == 0u) continue;
        const auto position_offset = vertex * 3;
        const auto rotation_offset = vertex * 4;
        std::copy_n(
            animated_base_world_positions_.data() + position_offset,
            3,
            next_world_positions.data() + position_offset
        );
        std::copy_n(
            animated_base_world_positions_.data() + position_offset,
            3,
            next_velocity_positions.data() + position_offset
        );
        std::fill_n(next_state_velocities.data() + position_offset, 3, 0.0f);
        std::copy_n(
            animated_base_world_rotations_.data() + rotation_offset,
            4,
            next_world_rotations.data() + rotation_offset
        );
    }
    world_positions_.swap(next_world_positions);
    world_rotations_.swap(next_world_rotations);
    velocity_positions_.swap(next_velocity_positions);
    state_velocities_.swap(next_state_velocities);
    center_shift_vectors_.swap(next_shift_vectors);
    center_shift_rotations_.swap(next_shift_rotations);
    center_shift_old_frame_positions_.swap(next_shift_old_frame_positions);
    center_shift_old_frame_rotations_.swap(next_shift_old_frame_rotations);
    center_shift_now_positions_.swap(next_shift_now_positions);
    center_shift_now_rotations_.swap(next_shift_now_rotations);
    center_shift_smoothing_velocities_.swap(next_smoothing_velocities);
    center_shift_teleport_flags_.swap(next_teleport_flags);
    center_debug_raw_component_deltas_.swap(next_raw_component_deltas);
    center_debug_anchor_shift_vectors_.swap(next_anchor_shift_vectors);
    center_debug_smoothing_shift_vectors_.swap(next_smoothing_shift_vectors);
    center_debug_world_shift_vectors_.swap(next_world_shift_vectors);
    center_debug_teleport_rotation_axes_.swap(next_teleport_rotation_axes);
    center_debug_teleport_measured_distances_.swap(next_teleport_measured_distances);
    center_debug_teleport_distance_thresholds_.swap(next_teleport_distance_thresholds);
    center_debug_teleport_measured_rotation_degrees_.swap(
        next_teleport_measured_rotation_degrees
    );
    center_debug_movement_speed_limited_.swap(next_movement_speed_limited);
    center_debug_rotation_speed_limited_.swap(next_rotation_speed_limited);
    center_frame_shift_ready_ = true;
    center_frame_shift_consumed_ = true;
    ++center_shift_count_;
}

void DomainV1::step_center(
    float dt,
    float frame_interpolation,
    const float* distance_weights
) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0 || !center_ready_) {
        throw std::logic_error("MC2 CPU Center step requires frame and configuration");
    }
    if (!std::isfinite(dt) || dt <= 0.0f || !std::isfinite(frame_interpolation) ||
        frame_interpolation < 0.0f || frame_interpolation > 1.0f) {
        throw std::invalid_argument("MC2 CPU Center step values are invalid");
    }
    require_finite(distance_weights, partition_count_, "distance_weights");
    for (std::size_t partition = 0; partition < partition_count_; ++partition) {
        hotools::Mc2CenterStepView view;
        const auto position_offset = partition * 3;
        const auto rotation_offset = partition * 4;
        const bool reset_teleport = center_frame_shift_ready_ &&
            (center_shift_teleport_flags_[partition] & 4u) != 0u;
        std::copy_n(
            (reset_teleport
                ? center_frame_world_positions_.data()
                : center_frame_shift_ready_
                ? center_shift_old_frame_positions_.data()
                : center_previous_frame_world_positions_.data()) + position_offset,
            3,
            view.old_frame_world_position
        );
        std::copy_n(
            center_frame_world_positions_.data() + position_offset,
            3,
            view.frame_world_position
        );
        std::copy_n(
            (reset_teleport
                ? center_frame_world_rotations_.data()
                : center_frame_shift_ready_
                ? center_shift_old_frame_rotations_.data()
                : center_previous_frame_world_rotations_.data()) + rotation_offset,
            4,
            view.old_frame_world_rotation
        );
        std::copy_n(
            center_frame_world_rotations_.data() + rotation_offset,
            4,
            view.frame_world_rotation
        );
        std::copy_n(
            partition_world_scales_.data() + position_offset,
            3,
            view.frame_world_scale
        );
        std::copy_n(
            partition_previous_world_scales_.data() + position_offset,
            3,
            view.old_frame_world_scale
        );
        std::copy_n(
            center_initial_scales_.data() + position_offset,
            3,
            view.initial_scale
        );
        std::copy_n(
            (reset_teleport
                ? center_frame_world_positions_.data()
                : center_frame_shift_ready_
                ? center_shift_now_positions_.data()
                : center_old_world_positions_.data()) + position_offset,
            3,
            view.old_world_position
        );
        std::copy_n(
            (reset_teleport
                ? center_frame_world_rotations_.data()
                : center_frame_shift_ready_
                ? center_shift_now_rotations_.data()
                : center_old_world_rotations_.data()) + rotation_offset,
            4,
            view.old_world_rotation
        );
        std::copy_n(
            view.old_world_position,
            3,
            center_inertia_old_world_positions_.data() + position_offset
        );
        std::copy_n(
            partition_initial_local_gravity_directions_.data() + position_offset,
            3,
            view.initial_local_gravity_direction
        );
        std::copy_n(
            center_gravity_directions_.data() + position_offset,
            3,
            view.world_gravity
        );
        view.dt = dt;
        view.frame_interpolation = frame_interpolation;
        view.distance_weight = distance_weights[partition];
        view.velocity_weight = center_velocity_weights_[partition];
        view.local_inertia = center_local_inertia_[partition];
        view.local_movement_speed_limit = center_local_movement_speed_limits_[partition];
        view.local_rotation_speed_limit = center_local_rotation_speed_limits_[partition];
        view.gravity = center_gravity_[partition];
        view.gravity_falloff = center_gravity_falloff_[partition];
        view.stabilization_time = center_stabilization_time_[partition];
        view.blend_weight = center_blend_weight_[partition];
        if (!hotools::evaluate_center_step_mc2(view)) {
            throw std::runtime_error("MC2 CPU Center evaluator rejected the frame");
        }
        std::copy_n(view.now_world_position, 3, center_now_world_positions_.data() + position_offset);
        std::copy_n(view.now_world_rotation, 4, center_now_world_rotations_.data() + rotation_offset);
        std::copy_n(view.step_vector, 3, center_step_vectors_.data() + position_offset);
        std::copy_n(view.step_rotation, 4, center_step_rotations_.data() + rotation_offset);
        std::copy_n(view.inertia_vector, 3, center_inertia_vectors_.data() + position_offset);
        std::copy_n(view.inertia_rotation, 4, center_inertia_rotations_.data() + rotation_offset);
        std::copy_n(view.rotation_axis, 3, center_rotation_axes_.data() + position_offset);
        center_gravity_ratios_[partition] = view.gravity_ratio;
        center_velocity_weights_[partition] = view.output_velocity_weight;
    }
    center_old_world_positions_ = center_now_world_positions_;
    center_old_world_rotations_ = center_now_world_rotations_;
    center_frame_shift_ready_ = false;
    center_inertia_pending_ = true;
    ++center_step_count_;
}

void DomainV1::step_center_inertia() {
    ensure_live();
    if (frame_ < 0 || generation_ < 0 || !center_ready_ || !inertia_ready_ ||
        !center_inertia_pending_) {
        throw std::logic_error(
            "MC2 CPU Center inertia requires frame, Center, particle, and Center-step state"
        );
    }

    prepare_prediction_state();
    hotools::Mc2PartitionedSubstepInertiaView view;
    view.positions = world_positions_.data();
    view.velocity_positions = velocity_positions_.data();
    view.velocities = state_velocities_.data();
    view.depths = inertia_depths_.data();
    view.inv_masses = inertia_inv_masses_.data();
    view.particle_partition_index = particle_partition_index_.data();
    view.old_world_positions = center_inertia_old_world_positions_.data();
    view.step_vectors = center_step_vectors_.data();
    view.step_rotations = center_step_rotations_.data();
    view.inertia_vectors = center_inertia_vectors_.data();
    view.inertia_rotations = center_inertia_rotations_.data();
    view.depth_inertia = center_depth_inertia_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.partition_count = static_cast<std::int64_t>(partition_count_);
    if (!hotools::apply_partitioned_substep_inertia_mc2(view)) {
        throw std::runtime_error("MC2 CPU Center inertia rejected the domain state");
    }
    center_inertia_pending_ = false;
    ++step_count_;
}

void DomainV1::prepare_prediction_state() {
    // V0 snapshots the pre-prediction position at the start of every substep.
    velocity_positions_ = world_positions_;
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if ((particle_attribute_flags_[vertex] & 0x01u) == 0u) continue;
        const auto position_offset = vertex * 3;
        const auto rotation_offset = vertex * 4;
        std::copy_n(
            animated_base_world_positions_.data() + position_offset,
            3,
            world_positions_.data() + position_offset
        );
        std::copy_n(
            animated_base_world_positions_.data() + position_offset,
            3,
            velocity_positions_.data() + position_offset
        );
        std::fill_n(state_velocities_.data() + position_offset, 3, 0.0f);
        std::copy_n(
            animated_base_world_rotations_.data() + rotation_offset,
            4,
            world_rotations_.data() + rotation_offset
        );
    }
    substep_old_positions_ = world_positions_;
    prediction_state_ready_ = true;
    substep_snapshot_ready_ = true;
}

void DomainV1::step() {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU domain step requires update_frame");
    }
    // E3 data-path slice: numerical integration/constraints are intentionally
    // not claimed here; the owner currently preserves the frame positions.
    ++step_count_;
}

void DomainV1::begin_constraint_debug(std::uint32_t mask) {
    ensure_live();
    constexpr std::uint32_t supported = kConstraintDebugAngle | kConstraintDebugMotion;
    if (mask == 0u || (mask & ~supported) != 0u) {
        throw std::invalid_argument("MC2 CPU constraint debug mask is invalid");
    }
    if ((mask & kConstraintDebugAngle) != 0u && !baseline_ready_) {
        throw std::logic_error("MC2 CPU Angle debug requires baseline configuration");
    }
    clear_constraint_debug();
    if ((mask & kConstraintDebugMotion) != 0u) {
        const auto records = particle_count_ * 2;
        motion_debug_origins_.assign(records * 3, 0.0f);
        motion_debug_targets_.assign(records * 3, 0.0f);
        motion_debug_corrections_.assign(records * 3, 0.0f);
        motion_debug_limits_.assign(records, 0.0f);
        motion_debug_valid_.assign(records, 0u);
    }
    if ((mask & kConstraintDebugAngle) != 0u) {
        const auto records = baseline_line_data_.size() * 2 * 3;
        angle_debug_origins_.assign(records * 2 * 3, 0.0f);
        angle_debug_targets_.assign(records * 3, 0.0f);
        angle_debug_target_vectors_.assign(records * 3, 0.0f);
        angle_debug_corrections_.assign(records * 2 * 3, 0.0f);
        angle_debug_currents_.assign(records, 0.0f);
        angle_debug_limits_.assign(records, 0.0f);
        angle_debug_valid_.assign(records, 0u);
    }
    constraint_debug_active_mask_ = mask;
}

void DomainV1::end_constraint_debug() {
    ensure_live();
    constraint_debug_captured_mask_ = constraint_debug_active_mask_;
    constraint_debug_active_mask_ = 0u;
}

void DomainV1::clear_constraint_debug() {
    ensure_live();
    constraint_debug_active_mask_ = 0u;
    constraint_debug_captured_mask_ = 0u;
    std::vector<float>().swap(motion_debug_origins_);
    std::vector<float>().swap(motion_debug_targets_);
    std::vector<float>().swap(motion_debug_corrections_);
    std::vector<float>().swap(motion_debug_limits_);
    std::vector<std::uint8_t>().swap(motion_debug_valid_);
    std::vector<float>().swap(angle_debug_origins_);
    std::vector<float>().swap(angle_debug_targets_);
    std::vector<float>().swap(angle_debug_target_vectors_);
    std::vector<float>().swap(angle_debug_corrections_);
    std::vector<float>().swap(angle_debug_currents_);
    std::vector<float>().swap(angle_debug_limits_);
    std::vector<std::uint8_t>().swap(angle_debug_valid_);
}

void DomainV1::configure_distance(
    const std::int32_t* starts,
    const std::int32_t* counts,
    const std::int32_t* neighbors,
    const float* rest_lengths,
    const float* stiffness_values,
    const float* depth_values,
    const float* friction_values,
    const float* velocity_attenuation_values,
    std::size_t neighbor_count
) {
    ensure_live();
    if (starts == nullptr || counts == nullptr || depth_values == nullptr ||
        friction_values == nullptr || velocity_attenuation_values == nullptr ||
        (neighbor_count != 0 && (neighbors == nullptr || rest_lengths == nullptr || stiffness_values == nullptr))) {
        throw std::invalid_argument("MC2 CPU distance arrays cannot be null");
    }
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if (starts[vertex] < 0 || counts[vertex] < 0 ||
            static_cast<std::size_t>(starts[vertex]) + static_cast<std::size_t>(counts[vertex]) > neighbor_count) {
            throw std::invalid_argument("MC2 CPU distance CSR range is invalid");
        }
    }
    for (std::size_t index = 0; index < neighbor_count; ++index) {
        if (neighbors[index] < 0 || static_cast<std::size_t>(neighbors[index]) >= particle_count_) {
            throw std::invalid_argument("MC2 CPU distance neighbor is out of range");
        }
        if (!std::isfinite(rest_lengths[index]) || !std::isfinite(stiffness_values[index])) {
            throw std::invalid_argument("MC2 CPU distance values must be finite");
        }
    }
    distance_inverse_masses_.resize(particle_count_);
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        const float depth = depth_values[vertex];
        const float friction = friction_values[vertex];
        const float velocity_attenuation = velocity_attenuation_values[vertex];
        if (!std::isfinite(depth) || depth < 0.0f || depth > 1.0f ||
            !std::isfinite(friction) || friction < 0.0f ||
            !std::isfinite(velocity_attenuation) || velocity_attenuation < 0.0f ||
            velocity_attenuation > 1.0f) {
            throw std::invalid_argument("MC2 CPU distance particle values are invalid");
        }
        if ((particle_attribute_flags_[vertex] & 0x01u) != 0u) {
            distance_inverse_masses_[vertex] = 0.0f;
            continue;
        }
        const float depth_delta = 1.0f - depth;
        distance_inverse_masses_[vertex] = 1.0f /
            (1.0f + friction * kDistanceFrictionMass + depth_delta * depth_delta * 5.0f);
    }
    distance_starts_.assign(starts, starts + particle_count_);
    distance_counts_.assign(counts, counts + particle_count_);
    distance_neighbors_.assign(neighbors, neighbors + neighbor_count);
    distance_rest_lengths_.assign(rest_lengths, rest_lengths + neighbor_count);
    distance_stiffness_values_.assign(stiffness_values, stiffness_values + neighbor_count);
    distance_velocity_attenuation_values_.assign(
        velocity_attenuation_values, velocity_attenuation_values + particle_count_
    );
    distance_ready_ = true;
}

void DomainV1::step_distance(float simulation_power) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU distance step requires update_frame");
    }
    if (!distance_ready_) {
        throw std::logic_error("MC2 CPU distance step requires configure_distance");
    }
    if (!std::isfinite(simulation_power) || simulation_power < 0.0f) {
        throw std::invalid_argument("MC2 CPU distance simulation power is invalid");
    }
    hotools::Mc2NeighborConstraintView view;
    view.positions = world_positions_.data();
    view.base_positions = step_basic_positions_.data();
    view.inv_masses = distance_inverse_masses_.data();
    view.starts = distance_starts_.data();
    view.counts = distance_counts_.data();
    view.neighbors = distance_neighbors_.data();
    view.rest_lengths = distance_rest_lengths_.data();
    view.stiffness_values = distance_stiffness_values_.data();
    view.velocity_positions = velocity_positions_.data();
    view.velocity_attenuation_values = distance_velocity_attenuation_values_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.neighbor_count = static_cast<std::int64_t>(distance_neighbors_.size());
    view.simulation_power = simulation_power;
    hotools::project_neighbor_constraints_mc2(view);
    ++step_count_;
}

void DomainV1::configure_baseline(
    const std::int32_t* parent_indices,
    const std::int32_t* line_starts,
    const std::int32_t* line_counts,
    std::size_t line_count,
    const std::int32_t* line_data,
    std::size_t data_count
) {
    ensure_live();
    if (parent_indices == nullptr ||
        (line_count != 0 && (line_starts == nullptr || line_counts == nullptr)) ||
        (data_count != 0 && line_data == nullptr)) {
        throw std::invalid_argument("MC2 CPU baseline arrays cannot be null");
    }
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        const auto parent = parent_indices[vertex];
        if (parent < -1 || (parent >= 0 && static_cast<std::size_t>(parent) >= particle_count_)) {
            throw std::invalid_argument("MC2 CPU baseline parent is out of range");
        }
    }
    for (std::size_t line = 0; line < line_count; ++line) {
        const auto start = line_starts[line];
        const auto count = line_counts[line];
        if (start < 0 || count < 0 ||
            static_cast<std::size_t>(start) + static_cast<std::size_t>(count) > data_count) {
            throw std::invalid_argument("MC2 CPU baseline line range is invalid");
        }
    }
    for (std::size_t index = 0; index < data_count; ++index) {
        if (line_data[index] < 0 || static_cast<std::size_t>(line_data[index]) >= particle_count_) {
            throw std::invalid_argument("MC2 CPU baseline line vertex is out of range");
        }
    }
    baseline_parent_indices_.assign(parent_indices, parent_indices + particle_count_);
    if (line_count != 0) {
        baseline_line_starts_.assign(line_starts, line_starts + line_count);
        baseline_line_counts_.assign(line_counts, line_counts + line_count);
    } else {
        baseline_line_starts_.clear();
        baseline_line_counts_.clear();
    }
    if (data_count != 0) {
        baseline_line_data_.assign(line_data, line_data + data_count);
    } else {
        baseline_line_data_.clear();
    }
    baseline_ready_ = true;
}

void DomainV1::configure_baseline_pose(
    const float* vertex_local_positions,
    const float* vertex_local_rotations
) {
    ensure_live();
    require_finite(
        vertex_local_positions, particle_count_ * 3,
        "baseline vertex local positions"
    );
    require_finite(
        vertex_local_rotations, particle_count_ * 4,
        "baseline vertex local rotations"
    );
    if (!baseline_ready_) {
        throw std::logic_error(
            "MC2 CPU baseline local pose requires baseline topology first"
        );
    }
    for (const auto vertex : baseline_line_data_) {
        const float* rotation = vertex_local_rotations + static_cast<std::size_t>(vertex) * 4;
        const float length_squared =
            rotation[0] * rotation[0] + rotation[1] * rotation[1] +
            rotation[2] * rotation[2] + rotation[3] * rotation[3];
        if (!std::isfinite(length_squared) || std::fabs(length_squared - 1.0f) > 1.0e-4f) {
            throw std::invalid_argument(
                "active baseline vertex local rotations must be unit quaternions"
            );
        }
    }
    baseline_vertex_local_positions_.assign(
        vertex_local_positions, vertex_local_positions + particle_count_ * 3
    );
    baseline_vertex_local_rotations_.assign(
        vertex_local_rotations, vertex_local_rotations + particle_count_ * 4
    );
    baseline_pose_ready_ = true;
}

void DomainV1::prepare_step_basic_pose(float animation_pose_ratio) {
    if (!std::isfinite(animation_pose_ratio) ||
        animation_pose_ratio < 0.0f || animation_pose_ratio > 1.0f) {
        throw std::invalid_argument("MC2 CPU animation pose ratio is invalid");
    }
    std::vector<float> ratios(partition_count_, animation_pose_ratio);
    prepare_step_basic_pose_partitioned(ratios.data());
}

void DomainV1::prepare_step_basic_pose_partitioned(const float* animation_pose_ratios) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU StepBasic pose requires update_frame");
    }
    if (!baseline_ready_ || !baseline_pose_ready_) {
        throw std::logic_error(
            "MC2 CPU StepBasic pose requires baseline topology and local pose"
        );
    }
    require_finite(
        animation_pose_ratios, partition_count_, "animation_pose_ratios"
    );
    for (std::size_t partition = 0; partition < partition_count_; ++partition) {
        if (animation_pose_ratios[partition] < 0.0f ||
            animation_pose_ratios[partition] > 1.0f) {
            throw std::invalid_argument("MC2 CPU animation pose ratio is invalid");
        }
    }
    hotools::Mc2StepBasicPoseView view;
    view.base_positions = animated_base_world_positions_.data();
    view.base_rotations = animated_base_world_rotations_.data();
    view.parent_indices = baseline_parent_indices_.data();
    view.baseline_start = baseline_line_starts_.data();
    view.baseline_count = baseline_line_counts_.data();
    view.baseline_data = baseline_line_data_.data();
    view.vertex_local_positions = baseline_vertex_local_positions_.data();
    view.vertex_local_rotations = baseline_vertex_local_rotations_.data();
    view.step_positions = step_basic_positions_.data();
    view.step_rotations = step_basic_rotations_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.line_count = static_cast<std::int64_t>(baseline_line_starts_.size());
    view.baseline_data_count = static_cast<std::int64_t>(baseline_line_data_.size());
    view.particle_partition_index = particle_partition_index_.data();
    view.partition_animation_pose_ratios = animation_pose_ratios;
    view.partition_count = static_cast<std::int64_t>(partition_count_);
    hotools::update_step_basic_pose_mc2(view);
    ++step_count_;
}

void DomainV1::configure_tether(const std::int32_t* root_indices) {
    ensure_live();
    if (root_indices == nullptr) {
        throw std::invalid_argument("MC2 CPU tether root indices cannot be null");
    }
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        const auto root = root_indices[vertex];
        if (root < -1 || (root >= 0 && static_cast<std::size_t>(root) >= particle_count_)) {
            throw std::invalid_argument("MC2 CPU tether root index is out of range");
        }
    }
    tether_root_indices_.assign(root_indices, root_indices + particle_count_);
    tether_ready_ = true;
}

void DomainV1::step_tether(
    const float* step_basic_positions,
    float compression,
    float stretch
) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU tether step requires update_frame");
    }
    if (!tether_ready_ || !inertia_ready_) {
        throw std::logic_error("MC2 CPU tether step requires topology and particle configuration");
    }
    require_finite(step_basic_positions, particle_count_ * 3, "tether StepBasic positions");
    if (!std::isfinite(compression) || compression < 0.0f || compression > 1.0f ||
        !std::isfinite(stretch) || stretch < 0.0f) {
        throw std::invalid_argument("MC2 CPU tether limits are invalid");
    }
    std::vector<float> rest_lengths(particle_count_, 0.0f);
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        const auto root = tether_root_indices_[vertex];
        if (root < 0) continue;
        const auto offset = vertex * 3;
        const auto root_offset = static_cast<std::size_t>(root) * 3;
        const float dx = step_basic_positions[root_offset + 0] - step_basic_positions[offset + 0];
        const float dy = step_basic_positions[root_offset + 1] - step_basic_positions[offset + 1];
        const float dz = step_basic_positions[root_offset + 2] - step_basic_positions[offset + 2];
        rest_lengths[vertex] = std::sqrt(dx * dx + dy * dy + dz * dz);
    }
    hotools::Mc2TetherConstraintView view;
    view.positions = world_positions_.data();
    view.inv_masses = inertia_inv_masses_.data();
    view.root_indices = tether_root_indices_.data();
    view.root_rest_lengths = rest_lengths.data();
    view.velocity_positions = velocity_positions_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.stiffness = 1.0f;
    view.compression = compression;
    view.stretch = stretch;
    hotools::project_tether_mc2(view);
    ++step_count_;
}

void DomainV1::step_tether_partitioned(
    const float* step_basic_positions,
    const float* compression_values,
    const float* stretch_values
) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU partitioned tether step requires update_frame");
    }
    if (!tether_ready_ || !inertia_ready_) {
        throw std::logic_error("MC2 CPU partitioned tether step requires particle configuration");
    }
    require_finite(step_basic_positions, particle_count_ * 3, "partitioned tether StepBasic positions");
    require_finite(compression_values, particle_count_, "partitioned tether compression");
    require_finite(stretch_values, particle_count_, "partitioned tether stretch");
    std::vector<float> rest_lengths(particle_count_, 0.0f);
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if (compression_values[vertex] < 0.0f || compression_values[vertex] > 1.0f ||
            stretch_values[vertex] < 0.0f) {
            throw std::invalid_argument("MC2 CPU partitioned tether limits are invalid");
        }
        const auto root = tether_root_indices_[vertex];
        if (root < 0) continue;
        const auto offset = vertex * 3;
        const auto root_offset = static_cast<std::size_t>(root) * 3;
        const float dx = step_basic_positions[root_offset + 0] - step_basic_positions[offset + 0];
        const float dy = step_basic_positions[root_offset + 1] - step_basic_positions[offset + 1];
        const float dz = step_basic_positions[root_offset + 2] - step_basic_positions[offset + 2];
        rest_lengths[vertex] = std::sqrt(dx * dx + dy * dy + dz * dz);
    }
    hotools::Mc2TetherConstraintView view;
    view.positions = world_positions_.data();
    view.inv_masses = inertia_inv_masses_.data();
    view.root_indices = tether_root_indices_.data();
    view.root_rest_lengths = rest_lengths.data();
    view.velocity_positions = velocity_positions_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.stiffness = 1.0f;
    view.compression_values = compression_values;
    view.stretch_values = stretch_values;
    hotools::project_tether_mc2(view);
    ++step_count_;
}

void DomainV1::step_angle(
    const float* step_basic_positions,
    const float* step_basic_rotations,
    const float* restoration_values,
    const float* limit_values,
    float restoration_velocity_attenuation,
    float restoration_gravity_falloff,
    float limit_stiffness,
    bool restoration_enabled,
    bool limit_enabled
) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU Angle step requires update_frame");
    }
    if (!baseline_ready_ || !inertia_ready_) {
        throw std::logic_error("MC2 CPU Angle step requires baseline and particle configuration");
    }
    require_finite(step_basic_positions, particle_count_ * 3, "Angle StepBasic positions");
    require_unit_quaternions(step_basic_rotations, particle_count_, "Angle StepBasic rotations");
    require_finite(restoration_values, particle_count_, "Angle restoration values");
    require_finite(limit_values, particle_count_, "Angle limit values");
    if (!std::isfinite(restoration_velocity_attenuation) ||
        !std::isfinite(restoration_gravity_falloff) ||
        !std::isfinite(limit_stiffness) || restoration_velocity_attenuation < 0.0f ||
        restoration_gravity_falloff < 0.0f || limit_stiffness < 0.0f || limit_stiffness > 1.0f) {
        throw std::invalid_argument("MC2 CPU Angle scalars are invalid");
    }
    hotools::Mc2AngleConstraintView view;
    view.positions = world_positions_.data();
    view.inv_masses = constraint_friction_ready_
        ? angle_inverse_masses_.data()
        : inertia_inv_masses_.data();
    view.parent_indices = baseline_parent_indices_.data();
    view.baseline_start = baseline_line_starts_.data();
    view.baseline_count = baseline_line_counts_.data();
    view.baseline_data = baseline_line_data_.data();
    view.step_basic_positions = step_basic_positions;
    view.step_basic_rotations = step_basic_rotations;
    view.restoration_values = restoration_values;
    view.limit_values = limit_values;
    view.velocity_positions = velocity_positions_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.line_count = static_cast<std::int64_t>(baseline_line_starts_.size());
    view.baseline_data_count = static_cast<std::int64_t>(baseline_line_data_.size());
    view.restoration_velocity_attenuation = restoration_velocity_attenuation;
    view.restoration_gravity_falloff = restoration_gravity_falloff;
    view.limit_stiffness = limit_stiffness;
    view.explicit_enable_flags = true;
    view.restoration_enabled = restoration_enabled;
    view.limit_enabled = limit_enabled;
    if ((constraint_debug_active_mask_ & kConstraintDebugAngle) != 0u) {
        view.debug_record_origins = angle_debug_origins_.data();
        view.debug_record_targets = angle_debug_targets_.data();
        view.debug_record_target_vectors = angle_debug_target_vectors_.data();
        view.debug_record_corrections = angle_debug_corrections_.data();
        view.debug_record_currents = angle_debug_currents_.data();
        view.debug_record_limits = angle_debug_limits_.data();
        view.debug_record_valid = angle_debug_valid_.data();
    }
    hotools::project_angle_constraints_mc2(view);
    if (restoration_enabled || limit_enabled) ++angle_solve_count_;
    ++step_count_;
}

void DomainV1::step_angle_partitioned(
    const float* step_basic_positions,
    const float* step_basic_rotations,
    const float* restoration_values,
    const float* limit_values,
    const float* restoration_velocity_attenuation_values,
    const float* restoration_gravity_falloff_values,
    const float* limit_stiffness_values,
    const std::uint32_t* restoration_enabled_values,
    const std::uint32_t* limit_enabled_values
) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU partitioned Angle step requires update_frame");
    }
    if (!baseline_ready_ || !inertia_ready_) {
        throw std::logic_error("MC2 CPU partitioned Angle step requires particle configuration");
    }
    require_finite(step_basic_positions, particle_count_ * 3, "partitioned Angle StepBasic positions");
    require_unit_quaternions(step_basic_rotations, particle_count_, "partitioned Angle StepBasic rotations");
    require_finite(restoration_values, particle_count_, "partitioned Angle restoration values");
    require_finite(limit_values, particle_count_, "partitioned Angle limit values");
    require_finite(restoration_velocity_attenuation_values, particle_count_, "partitioned Angle attenuation");
    require_finite(restoration_gravity_falloff_values, particle_count_, "partitioned Angle gravity falloff");
    require_finite(limit_stiffness_values, particle_count_, "partitioned Angle limit stiffness");
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if (restoration_velocity_attenuation_values[vertex] < 0.0f ||
            restoration_gravity_falloff_values[vertex] < 0.0f ||
            limit_stiffness_values[vertex] < 0.0f || limit_stiffness_values[vertex] > 1.0f ||
            restoration_enabled_values[vertex] > 1u || limit_enabled_values[vertex] > 1u) {
            throw std::invalid_argument("MC2 CPU partitioned Angle values are invalid");
        }
    }
    hotools::Mc2AngleConstraintView view;
    view.positions = world_positions_.data();
    view.inv_masses = constraint_friction_ready_ ? angle_inverse_masses_.data() : inertia_inv_masses_.data();
    view.parent_indices = baseline_parent_indices_.data();
    view.baseline_start = baseline_line_starts_.data();
    view.baseline_count = baseline_line_counts_.data();
    view.baseline_data = baseline_line_data_.data();
    view.step_basic_positions = step_basic_positions;
    view.step_basic_rotations = step_basic_rotations;
    view.restoration_values = restoration_values;
    view.limit_values = limit_values;
    view.velocity_positions = velocity_positions_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.line_count = static_cast<std::int64_t>(baseline_line_starts_.size());
    view.baseline_data_count = static_cast<std::int64_t>(baseline_line_data_.size());
    view.restoration_velocity_attenuation_values = restoration_velocity_attenuation_values;
    view.restoration_gravity_falloff_values = restoration_gravity_falloff_values;
    view.limit_stiffness_values = limit_stiffness_values;
    view.explicit_enable_flags = true;
    view.restoration_enabled_values = restoration_enabled_values;
    view.limit_enabled_values = limit_enabled_values;
    if ((constraint_debug_active_mask_ & kConstraintDebugAngle) != 0u) {
        view.debug_record_origins = angle_debug_origins_.data();
        view.debug_record_targets = angle_debug_targets_.data();
        view.debug_record_target_vectors = angle_debug_target_vectors_.data();
        view.debug_record_corrections = angle_debug_corrections_.data();
        view.debug_record_currents = angle_debug_currents_.data();
        view.debug_record_limits = angle_debug_limits_.data();
        view.debug_record_valid = angle_debug_valid_.data();
    }
    hotools::project_angle_constraints_mc2(view);
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if (restoration_enabled_values[vertex] != 0u || limit_enabled_values[vertex] != 0u) {
            ++angle_solve_count_;
            break;
        }
    }
    ++step_count_;
}

void DomainV1::step_motion(
    const float* base_positions,
    const float* base_rotations,
    const float* max_distances,
    const float* stiffness_values,
    const float* backstop_radii,
    const float* backstop_distances,
    std::int32_t normal_axis,
    bool max_distance_enabled,
    bool backstop_enabled
) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU Motion step requires update_frame");
    }
    if (!inertia_ready_) {
        throw std::logic_error("MC2 CPU Motion step requires particle configuration");
    }
    require_finite(base_positions, particle_count_ * 3, "Motion base positions");
    require_unit_quaternions(base_rotations, particle_count_, "Motion base rotations");
    require_finite(max_distances, particle_count_, "Motion max distances");
    require_finite(stiffness_values, particle_count_, "Motion stiffness values");
    require_finite(backstop_radii, particle_count_, "Motion backstop radii");
    require_finite(backstop_distances, particle_count_, "Motion backstop distances");
    if (normal_axis < 0 || normal_axis > 5) {
        throw std::invalid_argument("MC2 CPU Motion normal_axis must be in 0..5");
    }
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if (max_distances[vertex] < 0.0f || stiffness_values[vertex] < 0.0f ||
            stiffness_values[vertex] > 1.0f || backstop_radii[vertex] < 0.0f ||
            backstop_distances[vertex] < 0.0f) {
            throw std::invalid_argument("MC2 CPU Motion values are out of range");
        }
    }
    hotools::Mc2MotionConstraintView view;
    view.positions = world_positions_.data();
    view.base_positions = base_positions;
    view.base_rotations = base_rotations;
    view.inv_masses = inertia_inv_masses_.data();
    view.max_distances = max_distances;
    view.stiffness_values = stiffness_values;
    view.backstop_radii = backstop_radii;
    view.backstop_distances = backstop_distances;
    view.velocity_positions = velocity_positions_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.normal_axis = normal_axis;
    view.explicit_enable_flags = true;
    view.max_distance_enabled = max_distance_enabled;
    view.backstop_enabled = backstop_enabled;
    if ((constraint_debug_active_mask_ & kConstraintDebugMotion) != 0u) {
        view.debug_record_origins = motion_debug_origins_.data();
        view.debug_record_targets = motion_debug_targets_.data();
        view.debug_record_corrections = motion_debug_corrections_.data();
        view.debug_record_limits = motion_debug_limits_.data();
        view.debug_record_valid = motion_debug_valid_.data();
    }
    hotools::project_motion_constraints_mc2(view);
    if (max_distance_enabled || backstop_enabled) ++motion_solve_count_;
    ++step_count_;
}

void DomainV1::step_motion_partitioned(
    const float* base_positions,
    const float* base_rotations,
    const float* max_distances,
    const float* stiffness_values,
    const float* backstop_radii,
    const float* backstop_distances,
    const std::int32_t* normal_axis_values,
    const std::uint32_t* max_distance_enabled_values,
    const std::uint32_t* backstop_enabled_values
) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU partitioned Motion step requires update_frame");
    }
    if (!inertia_ready_) {
        throw std::logic_error("MC2 CPU partitioned Motion step requires particle configuration");
    }
    require_finite(base_positions, particle_count_ * 3, "partitioned Motion base positions");
    require_unit_quaternions(base_rotations, particle_count_, "partitioned Motion base rotations");
    require_finite(max_distances, particle_count_, "partitioned Motion max distances");
    require_finite(stiffness_values, particle_count_, "partitioned Motion stiffness");
    require_finite(backstop_radii, particle_count_, "partitioned Motion backstop radii");
    require_finite(backstop_distances, particle_count_, "partitioned Motion backstop distances");
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if (normal_axis_values[vertex] < 0 || normal_axis_values[vertex] > 5 ||
            max_distance_enabled_values[vertex] > 1u || backstop_enabled_values[vertex] > 1u ||
            max_distances[vertex] < 0.0f || stiffness_values[vertex] < 0.0f ||
            stiffness_values[vertex] > 1.0f || backstop_radii[vertex] < 0.0f ||
            backstop_distances[vertex] < 0.0f) {
            throw std::invalid_argument("MC2 CPU partitioned Motion values are invalid");
        }
    }
    hotools::Mc2MotionConstraintView view;
    view.positions = world_positions_.data();
    view.base_positions = base_positions;
    view.base_rotations = base_rotations;
    view.inv_masses = inertia_inv_masses_.data();
    view.max_distances = max_distances;
    view.stiffness_values = stiffness_values;
    view.backstop_radii = backstop_radii;
    view.backstop_distances = backstop_distances;
    view.velocity_positions = velocity_positions_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.explicit_enable_flags = true;
    view.normal_axis_values = normal_axis_values;
    view.max_distance_enabled_values = max_distance_enabled_values;
    view.backstop_enabled_values = backstop_enabled_values;
    if ((constraint_debug_active_mask_ & kConstraintDebugMotion) != 0u) {
        view.debug_record_origins = motion_debug_origins_.data();
        view.debug_record_targets = motion_debug_targets_.data();
        view.debug_record_corrections = motion_debug_corrections_.data();
        view.debug_record_limits = motion_debug_limits_.data();
        view.debug_record_valid = motion_debug_valid_.data();
    }
    hotools::project_motion_constraints_mc2(view);
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if (max_distance_enabled_values[vertex] != 0u || backstop_enabled_values[vertex] != 0u) {
            ++motion_solve_count_;
            break;
        }
    }
    ++step_count_;
}

void DomainV1::step_external_collision(
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
) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU external collision step requires update_frame");
    }
    if (!inertia_ready_) {
        throw std::logic_error("MC2 CPU external collision step requires particle configuration");
    }
    require_finite(base_positions, particle_count_ * 3, "collision base positions");
    require_finite(collision_radii, particle_count_, "collision radii");
    require_finite(friction, particle_count_, "collision friction");
    if ((collider_count != 0 &&
         (collider_types == nullptr || collider_group_bits == nullptr ||
          collider_centers == nullptr || collider_segment_a == nullptr || collider_segment_b == nullptr ||
          collider_old_centers == nullptr || collider_old_segment_a == nullptr ||
          collider_old_segment_b == nullptr || collider_radii == nullptr))) {
        throw std::invalid_argument("MC2 CPU collider arrays cannot be null");
    }
    require_finite(collider_centers, collider_count * 3, "collider centers");
    require_finite(collider_segment_a, collider_count * 3, "collider segment A");
    require_finite(collider_segment_b, collider_count * 3, "collider segment B");
    require_finite(collider_old_centers, collider_count * 3, "collider old centers");
    require_finite(collider_old_segment_a, collider_count * 3, "collider old segment A");
    require_finite(collider_old_segment_b, collider_count * 3, "collider old segment B");
    require_finite(collider_radii, collider_count, "collider radii");
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if (collision_radii[vertex] < 0.0f || friction[vertex] < 0.0f) {
            throw std::invalid_argument("MC2 CPU collision particle values are out of range");
        }
    }
    for (std::size_t collider = 0; collider < collider_count; ++collider) {
        if (collider_types[collider] < 0 || collider_types[collider] > 3 ||
            collider_group_bits[collider] <= 0 || collider_radii[collider] < 0.0f) {
            throw std::invalid_argument("MC2 CPU collider values are out of range");
        }
    }
    collision_friction_.assign(friction, friction + particle_count_);
    hotools::Mc2CollisionView view;
    view.positions = world_positions_.data();
    view.base_positions = base_positions;
    view.velocity_positions = nullptr;
    view.inv_masses = inertia_inv_masses_.data();
    view.collision_radii = collision_radii;
    view.max_lengths = nullptr;
    view.collision_normals = world_normals_.data();
    view.friction = collision_friction_.data();
    view.collider_types = collider_types;
    view.collider_group_bits = collider_group_bits;
    view.collider_centers = collider_centers;
    view.collider_segment_a = collider_segment_a;
    view.collider_segment_b = collider_segment_b;
    view.collider_old_centers = collider_old_centers;
    view.collider_old_segment_a = collider_old_segment_a;
    view.collider_old_segment_b = collider_old_segment_b;
    view.collider_radii = collider_radii;
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.collider_count = static_cast<std::int64_t>(collider_count);
    view.collided_by_groups = collided_by_groups;
    view.soft_sphere = false;
    hotools::project_collisions_mc2(view);
    ++step_count_;
}

void DomainV1::step_self_collision(
    const float* old_positions,
    const std::int32_t* edges,
    std::size_t edge_count,
    const std::int32_t* triangles,
    std::size_t triangle_count,
    const float* friction,
    float surface_thickness
) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU self collision step requires update_frame");
    }
    if (!inertia_ready_) {
        throw std::logic_error("MC2 CPU self collision step requires particle configuration");
    }
    require_finite(old_positions, particle_count_ * 3, "self collision old positions");
    require_finite(friction, particle_count_, "self collision friction");
    if (!std::isfinite(surface_thickness) || surface_thickness <= 0.0f) {
        throw std::invalid_argument("MC2 CPU self collision thickness must be positive");
    }
    if ((edge_count != 0 && edges == nullptr) || (triangle_count != 0 && triangles == nullptr)) {
        throw std::invalid_argument("MC2 CPU self collision topology cannot be null");
    }
    auto validate_indices = [&](const std::int32_t* values, std::size_t count) {
        for (std::size_t index = 0; index < count; ++index) {
            if (values[index] < 0 || static_cast<std::size_t>(values[index]) >= particle_count_) {
                throw std::invalid_argument("MC2 CPU self collision topology is out of range");
            }
        }
    };
    validate_indices(edges, edge_count * 2);
    validate_indices(triangles, triangle_count * 3);
    collision_friction_.assign(friction, friction + particle_count_);
    std::vector<std::uint8_t> attributes(particle_count_, 0u);
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if ((particle_attribute_flags_[vertex] & 0x02u) != 0u) {
            attributes[vertex] = 1u << 2u;
        }
    }
    hotools::Mc2SelfCollisionView view;
    view.positions = world_positions_.data();
    view.old_positions = old_positions;
    view.inv_masses = inertia_inv_masses_.data();
    view.edges = edges;
    view.triangles = triangles;
    view.attributes = attributes.data();
    view.collision_normals = world_normals_.data();
    view.friction = collision_friction_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.edge_count = static_cast<std::int64_t>(edge_count);
    view.triangle_count = static_cast<std::int64_t>(triangle_count);
    view.surface_thickness = surface_thickness;
    hotools::project_self_collisions_mc2(view);
    ++step_count_;
}

void DomainV1::configure_whole_domain_self(
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
) {
    ensure_live();
    if ((point_count != 0 && points == nullptr) ||
        (edge_count != 0 && edges == nullptr) ||
        (triangle_count != 0 && triangles == nullptr)) {
        throw std::invalid_argument("MC2 whole-domain self topology cannot be null");
    }
    if (partition_self_collision_modes == nullptr || partition_collision_groups == nullptr ||
        partition_collision_masks == nullptr) {
        throw std::invalid_argument("MC2 whole-domain self partition policy cannot be null");
    }
    require_finite(particle_friction, particle_count_, "whole-domain self friction");
    require_finite(particle_thickness, particle_count_, "whole-domain self thickness");
    require_finite(particle_cloth_mass, particle_count_, "whole-domain self cloth mass");
    for (std::size_t partition = 0; partition < partition_count_; ++partition) {
        if (partition_self_collision_modes[partition] != 0u &&
            partition_self_collision_modes[partition] != 2u) {
            throw std::invalid_argument("MC2 whole-domain self mode must be 0 or 2");
        }
    }
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if (particle_friction[vertex] < 0.0f || particle_thickness[vertex] < 0.0f ||
            particle_cloth_mass[vertex] < 0.0f || particle_cloth_mass[vertex] > 1.0f) {
            throw std::invalid_argument("MC2 whole-domain self particle values cannot be negative");
        }
    }
    auto validate_primitive = [&](const std::int32_t* values, std::size_t count, std::size_t width) {
        for (std::size_t primitive = 0; primitive < count; ++primitive) {
            const std::int32_t first = values[primitive * width];
            if (first < 0 || static_cast<std::size_t>(first) >= particle_count_) {
                throw std::invalid_argument("MC2 whole-domain self topology is out of range");
            }
            const auto owner = particle_partition_index_[static_cast<std::size_t>(first)];
            for (std::size_t axis = 1; axis < width; ++axis) {
                const std::int32_t vertex = values[primitive * width + axis];
                if (vertex < 0 || static_cast<std::size_t>(vertex) >= particle_count_ ||
                    particle_partition_index_[static_cast<std::size_t>(vertex)] != owner) {
                    throw std::invalid_argument(
                        "MC2 whole-domain self primitive must stay inside one partition"
                    );
                }
            }
        }
    };
    validate_primitive(points, point_count, 1);
    validate_primitive(edges, edge_count, 2);
    validate_primitive(triangles, triangle_count, 3);

    whole_domain_self_points_.clear();
    whole_domain_self_edges_.clear();
    whole_domain_self_triangles_.clear();
    if (point_count != 0) {
        whole_domain_self_points_.assign(points, points + point_count);
    }
    if (edge_count != 0) {
        whole_domain_self_edges_.assign(edges, edges + edge_count * 2);
    }
    if (triangle_count != 0) {
        whole_domain_self_triangles_.assign(triangles, triangles + triangle_count * 3);
    }
    whole_domain_self_modes_.assign(
        partition_self_collision_modes,
        partition_self_collision_modes + partition_count_
    );
    whole_domain_collision_groups_.assign(
        partition_collision_groups, partition_collision_groups + partition_count_
    );
    whole_domain_collision_masks_.assign(
        partition_collision_masks, partition_collision_masks + partition_count_
    );
    whole_domain_self_friction_.assign(particle_friction, particle_friction + particle_count_);
    whole_domain_self_thickness_.assign(particle_thickness, particle_thickness + particle_count_);
    whole_domain_self_cloth_mass_.assign(
        particle_cloth_mass,
        particle_cloth_mass + particle_count_
    );
    whole_domain_self_scaled_thickness_.assign(particle_count_, 0.0f);
    whole_domain_self_partition_scale_ratios_.assign(partition_count_, 1.0f);
    whole_domain_self_engine_->configure(
        particle_count_,
        points,
        point_count,
        edges,
        edge_count,
        triangles,
        triangle_count,
        particle_partition_index_.data(),
        particle_attribute_flags_.data(),
        partition_self_collision_modes,
        partition_collision_groups,
        partition_collision_masks,
        partition_count_
    );
    whole_domain_self_ready_ = true;
    whole_domain_self_step_count_ = 0;
    whole_domain_self_last_contact_count_ = 0;
    whole_domain_self_last_candidate_count_ = 0;
}

void DomainV1::step_whole_domain_self_impl(const float* old_positions, bool reset_friction) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 whole-domain self step requires update_frame");
    }
    if (!inertia_ready_) {
        throw std::logic_error("MC2 whole-domain self step requires particle configuration");
    }
    if (!whole_domain_self_ready_) {
        throw std::logic_error("MC2 whole-domain self step requires configuration");
    }
    require_finite(old_positions, particle_count_ * 3, "whole-domain self old positions");
    if (reset_friction || !collision_state_ready_) {
        collision_friction_ = whole_domain_self_friction_;
    }
    for (std::size_t partition = 0; partition < partition_count_; ++partition) {
        const auto offset = partition * 3;
        const float current_length = std::sqrt(
            partition_world_scales_[offset] * partition_world_scales_[offset] +
            partition_world_scales_[offset + 1] * partition_world_scales_[offset + 1] +
            partition_world_scales_[offset + 2] * partition_world_scales_[offset + 2]
        );
        const float initial_length = std::sqrt(
            center_initial_scales_[offset] * center_initial_scales_[offset] +
            center_initial_scales_[offset + 1] * center_initial_scales_[offset + 1] +
            center_initial_scales_[offset + 2] * center_initial_scales_[offset + 2]
        );
        whole_domain_self_partition_scale_ratios_[partition] = std::max(
            current_length / std::max(initial_length, 0.00000001f), 0.000001f
        );
    }
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        whole_domain_self_scaled_thickness_[vertex] = whole_domain_self_thickness_[vertex] *
            whole_domain_self_partition_scale_ratios_[particle_partition_index_[vertex]];
    }
    whole_domain_self_engine_->solve(
        world_positions_.data(),
        old_positions,
        whole_domain_self_scaled_thickness_.data(),
        collision_friction_.data(),
        whole_domain_self_cloth_mass_.data(),
        frame_,
        generation_,
        whole_domain_self_last_candidate_count_,
        whole_domain_self_last_contact_count_
    );
    collision_state_ready_ = true;
    ++whole_domain_self_step_count_;
    ++step_count_;
}

void DomainV1::step_whole_domain_self(const float* old_positions) {
    step_whole_domain_self_impl(old_positions, true);
}

void DomainV1::step_whole_domain_self_owned() {
    ensure_live();
    if (!substep_snapshot_ready_) {
        throw std::logic_error(
            "MC2 whole-domain self owned step requires the substep snapshot"
        );
    }
    step_whole_domain_self_impl(substep_old_positions_.data(), false);
}

void DomainV1::configure_compiled_external_collision(
    const std::int32_t* edges,
    std::size_t edge_count,
    const std::uint32_t* partition_collision_modes,
    const std::uint32_t* partition_collided_by_groups,
    const float* particle_radii,
    const float* particle_friction
) {
    ensure_live();
    if ((edge_count != 0 && edges == nullptr) || partition_collision_modes == nullptr ||
        partition_collided_by_groups == nullptr) {
        throw std::invalid_argument("MC2 compiled external collision policy cannot be null");
    }
    require_finite(particle_radii, particle_count_, "compiled external collision radii");
    require_finite(particle_friction, particle_count_, "compiled external collision friction");
    for (std::size_t partition = 0; partition < partition_count_; ++partition) {
        if (partition_collision_modes[partition] > 2u) {
            throw std::invalid_argument("MC2 compiled external collision mode must be 0, 1, or 2");
        }
    }
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if (particle_radii[vertex] < 0.0f || particle_friction[vertex] < 0.0f) {
            throw std::invalid_argument("MC2 compiled external particle values cannot be negative");
        }
    }
    for (std::size_t edge = 0; edge < edge_count; ++edge) {
        const std::int32_t v0 = edges[edge * 2];
        const std::int32_t v1 = edges[edge * 2 + 1];
        if (v0 < 0 || v1 < 0 || static_cast<std::size_t>(v0) >= particle_count_ ||
            static_cast<std::size_t>(v1) >= particle_count_ || v0 == v1 ||
            particle_partition_index_[static_cast<std::size_t>(v0)] !=
                particle_partition_index_[static_cast<std::size_t>(v1)]) {
            throw std::invalid_argument(
                "MC2 compiled external edge must be valid and stay inside one partition"
            );
        }
    }

    std::vector<std::int32_t> next_edges;
    if (edge_count != 0) {
        next_edges.assign(edges, edges + edge_count * 2);
    }
    std::vector<std::uint32_t> next_modes(
        partition_collision_modes, partition_collision_modes + partition_count_
    );
    std::vector<std::uint32_t> next_masks(
        partition_collided_by_groups, partition_collided_by_groups + partition_count_
    );
    std::vector<float> next_radii(particle_radii, particle_radii + particle_count_);
    std::vector<float> next_friction(particle_friction, particle_friction + particle_count_);
    compiled_external_edges_.swap(next_edges);
    compiled_external_modes_.swap(next_modes);
    compiled_external_masks_.swap(next_masks);
    compiled_external_radii_.swap(next_radii);
    compiled_external_friction_.swap(next_friction);
    compiled_external_ready_ = true;
    compiled_external_step_count_ = 0;
}

void DomainV1::step_compiled_external_collision(
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
) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 compiled external collision requires update_frame");
    }
    if (!inertia_ready_ || !compiled_external_ready_) {
        throw std::logic_error("MC2 compiled external collision requires configuration");
    }
    if (collider_count != 0 &&
        (collider_types == nullptr || collider_group_bits == nullptr || collider_centers == nullptr ||
         collider_segment_a == nullptr || collider_segment_b == nullptr ||
         collider_old_centers == nullptr || collider_old_segment_a == nullptr ||
         collider_old_segment_b == nullptr || collider_radii == nullptr)) {
        throw std::invalid_argument("MC2 compiled external collider arrays cannot be null");
    }
    require_finite(collider_centers, collider_count * 3, "compiled collider centers");
    require_finite(collider_segment_a, collider_count * 3, "compiled collider segment A");
    require_finite(collider_segment_b, collider_count * 3, "compiled collider segment B");
    require_finite(collider_old_centers, collider_count * 3, "compiled collider old centers");
    require_finite(collider_old_segment_a, collider_count * 3, "compiled collider old segment A");
    require_finite(collider_old_segment_b, collider_count * 3, "compiled collider old segment B");
    require_finite(collider_radii, collider_count, "compiled collider radii");
    for (std::size_t collider = 0; collider < collider_count; ++collider) {
        if (collider_types[collider] < 0 || collider_types[collider] > 3 ||
            collider_group_bits[collider] <= 0 || collider_radii[collider] < 0.0f) {
            throw std::invalid_argument("MC2 compiled external collider values are out of range");
        }
    }

    std::vector<float> partition_scale_ratios(partition_count_, 1.0f);
    for (std::size_t partition = 0; partition < partition_count_; ++partition) {
        const auto offset = partition * 3;
        const float current_length = std::sqrt(
            partition_world_scales_[offset] * partition_world_scales_[offset] +
            partition_world_scales_[offset + 1] * partition_world_scales_[offset + 1] +
            partition_world_scales_[offset + 2] * partition_world_scales_[offset + 2]
        );
        const float initial_length = std::sqrt(
            center_initial_scales_[offset] * center_initial_scales_[offset] +
            center_initial_scales_[offset + 1] * center_initial_scales_[offset + 1] +
            center_initial_scales_[offset + 2] * center_initial_scales_[offset + 2]
        );
        partition_scale_ratios[partition] = std::max(
            current_length / std::max(initial_length, 0.00000001f), 0.000001f
        );
    }
    std::vector<float> scaled_radii(particle_count_, 0.0f);
    std::vector<std::uint8_t> attributes(particle_count_, 0u);
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        scaled_radii[vertex] = compiled_external_radii_[vertex] *
            partition_scale_ratios[particle_partition_index_[vertex]];
        if ((particle_attribute_flags_[vertex] & 0x02u) != 0u) {
            attributes[vertex] = 1u << 2u;
        }
    }
    collision_friction_ = compiled_external_friction_;
    std::fill(world_normals_.begin(), world_normals_.end(), 0.0f);

    hotools::Mc2CollisionView point_view;
    point_view.positions = world_positions_.data();
    point_view.base_positions = animated_base_world_positions_.data();
    point_view.inv_masses = inertia_inv_masses_.data();
    point_view.collision_radii = scaled_radii.data();
    point_view.collision_normals = world_normals_.data();
    point_view.friction = collision_friction_.data();
    point_view.collider_types = collider_types;
    point_view.collider_group_bits = collider_group_bits;
    point_view.collider_centers = collider_centers;
    point_view.collider_segment_a = collider_segment_a;
    point_view.collider_segment_b = collider_segment_b;
    point_view.collider_old_centers = collider_old_centers;
    point_view.collider_old_segment_a = collider_old_segment_a;
    point_view.collider_old_segment_b = collider_old_segment_b;
    point_view.collider_radii = collider_radii;
    point_view.particle_partition_index = particle_partition_index_.data();
    point_view.partition_collision_modes = compiled_external_modes_.data();
    point_view.partition_collided_by_groups = compiled_external_masks_.data();
    point_view.vertex_count = static_cast<std::int64_t>(particle_count_);
    point_view.collider_count = static_cast<std::int64_t>(collider_count);
    point_view.partition_count = static_cast<std::int64_t>(partition_count_);
    hotools::project_collisions_mc2(point_view);

    hotools::Mc2EdgeCollisionView edge_view;
    edge_view.positions = world_positions_.data();
    edge_view.edges = compiled_external_edges_.data();
    edge_view.attributes = attributes.data();
    edge_view.inv_masses = inertia_inv_masses_.data();
    edge_view.collision_radii = scaled_radii.data();
    edge_view.collision_normals = world_normals_.data();
    edge_view.friction = collision_friction_.data();
    edge_view.collider_types = collider_types;
    edge_view.collider_group_bits = collider_group_bits;
    edge_view.collider_centers = collider_centers;
    edge_view.collider_segment_a = collider_segment_a;
    edge_view.collider_segment_b = collider_segment_b;
    edge_view.collider_old_centers = collider_old_centers;
    edge_view.collider_old_segment_a = collider_old_segment_a;
    edge_view.collider_old_segment_b = collider_old_segment_b;
    edge_view.collider_radii = collider_radii;
    edge_view.particle_partition_index = particle_partition_index_.data();
    edge_view.partition_collision_modes = compiled_external_modes_.data();
    edge_view.partition_collided_by_groups = compiled_external_masks_.data();
    edge_view.vertex_count = static_cast<std::int64_t>(particle_count_);
    edge_view.edge_count = static_cast<std::int64_t>(compiled_external_edges_.size() / 2);
    edge_view.collider_count = static_cast<std::int64_t>(collider_count);
    edge_view.partition_count = static_cast<std::int64_t>(partition_count_);
    hotools::project_edge_collisions_mc2(edge_view);

    collision_state_ready_ = true;
    ++compiled_external_step_count_;
    ++step_count_;
}

void DomainV1::step_external_edge_collision(
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
) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU external edge collision requires update_frame");
    }
    if (!inertia_ready_) {
        throw std::logic_error("MC2 CPU external edge collision requires particle configuration");
    }
    require_finite(collision_radii, particle_count_, "edge collision radii");
    require_finite(friction, particle_count_, "edge collision friction");
    if (!std::isfinite(static_cast<float>(collided_by_groups)) ||
        (edge_count != 0 && edges == nullptr) ||
        (collider_count != 0 && (collider_types == nullptr || collider_group_bits == nullptr ||
         collider_centers == nullptr || collider_segment_a == nullptr || collider_segment_b == nullptr ||
         collider_old_centers == nullptr || collider_old_segment_a == nullptr ||
         collider_old_segment_b == nullptr || collider_radii == nullptr))) {
        throw std::invalid_argument("MC2 CPU external edge collision inputs are invalid");
    }
    require_finite(collider_centers, collider_count * 3, "edge collider centers");
    require_finite(collider_segment_a, collider_count * 3, "edge collider segment A");
    require_finite(collider_segment_b, collider_count * 3, "edge collider segment B");
    require_finite(collider_old_centers, collider_count * 3, "edge collider old centers");
    require_finite(collider_old_segment_a, collider_count * 3, "edge collider old segment A");
    require_finite(collider_old_segment_b, collider_count * 3, "edge collider old segment B");
    require_finite(collider_radii, collider_count, "edge collider radii");
    auto validate_indices = [&](const std::int32_t* values, std::size_t count) {
        for (std::size_t index = 0; index < count; ++index) {
            if (values[index] < 0 || static_cast<std::size_t>(values[index]) >= particle_count_) {
                throw std::invalid_argument("MC2 CPU external edge topology is out of range");
            }
        }
    };
    validate_indices(edges, edge_count * 2);
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if (collision_radii[vertex] < 0.0f || friction[vertex] < 0.0f) {
            throw std::invalid_argument("MC2 CPU edge collision particle values are out of range");
        }
    }
    for (std::size_t collider = 0; collider < collider_count; ++collider) {
        if (collider_types[collider] < 0 || collider_types[collider] > 3 ||
            collider_group_bits[collider] <= 0 || collider_radii[collider] < 0.0f) {
            throw std::invalid_argument("MC2 CPU edge collider values are out of range");
        }
    }
    collision_friction_.assign(friction, friction + particle_count_);
    std::vector<std::uint8_t> attributes(particle_count_, 0u);
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if ((particle_attribute_flags_[vertex] & 0x02u) != 0u) {
            attributes[vertex] = 1u << 2u;
        }
    }
    hotools::Mc2EdgeCollisionView view;
    view.positions = world_positions_.data();
    view.edges = edges;
    view.attributes = attributes.data();
    view.inv_masses = inertia_inv_masses_.data();
    view.collision_radii = collision_radii;
    view.collision_normals = world_normals_.data();
    view.friction = collision_friction_.data();
    view.collider_types = collider_types;
    view.collider_group_bits = collider_group_bits;
    view.collider_centers = collider_centers;
    view.collider_segment_a = collider_segment_a;
    view.collider_segment_b = collider_segment_b;
    view.collider_old_centers = collider_old_centers;
    view.collider_old_segment_a = collider_old_segment_a;
    view.collider_old_segment_b = collider_old_segment_b;
    view.collider_radii = collider_radii;
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.edge_count = static_cast<std::int64_t>(edge_count);
    view.collider_count = static_cast<std::int64_t>(collider_count);
    view.collided_by_groups = collided_by_groups;
    view.move_attribute_mask = 1u << 2u;
    hotools::project_edge_collisions_mc2(view);
    ++step_count_;
}

void DomainV1::configure_bending(
    const std::int32_t* dihedral_pairs,
    const float* dihedral_rest_angles,
    const std::int32_t* dihedral_signs,
    std::size_t dihedral_count,
    const std::int32_t* volume_pairs,
    const float* volume_rest,
    std::size_t volume_count,
    const float* stiffness_values
) {
    ensure_live();
    if ((dihedral_count != 0 &&
         (dihedral_pairs == nullptr || dihedral_rest_angles == nullptr || dihedral_signs == nullptr)) ||
        (volume_count != 0 && (volume_pairs == nullptr || volume_rest == nullptr)) ||
        stiffness_values == nullptr) {
        throw std::invalid_argument("MC2 CPU bending arrays cannot be null");
    }
    const auto validate_pairs = [&](const std::int32_t* pairs, std::size_t count) {
        for (std::size_t record = 0; record < count * 4; ++record) {
            if (pairs[record] < 0 || static_cast<std::size_t>(pairs[record]) >= particle_count_) {
                throw std::invalid_argument("MC2 CPU bending vertex is out of range");
            }
        }
    };
    validate_pairs(dihedral_pairs, dihedral_count);
    validate_pairs(volume_pairs, volume_count);
    require_finite(dihedral_rest_angles, dihedral_count, "bending dihedral rest angles");
    require_finite(volume_rest, volume_count, "bending volume rest values");
    require_finite(stiffness_values, particle_count_, "bending stiffness values");
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if (stiffness_values[vertex] < 0.0f || stiffness_values[vertex] > 1.0f) {
            throw std::invalid_argument("MC2 CPU bending stiffness must be in 0..1");
        }
    }
    if (dihedral_count != 0) {
        bending_dihedral_pairs_.assign(dihedral_pairs, dihedral_pairs + dihedral_count * 4);
        bending_dihedral_rest_angles_.assign(
            dihedral_rest_angles, dihedral_rest_angles + dihedral_count
        );
        bending_dihedral_signs_.assign(dihedral_signs, dihedral_signs + dihedral_count);
    } else {
        bending_dihedral_pairs_.clear();
        bending_dihedral_rest_angles_.clear();
        bending_dihedral_signs_.clear();
    }
    if (volume_count != 0) {
        bending_volume_pairs_.assign(volume_pairs, volume_pairs + volume_count * 4);
        bending_volume_rest_.assign(volume_rest, volume_rest + volume_count);
    } else {
        bending_volume_pairs_.clear();
        bending_volume_rest_.clear();
    }
    bending_stiffness_values_.assign(stiffness_values, stiffness_values + particle_count_);
    bending_ready_ = dihedral_count != 0 || volume_count != 0;
}

void DomainV1::step_bending(float simulation_power) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU bending step requires update_frame");
    }
    if (!bending_ready_ || !inertia_ready_) {
        throw std::logic_error("MC2 CPU bending step requires topology and particle configuration");
    }
    if (!std::isfinite(simulation_power) || simulation_power < 0.0f) {
        throw std::invalid_argument("MC2 CPU bending simulation power is invalid");
    }
    hotools::Mc2TriangleBendingView view;
    view.positions = world_positions_.data();
    view.inv_masses = constraint_friction_ready_
        ? bending_inverse_masses_.data()
        : inertia_inv_masses_.data();
    view.stiffness_values = bending_stiffness_values_.data();
    view.dihedral_pairs = bending_dihedral_pairs_.data();
    view.dihedral_rest_angles = bending_dihedral_rest_angles_.data();
    view.dihedral_signs = bending_dihedral_signs_.data();
    view.volume_pairs = bending_volume_pairs_.data();
    view.volume_rest = bending_volume_rest_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.dihedral_count = static_cast<std::int64_t>(bending_dihedral_rest_angles_.size());
    view.volume_count = static_cast<std::int64_t>(bending_volume_rest_.size());
    view.simulation_power = simulation_power;
    hotools::project_triangle_bending_mc2(view);
    ++step_count_;
}

void DomainV1::configure_inertia(const float* depths, const float* inv_masses) {
    ensure_live();
    require_finite(depths, particle_count_, "inertia depths");
    require_finite(inv_masses, particle_count_, "inertia inverse masses");
    for (std::size_t index = 0; index < particle_count_; ++index) {
        if (depths[index] < 0.0f || depths[index] > 1.0f || inv_masses[index] < 0.0f) {
            throw std::invalid_argument("MC2 CPU inertia values are out of range");
        }
    }
    std::vector<float> next_depths(depths, depths + particle_count_);
    std::vector<float> next_inv_masses(inv_masses, inv_masses + particle_count_);
    inertia_depths_.swap(next_depths);
    inertia_inv_masses_.swap(next_inv_masses);
    inertia_ready_ = true;
}

void DomainV1::configure_constraint_friction(const float* friction_values) {
    ensure_live();
    if (!inertia_ready_) {
        throw std::logic_error("MC2 CPU constraint friction requires configure_inertia");
    }
    require_finite(friction_values, particle_count_, "constraint friction values");
    angle_inverse_masses_.resize(particle_count_);
    bending_inverse_masses_.resize(particle_count_);
    collision_friction_.assign(friction_values, friction_values + particle_count_);
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if (friction_values[vertex] < 0.0f) {
            throw std::invalid_argument("MC2 CPU constraint friction must be non-negative");
        }
        const bool fixed = (particle_attribute_flags_[vertex] & 0x01u) != 0u;
        const float friction_mass = 1.0f / (1.0f + friction_values[vertex] * 3.0f);
        angle_inverse_masses_[vertex] = fixed ? 0.0f : friction_mass;
        const float depth_offset = 1.0f - inertia_depths_[vertex];
        bending_inverse_masses_[vertex] = fixed
            ? 0.01f
            : 1.0f / (
                1.0f + friction_values[vertex] * 3.0f +
                depth_offset * depth_offset * 5.0f
            );
    }
    constraint_friction_ready_ = true;
}

void DomainV1::step_inertia(
    const float* old_world_position,
    const float* step_vector,
    const float* step_rotation,
    const float* inertia_vector,
    const float* inertia_rotation,
    float depth_inertia
) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU inertia step requires update_frame");
    }
    if (!inertia_ready_) {
        throw std::logic_error("MC2 CPU inertia step requires configure_inertia");
    }
    require_finite(old_world_position, 3, "inertia old world position");
    require_finite(step_vector, 3, "inertia step vector");
    require_finite(step_rotation, 4, "inertia step rotation");
    require_finite(inertia_vector, 3, "inertia vector");
    require_finite(inertia_rotation, 4, "inertia rotation");
    if (!std::isfinite(depth_inertia)) {
        throw std::invalid_argument("inertia depth factor must be finite");
    }
    hotools::Mc2SubstepInertiaView view;
    view.old_positions = world_positions_.data();
    view.velocities = state_velocities_.data();
    view.depths = inertia_depths_.data();
    view.inv_masses = inertia_inv_masses_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    std::copy_n(old_world_position, 3, view.old_world_position);
    std::copy_n(step_vector, 3, view.step_vector);
    std::copy_n(step_rotation, 4, view.step_rotation);
    std::copy_n(inertia_vector, 3, view.inertia_vector);
    std::copy_n(inertia_rotation, 4, view.inertia_rotation);
    view.depth_inertia = depth_inertia;
    hotools::apply_substep_inertia_mc2(view);
    ++step_count_;
}

void DomainV1::configure_integration(const float* damping_values) {
    ensure_live();
    require_finite(damping_values, particle_count_, "integration damping values");
    for (std::size_t index = 0; index < particle_count_; ++index) {
        if (damping_values[index] < 0.0f || damping_values[index] > 1.0f) {
            throw std::invalid_argument("MC2 CPU integration damping must be in 0..1");
        }
    }
    std::vector<float> next(damping_values, damping_values + particle_count_);
    integration_damping_values_.swap(next);
    integration_ready_ = true;
}

void DomainV1::step_integration(
    float dt,
    float simulation_power,
    float velocity_weight,
    const float* gravity
) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU integration step requires update_frame");
    }
    if (!inertia_ready_ || !integration_ready_) {
        throw std::logic_error("MC2 CPU integration step requires particle configuration");
    }
    require_finite(gravity, 3, "integration gravity");
    if (!std::isfinite(dt) || dt < 0.0f || !std::isfinite(simulation_power) ||
        simulation_power < 0.0f || !std::isfinite(velocity_weight) ||
        velocity_weight < 0.0f || velocity_weight > 1.0f) {
        throw std::invalid_argument("MC2 CPU integration scalars are invalid");
    }
    if (!prediction_state_ready_) prepare_prediction_state();
    hotools::Mc2ParticleIntegrationView view;
    view.positions = world_positions_.data();
    view.velocities = state_velocities_.data();
    view.inv_masses = inertia_inv_masses_.data();
    view.damping_values = integration_damping_values_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.dt = dt;
    view.simulation_power = simulation_power;
    view.velocity_weight = velocity_weight;
    std::copy_n(gravity, 3, view.gravity);
    hotools::integrate_particles_mc2(view);
    prediction_state_ready_ = false;
    ++step_count_;
}

void DomainV1::step_integration_partitioned(
    float dt,
    float simulation_power
) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU partitioned integration step requires update_frame");
    }
    if (!inertia_ready_ || !integration_ready_) {
        throw std::logic_error("MC2 CPU partitioned integration requires particle configuration");
    }
    if (!std::isfinite(dt) || dt < 0.0f || !std::isfinite(simulation_power) ||
        simulation_power < 0.0f) {
        throw std::invalid_argument("MC2 CPU partitioned integration scalars are invalid");
    }
    std::vector<float> velocity_weight_values(particle_count_);
    std::vector<float> gravity_values(particle_count_ * 3);
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        const auto partition = static_cast<std::size_t>(particle_partition_index_[vertex]);
        velocity_weight_values[vertex] = center_velocity_weights_[partition];
        for (std::size_t component = 0; component < 3; ++component) {
            gravity_values[vertex * 3 + component] =
                center_gravity_directions_[partition * 3 + component] *
                center_gravity_[partition] * center_gravity_ratios_[partition];
        }
    }
    if (!prediction_state_ready_) prepare_prediction_state();
    hotools::Mc2ParticleIntegrationView view;
    view.positions = world_positions_.data();
    view.velocities = state_velocities_.data();
    view.inv_masses = inertia_inv_masses_.data();
    view.damping_values = integration_damping_values_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.dt = dt;
    view.simulation_power = simulation_power;
    view.velocity_weight_values = velocity_weight_values.data();
    view.gravity_values = gravity_values.data();
    hotools::integrate_particles_mc2(view);
    prediction_state_ready_ = false;
    ++step_count_;
}

void DomainV1::step_post(
    const float* old_positions,
    float dt,
    float dynamic_friction,
    float static_friction_speed,
    float particle_speed_limit,
    float velocity_weight
) {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU post step requires update_frame");
    }
    if (!inertia_ready_) {
        throw std::logic_error("MC2 CPU post step requires particle configuration");
    }
    require_finite(old_positions, particle_count_ * 3, "post old positions");
    if (!std::isfinite(dt) || dt <= 0.0f ||
        !std::isfinite(dynamic_friction) || dynamic_friction < 0.0f || dynamic_friction > 1.0f ||
        !std::isfinite(static_friction_speed) || static_friction_speed < 0.0f ||
        !std::isfinite(particle_speed_limit) ||
        !std::isfinite(velocity_weight) || velocity_weight < 0.0f || velocity_weight > 1.0f) {
        throw std::invalid_argument("MC2 CPU post step scalars are invalid");
    }
    std::copy(
        old_positions,
        old_positions + particle_count_ * 3,
        post_old_positions_.begin()
    );
    hotools::Mc2PostStepView view;
    view.positions = world_positions_.data();
    view.old_positions = post_old_positions_.data();
    view.velocity_positions = velocity_positions_.data();
    view.velocities = state_velocities_.data();
    view.real_velocities = real_velocities_.data();
    view.friction = collision_friction_.data();
    view.static_friction = static_friction_.data();
    view.collision_normals = world_normals_.data();
    view.inv_masses = inertia_inv_masses_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.step_dt = dt;
    view.dynamic_friction = dynamic_friction;
    view.static_friction_speed = static_friction_speed;
    view.particle_speed_limit = particle_speed_limit;
    view.velocity_weight = velocity_weight;
    hotools::apply_post_step_mc2(view);
    substep_snapshot_ready_ = false;
    collision_state_ready_ = false;
    ++step_count_;
}

void DomainV1::step_post_owned(
    float dt,
    float dynamic_friction,
    float static_friction_speed,
    float particle_speed_limit,
    float velocity_weight
) {
    ensure_live();
    if (!substep_snapshot_ready_) {
        throw std::logic_error("MC2 post owned step requires the substep snapshot");
    }
    step_post(
        substep_old_positions_.data(), dt, dynamic_friction, static_friction_speed,
        particle_speed_limit, velocity_weight
    );
}

void DomainV1::step_post_owned_partitioned(
    float dt,
    const float* dynamic_friction_values,
    const float* static_friction_speed_values,
    const float* particle_speed_limit_values
) {
    ensure_live();
    if (!substep_snapshot_ready_) {
        throw std::logic_error("MC2 partitioned post owned step requires the substep snapshot");
    }
    require_finite(dynamic_friction_values, particle_count_, "partitioned post dynamic friction");
    require_finite(static_friction_speed_values, particle_count_, "partitioned post static friction speed");
    require_finite(particle_speed_limit_values, particle_count_, "partitioned post speed limit");
    if (!std::isfinite(dt) || dt <= 0.0f) {
        throw std::invalid_argument("MC2 partitioned post dt is invalid");
    }
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        if (dynamic_friction_values[vertex] < 0.0f || dynamic_friction_values[vertex] > 1.0f ||
            static_friction_speed_values[vertex] < 0.0f) {
            throw std::invalid_argument("MC2 partitioned post values are invalid");
        }
    }
    std::copy(
        substep_old_positions_.begin(), substep_old_positions_.end(), post_old_positions_.begin()
    );
    std::vector<float> velocity_weight_values(particle_count_);
    for (std::size_t vertex = 0; vertex < particle_count_; ++vertex) {
        velocity_weight_values[vertex] = center_velocity_weights_[
            static_cast<std::size_t>(particle_partition_index_[vertex])
        ];
    }
    hotools::Mc2PostStepView view;
    view.positions = world_positions_.data();
    view.old_positions = post_old_positions_.data();
    view.velocity_positions = velocity_positions_.data();
    view.velocities = state_velocities_.data();
    view.real_velocities = real_velocities_.data();
    view.friction = collision_friction_.data();
    view.static_friction = static_friction_.data();
    view.collision_normals = world_normals_.data();
    view.inv_masses = inertia_inv_masses_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.step_dt = dt;
    view.dynamic_friction_values = dynamic_friction_values;
    view.static_friction_speed_values = static_friction_speed_values;
    view.particle_speed_limit_values = particle_speed_limit_values;
    view.velocity_weight_values = velocity_weight_values.data();
    hotools::apply_post_step_mc2(view);
    substep_snapshot_ready_ = false;
    collision_state_ready_ = false;
    ++step_count_;
}

void DomainV1::dispose() noexcept {
    disposed_ = true;
    frame_ = -1;
    generation_ = -1;
    frame_delta_time_ = 0.0f;
    simulation_delta_time_ = 0.0f;
    time_scale_ = 1.0f;
    skip_count_ = 0;
    is_running_ = false;
    bind_positions_.clear();
    bind_rotations_.clear();
    particle_partition_index_.clear();
    particle_attribute_flags_.clear();
    animated_base_world_positions_.clear();
    world_positions_.clear();
    world_normals_.clear();
    velocity_positions_.clear();
    state_velocities_.clear();
    real_velocities_.clear();
    static_friction_.clear();
    post_old_positions_.clear();
    substep_old_positions_.clear();
    whole_domain_self_points_.clear();
    whole_domain_self_edges_.clear();
    whole_domain_self_triangles_.clear();
    whole_domain_self_modes_.clear();
    whole_domain_collision_groups_.clear();
    whole_domain_collision_masks_.clear();
    whole_domain_self_friction_.clear();
    whole_domain_self_thickness_.clear();
    whole_domain_self_cloth_mass_.clear();
    whole_domain_self_scaled_thickness_.clear();
    whole_domain_self_partition_scale_ratios_.clear();
    whole_domain_self_ready_ = false;
    whole_domain_self_step_count_ = 0;
    whole_domain_self_last_contact_count_ = 0;
    whole_domain_self_last_candidate_count_ = 0;
    compiled_external_edges_.clear();
    compiled_external_modes_.clear();
    compiled_external_masks_.clear();
    compiled_external_radii_.clear();
    compiled_external_friction_.clear();
    compiled_external_ready_ = false;
    compiled_external_step_count_ = 0;
    collision_state_ready_ = false;
    partition_world_positions_.clear();
    partition_previous_world_positions_.clear();
    partition_world_rotations_.clear();
    partition_previous_world_rotations_.clear();
    partition_world_scales_.clear();
    partition_world_linear_.clear();
    anchor_world_positions_.clear();
    anchor_world_rotations_.clear();
    anchor_previous_world_positions_.clear();
    anchor_previous_world_rotations_.clear();
    anchor_present_.clear();
    partition_frame_flags_.clear();
    velocity_weights_.clear();
    gravity_ratios_.clear();
    partition_reset_counts_.clear();
    partition_keep_counts_.clear();
    distance_starts_.clear();
    distance_counts_.clear();
    distance_neighbors_.clear();
    distance_rest_lengths_.clear();
    distance_stiffness_values_.clear();
    distance_inverse_masses_.clear();
    distance_velocity_attenuation_values_.clear();
    tether_root_indices_.clear();
    tether_ready_ = false;
    baseline_parent_indices_.clear();
    baseline_line_starts_.clear();
    baseline_line_counts_.clear();
    baseline_line_data_.clear();
    baseline_vertex_local_positions_.clear();
    baseline_vertex_local_rotations_.clear();
    step_basic_positions_.clear();
    step_basic_rotations_.clear();
    baseline_pose_ready_ = false;
    baseline_ready_ = false;
    bending_dihedral_pairs_.clear();
    bending_dihedral_rest_angles_.clear();
    bending_dihedral_signs_.clear();
    bending_volume_pairs_.clear();
    bending_volume_rest_.clear();
    bending_stiffness_values_.clear();
    bending_ready_ = false;
    distance_ready_ = false;
    inertia_depths_.clear();
    inertia_inv_masses_.clear();
    inertia_ready_ = false;
    integration_damping_values_.clear();
    collision_friction_.clear();
    integration_ready_ = false;
    center_shift_vectors_.clear();
    center_shift_rotations_.clear();
    center_shift_old_frame_positions_.clear();
    center_shift_old_frame_rotations_.clear();
    center_shift_now_positions_.clear();
    center_shift_now_rotations_.clear();
    center_shift_smoothing_velocities_.clear();
    center_shift_teleport_flags_.clear();
    center_debug_raw_component_deltas_.clear();
    center_debug_anchor_shift_vectors_.clear();
    center_debug_smoothing_shift_vectors_.clear();
    center_debug_world_shift_vectors_.clear();
    center_debug_teleport_rotation_axes_.clear();
    center_debug_teleport_measured_distances_.clear();
    center_debug_teleport_distance_thresholds_.clear();
    center_debug_teleport_measured_rotation_degrees_.clear();
    center_debug_movement_speed_limited_.clear();
    center_debug_rotation_speed_limited_.clear();
    center_frame_shift_ready_ = false;
    center_frame_shift_consumed_ = false;
    center_inertia_pending_ = false;
    prediction_state_ready_ = false;
    substep_snapshot_ready_ = false;
    center_shift_count_ = 0;
}

void DomainV1::ensure_live() const {
    if (disposed_) {
        throw std::runtime_error("MC2 CPU domain has been disposed");
    }
}

void DomainV1::validate_identity(
    const char* domain_signature,
    const char* layout_signature
) const {
    require_identity(domain_signature, "domain_signature");
    require_identity(layout_signature, "layout_signature");
    if (domain_signature_ != domain_signature || layout_signature_ != layout_signature) {
        throw std::invalid_argument("MC2 CPU domain signature mismatch");
    }
}

}  // namespace hotools::mc2_domain_cpu
