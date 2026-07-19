#include <Python.h>

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include "mc2_bindings.hpp"
#include "mc2_kernels.hpp"
#include "mc2_api.hpp"
#include "mc2_static_build.hpp"
#include "python_buffer_utils.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace nb = nanobind;

namespace {

using namespace hotools::py;

// ---------------------------------------------------------------------------
// nanobind ndarray 类型别名（按可变/只读、维度、元素类型分类）
// ---------------------------------------------------------------------------
using f32_2d  = nb::ndarray<float,          nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using f32_1d  = nb::ndarray<float,          nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using f64_2d  = nb::ndarray<double,         nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using f64_1d  = nb::ndarray<double,         nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using cf64_2d = nb::ndarray<const double,   nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using cf64_1d = nb::ndarray<const double,   nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using i32_2d  = nb::ndarray<int32_t,        nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using i32_1d  = nb::ndarray<int32_t,        nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using u8_1d   = nb::ndarray<uint8_t,        nb::ndim<1>, nb::c_contig, nb::device::cpu>;
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
inline void call_pyobject_api(PyObject* (*fn)(PyObject*, PyObject*), nb::args a) {
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

template<typename T>
nb::ndarray<nb::numpy, T> owned_array_1d(
    std::vector<T>&& values,
    nb::dict* result = nullptr,
    const char* owner_key = nullptr,
    const char* capsule_name = nullptr
) {
    auto* owner_data = new std::vector<T>(std::move(values));
    nb::capsule owner = capsule_name
        ? nb::capsule(owner_data, capsule_name, [](void* pointer) noexcept {
            delete static_cast<std::vector<T>*>(pointer);
        })
        : nb::capsule(owner_data, [](void* pointer) noexcept {
            delete static_cast<std::vector<T>*>(pointer);
        });
    if (result != nullptr && owner_key != nullptr) (*result)[owner_key] = owner;
    return nb::ndarray<nb::numpy, T>(
        owner_data->data(), {owner_data->size()}, owner
    );
}

template<typename T>
nb::ndarray<nb::numpy, T> owned_array_2d(
    std::vector<T>&& values,
    std::size_t rows,
    std::size_t columns,
    nb::dict* result = nullptr,
    const char* owner_key = nullptr,
    const char* capsule_name = nullptr
) {
    if (rows * columns != values.size()) {
        throw nb::value_error("owned ndarray shape does not match storage");
    }
    auto* owner_data = new std::vector<T>(std::move(values));
    nb::capsule owner = capsule_name
        ? nb::capsule(owner_data, capsule_name, [](void* pointer) noexcept {
            delete static_cast<std::vector<T>*>(pointer);
        })
        : nb::capsule(owner_data, [](void* pointer) noexcept {
            delete static_cast<std::vector<T>*>(pointer);
        });
    if (result != nullptr && owner_key != nullptr) (*result)[owner_key] = owner;
    return nb::ndarray<nb::numpy, T>(
        owner_data->data(), {rows, columns}, owner
    );
}

std::vector<float> float_vector(const double* values, std::size_t count) {
    std::vector<float> result(count);
    std::transform(values, values + count, result.begin(), [](double value) {
        return static_cast<float>(value);
    });
    return result;
}

}  // namespace

void hotools::bind_mc2(nb::module_& m) {
    // ---- Physics World MC2 context V0 ----
    m.def("mc2_interaction_v0_create",
        [](nb::args a) { return steal_or_throw(hotools::mc2_interaction_v0_create(nullptr, a.ptr())); });
    m.def("mc2_interaction_v0_inspect",
        [](nb::args a) { return steal_or_throw(hotools::mc2_interaction_v0_inspect(nullptr, a.ptr())); });
    m.def("mc2_interaction_v0_invalidate",
        [](nb::args a) { call_pyobject_api(hotools::mc2_interaction_v0_invalidate, a); });
    m.def("mc2_interaction_v0_step_group",
        [](nb::args a) { call_pyobject_api(hotools::mc2_interaction_v0_step_group, a); });
    m.def("mc2_interaction_v0_read_debug",
        [](nb::args a) { call_pyobject_api(hotools::mc2_interaction_v0_read_debug, a); });
    m.def("mc2_interaction_v0_free",
        [](nb::args a) { call_pyobject_api(hotools::mc2_interaction_v0_free, a); });
    m.def("mc2_context_v0_create",
        [](nb::args a) { return steal_or_throw(hotools::mc2_context_v0_create(nullptr, a.ptr())); });
    m.def("mc2_context_v0_inspect",
        [](nb::args a) { return steal_or_throw(hotools::mc2_context_v0_inspect(nullptr, a.ptr())); });
    m.def("mc2_context_v0_classify_static_fingerprint",
        [](nb::args a) { return steal_or_throw(hotools::mc2_context_v0_classify_static_fingerprint(nullptr, a.ptr())); });
    m.def("mc2_context_v0_update_static_fingerprint",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_update_static_fingerprint, a); });
    m.def("mc2_context_v0_clone_config_static",
        [](nb::args a) { return steal_or_throw(hotools::mc2_context_v0_clone_config_static(nullptr, a.ptr())); });
    m.def("mc2_context_v0_update_proxy_static",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_update_proxy_static, a); });
    m.def("mc2_context_v0_finalize_proxy_attributes",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_finalize_proxy_attributes, a); });
    m.def("mc2_context_v0_update_baseline_static",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_update_baseline_static, a); });
    m.def("mc2_context_v0_update_bone_static",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_update_bone_static, a); });
    m.def("mc2_context_v0_update_frame_producer_static",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_update_frame_producer_static, a); });
    m.def("mc2_context_v0_update_distance_static",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_update_distance_static, a); });
    m.def("mc2_context_v0_update_bending_static",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_update_bending_static, a); });
    m.def("mc2_context_v0_update_self_collision_static",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_update_self_collision_static, a); });
    m.def("mc2_context_v0_update_center_static",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_update_center_static, a); });
    m.def("mc2_context_v0_update_center_dynamic",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_update_center_dynamic, a); });
    m.def("mc2_context_v0_update_step_interpolation",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_update_step_interpolation, a); });
    m.def("mc2_context_v0_update_team_options",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_update_team_options, a); });
    m.def("mc2_context_v0_set_setup_kind",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_set_setup_kind, a); });
    m.def("mc2_context_v0_set_tether_enabled",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_set_tether_enabled, a); });
    m.def("mc2_context_v0_apply_center_frame_shift",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_apply_center_frame_shift, a); });
    m.def("mc2_context_v0_apply_center_negative_scale_teleport",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_apply_center_negative_scale_teleport, a); });
    m.def("mc2_context_v0_apply_task_teleport",
        [](nb::args a) { return steal_or_throw(hotools::mc2_context_v0_apply_task_teleport(nullptr, a.ptr())); });
    m.def("mc2_context_v0_update_parameters",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_update_parameters, a); });
    m.def("mc2_context_v0_update_dynamic",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_update_dynamic, a); });
    m.def("mc2_context_v0_derive_center_pose_raw",
        [](nb::args a) { return steal_or_throw(hotools::mc2_context_v0_derive_center_pose_raw(nullptr, a.ptr())); });
    m.def("mc2_context_v0_update_mesh_dynamic_raw",
        [](nb::args a) { return steal_or_throw(hotools::mc2_context_v0_update_mesh_dynamic_raw(nullptr, a.ptr())); });
    m.def("mc2_context_v0_update_bone_dynamic_raw",
        [](nb::args a) { return steal_or_throw(hotools::mc2_context_v0_update_bone_dynamic_raw(nullptr, a.ptr())); });
    m.def("mc2_context_v0_update_colliders",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_update_colliders, a); });
    m.def("mc2_context_v0_reset",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_reset, a); });
    m.def("mc2_context_v0_step",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_step, a); });
    m.def("mc2_context_v0_read",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read, a); });
    m.def("mc2_context_v0_read_self_collision_primitives",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_self_collision_primitives, a); });
    m.def("mc2_context_v0_read_self_collision_grid",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_self_collision_grid, a); });
    m.def("mc2_context_v0_read_self_collision_candidates",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_self_collision_candidates, a); });
    m.def("mc2_context_v0_read_self_collision_contacts",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_self_collision_contacts, a); });
    m.def("mc2_context_v0_read_self_collision_intersections",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_self_collision_intersections, a); });
    m.def("mc2_context_v0_read_debug_self_indices",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_debug_self_indices, a); });
    m.def("mc2_context_v0_read_debug_self_grid",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_debug_self_grid, a); });
    m.def("mc2_context_v0_read_debug_self_candidates",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_debug_self_candidates, a); });
    m.def("mc2_context_v0_read_debug_self_contacts",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_debug_self_contacts, a); });
    m.def("mc2_context_v0_read_debug_self_intersections",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_debug_self_intersections, a); });
    m.def("mc2_context_v0_read_bone_output",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_bone_output, a); });
    m.def("mc2_context_v0_read_step_basic",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_step_basic, a); });
    m.def("mc2_context_v0_read_debug_baseline",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_debug_baseline, a); });
    m.def("mc2_context_v0_read_debug_motion_base",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_debug_motion_base, a); });
    m.def("mc2_context_v0_read_debug_angle_restoration",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_debug_angle_restoration, a); });
    m.def("mc2_context_v0_read_debug_angle_limit",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_debug_angle_limit, a); });
    m.def("mc2_context_v0_read_debug_dynamics",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_debug_dynamics, a); });
    m.def("mc2_context_v0_read_debug_distance_tether",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_debug_distance_tether, a); });
    m.def("mc2_context_v0_read_debug_bending",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_read_debug_bending, a); });
    m.def("mc2_context_v0_read_center_step",
        [](nb::args a) { return steal_or_throw(hotools::mc2_context_v0_read_center_step(nullptr, a.ptr())); });
    m.def("mc2_context_v0_free",
        [](nb::args a) { call_pyobject_api(hotools::mc2_context_v0_free, a); });
    m.def("mc2_context_v0_stats",
        [](nb::args a) { return steal_or_throw(hotools::mc2_context_v0_stats(nullptr, a.ptr())); });
    m.def("mc2_mesh_static_fingerprint_v0",
        [](nb::args a) { return steal_or_throw(hotools::mc2_mesh_static_fingerprint_v0(nullptr, a.ptr())); });
    m.def("mc2_bone_static_fingerprint_v0",
        [](nb::args a) { return steal_or_throw(hotools::mc2_bone_static_fingerprint_v0(nullptr, a.ptr())); });
    m.def("mc2_optimize_triangle_direction_v0",
        [](cf64_2d positions, i32_2d triangles, f64_2d triangle_normals) {
            check_cols(positions, 3, "positions");
            check_cols(triangles, 3, "triangles");
            check_cols(triangle_normals, 3, "triangle_normals");
            check_len(triangle_normals.shape(0), triangles.shape(0), "triangle_normals");
            check_indices_in_range(
                triangles.data(),
                triangles.shape(0) * 3,
                positions.shape(0),
                "triangles"
            );
            try {
                nb::gil_scoped_release release;
                hotools::mc2_optimize_triangle_direction(
                    positions.data(),
                    positions.shape(0),
                    triangles.data(),
                    triangles.shape(0),
                    triangle_normals.data()
                );
            } catch (const std::invalid_argument& error) {
                throw nb::value_error(error.what());
            }
        });
    m.def("mc2_build_mesh_fallback_tangents_v0",
        [](f64_2d local_normals, f64_2d local_tangents) {
            check_cols(local_normals, 3, "local_normals");
            check_cols(local_tangents, 3, "local_tangents");
            check_len(local_tangents.shape(0), local_normals.shape(0), "local_tangents");
            try {
                nb::gil_scoped_release release;
                hotools::mc2_normalize_mesh_normals_and_fallback_tangents(
                    local_normals.data(),
                    local_normals.shape(0),
                    local_tangents.data()
                );
            } catch (const std::invalid_argument& error) {
                throw nb::value_error(error.what());
            }
        });
    m.def("mc2_build_bone_rest_frames_v0",
        [](cf32_2d matrices,
           f64_2d transform_rotations,
           f64_2d local_normals,
           f64_2d local_tangents) {
            check_cols(matrices, 16, "matrices");
            check_cols(transform_rotations, 4, "transform_rotations");
            check_cols(local_normals, 3, "local_normals");
            check_cols(local_tangents, 3, "local_tangents");
            check_len(transform_rotations.shape(0), matrices.shape(0), "transform_rotations");
            check_len(local_normals.shape(0), matrices.shape(0), "local_normals");
            check_len(local_tangents.shape(0), matrices.shape(0), "local_tangents");
            try {
                nb::gil_scoped_release release;
                hotools::mc2_build_bone_rest_frames(
                    matrices.data(),
                    matrices.shape(0),
                    transform_rotations.data(),
                    local_normals.data(),
                    local_tangents.data()
                );
            } catch (const std::invalid_argument& error) {
                throw nb::value_error(error.what());
            }
        });
    m.def("mc2_build_bone_vertex_to_transform_rotations_v0",
        [](cf64_2d local_normals,
           cf64_2d local_tangents,
           cf64_2d transform_rotations,
           f64_2d vertex_to_transform_rotations) {
            check_cols(local_normals, 3, "local_normals");
            check_cols(local_tangents, 3, "local_tangents");
            check_cols(transform_rotations, 4, "transform_rotations");
            check_cols(vertex_to_transform_rotations, 4, "vertex_to_transform_rotations");
            check_len(local_tangents.shape(0), local_normals.shape(0), "local_tangents");
            check_len(transform_rotations.shape(0), local_normals.shape(0), "transform_rotations");
            check_len(vertex_to_transform_rotations.shape(0), local_normals.shape(0), "vertex_to_transform_rotations");
            try {
                nb::gil_scoped_release release;
                hotools::mc2_build_bone_vertex_to_transform_rotations(
                    local_normals.data(),
                    local_tangents.data(),
                    transform_rotations.data(),
                    local_normals.shape(0),
                    vertex_to_transform_rotations.data()
                );
            } catch (const std::invalid_argument& error) {
                throw nb::value_error(error.what());
            }
        });
    m.def("mc2_build_bone_registration_rotations_v0",
        [](cf64_2d local_normals,
           cf64_2d local_tangents,
           cf64_2d transform_rotations,
           cf64_2d adjustment_rotations,
           f64_2d vertex_to_transform_rotations) {
            check_cols(local_normals, 3, "local_normals");
            check_cols(local_tangents, 3, "local_tangents");
            check_cols(transform_rotations, 4, "transform_rotations");
            check_cols(adjustment_rotations, 4, "adjustment_rotations");
            check_cols(vertex_to_transform_rotations, 4, "vertex_to_transform_rotations");
            const auto vertex_count = local_normals.shape(0);
            check_len(local_tangents.shape(0), vertex_count, "local_tangents");
            check_len(transform_rotations.shape(0), vertex_count, "transform_rotations");
            check_len(adjustment_rotations.shape(0), vertex_count, "adjustment_rotations");
            check_len(vertex_to_transform_rotations.shape(0), vertex_count, "vertex_to_transform_rotations");
            try {
                nb::gil_scoped_release release;
                hotools::mc2_build_bone_vertex_to_transform_rotations(
                    local_normals.data(),
                    local_tangents.data(),
                    transform_rotations.data(),
                    vertex_count,
                    vertex_to_transform_rotations.data()
                );
            } catch (const std::invalid_argument& error) {
                throw nb::value_error(error.what());
            }
            nb::dict result;
            result["normal_adjustment_rotations"] = owned_array_2d(
                float_vector(adjustment_rotations.data(), vertex_count * 4),
                vertex_count, 4, &result, "_bone_adjustment_rotations_owner",
                "hotools_native.mc2.bone_adjustment_rotations.v0"
            );
            result["vertex_to_transform_rotations"] = owned_array_2d(
                float_vector(vertex_to_transform_rotations.data(), vertex_count * 4),
                vertex_count, 4, &result, "_bone_transform_rotations_owner",
                "hotools_native.mc2.bone_transform_rotations.v0"
            );
            return result;
        });
    m.def("mc2_build_bone_transform_baseline_derived_v0",
        [](cf64_2d positions,
           cf64_2d local_normals,
           cf64_2d local_tangents,
           cu8_1d vertex_attributes,
           ci32_1d parent_indices,
           ci32_1d root_indices,
           i32_2d out_child_ranges,
           i32_1d out_child_data,
           u8_1d out_baseline_flags,
           i32_2d out_baseline_ranges,
           i32_1d out_baseline_data,
           u8_1d out_vertex_attributes,
           i32_1d out_roots,
           f64_1d out_depths,
           f64_2d out_local_positions,
           f64_2d out_local_rotations,
           bool produce_owned) {
            const auto vertex_count = vertex_attributes.shape(0);
            check_cols(positions, 3, "positions");
            check_cols(local_normals, 3, "local_normals");
            check_cols(local_tangents, 3, "local_tangents");
            check_len(positions.shape(0), vertex_count, "positions");
            check_len(local_normals.shape(0), vertex_count, "local_normals");
            check_len(local_tangents.shape(0), vertex_count, "local_tangents");
            check_len(parent_indices.shape(0), vertex_count, "parent_indices");
            check_cols(out_child_ranges, 2, "out_child_ranges");
            check_len(out_child_ranges.shape(0), vertex_count, "out_child_ranges");
            check_len(out_child_data.shape(0), vertex_count, "out_child_data");
            check_cols(out_baseline_ranges, 2, "out_baseline_ranges");
            check_len(out_baseline_ranges.shape(0), vertex_count, "out_baseline_ranges");
            check_len(out_baseline_flags.shape(0), vertex_count, "out_baseline_flags");
            check_len(out_baseline_data.shape(0), vertex_count, "out_baseline_data");
            check_len(out_vertex_attributes.shape(0), vertex_count, "out_vertex_attributes");
            check_len(out_roots.shape(0), vertex_count, "out_roots");
            check_len(out_depths.shape(0), vertex_count, "out_depths");
            check_cols(out_local_positions, 3, "out_local_positions");
            check_len(out_local_positions.shape(0), vertex_count, "out_local_positions");
            check_cols(out_local_rotations, 4, "out_local_rotations");
            check_len(out_local_rotations.shape(0), vertex_count, "out_local_rotations");
            hotools::Mc2BoneTransformBaselineDerived derived;
            try {
                nb::gil_scoped_release release;
                derived = hotools::mc2_build_bone_transform_baseline_derived(
                    positions.data(),
                    local_normals.data(),
                    local_tangents.data(),
                    vertex_attributes.data(),
                    parent_indices.data(),
                    vertex_count,
                    root_indices.data(),
                    root_indices.shape(0)
                );
            } catch (const std::invalid_argument& error) {
                throw nb::value_error(error.what());
            }
            const auto child_count = derived.child_data.size();
            const auto baseline_count = derived.baseline_flags.size();
            const auto baseline_data_count = derived.baseline_data.size();
            std::copy(derived.child_ranges.begin(), derived.child_ranges.end(), out_child_ranges.data());
            std::copy(derived.child_data.begin(), derived.child_data.end(), out_child_data.data());
            std::copy(derived.baseline_flags.begin(), derived.baseline_flags.end(), out_baseline_flags.data());
            std::copy(derived.baseline_ranges.begin(), derived.baseline_ranges.end(), out_baseline_ranges.data());
            std::copy(derived.baseline_data.begin(), derived.baseline_data.end(), out_baseline_data.data());
            std::copy(derived.vertex_attributes.begin(), derived.vertex_attributes.end(), out_vertex_attributes.data());
            std::copy(derived.root_indices.begin(), derived.root_indices.end(), out_roots.data());
            std::copy(derived.depths.begin(), derived.depths.end(), out_depths.data());
            std::copy(derived.vertex_local_positions.begin(), derived.vertex_local_positions.end(), out_local_positions.data());
            std::copy(derived.vertex_local_rotations.begin(), derived.vertex_local_rotations.end(), out_local_rotations.data());
            nb::dict result;
            result["child_count"] = child_count;
            result["baseline_count"] = baseline_count;
            result["baseline_data_count"] = baseline_data_count;
            if (produce_owned) {
                std::vector<std::int32_t> parents(
                    parent_indices.data(), parent_indices.data() + vertex_count
                );
                result["baseline_parents"] = owned_array_1d(
                    std::move(parents), &result, "_baseline_parents_owner",
                    "hotools_native.mc2.baseline_parents.v0"
                );
                result["baseline_child_ranges"] = owned_array_2d(
                    std::move(derived.child_ranges), vertex_count, 2,
                    &result, "_baseline_child_ranges_owner",
                    "hotools_native.mc2.baseline_child_ranges.v0"
                );
                result["baseline_child_data"] = owned_array_1d(
                    std::move(derived.child_data), &result, "_baseline_child_data_owner",
                    "hotools_native.mc2.baseline_child_data.v0"
                );
                result["baseline_flags"] = owned_array_1d(
                    std::move(derived.baseline_flags), &result, "_baseline_flags_owner",
                    "hotools_native.mc2.baseline_flags.v0"
                );
                result["baseline_ranges"] = owned_array_2d(
                    std::move(derived.baseline_ranges), baseline_count, 2,
                    &result, "_baseline_ranges_owner",
                    "hotools_native.mc2.baseline_ranges.v0"
                );
                result["baseline_data"] = owned_array_1d(
                    std::move(derived.baseline_data), &result, "_baseline_data_owner",
                    "hotools_native.mc2.baseline_data.v0"
                );
                result["baseline_roots"] = owned_array_1d(
                    std::move(derived.root_indices), &result, "_baseline_roots_owner",
                    "hotools_native.mc2.baseline_roots.v0"
                );
                result["baseline_depths"] = owned_array_1d(
                    float_vector(derived.depths.data(), vertex_count),
                    &result, "_baseline_depths_owner",
                    "hotools_native.mc2.baseline_depths.v0"
                );
                result["baseline_local_positions"] = owned_array_2d(
                    float_vector(derived.vertex_local_positions.data(), vertex_count * 3),
                    vertex_count, 3, &result, "_baseline_local_positions_owner",
                    "hotools_native.mc2.baseline_local_positions.v0"
                );
                result["baseline_local_rotations"] = owned_array_2d(
                    float_vector(derived.vertex_local_rotations.data(), vertex_count * 4),
                    vertex_count, 4, &result, "_baseline_local_rotations_owner",
                    "hotools_native.mc2.baseline_local_rotations.v0"
                );
            }
            return result;
        },
        nb::arg("positions"), nb::arg("local_normals"), nb::arg("local_tangents"),
        nb::arg("vertex_attributes"), nb::arg("parent_indices"), nb::arg("root_indices"),
        nb::arg("out_child_ranges"), nb::arg("out_child_data"),
        nb::arg("out_baseline_flags"), nb::arg("out_baseline_ranges"),
        nb::arg("out_baseline_data"), nb::arg("out_vertex_attributes"),
        nb::arg("out_roots"), nb::arg("out_depths"),
        nb::arg("out_local_positions"), nb::arg("out_local_rotations"),
        nb::arg("produce_owned") = false);
    m.def("mc2_build_mesh_final_proxy_derived_v1",
        [](cf64_2d positions,
           f64_2d local_normals,
           f64_2d local_tangents,
           cf64_2d uvs,
           u8_1d vertex_attributes,
           ci32_2d triangles,
           cf64_2d triangle_normals,
           cf64_2d triangle_uvs,
           ci32_2d lines,
           i32_2d out_edges,
           i32_2d out_neighbor_ranges,
           i32_1d out_neighbor_data,
           i32_2d out_triangle_ranges,
           i32_2d out_triangle_data,
           f64_2d out_bind_positions,
           f64_2d out_bind_rotations,
           std::int32_t owner_mode) {
            const auto vertex_count = positions.shape(0);
            const auto triangle_count = triangles.shape(0);
            check_cols(positions, 3, "positions");
            check_cols(local_normals, 3, "local_normals");
            check_cols(local_tangents, 3, "local_tangents");
            check_cols(uvs, 2, "uvs");
            check_len(local_normals.shape(0), vertex_count, "local_normals");
            check_len(local_tangents.shape(0), vertex_count, "local_tangents");
            check_len(uvs.shape(0), vertex_count, "uvs");
            check_len(vertex_attributes.shape(0), vertex_count, "vertex_attributes");
            check_cols(triangles, 3, "triangles");
            check_cols(triangle_normals, 3, "triangle_normals");
            check_len(triangle_normals.shape(0), triangle_count, "triangle_normals");
            check_cols(triangle_uvs, 6, "triangle_uvs");
            check_len(triangle_uvs.shape(0), triangle_count, "triangle_uvs");
            check_cols(lines, 2, "lines");
            check_indices_in_range(triangles.data(), triangle_count * 3, vertex_count, "triangles");
            check_indices_in_range(lines.data(), lines.shape(0) * 2, vertex_count, "lines");
            check_cols(out_edges, 2, "out_edges");
            check_cols(out_neighbor_ranges, 2, "out_neighbor_ranges");
            check_len(out_neighbor_ranges.shape(0), vertex_count, "out_neighbor_ranges");
            check_cols(out_triangle_ranges, 2, "out_triangle_ranges");
            check_len(out_triangle_ranges.shape(0), vertex_count, "out_triangle_ranges");
            check_cols(out_triangle_data, 2, "out_triangle_data");
            check_cols(out_bind_positions, 3, "out_bind_positions");
            check_len(out_bind_positions.shape(0), vertex_count, "out_bind_positions");
            check_cols(out_bind_rotations, 4, "out_bind_rotations");
            check_len(out_bind_rotations.shape(0), vertex_count, "out_bind_rotations");
            hotools::Mc2MeshFinalProxyDerived derived;
            try {
                nb::gil_scoped_release release;
                derived = hotools::mc2_build_mesh_final_proxy_derived(
                    positions.data(),
                    local_normals.data(),
                    local_tangents.data(),
                    uvs.data(),
                    triangle_uvs.data(),
                    vertex_attributes.data(),
                    vertex_count,
                    triangles.data(),
                    triangle_normals.data(),
                    triangle_count,
                    lines.data(),
                    lines.shape(0)
                );
            } catch (const std::exception& error) {
                throw nb::value_error(error.what());
            }
            const auto edge_count = derived.edges.size() / 2;
            const auto neighbor_count = derived.vertex_to_vertex_data.size();
            const auto triangle_record_count = derived.vertex_to_triangle_data.size() / 2;
            if (out_edges.shape(0) < edge_count ||
                out_neighbor_data.shape(0) < neighbor_count ||
                out_triangle_data.shape(0) < triangle_record_count) {
                throw nb::value_error("MC2 final proxy output buffer is too small");
            }
            std::copy(derived.local_normals.begin(), derived.local_normals.end(), local_normals.data());
            std::copy(derived.local_tangents.begin(), derived.local_tangents.end(), local_tangents.data());
            std::copy(derived.vertex_attributes.begin(), derived.vertex_attributes.end(), vertex_attributes.data());
            std::copy(derived.edges.begin(), derived.edges.end(), out_edges.data());
            std::copy(
                derived.vertex_to_vertex_ranges.begin(),
                derived.vertex_to_vertex_ranges.end(),
                out_neighbor_ranges.data()
            );
            std::copy(
                derived.vertex_to_vertex_data.begin(),
                derived.vertex_to_vertex_data.end(),
                out_neighbor_data.data()
            );
            std::copy(
                derived.vertex_to_triangle_ranges.begin(),
                derived.vertex_to_triangle_ranges.end(),
                out_triangle_ranges.data()
            );
            std::copy(
                derived.vertex_to_triangle_data.begin(),
                derived.vertex_to_triangle_data.end(),
                out_triangle_data.data()
            );
            std::copy(derived.bind_positions.begin(), derived.bind_positions.end(), out_bind_positions.data());
            std::copy(derived.bind_rotations.begin(), derived.bind_rotations.end(), out_bind_rotations.data());
            nb::dict result;
            result["edge_count"] = edge_count;
            result["neighbor_count"] = neighbor_count;
            result["triangle_record_count"] = triangle_record_count;
            if (owner_mode != 0) {
                result["proxy_local_positions"] = owned_array_2d(
                    float_vector(positions.data(), vertex_count * 3), vertex_count, 3,
                    &result, "_proxy_positions_owner",
                    "hotools_native.mc2.proxy_positions.v0"
                );
                result["proxy_local_normals"] = owned_array_2d(
                    float_vector(derived.local_normals.data(), vertex_count * 3), vertex_count, 3,
                    &result, "_proxy_normals_owner",
                    "hotools_native.mc2.proxy_normals.v0"
                );
                result["proxy_local_tangents"] = owned_array_2d(
                    float_vector(derived.local_tangents.data(), vertex_count * 3), vertex_count, 3,
                    &result, "_proxy_tangents_owner",
                    "hotools_native.mc2.proxy_tangents.v0"
                );
                result["proxy_uvs"] = owned_array_2d(
                    float_vector(uvs.data(), vertex_count * 2), vertex_count, 2,
                    &result, "_proxy_uvs_owner",
                    "hotools_native.mc2.proxy_uvs.v0"
                );
                result["proxy_attributes"] = owned_array_1d(
                    std::move(derived.vertex_attributes),
                    &result, "_proxy_attributes_owner",
                    "hotools_native.mc2.proxy_attributes.v0"
                );
                result["proxy_edges"] = owned_array_2d(
                    std::move(derived.edges), edge_count, 2,
                    &result, "_proxy_edges_owner",
                    "hotools_native.mc2.proxy_edges.v0"
                );
                result["proxy_triangles"] = owned_array_2d(
                    std::vector<std::int32_t>(
                        triangles.data(), triangles.data() + triangle_count * 3
                    ), triangle_count, 3,
                    &result, "_proxy_triangles_owner",
                    "hotools_native.mc2.proxy_triangles.v0"
                );
                if (owner_mode == 1) {
                    result["frame_triangle_uvs"] = owned_array_2d(
                        float_vector(derived.triangle_uvs.data(), triangle_count * 6),
                        triangle_count, 6,
                        &result, "_frame_triangle_uvs_owner",
                        "hotools_native.mc2.frame_triangle_uvs.v0"
                    );
                    result["frame_triangle_ranges"] = owned_array_2d(
                        std::move(derived.vertex_to_triangle_ranges), vertex_count, 2,
                        &result, "_frame_triangle_ranges_owner",
                        "hotools_native.mc2.frame_triangle_ranges.v0"
                    );
                    result["frame_triangle_records"] = owned_array_2d(
                        std::move(derived.vertex_to_triangle_data), triangle_record_count, 2,
                        &result, "_frame_triangle_records_owner",
                        "hotools_native.mc2.frame_triangle_records.v0"
                    );
                    result["frame_bind_rotations"] = owned_array_2d(
                        float_vector(derived.bind_rotations.data(), vertex_count * 4), vertex_count, 4,
                        &result, "_frame_bind_rotations_owner",
                        "hotools_native.mc2.frame_bind_rotations.v0"
                    );
                } else if (owner_mode == 2) {
                    result["bone_vertex_ranges"] = owned_array_2d(
                        std::move(derived.vertex_to_vertex_ranges), vertex_count, 2,
                        &result, "_bone_vertex_ranges_owner",
                        "hotools_native.mc2.bone_vertex_ranges.v0"
                    );
                    result["bone_vertex_data"] = owned_array_1d(
                        std::move(derived.vertex_to_vertex_data),
                        &result, "_bone_vertex_data_owner",
                        "hotools_native.mc2.bone_vertex_data.v0"
                    );
                    result["bone_triangle_ranges"] = owned_array_2d(
                        std::move(derived.vertex_to_triangle_ranges), vertex_count, 2,
                        &result, "_bone_triangle_ranges_owner",
                        "hotools_native.mc2.bone_triangle_ranges.v0"
                    );
                    result["bone_triangle_data"] = owned_array_2d(
                        std::move(derived.vertex_to_triangle_data), triangle_record_count, 2,
                        &result, "_bone_triangle_data_owner",
                        "hotools_native.mc2.bone_triangle_data.v0"
                    );
                    result["bone_bind_positions"] = owned_array_2d(
                        float_vector(derived.bind_positions.data(), vertex_count * 3), vertex_count, 3,
                        &result, "_bone_bind_positions_owner",
                        "hotools_native.mc2.bone_bind_positions.v0"
                    );
                    result["bone_bind_rotations"] = owned_array_2d(
                        float_vector(derived.bind_rotations.data(), vertex_count * 4), vertex_count, 4,
                        &result, "_bone_bind_rotations_owner",
                        "hotools_native.mc2.bone_bind_rotations.v0"
                    );
                } else {
                    throw nb::value_error("owner_mode must be 0, 1, or 2");
                }
            }
            return result;
        },
        nb::arg("positions"),
        nb::arg("local_normals"),
        nb::arg("local_tangents"),
        nb::arg("uvs"),
        nb::arg("vertex_attributes"),
        nb::arg("triangles"),
        nb::arg("triangle_normals"),
        nb::arg("triangle_uvs"),
        nb::arg("lines"),
        nb::arg("out_edges"),
        nb::arg("out_neighbor_ranges"),
        nb::arg("out_neighbor_data"),
        nb::arg("out_triangle_ranges"),
        nb::arg("out_triangle_data"),
        nb::arg("out_bind_positions"),
        nb::arg("out_bind_rotations"),
        nb::arg("owner_mode") = 0);
    m.def("mc2_build_mesh_baseline_derived_v0",
        [](cf64_2d positions,
           cf64_2d local_normals,
           cf64_2d local_tangents,
           u8_1d vertex_attributes,
           ci32_2d edges,
           i32_1d out_parents,
           i32_2d out_child_ranges,
           i32_1d out_child_data,
           u8_1d out_baseline_flags,
           i32_2d out_baseline_ranges,
           i32_1d out_baseline_data,
           i32_1d out_roots,
           f64_1d out_depths,
           f64_2d out_local_positions,
           f64_2d out_local_rotations,
           bool produce_owned) {
            const auto vertex_count = positions.shape(0);
            check_cols(positions, 3, "positions");
            check_cols(local_normals, 3, "local_normals");
            check_cols(local_tangents, 3, "local_tangents");
            check_len(local_normals.shape(0), vertex_count, "local_normals");
            check_len(local_tangents.shape(0), vertex_count, "local_tangents");
            check_len(vertex_attributes.shape(0), vertex_count, "vertex_attributes");
            check_cols(edges, 2, "edges");
            check_indices_in_range(edges.data(), edges.shape(0) * 2, vertex_count, "edges");
            check_len(out_parents.shape(0), vertex_count, "out_parents");
            check_cols(out_child_ranges, 2, "out_child_ranges");
            check_len(out_child_ranges.shape(0), vertex_count, "out_child_ranges");
            check_cols(out_baseline_ranges, 2, "out_baseline_ranges");
            check_len(out_baseline_ranges.shape(0), vertex_count, "out_baseline_ranges");
            check_len(out_roots.shape(0), vertex_count, "out_roots");
            check_len(out_depths.shape(0), vertex_count, "out_depths");
            check_cols(out_local_positions, 3, "out_local_positions");
            check_len(out_local_positions.shape(0), vertex_count, "out_local_positions");
            check_cols(out_local_rotations, 4, "out_local_rotations");
            check_len(out_local_rotations.shape(0), vertex_count, "out_local_rotations");
            hotools::Mc2MeshBaselineDerived derived;
            try {
                nb::gil_scoped_release release;
                derived = hotools::mc2_build_mesh_baseline_derived(
                    positions.data(),
                    local_normals.data(),
                    local_tangents.data(),
                    vertex_attributes.data(),
                    vertex_count,
                    edges.data(),
                    edges.shape(0)
                );
            } catch (const std::exception& error) {
                throw nb::value_error(error.what());
            }
            const auto child_count = derived.child_data.size();
            const auto baseline_count = derived.baseline_flags.size();
            const auto baseline_data_count = derived.baseline_data.size();
            if (out_child_data.shape(0) < child_count ||
                out_baseline_flags.shape(0) < baseline_count ||
                out_baseline_ranges.shape(0) < baseline_count ||
                out_baseline_data.shape(0) < baseline_data_count) {
                throw nb::value_error("MC2 baseline output buffer is too small");
            }
            std::copy(derived.vertex_attributes.begin(), derived.vertex_attributes.end(), vertex_attributes.data());
            std::copy(derived.parent_indices.begin(), derived.parent_indices.end(), out_parents.data());
            std::copy(derived.child_ranges.begin(), derived.child_ranges.end(), out_child_ranges.data());
            std::copy(derived.child_data.begin(), derived.child_data.end(), out_child_data.data());
            std::copy(derived.baseline_flags.begin(), derived.baseline_flags.end(), out_baseline_flags.data());
            std::copy(derived.baseline_ranges.begin(), derived.baseline_ranges.end(), out_baseline_ranges.data());
            std::copy(derived.baseline_data.begin(), derived.baseline_data.end(), out_baseline_data.data());
            std::copy(derived.root_indices.begin(), derived.root_indices.end(), out_roots.data());
            std::copy(derived.depths.begin(), derived.depths.end(), out_depths.data());
            std::copy(
                derived.vertex_local_positions.begin(),
                derived.vertex_local_positions.end(),
                out_local_positions.data()
            );
            std::copy(
                derived.vertex_local_rotations.begin(),
                derived.vertex_local_rotations.end(),
                out_local_rotations.data()
            );
            nb::dict result;
            result["child_count"] = child_count;
            result["baseline_count"] = baseline_count;
            result["baseline_data_count"] = baseline_data_count;
            if (produce_owned) {
                result["baseline_parents"] = owned_array_1d(
                    std::move(derived.parent_indices),
                    &result, "_baseline_parents_owner",
                    "hotools_native.mc2.baseline_parents.v0"
                );
                result["baseline_child_ranges"] = owned_array_2d(
                    std::move(derived.child_ranges), vertex_count, 2,
                    &result, "_baseline_child_ranges_owner",
                    "hotools_native.mc2.baseline_child_ranges.v0"
                );
                result["baseline_child_data"] = owned_array_1d(
                    std::move(derived.child_data),
                    &result, "_baseline_child_data_owner",
                    "hotools_native.mc2.baseline_child_data.v0"
                );
                result["baseline_flags"] = owned_array_1d(
                    std::move(derived.baseline_flags),
                    &result, "_baseline_flags_owner",
                    "hotools_native.mc2.baseline_flags.v0"
                );
                result["baseline_ranges"] = owned_array_2d(
                    std::move(derived.baseline_ranges), baseline_count, 2,
                    &result, "_baseline_ranges_owner",
                    "hotools_native.mc2.baseline_ranges.v0"
                );
                result["baseline_data"] = owned_array_1d(
                    std::move(derived.baseline_data),
                    &result, "_baseline_data_owner",
                    "hotools_native.mc2.baseline_data.v0"
                );
                result["baseline_roots"] = owned_array_1d(
                    std::move(derived.root_indices),
                    &result, "_baseline_roots_owner",
                    "hotools_native.mc2.baseline_roots.v0"
                );
                result["baseline_depths"] = owned_array_1d(
                    float_vector(derived.depths.data(), vertex_count),
                    &result, "_baseline_depths_owner",
                    "hotools_native.mc2.baseline_depths.v0"
                );
                result["baseline_local_positions"] = owned_array_2d(
                    float_vector(derived.vertex_local_positions.data(), vertex_count * 3),
                    vertex_count, 3,
                    &result, "_baseline_local_positions_owner",
                    "hotools_native.mc2.baseline_local_positions.v0"
                );
                result["baseline_local_rotations"] = owned_array_2d(
                    float_vector(derived.vertex_local_rotations.data(), vertex_count * 4),
                    vertex_count, 4,
                    &result, "_baseline_local_rotations_owner",
                    "hotools_native.mc2.baseline_local_rotations.v0"
                );
            }
            return result;
        },
        nb::arg("positions"),
        nb::arg("local_normals"),
        nb::arg("local_tangents"),
        nb::arg("vertex_attributes"),
        nb::arg("edges"),
        nb::arg("out_parents"),
        nb::arg("out_child_ranges"),
        nb::arg("out_child_data"),
        nb::arg("out_baseline_flags"),
        nb::arg("out_baseline_ranges"),
        nb::arg("out_baseline_data"),
        nb::arg("out_roots"),
        nb::arg("out_depths"),
        nb::arg("out_local_positions"),
        nb::arg("out_local_rotations"),
        nb::arg("produce_owned") = false);
    m.def("mc2_build_baseline_pose_depth_derived_v0",
        [](cf64_2d positions,
           cf64_2d local_normals,
           cf64_2d local_tangents,
           u8_1d vertex_attributes,
           ci32_1d parent_indices,
           ci32_1d baseline_data,
           i32_1d out_roots,
           f64_1d out_depths,
           f64_2d out_local_positions,
           f64_2d out_local_rotations) {
            const auto vertex_count = positions.shape(0);
            check_cols(positions, 3, "positions");
            check_cols(local_normals, 3, "local_normals");
            check_cols(local_tangents, 3, "local_tangents");
            check_len(local_normals.shape(0), vertex_count, "local_normals");
            check_len(local_tangents.shape(0), vertex_count, "local_tangents");
            check_len(vertex_attributes.shape(0), vertex_count, "vertex_attributes");
            check_len(parent_indices.shape(0), vertex_count, "parent_indices");
            check_root_or_minus_one(parent_indices.data(), vertex_count, vertex_count, "parent_indices");
            check_indices_in_range(
                baseline_data.data(), baseline_data.shape(0), vertex_count, "baseline_data"
            );
            check_len(out_roots.shape(0), vertex_count, "out_roots");
            check_len(out_depths.shape(0), vertex_count, "out_depths");
            check_cols(out_local_positions, 3, "out_local_positions");
            check_len(out_local_positions.shape(0), vertex_count, "out_local_positions");
            check_cols(out_local_rotations, 4, "out_local_rotations");
            check_len(out_local_rotations.shape(0), vertex_count, "out_local_rotations");
            hotools::Mc2BaselinePoseDepthDerived derived;
            try {
                nb::gil_scoped_release release;
                derived = hotools::mc2_build_baseline_pose_depth_derived(
                    positions.data(),
                    local_normals.data(),
                    local_tangents.data(),
                    vertex_attributes.data(),
                    parent_indices.data(),
                    vertex_count,
                    baseline_data.data(),
                    baseline_data.shape(0)
                );
            } catch (const std::exception& error) {
                throw nb::value_error(error.what());
            }
            std::copy(derived.vertex_attributes.begin(), derived.vertex_attributes.end(), vertex_attributes.data());
            std::copy(derived.root_indices.begin(), derived.root_indices.end(), out_roots.data());
            std::copy(derived.depths.begin(), derived.depths.end(), out_depths.data());
            std::copy(
                derived.vertex_local_positions.begin(),
                derived.vertex_local_positions.end(),
                out_local_positions.data()
            );
            std::copy(
                derived.vertex_local_rotations.begin(),
                derived.vertex_local_rotations.end(),
                out_local_rotations.data()
            );
        });
    // ---- MC2 单步约束求解器（ndarray 直传，GIL 在纯 C++ 计算段释放）----
    m.def("mc2_build_distance_derived_v0",
        [](cf64_2d positions,
           cu8_1d vertex_attributes,
           ci32_1d parent_indices,
           ci32_2d edges,
           ci32_2d triangles,
           ci32_2d adjacency_ranges,
           ci32_1d adjacency_data) {
            const auto vertex_count = positions.shape(0);
            check_cols(positions, 3, "positions");
            check_len(vertex_attributes.shape(0), vertex_count, "vertex_attributes");
            check_len(parent_indices.shape(0), vertex_count, "parent_indices");
            check_root_or_minus_one(parent_indices.data(), vertex_count, vertex_count, "parent_indices");
            check_cols(edges, 2, "edges");
            check_indices_in_range(edges.data(), edges.shape(0) * 2, vertex_count, "edges");
            check_cols(triangles, 3, "triangles");
            check_indices_in_range(
                triangles.data(), triangles.shape(0) * 3, vertex_count, "triangles"
            );
            check_cols(adjacency_ranges, 2, "adjacency_ranges");
            check_len(adjacency_ranges.shape(0), vertex_count, "adjacency_ranges");
            check_indices_in_range(
                adjacency_data.data(), adjacency_data.shape(0), vertex_count, "adjacency_data"
            );
            hotools::Mc2DistanceDerived derived;
            try {
                nb::gil_scoped_release release;
                derived = hotools::mc2_build_distance_derived(
                    positions.data(),
                    vertex_attributes.data(),
                    parent_indices.data(),
                    vertex_count,
                    edges.data(),
                    edges.shape(0),
                    triangles.data(),
                    triangles.shape(0),
                    adjacency_ranges.data(),
                    adjacency_data.data(),
                    adjacency_data.shape(0)
                );
            } catch (const std::exception& error) {
                throw nb::value_error(error.what());
            }
            nb::dict result;
            result["distance_ranges"] = owned_array_2d(
                std::move(derived.ranges), vertex_count, 2,
                &result, "_distance_ranges_owner",
                "hotools_native.mc2.distance_ranges.v0"
            );
            result["distance_targets"] = owned_array_1d(
                std::move(derived.targets), &result, "_distance_targets_owner",
                "hotools_native.mc2.distance_targets.v0"
            );
            result["distance_rest_signed"] = owned_array_1d(
                std::move(derived.rest_signed), &result, "_distance_rests_owner",
                "hotools_native.mc2.distance_rests.v0"
            );
            return result;
        });
    m.def("mc2_build_bending_derived_v0",
        [](cf32_2d positions,
           cu8_1d vertex_attributes,
           ci32_2d edges,
           ci32_2d triangles,
           cf32_2d initial_local_to_world_columns) {
            const auto vertex_count = positions.shape(0);
            check_cols(positions, 3, "positions");
            check_len(vertex_attributes.shape(0), vertex_count, "vertex_attributes");
            check_cols(edges, 2, "edges");
            check_indices_in_range(edges.data(), edges.shape(0) * 2, vertex_count, "edges");
            check_cols(triangles, 3, "triangles");
            check_indices_in_range(
                triangles.data(), triangles.shape(0) * 3, vertex_count, "triangles"
            );
            check_len(initial_local_to_world_columns.shape(0), 4, "initial_local_to_world_columns");
            check_cols(initial_local_to_world_columns, 4, "initial_local_to_world_columns");
            hotools::Mc2BendingDerived derived;
            try {
                nb::gil_scoped_release release;
                derived = hotools::mc2_build_bending_derived(
                    positions.data(),
                    vertex_attributes.data(),
                    vertex_count,
                    edges.data(),
                    edges.shape(0),
                    triangles.data(),
                    triangles.shape(0),
                    initial_local_to_world_columns.data()
                );
            } catch (const std::exception& error) {
                throw nb::value_error(error.what());
            }
            const auto record_count = derived.rest_angle_or_volume.size();
            nb::dict result;
            result["bending_quads"] = owned_array_2d(
                std::move(derived.quads), record_count, 4,
                &result, "_bending_quads_owner",
                "hotools_native.mc2.bending_quads.v0"
            );
            result["bending_rest_angle_or_volume"] = owned_array_1d(
                std::move(derived.rest_angle_or_volume),
                &result, "_bending_rests_owner",
                "hotools_native.mc2.bending_rests.v0"
            );
            result["bending_sign_or_volume"] = owned_array_1d(
                std::move(derived.sign_or_volume),
                &result, "_bending_markers_owner",
                "hotools_native.mc2.bending_markers.v0"
            );
            return result;
        });
    m.def("mc2_build_self_collision_derived_v0",
        [](cu8_1d vertex_attributes,
           cf64_1d vertex_depths,
           ci32_2d edges,
           ci32_2d triangles) {
            const auto vertex_count = vertex_attributes.shape(0);
            check_len(vertex_depths.shape(0), vertex_count, "vertex_depths");
            check_cols(edges, 2, "edges");
            check_indices_in_range(edges.data(), edges.shape(0) * 2, vertex_count, "edges");
            check_cols(triangles, 3, "triangles");
            check_indices_in_range(
                triangles.data(), triangles.shape(0) * 3, vertex_count, "triangles"
            );
            hotools::Mc2SelfCollisionDerived derived;
            try {
                nb::gil_scoped_release release;
                derived = hotools::mc2_build_self_collision_derived(
                    vertex_attributes.data(),
                    vertex_depths.data(),
                    vertex_count,
                    edges.data(),
                    edges.shape(0),
                    triangles.data(),
                    triangles.shape(0)
                );
            } catch (const std::exception& error) {
                throw nb::value_error(error.what());
            }
            const auto primitive_count = derived.primitive_flags.size();
            nb::dict result;
            result["primitive_flags"] = owned_array_1d(
                std::move(derived.primitive_flags),
                &result, "_self_flags_owner",
                "hotools_native.mc2.self_flags.v0"
            );
            result["particle_indices"] = owned_array_2d(
                std::move(derived.particle_indices), primitive_count, 3,
                &result, "_self_indices_owner",
                "hotools_native.mc2.self_indices.v0"
            );
            result["primitive_depths"] = owned_array_1d(
                std::move(derived.primitive_depths),
                &result, "_self_depths_owner",
                "hotools_native.mc2.self_depths.v0"
            );
            result["point_count"] = derived.point_count;
            result["edge_count"] = derived.edge_count;
            result["triangle_count"] = derived.triangle_count;
            return result;
        });
    m.def("mc2_build_center_static_derived_v0",
        [](cf64_2d positions,
           cf64_2d local_normals,
           cf64_2d local_tangents,
           cu8_1d vertex_attributes,
           cf64_2d bind_rotations,
           ci32_2d edges,
           cf64_1d world_gravity_direction) {
            const auto vertex_count = positions.shape(0);
            check_cols(positions, 3, "positions");
            check_cols(local_normals, 3, "local_normals");
            check_len(local_normals.shape(0), vertex_count, "local_normals");
            check_cols(local_tangents, 3, "local_tangents");
            check_len(local_tangents.shape(0), vertex_count, "local_tangents");
            check_len(vertex_attributes.shape(0), vertex_count, "vertex_attributes");
            check_cols(bind_rotations, 4, "bind_rotations");
            check_len(bind_rotations.shape(0), vertex_count, "bind_rotations");
            check_cols(edges, 2, "edges");
            check_indices_in_range(edges.data(), edges.shape(0) * 2, vertex_count, "edges");
            check_len(world_gravity_direction.shape(0), 3, "world_gravity_direction");
            hotools::Mc2CenterStaticDerived derived;
            try {
                nb::gil_scoped_release release;
                derived = hotools::mc2_build_center_static_derived(
                    positions.data(),
                    local_normals.data(),
                    local_tangents.data(),
                    vertex_attributes.data(),
                    bind_rotations.data(),
                    vertex_count,
                    edges.data(),
                    edges.shape(0),
                    world_gravity_direction.data()
                );
            } catch (const std::exception& error) {
                throw nb::value_error(error.what());
            }
            nb::dict result;
            result["fixed_indices"] = owned_array_1d(
                std::move(derived.fixed_indices),
                &result, "_center_fixed_owner",
                "hotools_native.mc2.center_fixed.v0"
            );
            result["local_center_position"] = owned_array_1d(
                std::move(derived.local_center_position),
                &result, "_center_position_owner",
                "hotools_native.mc2.center_position.v0"
            );
            result["initial_local_gravity_direction"] = owned_array_1d(
                std::move(derived.initial_local_gravity_direction),
                &result, "_center_gravity_owner",
                "hotools_native.mc2.center_gravity.v0"
            );
            return result;
        });
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
            view.explicit_enable_flags = false;
            view.max_distance_enabled = false;
            view.backstop_enabled = false;
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
            view.velocity_weight       = 1.0f;
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
            view.velocity_positions  = nullptr;
            view.inv_masses          = inv.data();
            view.collision_radii     = cr.data();
            view.max_lengths         = nullptr;
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
            view.soft_sphere         = false;
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
            view.move_attribute_mask = 1u << 2u;
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
            view.explicit_enable_flags            = false;
            view.restoration_enabled              = false;
            view.limit_enabled                    = false;
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
}
