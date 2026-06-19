#include <Python.h>

#include "hotools_mc2.hpp"
#include "hotools_mesh_xpbd.hpp"
#include "hotools_property_curve.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace {

struct Buffer {
    Py_buffer view {};
    bool acquired = false;

    ~Buffer() {
        if (acquired) {
            PyBuffer_Release(&view);
        }
    }

    bool get(PyObject* object, int flags, const char* name) {
        if (PyObject_GetBuffer(object, &view, flags) != 0) {
            return false;
        }
        acquired = true;

        if (!PyBuffer_IsContiguous(&view, 'C')) {
            PyErr_Format(PyExc_ValueError, "%s must be C-contiguous", name);
            return false;
        }
        return true;
    }
};

bool expect_float32(const Buffer& buffer, const char* name) {
    if (buffer.view.itemsize != 4) {
        PyErr_Format(PyExc_TypeError, "%s must use float32 elements", name);
        return false;
    }
    if (buffer.view.format != nullptr) {
        const char format = buffer.view.format[0];
        if (format != 'f') {
            PyErr_Format(PyExc_TypeError, "%s must use float32 elements", name);
            return false;
        }
    }
    return true;
}

bool expect_int32(const Buffer& buffer, const char* name) {
    if (buffer.view.itemsize != 4) {
        PyErr_Format(PyExc_TypeError, "%s must use int32 elements", name);
        return false;
    }
    if (buffer.view.format != nullptr) {
        const char format = buffer.view.format[0];
        if (format != 'i' && format != 'l') {
            PyErr_Format(PyExc_TypeError, "%s must use int32 elements", name);
            return false;
        }
    }
    return true;
}

bool expect_uint8(const Buffer& buffer, const char* name) {
    if (buffer.view.itemsize != 1) {
        PyErr_Format(PyExc_TypeError, "%s must use uint8 elements", name);
        return false;
    }
    if (buffer.view.format != nullptr) {
        const char format = buffer.view.format[0];
        if (format != 'B') {
            PyErr_Format(PyExc_TypeError, "%s must use uint8 elements", name);
            return false;
        }
    }
    return true;
}

bool expect_vector3_array(const Buffer& buffer, const char* name, Py_ssize_t* count) {
    if (!expect_float32(buffer, name)) {
        return false;
    }
    if (buffer.view.ndim != 2 || buffer.view.shape == nullptr || buffer.view.shape[1] != 3) {
        PyErr_Format(PyExc_ValueError, "%s must have shape (n, 3)", name);
        return false;
    }
    *count = buffer.view.shape[0];
    return true;
}

bool expect_1d_array(const Buffer& buffer, const char* name, Py_ssize_t expected_count) {
    if (buffer.view.ndim != 1 || buffer.view.shape == nullptr) {
        PyErr_Format(PyExc_ValueError, "%s must be a 1D array", name);
        return false;
    }
    if (expected_count >= 0 && buffer.view.shape[0] != expected_count) {
        PyErr_Format(PyExc_ValueError, "%s length mismatch", name);
        return false;
    }
    return true;
}

bool expect_same_vertex_count(const Buffer& buffer, const char* name, Py_ssize_t vertex_count) {
    Py_ssize_t count = 0;
    if (!expect_vector3_array(buffer, name, &count)) {
        return false;
    }
    if (count != vertex_count) {
        PyErr_Format(PyExc_ValueError, "%s vertex count mismatch", name);
        return false;
    }
    return true;
}

bool expect_vector4_array(const Buffer& buffer, const char* name, Py_ssize_t* count) {
    if (!expect_float32(buffer, name)) {
        return false;
    }
    if (buffer.view.ndim != 2 || buffer.view.shape == nullptr || buffer.view.shape[1] != 4) {
        PyErr_Format(PyExc_ValueError, "%s must have shape (n, 4)", name);
        return false;
    }
    *count = buffer.view.shape[0];
    return true;
}

bool expect_same_quat_vertex_count(const Buffer& buffer, const char* name, Py_ssize_t vertex_count) {
    Py_ssize_t count = 0;
    if (!expect_vector4_array(buffer, name, &count)) {
        return false;
    }
    if (count != vertex_count) {
        PyErr_Format(PyExc_ValueError, "%s vertex count mismatch", name);
        return false;
    }
    return true;
}

bool expect_indices_in_range(const Buffer& buffer, const char* name, Py_ssize_t vertex_count) {
    const auto* values = static_cast<const std::int32_t*>(buffer.view.buf);
    for (Py_ssize_t index = 0; index < buffer.view.shape[0]; ++index) {
        if (values[index] < 0 || static_cast<Py_ssize_t>(values[index]) >= vertex_count) {
            PyErr_Format(PyExc_ValueError, "%s contains vertex index out of range", name);
            return false;
        }
    }
    return true;
}

bool expect_root_indices_or_minus_one(const Buffer& buffer, const char* name, Py_ssize_t vertex_count) {
    const auto* values = static_cast<const std::int32_t*>(buffer.view.buf);
    for (Py_ssize_t index = 0; index < buffer.view.shape[0]; ++index) {
        if (values[index] < -1 || static_cast<Py_ssize_t>(values[index]) >= vertex_count) {
            PyErr_Format(PyExc_ValueError, "%s contains root index out of range", name);
            return false;
        }
    }
    return true;
}

bool expect_int32_scalar_array(const Buffer& buffer, const char* name) {
    if (!expect_int32(buffer, name)) {
        return false;
    }
    if (buffer.view.ndim != 1 || buffer.view.shape == nullptr) {
        PyErr_Format(PyExc_ValueError, "%s must be a 1D array", name);
        return false;
    }
    return true;
}

bool expect_uint8_scalar_array(const Buffer& buffer, const char* name) {
    if (!expect_uint8(buffer, name)) {
        return false;
    }
    if (buffer.view.ndim != 1 || buffer.view.shape == nullptr) {
        PyErr_Format(PyExc_ValueError, "%s must be a 1D array", name);
        return false;
    }
    return true;
}

bool expect_int32_quad_array(const Buffer& buffer, const char* name, Py_ssize_t* count) {
    if (!expect_int32(buffer, name)) {
        return false;
    }
    if (buffer.view.ndim != 2 || buffer.view.shape == nullptr || buffer.view.shape[1] != 4) {
        PyErr_Format(PyExc_ValueError, "%s must have shape (n, 4)", name);
        return false;
    }
    *count = buffer.view.shape[0];
    return true;
}

bool expect_int32_pair_array(const Buffer& buffer, const char* name, Py_ssize_t* count) {
    if (!expect_int32(buffer, name)) {
        return false;
    }
    if (buffer.view.ndim != 2 || buffer.view.shape == nullptr || buffer.view.shape[1] != 2) {
        PyErr_Format(PyExc_ValueError, "%s must have shape (n, 2)", name);
        return false;
    }
    *count = buffer.view.shape[0];
    return true;
}

bool expect_quad_indices_in_range(const Buffer& buffer, const char* name, Py_ssize_t vertex_count) {
    const auto* values = static_cast<const std::int32_t*>(buffer.view.buf);
    const Py_ssize_t count = buffer.view.shape[0] * 4;
    for (Py_ssize_t index = 0; index < count; ++index) {
        if (values[index] < 0 || static_cast<Py_ssize_t>(values[index]) >= vertex_count) {
            PyErr_Format(PyExc_ValueError, "%s contains vertex index out of range", name);
            return false;
        }
    }
    return true;
}

bool expect_pair_indices_in_range(const Buffer& buffer, const char* name, Py_ssize_t vertex_count) {
    const auto* values = static_cast<const std::int32_t*>(buffer.view.buf);
    const Py_ssize_t count = buffer.view.shape[0] * 2;
    for (Py_ssize_t index = 0; index < count; ++index) {
        if (values[index] < 0 || static_cast<Py_ssize_t>(values[index]) >= vertex_count) {
            PyErr_Format(PyExc_ValueError, "%s contains vertex index out of range", name);
            return false;
        }
    }
    return true;
}

double as_double(PyObject* object, const char* name) {
    const double value = PyFloat_AsDouble(object);
    if (PyErr_Occurred()) {
        PyErr_Format(PyExc_TypeError, "%s must be a float", name);
    }
    return value;
}

long as_long(PyObject* object, const char* name) {
    const long value = PyLong_AsLong(object);
    if (PyErr_Occurred()) {
        PyErr_Format(PyExc_TypeError, "%s must be an integer", name);
    }
    return value;
}

PyObject* solve_mesh_shape_key_xpbd(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 25;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "solve_mesh_shape_key_xpbd expects %zd arguments", kArgCount);
        return nullptr;
    }

    Buffer positions;
    Buffer prev_positions;
    Buffer rest_positions;
    Buffer inv_masses;
    Buffer edge_i;
    Buffer edge_j;
    Buffer edge_rest;
    Buffer bend_i;
    Buffer bend_j;
    Buffer bend_rest;
    Buffer gravity;
    Buffer collision_radii;
    Buffer collider_types;
    Buffer collider_groups;
    Buffer collider_centers;
    Buffer collider_segment_a;
    Buffer collider_segment_b;
    Buffer collider_radii;

    if (!positions.get(PyTuple_GET_ITEM(args, 0), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !prev_positions.get(PyTuple_GET_ITEM(args, 1), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "prev_positions") ||
        !rest_positions.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "rest_positions") ||
        !inv_masses.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !edge_i.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "edge_i") ||
        !edge_j.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "edge_j") ||
        !edge_rest.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "edge_rest") ||
        !bend_i.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "bend_i") ||
        !bend_j.get(PyTuple_GET_ITEM(args, 8), PyBUF_FORMAT | PyBUF_ND, "bend_j") ||
        !bend_rest.get(PyTuple_GET_ITEM(args, 9), PyBUF_FORMAT | PyBUF_ND, "bend_rest") ||
        !gravity.get(PyTuple_GET_ITEM(args, 10), PyBUF_FORMAT | PyBUF_ND, "gravity") ||
        !collision_radii.get(PyTuple_GET_ITEM(args, 17), PyBUF_FORMAT | PyBUF_ND, "collision_radii") ||
        !collider_types.get(PyTuple_GET_ITEM(args, 19), PyBUF_FORMAT | PyBUF_ND, "collider_types") ||
        !collider_groups.get(PyTuple_GET_ITEM(args, 20), PyBUF_FORMAT | PyBUF_ND, "collider_groups") ||
        !collider_centers.get(PyTuple_GET_ITEM(args, 21), PyBUF_FORMAT | PyBUF_ND, "collider_centers") ||
        !collider_segment_a.get(PyTuple_GET_ITEM(args, 22), PyBUF_FORMAT | PyBUF_ND, "collider_segment_a") ||
        !collider_segment_b.get(PyTuple_GET_ITEM(args, 23), PyBUF_FORMAT | PyBUF_ND, "collider_segment_b") ||
        !collider_radii.get(PyTuple_GET_ITEM(args, 24), PyBUF_FORMAT | PyBUF_ND, "collider_radii")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(prev_positions, "prev_positions", vertex_count) ||
        !expect_same_vertex_count(rest_positions, "rest_positions", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_int32(edge_i, "edge_i") ||
        !expect_int32(edge_j, "edge_j") ||
        !expect_float32(edge_rest, "edge_rest") ||
        !expect_int32(bend_i, "bend_i") ||
        !expect_int32(bend_j, "bend_j") ||
        !expect_float32(bend_rest, "bend_rest") ||
        !expect_float32(gravity, "gravity") ||
        !expect_1d_array(gravity, "gravity", 3) ||
        !expect_float32(collision_radii, "collision_radii") ||
        !expect_1d_array(collision_radii, "collision_radii", vertex_count) ||
        !expect_int32(collider_types, "collider_types") ||
        !expect_int32(collider_groups, "collider_groups") ||
        !expect_float32(collider_radii, "collider_radii")) {
        return nullptr;
    }

    const Py_ssize_t edge_count = edge_i.view.shape[0];
    const Py_ssize_t bend_count = bend_i.view.shape[0];
    if (!expect_1d_array(edge_j, "edge_j", edge_count) ||
        !expect_1d_array(edge_rest, "edge_rest", edge_count) ||
        !expect_1d_array(bend_j, "bend_j", bend_count) ||
        !expect_1d_array(bend_rest, "bend_rest", bend_count)) {
        return nullptr;
    }
    if (!expect_indices_in_range(edge_i, "edge_i", vertex_count) ||
        !expect_indices_in_range(edge_j, "edge_j", vertex_count) ||
        !expect_indices_in_range(bend_i, "bend_i", vertex_count) ||
        !expect_indices_in_range(bend_j, "bend_j", vertex_count)) {
        return nullptr;
    }

    Py_ssize_t collider_count = 0;
    Py_ssize_t collider_segment_a_count = 0;
    Py_ssize_t collider_segment_b_count = 0;
    if (!expect_vector3_array(collider_centers, "collider_centers", &collider_count) ||
        !expect_vector3_array(collider_segment_a, "collider_segment_a", &collider_segment_a_count) ||
        !expect_vector3_array(collider_segment_b, "collider_segment_b", &collider_segment_b_count)) {
        return nullptr;
    }
    if (collider_segment_a_count != collider_count || collider_segment_b_count != collider_count) {
        PyErr_SetString(PyExc_ValueError, "collider segment array length mismatch");
        return nullptr;
    }
    if (!expect_1d_array(collider_types, "collider_types", collider_count) ||
        !expect_1d_array(collider_groups, "collider_groups", collider_count) ||
        !expect_1d_array(collider_radii, "collider_radii", collider_count)) {
        return nullptr;
    }

    const double dt = as_double(PyTuple_GET_ITEM(args, 11), "dt");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double damping = as_double(PyTuple_GET_ITEM(args, 12), "damping");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const long substeps = as_long(PyTuple_GET_ITEM(args, 13), "substeps");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const long iterations = as_long(PyTuple_GET_ITEM(args, 14), "iterations");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double stretch_compliance = as_double(PyTuple_GET_ITEM(args, 15), "stretch_compliance");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double bend_compliance = as_double(PyTuple_GET_ITEM(args, 16), "bend_compliance");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const long collided_by_groups = as_long(PyTuple_GET_ITEM(args, 18), "collided_by_groups");
    if (PyErr_Occurred()) {
        return nullptr;
    }

    hotools::MeshXpbdView solver_view;
    solver_view.positions = static_cast<float*>(positions.view.buf);
    solver_view.prev_positions = static_cast<float*>(prev_positions.view.buf);
    solver_view.rest_positions = static_cast<const float*>(rest_positions.view.buf);
    solver_view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    solver_view.vertex_count = static_cast<std::int64_t>(vertex_count);
    solver_view.edge_i = static_cast<const std::int32_t*>(edge_i.view.buf);
    solver_view.edge_j = static_cast<const std::int32_t*>(edge_j.view.buf);
    solver_view.edge_rest = static_cast<const float*>(edge_rest.view.buf);
    solver_view.edge_count = static_cast<std::int64_t>(edge_count);
    solver_view.bend_i = static_cast<const std::int32_t*>(bend_i.view.buf);
    solver_view.bend_j = static_cast<const std::int32_t*>(bend_j.view.buf);
    solver_view.bend_rest = static_cast<const float*>(bend_rest.view.buf);
    solver_view.bend_count = static_cast<std::int64_t>(bend_count);
    solver_view.collision_radii = static_cast<const float*>(collision_radii.view.buf);
    solver_view.collided_by_groups = static_cast<std::int32_t>(collided_by_groups);
    solver_view.collider_types = static_cast<const std::int32_t*>(collider_types.view.buf);
    solver_view.collider_groups = static_cast<const std::int32_t*>(collider_groups.view.buf);
    solver_view.collider_centers = static_cast<const float*>(collider_centers.view.buf);
    solver_view.collider_segment_a = static_cast<const float*>(collider_segment_a.view.buf);
    solver_view.collider_segment_b = static_cast<const float*>(collider_segment_b.view.buf);
    solver_view.collider_radii = static_cast<const float*>(collider_radii.view.buf);
    solver_view.collider_count = static_cast<std::int64_t>(collider_count);

    const float* gravity_values = static_cast<const float*>(gravity.view.buf);
    solver_view.gravity[0] = gravity_values[0];
    solver_view.gravity[1] = gravity_values[1];
    solver_view.gravity[2] = gravity_values[2];
    solver_view.dt = static_cast<float>(dt);
    solver_view.damping = static_cast<float>(damping);
    solver_view.substeps = static_cast<int>(substeps);
    solver_view.iterations = static_cast<int>(iterations);
    solver_view.stretch_compliance = static_cast<float>(stretch_compliance);
    solver_view.bend_compliance = static_cast<float>(bend_compliance);

    hotools::solve_mesh_shape_key_xpbd(solver_view);

    Py_RETURN_NONE;
}

PyObject* project_neighbor_constraints_mc2(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 9;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "project_neighbor_constraints_mc2 expects %zd arguments", kArgCount);
        return nullptr;
    }

    Buffer positions;
    Buffer inv_masses;
    Buffer starts;
    Buffer counts;
    Buffer neighbors;
    Buffer rest_lengths;
    Buffer stiffness_values;
    Buffer velocity_positions;

    if (!positions.get(PyTuple_GET_ITEM(args, 0), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !inv_masses.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !starts.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "starts") ||
        !counts.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "counts") ||
        !neighbors.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "neighbors") ||
        !rest_lengths.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "rest_lengths") ||
        !stiffness_values.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "stiffness_values") ||
        !velocity_positions.get(PyTuple_GET_ITEM(args, 7), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "velocity_positions")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(velocity_positions, "velocity_positions", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_int32_scalar_array(starts, "starts") ||
        !expect_1d_array(starts, "starts", vertex_count) ||
        !expect_int32_scalar_array(counts, "counts") ||
        !expect_1d_array(counts, "counts", vertex_count) ||
        !expect_int32_scalar_array(neighbors, "neighbors") ||
        !expect_indices_in_range(neighbors, "neighbors", vertex_count) ||
        !expect_float32(rest_lengths, "rest_lengths") ||
        !expect_1d_array(rest_lengths, "rest_lengths", neighbors.view.shape[0]) ||
        !expect_float32(stiffness_values, "stiffness_values") ||
        !expect_1d_array(stiffness_values, "stiffness_values", vertex_count)) {
        return nullptr;
    }
    const double velocity_attenuation = as_double(PyTuple_GET_ITEM(args, 8), "velocity_attenuation");
    if (PyErr_Occurred()) {
        return nullptr;
    }

    hotools::Mc2NeighborConstraintView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.starts = static_cast<const std::int32_t*>(starts.view.buf);
    view.counts = static_cast<const std::int32_t*>(counts.view.buf);
    view.neighbors = static_cast<const std::int32_t*>(neighbors.view.buf);
    view.rest_lengths = static_cast<const float*>(rest_lengths.view.buf);
    view.stiffness_values = static_cast<const float*>(stiffness_values.view.buf);
    view.velocity_positions = static_cast<float*>(velocity_positions.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.neighbor_count = static_cast<std::int64_t>(neighbors.view.shape[0]);
    view.velocity_attenuation = static_cast<float>(velocity_attenuation);

    hotools::project_neighbor_constraints_mc2(view);
    Py_RETURN_NONE;
}

PyObject* project_tether_mc2(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 8;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "project_tether_mc2 expects %zd arguments", kArgCount);
        return nullptr;
    }

    Buffer positions;
    Buffer inv_masses;
    Buffer root_indices;
    Buffer root_rest_lengths;
    Buffer velocity_positions;

    if (!positions.get(PyTuple_GET_ITEM(args, 0), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !inv_masses.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !root_indices.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "root_indices") ||
        !root_rest_lengths.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "root_rest_lengths") ||
        !velocity_positions.get(PyTuple_GET_ITEM(args, 4), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "velocity_positions")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(velocity_positions, "velocity_positions", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_int32_scalar_array(root_indices, "root_indices") ||
        !expect_1d_array(root_indices, "root_indices", vertex_count) ||
        !expect_root_indices_or_minus_one(root_indices, "root_indices", vertex_count) ||
        !expect_float32(root_rest_lengths, "root_rest_lengths") ||
        !expect_1d_array(root_rest_lengths, "root_rest_lengths", vertex_count)) {
        return nullptr;
    }

    const double stiffness = as_double(PyTuple_GET_ITEM(args, 5), "stiffness");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double compression = as_double(PyTuple_GET_ITEM(args, 6), "compression");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double stretch = as_double(PyTuple_GET_ITEM(args, 7), "stretch");
    if (PyErr_Occurred()) {
        return nullptr;
    }

    hotools::Mc2TetherConstraintView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.root_indices = static_cast<const std::int32_t*>(root_indices.view.buf);
    view.root_rest_lengths = static_cast<const float*>(root_rest_lengths.view.buf);
    view.velocity_positions = static_cast<float*>(velocity_positions.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.stiffness = static_cast<float>(stiffness);
    view.compression = static_cast<float>(compression);
    view.stretch = static_cast<float>(stretch);

    hotools::project_tether_mc2(view);
    Py_RETURN_NONE;
}

PyObject* project_motion_constraints_mc2(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 10;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "project_motion_constraints_mc2 expects %zd arguments", kArgCount);
        return nullptr;
    }

    Buffer positions;
    Buffer base_positions;
    Buffer base_rotations;
    Buffer inv_masses;
    Buffer max_distances;
    Buffer stiffness_values;
    Buffer backstop_radii;
    Buffer backstop_distances;
    Buffer velocity_positions;

    if (!positions.get(PyTuple_GET_ITEM(args, 0), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !base_positions.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "base_positions") ||
        !base_rotations.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "base_rotations") ||
        !inv_masses.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !max_distances.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "max_distances") ||
        !stiffness_values.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "stiffness_values") ||
        !backstop_radii.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "backstop_radii") ||
        !backstop_distances.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "backstop_distances") ||
        !velocity_positions.get(PyTuple_GET_ITEM(args, 8), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "velocity_positions")) {
        return nullptr;
    }
    const long normal_axis = as_long(PyTuple_GET_ITEM(args, 9), "normal_axis");
    if (PyErr_Occurred()) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(base_positions, "base_positions", vertex_count) ||
        !expect_same_quat_vertex_count(base_rotations, "base_rotations", vertex_count) ||
        !expect_same_vertex_count(velocity_positions, "velocity_positions", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_float32(max_distances, "max_distances") ||
        !expect_1d_array(max_distances, "max_distances", vertex_count) ||
        !expect_float32(stiffness_values, "stiffness_values") ||
        !expect_1d_array(stiffness_values, "stiffness_values", vertex_count) ||
        !expect_float32(backstop_radii, "backstop_radii") ||
        !expect_1d_array(backstop_radii, "backstop_radii", vertex_count) ||
        !expect_float32(backstop_distances, "backstop_distances") ||
        !expect_1d_array(backstop_distances, "backstop_distances", vertex_count)) {
        return nullptr;
    }

    hotools::Mc2MotionConstraintView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.base_positions = static_cast<const float*>(base_positions.view.buf);
    view.base_rotations = static_cast<const float*>(base_rotations.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.max_distances = static_cast<const float*>(max_distances.view.buf);
    view.stiffness_values = static_cast<const float*>(stiffness_values.view.buf);
    view.backstop_radii = static_cast<const float*>(backstop_radii.view.buf);
    view.backstop_distances = static_cast<const float*>(backstop_distances.view.buf);
    view.velocity_positions = static_cast<float*>(velocity_positions.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.normal_axis = std::max(0, std::min(5, static_cast<int>(normal_axis)));

    hotools::project_motion_constraints_mc2(view);
    Py_RETURN_NONE;
}

PyObject* apply_post_step_mc2(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 13;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "apply_post_step_mc2 expects %zd arguments", kArgCount);
        return nullptr;
    }

    Buffer positions;
    Buffer old_positions;
    Buffer velocity_positions;
    Buffer velocities;
    Buffer real_velocities;
    Buffer friction;
    Buffer static_friction;
    Buffer collision_normals;
    Buffer inv_masses;

    if (!positions.get(PyTuple_GET_ITEM(args, 0), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !old_positions.get(PyTuple_GET_ITEM(args, 1), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "old_positions") ||
        !velocity_positions.get(PyTuple_GET_ITEM(args, 2), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "velocity_positions") ||
        !velocities.get(PyTuple_GET_ITEM(args, 3), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "velocities") ||
        !real_velocities.get(PyTuple_GET_ITEM(args, 4), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "real_velocities") ||
        !friction.get(PyTuple_GET_ITEM(args, 5), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "friction") ||
        !static_friction.get(PyTuple_GET_ITEM(args, 6), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "static_friction") ||
        !collision_normals.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "collision_normals") ||
        !inv_masses.get(PyTuple_GET_ITEM(args, 8), PyBUF_FORMAT | PyBUF_ND, "inv_masses")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(old_positions, "old_positions", vertex_count) ||
        !expect_same_vertex_count(velocity_positions, "velocity_positions", vertex_count) ||
        !expect_same_vertex_count(velocities, "velocities", vertex_count) ||
        !expect_same_vertex_count(real_velocities, "real_velocities", vertex_count) ||
        !expect_same_vertex_count(collision_normals, "collision_normals", vertex_count) ||
        !expect_float32(friction, "friction") ||
        !expect_1d_array(friction, "friction", vertex_count) ||
        !expect_float32(static_friction, "static_friction") ||
        !expect_1d_array(static_friction, "static_friction", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count)) {
        return nullptr;
    }

    const double step_dt = as_double(PyTuple_GET_ITEM(args, 9), "step_dt");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double dynamic_friction = as_double(PyTuple_GET_ITEM(args, 10), "dynamic_friction");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double static_friction_speed = as_double(PyTuple_GET_ITEM(args, 11), "static_friction_speed");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double particle_speed_limit = as_double(PyTuple_GET_ITEM(args, 12), "particle_speed_limit");
    if (PyErr_Occurred()) {
        return nullptr;
    }

    hotools::Mc2PostStepView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.old_positions = static_cast<float*>(old_positions.view.buf);
    view.velocity_positions = static_cast<float*>(velocity_positions.view.buf);
    view.velocities = static_cast<float*>(velocities.view.buf);
    view.real_velocities = static_cast<float*>(real_velocities.view.buf);
    view.friction = static_cast<float*>(friction.view.buf);
    view.static_friction = static_cast<float*>(static_friction.view.buf);
    view.collision_normals = static_cast<const float*>(collision_normals.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.step_dt = static_cast<float>(step_dt);
    view.dynamic_friction = static_cast<float>(dynamic_friction);
    view.static_friction_speed = static_cast<float>(static_friction_speed);
    view.particle_speed_limit = static_cast<float>(particle_speed_limit);

    hotools::apply_post_step_mc2(view);
    Py_RETURN_NONE;
}

PyObject* project_collisions_mc2(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 16;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "project_collisions_mc2 expects %zd arguments", kArgCount);
        return nullptr;
    }

    Buffer positions;
    Buffer base_positions;
    Buffer inv_masses;
    Buffer collision_radii;
    Buffer collision_normals;
    Buffer friction;
    Buffer collider_types;
    Buffer collider_group_bits;
    Buffer collider_centers;
    Buffer collider_segment_a;
    Buffer collider_segment_b;
    Buffer collider_old_centers;
    Buffer collider_old_segment_a;
    Buffer collider_old_segment_b;
    Buffer collider_radii;

    if (!positions.get(PyTuple_GET_ITEM(args, 0), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !base_positions.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "base_positions") ||
        !inv_masses.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !collision_radii.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "collision_radii") ||
        !collision_normals.get(PyTuple_GET_ITEM(args, 4), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "collision_normals") ||
        !friction.get(PyTuple_GET_ITEM(args, 5), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "friction") ||
        !collider_types.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "collider_types") ||
        !collider_group_bits.get(PyTuple_GET_ITEM(args, 8), PyBUF_FORMAT | PyBUF_ND, "collider_group_bits") ||
        !collider_centers.get(PyTuple_GET_ITEM(args, 9), PyBUF_FORMAT | PyBUF_ND, "collider_centers") ||
        !collider_segment_a.get(PyTuple_GET_ITEM(args, 10), PyBUF_FORMAT | PyBUF_ND, "collider_segment_a") ||
        !collider_segment_b.get(PyTuple_GET_ITEM(args, 11), PyBUF_FORMAT | PyBUF_ND, "collider_segment_b")) {
        return nullptr;
    }
    if (!collider_old_centers.get(PyTuple_GET_ITEM(args, 12), PyBUF_FORMAT | PyBUF_ND, "collider_old_centers") ||
        !collider_old_segment_a.get(PyTuple_GET_ITEM(args, 13), PyBUF_FORMAT | PyBUF_ND, "collider_old_segment_a") ||
        !collider_old_segment_b.get(PyTuple_GET_ITEM(args, 14), PyBUF_FORMAT | PyBUF_ND, "collider_old_segment_b") ||
        !collider_radii.get(PyTuple_GET_ITEM(args, 15), PyBUF_FORMAT | PyBUF_ND, "collider_radii")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(base_positions, "base_positions", vertex_count) ||
        !expect_same_vertex_count(collision_normals, "collision_normals", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_float32(collision_radii, "collision_radii") ||
        !expect_1d_array(collision_radii, "collision_radii", vertex_count) ||
        !expect_float32(friction, "friction") ||
        !expect_1d_array(friction, "friction", vertex_count) ||
        !expect_int32_scalar_array(collider_types, "collider_types") ||
        !expect_int32_scalar_array(collider_group_bits, "collider_group_bits") ||
        !expect_float32(collider_radii, "collider_radii")) {
        return nullptr;
    }

    const long collided_by_groups = as_long(PyTuple_GET_ITEM(args, 6), "collided_by_groups");
    if (PyErr_Occurred()) {
        return nullptr;
    }

    const Py_ssize_t collider_count = collider_types.view.shape[0];
    Py_ssize_t collider_centers_count = 0;
    Py_ssize_t collider_segment_a_count = 0;
    Py_ssize_t collider_segment_b_count = 0;
    Py_ssize_t collider_old_centers_count = collider_count;
    Py_ssize_t collider_old_segment_a_count = collider_count;
    Py_ssize_t collider_old_segment_b_count = collider_count;
    if (!expect_1d_array(collider_group_bits, "collider_group_bits", collider_count) ||
        !expect_1d_array(collider_radii, "collider_radii", collider_count) ||
        !expect_vector3_array(collider_centers, "collider_centers", &collider_centers_count) ||
        !expect_vector3_array(collider_segment_a, "collider_segment_a", &collider_segment_a_count) ||
        !expect_vector3_array(collider_segment_b, "collider_segment_b", &collider_segment_b_count)) {
        return nullptr;
    }
    if (!expect_vector3_array(collider_old_centers, "collider_old_centers", &collider_old_centers_count) ||
        !expect_vector3_array(collider_old_segment_a, "collider_old_segment_a", &collider_old_segment_a_count) ||
        !expect_vector3_array(collider_old_segment_b, "collider_old_segment_b", &collider_old_segment_b_count)) {
        return nullptr;
    }
    if (collider_centers_count != collider_count || collider_segment_a_count != collider_count ||
        collider_segment_b_count != collider_count || collider_old_centers_count != collider_count ||
        collider_old_segment_a_count != collider_count || collider_old_segment_b_count != collider_count) {
        PyErr_SetString(PyExc_ValueError, "collider array length mismatch");
        return nullptr;
    }

    hotools::Mc2CollisionView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.base_positions = static_cast<const float*>(base_positions.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.collision_radii = static_cast<const float*>(collision_radii.view.buf);
    view.collision_normals = static_cast<float*>(collision_normals.view.buf);
    view.friction = static_cast<float*>(friction.view.buf);
    view.collider_types = static_cast<const std::int32_t*>(collider_types.view.buf);
    view.collider_group_bits = static_cast<const std::int32_t*>(collider_group_bits.view.buf);
    view.collider_centers = static_cast<const float*>(collider_centers.view.buf);
    view.collider_segment_a = static_cast<const float*>(collider_segment_a.view.buf);
    view.collider_segment_b = static_cast<const float*>(collider_segment_b.view.buf);
    view.collider_old_centers = static_cast<const float*>(collider_old_centers.view.buf);
    view.collider_old_segment_a = static_cast<const float*>(collider_old_segment_a.view.buf);
    view.collider_old_segment_b = static_cast<const float*>(collider_old_segment_b.view.buf);
    view.collider_radii = static_cast<const float*>(collider_radii.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.collider_count = static_cast<std::int64_t>(collider_count);
    view.collided_by_groups = static_cast<std::int32_t>(collided_by_groups);

    hotools::project_collisions_mc2(view);
    Py_RETURN_NONE;
}

PyObject* project_edge_collisions_mc2(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 17;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "project_edge_collisions_mc2 expects %zd arguments", kArgCount);
        return nullptr;
    }

    Buffer positions;
    Buffer edges;
    Buffer attributes;
    Buffer inv_masses;
    Buffer collision_radii;
    Buffer collision_normals;
    Buffer friction;
    Buffer collider_types;
    Buffer collider_group_bits;
    Buffer collider_centers;
    Buffer collider_segment_a;
    Buffer collider_segment_b;
    Buffer collider_old_centers;
    Buffer collider_old_segment_a;
    Buffer collider_old_segment_b;
    Buffer collider_radii;

    if (!positions.get(PyTuple_GET_ITEM(args, 0), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !edges.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "edges") ||
        !attributes.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "attributes") ||
        !inv_masses.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !collision_radii.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "collision_radii") ||
        !collision_normals.get(PyTuple_GET_ITEM(args, 5), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND,
                               "collision_normals") ||
        !friction.get(PyTuple_GET_ITEM(args, 6), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "friction") ||
        !collider_types.get(PyTuple_GET_ITEM(args, 8), PyBUF_FORMAT | PyBUF_ND, "collider_types") ||
        !collider_group_bits.get(PyTuple_GET_ITEM(args, 9), PyBUF_FORMAT | PyBUF_ND, "collider_group_bits") ||
        !collider_centers.get(PyTuple_GET_ITEM(args, 10), PyBUF_FORMAT | PyBUF_ND, "collider_centers") ||
        !collider_segment_a.get(PyTuple_GET_ITEM(args, 11), PyBUF_FORMAT | PyBUF_ND, "collider_segment_a") ||
        !collider_segment_b.get(PyTuple_GET_ITEM(args, 12), PyBUF_FORMAT | PyBUF_ND, "collider_segment_b") ||
        !collider_old_centers.get(PyTuple_GET_ITEM(args, 13), PyBUF_FORMAT | PyBUF_ND,
                                  "collider_old_centers") ||
        !collider_old_segment_a.get(PyTuple_GET_ITEM(args, 14), PyBUF_FORMAT | PyBUF_ND,
                                    "collider_old_segment_a") ||
        !collider_old_segment_b.get(PyTuple_GET_ITEM(args, 15), PyBUF_FORMAT | PyBUF_ND,
                                    "collider_old_segment_b") ||
        !collider_radii.get(PyTuple_GET_ITEM(args, 16), PyBUF_FORMAT | PyBUF_ND, "collider_radii")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    Py_ssize_t edge_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_int32_pair_array(edges, "edges", &edge_count) ||
        !expect_pair_indices_in_range(edges, "edges", vertex_count) ||
        !expect_uint8_scalar_array(attributes, "attributes") ||
        !expect_1d_array(attributes, "attributes", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_float32(collision_radii, "collision_radii") ||
        !expect_1d_array(collision_radii, "collision_radii", vertex_count) ||
        !expect_same_vertex_count(collision_normals, "collision_normals", vertex_count) ||
        !expect_float32(friction, "friction") ||
        !expect_1d_array(friction, "friction", vertex_count) ||
        !expect_int32_scalar_array(collider_types, "collider_types") ||
        !expect_int32_scalar_array(collider_group_bits, "collider_group_bits") ||
        !expect_float32(collider_radii, "collider_radii")) {
        return nullptr;
    }

    const long collided_by_groups = as_long(PyTuple_GET_ITEM(args, 7), "collided_by_groups");
    if (PyErr_Occurred()) {
        return nullptr;
    }

    const Py_ssize_t collider_count = collider_types.view.shape[0];
    Py_ssize_t collider_centers_count = 0;
    Py_ssize_t collider_segment_a_count = 0;
    Py_ssize_t collider_segment_b_count = 0;
    Py_ssize_t collider_old_centers_count = 0;
    Py_ssize_t collider_old_segment_a_count = 0;
    Py_ssize_t collider_old_segment_b_count = 0;
    if (!expect_1d_array(collider_group_bits, "collider_group_bits", collider_count) ||
        !expect_1d_array(collider_radii, "collider_radii", collider_count) ||
        !expect_vector3_array(collider_centers, "collider_centers", &collider_centers_count) ||
        !expect_vector3_array(collider_segment_a, "collider_segment_a", &collider_segment_a_count) ||
        !expect_vector3_array(collider_segment_b, "collider_segment_b", &collider_segment_b_count) ||
        !expect_vector3_array(collider_old_centers, "collider_old_centers", &collider_old_centers_count) ||
        !expect_vector3_array(collider_old_segment_a, "collider_old_segment_a", &collider_old_segment_a_count) ||
        !expect_vector3_array(collider_old_segment_b, "collider_old_segment_b", &collider_old_segment_b_count)) {
        return nullptr;
    }
    if (collider_centers_count != collider_count || collider_segment_a_count != collider_count ||
        collider_segment_b_count != collider_count || collider_old_centers_count != collider_count ||
        collider_old_segment_a_count != collider_count || collider_old_segment_b_count != collider_count) {
        PyErr_SetString(PyExc_ValueError, "collider array length mismatch");
        return nullptr;
    }

    hotools::Mc2EdgeCollisionView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.edges = static_cast<const std::int32_t*>(edges.view.buf);
    view.attributes = static_cast<const std::uint8_t*>(attributes.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.collision_radii = static_cast<const float*>(collision_radii.view.buf);
    view.collision_normals = static_cast<float*>(collision_normals.view.buf);
    view.friction = static_cast<float*>(friction.view.buf);
    view.collider_types = static_cast<const std::int32_t*>(collider_types.view.buf);
    view.collider_group_bits = static_cast<const std::int32_t*>(collider_group_bits.view.buf);
    view.collider_centers = static_cast<const float*>(collider_centers.view.buf);
    view.collider_segment_a = static_cast<const float*>(collider_segment_a.view.buf);
    view.collider_segment_b = static_cast<const float*>(collider_segment_b.view.buf);
    view.collider_old_centers = static_cast<const float*>(collider_old_centers.view.buf);
    view.collider_old_segment_a = static_cast<const float*>(collider_old_segment_a.view.buf);
    view.collider_old_segment_b = static_cast<const float*>(collider_old_segment_b.view.buf);
    view.collider_radii = static_cast<const float*>(collider_radii.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.edge_count = static_cast<std::int64_t>(edge_count);
    view.collider_count = static_cast<std::int64_t>(collider_count);
    view.collided_by_groups = static_cast<std::int32_t>(collided_by_groups);

    hotools::project_edge_collisions_mc2(view);
    Py_RETURN_NONE;
}

PyObject* project_triangle_bending_mc2(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 8;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "project_triangle_bending_mc2 expects %zd arguments", kArgCount);
        return nullptr;
    }

    Buffer positions;
    Buffer inv_masses;
    Buffer dihedral_pairs;
    Buffer dihedral_rest_angles;
    Buffer dihedral_signs;
    Buffer volume_pairs;
    Buffer volume_rest;
    Buffer stiffness_values;

    if (!positions.get(PyTuple_GET_ITEM(args, 0), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !inv_masses.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !dihedral_pairs.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "dihedral_pairs") ||
        !dihedral_rest_angles.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "dihedral_rest_angles") ||
        !dihedral_signs.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "dihedral_signs") ||
        !volume_pairs.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "volume_pairs") ||
        !volume_rest.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "volume_rest") ||
        !stiffness_values.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "stiffness_values")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    Py_ssize_t dihedral_count = 0;
    Py_ssize_t volume_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_int32_quad_array(dihedral_pairs, "dihedral_pairs", &dihedral_count) ||
        !expect_float32(dihedral_rest_angles, "dihedral_rest_angles") ||
        !expect_1d_array(dihedral_rest_angles, "dihedral_rest_angles", dihedral_count) ||
        !expect_int32_scalar_array(dihedral_signs, "dihedral_signs") ||
        !expect_1d_array(dihedral_signs, "dihedral_signs", dihedral_count) ||
        !expect_int32_quad_array(volume_pairs, "volume_pairs", &volume_count) ||
        !expect_float32(volume_rest, "volume_rest") ||
        !expect_1d_array(volume_rest, "volume_rest", volume_count) ||
        !expect_float32(stiffness_values, "stiffness_values") ||
        !expect_1d_array(stiffness_values, "stiffness_values", vertex_count)) {
        return nullptr;
    }
    if ((dihedral_count > 0 && !expect_quad_indices_in_range(dihedral_pairs, "dihedral_pairs", vertex_count)) ||
        (volume_count > 0 && !expect_quad_indices_in_range(volume_pairs, "volume_pairs", vertex_count))) {
        return nullptr;
    }

    hotools::Mc2TriangleBendingView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.dihedral_pairs = static_cast<const std::int32_t*>(dihedral_pairs.view.buf);
    view.dihedral_rest_angles = static_cast<const float*>(dihedral_rest_angles.view.buf);
    view.dihedral_signs = static_cast<const std::int32_t*>(dihedral_signs.view.buf);
    view.volume_pairs = static_cast<const std::int32_t*>(volume_pairs.view.buf);
    view.volume_rest = static_cast<const float*>(volume_rest.view.buf);
    view.stiffness_values = static_cast<const float*>(stiffness_values.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.dihedral_count = static_cast<std::int64_t>(dihedral_count);
    view.volume_count = static_cast<std::int64_t>(volume_count);

    hotools::project_triangle_bending_mc2(view);
    Py_RETURN_NONE;
}

PyObject* project_angle_constraints_mc2(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 14;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "project_angle_constraints_mc2 expects %zd arguments", kArgCount);
        return nullptr;
    }

    Buffer positions;
    Buffer inv_masses;
    Buffer parent_indices;
    Buffer baseline_start;
    Buffer baseline_count;
    Buffer baseline_data;
    Buffer step_basic_positions;
    Buffer step_basic_rotations;
    Buffer restoration_values;
    Buffer limit_values;
    Buffer velocity_positions;

    if (!positions.get(PyTuple_GET_ITEM(args, 0), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !inv_masses.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !parent_indices.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "parent_indices") ||
        !baseline_start.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "baseline_start") ||
        !baseline_count.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "baseline_count") ||
        !baseline_data.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "baseline_data") ||
        !step_basic_positions.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "step_basic_positions") ||
        !step_basic_rotations.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "step_basic_rotations") ||
        !restoration_values.get(PyTuple_GET_ITEM(args, 8), PyBUF_FORMAT | PyBUF_ND, "restoration_values") ||
        !limit_values.get(PyTuple_GET_ITEM(args, 9), PyBUF_FORMAT | PyBUF_ND, "limit_values") ||
        !velocity_positions.get(PyTuple_GET_ITEM(args, 10), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "velocity_positions")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(step_basic_positions, "step_basic_positions", vertex_count) ||
        !expect_same_vertex_count(velocity_positions, "velocity_positions", vertex_count) ||
        !expect_same_quat_vertex_count(step_basic_rotations, "step_basic_rotations", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_int32_scalar_array(parent_indices, "parent_indices") ||
        !expect_1d_array(parent_indices, "parent_indices", vertex_count) ||
        !expect_root_indices_or_minus_one(parent_indices, "parent_indices", vertex_count) ||
        !expect_int32_scalar_array(baseline_start, "baseline_start") ||
        !expect_int32_scalar_array(baseline_count, "baseline_count") ||
        !expect_int32_scalar_array(baseline_data, "baseline_data") ||
        !expect_indices_in_range(baseline_data, "baseline_data", vertex_count) ||
        !expect_float32(restoration_values, "restoration_values") ||
        !expect_1d_array(restoration_values, "restoration_values", vertex_count) ||
        !expect_float32(limit_values, "limit_values") ||
        !expect_1d_array(limit_values, "limit_values", vertex_count)) {
        return nullptr;
    }
    const Py_ssize_t line_count = baseline_start.view.shape[0];
    if (!expect_1d_array(baseline_count, "baseline_count", line_count)) {
        return nullptr;
    }

    const double restoration_velocity_attenuation =
        as_double(PyTuple_GET_ITEM(args, 11), "restoration_velocity_attenuation");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double restoration_gravity_falloff = as_double(PyTuple_GET_ITEM(args, 12), "restoration_gravity_falloff");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double limit_stiffness = as_double(PyTuple_GET_ITEM(args, 13), "limit_stiffness");
    if (PyErr_Occurred()) {
        return nullptr;
    }

    hotools::Mc2AngleConstraintView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.parent_indices = static_cast<const std::int32_t*>(parent_indices.view.buf);
    view.baseline_start = static_cast<const std::int32_t*>(baseline_start.view.buf);
    view.baseline_count = static_cast<const std::int32_t*>(baseline_count.view.buf);
    view.baseline_data = static_cast<const std::int32_t*>(baseline_data.view.buf);
    view.step_basic_positions = static_cast<const float*>(step_basic_positions.view.buf);
    view.step_basic_rotations = static_cast<const float*>(step_basic_rotations.view.buf);
    view.restoration_values = static_cast<const float*>(restoration_values.view.buf);
    view.limit_values = static_cast<const float*>(limit_values.view.buf);
    view.velocity_positions = static_cast<float*>(velocity_positions.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.line_count = static_cast<std::int64_t>(line_count);
    view.baseline_data_count = static_cast<std::int64_t>(baseline_data.view.shape[0]);
    view.restoration_velocity_attenuation = static_cast<float>(restoration_velocity_attenuation);
    view.restoration_gravity_falloff = static_cast<float>(restoration_gravity_falloff);
    view.limit_stiffness = static_cast<float>(limit_stiffness);

    hotools::project_angle_constraints_mc2(view);
    Py_RETURN_NONE;
}

PyObject* update_step_basic_pose_mc2(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 11;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "update_step_basic_pose_mc2 expects %zd arguments", kArgCount);
        return nullptr;
    }

    Buffer base_positions;
    Buffer base_rotations;
    Buffer parent_indices;
    Buffer baseline_start;
    Buffer baseline_count;
    Buffer baseline_data;
    Buffer vertex_local_positions;
    Buffer vertex_local_rotations;
    Buffer step_positions;
    Buffer step_rotations;

    if (!base_positions.get(PyTuple_GET_ITEM(args, 0), PyBUF_FORMAT | PyBUF_ND, "base_positions") ||
        !base_rotations.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "base_rotations") ||
        !parent_indices.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "parent_indices") ||
        !baseline_start.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "baseline_start") ||
        !baseline_count.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "baseline_count") ||
        !baseline_data.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "baseline_data") ||
        !vertex_local_positions.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "vertex_local_positions") ||
        !vertex_local_rotations.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "vertex_local_rotations") ||
        !step_positions.get(PyTuple_GET_ITEM(args, 8), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "step_positions") ||
        !step_rotations.get(PyTuple_GET_ITEM(args, 9), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "step_rotations")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(base_positions, "base_positions", &vertex_count) ||
        !expect_same_quat_vertex_count(base_rotations, "base_rotations", vertex_count) ||
        !expect_same_vertex_count(vertex_local_positions, "vertex_local_positions", vertex_count) ||
        !expect_same_quat_vertex_count(vertex_local_rotations, "vertex_local_rotations", vertex_count) ||
        !expect_same_vertex_count(step_positions, "step_positions", vertex_count) ||
        !expect_same_quat_vertex_count(step_rotations, "step_rotations", vertex_count) ||
        !expect_int32_scalar_array(parent_indices, "parent_indices") ||
        !expect_1d_array(parent_indices, "parent_indices", vertex_count) ||
        !expect_root_indices_or_minus_one(parent_indices, "parent_indices", vertex_count) ||
        !expect_int32_scalar_array(baseline_start, "baseline_start") ||
        !expect_int32_scalar_array(baseline_count, "baseline_count") ||
        !expect_int32_scalar_array(baseline_data, "baseline_data") ||
        !expect_indices_in_range(baseline_data, "baseline_data", vertex_count)) {
        return nullptr;
    }
    const Py_ssize_t line_count = baseline_start.view.shape[0];
    if (!expect_1d_array(baseline_count, "baseline_count", line_count)) {
        return nullptr;
    }

    const double animation_pose_ratio = as_double(PyTuple_GET_ITEM(args, 10), "animation_pose_ratio");
    if (PyErr_Occurred()) {
        return nullptr;
    }

    hotools::Mc2StepBasicPoseView view;
    view.base_positions = static_cast<const float*>(base_positions.view.buf);
    view.base_rotations = static_cast<const float*>(base_rotations.view.buf);
    view.parent_indices = static_cast<const std::int32_t*>(parent_indices.view.buf);
    view.baseline_start = static_cast<const std::int32_t*>(baseline_start.view.buf);
    view.baseline_count = static_cast<const std::int32_t*>(baseline_count.view.buf);
    view.baseline_data = static_cast<const std::int32_t*>(baseline_data.view.buf);
    view.vertex_local_positions = static_cast<const float*>(vertex_local_positions.view.buf);
    view.vertex_local_rotations = static_cast<const float*>(vertex_local_rotations.view.buf);
    view.step_positions = static_cast<float*>(step_positions.view.buf);
    view.step_rotations = static_cast<float*>(step_rotations.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.line_count = static_cast<std::int64_t>(line_count);
    view.baseline_data_count = static_cast<std::int64_t>(baseline_data.view.shape[0]);
    view.animation_pose_ratio = static_cast<float>(animation_pose_ratio);

    hotools::update_step_basic_pose_mc2(view);
    Py_RETURN_NONE;
}

PyObject* update_base_pose_from_pose_mc2(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 12;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "update_base_pose_from_pose_mc2 expects %zd arguments", kArgCount);
        return nullptr;
    }

    Buffer base_positions;
    Buffer base_normals;
    Buffer parent_indices;
    Buffer baseline_start;
    Buffer baseline_count;
    Buffer baseline_data;
    Buffer vertex_local_positions;
    Buffer vertex_local_rotations;
    Buffer base_rotations;
    Buffer step_positions;
    Buffer step_rotations;

    if (!base_positions.get(PyTuple_GET_ITEM(args, 0), PyBUF_FORMAT | PyBUF_ND, "base_positions") ||
        !base_normals.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "base_normals") ||
        !parent_indices.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "parent_indices") ||
        !baseline_start.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "baseline_start") ||
        !baseline_count.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "baseline_count") ||
        !baseline_data.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "baseline_data") ||
        !vertex_local_positions.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "vertex_local_positions") ||
        !vertex_local_rotations.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "vertex_local_rotations") ||
        !base_rotations.get(PyTuple_GET_ITEM(args, 8), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "base_rotations") ||
        !step_positions.get(PyTuple_GET_ITEM(args, 9), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "step_positions") ||
        !step_rotations.get(PyTuple_GET_ITEM(args, 10), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "step_rotations")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(base_positions, "base_positions", &vertex_count) ||
        !expect_same_vertex_count(base_normals, "base_normals", vertex_count) ||
        !expect_same_vertex_count(vertex_local_positions, "vertex_local_positions", vertex_count) ||
        !expect_same_quat_vertex_count(vertex_local_rotations, "vertex_local_rotations", vertex_count) ||
        !expect_same_quat_vertex_count(base_rotations, "base_rotations", vertex_count) ||
        !expect_same_vertex_count(step_positions, "step_positions", vertex_count) ||
        !expect_same_quat_vertex_count(step_rotations, "step_rotations", vertex_count) ||
        !expect_int32_scalar_array(parent_indices, "parent_indices") ||
        !expect_1d_array(parent_indices, "parent_indices", vertex_count) ||
        !expect_root_indices_or_minus_one(parent_indices, "parent_indices", vertex_count) ||
        !expect_int32_scalar_array(baseline_start, "baseline_start") ||
        !expect_int32_scalar_array(baseline_count, "baseline_count") ||
        !expect_int32_scalar_array(baseline_data, "baseline_data") ||
        !expect_indices_in_range(baseline_data, "baseline_data", vertex_count)) {
        return nullptr;
    }
    const Py_ssize_t line_count = baseline_start.view.shape[0];
    if (!expect_1d_array(baseline_count, "baseline_count", line_count)) {
        return nullptr;
    }

    const double animation_pose_ratio = as_double(PyTuple_GET_ITEM(args, 11), "animation_pose_ratio");
    if (PyErr_Occurred()) {
        return nullptr;
    }

    hotools::Mc2BasePoseFromPoseView view;
    view.base_positions = static_cast<const float*>(base_positions.view.buf);
    view.base_normals = static_cast<const float*>(base_normals.view.buf);
    view.parent_indices = static_cast<const std::int32_t*>(parent_indices.view.buf);
    view.baseline_start = static_cast<const std::int32_t*>(baseline_start.view.buf);
    view.baseline_count = static_cast<const std::int32_t*>(baseline_count.view.buf);
    view.baseline_data = static_cast<const std::int32_t*>(baseline_data.view.buf);
    view.vertex_local_positions = static_cast<const float*>(vertex_local_positions.view.buf);
    view.vertex_local_rotations = static_cast<const float*>(vertex_local_rotations.view.buf);
    view.base_rotations = static_cast<float*>(base_rotations.view.buf);
    view.step_positions = static_cast<float*>(step_positions.view.buf);
    view.step_rotations = static_cast<float*>(step_rotations.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.line_count = static_cast<std::int64_t>(line_count);
    view.baseline_data_count = static_cast<std::int64_t>(baseline_data.view.shape[0]);
    view.animation_pose_ratio = static_cast<float>(animation_pose_ratio);

    hotools::update_base_pose_from_pose_mc2(view);
    Py_RETURN_NONE;
}

PyObject* apply_substep_inertia_mc2(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 10;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "apply_substep_inertia_mc2 expects %zd arguments", kArgCount);
        return nullptr;
    }

    Buffer old_positions;
    Buffer velocities;
    Buffer depths;
    Buffer inv_masses;
    Buffer old_world_position;
    Buffer step_vector;
    Buffer step_rotation;
    Buffer inertia_vector;
    Buffer inertia_rotation;

    if (!old_positions.get(PyTuple_GET_ITEM(args, 0), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "old_positions") ||
        !velocities.get(PyTuple_GET_ITEM(args, 1), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "velocities") ||
        !depths.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "depths") ||
        !inv_masses.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !old_world_position.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "old_world_position") ||
        !step_vector.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "step_vector") ||
        !step_rotation.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "step_rotation") ||
        !inertia_vector.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "inertia_vector") ||
        !inertia_rotation.get(PyTuple_GET_ITEM(args, 8), PyBUF_FORMAT | PyBUF_ND, "inertia_rotation")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(old_positions, "old_positions", &vertex_count) ||
        !expect_same_vertex_count(velocities, "velocities", vertex_count) ||
        !expect_float32(depths, "depths") ||
        !expect_1d_array(depths, "depths", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_float32(old_world_position, "old_world_position") ||
        !expect_1d_array(old_world_position, "old_world_position", 3) ||
        !expect_float32(step_vector, "step_vector") ||
        !expect_1d_array(step_vector, "step_vector", 3) ||
        !expect_float32(step_rotation, "step_rotation") ||
        !expect_1d_array(step_rotation, "step_rotation", 4) ||
        !expect_float32(inertia_vector, "inertia_vector") ||
        !expect_1d_array(inertia_vector, "inertia_vector", 3) ||
        !expect_float32(inertia_rotation, "inertia_rotation") ||
        !expect_1d_array(inertia_rotation, "inertia_rotation", 4)) {
        return nullptr;
    }

    const double depth_inertia = as_double(PyTuple_GET_ITEM(args, 9), "depth_inertia");
    if (PyErr_Occurred()) {
        return nullptr;
    }

    hotools::Mc2SubstepInertiaView view;
    view.old_positions = static_cast<float*>(old_positions.view.buf);
    view.velocities = static_cast<float*>(velocities.view.buf);
    view.depths = static_cast<const float*>(depths.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    const float* old_world_position_values = static_cast<const float*>(old_world_position.view.buf);
    const float* step_vector_values = static_cast<const float*>(step_vector.view.buf);
    const float* step_rotation_values = static_cast<const float*>(step_rotation.view.buf);
    const float* inertia_vector_values = static_cast<const float*>(inertia_vector.view.buf);
    const float* inertia_rotation_values = static_cast<const float*>(inertia_rotation.view.buf);
    for (int index = 0; index < 3; ++index) {
        view.old_world_position[index] = old_world_position_values[index];
        view.step_vector[index] = step_vector_values[index];
        view.inertia_vector[index] = inertia_vector_values[index];
    }
    for (int index = 0; index < 4; ++index) {
        view.step_rotation[index] = step_rotation_values[index];
        view.inertia_rotation[index] = inertia_rotation_values[index];
    }
    view.depth_inertia = static_cast<float>(depth_inertia);

    hotools::apply_substep_inertia_mc2(view);
    Py_RETURN_NONE;
}

PyObject* apply_centrifugal_velocity_mc2(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 8;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "apply_centrifugal_velocity_mc2 expects %zd arguments", kArgCount);
        return nullptr;
    }

    Buffer positions;
    Buffer velocities;
    Buffer depths;
    Buffer inv_masses;
    Buffer now_world_position;
    Buffer rotation_axis;

    if (!positions.get(PyTuple_GET_ITEM(args, 0), PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !velocities.get(PyTuple_GET_ITEM(args, 1), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "velocities") ||
        !depths.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "depths") ||
        !inv_masses.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !now_world_position.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "now_world_position") ||
        !rotation_axis.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "rotation_axis")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(velocities, "velocities", vertex_count) ||
        !expect_float32(depths, "depths") ||
        !expect_1d_array(depths, "depths", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_float32(now_world_position, "now_world_position") ||
        !expect_1d_array(now_world_position, "now_world_position", 3) ||
        !expect_float32(rotation_axis, "rotation_axis") ||
        !expect_1d_array(rotation_axis, "rotation_axis", 3)) {
        return nullptr;
    }

    const double angular_velocity = as_double(PyTuple_GET_ITEM(args, 6), "angular_velocity");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double centrifugal = as_double(PyTuple_GET_ITEM(args, 7), "centrifugal");
    if (PyErr_Occurred()) {
        return nullptr;
    }

    hotools::Mc2CentrifugalView view;
    view.positions = static_cast<const float*>(positions.view.buf);
    view.velocities = static_cast<float*>(velocities.view.buf);
    view.depths = static_cast<const float*>(depths.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    const float* now_world_position_values = static_cast<const float*>(now_world_position.view.buf);
    const float* rotation_axis_values = static_cast<const float*>(rotation_axis.view.buf);
    for (int index = 0; index < 3; ++index) {
        view.now_world_position[index] = now_world_position_values[index];
        view.rotation_axis[index] = rotation_axis_values[index];
    }
    view.angular_velocity = static_cast<float>(angular_velocity);
    view.centrifugal = static_cast<float>(centrifugal);

    hotools::apply_centrifugal_velocity_mc2(view);
    Py_RETURN_NONE;
}

PyObject* calculate_display_positions_mc2(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 6;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "calculate_display_positions_mc2 expects %zd arguments", kArgCount);
        return nullptr;
    }

    Buffer positions;
    Buffer real_velocities;
    Buffer root_indices;
    Buffer display_positions;

    if (!positions.get(PyTuple_GET_ITEM(args, 0), PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !real_velocities.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "real_velocities") ||
        !root_indices.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "root_indices") ||
        !display_positions.get(PyTuple_GET_ITEM(args, 3), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND,
                               "display_positions")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(real_velocities, "real_velocities", vertex_count) ||
        !expect_same_vertex_count(display_positions, "display_positions", vertex_count) ||
        !expect_int32_scalar_array(root_indices, "root_indices") ||
        !expect_1d_array(root_indices, "root_indices", vertex_count)) {
        return nullptr;
    }

    const double frame_dt = as_double(PyTuple_GET_ITEM(args, 4), "frame_dt");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double max_distance_ratio = as_double(PyTuple_GET_ITEM(args, 5), "max_distance_ratio");
    if (PyErr_Occurred()) {
        return nullptr;
    }

    hotools::Mc2DisplayPredictionView view;
    view.positions = static_cast<const float*>(positions.view.buf);
    view.real_velocities = static_cast<const float*>(real_velocities.view.buf);
    view.root_indices = static_cast<const std::int32_t*>(root_indices.view.buf);
    view.display_positions = static_cast<float*>(display_positions.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.frame_dt = static_cast<float>(frame_dt);
    view.max_distance_ratio = static_cast<float>(max_distance_ratio);

    hotools::calculate_display_positions_mc2(view);
    Py_RETURN_NONE;
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
    constexpr Py_ssize_t kArgCount = 89;
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
        PyErr_SetString(PyExc_ValueError, "collider array length mismatch");
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

    hotools::solve_meshcloth_mc2(view);
    Py_RETURN_NONE;
}

PyMethodDef kMethods[] = {
    {
        "compile_property_float_curve",
        hotools::compile_property_float_curve,
        METH_VARARGS,
        "Compile a float curve payload into a native capsule.",
    },
    {
        "compile_property_color_curve",
        hotools::compile_property_color_curve,
        METH_VARARGS,
        "Compile a color curve payload into a native capsule.",
    },
    {
        "sample_property_float_curve",
        hotools::sample_property_float_curve,
        METH_VARARGS,
        "Sample a native float curve or payload at one position.",
    },
    {
        "sample_property_color_curve",
        hotools::sample_property_color_curve,
        METH_VARARGS,
        "Sample a native color curve or payload at one position.",
    },
    {
        "sample_property_float_curve_many",
        hotools::sample_property_float_curve_many,
        METH_VARARGS,
        "Sample a native float curve or payload at evenly spaced positions.",
    },
    {
        "sample_property_color_curve_many",
        hotools::sample_property_color_curve_many,
        METH_VARARGS,
        "Sample a native color curve or payload at evenly spaced positions.",
    },
    {
        "sample_property_float_curve_positions",
        hotools::sample_property_float_curve_positions,
        METH_VARARGS,
        "Sample a native float curve or payload at explicit positions.",
    },
    {
        "sample_property_color_curve_positions",
        hotools::sample_property_color_curve_positions,
        METH_VARARGS,
        "Sample a native color curve or payload at explicit positions.",
    },
    {
        "solve_mesh_shape_key_xpbd",
        solve_mesh_shape_key_xpbd,
        METH_VARARGS,
        "Solve one mesh shape-key XPBD step in-place.",
    },
    {
        "project_neighbor_constraints_mc2",
        project_neighbor_constraints_mc2,
        METH_VARARGS,
        "Project MC2 neighbor constraints in-place.",
    },
    {
        "project_tether_mc2",
        project_tether_mc2,
        METH_VARARGS,
        "Project MC2 tether constraints in-place.",
    },
    {
        "project_motion_constraints_mc2",
        project_motion_constraints_mc2,
        METH_VARARGS,
        "Project MC2 motion constraints in-place.",
    },
    {
        "apply_post_step_mc2",
        apply_post_step_mc2,
        METH_VARARGS,
        "Apply MC2 post-step velocity and friction update in-place.",
    },
    {
        "project_collisions_mc2",
        project_collisions_mc2,
        METH_VARARGS,
        "Project MC2 point collisions in-place.",
    },
    {
        "project_edge_collisions_mc2",
        project_edge_collisions_mc2,
        METH_VARARGS,
        "Project MC2 edge collisions in-place.",
    },
    {
        "project_triangle_bending_mc2",
        project_triangle_bending_mc2,
        METH_VARARGS,
        "Project MC2 triangle bending constraints in-place.",
    },
    {
        "project_angle_constraints_mc2",
        project_angle_constraints_mc2,
        METH_VARARGS,
        "Project MC2 angle restoration and limit constraints in-place.",
    },
    {
        "update_step_basic_pose_mc2",
        update_step_basic_pose_mc2,
        METH_VARARGS,
        "Update MC2 step basic pose in-place.",
    },
    {
        "update_base_pose_from_pose_mc2",
        update_base_pose_from_pose_mc2,
        METH_VARARGS,
        "Update MC2 base rotations and step basic pose from BasePose positions/normals in-place.",
    },
    {
        "apply_substep_inertia_mc2",
        apply_substep_inertia_mc2,
        METH_VARARGS,
        "Apply MC2 substep inertia in-place.",
    },
    {
        "apply_centrifugal_velocity_mc2",
        apply_centrifugal_velocity_mc2,
        METH_VARARGS,
        "Apply MC2 centrifugal velocity in-place.",
    },
    {
        "calculate_display_positions_mc2",
        calculate_display_positions_mc2,
        METH_VARARGS,
        "Calculate MC2 display future prediction in-place.",
    },
    {
        "solve_meshcloth_mc2",
        solve_meshcloth_mc2,
        METH_VARARGS,
        "Solve one MC2 MeshCloth array frame in-place.",
    },
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef kModule = {
    PyModuleDef_HEAD_INIT,
    "hotools_native",
    "Native acceleration backend for HoTools.",
    -1,
    kMethods,
};

}  // namespace

PyMODINIT_FUNC PyInit_hotools_native() {
    return PyModule_Create(&kModule);
}
