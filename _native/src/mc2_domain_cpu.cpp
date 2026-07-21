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

}  // namespace

DomainV1::DomainV1(const ProgramViewV1& program)
    : particle_count_(program.particle_count),
      domain_signature_(program.domain_signature != nullptr ? program.domain_signature : ""),
      layout_signature_(program.layout_signature != nullptr ? program.layout_signature : ""),
      bind_positions_(program.particle_count * 3),
      bind_rotations_(program.particle_count * 4),
      world_positions_(program.particle_count * 3),
      world_normals_(program.particle_count * 3, 0.0f),
      velocity_positions_(program.particle_count * 3, 0.0f) {
    if (program.schema_version != 1) {
        throw std::invalid_argument("unsupported MC2 CPU domain schema version");
    }
    if (particle_count_ == 0) {
        throw std::invalid_argument("MC2 CPU domain requires particles");
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
    if (frame.frame < 0 || frame.generation < 0) {
        throw std::invalid_argument("MC2 CPU frame identity must be non-negative");
    }
    validate_identity(frame.domain_signature, frame.layout_signature);
    require_finite(frame.world_positions, particle_count_ * 3, "world_positions");
    require_finite(frame.world_normals, particle_count_ * 3, "world_normals");
    std::vector<float> next_positions(
        frame.world_positions, frame.world_positions + particle_count_ * 3
    );
    std::vector<float> next_normals(
        frame.world_normals, frame.world_normals + particle_count_ * 3
    );
    world_positions_.swap(next_positions);
    world_normals_.swap(next_normals);
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

void DomainV1::dispose() noexcept {
    disposed_ = true;
    bind_positions_.clear();
    bind_rotations_.clear();
    world_positions_.clear();
    world_normals_.clear();
    velocity_positions_.clear();
    distance_starts_.clear();
    distance_counts_.clear();
    distance_neighbors_.clear();
    distance_rest_lengths_.clear();
    distance_stiffness_values_.clear();
    distance_ready_ = false;
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
