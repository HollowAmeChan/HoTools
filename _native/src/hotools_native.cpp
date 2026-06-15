#include <Python.h>

#include "hotools_mesh_xpbd.hpp"

#include <cstdint>

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

PyMethodDef kMethods[] = {
    {
        "solve_mesh_shape_key_xpbd",
        solve_mesh_shape_key_xpbd,
        METH_VARARGS,
        "Solve one mesh shape-key XPBD step in-place.",
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
