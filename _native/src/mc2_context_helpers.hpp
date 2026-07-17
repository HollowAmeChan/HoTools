#pragma once

#include <Python.h>

#include "mc2_context_internal.hpp"
#include "python_buffer_utils.hpp"

namespace hotools::mc2_internal {

inline constexpr const char* kInteractionCapsuleName =
    "hotools_native.MC2InteractionV0";
inline constexpr long kSchemaVersion = 0;
inline constexpr Py_ssize_t kIntCount = 11;
inline constexpr Py_ssize_t kFloatCount = 47;
inline constexpr Py_ssize_t kCurveRows = 9;
inline constexpr Py_ssize_t kCurveColumns = 16;
inline constexpr Py_ssize_t kSelfCollisionSyncMode = 10;
inline constexpr float kMc2Epsilon = 0.00000001f;
inline constexpr std::uint32_t kSelfFix0 = 0x04000000u;
inline constexpr std::uint32_t kSelfAllFix = 0x20000000u;
inline constexpr std::uint32_t kSelfIgnore = 0x40000000u;
inline constexpr std::uint32_t kSelfIntersectMask = 0x00000007u;
inline constexpr std::int32_t kSelfIgnoreGrid = 1000000;

Mc2ContextV0* context_from(PyObject* object);
Mc2InteractionV0* interaction_from(PyObject* object);
bool ensure_live(Mc2ContextV0* context);
bool ensure_live(Mc2InteractionV0* interaction);
void destroy_interaction(PyObject* capsule);
void release_interaction(Mc2InteractionV0& interaction);
bool dict_i64(PyObject* dict, const char* key, std::int64_t value);
bool dict_bool(PyObject* dict, const char* key, bool value);
bool dict_float(PyObject* dict, const char* key, float value);
bool dict_string(PyObject* dict, const char* key, const char* value);
bool finite_floats(const py::Buffer& buffer, const char* name);
bool expect_2d(
    const py::Buffer& buffer,
    const char* name,
    Py_ssize_t rows,
    Py_ssize_t columns
);
bool build_bone_output(Mc2ContextV0& context);
bool validate_quaternions(const py::Buffer& rotations, const char* name);
bool validate_parameter_ints(const py::Buffer& ints);
bool validate_indices(
    const py::Buffer& buffer,
    std::int64_t vertex_count,
    const char* name,
    bool allow_minus_one = false
);
bool validate_dense_ranges(
    const py::Buffer& ranges,
    Py_ssize_t data_count,
    const char* name
);
bool expect_int8_scalar_array(const py::Buffer& buffer, const char* name);
bool rebuild_baseline_step_pose(Mc2ContextV0& context);
bool is_move(std::uint8_t attribute);
void clear_self_collision_contacts(Mc2ContextV0& context);
void rotate_vector_xyzw(const float* rotation, const float* value, float* output);
Vec3 add(Vec3 first, Vec3 second);
Vec3 mul(Vec3 value, float scale);
Vec3 cross(Vec3 first, Vec3 second);
float dot(Vec3 first, Vec3 second);
float length(Vec3 value);
std::array<float, 4> quaternion_multiply(
    const std::array<float, 4>& left,
    const std::array<float, 4>& right
);
void normalize_quaternion(std::array<float, 4>& value);
std::array<float, 4> quaternion_from_forward_up(Vec3 forward, Vec3 up);
Vec3 rotate_vector(const std::array<float, 4>& rotation, Vec3 value);
Vec3 transform_vector_matrix(const float* matrix, Vec3 value);
Vec3 transform_point_matrix(const float* matrix, Vec3 value);
std::array<float, 4> transform_rotation_matrix(
    const float* matrix,
    const std::array<float, 4>& rotation
);
std::array<float, 4> load_quaternion(
    const std::vector<float>& values,
    std::size_t vertex
);
void store_quaternion(
    std::vector<float>& values,
    std::size_t vertex,
    std::array<float, 4> rotation
);
Vec3 load_vector3(const std::vector<float>& values, std::size_t vertex);
bool apply_bone_triangle_output(
    Mc2ContextV0& context,
    const std::vector<float>& positions,
    std::vector<float>& work_rotations,
    bool count_bone_output
);

template <typename T>
std::vector<T> copy_values(const py::Buffer& buffer) {
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
    const py::Buffer& buffer
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
bool interaction_scope_matches(
    Mc2InteractionV0& interaction,
    const std::vector<std::uintptr_t>& scope_identity
);
void detect_self_collision_intersections_once(Mc2ContextV0& context);
bool begin_mc2_context_step(
    Mc2ContextV0& context,
    float dt,
    float simulation_power_y,
    float simulation_power_z,
    float simulation_power_w,
    Mc2ContextStepStateV0& state
);
void finish_mc2_context_step(
    Mc2ContextStepStateV0& state,
    float dt,
    bool is_final_substep
);
bool build_and_solve_interaction(
    Mc2InteractionV0& interaction,
    const std::vector<Mc2ContextStepStateV0>& states
);
void finish_interaction_intersections(Mc2InteractionV0& interaction);

}  // namespace hotools::mc2_internal
