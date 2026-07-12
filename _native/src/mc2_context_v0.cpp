#include "mc2_context_v0.hpp"

#include "python_buffer_utils.hpp"

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

std::atomic<std::int64_t> g_created {0};
std::atomic<std::int64_t> g_released {0};
std::atomic<std::int64_t> g_live {0};

struct Mc2ContextV0 {
    std::int64_t vertex_count = 0;
    std::int64_t parameter_revision = 0;
    std::int64_t proxy_static_revision = 0;
    std::int64_t baseline_static_revision = 0;
    std::int64_t dynamic_revision = 0;
    std::int64_t reset_count = 0;
    std::int64_t step_count = 0;
    std::int64_t frame = 0;
    std::int64_t generation = 0;
    bool parameters_ready = false;
    bool proxy_static_ready = false;
    bool baseline_static_ready = false;
    bool dynamic_ready = false;
    bool initialized = false;
    bool released = false;
    std::vector<float> float_values;
    std::vector<std::int32_t> int_values;
    std::vector<float> curve_values;
    std::vector<float> dynamic_positions;
    std::vector<float> dynamic_rotations;
    std::vector<float> state_positions;
    std::vector<float> state_rotations;
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
    context.state_positions.clear();
    context.state_rotations.clear();
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
    context.parameters_ready = false;
    context.proxy_static_ready = false;
    context.baseline_static_ready = false;
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

bool validate_quaternions(const Buffer& rotations) {
    const auto* values = static_cast<const float*>(rotations.view.buf);
    for (Py_ssize_t row = 0; row < rotations.view.shape[0]; ++row) {
        const float* value = values + row * 4;
        const double length_squared =
            static_cast<double>(value[0]) * value[0] +
            static_cast<double>(value[1]) * value[1] +
            static_cast<double>(value[2]) * value[2] +
            static_cast<double>(value[3]) * value[3];
        if (!std::isfinite(length_squared) || std::abs(length_squared - 1.0) > 2.0e-5) {
            PyErr_SetString(PyExc_ValueError, "world_rotations_xyzw must contain unit quaternions");
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
        !dict_i64(result, "edge_count", static_cast<std::int64_t>(context.proxy_edges.size() / 2)) ||
        !dict_i64(result, "triangle_count", static_cast<std::int64_t>(context.proxy_triangles.size() / 3)) ||
        !dict_i64(result, "baseline_count", static_cast<std::int64_t>(context.baseline_ranges.size() / 2)) ||
        !dict_i64(result, "fixed_count", fixed_count) ||
        !dict_i64(result, "parameter_revision", context.parameter_revision) ||
        !dict_i64(result, "dynamic_revision", context.dynamic_revision) ||
        !dict_i64(result, "reset_count", context.reset_count) ||
        !dict_i64(result, "step_count", context.step_count) ||
        !dict_i64(result, "frame", context.frame) ||
        !dict_i64(result, "generation", context.generation) ||
        !dict_bool(result, "parameters_ready", context.parameters_ready) ||
        !dict_bool(result, "proxy_static_ready", context.proxy_static_ready) ||
        !dict_bool(result, "baseline_static_ready", context.baseline_static_ready) ||
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
    if (PyTuple_GET_SIZE(args) != 5) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_dynamic expects 5 arguments");
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
    if (PyErr_Occurred()) return nullptr;
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
        !validate_quaternions(rotations)) {
        return nullptr;
    }
    auto next_positions = copy_values<float>(positions);
    auto next_rotations = copy_values<float>(rotations);
    context->dynamic_positions.swap(next_positions);
    context->dynamic_rotations.swap(next_rotations);
    context->frame = frame;
    context->generation = generation;
    context->dynamic_ready = true;
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
    context->initialized = true;
    ++context->reset_count;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_step(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_step expects 2 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const double dt = as_double(PyTuple_GET_ITEM(args, 1), "dt");
    if (PyErr_Occurred()) return nullptr;
    if (!std::isfinite(dt) || dt < 0.0) {
        PyErr_SetString(PyExc_ValueError, "dt must be finite and non-negative");
        return nullptr;
    }
    if (!context->parameters_ready || !context->dynamic_ready || !context->initialized) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 context is not ready to step");
        return nullptr;
    }
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
