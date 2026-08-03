#include "mc2_frame_orientations.hpp"

#include "mc2_api.hpp"
#include "python_buffer_utils.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace hotools {
namespace {

constexpr float kMc2Epsilon = 0.00000001f;

struct Vec3 {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

Vec3 add(Vec3 a, Vec3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
Vec3 sub(Vec3 a, Vec3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
Vec3 mul(Vec3 a, float value) { return {a.x * value, a.y * value, a.z * value}; }
float dot(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
Vec3 cross(Vec3 a, Vec3 b) {
    return {
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
    };
}
float length(Vec3 value) { return std::sqrt(dot(value, value)); }
Vec3 normalize(Vec3 value) {
    const float size = length(value);
    return size > kMc2Epsilon ? mul(value, 1.0f / size) : Vec3 {};
}

void normalize_quaternion(std::array<float, 4>& value) {
    float length_squared = 0.0f;
    for (const float component : value) length_squared += component * component;
    if (length_squared <= kMc2Epsilon) {
        value = {0.0f, 0.0f, 0.0f, 1.0f};
        return;
    }
    const float inverse_length = 1.0f / std::sqrt(length_squared);
    for (float& component : value) component *= inverse_length;
}

std::array<float, 4> quaternion_multiply(
    const std::array<float, 4>& left,
    const std::array<float, 4>& right
) {
    const float lx = left[0], ly = left[1], lz = left[2], lw = left[3];
    const float rx = right[0], ry = right[1], rz = right[2], rw = right[3];
    return {
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    };
}

std::array<float, 4> quaternion_inverse(std::array<float, 4> value) {
    normalize_quaternion(value);
    return {-value[0], -value[1], -value[2], value[3]};
}

Vec3 rotate_vector(const std::array<float, 4>& raw_rotation, Vec3 value) {
    auto rotation = raw_rotation;
    normalize_quaternion(rotation);
    const Vec3 axis {rotation[0], rotation[1], rotation[2]};
    const Vec3 twice_cross = mul(cross(axis, value), 2.0f);
    return add(add(value, mul(twice_cross, rotation[3])), cross(axis, twice_cross));
}

std::array<float, 4> quaternion_slerp(
    std::array<float, 4> first,
    std::array<float, 4> second,
    float ratio
) {
    normalize_quaternion(first);
    normalize_quaternion(second);
    float cosine = 0.0f;
    for (std::size_t component = 0; component < 4; ++component) {
        cosine += first[component] * second[component];
    }
    if (cosine < 0.0f) {
        for (float& component : second) component = -component;
        cosine = -cosine;
    }
    cosine = std::clamp(cosine, -1.0f, 1.0f);
    std::array<float, 4> result {};
    if (cosine > 0.9995f) {
        for (std::size_t component = 0; component < 4; ++component) {
            result[component] = first[component] +
                (second[component] - first[component]) * ratio;
        }
    } else {
        const float angle = std::acos(cosine);
        const float sine = std::sin(angle);
        const float first_weight = std::sin((1.0f - ratio) * angle) / sine;
        const float second_weight = std::sin(ratio * angle) / sine;
        for (std::size_t component = 0; component < 4; ++component) {
            result[component] = first[component] * first_weight +
                second[component] * second_weight;
        }
    }
    normalize_quaternion(result);
    return result;
}

std::array<float, 4> quaternion_from_to(Vec3 first, Vec3 second, float ratio = 1.0f) {
    first = normalize(first);
    second = normalize(second);
    const float cosine = std::clamp(dot(first, second), -1.0f, 1.0f);
    if (std::abs(1.0f - cosine) < 1.0e-6f) {
        return {0.0f, 0.0f, 0.0f, 1.0f};
    }
    Vec3 axis = cross(first, second);
    float angle = std::acos(cosine);
    if (std::abs(1.0f + cosine) < 1.0e-6f) {
        angle = 3.14159265358979323846f;
        axis = first.x > first.y && first.x > first.z
            ? cross(first, Vec3 {0.0f, 1.0f, 0.0f})
            : cross(first, Vec3 {1.0f, 0.0f, 0.0f});
    }
    axis = normalize(axis);
    const float half_angle = angle * ratio * 0.5f;
    const float sine = std::sin(half_angle);
    std::array<float, 4> result {
        axis.x * sine,
        axis.y * sine,
        axis.z * sine,
        std::cos(half_angle),
    };
    normalize_quaternion(result);
    return result;
}

Vec3 load_vector3(const float* values, std::size_t index) {
    const auto offset = index * 3;
    return {values[offset], values[offset + 1], values[offset + 2]};
}

std::array<float, 4> load_quaternion(const float* values, std::size_t index) {
    const auto offset = index * 4;
    std::array<float, 4> result {
        values[offset], values[offset + 1], values[offset + 2], values[offset + 3]
    };
    normalize_quaternion(result);
    return result;
}

void store_quaternion(float* values, std::size_t index, std::array<float, 4> rotation) {
    normalize_quaternion(rotation);
    const auto offset = index * 4;
    std::copy(rotation.begin(), rotation.end(), values + offset);
}

std::array<float, 4> quaternion_from_forward_up(Vec3 forward, Vec3 up) {
    const Vec3 z = normalize(forward);
    const Vec3 x = normalize(cross(up, z));
    const Vec3 y = cross(z, x);
    const float m00 = x.x, m01 = y.x, m02 = z.x;
    const float m10 = x.y, m11 = y.y, m12 = z.y;
    const float m20 = x.z, m21 = y.z, m22 = z.z;
    std::array<float, 4> result {};
    const float trace = m00 + m11 + m22;
    if (trace > 0.0f) {
        const float s = std::sqrt(trace + 1.0f) * 2.0f;
        result = {
            (m21 - m12) / s,
            (m02 - m20) / s,
            (m10 - m01) / s,
            0.25f * s,
        };
    } else if (m00 > m11 && m00 > m22) {
        const float s = std::sqrt(1.0f + m00 - m11 - m22) * 2.0f;
        result = {
            0.25f * s,
            (m01 + m10) / s,
            (m02 + m20) / s,
            (m21 - m12) / s,
        };
    } else if (m11 > m22) {
        const float s = std::sqrt(1.0f + m11 - m00 - m22) * 2.0f;
        result = {
            (m01 + m10) / s,
            0.25f * s,
            (m12 + m21) / s,
            (m02 - m20) / s,
        };
    } else {
        const float s = std::sqrt(1.0f + m22 - m00 - m11) * 2.0f;
        result = {
            (m02 + m20) / s,
            (m12 + m21) / s,
            0.25f * s,
            (m10 - m01) / s,
        };
    }
    normalize_quaternion(result);
    return result;
}

bool finite_floats(const py::Buffer& buffer, const char* name) {
    const auto count = static_cast<std::size_t>(buffer.view.len / sizeof(float));
    const auto* values = static_cast<const float*>(buffer.view.buf);
    for (std::size_t index = 0; index < count; ++index) {
        if (!std::isfinite(values[index])) {
            PyErr_Format(PyExc_ValueError, "%s must contain finite values", name);
            return false;
        }
    }
    return true;
}

bool expect_2d(
    const py::Buffer& buffer,
    const char* name,
    Py_ssize_t rows,
    Py_ssize_t columns
) {
    if (buffer.view.ndim != 2 || buffer.view.shape == nullptr ||
        buffer.view.shape[0] != rows || buffer.view.shape[1] != columns) {
        PyErr_Format(
            PyExc_ValueError,
            "%s must have shape (%zd, %zd)",
            name,
            rows,
            columns
        );
        return false;
    }
    return true;
}

bool validate_dense_ranges(
    const py::Buffer& ranges,
    Py_ssize_t data_count,
    const char* name
) {
    const auto* values = static_cast<const std::int32_t*>(ranges.view.buf);
    Py_ssize_t next = 0;
    for (Py_ssize_t row = 0; row < ranges.view.shape[0]; ++row) {
        const auto start = static_cast<Py_ssize_t>(values[row * 2]);
        const auto count = static_cast<Py_ssize_t>(values[row * 2 + 1]);
        if (start != next || count < 0 || start + count > data_count) {
            PyErr_Format(PyExc_ValueError, "%s must contain dense valid ranges", name);
            return false;
        }
        next += count;
    }
    if (next != data_count) {
        PyErr_Format(PyExc_ValueError, "%s must cover all records", name);
        return false;
    }
    return true;
}

bool validate_quaternions(const py::Buffer& rotations, const char* name) {
    const auto* values = static_cast<const float*>(rotations.view.buf);
    for (Py_ssize_t row = 0; row < rotations.view.shape[0]; ++row) {
        double length_squared = 0.0;
        for (std::size_t component = 0; component < 4; ++component) {
            const auto value = values[static_cast<std::size_t>(row) * 4 + component];
            length_squared += static_cast<double>(value) * value;
        }
        if (!std::isfinite(length_squared) ||
            std::abs(length_squared - 1.0) > 2.0e-5) {
            PyErr_Format(PyExc_ValueError, "%s must contain unit quaternions", name);
            return false;
        }
    }
    return true;
}

}  // namespace

bool derive_mesh_frame_orientations(const Mc2MeshFrameOrientationView& view) {
    const auto vertex_count = view.vertex_count;
    const auto triangle_count = view.triangle_count;
    if (triangle_count == 0) return true;
    const bool has_corner_uvs = view.triangle_uv_count == triangle_count * 6;
    if (view.positions == nullptr || view.triangles == nullptr ||
        view.triangle_ranges == nullptr || view.output_rotations == nullptr ||
        (!has_corner_uvs &&
         (view.proxy_uvs == nullptr || view.proxy_uv_count != vertex_count * 2)) ||
        (has_corner_uvs && view.triangle_uvs == nullptr) ||
        view.triangle_range_count != vertex_count * 2 ||
        (view.triangle_record_count != 0 && view.triangle_records == nullptr)) {
        return false;
    }

    const auto load_position = [&](std::size_t vertex) {
        const auto offset = vertex * 3;
        return Vec3 {
            view.positions[offset + 0],
            view.positions[offset + 1],
            view.positions[offset + 2],
        };
    };
    const auto store_output = [&](std::size_t vertex, std::array<float, 4> rotation) {
        normalize_quaternion(rotation);
        const auto offset = vertex * 4;
        for (std::size_t component = 0; component < 4; ++component) {
            view.output_rotations[offset + component] = rotation[component];
        }
    };

    std::vector<Vec3> triangle_normals(triangle_count);
    std::vector<Vec3> triangle_tangents(triangle_count);
    for (std::size_t triangle = 0; triangle < triangle_count; ++triangle) {
        const auto vertex0 = static_cast<std::size_t>(view.triangles[triangle * 3]);
        const auto vertex1 = static_cast<std::size_t>(view.triangles[triangle * 3 + 1]);
        const auto vertex2 = static_cast<std::size_t>(view.triangles[triangle * 3 + 2]);
        if (vertex0 >= vertex_count || vertex1 >= vertex_count || vertex2 >= vertex_count) {
            return false;
        }
        const Vec3 position0 = load_position(vertex0);
        const Vec3 position1 = load_position(vertex1);
        const Vec3 position2 = load_position(vertex2);
        const Vec3 edge_ba = sub(position1, position0);
        const Vec3 edge_ca = sub(position2, position0);
        const Vec3 triangle_cross = cross(edge_ba, edge_ca);
        const float normal_length = length(triangle_cross);
        if (normal_length > kMc2Epsilon) {
            triangle_normals[triangle] = mul(triangle_cross, 1.0f / normal_length);
        }

        const auto uv_value = [&](std::size_t corner, std::size_t vertex, std::size_t component) {
            return has_corner_uvs
                ? view.triangle_uvs[triangle * 6 + corner * 2 + component]
                : view.proxy_uvs[vertex * 2 + component];
        };
        const float uv_ba_x = uv_value(1, vertex1, 0) - uv_value(0, vertex0, 0);
        const float uv_ba_y = uv_value(1, vertex1, 1) - uv_value(0, vertex0, 1);
        const float uv_ca_x = uv_value(2, vertex2, 0) - uv_value(0, vertex0, 0);
        const float uv_ca_y = uv_value(2, vertex2, 1) - uv_value(0, vertex0, 1);
        float area = uv_ba_x * uv_ca_y - uv_ba_y * uv_ca_x;
        if (area == 0.0f) area = 1.0f;
        const float delta = 1.0f / area;
        const Vec3 tangent = mul(
            add(mul(edge_ba, uv_ca_y), mul(edge_ca, -uv_ba_y)),
            -delta
        );
        const float tangent_length = length(tangent);
        if (tangent_length > 0.0f) {
            triangle_tangents[triangle] = mul(tangent, 1.0f / tangent_length);
        }
    }

    const auto record_count = view.triangle_record_count / 2;
    for (std::size_t vertex = 0; vertex < vertex_count; ++vertex) {
        const auto start = view.triangle_ranges[vertex * 2];
        const auto count = view.triangle_ranges[vertex * 2 + 1];
        if (start < 0 || count < 0 ||
            static_cast<std::size_t>(start + count) > record_count) {
            return false;
        }
        if (count == 0) continue;
        Vec3 normal {};
        Vec3 tangent {};
        for (std::int32_t offset = 0; offset < count; ++offset) {
            const auto record = static_cast<std::size_t>(start + offset);
            const auto flip = view.triangle_records[record * 2];
            const auto triangle = view.triangle_records[record * 2 + 1];
            if (triangle < 0 || static_cast<std::size_t>(triangle) >= triangle_count) {
                return false;
            }
            normal = add(
                normal,
                mul(
                    triangle_normals[static_cast<std::size_t>(triangle)],
                    (flip & 0x01) == 0 ? 1.0f : -1.0f
                )
            );
            tangent = add(
                tangent,
                mul(
                    triangle_tangents[static_cast<std::size_t>(triangle)],
                    (flip & 0x02) == 0 ? 1.0f : -1.0f
                )
            );
        }
        const float normal_length = length(normal);
        const float tangent_length = length(tangent);
        if (normal_length <= 1.0e-6f || tangent_length <= 1.0e-6f) continue;
        normal = mul(normal, 1.0f / normal_length);
        tangent = mul(tangent, 1.0f / tangent_length);
        const float alignment = dot(normal, tangent);
        if (alignment == 1.0f || alignment == -1.0f) continue;
        const Vec3 binormal = normalize(cross(normal, tangent));
        std::array<float, 4> adjustment {0.0f, 0.0f, 0.0f, 1.0f};
        if (view.normal_adjustment_rotations != nullptr) {
            const auto offset = vertex * 4;
            adjustment = {
                view.normal_adjustment_rotations[offset + 0],
                view.normal_adjustment_rotations[offset + 1],
                view.normal_adjustment_rotations[offset + 2],
                view.normal_adjustment_rotations[offset + 3],
            };
            normalize_quaternion(adjustment);
        }
        store_output(
            vertex,
            quaternion_multiply(
                quaternion_from_forward_up(binormal, normal),
                adjustment
            )
        );
    }
    return true;
}

bool derive_bone_frame_orientations(
    const float* matrix_values,
    const float* component_rotation_values,
    const float* vertex_to_transform_values,
    std::size_t vertex_count,
    float* output_values,
    const char* matrix_name
) {
    const std::array<float, 4> component_quaternion {
        component_rotation_values[0], component_rotation_values[1],
        component_rotation_values[2], component_rotation_values[3]
    };
    for (std::size_t vertex = 0; vertex < vertex_count; ++vertex) {
        const float* matrix = matrix_values + vertex * 9;
        Vec3 x {matrix[0], matrix[3], matrix[6]};
        Vec3 y {matrix[1], matrix[4], matrix[7]};
        Vec3 z {matrix[2], matrix[5], matrix[8]};
        const float x_length = length(x), y_length = length(y), z_length = length(z);
        if (x_length <= kMc2Epsilon || y_length <= kMc2Epsilon ||
            z_length <= kMc2Epsilon) {
            PyErr_Format(PyExc_ValueError, "%s contains zero scale", matrix_name);
            return false;
        }
        x = mul(x, 1.0f / x_length);
        y = mul(y, 1.0f / y_length);
        z = mul(z, 1.0f / z_length);
        const float determinant = dot(cross(x, y), z);
        if (std::abs(dot(x, y)) > 1.0e-4f ||
            std::abs(dot(x, z)) > 1.0e-4f ||
            std::abs(dot(y, z)) > 1.0e-4f ||
            std::abs(determinant - 1.0f) > 1.0e-4f) {
            PyErr_Format(
                PyExc_ValueError,
                "%s must be proper and shear-free",
                matrix_name
            );
            return false;
        }
        const auto transform_rotation = quaternion_multiply(
            component_quaternion,
            quaternion_from_forward_up(z, y)
        );
        const float* vertex_rotation = vertex_to_transform_values + vertex * 4;
        const std::array<float, 4> transform_to_vertex {
            -vertex_rotation[0],
            -vertex_rotation[1],
            -vertex_rotation[2],
            vertex_rotation[3],
        };
        auto proxy_rotation = quaternion_multiply(
            transform_rotation,
            transform_to_vertex
        );
        normalize_quaternion(proxy_rotation);
        std::copy(
            proxy_rotation.begin(),
            proxy_rotation.end(),
            output_values + vertex * 4
        );
    }
    return true;
}

bool derive_bone_line_output(
    const std::uint8_t* attributes,
    const float* positions,
    const float* base_positions,
    const float* base_rotations,
    const std::int32_t* child_ranges,
    const std::int32_t* child_data,
    std::size_t child_data_count,
    const std::int32_t* baseline_ranges,
    std::size_t baseline_count,
    const std::int32_t* baseline_data,
    std::size_t baseline_data_count,
    const float* vertex_local_positions,
    const float* vertex_local_rotations,
    const std::int32_t* triangles,
    std::size_t triangle_count,
    const float* uvs,
    const std::int32_t* triangle_ranges,
    const std::int32_t* triangle_data,
    std::size_t triangle_record_count,
    const float* normal_adjustment_rotations,
    const float* vertex_to_transform_rotations,
    std::size_t vertex_count,
    bool mesh_semantics,
    float rotational_interpolation,
    float root_rotation,
    float animation_pose_ratio,
    float blend_weight,
    float* output_rotations
) {
    if (attributes == nullptr || positions == nullptr || base_positions == nullptr ||
        base_rotations == nullptr || child_ranges == nullptr ||
        baseline_ranges == nullptr || vertex_local_positions == nullptr ||
        vertex_local_rotations == nullptr || uvs == nullptr ||
        triangle_ranges == nullptr || normal_adjustment_rotations == nullptr ||
        vertex_to_transform_rotations == nullptr || output_rotations == nullptr ||
        (child_data_count != 0 && child_data == nullptr) ||
        (baseline_data_count != 0 && baseline_data == nullptr) ||
        (triangle_count != 0 && triangles == nullptr) ||
        (triangle_record_count != 0 && triangle_data == nullptr)) {
        return false;
    }

    std::vector<float> work_rotations(
        base_rotations,
        base_rotations + vertex_count * 4
    );
    for (std::size_t baseline = 0; baseline < baseline_count; ++baseline) {
        const auto range_start = baseline_ranges[baseline * 2];
        const auto range_length = baseline_ranges[baseline * 2 + 1];
        if (range_start < 0 || range_length < 0 ||
            static_cast<std::size_t>(range_start + range_length) > baseline_data_count) {
            return false;
        }
        for (std::int32_t offset = 0; offset < range_length; ++offset) {
            const auto raw_index = baseline_data[range_start + offset];
            if (raw_index < 0 || static_cast<std::size_t>(raw_index) >= vertex_count) {
                return false;
            }
            const auto vertex = static_cast<std::size_t>(raw_index);
            const Vec3 position = load_vector3(positions, vertex);
            auto rotation = load_quaternion(work_rotations.data(), vertex);
            const auto attribute = attributes[vertex];
            const auto child_start = child_ranges[vertex * 2];
            const auto child_count = child_ranges[vertex * 2 + 1];
            if (child_start < 0 || child_count < 0 ||
                static_cast<std::size_t>(child_start + child_count) > child_data_count) {
                return false;
            }
            const Vec3 base_position = load_vector3(base_positions, vertex);
            const auto base_rotation = load_quaternion(base_rotations, vertex);
            const auto inverse_base_rotation = quaternion_inverse(base_rotation);

            if (child_count > 0 && (attribute & 0x03u) != 0u) {
                Vec3 original_sum {};
                Vec3 current_sum {};
                for (std::int32_t child_offset = 0;
                     child_offset < child_count;
                     ++child_offset) {
                    const auto raw_child = child_data[child_start + child_offset];
                    if (raw_child < 0 ||
                        static_cast<std::size_t>(raw_child) >= vertex_count) {
                        return false;
                    }
                    const auto child = static_cast<std::size_t>(raw_child);
                    const auto child_attribute = attributes[child];
                    const bool zero_distance = (child_attribute & 0x20u) != 0u;
                    const Vec3 child_base_local_position = rotate_vector(
                        inverse_base_rotation,
                        sub(load_vector3(base_positions, child), base_position)
                    );
                    const auto child_base_local_rotation = quaternion_multiply(
                        inverse_base_rotation,
                        load_quaternion(base_rotations, child)
                    );
                    const Vec3 static_local_position = load_vector3(
                        vertex_local_positions,
                        child
                    );
                    const Vec3 child_local_position = add(
                        mul(static_local_position, 1.0f - animation_pose_ratio),
                        mul(child_base_local_position, animation_pose_ratio)
                    );
                    const auto child_local_rotation = quaternion_slerp(
                        load_quaternion(vertex_local_rotations, child),
                        child_base_local_rotation,
                        animation_pose_ratio
                    );
                    const Vec3 original_vector = zero_distance
                        ? Vec3 {}
                        : rotate_vector(rotation, child_local_position);
                    original_sum = add(original_sum, original_vector);
                    if (mesh_semantics || (child_attribute & 0x02u) != 0u) {
                        const Vec3 current_vector = sub(
                            load_vector3(positions, child),
                            position
                        );
                        current_sum = add(current_sum, current_vector);
                        auto child_rotation = quaternion_multiply(
                            rotation,
                            child_local_rotation
                        );
                        if (!zero_distance &&
                            length(original_vector) > kMc2Epsilon &&
                            length(current_vector) > kMc2Epsilon) {
                            child_rotation = quaternion_multiply(
                                quaternion_from_to(original_vector, current_vector),
                                child_rotation
                            );
                        }
                        store_quaternion(
                            work_rotations.data(),
                            child,
                            child_rotation
                        );
                    } else {
                        current_sum = add(current_sum, original_vector);
                    }
                }
                const float ratio = mesh_semantics
                    ? 1.0f
                    : (attribute & 0x02u) != 0u
                    ? rotational_interpolation
                    : root_rotation;
                const auto adjustment =
                    length(original_sum) <= kMc2Epsilon ||
                    length(current_sum) <= kMc2Epsilon
                    ? std::array<float, 4> {0.0f, 0.0f, 0.0f, 1.0f}
                    : quaternion_from_to(original_sum, current_sum, ratio);
                rotation = quaternion_multiply(adjustment, rotation);
            }
            store_quaternion(
                work_rotations.data(),
                vertex,
                quaternion_slerp(base_rotation, rotation, blend_weight)
            );
        }
    }

    const Mc2MeshFrameOrientationView triangle_view {
        vertex_count,
        positions,
        triangles,
        triangle_count,
        uvs,
        vertex_count * 2,
        nullptr,
        0,
        triangle_ranges,
        vertex_count * 2,
        triangle_data,
        triangle_record_count * 2,
        normal_adjustment_rotations,
        work_rotations.data(),
    };
    if (!derive_mesh_frame_orientations(triangle_view)) return false;

    for (std::size_t vertex = 0; vertex < vertex_count; ++vertex) {
        store_quaternion(
            output_rotations,
            vertex,
            quaternion_multiply(
                load_quaternion(work_rotations.data(), vertex),
                load_quaternion(vertex_to_transform_rotations, vertex)
            )
        );
    }
    return true;
}

PyObject* mc2_mesh_frame_orientations_v1(PyObject*, PyObject* args) {
    using namespace py;
    if (PyTuple_GET_SIZE(args) != 6) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_mesh_frame_orientations_v1 expects 6 arguments"
        );
        return nullptr;
    }
    Buffer positions, triangles, triangle_uvs, ranges, records, output;
    if (!positions.get(
            PyTuple_GET_ITEM(args, 0), PyBUF_FORMAT | PyBUF_ND, "world_positions"
        ) ||
        !triangles.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "triangles"
        ) ||
        !triangle_uvs.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "triangle_uvs"
        ) ||
        !ranges.get(
            PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND,
            "vertex_to_triangle_ranges"
        ) ||
        !records.get(
            PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND,
            "vertex_to_triangle_data"
        ) ||
        !output.get(
            PyTuple_GET_ITEM(args, 5),
            PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_rotations"
        )) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    Py_ssize_t triangle_count = 0;
    Py_ssize_t range_count = 0;
    Py_ssize_t record_count = 0;
    if (!expect_vector3_array(positions, "world_positions", &vertex_count) ||
        vertex_count <= 0 ||
        !finite_floats(positions, "world_positions") ||
        !expect_int32_triple_array(triangles, "triangles", &triangle_count) ||
        !expect_triple_indices_in_range(triangles, "triangles", vertex_count) ||
        !expect_float32(triangle_uvs, "triangle_uvs") ||
        !expect_2d(triangle_uvs, "triangle_uvs", triangle_count, 6) ||
        !finite_floats(triangle_uvs, "triangle_uvs") ||
        !expect_int32_pair_array(
            ranges, "vertex_to_triangle_ranges", &range_count
        ) ||
        range_count != vertex_count ||
        !expect_int32_pair_array(
            records, "vertex_to_triangle_data", &record_count
        ) ||
        !validate_dense_ranges(
            ranges, record_count, "vertex_to_triangle_ranges"
        ) ||
        !expect_float32(output, "out_rotations") ||
        !expect_2d(output, "out_rotations", vertex_count, 4)) {
        return nullptr;
    }

    const auto* range_values = static_cast<const std::int32_t*>(ranges.view.buf);
    const auto* record_values = static_cast<const std::int32_t*>(records.view.buf);
    for (Py_ssize_t vertex = 0; vertex < vertex_count; ++vertex) {
        const auto start = range_values[vertex * 2];
        const auto count = range_values[vertex * 2 + 1];
        if (count <= 0 || count > 7) {
            PyErr_SetString(
                PyExc_ValueError,
                "mesh frame orientation requires 1..7 triangle records per vertex"
            );
            return nullptr;
        }
        for (std::int32_t offset = 0; offset < count; ++offset) {
            const auto* record = record_values + (start + offset) * 2;
            if (record[0] < 0 || record[0] > 3 ||
                record[1] < 0 || record[1] >= triangle_count) {
                PyErr_SetString(
                    PyExc_ValueError,
                    "mesh frame orientation triangle record is invalid"
                );
                return nullptr;
            }
        }
    }

    auto* output_values = static_cast<float*>(output.view.buf);
    std::fill_n(output_values, static_cast<std::size_t>(vertex_count) * 4, 0.0f);
    for (Py_ssize_t vertex = 0; vertex < vertex_count; ++vertex) {
        output_values[static_cast<std::size_t>(vertex) * 4 + 3] = 1.0f;
    }
    const Mc2MeshFrameOrientationView view {
        static_cast<std::size_t>(vertex_count),
        static_cast<const float*>(positions.view.buf),
        static_cast<const std::int32_t*>(triangles.view.buf),
        static_cast<std::size_t>(triangle_count),
        nullptr,
        0,
        static_cast<const float*>(triangle_uvs.view.buf),
        static_cast<std::size_t>(triangle_count) * 6,
        static_cast<const std::int32_t*>(ranges.view.buf),
        static_cast<std::size_t>(vertex_count) * 2,
        static_cast<const std::int32_t*>(records.view.buf),
        static_cast<std::size_t>(record_count) * 2,
        nullptr,
        output_values,
    };
    if (!derive_mesh_frame_orientations(view)) {
        PyErr_SetString(PyExc_RuntimeError, "mesh frame orientation producer failed");
        return nullptr;
    }
    Py_RETURN_NONE;
}

PyObject* mc2_bone_frame_orientations_v1(PyObject*, PyObject* args) {
    using namespace py;
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_bone_frame_orientations_v1 expects 4 arguments"
        );
        return nullptr;
    }
    Buffer matrices, component_rotation, vertex_to_transform, output;
    if (!matrices.get(
            PyTuple_GET_ITEM(args, 0), PyBUF_FORMAT | PyBUF_ND, "pose_matrices"
        ) ||
        !component_rotation.get(
            PyTuple_GET_ITEM(args, 1),
            PyBUF_FORMAT | PyBUF_ND,
            "component_rotation_xyzw"
        ) ||
        !vertex_to_transform.get(
            PyTuple_GET_ITEM(args, 2),
            PyBUF_FORMAT | PyBUF_ND,
            "vertex_to_transform_rotations"
        ) ||
        !output.get(
            PyTuple_GET_ITEM(args, 3),
            PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_rotations"
        )) {
        return nullptr;
    }
    if (!expect_float32(matrices, "pose_matrices") ||
        matrices.view.ndim != 3 || matrices.view.shape == nullptr ||
        matrices.view.shape[0] <= 0 || matrices.view.shape[1] != 3 ||
        matrices.view.shape[2] != 3) {
        if (!PyErr_Occurred()) {
            PyErr_SetString(PyExc_ValueError, "pose_matrices must be float32[N,3,3]");
        }
        return nullptr;
    }
    const auto count = matrices.view.shape[0];
    if (!expect_float32(component_rotation, "component_rotation_xyzw") ||
        !expect_1d_array(component_rotation, "component_rotation_xyzw", 4) ||
        !expect_float32(
            vertex_to_transform, "vertex_to_transform_rotations"
        ) ||
        !expect_2d(
            vertex_to_transform,
            "vertex_to_transform_rotations",
            count,
            4
        ) ||
        !expect_float32(output, "out_rotations") ||
        !expect_2d(output, "out_rotations", count, 4) ||
        !finite_floats(matrices, "pose_matrices") ||
        !finite_floats(component_rotation, "component_rotation_xyzw") ||
        !finite_floats(
            vertex_to_transform, "vertex_to_transform_rotations"
        ) ||
        !validate_quaternions(
            vertex_to_transform, "vertex_to_transform_rotations"
        )) {
        return nullptr;
    }
    const auto* component_values = static_cast<const float*>(
        component_rotation.view.buf
    );
    double component_length_squared = 0.0;
    for (std::size_t component = 0; component < 4; ++component) {
        component_length_squared +=
            static_cast<double>(component_values[component]) *
            component_values[component];
    }
    if (std::abs(component_length_squared - 1.0) > 2.0e-5) {
        PyErr_SetString(
            PyExc_ValueError,
            "component_rotation_xyzw must be a unit quaternion"
        );
        return nullptr;
    }
    std::vector<float> staged_rotations(static_cast<std::size_t>(count) * 4);
    if (!derive_bone_frame_orientations(
            static_cast<const float*>(matrices.view.buf),
            component_values,
            static_cast<const float*>(vertex_to_transform.view.buf),
            static_cast<std::size_t>(count),
            staged_rotations.data(),
            "bone frame pose matrix"
        )) {
        return nullptr;
    }
    std::copy(
        staged_rotations.begin(),
        staged_rotations.end(),
        static_cast<float*>(output.view.buf)
    );
    Py_RETURN_NONE;
}

PyObject* mc2_bone_output_impl(PyObject* args, bool mesh_semantics) {
    using namespace py;
    constexpr Py_ssize_t kArgumentCount = 18;
    if (PyTuple_GET_SIZE(args) != kArgumentCount) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_bone_line_output_v1 expects 18 arguments"
        );
        return nullptr;
    }
    Buffer attributes, positions, base_positions, base_rotations;
    Buffer child_ranges, child_data, baseline_ranges, baseline_data;
    Buffer local_positions, local_rotations, triangles, uvs;
    Buffer triangle_ranges, triangle_data, normal_adjustments;
    Buffer vertex_to_transform, parameters, output;
    Buffer* buffers[] = {
        &attributes, &positions, &base_positions, &base_rotations,
        &child_ranges, &child_data, &baseline_ranges, &baseline_data,
        &local_positions, &local_rotations, &triangles, &uvs,
        &triangle_ranges, &triangle_data, &normal_adjustments,
        &vertex_to_transform, &parameters, &output,
    };
    const char* names[] = {
        "vertex_attributes", "world_positions", "base_positions",
        "base_rotations", "child_ranges", "child_data",
        "baseline_ranges", "baseline_data", "vertex_local_positions",
        "vertex_local_rotations", "triangles", "uvs",
        "vertex_to_triangle_ranges", "vertex_to_triangle_data",
        "normal_adjustment_rotations", "vertex_to_transform_rotations",
        "rotation_parameters", "out_rotations",
    };
    for (Py_ssize_t index = 0; index < kArgumentCount; ++index) {
        int flags = PyBUF_FORMAT | PyBUF_ND;
        if (index == kArgumentCount - 1) flags |= PyBUF_WRITABLE;
        if (!buffers[index]->get(PyTuple_GET_ITEM(args, index), flags, names[index])) {
            return nullptr;
        }
    }

    Py_ssize_t vertex_count = 0;
    Py_ssize_t count = 0;
    Py_ssize_t child_range_count = 0;
    Py_ssize_t baseline_count = 0;
    Py_ssize_t triangle_count = 0;
    Py_ssize_t triangle_range_count = 0;
    Py_ssize_t triangle_record_count = 0;
    if (!expect_vector3_array(positions, "world_positions", &vertex_count) ||
        vertex_count <= 0 ||
        !expect_uint8_scalar_array(attributes, "vertex_attributes") ||
        attributes.view.shape[0] != vertex_count ||
        !expect_same_vertex_count(base_positions, "base_positions", vertex_count) ||
        !expect_same_quat_vertex_count(base_rotations, "base_rotations", vertex_count) ||
        !expect_int32_pair_array(child_ranges, "child_ranges", &child_range_count) ||
        child_range_count != vertex_count ||
        !expect_int32_scalar_array(child_data, "child_data") ||
        !validate_dense_ranges(child_ranges, child_data.view.shape[0], "child_ranges") ||
        !expect_int32_pair_array(baseline_ranges, "baseline_ranges", &baseline_count) ||
        baseline_count <= 0 ||
        !expect_int32_scalar_array(baseline_data, "baseline_data") ||
        !validate_dense_ranges(
            baseline_ranges, baseline_data.view.shape[0], "baseline_ranges"
        ) ||
        !expect_same_vertex_count(
            local_positions, "vertex_local_positions", vertex_count
        ) ||
        !expect_same_quat_vertex_count(
            local_rotations, "vertex_local_rotations", vertex_count
        ) ||
        !expect_int32_triple_array(triangles, "triangles", &triangle_count) ||
        !expect_float32(uvs, "uvs") ||
        !expect_2d(uvs, "uvs", vertex_count, 2) ||
        !expect_int32_pair_array(
            triangle_ranges, "vertex_to_triangle_ranges", &triangle_range_count
        ) ||
        triangle_range_count != vertex_count ||
        !expect_int32_pair_array(
            triangle_data, "vertex_to_triangle_data", &triangle_record_count
        ) ||
        !validate_dense_ranges(
            triangle_ranges,
            triangle_record_count,
            "vertex_to_triangle_ranges"
        ) ||
        !expect_same_quat_vertex_count(
            normal_adjustments, "normal_adjustment_rotations", vertex_count
        ) ||
        !expect_same_quat_vertex_count(
            vertex_to_transform, "vertex_to_transform_rotations", vertex_count
        ) ||
        !expect_float32(parameters, "rotation_parameters") ||
        !expect_1d_array(parameters, "rotation_parameters", 4) ||
        !expect_vector4_array(output, "out_rotations", &count) ||
        count != vertex_count ||
        !finite_floats(positions, "world_positions") ||
        !finite_floats(base_positions, "base_positions") ||
        !finite_floats(base_rotations, "base_rotations") ||
        !finite_floats(local_positions, "vertex_local_positions") ||
        !finite_floats(local_rotations, "vertex_local_rotations") ||
        !finite_floats(uvs, "uvs") ||
        !finite_floats(normal_adjustments, "normal_adjustment_rotations") ||
        !finite_floats(vertex_to_transform, "vertex_to_transform_rotations") ||
        !finite_floats(parameters, "rotation_parameters") ||
        !validate_quaternions(base_rotations, "base_rotations") ||
        !validate_quaternions(local_rotations, "vertex_local_rotations") ||
        !validate_quaternions(
            normal_adjustments, "normal_adjustment_rotations"
        ) ||
        !validate_quaternions(
            vertex_to_transform, "vertex_to_transform_rotations"
        ) ||
        !expect_indices_in_range(child_data, "child_data", vertex_count) ||
        !expect_indices_in_range(baseline_data, "baseline_data", vertex_count) ||
        !expect_triple_indices_in_range(triangles, "triangles", vertex_count)) {
        return nullptr;
    }

    const auto* triangle_records = static_cast<const std::int32_t*>(
        triangle_data.view.buf
    );
    for (Py_ssize_t record = 0; record < triangle_record_count; ++record) {
        const auto flip = triangle_records[record * 2];
        const auto triangle = triangle_records[record * 2 + 1];
        if (flip < 0 || flip > 0xFFF || triangle < 0 || triangle >= triangle_count) {
            PyErr_SetString(
                PyExc_ValueError,
                "vertex_to_triangle_data contains an invalid record"
            );
            return nullptr;
        }
    }
    const auto* parameter_values = static_cast<const float*>(parameters.view.buf);
    for (std::size_t index = 0; index < 4; ++index) {
        if (parameter_values[index] < 0.0f || parameter_values[index] > 1.0f) {
            PyErr_SetString(
                PyExc_ValueError,
                "rotation_parameters must be in 0..1"
            );
            return nullptr;
        }
    }

    if (!derive_bone_line_output(
            static_cast<const std::uint8_t*>(attributes.view.buf),
            static_cast<const float*>(positions.view.buf),
            static_cast<const float*>(base_positions.view.buf),
            static_cast<const float*>(base_rotations.view.buf),
            static_cast<const std::int32_t*>(child_ranges.view.buf),
            static_cast<const std::int32_t*>(child_data.view.buf),
            static_cast<std::size_t>(child_data.view.shape[0]),
            static_cast<const std::int32_t*>(baseline_ranges.view.buf),
            static_cast<std::size_t>(baseline_count),
            static_cast<const std::int32_t*>(baseline_data.view.buf),
            static_cast<std::size_t>(baseline_data.view.shape[0]),
            static_cast<const float*>(local_positions.view.buf),
            static_cast<const float*>(local_rotations.view.buf),
            static_cast<const std::int32_t*>(triangles.view.buf),
            static_cast<std::size_t>(triangle_count),
            static_cast<const float*>(uvs.view.buf),
            static_cast<const std::int32_t*>(triangle_ranges.view.buf),
            static_cast<const std::int32_t*>(triangle_data.view.buf),
            static_cast<std::size_t>(triangle_record_count),
            static_cast<const float*>(normal_adjustments.view.buf),
            static_cast<const float*>(vertex_to_transform.view.buf),
            static_cast<std::size_t>(vertex_count),
            mesh_semantics,
            parameter_values[0],
            parameter_values[1],
            parameter_values[2],
            parameter_values[3],
            static_cast<float*>(output.view.buf))) {
        PyErr_SetString(PyExc_RuntimeError, "Bone Line output producer failed");
        return nullptr;
    }
    Py_RETURN_NONE;
}

PyObject* mc2_bone_line_output_v1(PyObject*, PyObject* args) {
    return mc2_bone_output_impl(args, false);
}

PyObject* mc2_bone_mesh_output_v1(PyObject*, PyObject* args) {
    return mc2_bone_output_impl(args, true);
}

}  // namespace hotools
