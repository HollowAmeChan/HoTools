#include "mc2_context_v0.hpp"

#include "mc2_context_internal.hpp"
#include "mc2_kernels.hpp"
#include "mc2_static_build.hpp"
#include "python_buffer_utils.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

namespace hotools {
namespace {

using namespace py;
using namespace mc2_internal;

constexpr const char* kCapsuleName = "hotools_native.MC2ContextV0";
constexpr const char* kInteractionCapsuleName = "hotools_native.MC2InteractionV0";
constexpr long kSchemaVersion = 0;
constexpr Py_ssize_t kFloatCount = 47;
constexpr Py_ssize_t kIntCount = 11;
constexpr Py_ssize_t kCurveRows = 9;
constexpr Py_ssize_t kCurveColumns = 16;
constexpr float kMc2Epsilon = 0.00000001f;
constexpr float kDistanceHorizontalStiffness = 0.5f;
constexpr float kDistanceFixedInverseMass = 1.0f / 50.0f;
constexpr Py_ssize_t kDistanceStiffnessCurve = 2;
constexpr Py_ssize_t kAngleRestorationCurve = 3;
constexpr Py_ssize_t kAngleLimitCurve = 4;
constexpr Py_ssize_t kMaxDistanceCurve = 5;
constexpr Py_ssize_t kBackstopDistanceCurve = 6;
constexpr Py_ssize_t kCollisionLimitDistanceCurve = 7;
constexpr Py_ssize_t kSelfCollisionThicknessCurve = 8;
constexpr Py_ssize_t kRadiusCurve = 1;
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
constexpr Py_ssize_t kTetherCompression = 24;
constexpr Py_ssize_t kTetherStretch = 25;
constexpr Py_ssize_t kAngleRestorationVelocityAttenuation = 28;
constexpr Py_ssize_t kAngleRestorationGravityFalloff = 29;
constexpr Py_ssize_t kAngleLimitStiffness = 30;
constexpr Py_ssize_t kBackstopRadius = 31;
constexpr Py_ssize_t kMotionStiffness = 32;
constexpr Py_ssize_t kCollisionDynamicFriction = 33;
constexpr Py_ssize_t kCollisionStaticFriction = 34;
constexpr Py_ssize_t kClothMass = 35;
constexpr Py_ssize_t kParticleSpeedLimit = 21;
constexpr Py_ssize_t kNormalAxis = 0;
constexpr Py_ssize_t kUseAngleRestoration = 4;
constexpr Py_ssize_t kUseAngleLimit = 5;
constexpr Py_ssize_t kUseMaxDistance = 6;
constexpr Py_ssize_t kUseBackstop = 7;
constexpr Py_ssize_t kCollisionMode = 8;
constexpr Py_ssize_t kSelfCollisionMode = 9;
constexpr Py_ssize_t kSelfCollisionSyncMode = 10;
constexpr float kFrictionMass = 3.0f;
constexpr std::uint32_t kSelfFix0 = 0x04000000u;
constexpr std::uint32_t kSelfAllFix = 0x20000000u;
constexpr std::uint32_t kSelfIgnore = 0x40000000u;
constexpr std::uint32_t kSelfIntersectMask = 0x00000007u;
constexpr std::int32_t kSelfIgnoreGrid = 1000000;
constexpr long kStaticChangeTopology = 1l;
constexpr long kStaticChangeGeometry = 2l;
constexpr long kStaticChangeSurface = 4l;
constexpr long kStaticChangeConfig = 8l;
constexpr long kStaticChangeAll = 15l;

std::atomic<std::int64_t> g_created {0};
std::atomic<std::int64_t> g_released {0};
std::atomic<std::int64_t> g_live {0};

Mc2ContextV0* context_from(PyObject* object) {
    return static_cast<Mc2ContextV0*>(PyCapsule_GetPointer(object, kCapsuleName));
}

Mc2InteractionV0* interaction_from(PyObject* object) {
    return static_cast<Mc2InteractionV0*>(
        PyCapsule_GetPointer(object, kInteractionCapsuleName)
    );
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
    context.particle_friction.clear();
    context.particle_static_friction.clear();
    context.particle_collision_normals.clear();
    context.particle_real_velocities.clear();
    context.animated_base_positions.clear();
    context.animated_base_rotations.clear();
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
    context.self_primitive_flags.clear();
    context.self_particle_indices.clear();
    context.self_primitive_depths.clear();
    context.self_primitive_inverse_masses.clear();
    context.self_primitive_aabb_min.clear();
    context.self_primitive_aabb_max.clear();
    context.self_primitive_thickness.clear();
    context.self_primitive_owner_indices.clear();
    context.self_owner_primary_group_bits.clear();
    context.self_owner_collided_by_groups.clear();
    context.self_primitive_grids.clear();
    context.self_grid_hashes.clear();
    context.self_grid_starts.clear();
    context.self_grid_counts.clear();
    context.self_contact_candidates.clear();
    context.self_contact_primitive_indices.clear();
    context.self_contact_types.clear();
    context.self_contact_enabled.clear();
    context.self_contact_thickness.clear();
    context.self_contact_s.clear();
    context.self_contact_t.clear();
    context.self_contact_normals.clear();
    context.self_point_primitive_count = 0;
    context.self_edge_primitive_count = 0;
    context.self_triangle_primitive_count = 0;
    context.self_contact_keys.clear();
    context.self_intersect_records.clear();
    context.self_particle_intersect_flags.clear();
    context.collided_by_groups = 0;
    context.collider_types.clear();
    context.collider_group_bits.clear();
    context.collider_centers.clear();
    context.collider_segment_a.clear();
    context.collider_segment_b.clear();
    context.collider_old_centers.clear();
    context.collider_old_segment_a.clear();
    context.collider_old_segment_b.clear();
    context.collider_radii.clear();
    context.center_fixed_indices.clear();
    context.center_local_position.clear();
    context.center_initial_local_gravity_direction.clear();
    context.static_topology_fingerprint.clear();
    context.static_geometry_fingerprint.clear();
    context.static_surface_fingerprint.clear();
    context.static_config_fingerprint.clear();
    context.static_overall_fingerprint.clear();
    context.static_fingerprint_ready = false;
    context.parameters_ready = false;
    context.proxy_static_ready = false;
    context.baseline_static_ready = false;
    context.bone_static_ready = false;
    context.distance_static_ready = false;
    context.bending_static_ready = false;
    context.self_collision_static_ready = false;
    context.self_primitive_dynamic_ready = false;
    context.self_grid_dynamic_ready = false;
    context.self_candidate_ready = false;
    context.self_contact_ready = false;
    context.self_intersect_detection_ready = false;
    context.self_intersect_flags_ready = false;
    context.self_point_grid_count = 0;
    context.self_edge_grid_count = 0;
    context.self_triangle_grid_count = 0;
    context.self_max_primitive_size = 0.0f;
    context.self_grid_size = 0.0f;
    context.tether_enabled = false;
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

void release_interaction(Mc2InteractionV0& interaction) {
    if (interaction.released) return;
    interaction.participants.clear();
    interaction.scope_identity.clear();
    interaction.old_positions.clear();
    interaction.aggregate = Mc2ContextV0 {};
    interaction.aggregate.released = true;
    interaction.released = true;
}

void destroy_interaction(PyObject* capsule) {
    auto* interaction = interaction_from(capsule);
    if (interaction == nullptr) {
        PyErr_Clear();
        return;
    }
    release_interaction(*interaction);
    delete interaction;
}

bool ensure_live(Mc2InteractionV0* interaction) {
    if (interaction == nullptr) return false;
    if (interaction->released) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 interaction V0 has been released");
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

bool read_static_fingerprints(
    PyObject* args,
    std::array<std::string, 5>& fingerprints
) {
    const char* names[] = {"topology", "geometry", "surface", "config", "overall"};
    for (Py_ssize_t index = 0; index < 5; ++index) {
        Py_ssize_t size = 0;
        const char* value = PyUnicode_AsUTF8AndSize(
            PyTuple_GET_ITEM(args, index + 1),
            &size
        );
        if (value == nullptr) return false;
        if (size != 32) {
            PyErr_Format(PyExc_ValueError, "%s fingerprint must be 32 lowercase hex characters", names[index]);
            return false;
        }
        for (Py_ssize_t character = 0; character < size; ++character) {
            const char current = value[character];
            if (!((current >= '0' && current <= '9') || (current >= 'a' && current <= 'f'))) {
                PyErr_Format(PyExc_ValueError, "%s fingerprint must be 32 lowercase hex characters", names[index]);
                return false;
            }
        }
        fingerprints[static_cast<std::size_t>(index)].assign(
            value,
            static_cast<std::size_t>(size)
        );
    }
    return true;
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

template <typename T>
std::vector<T>* validated_owned_values(
    PyObject* capsule,
    const char* capsule_name,
    const Buffer& buffer
) {
    if (!PyCapsule_IsValid(capsule, capsule_name)) {
        PyErr_SetString(PyExc_ValueError, "MC2 static owner capsule is invalid");
        return nullptr;
    }
    auto* values = static_cast<std::vector<T>*>(
        PyCapsule_GetPointer(capsule, capsule_name)
    );
    if (values == nullptr) return nullptr;
    const auto count = static_cast<std::size_t>(
        buffer.view.len / static_cast<Py_ssize_t>(sizeof(T))
    );
    if (values->size() != count ||
        (count > 0 && values->data() != buffer.view.buf)) {
        PyErr_SetString(PyExc_ValueError, "MC2 static owner does not match its array");
        return nullptr;
    }
    return values;
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
    context.animated_base_positions.resize(count * 3);
    context.animated_base_rotations.resize(count * 4);
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
            context.animated_base_positions[offset + component] =
                context.old_dynamic_positions[offset + component] *
                    (1.0f - context.frame_interpolation) +
                context.dynamic_positions[offset + component] * context.frame_interpolation;
            context.step_basic_positions[offset + component] =
                context.animated_base_positions[offset + component];
        }
        slerp_xyzw(
            context.old_dynamic_rotations.data() + rotation_offset,
            context.dynamic_rotations.data() + rotation_offset,
            context.frame_interpolation,
            context.animated_base_rotations.data() + rotation_offset
        );
        std::copy_n(
            context.animated_base_rotations.data() + rotation_offset,
            4,
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

std::uint16_t float_to_half_bits(float value) {
    std::uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof(bits));
    const std::uint32_t sign = (bits >> 16u) & 0x8000u;
    const std::uint32_t exponent = (bits >> 23u) & 0xffu;
    const std::uint32_t mantissa = bits & 0x7fffffu;
    if (exponent == 0xffu) {
        return static_cast<std::uint16_t>(
            sign | 0x7c00u | (mantissa != 0u ? 0x0200u : 0u)
        );
    }
    const int half_exponent = static_cast<int>(exponent) - 127 + 15;
    if (half_exponent >= 31) return static_cast<std::uint16_t>(sign | 0x7c00u);
    if (half_exponent <= 0) {
        if (half_exponent < -10) return static_cast<std::uint16_t>(sign);
        const std::uint32_t full_mantissa = mantissa | 0x800000u;
        const int shift = 14 - half_exponent;
        std::uint32_t half_mantissa = full_mantissa >> shift;
        const std::uint32_t remainder_mask = (std::uint32_t {1} << shift) - 1u;
        const std::uint32_t remainder = full_mantissa & remainder_mask;
        const std::uint32_t halfway = std::uint32_t {1} << (shift - 1);
        if (remainder > halfway || (remainder == halfway && (half_mantissa & 1u) != 0u)) {
            ++half_mantissa;
        }
        return static_cast<std::uint16_t>(sign | half_mantissa);
    }
    std::uint32_t rounded_mantissa = mantissa >> 13u;
    const std::uint32_t remainder = mantissa & 0x1fffu;
    if (remainder > 0x1000u || (remainder == 0x1000u && (rounded_mantissa & 1u) != 0u)) {
        ++rounded_mantissa;
    }
    std::uint32_t rounded_exponent = static_cast<std::uint32_t>(half_exponent);
    if (rounded_mantissa == 0x0400u) {
        rounded_mantissa = 0;
        ++rounded_exponent;
        if (rounded_exponent >= 31u) return static_cast<std::uint16_t>(sign | 0x7c00u);
    }
    return static_cast<std::uint16_t>(
        sign | (rounded_exponent << 10u) | rounded_mantissa
    );
}

float half_bits_to_float(std::uint16_t value) {
    const std::uint32_t sign = static_cast<std::uint32_t>(value & 0x8000u) << 16u;
    std::uint32_t exponent = (value >> 10u) & 0x1fu;
    std::uint32_t mantissa = value & 0x03ffu;
    std::uint32_t bits = 0;
    if (exponent == 0u) {
        if (mantissa == 0u) {
            bits = sign;
        } else {
            int normal_exponent = -14;
            while ((mantissa & 0x0400u) == 0u) {
                mantissa <<= 1u;
                --normal_exponent;
            }
            mantissa &= 0x03ffu;
            bits = sign |
                (static_cast<std::uint32_t>(normal_exponent + 127) << 23u) |
                (mantissa << 13u);
        }
    } else if (exponent == 31u) {
        bits = sign | 0x7f800000u | (mantissa << 13u);
    } else {
        const auto float_exponent = static_cast<std::uint32_t>(
            static_cast<int>(exponent) - 15 + 127
        );
        bits = sign | (float_exponent << 23u) | (mantissa << 13u);
    }
    float result = 0.0f;
    std::memcpy(&result, &bits, sizeof(result));
    return result;
}

float quantize_half(float value) {
    return half_bits_to_float(float_to_half_bits(value));
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

bool apply_bone_triangle_output(
    Mc2ContextV0& context,
    const std::vector<float>& positions,
    std::vector<float>& work_rotations,
    bool count_bone_output = true
) {
    const auto vertex_count = static_cast<std::size_t>(context.vertex_count);
    const auto triangle_count = context.proxy_triangles.size() / 3;
    if (triangle_count == 0) return true;
    if (context.proxy_uvs.size() != vertex_count * 2 ||
        positions.size() != vertex_count * 3 ||
        work_rotations.size() != vertex_count * 4 ||
        context.bone_vertex_to_triangle_ranges.size() != vertex_count * 2 ||
        context.bone_vertex_to_triangle_data.size() % 2 != 0 ||
        context.bone_normal_adjustment_rotations.size() != vertex_count * 4) {
        return false;
    }

    std::vector<Vec3> triangle_normals(triangle_count);
    std::vector<Vec3> triangle_tangents(triangle_count);
    for (std::size_t triangle = 0; triangle < triangle_count; ++triangle) {
        const auto vertex0 = static_cast<std::size_t>(context.proxy_triangles[triangle * 3]);
        const auto vertex1 = static_cast<std::size_t>(context.proxy_triangles[triangle * 3 + 1]);
        const auto vertex2 = static_cast<std::size_t>(context.proxy_triangles[triangle * 3 + 2]);
        const Vec3 position0 = load_vector3(positions, vertex0);
        const Vec3 position1 = load_vector3(positions, vertex1);
        const Vec3 position2 = load_vector3(positions, vertex2);
        const Vec3 edge_ba = sub(position1, position0);
        const Vec3 edge_ca = sub(position2, position0);
        const Vec3 triangle_cross = cross(edge_ba, edge_ca);
        const float normal_length = length(triangle_cross);
        if (normal_length > kMc2Epsilon) {
            triangle_normals[triangle] = mul(triangle_cross, 1.0f / normal_length);
        }

        const float uv_ba_x = context.proxy_uvs[vertex1 * 2] -
            context.proxy_uvs[vertex0 * 2];
        const float uv_ba_y = context.proxy_uvs[vertex1 * 2 + 1] -
            context.proxy_uvs[vertex0 * 2 + 1];
        const float uv_ca_x = context.proxy_uvs[vertex2 * 2] -
            context.proxy_uvs[vertex0 * 2];
        const float uv_ca_y = context.proxy_uvs[vertex2 * 2 + 1] -
            context.proxy_uvs[vertex0 * 2 + 1];
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

    const auto record_count = context.bone_vertex_to_triangle_data.size() / 2;
    for (std::size_t vertex = 0; vertex < vertex_count; ++vertex) {
        const auto start = context.bone_vertex_to_triangle_ranges[vertex * 2];
        const auto count = context.bone_vertex_to_triangle_ranges[vertex * 2 + 1];
        if (start < 0 || count < 0 ||
            static_cast<std::size_t>(start + count) > record_count) {
            return false;
        }
        if (count == 0) continue;
        Vec3 normal {};
        Vec3 tangent {};
        for (std::int32_t offset = 0; offset < count; ++offset) {
            const auto record = static_cast<std::size_t>(start + offset);
            const auto flip = context.bone_vertex_to_triangle_data[record * 2];
            const auto triangle = context.bone_vertex_to_triangle_data[record * 2 + 1];
            if (triangle < 0 || static_cast<std::size_t>(triangle) >= triangle_count) {
                return false;
            }
            normal = add(
                normal,
                mul(triangle_normals[static_cast<std::size_t>(triangle)],
                    (flip & 0x01) == 0 ? 1.0f : -1.0f)
            );
            tangent = add(
                tangent,
                mul(triangle_tangents[static_cast<std::size_t>(triangle)],
                    (flip & 0x02) == 0 ? 1.0f : -1.0f)
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
        auto rotation = quaternion_multiply(
            quaternion_from_forward_up(binormal, normal),
            load_quaternion(context.bone_normal_adjustment_rotations, vertex)
        );
        store_quaternion(work_rotations, vertex, rotation);
    }
    if (count_bone_output) ++context.bone_triangle_output_count;
    return true;
}

bool build_bone_output(Mc2ContextV0& context) {
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

    if (!apply_bone_triangle_output(context, context.state_positions, work_rotations)) return false;

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
    const float friction = context.particle_friction.size() == static_cast<std::size_t>(context.vertex_count)
        ? context.particle_friction[vertex] : 0.0f;
    return 1.0f / (1.0f + friction * kFrictionMass + depth_offset * depth_offset * 5.0f);
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
    const float friction = context.particle_friction.size() == static_cast<std::size_t>(context.vertex_count)
        ? context.particle_friction[vertex] : 0.0f;
    return 1.0f / (1.0f + friction * kFrictionMass + depth_delta * depth_delta * 5.0f);
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

void solve_tether_once(Mc2ContextV0& context) {
    if (!context.tether_enabled) return;
    const auto count = static_cast<std::size_t>(context.vertex_count);
    if (context.state_positions.size() != count * 3 ||
        context.velocity_reference_positions.size() != count * 3 ||
        context.step_basic_positions.size() != count * 3 ||
        context.proxy_attributes.size() != count ||
        context.baseline_roots.size() != count ||
        context.float_values.size() != static_cast<std::size_t>(kFloatCount)) {
        return;
    }
    std::vector<float> inverse_masses(count, 0.0f);
    std::vector<float> rest_lengths(count, 0.0f);
    for (std::size_t vertex = 0; vertex < count; ++vertex) {
        if (!is_move(context.proxy_attributes[vertex])) continue;
        inverse_masses[vertex] = 1.0f;
        const auto root = context.baseline_roots[vertex];
        if (root < 0 || static_cast<std::size_t>(root) >= count) continue;
        const auto offset = vertex * 3;
        const auto root_offset = static_cast<std::size_t>(root) * 3;
        const float dx = context.step_basic_positions[root_offset + 0] -
            context.step_basic_positions[offset + 0];
        const float dy = context.step_basic_positions[root_offset + 1] -
            context.step_basic_positions[offset + 1];
        const float dz = context.step_basic_positions[root_offset + 2] -
            context.step_basic_positions[offset + 2];
        rest_lengths[vertex] = std::sqrt(dx * dx + dy * dy + dz * dz);
    }
    Mc2TetherConstraintView view;
    view.positions = context.state_positions.data();
    view.inv_masses = inverse_masses.data();
    view.root_indices = context.baseline_roots.data();
    view.root_rest_lengths = rest_lengths.data();
    view.velocity_positions = context.velocity_reference_positions.data();
    view.vertex_count = context.vertex_count;
    view.stiffness = 1.0f;
    view.compression = context.float_values[kTetherCompression];
    view.stretch = context.float_values[kTetherStretch];
    project_tether_mc2(view);
    ++context.tether_solve_count;
}

void solve_angle_once(Mc2ContextV0& context, float simulation_power_w) {
    const auto count = static_cast<std::size_t>(context.vertex_count);
    if (context.int_values.size() != static_cast<std::size_t>(kIntCount) ||
        context.float_values.size() != static_cast<std::size_t>(kFloatCount) ||
        context.state_positions.size() != count * 3 ||
        context.velocity_reference_positions.size() != count * 3 ||
        context.step_basic_positions.size() != count * 3 ||
        context.step_basic_rotations.size() != count * 4 ||
        context.proxy_attributes.size() != count ||
        context.baseline_parents.size() != count ||
        context.baseline_depths.size() != count ||
        context.baseline_ranges.empty() ||
        context.baseline_ranges.size() % 2 != 0 ||
        context.baseline_data.empty()) {
        return;
    }
    const bool use_restoration = context.int_values[kUseAngleRestoration] != 0;
    const bool use_limit = context.int_values[kUseAngleLimit] != 0;
    if (!use_restoration && !use_limit) return;

    std::vector<float> inverse_masses(count, 0.0f);
    std::vector<float> restoration_values(count, 0.0f);
    std::vector<float> limit_values(count, 0.0f);
    for (std::size_t vertex = 0; vertex < count; ++vertex) {
        if (is_move(context.proxy_attributes[vertex])) {
            const float friction = context.particle_friction.size() == count
                ? context.particle_friction[vertex] : 0.0f;
            inverse_masses[vertex] = 1.0f / (1.0f + friction * kFrictionMass);
        }
        const float depth = context.baseline_depths[vertex];
        if (use_restoration) {
            restoration_values[vertex] = std::max(
                0.0f,
                std::min(1.0f, sample_curve16(
                    context.curve_values,
                    kAngleRestorationCurve,
                    depth
                ) * simulation_power_w)
            );
        }
        if (use_limit) {
            limit_values[vertex] = std::max(
                0.0f,
                sample_curve16(context.curve_values, kAngleLimitCurve, depth)
            );
        }
    }

    const auto line_count = context.baseline_ranges.size() / 2;
    std::vector<std::int32_t> baseline_start(line_count, 0);
    std::vector<std::int32_t> baseline_count(line_count, 0);
    for (std::size_t line = 0; line < line_count; ++line) {
        baseline_start[line] = context.baseline_ranges[line * 2];
        baseline_count[line] = context.baseline_ranges[line * 2 + 1];
    }

    Mc2AngleConstraintView view;
    view.positions = context.state_positions.data();
    view.inv_masses = inverse_masses.data();
    view.parent_indices = context.baseline_parents.data();
    view.baseline_start = baseline_start.data();
    view.baseline_count = baseline_count.data();
    view.baseline_data = context.baseline_data.data();
    view.step_basic_positions = context.step_basic_positions.data();
    view.step_basic_rotations = context.step_basic_rotations.data();
    view.restoration_values = use_restoration ? restoration_values.data() : nullptr;
    view.limit_values = use_limit ? limit_values.data() : nullptr;
    view.velocity_positions = context.velocity_reference_positions.data();
    view.vertex_count = context.vertex_count;
    view.line_count = static_cast<std::int64_t>(line_count);
    view.baseline_data_count = static_cast<std::int64_t>(context.baseline_data.size());
    view.restoration_velocity_attenuation =
        context.float_values[kAngleRestorationVelocityAttenuation];
    view.restoration_gravity_falloff =
        context.float_values[kAngleRestorationGravityFalloff] *
        (1.0f - context.center_gravity_dot);
    view.limit_stiffness = context.float_values[kAngleLimitStiffness];
    view.explicit_enable_flags = true;
    view.restoration_enabled = use_restoration;
    view.limit_enabled = use_limit;
    project_angle_constraints_mc2(view);
    ++context.angle_solve_count;
}

void solve_motion_once(Mc2ContextV0& context) {
    const auto count = static_cast<std::size_t>(context.vertex_count);
    if (context.int_values.size() != static_cast<std::size_t>(kIntCount) ||
        context.float_values.size() != static_cast<std::size_t>(kFloatCount) ||
        context.state_positions.size() != count * 3 ||
        context.velocity_reference_positions.size() != count * 3 ||
        context.animated_base_positions.size() != count * 3 ||
        context.animated_base_rotations.size() != count * 4 ||
        context.proxy_attributes.size() != count ||
        context.baseline_depths.size() != count) {
        return;
    }
    const bool use_max_distance = context.int_values[kUseMaxDistance] != 0;
    const bool use_backstop = context.int_values[kUseBackstop] != 0;
    if (!use_max_distance && !use_backstop) return;

    std::vector<float> inverse_masses(count, 0.0f);
    std::vector<float> max_distances(count, 0.0f);
    std::vector<float> stiffness_values(
        count,
        std::max(0.0f, std::min(1.0f, context.float_values[kMotionStiffness]))
    );
    std::vector<float> backstop_radii(count, 0.0f);
    std::vector<float> backstop_distances(count, 0.0f);
    for (std::size_t vertex = 0; vertex < count; ++vertex) {
        const auto attribute = context.proxy_attributes[vertex];
        if (is_move(attribute) && (attribute & 0x08u) == 0u) {
            inverse_masses[vertex] = 1.0f;
        }
        const float depth = context.baseline_depths[vertex];
        const float motion_depth = depth * depth;
        if (use_max_distance) {
            max_distances[vertex] = std::max(
                0.0f,
                sample_curve16(context.curve_values, kMaxDistanceCurve, motion_depth)
            );
        }
        if (use_backstop) {
            backstop_radii[vertex] = std::max(0.0f, context.float_values[kBackstopRadius]);
            backstop_distances[vertex] = std::max(
                0.0f,
                sample_curve16(context.curve_values, kBackstopDistanceCurve, motion_depth)
            );
        }
    }

    Mc2MotionConstraintView view;
    view.positions = context.state_positions.data();
    view.base_positions = context.animated_base_positions.data();
    view.base_rotations = context.animated_base_rotations.data();
    view.inv_masses = inverse_masses.data();
    view.max_distances = max_distances.data();
    view.stiffness_values = stiffness_values.data();
    view.backstop_radii = backstop_radii.data();
    view.backstop_distances = backstop_distances.data();
    view.velocity_positions = context.velocity_reference_positions.data();
    view.vertex_count = context.vertex_count;
    view.normal_axis = context.int_values[kNormalAxis];
    view.explicit_enable_flags = true;
    view.max_distance_enabled = use_max_distance;
    view.backstop_enabled = use_backstop;
    project_motion_constraints_mc2(view);
    ++context.motion_solve_count;
}

std::int32_t self_grid_hash(std::int32_t x, std::int32_t y, std::int32_t z) {
    const std::uint32_t hash =
        static_cast<std::uint32_t>(x) * 0x4C7F6DD1u +
        static_cast<std::uint32_t>(y) * 0x4822A3E9u +
        static_cast<std::uint32_t>(z) * 0xAAC3C25Du +
        0xD21D0945u;
    std::int32_t result = 0;
    static_assert(sizeof(result) == sizeof(hash));
    std::memcpy(&result, &hash, sizeof(result));
    return result;
}

template <typename T>
void reorder_self_primitive_chunk(
    std::vector<T>& values,
    std::size_t start,
    std::size_t count,
    std::size_t stride,
    const std::vector<std::size_t>& order
) {
    std::vector<T> reordered(count * stride);
    for (std::size_t destination = 0; destination < count; ++destination) {
        const auto source = order[destination];
        std::copy_n(
            values.data() + source * stride,
            stride,
            reordered.data() + destination * stride
        );
    }
    std::copy(
        reordered.begin(),
        reordered.end(),
        values.begin() + static_cast<std::ptrdiff_t>(start * stride)
    );
}

bool self_owner_pair_allowed(
    const Mc2ContextV0& context,
    std::size_t primitive0,
    std::size_t primitive1
) {
    if (context.self_primitive_owner_indices.empty()) return true;
    if (primitive0 >= context.self_primitive_owner_indices.size() ||
        primitive1 >= context.self_primitive_owner_indices.size()) {
        return false;
    }
    const auto owner0 = context.self_primitive_owner_indices[primitive0];
    const auto owner1 = context.self_primitive_owner_indices[primitive1];
    if (owner0 < 0 || owner1 < 0 || owner0 == owner1) return false;
    const auto owner_count = context.self_owner_primary_group_bits.size();
    if (static_cast<std::size_t>(owner0) >= owner_count ||
        static_cast<std::size_t>(owner1) >= owner_count ||
        context.self_owner_collided_by_groups.size() != owner_count) {
        return false;
    }
    const auto mask0 = context.self_owner_collided_by_groups[owner0];
    const auto mask1 = context.self_owner_collided_by_groups[owner1];
    const bool allows0 = mask0 == 0 ||
        (mask0 & context.self_owner_primary_group_bits[owner1]) != 0;
    const bool allows1 = mask1 == 0 ||
        (mask1 & context.self_owner_primary_group_bits[owner0]) != 0;
    return allows0 && allows1;
}

bool update_self_collision_grid(Mc2ContextV0& context) {
    const auto primitive_count = context.self_primitive_flags.size();
    context.self_contact_candidates.clear();
    context.self_candidate_ready = false;
    context.self_primitive_grids.assign(
        primitive_count * 3,
        kSelfIgnoreGrid
    );
    context.self_grid_hashes.assign(primitive_count, 0);
    context.self_grid_starts.assign(primitive_count, 0);
    context.self_grid_counts.assign(primitive_count, 0);
    context.self_point_grid_count = 0;
    context.self_edge_grid_count = 0;
    context.self_triangle_grid_count = 0;
    if (context.self_grid_size <= kMc2Epsilon) {
        context.self_grid_dynamic_ready = false;
        return false;
    }

    const std::array<std::size_t, 3> starts {
        0,
        static_cast<std::size_t>(context.self_point_primitive_count),
        static_cast<std::size_t>(
            context.self_point_primitive_count + context.self_edge_primitive_count
        ),
    };
    const std::array<std::size_t, 3> counts {
        static_cast<std::size_t>(context.self_point_primitive_count),
        static_cast<std::size_t>(context.self_edge_primitive_count),
        static_cast<std::size_t>(context.self_triangle_primitive_count),
    };
    std::array<std::int64_t*, 3> grid_count_outputs {
        &context.self_point_grid_count,
        &context.self_edge_grid_count,
        &context.self_triangle_grid_count,
    };

    for (std::size_t kind = 0; kind < 3; ++kind) {
        const auto start = starts[kind];
        const auto count = counts[kind];
        if (count == 0) continue;
        for (std::size_t local = 0; local < count; ++local) {
            const auto primitive = start + local;
            if ((context.self_primitive_flags[primitive] & kSelfIgnore) != 0u) continue;
            for (std::size_t component = 0; component < 3; ++component) {
                const auto offset = primitive * 3 + component;
                const float center = (
                    context.self_primitive_aabb_min[offset] +
                    context.self_primitive_aabb_max[offset]
                ) * 0.5f;
                context.self_primitive_grids[offset] = static_cast<std::int32_t>(
                    std::floor(center / context.self_grid_size)
                );
            }
        }

        std::vector<std::size_t> order(count);
        for (std::size_t local = 0; local < count; ++local) order[local] = start + local;
        std::stable_sort(order.begin(), order.end(), [&](std::size_t left, std::size_t right) {
            for (std::size_t component = 0; component < 3; ++component) {
                const auto left_value = context.self_primitive_grids[left * 3 + component];
                const auto right_value = context.self_primitive_grids[right * 3 + component];
                if (left_value != right_value) return left_value < right_value;
            }
            return false;
        });
        reorder_self_primitive_chunk(context.self_primitive_flags, start, count, 1, order);
        reorder_self_primitive_chunk(context.self_particle_indices, start, count, 3, order);
        reorder_self_primitive_chunk(context.self_primitive_depths, start, count, 1, order);
        reorder_self_primitive_chunk(context.self_primitive_inverse_masses, start, count, 3, order);
        reorder_self_primitive_chunk(context.self_primitive_aabb_min, start, count, 3, order);
        reorder_self_primitive_chunk(context.self_primitive_aabb_max, start, count, 3, order);
        reorder_self_primitive_chunk(context.self_primitive_thickness, start, count, 1, order);
        if (context.self_primitive_owner_indices.size() == primitive_count) {
            reorder_self_primitive_chunk(
                context.self_primitive_owner_indices,
                start,
                count,
                1,
                order
            );
        }
        reorder_self_primitive_chunk(context.self_primitive_grids, start, count, 3, order);

        struct GridRun {
            std::int32_t hash;
            std::int32_t start;
            std::int32_t count;
        };
        std::vector<GridRun> runs;
        std::size_t run_start = start;
        for (std::size_t local = 1; local <= count; ++local) {
            bool same_grid = false;
            if (local < count) {
                same_grid = true;
                for (std::size_t component = 0; component < 3; ++component) {
                    if (context.self_primitive_grids[(start + local) * 3 + component] !=
                        context.self_primitive_grids[run_start * 3 + component]) {
                        same_grid = false;
                        break;
                    }
                }
            }
            if (same_grid) continue;
            const auto x = context.self_primitive_grids[run_start * 3];
            const auto y = context.self_primitive_grids[run_start * 3 + 1];
            const auto z = context.self_primitive_grids[run_start * 3 + 2];
            runs.push_back(GridRun {
                self_grid_hash(x, y, z),
                static_cast<std::int32_t>(run_start),
                static_cast<std::int32_t>(start + local - run_start),
            });
            run_start = start + local;
        }
        std::stable_sort(runs.begin(), runs.end(), [](const GridRun& left, const GridRun& right) {
            return left.hash < right.hash;
        });
        for (std::size_t run = 0; run < runs.size(); ++run) {
            context.self_grid_hashes[start + run] = runs[run].hash;
            context.self_grid_starts[start + run] = runs[run].start;
            context.self_grid_counts[start + run] = runs[run].count;
        }
        *grid_count_outputs[kind] = static_cast<std::int64_t>(runs.size());
    }
    context.self_grid_dynamic_ready = true;
    ++context.self_grid_update_count;
    return true;
}

bool self_primitives_share_particle(
    const Mc2ContextV0& context,
    std::size_t left,
    std::size_t right
) {
    const auto left_kind = static_cast<std::size_t>(
        (context.self_primitive_flags[left] >> 24u) & 0x03u
    );
    const auto right_kind = static_cast<std::size_t>(
        (context.self_primitive_flags[right] >> 24u) & 0x03u
    );
    for (std::size_t left_axis = 0; left_axis <= left_kind; ++left_axis) {
        const auto particle = context.self_particle_indices[left * 3 + left_axis];
        for (std::size_t right_axis = 0; right_axis <= right_kind; ++right_axis) {
            if (particle == context.self_particle_indices[right * 3 + right_axis]) return true;
        }
    }
    return false;
}

bool self_aabbs_overlap(
    const Mc2ContextV0& context,
    std::size_t left,
    std::size_t right
) {
    for (std::size_t component = 0; component < 3; ++component) {
        if (context.self_primitive_aabb_max[left * 3 + component] <
                context.self_primitive_aabb_min[right * 3 + component] ||
            context.self_primitive_aabb_min[left * 3 + component] >
                context.self_primitive_aabb_max[right * 3 + component]) {
            return false;
        }
    }
    return true;
}

std::int64_t self_binary_search_grid_hash(
    const Mc2ContextV0& context,
    std::size_t start,
    std::size_t length,
    std::int32_t value
) {
    std::size_t offset = 0;
    for (std::size_t remaining = length; remaining != 0; remaining >>= 1) {
        const auto index = offset + (remaining >> 1);
        const auto current = context.self_grid_hashes[start + index];
        if (value == current) return static_cast<std::int64_t>(index);
        if (value > current) {
            offset = index + 1;
            --remaining;
        }
    }
    return -1;
}

bool self_collision_intersect_enabled(const Mc2ContextV0& context) {
    return context.self_collision_static_ready &&
        context.setup_kind != 2 &&
        context.int_values.size() == static_cast<std::size_t>(kIntCount) &&
        context.int_values[kSelfCollisionMode] == 2 &&
        context.self_edge_primitive_count > 0 &&
        context.self_triangle_primitive_count > 0;
}

void detect_self_collision_intersections_once(Mc2ContextV0& context) {
    if (context.self_intersect_detection_ready &&
        context.self_intersect_detection_frame == context.frame &&
        context.self_intersect_detection_generation == context.generation) {
        return;
    }
    context.self_intersect_records.clear();
    context.self_intersect_detection_ready = false;
    context.self_intersect_detection_frame = context.frame;
    context.self_intersect_detection_generation = context.generation;
    if (!self_collision_intersect_enabled(context)) {
        context.self_particle_intersect_flags.assign(
            static_cast<std::size_t>(context.vertex_count),
            static_cast<std::uint8_t>(0)
        );
        context.self_intersect_flags_ready = false;
        return;
    }

    context.self_intersect_detection_ready = true;
    ++context.self_intersect_detection_count;
    if (!context.self_grid_dynamic_ready ||
        context.self_max_primitive_size <= kMc2Epsilon ||
        context.self_grid_size <= kMc2Epsilon) {
        return;
    }

    struct IntersectRecord {
        std::array<std::int32_t, 5> particles {};
    };
    std::vector<IntersectRecord> records;
    const auto edge_start = static_cast<std::size_t>(context.self_point_primitive_count);
    const auto edge_count = static_cast<std::size_t>(context.self_edge_primitive_count);
    const auto triangle_start = static_cast<std::size_t>(
        context.self_point_primitive_count + context.self_edge_primitive_count
    );
    const auto triangle_grid_count = static_cast<std::size_t>(
        context.self_triangle_grid_count
    );
    const auto frame_index = static_cast<std::size_t>((context.frame % 2 + 2) % 2);
    for (std::size_t edge = edge_start; edge < edge_start + edge_count; ++edge) {
        if ((edge % 2) != frame_index) continue;
        const auto edge_flag = context.self_primitive_flags[edge];
        if ((edge_flag & kSelfIgnore) != 0u) continue;
        std::array<std::int32_t, 3> start_grid {};
        std::array<std::int32_t, 3> end_grid {};
        const float padding = context.self_max_primitive_size * 0.5f;
        for (std::size_t component = 0; component < 3; ++component) {
            start_grid[component] = static_cast<std::int32_t>(std::floor(
                (context.self_primitive_aabb_min[edge * 3 + component] - padding) /
                context.self_grid_size
            ));
            end_grid[component] = static_cast<std::int32_t>(std::floor(
                (context.self_primitive_aabb_max[edge * 3 + component] + padding) /
                context.self_grid_size
            ));
        }
        for (std::int64_t z = start_grid[2]; z <= end_grid[2]; ++z) {
            for (std::int64_t y = start_grid[1]; y <= end_grid[1]; ++y) {
                for (std::int64_t x = start_grid[0]; x <= end_grid[0]; ++x) {
                    const auto hash = self_grid_hash(
                        static_cast<std::int32_t>(x),
                        static_cast<std::int32_t>(y),
                        static_cast<std::int32_t>(z)
                    );
                    const auto run_index = self_binary_search_grid_hash(
                        context,
                        triangle_start,
                        triangle_grid_count,
                        hash
                    );
                    if (run_index < 0) continue;
                    const auto buffer_index = triangle_start +
                        static_cast<std::size_t>(run_index);
                    const auto run_start = static_cast<std::size_t>(
                        context.self_grid_starts[buffer_index]
                    );
                    const auto run_end = run_start + static_cast<std::size_t>(
                        context.self_grid_counts[buffer_index]
                    );
                    for (std::size_t triangle = run_start; triangle < run_end; ++triangle) {
                        const auto triangle_flag = context.self_primitive_flags[triangle];
                        if (!self_owner_pair_allowed(context, edge, triangle) ||
                            !self_aabbs_overlap(context, edge, triangle) ||
                            (triangle_flag & kSelfIgnore) != 0u ||
                            ((edge_flag & kSelfAllFix) != 0u &&
                             (triangle_flag & kSelfAllFix) != 0u) ||
                            self_primitives_share_particle(context, edge, triangle)) {
                            continue;
                        }
                        records.push_back(IntersectRecord {{
                            context.self_particle_indices[edge * 3],
                            context.self_particle_indices[edge * 3 + 1],
                            context.self_particle_indices[triangle * 3],
                            context.self_particle_indices[triangle * 3 + 1],
                            context.self_particle_indices[triangle * 3 + 2],
                        }});
                    }
                }
            }
        }
    }
    std::sort(records.begin(), records.end(), [](const auto& left, const auto& right) {
        return left.particles < right.particles;
    });
    records.erase(
        std::unique(records.begin(), records.end(), [](const auto& left, const auto& right) {
            return left.particles == right.particles;
        }),
        records.end()
    );
    context.self_intersect_records.reserve(records.size() * 5);
    for (const auto& record : records) {
        context.self_intersect_records.insert(
            context.self_intersect_records.end(),
            record.particles.begin(),
            record.particles.end()
        );
    }
}

void solve_self_collision_intersections_final(Mc2ContextV0& context) {
    if (!self_collision_intersect_enabled(context) ||
        !context.self_intersect_detection_ready) {
        return;
    }
    const auto vertex_count = static_cast<std::size_t>(context.vertex_count);
    context.self_particle_intersect_flags.assign(vertex_count, static_cast<std::uint8_t>(0));
    if (context.state_positions.size() != vertex_count * 3) {
        context.self_intersect_flags_ready = false;
        return;
    }
    const auto record_count = context.self_intersect_records.size() / 5;
    for (std::size_t record = 0; record < record_count; ++record) {
        const auto* particles = context.self_intersect_records.data() + record * 5;
        Vec3 p = load_vector3(context.state_positions, static_cast<std::size_t>(particles[0]));
        const Vec3 q = load_vector3(context.state_positions, static_cast<std::size_t>(particles[1]));
        const Vec3 a = load_vector3(context.state_positions, static_cast<std::size_t>(particles[2]));
        const Vec3 b = load_vector3(context.state_positions, static_cast<std::size_t>(particles[3]));
        const Vec3 c = load_vector3(context.state_positions, static_cast<std::size_t>(particles[4]));
        Vec3 qp = sub(p, q);
        const Vec3 ac = sub(c, a);
        const Vec3 ab = sub(b, a);
        const Vec3 n = cross(ab, ac);
        float d = dot(qp, n);
        if (std::abs(d) < kMc2Epsilon) continue;
        if (d < 0.0f) {
            p = q;
            qp = mul(qp, -1.0f);
            d = -d;
        }
        const Vec3 ap = sub(p, a);
        const float t = dot(ap, n);
        if (t < 0.0f || t > d) continue;
        const Vec3 e = cross(qp, ap);
        const float v = dot(ac, e);
        if (v < 0.0f || v > d) continue;
        const float w = -dot(ab, e);
        if (w < 0.0f || v + w > d) continue;
        context.self_particle_intersect_flags[static_cast<std::size_t>(particles[0])] = 1;
        context.self_particle_intersect_flags[static_cast<std::size_t>(particles[1])] = 1;
    }
    context.self_intersect_flags_ready = true;
    ++context.self_intersect_solve_count;
}

void update_self_collision_candidates(Mc2ContextV0& context) {
    context.self_contact_candidates.clear();
    context.self_candidate_ready = false;
    if (!context.self_grid_dynamic_ready) return;

    struct Candidate {
        std::int32_t primitive0;
        std::int32_t primitive1;
        std::int32_t type;
    };
    std::vector<Candidate> candidates;
    const auto point_start = std::size_t {0};
    const auto edge_start = static_cast<std::size_t>(context.self_point_primitive_count);
    const auto triangle_start = static_cast<std::size_t>(
        context.self_point_primitive_count + context.self_edge_primitive_count
    );

    auto detect = [&](std::size_t my_start,
                      std::size_t my_count,
                      std::size_t target_start,
                      std::size_t target_count,
                      std::size_t target_grid_count,
                      std::int32_t contact_type,
                      bool duplicate_detection) {
        if (my_count == 0 || target_count == 0 || target_grid_count == 0) return;
        for (std::size_t primitive = my_start; primitive < my_start + my_count; ++primitive) {
            const auto flag = context.self_primitive_flags[primitive];
            if ((flag & kSelfIgnore) != 0u) continue;
            std::array<std::int32_t, 3> start_grid {};
            std::array<std::int32_t, 3> end_grid {};
            for (std::size_t component = 0; component < 3; ++component) {
                const float padding = context.self_max_primitive_size * 0.5f;
                start_grid[component] = static_cast<std::int32_t>(std::floor(
                    (context.self_primitive_aabb_min[primitive * 3 + component] - padding) /
                    context.self_grid_size
                ));
                end_grid[component] = static_cast<std::int32_t>(std::floor(
                    (context.self_primitive_aabb_max[primitive * 3 + component] + padding) /
                    context.self_grid_size
                ));
            }
            for (std::int64_t z = start_grid[2]; z <= end_grid[2]; ++z) {
                for (std::int64_t y = start_grid[1]; y <= end_grid[1]; ++y) {
                    for (std::int64_t x = start_grid[0]; x <= end_grid[0]; ++x) {
                        const auto hash = self_grid_hash(
                            static_cast<std::int32_t>(x),
                            static_cast<std::int32_t>(y),
                            static_cast<std::int32_t>(z)
                        );
                        const auto run_index = self_binary_search_grid_hash(
                            context,
                            target_start,
                            target_grid_count,
                            hash
                        );
                        if (run_index < 0) continue;
                        const auto buffer_index = target_start + static_cast<std::size_t>(run_index);
                        const auto run_start = static_cast<std::size_t>(
                            context.self_grid_starts[buffer_index]
                        );
                        const auto run_end = run_start + static_cast<std::size_t>(
                            context.self_grid_counts[buffer_index]
                        );
                        if (duplicate_detection && run_end < primitive) continue;
                        auto target = duplicate_detection
                            ? std::max(run_start, primitive)
                            : run_start;
                        for (; target < run_end; ++target) {
                            if (duplicate_detection && primitive == target) continue;
                            const auto target_flag = context.self_primitive_flags[target];
                            if (!self_owner_pair_allowed(context, primitive, target) ||
                                !self_aabbs_overlap(context, primitive, target) ||
                                (target_flag & kSelfIgnore) != 0u ||
                                ((flag & kSelfAllFix) != 0u &&
                                 (target_flag & kSelfAllFix) != 0u) ||
                                self_primitives_share_particle(context, primitive, target)) {
                                continue;
                            }
                            candidates.push_back(Candidate {
                                static_cast<std::int32_t>(primitive),
                                static_cast<std::int32_t>(target),
                                contact_type,
                            });
                        }
                    }
                }
            }
        }
    };

    detect(
        edge_start,
        static_cast<std::size_t>(context.self_edge_primitive_count),
        edge_start,
        static_cast<std::size_t>(context.self_edge_primitive_count),
        static_cast<std::size_t>(context.self_edge_grid_count),
        0,
        true
    );
    detect(
        point_start,
        static_cast<std::size_t>(context.self_point_primitive_count),
        triangle_start,
        static_cast<std::size_t>(context.self_triangle_primitive_count),
        static_cast<std::size_t>(context.self_triangle_grid_count),
        1,
        false
    );
    std::sort(candidates.begin(), candidates.end(), [](const Candidate& left, const Candidate& right) {
        if (left.type != right.type) return left.type < right.type;
        if (left.primitive0 != right.primitive0) return left.primitive0 < right.primitive0;
        return left.primitive1 < right.primitive1;
    });
    candidates.erase(
        std::unique(candidates.begin(), candidates.end(), [](const Candidate& left, const Candidate& right) {
            return left.type == right.type &&
                left.primitive0 == right.primitive0 &&
                left.primitive1 == right.primitive1;
        }),
        candidates.end()
    );
    context.self_contact_candidates.reserve(candidates.size() * 3);
    for (const auto& candidate : candidates) {
        context.self_contact_candidates.push_back(candidate.primitive0);
        context.self_contact_candidates.push_back(candidate.primitive1);
        context.self_contact_candidates.push_back(candidate.type);
    }
    context.self_candidate_ready = true;
    ++context.self_candidate_update_count;
}

struct SelfContactValue {
    std::int32_t primitive0 = 0;
    std::int32_t primitive1 = 0;
    std::int32_t type = 0;
    std::uint8_t enabled = 0;
    float thickness = 0.0f;
    float s = 0.0f;
    float t = 0.0f;
    Vec3 normal {};
};

float closest_segment_segment(
    Vec3 p1,
    Vec3 q1,
    Vec3 p2,
    Vec3 q2,
    float& s,
    float& t,
    Vec3& c1,
    Vec3& c2
) {
    const Vec3 d1 = sub(q1, p1);
    const Vec3 d2 = sub(q2, p2);
    const Vec3 r = sub(p1, p2);
    const float a = dot(d1, d1);
    const float e = dot(d2, d2);
    const float f = dot(d2, r);
    if (a <= 1.0e-8f && e <= 1.0e-8f) {
        s = t = 0.0f;
        c1 = p1;
        c2 = p2;
        return length_squared(sub(c1, c2));
    }
    if (a <= 1.0e-8f) {
        s = 0.0f;
        t = saturate(f / e);
    } else {
        const float c = dot(d1, r);
        if (e <= 1.0e-8f) {
            t = 0.0f;
            s = saturate(-c / a);
        } else {
            const float b = dot(d1, d2);
            const float denominator = a * e - b * b;
            s = denominator != 0.0f
                ? saturate((b * f - c * e) / denominator)
                : 0.0f;
            t = (b * s + f) / e;
            if (t < 0.0f) {
                t = 0.0f;
                s = saturate(-c / a);
            } else if (t > 1.0f) {
                t = 1.0f;
                s = saturate((b - c) / a);
            }
        }
    }
    c1 = add(p1, mul(d1, s));
    c2 = add(p2, mul(d2, t));
    return length_squared(sub(c1, c2));
}

Vec3 closest_point_triangle(
    Vec3 point,
    Vec3 a,
    Vec3 b,
    Vec3 c,
    Vec3& uvw
) {
    uvw = {};
    const Vec3 ab = sub(b, a);
    const Vec3 ac = sub(c, a);
    const Vec3 ap = sub(point, a);
    const float d1 = dot(ab, ap);
    const float d2 = dot(ac, ap);
    if (d1 <= 0.0f && d2 <= 0.0f) {
        uvw.x = 1.0f;
        return a;
    }
    const Vec3 bp = sub(point, b);
    const float d3 = dot(ab, bp);
    const float d4 = dot(ac, bp);
    if (d3 >= 0.0f && d4 <= d3) {
        uvw.y = 1.0f;
        return b;
    }
    const float vc = d1 * d4 - d3 * d2;
    if (vc <= 0.0f && d1 >= 0.0f && d3 <= 0.0f) {
        const float v = d1 / (d1 - d3);
        uvw = {1.0f - v, v, 0.0f};
        return add(a, mul(ab, v));
    }
    const Vec3 cp = sub(point, c);
    const float d5 = dot(ab, cp);
    const float d6 = dot(ac, cp);
    if (d6 >= 0.0f && d5 <= d6) {
        uvw.z = 1.0f;
        return c;
    }
    const float vb = d5 * d2 - d1 * d6;
    if (vb <= 0.0f && d2 >= 0.0f && d6 <= 0.0f) {
        const float w = d2 / (d2 - d6);
        uvw = {1.0f - w, 0.0f, w};
        return add(a, mul(ac, w));
    }
    const float va = d3 * d6 - d5 * d4;
    if (va <= 0.0f && (d4 - d3) >= 0.0f && (d5 - d6) >= 0.0f) {
        const float denominator = (d4 - d3) + (d5 - d6);
        const float w = (d4 - d3) / denominator;
        uvw = {0.0f, 1.0f - w, w};
        return add(b, mul(sub(c, b), w));
    }
    const float denominator = 1.0f / (va + vb + vc);
    const float v = vb * denominator;
    const float w = vc * denominator;
    uvw = {1.0f - v - w, v, w};
    return add(add(a, mul(ab, v)), mul(ac, w));
}

bool update_self_contact_value(
    const Mc2ContextV0& context,
    const std::vector<float>& old_positions,
    bool first,
    SelfContactValue& contact
) {
    contact.enabled = 0;
    const auto primitive0 = static_cast<std::size_t>(contact.primitive0);
    const auto primitive1 = static_cast<std::size_t>(contact.primitive1);
    const float threshold = contact.thickness * 3.0f;
    auto particle = [&](std::size_t primitive, std::size_t axis) {
        return static_cast<std::size_t>(context.self_particle_indices[primitive * 3 + axis]);
    };
    if (contact.type == 0) {
        const auto a0 = particle(primitive0, 0);
        const auto a1 = particle(primitive0, 1);
        const auto b0 = particle(primitive1, 0);
        const auto b1 = particle(primitive1, 1);
        const Vec3 next_a0 = load_vector3(context.state_positions, a0);
        const Vec3 next_a1 = load_vector3(context.state_positions, a1);
        const Vec3 next_b0 = load_vector3(context.state_positions, b0);
        const Vec3 next_b1 = load_vector3(context.state_positions, b1);
        const Vec3 old_a0 = load_vector3(old_positions, a0);
        const Vec3 old_a1 = load_vector3(old_positions, a1);
        const Vec3 old_b0 = load_vector3(old_positions, b0);
        const Vec3 old_b1 = load_vector3(old_positions, b1);
        float s = 0.0f, t = 0.0f;
        Vec3 closest_a {}, closest_b {};
        const float closest_length = std::sqrt(closest_segment_segment(
            old_a0, old_a1, old_b0, old_b1, s, t, closest_a, closest_b
        ));
        if (closest_length < 1.0e-9f) return false;
        const Vec3 normal = mul(sub(closest_a, closest_b), 1.0f / closest_length);
        const Vec3 displacement_a = add(
            mul(sub(next_a0, old_a0), 1.0f - s),
            mul(sub(next_a1, old_a1), s)
        );
        const Vec3 displacement_b = add(
            mul(sub(next_b0, old_b0), 1.0f - t),
            mul(sub(next_b1, old_b1), t)
        );
        const float predicted_length = closest_length +
            dot(normal, displacement_a) - dot(normal, displacement_b);
        if (predicted_length > threshold) return false;
        contact.enabled = 1;
        contact.s = quantize_half(s);
        contact.t = quantize_half(t);
        contact.normal = {
            quantize_half(normal.x),
            quantize_half(normal.y),
            quantize_half(normal.z),
        };
        return true;
    }
    if (contact.type == 1) {
        const auto point_index = particle(primitive0, 0);
        const auto b0 = particle(primitive1, 0);
        const auto b1 = particle(primitive1, 1);
        const auto b2 = particle(primitive1, 2);
        const Vec3 next_point = load_vector3(context.state_positions, point_index);
        const Vec3 old_point = load_vector3(old_positions, point_index);
        const Vec3 next_b0 = load_vector3(context.state_positions, b0);
        const Vec3 next_b1 = load_vector3(context.state_positions, b1);
        const Vec3 next_b2 = load_vector3(context.state_positions, b2);
        const Vec3 old_b0 = load_vector3(old_positions, b0);
        const Vec3 old_b1 = load_vector3(old_positions, b1);
        const Vec3 old_b2 = load_vector3(old_positions, b2);
        const Vec3 point_displacement = sub(next_point, old_point);
        const Vec3 displacement_b0 = sub(next_b0, old_b0);
        const Vec3 displacement_b1 = sub(next_b1, old_b1);
        const Vec3 displacement_b2 = sub(next_b2, old_b2);
        Vec3 uvw {};
        const Vec3 closest = closest_point_triangle(
            old_point, old_b0, old_b1, old_b2, uvw
        );
        const Vec3 triangle_displacement = add(
            add(mul(displacement_b0, uvw.x), mul(displacement_b1, uvw.y)),
            mul(displacement_b2, uvw.z)
        );
        const Vec3 closest_vector = sub(closest, old_point);
        const float closest_length = length(closest_vector);
        if (closest_length <= kMc2Epsilon) return false;
        Vec3 normal = mul(closest_vector, 1.0f / closest_length);
        const float predicted_length = closest_length -
            dot(normal, point_displacement) + dot(normal, triangle_displacement);
        if (predicted_length >= threshold) return false;
        float sign = contact.s;
        if (first) {
            const Vec3 triangle_normal = normalize(cross(
                sub(old_b1, old_b0),
                sub(old_b2, old_b0)
            ));
            normal = normalize(sub(old_point, closest));
            const float direction = dot(triangle_normal, normal);
            if (std::abs(direction) < 0.5f) return false;
            sign = direction > 0.0f ? 1.0f : -1.0f;
        }
        contact.s = quantize_half(sign);
        contact.enabled = 1;
        return true;
    }
    return false;
}

void clear_self_collision_contacts(Mc2ContextV0& context) {
    context.self_contact_keys.clear();
    context.self_contact_primitive_indices.clear();
    context.self_contact_types.clear();
    context.self_contact_enabled.clear();
    context.self_contact_thickness.clear();
    context.self_contact_s.clear();
    context.self_contact_t.clear();
    context.self_contact_normals.clear();
    context.self_contact_ready = false;
}

void append_self_contact(Mc2ContextV0& context, const SelfContactValue& contact) {
    context.self_contact_primitive_indices.push_back(contact.primitive0);
    context.self_contact_primitive_indices.push_back(contact.primitive1);
    context.self_contact_types.push_back(contact.type);
    context.self_contact_enabled.push_back(contact.enabled);
    context.self_contact_thickness.push_back(contact.thickness);
    context.self_contact_s.push_back(contact.s);
    context.self_contact_t.push_back(contact.t);
    context.self_contact_normals.push_back(contact.normal.x);
    context.self_contact_normals.push_back(contact.normal.y);
    context.self_contact_normals.push_back(contact.normal.z);
    const auto key =
        (static_cast<std::uint64_t>(contact.type) << 62u) |
        (static_cast<std::uint64_t>(static_cast<std::uint32_t>(contact.primitive0)) << 31u) |
        static_cast<std::uint32_t>(contact.primitive1);
    context.self_contact_keys.push_back(key);
}

void build_self_collision_contacts(
    Mc2ContextV0& context,
    const std::vector<float>& old_positions
) {
    clear_self_collision_contacts(context);
    const auto candidate_count = context.self_contact_candidates.size() / 3;
    for (std::size_t candidate = 0; candidate < candidate_count; ++candidate) {
        const auto primitive0 = context.self_contact_candidates[candidate * 3];
        const auto primitive1 = context.self_contact_candidates[candidate * 3 + 1];
        SelfContactValue contact;
        contact.primitive0 = primitive0;
        contact.primitive1 = primitive1;
        contact.type = context.self_contact_candidates[candidate * 3 + 2];
        contact.thickness = quantize_half(
            context.self_primitive_thickness[primitive0] +
            context.self_primitive_thickness[primitive1]
        );
        if (update_self_contact_value(context, old_positions, true, contact)) {
            append_self_contact(context, contact);
        }
    }
    context.self_contact_ready = true;
    ++context.self_contact_build_count;
}

void update_self_collision_contacts(
    Mc2ContextV0& context,
    const std::vector<float>& old_positions
) {
    if (!context.self_contact_ready) return;
    const auto count = context.self_contact_types.size();
    for (std::size_t index = 0; index < count; ++index) {
        SelfContactValue contact;
        contact.primitive0 = context.self_contact_primitive_indices[index * 2];
        contact.primitive1 = context.self_contact_primitive_indices[index * 2 + 1];
        contact.type = context.self_contact_types[index];
        contact.enabled = context.self_contact_enabled[index];
        contact.thickness = context.self_contact_thickness[index];
        contact.s = context.self_contact_s[index];
        contact.t = context.self_contact_t[index];
        contact.normal = {
            context.self_contact_normals[index * 3],
            context.self_contact_normals[index * 3 + 1],
            context.self_contact_normals[index * 3 + 2],
        };
        update_self_contact_value(context, old_positions, false, contact);
        context.self_contact_enabled[index] = contact.enabled;
        context.self_contact_s[index] = contact.s;
        context.self_contact_t[index] = contact.t;
        context.self_contact_normals[index * 3] = contact.normal.x;
        context.self_contact_normals[index * 3 + 1] = contact.normal.y;
        context.self_contact_normals[index * 3 + 2] = contact.normal.z;
    }
    ++context.self_contact_update_count;
}

void add_wrapped_int32(std::int32_t& destination, std::int32_t value) {
    const std::uint32_t sum =
        static_cast<std::uint32_t>(destination) + static_cast<std::uint32_t>(value);
    std::memcpy(&destination, &sum, sizeof(destination));
}

void solve_self_collision_contacts(Mc2ContextV0& context) {
    if (!context.self_contact_ready) return;
    const auto vertex_count = static_cast<std::size_t>(context.vertex_count);
    std::vector<std::int32_t> counts(vertex_count, 0);
    std::vector<std::int32_t> sums(vertex_count * 3, 0);
    auto accumulate = [&](std::size_t vertex, Vec3 correction) {
        ++counts[vertex];
        const std::array<float, 3> values {correction.x, correction.y, correction.z};
        for (std::size_t component = 0; component < 3; ++component) {
            const auto fixed = static_cast<std::int32_t>(values[component] * 1000000.0f);
            add_wrapped_int32(sums[vertex * 3 + component], fixed);
        }
    };
    auto particle = [&](std::size_t primitive, std::size_t axis) {
        return static_cast<std::size_t>(context.self_particle_indices[primitive * 3 + axis]);
    };
    auto inverse_mass = [&](std::size_t primitive, std::size_t axis) {
        return context.self_primitive_inverse_masses[primitive * 3 + axis];
    };
    auto can_write = [&](std::size_t primitive, std::size_t axis) {
        const auto blocked = (kSelfFix0 | 0x00000001u) << axis;
        return (context.self_primitive_flags[primitive] & blocked) == 0u;
    };

    constexpr int kSolverIterations = 4;
    for (int iteration = 0; iteration < kSolverIterations; ++iteration) {
        const auto contact_count = context.self_contact_types.size();
        for (std::size_t contact = 0; contact < contact_count; ++contact) {
            if (context.self_contact_enabled[contact] == 0) continue;
            const auto primitive0 = static_cast<std::size_t>(
                context.self_contact_primitive_indices[contact * 2]
            );
            const auto primitive1 = static_cast<std::size_t>(
                context.self_contact_primitive_indices[contact * 2 + 1]
            );
            const float thickness = context.self_contact_thickness[contact];
            if (context.self_contact_types[contact] == 0) {
                const auto a0 = particle(primitive0, 0);
                const auto a1 = particle(primitive0, 1);
                const auto b0 = particle(primitive1, 0);
                const auto b1 = particle(primitive1, 1);
                const float s = context.self_contact_s[contact];
                const float t = context.self_contact_t[contact];
                const Vec3 normal {
                    context.self_contact_normals[contact * 3],
                    context.self_contact_normals[contact * 3 + 1],
                    context.self_contact_normals[contact * 3 + 2],
                };
                const Vec3 a = add(
                    mul(load_vector3(context.state_positions, a0), 1.0f - s),
                    mul(load_vector3(context.state_positions, a1), s)
                );
                const Vec3 b = add(
                    mul(load_vector3(context.state_positions, b0), 1.0f - t),
                    mul(load_vector3(context.state_positions, b1), t)
                );
                const float projected_length = dot(normal, sub(a, b));
                if (projected_length > thickness) continue;
                const float weight_a0 = 1.0f - s;
                const float weight_a1 = s;
                const float weight_b0 = 1.0f - t;
                const float weight_b1 = t;
                const float inv_a0 = inverse_mass(primitive0, 0);
                const float inv_a1 = inverse_mass(primitive0, 1);
                const float inv_b0 = inverse_mass(primitive1, 0);
                const float inv_b1 = inverse_mass(primitive1, 1);
                const float denominator =
                    inv_a0 * weight_a0 * weight_a0 +
                    inv_a1 * weight_a1 * weight_a1 +
                    inv_b0 * weight_b0 * weight_b0 +
                    inv_b1 * weight_b1 * weight_b1;
                if (denominator == 0.0f) continue;
                const float scale = (thickness - projected_length) / denominator;
                const Vec3 correction_a0 = mul(normal, scale * inv_a0 * weight_a0);
                const Vec3 correction_a1 = mul(normal, scale * inv_a1 * weight_a1);
                const Vec3 correction_b0 = mul(normal, -scale * inv_b0 * weight_b0);
                const Vec3 correction_b1 = mul(normal, -scale * inv_b1 * weight_b1);
                if (can_write(primitive0, 0)) accumulate(a0, correction_a0);
                if (can_write(primitive0, 1)) accumulate(a1, correction_a1);
                if (can_write(primitive1, 0)) accumulate(b0, correction_b0);
                if (can_write(primitive1, 1)) accumulate(b1, correction_b1);
            } else if (context.self_contact_types[contact] == 1) {
                const auto point_index = particle(primitive0, 0);
                const auto b0 = particle(primitive1, 0);
                const auto b1 = particle(primitive1, 1);
                const auto b2 = particle(primitive1, 2);
                const Vec3 position_b0 = load_vector3(context.state_positions, b0);
                const Vec3 position_b1 = load_vector3(context.state_positions, b1);
                const Vec3 position_b2 = load_vector3(context.state_positions, b2);
                const Vec3 point_position = load_vector3(context.state_positions, point_index);
                const Vec3 triangle_normal = normalize(cross(
                    sub(position_b1, position_b0),
                    sub(position_b2, position_b0)
                ));
                Vec3 uvw {};
                closest_point_triangle(
                    point_position,
                    position_b0,
                    position_b1,
                    position_b2,
                    uvw
                );
                const Vec3 normal = mul(triangle_normal, context.self_contact_s[contact]);
                const float distance = dot(normal, sub(point_position, position_b0));
                if (distance >= thickness) continue;
                const float inv_point = inverse_mass(primitive0, 0);
                const float inv_b0 = inverse_mass(primitive1, 0);
                const float inv_b1 = inverse_mass(primitive1, 1);
                const float inv_b2 = inverse_mass(primitive1, 2);
                const float denominator =
                    inv_point +
                    inv_b0 * uvw.x * uvw.x +
                    inv_b1 * uvw.y * uvw.y +
                    inv_b2 * uvw.z * uvw.z;
                if (denominator == 0.0f) continue;
                const float scale = (distance - thickness) / denominator;
                const Vec3 correction = mul(normal, -scale * inv_point);
                const Vec3 correction_b0 = mul(normal, scale * inv_b0 * uvw.x);
                const Vec3 correction_b1 = mul(normal, scale * inv_b1 * uvw.y);
                const Vec3 correction_b2 = mul(normal, scale * inv_b2 * uvw.z);
                if (can_write(primitive0, 0)) accumulate(point_index, correction);
                if (can_write(primitive1, 0)) accumulate(b0, correction_b0);
                if (can_write(primitive1, 1)) accumulate(b1, correction_b1);
                if (can_write(primitive1, 2)) accumulate(b2, correction_b2);
            }
        }
        for (std::size_t vertex = 0; vertex < vertex_count; ++vertex) {
            const auto count = counts[vertex];
            if (count > 0) {
                for (std::size_t component = 0; component < 3; ++component) {
                    const float correction =
                        static_cast<float>(sums[vertex * 3 + component]) /
                        static_cast<float>(count) * 0.000001f;
                    context.state_positions[vertex * 3 + component] += correction;
                }
            }
        }
        std::fill(counts.begin(), counts.end(), 0);
        std::fill(sums.begin(), sums.end(), 0);
        ++context.self_contact_solver_iteration_count;
        ++context.self_contact_sum_count;
    }
}

void update_self_collision_primitives_once(
    Mc2ContextV0& context,
    const std::vector<float>& old_positions
) {
    const auto primitive_count = context.self_primitive_flags.size();
    const auto vertex_count = static_cast<std::size_t>(context.vertex_count);
    const bool has_self_parameters =
        context.int_values.size() == static_cast<std::size_t>(kIntCount);
    const bool internal_self_enabled = has_self_parameters &&
        context.int_values[kSelfCollisionMode] != 0;
    const bool interaction_enabled = has_self_parameters &&
        context.int_values[kSelfCollisionSyncMode] != 0;
    if (!context.self_collision_static_ready || primitive_count == 0 ||
        context.setup_kind == 2 ||
        (!internal_self_enabled && !interaction_enabled)) {
        context.self_primitive_dynamic_ready = false;
        context.self_grid_dynamic_ready = false;
        context.self_point_grid_count = 0;
        context.self_edge_grid_count = 0;
        context.self_triangle_grid_count = 0;
        context.self_contact_candidates.clear();
        context.self_candidate_ready = false;
        clear_self_collision_contacts(context);
        context.self_max_primitive_size = 0.0f;
        context.self_grid_size = 0.0f;
        return;
    }
    if (context.self_primitive_dynamic_ready &&
        context.self_primitive_frame == context.frame &&
        context.self_primitive_generation == context.generation) {
        if (internal_self_enabled) {
            update_self_collision_contacts(context, old_positions);
            solve_self_collision_contacts(context);
        }
        return;
    }
    if (context.float_values.size() != static_cast<std::size_t>(kFloatCount) ||
        context.curve_values.size() != static_cast<std::size_t>(kCurveRows * kCurveColumns) ||
        context.state_positions.size() != vertex_count * 3 ||
        old_positions.size() != vertex_count * 3 ||
        context.particle_friction.size() != vertex_count ||
        context.self_particle_indices.size() != primitive_count * 3 ||
        context.self_primitive_depths.size() != primitive_count) {
        context.self_primitive_dynamic_ready = false;
        context.self_grid_dynamic_ready = false;
        context.self_point_grid_count = 0;
        context.self_edge_grid_count = 0;
        context.self_triangle_grid_count = 0;
        context.self_contact_candidates.clear();
        context.self_candidate_ready = false;
        clear_self_collision_contacts(context);
        context.self_max_primitive_size = 0.0f;
        context.self_grid_size = 0.0f;
        return;
    }

    context.self_primitive_inverse_masses.assign(primitive_count * 3, 0.0f);
    context.self_primitive_aabb_min.assign(primitive_count * 3, 0.0f);
    context.self_primitive_aabb_max.assign(primitive_count * 3, 0.0f);
    context.self_primitive_thickness.assign(primitive_count, 0.0f);
    float edge_max_size = 0.0f;
    const float cloth_mass = context.float_values[kClothMass];
    for (std::size_t primitive = 0; primitive < primitive_count; ++primitive) {
        auto flag = context.self_primitive_flags[primitive] & ~kSelfIntersectMask;
        const auto kind = static_cast<std::size_t>((flag >> 24u) & 0x03u);
        const auto axis_count = kind + 1;
        for (std::size_t axis = 0; axis < axis_count; ++axis) {
            const auto vertex = static_cast<std::size_t>(
                context.self_particle_indices[primitive * 3 + axis]
            );
            if (vertex < context.self_particle_intersect_flags.size() &&
                context.self_particle_intersect_flags[vertex] != 0) {
                flag |= 1u << axis;
            }
        }
        context.self_primitive_flags[primitive] = flag;
        if ((flag & kSelfIgnore) != 0u) continue;
        std::array<float, 3> minimum {
            std::numeric_limits<float>::max(),
            std::numeric_limits<float>::max(),
            std::numeric_limits<float>::max(),
        };
        std::array<float, 3> maximum {
            std::numeric_limits<float>::lowest(),
            std::numeric_limits<float>::lowest(),
            std::numeric_limits<float>::lowest(),
        };
        for (std::size_t axis = 0; axis < axis_count; ++axis) {
            const auto vertex = static_cast<std::size_t>(
                context.self_particle_indices[primitive * 3 + axis]
            );
            const bool fixed = (flag & (kSelfFix0 << axis)) != 0u;
            float mass = fixed
                ? 100.0f
                : 1.0f + context.particle_friction[vertex] * 10.0f;
            mass += cloth_mass * 50.0f;
            context.self_primitive_inverse_masses[primitive * 3 + axis] = 1.0f / mass;
            for (std::size_t component = 0; component < 3; ++component) {
                const auto offset = vertex * 3 + component;
                minimum[component] = std::min(
                    minimum[component],
                    std::min(context.state_positions[offset], old_positions[offset])
                );
                maximum[component] = std::max(
                    maximum[component],
                    std::max(context.state_positions[offset], old_positions[offset])
                );
            }
        }
        const float unexpanded_size = std::max({
            maximum[0] - minimum[0],
            maximum[1] - minimum[1],
            maximum[2] - minimum[2],
        });
        if (kind == 1) edge_max_size = std::max(edge_max_size, unexpanded_size);
        const float thickness = sample_curve16(
            context.curve_values,
            kSelfCollisionThicknessCurve,
            context.self_primitive_depths[primitive]
        ) * context.scale_ratio;
        context.self_primitive_thickness[primitive] = thickness;
        for (std::size_t component = 0; component < 3; ++component) {
            context.self_primitive_aabb_min[primitive * 3 + component] =
                minimum[component] - thickness;
            context.self_primitive_aabb_max[primitive * 3 + component] =
                maximum[component] + thickness;
        }
    }
    context.self_max_primitive_size = edge_max_size;
    context.self_grid_size = edge_max_size * 3.0f;
    context.self_primitive_frame = context.frame;
    context.self_primitive_generation = context.generation;
    context.self_primitive_dynamic_ready = true;
    ++context.self_primitive_update_count;
    if (update_self_collision_grid(context) && internal_self_enabled) {
        update_self_collision_candidates(context);
        build_self_collision_contacts(context, old_positions);
        solve_self_collision_contacts(context);
    } else {
        clear_self_collision_contacts(context);
    }
}

void solve_point_collision_once(Mc2ContextV0& context) {
    const auto count = static_cast<std::size_t>(context.vertex_count);
    const bool is_spring = context.setup_kind == 2;
    if (context.int_values.size() != static_cast<std::size_t>(kIntCount) ||
        context.int_values[kCollisionMode] != 1 || context.collider_types.empty() ||
        context.collided_by_groups == 0 || context.state_positions.size() != count * 3 ||
        context.proxy_attributes.size() != count || context.baseline_depths.size() != count ||
        context.particle_friction.size() != count ||
        context.particle_collision_normals.size() != count * 3) return;
    std::vector<float> base_positions(count * 3, 0.0f);
    std::vector<float> inverse_masses(count, 0.0f);
    std::vector<float> collision_radii(count, 0.0f);
    std::vector<float> max_lengths(count, 0.0f);
    if (is_spring) {
        if (context.animated_base_positions.size() != count * 3) return;
        base_positions = context.animated_base_positions;
    }
    for (std::size_t vertex = 0; vertex < count; ++vertex) {
        const auto attribute = context.proxy_attributes[vertex];
        const bool valid = (attribute & 0x03u) != 0u;
        if ((is_spring ? valid : is_move(attribute)) && (attribute & 0x10u) == 0u) {
            inverse_masses[vertex] = 1.0f;
        }
        collision_radii[vertex] = std::max(
            sample_curve16(context.curve_values, kRadiusCurve, context.baseline_depths[vertex]) *
                context.scale_ratio,
            0.0001f
        );
        if (is_spring) {
            max_lengths[vertex] = std::max(
                sample_curve16(
                    context.curve_values,
                    kCollisionLimitDistanceCurve,
                    context.baseline_depths[vertex]
                ) * context.scale_ratio,
                0.0f
            );
        }
    }
    Mc2CollisionView view;
    view.positions = context.state_positions.data();
    view.base_positions = base_positions.data();
    view.velocity_positions = is_spring ? context.velocity_reference_positions.data() : nullptr;
    view.inv_masses = inverse_masses.data();
    view.collision_radii = collision_radii.data();
    view.max_lengths = is_spring ? max_lengths.data() : nullptr;
    view.collision_normals = context.particle_collision_normals.data();
    view.friction = context.particle_friction.data();
    view.collider_types = context.collider_types.data();
    view.collider_group_bits = context.collider_group_bits.data();
    view.collider_centers = context.collider_centers.data();
    view.collider_segment_a = context.collider_segment_a.data();
    view.collider_segment_b = context.collider_segment_b.data();
    view.collider_old_centers = context.collider_old_centers.data();
    view.collider_old_segment_a = context.collider_old_segment_a.data();
    view.collider_old_segment_b = context.collider_old_segment_b.data();
    view.collider_radii = context.collider_radii.data();
    view.vertex_count = context.vertex_count;
    view.collider_count = static_cast<std::int64_t>(context.collider_types.size());
    view.collided_by_groups = context.collided_by_groups;
    view.soft_sphere = is_spring;
    project_collisions_mc2(view);
    ++context.point_collision_solve_count;
}

void solve_edge_collision_once(Mc2ContextV0& context) {
    const auto count = static_cast<std::size_t>(context.vertex_count);
    if (context.int_values.size() != static_cast<std::size_t>(kIntCount) ||
        context.int_values[kCollisionMode] != 2 || context.collider_types.empty() ||
        context.collided_by_groups == 0 || context.proxy_edges.empty() ||
        context.state_positions.size() != count * 3 || context.proxy_attributes.size() != count ||
        context.baseline_depths.size() != count || context.particle_friction.size() != count ||
        context.particle_collision_normals.size() != count * 3) return;
    std::vector<float> collision_radii(count, 0.0f);
    for (std::size_t vertex = 0; vertex < count; ++vertex) {
        collision_radii[vertex] = std::max(
            sample_curve16(context.curve_values, kRadiusCurve, context.baseline_depths[vertex]) *
                context.scale_ratio,
            0.0001f
        );
    }
    Mc2EdgeCollisionView view;
    view.positions = context.state_positions.data();
    view.edges = context.proxy_edges.data();
    view.attributes = context.proxy_attributes.data();
    view.collision_radii = collision_radii.data();
    view.collision_normals = context.particle_collision_normals.data();
    view.friction = context.particle_friction.data();
    view.collider_types = context.collider_types.data();
    view.collider_group_bits = context.collider_group_bits.data();
    view.collider_centers = context.collider_centers.data();
    view.collider_segment_a = context.collider_segment_a.data();
    view.collider_segment_b = context.collider_segment_b.data();
    view.collider_old_centers = context.collider_old_centers.data();
    view.collider_old_segment_a = context.collider_old_segment_a.data();
    view.collider_old_segment_b = context.collider_old_segment_b.data();
    view.collider_radii = context.collider_radii.data();
    view.vertex_count = context.vertex_count;
    view.edge_count = static_cast<std::int64_t>(context.proxy_edges.size() / 2);
    view.collider_count = static_cast<std::int64_t>(context.collider_types.size());
    view.collided_by_groups = context.collided_by_groups;
    view.move_attribute_mask = 0x02u;
    project_edge_collisions_mc2(view);
    ++context.edge_collision_solve_count;
}

void commit_particle_post(Mc2ContextV0& context, float dt, const std::vector<float>& previous_positions) {
    const auto count = static_cast<std::size_t>(context.vertex_count);
    std::vector<float> old_positions = previous_positions;
    std::vector<float> inverse_masses(count, 0.0f);
    for (std::size_t vertex = 0; vertex < count; ++vertex) {
        const auto attribute = context.proxy_attributes[vertex];
        if (is_move(attribute) || (context.setup_kind == 2 && (attribute & 0x03u) != 0u)) {
            inverse_masses[vertex] = 1.0f;
        }
    }
    Mc2PostStepView view;
    view.positions = context.state_positions.data();
    view.old_positions = old_positions.data();
    view.velocity_positions = context.velocity_reference_positions.data();
    view.velocities = context.state_velocities.data();
    view.real_velocities = context.particle_real_velocities.data();
    view.friction = context.particle_friction.data();
    view.static_friction = context.particle_static_friction.data();
    view.collision_normals = context.particle_collision_normals.data();
    view.inv_masses = inverse_masses.data();
    view.vertex_count = context.vertex_count;
    view.step_dt = dt;
    view.dynamic_friction = context.float_values[kCollisionDynamicFriction];
    view.static_friction_speed = context.float_values[kCollisionStaticFriction] * context.scale_ratio;
    view.particle_speed_limit = context.float_values[kParticleSpeedLimit] * context.scale_ratio;
    view.velocity_weight = context.velocity_weight;
    apply_post_step_mc2(view);
}

struct Mc2ContextStepStateV0 {
    Mc2ContextV0* context = nullptr;
    std::vector<float> previous_positions;
    bool center_step_active = false;
};

bool begin_mc2_context_step(
    Mc2ContextV0& context,
    float dt,
    float simulation_power_y,
    float simulation_power_z,
    float simulation_power_w,
    Mc2ContextStepStateV0& state
) {
    state.context = &context;
    state.center_step_active = context.center_dynamic_ready;
    if (state.center_step_active && !evaluate_center_step(context, dt)) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 Center state is incomplete");
        return false;
    }
    if (!context.proxy_static_ready) return true;
    detect_self_collision_intersections_once(context);
    state.previous_positions = context.state_positions;
    if (!predict_particles(context, dt, simulation_power_z, state.center_step_active)) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 particle state is incomplete");
        return false;
    }
    solve_tether_once(context);
    solve_distance_once(context, simulation_power_y);
    solve_angle_once(context, simulation_power_w);
    solve_bending_once(context, simulation_power_y);
    solve_point_collision_once(context);
    solve_edge_collision_once(context);
    solve_distance_once(context, simulation_power_y);
    solve_motion_once(context);
    update_self_collision_primitives_once(context, state.previous_positions);
    return true;
}

void finish_mc2_context_step(
    Mc2ContextStepStateV0& state,
    float dt,
    bool is_final_substep
) {
    auto& context = *state.context;
    if (context.proxy_static_ready) {
        commit_particle_post(context, dt, state.previous_positions);
        if (is_final_substep) solve_self_collision_intersections_final(context);
    }
    if (state.center_step_active) {
        context.center_old_world_position = context.center_now_world_position;
        context.center_old_world_rotation = context.center_now_world_rotation;
    }
    context.bone_output_positions.clear();
    context.bone_output_rotations.clear();
    ++context.step_count;
}

void clear_interaction_scope_state(Mc2InteractionV0& interaction) {
    interaction.aggregate = Mc2ContextV0 {};
    interaction.participants.clear();
    interaction.old_positions.clear();
    interaction.pair_count = 0;
    interaction.candidate_count = 0;
    interaction.contact_count = 0;
    interaction.intersect_record_count = 0;
}

bool interaction_scope_matches(
    Mc2InteractionV0& interaction,
    const std::vector<std::uintptr_t>& identity
) {
    if (interaction.scope_identity == identity) return true;
    clear_interaction_scope_state(interaction);
    interaction.scope_identity = identity;
    ++interaction.scope_revision;
    return false;
}

void append_interaction_primitives(
    Mc2InteractionV0& interaction,
    std::size_t kind
) {
    auto& aggregate = interaction.aggregate;
    for (std::size_t owner = 0; owner < interaction.participants.size(); ++owner) {
        const auto& participant = interaction.participants[owner];
        const auto& context = *participant.context;
        const std::array<std::size_t, 3> starts {
            0,
            static_cast<std::size_t>(context.self_point_primitive_count),
            static_cast<std::size_t>(
                context.self_point_primitive_count + context.self_edge_primitive_count
            ),
        };
        const std::array<std::size_t, 3> counts {
            static_cast<std::size_t>(context.self_point_primitive_count),
            static_cast<std::size_t>(context.self_edge_primitive_count),
            static_cast<std::size_t>(context.self_triangle_primitive_count),
        };
        const auto start = starts[kind];
        const auto count = counts[kind];
        for (std::size_t local = 0; local < count; ++local) {
            const auto primitive = start + local;
            aggregate.self_primitive_flags.push_back(
                context.self_primitive_flags[primitive]
            );
            aggregate.self_primitive_depths.push_back(
                context.self_primitive_depths[primitive]
            );
            aggregate.self_primitive_thickness.push_back(
                context.self_primitive_thickness[primitive]
            );
            aggregate.self_primitive_owner_indices.push_back(
                static_cast<std::int32_t>(owner)
            );
            for (std::size_t axis = 0; axis < 3; ++axis) {
                const auto particle = context.self_particle_indices[primitive * 3 + axis];
                aggregate.self_particle_indices.push_back(
                    static_cast<std::int32_t>(participant.vertex_offset) + particle
                );
                aggregate.self_primitive_inverse_masses.push_back(
                    context.self_primitive_inverse_masses[primitive * 3 + axis]
                );
                aggregate.self_primitive_aabb_min.push_back(
                    context.self_primitive_aabb_min[primitive * 3 + axis]
                );
                aggregate.self_primitive_aabb_max.push_back(
                    context.self_primitive_aabb_max[primitive * 3 + axis]
                );
            }
        }
    }
}

bool build_and_solve_interaction(
    Mc2InteractionV0& interaction,
    const std::vector<Mc2ContextStepStateV0>& states
) {
    auto& aggregate = interaction.aggregate;
    aggregate.self_primitive_flags.clear();
    aggregate.self_particle_indices.clear();
    aggregate.self_primitive_depths.clear();
    aggregate.self_primitive_inverse_masses.clear();
    aggregate.self_primitive_aabb_min.clear();
    aggregate.self_primitive_aabb_max.clear();
    aggregate.self_primitive_thickness.clear();
    aggregate.self_primitive_owner_indices.clear();
    aggregate.self_owner_primary_group_bits.clear();
    aggregate.self_owner_collided_by_groups.clear();
    aggregate.state_positions.clear();
    interaction.old_positions.clear();
    aggregate.vertex_count = 0;
    aggregate.self_max_primitive_size = 0.0f;

    std::size_t vertex_offset = 0;
    for (auto& participant : interaction.participants) {
        participant.vertex_offset = vertex_offset;
        auto& context = *participant.context;
        const auto& previous_positions = states[participant.step_index].previous_positions;
        aggregate.state_positions.insert(
            aggregate.state_positions.end(),
            context.state_positions.begin(),
            context.state_positions.end()
        );
        interaction.old_positions.insert(
            interaction.old_positions.end(),
            previous_positions.begin(),
            previous_positions.end()
        );
        aggregate.self_owner_primary_group_bits.push_back(
            participant.primary_group_bit
        );
        aggregate.self_owner_collided_by_groups.push_back(
            participant.collided_by_groups
        );
        aggregate.self_max_primitive_size = std::max(
            aggregate.self_max_primitive_size,
            context.self_max_primitive_size
        );
        vertex_offset += static_cast<std::size_t>(context.vertex_count);
    }
    aggregate.vertex_count = static_cast<std::int64_t>(vertex_offset);
    aggregate.self_point_primitive_count = 0;
    aggregate.self_edge_primitive_count = 0;
    aggregate.self_triangle_primitive_count = 0;
    for (const auto& participant : interaction.participants) {
        aggregate.self_point_primitive_count +=
            participant.context->self_point_primitive_count;
        aggregate.self_edge_primitive_count +=
            participant.context->self_edge_primitive_count;
        aggregate.self_triangle_primitive_count +=
            participant.context->self_triangle_primitive_count;
    }
    append_interaction_primitives(interaction, 0);
    append_interaction_primitives(interaction, 1);
    append_interaction_primitives(interaction, 2);
    aggregate.self_grid_size = aggregate.self_max_primitive_size * 3.0f;
    aggregate.self_collision_static_ready = true;
    aggregate.self_primitive_dynamic_ready = true;
    aggregate.setup_kind = 0;
    aggregate.int_values.assign(static_cast<std::size_t>(kIntCount), 0);
    aggregate.int_values[kSelfCollisionMode] = 2;
    if (!interaction.participants.empty()) {
        aggregate.frame = interaction.participants.front().context->frame;
        aggregate.generation = interaction.participants.front().context->generation;
    }
    if (!update_self_collision_grid(aggregate)) {
        clear_self_collision_contacts(aggregate);
        interaction.candidate_count = 0;
        interaction.contact_count = 0;
        return false;
    }
    update_self_collision_candidates(aggregate);
    build_self_collision_contacts(aggregate, interaction.old_positions);
    solve_self_collision_contacts(aggregate);
    interaction.candidate_count = static_cast<std::int64_t>(
        aggregate.self_contact_candidates.size() / 3
    );
    interaction.contact_count = static_cast<std::int64_t>(
        aggregate.self_contact_types.size()
    );
    for (const auto& participant : interaction.participants) {
        auto& context = *participant.context;
        const auto offset = participant.vertex_offset * 3;
        std::copy_n(
            aggregate.state_positions.data() + offset,
            context.state_positions.size(),
            context.state_positions.data()
        );
    }
    return true;
}

void finish_interaction_intersections(Mc2InteractionV0& interaction) {
    auto& aggregate = interaction.aggregate;
    if (interaction.participants.empty()) return;
    aggregate.state_positions.clear();
    for (const auto& participant : interaction.participants) {
        const auto& positions = participant.context->state_positions;
        aggregate.state_positions.insert(
            aggregate.state_positions.end(), positions.begin(), positions.end()
        );
    }
    solve_self_collision_intersections_final(aggregate);
    interaction.intersect_record_count = static_cast<std::int64_t>(
        aggregate.self_intersect_records.size() / 5
    );
    if (!aggregate.self_intersect_flags_ready) return;
    for (const auto& participant : interaction.participants) {
        auto& context = *participant.context;
        const auto count = static_cast<std::size_t>(context.vertex_count);
        if (context.self_particle_intersect_flags.size() != count) {
            context.self_particle_intersect_flags.assign(count, 0);
        }
        for (std::size_t vertex = 0; vertex < count; ++vertex) {
            context.self_particle_intersect_flags[vertex] = static_cast<std::uint8_t>(
                context.self_particle_intersect_flags[vertex] != 0 ||
                aggregate.self_particle_intersect_flags[
                    participant.vertex_offset + vertex
                ] != 0
            );
        }
    }
}

template <typename T>
std::int64_t vector_bytes(const std::vector<T>& values) {
    return static_cast<std::int64_t>(values.size() * sizeof(T));
}

std::int64_t estimate_context_bytes(const Mc2ContextV0& context) {
    std::int64_t bytes = static_cast<std::int64_t>(sizeof(Mc2ContextV0));
    bytes += static_cast<std::int64_t>(
        context.static_topology_fingerprint.size() +
        context.static_geometry_fingerprint.size() +
        context.static_surface_fingerprint.size() +
        context.static_config_fingerprint.size() +
        context.static_overall_fingerprint.size()
    );
#define MC2_ADD_VECTOR_BYTES(name) bytes += vector_bytes(context.name)
    MC2_ADD_VECTOR_BYTES(float_values);
    MC2_ADD_VECTOR_BYTES(int_values);
    MC2_ADD_VECTOR_BYTES(curve_values);
    MC2_ADD_VECTOR_BYTES(dynamic_positions);
    MC2_ADD_VECTOR_BYTES(dynamic_rotations);
    MC2_ADD_VECTOR_BYTES(old_dynamic_positions);
    MC2_ADD_VECTOR_BYTES(old_dynamic_rotations);
    MC2_ADD_VECTOR_BYTES(state_positions);
    MC2_ADD_VECTOR_BYTES(state_rotations);
    MC2_ADD_VECTOR_BYTES(state_velocities);
    MC2_ADD_VECTOR_BYTES(velocity_reference_positions);
    MC2_ADD_VECTOR_BYTES(particle_friction);
    MC2_ADD_VECTOR_BYTES(particle_static_friction);
    MC2_ADD_VECTOR_BYTES(particle_collision_normals);
    MC2_ADD_VECTOR_BYTES(particle_real_velocities);
    MC2_ADD_VECTOR_BYTES(animated_base_positions);
    MC2_ADD_VECTOR_BYTES(animated_base_rotations);
    MC2_ADD_VECTOR_BYTES(step_basic_positions);
    MC2_ADD_VECTOR_BYTES(step_basic_rotations);
    MC2_ADD_VECTOR_BYTES(proxy_local_positions);
    MC2_ADD_VECTOR_BYTES(proxy_local_normals);
    MC2_ADD_VECTOR_BYTES(proxy_local_tangents);
    MC2_ADD_VECTOR_BYTES(proxy_uvs);
    MC2_ADD_VECTOR_BYTES(proxy_attributes);
    MC2_ADD_VECTOR_BYTES(proxy_edges);
    MC2_ADD_VECTOR_BYTES(proxy_triangles);
    MC2_ADD_VECTOR_BYTES(baseline_parents);
    MC2_ADD_VECTOR_BYTES(baseline_child_ranges);
    MC2_ADD_VECTOR_BYTES(baseline_child_data);
    MC2_ADD_VECTOR_BYTES(baseline_flags);
    MC2_ADD_VECTOR_BYTES(baseline_ranges);
    MC2_ADD_VECTOR_BYTES(baseline_data);
    MC2_ADD_VECTOR_BYTES(baseline_roots);
    MC2_ADD_VECTOR_BYTES(baseline_depths);
    MC2_ADD_VECTOR_BYTES(baseline_local_positions);
    MC2_ADD_VECTOR_BYTES(baseline_local_rotations);
    MC2_ADD_VECTOR_BYTES(bone_vertex_to_vertex_ranges);
    MC2_ADD_VECTOR_BYTES(bone_vertex_to_vertex_data);
    MC2_ADD_VECTOR_BYTES(bone_vertex_to_triangle_ranges);
    MC2_ADD_VECTOR_BYTES(bone_vertex_to_triangle_data);
    MC2_ADD_VECTOR_BYTES(bone_vertex_bind_pose_positions);
    MC2_ADD_VECTOR_BYTES(bone_vertex_bind_pose_rotations);
    MC2_ADD_VECTOR_BYTES(bone_normal_adjustment_rotations);
    MC2_ADD_VECTOR_BYTES(bone_vertex_to_transform_rotations);
    MC2_ADD_VECTOR_BYTES(bone_output_positions);
    MC2_ADD_VECTOR_BYTES(bone_output_rotations);
    MC2_ADD_VECTOR_BYTES(distance_ranges);
    MC2_ADD_VECTOR_BYTES(distance_targets);
    MC2_ADD_VECTOR_BYTES(distance_rest_signed);
    MC2_ADD_VECTOR_BYTES(bending_quads);
    MC2_ADD_VECTOR_BYTES(bending_rest_angle_or_volume);
    MC2_ADD_VECTOR_BYTES(bending_sign_or_volume);
    MC2_ADD_VECTOR_BYTES(self_primitive_flags);
    MC2_ADD_VECTOR_BYTES(self_particle_indices);
    MC2_ADD_VECTOR_BYTES(self_primitive_depths);
    MC2_ADD_VECTOR_BYTES(self_primitive_inverse_masses);
    MC2_ADD_VECTOR_BYTES(self_primitive_aabb_min);
    MC2_ADD_VECTOR_BYTES(self_primitive_aabb_max);
    MC2_ADD_VECTOR_BYTES(self_primitive_thickness);
    MC2_ADD_VECTOR_BYTES(self_primitive_owner_indices);
    MC2_ADD_VECTOR_BYTES(self_owner_primary_group_bits);
    MC2_ADD_VECTOR_BYTES(self_owner_collided_by_groups);
    MC2_ADD_VECTOR_BYTES(self_primitive_grids);
    MC2_ADD_VECTOR_BYTES(self_grid_hashes);
    MC2_ADD_VECTOR_BYTES(self_grid_starts);
    MC2_ADD_VECTOR_BYTES(self_grid_counts);
    MC2_ADD_VECTOR_BYTES(self_contact_candidates);
    MC2_ADD_VECTOR_BYTES(self_contact_primitive_indices);
    MC2_ADD_VECTOR_BYTES(self_contact_types);
    MC2_ADD_VECTOR_BYTES(self_contact_enabled);
    MC2_ADD_VECTOR_BYTES(self_contact_thickness);
    MC2_ADD_VECTOR_BYTES(self_contact_s);
    MC2_ADD_VECTOR_BYTES(self_contact_t);
    MC2_ADD_VECTOR_BYTES(self_contact_normals);
    MC2_ADD_VECTOR_BYTES(self_contact_keys);
    MC2_ADD_VECTOR_BYTES(self_intersect_records);
    MC2_ADD_VECTOR_BYTES(self_particle_intersect_flags);
    MC2_ADD_VECTOR_BYTES(collider_types);
    MC2_ADD_VECTOR_BYTES(collider_group_bits);
    MC2_ADD_VECTOR_BYTES(collider_centers);
    MC2_ADD_VECTOR_BYTES(collider_segment_a);
    MC2_ADD_VECTOR_BYTES(collider_segment_b);
    MC2_ADD_VECTOR_BYTES(collider_old_centers);
    MC2_ADD_VECTOR_BYTES(collider_old_segment_a);
    MC2_ADD_VECTOR_BYTES(collider_old_segment_b);
    MC2_ADD_VECTOR_BYTES(collider_radii);
    MC2_ADD_VECTOR_BYTES(center_fixed_indices);
    MC2_ADD_VECTOR_BYTES(center_local_position);
    MC2_ADD_VECTOR_BYTES(center_initial_local_gravity_direction);
#undef MC2_ADD_VECTOR_BYTES
    return bytes;
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
        !dict_i64(result, "estimated_bytes", estimate_context_bytes(context)) ||
        !dict_i64(result, "setup_kind", context.setup_kind) ||
        !dict_i64(result, "proxy_static_revision", context.proxy_static_revision) ||
        !dict_i64(result, "baseline_static_revision", context.baseline_static_revision) ||
        !dict_i64(result, "bone_static_revision", context.bone_static_revision) ||
        !dict_i64(result, "distance_static_revision", context.distance_static_revision) ||
        !dict_i64(result, "bending_static_revision", context.bending_static_revision) ||
        !dict_i64(result, "center_static_revision", context.center_static_revision) ||
        !dict_i64(result, "self_collision_static_revision", context.self_collision_static_revision) ||
        !dict_i64(result, "owned_static_take_count", context.owned_static_take_count) ||
        !dict_i64(result, "static_clone_count", context.static_clone_count) ||
        !dict_i64(result, "center_static_rebuild_count", context.center_static_rebuild_count) ||
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
        !dict_i64(result, "self_primitive_count", static_cast<std::int64_t>(context.self_primitive_flags.size())) ||
        !dict_i64(result, "self_point_primitive_count", context.self_point_primitive_count) ||
        !dict_i64(result, "self_edge_primitive_count", context.self_edge_primitive_count) ||
        !dict_i64(result, "self_triangle_primitive_count", context.self_triangle_primitive_count) ||
        !dict_i64(result, "self_point_grid_count", context.self_point_grid_count) ||
        !dict_i64(result, "self_edge_grid_count", context.self_edge_grid_count) ||
        !dict_i64(result, "self_triangle_grid_count", context.self_triangle_grid_count) ||
        !dict_i64(
            result,
            "self_grid_count",
            context.self_point_grid_count +
                context.self_edge_grid_count +
                context.self_triangle_grid_count
        ) ||
        !dict_i64(
            result,
            "self_contact_candidate_count",
            static_cast<std::int64_t>(context.self_contact_candidates.size() / 3)
        ) ||
        !dict_i64(result, "self_contact_cache_count", static_cast<std::int64_t>(context.self_contact_keys.size())) ||
        !dict_i64(
            result,
            "self_contact_enabled_count",
            static_cast<std::int64_t>(std::count(
                context.self_contact_enabled.begin(),
                context.self_contact_enabled.end(),
                static_cast<std::uint8_t>(1)
            ))
        ) ||
        !dict_i64(result, "self_intersect_record_count", static_cast<std::int64_t>(context.self_intersect_records.size() / 5)) ||
        !dict_i64(
            result,
            "self_intersect_particle_count",
            static_cast<std::int64_t>(std::count(
                context.self_particle_intersect_flags.begin(),
                context.self_particle_intersect_flags.end(),
                static_cast<std::uint8_t>(1)
            ))
        ) ||
        !dict_i64(result, "parameter_revision", context.parameter_revision) ||
        !dict_i64(result, "dynamic_revision", context.dynamic_revision) ||
        !dict_i64(result, "collider_revision", context.collider_revision) ||
        !dict_i64(result, "collider_count", static_cast<std::int64_t>(context.collider_types.size())) ||
        !dict_i64(result, "collided_by_groups", context.collided_by_groups) ||
        !dict_float(result, "velocity_weight", context.velocity_weight) ||
        !dict_float(result, "gravity_ratio", context.gravity_ratio) ||
        !dict_float(result, "scale_ratio", context.scale_ratio) ||
        !dict_float(result, "negative_scale_sign", context.negative_scale_sign) ||
        !dict_float(result, "frame_interpolation", context.frame_interpolation) ||
        !dict_i64(result, "reset_count", context.reset_count) ||
        !dict_i64(result, "step_count", context.step_count) ||
        !dict_i64(result, "distance_solve_count", context.distance_solve_count) ||
        !dict_i64(result, "particle_prediction_count", context.particle_prediction_count) ||
        !dict_i64(result, "particle_inertia_count", context.particle_inertia_count) ||
        !dict_i64(result, "bending_solve_count", context.bending_solve_count) ||
        !dict_i64(result, "tether_solve_count", context.tether_solve_count) ||
        !dict_i64(result, "angle_solve_count", context.angle_solve_count) ||
        !dict_i64(result, "motion_solve_count", context.motion_solve_count) ||
        !dict_i64(result, "point_collision_solve_count", context.point_collision_solve_count) ||
        !dict_i64(result, "edge_collision_solve_count", context.edge_collision_solve_count) ||
        !dict_i64(result, "self_primitive_update_count", context.self_primitive_update_count) ||
        !dict_i64(result, "self_grid_update_count", context.self_grid_update_count) ||
        !dict_i64(result, "self_candidate_update_count", context.self_candidate_update_count) ||
        !dict_i64(result, "self_contact_build_count", context.self_contact_build_count) ||
        !dict_i64(result, "self_contact_update_count", context.self_contact_update_count) ||
        !dict_i64(
            result,
            "self_contact_solver_iteration_count",
            context.self_contact_solver_iteration_count
        ) ||
        !dict_i64(result, "self_contact_sum_count", context.self_contact_sum_count) ||
        !dict_i64(
            result,
            "self_intersect_detection_count",
            context.self_intersect_detection_count
        ) ||
        !dict_i64(result, "self_intersect_solve_count", context.self_intersect_solve_count) ||
        !dict_i64(result, "center_step_count", context.center_step_count) ||
        !dict_i64(result, "center_frame_shift_count", context.center_frame_shift_count) ||
        !dict_i64(
            result,
            "center_negative_scale_teleport_count",
            context.center_negative_scale_teleport_count
        ) ||
        !dict_i64(result, "team_options_revision", context.team_options_revision) ||
        !dict_i64(result, "static_fingerprint_revision", context.static_fingerprint_revision) ||
        !dict_i64(result, "baseline_pose_rebuild_count", context.baseline_pose_rebuild_count) ||
        !dict_i64(result, "bone_line_output_count", context.bone_line_output_count) ||
        !dict_i64(result, "bone_triangle_output_count", context.bone_triangle_output_count) ||
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
        !dict_bool(result, "self_collision_static_ready", context.self_collision_static_ready) ||
        !dict_bool(result, "self_primitive_dynamic_ready", context.self_primitive_dynamic_ready) ||
        !dict_bool(result, "self_grid_dynamic_ready", context.self_grid_dynamic_ready) ||
        !dict_bool(result, "self_candidate_ready", context.self_candidate_ready) ||
        !dict_bool(result, "self_contact_ready", context.self_contact_ready) ||
        !dict_bool(
            result,
            "self_intersect_detection_ready",
            context.self_intersect_detection_ready
        ) ||
        !dict_bool(result, "self_intersect_flags_ready", context.self_intersect_flags_ready) ||
        !dict_float(result, "self_max_primitive_size", context.self_max_primitive_size) ||
        !dict_float(result, "self_grid_size", context.self_grid_size) ||
        !dict_bool(result, "tether_enabled", context.tether_enabled) ||
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
        !dict_bool(result, "static_fingerprint_ready", context.static_fingerprint_ready) ||
        !dict_string(result, "static_topology_fingerprint", context.static_topology_fingerprint.c_str()) ||
        !dict_string(result, "static_geometry_fingerprint", context.static_geometry_fingerprint.c_str()) ||
        !dict_string(result, "static_surface_fingerprint", context.static_surface_fingerprint.c_str()) ||
        !dict_string(result, "static_config_fingerprint", context.static_config_fingerprint.c_str()) ||
        !dict_string(result, "static_overall_fingerprint", context.static_overall_fingerprint.c_str()) ||
        !dict_bool(result, "released", context.released)) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}

}  // namespace

PyObject* mc2_interaction_v0_create(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 1) {
        PyErr_SetString(PyExc_TypeError, "mc2_interaction_v0_create expects 1 argument");
        return nullptr;
    }
    const long schema = as_long(PyTuple_GET_ITEM(args, 0), "schema_version");
    if (PyErr_Occurred()) return nullptr;
    if (schema != kSchemaVersion) {
        PyErr_SetString(PyExc_ValueError, "unsupported MC2 interaction schema version");
        return nullptr;
    }
    auto* interaction = new Mc2InteractionV0();
    PyObject* capsule = PyCapsule_New(
        interaction,
        kInteractionCapsuleName,
        destroy_interaction
    );
    if (capsule == nullptr) {
        delete interaction;
        return nullptr;
    }
    return capsule;
}

PyObject* mc2_interaction_v0_inspect(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 1) {
        PyErr_SetString(PyExc_TypeError, "mc2_interaction_v0_inspect expects 1 argument");
        return nullptr;
    }
    auto* interaction = interaction_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(interaction)) return nullptr;
    const auto& aggregate = interaction->aggregate;
    const std::int64_t estimated_bytes = static_cast<std::int64_t>(
        aggregate.state_positions.size() * sizeof(float) +
        interaction->old_positions.size() * sizeof(float) +
        aggregate.self_primitive_flags.size() * sizeof(std::uint32_t) +
        aggregate.self_particle_indices.size() * sizeof(std::int32_t) +
        aggregate.self_primitive_depths.size() * sizeof(float) +
        aggregate.self_primitive_inverse_masses.size() * sizeof(float) +
        aggregate.self_primitive_aabb_min.size() * sizeof(float) +
        aggregate.self_primitive_aabb_max.size() * sizeof(float) +
        aggregate.self_primitive_thickness.size() * sizeof(float) +
        aggregate.self_primitive_owner_indices.size() * sizeof(std::int32_t) +
        aggregate.self_primitive_grids.size() * sizeof(std::int32_t) +
        aggregate.self_grid_hashes.size() * sizeof(std::int32_t) +
        aggregate.self_grid_starts.size() * sizeof(std::int32_t) +
        aggregate.self_grid_counts.size() * sizeof(std::int32_t) +
        aggregate.self_contact_candidates.size() * sizeof(std::int32_t) +
        aggregate.self_contact_primitive_indices.size() * sizeof(std::int32_t) +
        aggregate.self_contact_types.size() * sizeof(std::int32_t) +
        aggregate.self_contact_enabled.size() * sizeof(std::uint8_t) +
        aggregate.self_contact_thickness.size() * sizeof(float) +
        aggregate.self_contact_s.size() * sizeof(float) +
        aggregate.self_contact_t.size() * sizeof(float) +
        aggregate.self_contact_normals.size() * sizeof(float) +
        aggregate.self_intersect_records.size() * sizeof(std::int32_t) +
        aggregate.self_particle_intersect_flags.size() * sizeof(std::uint8_t)
    );
    PyObject* result = PyDict_New();
    if (result == nullptr) return nullptr;
    if (!dict_string(result, "schema", "mc2_interaction_v0") ||
        !dict_i64(result, "schema_version", kSchemaVersion) ||
        !dict_i64(result, "scope_revision", interaction->scope_revision) ||
        !dict_i64(result, "step_count", interaction->step_count) ||
        !dict_i64(
            result,
            "participant_count",
            static_cast<std::int64_t>(interaction->participants.size())
        ) ||
        !dict_i64(result, "pair_count", interaction->pair_count) ||
        !dict_i64(result, "vertex_count", interaction->aggregate.vertex_count) ||
        !dict_i64(
            result,
            "point_primitive_count",
            aggregate.self_point_primitive_count
        ) ||
        !dict_i64(
            result,
            "edge_primitive_count",
            aggregate.self_edge_primitive_count
        ) ||
        !dict_i64(
            result,
            "triangle_primitive_count",
            aggregate.self_triangle_primitive_count
        ) ||
        !dict_i64(
            result,
            "primitive_count",
            static_cast<std::int64_t>(
                interaction->aggregate.self_primitive_flags.size()
            )
        ) ||
        !dict_i64(result, "candidate_count", interaction->candidate_count) ||
        !dict_i64(result, "contact_count", interaction->contact_count) ||
        !dict_i64(
            result,
            "grid_count",
            aggregate.self_point_grid_count +
                aggregate.self_edge_grid_count +
                aggregate.self_triangle_grid_count
        ) ||
        !dict_i64(result, "estimated_bytes", estimated_bytes) ||
        !dict_float(result, "max_primitive_size", aggregate.self_max_primitive_size) ||
        !dict_float(result, "grid_size", aggregate.self_grid_size) ||
        !dict_i64(
            result,
            "intersect_record_count",
            interaction->intersect_record_count
        ) ||
        !dict_bool(result, "released", interaction->released)) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}

PyObject* mc2_interaction_v0_step_group(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 9) {
        PyErr_SetString(PyExc_TypeError, "mc2_interaction_v0_step_group expects 9 arguments");
        return nullptr;
    }
    auto* interaction = interaction_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(interaction)) return nullptr;
    PyObject* context_sequence = PySequence_Fast(
        PyTuple_GET_ITEM(args, 1), "contexts must be a sequence"
    );
    PyObject* group_sequence = PySequence_Fast(
        PyTuple_GET_ITEM(args, 2), "primary_group_bits must be a sequence"
    );
    PyObject* mask_sequence = PySequence_Fast(
        PyTuple_GET_ITEM(args, 3), "collided_by_groups must be a sequence"
    );
    if (context_sequence == nullptr || group_sequence == nullptr || mask_sequence == nullptr) {
        Py_XDECREF(context_sequence);
        Py_XDECREF(group_sequence);
        Py_XDECREF(mask_sequence);
        return nullptr;
    }
    const auto count = PySequence_Fast_GET_SIZE(context_sequence);
    if (PySequence_Fast_GET_SIZE(group_sequence) != count ||
        PySequence_Fast_GET_SIZE(mask_sequence) != count) {
        Py_DECREF(context_sequence);
        Py_DECREF(group_sequence);
        Py_DECREF(mask_sequence);
        PyErr_SetString(PyExc_ValueError, "interaction metadata length mismatch");
        return nullptr;
    }
    const double dt = as_double(PyTuple_GET_ITEM(args, 4), "dt");
    const double simulation_power_y = as_double(
        PyTuple_GET_ITEM(args, 5), "simulation_power_y"
    );
    const double simulation_power_z = as_double(
        PyTuple_GET_ITEM(args, 6), "simulation_power_z"
    );
    const double simulation_power_w = as_double(
        PyTuple_GET_ITEM(args, 7), "simulation_power_w"
    );
    const int final_substep_value = PyObject_IsTrue(PyTuple_GET_ITEM(args, 8));
    if (PyErr_Occurred() || final_substep_value < 0 ||
        !std::isfinite(dt) || dt < 0.0 ||
        !std::isfinite(simulation_power_y) || simulation_power_y < 0.0 ||
        !std::isfinite(simulation_power_z) || simulation_power_z < 0.0 ||
        !std::isfinite(simulation_power_w) || simulation_power_w < 0.0) {
        Py_DECREF(context_sequence);
        Py_DECREF(group_sequence);
        Py_DECREF(mask_sequence);
        if (!PyErr_Occurred()) {
            PyErr_SetString(
                PyExc_ValueError,
                "dt and simulation powers must be finite and non-negative"
            );
        }
        return nullptr;
    }
    if (dt <= kMc2Epsilon) {
        Py_DECREF(context_sequence);
        Py_DECREF(group_sequence);
        Py_DECREF(mask_sequence);
        Py_RETURN_NONE;
    }

    std::vector<Mc2ContextV0*> contexts;
    std::vector<std::int32_t> primary_group_bits;
    std::vector<std::int32_t> collided_by_groups;
    std::vector<std::uintptr_t> scope_identity;
    contexts.reserve(static_cast<std::size_t>(count));
    primary_group_bits.reserve(static_cast<std::size_t>(count));
    collided_by_groups.reserve(static_cast<std::size_t>(count));
    for (Py_ssize_t index = 0; index < count; ++index) {
        auto* context = context_from(PySequence_Fast_GET_ITEM(context_sequence, index));
        if (!ensure_live(context)) {
            Py_DECREF(context_sequence);
            Py_DECREF(group_sequence);
            Py_DECREF(mask_sequence);
            return nullptr;
        }
        if (!context->parameters_ready || !context->dynamic_ready || !context->initialized) {
            Py_DECREF(context_sequence);
            Py_DECREF(group_sequence);
            Py_DECREF(mask_sequence);
            PyErr_SetString(PyExc_RuntimeError, "MC2 V0 context is not ready to step");
            return nullptr;
        }
        const long group_bit = as_long(
            PySequence_Fast_GET_ITEM(group_sequence, index),
            "primary_group_bit"
        );
        const long mask = as_long(
            PySequence_Fast_GET_ITEM(mask_sequence, index),
            "collided_by_groups"
        );
        if (PyErr_Occurred() || group_bit <= 0 || group_bit > 0x8000 ||
            (group_bit & (group_bit - 1)) != 0 || mask < 0 || mask > 0xFFFF) {
            Py_DECREF(context_sequence);
            Py_DECREF(group_sequence);
            Py_DECREF(mask_sequence);
            if (!PyErr_Occurred()) {
                PyErr_SetString(PyExc_ValueError, "invalid MC2 interaction group metadata");
            }
            return nullptr;
        }
        contexts.push_back(context);
        primary_group_bits.push_back(static_cast<std::int32_t>(group_bit));
        collided_by_groups.push_back(static_cast<std::int32_t>(mask));
        const bool interactive = context->setup_kind == 0 &&
            context->int_values.size() == static_cast<std::size_t>(kIntCount) &&
            context->int_values[kSelfCollisionSyncMode] != 0;
        if (interactive) {
            scope_identity.push_back(reinterpret_cast<std::uintptr_t>(context));
            scope_identity.push_back(static_cast<std::uintptr_t>(group_bit));
            scope_identity.push_back(static_cast<std::uintptr_t>(mask));
        }
    }
    Py_DECREF(context_sequence);
    Py_DECREF(group_sequence);
    Py_DECREF(mask_sequence);

    const bool same_scope = interaction_scope_matches(*interaction, scope_identity);
    if (same_scope && !interaction->participants.empty() &&
        interaction->aggregate.self_grid_dynamic_ready) {
        interaction->aggregate.frame = interaction->participants.front().context->frame;
        interaction->aggregate.generation =
            interaction->participants.front().context->generation;
        detect_self_collision_intersections_once(interaction->aggregate);
    }

    std::vector<Mc2ContextStepStateV0> states(contexts.size());
    for (std::size_t index = 0; index < contexts.size(); ++index) {
        if (!begin_mc2_context_step(
                *contexts[index],
                static_cast<float>(dt),
                static_cast<float>(simulation_power_y),
                static_cast<float>(simulation_power_z),
                static_cast<float>(simulation_power_w),
                states[index])) {
            return nullptr;
        }
    }

    interaction->participants.clear();
    for (std::size_t index = 0; index < contexts.size(); ++index) {
        auto* context = contexts[index];
        const bool interactive = context->setup_kind == 0 &&
            context->int_values.size() == static_cast<std::size_t>(kIntCount) &&
            context->int_values[kSelfCollisionSyncMode] != 0 &&
            context->self_primitive_dynamic_ready;
        if (!interactive) continue;
        interaction->participants.push_back(Mc2InteractionParticipantV0 {
            context,
            primary_group_bits[index],
            collided_by_groups[index],
            0,
            index,
        });
    }
    interaction->pair_count = 0;
    for (std::size_t left = 0; left < interaction->participants.size(); ++left) {
        for (std::size_t right = left + 1; right < interaction->participants.size(); ++right) {
            const auto& a = interaction->participants[left];
            const auto& b = interaction->participants[right];
            const bool allows_a = a.collided_by_groups == 0 ||
                (a.collided_by_groups & b.primary_group_bit) != 0;
            const bool allows_b = b.collided_by_groups == 0 ||
                (b.collided_by_groups & a.primary_group_bit) != 0;
            if (allows_a && allows_b) ++interaction->pair_count;
        }
    }
    if (interaction->participants.size() >= 2) {
        build_and_solve_interaction(*interaction, states);
    } else {
        interaction->candidate_count = 0;
        interaction->contact_count = 0;
        interaction->intersect_record_count = 0;
    }

    const bool is_final_substep = final_substep_value != 0;
    for (auto& state : states) {
        finish_mc2_context_step(state, static_cast<float>(dt), is_final_substep);
    }
    if (is_final_substep && interaction->participants.size() >= 2) {
        finish_interaction_intersections(*interaction);
    }
    ++interaction->step_count;
    Py_RETURN_NONE;
}

PyObject* mc2_interaction_v0_read_debug(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 18) {
        PyErr_SetString(PyExc_TypeError, "mc2_interaction_v0_read_debug expects 18 arguments");
        return nullptr;
    }
    auto* interaction = interaction_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(interaction)) return nullptr;
    auto& aggregate = interaction->aggregate;
    if (!aggregate.self_primitive_dynamic_ready) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 interaction debug state is not ready");
        return nullptr;
    }
    const auto vertex_count = static_cast<Py_ssize_t>(aggregate.vertex_count);
    const auto primitive_count = static_cast<Py_ssize_t>(
        aggregate.self_primitive_flags.size()
    );
    const auto candidate_count = static_cast<Py_ssize_t>(
        aggregate.self_contact_candidates.size() / 3
    );
    const auto contact_count = static_cast<Py_ssize_t>(
        aggregate.self_contact_types.size()
    );
    const auto intersect_count = static_cast<Py_ssize_t>(
        aggregate.self_intersect_records.size() / 5
    );
    Buffer positions, particle_indices, owner_indices, aabb_min, aabb_max, thickness;
    Buffer grids, hashes, starts, counts, candidates, contact_indices, contact_types;
    Buffer contact_enabled, contact_normals, intersect_records, particle_flags;
    Buffer* buffers[] = {
        &positions, &particle_indices, &owner_indices, &aabb_min, &aabb_max,
        &thickness, &grids, &hashes, &starts, &counts, &candidates,
        &contact_indices, &contact_types, &contact_enabled, &contact_normals,
        &intersect_records, &particle_flags,
    };
    const char* names[] = {
        "out_positions", "out_particle_indices", "out_owner_indices",
        "out_aabb_min", "out_aabb_max", "out_thickness", "out_grids",
        "out_hashes", "out_starts", "out_counts", "out_candidates",
        "out_contact_indices", "out_contact_types", "out_contact_enabled",
        "out_contact_normals", "out_intersect_records", "out_particle_flags",
    };
    for (std::size_t index = 0; index < 17; ++index) {
        if (!buffers[index]->get(
                PyTuple_GET_ITEM(args, static_cast<Py_ssize_t>(index + 1)),
                PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
                names[index])) {
            return nullptr;
        }
    }
    if (!expect_float32(positions, names[0]) ||
        !expect_2d(positions, names[0], vertex_count, 3) ||
        !expect_int32(particle_indices, names[1]) ||
        !expect_2d(particle_indices, names[1], primitive_count, 3) ||
        !expect_int32(owner_indices, names[2]) ||
        !expect_1d_array(owner_indices, names[2], primitive_count) ||
        !expect_float32(aabb_min, names[3]) ||
        !expect_2d(aabb_min, names[3], primitive_count, 3) ||
        !expect_float32(aabb_max, names[4]) ||
        !expect_2d(aabb_max, names[4], primitive_count, 3) ||
        !expect_float32(thickness, names[5]) ||
        !expect_1d_array(thickness, names[5], primitive_count) ||
        !expect_int32(grids, names[6]) ||
        !expect_2d(grids, names[6], primitive_count, 3) ||
        !expect_int32(hashes, names[7]) ||
        !expect_1d_array(hashes, names[7], primitive_count) ||
        !expect_int32(starts, names[8]) ||
        !expect_1d_array(starts, names[8], primitive_count) ||
        !expect_int32(counts, names[9]) ||
        !expect_1d_array(counts, names[9], primitive_count) ||
        !expect_int32(candidates, names[10]) ||
        !expect_2d(candidates, names[10], candidate_count, 3) ||
        !expect_int32(contact_indices, names[11]) ||
        !expect_2d(contact_indices, names[11], contact_count, 2) ||
        !expect_int32(contact_types, names[12]) ||
        !expect_1d_array(contact_types, names[12], contact_count) ||
        !expect_uint8_scalar_array(contact_enabled, names[13]) ||
        !expect_1d_array(contact_enabled, names[13], contact_count) ||
        !expect_float32(contact_normals, names[14]) ||
        !expect_2d(contact_normals, names[14], contact_count, 3) ||
        !expect_int32(intersect_records, names[15]) ||
        !expect_2d(intersect_records, names[15], intersect_count, 5) ||
        !expect_uint8_scalar_array(particle_flags, names[16]) ||
        !expect_1d_array(particle_flags, names[16], vertex_count)) {
        return nullptr;
    }
    auto copy = [](Buffer& output, const auto& source) {
        if (source.empty()) return;
        std::memcpy(output.view.buf, source.data(), source.size() * sizeof(source[0]));
    };
    copy(positions, aggregate.state_positions);
    copy(particle_indices, aggregate.self_particle_indices);
    copy(owner_indices, aggregate.self_primitive_owner_indices);
    copy(aabb_min, aggregate.self_primitive_aabb_min);
    copy(aabb_max, aggregate.self_primitive_aabb_max);
    copy(thickness, aggregate.self_primitive_thickness);
    copy(grids, aggregate.self_primitive_grids);
    copy(hashes, aggregate.self_grid_hashes);
    copy(starts, aggregate.self_grid_starts);
    copy(counts, aggregate.self_grid_counts);
    copy(candidates, aggregate.self_contact_candidates);
    copy(contact_indices, aggregate.self_contact_primitive_indices);
    copy(contact_types, aggregate.self_contact_types);
    copy(contact_enabled, aggregate.self_contact_enabled);
    copy(contact_normals, aggregate.self_contact_normals);
    copy(intersect_records, aggregate.self_intersect_records);
    copy(particle_flags, aggregate.self_particle_intersect_flags);
    Py_RETURN_NONE;
}

PyObject* mc2_interaction_v0_free(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 1) {
        PyErr_SetString(PyExc_TypeError, "mc2_interaction_v0_free expects 1 argument");
        return nullptr;
    }
    auto* interaction = interaction_from(PyTuple_GET_ITEM(args, 0));
    if (interaction == nullptr) return nullptr;
    release_interaction(*interaction);
    Py_RETURN_NONE;
}

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

PyObject* mc2_context_v0_classify_static_fingerprint(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 6) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_classify_static_fingerprint expects 6 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    std::array<std::string, 5> fingerprints;
    if (!read_static_fingerprints(args, fingerprints)) return nullptr;
    if (!context->static_fingerprint_ready) {
        return PyLong_FromLong(kStaticChangeAll);
    }
    long mask = 0;
    if (context->static_topology_fingerprint != fingerprints[0]) mask |= kStaticChangeTopology;
    if (context->static_geometry_fingerprint != fingerprints[1]) mask |= kStaticChangeGeometry;
    if (context->static_surface_fingerprint != fingerprints[2]) mask |= kStaticChangeSurface;
    if (context->static_config_fingerprint != fingerprints[3]) mask |= kStaticChangeConfig;
    return PyLong_FromLong(mask);
}

PyObject* mc2_context_v0_update_static_fingerprint(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 6) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_update_static_fingerprint expects 6 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    std::array<std::string, 5> fingerprints;
    if (!read_static_fingerprints(args, fingerprints)) return nullptr;
    context->static_topology_fingerprint = std::move(fingerprints[0]);
    context->static_geometry_fingerprint = std::move(fingerprints[1]);
    context->static_surface_fingerprint = std::move(fingerprints[2]);
    context->static_config_fingerprint = std::move(fingerprints[3]);
    context->static_overall_fingerprint = std::move(fingerprints[4]);
    context->static_fingerprint_ready = true;
    ++context->static_fingerprint_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_clone_config_static(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 5) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_clone_config_static expects 5 arguments"
        );
        return nullptr;
    }
    auto* target = context_from(PyTuple_GET_ITEM(args, 0));
    auto* source = context_from(PyTuple_GET_ITEM(args, 1));
    if (!ensure_live(target) || !ensure_live(source)) return nullptr;
    if (target == source) {
        PyErr_SetString(PyExc_ValueError, "config static clone requires distinct contexts");
        return nullptr;
    }
    if (target->vertex_count != source->vertex_count ||
        target->setup_kind != source->setup_kind) {
        PyErr_SetString(PyExc_ValueError, "config static clone context shape mismatch");
        return nullptr;
    }
    if (!source->proxy_static_ready || !source->baseline_static_ready ||
        (source->setup_kind != 0 && !source->bone_static_ready) ||
        !source->distance_static_ready ||
        !source->bending_static_ready || !source->center_static_ready ||
        !source->self_collision_static_ready) {
        PyErr_SetString(PyExc_RuntimeError, "source context static is incomplete");
        return nullptr;
    }
    if (target->proxy_static_ready || target->baseline_static_ready ||
        target->bone_static_ready || target->distance_static_ready ||
        target->bending_static_ready || target->center_static_ready ||
        target->self_collision_static_ready) {
        PyErr_SetString(PyExc_RuntimeError, "target context static is not empty");
        return nullptr;
    }

    Buffer gravity;
    if (!gravity.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "gravity_direction") ||
        !expect_float32(gravity, "gravity_direction") ||
        !expect_1d_array(gravity, "gravity_direction", 3) ||
        !finite_floats(gravity, "gravity_direction")) {
        return nullptr;
    }
    Py_ssize_t task_id_size = 0;
    Py_ssize_t proxy_signature_size = 0;
    const char* task_id = PyUnicode_AsUTF8AndSize(
        PyTuple_GET_ITEM(args, 3), &task_id_size
    );
    const char* proxy_signature = PyUnicode_AsUTF8AndSize(
        PyTuple_GET_ITEM(args, 4), &proxy_signature_size
    );
    if (task_id == nullptr || proxy_signature == nullptr) return nullptr;
    const auto is_ascii = [](const char* value, Py_ssize_t size) {
        return std::all_of(value, value + size, [](char item) {
            return static_cast<unsigned char>(item) < 0x80u;
        });
    };
    if (!is_ascii(task_id, task_id_size) ||
        !is_ascii(proxy_signature, proxy_signature_size)) {
        PyErr_SetString(PyExc_ValueError, "Center signature identities must be ASCII");
        return nullptr;
    }

    target->proxy_local_positions = source->proxy_local_positions;
    target->proxy_local_normals = source->proxy_local_normals;
    target->proxy_local_tangents = source->proxy_local_tangents;
    target->proxy_uvs = source->proxy_uvs;
    target->proxy_attributes = source->proxy_attributes;
    target->proxy_edges = source->proxy_edges;
    target->proxy_triangles = source->proxy_triangles;
    target->baseline_parents = source->baseline_parents;
    target->baseline_child_ranges = source->baseline_child_ranges;
    target->baseline_child_data = source->baseline_child_data;
    target->baseline_flags = source->baseline_flags;
    target->baseline_ranges = source->baseline_ranges;
    target->baseline_data = source->baseline_data;
    target->baseline_roots = source->baseline_roots;
    target->baseline_depths = source->baseline_depths;
    target->baseline_local_positions = source->baseline_local_positions;
    target->baseline_local_rotations = source->baseline_local_rotations;
    target->bone_vertex_to_vertex_ranges = source->bone_vertex_to_vertex_ranges;
    target->bone_vertex_to_vertex_data = source->bone_vertex_to_vertex_data;
    target->bone_vertex_to_triangle_ranges = source->bone_vertex_to_triangle_ranges;
    target->bone_vertex_to_triangle_data = source->bone_vertex_to_triangle_data;
    target->bone_vertex_bind_pose_positions = source->bone_vertex_bind_pose_positions;
    target->bone_vertex_bind_pose_rotations = source->bone_vertex_bind_pose_rotations;
    target->bone_normal_adjustment_rotations = source->bone_normal_adjustment_rotations;
    target->bone_vertex_to_transform_rotations = source->bone_vertex_to_transform_rotations;
    target->distance_ranges = source->distance_ranges;
    target->distance_targets = source->distance_targets;
    target->distance_rest_signed = source->distance_rest_signed;
    target->bending_quads = source->bending_quads;
    target->bending_rest_angle_or_volume = source->bending_rest_angle_or_volume;
    target->bending_sign_or_volume = source->bending_sign_or_volume;
    target->self_primitive_flags = source->self_primitive_flags;
    target->self_particle_indices = source->self_particle_indices;
    target->self_primitive_depths = source->self_primitive_depths;
    target->self_point_primitive_count = source->self_point_primitive_count;
    target->self_edge_primitive_count = source->self_edge_primitive_count;
    target->self_triangle_primitive_count = source->self_triangle_primitive_count;

    Mc2CenterStaticDerived center;
    try {
        const auto to_double = [](const std::vector<float>& values) {
            return std::vector<double>(values.begin(), values.end());
        };
        const auto positions = to_double(target->proxy_local_positions);
        const auto normals = to_double(target->proxy_local_normals);
        const auto tangents = to_double(target->proxy_local_tangents);
        const auto bind_rotations = to_double(target->bone_vertex_bind_pose_rotations);
        const auto* gravity_values = static_cast<const float*>(gravity.view.buf);
        const double gravity_f64[3] = {
            gravity_values[0], gravity_values[1], gravity_values[2],
        };
        center = mc2_build_center_static_derived(
            positions.data(),
            normals.data(),
            tangents.data(),
            target->proxy_attributes.data(),
            bind_rotations.data(),
            static_cast<std::size_t>(target->vertex_count),
            target->proxy_edges.data(),
            target->proxy_edges.size() / 2,
            gravity_f64
        );
    } catch (const std::exception& error) {
        PyErr_SetString(PyExc_ValueError, error.what());
        return nullptr;
    }
    target->center_fixed_indices = std::move(center.fixed_indices);
    target->center_local_position = std::move(center.local_center_position);
    target->center_initial_local_gravity_direction = std::move(
        center.initial_local_gravity_direction
    );

    std::vector<std::uint8_t> signature_payload;
    const char prefix[] = "mc2_center_static_v0\0";
    const auto append_bytes = [&](const void* data, std::size_t size) {
        const auto* begin = static_cast<const std::uint8_t*>(data);
        signature_payload.insert(signature_payload.end(), begin, begin + size);
    };
    append_bytes(prefix, sizeof(prefix) - 1);
    append_bytes(task_id, static_cast<std::size_t>(task_id_size));
    append_bytes(proxy_signature, static_cast<std::size_t>(proxy_signature_size));
    append_bytes(
        target->center_fixed_indices.data(),
        target->center_fixed_indices.size() * sizeof(std::int32_t)
    );
    append_bytes(
        target->center_local_position.data(),
        target->center_local_position.size() * sizeof(float)
    );
    append_bytes(
        target->center_initial_local_gravity_direction.data(),
        target->center_initial_local_gravity_direction.size() * sizeof(float)
    );
    PyObject* hashlib = PyImport_ImportModule("hashlib");
    if (hashlib == nullptr) return nullptr;
    PyObject* payload = PyBytes_FromStringAndSize(
        reinterpret_cast<const char*>(signature_payload.data()),
        static_cast<Py_ssize_t>(signature_payload.size())
    );
    PyObject* digest = payload == nullptr
        ? nullptr
        : PyObject_CallMethod(hashlib, "sha256", "O", payload);
    Py_XDECREF(payload);
    Py_DECREF(hashlib);
    if (digest == nullptr) return nullptr;
    PyObject* signature = PyObject_CallMethod(digest, "hexdigest", nullptr);
    Py_DECREF(digest);
    if (signature == nullptr) return nullptr;

    target->proxy_static_ready = true;
    target->baseline_static_ready = true;
    target->bone_static_ready = source->bone_static_ready;
    target->distance_static_ready = true;
    target->bending_static_ready = true;
    target->self_collision_static_ready = true;
    target->center_static_ready = true;
    target->proxy_static_revision = 1;
    target->baseline_static_revision = 1;
    target->bone_static_revision = source->bone_static_ready ? 1 : 0;
    target->distance_static_revision = 1;
    target->bending_static_revision = 1;
    target->self_collision_static_revision = 1;
    target->center_static_revision = 1;
    target->static_clone_count = source->setup_kind == 0 ? 5 : 6;
    target->center_static_rebuild_count = 1;

    PyObject* result = PyDict_New();
    if (result == nullptr ||
        !dict_i64(
            result,
            "fixed_count",
            static_cast<std::int64_t>(target->center_fixed_indices.size())
        ) ||
        PyDict_SetItemString(result, "center_static_signature", signature) < 0) {
        Py_XDECREF(result);
        Py_DECREF(signature);
        return nullptr;
    }
    Py_DECREF(signature);
    return result;
}

PyObject* mc2_context_v0_update_proxy_static(PyObject*, PyObject* args) {
    const auto argument_count = PyTuple_GET_SIZE(args);
    const bool take_owned = argument_count == 15;
    if (argument_count != 8 && !take_owned) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_proxy_static expects 8 or 15 arguments");
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
    std::vector<float> next_positions;
    std::vector<float> next_normals;
    std::vector<float> next_tangents;
    std::vector<float> next_uvs;
    std::vector<std::uint8_t> next_attributes;
    std::vector<std::int32_t> next_edges;
    std::vector<std::int32_t> next_triangles;
    if (take_owned) {
        auto* owned_positions = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 8), "hotools_native.mc2.proxy_positions.v0", positions
        );
        auto* owned_normals = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 9), "hotools_native.mc2.proxy_normals.v0", normals
        );
        auto* owned_tangents = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 10), "hotools_native.mc2.proxy_tangents.v0", tangents
        );
        auto* owned_uvs = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 11), "hotools_native.mc2.proxy_uvs.v0", uvs
        );
        auto* owned_attributes = validated_owned_values<std::uint8_t>(
            PyTuple_GET_ITEM(args, 12), "hotools_native.mc2.proxy_attributes.v0", attributes
        );
        auto* owned_edges = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 13), "hotools_native.mc2.proxy_edges.v0", edges
        );
        auto* owned_triangles = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 14), "hotools_native.mc2.proxy_triangles.v0", triangles
        );
        if (owned_positions == nullptr || owned_normals == nullptr ||
            owned_tangents == nullptr || owned_uvs == nullptr ||
            owned_attributes == nullptr || owned_edges == nullptr ||
            owned_triangles == nullptr) {
            return nullptr;
        }
        next_positions = std::move(*owned_positions);
        next_normals = std::move(*owned_normals);
        next_tangents = std::move(*owned_tangents);
        next_uvs = std::move(*owned_uvs);
        next_attributes = std::move(*owned_attributes);
        next_edges = std::move(*owned_edges);
        next_triangles = std::move(*owned_triangles);
        ++context->owned_static_take_count;
    } else {
        next_positions = copy_values<float>(positions);
        next_normals = copy_values<float>(normals);
        next_tangents = copy_values<float>(tangents);
        next_uvs = copy_values<float>(uvs);
        next_attributes = copy_values<std::uint8_t>(attributes);
        next_edges = copy_values<std::int32_t>(edges);
        next_triangles = copy_values<std::int32_t>(triangles);
    }
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

PyObject* mc2_context_v0_finalize_proxy_attributes(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_finalize_proxy_attributes expects 2 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->proxy_static_ready) {
        PyErr_SetString(PyExc_RuntimeError, "proxy attributes require proxy static");
        return nullptr;
    }
    Buffer attributes;
    if (!attributes.get(
            PyTuple_GET_ITEM(args, 1),
            PyBUF_FORMAT | PyBUF_ND,
            "vertex_attributes"
        ) ||
        !expect_uint8(attributes, "vertex_attributes") ||
        !expect_1d_array(
            attributes,
            "vertex_attributes",
            static_cast<Py_ssize_t>(context->vertex_count)
        )) {
        return nullptr;
    }
    context->proxy_attributes = copy_values<std::uint8_t>(attributes);
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_baseline_static(PyObject*, PyObject* args) {
    const auto argument_count = PyTuple_GET_SIZE(args);
    const bool take_owned = argument_count == 21;
    if (argument_count != 11 && !take_owned) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_baseline_static expects 11 or 21 arguments");
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
    std::vector<std::int32_t> next_parents;
    std::vector<std::int32_t> next_child_ranges;
    std::vector<std::int32_t> next_child_data;
    std::vector<std::uint8_t> next_flags;
    std::vector<std::int32_t> next_ranges;
    std::vector<std::int32_t> next_data;
    std::vector<std::int32_t> next_roots;
    std::vector<float> next_depths;
    std::vector<float> next_local_positions;
    std::vector<float> next_local_rotations;
    if (take_owned) {
        auto* owned_parents = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 11), "hotools_native.mc2.baseline_parents.v0", parents
        );
        auto* owned_child_ranges = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 12), "hotools_native.mc2.baseline_child_ranges.v0", child_ranges
        );
        auto* owned_child_data = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 13), "hotools_native.mc2.baseline_child_data.v0", child_data
        );
        auto* owned_flags = validated_owned_values<std::uint8_t>(
            PyTuple_GET_ITEM(args, 14), "hotools_native.mc2.baseline_flags.v0", flags
        );
        auto* owned_ranges = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 15), "hotools_native.mc2.baseline_ranges.v0", ranges
        );
        auto* owned_data = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 16), "hotools_native.mc2.baseline_data.v0", data
        );
        auto* owned_roots = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 17), "hotools_native.mc2.baseline_roots.v0", roots
        );
        auto* owned_depths = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 18), "hotools_native.mc2.baseline_depths.v0", depths
        );
        auto* owned_local_positions = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 19), "hotools_native.mc2.baseline_local_positions.v0", local_positions
        );
        auto* owned_local_rotations = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 20), "hotools_native.mc2.baseline_local_rotations.v0", local_rotations
        );
        if (owned_parents == nullptr || owned_child_ranges == nullptr ||
            owned_child_data == nullptr || owned_flags == nullptr ||
            owned_ranges == nullptr || owned_data == nullptr ||
            owned_roots == nullptr || owned_depths == nullptr ||
            owned_local_positions == nullptr || owned_local_rotations == nullptr) {
            return nullptr;
        }
        next_parents = std::move(*owned_parents);
        next_child_ranges = std::move(*owned_child_ranges);
        next_child_data = std::move(*owned_child_data);
        next_flags = std::move(*owned_flags);
        next_ranges = std::move(*owned_ranges);
        next_data = std::move(*owned_data);
        next_roots = std::move(*owned_roots);
        next_depths = std::move(*owned_depths);
        next_local_positions = std::move(*owned_local_positions);
        next_local_rotations = std::move(*owned_local_rotations);
        ++context->owned_static_take_count;
    } else {
        next_parents = copy_values<std::int32_t>(parents);
        next_child_ranges = copy_values<std::int32_t>(child_ranges);
        next_child_data = copy_values<std::int32_t>(child_data);
        next_flags = copy_values<std::uint8_t>(flags);
        next_ranges = copy_values<std::int32_t>(ranges);
        next_data = copy_values<std::int32_t>(data);
        next_roots = copy_values<std::int32_t>(roots);
        next_depths = copy_values<float>(depths);
        next_local_positions = copy_values<float>(local_positions);
        next_local_rotations = copy_values<float>(local_rotations);
    }
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
    const auto argument_count = PyTuple_GET_SIZE(args);
    const bool take_owned = argument_count == 17;
    if (argument_count != 9 && !take_owned) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_update_bone_static expects 9 or 17 arguments"
        );
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

    std::vector<std::int32_t> next_vertex_ranges;
    std::vector<std::int32_t> next_vertex_data;
    std::vector<std::int32_t> next_triangle_ranges;
    std::vector<std::int32_t> next_triangle_data;
    std::vector<float> next_bind_positions;
    std::vector<float> next_bind_rotations;
    std::vector<float> next_adjustment_rotations;
    std::vector<float> next_transform_rotations;
    if (take_owned) {
        auto* owned_vertex_ranges = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 9),
            "hotools_native.mc2.bone_vertex_ranges.v0",
            vertex_ranges
        );
        auto* owned_vertex_data = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 10),
            "hotools_native.mc2.bone_vertex_data.v0",
            vertex_data
        );
        auto* owned_triangle_ranges = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 11),
            "hotools_native.mc2.bone_triangle_ranges.v0",
            triangle_ranges
        );
        auto* owned_triangle_data = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 12),
            "hotools_native.mc2.bone_triangle_data.v0",
            triangle_data
        );
        auto* owned_bind_positions = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 13),
            "hotools_native.mc2.bone_bind_positions.v0",
            bind_positions
        );
        auto* owned_bind_rotations = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 14),
            "hotools_native.mc2.bone_bind_rotations.v0",
            bind_rotations
        );
        auto* owned_adjustment_rotations = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 15),
            "hotools_native.mc2.bone_adjustment_rotations.v0",
            adjustment_rotations
        );
        auto* owned_transform_rotations = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 16),
            "hotools_native.mc2.bone_transform_rotations.v0",
            transform_rotations
        );
        if (owned_vertex_ranges == nullptr || owned_vertex_data == nullptr ||
            owned_triangle_ranges == nullptr || owned_triangle_data == nullptr ||
            owned_bind_positions == nullptr || owned_bind_rotations == nullptr ||
            owned_adjustment_rotations == nullptr || owned_transform_rotations == nullptr) {
            return nullptr;
        }
        next_vertex_ranges = std::move(*owned_vertex_ranges);
        next_vertex_data = std::move(*owned_vertex_data);
        next_triangle_ranges = std::move(*owned_triangle_ranges);
        next_triangle_data = std::move(*owned_triangle_data);
        next_bind_positions = std::move(*owned_bind_positions);
        next_bind_rotations = std::move(*owned_bind_rotations);
        next_adjustment_rotations = std::move(*owned_adjustment_rotations);
        next_transform_rotations = std::move(*owned_transform_rotations);
        ++context->owned_static_take_count;
    } else {
        next_vertex_ranges = copy_values<std::int32_t>(vertex_ranges);
        next_vertex_data = copy_values<std::int32_t>(vertex_data);
        next_triangle_ranges = copy_values<std::int32_t>(triangle_ranges);
        next_triangle_data = copy_values<std::int32_t>(triangle_data);
        next_bind_positions = copy_values<float>(bind_positions);
        next_bind_rotations = copy_values<float>(bind_rotations);
        next_adjustment_rotations = copy_values<float>(adjustment_rotations);
        next_transform_rotations = copy_values<float>(transform_rotations);
    }
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

PyObject* mc2_context_v0_update_frame_producer_static(PyObject*, PyObject* args) {
    const auto argument_count = PyTuple_GET_SIZE(args);
    const bool take_owned = argument_count == 7;
    if (argument_count != 4 && !take_owned) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_update_frame_producer_static expects 4 or 7 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->proxy_static_ready) {
        PyErr_SetString(PyExc_RuntimeError, "frame producer static requires proxy static");
        return nullptr;
    }
    Buffer ranges, data, bind_rotations;
    if (!ranges.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "vertex_to_triangle_ranges") ||
        !data.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "vertex_to_triangle_data") ||
        !bind_rotations.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "vertex_bind_pose_rotations")) {
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->vertex_count);
    Py_ssize_t range_count = 0;
    Py_ssize_t record_count = 0;
    if (!expect_int32_pair_array(ranges, "vertex_to_triangle_ranges", &range_count) ||
        range_count != count ||
        !expect_int32_pair_array(data, "vertex_to_triangle_data", &record_count) ||
        !validate_dense_ranges(ranges, record_count, "vertex_to_triangle_ranges") ||
        !expect_float32(bind_rotations, "vertex_bind_pose_rotations") ||
        !expect_2d(bind_rotations, "vertex_bind_pose_rotations", count, 4) ||
        !finite_floats(bind_rotations, "vertex_bind_pose_rotations") ||
        !validate_quaternions(bind_rotations, "vertex_bind_pose_rotations")) {
        return nullptr;
    }
    const auto* range_values = static_cast<const std::int32_t*>(ranges.view.buf);
    const auto* data_values = static_cast<const std::int32_t*>(data.view.buf);
    const auto triangle_count = static_cast<std::int32_t>(context->proxy_triangles.size() / 3);
    for (Py_ssize_t vertex = 0; vertex < count; ++vertex) {
        const auto start = range_values[vertex * 2];
        const auto length = range_values[vertex * 2 + 1];
        if (length <= 0 || length > 7) {
            PyErr_SetString(PyExc_ValueError, "frame producer requires 1..7 triangle records per vertex");
            return nullptr;
        }
        for (std::int32_t offset = 0; offset < length; ++offset) {
            const auto* record = data_values + (start + offset) * 2;
            if (record[0] < 0 || record[0] > 3 || record[1] < 0 || record[1] >= triangle_count) {
                PyErr_SetString(PyExc_ValueError, "frame producer triangle record is invalid");
                return nullptr;
            }
        }
    }
    std::vector<std::int32_t> next_ranges;
    std::vector<std::int32_t> next_data;
    std::vector<float> next_bind_rotations;
    if (take_owned) {
        auto* owned_ranges = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 4),
            "hotools_native.mc2.frame_triangle_ranges.v0",
            ranges
        );
        auto* owned_data = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 5),
            "hotools_native.mc2.frame_triangle_records.v0",
            data
        );
        auto* owned_bind_rotations = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 6),
            "hotools_native.mc2.frame_bind_rotations.v0",
            bind_rotations
        );
        if (owned_ranges == nullptr || owned_data == nullptr ||
            owned_bind_rotations == nullptr) {
            return nullptr;
        }
        next_ranges = std::move(*owned_ranges);
        next_data = std::move(*owned_data);
        next_bind_rotations = std::move(*owned_bind_rotations);
        ++context->owned_static_take_count;
    } else {
        next_ranges = copy_values<std::int32_t>(ranges);
        next_data = copy_values<std::int32_t>(data);
        next_bind_rotations = copy_values<float>(bind_rotations);
    }
    context->bone_vertex_to_triangle_ranges.swap(next_ranges);
    context->bone_vertex_to_triangle_data.swap(next_data);
    context->bone_vertex_bind_pose_rotations.swap(next_bind_rotations);
    context->bone_normal_adjustment_rotations.assign(
        static_cast<std::size_t>(context->vertex_count) * 4,
        0.0f
    );
    for (std::size_t vertex = 0; vertex < static_cast<std::size_t>(context->vertex_count); ++vertex) {
        context->bone_normal_adjustment_rotations[vertex * 4 + 3] = 1.0f;
    }
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_distance_static(PyObject*, PyObject* args) {
    const auto argument_count = PyTuple_GET_SIZE(args);
    const bool take_owned = argument_count == 7;
    if (argument_count != 4 && !take_owned) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_distance_static expects 4 or 7 arguments");
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
    std::vector<std::int32_t> next_ranges;
    std::vector<std::int32_t> next_targets;
    std::vector<float> next_rests;
    if (take_owned) {
        auto* owned_ranges = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 4), "hotools_native.mc2.distance_ranges.v0", ranges
        );
        auto* owned_targets = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 5), "hotools_native.mc2.distance_targets.v0", targets
        );
        auto* owned_rests = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 6), "hotools_native.mc2.distance_rests.v0", rests
        );
        if (owned_ranges == nullptr || owned_targets == nullptr || owned_rests == nullptr) return nullptr;
        next_ranges = std::move(*owned_ranges);
        next_targets = std::move(*owned_targets);
        next_rests = std::move(*owned_rests);
        ++context->owned_static_take_count;
    } else {
        next_ranges = copy_values<std::int32_t>(ranges);
        next_targets = copy_values<std::int32_t>(targets);
        next_rests = copy_values<float>(rests);
    }
    context->distance_ranges.swap(next_ranges);
    context->distance_targets.swap(next_targets);
    context->distance_rest_signed.swap(next_rests);
    context->distance_static_ready = true;
    ++context->distance_static_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_bending_static(PyObject*, PyObject* args) {
    const auto argument_count = PyTuple_GET_SIZE(args);
    const bool take_owned = argument_count == 7;
    if (argument_count != 4 && !take_owned) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_bending_static expects 4 or 7 arguments");
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
    std::vector<std::int32_t> next_quads;
    std::vector<float> next_rests;
    std::vector<std::int8_t> next_markers;
    if (take_owned) {
        auto* owned_quads = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 4), "hotools_native.mc2.bending_quads.v0", quads
        );
        auto* owned_rests = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 5), "hotools_native.mc2.bending_rests.v0", rests
        );
        auto* owned_markers = validated_owned_values<std::int8_t>(
            PyTuple_GET_ITEM(args, 6), "hotools_native.mc2.bending_markers.v0", markers
        );
        if (owned_quads == nullptr || owned_rests == nullptr || owned_markers == nullptr) return nullptr;
        next_quads = std::move(*owned_quads);
        next_rests = std::move(*owned_rests);
        next_markers = std::move(*owned_markers);
        ++context->owned_static_take_count;
    } else {
        next_quads = copy_values<std::int32_t>(quads);
        next_rests = copy_values<float>(rests);
        next_markers = copy_values<std::int8_t>(markers);
    }
    context->bending_quads.swap(next_quads);
    context->bending_rest_angle_or_volume.swap(next_rests);
    context->bending_sign_or_volume.swap(next_markers);
    context->bending_static_ready = true;
    ++context->bending_static_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_self_collision_static(PyObject*, PyObject* args) {
    const auto argument_count = PyTuple_GET_SIZE(args);
    const bool take_owned = argument_count == 10;
    if (argument_count != 7 && !take_owned) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_self_collision_static expects 7 or 10 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->proxy_static_ready || !context->baseline_static_ready) {
        PyErr_SetString(PyExc_RuntimeError, "proxy and baseline static data must be uploaded first");
        return nullptr;
    }
    Buffer flags, indices, depths;
    if (!flags.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "self_primitive_flags") ||
        !indices.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "self_particle_indices") ||
        !depths.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "self_primitive_depths")) {
        return nullptr;
    }
    const long point_count = as_long(PyTuple_GET_ITEM(args, 4), "self_point_primitive_count");
    const long edge_count = as_long(PyTuple_GET_ITEM(args, 5), "self_edge_primitive_count");
    const long triangle_count = as_long(PyTuple_GET_ITEM(args, 6), "self_triangle_primitive_count");
    if (PyErr_Occurred()) return nullptr;
    if (point_count < 0 || edge_count < 0 || triangle_count < 0) {
        PyErr_SetString(PyExc_ValueError, "self-collision primitive counts cannot be negative");
        return nullptr;
    }
    const Py_ssize_t count = static_cast<Py_ssize_t>(point_count + edge_count + triangle_count);
    if (!expect_uint32_scalar_array(flags, "self_primitive_flags") ||
        flags.view.shape[0] != count ||
        !expect_int32(indices, "self_particle_indices") ||
        !expect_2d(indices, "self_particle_indices", count, 3) ||
        !expect_float32(depths, "self_primitive_depths") ||
        !expect_1d_array(depths, "self_primitive_depths", count) ||
        !finite_floats(depths, "self_primitive_depths") ||
        !validate_indices(indices, context->vertex_count, "self_particle_indices", true)) {
        return nullptr;
    }
    const auto expected_edges = static_cast<long>(context->proxy_edges.size() / 2);
    const auto expected_triangles = static_cast<long>(context->proxy_triangles.size() / 3);
    const auto expected_points = expected_triangles > 0 ? static_cast<long>(context->vertex_count) : 0L;
    if (point_count != expected_points || edge_count != expected_edges || triangle_count != expected_triangles) {
        PyErr_SetString(PyExc_ValueError, "self-collision primitive counts do not match proxy topology");
        return nullptr;
    }
    const auto* flag_values = static_cast<const std::uint32_t*>(flags.view.buf);
    const auto* index_values = static_cast<const std::int32_t*>(indices.view.buf);
    const auto* depth_values = static_cast<const float*>(depths.view.buf);
    for (Py_ssize_t primitive = 0; primitive < count; ++primitive) {
        const std::uint32_t expected_kind = primitive < point_count
            ? 0u : (primitive < point_count + edge_count ? 1u : 2u);
        const auto axis_count = static_cast<Py_ssize_t>(expected_kind + 1u);
        std::uint32_t expected_flag = expected_kind << 24u;
        float expected_depth = 0.0f;
        Py_ssize_t fixed_count = 0;
        for (Py_ssize_t axis = 0; axis < 3; ++axis) {
            const auto value = index_values[primitive * 3 + axis];
            if ((axis < axis_count && value < 0) || (axis >= axis_count && value != -1)) {
                PyErr_SetString(PyExc_ValueError, "self-collision primitive index arity mismatch");
                return nullptr;
            }
            if (axis >= axis_count) continue;
            std::int32_t expected_index = 0;
            if (expected_kind == 0u) {
                expected_index = static_cast<std::int32_t>(primitive);
            } else if (expected_kind == 1u) {
                const auto edge = primitive - point_count;
                expected_index = context->proxy_edges[edge * 2 + axis];
            } else {
                const auto triangle = primitive - point_count - edge_count;
                expected_index = context->proxy_triangles[triangle * 3 + axis];
            }
            if (value != expected_index) {
                PyErr_SetString(PyExc_ValueError, "self-collision primitive proxy order mismatch");
                return nullptr;
            }
            const auto attribute = context->proxy_attributes[expected_index];
            if (!is_move(attribute)) {
                expected_flag |= kSelfFix0 << axis;
                ++fixed_count;
            }
            if ((attribute & 0x03u) == 0u) expected_flag |= kSelfIgnore;
            expected_depth += context->baseline_depths[expected_index];
        }
        if (fixed_count == axis_count) expected_flag |= kSelfAllFix;
        if (flag_values[primitive] != expected_flag) {
            PyErr_SetString(PyExc_ValueError, "self-collision primitive flags mismatch");
            return nullptr;
        }
        expected_depth /= static_cast<float>(axis_count);
        if (depth_values[primitive] < 0.0f || depth_values[primitive] > 1.0f ||
            std::abs(depth_values[primitive] - expected_depth) > 1.0e-6f) {
            PyErr_SetString(PyExc_ValueError, "self-collision primitive depth mismatch");
            return nullptr;
        }
    }
    std::vector<std::uint32_t> next_flags;
    std::vector<std::int32_t> next_indices;
    std::vector<float> next_depths;
    if (take_owned) {
        auto* owned_flags = validated_owned_values<std::uint32_t>(
            PyTuple_GET_ITEM(args, 7), "hotools_native.mc2.self_flags.v0", flags
        );
        auto* owned_indices = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 8), "hotools_native.mc2.self_indices.v0", indices
        );
        auto* owned_depths = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 9), "hotools_native.mc2.self_depths.v0", depths
        );
        if (owned_flags == nullptr || owned_indices == nullptr || owned_depths == nullptr) return nullptr;
        next_flags = std::move(*owned_flags);
        next_indices = std::move(*owned_indices);
        next_depths = std::move(*owned_depths);
        ++context->owned_static_take_count;
    } else {
        next_flags = copy_values<std::uint32_t>(flags);
        next_indices = copy_values<std::int32_t>(indices);
        next_depths = copy_values<float>(depths);
    }
    context->self_primitive_flags.swap(next_flags);
    context->self_particle_indices.swap(next_indices);
    context->self_primitive_depths.swap(next_depths);
    context->self_primitive_inverse_masses.assign(static_cast<std::size_t>(count) * 3, 0.0f);
    context->self_primitive_aabb_min.assign(static_cast<std::size_t>(count) * 3, 0.0f);
    context->self_primitive_aabb_max.assign(static_cast<std::size_t>(count) * 3, 0.0f);
    context->self_primitive_thickness.assign(static_cast<std::size_t>(count), 0.0f);
    context->self_primitive_grids.assign(
        static_cast<std::size_t>(count) * 3,
        kSelfIgnoreGrid
    );
    context->self_grid_hashes.assign(static_cast<std::size_t>(count), 0);
    context->self_grid_starts.assign(static_cast<std::size_t>(count), 0);
    context->self_grid_counts.assign(static_cast<std::size_t>(count), 0);
    context->self_contact_candidates.clear();
    clear_self_collision_contacts(*context);
    context->self_point_primitive_count = point_count;
    context->self_edge_primitive_count = edge_count;
    context->self_triangle_primitive_count = triangle_count;
    context->self_contact_keys.clear();
    context->self_intersect_records.clear();
    context->self_particle_intersect_flags.assign(
        static_cast<std::size_t>(context->vertex_count),
        static_cast<std::uint8_t>(0)
    );
    context->self_intersect_detection_ready = false;
    context->self_intersect_flags_ready = false;
    context->self_collision_static_ready = true;
    context->self_primitive_dynamic_ready = false;
    context->self_grid_dynamic_ready = false;
    context->self_candidate_ready = false;
    context->self_point_grid_count = 0;
    context->self_edge_grid_count = 0;
    context->self_triangle_grid_count = 0;
    context->self_max_primitive_size = 0.0f;
    context->self_grid_size = 0.0f;
    ++context->self_collision_static_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_center_static(PyObject*, PyObject* args) {
    const auto argument_count = PyTuple_GET_SIZE(args);
    const bool take_owned = argument_count == 7;
    if (argument_count != 4 && !take_owned) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_center_static expects 4 or 7 arguments");
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
    std::vector<std::int32_t> next_fixed;
    std::vector<float> next_center;
    std::vector<float> next_gravity;
    if (take_owned) {
        auto* owned_fixed = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, 4), "hotools_native.mc2.center_fixed.v0", fixed_indices
        );
        auto* owned_center = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 5), "hotools_native.mc2.center_position.v0", local_center
        );
        auto* owned_gravity = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, 6), "hotools_native.mc2.center_gravity.v0", local_gravity
        );
        if (owned_fixed == nullptr || owned_center == nullptr || owned_gravity == nullptr) return nullptr;
        next_fixed = std::move(*owned_fixed);
        next_center = std::move(*owned_center);
        next_gravity = std::move(*owned_gravity);
        ++context->owned_static_take_count;
    } else {
        next_fixed = copy_values<std::int32_t>(fixed_indices);
        next_center = copy_values<float>(local_center);
        next_gravity = copy_values<float>(local_gravity);
    }
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

void commit_dynamic_values(
    Mc2ContextV0& context,
    long frame,
    long generation,
    std::vector<float>&& positions,
    std::vector<float>&& rotations,
    float velocity_weight,
    float gravity_ratio,
    float scale_ratio,
    float negative_scale_sign,
    float frame_interpolation
) {
    if (context.dynamic_ready) {
        context.old_dynamic_positions = context.dynamic_positions;
        context.old_dynamic_rotations = context.dynamic_rotations;
    } else {
        context.old_dynamic_positions = positions;
        context.old_dynamic_rotations = rotations;
    }
    context.dynamic_positions = std::move(positions);
    context.dynamic_rotations = std::move(rotations);
    context.frame = frame;
    context.generation = generation;
    context.velocity_weight = velocity_weight;
    context.gravity_ratio = gravity_ratio;
    context.scale_ratio = scale_ratio;
    context.negative_scale_sign = negative_scale_sign;
    context.frame_interpolation = frame_interpolation;
    context.center_dynamic_ready = false;
    context.center_frame_ready = false;
    context.center_result_ready = false;
    context.dynamic_ready = true;
    context.bone_output_positions.clear();
    context.bone_output_rotations.clear();
    ++context.dynamic_revision;
}

PyObject* build_raw_center_pose(
    Mc2ContextV0& context,
    const float* component_position,
    const float* component_rotation,
    const float* component_scale
) {
    Vec3 position {
        component_position[0], component_position[1], component_position[2]
    };
    std::array<float, 4> rotation {
        component_rotation[0], component_rotation[1],
        component_rotation[2], component_rotation[3]
    };
    const bool has_negative_scale =
        component_scale[0] < 0.0f || component_scale[1] < 0.0f || component_scale[2] < 0.0f;
    if (!context.center_fixed_indices.empty()) {
        if (context.bone_vertex_bind_pose_rotations.size() !=
            static_cast<std::size_t>(context.vertex_count) * 4) {
            PyErr_SetString(PyExc_RuntimeError, "raw Center producer has no bind rotations");
            return nullptr;
        }
        position = {};
        Vec3 normal_sum {};
        Vec3 tangent_sum {};
        for (const auto raw_index : context.center_fixed_indices) {
            if (raw_index < 0 || raw_index >= context.vertex_count) {
                PyErr_SetString(PyExc_RuntimeError, "raw Center fixed index is invalid");
                return nullptr;
            }
            const auto index = static_cast<std::size_t>(raw_index);
            position = add(position, load_vector3(context.dynamic_positions, index));
            auto frame_rotation = load_quaternion(context.dynamic_rotations, index);
            if (has_negative_scale) {
                const Vec3 normal = rotate_vector(frame_rotation, {0.0f, 1.0f, 0.0f});
                const Vec3 tangent = rotate_vector(frame_rotation, {0.0f, 0.0f, 1.0f});
                frame_rotation = quaternion_from_forward_up(
                    mul(tangent, -1.0f), mul(normal, -1.0f)
                );
            }
            auto corrected = quaternion_multiply(
                frame_rotation,
                load_quaternion(context.bone_vertex_bind_pose_rotations, index)
            );
            normalize_quaternion(corrected);
            normal_sum = add(normal_sum, rotate_vector(corrected, {0.0f, 1.0f, 0.0f}));
            tangent_sum = add(tangent_sum, rotate_vector(corrected, {0.0f, 0.0f, 1.0f}));
        }
        position = mul(
            position,
            1.0f / static_cast<float>(context.center_fixed_indices.size())
        );
        if (component_scale[0] < 0.0f || component_scale[2] < 0.0f) {
            normal_sum = mul(normal_sum, -1.0f);
        }
        if (component_scale[0] < 0.0f || component_scale[1] < 0.0f) {
            tangent_sum = mul(tangent_sum, -1.0f);
        }
        if (length(normal_sum) <= kMc2Epsilon || length(tangent_sum) <= kMc2Epsilon) {
            PyErr_SetString(PyExc_ValueError, "raw Center orientation is degenerate");
            return nullptr;
        }
        rotation = quaternion_from_forward_up(tangent_sum, normal_sum);
    }
    return Py_BuildValue(
        "(ffffffffff)",
        position.x, position.y, position.z,
        rotation[0], rotation[1], rotation[2], rotation[3],
        component_scale[0], component_scale[1], component_scale[2]
    );
}

bool parse_raw_dynamic_scalars(
    PyObject* args,
    int first_scalar,
    float& velocity_weight,
    float& gravity_ratio,
    float& scale_ratio,
    float& negative_scale_sign,
    float& frame_interpolation
) {
    const double velocity = as_double(PyTuple_GET_ITEM(args, first_scalar), "velocity_weight");
    const double gravity = as_double(PyTuple_GET_ITEM(args, first_scalar + 1), "gravity_ratio");
    const double scale = as_double(PyTuple_GET_ITEM(args, first_scalar + 2), "scale_ratio");
    const double negative = as_double(PyTuple_GET_ITEM(args, first_scalar + 3), "negative_scale_sign");
    const double interpolation = as_double(PyTuple_GET_ITEM(args, first_scalar + 4), "frame_interpolation");
    if (PyErr_Occurred()) return false;
    if (!std::isfinite(velocity) || velocity < 0.0 || velocity > 1.0 ||
        !std::isfinite(gravity) || gravity < 0.0 || gravity > 1.0 ||
        !std::isfinite(scale) || scale <= 0.0 ||
        (negative != -1.0 && negative != 1.0) ||
        !std::isfinite(interpolation) || interpolation < 0.0 || interpolation > 1.0) {
        PyErr_SetString(PyExc_ValueError, "MC2 raw dynamic scalar is out of range");
        return false;
    }
    velocity_weight = static_cast<float>(velocity);
    gravity_ratio = static_cast<float>(gravity);
    scale_ratio = static_cast<float>(scale);
    negative_scale_sign = static_cast<float>(negative);
    frame_interpolation = static_cast<float>(interpolation);
    return true;
}

bool validate_component_pose(
    Buffer& position,
    Buffer& rotation,
    Buffer& scale
) {
    if (!expect_float32(position, "component_position") ||
        !expect_1d_array(position, "component_position", 3) ||
        !expect_float32(rotation, "component_rotation_xyzw") ||
        !expect_1d_array(rotation, "component_rotation_xyzw", 4) ||
        !expect_float32(scale, "component_scale") ||
        !expect_1d_array(scale, "component_scale", 3) ||
        !finite_floats(position, "component_position") ||
        !finite_floats(rotation, "component_rotation_xyzw") ||
        !finite_floats(scale, "component_scale")) {
        return false;
    }
    const auto* rotation_values = static_cast<const float*>(rotation.view.buf);
    const double rotation_length_squared =
        static_cast<double>(rotation_values[0]) * rotation_values[0] +
        static_cast<double>(rotation_values[1]) * rotation_values[1] +
        static_cast<double>(rotation_values[2]) * rotation_values[2] +
        static_cast<double>(rotation_values[3]) * rotation_values[3];
    if (!std::isfinite(rotation_length_squared) ||
        std::abs(rotation_length_squared - 1.0) > 2.0e-5) {
        PyErr_SetString(PyExc_ValueError, "component_rotation_xyzw must be a unit quaternion");
        return false;
    }
    const auto* scale_values = static_cast<const float*>(scale.view.buf);
    if (std::abs(scale_values[0]) <= kMc2Epsilon ||
        std::abs(scale_values[1]) <= kMc2Epsilon ||
        std::abs(scale_values[2]) <= kMc2Epsilon) {
        PyErr_SetString(PyExc_ValueError, "component_scale cannot contain zero");
        return false;
    }
    return true;
}

PyObject* mc2_context_v0_update_mesh_dynamic_raw(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 12) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_mesh_dynamic_raw expects 12 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->parameters_ready || !context->proxy_static_ready) {
        PyErr_SetString(PyExc_RuntimeError, "raw Mesh dynamic requires parameters and proxy static");
        return nullptr;
    }
    const long frame = as_long(PyTuple_GET_ITEM(args, 1), "frame");
    const long generation = as_long(PyTuple_GET_ITEM(args, 2), "generation");
    if (PyErr_Occurred()) return nullptr;
    Buffer positions, component_position, component_rotation, component_scale;
    if (!positions.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "world_positions") ||
        !component_position.get(PyTuple_GET_ITEM(args, 9), PyBUF_FORMAT | PyBUF_ND, "component_position") ||
        !component_rotation.get(PyTuple_GET_ITEM(args, 10), PyBUF_FORMAT | PyBUF_ND, "component_rotation_xyzw") ||
        !component_scale.get(PyTuple_GET_ITEM(args, 11), PyBUF_FORMAT | PyBUF_ND, "component_scale")) {
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->vertex_count);
    if (!expect_float32(positions, "world_positions") ||
        !expect_2d(positions, "world_positions", count, 3) ||
        !finite_floats(positions, "world_positions") ||
        !validate_component_pose(component_position, component_rotation, component_scale)) {
        return nullptr;
    }
    float velocity_weight, gravity_ratio, scale_ratio, negative_scale_sign, frame_interpolation;
    if (!parse_raw_dynamic_scalars(
        args, 4, velocity_weight, gravity_ratio, scale_ratio,
        negative_scale_sign, frame_interpolation
    )) return nullptr;
    auto next_positions = copy_values<float>(positions);
    std::vector<float> next_rotations(static_cast<std::size_t>(context->vertex_count) * 4, 0.0f);
    for (std::size_t vertex = 0; vertex < static_cast<std::size_t>(context->vertex_count); ++vertex) {
        next_rotations[vertex * 4 + 3] = 1.0f;
    }
    if (!apply_bone_triangle_output(*context, next_positions, next_rotations, false)) {
        PyErr_SetString(PyExc_RuntimeError, "raw Mesh frame orientation producer failed");
        return nullptr;
    }
    commit_dynamic_values(
        *context, frame, generation, std::move(next_positions), std::move(next_rotations),
        velocity_weight, gravity_ratio, scale_ratio, negative_scale_sign, frame_interpolation
    );
    return build_raw_center_pose(
        *context,
        static_cast<const float*>(component_position.view.buf),
        static_cast<const float*>(component_rotation.view.buf),
        static_cast<const float*>(component_scale.view.buf)
    );
}

PyObject* mc2_context_v0_update_bone_dynamic_raw(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 13) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_bone_dynamic_raw expects 13 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->parameters_ready || !context->bone_static_ready) {
        PyErr_SetString(PyExc_RuntimeError, "raw Bone dynamic requires parameters and Bone static");
        return nullptr;
    }
    const long frame = as_long(PyTuple_GET_ITEM(args, 1), "frame");
    const long generation = as_long(PyTuple_GET_ITEM(args, 2), "generation");
    if (PyErr_Occurred()) return nullptr;
    Buffer positions, matrices, component_position, component_rotation, component_scale;
    if (!positions.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "world_positions") ||
        !matrices.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "pose_matrices") ||
        !component_position.get(PyTuple_GET_ITEM(args, 10), PyBUF_FORMAT | PyBUF_ND, "component_position") ||
        !component_rotation.get(PyTuple_GET_ITEM(args, 11), PyBUF_FORMAT | PyBUF_ND, "component_rotation_xyzw") ||
        !component_scale.get(PyTuple_GET_ITEM(args, 12), PyBUF_FORMAT | PyBUF_ND, "component_scale")) {
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->vertex_count);
    if (!expect_float32(positions, "world_positions") ||
        !expect_2d(positions, "world_positions", count, 3) ||
        !expect_float32(matrices, "pose_matrices") || matrices.view.ndim != 3 ||
        matrices.view.shape[0] != count || matrices.view.shape[1] != 3 || matrices.view.shape[2] != 3 ||
        !finite_floats(positions, "world_positions") ||
        !finite_floats(matrices, "pose_matrices") ||
        !validate_component_pose(component_position, component_rotation, component_scale)) {
        return nullptr;
    }
    float velocity_weight, gravity_ratio, scale_ratio, negative_scale_sign, frame_interpolation;
    if (!parse_raw_dynamic_scalars(
        args, 5, velocity_weight, gravity_ratio, scale_ratio,
        negative_scale_sign, frame_interpolation
    )) return nullptr;
    auto next_positions = copy_values<float>(positions);
    std::vector<float> next_rotations(static_cast<std::size_t>(context->vertex_count) * 4);
    const auto* matrix_values = static_cast<const float*>(matrices.view.buf);
    const auto* component_rotation_values = static_cast<const float*>(component_rotation.view.buf);
    const std::array<float, 4> component_quaternion {
        component_rotation_values[0], component_rotation_values[1],
        component_rotation_values[2], component_rotation_values[3]
    };
    for (std::size_t vertex = 0; vertex < static_cast<std::size_t>(context->vertex_count); ++vertex) {
        const float* matrix = matrix_values + vertex * 9;
        Vec3 x {matrix[0], matrix[3], matrix[6]};
        Vec3 y {matrix[1], matrix[4], matrix[7]};
        Vec3 z {matrix[2], matrix[5], matrix[8]};
        const float x_length = length(x), y_length = length(y), z_length = length(z);
        if (x_length <= kMc2Epsilon || y_length <= kMc2Epsilon || z_length <= kMc2Epsilon) {
            PyErr_SetString(PyExc_ValueError, "raw Bone pose matrix contains zero scale");
            return nullptr;
        }
        x = mul(x, 1.0f / x_length);
        y = mul(y, 1.0f / y_length);
        z = mul(z, 1.0f / z_length);
        const float determinant = dot(cross(x, y), z);
        if (std::abs(dot(x, y)) > 1.0e-4f || std::abs(dot(x, z)) > 1.0e-4f ||
            std::abs(dot(y, z)) > 1.0e-4f || std::abs(determinant - 1.0f) > 1.0e-4f) {
            PyErr_SetString(PyExc_ValueError, "raw Bone pose matrix must be proper and shear-free");
            return nullptr;
        }
        auto rotation = quaternion_multiply(
            component_quaternion,
            quaternion_from_forward_up(z, y)
        );
        store_quaternion(next_rotations, vertex, rotation);
    }
    commit_dynamic_values(
        *context, frame, generation, std::move(next_positions), std::move(next_rotations),
        velocity_weight, gravity_ratio, scale_ratio, negative_scale_sign, frame_interpolation
    );
    return build_raw_center_pose(
        *context,
        static_cast<const float*>(component_position.view.buf),
        component_rotation_values,
        static_cast<const float*>(component_scale.view.buf)
    );
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

PyObject* mc2_context_v0_derive_center_pose_raw(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_derive_center_pose_raw expects 4 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->center_static_ready || !context->dynamic_ready) {
        PyErr_SetString(PyExc_RuntimeError, "raw Center pose requires static and dynamic data");
        return nullptr;
    }
    Buffer position, rotation, scale;
    if (!position.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "component_position") ||
        !rotation.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "component_rotation") ||
        !scale.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "component_scale")) {
        return nullptr;
    }
    if (!expect_float32(position, "component_position") ||
        !expect_1d_array(position, "component_position", 3) ||
        !finite_floats(position, "component_position") ||
        !expect_float32(rotation, "component_rotation") ||
        !expect_2d(rotation, "component_rotation", 1, 4) ||
        !finite_floats(rotation, "component_rotation") ||
        !validate_quaternions(rotation, "component_rotation") ||
        !expect_float32(scale, "component_scale") ||
        !expect_1d_array(scale, "component_scale", 3) ||
        !finite_floats(scale, "component_scale")) {
        return nullptr;
    }
    const auto* scale_values = static_cast<const float*>(scale.view.buf);
    if (std::abs(scale_values[0]) <= kMc2Epsilon ||
        std::abs(scale_values[1]) <= kMc2Epsilon ||
        std::abs(scale_values[2]) <= kMc2Epsilon) {
        PyErr_SetString(PyExc_ValueError, "component_scale cannot contain zero");
        return nullptr;
    }
    return build_raw_center_pose(
        *context,
        static_cast<const float*>(position.view.buf),
        static_cast<const float*>(rotation.view.buf),
        scale_values
    );
}

PyObject* mc2_context_v0_update_colliders(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 11) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_colliders expects 11 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const long mask = as_long(PyTuple_GET_ITEM(args, 1), "collided_by_groups");
    if (PyErr_Occurred()) return nullptr;
    if (mask < 0 || mask > 0xFFFF) {
        PyErr_SetString(PyExc_ValueError, "collided_by_groups must be in 0..65535");
        return nullptr;
    }

    Buffer types, groups, centers, segment_a, segment_b;
    Buffer old_centers, old_segment_a, old_segment_b, radii;
    if (!types.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "collider_types") ||
        !groups.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "collider_group_bits") ||
        !centers.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "collider_centers") ||
        !segment_a.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "collider_segment_a") ||
        !segment_b.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "collider_segment_b") ||
        !old_centers.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "collider_old_centers") ||
        !old_segment_a.get(PyTuple_GET_ITEM(args, 8), PyBUF_FORMAT | PyBUF_ND, "collider_old_segment_a") ||
        !old_segment_b.get(PyTuple_GET_ITEM(args, 9), PyBUF_FORMAT | PyBUF_ND, "collider_old_segment_b") ||
        !radii.get(PyTuple_GET_ITEM(args, 10), PyBUF_FORMAT | PyBUF_ND, "collider_radii")) {
        return nullptr;
    }
    if (!expect_int32_scalar_array(types, "collider_types")) return nullptr;
    const Py_ssize_t count = types.view.shape[0];
    if (!expect_int32_scalar_array(groups, "collider_group_bits") || groups.view.shape[0] != count ||
        !expect_float32(centers, "collider_centers") || !expect_2d(centers, "collider_centers", count, 3) ||
        !expect_float32(segment_a, "collider_segment_a") || !expect_2d(segment_a, "collider_segment_a", count, 3) ||
        !expect_float32(segment_b, "collider_segment_b") || !expect_2d(segment_b, "collider_segment_b", count, 3) ||
        !expect_float32(old_centers, "collider_old_centers") || !expect_2d(old_centers, "collider_old_centers", count, 3) ||
        !expect_float32(old_segment_a, "collider_old_segment_a") || !expect_2d(old_segment_a, "collider_old_segment_a", count, 3) ||
        !expect_float32(old_segment_b, "collider_old_segment_b") || !expect_2d(old_segment_b, "collider_old_segment_b", count, 3) ||
        !expect_float32(radii, "collider_radii") || radii.view.ndim != 1 || radii.view.shape[0] != count ||
        !finite_floats(centers, "collider_centers") ||
        !finite_floats(segment_a, "collider_segment_a") ||
        !finite_floats(segment_b, "collider_segment_b") ||
        !finite_floats(old_centers, "collider_old_centers") ||
        !finite_floats(old_segment_a, "collider_old_segment_a") ||
        !finite_floats(old_segment_b, "collider_old_segment_b") ||
        !finite_floats(radii, "collider_radii")) {
        return nullptr;
    }
    const auto* type_values = static_cast<const std::int32_t*>(types.view.buf);
    const auto* group_values = static_cast<const std::int32_t*>(groups.view.buf);
    for (Py_ssize_t index = 0; index < count; ++index) {
        if (type_values[index] < 0 || type_values[index] > 3) {
            PyErr_SetString(PyExc_ValueError, "collider type must be in 0..3");
            return nullptr;
        }
        const auto group = group_values[index];
        if (group <= 0 || group > 0x8000 || (group & (group - 1)) != 0) {
            PyErr_SetString(PyExc_ValueError, "collider group bit must be one bit in 1..32768");
            return nullptr;
        }
    }

    context->collided_by_groups = static_cast<std::int32_t>(mask);
    context->collider_types = copy_values<std::int32_t>(types);
    context->collider_group_bits = copy_values<std::int32_t>(groups);
    context->collider_centers = copy_values<float>(centers);
    context->collider_segment_a = copy_values<float>(segment_a);
    context->collider_segment_b = copy_values<float>(segment_b);
    context->collider_old_centers = copy_values<float>(old_centers);
    context->collider_old_segment_a = copy_values<float>(old_segment_a);
    context->collider_old_segment_b = copy_values<float>(old_segment_b);
    context->collider_radii = copy_values<float>(radii);
    ++context->collider_revision;
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
    context->particle_friction.assign(static_cast<std::size_t>(context->vertex_count), 0.0f);
    context->particle_static_friction.assign(static_cast<std::size_t>(context->vertex_count), 0.0f);
    context->particle_collision_normals.assign(static_cast<std::size_t>(context->vertex_count) * 3, 0.0f);
    context->particle_real_velocities.assign(static_cast<std::size_t>(context->vertex_count) * 3, 0.0f);
    context->step_basic_positions = context->dynamic_positions;
    context->step_basic_rotations = context->dynamic_rotations;
    context->center_dynamic_ready = false;
    context->center_frame_ready = false;
    context->center_result_ready = false;
    context->bone_output_positions.clear();
    context->bone_output_rotations.clear();
    context->self_contact_keys.clear();
    context->self_intersect_records.clear();
    context->self_particle_intersect_flags.assign(
        static_cast<std::size_t>(context->vertex_count),
        static_cast<std::uint8_t>(0)
    );
    context->self_intersect_detection_ready = false;
    context->self_intersect_flags_ready = false;
    for (auto& flag : context->self_primitive_flags) {
        flag &= ~kSelfIntersectMask;
    }
    context->self_contact_candidates.clear();
    clear_self_collision_contacts(*context);
    context->self_primitive_dynamic_ready = false;
    context->self_grid_dynamic_ready = false;
    context->self_candidate_ready = false;
    context->self_point_grid_count = 0;
    context->self_edge_grid_count = 0;
    context->self_triangle_grid_count = 0;
    context->self_max_primitive_size = 0.0f;
    context->self_grid_size = 0.0f;
    context->initialized = true;
    ++context->reset_count;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_set_tether_enabled(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_set_tether_enabled expects 2 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const int enabled = PyObject_IsTrue(PyTuple_GET_ITEM(args, 1));
    if (enabled < 0) return nullptr;
    context->tether_enabled = enabled != 0;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_set_setup_kind(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_set_setup_kind expects 2 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const long setup_kind = as_long(PyTuple_GET_ITEM(args, 1), "setup_kind");
    if (PyErr_Occurred()) return nullptr;
    if (setup_kind < 0 || setup_kind > 2) {
        PyErr_SetString(PyExc_ValueError, "setup_kind must be in 0..2");
        return nullptr;
    }
    if (context->proxy_static_ready || context->baseline_static_ready || context->initialized) {
        PyErr_SetString(PyExc_RuntimeError, "setup_kind is immutable after context initialization");
        return nullptr;
    }
    context->setup_kind = static_cast<std::int32_t>(setup_kind);
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_step(PyObject*, PyObject* args) {
    const Py_ssize_t argument_count = PyTuple_GET_SIZE(args);
    if (argument_count != 4 && argument_count != 5 && argument_count != 6) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_step expects 4, 5, or 6 arguments");
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
    const double simulation_power_w = argument_count >= 5
        ? as_double(PyTuple_GET_ITEM(args, 4), "simulation_power_w")
        : 1.0;
    const int final_substep_value = argument_count == 6
        ? PyObject_IsTrue(PyTuple_GET_ITEM(args, 5))
        : 1;
    if (final_substep_value < 0) return nullptr;
    const bool is_final_substep = final_substep_value != 0;
    if (PyErr_Occurred()) return nullptr;
    if (!std::isfinite(dt) || dt < 0.0 ||
        !std::isfinite(simulation_power_y) || simulation_power_y < 0.0 ||
        !std::isfinite(simulation_power_z) || simulation_power_z < 0.0 ||
        !std::isfinite(simulation_power_w) || simulation_power_w < 0.0) {
        PyErr_SetString(PyExc_ValueError, "dt and simulation powers must be finite and non-negative");
        return nullptr;
    }
    if (!context->parameters_ready || !context->dynamic_ready || !context->initialized) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 context is not ready to step");
        return nullptr;
    }
    if (dt <= kMc2Epsilon) Py_RETURN_NONE;
    Mc2ContextStepStateV0 state;
    if (!begin_mc2_context_step(
            *context,
            static_cast<float>(dt),
            static_cast<float>(simulation_power_y),
            static_cast<float>(simulation_power_z),
            static_cast<float>(simulation_power_w),
            state)) {
        return nullptr;
    }
    finish_mc2_context_step(state, static_cast<float>(dt), is_final_substep);
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

PyObject* mc2_context_v0_read_self_collision_primitives(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 5) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_self_collision_primitives expects 5 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->self_primitive_dynamic_ready) {
        PyErr_SetString(PyExc_RuntimeError, "self-collision primitive dynamics are not ready");
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->self_primitive_flags.size());
    Buffer inverse_masses, aabb_min, aabb_max, thickness;
    if (!inverse_masses.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_inverse_masses"
        ) ||
        !aabb_min.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_aabb_min"
        ) ||
        !aabb_max.get(
            PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_aabb_max"
        ) ||
        !thickness.get(
            PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_thickness"
        )) {
        return nullptr;
    }
    if (!expect_float32(inverse_masses, "out_self_inverse_masses") ||
        !expect_2d(inverse_masses, "out_self_inverse_masses", count, 3) ||
        !expect_float32(aabb_min, "out_self_aabb_min") ||
        !expect_2d(aabb_min, "out_self_aabb_min", count, 3) ||
        !expect_float32(aabb_max, "out_self_aabb_max") ||
        !expect_2d(aabb_max, "out_self_aabb_max", count, 3) ||
        !expect_float32(thickness, "out_self_thickness") ||
        !expect_1d_array(thickness, "out_self_thickness", count)) {
        return nullptr;
    }
    std::memcpy(
        inverse_masses.view.buf,
        context->self_primitive_inverse_masses.data(),
        context->self_primitive_inverse_masses.size() * sizeof(float)
    );
    std::memcpy(
        aabb_min.view.buf,
        context->self_primitive_aabb_min.data(),
        context->self_primitive_aabb_min.size() * sizeof(float)
    );
    std::memcpy(
        aabb_max.view.buf,
        context->self_primitive_aabb_max.data(),
        context->self_primitive_aabb_max.size() * sizeof(float)
    );
    std::memcpy(
        thickness.view.buf,
        context->self_primitive_thickness.data(),
        context->self_primitive_thickness.size() * sizeof(float)
    );
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_self_collision_grid(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 6) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_self_collision_grid expects 6 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->self_grid_dynamic_ready) {
        PyErr_SetString(PyExc_RuntimeError, "self-collision grid is not ready");
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->self_primitive_flags.size());
    Buffer particle_indices, grids, hashes, starts, counts;
    if (!particle_indices.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_particle_indices"
        ) ||
        !grids.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_primitive_grids"
        ) ||
        !hashes.get(
            PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_grid_hashes"
        ) ||
        !starts.get(
            PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_grid_starts"
        ) ||
        !counts.get(
            PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_grid_counts"
        )) {
        return nullptr;
    }
    if (!expect_int32(particle_indices, "out_self_particle_indices") ||
        !expect_2d(particle_indices, "out_self_particle_indices", count, 3) ||
        !expect_int32(grids, "out_self_primitive_grids") ||
        !expect_2d(grids, "out_self_primitive_grids", count, 3) ||
        !expect_int32(hashes, "out_self_grid_hashes") ||
        !expect_1d_array(hashes, "out_self_grid_hashes", count) ||
        !expect_int32(starts, "out_self_grid_starts") ||
        !expect_1d_array(starts, "out_self_grid_starts", count) ||
        !expect_int32(counts, "out_self_grid_counts") ||
        !expect_1d_array(counts, "out_self_grid_counts", count)) {
        return nullptr;
    }
    std::memcpy(
        particle_indices.view.buf,
        context->self_particle_indices.data(),
        context->self_particle_indices.size() * sizeof(std::int32_t)
    );
    std::memcpy(
        grids.view.buf,
        context->self_primitive_grids.data(),
        context->self_primitive_grids.size() * sizeof(std::int32_t)
    );
    std::memcpy(
        hashes.view.buf,
        context->self_grid_hashes.data(),
        context->self_grid_hashes.size() * sizeof(std::int32_t)
    );
    std::memcpy(
        starts.view.buf,
        context->self_grid_starts.data(),
        context->self_grid_starts.size() * sizeof(std::int32_t)
    );
    std::memcpy(
        counts.view.buf,
        context->self_grid_counts.data(),
        context->self_grid_counts.size() * sizeof(std::int32_t)
    );
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_self_collision_candidates(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_self_collision_candidates expects 2 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->self_candidate_ready) {
        PyErr_SetString(PyExc_RuntimeError, "self-collision candidates are not ready");
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->self_contact_candidates.size() / 3);
    Buffer candidates;
    if (!candidates.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_candidates"
        )) {
        return nullptr;
    }
    if (!expect_int32(candidates, "out_self_contact_candidates") ||
        !expect_2d(candidates, "out_self_contact_candidates", count, 3)) {
        return nullptr;
    }
    std::memcpy(
        candidates.view.buf,
        context->self_contact_candidates.data(),
        context->self_contact_candidates.size() * sizeof(std::int32_t)
    );
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_self_collision_contacts(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 8) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_self_collision_contacts expects 8 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->self_contact_ready) {
        PyErr_SetString(PyExc_RuntimeError, "self-collision contacts are not ready");
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->self_contact_types.size());
    Buffer indices, types, enabled, thickness, s, t, normals;
    if (!indices.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_indices"
        ) ||
        !types.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_types"
        ) ||
        !enabled.get(
            PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_enabled"
        ) ||
        !thickness.get(
            PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_thickness"
        ) ||
        !s.get(
            PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_s"
        ) ||
        !t.get(
            PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_t"
        ) ||
        !normals.get(
            PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_normals"
        )) {
        return nullptr;
    }
    if (!expect_int32(indices, "out_self_contact_indices") ||
        !expect_2d(indices, "out_self_contact_indices", count, 2) ||
        !expect_int32(types, "out_self_contact_types") ||
        !expect_1d_array(types, "out_self_contact_types", count) ||
        !expect_uint8_scalar_array(enabled, "out_self_contact_enabled") ||
        !expect_1d_array(enabled, "out_self_contact_enabled", count) ||
        !expect_float32(thickness, "out_self_contact_thickness") ||
        !expect_1d_array(thickness, "out_self_contact_thickness", count) ||
        !expect_float32(s, "out_self_contact_s") ||
        !expect_1d_array(s, "out_self_contact_s", count) ||
        !expect_float32(t, "out_self_contact_t") ||
        !expect_1d_array(t, "out_self_contact_t", count) ||
        !expect_float32(normals, "out_self_contact_normals") ||
        !expect_2d(normals, "out_self_contact_normals", count, 3)) {
        return nullptr;
    }
    std::memcpy(indices.view.buf, context->self_contact_primitive_indices.data(),
                context->self_contact_primitive_indices.size() * sizeof(std::int32_t));
    std::memcpy(types.view.buf, context->self_contact_types.data(),
                context->self_contact_types.size() * sizeof(std::int32_t));
    std::memcpy(enabled.view.buf, context->self_contact_enabled.data(),
                context->self_contact_enabled.size() * sizeof(std::uint8_t));
    std::memcpy(thickness.view.buf, context->self_contact_thickness.data(),
                context->self_contact_thickness.size() * sizeof(float));
    std::memcpy(s.view.buf, context->self_contact_s.data(),
                context->self_contact_s.size() * sizeof(float));
    std::memcpy(t.view.buf, context->self_contact_t.data(),
                context->self_contact_t.size() * sizeof(float));
    std::memcpy(normals.view.buf, context->self_contact_normals.data(),
                context->self_contact_normals.size() * sizeof(float));
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_self_collision_intersections(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_self_collision_intersections expects 4 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->self_intersect_detection_ready && !context->self_intersect_flags_ready) {
        PyErr_SetString(PyExc_RuntimeError, "self-collision intersections are not ready");
        return nullptr;
    }
    const auto record_count = static_cast<Py_ssize_t>(
        context->self_intersect_records.size() / 5
    );
    const auto vertex_count = static_cast<Py_ssize_t>(context->vertex_count);
    const auto primitive_count = static_cast<Py_ssize_t>(context->self_primitive_flags.size());
    Buffer records, particle_flags, primitive_flags;
    if (!records.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_intersect_records"
        ) ||
        !particle_flags.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_particle_intersect_flags"
        ) ||
        !primitive_flags.get(
            PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_primitive_flags"
        )) {
        return nullptr;
    }
    if (!expect_int32(records, "out_self_intersect_records") ||
        !expect_2d(records, "out_self_intersect_records", record_count, 5) ||
        !expect_uint8_scalar_array(particle_flags, "out_self_particle_intersect_flags") ||
        !expect_1d_array(
            particle_flags,
            "out_self_particle_intersect_flags",
            vertex_count
        ) ||
        !expect_uint32_scalar_array(primitive_flags, "out_self_primitive_flags") ||
        !expect_1d_array(primitive_flags, "out_self_primitive_flags", primitive_count)) {
        return nullptr;
    }
    std::memcpy(
        records.view.buf,
        context->self_intersect_records.data(),
        context->self_intersect_records.size() * sizeof(std::int32_t)
    );
    std::memcpy(
        particle_flags.view.buf,
        context->self_particle_intersect_flags.data(),
        context->self_particle_intersect_flags.size() * sizeof(std::uint8_t)
    );
    std::memcpy(
        primitive_flags.view.buf,
        context->self_primitive_flags.data(),
        context->self_primitive_flags.size() * sizeof(std::uint32_t)
    );
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_bone_output(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 3) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_read_bone_output expects 3 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!build_bone_output(*context)) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 Bone output state is incomplete");
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
