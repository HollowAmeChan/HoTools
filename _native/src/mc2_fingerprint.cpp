#include "mc2_api.hpp"

#include "python_buffer_utils.hpp"

#include <cmath>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>

namespace hotools {
namespace {

using namespace py;

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

struct Mc2StaticFingerprintV0 {
    std::uint64_t first = 1469598103934665603ull;
    std::uint64_t second = 1099511628211ull;

    void append(const void* raw_data, std::size_t size) {
        const auto* data = static_cast<const std::uint8_t*>(raw_data);
        for (std::size_t index = 0; index < size; ++index) {
            first ^= static_cast<std::uint64_t>(data[index]);
            first *= 1099511628211ull;
            second ^= static_cast<std::uint64_t>(data[index] + 0x9du);
            second *= 14029467366897019727ull;
        }
        first ^= static_cast<std::uint64_t>(size);
        first *= 1099511628211ull;
        second ^= static_cast<std::uint64_t>(size << 1u);
        second *= 14029467366897019727ull;
    }

    void append_buffer(const char* label, const Buffer& buffer) {
        append(label, std::strlen(label));
        append(buffer.view.buf, static_cast<std::size_t>(buffer.view.len));
    }

    void append_text(const char* value) {
        append(value, std::strlen(value));
    }

    std::string encoded() const {
        char encoded[33] {};
        std::snprintf(
            encoded,
            sizeof(encoded),
            "%016llx%016llx",
            static_cast<unsigned long long>(first),
            static_cast<unsigned long long>(second)
        );
        return std::string(encoded, 32);
    }
};

PyObject* static_fingerprint_result(
    const Mc2StaticFingerprintV0& topology,
    const Mc2StaticFingerprintV0& geometry,
    const Mc2StaticFingerprintV0& surface
) {
    const std::string topology_value = topology.encoded();
    const std::string geometry_value = geometry.encoded();
    const std::string surface_value = surface.encoded();
    PyObject* result = PyDict_New();
    if (result == nullptr) return nullptr;
    if (!dict_string(result, "topology", topology_value.c_str()) ||
        !dict_string(result, "geometry", geometry_value.c_str()) ||
        !dict_string(result, "surface", surface_value.c_str())) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}

}  // namespace

PyObject* mc2_mesh_static_fingerprint_v0(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 14) {
        PyErr_Format(
            PyExc_TypeError,
            "mc2_mesh_static_fingerprint_v0 expects 14 arguments, got %zd",
            PyTuple_GET_SIZE(args)
        );
        return nullptr;
    }
    Buffer positions, normals, edges, triangles, loop_vertices, loop_uvs, pin_weights,
        radius_multipliers;
    if (!positions.get(PyTuple_GET_ITEM(args, 0), PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !normals.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "normals") ||
        !edges.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "edges") ||
        !triangles.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "triangles") ||
        !loop_vertices.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "loop_vertices") ||
        !loop_uvs.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "loop_uvs") ||
        !pin_weights.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "pin_weights") ||
        !radius_multipliers.get(
            PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "radius_multipliers"
        )) {
        return nullptr;
    }
    if (!expect_float32(positions, "positions") || positions.view.ndim != 1 ||
        positions.view.shape[0] % 3 != 0 || !finite_floats(positions, "positions") ||
        !expect_float32(normals, "normals") || normals.view.ndim != 1 ||
        normals.view.shape[0] != positions.view.shape[0] ||
        !finite_floats(normals, "normals") ||
        !expect_int32(edges, "edges") || edges.view.ndim != 1 ||
        edges.view.shape[0] % 2 != 0 ||
        !expect_int32(triangles, "triangles") || triangles.view.ndim != 1 ||
        triangles.view.shape[0] % 3 != 0 ||
        !expect_int32(loop_vertices, "loop_vertices") || loop_vertices.view.ndim != 1 ||
        !expect_float32(loop_uvs, "loop_uvs") || loop_uvs.view.ndim != 1 ||
        !finite_floats(loop_uvs, "loop_uvs") ||
        !expect_float32(pin_weights, "pin_weights") || pin_weights.view.ndim != 1 ||
        (pin_weights.view.shape[0] != 0 &&
         pin_weights.view.shape[0] != positions.view.shape[0] / 3) ||
        !finite_floats(pin_weights, "pin_weights")) {
        return nullptr;
    }

    if (!expect_float32(radius_multipliers, "radius_multipliers") ||
        radius_multipliers.view.ndim != 1 ||
        radius_multipliers.view.shape[0] != positions.view.shape[0] / 3 ||
        !finite_floats(radius_multipliers, "radius_multipliers")) {
        return nullptr;
    }
    const auto* radius_values = static_cast<const float*>(radius_multipliers.view.buf);
    for (Py_ssize_t index = 0; index < radius_multipliers.view.shape[0]; ++index) {
        if (radius_values[index] < 0.0f || radius_values[index] > 1.0f) {
            PyErr_SetString(PyExc_ValueError, "radius_multipliers must be in 0..1");
            return nullptr;
        }
    }

    const auto object_pointer = PyLong_AsUnsignedLongLong(PyTuple_GET_ITEM(args, 8));
    const auto mesh_pointer = PyLong_AsUnsignedLongLong(PyTuple_GET_ITEM(args, 9));
    const int pin_enabled = PyObject_IsTrue(PyTuple_GET_ITEM(args, 10));
    Py_ssize_t pin_name_size = 0;
    const char* pin_name = PyUnicode_AsUTF8AndSize(
        PyTuple_GET_ITEM(args, 11),
        &pin_name_size
    );
    Py_ssize_t radius_group_name_size = 0;
    const char* radius_group_name = PyUnicode_AsUTF8AndSize(
        PyTuple_GET_ITEM(args, 12),
        &radius_group_name_size
    );
    const int has_uv_layer = PyObject_IsTrue(PyTuple_GET_ITEM(args, 13));
    if (PyErr_Occurred() || pin_enabled < 0 || has_uv_layer < 0 ||
        pin_name == nullptr || radius_group_name == nullptr) {
        return nullptr;
    }
    const Py_ssize_t expected_uv_values = loop_vertices.view.shape[0] * 2;
    if ((has_uv_layer && loop_uvs.view.shape[0] != expected_uv_values) ||
        (!has_uv_layer && loop_uvs.view.shape[0] != 0)) {
        PyErr_SetString(
            PyExc_ValueError,
            has_uv_layer
                ? "loop_uvs length must equal loop_vertices length * 2 when a UV layer exists"
                : "loop_uvs must be empty when no UV layer exists"
        );
        return nullptr;
    }

    Mc2StaticFingerprintV0 topology, geometry, surface;
    topology.append_text("mc2_mesh_topology_v0");
    topology.append(&object_pointer, sizeof(object_pointer));
    topology.append(&mesh_pointer, sizeof(mesh_pointer));
    topology.append_buffer("edges", edges);
    topology.append_buffer("triangles", triangles);
    topology.append_buffer("loop_vertices", loop_vertices);
    geometry.append_text("mc2_mesh_geometry_v0");
    geometry.append_buffer("positions", positions);
    geometry.append_buffer("normals", normals);
    surface.append_text("mc2_mesh_surface_v0");
    surface.append(&pin_enabled, sizeof(pin_enabled));
    surface.append(&has_uv_layer, sizeof(has_uv_layer));
    surface.append(pin_name, static_cast<std::size_t>(pin_name_size));
    surface.append(radius_group_name, static_cast<std::size_t>(radius_group_name_size));
    surface.append_buffer("loop_uvs", loop_uvs);
    surface.append_buffer("pin_weights", pin_weights);
    surface.append_buffer("radius_multipliers", radius_multipliers);
    return static_fingerprint_result(topology, geometry, surface);
}

PyObject* mc2_bone_static_fingerprint_v0(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 8) {
        PyErr_Format(
            PyExc_TypeError,
            "mc2_bone_static_fingerprint_v0 expects 8 arguments, got %zd",
            PyTuple_GET_SIZE(args)
        );
        return nullptr;
    }
    Buffer parents, head_tail, matrices;
    if (!parents.get(PyTuple_GET_ITEM(args, 0), PyBUF_FORMAT | PyBUF_ND, "parents") ||
        !head_tail.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "head_tail") ||
        !matrices.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "matrices")) {
        return nullptr;
    }
    if (!expect_int32(parents, "parents") || parents.view.ndim != 1 ||
        !expect_float32(head_tail, "head_tail") || head_tail.view.ndim != 1 ||
        head_tail.view.shape[0] != parents.view.shape[0] * 6 ||
        !finite_floats(head_tail, "head_tail") ||
        !expect_float32(matrices, "matrices") || matrices.view.ndim != 1 ||
        matrices.view.shape[0] != parents.view.shape[0] * 16 ||
        !finite_floats(matrices, "matrices")) {
        return nullptr;
    }
    const auto* parent_values = static_cast<const std::int32_t*>(parents.view.buf);
    for (Py_ssize_t index = 0; index < parents.view.shape[0]; ++index) {
        if (parent_values[index] < -1 || parent_values[index] >= parents.view.shape[0]) {
            PyErr_SetString(PyExc_ValueError, "parents contains an invalid bone index");
            return nullptr;
        }
    }

    const auto armature_pointer = PyLong_AsUnsignedLongLong(PyTuple_GET_ITEM(args, 3));
    const char* text_values[3] {};
    Py_ssize_t text_sizes[3] {};
    for (int index = 0; index < 3; ++index) {
        text_values[index] = PyUnicode_AsUTF8AndSize(
            PyTuple_GET_ITEM(args, 4 + index),
            &text_sizes[index]
        );
        if (text_values[index] == nullptr) return nullptr;
    }
    const int resolved = PyObject_IsTrue(PyTuple_GET_ITEM(args, 7));
    if (PyErr_Occurred() || resolved < 0) return nullptr;

    Mc2StaticFingerprintV0 topology, geometry, surface;
    topology.append_text("mc2_bone_topology_v0");
    topology.append(&armature_pointer, sizeof(armature_pointer));
    topology.append(&resolved, sizeof(resolved));
    for (int index = 0; index < 3; ++index) {
        topology.append(text_values[index], static_cast<std::size_t>(text_sizes[index]));
    }
    topology.append_buffer("parents", parents);
    geometry.append_text("mc2_bone_geometry_v0");
    geometry.append_buffer("head_tail", head_tail);
    geometry.append_buffer("matrices", matrices);
    surface.append_text("mc2_bone_surface_v0");
    return static_fingerprint_result(topology, geometry, surface);
}

}  // namespace hotools
