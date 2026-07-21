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
      world_positions_(program.particle_count * 3),
      world_normals_(program.particle_count * 3, 0.0f),
      velocity_positions_(program.particle_count * 3, 0.0f),
      partition_world_positions_(program.partition_count * 3, 0.0f),
      partition_previous_world_positions_(program.partition_count * 3, 0.0f),
      partition_world_rotations_(program.partition_count * 4, 0.0f),
      partition_previous_world_rotations_(program.partition_count * 4, 0.0f),
      partition_world_scales_(program.partition_count * 3, 1.0f),
      partition_world_linear_(program.partition_count * 9, 0.0f),
      anchor_world_positions_(program.partition_count * 3, 0.0f),
      anchor_world_rotations_(program.partition_count * 4, 0.0f),
      anchor_present_(program.partition_count, 0u),
      partition_frame_flags_(program.partition_count, 0u),
      velocity_weights_(program.partition_count, 1.0f),
      gravity_ratios_(program.partition_count, 1.0f),
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
    world_positions_ = bind_positions_;
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
    validate_identity(frame.domain_signature, frame.layout_signature);
    require_finite(frame.world_positions, particle_count_ * 3, "world_positions");
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
    std::vector<float> next_positions(
        frame.world_positions, frame.world_positions + particle_count_ * 3
    );
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
    std::vector<float> next_anchor_positions(
        frame.anchor_world_positions, frame.anchor_world_positions + partition_count_ * 3
    );
    std::vector<float> next_anchor_rotations(
        frame.anchor_world_rotations, frame.anchor_world_rotations + partition_count_ * 4
    );
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
    for (std::size_t index = 0; index < partition_count_; ++index) {
        if ((frame.partition_frame_flags[index] & 1u) != 0u) ++next_reset_counts[index];
        if ((frame.partition_frame_flags[index] & 2u) != 0u) ++next_keep_counts[index];
    }
    const bool reset_history = frame_ < 0 || generation_ != frame.generation;
    std::vector<float> next_previous_positions = reset_history
        ? next_partition_positions : partition_world_positions_;
    std::vector<float> next_previous_rotations = reset_history
        ? next_partition_rotations : partition_world_rotations_;
    world_positions_.swap(next_positions);
    world_normals_.swap(next_normals);
    partition_previous_world_positions_.swap(next_previous_positions);
    partition_previous_world_rotations_.swap(next_previous_rotations);
    partition_world_positions_.swap(next_partition_positions);
    partition_world_rotations_.swap(next_partition_rotations);
    partition_world_scales_.swap(next_partition_scales);
    partition_world_linear_.swap(next_partition_linear);
    anchor_world_positions_.swap(next_anchor_positions);
    anchor_world_rotations_.swap(next_anchor_rotations);
    anchor_present_.swap(next_anchor_present);
    partition_frame_flags_.swap(next_frame_flags);
    velocity_weights_.swap(next_velocity_weights);
    gravity_ratios_.swap(next_gravity_ratios);
    partition_reset_counts_.swap(next_reset_counts);
    partition_keep_counts_.swap(next_keep_counts);
    frame_ = frame.frame;
    generation_ = frame.generation;
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
    bind_positions_.clear();
    bind_rotations_.clear();
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
    distance_ready_ = false;
    inertia_depths_.clear();
    inertia_inv_masses_.clear();
    inertia_ready_ = false;
    integration_damping_values_.clear();
    integration_ready_ = false;
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
