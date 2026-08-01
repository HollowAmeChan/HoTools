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
        test_sphere_collision();
        std::cout << "Mesh XPBD core: 3 passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Mesh XPBD core failure: " << error.what() << '\n';
        return 1;
    }
}
