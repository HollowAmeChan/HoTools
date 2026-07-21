#include "mc2_domain_cpu.hpp"

#include "mc2_kernels.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace hotools::mc2_domain_cpu {
namespace {

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
      center_gravity_(program.partition_count, 0.0f),
      center_gravity_directions_(program.partition_count * 3, 0.0f),
      center_gravity_falloff_(program.partition_count, 0.0f),
      center_stabilization_time_(program.partition_count, 0.0f),
      center_blend_weight_(program.partition_count, 1.0f),
      center_initial_scales_(program.partition_count * 3, 1.0f),
      center_old_world_positions_(program.partition_count * 3, 0.0f),
      center_old_world_rotations_(program.partition_count * 4, 0.0f),
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
        const bool fixed = (particle_attribute_flags_[particle] & 1u) != 0u;
        const bool partition_reset =
            (frame.partition_frame_flags[partition] & 1u) != 0u;
        if (!reset_history && !partition_reset && !fixed) continue;
        const auto offset = particle * 3;
        for (std::size_t component = 0; component < 3; ++component) {
            next_positions[offset + component] = next_animated_positions[offset + component];
            next_velocity_positions[offset + component] = 0.0f;
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
        keep_view.velocities = next_velocity_positions.data();
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
    require_finite(gravity, partition_count_, "gravity");
    require_finite(gravity_directions, partition_count_ * 3, "gravity_directions");
    require_finite(gravity_falloff, partition_count_, "gravity_falloff");
    require_finite(stabilization_time, partition_count_, "stabilization_time");
    require_finite(blend_weight, partition_count_, "blend_weight");
    for (std::size_t index = 0; index < partition_count_; ++index) {
        if (local_inertia[index] < 0.0f || local_inertia[index] > 1.0f ||
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
    std::vector<float> next_shift_vectors(partition_count_ * 3, 0.0f);
    std::vector<float> next_shift_rotations(partition_count_ * 4, 0.0f);
    std::vector<float> next_shift_old_frame_positions(partition_count_ * 3, 0.0f);
    std::vector<float> next_shift_old_frame_rotations(partition_count_ * 4, 0.0f);
    std::vector<float> next_shift_now_positions(partition_count_ * 3, 0.0f);
    std::vector<float> next_shift_now_rotations(partition_count_ * 4, 0.0f);
    std::vector<float> next_smoothing_velocities = center_shift_smoothing_velocities_;
    std::vector<std::uint32_t> next_teleport_flags(partition_count_, 0u);
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
        next_teleport_flags[partition] =
            (view.teleport_triggered ? 1u : 0u) |
            (view.keep_teleport ? 2u : 0u) |
            (view.reset_teleport ? 4u : 0u);
    }
    center_shift_vectors_.swap(next_shift_vectors);
    center_shift_rotations_.swap(next_shift_rotations);
    center_shift_old_frame_positions_.swap(next_shift_old_frame_positions);
    center_shift_old_frame_rotations_.swap(next_shift_old_frame_rotations);
    center_shift_now_positions_.swap(next_shift_now_positions);
    center_shift_now_rotations_.swap(next_shift_now_rotations);
    center_shift_smoothing_velocities_.swap(next_smoothing_velocities);
    center_shift_teleport_flags_.swap(next_teleport_flags);
    center_frame_shift_ready_ = true;
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
        std::copy_n(
            (center_frame_shift_ready_
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
            (center_frame_shift_ready_
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
            (center_frame_shift_ready_
                ? center_shift_now_positions_.data()
                : center_old_world_positions_.data()) + position_offset,
            3,
            view.old_world_position
        );
        std::copy_n(
            (center_frame_shift_ready_
                ? center_shift_now_rotations_.data()
                : center_old_world_rotations_.data()) + rotation_offset,
            4,
            view.old_world_rotation
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
    ++center_step_count_;
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

void DomainV1::configure_distance(
    const std::int32_t* starts,
    const std::int32_t* counts,
    const std::int32_t* neighbors,
    const float* rest_lengths,
    const float* stiffness_values,
    std::size_t neighbor_count
) {
    ensure_live();
    if (starts == nullptr || counts == nullptr ||
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
    distance_starts_.assign(starts, starts + particle_count_);
    distance_counts_.assign(counts, counts + particle_count_);
    distance_neighbors_.assign(neighbors, neighbors + neighbor_count);
    distance_rest_lengths_.assign(rest_lengths, rest_lengths + neighbor_count);
    distance_stiffness_values_.assign(stiffness_values, stiffness_values + neighbor_count);
    distance_ready_ = true;
}

void DomainV1::step_distance() {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU distance step requires update_frame");
    }
    if (!distance_ready_) {
        throw std::logic_error("MC2 CPU distance step requires configure_distance");
    }
    const std::vector<float> base_positions = world_positions_;
    hotools::Mc2NeighborConstraintView view;
    view.positions = world_positions_.data();
    view.base_positions = base_positions.data();
    view.inv_masses = nullptr;
    std::vector<float> inv_masses(particle_count_, 1.0f);
    view.inv_masses = inv_masses.data();
    view.starts = distance_starts_.data();
    view.counts = distance_counts_.data();
    view.neighbors = distance_neighbors_.data();
    view.rest_lengths = distance_rest_lengths_.data();
    view.stiffness_values = distance_stiffness_values_.data();
    view.velocity_positions = velocity_positions_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.neighbor_count = static_cast<std::int64_t>(distance_neighbors_.size());
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
    view.inv_masses = inertia_inv_masses_.data();
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
    hotools::project_angle_constraints_mc2(view);
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
    if (normal_axis < 0 || normal_axis > 2) {
        throw std::invalid_argument("MC2 CPU Motion normal_axis must be 0, 1, or 2");
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
    hotools::project_motion_constraints_mc2(view);
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

void DomainV1::step_bending() {
    ensure_live();
    if (frame_ < 0 || generation_ < 0) {
        throw std::logic_error("MC2 CPU bending step requires update_frame");
    }
    if (!bending_ready_ || !inertia_ready_) {
        throw std::logic_error("MC2 CPU bending step requires topology and particle configuration");
    }
    hotools::Mc2TriangleBendingView view;
    view.positions = world_positions_.data();
    view.inv_masses = inertia_inv_masses_.data();
    view.stiffness_values = bending_stiffness_values_.data();
    view.dihedral_pairs = bending_dihedral_pairs_.data();
    view.dihedral_rest_angles = bending_dihedral_rest_angles_.data();
    view.dihedral_signs = bending_dihedral_signs_.data();
    view.volume_pairs = bending_volume_pairs_.data();
    view.volume_rest = bending_volume_rest_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.dihedral_count = static_cast<std::int64_t>(bending_dihedral_rest_angles_.size());
    view.volume_count = static_cast<std::int64_t>(bending_volume_rest_.size());
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
    view.velocities = velocity_positions_.data();
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
    hotools::Mc2ParticleIntegrationView view;
    view.positions = world_positions_.data();
    view.velocities = velocity_positions_.data();
    view.inv_masses = inertia_inv_masses_.data();
    view.damping_values = integration_damping_values_.data();
    view.vertex_count = static_cast<std::int64_t>(particle_count_);
    view.dt = dt;
    view.simulation_power = simulation_power;
    view.velocity_weight = velocity_weight;
    std::copy_n(gravity, 3, view.gravity);
    hotools::integrate_particles_mc2(view);
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
    tether_root_indices_.clear();
    tether_ready_ = false;
    baseline_parent_indices_.clear();
    baseline_line_starts_.clear();
    baseline_line_counts_.clear();
    baseline_line_data_.clear();
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
    center_frame_shift_ready_ = false;
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
