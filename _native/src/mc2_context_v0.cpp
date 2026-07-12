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
    std::int64_t dynamic_revision = 0;
    std::int64_t reset_count = 0;
    std::int64_t step_count = 0;
    std::int64_t frame = 0;
    std::int64_t generation = 0;
    bool parameters_ready = false;
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
    context.parameters_ready = false;
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

PyObject* inspect_context(const Mc2ContextV0& context) {
    PyObject* result = PyDict_New();
    if (result == nullptr) return nullptr;
    if (!dict_string(result, "schema", "mc2_context_v0") ||
        !dict_i64(result, "schema_version", kSchemaVersion) ||
        !dict_i64(result, "vertex_count", context.vertex_count) ||
        !dict_i64(result, "parameter_revision", context.parameter_revision) ||
        !dict_i64(result, "dynamic_revision", context.dynamic_revision) ||
        !dict_i64(result, "reset_count", context.reset_count) ||
        !dict_i64(result, "step_count", context.step_count) ||
        !dict_i64(result, "frame", context.frame) ||
        !dict_i64(result, "generation", context.generation) ||
        !dict_bool(result, "parameters_ready", context.parameters_ready) ||
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
