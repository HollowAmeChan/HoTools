#include <Python.h>

#include "hotools_spring_bone_vrm.hpp"
#include "python_buffer_utils.hpp"

#include <algorithm>
#include <cstdint>

namespace {

using hotools::py::Buffer;

bool expect_matrix16_array(const Buffer& buffer, const char* name, Py_ssize_t* count) {
    if (!hotools::py::expect_float32(buffer, name)) {
        return false;
    }
    if (buffer.view.ndim != 2 || buffer.view.shape == nullptr || buffer.view.shape[1] != 16) {
        PyErr_Format(PyExc_ValueError, "%s must have shape (n, 16)", name);
        return false;
    }
    *count = buffer.view.shape[0];
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

std::int32_t* int32_ptr(Buffer& buffer) {
    return static_cast<std::int32_t*>(buffer.view.buf);
}

const std::int32_t* int32_ptr(const Buffer& buffer) {
    return static_cast<const std::int32_t*>(buffer.view.buf);
}

const float* float_ptr(const Buffer& buffer) {
    return static_cast<const float*>(buffer.view.buf);
}

float* float_ptr(Buffer& buffer) {
    return static_cast<float*>(buffer.view.buf);
}

}  // namespace

PyObject* solve_spring_bone_vrm_cpp(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 34;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "solve_spring_bone_vrm_cpp expects %zd arguments", kArgCount);
        return nullptr;
    }

    Buffer current_tails;
    Buffer prev_tails;
    Buffer target_matrices;
    Buffer current_heads;
    Buffer current_pose_matrices;
    Buffer current_pose_quaternions;
    Buffer parent_pose_quaternions;
    Buffer current_pose_tails;
    Buffer lengths;
    Buffer init_axis_local;
    Buffer init_axis_parent;
    Buffer init_rotations;
    Buffer init_scales;
    Buffer parent_indices;
    Buffer pinned;
    Buffer use_connect;
    Buffer root_quaternion;
    Buffer root_tail_world;
    Buffer armature_world;
    Buffer armature_world_inv;
    Buffer gravity_dir;
    Buffer hit_radii;
    Buffer collided_by_groups;
    Buffer collider_types;
    Buffer collider_groups;
    Buffer collider_centers;
    Buffer collider_segment_a;
    Buffer collider_segment_b;
    Buffer collider_radii;

    if (!current_tails.get(PyTuple_GET_ITEM(args, 0), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "current_tails") ||
        !prev_tails.get(PyTuple_GET_ITEM(args, 1), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "prev_tails") ||
        !target_matrices.get(PyTuple_GET_ITEM(args, 2), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "target_matrices") ||
        !current_heads.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "current_heads") ||
        !current_pose_matrices.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "current_pose_matrices") ||
        !current_pose_quaternions.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "current_pose_quaternions") ||
        !parent_pose_quaternions.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "parent_pose_quaternions") ||
        !current_pose_tails.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "current_pose_tails") ||
        !lengths.get(PyTuple_GET_ITEM(args, 8), PyBUF_FORMAT | PyBUF_ND, "lengths") ||
        !init_axis_local.get(PyTuple_GET_ITEM(args, 9), PyBUF_FORMAT | PyBUF_ND, "init_axis_local") ||
        !init_axis_parent.get(PyTuple_GET_ITEM(args, 10), PyBUF_FORMAT | PyBUF_ND, "init_axis_parent") ||
        !init_rotations.get(PyTuple_GET_ITEM(args, 11), PyBUF_FORMAT | PyBUF_ND, "init_rotations") ||
        !init_scales.get(PyTuple_GET_ITEM(args, 12), PyBUF_FORMAT | PyBUF_ND, "init_scales") ||
        !parent_indices.get(PyTuple_GET_ITEM(args, 13), PyBUF_FORMAT | PyBUF_ND, "parent_indices") ||
        !pinned.get(PyTuple_GET_ITEM(args, 14), PyBUF_FORMAT | PyBUF_ND, "pinned") ||
        !use_connect.get(PyTuple_GET_ITEM(args, 15), PyBUF_FORMAT | PyBUF_ND, "use_connect") ||
        !root_quaternion.get(PyTuple_GET_ITEM(args, 16), PyBUF_FORMAT | PyBUF_ND, "root_quaternion") ||
        !root_tail_world.get(PyTuple_GET_ITEM(args, 17), PyBUF_FORMAT | PyBUF_ND, "root_tail_world") ||
        !armature_world.get(PyTuple_GET_ITEM(args, 18), PyBUF_FORMAT | PyBUF_ND, "armature_world") ||
        !armature_world_inv.get(PyTuple_GET_ITEM(args, 19), PyBUF_FORMAT | PyBUF_ND, "armature_world_inv") ||
        !gravity_dir.get(PyTuple_GET_ITEM(args, 20), PyBUF_FORMAT | PyBUF_ND, "gravity_dir") ||
        !hit_radii.get(PyTuple_GET_ITEM(args, 21), PyBUF_FORMAT | PyBUF_ND, "hit_radii") ||
        !collided_by_groups.get(PyTuple_GET_ITEM(args, 22), PyBUF_FORMAT | PyBUF_ND, "collided_by_groups") ||
        !collider_types.get(PyTuple_GET_ITEM(args, 23), PyBUF_FORMAT | PyBUF_ND, "collider_types") ||
        !collider_groups.get(PyTuple_GET_ITEM(args, 24), PyBUF_FORMAT | PyBUF_ND, "collider_groups") ||
        !collider_centers.get(PyTuple_GET_ITEM(args, 25), PyBUF_FORMAT | PyBUF_ND, "collider_centers") ||
        !collider_segment_a.get(PyTuple_GET_ITEM(args, 26), PyBUF_FORMAT | PyBUF_ND, "collider_segment_a") ||
        !collider_segment_b.get(PyTuple_GET_ITEM(args, 27), PyBUF_FORMAT | PyBUF_ND, "collider_segment_b") ||
        !collider_radii.get(PyTuple_GET_ITEM(args, 28), PyBUF_FORMAT | PyBUF_ND, "collider_radii")) {
        return nullptr;
    }

    Py_ssize_t bone_count = 0;
    if (!hotools::py::expect_vector3_array(current_tails, "current_tails", &bone_count) ||
        !hotools::py::expect_same_vertex_count(prev_tails, "prev_tails", bone_count) ||
        !expect_matrix16_array(target_matrices, "target_matrices", &bone_count) ||
        !hotools::py::expect_same_vertex_count(current_heads, "current_heads", bone_count) ||
        !expect_matrix16_array(current_pose_matrices, "current_pose_matrices", &bone_count) ||
        !hotools::py::expect_vector4_array(current_pose_quaternions, "current_pose_quaternions", &bone_count) ||
        !hotools::py::expect_vector4_array(parent_pose_quaternions, "parent_pose_quaternions", &bone_count) ||
        !hotools::py::expect_same_vertex_count(current_pose_tails, "current_pose_tails", bone_count) ||
        !hotools::py::expect_float32(lengths, "lengths") ||
        !hotools::py::expect_1d_array(lengths, "lengths", bone_count) ||
        !hotools::py::expect_same_vertex_count(init_axis_local, "init_axis_local", bone_count) ||
        !hotools::py::expect_same_vertex_count(init_axis_parent, "init_axis_parent", bone_count) ||
        !hotools::py::expect_vector4_array(init_rotations, "init_rotations", &bone_count) ||
        !hotools::py::expect_same_vertex_count(init_scales, "init_scales", bone_count) ||
        !hotools::py::expect_int32(parent_indices, "parent_indices") ||
        !hotools::py::expect_1d_array(parent_indices, "parent_indices", bone_count) ||
        !hotools::py::expect_uint8(pinned, "pinned") ||
        !hotools::py::expect_1d_array(pinned, "pinned", bone_count) ||
        !hotools::py::expect_uint8(use_connect, "use_connect") ||
        !hotools::py::expect_1d_array(use_connect, "use_connect", bone_count) ||
        !hotools::py::expect_float32(root_quaternion, "root_quaternion") ||
        !hotools::py::expect_1d_array(root_quaternion, "root_quaternion", 4) ||
        !hotools::py::expect_float32(root_tail_world, "root_tail_world") ||
        !hotools::py::expect_1d_array(root_tail_world, "root_tail_world", 3) ||
        !hotools::py::expect_float32(armature_world, "armature_world") ||
        !hotools::py::expect_1d_array(armature_world, "armature_world", 16) ||
        !hotools::py::expect_float32(armature_world_inv, "armature_world_inv") ||
        !hotools::py::expect_1d_array(armature_world_inv, "armature_world_inv", 16) ||
        !hotools::py::expect_float32(gravity_dir, "gravity_dir") ||
        !hotools::py::expect_1d_array(gravity_dir, "gravity_dir", 3) ||
        !hotools::py::expect_float32(hit_radii, "hit_radii") ||
        !hotools::py::expect_1d_array(hit_radii, "hit_radii", bone_count) ||
        !hotools::py::expect_int32(collided_by_groups, "collided_by_groups") ||
        !hotools::py::expect_1d_array(collided_by_groups, "collided_by_groups", bone_count) ||
        !hotools::py::expect_int32(collider_types, "collider_types") ||
        !hotools::py::expect_int32(collider_groups, "collider_groups") ||
        !hotools::py::expect_float32(collider_radii, "collider_radii")) {
        return nullptr;
    }

    Py_ssize_t collider_count = 0;
    Py_ssize_t collider_segment_a_count = 0;
    Py_ssize_t collider_segment_b_count = 0;
    if (!hotools::py::expect_vector3_array(collider_centers, "collider_centers", &collider_count) ||
        !hotools::py::expect_vector3_array(collider_segment_a, "collider_segment_a", &collider_segment_a_count) ||
        !hotools::py::expect_vector3_array(collider_segment_b, "collider_segment_b", &collider_segment_b_count)) {
        return nullptr;
    }
    if (collider_segment_a_count != collider_count || collider_segment_b_count != collider_count) {
        PyErr_SetString(PyExc_ValueError, "collider segment array length mismatch");
        return nullptr;
    }
    if (!hotools::py::expect_1d_array(collider_types, "collider_types", collider_count) ||
        !hotools::py::expect_1d_array(collider_groups, "collider_groups", collider_count) ||
        !hotools::py::expect_1d_array(collider_radii, "collider_radii", collider_count)) {
        return nullptr;
    }

    const double dt = as_double(PyTuple_GET_ITEM(args, 29), "dt");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const long substeps = as_long(PyTuple_GET_ITEM(args, 30), "substeps");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double stiffness_force = as_double(PyTuple_GET_ITEM(args, 31), "stiffness_force");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double drag_force = as_double(PyTuple_GET_ITEM(args, 32), "drag_force");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double gravity_power = as_double(PyTuple_GET_ITEM(args, 33), "gravity_power");
    if (PyErr_Occurred()) {
        return nullptr;
    }

    hotools::SpringBoneVrmChainView view;
    view.current_tails = float_ptr(current_tails);
    view.prev_tails = float_ptr(prev_tails);
    view.target_matrices = float_ptr(target_matrices);
    view.current_heads = float_ptr(current_heads);
    view.current_pose_matrices = float_ptr(current_pose_matrices);
    view.current_pose_quaternions = float_ptr(current_pose_quaternions);
    view.parent_pose_quaternions = float_ptr(parent_pose_quaternions);
    view.current_pose_tails = float_ptr(current_pose_tails);
    view.lengths = float_ptr(lengths);
    view.init_axis_local = float_ptr(init_axis_local);
    view.init_axis_parent = float_ptr(init_axis_parent);
    view.init_rotations = float_ptr(init_rotations);
    view.init_scales = float_ptr(init_scales);
    view.parent_indices = int32_ptr(parent_indices);
    view.pinned = static_cast<const std::uint8_t*>(pinned.view.buf);
    view.use_connect = static_cast<const std::uint8_t*>(use_connect.view.buf);
    view.root_quaternion = float_ptr(root_quaternion);
    view.root_tail_world = float_ptr(root_tail_world);
    view.armature_world = float_ptr(armature_world);
    view.armature_world_inv = float_ptr(armature_world_inv);
    view.gravity_dir = float_ptr(gravity_dir);
    view.hit_radii = float_ptr(hit_radii);
    view.collided_by_groups = int32_ptr(collided_by_groups);
    view.collider_types = int32_ptr(collider_types);
    view.collider_groups = int32_ptr(collider_groups);
    view.collider_centers = float_ptr(collider_centers);
    view.collider_segment_a = float_ptr(collider_segment_a);
    view.collider_segment_b = float_ptr(collider_segment_b);
    view.collider_radii = float_ptr(collider_radii);
    view.bone_count = static_cast<std::int64_t>(bone_count);
    view.collider_count = static_cast<std::int64_t>(collider_count);
    view.substeps = static_cast<int>(substeps);
    view.dt = static_cast<float>(dt);
    view.stiffness_force = static_cast<float>(stiffness_force);
    view.drag_force = static_cast<float>(drag_force);
    view.gravity_power = static_cast<float>(gravity_power);

    hotools::solve_spring_bone_vrm_cpp(view);
    Py_RETURN_NONE;
}
