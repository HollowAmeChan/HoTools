#include "hotools_mesh_xpbd.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_set>

namespace hotools::mesh_xpbd {
namespace {

constexpr float kEpsilon = 1.0e-7F;

bool finite(float value) {
    return std::isfinite(value);
}

void require_finite_array(const std::vector<float>& values, const char* name) {
    if (!std::all_of(values.begin(), values.end(), finite)) {
        throw std::invalid_argument(std::string(name) + " must contain finite values");
    }
}

float dot3(const std::array<float, 3>& a, const std::array<float, 3>& b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

std::array<float, 3> subtract3(
    const std::array<float, 3>& a,
    const std::array<float, 3>& b
) {
    return {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
}

std::array<float, 3> add3(
    const std::array<float, 3>& a,
    const std::array<float, 3>& b
) {
    return {a[0] + b[0], a[1] + b[1], a[2] + b[2]};
}

std::array<float, 3> multiply3(const std::array<float, 3>& value, float scale) {
    return {value[0] * scale, value[1] * scale, value[2] * scale};
}

float length3(const std::array<float, 3>& value) {
    return std::sqrt(std::max(dot3(value, value), 0.0F));
}

std::array<float, 3> normalized3(
    const std::array<float, 3>& value,
    const std::array<float, 3>& fallback = {1.0F, 0.0F, 0.0F}
) {
    const float length = length3(value);
    return length > kEpsilon ? multiply3(value, 1.0F / length) : fallback;
}

std::array<float, 3> cross3(
    const std::array<float, 3>& a,
    const std::array<float, 3>& b
) {
    return {
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    };
}

std::array<float, 3> load3(const float* values, std::size_t index) {
    const std::size_t offset = index * 3;
    return {values[offset], values[offset + 1], values[offset + 2]};
}

void store3(std::vector<float>& values, std::size_t index, const std::array<float, 3>& value) {
    const std::size_t offset = index * 3;
    values[offset] = value[0];
    values[offset + 1] = value[1];
    values[offset + 2] = value[2];
}

std::uint64_t pair_key(std::int32_t first, std::int32_t second) {
    const auto low = static_cast<std::uint32_t>(std::min(first, second));
    const auto high = static_cast<std::uint32_t>(std::max(first, second));
    return (static_cast<std::uint64_t>(high) << 32U) | low;
}

void validate_parameters(
    float damping,
    float stretch_compliance,
    float bend_compliance,
    std::int32_t iterations
) {
    if (!finite(damping) || damping < 0.0F || damping > 1.0F) {
        throw std::invalid_argument("damping must be finite and in [0,1]");
    }
    if (!finite(stretch_compliance) || stretch_compliance < 0.0F ||
        !finite(bend_compliance) || bend_compliance < 0.0F) {
        throw std::invalid_argument("constraint compliance must be finite and non-negative");
    }
    if (iterations < 0 || iterations > 64) {
        throw std::invalid_argument("iterations must be in [0,64]");
    }
}

}  // namespace

Context::Context(
    std::vector<float> rest_positions,
    std::vector<float> inverse_masses,
    std::vector<std::int32_t> stretch_indices,
    std::vector<std::int32_t> bend_indices,
    std::vector<float> collision_radii,
    float damping,
    float stretch_compliance,
    float bend_compliance,
    std::int32_t iterations
)
    : rest_positions_(std::move(rest_positions)),
      last_step_pin_positions_(rest_positions_),
      pin_positions_(rest_positions_),
      positions_(rest_positions_),
      previous_positions_(rest_positions_),
      inverse_masses_(std::move(inverse_masses)),
      collision_radii_(std::move(collision_radii)),
      stretch_indices_(std::move(stretch_indices)),
      bend_indices_(std::move(bend_indices)) {
    validate_reference_arrays(rest_positions_, inverse_masses_, collision_radii_);
    if (stretch_indices_.size() % 2 != 0 || bend_indices_.size() % 2 != 0) {
        throw std::invalid_argument("constraint index arrays must contain pairs");
    }
    update_parameters(damping, stretch_compliance, bend_compliance, iterations);
    stats_.parameter_update_count = 0;
    rebuild_constraints();
    stats_.particle_count = inverse_masses_.size();
    stats_.stretch_constraint_count = stretch_constraints_.size();
    stats_.bend_constraint_count = bend_constraints_.size();
}

void Context::require_live() const {
    if (disposed_) {
        throw std::runtime_error("Mesh XPBD context is disposed");
    }
}

void Context::validate_reference_arrays(
    const std::vector<float>& rest_positions,
    const std::vector<float>& inverse_masses,
    const std::vector<float>& collision_radii
) const {
    if (rest_positions.empty() || rest_positions.size() % 3 != 0) {
        throw std::invalid_argument("rest_positions must contain at least one float3");
    }
    const std::size_t count = rest_positions.size() / 3;
    if (inverse_masses.size() != count || collision_radii.size() != count) {
        throw std::invalid_argument("particle arrays must match rest_positions");
    }
    require_finite_array(rest_positions, "rest_positions");
    require_finite_array(inverse_masses, "inverse_masses");
    require_finite_array(collision_radii, "collision_radii");
    if (std::any_of(inverse_masses.begin(), inverse_masses.end(), [](float value) {
            return value < 0.0F;
        })) {
        throw std::invalid_argument("inverse_masses must be non-negative");
    }
    if (std::any_of(collision_radii.begin(), collision_radii.end(), [](float value) {
            return value < 0.0F;
        })) {
        throw std::invalid_argument("collision_radii must be non-negative");
    }
}

void Context::rebuild_constraints() {
    const std::size_t particle_count = inverse_masses_.size();
    auto build = [&](const std::vector<std::int32_t>& indices) {
        std::vector<Constraint> result;
        result.reserve(indices.size() / 2);
        std::unordered_set<std::uint64_t> seen;
        for (std::size_t pair = 0; pair < indices.size(); pair += 2) {
            const std::int32_t first = indices[pair];
            const std::int32_t second = indices[pair + 1];
            if (first < 0 || second < 0 || first == second ||
                static_cast<std::size_t>(first) >= particle_count ||
                static_cast<std::size_t>(second) >= particle_count) {
                throw std::invalid_argument("constraint indices are invalid");
            }
            if (!seen.insert(pair_key(first, second)).second) {
                throw std::invalid_argument("duplicate undirected constraint");
            }
            const auto delta = subtract3(
                load3(rest_positions_.data(), static_cast<std::size_t>(first)),
                load3(rest_positions_.data(), static_cast<std::size_t>(second))
            );
            Constraint constraint;
            constraint.first = first;
            constraint.second = second;
            constraint.rest_length = length3(delta);
            constraint.rest_direction = normalized3(delta);
            result.push_back(constraint);
        }
        return result;
    };
    stretch_constraints_ = build(stretch_indices_);
    bend_constraints_ = build(bend_indices_);
    stretch_lambdas_.assign(stretch_constraints_.size(), 0.0F);
    bend_lambdas_.assign(bend_constraints_.size(), 0.0F);
}

void Context::update_reference(
    std::vector<float> rest_positions,
    std::vector<float> inverse_masses,
    std::vector<float> collision_radii
) {
    require_live();
    validate_reference_arrays(rest_positions, inverse_masses, collision_radii);
    if (rest_positions.size() != rest_positions_.size()) {
        throw std::invalid_argument("reference update cannot change particle count");
    }
    rest_positions_ = std::move(rest_positions);
    last_step_pin_positions_ = rest_positions_;
    pin_positions_ = rest_positions_;
    inverse_masses_ = std::move(inverse_masses);
    collision_radii_ = std::move(collision_radii);
    rebuild_constraints();
    ++stats_.reference_update_count;
}

void Context::update_pin_targets(std::vector<float> pin_positions) {
    require_live();
    if (pin_positions.size() != rest_positions_.size()) {
        throw std::invalid_argument("pin_positions must match particle count");
    }
    require_finite_array(pin_positions, "pin_positions");
    pin_positions_ = std::move(pin_positions);
    apply_pins();
    ++stats_.pin_target_update_count;
}

void Context::update_parameters(
    float damping,
    float stretch_compliance,
    float bend_compliance,
    std::int32_t iterations
) {
    require_live();
    validate_parameters(damping, stretch_compliance, bend_compliance, iterations);
    damping_ = damping;
    stretch_compliance_ = stretch_compliance;
    bend_compliance_ = bend_compliance;
    iterations_ = iterations;
    ++stats_.parameter_update_count;
}

void Context::reset(const std::vector<float>& positions) {
    require_live();
    if (positions.size() != positions_.size()) {
        throw std::invalid_argument("reset positions must match particle count");
    }
    require_finite_array(positions, "positions");
    positions_ = positions;
    previous_positions_ = positions;
    pin_positions_ = positions;
    last_step_pin_positions_ = positions;
    std::fill(stretch_lambdas_.begin(), stretch_lambdas_.end(), 0.0F);
    std::fill(bend_lambdas_.begin(), bend_lambdas_.end(), 0.0F);
    apply_pins();
    ++stats_.reset_count;
    stats_.last_contact_count = 0;
}

void Context::solve_distance_constraints(
    const std::vector<Constraint>& constraints,
    std::vector<float>& lambdas,
    float compliance,
    float substep_delta_time
) {
    const float alpha = compliance / (substep_delta_time * substep_delta_time);
    for (std::size_t index = 0; index < constraints.size(); ++index) {
        const Constraint& constraint = constraints[index];
        const std::size_t first = static_cast<std::size_t>(constraint.first);
        const std::size_t second = static_cast<std::size_t>(constraint.second);
        const float first_weight = inverse_masses_[first];
        const float second_weight = inverse_masses_[second];
        const float denominator = first_weight + second_weight + alpha;
        if (denominator <= kEpsilon) {
            continue;
        }
        const auto first_position = load3(positions_.data(), first);
        const auto second_position = load3(positions_.data(), second);
        const auto delta = subtract3(first_position, second_position);
        const float length = length3(delta);
        const auto gradient = length > kEpsilon
            ? multiply3(delta, 1.0F / length)
            : constraint.rest_direction;
        const float constraint_value = length - constraint.rest_length;
        const float delta_lambda = (
            -constraint_value - alpha * lambdas[index]
        ) / denominator;
        lambdas[index] += delta_lambda;
        if (first_weight > 0.0F) {
            store3(
                positions_, first,
                add3(first_position, multiply3(gradient, first_weight * delta_lambda))
            );
        }
        if (second_weight > 0.0F) {
            store3(
                positions_, second,
                subtract3(second_position, multiply3(gradient, second_weight * delta_lambda))
            );
        }
    }
}

std::uint64_t Context::solve_collisions(
    const ColliderView& colliders,
    std::uint32_t collided_by_groups
) {
    if (collided_by_groups == 0 || colliders.count == 0) {
        return 0;
    }
    if (colliders.types == nullptr || colliders.group_bits == nullptr ||
        colliders.centers == nullptr || colliders.segment_a == nullptr ||
        colliders.segment_b == nullptr || colliders.radii == nullptr) {
        throw std::invalid_argument("collider view pointers cannot be null");
    }
    std::uint64_t contacts = 0;
    for (std::size_t particle = 0; particle < inverse_masses_.size(); ++particle) {
        if (inverse_masses_[particle] <= 0.0F) {
            continue;
        }
        auto position = load3(positions_.data(), particle);
        const float particle_radius = collision_radii_[particle];
        if (particle_radius <= 0.0F) {
            continue;
        }
        for (std::size_t collider = 0; collider < colliders.count; ++collider) {
            const auto group_bit = static_cast<std::uint32_t>(colliders.group_bits[collider]);
            if ((collided_by_groups & group_bit) == 0U) {
                continue;
            }
            const std::int32_t type = colliders.types[collider];
            const auto center = load3(colliders.centers, collider);
            const auto segment_a = load3(colliders.segment_a, collider);
            const auto segment_b = load3(colliders.segment_b, collider);
            const float collider_radius = colliders.radii[collider];
            bool hit = false;
            std::array<float, 3> projected = position;

            if (type == 0 || type == 1) {
                std::array<float, 3> closest = center;
                if (type == 1) {
                    const auto segment = subtract3(segment_b, segment_a);
                    const float length_squared = dot3(segment, segment);
                    const float ratio = length_squared > kEpsilon
                        ? std::clamp(
                            dot3(subtract3(position, segment_a), segment) / length_squared,
                            0.0F,
                            1.0F
                        )
                        : 0.0F;
                    closest = add3(segment_a, multiply3(segment, ratio));
                }
                const auto delta = subtract3(position, closest);
                const float distance = length3(delta);
                const float target = collider_radius + particle_radius;
                if (target > 0.0F && distance < target) {
                    projected = add3(closest, multiply3(normalized3(delta), target));
                    hit = true;
                }
            } else if (type == 2) {
                const auto normal = normalized3(segment_a, {0.0F, 0.0F, 1.0F});
                const float signed_distance = dot3(subtract3(position, center), normal);
                if (signed_distance < particle_radius) {
                    projected = add3(
                        position,
                        multiply3(normal, particle_radius - signed_distance)
                    );
                    hit = true;
                }
            } else if (type == 3) {
                const float half_x = length3(segment_a);
                const float half_y = length3(segment_b);
                const float half_z = std::abs(collider_radius);
                if (half_x > kEpsilon && half_y > kEpsilon && half_z > kEpsilon) {
                    const auto axis_x = multiply3(segment_a, 1.0F / half_x);
                    const auto axis_y = multiply3(segment_b, 1.0F / half_y);
                    auto axis_z = normalized3(cross3(axis_x, axis_y), {0.0F, 0.0F, 1.0F});
                    if (collider_radius < 0.0F) {
                        axis_z = multiply3(axis_z, -1.0F);
                    }
                    const auto relative = subtract3(position, center);
                    std::array<float, 3> local {
                        dot3(relative, axis_x),
                        dot3(relative, axis_y),
                        dot3(relative, axis_z),
                    };
                    const std::array<float, 3> half {half_x, half_y, half_z};
                    std::array<float, 3> closest_local {
                        std::clamp(local[0], -half[0], half[0]),
                        std::clamp(local[1], -half[1], half[1]),
                        std::clamp(local[2], -half[2], half[2]),
                    };
                    auto from_local = [&](const std::array<float, 3>& value) {
                        return add3(center, add3(
                            multiply3(axis_x, value[0]),
                            add3(multiply3(axis_y, value[1]), multiply3(axis_z, value[2]))
                        ));
                    };
                    const auto closest = from_local(closest_local);
                    const auto delta = subtract3(position, closest);
                    const float distance = length3(delta);
                    const bool inside =
                        std::abs(local[0]) <= half[0] &&
                        std::abs(local[1]) <= half[1] &&
                        std::abs(local[2]) <= half[2];
                    if (inside) {
                        std::size_t axis = 0;
                        float minimum_gap = half[0] - std::abs(local[0]);
                        for (std::size_t candidate = 1; candidate < 3; ++candidate) {
                            const float gap = half[candidate] - std::abs(local[candidate]);
                            if (gap < minimum_gap) {
                                minimum_gap = gap;
                                axis = candidate;
                            }
                        }
                        closest_local = local;
                        const float sign = local[axis] < 0.0F ? -1.0F : 1.0F;
                        closest_local[axis] = sign * (half[axis] + particle_radius);
                        projected = from_local(closest_local);
                        hit = true;
                    } else if (distance < particle_radius) {
                        projected = add3(
                            closest,
                            multiply3(normalized3(delta), particle_radius)
                        );
                        hit = true;
                    }
                }
            }
            if (hit) {
                position = projected;
                ++contacts;
            }
        }
        store3(positions_, particle, position);
    }
    return contacts;
}

void Context::apply_pins(float target_ratio) {
    const float ratio = std::clamp(target_ratio, 0.0F, 1.0F);
    for (std::size_t particle = 0; particle < inverse_masses_.size(); ++particle) {
        if (inverse_masses_[particle] > 0.0F) {
            continue;
        }
        const auto previous_target = load3(last_step_pin_positions_.data(), particle);
        const auto target = add3(
            previous_target,
            multiply3(
                subtract3(load3(pin_positions_.data(), particle), previous_target),
                ratio
            )
        );
        store3(positions_, particle, target);
        store3(previous_positions_, particle, target);
    }
}

void Context::step(
    float delta_time,
    std::int32_t substeps,
    const std::array<float, 3>& gravity_direction,
    float gravity_power,
    const ColliderView& colliders,
    std::uint32_t collided_by_groups
) {
    require_live();
    if (!finite(delta_time) || delta_time <= 0.0F) {
        throw std::invalid_argument("delta_time must be finite and positive");
    }
    if (substeps < 1 || substeps > 16) {
        throw std::invalid_argument("substeps must be in [1,16]");
    }
    if (!finite(gravity_power) || gravity_power < 0.0F ||
        !std::all_of(gravity_direction.begin(), gravity_direction.end(), finite)) {
        throw std::invalid_argument("gravity input must be finite and power non-negative");
    }
    if (collided_by_groups > 0xFFFFU) {
        throw std::invalid_argument("collided_by_groups exceeds the Physics World mask");
    }
    if (colliders.count > 0 && (
        colliders.types == nullptr || colliders.group_bits == nullptr ||
        colliders.centers == nullptr || colliders.segment_a == nullptr ||
        colliders.segment_b == nullptr || colliders.radii == nullptr
    )) {
        throw std::invalid_argument("collider view pointers cannot be null");
    }
    for (std::size_t collider = 0; collider < colliders.count; ++collider) {
        const std::int32_t type = colliders.types[collider];
        const std::int32_t group = colliders.group_bits[collider];
        if (type < 0 || type > 3 || group <= 0 || group > 0xFFFF ||
            (group & (group - 1)) != 0) {
            throw std::invalid_argument("collider type/group is invalid");
        }
        const auto center = load3(colliders.centers, collider);
        const auto segment_a = load3(colliders.segment_a, collider);
        const auto segment_b = load3(colliders.segment_b, collider);
        if (!std::all_of(center.begin(), center.end(), finite) ||
            !std::all_of(segment_a.begin(), segment_a.end(), finite) ||
            !std::all_of(segment_b.begin(), segment_b.end(), finite) ||
            !finite(colliders.radii[collider])) {
            throw std::invalid_argument("collider arrays must be finite");
        }
        if ((type == 0 || type == 1) && colliders.radii[collider] < 0.0F) {
            throw std::invalid_argument("sphere/capsule radius must be non-negative");
        }
        if (type == 2 && length3(segment_a) <= kEpsilon) {
            throw std::invalid_argument("plane normal must be non-zero");
        }
        if (type == 3 && (
            length3(segment_a) <= kEpsilon ||
            length3(segment_b) <= kEpsilon ||
            std::abs(colliders.radii[collider]) <= kEpsilon ||
            length3(cross3(segment_a, segment_b)) <= kEpsilon
        )) {
            throw std::invalid_argument("box axes and half extents must be non-degenerate");
        }
        if (type == 3) {
            const auto axis_x = normalized3(segment_a);
            const auto axis_y = normalized3(segment_b);
            if (std::abs(dot3(axis_x, axis_y)) > 1.0e-4F) {
                throw std::invalid_argument("box axes must be orthogonal");
            }
        }
    }

    const float substep_delta_time = delta_time / static_cast<float>(substeps);
    const float frame_velocity_retention = std::max(1.0F - damping_, 0.0F);
    const float velocity_retention = std::pow(
        frame_velocity_retention,
        1.0F / static_cast<float>(substeps)
    );
    const auto gravity_normal = normalized3(
        gravity_direction,
        {0.0F, 0.0F, 0.0F}
    );
    const auto acceleration = multiply3(gravity_normal, gravity_power);
    std::uint64_t contacts = 0;

    for (std::int32_t substep = 0; substep < substeps; ++substep) {
        for (std::size_t particle = 0; particle < inverse_masses_.size(); ++particle) {
            if (inverse_masses_[particle] <= 0.0F) {
                continue;
            }
            const auto current = load3(positions_.data(), particle);
            const auto previous = load3(previous_positions_.data(), particle);
            const auto velocity = multiply3(
                subtract3(current, previous),
                velocity_retention
            );
            store3(previous_positions_, particle, current);
            store3(
                positions_, particle,
                add3(
                    add3(current, velocity),
                    multiply3(acceleration, substep_delta_time * substep_delta_time)
                )
            );
        }
        const float pin_target_ratio = static_cast<float>(substep + 1) /
            static_cast<float>(substeps);
        apply_pins(pin_target_ratio);
        std::fill(stretch_lambdas_.begin(), stretch_lambdas_.end(), 0.0F);
        std::fill(bend_lambdas_.begin(), bend_lambdas_.end(), 0.0F);
        for (std::int32_t iteration = 0; iteration < iterations_; ++iteration) {
            solve_distance_constraints(
                stretch_constraints_, stretch_lambdas_, stretch_compliance_,
                substep_delta_time
            );
            solve_distance_constraints(
                bend_constraints_, bend_lambdas_, bend_compliance_,
                substep_delta_time
            );
            contacts += solve_collisions(colliders, collided_by_groups);
            apply_pins(pin_target_ratio);
        }
    }
    if (!std::all_of(positions_.begin(), positions_.end(), finite)) {
        throw std::runtime_error("Mesh XPBD produced non-finite positions");
    }
    last_step_pin_positions_ = pin_positions_;
    ++stats_.step_count;
    stats_.last_contact_count = contacts;
}

void Context::dispose() noexcept {
    if (disposed_) {
        return;
    }
    disposed_ = true;
    rest_positions_.clear();
    last_step_pin_positions_.clear();
    pin_positions_.clear();
    positions_.clear();
    previous_positions_.clear();
    inverse_masses_.clear();
    collision_radii_.clear();
    stretch_indices_.clear();
    bend_indices_.clear();
    stretch_constraints_.clear();
    bend_constraints_.clear();
    stretch_lambdas_.clear();
    bend_lambdas_.clear();
}

const std::vector<float>& Context::positions() const {
    require_live();
    return positions_;
}

const ContextStats& Context::stats() const {
    require_live();
    return stats_;
}

}  // namespace hotools::mesh_xpbd
