#include <Python.h>

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include "hotools_mc2.hpp"
#include "hotools_mc2_bonecloth_io.hpp"
#include "hotools_property_curve.hpp"
#include "mc2_context.hpp"
#include "mc2_context_v0.hpp"
#include "python_buffer_utils.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

PyObject* spring_vrm_create_context(PyObject*, PyObject*);
PyObject* free_spring_vrm_context(PyObject*, PyObject*);
PyObject* spring_vrm_reset_state(PyObject*, PyObject*);
PyObject* spring_vrm_update_dynamic(PyObject*, PyObject*);
PyObject* spring_vrm_step(PyObject*, PyObject*);
PyObject* spring_vrm_read_results(PyObject*, PyObject*);
PyObject* spring_vrm_read_debug(PyObject*, PyObject*);

namespace nb = nanobind;

namespace {

using namespace hotools::py;  // Buffer, expect_*, as_double, as_long（solve_meshcloth_mc2 旧函数仍用）

// ---------------------------------------------------------------------------
// nanobind ndarray 类型别名（按可变/只读、维度、元素类型分类）
// ---------------------------------------------------------------------------
using f32_2d  = nb::ndarray<float,          nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using f32_1d  = nb::ndarray<float,          nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using cf32_2d = nb::ndarray<const float,    nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using cf32_1d = nb::ndarray<const float,    nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using ci32_2d = nb::ndarray<const int32_t,  nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using ci32_1d = nb::ndarray<const int32_t,  nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using cu8_1d  = nb::ndarray<const uint8_t,  nb::ndim<1>, nb::c_contig, nb::device::cpu>;

// ---------------------------------------------------------------------------
// 旧式 PyObject* 函数辅助（property curve / tuple-args 大函数仍需）
// ---------------------------------------------------------------------------
nb::object steal_or_throw(PyObject* result) {
    if (result == nullptr) throw nb::python_error();
    return nb::steal<nb::object>(result);
}
inline void call_legacy(PyObject* (*fn)(PyObject*, PyObject*), nb::args a) {
    PyObject* r = fn(nullptr, a.ptr());
    if (!r) throw nb::python_error();
    Py_DECREF(r);
}

// ---------------------------------------------------------------------------
// ndarray 路径：nanobind 在调用边界已保证 dtype/ndim/contiguous
// 以下辅助仅处理 nanobind 类型系统无法表达的语义约束
// ---------------------------------------------------------------------------

// 检查 2D 数组第二维等于期望列数
template<typename Arr>
inline void check_cols(const Arr& arr, size_t expected, const char* name) {
    if (static_cast<size_t>(arr.shape(1)) != expected)
        throw nb::value_error((std::string(name) + " 列数错误").c_str());
}
// 检查数组行/元素数量
inline void check_len(size_t actual, size_t expected, const char* name) {
    if (actual != expected)
        throw nb::value_error((std::string(name) + " 长度不匹配").c_str());
}
// 检查 int32 indices 都在 [0, vertex_count)
inline void check_indices_in_range(const int32_t* data, size_t n, size_t vc, const char* name) {
    for (size_t i = 0; i < n; ++i)
        if (data[i] < 0 || static_cast<size_t>(data[i]) >= vc)
            throw nb::value_error((std::string(name) + " 包含越界顶点索引").c_str());
}
// 检查 root indices 在 [-1, vertex_count)，-1 表示根节点
inline void check_root_or_minus_one(const int32_t* data, size_t n, size_t vc, const char* name) {
    for (size_t i = 0; i < n; ++i)
        if (data[i] < -1 || (data[i] >= 0 && static_cast<size_t>(data[i]) >= vc))
            throw nb::value_error((std::string(name) + " 包含越界 root 索引").c_str());
}

PyObject* solve_meshcloth_mc2(PyObject*, PyObject* args) {
    enum SolveArg {
        APositions = 0,
        AOldPositions,
        AVelocityPositions,
        AVelocities,
        ARealVelocities,
        AFriction,
        AStaticFriction,
        ACollisionNormals,
        AInvMasses,
        AStepBasicPositions,
        AStepBasicRotations,
        ADisplayPositions,
        ABasePositions,
        ABaseNormals,
        ABaseRotations,
        AAttributes,
        ADepths,
        ARootIndices,
        ATetherRestLengths,
        AParentIndices,
        ABaselineStart,
        ABaselineCount,
        ABaselineData,
        AVertexLocalPositions,
        AVertexLocalRotations,
        ADistanceStart,
        ADistanceCount,
        ADistanceData,
        ADistanceRest,
        ADistanceStiffnessValues,
        ABendDistanceStart,
        ABendDistanceCount,
        ABendDistanceData,
        ABendDistanceRest,
        ABendStiffnessValues,
        ADihedralPairs,
        ADihedralRestAngles,
        ADihedralSigns,
        AVolumePairs,
        AVolumeRest,
        AAngleRestorationValues,
        AAngleRestorationVelocityAttenuationValues,
        AAngleRestorationGravityFalloffValues,
        AAngleLimitValues,
        ASubstepDampingValues,
        AMaxDistances,
        AMotionStiffnessValues,
        ABackstopRadii,
        ABackstopDistances,
        AEdges,
        ATriangles,
        ACollisionRadii,
        AColliderTypes,
        AColliderGroupBits,
        AColliderCenters,
        AColliderSegmentA,
        AColliderSegmentB,
        AColliderOldCenters,
        AColliderOldSegmentA,
        AColliderOldSegmentB,
        AColliderRadii,
        ASubstepOldWorldPositions,
        ASubstepStepVectors,
        ASubstepStepRotations,
        ASubstepInertiaVectors,
        ASubstepInertiaRotations,
        ASubstepNowWorldPositions,
        ASubstepRotationAxes,
        ASubstepAngularVelocities,
        ASubstepVelocityWeights,
        kSolveBufferCount,
    };
    constexpr Py_ssize_t kArgCount = 93;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "solve_meshcloth_mc2 expects %zd arguments", kArgCount);
        return nullptr;
    }

    const char* names[kSolveBufferCount] = {
        "positions",
        "old_positions",
        "velocity_positions",
        "velocities",
        "real_velocities",
        "friction",
        "static_friction",
        "collision_normals",
        "inv_masses",
        "step_basic_positions",
        "step_basic_rotations",
        "display_positions",
        "base_positions",
        "base_normals",
        "base_rotations",
        "attributes",
        "depths",
        "root_indices",
        "tether_rest_lengths",
        "parent_indices",
        "baseline_start",
        "baseline_count",
        "baseline_data",
        "vertex_local_positions",
        "vertex_local_rotations",
        "distance_start",
        "distance_count",
        "distance_data",
        "distance_rest",
        "distance_stiffness_values",
        "bend_distance_start",
        "bend_distance_count",
        "bend_distance_data",
        "bend_distance_rest",
        "bend_stiffness_values",
        "dihedral_pairs",
        "dihedral_rest_angles",
        "dihedral_signs",
        "volume_pairs",
        "volume_rest",
        "angle_restoration_values",
        "angle_restoration_velocity_attenuation_values",
        "angle_restoration_gravity_falloff_values",
        "angle_limit_values",
        "substep_damping_values",
        "max_distances",
        "motion_stiffness_values",
        "backstop_radii",
        "backstop_distances",
        "edges",
        "triangles",
        "collision_radii",
        "collider_types",
        "collider_group_bits",
        "collider_centers",
        "collider_segment_a",
        "collider_segment_b",
        "collider_old_centers",
        "collider_old_segment_a",
        "collider_old_segment_b",
        "collider_radii",
        "substep_old_world_positions",
        "substep_step_vectors",
        "substep_step_rotations",
        "substep_inertia_vectors",
        "substep_inertia_rotations",
        "substep_now_world_positions",
        "substep_rotation_axes",
        "substep_angular_velocities",
        "substep_velocity_weights",
    };

    Buffer buffers[kSolveBufferCount];
    for (int index = 0; index < kSolveBufferCount; ++index) {
        const int flags = index <= ADisplayPositions ? (PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND)
                                                     : (PyBUF_FORMAT | PyBUF_ND);
        if (!buffers[index].get(PyTuple_GET_ITEM(args, index), flags, names[index])) {
            return nullptr;
        }
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(buffers[APositions], "positions", &vertex_count) ||
        !expect_same_vertex_count(buffers[AOldPositions], "old_positions", vertex_count) ||
        !expect_same_vertex_count(buffers[AVelocityPositions], "velocity_positions", vertex_count) ||
        !expect_same_vertex_count(buffers[AVelocities], "velocities", vertex_count) ||
        !expect_same_vertex_count(buffers[ARealVelocities], "real_velocities", vertex_count) ||
        !expect_same_vertex_count(buffers[ACollisionNormals], "collision_normals", vertex_count) ||
        !expect_same_vertex_count(buffers[AStepBasicPositions], "step_basic_positions", vertex_count) ||
        !expect_same_vertex_count(buffers[ADisplayPositions], "display_positions", vertex_count) ||
        !expect_same_vertex_count(buffers[ABasePositions], "base_positions", vertex_count) ||
        !expect_same_vertex_count(buffers[ABaseNormals], "base_normals", vertex_count) ||
        !expect_same_quat_vertex_count(buffers[AStepBasicRotations], "step_basic_rotations", vertex_count) ||
        !expect_same_quat_vertex_count(buffers[ABaseRotations], "base_rotations", vertex_count) ||
        !expect_same_vertex_count(buffers[AVertexLocalPositions], "vertex_local_positions", vertex_count) ||
        !expect_same_quat_vertex_count(buffers[AVertexLocalRotations], "vertex_local_rotations", vertex_count)) {
        return nullptr;
    }

    if (!expect_float32(buffers[AFriction], "friction") ||
        !expect_1d_array(buffers[AFriction], "friction", vertex_count) ||
        !expect_float32(buffers[AStaticFriction], "static_friction") ||
        !expect_1d_array(buffers[AStaticFriction], "static_friction", vertex_count) ||
        !expect_float32(buffers[AInvMasses], "inv_masses") ||
        !expect_1d_array(buffers[AInvMasses], "inv_masses", vertex_count) ||
        !expect_uint8_scalar_array(buffers[AAttributes], "attributes") ||
        !expect_1d_array(buffers[AAttributes], "attributes", vertex_count) ||
        !expect_float32(buffers[ADepths], "depths") ||
        !expect_1d_array(buffers[ADepths], "depths", vertex_count) ||
        !expect_int32_scalar_array(buffers[ARootIndices], "root_indices") ||
        !expect_1d_array(buffers[ARootIndices], "root_indices", vertex_count) ||
        !expect_root_indices_or_minus_one(buffers[ARootIndices], "root_indices", vertex_count) ||
        !expect_float32(buffers[ATetherRestLengths], "tether_rest_lengths") ||
        !expect_1d_array(buffers[ATetherRestLengths], "tether_rest_lengths", vertex_count) ||
        !expect_int32_scalar_array(buffers[AParentIndices], "parent_indices") ||
        !expect_1d_array(buffers[AParentIndices], "parent_indices", vertex_count) ||
        !expect_root_indices_or_minus_one(buffers[AParentIndices], "parent_indices", vertex_count)) {
        return nullptr;
    }

    if (!expect_int32_scalar_array(buffers[ABaselineStart], "baseline_start") ||
        !expect_int32_scalar_array(buffers[ABaselineCount], "baseline_count") ||
        !expect_int32_scalar_array(buffers[ABaselineData], "baseline_data") ||
        !expect_indices_in_range(buffers[ABaselineData], "baseline_data", vertex_count)) {
        return nullptr;
    }
    const Py_ssize_t line_count = buffers[ABaselineStart].view.shape[0];
    if (!expect_1d_array(buffers[ABaselineCount], "baseline_count", line_count)) {
        return nullptr;
    }

    if (!expect_int32_scalar_array(buffers[ADistanceStart], "distance_start") ||
        !expect_1d_array(buffers[ADistanceStart], "distance_start", vertex_count) ||
        !expect_int32_scalar_array(buffers[ADistanceCount], "distance_count") ||
        !expect_1d_array(buffers[ADistanceCount], "distance_count", vertex_count) ||
        !expect_int32_scalar_array(buffers[ADistanceData], "distance_data") ||
        !expect_indices_in_range(buffers[ADistanceData], "distance_data", vertex_count) ||
        !expect_float32(buffers[ADistanceRest], "distance_rest") ||
        !expect_1d_array(buffers[ADistanceRest], "distance_rest", buffers[ADistanceData].view.shape[0]) ||
        !expect_float32(buffers[ADistanceStiffnessValues], "distance_stiffness_values") ||
        !expect_1d_array(buffers[ADistanceStiffnessValues], "distance_stiffness_values", vertex_count)) {
        return nullptr;
    }

    if (!expect_int32_scalar_array(buffers[ABendDistanceStart], "bend_distance_start") ||
        !expect_1d_array(buffers[ABendDistanceStart], "bend_distance_start", vertex_count) ||
        !expect_int32_scalar_array(buffers[ABendDistanceCount], "bend_distance_count") ||
        !expect_1d_array(buffers[ABendDistanceCount], "bend_distance_count", vertex_count) ||
        !expect_int32_scalar_array(buffers[ABendDistanceData], "bend_distance_data") ||
        !expect_indices_in_range(buffers[ABendDistanceData], "bend_distance_data", vertex_count) ||
        !expect_float32(buffers[ABendDistanceRest], "bend_distance_rest") ||
        !expect_1d_array(buffers[ABendDistanceRest], "bend_distance_rest", buffers[ABendDistanceData].view.shape[0]) ||
        !expect_float32(buffers[ABendStiffnessValues], "bend_stiffness_values") ||
        !expect_1d_array(buffers[ABendStiffnessValues], "bend_stiffness_values", vertex_count)) {
        return nullptr;
    }

    Py_ssize_t dihedral_count = 0;
    Py_ssize_t volume_count = 0;
    if (!expect_int32_quad_array(buffers[ADihedralPairs], "dihedral_pairs", &dihedral_count) ||
        !expect_float32(buffers[ADihedralRestAngles], "dihedral_rest_angles") ||
        !expect_1d_array(buffers[ADihedralRestAngles], "dihedral_rest_angles", dihedral_count) ||
        !expect_int32_scalar_array(buffers[ADihedralSigns], "dihedral_signs") ||
        !expect_1d_array(buffers[ADihedralSigns], "dihedral_signs", dihedral_count) ||
        !expect_int32_quad_array(buffers[AVolumePairs], "volume_pairs", &volume_count) ||
        !expect_float32(buffers[AVolumeRest], "volume_rest") ||
        !expect_1d_array(buffers[AVolumeRest], "volume_rest", volume_count)) {
        return nullptr;
    }
    if ((dihedral_count > 0 && !expect_quad_indices_in_range(buffers[ADihedralPairs], "dihedral_pairs", vertex_count)) ||
        (volume_count > 0 && !expect_quad_indices_in_range(buffers[AVolumePairs], "volume_pairs", vertex_count))) {
        return nullptr;
    }

    Py_ssize_t edge_count = 0;
    Py_ssize_t triangle_count = 0;
    if (!expect_float32(buffers[AAngleRestorationValues], "angle_restoration_values") ||
        !expect_1d_array(buffers[AAngleRestorationValues], "angle_restoration_values", vertex_count) ||
        !expect_float32(buffers[AAngleRestorationVelocityAttenuationValues],
                        "angle_restoration_velocity_attenuation_values") ||
        !expect_1d_array(buffers[AAngleRestorationVelocityAttenuationValues],
                         "angle_restoration_velocity_attenuation_values", vertex_count) ||
        !expect_float32(buffers[AAngleRestorationGravityFalloffValues],
                        "angle_restoration_gravity_falloff_values") ||
        !expect_1d_array(buffers[AAngleRestorationGravityFalloffValues],
                         "angle_restoration_gravity_falloff_values", vertex_count) ||
        !expect_float32(buffers[AAngleLimitValues], "angle_limit_values") ||
        !expect_1d_array(buffers[AAngleLimitValues], "angle_limit_values", vertex_count) ||
        !expect_float32(buffers[ASubstepDampingValues], "substep_damping_values") ||
        !expect_1d_array(buffers[ASubstepDampingValues], "substep_damping_values", vertex_count) ||
        !expect_float32(buffers[AMaxDistances], "max_distances") ||
        !expect_1d_array(buffers[AMaxDistances], "max_distances", vertex_count) ||
        !expect_float32(buffers[AMotionStiffnessValues], "motion_stiffness_values") ||
        !expect_1d_array(buffers[AMotionStiffnessValues], "motion_stiffness_values", vertex_count) ||
        !expect_float32(buffers[ABackstopRadii], "backstop_radii") ||
        !expect_1d_array(buffers[ABackstopRadii], "backstop_radii", vertex_count) ||
        !expect_float32(buffers[ABackstopDistances], "backstop_distances") ||
        !expect_1d_array(buffers[ABackstopDistances], "backstop_distances", vertex_count) ||
        !expect_int32_pair_array(buffers[AEdges], "edges", &edge_count) ||
        !expect_pair_indices_in_range(buffers[AEdges], "edges", vertex_count) ||
        !expect_int32_triple_array(buffers[ATriangles], "triangles", &triangle_count) ||
        !expect_triple_indices_in_range(buffers[ATriangles], "triangles", vertex_count) ||
        !expect_float32(buffers[ACollisionRadii], "collision_radii") ||
        !expect_1d_array(buffers[ACollisionRadii], "collision_radii", vertex_count)) {
        return nullptr;
    }

    if (!expect_int32_scalar_array(buffers[AColliderTypes], "collider_types") ||
        !expect_int32_scalar_array(buffers[AColliderGroupBits], "collider_group_bits") ||
        !expect_float32(buffers[AColliderRadii], "collider_radii")) {
        return nullptr;
    }
    const Py_ssize_t collider_count = buffers[AColliderTypes].view.shape[0];
    Py_ssize_t collider_centers_count = 0;
    Py_ssize_t collider_segment_a_count = 0;
    Py_ssize_t collider_segment_b_count = 0;
    Py_ssize_t collider_old_centers_count = 0;
    Py_ssize_t collider_old_segment_a_count = 0;
    Py_ssize_t collider_old_segment_b_count = 0;
    if (!expect_1d_array(buffers[AColliderGroupBits], "collider_group_bits", collider_count) ||
        !expect_1d_array(buffers[AColliderRadii], "collider_radii", collider_count) ||
        !expect_vector3_array(buffers[AColliderCenters], "collider_centers", &collider_centers_count) ||
        !expect_vector3_array(buffers[AColliderSegmentA], "collider_segment_a", &collider_segment_a_count) ||
        !expect_vector3_array(buffers[AColliderSegmentB], "collider_segment_b", &collider_segment_b_count) ||
        !expect_vector3_array(buffers[AColliderOldCenters], "collider_old_centers", &collider_old_centers_count) ||
        !expect_vector3_array(buffers[AColliderOldSegmentA], "collider_old_segment_a",
                              &collider_old_segment_a_count) ||
        !expect_vector3_array(buffers[AColliderOldSegmentB], "collider_old_segment_b",
                              &collider_old_segment_b_count)) {
        return nullptr;
    }
    if (collider_centers_count != collider_count || collider_segment_a_count != collider_count ||
        collider_segment_b_count != collider_count || collider_old_centers_count != collider_count ||
        collider_old_segment_a_count != collider_count || collider_old_segment_b_count != collider_count) {
        PyErr_SetString(PyExc_ValueError, "collider 数组长度不匹配");
        return nullptr;
    }

    constexpr Py_ssize_t kScalarStart = kSolveBufferCount;
    const double frame_dt = as_double(PyTuple_GET_ITEM(args, kScalarStart + 0), "frame_dt");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double step_dt = as_double(PyTuple_GET_ITEM(args, kScalarStart + 1), "step_dt");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const long raw_substeps = as_long(PyTuple_GET_ITEM(args, kScalarStart + 2), "substeps");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const long raw_iterations = as_long(PyTuple_GET_ITEM(args, kScalarStart + 3), "iterations");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    Buffer gravity;
    if (!gravity.get(PyTuple_GET_ITEM(args, kScalarStart + 4), PyBUF_FORMAT | PyBUF_ND, "gravity") ||
        !expect_float32(gravity, "gravity") ||
        !expect_1d_array(gravity, "gravity", 3)) {
        return nullptr;
    }
    const int substeps = std::max(1, std::min(16, static_cast<int>(raw_substeps)));
    Py_ssize_t substep_vec_count = 0;
    Py_ssize_t substep_quat_count = 0;
    if (!expect_vector3_array(buffers[ASubstepOldWorldPositions], "substep_old_world_positions", &substep_vec_count) ||
        substep_vec_count != substeps ||
        !expect_vector3_array(buffers[ASubstepStepVectors], "substep_step_vectors", &substep_vec_count) ||
        substep_vec_count != substeps ||
        !expect_vector4_array(buffers[ASubstepStepRotations], "substep_step_rotations", &substep_quat_count) ||
        substep_quat_count != substeps ||
        !expect_vector3_array(buffers[ASubstepInertiaVectors], "substep_inertia_vectors", &substep_vec_count) ||
        substep_vec_count != substeps ||
        !expect_vector4_array(buffers[ASubstepInertiaRotations], "substep_inertia_rotations", &substep_quat_count) ||
        substep_quat_count != substeps ||
        !expect_vector3_array(buffers[ASubstepNowWorldPositions], "substep_now_world_positions", &substep_vec_count) ||
        substep_vec_count != substeps ||
        !expect_vector3_array(buffers[ASubstepRotationAxes], "substep_rotation_axes", &substep_vec_count) ||
        substep_vec_count != substeps ||
        !expect_float32(buffers[ASubstepAngularVelocities], "substep_angular_velocities") ||
        !expect_1d_array(buffers[ASubstepAngularVelocities], "substep_angular_velocities", substeps) ||
        !expect_float32(buffers[ASubstepVelocityWeights], "substep_velocity_weights") ||
        !expect_1d_array(buffers[ASubstepVelocityWeights], "substep_velocity_weights", substeps)) {
        PyErr_SetString(PyExc_ValueError, "substep inertia 数组长度不匹配");
        return nullptr;
    }

    const double depth_inertia = as_double(PyTuple_GET_ITEM(args, kScalarStart + 5), "depth_inertia");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double centrifugal = as_double(PyTuple_GET_ITEM(args, kScalarStart + 6), "centrifugal");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const bool use_tether = PyObject_IsTrue(PyTuple_GET_ITEM(args, kScalarStart + 7)) == 1;
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double tether_compression = as_double(PyTuple_GET_ITEM(args, kScalarStart + 8), "tether_compression");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double tether_stretch = as_double(PyTuple_GET_ITEM(args, kScalarStart + 9), "tether_stretch");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double dynamic_friction = as_double(PyTuple_GET_ITEM(args, kScalarStart + 10), "dynamic_friction");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double static_friction_speed = as_double(PyTuple_GET_ITEM(args, kScalarStart + 11), "static_friction_speed");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double particle_speed_limit = as_double(PyTuple_GET_ITEM(args, kScalarStart + 12), "particle_speed_limit");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double angle_limit_stiffness =
        as_double(PyTuple_GET_ITEM(args, kScalarStart + 13), "angle_limit_stiffness");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const long normal_axis = as_long(PyTuple_GET_ITEM(args, kScalarStart + 14), "normal_axis");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const long collided_by_groups = as_long(PyTuple_GET_ITEM(args, kScalarStart + 15), "collided_by_groups");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const long collider_collision_mode =
        as_long(PyTuple_GET_ITEM(args, kScalarStart + 16), "collider_collision_mode");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double display_max_distance_ratio =
        as_double(PyTuple_GET_ITEM(args, kScalarStart + 17), "display_max_distance_ratio");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double animation_pose_ratio = as_double(PyTuple_GET_ITEM(args, kScalarStart + 18), "animation_pose_ratio");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double blend_weight = as_double(PyTuple_GET_ITEM(args, kScalarStart + 19), "blend_weight");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const bool self_collision_enabled = PyObject_IsTrue(PyTuple_GET_ITEM(args, kScalarStart + 20)) == 1;
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double self_collision_surface_thickness =
        as_double(PyTuple_GET_ITEM(args, kScalarStart + 21), "self_collision_surface_thickness");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double self_collision_mass = as_double(PyTuple_GET_ITEM(args, kScalarStart + 22), "self_collision_mass");
    if (PyErr_Occurred()) {
        return nullptr;
    }

    hotools::Mc2MeshClothSolveView view;
    view.positions = static_cast<float*>(buffers[APositions].view.buf);
    view.old_positions = static_cast<float*>(buffers[AOldPositions].view.buf);
    view.velocity_positions = static_cast<float*>(buffers[AVelocityPositions].view.buf);
    view.velocities = static_cast<float*>(buffers[AVelocities].view.buf);
    view.real_velocities = static_cast<float*>(buffers[ARealVelocities].view.buf);
    view.friction = static_cast<float*>(buffers[AFriction].view.buf);
    view.static_friction = static_cast<float*>(buffers[AStaticFriction].view.buf);
    view.collision_normals = static_cast<float*>(buffers[ACollisionNormals].view.buf);
    view.inv_masses = static_cast<float*>(buffers[AInvMasses].view.buf);
    view.step_basic_positions = static_cast<float*>(buffers[AStepBasicPositions].view.buf);
    view.step_basic_rotations = static_cast<float*>(buffers[AStepBasicRotations].view.buf);
    view.display_positions = static_cast<float*>(buffers[ADisplayPositions].view.buf);
    view.base_positions = static_cast<const float*>(buffers[ABasePositions].view.buf);
    view.base_normals = static_cast<const float*>(buffers[ABaseNormals].view.buf);
    view.base_rotations = static_cast<const float*>(buffers[ABaseRotations].view.buf);
    view.attributes = static_cast<const std::uint8_t*>(buffers[AAttributes].view.buf);
    view.depths = static_cast<const float*>(buffers[ADepths].view.buf);
    view.root_indices = static_cast<const std::int32_t*>(buffers[ARootIndices].view.buf);
    view.tether_rest_lengths = static_cast<const float*>(buffers[ATetherRestLengths].view.buf);
    view.parent_indices = static_cast<const std::int32_t*>(buffers[AParentIndices].view.buf);
    view.baseline_start = static_cast<const std::int32_t*>(buffers[ABaselineStart].view.buf);
    view.baseline_count = static_cast<const std::int32_t*>(buffers[ABaselineCount].view.buf);
    view.baseline_data = static_cast<const std::int32_t*>(buffers[ABaselineData].view.buf);
    view.vertex_local_positions = static_cast<const float*>(buffers[AVertexLocalPositions].view.buf);
    view.vertex_local_rotations = static_cast<const float*>(buffers[AVertexLocalRotations].view.buf);
    view.distance_start = static_cast<const std::int32_t*>(buffers[ADistanceStart].view.buf);
    view.distance_count = static_cast<const std::int32_t*>(buffers[ADistanceCount].view.buf);
    view.distance_data = static_cast<const std::int32_t*>(buffers[ADistanceData].view.buf);
    view.distance_rest = static_cast<const float*>(buffers[ADistanceRest].view.buf);
    view.distance_stiffness_values = static_cast<const float*>(buffers[ADistanceStiffnessValues].view.buf);
    view.bend_distance_start = static_cast<const std::int32_t*>(buffers[ABendDistanceStart].view.buf);
    view.bend_distance_count = static_cast<const std::int32_t*>(buffers[ABendDistanceCount].view.buf);
    view.bend_distance_data = static_cast<const std::int32_t*>(buffers[ABendDistanceData].view.buf);
    view.bend_distance_rest = static_cast<const float*>(buffers[ABendDistanceRest].view.buf);
    view.bend_stiffness_values = static_cast<const float*>(buffers[ABendStiffnessValues].view.buf);
    view.dihedral_pairs = static_cast<const std::int32_t*>(buffers[ADihedralPairs].view.buf);
    view.dihedral_rest_angles = static_cast<const float*>(buffers[ADihedralRestAngles].view.buf);
    view.dihedral_signs = static_cast<const std::int32_t*>(buffers[ADihedralSigns].view.buf);
    view.volume_pairs = static_cast<const std::int32_t*>(buffers[AVolumePairs].view.buf);
    view.volume_rest = static_cast<const float*>(buffers[AVolumeRest].view.buf);
    view.angle_restoration_values = static_cast<const float*>(buffers[AAngleRestorationValues].view.buf);
    view.angle_restoration_velocity_attenuation_values =
        static_cast<const float*>(buffers[AAngleRestorationVelocityAttenuationValues].view.buf);
    view.angle_restoration_gravity_falloff_values =
        static_cast<const float*>(buffers[AAngleRestorationGravityFalloffValues].view.buf);
    view.angle_limit_values = static_cast<const float*>(buffers[AAngleLimitValues].view.buf);
    view.substep_damping_values = static_cast<const float*>(buffers[ASubstepDampingValues].view.buf);
    view.max_distances = static_cast<const float*>(buffers[AMaxDistances].view.buf);
    view.motion_stiffness_values = static_cast<const float*>(buffers[AMotionStiffnessValues].view.buf);
    view.backstop_radii = static_cast<const float*>(buffers[ABackstopRadii].view.buf);
    view.backstop_distances = static_cast<const float*>(buffers[ABackstopDistances].view.buf);
    view.edges = static_cast<const std::int32_t*>(buffers[AEdges].view.buf);
    view.triangles = static_cast<const std::int32_t*>(buffers[ATriangles].view.buf);
    view.collision_radii = static_cast<const float*>(buffers[ACollisionRadii].view.buf);
    view.collider_types = static_cast<const std::int32_t*>(buffers[AColliderTypes].view.buf);
    view.collider_group_bits = static_cast<const std::int32_t*>(buffers[AColliderGroupBits].view.buf);
    view.collider_centers = static_cast<const float*>(buffers[AColliderCenters].view.buf);
    view.collider_segment_a = static_cast<const float*>(buffers[AColliderSegmentA].view.buf);
    view.collider_segment_b = static_cast<const float*>(buffers[AColliderSegmentB].view.buf);
    view.collider_old_centers = static_cast<const float*>(buffers[AColliderOldCenters].view.buf);
    view.collider_old_segment_a = static_cast<const float*>(buffers[AColliderOldSegmentA].view.buf);
    view.collider_old_segment_b = static_cast<const float*>(buffers[AColliderOldSegmentB].view.buf);
    view.collider_radii = static_cast<const float*>(buffers[AColliderRadii].view.buf);
    view.substep_old_world_positions = static_cast<const float*>(buffers[ASubstepOldWorldPositions].view.buf);
    view.substep_step_vectors = static_cast<const float*>(buffers[ASubstepStepVectors].view.buf);
    view.substep_step_rotations = static_cast<const float*>(buffers[ASubstepStepRotations].view.buf);
    view.substep_inertia_vectors = static_cast<const float*>(buffers[ASubstepInertiaVectors].view.buf);
    view.substep_inertia_rotations = static_cast<const float*>(buffers[ASubstepInertiaRotations].view.buf);
    view.substep_now_world_positions = static_cast<const float*>(buffers[ASubstepNowWorldPositions].view.buf);
    view.substep_rotation_axes = static_cast<const float*>(buffers[ASubstepRotationAxes].view.buf);
    view.substep_angular_velocities = static_cast<const float*>(buffers[ASubstepAngularVelocities].view.buf);
    view.substep_velocity_weights = static_cast<const float*>(buffers[ASubstepVelocityWeights].view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.line_count = static_cast<std::int64_t>(line_count);
    view.baseline_data_count = static_cast<std::int64_t>(buffers[ABaselineData].view.shape[0]);
    view.distance_count_total = static_cast<std::int64_t>(buffers[ADistanceData].view.shape[0]);
    view.bend_distance_count_total = static_cast<std::int64_t>(buffers[ABendDistanceData].view.shape[0]);
    view.edge_count = static_cast<std::int64_t>(edge_count);
    view.triangle_count = static_cast<std::int64_t>(triangle_count);
    view.dihedral_count = static_cast<std::int64_t>(dihedral_count);
    view.volume_count = static_cast<std::int64_t>(volume_count);
    view.collider_count = static_cast<std::int64_t>(collider_count);
    view.substeps = substeps;
    view.iterations = std::max(0, std::min(64, static_cast<int>(raw_iterations)));
    view.frame_dt = static_cast<float>(frame_dt);
    view.step_dt = static_cast<float>(step_dt);
    const float* gravity_values = static_cast<const float*>(gravity.view.buf);
    view.gravity[0] = gravity_values[0];
    view.gravity[1] = gravity_values[1];
    view.gravity[2] = gravity_values[2];
    view.depth_inertia = static_cast<float>(depth_inertia);
    view.centrifugal = static_cast<float>(centrifugal);
    view.use_tether = use_tether;
    view.tether_compression = static_cast<float>(tether_compression);
    view.tether_stretch = static_cast<float>(tether_stretch);
    view.dynamic_friction = static_cast<float>(dynamic_friction);
    view.static_friction_speed = static_cast<float>(static_friction_speed);
    view.particle_speed_limit = static_cast<float>(particle_speed_limit);
    view.angle_limit_stiffness = static_cast<float>(angle_limit_stiffness);
    view.normal_axis = std::max(0, std::min(5, static_cast<int>(normal_axis)));
    view.display_max_distance_ratio = static_cast<float>(display_max_distance_ratio);
    view.animation_pose_ratio = static_cast<float>(animation_pose_ratio);
    view.blend_weight = static_cast<float>(blend_weight);
    view.collided_by_groups = static_cast<std::int32_t>(collided_by_groups);
    view.collider_collision_mode = std::max(0, std::min(2, static_cast<int>(collider_collision_mode)));
    view.self_collision_enabled = self_collision_enabled;
    view.self_collision_surface_thickness = static_cast<float>(self_collision_surface_thickness);
    view.self_collision_mass = static_cast<float>(self_collision_mass);

    { nb::gil_scoped_release _; hotools::solve_meshcloth_mc2(view); }
    Py_RETURN_NONE;
}

// ---------------------------------------------------------------------------
// BoneCloth IO 绑定：solve_mc2_bonecloth_io
// ---------------------------------------------------------------------------
// 参数顺序（15个）：
//   world_rotations(rw), display_positions, base_positions, base_rotations,
//   vertex_local_positions, vertex_local_rotations,
//   parent_indices, baseline_start, baseline_count, baseline_data, attributes,
//   rotational_interpolation, blend_weight, anime_ratio, root_rotation

}  // namespace

NB_MODULE(hotools_native, m) {
    m.doc() = "Native acceleration backend for HoTools (nanobind module shell).";

    // ---- 属性曲线 ----
    m.def("compile_property_float_curve",
        [](nb::object p) { return steal_or_throw(hotools::compile_property_float_curve_object(p.ptr())); },
        nb::arg("payload"), "Compile a float curve payload into a native capsule.");
    m.def("compile_property_color_curve",
        [](nb::object p) { return steal_or_throw(hotools::compile_property_color_curve_object(p.ptr())); },
        nb::arg("payload"), "Compile a color curve payload into a native capsule.");
    m.def("sample_property_float_curve",
        [](nb::object c, double pos, nb::object ext) {
            return steal_or_throw(hotools::sample_property_float_curve_object(c.ptr(), pos, ext.ptr()));
        }, nb::arg("curve"), nb::arg("position"), nb::arg("extend").none(),
        "Sample a native float curve or payload at one position.");
    m.def("sample_property_color_curve",
        [](nb::object c, double pos, nb::object ext) {
            return steal_or_throw(hotools::sample_property_color_curve_object(c.ptr(), pos, ext.ptr()));
        }, nb::arg("curve"), nb::arg("position"), nb::arg("extend").none(),
        "Sample a native color curve or payload at one position.");
    m.def("sample_property_float_curve_many",
        [](nb::object c, int n, nb::object ext) {
            return steal_or_throw(hotools::sample_property_float_curve_many_object(c.ptr(), n, ext.ptr()));
        }, nb::arg("curve"), nb::arg("count"), nb::arg("extend").none(),
        "Sample a native float curve or payload at evenly spaced positions.");
    m.def("sample_property_color_curve_many",
        [](nb::object c, int n, nb::object ext) {
            return steal_or_throw(hotools::sample_property_color_curve_many_object(c.ptr(), n, ext.ptr()));
        }, nb::arg("curve"), nb::arg("count"), nb::arg("extend").none(),
        "Sample a native color curve or payload at evenly spaced positions.");
    m.def("sample_property_float_curve_positions",
        [](nb::object c, nb::object pos, nb::object ext) {
            return steal_or_throw(hotools::sample_property_float_curve_positions_object(c.ptr(), pos.ptr(), ext.ptr()));
        }, nb::arg("curve"), nb::arg("positions"), nb::arg("extend").none(),
        "Sample a native float curve or payload at explicit positions.");
    m.def("sample_property_color_curve_positions",
        [](nb::object c, nb::object pos, nb::object ext) {
            return steal_or_throw(hotools::sample_property_color_curve_positions_object(c.ptr(), pos.ptr(), ext.ptr()));
        }, nb::arg("curve"), nb::arg("positions"), nb::arg("extend").none(),
        "Sample a native color curve or payload at explicit positions.");

    // ---- VRM spring bone ----
    m.def("spring_vrm_create_context",
        [](nb::args a) { return steal_or_throw(spring_vrm_create_context(nullptr, a.ptr())); },
        "Create a VRM SpringBone context (dual-call API).");
    m.def("free_spring_vrm_context",
        [](nb::args a) { call_legacy(free_spring_vrm_context, a); },
        "Release a VRM SpringBone context. Repeated calls are safe.");
    m.def("spring_vrm_reset_state",
        [](nb::args a) { call_legacy(spring_vrm_reset_state, a); },
        "Reset tail state to current pose tails (restart 时调用).");
    m.def("spring_vrm_update_dynamic",
        [](nb::args a) { call_legacy(spring_vrm_update_dynamic, a); },
        "Upload per-frame pose and collider arrays.");
    m.def("spring_vrm_step",
        [](nb::args a) { call_legacy(spring_vrm_step, a); },
        "Step spring bone simulation.");
    m.def("spring_vrm_read_results",
        [](nb::args a) { call_legacy(spring_vrm_read_results, a); },
        "Copy result matrices/quaternions into pre-allocated output buffers.");
    m.def("spring_vrm_read_debug",
        [](nb::args a) { call_legacy(spring_vrm_read_debug, a); },
        "Copy SpringBone context debug/state arrays into pre-allocated output buffers.");

    // ---- MC2 上下文管理 ----
    m.def("create_meshcloth_mc2_context",
        [](long vc, long dc, long bc, long crc) {
            return steal_or_throw(hotools::create_meshcloth_mc2_context_object(vc, dc, bc, crc));
        }, nb::arg("vertex_count"), nb::arg("distance_count"),
        nb::arg("bend_count"), nb::arg("collider_radius_count"),
        "Create an MC2 MeshCloth native context handle.");
    m.def("update_meshcloth_mc2_context_static",
        [](nb::object h, long vc, long dc, long bc, long crc) {
            PyObject* r = hotools::update_meshcloth_mc2_context_static_object(h.ptr(), vc, dc, bc, crc);
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        }, nb::arg("handle"), nb::arg("vertex_count"), nb::arg("distance_count"),
        nb::arg("bend_count"), nb::arg("collider_radius_count"),
        "Update MC2 MeshCloth native context static metadata.");
    m.def("update_meshcloth_mc2_context_static_arrays",
        [](nb::args a) { call_legacy(hotools::update_meshcloth_mc2_context_static_arrays, a); },
        "Upload MC2 MeshCloth static topology arrays into a native context.");
    m.def("update_meshcloth_mc2_context_params",
        [](nb::object h, long n) {
            PyObject* r = hotools::update_meshcloth_mc2_context_params_object(h.ptr(), n);
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        }, nb::arg("handle"), nb::arg("param_slot_count"),
        "Update MC2 MeshCloth native context parameter metadata.");
    m.def("update_meshcloth_mc2_context_param_arrays",
        [](nb::args a) { call_legacy(hotools::update_meshcloth_mc2_context_param_arrays, a); },
        "Upload MC2 MeshCloth parameter sample arrays into a native context.");
    m.def("meshcloth_mc2_context_info",
        [](nb::object h) { return steal_or_throw(hotools::meshcloth_mc2_context_info_object(h.ptr())); },
        nb::arg("handle"), "Return MC2 MeshCloth native context metadata.");
    m.def("free_meshcloth_mc2_context",
        [](nb::object h) {
            PyObject* r = hotools::free_meshcloth_mc2_context_object(h.ptr());
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        }, nb::arg("handle"), "Release MC2 MeshCloth native context resources.");
    // ---- New Physics World MC2 context V0 (isolated from the legacy full-core context) ----
    m.def("mc2_context_v0_create",
        [](nb::args a) { return steal_or_throw(hotools::mc2_context_v0_create(nullptr, a.ptr())); });
    m.def("mc2_context_v0_inspect",
        [](nb::args a) { return steal_or_throw(hotools::mc2_context_v0_inspect(nullptr, a.ptr())); });
    m.def("mc2_context_v0_update_proxy_static",
        [](nb::args a) { call_legacy(hotools::mc2_context_v0_update_proxy_static, a); });
    m.def("mc2_context_v0_update_baseline_static",
        [](nb::args a) { call_legacy(hotools::mc2_context_v0_update_baseline_static, a); });
    m.def("mc2_context_v0_update_distance_static",
        [](nb::args a) { call_legacy(hotools::mc2_context_v0_update_distance_static, a); });
    m.def("mc2_context_v0_update_bending_static",
        [](nb::args a) { call_legacy(hotools::mc2_context_v0_update_bending_static, a); });
    m.def("mc2_context_v0_update_center_static",
        [](nb::args a) { call_legacy(hotools::mc2_context_v0_update_center_static, a); });
    m.def("mc2_context_v0_update_center_dynamic",
        [](nb::args a) { call_legacy(hotools::mc2_context_v0_update_center_dynamic, a); });
    m.def("mc2_context_v0_apply_center_frame_shift",
        [](nb::args a) { call_legacy(hotools::mc2_context_v0_apply_center_frame_shift, a); });
    m.def("mc2_context_v0_update_parameters",
        [](nb::args a) { call_legacy(hotools::mc2_context_v0_update_parameters, a); });
    m.def("mc2_context_v0_update_dynamic",
        [](nb::args a) { call_legacy(hotools::mc2_context_v0_update_dynamic, a); });
    m.def("mc2_context_v0_reset",
        [](nb::args a) { call_legacy(hotools::mc2_context_v0_reset, a); });
    m.def("mc2_context_v0_step",
        [](nb::args a) { call_legacy(hotools::mc2_context_v0_step, a); });
    m.def("mc2_context_v0_read",
        [](nb::args a) { call_legacy(hotools::mc2_context_v0_read, a); });
    m.def("mc2_context_v0_read_center_step",
        [](nb::args a) { return steal_or_throw(hotools::mc2_context_v0_read_center_step(nullptr, a.ptr())); });
    m.def("mc2_context_v0_free",
        [](nb::args a) { call_legacy(hotools::mc2_context_v0_free, a); });
    m.def("mc2_context_v0_stats",
        [](nb::args a) { return steal_or_throw(hotools::mc2_context_v0_stats(nullptr, a.ptr())); });
    // ---- MC2 单步约束求解器（ndarray 直传，GIL 在纯 C++ 计算段释放）----
    m.def("project_neighbor_constraints_mc2",
        [](f32_2d pos, cf32_1d inv, ci32_1d starts, ci32_1d counts,
           ci32_1d nbrs, cf32_1d rest, cf32_1d stiff, f32_2d vel, float attn) {
            check_cols(pos, 3, "positions"); check_cols(vel, 3, "velocity_positions");
            const size_t vc = pos.shape(0);
            check_len(inv.shape(0), vc, "inv_masses");
            check_len(starts.shape(0), vc, "starts");
            check_len(counts.shape(0), vc, "counts");
            check_len(stiff.shape(0), vc, "stiffness_values");
            check_len(vel.shape(0), vc, "velocity_positions");
            check_len(rest.shape(0), nbrs.shape(0), "rest_lengths");
            check_indices_in_range(nbrs.data(), nbrs.shape(0), vc, "neighbors");
            hotools::Mc2NeighborConstraintView view;
            view.positions          = pos.data();
            view.inv_masses         = inv.data();
            view.starts             = starts.data();
            view.counts             = counts.data();
            view.neighbors          = nbrs.data();
            view.rest_lengths       = rest.data();
            view.stiffness_values   = stiff.data();
            view.velocity_positions = vel.data();
            view.vertex_count       = static_cast<std::int64_t>(vc);
            view.neighbor_count     = static_cast<std::int64_t>(nbrs.shape(0));
            view.velocity_attenuation = attn;
            { nb::gil_scoped_release _; hotools::project_neighbor_constraints_mc2(view); }
        },
        nb::arg("positions"), nb::arg("inv_masses"), nb::arg("starts"), nb::arg("counts"),
        nb::arg("neighbors"), nb::arg("rest_lengths"), nb::arg("stiffness_values"),
        nb::arg("velocity_positions"), nb::arg("velocity_attenuation"),
        "Project MC2 neighbor constraints in-place.");
    m.def("project_tether_mc2",
        [](f32_2d pos, cf32_1d inv, ci32_1d ri, cf32_1d rrl, f32_2d vel,
           float stiff, float comp, float stretch) {
            check_cols(pos, 3, "positions"); check_cols(vel, 3, "velocity_positions");
            const size_t vc = pos.shape(0);
            check_len(inv.shape(0), vc, "inv_masses");
            check_len(ri.shape(0), vc, "root_indices");
            check_len(rrl.shape(0), vc, "root_rest_lengths");
            check_len(vel.shape(0), vc, "velocity_positions");
            check_root_or_minus_one(ri.data(), vc, vc, "root_indices");
            hotools::Mc2TetherConstraintView view;
            view.positions          = pos.data();
            view.inv_masses         = inv.data();
            view.root_indices       = ri.data();
            view.root_rest_lengths  = rrl.data();
            view.velocity_positions = vel.data();
            view.vertex_count       = static_cast<std::int64_t>(vc);
            view.stiffness          = stiff;
            view.compression        = comp;
            view.stretch            = stretch;
            { nb::gil_scoped_release _; hotools::project_tether_mc2(view); }
        },
        nb::arg("positions"), nb::arg("inv_masses"), nb::arg("root_indices"),
        nb::arg("root_rest_lengths"), nb::arg("velocity_positions"),
        nb::arg("stiffness"), nb::arg("compression"), nb::arg("stretch"),
        "Project MC2 tether constraints in-place.");
    m.def("project_motion_constraints_mc2",
        [](f32_2d pos, cf32_2d bp, cf32_2d br, cf32_1d inv, cf32_1d md,
           cf32_1d sv, cf32_1d bkr, cf32_1d bkd, f32_2d vel, int axis) {
            check_cols(pos, 3, "positions"); check_cols(bp, 3, "base_positions");
            check_cols(br, 4, "base_rotations"); check_cols(vel, 3, "velocity_positions");
            const size_t vc = pos.shape(0);
            check_len(bp.shape(0), vc, "base_positions");
            check_len(br.shape(0), vc, "base_rotations");
            check_len(inv.shape(0), vc, "inv_masses");
            check_len(md.shape(0), vc, "max_distances");
            check_len(sv.shape(0), vc, "stiffness_values");
            check_len(bkr.shape(0), vc, "backstop_radii");
            check_len(bkd.shape(0), vc, "backstop_distances");
            check_len(vel.shape(0), vc, "velocity_positions");
            hotools::Mc2MotionConstraintView view;
            view.positions          = pos.data();
            view.base_positions     = bp.data();
            view.base_rotations     = br.data();
            view.inv_masses         = inv.data();
            view.max_distances      = md.data();
            view.stiffness_values   = sv.data();
            view.backstop_radii     = bkr.data();
            view.backstop_distances = bkd.data();
            view.velocity_positions = vel.data();
            view.vertex_count       = static_cast<std::int64_t>(vc);
            view.normal_axis        = std::max(0, std::min(5, axis));
            { nb::gil_scoped_release _; hotools::project_motion_constraints_mc2(view); }
        },
        nb::arg("positions"), nb::arg("base_positions"), nb::arg("base_rotations"),
        nb::arg("inv_masses"), nb::arg("max_distances"), nb::arg("stiffness_values"),
        nb::arg("backstop_radii"), nb::arg("backstop_distances"),
        nb::arg("velocity_positions"), nb::arg("normal_axis"),
        "Project MC2 motion constraints in-place.");
    m.def("apply_post_step_mc2",
        [](f32_2d pos, f32_2d old, f32_2d vp, f32_2d vel, f32_2d rvel,
           f32_1d fric, f32_1d sfric, cf32_2d cn, cf32_1d inv,
           float dt, float dfric, float sfs, float psl) {
            check_cols(pos, 3, "positions"); check_cols(old, 3, "old_positions");
            check_cols(vp, 3, "velocity_positions"); check_cols(vel, 3, "velocities");
            check_cols(rvel, 3, "real_velocities"); check_cols(cn, 3, "collision_normals");
            const size_t vc = pos.shape(0);
            check_len(old.shape(0), vc, "old_positions");
            check_len(vp.shape(0), vc, "velocity_positions");
            check_len(vel.shape(0), vc, "velocities");
            check_len(rvel.shape(0), vc, "real_velocities");
            check_len(cn.shape(0), vc, "collision_normals");
            check_len(fric.shape(0), vc, "friction");
            check_len(sfric.shape(0), vc, "static_friction");
            check_len(inv.shape(0), vc, "inv_masses");
            hotools::Mc2PostStepView view;
            view.positions           = pos.data();
            view.old_positions       = old.data();
            view.velocity_positions  = vp.data();
            view.velocities          = vel.data();
            view.real_velocities     = rvel.data();
            view.friction            = fric.data();
            view.static_friction     = sfric.data();
            view.collision_normals   = cn.data();
            view.inv_masses          = inv.data();
            view.vertex_count        = static_cast<std::int64_t>(vc);
            view.step_dt             = dt;
            view.dynamic_friction    = dfric;
            view.static_friction_speed = sfs;
            view.particle_speed_limit  = psl;
            { nb::gil_scoped_release _; hotools::apply_post_step_mc2(view); }
        },
        nb::arg("positions"), nb::arg("old_positions"), nb::arg("velocity_positions"),
        nb::arg("velocities"), nb::arg("real_velocities"), nb::arg("friction"),
        nb::arg("static_friction"), nb::arg("collision_normals"), nb::arg("inv_masses"),
        nb::arg("step_dt"), nb::arg("dynamic_friction"),
        nb::arg("static_friction_speed"), nb::arg("particle_speed_limit"),
        "Apply MC2 post-step velocity and friction update in-place.");
    m.def("project_collisions_mc2",
        [](f32_2d pos, cf32_2d bp, cf32_1d inv, cf32_1d cr, f32_2d cn, f32_1d fric,
           int cbg, ci32_1d ct, ci32_1d cgb,
           cf32_2d cc, cf32_2d csa, cf32_2d csb,
           cf32_2d coc, cf32_2d cosa, cf32_2d cosb, cf32_1d crad) {
            check_cols(pos, 3, "positions"); check_cols(bp, 3, "base_positions");
            check_cols(cn, 3, "collision_normals");
            const size_t vc = pos.shape(0);
            check_len(bp.shape(0), vc, "base_positions");
            check_len(cn.shape(0), vc, "collision_normals");
            check_len(inv.shape(0), vc, "inv_masses");
            check_len(cr.shape(0), vc, "collision_radii");
            check_len(fric.shape(0), vc, "friction");
            const size_t nc = static_cast<size_t>(ct.shape(0));
            check_len(cgb.shape(0), nc, "collider_group_bits");
            check_len(crad.shape(0), nc, "collider_radii");
            check_cols(cc, 3, "collider_centers");   check_len(cc.shape(0), nc, "collider_centers");
            check_cols(csa, 3, "collider_segment_a"); check_len(csa.shape(0), nc, "collider_segment_a");
            check_cols(csb, 3, "collider_segment_b"); check_len(csb.shape(0), nc, "collider_segment_b");
            check_cols(coc, 3, "collider_old_centers");    check_len(coc.shape(0), nc, "collider_old_centers");
            check_cols(cosa, 3, "collider_old_segment_a"); check_len(cosa.shape(0), nc, "collider_old_segment_a");
            check_cols(cosb, 3, "collider_old_segment_b"); check_len(cosb.shape(0), nc, "collider_old_segment_b");
            hotools::Mc2CollisionView view;
            view.positions           = pos.data();
            view.base_positions      = bp.data();
            view.inv_masses          = inv.data();
            view.collision_radii     = cr.data();
            view.collision_normals   = cn.data();
            view.friction            = fric.data();
            view.collider_types      = ct.data();
            view.collider_group_bits = cgb.data();
            view.collider_centers    = cc.data();
            view.collider_segment_a  = csa.data();
            view.collider_segment_b  = csb.data();
            view.collider_old_centers   = coc.data();
            view.collider_old_segment_a = cosa.data();
            view.collider_old_segment_b = cosb.data();
            view.collider_radii      = crad.data();
            view.vertex_count        = static_cast<std::int64_t>(vc);
            view.collider_count      = static_cast<std::int64_t>(nc);
            view.collided_by_groups  = static_cast<std::int32_t>(cbg);
            { nb::gil_scoped_release _; hotools::project_collisions_mc2(view); }
        },
        nb::arg("positions"), nb::arg("base_positions"), nb::arg("inv_masses"),
        nb::arg("collision_radii"), nb::arg("collision_normals"), nb::arg("friction"),
        nb::arg("collided_by_groups"), nb::arg("collider_types"), nb::arg("collider_group_bits"),
        nb::arg("collider_centers"), nb::arg("collider_segment_a"), nb::arg("collider_segment_b"),
        nb::arg("collider_old_centers"), nb::arg("collider_old_segment_a"),
        nb::arg("collider_old_segment_b"), nb::arg("collider_radii"),
        "Project MC2 point collisions in-place.");
    m.def("project_edge_collisions_mc2",
        [](f32_2d pos, ci32_2d edges, cu8_1d attr, cf32_1d inv,
           cf32_1d cr, f32_2d cn, f32_1d fric, int cbg,
           ci32_1d ct, ci32_1d cgb, cf32_2d cc, cf32_2d csa, cf32_2d csb,
           cf32_2d coc, cf32_2d cosa, cf32_2d cosb, cf32_1d crad) {
            check_cols(pos, 3, "positions"); check_cols(cn, 3, "collision_normals");
            check_cols(edges, 2, "edges");
            const size_t vc = pos.shape(0);
            check_len(attr.shape(0), vc, "attributes");
            check_len(inv.shape(0), vc, "inv_masses");
            check_len(cr.shape(0), vc, "collision_radii");
            check_len(cn.shape(0), vc, "collision_normals");
            check_len(fric.shape(0), vc, "friction");
            const size_t nc = static_cast<size_t>(ct.shape(0));
            check_len(cgb.shape(0), nc, "collider_group_bits");
            check_len(crad.shape(0), nc, "collider_radii");
            check_cols(cc, 3, "collider_centers");    check_len(cc.shape(0), nc, "collider_centers");
            check_cols(csa, 3, "collider_segment_a"); check_len(csa.shape(0), nc, "collider_segment_a");
            check_cols(csb, 3, "collider_segment_b"); check_len(csb.shape(0), nc, "collider_segment_b");
            check_cols(coc, 3, "collider_old_centers");    check_len(coc.shape(0), nc, "collider_old_centers");
            check_cols(cosa, 3, "collider_old_segment_a"); check_len(cosa.shape(0), nc, "collider_old_segment_a");
            check_cols(cosb, 3, "collider_old_segment_b"); check_len(cosb.shape(0), nc, "collider_old_segment_b");
            hotools::Mc2EdgeCollisionView view;
            view.positions           = pos.data();
            view.edges               = edges.data();
            view.attributes          = attr.data();
            view.inv_masses          = inv.data();
            view.collision_radii     = cr.data();
            view.collision_normals   = cn.data();
            view.friction            = fric.data();
            view.collider_types      = ct.data();
            view.collider_group_bits = cgb.data();
            view.collider_centers    = cc.data();
            view.collider_segment_a  = csa.data();
            view.collider_segment_b  = csb.data();
            view.collider_old_centers   = coc.data();
            view.collider_old_segment_a = cosa.data();
            view.collider_old_segment_b = cosb.data();
            view.collider_radii      = crad.data();
            view.vertex_count        = static_cast<std::int64_t>(vc);
            view.edge_count          = static_cast<std::int64_t>(edges.shape(0));
            view.collider_count      = static_cast<std::int64_t>(nc);
            view.collided_by_groups  = static_cast<std::int32_t>(cbg);
            { nb::gil_scoped_release _; hotools::project_edge_collisions_mc2(view); }
        },
        nb::arg("positions"), nb::arg("edges"), nb::arg("attributes"),
        nb::arg("inv_masses"), nb::arg("collision_radii"), nb::arg("collision_normals"),
        nb::arg("friction"), nb::arg("collided_by_groups"), nb::arg("collider_types"),
        nb::arg("collider_group_bits"), nb::arg("collider_centers"),
        nb::arg("collider_segment_a"), nb::arg("collider_segment_b"),
        nb::arg("collider_old_centers"), nb::arg("collider_old_segment_a"),
        nb::arg("collider_old_segment_b"), nb::arg("collider_radii"),
        "Project MC2 edge collisions in-place.");
    m.def("project_self_collisions_mc2",
        [](f32_2d pos, cf32_2d old, cf32_1d inv, ci32_2d edges,
           ci32_2d tri, cu8_1d attr, f32_2d cn, f32_1d fric, float st) {
            check_cols(pos, 3, "positions"); check_cols(old, 3, "old_positions");
            check_cols(cn, 3, "collision_normals");
            check_cols(edges, 2, "edges"); check_cols(tri, 3, "triangles");
            const size_t vc = pos.shape(0);
            check_len(old.shape(0), vc, "old_positions");
            check_len(inv.shape(0), vc, "inv_masses");
            check_len(attr.shape(0), vc, "attributes");
            check_len(cn.shape(0), vc, "collision_normals");
            check_len(fric.shape(0), vc, "friction");
            hotools::Mc2SelfCollisionView view;
            view.positions        = pos.data();
            view.old_positions    = old.data();
            view.inv_masses       = inv.data();
            view.edges            = edges.data();
            view.triangles        = tri.data();
            view.attributes       = attr.data();
            view.collision_normals = cn.data();
            view.friction         = fric.data();
            view.vertex_count     = static_cast<std::int64_t>(vc);
            view.edge_count       = static_cast<std::int64_t>(edges.shape(0));
            view.triangle_count   = static_cast<std::int64_t>(tri.shape(0));
            view.surface_thickness = st;
            { nb::gil_scoped_release _; hotools::project_self_collisions_mc2(view); }
        },
        nb::arg("positions"), nb::arg("old_positions"), nb::arg("inv_masses"),
        nb::arg("edges"), nb::arg("triangles"), nb::arg("attributes"),
        nb::arg("collision_normals"), nb::arg("friction"), nb::arg("surface_thickness"),
        "Project MC2 self collisions in-place.");
    m.def("project_triangle_bending_mc2",
        [](f32_2d pos, cf32_1d inv, ci32_2d dp, cf32_1d dra,
           ci32_1d ds, ci32_2d vp, cf32_1d vr, cf32_1d sv) {
            check_cols(pos, 3, "positions");
            check_cols(dp, 4, "dihedral_pairs"); check_cols(vp, 4, "volume_pairs");
            const size_t vc = pos.shape(0);
            check_len(inv.shape(0), vc, "inv_masses");
            const size_t dc = static_cast<size_t>(dp.shape(0));
            const size_t volc = static_cast<size_t>(vp.shape(0));
            check_len(dra.shape(0), dc, "dihedral_rest_angles");
            check_len(ds.shape(0), dc, "dihedral_signs");
            check_len(vr.shape(0), volc, "volume_rest");
            check_len(sv.shape(0), vc, "stiffness_values");
            hotools::Mc2TriangleBendingView view;
            view.positions            = pos.data();
            view.inv_masses           = inv.data();
            view.dihedral_pairs       = dp.data();
            view.dihedral_rest_angles = dra.data();
            view.dihedral_signs       = ds.data();
            view.volume_pairs         = vp.data();
            view.volume_rest          = vr.data();
            view.stiffness_values     = sv.data();
            view.vertex_count         = static_cast<std::int64_t>(vc);
            view.dihedral_count       = static_cast<std::int64_t>(dc);
            view.volume_count         = static_cast<std::int64_t>(volc);
            { nb::gil_scoped_release _; hotools::project_triangle_bending_mc2(view); }
        },
        nb::arg("positions"), nb::arg("inv_masses"), nb::arg("dihedral_pairs"),
        nb::arg("dihedral_rest_angles"), nb::arg("dihedral_signs"),
        nb::arg("volume_pairs"), nb::arg("volume_rest"), nb::arg("stiffness_values"),
        "Project MC2 triangle bending constraints in-place.");
    m.def("project_angle_constraints_mc2",
        [](f32_2d pos, cf32_1d inv, ci32_1d pi, ci32_1d bs,
           ci32_1d bc, ci32_1d bd, cf32_2d sbp, cf32_2d sbr,
           cf32_1d rv, cf32_1d lv, f32_2d vel, float rva, float rgf, float ls) {
            check_cols(pos, 3, "positions");
            check_cols(sbp, 3, "step_basic_positions");
            check_cols(sbr, 4, "step_basic_rotations");
            check_cols(vel, 3, "velocity_positions");
            const size_t vc = pos.shape(0);
            check_len(inv.shape(0), vc, "inv_masses");
            check_len(pi.shape(0), vc, "parent_indices");
            check_len(sbp.shape(0), vc, "step_basic_positions");
            check_len(sbr.shape(0), vc, "step_basic_rotations");
            check_len(rv.shape(0), vc, "restoration_values");
            check_len(lv.shape(0), vc, "limit_values");
            check_len(vel.shape(0), vc, "velocity_positions");
            check_root_or_minus_one(pi.data(), vc, vc, "parent_indices");
            const size_t lc = static_cast<size_t>(bs.shape(0));
            check_len(bc.shape(0), lc, "baseline_count");
            check_indices_in_range(bd.data(), bd.shape(0), vc, "baseline_data");
            hotools::Mc2AngleConstraintView view;
            view.positions              = pos.data();
            view.inv_masses             = inv.data();
            view.parent_indices         = pi.data();
            view.baseline_start         = bs.data();
            view.baseline_count         = bc.data();
            view.baseline_data          = bd.data();
            view.step_basic_positions   = sbp.data();
            view.step_basic_rotations   = sbr.data();
            view.restoration_values     = rv.data();
            view.limit_values           = lv.data();
            view.velocity_positions     = vel.data();
            view.vertex_count           = static_cast<std::int64_t>(vc);
            view.line_count             = static_cast<std::int64_t>(lc);
            view.baseline_data_count    = static_cast<std::int64_t>(bd.shape(0));
            view.restoration_velocity_attenuation = rva;
            view.restoration_gravity_falloff      = rgf;
            view.limit_stiffness                  = ls;
            { nb::gil_scoped_release _; hotools::project_angle_constraints_mc2(view); }
        },
        nb::arg("positions"), nb::arg("inv_masses"), nb::arg("parent_indices"),
        nb::arg("baseline_start"), nb::arg("baseline_count"), nb::arg("baseline_data"),
        nb::arg("step_basic_positions"), nb::arg("step_basic_rotations"),
        nb::arg("restoration_values"), nb::arg("limit_values"), nb::arg("velocity_positions"),
        nb::arg("restoration_velocity_attenuation"), nb::arg("restoration_gravity_falloff"),
        nb::arg("limit_stiffness"),
        "Project MC2 angle restoration and limit constraints in-place.");
    m.def("update_step_basic_pose_mc2",
        [](cf32_2d bp, cf32_2d br, ci32_1d pi, ci32_1d bstart, ci32_1d bcount,
           ci32_1d bd, cf32_2d vlp, cf32_2d vlr, f32_2d sp, f32_2d sr, float apr) {
            check_cols(bp, 3, "base_positions"); check_cols(br, 4, "base_rotations");
            check_cols(vlp, 3, "vertex_local_positions"); check_cols(vlr, 4, "vertex_local_rotations");
            check_cols(sp, 3, "step_positions"); check_cols(sr, 4, "step_rotations");
            const size_t vc = bp.shape(0);
            check_len(br.shape(0), vc, "base_rotations");
            check_len(pi.shape(0), vc, "parent_indices");
            check_len(vlp.shape(0), vc, "vertex_local_positions");
            check_len(vlr.shape(0), vc, "vertex_local_rotations");
            check_len(sp.shape(0), vc, "step_positions");
            check_len(sr.shape(0), vc, "step_rotations");
            check_root_or_minus_one(pi.data(), vc, vc, "parent_indices");
            const size_t lc = static_cast<size_t>(bstart.shape(0));
            check_len(bcount.shape(0), lc, "baseline_count");
            check_indices_in_range(bd.data(), bd.shape(0), vc, "baseline_data");
            hotools::Mc2StepBasicPoseView view;
            view.base_positions          = bp.data();
            view.base_rotations          = br.data();
            view.parent_indices          = pi.data();
            view.baseline_start          = bstart.data();
            view.baseline_count          = bcount.data();
            view.baseline_data           = bd.data();
            view.vertex_local_positions  = vlp.data();
            view.vertex_local_rotations  = vlr.data();
            view.step_positions          = sp.data();
            view.step_rotations          = sr.data();
            view.vertex_count            = static_cast<std::int64_t>(vc);
            view.line_count              = static_cast<std::int64_t>(lc);
            view.baseline_data_count     = static_cast<std::int64_t>(bd.shape(0));
            view.animation_pose_ratio    = apr;
            { nb::gil_scoped_release _; hotools::update_step_basic_pose_mc2(view); }
        },
        nb::arg("base_positions"), nb::arg("base_rotations"), nb::arg("parent_indices"),
        nb::arg("baseline_start"), nb::arg("baseline_count"), nb::arg("baseline_data"),
        nb::arg("vertex_local_positions"), nb::arg("vertex_local_rotations"),
        nb::arg("step_positions"), nb::arg("step_rotations"), nb::arg("animation_pose_ratio"),
        "Update MC2 step basic pose in-place.");
    m.def("update_base_pose_from_pose_mc2",
        [](cf32_2d bp, cf32_2d bn, ci32_1d pi, ci32_1d bstart, ci32_1d bcount,
           ci32_1d bd, cf32_2d vlp, cf32_2d vlr, f32_2d br2, f32_2d sp, f32_2d sr, float apr) {
            check_cols(bp, 3, "base_positions"); check_cols(bn, 3, "base_normals");
            check_cols(vlp, 3, "vertex_local_positions"); check_cols(vlr, 4, "vertex_local_rotations");
            check_cols(br2, 4, "base_rotations"); check_cols(sp, 3, "step_positions");
            check_cols(sr, 4, "step_rotations");
            const size_t vc = bp.shape(0);
            check_len(bn.shape(0), vc, "base_normals");
            check_len(pi.shape(0), vc, "parent_indices");
            check_len(vlp.shape(0), vc, "vertex_local_positions");
            check_len(vlr.shape(0), vc, "vertex_local_rotations");
            check_len(br2.shape(0), vc, "base_rotations");
            check_len(sp.shape(0), vc, "step_positions");
            check_len(sr.shape(0), vc, "step_rotations");
            check_root_or_minus_one(pi.data(), vc, vc, "parent_indices");
            const size_t lc = static_cast<size_t>(bstart.shape(0));
            check_len(bcount.shape(0), lc, "baseline_count");
            check_indices_in_range(bd.data(), bd.shape(0), vc, "baseline_data");
            hotools::Mc2BasePoseFromPoseView view;
            view.base_positions          = bp.data();
            view.base_normals            = bn.data();
            view.parent_indices          = pi.data();
            view.baseline_start          = bstart.data();
            view.baseline_count          = bcount.data();
            view.baseline_data           = bd.data();
            view.vertex_local_positions  = vlp.data();
            view.vertex_local_rotations  = vlr.data();
            view.base_rotations          = br2.data();
            view.step_positions          = sp.data();
            view.step_rotations          = sr.data();
            view.vertex_count            = static_cast<std::int64_t>(vc);
            view.line_count              = static_cast<std::int64_t>(lc);
            view.baseline_data_count     = static_cast<std::int64_t>(bd.shape(0));
            view.animation_pose_ratio    = apr;
            { nb::gil_scoped_release _; hotools::update_base_pose_from_pose_mc2(view); }
        },
        nb::arg("base_positions"), nb::arg("base_normals"), nb::arg("parent_indices"),
        nb::arg("baseline_start"), nb::arg("baseline_count"), nb::arg("baseline_data"),
        nb::arg("vertex_local_positions"), nb::arg("vertex_local_rotations"),
        nb::arg("base_rotations"), nb::arg("step_positions"), nb::arg("step_rotations"),
        nb::arg("animation_pose_ratio"),
        "Update MC2 base rotations and step basic pose from BasePose positions/normals in-place.");
    m.def("apply_substep_inertia_mc2",
        [](f32_2d old, f32_2d vel, cf32_1d dep, cf32_1d inv,
           cf32_1d owp, cf32_1d sv, cf32_1d sr, cf32_1d iv, cf32_1d ir, float di) {
            check_cols(old, 3, "old_positions"); check_cols(vel, 3, "velocities");
            const size_t vc = old.shape(0);
            check_len(vel.shape(0), vc, "velocities");
            check_len(dep.shape(0), vc, "depths");
            check_len(inv.shape(0), vc, "inv_masses");
            if (owp.shape(0) != 3) throw nb::value_error("old_world_position 需要3个元素");
            if (sv.shape(0) != 3)  throw nb::value_error("step_vector 需要3个元素");
            if (sr.shape(0) != 4)  throw nb::value_error("step_rotation 需要4个元素");
            if (iv.shape(0) != 3)  throw nb::value_error("inertia_vector 需要3个元素");
            if (ir.shape(0) != 4)  throw nb::value_error("inertia_rotation 需要4个元素");
            hotools::Mc2SubstepInertiaView view;
            view.old_positions = old.data();
            view.velocities    = vel.data();
            view.depths        = dep.data();
            view.inv_masses    = inv.data();
            view.vertex_count  = static_cast<std::int64_t>(vc);
            const float* owp_d = owp.data();
            const float* sv_d  = sv.data();
            const float* sr_d  = sr.data();
            const float* iv_d  = iv.data();
            const float* ir_d  = ir.data();
            for (int i = 0; i < 3; ++i) {
                view.old_world_position[i] = owp_d[i];
                view.step_vector[i]        = sv_d[i];
                view.inertia_vector[i]     = iv_d[i];
            }
            for (int i = 0; i < 4; ++i) {
                view.step_rotation[i]    = sr_d[i];
                view.inertia_rotation[i] = ir_d[i];
            }
            view.depth_inertia = di;
            { nb::gil_scoped_release _; hotools::apply_substep_inertia_mc2(view); }
        },
        nb::arg("old_positions"), nb::arg("velocities"), nb::arg("depths"),
        nb::arg("inv_masses"), nb::arg("old_world_position"), nb::arg("step_vector"),
        nb::arg("step_rotation"), nb::arg("inertia_vector"), nb::arg("inertia_rotation"),
        nb::arg("depth_inertia"),
        "Apply MC2 substep inertia in-place.");
    m.def("apply_centrifugal_velocity_mc2",
        [](cf32_2d pos, f32_2d vel, cf32_1d dep, cf32_1d inv,
           cf32_1d nwp, cf32_1d ra, float av, float cf_val) {
            check_cols(pos, 3, "positions"); check_cols(vel, 3, "velocities");
            const size_t vc = pos.shape(0);
            check_len(vel.shape(0), vc, "velocities");
            check_len(dep.shape(0), vc, "depths");
            check_len(inv.shape(0), vc, "inv_masses");
            if (nwp.shape(0) != 3) throw nb::value_error("now_world_position 需要3个元素");
            if (ra.shape(0) != 3)  throw nb::value_error("rotation_axis 需要3个元素");
            hotools::Mc2CentrifugalView view;
            view.positions    = pos.data();
            view.velocities   = vel.data();
            view.depths       = dep.data();
            view.inv_masses   = inv.data();
            view.vertex_count = static_cast<std::int64_t>(vc);
            const float* nwp_d = nwp.data();
            const float* ra_d  = ra.data();
            for (int i = 0; i < 3; ++i) {
                view.now_world_position[i] = nwp_d[i];
                view.rotation_axis[i]      = ra_d[i];
            }
            view.angular_velocity = av;
            view.centrifugal      = cf_val;
            { nb::gil_scoped_release _; hotools::apply_centrifugal_velocity_mc2(view); }
        },
        nb::arg("positions"), nb::arg("velocities"), nb::arg("depths"), nb::arg("inv_masses"),
        nb::arg("now_world_position"), nb::arg("rotation_axis"),
        nb::arg("angular_velocity"), nb::arg("centrifugal"),
        "Apply MC2 centrifugal velocity in-place.");
    m.def("calculate_display_positions_mc2",
        [](cf32_2d pos, cf32_2d rvel, ci32_1d ri, f32_2d dp, float fdt, float mdr) {
            check_cols(pos, 3, "positions"); check_cols(rvel, 3, "real_velocities");
            check_cols(dp, 3, "display_positions");
            const size_t vc = pos.shape(0);
            check_len(rvel.shape(0), vc, "real_velocities");
            check_len(ri.shape(0), vc, "root_indices");
            check_len(dp.shape(0), vc, "display_positions");
            hotools::Mc2DisplayPredictionView view;
            view.positions         = pos.data();
            view.real_velocities   = rvel.data();
            view.root_indices      = ri.data();
            view.display_positions = dp.data();
            view.vertex_count      = static_cast<std::int64_t>(vc);
            view.frame_dt          = fdt;
            view.max_distance_ratio = mdr;
            { nb::gil_scoped_release _; hotools::calculate_display_positions_mc2(view); }
        },
        nb::arg("positions"), nb::arg("real_velocities"), nb::arg("root_indices"),
        nb::arg("display_positions"), nb::arg("frame_dt"), nb::arg("max_distance_ratio"),
        "Calculate MC2 display future prediction in-place.");
    // ---- MC2 网格布料大函数 ----
    m.def("solve_meshcloth_mc2",
        [](nb::args a) { call_legacy(solve_meshcloth_mc2, a); },
        "Solve one MC2 MeshCloth array frame in-place.");
    m.def("solve_meshcloth_mc2_context",
        [](nb::args a) { call_legacy(hotools::solve_meshcloth_mc2_context, a); },
        "Solve one MC2 MeshCloth frame using a native context for static arrays.");
    m.def("solve_meshcloth_mc2_context_cached_params",
        [](nb::args a) { call_legacy(hotools::solve_meshcloth_mc2_context_cached_params, a); },
        "Solve one MC2 MeshCloth frame using native context static and parameter arrays.");

    // ---- 骨骼布料 IO ----
    m.def("solve_mc2_bonecloth_io",
        [](f32_2d wr, cf32_2d dp, cf32_2d bp, cf32_2d br,
           cf32_2d vlp, cf32_2d vlr, ci32_1d pi, ci32_1d bstart,
           ci32_1d bcount, ci32_1d bd, cu8_1d attr,
           float ri, float bw, float ar, float rr) {
            check_cols(wr, 4, "world_rotations");
            check_cols(dp, 3, "display_positions");
            check_cols(bp, 3, "base_positions");
            check_cols(br, 4, "base_rotations");
            check_cols(vlp, 3, "vertex_local_positions");
            check_cols(vlr, 4, "vertex_local_rotations");
            const size_t vc = static_cast<size_t>(wr.shape(0));
            check_len(dp.shape(0), vc, "display_positions");
            check_len(bp.shape(0), vc, "base_positions");
            check_len(br.shape(0), vc, "base_rotations");
            check_len(vlp.shape(0), vc, "vertex_local_positions");
            check_len(vlr.shape(0), vc, "vertex_local_rotations");
            check_len(pi.shape(0), vc, "parent_indices");
            check_len(attr.shape(0), vc, "attributes");
            const size_t lc = static_cast<size_t>(bstart.shape(0));
            check_len(bcount.shape(0), lc, "baseline_count");
            check_indices_in_range(bd.data(), bd.shape(0), vc, "baseline_data");
            hotools::BoneClothIoView view;
            view.world_rotations        = wr.data();
            view.display_positions      = dp.data();
            view.base_positions         = bp.data();
            view.base_rotations         = br.data();
            view.vertex_local_positions = vlp.data();
            view.vertex_local_rotations = vlr.data();
            view.parent_indices         = pi.data();
            view.baseline_start         = bstart.data();
            view.baseline_count         = bcount.data();
            view.baseline_data          = bd.data();
            view.attributes             = attr.data();
            view.rotational_interpolation = ri;
            view.blend_weight             = bw;
            view.anime_ratio              = ar;
            view.root_rotation            = rr;
            view.vertex_count             = static_cast<std::int64_t>(vc);
            view.baseline_lines           = static_cast<std::int64_t>(lc);
            view.baseline_total           = static_cast<std::int64_t>(bd.shape(0));
            { nb::gil_scoped_release _; hotools::solve_bonecloth_io(view); }
        },
        nb::arg("world_rotations"), nb::arg("display_positions"),
        nb::arg("base_positions"), nb::arg("base_rotations"),
        nb::arg("vertex_local_positions"), nb::arg("vertex_local_rotations"),
        nb::arg("parent_indices"), nb::arg("baseline_start"),
        nb::arg("baseline_count"), nb::arg("baseline_data"), nb::arg("attributes"),
        nb::arg("rotational_interpolation"), nb::arg("blend_weight"),
        nb::arg("anime_ratio"), nb::arg("root_rotation"),
        "Compute MC2 BoneCloth chain-propagated world rotations in-place.");
}
