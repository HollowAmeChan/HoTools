#include "mc2_api.hpp"

#include "mc2_context_internal.hpp"
#include "mc2_context_helpers.hpp"
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
namespace mc2_internal {

using namespace py;

constexpr const char* kCapsuleName = "hotools_native.MC2ContextV0";
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
constexpr float kFrictionMass = 3.0f;
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
    context.external_contact_debug_records.clear();
    context.debug_constraint_origins.clear();
    context.debug_constraint_corrections.clear();
    context.debug_distance_record_origins.clear();
    context.debug_distance_record_corrections.clear();
    context.debug_distance_record_lengths.clear();
    context.debug_distance_record_rests.clear();
    context.debug_distance_record_valid.clear();
    context.debug_bending_record_origins.clear();
    context.debug_bending_record_corrections.clear();
    context.debug_bending_record_valid.clear();
    context.debug_motion_record_origins.clear();
    context.debug_motion_record_corrections.clear();
    context.debug_motion_record_valid.clear();
    context.debug_angle_record_origins.clear();
    context.debug_angle_record_corrections.clear();
    context.debug_angle_record_currents.clear();
    context.debug_angle_record_limits.clear();
    context.debug_angle_record_children.clear();
    context.debug_angle_record_parents.clear();
    context.debug_angle_record_valid.clear();
    context.animated_base_positions.clear();
    context.animated_base_rotations.clear();
    context.step_basic_positions.clear();
    context.step_basic_rotations.clear();
    context.proxy_local_positions.clear();
    context.proxy_local_normals.clear();
    context.proxy_local_tangents.clear();
    context.proxy_uvs.clear();
    context.frame_triangle_uvs.clear();
    context.proxy_attributes.clear();
    context.proxy_radius_multipliers.clear();
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
    context.self_topology_neighbor_keys.clear();
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

bool expect_3d(
    const Buffer& buffer,
    const char* name,
    Py_ssize_t first,
    Py_ssize_t second,
    Py_ssize_t third
) {
    if (buffer.view.ndim != 3 || buffer.view.shape == nullptr ||
        buffer.view.shape[0] != first || buffer.view.shape[1] != second ||
        buffer.view.shape[2] != third) {
        PyErr_Format(PyExc_ValueError, "%s shape mismatch", name);
        return false;
    }
    return true;
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
                      bool allow_minus_one) {
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

float collision_radius_for_vertex(const Mc2ContextV0& context, std::size_t vertex) {
    if (vertex >= context.baseline_depths.size() ||
        vertex >= context.proxy_radius_multipliers.size()) {
        return 0.0f;
    }
    const float multiplier = context.proxy_radius_multipliers[vertex];
    if (multiplier <= kMc2Epsilon) return 0.0f;
    return std::max(
        sample_curve16(context.curve_values, kRadiusCurve, context.baseline_depths[vertex]) *
            multiplier * context.scale_ratio,
        0.0001f
    );
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
                (1.0f - depth * std::sqrt(depth));
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

std::array<float, 4> quaternion_from_to(Vec3 first, Vec3 second, float ratio) {
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
    const bool has_corner_uvs = context.frame_triangle_uvs.size() == triangle_count * 6;
    if ((!has_corner_uvs && context.proxy_uvs.size() != vertex_count * 2) ||
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

        const auto uv_value = [&](std::size_t corner, std::size_t vertex, std::size_t component) {
            return has_corner_uvs
                ? context.frame_triangle_uvs[triangle * 6 + corner * 2 + component]
                : context.proxy_uvs[vertex * 2 + component];
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
    const float volume_error = rest - volume;
    if (std::fabs(volume_error) <= std::max(1.0e-6f, std::fabs(rest) * 2.0e-6f)) {
        return false;
    }
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
    lambda = stiffness * volume_error / lambda;
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
    const float angle_error = rest - phi;
    if (std::fabs(angle_error) <= 1.0e-3f) return false;
    const float lambda = angle_error / denominator * stiffness;
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

void capture_bending_records_once(
    Mc2ContextV0& context,
    float simulation_power_y
) {
    const auto record_count = context.bending_rest_angle_or_volume.size();
    const auto vertex_count = static_cast<std::size_t>(context.vertex_count);
    const auto role_count = record_count * 4;
    if ((context.debug_constraint_request_mask & kDebugConstraintBending) == 0 ||
        !context.bending_static_ready ||
        context.int_values.size() != static_cast<std::size_t>(kIntCount) ||
        context.int_values[3] == 0 ||
        context.float_values.size() != static_cast<std::size_t>(kFloatCount) ||
        context.state_positions.size() != vertex_count * 3 ||
        context.proxy_attributes.size() != vertex_count ||
        context.baseline_depths.size() != vertex_count ||
        context.bending_quads.size() != role_count ||
        context.bending_sign_or_volume.size() != record_count ||
        context.debug_bending_record_origins.size() != role_count * 3 ||
        context.debug_bending_record_corrections.size() != role_count * 3 ||
        context.debug_bending_record_valid.size() != record_count) {
        return;
    }
    const float stiffness = std::max(
        0.0f,
        std::min(1.0f, context.float_values[kBendingStiffness] * simulation_power_y)
    );
    if (stiffness < 1.0e-6f) return;

    std::vector<std::int32_t> counts(vertex_count, 0);
    for (std::size_t record = 0; record < record_count; ++record) {
        Vec3 positions[4];
        float inv_mass[4];
        std::size_t vertices[4];
        for (int role = 0; role < 4; ++role) {
            vertices[role] = static_cast<std::size_t>(
                context.bending_quads[record * 4 + role]
            );
            const auto source_offset = vertices[role] * 3;
            const auto debug_offset = (record * 4 + role) * 3;
            positions[role] = {
                context.state_positions[source_offset + 0],
                context.state_positions[source_offset + 1],
                context.state_positions[source_offset + 2],
            };
            inv_mass[role] = bending_inverse_mass(context, vertices[role]);
            context.debug_bending_record_origins[debug_offset + 0] = positions[role].x;
            context.debug_bending_record_origins[debug_offset + 1] = positions[role].y;
            context.debug_bending_record_origins[debug_offset + 2] = positions[role].z;
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
                raw_rest * (marker < 0 ? -1.0f : 1.0f) *
                    context.negative_scale_sign,
                stiffness,
                correction
            );
        if (!solved) continue;
        context.debug_bending_record_valid[record] = 1;
        for (int role = 0; role < 4; ++role) {
            const auto debug_offset = (record * 4 + role) * 3;
            context.debug_bending_record_corrections[debug_offset + 0] =
                static_cast<float>(static_cast<std::int32_t>(correction[role].x * 1000000.0f));
            context.debug_bending_record_corrections[debug_offset + 1] =
                static_cast<float>(static_cast<std::int32_t>(correction[role].y * 1000000.0f));
            context.debug_bending_record_corrections[debug_offset + 2] =
                static_cast<float>(static_cast<std::int32_t>(correction[role].z * 1000000.0f));
            ++counts[vertices[role]];
        }
    }
    for (std::size_t record = 0; record < record_count; ++record) {
        if (context.debug_bending_record_valid[record] == 0) continue;
        for (int role = 0; role < 4; ++role) {
            const auto vertex = static_cast<std::size_t>(
                context.bending_quads[record * 4 + role]
            );
            const auto debug_offset = (record * 4 + role) * 3;
            const float scale = is_move(context.proxy_attributes[vertex]) &&
                counts[vertex] > 0
                ? 0.000001f / static_cast<float>(counts[vertex])
                : 0.0f;
            context.debug_bending_record_corrections[debug_offset + 0] *= scale;
            context.debug_bending_record_corrections[debug_offset + 1] *= scale;
            context.debug_bending_record_corrections[debug_offset + 2] *= scale;
        }
    }
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
        context.proxy_local_positions.size() != count * 3 ||
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
            const float static_local_dx =
                context.proxy_local_positions[target_offset + 0] -
                context.proxy_local_positions[offset + 0];
            const float static_local_dy =
                context.proxy_local_positions[target_offset + 1] -
                context.proxy_local_positions[offset + 1];
            const float static_local_dz =
                context.proxy_local_positions[target_offset + 2] -
                context.proxy_local_positions[offset + 2];
            const float static_scaled_x = static_local_dx *
                context.center_initial_scale[0] * context.scale_ratio;
            const float static_scaled_y = static_local_dy *
                context.center_initial_scale[1] * context.scale_ratio;
            const float static_scaled_z = static_local_dz *
                context.center_initial_scale[2] * context.scale_ratio;
            const float local_scaled_rest = std::sqrt(
                static_scaled_x * static_scaled_x +
                static_scaled_y * static_scaled_y +
                static_scaled_z * static_scaled_z
            );
            const float scaled_static_rest = local_scaled_rest > kMc2Epsilon
                ? local_scaled_rest
                : static_rest * context.scale_ratio;
            const float rest =
                scaled_static_rest * (1.0f - context.animation_pose_ratio) +
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

void capture_distance_records_once(
    Mc2ContextV0& context,
    float simulation_power_y,
    std::size_t debug_phase
) {
    const auto vertex_count = static_cast<std::size_t>(context.vertex_count);
    const auto total_records = context.distance_targets.size();
    if ((context.debug_constraint_request_mask & kDebugConstraintDistance) == 0 ||
        debug_phase >= 2 ||
        !context.distance_static_ready ||
        context.state_positions.size() != vertex_count * 3 ||
        context.proxy_attributes.size() != vertex_count ||
        context.baseline_depths.size() != vertex_count ||
        context.proxy_local_positions.size() != vertex_count * 3 ||
        context.distance_ranges.size() != vertex_count * 2 ||
        context.distance_targets.size() != context.distance_rest_signed.size() ||
        context.debug_distance_record_origins.size() != total_records * 2 * 3 ||
        context.debug_distance_record_corrections.size() != total_records * 2 * 3 ||
        context.debug_distance_record_lengths.size() != total_records * 2 ||
        context.debug_distance_record_rests.size() != total_records * 2 ||
        context.debug_distance_record_valid.size() != total_records * 2) {
        return;
    }

    std::vector<float> positions = context.state_positions;
    const auto phase_record_start = debug_phase * total_records;
    for (std::size_t vertex = 0; vertex < vertex_count; ++vertex) {
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
        const float current_x = positions[offset + 0];
        const float current_y = positions[offset + 1];
        const float current_z = positions[offset + 2];
        const float inverse_mass = distance_inverse_mass(context, vertex);
        float add_x = 0.0f;
        float add_y = 0.0f;
        float add_z = 0.0f;
        std::int32_t add_count = 0;
        for (std::int32_t local = 0; local < record_count; ++local) {
            const auto record = static_cast<std::size_t>(start + local);
            const auto target = static_cast<std::size_t>(
                context.distance_targets[record]
            );
            const auto target_offset = target * 3;
            const float dx = positions[target_offset + 0] - current_x;
            const float dy = positions[target_offset + 1] - current_y;
            const float dz = positions[target_offset + 2] - current_z;
            const float rest_signed = context.distance_rest_signed[record];
            const float static_rest = std::fabs(rest_signed);
            const auto debug_record = phase_record_start + record;
            const auto debug_offset = debug_record * 3;
            context.debug_distance_record_origins[debug_offset + 0] = current_x;
            context.debug_distance_record_origins[debug_offset + 1] = current_y;
            context.debug_distance_record_origins[debug_offset + 2] = current_z;
            if (static_rest <= kMc2Epsilon) {
                add_x = dx * 0.5f;
                add_y = dy * 0.5f;
                add_z = dz * 0.5f;
                for (std::int32_t previous = 0; previous < local; ++previous) {
                    const auto previous_record = static_cast<std::size_t>(
                        start + previous
                    );
                    const auto previous_offset =
                        (phase_record_start + previous_record) * 3;
                    context.debug_distance_record_corrections[previous_offset + 0] = 0.0f;
                    context.debug_distance_record_corrections[previous_offset + 1] = 0.0f;
                    context.debug_distance_record_corrections[previous_offset + 2] = 0.0f;
                }
                context.debug_distance_record_corrections[debug_offset + 0] = add_x;
                context.debug_distance_record_corrections[debug_offset + 1] = add_y;
                context.debug_distance_record_corrections[debug_offset + 2] = add_z;
                context.debug_distance_record_lengths[debug_record] = std::sqrt(
                    dx * dx + dy * dy + dz * dz
                );
                context.debug_distance_record_rests[debug_record] = 0.0f;
                context.debug_distance_record_valid[debug_record] = 1;
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
            const float static_local_dx =
                context.proxy_local_positions[target_offset + 0] -
                context.proxy_local_positions[offset + 0];
            const float static_local_dy =
                context.proxy_local_positions[target_offset + 1] -
                context.proxy_local_positions[offset + 1];
            const float static_local_dz =
                context.proxy_local_positions[target_offset + 2] -
                context.proxy_local_positions[offset + 2];
            const float static_scaled_x = static_local_dx *
                context.center_initial_scale[0] * context.scale_ratio;
            const float static_scaled_y = static_local_dy *
                context.center_initial_scale[1] * context.scale_ratio;
            const float static_scaled_z = static_local_dz *
                context.center_initial_scale[2] * context.scale_ratio;
            const float local_scaled_rest = std::sqrt(
                static_scaled_x * static_scaled_x +
                static_scaled_y * static_scaled_y +
                static_scaled_z * static_scaled_z
            );
            const float scaled_static_rest = local_scaled_rest > kMc2Epsilon
                ? local_scaled_rest
                : static_rest * context.scale_ratio;
            const float rest =
                scaled_static_rest * (1.0f - context.animation_pose_ratio) +
                animated_rest * context.animation_pose_ratio;
            const float local_stiffness = rest_signed < 0.0f
                ? stiffness * kDistanceHorizontalStiffness
                : stiffness;
            const float correction =
                ((distance - rest) * local_stiffness /
                 (inverse_mass + target_inverse_mass)) /
                distance;
            const float record_x = dx * correction * inverse_mass;
            const float record_y = dy * correction * inverse_mass;
            const float record_z = dz * correction * inverse_mass;
            add_x += record_x;
            add_y += record_y;
            add_z += record_z;
            context.debug_distance_record_corrections[debug_offset + 0] = record_x;
            context.debug_distance_record_corrections[debug_offset + 1] = record_y;
            context.debug_distance_record_corrections[debug_offset + 2] = record_z;
            context.debug_distance_record_lengths[debug_record] = distance;
            context.debug_distance_record_rests[debug_record] = rest;
            context.debug_distance_record_valid[debug_record] = 1;
            ++add_count;
        }
        if (add_count <= 0) continue;
        const float inverse_count = 1.0f / static_cast<float>(add_count);
        for (std::int32_t local = 0; local < record_count; ++local) {
            const auto record = static_cast<std::size_t>(start + local);
            const auto debug_record = phase_record_start + record;
            if (context.debug_distance_record_valid[debug_record] == 0) continue;
            const auto debug_offset = debug_record * 3;
            context.debug_distance_record_corrections[debug_offset + 0] *= inverse_count;
            context.debug_distance_record_corrections[debug_offset + 1] *= inverse_count;
            context.debug_distance_record_corrections[debug_offset + 2] *= inverse_count;
        }
        positions[offset + 0] = current_x + add_x * inverse_count;
        positions[offset + 1] = current_y + add_y * inverse_count;
        positions[offset + 2] = current_z + add_z * inverse_count;
    }
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

void capture_angle_records_once(
    Mc2ContextV0& context,
    float simulation_power_w
) {
    const auto count = static_cast<std::size_t>(context.vertex_count);
    const auto data_count = context.baseline_data.size();
    const auto record_count = data_count * kMc2AngleIterationCount * 2;
    if ((context.debug_constraint_request_mask & kDebugConstraintAngle) == 0 ||
        context.int_values.size() != static_cast<std::size_t>(kIntCount) ||
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
        data_count == 0 ||
        context.debug_angle_record_origins.size() != record_count * 2 * 3 ||
        context.debug_angle_record_corrections.size() != record_count * 2 * 3 ||
        context.debug_angle_record_currents.size() != record_count ||
        context.debug_angle_record_limits.size() != record_count ||
        context.debug_angle_record_children.size() != record_count ||
        context.debug_angle_record_parents.size() != record_count ||
        context.debug_angle_record_valid.size() != record_count) {
        return;
    }
    const bool use_restoration = context.int_values[kUseAngleRestoration] != 0;
    const bool use_limit = context.int_values[kUseAngleLimit] != 0;
    if (!use_restoration && !use_limit) return;

    std::vector<float> positions = context.state_positions;
    std::vector<float> velocity_positions = context.velocity_reference_positions;
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
                    context.curve_values, kAngleRestorationCurve, depth
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
    for (std::size_t branch = 0; branch < 2; ++branch) {
        for (std::size_t iteration = 0;
             iteration < static_cast<std::size_t>(kMc2AngleIterationCount);
             ++iteration) {
            for (std::size_t data = 0; data < data_count; ++data) {
                const auto record =
                    (branch * kMc2AngleIterationCount + iteration) * data_count + data;
                const auto child = context.baseline_data[data];
                context.debug_angle_record_children[record] = child;
                context.debug_angle_record_parents[record] =
                    child >= 0 && static_cast<std::size_t>(child) < count
                    ? context.baseline_parents[static_cast<std::size_t>(child)]
                    : -1;
            }
        }
    }

    Mc2AngleConstraintView view;
    view.positions = positions.data();
    view.inv_masses = inverse_masses.data();
    view.parent_indices = context.baseline_parents.data();
    view.baseline_start = baseline_start.data();
    view.baseline_count = baseline_count.data();
    view.baseline_data = context.baseline_data.data();
    view.step_basic_positions = context.step_basic_positions.data();
    view.step_basic_rotations = context.step_basic_rotations.data();
    view.restoration_values = use_restoration ? restoration_values.data() : nullptr;
    view.limit_values = use_limit ? limit_values.data() : nullptr;
    view.velocity_positions = velocity_positions.data();
    view.vertex_count = context.vertex_count;
    view.line_count = static_cast<std::int64_t>(line_count);
    view.baseline_data_count = static_cast<std::int64_t>(data_count);
    view.restoration_velocity_attenuation =
        context.float_values[kAngleRestorationVelocityAttenuation];
    view.restoration_gravity_falloff =
        context.float_values[kAngleRestorationGravityFalloff] *
        (1.0f - context.center_gravity_dot);
    view.limit_stiffness = context.float_values[kAngleLimitStiffness];
    view.explicit_enable_flags = true;
    view.restoration_enabled = use_restoration;
    view.limit_enabled = use_limit;
    view.debug_record_origins = context.debug_angle_record_origins.data();
    view.debug_record_corrections = context.debug_angle_record_corrections.data();
    view.debug_record_currents = context.debug_angle_record_currents.data();
    view.debug_record_limits = context.debug_angle_record_limits.data();
    view.debug_record_valid = context.debug_angle_record_valid.data();
    project_angle_constraints_mc2(view);
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

void capture_motion_records_once(Mc2ContextV0& context) {
    const auto count = static_cast<std::size_t>(context.vertex_count);
    const auto record_count = count * 2;
    if ((context.debug_constraint_request_mask & kDebugConstraintMotion) == 0 ||
        context.int_values.size() != static_cast<std::size_t>(kIntCount) ||
        context.float_values.size() != static_cast<std::size_t>(kFloatCount) ||
        context.state_positions.size() != count * 3 ||
        context.velocity_reference_positions.size() != count * 3 ||
        context.animated_base_positions.size() != count * 3 ||
        context.animated_base_rotations.size() != count * 4 ||
        context.proxy_attributes.size() != count ||
        context.baseline_depths.size() != count ||
        context.debug_motion_record_origins.size() != record_count * 3 ||
        context.debug_motion_record_corrections.size() != record_count * 3 ||
        context.debug_motion_record_valid.size() != record_count) {
        return;
    }
    const bool use_max_distance = context.int_values[kUseMaxDistance] != 0;
    const bool use_backstop = context.int_values[kUseBackstop] != 0;
    if (!use_max_distance && !use_backstop) return;

    std::vector<float> positions = context.state_positions;
    std::vector<float> velocity_positions = context.velocity_reference_positions;
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
        const float motion_depth =
            context.baseline_depths[vertex] * context.baseline_depths[vertex];
        if (use_max_distance) {
            max_distances[vertex] = std::max(
                0.0f,
                sample_curve16(context.curve_values, kMaxDistanceCurve, motion_depth)
            );
        }
        if (use_backstop) {
            backstop_radii[vertex] = std::max(
                0.0f, context.float_values[kBackstopRadius]
            );
            backstop_distances[vertex] = std::max(
                0.0f,
                sample_curve16(
                    context.curve_values, kBackstopDistanceCurve, motion_depth
                )
            );
        }
    }

    Mc2MotionConstraintView view;
    view.positions = positions.data();
    view.base_positions = context.animated_base_positions.data();
    view.base_rotations = context.animated_base_rotations.data();
    view.inv_masses = inverse_masses.data();
    view.max_distances = max_distances.data();
    view.stiffness_values = stiffness_values.data();
    view.backstop_radii = backstop_radii.data();
    view.backstop_distances = backstop_distances.data();
    view.velocity_positions = velocity_positions.data();
    view.vertex_count = context.vertex_count;
    view.normal_axis = context.int_values[kNormalAxis];
    view.explicit_enable_flags = true;
    view.max_distance_enabled = use_max_distance;
    view.backstop_enabled = use_backstop;
    view.debug_record_origins = context.debug_motion_record_origins.data();
    view.debug_record_corrections = context.debug_motion_record_corrections.data();
    view.debug_record_valid = context.debug_motion_record_valid.data();
    project_motion_constraints_mc2(view);
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

bool self_primitives_are_topology_neighbors(
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
            const auto target = context.self_particle_indices[right * 3 + right_axis];
            if (particle == target) return true;
            const auto key = self_particle_pair_key(particle, target);
            if (std::binary_search(
                    context.self_topology_neighbor_keys.begin(),
                    context.self_topology_neighbor_keys.end(),
                    key)) {
                return true;
            }
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
    context.self_intersect_flags_ready = false;
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
                            self_primitives_are_topology_neighbors(context, edge, triangle)) {
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
        context.self_intersect_records.clear();
        context.self_intersect_flags_ready = false;
        return;
    }
    const auto record_count = context.self_intersect_records.size() / 5;
    std::vector<std::int32_t> confirmed_records;
    confirmed_records.reserve(context.self_intersect_records.size());
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
        confirmed_records.insert(
            confirmed_records.end(),
            particles,
            particles + 5
        );
    }
    context.self_intersect_records.swap(confirmed_records);
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
                                self_primitives_are_topology_neighbors(
                                    context,
                                    primitive,
                                    target
                                )) {
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
    context.self_contact_debug_ready = false;
    context.debug_self_contact_corrections.clear();
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
    const auto contact_count = context.self_contact_types.size();
    const bool capture_debug = context.self_contact_debug_requested;
    context.self_contact_debug_ready = false;
    if (capture_debug) {
        context.debug_self_contact_corrections.assign(contact_count * 2 * 3, 0.0f);
    } else {
        context.debug_self_contact_corrections.clear();
    }
    std::vector<std::int32_t> counts(vertex_count, 0);
    std::vector<std::int32_t> sums(vertex_count * 3, 0);
    struct DebugContribution {
        std::size_t contact;
        std::size_t side;
        std::size_t vertex;
        std::array<std::int32_t, 3> fixed;
    };
    std::vector<DebugContribution> debug_contributions;
    auto accumulate = [&](
        std::size_t vertex,
        Vec3 correction,
        std::size_t contact,
        std::size_t side
    ) {
        ++counts[vertex];
        const std::array<float, 3> values {correction.x, correction.y, correction.z};
        if (capture_debug) {
            DebugContribution debug {contact, side, vertex, {}};
            for (std::size_t component = 0; component < 3; ++component) {
                const auto fixed = static_cast<std::int32_t>(
                    values[component] * 1000000.0f
                );
                add_wrapped_int32(sums[vertex * 3 + component], fixed);
                debug.fixed[component] = fixed;
            }
            debug_contributions.push_back(debug);
            return;
        }
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
                if (can_write(primitive0, 0)) accumulate(a0, correction_a0, contact, 0);
                if (can_write(primitive0, 1)) accumulate(a1, correction_a1, contact, 0);
                if (can_write(primitive1, 0)) accumulate(b0, correction_b0, contact, 1);
                if (can_write(primitive1, 1)) accumulate(b1, correction_b1, contact, 1);
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
                if (can_write(primitive0, 0)) accumulate(point_index, correction, contact, 0);
                if (can_write(primitive1, 0)) accumulate(b0, correction_b0, contact, 1);
                if (can_write(primitive1, 1)) accumulate(b1, correction_b1, contact, 1);
                if (can_write(primitive1, 2)) accumulate(b2, correction_b2, contact, 1);
            }
        }
        if (capture_debug) {
            for (const auto& contribution : debug_contributions) {
                const auto count = counts[contribution.vertex];
                if (count <= 0) continue;
                const auto start = (contribution.contact * 2 + contribution.side) * 3;
                for (std::size_t component = 0; component < 3; ++component) {
                    context.debug_self_contact_corrections[start + component] +=
                        static_cast<float>(contribution.fixed[component]) /
                        static_cast<float>(count) * 0.000001f;
                }
            }
            debug_contributions.clear();
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
    context.self_contact_debug_ready = capture_debug;
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
        float primitive_radius_multiplier = 0.0f;
        for (std::size_t axis = 0; axis < axis_count; ++axis) {
            const auto vertex = static_cast<std::size_t>(
                context.self_particle_indices[primitive * 3 + axis]
            );
            if (vertex < context.proxy_radius_multipliers.size()) {
                primitive_radius_multiplier += context.proxy_radius_multipliers[vertex];
            }
        }
        primitive_radius_multiplier /= static_cast<float>(axis_count);
        const float thickness = sample_curve16(
            context.curve_values,
            kSelfCollisionThicknessCurve,
            context.self_primitive_depths[primitive]
        ) * primitive_radius_multiplier * context.scale_ratio;
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
        collision_radii[vertex] = collision_radius_for_vertex(context, vertex);
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
    view.debug_contacts = context.external_contact_debug_requested
        ? &context.external_contact_debug_records
        : nullptr;
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
        collision_radii[vertex] = collision_radius_for_vertex(context, vertex);
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
    view.debug_contacts = context.external_contact_debug_requested
        ? &context.external_contact_debug_records
        : nullptr;
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

void begin_constraint_debug_pass(
    const Mc2ContextV0& context,
    std::uint32_t request_bit,
    std::vector<float>& before
) {
    before.clear();
    if ((context.debug_constraint_request_mask & request_bit) == 0) return;
    before = context.state_positions;
}

void finish_constraint_debug_pass(
    Mc2ContextV0& context,
    std::uint32_t request_bit,
    std::size_t pass_index,
    const std::vector<float>& before
) {
    if ((context.debug_constraint_request_mask & request_bit) == 0 ||
        before.size() != context.state_positions.size()) {
        return;
    }
    const auto stride = context.state_positions.size();
    const auto required = stride * debug_constraint_pass_count(
        context.debug_constraint_request_mask
    );
    if (context.debug_constraint_origins.size() != required) {
        context.debug_constraint_origins.assign(required, 0.0f);
    }
    if (context.debug_constraint_corrections.size() != required) {
        context.debug_constraint_corrections.assign(required, 0.0f);
    }
    const auto start = debug_constraint_pass_offset(
        context.debug_constraint_request_mask, pass_index
    ) * stride;
    for (std::size_t index = 0; index < stride; ++index) {
        context.debug_constraint_origins[start + index] = before[index];
        context.debug_constraint_corrections[start + index] =
            context.state_positions[index] - before[index];
    }
    context.debug_constraint_ready_mask |= request_bit;
}

bool begin_mc2_context_step(
    Mc2ContextV0& context,
    float dt,
    float simulation_power_y,
    float simulation_power_z,
    float simulation_power_w,
    Mc2ContextStepStateV0& state
) {
    state.context = &context;
    context.debug_constraint_ready_mask = 0;
    context.debug_constraint_origins.clear();
    context.debug_constraint_corrections.clear();
    context.debug_distance_record_phase_mask = 0;
    context.debug_distance_record_ready = false;
    context.debug_distance_record_origins.clear();
    context.debug_distance_record_corrections.clear();
    context.debug_distance_record_lengths.clear();
    context.debug_distance_record_rests.clear();
    context.debug_distance_record_valid.clear();
    context.debug_bending_record_ready = false;
    context.debug_bending_record_origins.clear();
    context.debug_bending_record_corrections.clear();
    context.debug_bending_record_valid.clear();
    context.debug_motion_record_ready = false;
    context.debug_motion_record_origins.clear();
    context.debug_motion_record_corrections.clear();
    context.debug_motion_record_valid.clear();
    context.debug_angle_record_ready = false;
    context.debug_angle_record_origins.clear();
    context.debug_angle_record_corrections.clear();
    context.debug_angle_record_currents.clear();
    context.debug_angle_record_limits.clear();
    context.debug_angle_record_children.clear();
    context.debug_angle_record_parents.clear();
    context.debug_angle_record_valid.clear();
    if ((context.debug_constraint_request_mask & kDebugConstraintDistance) != 0) {
        const auto record_count = context.distance_targets.size();
        context.debug_distance_record_origins.assign(record_count * 2 * 3, 0.0f);
        context.debug_distance_record_corrections.assign(record_count * 2 * 3, 0.0f);
        context.debug_distance_record_lengths.assign(record_count * 2, 0.0f);
        context.debug_distance_record_rests.assign(record_count * 2, 0.0f);
        context.debug_distance_record_valid.assign(
            record_count * 2, static_cast<std::uint8_t>(0)
        );
    }
    if ((context.debug_constraint_request_mask & kDebugConstraintBending) != 0) {
        const auto record_count = context.bending_rest_angle_or_volume.size();
        context.debug_bending_record_origins.assign(record_count * 4 * 3, 0.0f);
        context.debug_bending_record_corrections.assign(record_count * 4 * 3, 0.0f);
        context.debug_bending_record_valid.assign(
            record_count, static_cast<std::uint8_t>(0)
        );
    }
    if ((context.debug_constraint_request_mask & kDebugConstraintMotion) != 0) {
        const auto record_count = static_cast<std::size_t>(context.vertex_count) * 2;
        context.debug_motion_record_origins.assign(record_count * 3, 0.0f);
        context.debug_motion_record_corrections.assign(record_count * 3, 0.0f);
        context.debug_motion_record_valid.assign(
            record_count, static_cast<std::uint8_t>(0)
        );
    }
    if ((context.debug_constraint_request_mask & kDebugConstraintAngle) != 0) {
        const auto record_count = context.baseline_data.size() *
            static_cast<std::size_t>(kMc2AngleIterationCount) * 2;
        context.debug_angle_record_origins.assign(record_count * 2 * 3, 0.0f);
        context.debug_angle_record_corrections.assign(record_count * 2 * 3, 0.0f);
        context.debug_angle_record_currents.assign(record_count, 0.0f);
        context.debug_angle_record_limits.assign(record_count, 0.0f);
        context.debug_angle_record_children.assign(record_count, -1);
        context.debug_angle_record_parents.assign(record_count, -1);
        context.debug_angle_record_valid.assign(
            record_count, static_cast<std::uint8_t>(0)
        );
    }
    if (context.external_contact_debug_requested) {
        context.external_contact_debug_records.clear();
        context.external_contact_debug_ready = false;
    }
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
    std::vector<float> debug_before;
    begin_constraint_debug_pass(context, kDebugConstraintTether, debug_before);
    solve_tether_once(context);
    finish_constraint_debug_pass(
        context, kDebugConstraintTether, 0, debug_before
    );
    begin_constraint_debug_pass(context, kDebugConstraintDistance, debug_before);
    if ((context.debug_constraint_request_mask & kDebugConstraintDistance) != 0) {
        capture_distance_records_once(context, simulation_power_y, 0);
    }
    solve_distance_once(context, simulation_power_y);
    if ((context.debug_constraint_request_mask & kDebugConstraintDistance) != 0) {
        context.debug_distance_record_phase_mask |= 1u;
    }
    finish_constraint_debug_pass(
        context, kDebugConstraintDistance, 1, debug_before
    );
    begin_constraint_debug_pass(context, kDebugConstraintAngle, debug_before);
    if ((context.debug_constraint_request_mask & kDebugConstraintAngle) != 0) {
        capture_angle_records_once(context, simulation_power_w);
    }
    solve_angle_once(context, simulation_power_w);
    if ((context.debug_constraint_request_mask & kDebugConstraintAngle) != 0) {
        context.debug_angle_record_ready = true;
    }
    finish_constraint_debug_pass(
        context, kDebugConstraintAngle, 2, debug_before
    );
    begin_constraint_debug_pass(context, kDebugConstraintBending, debug_before);
    if ((context.debug_constraint_request_mask & kDebugConstraintBending) != 0) {
        capture_bending_records_once(context, simulation_power_y);
    }
    solve_bending_once(context, simulation_power_y);
    if ((context.debug_constraint_request_mask & kDebugConstraintBending) != 0) {
        context.debug_bending_record_ready = true;
    }
    finish_constraint_debug_pass(
        context, kDebugConstraintBending, 3, debug_before
    );
    solve_point_collision_once(context);
    solve_edge_collision_once(context);
    begin_constraint_debug_pass(context, kDebugConstraintDistance, debug_before);
    if ((context.debug_constraint_request_mask & kDebugConstraintDistance) != 0) {
        capture_distance_records_once(context, simulation_power_y, 1);
    }
    solve_distance_once(context, simulation_power_y);
    if ((context.debug_constraint_request_mask & kDebugConstraintDistance) != 0) {
        context.debug_distance_record_phase_mask |= 2u;
        context.debug_distance_record_ready =
            context.debug_distance_record_phase_mask == 3u;
    }
    finish_constraint_debug_pass(
        context, kDebugConstraintDistance, 4, debug_before
    );
    begin_constraint_debug_pass(context, kDebugConstraintMotion, debug_before);
    if ((context.debug_constraint_request_mask & kDebugConstraintMotion) != 0) {
        capture_motion_records_once(context);
    }
    solve_motion_once(context);
    if ((context.debug_constraint_request_mask & kDebugConstraintMotion) != 0) {
        context.debug_motion_record_ready = true;
    }
    finish_constraint_debug_pass(
        context, kDebugConstraintMotion, 5, debug_before
    );
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
    if (context.external_contact_debug_requested && is_final_substep) {
        context.external_contact_debug_ready = true;
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
    aggregate.self_topology_neighbor_keys.clear();
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
    MC2_ADD_VECTOR_BYTES(external_contact_debug_records);
    MC2_ADD_VECTOR_BYTES(debug_constraint_origins);
    MC2_ADD_VECTOR_BYTES(debug_constraint_corrections);
    MC2_ADD_VECTOR_BYTES(debug_distance_record_origins);
    MC2_ADD_VECTOR_BYTES(debug_distance_record_corrections);
    MC2_ADD_VECTOR_BYTES(debug_distance_record_lengths);
    MC2_ADD_VECTOR_BYTES(debug_distance_record_rests);
    MC2_ADD_VECTOR_BYTES(debug_distance_record_valid);
    MC2_ADD_VECTOR_BYTES(debug_bending_record_origins);
    MC2_ADD_VECTOR_BYTES(debug_bending_record_corrections);
    MC2_ADD_VECTOR_BYTES(debug_bending_record_valid);
    MC2_ADD_VECTOR_BYTES(debug_motion_record_origins);
    MC2_ADD_VECTOR_BYTES(debug_motion_record_corrections);
    MC2_ADD_VECTOR_BYTES(debug_motion_record_valid);
    MC2_ADD_VECTOR_BYTES(debug_angle_record_origins);
    MC2_ADD_VECTOR_BYTES(debug_angle_record_corrections);
    MC2_ADD_VECTOR_BYTES(debug_angle_record_currents);
    MC2_ADD_VECTOR_BYTES(debug_angle_record_limits);
    MC2_ADD_VECTOR_BYTES(debug_angle_record_children);
    MC2_ADD_VECTOR_BYTES(debug_angle_record_parents);
    MC2_ADD_VECTOR_BYTES(debug_angle_record_valid);
    MC2_ADD_VECTOR_BYTES(animated_base_positions);
    MC2_ADD_VECTOR_BYTES(animated_base_rotations);
    MC2_ADD_VECTOR_BYTES(step_basic_positions);
    MC2_ADD_VECTOR_BYTES(step_basic_rotations);
    MC2_ADD_VECTOR_BYTES(proxy_local_positions);
    MC2_ADD_VECTOR_BYTES(proxy_local_normals);
    MC2_ADD_VECTOR_BYTES(proxy_local_tangents);
    MC2_ADD_VECTOR_BYTES(proxy_uvs);
    MC2_ADD_VECTOR_BYTES(frame_triangle_uvs);
    MC2_ADD_VECTOR_BYTES(proxy_attributes);
    MC2_ADD_VECTOR_BYTES(proxy_radius_multipliers);
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
    MC2_ADD_VECTOR_BYTES(self_topology_neighbor_keys);
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
    MC2_ADD_VECTOR_BYTES(debug_self_contact_corrections);
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
        !dict_i64(
            result,
            "external_contact_debug_count",
            static_cast<std::int64_t>(context.external_contact_debug_records.size())
        ) ||
        !dict_i64(
            result,
            "self_contact_debug_correction_count",
            static_cast<std::int64_t>(context.debug_self_contact_corrections.size() / 6)
        ) ||
        !dict_i64(
            result,
            "debug_constraint_request_mask",
            static_cast<std::int64_t>(context.debug_constraint_request_mask)
        ) ||
        !dict_i64(
            result,
            "debug_constraint_ready_mask",
            static_cast<std::int64_t>(context.debug_constraint_ready_mask)
        ) ||
        !dict_i64(
            result,
            "debug_constraint_float_count",
            static_cast<std::int64_t>(
                context.debug_constraint_origins.size() +
                context.debug_constraint_corrections.size()
            )
        ) ||
        !dict_bool(
            result,
            "debug_distance_record_ready",
            context.debug_distance_record_ready
        ) ||
        !dict_i64(
            result,
            "debug_distance_record_count",
            static_cast<std::int64_t>(context.debug_distance_record_valid.size())
        ) ||
        !dict_i64(
            result,
            "debug_distance_record_float_count",
            static_cast<std::int64_t>(
                context.debug_distance_record_origins.size() +
                context.debug_distance_record_corrections.size() +
                context.debug_distance_record_lengths.size() +
                context.debug_distance_record_rests.size()
            )
        ) ||
        !dict_bool(
            result,
            "debug_bending_record_ready",
            context.debug_bending_record_ready
        ) ||
        !dict_i64(
            result,
            "debug_bending_record_count",
            static_cast<std::int64_t>(context.debug_bending_record_valid.size())
        ) ||
        !dict_i64(
            result,
            "debug_bending_record_float_count",
            static_cast<std::int64_t>(
                context.debug_bending_record_origins.size() +
                context.debug_bending_record_corrections.size()
            )
        ) ||
        !dict_bool(
            result,
            "debug_motion_record_ready",
            context.debug_motion_record_ready
        ) ||
        !dict_i64(
            result,
            "debug_motion_record_count",
            static_cast<std::int64_t>(context.debug_motion_record_valid.size())
        ) ||
        !dict_i64(
            result,
            "debug_motion_record_float_count",
            static_cast<std::int64_t>(
                context.debug_motion_record_origins.size() +
                context.debug_motion_record_corrections.size()
            )
        ) ||
        !dict_bool(
            result,
            "debug_angle_record_ready",
            context.debug_angle_record_ready
        ) ||
        !dict_i64(
            result,
            "debug_angle_record_count",
            static_cast<std::int64_t>(context.debug_angle_record_valid.size())
        ) ||
        !dict_i64(
            result,
            "debug_angle_record_float_count",
            static_cast<std::int64_t>(
                context.debug_angle_record_origins.size() +
                context.debug_angle_record_corrections.size() +
                context.debug_angle_record_currents.size() +
                context.debug_angle_record_limits.size()
            )
        ) ||
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
        !dict_i64(
            result,
            "task_teleport_apply_count",
            context.task_teleport_apply_count
        ) ||
        !dict_i64(
            result,
            "task_teleport_trigger_count",
            context.task_teleport_trigger_count
        ) ||
        !dict_i64(result, "task_teleport_mode", context.task_teleport_mode) ||
        !dict_float(
            result,
            "task_teleport_max_distance",
            context.task_teleport_max_distance
        ) ||
        !dict_float(
            result,
            "task_teleport_max_rotation_degrees",
            context.task_teleport_max_rotation_degrees
        ) ||
        !dict_float(
            result,
            "task_teleport_distance_threshold",
            context.task_teleport_distance_threshold
        ) ||
        !dict_float(
            result,
            "task_teleport_rotation_threshold_degrees",
            context.task_teleport_rotation_threshold_degrees
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
        !dict_bool(result, "component_pose_ready", context.component_pose_ready) ||
        !dict_bool(
            result,
            "external_contact_debug_requested",
            context.external_contact_debug_requested
        ) ||
        !dict_bool(
            result,
            "external_contact_debug_ready",
            context.external_contact_debug_ready
        ) ||
        !dict_bool(
            result,
            "self_contact_debug_requested",
            context.self_contact_debug_requested
        ) ||
        !dict_bool(
            result,
            "self_contact_debug_ready",
            context.self_contact_debug_ready
        ) ||
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

}  // namespace mc2_internal

using namespace mc2_internal;

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
