#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace hotools::mesh_xpbd {

constexpr std::uint32_t kSchemaVersion = 1;

struct ColliderView {
    std::size_t count = 0;
    const std::int32_t* types = nullptr;
    const std::int32_t* group_bits = nullptr;
    const float* centers = nullptr;
    const float* segment_a = nullptr;
    const float* segment_b = nullptr;
    const float* radii = nullptr;
};

struct ContextStats {
    std::uint64_t step_count = 0;
    std::uint64_t reset_count = 0;
    std::uint64_t parameter_update_count = 0;
    std::uint64_t reference_update_count = 0;
    std::uint64_t pin_target_update_count = 0;
    std::uint64_t last_contact_count = 0;
    std::size_t particle_count = 0;
    std::size_t stretch_constraint_count = 0;
    std::size_t bend_constraint_count = 0;
};

class Context final {
public:
    Context(
        std::vector<float> rest_positions,
        std::vector<float> inverse_masses,
        std::vector<std::int32_t> stretch_indices,
        std::vector<std::int32_t> bend_indices,
        std::vector<float> collision_radii,
        float damping,
        float stretch_compliance,
        float bend_compliance,
        std::int32_t iterations
    );

    Context(const Context&) = delete;
    Context& operator=(const Context&) = delete;
    Context(Context&&) = delete;
    Context& operator=(Context&&) = delete;
    ~Context() = default;

    void update_reference(
        std::vector<float> rest_positions,
        std::vector<float> inverse_masses,
        std::vector<float> collision_radii
    );
    void update_parameters(
        float damping,
        float stretch_compliance,
        float bend_compliance,
        std::int32_t iterations
    );
    void set_orientation_guard(bool enabled);
    void update_pin_targets(std::vector<float> pin_positions);
    void reset(const std::vector<float>& positions);
    void step(
        float delta_time,
        std::int32_t substeps,
        const std::array<float, 3>& gravity_direction,
        float gravity_power,
        const ColliderView& colliders,
        std::uint32_t collided_by_groups
    );
    void dispose() noexcept;

    [[nodiscard]] bool disposed() const noexcept { return disposed_; }
    [[nodiscard]] const std::vector<float>& positions() const;
    [[nodiscard]] const ContextStats& stats() const;

private:
    struct Constraint {
        std::int32_t first = 0;
        std::int32_t second = 0;
        float rest_length = 0.0F;
        std::array<float, 3> rest_direction {1.0F, 0.0F, 0.0F};
    };

    void require_live() const;
    void validate_reference_arrays(
        const std::vector<float>& rest_positions,
        const std::vector<float>& inverse_masses,
        const std::vector<float>& collision_radii
    ) const;
    void rebuild_constraints();
    void solve_distance_constraints(
        const std::vector<Constraint>& constraints,
        std::vector<float>& lambdas,
        float compliance,
        float substep_delta_time
    );
    void enforce_orientation_guard(
        const std::vector<Constraint>& constraints
    );
    std::uint64_t solve_collisions(
        const ColliderView& colliders,
        std::uint32_t collided_by_groups
    );
    void apply_pins(float target_ratio = 1.0F);

    bool disposed_ = false;
    std::vector<float> rest_positions_;
    std::vector<float> last_step_pin_positions_;
    std::vector<float> pin_positions_;
    std::vector<float> positions_;
    std::vector<float> previous_positions_;
    std::vector<float> orientation_reference_positions_;
    std::vector<float> inverse_masses_;
    std::vector<float> collision_radii_;
    std::vector<std::int32_t> stretch_indices_;
    std::vector<std::int32_t> bend_indices_;
    std::vector<Constraint> stretch_constraints_;
    std::vector<Constraint> bend_constraints_;
    std::vector<float> stretch_lambdas_;
    std::vector<float> bend_lambdas_;
    float damping_ = 0.0F;
    float stretch_compliance_ = 0.0F;
    float bend_compliance_ = 0.0F;
    std::int32_t iterations_ = 0;
    bool orientation_guard_ = false;
    ContextStats stats_;
};

}  // namespace hotools::mesh_xpbd
