#include "rigid_writeback.hpp"

#include <nanobind/ndarray.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace nb = nanobind;

namespace hotools {
namespace {

using cf32_2d = nb::ndarray<const float, nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using ci32_1d = nb::ndarray<const std::int32_t, nb::ndim<1>, nb::c_contig, nb::device::cpu>;

struct Quaternion {
    float w;
    float x;
    float y;
    float z;
};

Quaternion multiply(const Quaternion& a, const Quaternion& b) {
    return {
        a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
        a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
        a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
        a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
    };
}

Quaternion normalize(Quaternion value) {
    const float length = std::sqrt(
        value.w * value.w + value.x * value.x
        + value.y * value.y + value.z * value.z
    );
    if (!(length > 1.0e-20f) || !std::isfinite(length))
        return {1.0f, 0.0f, 0.0f, 0.0f};
    const float inverse = 1.0f / length;
    return {
        value.w * inverse,
        value.x * inverse,
        value.y * inverse,
        value.z * inverse,
    };
}

Quaternion conjugated(const Quaternion& value) {
    return {value.w, -value.x, -value.y, -value.z};
}

Quaternion axis_quaternion(float angle, float x, float y, float z) {
    const float length = std::sqrt(x * x + y * y + z * z);
    if (!(length > 1.0e-20f) || !std::isfinite(length)) {
        x = 0.0f;
        y = 0.0f;
        z = 1.0f;
    } else {
        const float inverse = 1.0f / length;
        x *= inverse;
        y *= inverse;
        z *= inverse;
    }
    const float half = angle * 0.5f;
    const float sine = std::sin(half);
    return normalize({std::cos(half), x * sine, y * sine, z * sine});
}

Quaternion axis_quaternion(char axis, float angle) {
    if (axis == 'X')
        return axis_quaternion(angle, 1.0f, 0.0f, 0.0f);
    if (axis == 'Y')
        return axis_quaternion(angle, 0.0f, 1.0f, 0.0f);
    return axis_quaternion(angle, 0.0f, 0.0f, 1.0f);
}

Quaternion euler_quaternion(const float* values, std::int32_t mode) {
    static constexpr const char* orders[] = {
        "XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX",
    };
    const std::int32_t order_index = std::clamp(mode, 0, 5);
    const char* order = orders[order_index];
    const float x = values[0];
    const float y = values[1];
    const float z = values[2];
    auto angle_for = [x, y, z](char axis) {
        return axis == 'X' ? x : (axis == 'Y' ? y : z);
    };
    // Blender 的 Euler 顺序对应从右到左的轴四元数乘法。
    Quaternion result = axis_quaternion(order[2], angle_for(order[2]));
    result = multiply(result, axis_quaternion(order[1], angle_for(order[1])));
    result = multiply(result, axis_quaternion(order[0], angle_for(order[0])));
    return normalize(result);
}

struct EulerOrder {
    int axis[3];
    bool parity;
};

constexpr EulerOrder kEulerOrders[] = {
    {{0, 1, 2}, false},
    {{0, 2, 1}, true},
    {{1, 0, 2}, true},
    {{1, 2, 0}, false},
    {{2, 0, 1}, false},
    {{2, 1, 0}, true},
};

void quaternion_to_matrix(const Quaternion& value, float matrix[3][3]) {
    const float q0 = 1.4142135623730951f * value.w;
    const float q1 = 1.4142135623730951f * value.x;
    const float q2 = 1.4142135623730951f * value.y;
    const float q3 = 1.4142135623730951f * value.z;
    const float qda = q0 * q1;
    const float qdb = q0 * q2;
    const float qdc = q0 * q3;
    const float qaa = q1 * q1;
    const float qab = q1 * q2;
    const float qac = q1 * q3;
    const float qbb = q2 * q2;
    const float qbc = q2 * q3;
    const float qcc = q3 * q3;
    matrix[0][0] = 1.0f - qbb - qcc;
    matrix[0][1] = qdc + qab;
    matrix[0][2] = -qdb + qac;
    matrix[1][0] = -qdc + qab;
    matrix[1][1] = 1.0f - qaa - qcc;
    matrix[1][2] = qda + qbc;
    matrix[2][0] = qdb + qac;
    matrix[2][1] = -qda + qbc;
    matrix[2][2] = 1.0f - qaa - qbb;
}

void quaternion_to_euler(const Quaternion& value, std::int32_t mode, float output[3]) {
    const EulerOrder& order = kEulerOrders[std::clamp(mode, 0, 5)];
    float matrix[3][3];
    quaternion_to_matrix(value, matrix);
    const int i = order.axis[0];
    const int j = order.axis[1];
    const int k = order.axis[2];
    const float cy = std::hypot(matrix[i][i], matrix[i][j]);
    float first[3] = {0.0f, 0.0f, 0.0f};
    float second[3] = {0.0f, 0.0f, 0.0f};
    constexpr float epsilon = 0.0000375f;
    if (cy > epsilon) {
        first[i] = std::atan2(matrix[j][k], matrix[k][k]);
        first[j] = std::atan2(-matrix[i][k], cy);
        first[k] = std::atan2(matrix[i][j], matrix[i][i]);
        second[i] = std::atan2(-matrix[j][k], -matrix[k][k]);
        second[j] = std::atan2(-matrix[i][k], -cy);
        second[k] = std::atan2(-matrix[i][j], -matrix[i][i]);
    } else {
        first[i] = std::atan2(-matrix[k][j], matrix[j][j]);
        first[j] = std::atan2(-matrix[i][k], cy);
        first[k] = 0.0f;
        std::copy(first, first + 3, second);
    }
    if (order.parity) {
        for (int axis = 0; axis < 3; ++axis) {
            first[axis] = -first[axis];
            second[axis] = -second[axis];
        }
    }
    const float first_length = std::fabs(first[0]) + std::fabs(first[1]) + std::fabs(first[2]);
    const float second_length = std::fabs(second[0]) + std::fabs(second[1]) + std::fabs(second[2]);
    const float* selected = first_length <= second_length ? first : second;
    std::copy(selected, selected + 3, output);
}

template<typename T>
nb::ndarray<nb::numpy, T> owned_array_2d(
    const std::vector<T>& source,
    std::size_t rows,
    std::size_t columns
) {
    auto* owner_data = new std::vector<T>(source);
    nb::capsule owner(owner_data, [](void* pointer) noexcept {
        delete static_cast<std::vector<T>*>(pointer);
    });
    return nb::ndarray<nb::numpy, T>(
        owner_data->data(), {rows, columns}, owner
    );
}

void require_shape(cf32_2d values, std::size_t columns, const char* name) {
    if (values.shape(1) != columns)
        throw nb::value_error((std::string(name) + " has an invalid column count").c_str());
}

}  // namespace

void bind_rigid_writeback(nb::module_& module) {
    module.def(
        "compute_rigid_delta_columns_v2",
        [](
            cf32_2d base_locations,
            cf32_2d base_rotation_eulers,
            cf32_2d base_rotation_quaternions,
            cf32_2d base_rotation_axis_angles,
            cf32_2d solved_positions,
            cf32_2d solved_rotations_wxyz,
            ci32_1d object_indices,
            ci32_1d rotation_modes
        ) {
            require_shape(base_locations, 3, "base_locations");
            require_shape(base_rotation_eulers, 3, "base_rotation_eulers");
            require_shape(base_rotation_quaternions, 4, "base_rotation_quaternions");
            require_shape(base_rotation_axis_angles, 4, "base_rotation_axis_angles");
            require_shape(solved_positions, 3, "solved_positions");
            require_shape(solved_rotations_wxyz, 4, "solved_rotations_wxyz");

            const std::size_t base_count = static_cast<std::size_t>(base_locations.shape(0));
            const std::size_t count = static_cast<std::size_t>(solved_positions.shape(0));
            if (
                static_cast<std::size_t>(base_rotation_eulers.shape(0)) != base_count
                || static_cast<std::size_t>(base_rotation_quaternions.shape(0)) != base_count
                || static_cast<std::size_t>(base_rotation_axis_angles.shape(0)) != base_count
                || static_cast<std::size_t>(solved_rotations_wxyz.shape(0)) != count
                || static_cast<std::size_t>(object_indices.shape(0)) != count
                || static_cast<std::size_t>(rotation_modes.shape(0)) != count
            ) {
                throw nb::value_error("rigid writeback arrays have inconsistent row counts");
            }

            std::vector<float> delta_locations(count * 3u, 0.0f);
            std::vector<float> delta_eulers(count * 3u, 0.0f);
            std::vector<float> delta_quaternions(count * 4u, 0.0f);
            for (std::size_t row = 0; row < count; ++row) {
                const std::int32_t object_index = object_indices.data()[row];
                if (object_index < 0 || static_cast<std::size_t>(object_index) >= base_count)
                    throw nb::value_error("rigid writeback object index is out of range");
                const std::size_t base = static_cast<std::size_t>(object_index);
                const std::int32_t mode = rotation_modes.data()[row];
                if (mode < 0 || mode > 7)
                    throw nb::value_error("rigid writeback rotation mode is invalid");

                const float* base_position = base_locations.data() + base * 3u;
                const float* solved_position = solved_positions.data() + row * 3u;
                float* delta_position = delta_locations.data() + row * 3u;
                delta_position[0] = solved_position[0] - base_position[0];
                delta_position[1] = solved_position[1] - base_position[1];
                delta_position[2] = solved_position[2] - base_position[2];

                Quaternion rest;
                if (mode <= 5) {
                    rest = euler_quaternion(
                        base_rotation_eulers.data() + base * 3u,
                        mode
                    );
                } else if (mode == 6) {
                    const float* values = base_rotation_quaternions.data() + base * 4u;
                    rest = normalize({values[0], values[1], values[2], values[3]});
                } else {
                    const float* values = base_rotation_axis_angles.data() + base * 4u;
                    rest = axis_quaternion(values[0], values[1], values[2], values[3]);
                }

                const float* solved = solved_rotations_wxyz.data() + row * 4u;
                const Quaternion current = normalize({solved[0], solved[1], solved[2], solved[3]});
                const Quaternion delta = normalize(multiply(conjugated(rest), current));
                if (mode <= 5)
                    quaternion_to_euler(delta, mode, delta_eulers.data() + row * 3u);
                float* delta_rotation = delta_quaternions.data() + row * 4u;
                delta_rotation[0] = delta.w;
                delta_rotation[1] = delta.x;
                delta_rotation[2] = delta.y;
                delta_rotation[3] = delta.z;
            }

            return nb::make_tuple(
                owned_array_2d(delta_locations, count, 3),
                owned_array_2d(delta_eulers, count, 3),
                owned_array_2d(delta_quaternions, count, 4)
            );
        },
        nb::arg("base_locations"),
        nb::arg("base_rotation_eulers"),
        nb::arg("base_rotation_quaternions"),
        nb::arg("base_rotation_axis_angles"),
        nb::arg("solved_positions"),
        nb::arg("solved_rotations_wxyz"),
        nb::arg("object_indices"),
        nb::arg("rotation_modes"),
        "计算刚体写回所需的位置增量和旋转增量四元数。"
    );
}

}  // namespace hotools
