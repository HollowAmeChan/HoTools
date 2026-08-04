#include "hotools_mesh_xpbd.hpp"

#include <cmath>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace xpbd = hotools::mesh_xpbd;

namespace {

void require_close(float actual, float expected, const char* message) {
    if (std::abs(actual - expected) > 1.0e-5F) {
        throw std::runtime_error(message);
    }
}

xpbd::Context make_distance_context(float compliance, std::int32_t iterations) {
    return xpbd::Context(
        {0.0F, 0.0F, 0.0F, 1.0F, 0.0F, 0.0F},
        {0.0F, 1.0F},
        {0, 1},
        {},
        {0.0F, 0.0F},
        0.0F,
        compliance,
        0.0F,
        iterations
    );
}

void test_accumulated_lambda() {
    auto context = make_distance_context(1.0F, 2);
    context.reset({0.0F, 0.0F, 0.0F, 2.0F, 0.0F, 0.0F});
    context.step(1.0F, 1, {0.0F, 0.0F, 0.0F}, 0.0F, {}, 0U);
    require_close(context.positions()[3], 1.5F, "XPBD lambda was not accumulated");
}

void test_hard_constraint() {
    auto context = make_distance_context(0.0F, 2);
    context.reset({0.0F, 0.0F, 0.0F, 2.0F, 0.0F, 0.0F});
    context.step(1.0F, 1, {0.0F, 0.0F, 0.0F}, 0.0F, {}, 0U);
    require_close(context.positions()[3], 1.0F, "hard distance constraint failed");
}

void test_moving_pin_target_does_not_change_rest_length() {
    auto context = make_distance_context(0.0F, 2);
    context.update_pin_targets({1.0F, 0.0F, 0.0F, 1.0F, 0.0F, 0.0F});
    context.step(1.0F, 1, {0.0F, 0.0F, 0.0F}, 0.0F, {}, 0U);
    require_close(context.positions()[0], 1.0F, "moving pin target was not applied");
    require_close(context.positions()[3], 2.0F, "moving pin changed constraint rest length");
}

void test_fast_moving_pin_uses_substep_trajectory() {
    auto context = make_distance_context(1.0F, 1);
    context.update_pin_targets({10.0F, 0.0F, 0.0F, 1.0F, 0.0F, 0.0F});
    require_close(context.positions()[0], 10.0F, "same-frame pin sync missed its target");
    context.step(1.0F, 2, {0.0F, 0.0F, 0.0F}, 0.0F, {}, 0U);
    require_close(context.positions()[0], 10.0F, "moving pin missed its final target");
    require_close(
        context.positions()[3], 3.56F,
        "moving pin target was not interpolated across substeps"
    );
}

void test_same_frame_pin_updates_do_not_advance_step_history() {
    auto context = make_distance_context(1.0F, 1);
    context.update_pin_targets({5.0F, 0.0F, 0.0F, 1.0F, 0.0F, 0.0F});
    context.update_pin_targets({10.0F, 0.0F, 0.0F, 1.0F, 0.0F, 0.0F});
    context.step(1.0F, 2, {0.0F, 0.0F, 0.0F}, 0.0F, {}, 0U);
    require_close(
        context.positions()[3], 3.56F,
        "same-frame pin sync advanced the last consumed target"
    );
}

void test_reset_synchronizes_moving_pin_history() {
    auto reset_context = make_distance_context(1.0F, 1);
    reset_context.update_pin_targets({10.0F, 0.0F, 0.0F, 1.0F, 0.0F, 0.0F});
    reset_context.reset({3.0F, 0.0F, 0.0F, 4.0F, 0.0F, 0.0F});
    reset_context.update_pin_targets({7.0F, 0.0F, 0.0F, 4.0F, 0.0F, 0.0F});
    reset_context.step(1.0F, 2, {0.0F, 0.0F, 0.0F}, 0.0F, {}, 0U);

    xpbd::Context cold_context(
        {3.0F, 0.0F, 0.0F, 4.0F, 0.0F, 0.0F},
        {0.0F, 1.0F},
        {0, 1},
        {},
        {0.0F, 0.0F},
        0.0F,
        1.0F,
        0.0F,
        1
    );
    cold_context.update_pin_targets({7.0F, 0.0F, 0.0F, 4.0F, 0.0F, 0.0F});
    cold_context.step(1.0F, 2, {0.0F, 0.0F, 0.0F}, 0.0F, {}, 0U);

    for (std::size_t index = 0; index < reset_context.positions().size(); ++index) {
        require_close(
            reset_context.positions()[index],
            cold_context.positions()[index],
            "reset did not synchronize moving Pin history"
        );
    }
}

void test_sphere_collision() {
    xpbd::Context context(
        {0.5F, 0.0F, 0.0F}, {1.0F}, {}, {}, {0.1F},
        0.0F, 0.0F, 0.0F, 1
    );
    const std::int32_t types[] = {0};
    const std::int32_t groups[] = {1};
    const float centers[] = {0.0F, 0.0F, 0.0F};
    const float segment_a[] = {0.0F, 0.0F, 0.0F};
    const float segment_b[] = {0.0F, 0.0F, 0.0F};
    const float radii[] = {1.0F};
    const xpbd::ColliderView view {
        1, types, groups, centers, segment_a, segment_b, radii,
    };
    context.step(1.0F, 1, {0.0F, 0.0F, 0.0F}, 0.0F, view, 1U);
    require_close(context.positions()[0], 1.1F, "sphere collision failed");
}

}  // namespace

int main() {
    try {
        test_accumulated_lambda();
        test_hard_constraint();
        test_moving_pin_target_does_not_change_rest_length();
        test_fast_moving_pin_uses_substep_trajectory();
        test_same_frame_pin_updates_do_not_advance_step_history();
        test_reset_synchronizes_moving_pin_history();
        test_sphere_collision();
        std::cout << "Mesh XPBD core: 7 passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Mesh XPBD core failure: " << error.what() << '\n';
        return 1;
    }
}
