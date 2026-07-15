#include "mc2_context_v0.hpp"

#include "python_buffer_utils.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <vector>

namespace hotools {
namespace {

using namespace py;

constexpr const char* kCapsuleName = "hotools_native.MC2ContextV0";
constexpr long kSchemaVersion = 0;
constexpr Py_ssize_t kFloatCount = 47;
constexpr Py_ssize_t kIntCount = 11;
constexpr Py_ssize_t kCurveRows = 9;
constexpr Py_ssize_t kCurveColumns = 16;
constexpr float kMc2Epsilon = 0.00000001f;
constexpr float kDistanceHorizontalStiffness = 0.5f;
constexpr float kDistanceFixedInverseMass = 1.0f / 50.0f;
constexpr Py_ssize_t kDistanceStiffnessCurve = 2;
constexpr Py_ssize_t kDampingCurve = 0;
constexpr Py_ssize_t kGravity = 0;
constexpr Py_ssize_t kGravityDirection = 1;
constexpr Py_ssize_t kDistanceVelocityAttenuation = 26;
constexpr Py_ssize_t kBendingStiffness = 27;
constexpr Py_ssize_t kGravityFalloff = 4;
constexpr Py_ssize_t kStabilizationTime = 5;
constexpr Py_ssize_t kBlendWeight = 6;
constexpr Py_ssize_t kRotationalInterpolation = 7;
constexpr Py_ssize_t kRootRotation = 8;
constexpr Py_ssize_t kLocalInertia = 16;
constexpr Py_ssize_t kLocalMovementSpeedLimit = 17;
constexpr Py_ssize_t kLocalRotationSpeedLimit = 18;
constexpr Py_ssize_t kDepthInertia = 19;

std::atomic<std::int64_t> g_created {0};
std::atomic<std::int64_t> g_released {0};
std::atomic<std::int64_t> g_live {0};

struct Mc2ContextV0 {
    std::int64_t vertex_count = 0;
    std::int64_t parameter_revision = 0;
    std::int64_t proxy_static_revision = 0;
    std::int64_t baseline_static_revision = 0;
    std::int64_t bone_static_revision = 0;
    std::int64_t distance_static_revision = 0;
    std::int64_t bending_static_revision = 0;
    std::int64_t center_static_revision = 0;
    std::int64_t dynamic_revision = 0;
    std::int64_t reset_count = 0;
    std::int64_t step_count = 0;
    std::int64_t distance_solve_count = 0;
    std::int64_t particle_prediction_count = 0;
    std::int64_t particle_inertia_count = 0;
    std::int64_t bending_solve_count = 0;
    std::int64_t center_dynamic_revision = 0;
    std::int64_t step_interpolation_revision = 0;
    std::int64_t center_step_count = 0;
    std::int64_t center_frame_shift_count = 0;
    std::int64_t center_negative_scale_teleport_count = 0;
    std::int64_t team_options_revision = 0;
    std::int64_t baseline_pose_rebuild_count = 0;
    std::int64_t bone_line_output_count = 0;
    std::int64_t frame = 0;
    std::int64_t generation = 0;
    float velocity_weight = 1.0f;
    float gravity_ratio = 1.0f;
    float scale_ratio = 1.0f;
    float negative_scale_sign = 1.0f;
    float frame_interpolation = 1.0f;
    float animation_pose_ratio = 0.0f;
    bool parameters_ready = false;
    bool proxy_static_ready = false;
    bool baseline_static_ready = false;
    bool bone_static_ready = false;
    bool distance_static_ready = false;
    bool bending_static_ready = false;
    bool center_static_ready = false;
    bool center_dynamic_ready = false;
    bool center_frame_ready = false;
    bool center_result_ready = false;
    bool dynamic_ready = false;
    bool initialized = false;
    bool released = false;
    std::vector<float> float_values;
    std::vector<std::int32_t> int_values;
    std::vector<float> curve_values;
    std::vector<float> dynamic_positions;
    std::vector<float> dynamic_rotations;
    std::vector<float> old_dynamic_positions;
    std::vector<float> old_dynamic_rotations;
    std::vector<float> state_positions;
    std::vector<float> state_rotations;
    std::vector<float> state_velocities;
    std::vector<float> velocity_reference_positions;
    std::vector<float> step_basic_positions;
    std::vector<float> step_basic_rotations;
    std::vector<float> proxy_local_positions;
    std::vector<float> proxy_local_normals;
    std::vector<float> proxy_local_tangents;
    std::vector<float> proxy_uvs;
    std::vector<std::uint8_t> proxy_attributes;
    std::vector<std::int32_t> proxy_edges;
    std::vector<std::int32_t> proxy_triangles;
    std::vector<std::int32_t> baseline_parents;
    std::vector<std::int32_t> baseline_child_ranges;
    std::vector<std::int32_t> baseline_child_data;
    std::vector<std::uint8_t> baseline_flags;
    std::vector<std::int32_t> baseline_ranges;
    std::vector<std::int32_t> baseline_data;
    std::vector<std::int32_t> baseline_roots;
    std::vector<float> baseline_depths;
    std::vector<float> baseline_local_positions;
    std::vector<float> baseline_local_rotations;
    std::vector<std::int32_t> bone_vertex_to_vertex_ranges;
    std::vector<std::int32_t> bone_vertex_to_vertex_data;
    std::vector<std::int32_t> bone_vertex_to_triangle_ranges;
    std::vector<std::int32_t> bone_vertex_to_triangle_data;
    std::vector<float> bone_vertex_bind_pose_positions;
    std::vector<float> bone_vertex_bind_pose_rotations;
    std::vector<float> bone_normal_adjustment_rotations;
    std::vector<float> bone_vertex_to_transform_rotations;
    std::vector<float> bone_output_positions;
    std::vector<float> bone_output_rotations;
    std::vector<std::int32_t> distance_ranges;
    std::vector<std::int32_t> distance_targets;
    std::vector<float> distance_rest_signed;
    std::vector<std::int32_t> bending_quads;
    std::vector<float> bending_rest_angle_or_volume;
    std::vector<std::int8_t> bending_sign_or_volume;
    std::vector<std::int32_t> center_fixed_indices;
    std::vector<float> center_local_position;
    std::vector<float> center_initial_local_gravity_direction;
    std::array<float, 3> center_old_frame_world_position {};
    std::array<float, 3> center_frame_world_position {};
    std::array<float, 4> center_old_frame_world_rotation {0.0f, 0.0f, 0.0f, 1.0f};
    std::array<float, 4> center_frame_world_rotation {0.0f, 0.0f, 0.0f, 1.0f};
    std::array<float, 3> center_old_frame_world_scale {1.0f, 1.0f, 1.0f};
    std::array<float, 3> center_frame_world_scale {1.0f, 1.0f, 1.0f};
    std::array<float, 3> center_old_world_position {};
    std::array<float, 4> center_old_world_rotation {0.0f, 0.0f, 0.0f, 1.0f};
    std::array<float, 3> center_initial_scale {1.0f, 1.0f, 1.0f};
    std::array<float, 3> center_negative_scale_direction {1.0f, 1.0f, 1.0f};
    float center_distance_weight = 1.0f;
    std::array<float, 3> center_now_world_position {};
    std::array<float, 4> center_now_world_rotation {0.0f, 0.0f, 0.0f, 1.0f};
    std::array<float, 3> center_step_vector {};
    std::array<float, 4> center_step_rotation {0.0f, 0.0f, 0.0f, 1.0f};
    std::array<float, 3> center_inertia_vector {};
    std::array<float, 4> center_inertia_rotation {0.0f, 0.0f, 0.0f, 1.0f};
    std::array<float, 3> center_rotation_axis {};
    float center_step_move_inertia_ratio = 1.0f;
    float center_step_rotation_inertia_ratio = 1.0f;
    float center_angular_velocity = 0.0f;
    float center_gravity_dot = 1.0f;
    float center_blend_weight = 1.0f;
};

Mc2ContextV0* context_from(PyObject* object) {
    return static_cast<Mc2ContextV0*>(PyCapsule_GetPointer(object, kCapsuleName));
}

void release_resources(Mc2ContextV0& context) {
    if (context.released) {
        return;
    }
    context.float_values.clear();
    context.int_values.clear();
    context.curve_values.clear();
    context.dynamic_positions.clear();
    context.dynamic_rotations.clear();
    context.old_dynamic_positions.clear();
    context.old_dynamic_rotations.clear();
    context.state_positions.clear();
    context.state_rotations.clear();
    context.state_velocities.clear();
    context.velocity_reference_positions.clear();
    context.step_basic_positions.clear();
    context.step_basic_rotations.clear();
    context.proxy_local_positions.clear();
    context.proxy_local_normals.clear();
    context.proxy_local_tangents.clear();
    context.proxy_uvs.clear();
    context.proxy_attributes.clear();
    context.proxy_edges.clear();
    context.proxy_triangles.clear();
    context.baseline_parents.clear();
    context.baseline_child_ranges.clear();
    context.baseline_child_data.clear();
    context.baseline_flags.clear();
    context.baseline_ranges.clear();
    context.baseline_data.clear();
    context.baseline_roots.clear();
    context.baseline_depths.clear();
    context.baseline_local_positions.clear();
    context.baseline_local_rotations.clear();
    context.bone_vertex_to_vertex_ranges.clear();
    context.bone_vertex_to_vertex_data.clear();
    context.bone_vertex_to_triangle_ranges.clear();
    context.bone_vertex_to_triangle_data.clear();
    context.bone_vertex_bind_pose_positions.clear();
    context.bone_vertex_bind_pose_rotations.clear();
    context.bone_normal_adjustment_rotations.clear();
    context.bone_vertex_to_transform_rotations.clear();
    context.bone_output_positions.clear();
    context.bone_output_rotations.clear();
    context.distance_ranges.clear();
    context.distance_targets.clear();
    context.distance_rest_signed.clear();
    context.bending_quads.clear();
    context.bending_rest_angle_or_volume.clear();
    context.bending_sign_or_volume.clear();
    context.center_fixed_indices.clear();
    context.center_local_position.clear();
    context.center_initial_local_gravity_direction.clear();
    context.parameters_ready = false;
    context.proxy_static_ready = false;
    context.baseline_static_ready = false;
    context.bone_static_ready = false;
    context.distance_static_ready = false;
    context.bending_static_ready = false;
    context.center_static_ready = false;
    context.center_dynamic_ready = false;
    context.center_frame_ready = false;
    context.center_result_ready = false;
    context.dynamic_ready = false;
    context.initialized = false;
    context.released = true;
    ++g_released;
    --g_live;
}

void destroy_context(PyObject* capsule) {
    auto* context = context_from(capsule);
    if (context == nullptr) {
        PyErr_Clear();
        return;
    }
    release_resources(*context);
    delete context;
}

bool ensure_live(Mc2ContextV0* context) {
    if (context == nullptr) {
        return false;
    }
    if (context->released) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 context has been released");
        return false;
    }
    return true;
}

bool dict_i64(PyObject* dict, const char* key, std::int64_t value) {
    PyObject* item = PyLong_FromLongLong(value);
    if (item == nullptr) return false;
    const int result = PyDict_SetItemString(dict, key, item);
    Py_DECREF(item);
    return result == 0;
}

bool dict_bool(PyObject* dict, const char* key, bool value) {
    PyObject* item = PyBool_FromLong(value ? 1 : 0);
    if (item == nullptr) return false;
    const int result = PyDict_SetItemString(dict, key, item);
    Py_DECREF(item);
    return result == 0;
}

bool dict_float(PyObject* dict, const char* key, float value) {
    PyObject* item = PyFloat_FromDouble(static_cast<double>(value));
    if (item == nullptr) return false;
    const int result = PyDict_SetItemString(dict, key, item);
    Py_DECREF(item);
    return result == 0;
}

bool dict_string(PyObject* dict, const char* key, const char* value) {
    PyObject* item = PyUnicode_FromString(value);
    if (item == nullptr) return false;
    const int result = PyDict_SetItemString(dict, key, item);
    Py_DECREF(item);
    return result == 0;
}

bool finite_floats(const Buffer& buffer, const char* name) {
    const auto count = buffer.view.len / static_cast<Py_ssize_t>(sizeof(float));
    const auto* values = static_cast<const float*>(buffer.view.buf);
    for (Py_ssize_t index = 0; index < count; ++index) {
        if (!std::isfinite(values[index])) {
            PyErr_Format(PyExc_ValueError, "%s cannot contain NaN/Inf", name);
            return false;
        }
    }
    return true;
}

bool expect_2d(const Buffer& buffer,
               const char* name,
               Py_ssize_t rows,
               Py_ssize_t columns) {
    if (buffer.view.ndim != 2 || buffer.view.shape == nullptr ||
        buffer.view.shape[0] != rows || buffer.view.shape[1] != columns) {
        PyErr_Format(PyExc_ValueError, "%s shape mismatch", name);
        return false;
    }
    return true;
}

template <typename T>
std::vector<T> copy_values(const Buffer& buffer) {
    const auto count = static_cast<std::size_t>(
        buffer.view.len / static_cast<Py_ssize_t>(sizeof(T))
    );
    const auto* values = static_cast<const T*>(buffer.view.buf);
    return std::vector<T>(values, values + count);
}

bool validate_quaternions(const Buffer& rotations, const char* name) {
    const auto* values = static_cast<const float*>(rotations.view.buf);
    for (Py_ssize_t row = 0; row < rotations.view.shape[0]; ++row) {
        const float* value = values + row * 4;
        const double length_squared =
            static_cast<double>(value[0]) * value[0] +
            static_cast<double>(value[1]) * value[1] +
            static_cast<double>(value[2]) * value[2] +
            static_cast<double>(value[3]) * value[3];
        if (!std::isfinite(length_squared) || std::abs(length_squared - 1.0) > 2.0e-5) {
            PyErr_Format(PyExc_ValueError, "%s must contain unit quaternions", name);
            return false;
        }
    }
    return true;
}

bool validate_parameter_ints(const Buffer& ints) {
    const auto* values = static_cast<const std::int32_t*>(ints.view.buf);
    if (values[0] < 0 || values[0] > 5) {
        PyErr_SetString(PyExc_ValueError, "normal_axis must be in 0..5");
        return false;
    }
    for (const Py_ssize_t index : {1, 4, 5, 6, 7}) {
        if (values[index] != 0 && values[index] != 1) {
            PyErr_SetString(PyExc_ValueError, "MC2 boolean parameter must be 0 or 1");
            return false;
        }
    }
    if (values[2] < 0 || values[2] > 2) {
        PyErr_SetString(PyExc_ValueError, "teleport_mode must be in 0..2");
        return false;
    }
    if (values[3] != 0 && values[3] != 2) {
        PyErr_SetString(PyExc_ValueError, "bending_method must be 0 or 2");
        return false;
    }
    if (values[8] < 0 || values[8] > 2) {
        PyErr_SetString(PyExc_ValueError, "collision_mode must be in 0..2");
        return false;
    }
    for (const Py_ssize_t index : {9, 10}) {
        if (values[index] != 0 && values[index] != 2) {
            PyErr_SetString(PyExc_ValueError, "self collision mode must be 0 or 2");
            return false;
        }
    }
    return true;
}

bool validate_indices(const Buffer& buffer,
                      std::int64_t vertex_count,
                      const char* name,
                      bool allow_minus_one = false) {
    const auto count = buffer.view.len / static_cast<Py_ssize_t>(sizeof(std::int32_t));
    const auto* values = static_cast<const std::int32_t*>(buffer.view.buf);
    for (Py_ssize_t index = 0; index < count; ++index) {
        const auto value = values[index];
        if (value >= vertex_count || value < (allow_minus_one ? -1 : 0)) {
            PyErr_Format(PyExc_ValueError, "%s contains an out-of-range vertex index", name);
            return false;
        }
    }
    return true;
}

bool validate_dense_ranges(const Buffer& ranges,
                           Py_ssize_t data_count,
                           const char* name) {
    const auto* values = static_cast<const std::int32_t*>(ranges.view.buf);
    Py_ssize_t cursor = 0;
    for (Py_ssize_t row = 0; row < ranges.view.shape[0]; ++row) {
        const auto start = values[row * 2];
        const auto length = values[row * 2 + 1];
        if (start != cursor || length < 0) {
            PyErr_Format(PyExc_ValueError, "%s must form dense non-negative ranges", name);
            return false;
        }
        cursor += length;
    }
    if (cursor != data_count) {
        PyErr_Format(PyExc_ValueError, "%s does not cover its data array", name);
        return false;
    }
    return true;
}

bool expect_int8_scalar_array(const Buffer& buffer, const char* name) {
    if (buffer.view.itemsize != 1 ||
        (buffer.view.format != nullptr && buffer.view.format[0] != 'b')) {
        PyErr_Format(PyExc_TypeError, "%s must use int8 elements", name);
        return false;
    }
    if (buffer.view.ndim != 1 || buffer.view.shape == nullptr) {
        PyErr_Format(PyExc_ValueError, "%s must be a 1D array", name);
        return false;
    }
    return true;
}

float sample_curve16(const std::vector<float>& curves, Py_ssize_t row, float depth) {
    if (curves.size() != static_cast<std::size_t>(kCurveRows * kCurveColumns)) return 0.0f;
    depth = std::max(0.0f, std::min(1.0f, depth));
    const float scaled = depth * static_cast<float>(kCurveColumns - 1);
    const auto lower = static_cast<Py_ssize_t>(std::floor(scaled));
    const auto upper = std::min(lower + 1, kCurveColumns - 1);
    const float ratio = scaled - static_cast<float>(lower);
    const auto offset = row * kCurveColumns;
    return curves[offset + lower] * (1.0f - ratio) + curves[offset + upper] * ratio;
}

bool is_move(std::uint8_t attribute) {
    return (attribute & 0x02u) != 0u;
}

void slerp_xyzw(const float* first, const float* second, float ratio, float* output) {
    float target[4] = {second[0], second[1], second[2], second[3]};
    float cosine = first[0] * target[0] + first[1] * target[1] +
        first[2] * target[2] + first[3] * target[3];
    if (cosine < 0.0f) {
        cosine = -cosine;
        for (float& value : target) value = -value;
    }
    float first_weight = 1.0f - ratio;
    float second_weight = ratio;
    if (cosine < 0.9995f) {
        const float angle = std::acos(std::max(-1.0f, std::min(1.0f, cosine)));
        const float sine = std::sin(angle);
        first_weight = std::sin((1.0f - ratio) * angle) / sine;
        second_weight = std::sin(ratio * angle) / sine;
    }
    float length_squared = 0.0f;
    for (int component = 0; component < 4; ++component) {
        output[component] = first[component] * first_weight + target[component] * second_weight;
        length_squared += output[component] * output[component];
    }
    const float inverse_length = length_squared > kMc2Epsilon
        ? 1.0f / std::sqrt(length_squared)
        : 1.0f;
    for (int component = 0; component < 4; ++component) output[component] *= inverse_length;
}

void rotate_vector_xyzw(const float* rotation, const float* value, float* output) {
    const float cross_x = rotation[1] * value[2] - rotation[2] * value[1];
    const float cross_y = rotation[2] * value[0] - rotation[0] * value[2];
    const float cross_z = rotation[0] * value[1] - rotation[1] * value[0];
    const float twice_cross_x = 2.0f * cross_x;
    const float twice_cross_y = 2.0f * cross_y;
    const float twice_cross_z = 2.0f * cross_z;
    output[0] = value[0] + rotation[3] * twice_cross_x +
        (rotation[1] * twice_cross_z - rotation[2] * twice_cross_y);
    output[1] = value[1] + rotation[3] * twice_cross_y +
        (rotation[2] * twice_cross_x - rotation[0] * twice_cross_z);
    output[2] = value[2] + rotation[3] * twice_cross_z +
        (rotation[0] * twice_cross_y - rotation[1] * twice_cross_x);
}

bool rebuild_baseline_step_pose(Mc2ContextV0& context);

bool predict_particles(
    Mc2ContextV0& context,
    float dt,
    float simulation_power_z,
    bool apply_center_inertia
) {
    const auto count = static_cast<std::size_t>(context.vertex_count);
    if (context.state_positions.size() != count * 3 ||
        context.state_rotations.size() != count * 4 ||
        context.state_velocities.size() != count * 3 ||
        context.dynamic_positions.size() != count * 3 ||
        context.old_dynamic_positions.size() != count * 3 ||
        context.dynamic_rotations.size() != count * 4 ||
        context.old_dynamic_rotations.size() != count * 4 ||
        context.proxy_attributes.size() != count ||
        context.baseline_depths.size() != count ||
        context.float_values.size() != static_cast<std::size_t>(kFloatCount)) {
        return false;
    }
    context.velocity_reference_positions = context.state_positions;
    context.step_basic_positions.resize(count * 3);
    context.step_basic_rotations.resize(count * 4);
    const float gravity_scale =
        context.float_values[kGravity] * context.gravity_ratio * context.scale_ratio;
    const float gravity_x = context.float_values[kGravityDirection + 0] * gravity_scale;
    const float gravity_y = context.float_values[kGravityDirection + 1] * gravity_scale;
    const float gravity_z = context.float_values[kGravityDirection + 2] * gravity_scale;
    for (std::size_t vertex = 0; vertex < count; ++vertex) {
        const auto offset = vertex * 3;
        const auto rotation_offset = vertex * 4;
        for (std::size_t component = 0; component < 3; ++component) {
            context.step_basic_positions[offset + component] =
                context.old_dynamic_positions[offset + component] *
                    (1.0f - context.frame_interpolation) +
                context.dynamic_positions[offset + component] * context.frame_interpolation;
        }
        slerp_xyzw(
            context.old_dynamic_rotations.data() + rotation_offset,
            context.dynamic_rotations.data() + rotation_offset,
            context.frame_interpolation,
            context.step_basic_rotations.data() + rotation_offset
        );
        if (!is_move(context.proxy_attributes[vertex])) {
            for (std::size_t component = 0; component < 3; ++component) {
                const float base = context.step_basic_positions[offset + component];
                context.state_positions[offset + component] = base;
                context.velocity_reference_positions[offset + component] = base;
            }
            std::copy_n(
                context.step_basic_rotations.data() + rotation_offset,
                4,
                context.state_rotations.data() + rotation_offset
            );
            context.state_velocities[offset + 0] = 0.0f;
            context.state_velocities[offset + 1] = 0.0f;
            context.state_velocities[offset + 2] = 0.0f;
            continue;
        }
        if (apply_center_inertia) {
            const float depth = context.baseline_depths[vertex];
            const float inertia_depth = context.float_values[kDepthInertia] *
                (1.0f - depth * depth);
            float inertia_rotation[4] {};
            slerp_xyzw(
                context.center_inertia_rotation.data(),
                context.center_step_rotation.data(),
                inertia_depth,
                inertia_rotation
            );
            const float old_position[3] = {
                context.state_positions[offset + 0],
                context.state_positions[offset + 1],
                context.state_positions[offset + 2],
            };
            const float local_position[3] = {
                old_position[0] - context.center_old_world_position[0],
                old_position[1] - context.center_old_world_position[1],
                old_position[2] - context.center_old_world_position[2],
            };
            float rotated_position[3] {};
            rotate_vector_xyzw(inertia_rotation, local_position, rotated_position);
            for (std::size_t component = 0; component < 3; ++component) {
                const float inertia_vector =
                    context.center_inertia_vector[component] * (1.0f - inertia_depth) +
                    context.center_step_vector[component] * inertia_depth;
                const float world_position = context.center_old_world_position[component] +
                    rotated_position[component] + inertia_vector;
                const float inertia_offset = world_position - old_position[component];
                context.state_positions[offset + component] = world_position;
                context.velocity_reference_positions[offset + component] += inertia_offset;
            }
            float rotated_velocity[3] {};
            rotate_vector_xyzw(
                inertia_rotation,
                context.state_velocities.data() + offset,
                rotated_velocity
            );
            std::copy_n(rotated_velocity, 3, context.state_velocities.data() + offset);
            ++context.particle_inertia_count;
        }
        const float damping = sample_curve16(
            context.curve_values,
            kDampingCurve,
            context.baseline_depths[vertex]
        );
        const float damping_factor = std::max(
            0.0f,
            std::min(1.0f, 1.0f - damping * simulation_power_z)
        );
        context.state_velocities[offset + 0] *= context.velocity_weight * damping_factor;
        context.state_velocities[offset + 1] *= context.velocity_weight * damping_factor;
        context.state_velocities[offset + 2] *= context.velocity_weight * damping_factor;
        context.state_velocities[offset + 0] += gravity_x * dt;
        context.state_velocities[offset + 1] += gravity_y * dt;
        context.state_velocities[offset + 2] += gravity_z * dt;
        context.state_positions[offset + 0] += context.state_velocities[offset + 0] * dt;
        context.state_positions[offset + 1] += context.state_velocities[offset + 1] * dt;
        context.state_positions[offset + 2] += context.state_velocities[offset + 2] * dt;
    }
    if (!rebuild_baseline_step_pose(context)) return false;
    ++context.particle_prediction_count;
    return true;
}

void commit_particle_velocities(Mc2ContextV0& context, float dt) {
    const auto count = static_cast<std::size_t>(context.vertex_count);
    if (dt <= kMc2Epsilon || context.velocity_reference_positions.size() != count * 3) return;
    for (std::size_t vertex = 0; vertex < count; ++vertex) {
        const auto offset = vertex * 3;
        if (!is_move(context.proxy_attributes[vertex])) continue;
        context.state_velocities[offset + 0] =
            (context.state_positions[offset + 0] - context.velocity_reference_positions[offset + 0]) /
            dt * context.velocity_weight;
        context.state_velocities[offset + 1] =
            (context.state_positions[offset + 1] - context.velocity_reference_positions[offset + 1]) /
            dt * context.velocity_weight;
        context.state_velocities[offset + 2] =
            (context.state_positions[offset + 2] - context.velocity_reference_positions[offset + 2]) /
            dt * context.velocity_weight;
    }
}

struct Vec3 {
    float x = 0.0f, y = 0.0f, z = 0.0f;
};

Vec3 add(Vec3 a, Vec3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
Vec3 sub(Vec3 a, Vec3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
Vec3 mul(Vec3 a, float value) { return {a.x * value, a.y * value, a.z * value}; }
float dot(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
Vec3 cross(Vec3 a, Vec3 b) {
    return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
float length_squared(Vec3 value) { return dot(value, value); }
float length(Vec3 value) { return std::sqrt(length_squared(value)); }
Vec3 normalize(Vec3 value) {
    const float size = length(value);
    return size > kMc2Epsilon ? mul(value, 1.0f / size) : Vec3{};
}

float saturate(float value) {
    return std::max(0.0f, std::min(1.0f, value));
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

Vec3 rotate_vector(const std::array<float, 4>& rotation, Vec3 value);

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
        result = {(m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25f * s};
    } else if (m00 > m11 && m00 > m22) {
        const float s = std::sqrt(1.0f + m00 - m11 - m22) * 2.0f;
        result = {0.25f * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s};
    } else if (m11 > m22) {
        const float s = std::sqrt(1.0f + m11 - m00 - m22) * 2.0f;
        result = {(m01 + m10) / s, 0.25f * s, (m12 + m21) / s, (m02 - m20) / s};
    } else {
        const float s = std::sqrt(1.0f + m22 - m00 - m11) * 2.0f;
        result = {(m02 + m20) / s, (m12 + m21) / s, 0.25f * s, (m10 - m01) / s};
    }
    normalize_quaternion(result);
    return result;
}

Vec3 transform_vector_matrix(const float* matrix, Vec3 value) {
    return {
        matrix[0] * value.x + matrix[1] * value.y + matrix[2] * value.z,
        matrix[4] * value.x + matrix[5] * value.y + matrix[6] * value.z,
        matrix[8] * value.x + matrix[9] * value.y + matrix[10] * value.z,
    };
}

Vec3 transform_point_matrix(const float* matrix, Vec3 value) {
    Vec3 result = transform_vector_matrix(matrix, value);
    result.x += matrix[3];
    result.y += matrix[7];
    result.z += matrix[11];
    return result;
}

std::array<float, 4> transform_rotation_matrix(
    const float* matrix,
    const std::array<float, 4>& rotation
) {
    const Vec3 up = transform_vector_matrix(matrix, rotate_vector(rotation, {0.0f, 1.0f, 0.0f}));
    const Vec3 forward = transform_vector_matrix(matrix, rotate_vector(rotation, {0.0f, 0.0f, 1.0f}));
    return quaternion_from_forward_up(forward, up);
}

Vec3 rotate_vector(const std::array<float, 4>& rotation, Vec3 value) {
    const Vec3 xyz {rotation[0], rotation[1], rotation[2]};
    const Vec3 twice_cross = mul(cross(xyz, value), 2.0f);
    return add(add(value, mul(twice_cross, rotation[3])), cross(xyz, twice_cross));
}

std::array<float, 4> quaternion_inverse(std::array<float, 4> value) {
    normalize_quaternion(value);
    return {-value[0], -value[1], -value[2], value[3]};
}

std::array<float, 4> quaternion_from_to(Vec3 first, Vec3 second, float ratio = 1.0f) {
    const float first_length = length(first);
    const float second_length = length(second);
    if (first_length <= kMc2Epsilon || second_length <= kMc2Epsilon) {
        return {0.0f, 0.0f, 0.0f, 1.0f};
    }
    first = mul(first, 1.0f / first_length);
    second = mul(second, 1.0f / second_length);
    const float cosine = std::max(-1.0f, std::min(1.0f, dot(first, second)));
    if (std::abs(1.0f - cosine) < 1.0e-6f) {
        return {0.0f, 0.0f, 0.0f, 1.0f};
    }
    float angle = std::acos(cosine);
    Vec3 axis = cross(first, second);
    if (std::abs(1.0f + cosine) < 1.0e-6f) {
        angle = static_cast<float>(3.14159265358979323846);
        axis = first.x > first.y && first.x > first.z
            ? cross(first, {0.0f, 1.0f, 0.0f})
            : cross(first, {1.0f, 0.0f, 0.0f});
    }
    axis = normalize(axis);
    if (length_squared(axis) <= kMc2Epsilon) {
        return {0.0f, 0.0f, 0.0f, 1.0f};
    }
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

std::array<float, 4> load_quaternion(
    const std::vector<float>& values,
    std::size_t vertex
) {
    const auto offset = vertex * 4;
    std::array<float, 4> result {
        values[offset + 0],
        values[offset + 1],
        values[offset + 2],
        values[offset + 3],
    };
    normalize_quaternion(result);
    return result;
}

void store_quaternion(
    std::vector<float>& values,
    std::size_t vertex,
    std::array<float, 4> rotation
) {
    normalize_quaternion(rotation);
    const auto offset = vertex * 4;
    for (std::size_t component = 0; component < 4; ++component) {
        values[offset + component] = rotation[component];
    }
}

Vec3 load_vector3(const std::vector<float>& values, std::size_t vertex) {
    const auto offset = vertex * 3;
    return {values[offset + 0], values[offset + 1], values[offset + 2]};
}

std::array<float, 4> quaternion_slerp(
    const std::array<float, 4>& first,
    const std::array<float, 4>& second,
    float ratio
) {
    std::array<float, 4> output {};
    slerp_xyzw(first.data(), second.data(), ratio, output.data());
    return output;
}

bool build_bone_line_output(Mc2ContextV0& context) {
    const auto count = static_cast<std::size_t>(context.vertex_count);
    if (!context.bone_static_ready || !context.parameters_ready || !context.initialized ||
        context.state_positions.size() != count * 3 ||
        context.state_rotations.size() != count * 4 ||
        context.step_basic_positions.size() != count * 3 ||
        context.step_basic_rotations.size() != count * 4 ||
        context.proxy_attributes.size() != count ||
        context.baseline_child_ranges.size() != count * 2 ||
        context.baseline_local_positions.size() != count * 3 ||
        context.baseline_local_rotations.size() != count * 4 ||
        context.bone_vertex_to_transform_rotations.size() != count * 4 ||
        context.float_values.size() != static_cast<std::size_t>(kFloatCount)) {
        return false;
    }

    std::vector<float> work_rotations = context.step_basic_rotations;
    const float average_rate = saturate(context.float_values[kRotationalInterpolation]);
    const float root_rate = saturate(context.float_values[kRootRotation]);
    const float animation_ratio = saturate(context.animation_pose_ratio);
    const float blend = context.center_result_ready
        ? saturate(context.center_blend_weight)
        : saturate(context.velocity_weight * context.float_values[kBlendWeight]);

    const auto baseline_count = context.baseline_ranges.size() / 2;
    if (context.baseline_flags.size() != baseline_count) return false;
    for (std::size_t baseline = 0; baseline < baseline_count; ++baseline) {
        if ((context.baseline_flags[baseline] & 0x01u) == 0u) continue;
        const auto range_start = context.baseline_ranges[baseline * 2];
        const auto range_length = context.baseline_ranges[baseline * 2 + 1];
        for (std::int32_t offset = 0; offset < range_length; ++offset) {
            const auto raw_index = context.baseline_data[range_start + offset];
            if (raw_index < 0 || raw_index >= context.vertex_count) return false;
            const auto vertex = static_cast<std::size_t>(raw_index);
            const auto position = load_vector3(context.state_positions, vertex);
            auto rotation = load_quaternion(work_rotations, vertex);
            const auto attribute = context.proxy_attributes[vertex];
            const auto child_start = context.baseline_child_ranges[vertex * 2];
            const auto child_count = context.baseline_child_ranges[vertex * 2 + 1];
            const auto base_position = load_vector3(context.step_basic_positions, vertex);
            const auto base_rotation = load_quaternion(context.step_basic_rotations, vertex);
            const auto inverse_base_rotation = quaternion_inverse(base_rotation);

            if (child_count > 0 && (attribute & 0x03u) != 0u) {
                Vec3 original_sum {};
                Vec3 current_sum {};
                for (std::int32_t child_offset = 0; child_offset < child_count; ++child_offset) {
                    const auto raw_child = context.baseline_child_data[child_start + child_offset];
                    if (raw_child < 0 || raw_child >= context.vertex_count) return false;
                    const auto child = static_cast<std::size_t>(raw_child);
                    const auto child_attribute = context.proxy_attributes[child];
                    const bool zero_distance = (child_attribute & 0x20u) != 0u;
                    const auto child_base_position = load_vector3(context.step_basic_positions, child);
                    const auto child_base_rotation = load_quaternion(context.step_basic_rotations, child);
                    const auto child_base_local_position = rotate_vector(
                        inverse_base_rotation,
                        sub(child_base_position, base_position)
                    );
                    const auto child_base_local_rotation = quaternion_multiply(
                        inverse_base_rotation,
                        child_base_rotation
                    );
                    const auto static_local_position = load_vector3(
                        context.baseline_local_positions,
                        child
                    );
                    const auto child_local_position = add(
                        mul(static_local_position, 1.0f - animation_ratio),
                        mul(child_base_local_position, animation_ratio)
                    );
                    const auto static_local_rotation = load_quaternion(
                        context.baseline_local_rotations,
                        child
                    );
                    const auto child_local_rotation = quaternion_slerp(
                        static_local_rotation,
                        child_base_local_rotation,
                        animation_ratio
                    );
                    const auto original_vector = zero_distance
                        ? Vec3{}
                        : rotate_vector(rotation, child_local_position);
                    original_sum = add(original_sum, original_vector);
                    if (is_move(child_attribute)) {
                        const auto current_vector = sub(
                            load_vector3(context.state_positions, child),
                            position
                        );
                        current_sum = add(current_sum, current_vector);
                        auto child_rotation = quaternion_multiply(
                            rotation,
                            child_local_rotation
                        );
                        if (!zero_distance) {
                            child_rotation = quaternion_multiply(
                                quaternion_from_to(original_vector, current_vector),
                                child_rotation
                            );
                        }
                        store_quaternion(work_rotations, child, child_rotation);
                    } else {
                        current_sum = add(current_sum, original_vector);
                    }
                }
                const float ratio = is_move(attribute) ? average_rate : root_rate;
                const auto adjustment =
                    length(original_sum) < kMc2Epsilon || length(current_sum) < kMc2Epsilon
                    ? std::array<float, 4> {0.0f, 0.0f, 0.0f, 1.0f}
                    : quaternion_from_to(original_sum, current_sum, ratio);
                rotation = quaternion_multiply(adjustment, rotation);
            }
            store_quaternion(
                work_rotations,
                vertex,
                quaternion_slerp(base_rotation, rotation, blend)
            );
        }
    }

    context.bone_output_positions = context.state_positions;
    context.bone_output_rotations.resize(count * 4);
    for (std::size_t vertex = 0; vertex < count; ++vertex) {
        auto world_rotation = quaternion_multiply(
            load_quaternion(work_rotations, vertex),
            load_quaternion(context.bone_vertex_to_transform_rotations, vertex)
        );
        store_quaternion(context.bone_output_rotations, vertex, world_rotation);
    }
    ++context.bone_line_output_count;
    return true;
}

bool rebuild_baseline_step_pose(Mc2ContextV0& context) {
    if (context.animation_pose_ratio > 0.99f) return true;
    const auto count = static_cast<std::size_t>(context.vertex_count);
    if (context.baseline_parents.size() != count ||
        context.baseline_local_positions.size() != count * 3 ||
        context.baseline_local_rotations.size() != count * 4 ||
        context.proxy_attributes.size() != count ||
        context.step_basic_positions.size() != count * 3 ||
        context.step_basic_rotations.size() != count * 4 ||
        context.old_dynamic_positions.size() != count * 3 ||
        context.dynamic_positions.size() != count * 3 ||
        context.old_dynamic_rotations.size() != count * 4 ||
        context.dynamic_rotations.size() != count * 4 ||
        context.baseline_ranges.size() % 2 != 0) {
        return false;
    }
    const std::array<float, 4> negative_quaternion {
        context.center_negative_scale_direction[0] < 0.0f
            ? 1.0f : -1.0f,
        context.center_negative_scale_direction[1] < 0.0f
            ? 1.0f : -1.0f,
        context.center_negative_scale_direction[2] < 0.0f
            ? 1.0f : -1.0f,
        1.0f,
    };
    const bool has_negative =
        context.center_negative_scale_direction[0] < 0.0f ||
        context.center_negative_scale_direction[1] < 0.0f ||
        context.center_negative_scale_direction[2] < 0.0f;
    for (std::size_t baseline = 0; baseline < context.baseline_ranges.size() / 2; ++baseline) {
        const std::int32_t start = context.baseline_ranges[baseline * 2 + 0];
        const std::int32_t range_count = context.baseline_ranges[baseline * 2 + 1];
        for (std::int32_t offset = 0; offset < range_count; ++offset) {
            const std::int32_t data_index = start + offset;
            if (data_index < 0 ||
                data_index >= static_cast<std::int32_t>(context.baseline_data.size())) {
                return false;
            }
            const std::int32_t vertex = context.baseline_data[data_index];
            if (vertex < 0 || vertex >= static_cast<std::int32_t>(count)) return false;
            const std::int32_t parent = context.baseline_parents[vertex];
            const auto position_offset = static_cast<std::size_t>(vertex) * 3;
            const auto rotation_offset = static_cast<std::size_t>(vertex) * 4;
            if (is_move(context.proxy_attributes[vertex]) && parent >= 0) {
                if (parent >= static_cast<std::int32_t>(count)) return false;
                const auto parent_position_offset = static_cast<std::size_t>(parent) * 3;
                const auto parent_rotation_offset = static_cast<std::size_t>(parent) * 4;
                const Vec3 local_position {
                    context.baseline_local_positions[position_offset + 0] *
                        context.center_negative_scale_direction[0] *
                        context.center_initial_scale[0] * context.scale_ratio,
                    context.baseline_local_positions[position_offset + 1] *
                        context.center_negative_scale_direction[1] *
                        context.center_initial_scale[1] * context.scale_ratio,
                    context.baseline_local_positions[position_offset + 2] *
                        context.center_negative_scale_direction[2] *
                        context.center_initial_scale[2] * context.scale_ratio,
                };
                const std::array<float, 4> parent_rotation {
                    context.step_basic_rotations[parent_rotation_offset + 0],
                    context.step_basic_rotations[parent_rotation_offset + 1],
                    context.step_basic_rotations[parent_rotation_offset + 2],
                    context.step_basic_rotations[parent_rotation_offset + 3],
                };
                const Vec3 parent_position {
                    context.step_basic_positions[parent_position_offset + 0],
                    context.step_basic_positions[parent_position_offset + 1],
                    context.step_basic_positions[parent_position_offset + 2],
                };
                const Vec3 world_position = add(
                    parent_position,
                    rotate_vector(parent_rotation, local_position)
                );
                context.step_basic_positions[position_offset + 0] = world_position.x;
                context.step_basic_positions[position_offset + 1] = world_position.y;
                context.step_basic_positions[position_offset + 2] = world_position.z;
                std::array<float, 4> local_rotation {
                    context.baseline_local_rotations[rotation_offset + 0],
                    context.baseline_local_rotations[rotation_offset + 1],
                    context.baseline_local_rotations[rotation_offset + 2],
                    context.baseline_local_rotations[rotation_offset + 3],
                };
                if (has_negative) {
                    for (std::size_t component = 0; component < 4; ++component) {
                        local_rotation[component] *= negative_quaternion[component];
                    }
                }
                auto world_rotation = quaternion_multiply(parent_rotation, local_rotation);
                normalize_quaternion(world_rotation);
                std::copy(
                    world_rotation.begin(), world_rotation.end(),
                    context.step_basic_rotations.begin() +
                        static_cast<std::ptrdiff_t>(rotation_offset)
                );
            } else if (has_negative) {
                const std::array<float, 4> rotation {
                    context.step_basic_rotations[rotation_offset + 0],
                    context.step_basic_rotations[rotation_offset + 1],
                    context.step_basic_rotations[rotation_offset + 2],
                    context.step_basic_rotations[rotation_offset + 3],
                };
                const Vec3 up = rotate_vector(
                    rotation,
                    {0.0f, context.center_negative_scale_direction[1], 0.0f}
                );
                const Vec3 forward = rotate_vector(
                    rotation,
                    {0.0f, 0.0f, context.center_negative_scale_direction[2]}
                );
                const auto transformed = quaternion_from_forward_up(forward, up);
                std::copy(
                    transformed.begin(), transformed.end(),
                    context.step_basic_rotations.begin() +
                        static_cast<std::ptrdiff_t>(rotation_offset)
                );
            }
        }
    }
    const float blend = context.animation_pose_ratio;
    if (blend > kMc2Epsilon) {
        for (std::size_t baseline = 0; baseline < context.baseline_ranges.size() / 2; ++baseline) {
            const std::int32_t start = context.baseline_ranges[baseline * 2 + 0];
            const std::int32_t range_count = context.baseline_ranges[baseline * 2 + 1];
            for (std::int32_t offset = 0; offset < range_count; ++offset) {
                const std::int32_t vertex = context.baseline_data[start + offset];
                const auto position_offset = static_cast<std::size_t>(vertex) * 3;
                const auto rotation_offset = static_cast<std::size_t>(vertex) * 4;
                for (std::size_t component = 0; component < 3; ++component) {
                    const float animated_position =
                        context.old_dynamic_positions[position_offset + component] *
                            (1.0f - context.frame_interpolation) +
                        context.dynamic_positions[position_offset + component] *
                            context.frame_interpolation;
                    context.step_basic_positions[position_offset + component] +=
                        (animated_position -
                         context.step_basic_positions[position_offset + component]) * blend;
                }
                float animated_rotation[4] {};
                slerp_xyzw(
                    context.old_dynamic_rotations.data() + rotation_offset,
                    context.dynamic_rotations.data() + rotation_offset,
                    context.frame_interpolation,
                    animated_rotation
                );
                float blended_rotation[4] {};
                slerp_xyzw(
                    context.step_basic_rotations.data() + rotation_offset,
                    animated_rotation,
                    blend,
                    blended_rotation
                );
                std::copy_n(
                    blended_rotation, 4,
                    context.step_basic_rotations.data() + rotation_offset
                );
            }
        }
    }
    if (!context.baseline_ranges.empty()) ++context.baseline_pose_rebuild_count;
    return true;
}

bool evaluate_center_step(Mc2ContextV0& context, float dt) {
    if (!context.center_static_ready || !context.center_dynamic_ready ||
        context.center_initial_local_gravity_direction.size() != 3 ||
        context.float_values.size() != static_cast<std::size_t>(kFloatCount) ||
        dt <= kMc2Epsilon) {
        return false;
    }
    const float ratio = context.frame_interpolation;
    for (std::size_t component = 0; component < 3; ++component) {
        context.center_now_world_position[component] =
            context.center_old_frame_world_position[component] * (1.0f - ratio) +
            context.center_frame_world_position[component] * ratio;
        context.center_step_vector[component] =
            context.center_now_world_position[component] -
            context.center_old_world_position[component];
    }
    slerp_xyzw(
        context.center_old_frame_world_rotation.data(),
        context.center_frame_world_rotation.data(),
        ratio,
        context.center_now_world_rotation.data()
    );
    const std::array<float, 4> inverse_old {
        -context.center_old_world_rotation[0],
        -context.center_old_world_rotation[1],
        -context.center_old_world_rotation[2],
        context.center_old_world_rotation[3],
    };
    context.center_step_rotation = quaternion_multiply(
        context.center_now_world_rotation,
        inverse_old
    );
    normalize_quaternion(context.center_step_rotation);
    float rotation_cosine = 0.0f;
    for (std::size_t component = 0; component < 4; ++component) {
        rotation_cosine += context.center_old_world_rotation[component] *
            context.center_now_world_rotation[component];
    }
    const float step_angle = 2.0f * std::acos(
        std::max(0.0f, std::min(1.0f, std::fabs(rotation_cosine)))
    );

    float move_inertia = 1.0f - context.float_values[kLocalInertia];
    const Vec3 step_vector {
        context.center_step_vector[0],
        context.center_step_vector[1],
        context.center_step_vector[2],
    };
    const float local_speed = length(mul(step_vector, 1.0f - move_inertia)) / dt;
    const float movement_limit = context.float_values[kLocalMovementSpeedLimit];
    if (local_speed > movement_limit && movement_limit >= 0.0f) {
        const float limit_ratio = movement_limit / local_speed;
        move_inertia = 1.0f + (move_inertia - 1.0f) * limit_ratio;
    }
    float rotation_inertia = 1.0f - context.float_values[kLocalInertia];
    const float local_angle_speed =
        step_angle * (1.0f - rotation_inertia) / dt * 57.29577951308232f;
    const float rotation_limit = context.float_values[kLocalRotationSpeedLimit];
    if (local_angle_speed > rotation_limit && rotation_limit >= 0.0f) {
        const float limit_ratio = rotation_limit / local_angle_speed;
        rotation_inertia = 1.0f + (rotation_inertia - 1.0f) * limit_ratio;
    }
    context.center_step_move_inertia_ratio = move_inertia;
    context.center_step_rotation_inertia_ratio = rotation_inertia;
    for (std::size_t component = 0; component < 3; ++component) {
        context.center_inertia_vector[component] =
            context.center_step_vector[component] * move_inertia;
    }
    const std::array<float, 4> identity {0.0f, 0.0f, 0.0f, 1.0f};
    slerp_xyzw(
        identity.data(),
        context.center_step_rotation.data(),
        rotation_inertia,
        context.center_inertia_rotation.data()
    );
    context.center_angular_velocity = step_angle / dt;
    const float axis_length = std::sqrt(
        context.center_step_rotation[0] * context.center_step_rotation[0] +
        context.center_step_rotation[1] * context.center_step_rotation[1] +
        context.center_step_rotation[2] * context.center_step_rotation[2]
    );
    for (std::size_t component = 0; component < 3; ++component) {
        context.center_rotation_axis[component] =
            context.center_angular_velocity > kMc2Epsilon && axis_length > kMc2Epsilon
            ? context.center_step_rotation[component] / axis_length
            : 0.0f;
    }

    std::array<float, 3> world_scale {};
    for (std::size_t component = 0; component < 3; ++component) {
        world_scale[component] =
            context.center_old_frame_world_scale[component] * (1.0f - ratio) +
            context.center_frame_world_scale[component] * ratio;
    }
    const float world_scale_length = std::sqrt(
        world_scale[0] * world_scale[0] +
        world_scale[1] * world_scale[1] +
        world_scale[2] * world_scale[2]
    );
    const float initial_scale_length = std::sqrt(
        context.center_initial_scale[0] * context.center_initial_scale[0] +
        context.center_initial_scale[1] * context.center_initial_scale[1] +
        context.center_initial_scale[2] * context.center_initial_scale[2]
    );
    context.scale_ratio = std::max(world_scale_length / initial_scale_length, 1.0e-6f);

    Vec3 initial_gravity {
        context.center_initial_local_gravity_direction[0],
        context.center_initial_local_gravity_direction[1] *
            context.center_negative_scale_direction[1],
        context.center_initial_local_gravity_direction[2],
    };
    const Vec3 world_gravity {
        context.float_values[kGravityDirection + 0],
        context.float_values[kGravityDirection + 1],
        context.float_values[kGravityDirection + 2],
    };
    float gravity_dot = 1.0f;
    if (length_squared(world_gravity) > kMc2Epsilon) {
        gravity_dot = saturate(
            dot(rotate_vector(context.center_now_world_rotation, initial_gravity), world_gravity) *
            0.5f + 0.5f
        );
    }
    context.center_gravity_dot = gravity_dot;
    context.gravity_ratio = 1.0f;
    const float gravity_falloff = context.float_values[kGravityFalloff];
    if (context.float_values[kGravity] > 1.0e-6f && gravity_falloff > 1.0e-6f) {
        context.gravity_ratio =
            saturate(1.0f - gravity_falloff) +
            (1.0f - saturate(1.0f - gravity_falloff)) *
            saturate(1.0f - gravity_dot);
    }
    if (context.velocity_weight < 1.0f) {
        const float stabilization = context.float_values[kStabilizationTime];
        const float added = stabilization > 1.0e-6f ? dt / stabilization : 1.0f;
        context.velocity_weight = saturate(context.velocity_weight + added);
    }
    context.center_blend_weight = saturate(
        context.velocity_weight * context.float_values[kBlendWeight] *
        context.center_distance_weight
    );
    context.center_dynamic_ready = false;
    context.center_result_ready = true;
    ++context.center_step_count;
    return true;
}

float bending_inverse_mass(const Mc2ContextV0& context, std::size_t vertex) {
    if (!is_move(context.proxy_attributes[vertex])) return 0.01f;
    const float depth_offset = 1.0f - context.baseline_depths[vertex];
    return 1.0f / (1.0f + depth_offset * depth_offset * 5.0f);
}

bool calc_bending_volume(
    const Vec3 p[4], const float inv_mass[4], float rest, float stiffness, Vec3 out[4]
) {
    float volume = dot(cross(sub(p[1], p[0]), sub(p[2], p[0])), sub(p[3], p[0])) /
        6.0f * 1000.0f;
    Vec3 grad[4] = {
        cross(sub(p[1], p[2]), sub(p[3], p[2])),
        cross(sub(p[2], p[0]), sub(p[3], p[0])),
        cross(sub(p[0], p[1]), sub(p[3], p[1])),
        cross(sub(p[1], p[0]), sub(p[2], p[0])),
    };
    float lambda = 0.0f;
    for (int i = 0; i < 4; ++i) lambda += inv_mass[i] * length_squared(grad[i]);
    lambda *= 1000.0f;
    if (std::fabs(lambda) < 1.0e-6f) return false;
    lambda = stiffness * (rest - volume) / lambda;
    for (int i = 0; i < 4; ++i) out[i] = mul(grad[i], lambda * inv_mass[i]);
    return true;
}

bool calc_bending_dihedral(
    const Vec3 p[4], const float inv_mass[4], float rest, float stiffness, Vec3 out[4]
) {
    const Vec3 edge = sub(p[3], p[2]);
    const float edge_length = length(edge);
    if (edge_length < kMc2Epsilon) return false;
    const float inverse_edge_length = 1.0f / edge_length;
    Vec3 n1 = cross(sub(p[2], p[0]), sub(p[3], p[0]));
    Vec3 n2 = cross(sub(p[3], p[1]), sub(p[2], p[1]));
    const float n1_length_squared = length_squared(n1);
    const float n2_length_squared = length_squared(n2);
    if (n1_length_squared == 0.0f || n2_length_squared == 0.0f) return false;
    n1 = mul(n1, 1.0f / n1_length_squared);
    n2 = mul(n2, 1.0f / n2_length_squared);
    Vec3 derivative[4] = {
        mul(n1, edge_length),
        mul(n2, edge_length),
        add(
            mul(n1, dot(sub(p[0], p[3]), edge) * inverse_edge_length),
            mul(n2, dot(sub(p[1], p[3]), edge) * inverse_edge_length)
        ),
        add(
            mul(n1, dot(sub(p[2], p[0]), edge) * inverse_edge_length),
            mul(n2, dot(sub(p[2], p[1]), edge) * inverse_edge_length)
        ),
    };
    n1 = normalize(n1);
    n2 = normalize(n2);
    float phi = std::acos(std::max(-1.0f, std::min(1.0f, dot(n1, n2))));
    float denominator = 0.0f;
    for (int i = 0; i < 4; ++i) denominator += inv_mass[i] * length_squared(derivative[i]);
    if (denominator == 0.0f) return false;
    const float direction_value = dot(cross(n1, n2), edge);
    const float direction = direction_value < 0.0f ? -1.0f : (direction_value > 0.0f ? 1.0f : 0.0f);
    phi *= direction;
    const float lambda = (rest - phi) / denominator * stiffness;
    for (int i = 0; i < 4; ++i) out[i] = mul(derivative[i], -inv_mass[i] * lambda);
    return true;
}

void solve_bending_once(Mc2ContextV0& context, float simulation_power_y) {
    const auto record_count = context.bending_rest_angle_or_volume.size();
    const auto vertex_count = static_cast<std::size_t>(context.vertex_count);
    if (!context.bending_static_ready || record_count == 0 ||
        context.int_values.size() != static_cast<std::size_t>(kIntCount) ||
        context.int_values[3] == 0 ||
        context.float_values.size() != static_cast<std::size_t>(kFloatCount)) return;
    const float stiffness = std::max(
        0.0f,
        std::min(1.0f, context.float_values[kBendingStiffness] * simulation_power_y)
    );
    if (stiffness < 1.0e-6f) return;
    std::vector<std::int32_t> sums(vertex_count * 3, 0);
    std::vector<std::int32_t> counts(vertex_count, 0);
    for (std::size_t record = 0; record < record_count; ++record) {
        Vec3 positions[4];
        float inv_mass[4];
        std::size_t vertices[4];
        for (int role = 0; role < 4; ++role) {
            vertices[role] = static_cast<std::size_t>(context.bending_quads[record * 4 + role]);
            const auto offset = vertices[role] * 3;
            positions[role] = {
                context.state_positions[offset + 0],
                context.state_positions[offset + 1],
                context.state_positions[offset + 2],
            };
            inv_mass[role] = bending_inverse_mass(context, vertices[role]);
        }
        Vec3 correction[4];
        const auto marker = context.bending_sign_or_volume[record];
        const float raw_rest = context.bending_rest_angle_or_volume[record];
        const bool solved = marker == 100
            ? calc_bending_volume(
                positions,
                inv_mass,
                raw_rest * context.scale_ratio * context.negative_scale_sign,
                stiffness,
                correction
            )
            : calc_bending_dihedral(
                positions,
                inv_mass,
                raw_rest * (marker < 0 ? -1.0f : 1.0f) * context.negative_scale_sign,
                stiffness,
                correction
            );
        if (!solved) continue;
        for (int role = 0; role < 4; ++role) {
            const auto vertex = vertices[role];
            sums[vertex * 3 + 0] += static_cast<std::int32_t>(correction[role].x * 1000000.0f);
            sums[vertex * 3 + 1] += static_cast<std::int32_t>(correction[role].y * 1000000.0f);
            sums[vertex * 3 + 2] += static_cast<std::int32_t>(correction[role].z * 1000000.0f);
            ++counts[vertex];
        }
    }
    for (std::size_t vertex = 0; vertex < vertex_count; ++vertex) {
        if (!is_move(context.proxy_attributes[vertex]) || counts[vertex] <= 0) continue;
        const auto offset = vertex * 3;
        const float scale = 0.000001f / static_cast<float>(counts[vertex]);
        context.state_positions[offset + 0] += static_cast<float>(sums[offset + 0]) * scale;
        context.state_positions[offset + 1] += static_cast<float>(sums[offset + 1]) * scale;
        context.state_positions[offset + 2] += static_cast<float>(sums[offset + 2]) * scale;
    }
    ++context.bending_solve_count;
}

float distance_inverse_mass(const Mc2ContextV0& context, std::size_t vertex) {
    if (!is_move(context.proxy_attributes[vertex])) return kDistanceFixedInverseMass;
    const float depth_delta = 1.0f - context.baseline_depths[vertex];
    return 1.0f / (1.0f + depth_delta * depth_delta * 5.0f);
}

void solve_distance_once(Mc2ContextV0& context, float simulation_power_y) {
    const auto count = static_cast<std::size_t>(context.vertex_count);
    if (context.state_positions.size() != count * 3 ||
        context.proxy_attributes.size() != count) {
        return;
    }

    if (!context.distance_static_ready || context.distance_targets.empty()) return;
    if (context.baseline_depths.size() != count ||
        context.distance_ranges.size() != count * 2 ||
        context.distance_targets.size() != context.distance_rest_signed.size()) {
        return;
    }

    for (std::size_t vertex = 0; vertex < count; ++vertex) {
        if (!is_move(context.proxy_attributes[vertex])) continue;
        const float stiffness = std::max(
            0.0f,
            std::min(1.0f, sample_curve16(
                context.curve_values,
                kDistanceStiffnessCurve,
                context.baseline_depths[vertex]
            ) * simulation_power_y)
        );
        if (stiffness <= kMc2Epsilon) continue;
        const auto start = context.distance_ranges[vertex * 2];
        const auto record_count = context.distance_ranges[vertex * 2 + 1];
        const auto offset = vertex * 3;
        const float current_x = context.state_positions[offset + 0];
        const float current_y = context.state_positions[offset + 1];
        const float current_z = context.state_positions[offset + 2];
        const float inverse_mass = distance_inverse_mass(context, vertex);
        float add_x = 0.0f;
        float add_y = 0.0f;
        float add_z = 0.0f;
        std::int32_t add_count = 0;
        for (std::int32_t local = 0; local < record_count; ++local) {
            const auto record = static_cast<std::size_t>(start + local);
            const auto target = static_cast<std::size_t>(context.distance_targets[record]);
            const auto target_offset = target * 3;
            const float dx = context.state_positions[target_offset + 0] - current_x;
            const float dy = context.state_positions[target_offset + 1] - current_y;
            const float dz = context.state_positions[target_offset + 2] - current_z;
            const float rest_signed = context.distance_rest_signed[record];
            const float static_rest = std::fabs(rest_signed);
            if (static_rest <= kMc2Epsilon) {
                add_x = dx * 0.5f;
                add_y = dy * 0.5f;
                add_z = dz * 0.5f;
                ++add_count;
                continue;
            }
            const float distance = std::sqrt(dx * dx + dy * dy + dz * dz);
            if (distance <= kMc2Epsilon) continue;
            const float target_inverse_mass = distance_inverse_mass(context, target);
            const float animated_dx =
                context.step_basic_positions[target_offset + 0] -
                context.step_basic_positions[offset + 0];
            const float animated_dy =
                context.step_basic_positions[target_offset + 1] -
                context.step_basic_positions[offset + 1];
            const float animated_dz =
                context.step_basic_positions[target_offset + 2] -
                context.step_basic_positions[offset + 2];
            const float animated_rest = std::sqrt(
                animated_dx * animated_dx + animated_dy * animated_dy +
                animated_dz * animated_dz
            );
            const float rest =
                static_rest * context.scale_ratio * (1.0f - context.animation_pose_ratio) +
                animated_rest * context.animation_pose_ratio;
            const float local_stiffness = rest_signed < 0.0f
                ? stiffness * kDistanceHorizontalStiffness
                : stiffness;
            const float correction =
                ((distance - rest) * local_stiffness /
                 (inverse_mass + target_inverse_mass)) /
                distance;
            add_x += dx * correction * inverse_mass;
            add_y += dy * correction * inverse_mass;
            add_z += dz * correction * inverse_mass;
            ++add_count;
        }
        if (add_count > 0) {
            const float inverse_count = 1.0f / static_cast<float>(add_count);
            const float correction_x = add_x * inverse_count;
            const float correction_y = add_y * inverse_count;
            const float correction_z = add_z * inverse_count;
            context.state_positions[offset + 0] = current_x + correction_x;
            context.state_positions[offset + 1] = current_y + correction_y;
            context.state_positions[offset + 2] = current_z + correction_z;
            if (context.velocity_reference_positions.size() == count * 3) {
                const float attenuation = context.float_values[kDistanceVelocityAttenuation];
                context.velocity_reference_positions[offset + 0] += correction_x * attenuation;
                context.velocity_reference_positions[offset + 1] += correction_y * attenuation;
                context.velocity_reference_positions[offset + 2] += correction_z * attenuation;
            }
        }
    }
    ++context.distance_solve_count;
}

PyObject* inspect_context(const Mc2ContextV0& context) {
    std::int64_t fixed_count = 0;
    for (const auto attribute : context.proxy_attributes) {
        if ((attribute & 0x01u) != 0u) ++fixed_count;
    }
    PyObject* result = PyDict_New();
    if (result == nullptr) return nullptr;
    if (!dict_string(result, "schema", "mc2_context_v0") ||
        !dict_i64(result, "schema_version", kSchemaVersion) ||
        !dict_i64(result, "vertex_count", context.vertex_count) ||
        !dict_i64(result, "proxy_static_revision", context.proxy_static_revision) ||
        !dict_i64(result, "baseline_static_revision", context.baseline_static_revision) ||
        !dict_i64(result, "bone_static_revision", context.bone_static_revision) ||
        !dict_i64(result, "distance_static_revision", context.distance_static_revision) ||
        !dict_i64(result, "bending_static_revision", context.bending_static_revision) ||
        !dict_i64(result, "center_static_revision", context.center_static_revision) ||
        !dict_i64(result, "center_dynamic_revision", context.center_dynamic_revision) ||
        !dict_i64(
            result,
            "step_interpolation_revision",
            context.step_interpolation_revision
        ) ||
        !dict_i64(result, "edge_count", static_cast<std::int64_t>(context.proxy_edges.size() / 2)) ||
        !dict_i64(result, "triangle_count", static_cast<std::int64_t>(context.proxy_triangles.size() / 3)) ||
        !dict_i64(result, "baseline_count", static_cast<std::int64_t>(context.baseline_ranges.size() / 2)) ||
        !dict_i64(result, "bone_vertex_adjacency_count", static_cast<std::int64_t>(context.bone_vertex_to_vertex_data.size())) ||
        !dict_i64(result, "bone_vertex_triangle_record_count", static_cast<std::int64_t>(context.bone_vertex_to_triangle_data.size() / 2)) ||
        !dict_i64(result, "fixed_count", fixed_count) ||
        !dict_i64(result, "distance_record_count", static_cast<std::int64_t>(context.distance_targets.size())) ||
        !dict_i64(result, "bending_record_count", static_cast<std::int64_t>(context.bending_rest_angle_or_volume.size())) ||
        !dict_i64(result, "center_fixed_count", static_cast<std::int64_t>(context.center_fixed_indices.size())) ||
        !dict_i64(result, "parameter_revision", context.parameter_revision) ||
        !dict_i64(result, "dynamic_revision", context.dynamic_revision) ||
        !dict_i64(result, "reset_count", context.reset_count) ||
        !dict_i64(result, "step_count", context.step_count) ||
        !dict_i64(result, "distance_solve_count", context.distance_solve_count) ||
        !dict_i64(result, "particle_prediction_count", context.particle_prediction_count) ||
        !dict_i64(result, "particle_inertia_count", context.particle_inertia_count) ||
        !dict_i64(result, "bending_solve_count", context.bending_solve_count) ||
        !dict_i64(result, "center_step_count", context.center_step_count) ||
        !dict_i64(result, "center_frame_shift_count", context.center_frame_shift_count) ||
        !dict_i64(
            result,
            "center_negative_scale_teleport_count",
            context.center_negative_scale_teleport_count
        ) ||
        !dict_i64(result, "team_options_revision", context.team_options_revision) ||
        !dict_i64(result, "baseline_pose_rebuild_count", context.baseline_pose_rebuild_count) ||
        !dict_i64(result, "bone_line_output_count", context.bone_line_output_count) ||
        !dict_float(result, "animation_pose_ratio", context.animation_pose_ratio) ||
        !dict_i64(result, "frame", context.frame) ||
        !dict_i64(result, "generation", context.generation) ||
        !dict_bool(result, "parameters_ready", context.parameters_ready) ||
        !dict_bool(result, "proxy_static_ready", context.proxy_static_ready) ||
        !dict_bool(result, "baseline_static_ready", context.baseline_static_ready) ||
        !dict_bool(result, "bone_static_ready", context.bone_static_ready) ||
        !dict_bool(
            result,
            "bone_output_ready",
            context.bone_output_positions.size() ==
                    static_cast<std::size_t>(context.vertex_count) * 3 &&
                context.bone_output_rotations.size() ==
                    static_cast<std::size_t>(context.vertex_count) * 4
        ) ||
        !dict_bool(result, "distance_static_ready", context.distance_static_ready) ||
        !dict_bool(result, "bending_static_ready", context.bending_static_ready) ||
        !dict_bool(result, "center_static_ready", context.center_static_ready) ||
        !dict_bool(result, "center_dynamic_ready", context.center_dynamic_ready) ||
        !dict_bool(result, "center_frame_ready", context.center_frame_ready) ||
        !dict_bool(result, "center_result_ready", context.center_result_ready) ||
        !dict_bool(
            result,
            "step_basic_ready",
            context.step_basic_positions.size() ==
                    static_cast<std::size_t>(context.vertex_count) * 3 &&
                context.step_basic_rotations.size() ==
                    static_cast<std::size_t>(context.vertex_count) * 4
        ) ||
        !dict_bool(result, "dynamic_ready", context.dynamic_ready) ||
        !dict_bool(result, "initialized", context.initialized) ||
        !dict_bool(result, "released", context.released)) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}

}  // namespace

PyObject* mc2_context_v0_create(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_create expects 2 arguments");
        return nullptr;
    }
    const long schema = as_long(PyTuple_GET_ITEM(args, 0), "schema_version");
    const long vertex_count = as_long(PyTuple_GET_ITEM(args, 1), "vertex_count");
    if (PyErr_Occurred()) return nullptr;
    if (schema != kSchemaVersion) {
        PyErr_SetString(PyExc_ValueError, "unsupported MC2 context schema version");
        return nullptr;
    }
    if (vertex_count <= 0 || vertex_count > std::numeric_limits<std::int32_t>::max()) {
        PyErr_SetString(PyExc_ValueError, "vertex_count must be positive int32");
        return nullptr;
    }
    auto* context = new Mc2ContextV0();
    context->vertex_count = vertex_count;
    PyObject* capsule = PyCapsule_New(context, kCapsuleName, destroy_context);
    if (capsule == nullptr) {
        delete context;
        return nullptr;
    }
    ++g_created;
    ++g_live;
    return capsule;
}

PyObject* mc2_context_v0_inspect(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 1) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_inspect expects 1 argument");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (context == nullptr) return nullptr;
    return inspect_context(*context);
}

PyObject* mc2_context_v0_update_proxy_static(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 8) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_proxy_static expects 8 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    Buffer positions, normals, tangents, uvs, attributes, edges, triangles;
    if (!positions.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "local_positions") ||
        !normals.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "local_normals") ||
        !tangents.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "local_tangents") ||
        !uvs.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "uvs") ||
        !attributes.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "vertex_attributes") ||
        !edges.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "edges") ||
        !triangles.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "triangles")) {
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->vertex_count);
    Py_ssize_t edge_count = 0;
    Py_ssize_t triangle_count = 0;
    if (!expect_float32(positions, "local_positions") ||
        !expect_2d(positions, "local_positions", count, 3) ||
        !expect_float32(normals, "local_normals") ||
        !expect_2d(normals, "local_normals", count, 3) ||
        !expect_float32(tangents, "local_tangents") ||
        !expect_2d(tangents, "local_tangents", count, 3) ||
        !expect_float32(uvs, "uvs") ||
        !expect_2d(uvs, "uvs", count, 2) ||
        !expect_uint8(attributes, "vertex_attributes") ||
        !expect_1d_array(attributes, "vertex_attributes", count) ||
        !expect_int32_pair_array(edges, "edges", &edge_count) ||
        !expect_int32_triple_array(triangles, "triangles", &triangle_count) ||
        !finite_floats(positions, "local_positions") ||
        !finite_floats(normals, "local_normals") ||
        !finite_floats(tangents, "local_tangents") ||
        !finite_floats(uvs, "uvs") ||
        !validate_indices(edges, context->vertex_count, "edges") ||
        !validate_indices(triangles, context->vertex_count, "triangles")) {
        return nullptr;
    }
    const auto* edge_values = static_cast<const std::int32_t*>(edges.view.buf);
    for (Py_ssize_t row = 0; row < edge_count; ++row) {
        if (edge_values[row * 2] == edge_values[row * 2 + 1]) {
            PyErr_SetString(PyExc_ValueError, "edges cannot contain self edges");
            return nullptr;
        }
    }
    const auto* triangle_values = static_cast<const std::int32_t*>(triangles.view.buf);
    for (Py_ssize_t row = 0; row < triangle_count; ++row) {
        const auto* value = triangle_values + row * 3;
        if (value[0] == value[1] || value[0] == value[2] || value[1] == value[2]) {
            PyErr_SetString(PyExc_ValueError, "triangles cannot be degenerate");
            return nullptr;
        }
    }
    auto next_positions = copy_values<float>(positions);
    auto next_normals = copy_values<float>(normals);
    auto next_tangents = copy_values<float>(tangents);
    auto next_uvs = copy_values<float>(uvs);
    auto next_attributes = copy_values<std::uint8_t>(attributes);
    auto next_edges = copy_values<std::int32_t>(edges);
    auto next_triangles = copy_values<std::int32_t>(triangles);
    context->proxy_local_positions.swap(next_positions);
    context->proxy_local_normals.swap(next_normals);
    context->proxy_local_tangents.swap(next_tangents);
    context->proxy_uvs.swap(next_uvs);
    context->proxy_attributes.swap(next_attributes);
    context->proxy_edges.swap(next_edges);
    context->proxy_triangles.swap(next_triangles);
    context->proxy_static_ready = true;
    ++context->proxy_static_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_baseline_static(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 11) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_baseline_static expects 11 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    Buffer parents, child_ranges, child_data, flags, ranges, data, roots;
    Buffer depths, local_positions, local_rotations;
    if (!parents.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "parent_indices") ||
        !child_ranges.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "child_ranges") ||
        !child_data.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "child_data") ||
        !flags.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "baseline_flags") ||
        !ranges.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "baseline_ranges") ||
        !data.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "baseline_data") ||
        !roots.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "root_indices") ||
        !depths.get(PyTuple_GET_ITEM(args, 8), PyBUF_FORMAT | PyBUF_ND, "depths") ||
        !local_positions.get(PyTuple_GET_ITEM(args, 9), PyBUF_FORMAT | PyBUF_ND, "vertex_local_positions") ||
        !local_rotations.get(PyTuple_GET_ITEM(args, 10), PyBUF_FORMAT | PyBUF_ND, "vertex_local_rotations")) {
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->vertex_count);
    Py_ssize_t child_range_count = 0;
    Py_ssize_t range_count = 0;
    if (!expect_int32(parents, "parent_indices") ||
        !expect_1d_array(parents, "parent_indices", count) ||
        !expect_int32_pair_array(child_ranges, "child_ranges", &child_range_count) ||
        child_range_count != count ||
        !expect_int32_scalar_array(child_data, "child_data") ||
        !expect_uint8_scalar_array(flags, "baseline_flags") ||
        !expect_int32_pair_array(ranges, "baseline_ranges", &range_count) ||
        flags.view.shape[0] != range_count ||
        !expect_int32_scalar_array(data, "baseline_data") ||
        !expect_int32(roots, "root_indices") ||
        !expect_1d_array(roots, "root_indices", count) ||
        !expect_float32(depths, "depths") ||
        !expect_1d_array(depths, "depths", count) ||
        !expect_float32(local_positions, "vertex_local_positions") ||
        !expect_2d(local_positions, "vertex_local_positions", count, 3) ||
        !expect_float32(local_rotations, "vertex_local_rotations") ||
        !expect_2d(local_rotations, "vertex_local_rotations", count, 4) ||
        !validate_indices(parents, context->vertex_count, "parent_indices", true) ||
        !validate_indices(child_data, context->vertex_count, "child_data") ||
        !validate_indices(data, context->vertex_count, "baseline_data") ||
        !validate_indices(roots, context->vertex_count, "root_indices", true) ||
        !validate_dense_ranges(child_ranges, child_data.view.shape[0], "child_ranges") ||
        !validate_dense_ranges(ranges, data.view.shape[0], "baseline_ranges") ||
        !finite_floats(depths, "depths") ||
        !finite_floats(local_positions, "vertex_local_positions") ||
        !finite_floats(local_rotations, "vertex_local_rotations")) {
        if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "baseline static shape mismatch");
        return nullptr;
    }
    const auto* depth_values = static_cast<const float*>(depths.view.buf);
    for (Py_ssize_t index = 0; index < count; ++index) {
        if (depth_values[index] < 0.0f || depth_values[index] > 1.0f) {
            PyErr_SetString(PyExc_ValueError, "depths must be normalized");
            return nullptr;
        }
    }
    auto next_parents = copy_values<std::int32_t>(parents);
    auto next_child_ranges = copy_values<std::int32_t>(child_ranges);
    auto next_child_data = copy_values<std::int32_t>(child_data);
    auto next_flags = copy_values<std::uint8_t>(flags);
    auto next_ranges = copy_values<std::int32_t>(ranges);
    auto next_data = copy_values<std::int32_t>(data);
    auto next_roots = copy_values<std::int32_t>(roots);
    auto next_depths = copy_values<float>(depths);
    auto next_local_positions = copy_values<float>(local_positions);
    auto next_local_rotations = copy_values<float>(local_rotations);
    context->baseline_parents.swap(next_parents);
    context->baseline_child_ranges.swap(next_child_ranges);
    context->baseline_child_data.swap(next_child_data);
    context->baseline_flags.swap(next_flags);
    context->baseline_ranges.swap(next_ranges);
    context->baseline_data.swap(next_data);
    context->baseline_roots.swap(next_roots);
    context->baseline_depths.swap(next_depths);
    context->baseline_local_positions.swap(next_local_positions);
    context->baseline_local_rotations.swap(next_local_rotations);
    context->baseline_static_ready = true;
    ++context->baseline_static_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_bone_static(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 9) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_bone_static expects 9 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->proxy_static_ready || !context->baseline_static_ready) {
        PyErr_SetString(PyExc_RuntimeError, "Bone static requires proxy and baseline static");
        return nullptr;
    }

    Buffer vertex_ranges, vertex_data, triangle_ranges, triangle_data;
    Buffer bind_positions, bind_rotations, adjustment_rotations, transform_rotations;
    if (!vertex_ranges.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "vertex_to_vertex_ranges") ||
        !vertex_data.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "vertex_to_vertex_data") ||
        !triangle_ranges.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "vertex_to_triangle_ranges") ||
        !triangle_data.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "vertex_to_triangle_data") ||
        !bind_positions.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "vertex_bind_pose_positions") ||
        !bind_rotations.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "vertex_bind_pose_rotations") ||
        !adjustment_rotations.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "normal_adjustment_rotations") ||
        !transform_rotations.get(PyTuple_GET_ITEM(args, 8), PyBUF_FORMAT | PyBUF_ND, "vertex_to_transform_rotations")) {
        return nullptr;
    }

    const auto count = static_cast<Py_ssize_t>(context->vertex_count);
    Py_ssize_t vertex_range_count = 0;
    Py_ssize_t triangle_range_count = 0;
    Py_ssize_t triangle_record_count = 0;
    if (!expect_int32_pair_array(vertex_ranges, "vertex_to_vertex_ranges", &vertex_range_count) ||
        vertex_range_count != count ||
        !expect_int32_scalar_array(vertex_data, "vertex_to_vertex_data") ||
        !expect_int32_pair_array(triangle_ranges, "vertex_to_triangle_ranges", &triangle_range_count) ||
        triangle_range_count != count ||
        !expect_int32_pair_array(triangle_data, "vertex_to_triangle_data", &triangle_record_count) ||
        !expect_float32(bind_positions, "vertex_bind_pose_positions") ||
        !expect_2d(bind_positions, "vertex_bind_pose_positions", count, 3) ||
        !expect_float32(bind_rotations, "vertex_bind_pose_rotations") ||
        !expect_2d(bind_rotations, "vertex_bind_pose_rotations", count, 4) ||
        !expect_float32(adjustment_rotations, "normal_adjustment_rotations") ||
        !expect_2d(adjustment_rotations, "normal_adjustment_rotations", count, 4) ||
        !expect_float32(transform_rotations, "vertex_to_transform_rotations") ||
        !expect_2d(transform_rotations, "vertex_to_transform_rotations", count, 4) ||
        !validate_dense_ranges(vertex_ranges, vertex_data.view.shape[0], "vertex_to_vertex_ranges") ||
        !validate_dense_ranges(triangle_ranges, triangle_record_count, "vertex_to_triangle_ranges") ||
        !validate_indices(vertex_data, context->vertex_count, "vertex_to_vertex_data") ||
        !finite_floats(bind_positions, "vertex_bind_pose_positions") ||
        !finite_floats(bind_rotations, "vertex_bind_pose_rotations") ||
        !finite_floats(adjustment_rotations, "normal_adjustment_rotations") ||
        !finite_floats(transform_rotations, "vertex_to_transform_rotations") ||
        !validate_quaternions(bind_rotations, "vertex_bind_pose_rotations") ||
        !validate_quaternions(adjustment_rotations, "normal_adjustment_rotations") ||
        !validate_quaternions(transform_rotations, "vertex_to_transform_rotations")) {
        return nullptr;
    }

    const auto* vertex_range_values = static_cast<const std::int32_t*>(vertex_ranges.view.buf);
    const auto* vertex_data_values = static_cast<const std::int32_t*>(vertex_data.view.buf);
    std::vector<std::pair<std::int32_t, std::int32_t>> observed_relations;
    observed_relations.reserve(static_cast<std::size_t>(vertex_data.view.shape[0]));
    for (Py_ssize_t vertex = 0; vertex < count; ++vertex) {
        const auto start = vertex_range_values[vertex * 2];
        const auto length = vertex_range_values[vertex * 2 + 1];
        std::vector<std::int32_t> seen;
        seen.reserve(static_cast<std::size_t>(length));
        for (std::int32_t offset = 0; offset < length; ++offset) {
            const auto neighbor = vertex_data_values[start + offset];
            if (neighbor == vertex || std::find(seen.begin(), seen.end(), neighbor) != seen.end()) {
                PyErr_SetString(PyExc_ValueError, "vertex adjacency cannot contain self or duplicate neighbors");
                return nullptr;
            }
            seen.push_back(neighbor);
            observed_relations.emplace_back(static_cast<std::int32_t>(vertex), neighbor);
        }
    }
    std::vector<std::pair<std::int32_t, std::int32_t>> expected_relations;
    expected_relations.reserve(context->proxy_edges.size());
    for (std::size_t offset = 0; offset < context->proxy_edges.size(); offset += 2) {
        const auto first = context->proxy_edges[offset];
        const auto second = context->proxy_edges[offset + 1];
        expected_relations.emplace_back(first, second);
        expected_relations.emplace_back(second, first);
    }
    std::sort(observed_relations.begin(), observed_relations.end());
    std::sort(expected_relations.begin(), expected_relations.end());
    if (observed_relations != expected_relations) {
        PyErr_SetString(PyExc_ValueError, "vertex adjacency must cover exactly the proxy edges");
        return nullptr;
    }

    const auto* triangle_range_values = static_cast<const std::int32_t*>(triangle_ranges.view.buf);
    const auto* triangle_data_values = static_cast<const std::int32_t*>(triangle_data.view.buf);
    const auto triangle_count = static_cast<std::int32_t>(context->proxy_triangles.size() / 3);
    for (Py_ssize_t vertex = 0; vertex < count; ++vertex) {
        const auto start = triangle_range_values[vertex * 2];
        const auto length = triangle_range_values[vertex * 2 + 1];
        if (length > 7) {
            PyErr_SetString(PyExc_ValueError, "vertex_to_triangle_data supports at most 7 records per vertex");
            return nullptr;
        }
        std::vector<std::int32_t> seen;
        seen.reserve(static_cast<std::size_t>(length));
        for (std::int32_t offset = 0; offset < length; ++offset) {
            const auto* record = triangle_data_values + (start + offset) * 2;
            const auto flip = record[0];
            const auto triangle = record[1];
            if (flip < 0 || flip > 3) {
                PyErr_SetString(PyExc_ValueError, "vertex-to-triangle flip flag must be in 0..3");
                return nullptr;
            }
            if (triangle < 0 || triangle >= triangle_count) {
                PyErr_SetString(PyExc_ValueError, "vertex-to-triangle index is out of range");
                return nullptr;
            }
            if (std::find(seen.begin(), seen.end(), triangle) != seen.end()) {
                PyErr_SetString(PyExc_ValueError, "vertex-to-triangle records cannot repeat a triangle");
                return nullptr;
            }
            seen.push_back(triangle);
            const auto triangle_offset = static_cast<std::size_t>(triangle) * 3;
            if (context->proxy_triangles[triangle_offset] != vertex &&
                context->proxy_triangles[triangle_offset + 1] != vertex &&
                context->proxy_triangles[triangle_offset + 2] != vertex) {
                PyErr_SetString(PyExc_ValueError, "vertex-to-triangle record is not incident to its vertex");
                return nullptr;
            }
        }
    }

    auto next_vertex_ranges = copy_values<std::int32_t>(vertex_ranges);
    auto next_vertex_data = copy_values<std::int32_t>(vertex_data);
    auto next_triangle_ranges = copy_values<std::int32_t>(triangle_ranges);
    auto next_triangle_data = copy_values<std::int32_t>(triangle_data);
    auto next_bind_positions = copy_values<float>(bind_positions);
    auto next_bind_rotations = copy_values<float>(bind_rotations);
    auto next_adjustment_rotations = copy_values<float>(adjustment_rotations);
    auto next_transform_rotations = copy_values<float>(transform_rotations);
    context->bone_vertex_to_vertex_ranges.swap(next_vertex_ranges);
    context->bone_vertex_to_vertex_data.swap(next_vertex_data);
    context->bone_vertex_to_triangle_ranges.swap(next_triangle_ranges);
    context->bone_vertex_to_triangle_data.swap(next_triangle_data);
    context->bone_vertex_bind_pose_positions.swap(next_bind_positions);
    context->bone_vertex_bind_pose_rotations.swap(next_bind_rotations);
    context->bone_normal_adjustment_rotations.swap(next_adjustment_rotations);
    context->bone_vertex_to_transform_rotations.swap(next_transform_rotations);
    context->bone_static_ready = true;
    ++context->bone_static_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_distance_static(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_distance_static expects 4 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->proxy_static_ready || !context->baseline_static_ready) {
        PyErr_SetString(PyExc_RuntimeError, "Distance static requires proxy and baseline static");
        return nullptr;
    }
    Buffer ranges, targets, rests;
    if (!ranges.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "distance_ranges") ||
        !targets.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "distance_targets") ||
        !rests.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "distance_rest_signed")) {
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->vertex_count);
    Py_ssize_t range_count = 0;
    if (!expect_int32_pair_array(ranges, "distance_ranges", &range_count) ||
        range_count != count ||
        !expect_int32_scalar_array(targets, "distance_targets") ||
        !expect_float32(rests, "distance_rest_signed") ||
        !expect_1d_array(rests, "distance_rest_signed", targets.view.shape[0]) ||
        !validate_dense_ranges(ranges, targets.view.shape[0], "distance_ranges") ||
        !validate_indices(targets, context->vertex_count, "distance_targets") ||
        !finite_floats(rests, "distance_rest_signed")) {
        if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "distance static shape mismatch");
        return nullptr;
    }
    const auto* range_values = static_cast<const std::int32_t*>(ranges.view.buf);
    for (Py_ssize_t row = 0; row < count; ++row) {
        if (range_values[row * 2] > 1048575 || range_values[row * 2 + 1] > 4095) {
            PyErr_SetString(PyExc_ValueError, "distance range exceeds MC2 packed source limits");
            return nullptr;
        }
    }
    const auto* rest_values = static_cast<const float*>(rests.view.buf);
    for (Py_ssize_t index = 0; index < rests.view.shape[0]; ++index) {
        if (rest_values[index] == 0.0f && std::signbit(rest_values[index])) {
            PyErr_SetString(PyExc_ValueError, "distance zero rest must use +0.0");
            return nullptr;
        }
    }
    auto next_ranges = copy_values<std::int32_t>(ranges);
    auto next_targets = copy_values<std::int32_t>(targets);
    auto next_rests = copy_values<float>(rests);
    context->distance_ranges.swap(next_ranges);
    context->distance_targets.swap(next_targets);
    context->distance_rest_signed.swap(next_rests);
    context->distance_static_ready = true;
    ++context->distance_static_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_bending_static(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_bending_static expects 4 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->proxy_static_ready) {
        PyErr_SetString(PyExc_RuntimeError, "Bending static requires proxy static");
        return nullptr;
    }
    Buffer quads, rests, markers;
    if (!quads.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "bending_quads") ||
        !rests.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "bending_rest_angle_or_volume") ||
        !markers.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "bending_sign_or_volume")) {
        return nullptr;
    }
    Py_ssize_t record_count = 0;
    if (!expect_int32_quad_array(quads, "bending_quads", &record_count) ||
        !expect_float32(rests, "bending_rest_angle_or_volume") ||
        !expect_1d_array(rests, "bending_rest_angle_or_volume", record_count) ||
        !expect_int8_scalar_array(markers, "bending_sign_or_volume") ||
        markers.view.shape[0] != record_count ||
        !validate_indices(quads, context->vertex_count, "bending_quads") ||
        !finite_floats(rests, "bending_rest_angle_or_volume")) {
        if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "bending static shape mismatch");
        return nullptr;
    }
    const auto* quad_values = static_cast<const std::int32_t*>(quads.view.buf);
    const auto* marker_values = static_cast<const std::int8_t*>(markers.view.buf);
    for (Py_ssize_t row = 0; row < record_count; ++row) {
        const auto* value = quad_values + row * 4;
        if (value[0] == value[1] || value[0] == value[2] || value[0] == value[3] ||
            value[1] == value[2] || value[1] == value[3] || value[2] == value[3]) {
            PyErr_SetString(PyExc_ValueError, "bending quad must contain four distinct roles");
            return nullptr;
        }
        if (marker_values[row] != -1 && marker_values[row] != 1 && marker_values[row] != 100) {
            PyErr_SetString(PyExc_ValueError, "bending marker must be -1, 1, or 100");
            return nullptr;
        }
    }
    auto next_quads = copy_values<std::int32_t>(quads);
    auto next_rests = copy_values<float>(rests);
    auto next_markers = copy_values<std::int8_t>(markers);
    context->bending_quads.swap(next_quads);
    context->bending_rest_angle_or_volume.swap(next_rests);
    context->bending_sign_or_volume.swap(next_markers);
    context->bending_static_ready = true;
    ++context->bending_static_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_center_static(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_center_static expects 4 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->proxy_static_ready) {
        PyErr_SetString(PyExc_RuntimeError, "Center static requires proxy static");
        return nullptr;
    }
    Buffer fixed_indices, local_center, local_gravity;
    if (!fixed_indices.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "center_fixed_indices") ||
        !local_center.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "center_local_position") ||
        !local_gravity.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "center_initial_local_gravity_direction")) {
        return nullptr;
    }
    if (!expect_int32_scalar_array(fixed_indices, "center_fixed_indices") ||
        !expect_float32(local_center, "center_local_position") ||
        !expect_1d_array(local_center, "center_local_position", 3) ||
        !expect_float32(local_gravity, "center_initial_local_gravity_direction") ||
        !expect_1d_array(local_gravity, "center_initial_local_gravity_direction", 3) ||
        !validate_indices(fixed_indices, context->vertex_count, "center_fixed_indices") ||
        !finite_floats(local_center, "center_local_position") ||
        !finite_floats(local_gravity, "center_initial_local_gravity_direction")) {
        return nullptr;
    }
    const auto fixed_count = fixed_indices.view.shape[0];
    const auto* fixed_values = static_cast<const std::int32_t*>(fixed_indices.view.buf);
    std::vector<bool> seen(static_cast<std::size_t>(context->vertex_count), false);
    float expected_center[3] = {0.0f, 0.0f, 0.0f};
    for (Py_ssize_t index = 0; index < fixed_count; ++index) {
        const auto vertex = static_cast<std::size_t>(fixed_values[index]);
        if (seen[vertex]) {
            PyErr_SetString(PyExc_ValueError, "center_fixed_indices must be unique");
            return nullptr;
        }
        if (is_move(context->proxy_attributes[vertex])) {
            PyErr_SetString(PyExc_ValueError, "center_fixed_indices cannot contain Move vertices");
            return nullptr;
        }
        seen[vertex] = true;
        for (std::size_t component = 0; component < 3; ++component) {
            expected_center[component] += context->proxy_local_positions[vertex * 3 + component];
        }
    }
    const auto* center_values = static_cast<const float*>(local_center.view.buf);
    if (fixed_count > 0) {
        for (float& value : expected_center) value /= static_cast<float>(fixed_count);
    }
    for (std::size_t component = 0; component < 3; ++component) {
        if (std::fabs(center_values[component] - expected_center[component]) > 1.0e-5f) {
            PyErr_SetString(PyExc_ValueError, "center_local_position does not match fixed vertex average");
            return nullptr;
        }
    }
    const auto* gravity_values = static_cast<const float*>(local_gravity.view.buf);
    const float gravity_length_squared =
        gravity_values[0] * gravity_values[0] +
        gravity_values[1] * gravity_values[1] +
        gravity_values[2] * gravity_values[2];
    if (std::fabs(gravity_length_squared - 1.0f) > 2.0e-5f) {
        PyErr_SetString(PyExc_ValueError, "center_initial_local_gravity_direction must be unit length");
        return nullptr;
    }
    auto next_fixed = copy_values<std::int32_t>(fixed_indices);
    auto next_center = copy_values<float>(local_center);
    auto next_gravity = copy_values<float>(local_gravity);
    context->center_fixed_indices.swap(next_fixed);
    context->center_local_position.swap(next_center);
    context->center_initial_local_gravity_direction.swap(next_gravity);
    context->center_static_ready = true;
    context->center_dynamic_ready = false;
    context->center_frame_ready = false;
    context->center_result_ready = false;
    ++context->center_static_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_center_dynamic(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 14) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_center_dynamic expects 14 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->center_static_ready || !context->parameters_ready) {
        PyErr_SetString(PyExc_RuntimeError, "Center dynamic requires Center static and parameters");
        return nullptr;
    }
    Buffer old_frame_position, frame_position, old_frame_rotation, frame_rotation;
    Buffer old_frame_scale, frame_scale, old_world_position, old_world_rotation;
    Buffer initial_scale, negative_scale_direction;
    if (!old_frame_position.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "center_old_frame_world_position") ||
        !frame_position.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "center_frame_world_position") ||
        !old_frame_rotation.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "center_old_frame_world_rotation") ||
        !frame_rotation.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "center_frame_world_rotation") ||
        !old_frame_scale.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "center_old_frame_world_scale") ||
        !frame_scale.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "center_frame_world_scale") ||
        !old_world_position.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "center_old_world_position") ||
        !old_world_rotation.get(PyTuple_GET_ITEM(args, 8), PyBUF_FORMAT | PyBUF_ND, "center_old_world_rotation") ||
        !initial_scale.get(PyTuple_GET_ITEM(args, 9), PyBUF_FORMAT | PyBUF_ND, "center_initial_scale") ||
        !negative_scale_direction.get(PyTuple_GET_ITEM(args, 10), PyBUF_FORMAT | PyBUF_ND, "center_negative_scale_direction")) {
        return nullptr;
    }
    Buffer* vectors3[] = {
        &old_frame_position, &frame_position, &old_frame_scale, &frame_scale,
        &old_world_position, &initial_scale, &negative_scale_direction,
    };
    const char* vector3_names[] = {
        "center_old_frame_world_position", "center_frame_world_position",
        "center_old_frame_world_scale", "center_frame_world_scale",
        "center_old_world_position", "center_initial_scale",
        "center_negative_scale_direction",
    };
    for (std::size_t index = 0; index < 7; ++index) {
        if (!expect_float32(*vectors3[index], vector3_names[index]) ||
            !expect_1d_array(*vectors3[index], vector3_names[index], 3) ||
            !finite_floats(*vectors3[index], vector3_names[index])) {
            return nullptr;
        }
    }
    Buffer* quaternions[] = {&old_frame_rotation, &frame_rotation, &old_world_rotation};
    const char* quaternion_names[] = {
        "center_old_frame_world_rotation", "center_frame_world_rotation",
        "center_old_world_rotation",
    };
    for (std::size_t index = 0; index < 3; ++index) {
        if (!expect_float32(*quaternions[index], quaternion_names[index]) ||
            !expect_1d_array(*quaternions[index], quaternion_names[index], 4) ||
            !finite_floats(*quaternions[index], quaternion_names[index])) {
            return nullptr;
        }
        const auto* values = static_cast<const float*>(quaternions[index]->view.buf);
        float length_squared = 0.0f;
        for (std::size_t component = 0; component < 4; ++component) {
            length_squared += values[component] * values[component];
        }
        if (std::fabs(length_squared - 1.0f) > 2.0e-5f) {
            PyErr_Format(PyExc_ValueError, "%s must contain a unit quaternion", quaternion_names[index]);
            return nullptr;
        }
    }
    const double distance_weight = as_double(PyTuple_GET_ITEM(args, 11), "center_distance_weight");
    const double frame_interpolation = as_double(
        PyTuple_GET_ITEM(args, 12), "center_frame_interpolation"
    );
    const double velocity_weight = as_double(
        PyTuple_GET_ITEM(args, 13), "center_velocity_weight"
    );
    if (PyErr_Occurred()) return nullptr;
    if (!std::isfinite(distance_weight) || distance_weight < 0.0 || distance_weight > 1.0 ||
        !std::isfinite(frame_interpolation) || frame_interpolation < 0.0 || frame_interpolation > 1.0 ||
        !std::isfinite(velocity_weight) || velocity_weight < 0.0 || velocity_weight > 1.0) {
        PyErr_SetString(PyExc_ValueError, "Center dynamic weights must be in 0..1");
        return nullptr;
    }
    const auto* initial_scale_values = static_cast<const float*>(initial_scale.view.buf);
    const auto* negative_values = static_cast<const float*>(negative_scale_direction.view.buf);
    for (std::size_t component = 0; component < 3; ++component) {
        if (std::fabs(initial_scale_values[component]) <= kMc2Epsilon) {
            PyErr_SetString(PyExc_ValueError, "center_initial_scale cannot contain zero");
            return nullptr;
        }
        if (negative_values[component] != -1.0f && negative_values[component] != 1.0f) {
            PyErr_SetString(PyExc_ValueError, "center_negative_scale_direction must contain only -1 or 1");
            return nullptr;
        }
    }
    auto copy3 = [](const Buffer& source, std::array<float, 3>& target) {
        const auto* values = static_cast<const float*>(source.view.buf);
        std::copy(values, values + 3, target.begin());
    };
    auto copy4 = [](const Buffer& source, std::array<float, 4>& target) {
        const auto* values = static_cast<const float*>(source.view.buf);
        std::copy(values, values + 4, target.begin());
    };
    copy3(old_frame_position, context->center_old_frame_world_position);
    copy3(frame_position, context->center_frame_world_position);
    copy4(old_frame_rotation, context->center_old_frame_world_rotation);
    copy4(frame_rotation, context->center_frame_world_rotation);
    copy3(old_frame_scale, context->center_old_frame_world_scale);
    copy3(frame_scale, context->center_frame_world_scale);
    copy3(old_world_position, context->center_old_world_position);
    copy4(old_world_rotation, context->center_old_world_rotation);
    copy3(initial_scale, context->center_initial_scale);
    copy3(negative_scale_direction, context->center_negative_scale_direction);
    context->center_distance_weight = static_cast<float>(distance_weight);
    context->frame_interpolation = static_cast<float>(frame_interpolation);
    context->velocity_weight = static_cast<float>(velocity_weight);
    context->center_dynamic_ready = true;
    context->center_frame_ready = true;
    context->center_result_ready = false;
    ++context->center_dynamic_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_step_interpolation(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_update_step_interpolation expects 2 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->center_frame_ready) {
        PyErr_SetString(
            PyExc_RuntimeError,
            "Step interpolation requires a complete Center frame update"
        );
        return nullptr;
    }
    const double frame_interpolation = as_double(
        PyTuple_GET_ITEM(args, 1), "frame_interpolation"
    );
    if (PyErr_Occurred()) return nullptr;
    if (!std::isfinite(frame_interpolation) ||
        frame_interpolation < 0.0 || frame_interpolation > 1.0) {
        PyErr_SetString(PyExc_ValueError, "frame_interpolation must be in 0..1");
        return nullptr;
    }
    context->frame_interpolation = static_cast<float>(frame_interpolation);
    context->center_dynamic_ready = true;
    context->center_result_ready = false;
    ++context->step_interpolation_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_team_options(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_team_options expects 2 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const double animation_pose_ratio = as_double(
        PyTuple_GET_ITEM(args, 1), "animation_pose_ratio"
    );
    if (PyErr_Occurred()) return nullptr;
    if (!std::isfinite(animation_pose_ratio) ||
        animation_pose_ratio < 0.0 || animation_pose_ratio > 1.0) {
        PyErr_SetString(PyExc_ValueError, "animation_pose_ratio must be in 0..1");
        return nullptr;
    }
    context->animation_pose_ratio = static_cast<float>(animation_pose_ratio);
    ++context->team_options_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_apply_center_frame_shift(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_apply_center_frame_shift expects 4 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto count = static_cast<std::size_t>(context->vertex_count);
    if (!context->initialized || context->state_positions.size() != count * 3 ||
        context->state_rotations.size() != count * 4 ||
        context->state_velocities.size() != count * 3 ||
        context->velocity_reference_positions.size() != count * 3) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 particle state is not initialized for Center frame shift");
        return nullptr;
    }
    Buffer pivot, shift_vector, shift_rotation;
    if (!pivot.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "center_shift_pivot") ||
        !shift_vector.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "center_shift_vector") ||
        !shift_rotation.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "center_shift_rotation")) {
        return nullptr;
    }
    if (!expect_float32(pivot, "center_shift_pivot") ||
        !expect_1d_array(pivot, "center_shift_pivot", 3) ||
        !finite_floats(pivot, "center_shift_pivot") ||
        !expect_float32(shift_vector, "center_shift_vector") ||
        !expect_1d_array(shift_vector, "center_shift_vector", 3) ||
        !finite_floats(shift_vector, "center_shift_vector") ||
        !expect_float32(shift_rotation, "center_shift_rotation") ||
        !expect_1d_array(shift_rotation, "center_shift_rotation", 4) ||
        !finite_floats(shift_rotation, "center_shift_rotation")) {
        return nullptr;
    }
    const auto* rotation = static_cast<const float*>(shift_rotation.view.buf);
    float rotation_length_squared = 0.0f;
    for (std::size_t component = 0; component < 4; ++component) {
        rotation_length_squared += rotation[component] * rotation[component];
    }
    if (std::fabs(rotation_length_squared - 1.0f) > 2.0e-5f) {
        PyErr_SetString(PyExc_ValueError, "center_shift_rotation must contain a unit quaternion");
        return nullptr;
    }
    const auto* pivot_values = static_cast<const float*>(pivot.view.buf);
    const auto* shift_values = static_cast<const float*>(shift_vector.view.buf);
    const std::array<float, 4> shift_quaternion {
        rotation[0], rotation[1], rotation[2], rotation[3]
    };
    for (std::size_t vertex = 0; vertex < count; ++vertex) {
        const auto offset = vertex * 3;
        const auto rotation_offset = vertex * 4;
        float local_position[3] {
            context->state_positions[offset + 0] - pivot_values[0],
            context->state_positions[offset + 1] - pivot_values[1],
            context->state_positions[offset + 2] - pivot_values[2],
        };
        float rotated_position[3] {};
        rotate_vector_xyzw(rotation, local_position, rotated_position);
        for (std::size_t component = 0; component < 3; ++component) {
            context->state_positions[offset + component] =
                pivot_values[component] + rotated_position[component] + shift_values[component];
        }
        float local_reference[3] {
            context->velocity_reference_positions[offset + 0] - pivot_values[0],
            context->velocity_reference_positions[offset + 1] - pivot_values[1],
            context->velocity_reference_positions[offset + 2] - pivot_values[2],
        };
        float rotated_reference[3] {};
        rotate_vector_xyzw(rotation, local_reference, rotated_reference);
        for (std::size_t component = 0; component < 3; ++component) {
            context->velocity_reference_positions[offset + component] =
                pivot_values[component] + rotated_reference[component] + shift_values[component];
        }
        float rotated_velocity[3] {};
        rotate_vector_xyzw(
            rotation,
            context->state_velocities.data() + offset,
            rotated_velocity
        );
        std::copy_n(rotated_velocity, 3, context->state_velocities.data() + offset);
        const std::array<float, 4> state_rotation {
            context->state_rotations[rotation_offset + 0],
            context->state_rotations[rotation_offset + 1],
            context->state_rotations[rotation_offset + 2],
            context->state_rotations[rotation_offset + 3],
        };
        auto shifted_rotation = quaternion_multiply(shift_quaternion, state_rotation);
        normalize_quaternion(shifted_rotation);
        std::copy(
            shifted_rotation.begin(), shifted_rotation.end(),
            context->state_rotations.begin() + static_cast<std::ptrdiff_t>(rotation_offset)
        );
    }
    ++context->center_frame_shift_count;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_apply_center_negative_scale_teleport(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_apply_center_negative_scale_teleport expects 2 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto count = static_cast<std::size_t>(context->vertex_count);
    if (!context->initialized || context->state_positions.size() != count * 3 ||
        context->state_rotations.size() != count * 4 ||
        context->state_velocities.size() != count * 3 ||
        context->velocity_reference_positions.size() != count * 3) {
        PyErr_SetString(
            PyExc_RuntimeError,
            "MC2 V0 particle state is not initialized for negative-scale teleport"
        );
        return nullptr;
    }
    Buffer matrix;
    if (!matrix.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND,
            "center_negative_scale_matrix"
        ) ||
        !expect_float32(matrix, "center_negative_scale_matrix") ||
        !expect_2d(matrix, "center_negative_scale_matrix", 4, 4) ||
        !finite_floats(matrix, "center_negative_scale_matrix")) {
        return nullptr;
    }
    const auto* values = static_cast<const float*>(matrix.view.buf);
    for (std::size_t vertex = 0; vertex < count; ++vertex) {
        const auto offset = vertex * 3;
        const auto rotation_offset = vertex * 4;
        const Vec3 position {
            context->state_positions[offset + 0],
            context->state_positions[offset + 1],
            context->state_positions[offset + 2],
        };
        const Vec3 reference {
            context->velocity_reference_positions[offset + 0],
            context->velocity_reference_positions[offset + 1],
            context->velocity_reference_positions[offset + 2],
        };
        const Vec3 velocity {
            context->state_velocities[offset + 0],
            context->state_velocities[offset + 1],
            context->state_velocities[offset + 2],
        };
        const Vec3 transformed_position = transform_point_matrix(values, position);
        const Vec3 transformed_reference = transform_point_matrix(values, reference);
        const Vec3 transformed_velocity = transform_vector_matrix(values, velocity);
        const std::array<float, 4> rotation {
            context->state_rotations[rotation_offset + 0],
            context->state_rotations[rotation_offset + 1],
            context->state_rotations[rotation_offset + 2],
            context->state_rotations[rotation_offset + 3],
        };
        const auto transformed_rotation = transform_rotation_matrix(values, rotation);
        const Vec3 vectors[] = {
            transformed_position, transformed_reference, transformed_velocity
        };
        float* outputs[] = {
            context->state_positions.data() + offset,
            context->velocity_reference_positions.data() + offset,
            context->state_velocities.data() + offset,
        };
        for (std::size_t index = 0; index < 3; ++index) {
            outputs[index][0] = vectors[index].x;
            outputs[index][1] = vectors[index].y;
            outputs[index][2] = vectors[index].z;
        }
        std::copy(
            transformed_rotation.begin(), transformed_rotation.end(),
            context->state_rotations.begin() + static_cast<std::ptrdiff_t>(rotation_offset)
        );
    }
    ++context->center_negative_scale_teleport_count;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_parameters(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_parameters expects 4 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    Buffer floats, ints, curves;
    if (!floats.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "float_values") ||
        !ints.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "int_values") ||
        !curves.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "curve_values")) {
        return nullptr;
    }
    if (!expect_float32(floats, "float_values") ||
        !expect_1d_array(floats, "float_values", kFloatCount) ||
        !expect_int32(ints, "int_values") ||
        !expect_1d_array(ints, "int_values", kIntCount) ||
        !validate_parameter_ints(ints) ||
        !expect_float32(curves, "curve_values") ||
        !expect_2d(curves, "curve_values", kCurveRows, kCurveColumns) ||
        !finite_floats(floats, "float_values") ||
        !finite_floats(curves, "curve_values")) {
        return nullptr;
    }
    auto next_floats = copy_values<float>(floats);
    auto next_ints = copy_values<std::int32_t>(ints);
    auto next_curves = copy_values<float>(curves);
    context->float_values.swap(next_floats);
    context->int_values.swap(next_ints);
    context->curve_values.swap(next_curves);
    context->parameters_ready = true;
    ++context->parameter_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_dynamic(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 10) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_dynamic expects 10 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->parameters_ready) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 parameters have not been uploaded");
        return nullptr;
    }
    const long frame = as_long(PyTuple_GET_ITEM(args, 1), "frame");
    const long generation = as_long(PyTuple_GET_ITEM(args, 2), "generation");
    const double velocity_weight = as_double(PyTuple_GET_ITEM(args, 5), "velocity_weight");
    const double gravity_ratio = as_double(PyTuple_GET_ITEM(args, 6), "gravity_ratio");
    const double scale_ratio = as_double(PyTuple_GET_ITEM(args, 7), "scale_ratio");
    const double negative_scale_sign = as_double(
        PyTuple_GET_ITEM(args, 8), "negative_scale_sign"
    );
    const double frame_interpolation = as_double(
        PyTuple_GET_ITEM(args, 9), "frame_interpolation"
    );
    if (PyErr_Occurred()) return nullptr;
    if (!std::isfinite(velocity_weight) || velocity_weight < 0.0 || velocity_weight > 1.0 ||
        !std::isfinite(gravity_ratio) || gravity_ratio < 0.0 || gravity_ratio > 1.0 ||
        !std::isfinite(scale_ratio) || scale_ratio <= 0.0 ||
        (negative_scale_sign != -1.0 && negative_scale_sign != 1.0) ||
        !std::isfinite(frame_interpolation) ||
        frame_interpolation < 0.0 || frame_interpolation > 1.0) {
        PyErr_SetString(PyExc_ValueError, "MC2 dynamic scalar is out of range");
        return nullptr;
    }
    Buffer positions, rotations;
    if (!positions.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "world_positions") ||
        !rotations.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "world_rotations_xyzw")) {
        return nullptr;
    }
    const Py_ssize_t count = static_cast<Py_ssize_t>(context->vertex_count);
    if (!expect_float32(positions, "world_positions") ||
        !expect_2d(positions, "world_positions", count, 3) ||
        !expect_float32(rotations, "world_rotations_xyzw") ||
        !expect_2d(rotations, "world_rotations_xyzw", count, 4) ||
        !finite_floats(positions, "world_positions") ||
        !finite_floats(rotations, "world_rotations_xyzw") ||
        !validate_quaternions(rotations, "world_rotations_xyzw")) {
        return nullptr;
    }
    auto next_positions = copy_values<float>(positions);
    auto next_rotations = copy_values<float>(rotations);
    if (context->dynamic_ready) {
        context->old_dynamic_positions = context->dynamic_positions;
        context->old_dynamic_rotations = context->dynamic_rotations;
    } else {
        context->old_dynamic_positions = next_positions;
        context->old_dynamic_rotations = next_rotations;
    }
    context->dynamic_positions.swap(next_positions);
    context->dynamic_rotations.swap(next_rotations);
    context->frame = frame;
    context->generation = generation;
    context->velocity_weight = static_cast<float>(velocity_weight);
    context->gravity_ratio = static_cast<float>(gravity_ratio);
    context->scale_ratio = static_cast<float>(scale_ratio);
    context->negative_scale_sign = static_cast<float>(negative_scale_sign);
    context->frame_interpolation = static_cast<float>(frame_interpolation);
    context->center_dynamic_ready = false;
    context->center_frame_ready = false;
    context->center_result_ready = false;
    context->dynamic_ready = true;
    context->bone_output_positions.clear();
    context->bone_output_rotations.clear();
    ++context->dynamic_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_reset(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 1) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_reset expects 1 argument");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->dynamic_ready) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 dynamic frame has not been uploaded");
        return nullptr;
    }
    context->state_positions = context->dynamic_positions;
    context->state_rotations = context->dynamic_rotations;
    context->old_dynamic_positions = context->dynamic_positions;
    context->old_dynamic_rotations = context->dynamic_rotations;
    context->state_velocities.assign(
        static_cast<std::size_t>(context->vertex_count) * 3,
        0.0f
    );
    context->velocity_reference_positions = context->dynamic_positions;
    context->step_basic_positions = context->dynamic_positions;
    context->step_basic_rotations = context->dynamic_rotations;
    context->center_dynamic_ready = false;
    context->center_frame_ready = false;
    context->center_result_ready = false;
    context->bone_output_positions.clear();
    context->bone_output_rotations.clear();
    context->initialized = true;
    ++context->reset_count;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_step(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_step expects 4 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const double dt = as_double(PyTuple_GET_ITEM(args, 1), "dt");
    const double simulation_power_y = as_double(
        PyTuple_GET_ITEM(args, 2),
        "simulation_power_y"
    );
    const double simulation_power_z = as_double(
        PyTuple_GET_ITEM(args, 3),
        "simulation_power_z"
    );
    if (PyErr_Occurred()) return nullptr;
    if (!std::isfinite(dt) || dt < 0.0 ||
        !std::isfinite(simulation_power_y) || simulation_power_y < 0.0 ||
        !std::isfinite(simulation_power_z) || simulation_power_z < 0.0) {
        PyErr_SetString(PyExc_ValueError, "dt and simulation powers must be finite and non-negative");
        return nullptr;
    }
    if (!context->parameters_ready || !context->dynamic_ready || !context->initialized) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 context is not ready to step");
        return nullptr;
    }
    if (dt <= kMc2Epsilon) Py_RETURN_NONE;
    const bool center_step_active = context->center_dynamic_ready;
    if (center_step_active && !evaluate_center_step(*context, static_cast<float>(dt))) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 Center state is incomplete");
        return nullptr;
    }
    if (context->proxy_static_ready) {
        if (!predict_particles(
                *context,
                static_cast<float>(dt),
                static_cast<float>(simulation_power_z),
                center_step_active)) {
            PyErr_SetString(PyExc_RuntimeError, "MC2 V0 particle state is incomplete");
            return nullptr;
        }
        solve_distance_once(*context, static_cast<float>(simulation_power_y));
        solve_bending_once(*context, static_cast<float>(simulation_power_y));
        solve_distance_once(*context, static_cast<float>(simulation_power_y));
        commit_particle_velocities(*context, static_cast<float>(dt));
    }
    if (center_step_active) {
        context->center_old_world_position = context->center_now_world_position;
        context->center_old_world_rotation = context->center_now_world_rotation;
    }
    context->bone_output_positions.clear();
    context->bone_output_rotations.clear();
    ++context->step_count;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 3) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_read expects 3 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->initialized) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 context has not been reset");
        return nullptr;
    }
    Buffer positions, rotations;
    if (!positions.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE, "out_positions") ||
        !rotations.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE, "out_rotations")) {
        return nullptr;
    }
    const Py_ssize_t count = static_cast<Py_ssize_t>(context->vertex_count);
    if (!expect_float32(positions, "out_positions") ||
        !expect_2d(positions, "out_positions", count, 3) ||
        !expect_float32(rotations, "out_rotations") ||
        !expect_2d(rotations, "out_rotations", count, 4)) {
        return nullptr;
    }
    std::memcpy(positions.view.buf,
                context->state_positions.data(),
                context->state_positions.size() * sizeof(float));
    std::memcpy(rotations.view.buf,
                context->state_rotations.data(),
                context->state_rotations.size() * sizeof(float));
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_bone_output(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 3) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_read_bone_output expects 3 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!build_bone_line_output(*context)) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 Bone Line output state is incomplete");
        return nullptr;
    }
    Buffer positions, rotations;
    if (!positions.get(
            PyTuple_GET_ITEM(args, 1),
            PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_bone_positions") ||
        !rotations.get(
            PyTuple_GET_ITEM(args, 2),
            PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_bone_rotations")) {
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->vertex_count);
    if (!expect_float32(positions, "out_bone_positions") ||
        !expect_2d(positions, "out_bone_positions", count, 3) ||
        !expect_float32(rotations, "out_bone_rotations") ||
        !expect_2d(rotations, "out_bone_rotations", count, 4)) {
        return nullptr;
    }
    std::memcpy(
        positions.view.buf,
        context->bone_output_positions.data(),
        context->bone_output_positions.size() * sizeof(float)
    );
    std::memcpy(
        rotations.view.buf,
        context->bone_output_rotations.data(),
        context->bone_output_rotations.size() * sizeof(float)
    );
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_step_basic(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 3) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_read_step_basic expects 3 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto count = static_cast<std::size_t>(context->vertex_count);
    if (context->step_basic_positions.size() != count * 3 ||
        context->step_basic_rotations.size() != count * 4) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 step-basic pose is not ready");
        return nullptr;
    }
    Buffer positions, rotations;
    if (!positions.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_step_basic_positions"
        ) ||
        !rotations.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_step_basic_rotations"
        )) {
        return nullptr;
    }
    const Py_ssize_t vertex_count = static_cast<Py_ssize_t>(context->vertex_count);
    if (!expect_float32(positions, "out_step_basic_positions") ||
        !expect_2d(positions, "out_step_basic_positions", vertex_count, 3) ||
        !expect_float32(rotations, "out_step_basic_rotations") ||
        !expect_2d(rotations, "out_step_basic_rotations", vertex_count, 4)) {
        return nullptr;
    }
    std::memcpy(
        positions.view.buf,
        context->step_basic_positions.data(),
        context->step_basic_positions.size() * sizeof(float)
    );
    std::memcpy(
        rotations.view.buf,
        context->step_basic_rotations.data(),
        context->step_basic_rotations.size() * sizeof(float)
    );
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_center_step(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 8) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_read_center_step expects 8 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->center_result_ready) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 Center step result is not ready");
        return nullptr;
    }
    Buffer now_position, now_rotation, step_vector, step_rotation;
    Buffer inertia_vector, inertia_rotation, rotation_axis;
    Buffer* outputs[] = {
        &now_position, &now_rotation, &step_vector, &step_rotation,
        &inertia_vector, &inertia_rotation, &rotation_axis,
    };
    const char* names[] = {
        "out_center_now_world_position", "out_center_now_world_rotation",
        "out_center_step_vector", "out_center_step_rotation",
        "out_center_inertia_vector", "out_center_inertia_rotation",
        "out_center_rotation_axis",
    };
    const Py_ssize_t widths[] = {3, 4, 3, 4, 3, 4, 3};
    for (std::size_t index = 0; index < 7; ++index) {
        if (!outputs[index]->get(
                PyTuple_GET_ITEM(args, static_cast<Py_ssize_t>(index + 1)),
                PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
                names[index]) ||
            !expect_float32(*outputs[index], names[index]) ||
            !expect_1d_array(*outputs[index], names[index], widths[index])) {
            return nullptr;
        }
    }
    const float* values[] = {
        context->center_now_world_position.data(),
        context->center_now_world_rotation.data(),
        context->center_step_vector.data(),
        context->center_step_rotation.data(),
        context->center_inertia_vector.data(),
        context->center_inertia_rotation.data(),
        context->center_rotation_axis.data(),
    };
    for (std::size_t index = 0; index < 7; ++index) {
        std::memcpy(
            outputs[index]->view.buf,
            values[index],
            static_cast<std::size_t>(widths[index]) * sizeof(float)
        );
    }
    PyObject* result = PyDict_New();
    if (result == nullptr) return nullptr;
    if (!dict_float(result, "frame_interpolation", context->frame_interpolation) ||
        !dict_float(result, "step_move_inertia_ratio", context->center_step_move_inertia_ratio) ||
        !dict_float(result, "step_rotation_inertia_ratio", context->center_step_rotation_inertia_ratio) ||
        !dict_float(result, "angular_velocity", context->center_angular_velocity) ||
        !dict_float(result, "scale_ratio", context->scale_ratio) ||
        !dict_float(result, "gravity_dot", context->center_gravity_dot) ||
        !dict_float(result, "gravity_ratio", context->gravity_ratio) ||
        !dict_float(result, "velocity_weight", context->velocity_weight) ||
        !dict_float(result, "blend_weight", context->center_blend_weight)) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}

PyObject* mc2_context_v0_free(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 1) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_free expects 1 argument");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (context == nullptr) return nullptr;
    release_resources(*context);
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_stats(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 0) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_stats expects no arguments");
        return nullptr;
    }
    PyObject* result = PyDict_New();
    if (result == nullptr) return nullptr;
    if (!dict_i64(result, "created", g_created.load()) ||
        !dict_i64(result, "released", g_released.load()) ||
        !dict_i64(result, "live", g_live.load())) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}

}  // namespace hotools
