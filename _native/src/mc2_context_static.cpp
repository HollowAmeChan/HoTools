#include "mc2_api.hpp"

#include "mc2_context_internal.hpp"
#include "mc2_context_helpers.hpp"
#include "mc2_static_build.hpp"
#include "python_buffer_utils.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <utility>
#include <vector>

namespace hotools {

using namespace mc2_internal;
using namespace py;

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
    target->frame_triangle_uvs = source->frame_triangle_uvs;
    target->proxy_attributes = source->proxy_attributes;
    target->proxy_radius_multipliers = source->proxy_radius_multipliers;
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
    target->self_topology_neighbor_keys = source->self_topology_neighbor_keys;
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
    const bool has_radius_multipliers = argument_count == 9 || argument_count == 16;
    const bool take_owned = argument_count == 15 || argument_count == 16;
    if (argument_count != 8 && argument_count != 9 && !take_owned) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_update_proxy_static expects 8, 9, 15, or 16 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    Buffer positions, normals, tangents, uvs, attributes, edges, triangles, radius_multipliers;
    if (!positions.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "local_positions") ||
        !normals.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "local_normals") ||
        !tangents.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "local_tangents") ||
        !uvs.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "uvs") ||
        !attributes.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "vertex_attributes") ||
        !edges.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "edges") ||
        !triangles.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "triangles")) {
        return nullptr;
    }
    if (has_radius_multipliers && !radius_multipliers.get(
            PyTuple_GET_ITEM(args, 8),
            PyBUF_FORMAT | PyBUF_ND,
            "radius_multipliers"
        )) {
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
        (has_radius_multipliers &&
         (!expect_float32(radius_multipliers, "radius_multipliers") ||
          !expect_1d_array(radius_multipliers, "radius_multipliers", count) ||
          !finite_floats(radius_multipliers, "radius_multipliers"))) ||
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
    if (has_radius_multipliers) {
        const auto* values = static_cast<const float*>(radius_multipliers.view.buf);
        for (Py_ssize_t index = 0; index < count; ++index) {
            if (values[index] < 0.0f || values[index] > 1.0f) {
                PyErr_SetString(PyExc_ValueError, "radius_multipliers must be in 0..1");
                return nullptr;
            }
        }
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
    std::vector<float> next_radius_multipliers(
        static_cast<std::size_t>(count),
        1.0f
    );
    std::vector<std::int32_t> next_edges;
    std::vector<std::int32_t> next_triangles;
    if (take_owned) {
        const Py_ssize_t owner_offset = has_radius_multipliers ? 9 : 8;
        auto* owned_positions = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, owner_offset), "hotools_native.mc2.proxy_positions.v0", positions
        );
        auto* owned_normals = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, owner_offset + 1), "hotools_native.mc2.proxy_normals.v0", normals
        );
        auto* owned_tangents = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, owner_offset + 2), "hotools_native.mc2.proxy_tangents.v0", tangents
        );
        auto* owned_uvs = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, owner_offset + 3), "hotools_native.mc2.proxy_uvs.v0", uvs
        );
        auto* owned_attributes = validated_owned_values<std::uint8_t>(
            PyTuple_GET_ITEM(args, owner_offset + 4), "hotools_native.mc2.proxy_attributes.v0", attributes
        );
        auto* owned_edges = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, owner_offset + 5), "hotools_native.mc2.proxy_edges.v0", edges
        );
        auto* owned_triangles = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, owner_offset + 6), "hotools_native.mc2.proxy_triangles.v0", triangles
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
    if (has_radius_multipliers) {
        next_radius_multipliers = copy_values<float>(radius_multipliers);
    }
    context->proxy_local_positions.swap(next_positions);
    context->proxy_local_normals.swap(next_normals);
    context->proxy_local_tangents.swap(next_tangents);
    context->proxy_uvs.swap(next_uvs);
    context->proxy_attributes.swap(next_attributes);
    context->proxy_radius_multipliers.swap(next_radius_multipliers);
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
    const bool has_triangle_uvs = argument_count == 5 || argument_count == 9;
    const bool take_owned = argument_count == 7 || argument_count == 9;
    if (argument_count != 4 && argument_count != 5 &&
        argument_count != 7 && argument_count != 9) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_update_frame_producer_static expects 4, 5, 7, or 9 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->proxy_static_ready) {
        PyErr_SetString(PyExc_RuntimeError, "frame producer static requires proxy static");
        return nullptr;
    }
    Buffer ranges, data, bind_rotations, triangle_uvs;
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
    const auto triangle_count = static_cast<Py_ssize_t>(context->proxy_triangles.size() / 3);
    if (has_triangle_uvs &&
        (!triangle_uvs.get(
            PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "triangle_uvs"
        ) ||
        !expect_float32(triangle_uvs, "triangle_uvs") ||
        !expect_2d(triangle_uvs, "triangle_uvs", triangle_count, 6) ||
        !finite_floats(triangle_uvs, "triangle_uvs"))) {
        return nullptr;
    }
    const auto* range_values = static_cast<const std::int32_t*>(ranges.view.buf);
    const auto* data_values = static_cast<const std::int32_t*>(data.view.buf);
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
    std::vector<float> next_triangle_uvs;
    if (take_owned) {
        const auto owner_offset = has_triangle_uvs ? 5 : 4;
        auto* owned_ranges = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, owner_offset),
            "hotools_native.mc2.frame_triangle_ranges.v0",
            ranges
        );
        auto* owned_data = validated_owned_values<std::int32_t>(
            PyTuple_GET_ITEM(args, owner_offset + 1),
            "hotools_native.mc2.frame_triangle_records.v0",
            data
        );
        auto* owned_bind_rotations = validated_owned_values<float>(
            PyTuple_GET_ITEM(args, owner_offset + 2),
            "hotools_native.mc2.frame_bind_rotations.v0",
            bind_rotations
        );
        std::vector<float>* owned_triangle_uvs = nullptr;
        if (has_triangle_uvs) {
            owned_triangle_uvs = validated_owned_values<float>(
                PyTuple_GET_ITEM(args, owner_offset + 3),
                "hotools_native.mc2.frame_triangle_uvs.v0",
                triangle_uvs
            );
        }
        if (owned_ranges == nullptr || owned_data == nullptr ||
            owned_bind_rotations == nullptr ||
            (has_triangle_uvs && owned_triangle_uvs == nullptr)) {
            return nullptr;
        }
        next_ranges = std::move(*owned_ranges);
        next_data = std::move(*owned_data);
        next_bind_rotations = std::move(*owned_bind_rotations);
        if (has_triangle_uvs) next_triangle_uvs = std::move(*owned_triangle_uvs);
        ++context->owned_static_take_count;
    } else {
        next_ranges = copy_values<std::int32_t>(ranges);
        next_data = copy_values<std::int32_t>(data);
        next_bind_rotations = copy_values<float>(bind_rotations);
        if (has_triangle_uvs) next_triangle_uvs = copy_values<float>(triangle_uvs);
    }
    context->bone_vertex_to_triangle_ranges.swap(next_ranges);
    context->bone_vertex_to_triangle_data.swap(next_data);
    context->bone_vertex_bind_pose_rotations.swap(next_bind_rotations);
    context->frame_triangle_uvs.swap(next_triangle_uvs);
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
    std::vector<std::uint64_t> next_topology_neighbor_keys;
    next_topology_neighbor_keys.reserve(context->proxy_edges.size() / 2);
    for (std::size_t edge = 0; edge < context->proxy_edges.size(); edge += 2) {
        const auto first = context->proxy_edges[edge];
        const auto second = context->proxy_edges[edge + 1];
        if (first == second) continue;
        next_topology_neighbor_keys.push_back(
            self_particle_pair_key(first, second)
        );
    }
    std::sort(
        next_topology_neighbor_keys.begin(),
        next_topology_neighbor_keys.end()
    );
    next_topology_neighbor_keys.erase(
        std::unique(
            next_topology_neighbor_keys.begin(),
            next_topology_neighbor_keys.end()
        ),
        next_topology_neighbor_keys.end()
    );
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
    context->self_topology_neighbor_keys.swap(next_topology_neighbor_keys);
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

}  // namespace hotools
