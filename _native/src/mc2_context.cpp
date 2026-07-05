#include "mc2_context.hpp"

#include "hotools_mc2.hpp"
#include "python_buffer_utils.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace hotools {
namespace {

using py::Buffer;
using py::as_double;
using py::as_long;
using py::expect_1d_array;
using py::expect_float32;
using py::expect_indices_in_range;
using py::expect_int32_pair_array;
using py::expect_int32_quad_array;
using py::expect_int32_scalar_array;
using py::expect_int32_triple_array;
using py::expect_pair_indices_in_range;
using py::expect_quad_indices_in_range;
using py::expect_root_indices_or_minus_one;
using py::expect_same_quat_vertex_count;
using py::expect_same_vertex_count;
using py::expect_triple_indices_in_range;
using py::expect_uint8_scalar_array;
using py::expect_vector3_array;
using py::expect_vector4_array;

constexpr const char* kMc2ContextCapsuleName = "hotools_native.MC2Context";

struct Mc2NativeContext {
    std::int64_t vertex_count = 0;
    std::int64_t line_count = 0;
    std::int64_t baseline_data_count = 0;
    std::int64_t distance_count = 0;
    std::int64_t bend_count = 0;
    std::int64_t collider_radius_count = 0;
    std::int64_t edge_count = 0;
    std::int64_t triangle_count = 0;
    std::int64_t dihedral_count = 0;
    std::int64_t volume_count = 0;
    std::int64_t param_slot_count = 0;
    std::int64_t param_array_count = 0;
    std::int64_t topology_serial = 0;
    std::int64_t param_serial = 0;
    bool static_ready = false;
    bool param_arrays_ready = false;
    bool released = false;

    std::vector<std::uint8_t> attributes;
    std::vector<float> depths;
    std::vector<std::int32_t> root_indices;
    std::vector<float> tether_rest_lengths;
    std::vector<std::int32_t> parent_indices;
    std::vector<std::int32_t> baseline_start;
    std::vector<std::int32_t> baseline_count;
    std::vector<std::int32_t> baseline_data;
    std::vector<float> vertex_local_positions;
    std::vector<float> vertex_local_rotations;
    std::vector<std::int32_t> distance_start;
    std::vector<std::int32_t> distance_count_values;
    std::vector<std::int32_t> distance_data;
    std::vector<float> distance_rest;
    std::vector<std::int32_t> bend_distance_start;
    std::vector<std::int32_t> bend_distance_count;
    std::vector<std::int32_t> bend_distance_data;
    std::vector<float> bend_distance_rest;
    std::vector<std::int32_t> dihedral_pairs;
    std::vector<float> dihedral_rest_angles;
    std::vector<std::int32_t> dihedral_signs;
    std::vector<std::int32_t> volume_pairs;
    std::vector<float> volume_rest;
    std::vector<std::int32_t> edges;
    std::vector<std::int32_t> triangles;
    std::vector<float> distance_stiffness_values;
    std::vector<float> bend_stiffness_values;
    std::vector<float> angle_restoration_values;
    std::vector<float> angle_restoration_velocity_attenuation_values;
    std::vector<float> angle_restoration_gravity_falloff_values;
    std::vector<float> angle_limit_values;
    std::vector<float> substep_damping_values;
    std::vector<float> max_distances;
    std::vector<float> motion_stiffness_values;
    std::vector<float> backstop_radii;
    std::vector<float> backstop_distances;
};

Mc2NativeContext* get_mc2_context(PyObject* capsule) {
    return static_cast<Mc2NativeContext*>(PyCapsule_GetPointer(capsule, kMc2ContextCapsuleName));
}

void destroy_mc2_context(PyObject* capsule) {
    auto* context = static_cast<Mc2NativeContext*>(PyCapsule_GetPointer(capsule, kMc2ContextCapsuleName));
    if (context == nullptr) {
        PyErr_Clear();
        return;
    }
    delete context;
}

bool ensure_context_live(const Mc2NativeContext* context) {
    if (context == nullptr) {
        return false;
    }
    if (context->released) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 context has been released");
        return false;
    }
    return true;
}

bool dict_set_i64(PyObject* dict, const char* key, std::int64_t value) {
    PyObject* object = PyLong_FromLongLong(value);
    if (object == nullptr) {
        return false;
    }
    const int result = PyDict_SetItemString(dict, key, object);
    Py_DECREF(object);
    return result == 0;
}

bool dict_set_bool(PyObject* dict, const char* key, bool value) {
    PyObject* object = PyBool_FromLong(value ? 1 : 0);
    if (object == nullptr) {
        return false;
    }
    const int result = PyDict_SetItemString(dict, key, object);
    Py_DECREF(object);
    return result == 0;
}

const float* data_or_dummy(const std::vector<float>& values) {
    static const float dummy = 0.0f;
    return values.empty() ? &dummy : values.data();
}

const std::int32_t* data_or_dummy(const std::vector<std::int32_t>& values) {
    static const std::int32_t dummy = 0;
    return values.empty() ? &dummy : values.data();
}

const std::uint8_t* data_or_dummy(const std::vector<std::uint8_t>& values) {
    static const std::uint8_t dummy = 0;
    return values.empty() ? &dummy : values.data();
}

template <typename T>
void copy_buffer_values(const Buffer& buffer, std::vector<T>& target) {
    const auto count = static_cast<std::size_t>(buffer.view.len / static_cast<Py_ssize_t>(sizeof(T)));
    const auto* begin = static_cast<const T*>(buffer.view.buf);
    target.assign(begin, begin + count);
}

void clear_param_storage(Mc2NativeContext& context) {
    context.param_arrays_ready = false;
    context.param_array_count = 0;
    context.distance_stiffness_values.clear();
    context.bend_stiffness_values.clear();
    context.angle_restoration_values.clear();
    context.angle_restoration_velocity_attenuation_values.clear();
    context.angle_restoration_gravity_falloff_values.clear();
    context.angle_limit_values.clear();
    context.substep_damping_values.clear();
    context.max_distances.clear();
    context.motion_stiffness_values.clear();
    context.backstop_radii.clear();
    context.backstop_distances.clear();
}

void clear_static_storage(Mc2NativeContext& context) {
    context.static_ready = false;
    context.line_count = 0;
    context.baseline_data_count = 0;
    context.distance_count = 0;
    context.bend_count = 0;
    context.edge_count = 0;
    context.triangle_count = 0;
    context.dihedral_count = 0;
    context.volume_count = 0;
    context.attributes.clear();
    context.depths.clear();
    context.root_indices.clear();
    context.tether_rest_lengths.clear();
    context.parent_indices.clear();
    context.baseline_start.clear();
    context.baseline_count.clear();
    context.baseline_data.clear();
    context.vertex_local_positions.clear();
    context.vertex_local_rotations.clear();
    context.distance_start.clear();
    context.distance_count_values.clear();
    context.distance_data.clear();
    context.distance_rest.clear();
    context.bend_distance_start.clear();
    context.bend_distance_count.clear();
    context.bend_distance_data.clear();
    context.bend_distance_rest.clear();
    context.dihedral_pairs.clear();
    context.dihedral_rest_angles.clear();
    context.dihedral_signs.clear();
    context.volume_pairs.clear();
    context.volume_rest.clear();
    context.edges.clear();
    context.triangles.clear();
    clear_param_storage(context);
}

PyObject* mc2_context_to_dict(const Mc2NativeContext& context) {
    PyObject* result = PyDict_New();
    if (result == nullptr) {
        return nullptr;
    }
    if (!dict_set_i64(result, "vertex_count", context.vertex_count) ||
        !dict_set_i64(result, "line_count", context.line_count) ||
        !dict_set_i64(result, "baseline_data_count", context.baseline_data_count) ||
        !dict_set_i64(result, "distance_count", context.distance_count) ||
        !dict_set_i64(result, "bend_count", context.bend_count) ||
        !dict_set_i64(result, "collider_radius_count", context.collider_radius_count) ||
        !dict_set_i64(result, "edge_count", context.edge_count) ||
        !dict_set_i64(result, "triangle_count", context.triangle_count) ||
        !dict_set_i64(result, "dihedral_count", context.dihedral_count) ||
        !dict_set_i64(result, "volume_count", context.volume_count) ||
        !dict_set_i64(result, "param_slot_count", context.param_slot_count) ||
        !dict_set_i64(result, "param_array_count", context.param_array_count) ||
        !dict_set_i64(result, "topology_serial", context.topology_serial) ||
        !dict_set_i64(result, "param_serial", context.param_serial) ||
        !dict_set_bool(result, "static_ready", context.static_ready) ||
        !dict_set_bool(result, "param_arrays_ready", context.param_arrays_ready) ||
        !dict_set_bool(result, "released", context.released)) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}

bool expect_param_array_size(const std::vector<float>& values, Py_ssize_t vertex_count, const char* name) {
    if (static_cast<Py_ssize_t>(values.size()) != vertex_count) {
        PyErr_Format(PyExc_ValueError, "%s length mismatch", name);
        return false;
    }
    return true;
}

bool ensure_context_param_arrays_ready(const Mc2NativeContext& context, Py_ssize_t vertex_count) {
    if (!context.param_arrays_ready) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 context parameter arrays have not been uploaded");
        return false;
    }
    return expect_param_array_size(context.distance_stiffness_values, vertex_count, "distance_stiffness_values") &&
           expect_param_array_size(context.bend_stiffness_values, vertex_count, "bend_stiffness_values") &&
           expect_param_array_size(context.angle_restoration_values, vertex_count, "angle_restoration_values") &&
           expect_param_array_size(context.angle_restoration_velocity_attenuation_values,
                                   vertex_count,
                                   "angle_restoration_velocity_attenuation_values") &&
           expect_param_array_size(context.angle_restoration_gravity_falloff_values,
                                   vertex_count,
                                   "angle_restoration_gravity_falloff_values") &&
           expect_param_array_size(context.angle_limit_values, vertex_count, "angle_limit_values") &&
           expect_param_array_size(context.substep_damping_values, vertex_count, "substep_damping_values") &&
           expect_param_array_size(context.max_distances, vertex_count, "max_distances") &&
           expect_param_array_size(context.motion_stiffness_values, vertex_count, "motion_stiffness_values") &&
           expect_param_array_size(context.backstop_radii, vertex_count, "backstop_radii") &&
           expect_param_array_size(context.backstop_distances, vertex_count, "backstop_distances");
}

}  // namespace

PyObject* create_meshcloth_mc2_context_object(long vertex_count,
                                              long distance_count,
                                              long bend_count,
                                              long collider_radius_count) {
    auto* context = new Mc2NativeContext();
    context->vertex_count = vertex_count;
    context->distance_count = distance_count;
    context->bend_count = bend_count;
    context->collider_radius_count = collider_radius_count;
    context->topology_serial = 1;
    PyObject* capsule = PyCapsule_New(context, kMc2ContextCapsuleName, destroy_mc2_context);
    if (capsule == nullptr) {
        delete context;
        return nullptr;
    }
    return capsule;
}

PyObject* update_meshcloth_mc2_context_static_object(PyObject* context_object,
                                                     long vertex_count,
                                                     long distance_count,
                                                     long bend_count,
                                                     long collider_radius_count) {
    auto* context = get_mc2_context(context_object);
    if (!ensure_context_live(context)) {
        return nullptr;
    }
    clear_static_storage(*context);
    context->vertex_count = vertex_count;
    context->distance_count = distance_count;
    context->bend_count = bend_count;
    context->collider_radius_count = collider_radius_count;
    context->topology_serial += 1;
    Py_RETURN_NONE;
}

PyObject* update_meshcloth_mc2_context_static_arrays(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArrayCount = 25;
    constexpr Py_ssize_t kArgCount = kArrayCount + 1;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "update_meshcloth_mc2_context_static_arrays expects %zd arguments", kArgCount);
        return nullptr;
    }
    auto* context = get_mc2_context(PyTuple_GET_ITEM(args, 0));
    if (!ensure_context_live(context)) {
        return nullptr;
    }

    enum StaticArg {
        AAttributes = 0,
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
        ABendDistanceStart,
        ABendDistanceCount,
        ABendDistanceData,
        ABendDistanceRest,
        ADihedralPairs,
        ADihedralRestAngles,
        ADihedralSigns,
        AVolumePairs,
        AVolumeRest,
        AEdges,
        ATriangles,
    };
    const char* names[kArrayCount] = {
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
        "bend_distance_start",
        "bend_distance_count",
        "bend_distance_data",
        "bend_distance_rest",
        "dihedral_pairs",
        "dihedral_rest_angles",
        "dihedral_signs",
        "volume_pairs",
        "volume_rest",
        "edges",
        "triangles",
    };

    Buffer buffers[kArrayCount];
    for (int index = 0; index < kArrayCount; ++index) {
        if (!buffers[index].get(PyTuple_GET_ITEM(args, index + 1), PyBUF_FORMAT | PyBUF_ND, names[index])) {
            return nullptr;
        }
    }

    const Py_ssize_t vertex_count = static_cast<Py_ssize_t>(context->vertex_count);
    if (vertex_count <= 0) {
        PyErr_SetString(PyExc_ValueError, "MC2 context vertex_count must be positive before static array upload");
        return nullptr;
    }
    if (!expect_uint8_scalar_array(buffers[AAttributes], "attributes") ||
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
        !expect_root_indices_or_minus_one(buffers[AParentIndices], "parent_indices", vertex_count) ||
        !expect_same_vertex_count(buffers[AVertexLocalPositions], "vertex_local_positions", vertex_count) ||
        !expect_same_quat_vertex_count(buffers[AVertexLocalRotations], "vertex_local_rotations", vertex_count)) {
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
        !expect_1d_array(buffers[ADistanceRest], "distance_rest", buffers[ADistanceData].view.shape[0])) {
        return nullptr;
    }

    if (!expect_int32_scalar_array(buffers[ABendDistanceStart], "bend_distance_start") ||
        !expect_1d_array(buffers[ABendDistanceStart], "bend_distance_start", vertex_count) ||
        !expect_int32_scalar_array(buffers[ABendDistanceCount], "bend_distance_count") ||
        !expect_1d_array(buffers[ABendDistanceCount], "bend_distance_count", vertex_count) ||
        !expect_int32_scalar_array(buffers[ABendDistanceData], "bend_distance_data") ||
        !expect_indices_in_range(buffers[ABendDistanceData], "bend_distance_data", vertex_count) ||
        !expect_float32(buffers[ABendDistanceRest], "bend_distance_rest") ||
        !expect_1d_array(buffers[ABendDistanceRest], "bend_distance_rest", buffers[ABendDistanceData].view.shape[0])) {
        return nullptr;
    }

    Py_ssize_t dihedral_count = 0;
    Py_ssize_t volume_count = 0;
    Py_ssize_t edge_count = 0;
    Py_ssize_t triangle_count = 0;
    if (!expect_int32_quad_array(buffers[ADihedralPairs], "dihedral_pairs", &dihedral_count) ||
        !expect_float32(buffers[ADihedralRestAngles], "dihedral_rest_angles") ||
        !expect_1d_array(buffers[ADihedralRestAngles], "dihedral_rest_angles", dihedral_count) ||
        !expect_int32_scalar_array(buffers[ADihedralSigns], "dihedral_signs") ||
        !expect_1d_array(buffers[ADihedralSigns], "dihedral_signs", dihedral_count) ||
        !expect_int32_quad_array(buffers[AVolumePairs], "volume_pairs", &volume_count) ||
        !expect_float32(buffers[AVolumeRest], "volume_rest") ||
        !expect_1d_array(buffers[AVolumeRest], "volume_rest", volume_count) ||
        !expect_int32_pair_array(buffers[AEdges], "edges", &edge_count) ||
        !expect_int32_triple_array(buffers[ATriangles], "triangles", &triangle_count)) {
        return nullptr;
    }
    if ((dihedral_count > 0 && !expect_quad_indices_in_range(buffers[ADihedralPairs], "dihedral_pairs", vertex_count)) ||
        (volume_count > 0 && !expect_quad_indices_in_range(buffers[AVolumePairs], "volume_pairs", vertex_count)) ||
        (edge_count > 0 && !expect_pair_indices_in_range(buffers[AEdges], "edges", vertex_count)) ||
        (triangle_count > 0 && !expect_triple_indices_in_range(buffers[ATriangles], "triangles", vertex_count))) {
        return nullptr;
    }

    clear_static_storage(*context);
    context->vertex_count = static_cast<std::int64_t>(vertex_count);
    context->line_count = static_cast<std::int64_t>(line_count);
    context->baseline_data_count = static_cast<std::int64_t>(buffers[ABaselineData].view.shape[0]);
    context->distance_count = static_cast<std::int64_t>(buffers[ADistanceData].view.shape[0]);
    context->bend_count = static_cast<std::int64_t>(buffers[ABendDistanceData].view.shape[0]);
    context->edge_count = static_cast<std::int64_t>(edge_count);
    context->triangle_count = static_cast<std::int64_t>(triangle_count);
    context->dihedral_count = static_cast<std::int64_t>(dihedral_count);
    context->volume_count = static_cast<std::int64_t>(volume_count);

    copy_buffer_values(buffers[AAttributes], context->attributes);
    copy_buffer_values(buffers[ADepths], context->depths);
    copy_buffer_values(buffers[ARootIndices], context->root_indices);
    copy_buffer_values(buffers[ATetherRestLengths], context->tether_rest_lengths);
    copy_buffer_values(buffers[AParentIndices], context->parent_indices);
    copy_buffer_values(buffers[ABaselineStart], context->baseline_start);
    copy_buffer_values(buffers[ABaselineCount], context->baseline_count);
    copy_buffer_values(buffers[ABaselineData], context->baseline_data);
    copy_buffer_values(buffers[AVertexLocalPositions], context->vertex_local_positions);
    copy_buffer_values(buffers[AVertexLocalRotations], context->vertex_local_rotations);
    copy_buffer_values(buffers[ADistanceStart], context->distance_start);
    copy_buffer_values(buffers[ADistanceCount], context->distance_count_values);
    copy_buffer_values(buffers[ADistanceData], context->distance_data);
    copy_buffer_values(buffers[ADistanceRest], context->distance_rest);
    copy_buffer_values(buffers[ABendDistanceStart], context->bend_distance_start);
    copy_buffer_values(buffers[ABendDistanceCount], context->bend_distance_count);
    copy_buffer_values(buffers[ABendDistanceData], context->bend_distance_data);
    copy_buffer_values(buffers[ABendDistanceRest], context->bend_distance_rest);
    copy_buffer_values(buffers[ADihedralPairs], context->dihedral_pairs);
    copy_buffer_values(buffers[ADihedralRestAngles], context->dihedral_rest_angles);
    copy_buffer_values(buffers[ADihedralSigns], context->dihedral_signs);
    copy_buffer_values(buffers[AVolumePairs], context->volume_pairs);
    copy_buffer_values(buffers[AVolumeRest], context->volume_rest);
    copy_buffer_values(buffers[AEdges], context->edges);
    copy_buffer_values(buffers[ATriangles], context->triangles);
    context->static_ready = true;
    context->topology_serial += 1;
    Py_RETURN_NONE;
}

PyObject* update_meshcloth_mc2_context_params_object(PyObject* context_object, long param_slot_count) {
    auto* context = get_mc2_context(context_object);
    if (!ensure_context_live(context)) {
        return nullptr;
    }
    context->param_slot_count = param_slot_count;
    clear_param_storage(*context);
    context->param_serial += 1;
    Py_RETURN_NONE;
}

PyObject* update_meshcloth_mc2_context_param_arrays(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArrayCount = 11;
    constexpr Py_ssize_t kArgCount = kArrayCount + 1;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "update_meshcloth_mc2_context_param_arrays expects %zd arguments", kArgCount);
        return nullptr;
    }
    auto* context = get_mc2_context(PyTuple_GET_ITEM(args, 0));
    if (!ensure_context_live(context)) {
        return nullptr;
    }

    enum ParamArg {
        ADistanceStiffness = 0,
        ABendStiffness,
        AAngleRestoration,
        AAngleRestorationVelocityAttenuation,
        AAngleRestorationGravityFalloff,
        AAngleLimit,
        ASubstepDamping,
        AMaxDistances,
        AMotionStiffness,
        ABackstopRadii,
        ABackstopDistances,
    };
    const char* names[kArrayCount] = {
        "distance_stiffness_values",
        "bend_stiffness_values",
        "angle_restoration_values",
        "angle_restoration_velocity_attenuation_values",
        "angle_restoration_gravity_falloff_values",
        "angle_limit_values",
        "substep_damping_values",
        "max_distances",
        "motion_stiffness_values",
        "backstop_radii",
        "backstop_distances",
    };

    Buffer buffers[kArrayCount];
    for (int index = 0; index < kArrayCount; ++index) {
        if (!buffers[index].get(PyTuple_GET_ITEM(args, index + 1), PyBUF_FORMAT | PyBUF_ND, names[index])) {
            return nullptr;
        }
    }

    const Py_ssize_t vertex_count = static_cast<Py_ssize_t>(context->vertex_count);
    if (vertex_count <= 0) {
        PyErr_SetString(PyExc_ValueError, "MC2 context vertex_count must be positive before parameter array upload");
        return nullptr;
    }
    for (int index = 0; index < kArrayCount; ++index) {
        if (!expect_float32(buffers[index], names[index]) || !expect_1d_array(buffers[index], names[index], vertex_count)) {
            return nullptr;
        }
    }

    clear_param_storage(*context);
    copy_buffer_values(buffers[ADistanceStiffness], context->distance_stiffness_values);
    copy_buffer_values(buffers[ABendStiffness], context->bend_stiffness_values);
    copy_buffer_values(buffers[AAngleRestoration], context->angle_restoration_values);
    copy_buffer_values(buffers[AAngleRestorationVelocityAttenuation],
                       context->angle_restoration_velocity_attenuation_values);
    copy_buffer_values(buffers[AAngleRestorationGravityFalloff],
                       context->angle_restoration_gravity_falloff_values);
    copy_buffer_values(buffers[AAngleLimit], context->angle_limit_values);
    copy_buffer_values(buffers[ASubstepDamping], context->substep_damping_values);
    copy_buffer_values(buffers[AMaxDistances], context->max_distances);
    copy_buffer_values(buffers[AMotionStiffness], context->motion_stiffness_values);
    copy_buffer_values(buffers[ABackstopRadii], context->backstop_radii);
    copy_buffer_values(buffers[ABackstopDistances], context->backstop_distances);
    context->param_array_count = vertex_count;
    context->param_arrays_ready = true;
    context->param_serial += 1;
    Py_RETURN_NONE;
}

PyObject* meshcloth_mc2_context_info_object(PyObject* context_object) {
    auto* context = get_mc2_context(context_object);
    if (!ensure_context_live(context)) {
        return nullptr;
    }
    return mc2_context_to_dict(*context);
}

PyObject* free_meshcloth_mc2_context_object(PyObject* context_object) {
    auto* context = get_mc2_context(context_object);
    if (context == nullptr) {
        return nullptr;
    }
    context->released = true;
    context->vertex_count = 0;
    context->distance_count = 0;
    context->bend_count = 0;
    context->collider_radius_count = 0;
    context->param_slot_count = 0;
    clear_static_storage(*context);
    Py_RETURN_NONE;
}

PyObject* solve_meshcloth_mc2_context_impl(PyObject* args, bool use_cached_params, const char* function_name) {
    enum DynamicArg {
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
        ADistanceStiffnessValues,
        ABendStiffnessValues,
        AAngleRestorationValues,
        AAngleRestorationVelocityAttenuationValues,
        AAngleRestorationGravityFalloffValues,
        AAngleLimitValues,
        ASubstepDampingValues,
        AMaxDistances,
        AMotionStiffnessValues,
        ABackstopRadii,
        ABackstopDistances,
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
        kDynamicBufferCount,
    };
    constexpr int kCachedParamStart = ADistanceStiffnessValues;
    constexpr int kCachedParamEnd = ABackstopDistances;
    constexpr int kCachedParamCount = kCachedParamEnd - kCachedParamStart + 1;
    const Py_ssize_t dynamic_arg_count =
        use_cached_params ? kDynamicBufferCount - kCachedParamCount : kDynamicBufferCount;
    const Py_ssize_t kArgCount = 1 + dynamic_arg_count + 23;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "%s expects %zd arguments", function_name, kArgCount);
        return nullptr;
    }

    auto* context = get_mc2_context(PyTuple_GET_ITEM(args, 0));
    if (!ensure_context_live(context)) {
        return nullptr;
    }
    if (!context->static_ready) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 context static arrays have not been uploaded");
        return nullptr;
    }

    const char* names[kDynamicBufferCount] = {
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
        "distance_stiffness_values",
        "bend_stiffness_values",
        "angle_restoration_values",
        "angle_restoration_velocity_attenuation_values",
        "angle_restoration_gravity_falloff_values",
        "angle_limit_values",
        "substep_damping_values",
        "max_distances",
        "motion_stiffness_values",
        "backstop_radii",
        "backstop_distances",
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

    Buffer buffers[kDynamicBufferCount];
    for (int index = 0; index < kDynamicBufferCount; ++index) {
        if (use_cached_params && index >= kCachedParamStart && index <= kCachedParamEnd) {
            continue;
        }
        const int flags = index <= ADisplayPositions ? (PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND)
                                                     : (PyBUF_FORMAT | PyBUF_ND);
        const Py_ssize_t tuple_index =
            index + 1 - ((use_cached_params && index > kCachedParamEnd) ? kCachedParamCount : 0);
        if (!buffers[index].get(PyTuple_GET_ITEM(args, tuple_index), flags, names[index])) {
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
        !expect_same_quat_vertex_count(buffers[ABaseRotations], "base_rotations", vertex_count)) {
        return nullptr;
    }
    if (vertex_count != context->vertex_count) {
        PyErr_SetString(PyExc_ValueError, "context vertex count mismatch");
        return nullptr;
    }

    if (!expect_float32(buffers[AFriction], "friction") ||
        !expect_1d_array(buffers[AFriction], "friction", vertex_count) ||
        !expect_float32(buffers[AStaticFriction], "static_friction") ||
        !expect_1d_array(buffers[AStaticFriction], "static_friction", vertex_count) ||
        !expect_float32(buffers[AInvMasses], "inv_masses") ||
        !expect_1d_array(buffers[AInvMasses], "inv_masses", vertex_count)) {
        return nullptr;
    }
    if (use_cached_params) {
        if (!ensure_context_param_arrays_ready(*context, vertex_count)) {
            return nullptr;
        }
    } else if (!expect_float32(buffers[ADistanceStiffnessValues], "distance_stiffness_values") ||
        !expect_1d_array(buffers[ADistanceStiffnessValues], "distance_stiffness_values", vertex_count) ||
        !expect_float32(buffers[ABendStiffnessValues], "bend_stiffness_values") ||
        !expect_1d_array(buffers[ABendStiffnessValues], "bend_stiffness_values", vertex_count) ||
        !expect_float32(buffers[AAngleRestorationValues], "angle_restoration_values") ||
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
        !expect_1d_array(buffers[ABackstopDistances], "backstop_distances", vertex_count)) {
        return nullptr;
    }
    if (!expect_float32(buffers[ACollisionRadii], "collision_radii") ||
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
        PyErr_SetString(PyExc_ValueError, "collider array length mismatch");
        return nullptr;
    }

    const Py_ssize_t kScalarStart = 1 + dynamic_arg_count;
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
        PyErr_SetString(PyExc_ValueError, "substep inertia array length mismatch");
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

    Mc2MeshClothSolveView view;
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
    view.attributes = data_or_dummy(context->attributes);
    view.depths = data_or_dummy(context->depths);
    view.root_indices = data_or_dummy(context->root_indices);
    view.tether_rest_lengths = data_or_dummy(context->tether_rest_lengths);
    view.parent_indices = data_or_dummy(context->parent_indices);
    view.baseline_start = data_or_dummy(context->baseline_start);
    view.baseline_count = data_or_dummy(context->baseline_count);
    view.baseline_data = data_or_dummy(context->baseline_data);
    view.vertex_local_positions = data_or_dummy(context->vertex_local_positions);
    view.vertex_local_rotations = data_or_dummy(context->vertex_local_rotations);
    view.distance_start = data_or_dummy(context->distance_start);
    view.distance_count = data_or_dummy(context->distance_count_values);
    view.distance_data = data_or_dummy(context->distance_data);
    view.distance_rest = data_or_dummy(context->distance_rest);
    view.distance_stiffness_values = use_cached_params
                                         ? data_or_dummy(context->distance_stiffness_values)
                                         : static_cast<const float*>(buffers[ADistanceStiffnessValues].view.buf);
    view.bend_distance_start = data_or_dummy(context->bend_distance_start);
    view.bend_distance_count = data_or_dummy(context->bend_distance_count);
    view.bend_distance_data = data_or_dummy(context->bend_distance_data);
    view.bend_distance_rest = data_or_dummy(context->bend_distance_rest);
    view.bend_stiffness_values = use_cached_params
                                     ? data_or_dummy(context->bend_stiffness_values)
                                     : static_cast<const float*>(buffers[ABendStiffnessValues].view.buf);
    view.dihedral_pairs = data_or_dummy(context->dihedral_pairs);
    view.dihedral_rest_angles = data_or_dummy(context->dihedral_rest_angles);
    view.dihedral_signs = data_or_dummy(context->dihedral_signs);
    view.volume_pairs = data_or_dummy(context->volume_pairs);
    view.volume_rest = data_or_dummy(context->volume_rest);
    view.angle_restoration_values = use_cached_params
                                        ? data_or_dummy(context->angle_restoration_values)
                                        : static_cast<const float*>(buffers[AAngleRestorationValues].view.buf);
    view.angle_restoration_velocity_attenuation_values =
        use_cached_params
            ? data_or_dummy(context->angle_restoration_velocity_attenuation_values)
            : static_cast<const float*>(buffers[AAngleRestorationVelocityAttenuationValues].view.buf);
    view.angle_restoration_gravity_falloff_values =
        use_cached_params
            ? data_or_dummy(context->angle_restoration_gravity_falloff_values)
            : static_cast<const float*>(buffers[AAngleRestorationGravityFalloffValues].view.buf);
    view.angle_limit_values = use_cached_params
                                  ? data_or_dummy(context->angle_limit_values)
                                  : static_cast<const float*>(buffers[AAngleLimitValues].view.buf);
    view.substep_damping_values = use_cached_params
                                      ? data_or_dummy(context->substep_damping_values)
                                      : static_cast<const float*>(buffers[ASubstepDampingValues].view.buf);
    view.max_distances = use_cached_params
                             ? data_or_dummy(context->max_distances)
                             : static_cast<const float*>(buffers[AMaxDistances].view.buf);
    view.motion_stiffness_values = use_cached_params
                                       ? data_or_dummy(context->motion_stiffness_values)
                                       : static_cast<const float*>(buffers[AMotionStiffnessValues].view.buf);
    view.backstop_radii = use_cached_params
                              ? data_or_dummy(context->backstop_radii)
                              : static_cast<const float*>(buffers[ABackstopRadii].view.buf);
    view.backstop_distances = use_cached_params
                                  ? data_or_dummy(context->backstop_distances)
                                  : static_cast<const float*>(buffers[ABackstopDistances].view.buf);
    view.edges = data_or_dummy(context->edges);
    view.triangles = data_or_dummy(context->triangles);
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
    view.vertex_count = context->vertex_count;
    view.line_count = context->line_count;
    view.baseline_data_count = context->baseline_data_count;
    view.distance_count_total = context->distance_count;
    view.bend_distance_count_total = context->bend_count;
    view.edge_count = context->edge_count;
    view.triangle_count = context->triangle_count;
    view.dihedral_count = context->dihedral_count;
    view.volume_count = context->volume_count;
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

    solve_meshcloth_mc2(view);
    Py_RETURN_NONE;
}

PyObject* solve_meshcloth_mc2_context(PyObject*, PyObject* args) {
    return solve_meshcloth_mc2_context_impl(args, false, "solve_meshcloth_mc2_context");
}

PyObject* solve_meshcloth_mc2_context_cached_params(PyObject*, PyObject* args) {
    return solve_meshcloth_mc2_context_impl(args, true, "solve_meshcloth_mc2_context_cached_params");
}

}  // namespace hotools
