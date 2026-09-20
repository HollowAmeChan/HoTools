#include <Python.h>

#include "hotools_spring_bone_vrm.hpp"
#include "python_buffer_utils.hpp"

#include <cstdint>

namespace {

using hotools::py::Buffer;

bool expect_flat_float32(const Buffer& buffer, const char* name, Py_ssize_t expected_count) {
    return hotools::py::expect_float32(buffer, name) &&
           hotools::py::expect_1d_array(buffer, name, expected_count);
}

bool expect_flat_int32(const Buffer& buffer, const char* name, Py_ssize_t expected_count) {
    return hotools::py::expect_int32(buffer, name) &&
           hotools::py::expect_1d_array(buffer, name, expected_count);
}

bool expect_flat_uint8(const Buffer& buffer, const char* name, Py_ssize_t expected_count) {
    return hotools::py::expect_uint8(buffer, name) &&
           hotools::py::expect_1d_array(buffer, name, expected_count);
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

// ─────────────────────────────────────────────────────────────────────────────
// SpringBone context bindings
// ─────────────────────────────────────────────────────────────────────────────

static void spring_vrm_context_capsule_destructor(PyObject* capsule) {
    auto* ctx = static_cast<hotools::SpringVrmContext*>(
        PyCapsule_GetPointer(capsule, "spring_vrm_context"));
    hotools::spring_vrm_context_free(ctx);
}

// free_spring_vrm_context(capsule) -> None
//
// Slot owners release contexts deterministically instead of waiting for GC.
// Renaming the capsule makes repeated release idempotent and prevents every
// other context API from using the freed pointer.
PyObject* free_spring_vrm_context(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 1) {
        PyErr_SetString(PyExc_TypeError, "free_spring_vrm_context expects 1 argument");
        return nullptr;
    }

    PyObject* capsule = PyTuple_GET_ITEM(args, 0);
    if (PyCapsule_IsValid(capsule, "spring_vrm_context.freed")) {
        Py_RETURN_NONE;
    }
    if (!PyCapsule_IsValid(capsule, "spring_vrm_context")) {
        PyErr_SetString(PyExc_ValueError, "invalid SpringBone context capsule");
        return nullptr;
    }

    auto* ctx = static_cast<hotools::SpringVrmContext*>(
        PyCapsule_GetPointer(capsule, "spring_vrm_context"));
    if (!ctx) {
        return nullptr;
    }
    if (PyCapsule_SetDestructor(capsule, nullptr) != 0) {
        return nullptr;
    }
    if (PyCapsule_SetName(capsule, "spring_vrm_context.freed") != 0) {
        PyCapsule_SetDestructor(capsule, spring_vrm_context_capsule_destructor);
        return nullptr;
    }

    hotools::spring_vrm_context_free(ctx);
    Py_RETURN_NONE;
}

// spring_vrm_create_context(schema, bone_count,
//     lengths, init_axis_local, init_axis_parent, init_rotations, init_scales,
//     parent_indices, pinned, use_connect) -> capsule
PyObject* spring_vrm_create_context(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 10) {
        PyErr_SetString(PyExc_TypeError, "spring_vrm_create_context expects 10 arguments");
        return nullptr;
    }

    const long schema     = as_long(PyTuple_GET_ITEM(args, 0), "schema");
    if (PyErr_Occurred()) return nullptr;
    const long bone_count = as_long(PyTuple_GET_ITEM(args, 1), "bone_count");
    if (PyErr_Occurred()) return nullptr;
    if (bone_count <= 0) {
        PyErr_SetString(PyExc_ValueError, "bone_count must be > 0");
        return nullptr;
    }
    if (schema != 1) {
        PyErr_SetString(PyExc_ValueError, "unsupported SpringBone context schema");
        return nullptr;
    }

    Buffer lengths, init_axis_local, init_axis_parent, init_rotations, init_scales;
    Buffer parent_indices, pinned, use_connect;

    if (!lengths.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "lengths") ||
        !init_axis_local.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "init_axis_local") ||
        !init_axis_parent.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "init_axis_parent") ||
        !init_rotations.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "init_rotations") ||
        !init_scales.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "init_scales") ||
        !parent_indices.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "parent_indices") ||
        !pinned.get(PyTuple_GET_ITEM(args, 8), PyBUF_FORMAT | PyBUF_ND, "pinned") ||
        !use_connect.get(PyTuple_GET_ITEM(args, 9), PyBUF_FORMAT | PyBUF_ND, "use_connect")) {
        return nullptr;
    }

    const Py_ssize_t n = static_cast<Py_ssize_t>(bone_count);
    if (!expect_flat_float32(lengths, "lengths", n) ||
        !expect_flat_float32(init_axis_local, "init_axis_local", n * 3) ||
        !expect_flat_float32(init_axis_parent, "init_axis_parent", n * 3) ||
        !expect_flat_float32(init_rotations, "init_rotations", n * 4) ||
        !expect_flat_float32(init_scales, "init_scales", n * 3) ||
        !expect_flat_int32(parent_indices, "parent_indices", n) ||
        !expect_flat_uint8(pinned, "pinned", n) ||
        !expect_flat_uint8(use_connect, "use_connect", n) ||
        !hotools::py::expect_root_indices_or_minus_one(parent_indices, "parent_indices", n)) {
        return nullptr;
    }

    auto* ctx = hotools::spring_vrm_context_create(
        static_cast<int>(schema),
        static_cast<std::int64_t>(bone_count),
        float_ptr(lengths),
        float_ptr(init_axis_local),
        float_ptr(init_axis_parent),
        float_ptr(init_rotations),
        float_ptr(init_scales),
        int32_ptr(parent_indices),
        static_cast<const std::uint8_t*>(pinned.view.buf),
        static_cast<const std::uint8_t*>(use_connect.view.buf));

    if (!ctx) {
        PyErr_SetString(PyExc_RuntimeError, "spring_vrm_create_context: allocation failed");
        return nullptr;
    }
    return PyCapsule_New(ctx, "spring_vrm_context", spring_vrm_context_capsule_destructor);
}

// spring_vrm_reset_state(capsule) -> None
PyObject* spring_vrm_reset_state(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 1) {
        PyErr_SetString(PyExc_TypeError, "spring_vrm_reset_state expects 1 argument");
        return nullptr;
    }
    auto* ctx = static_cast<hotools::SpringVrmContext*>(
        PyCapsule_GetPointer(PyTuple_GET_ITEM(args, 0), "spring_vrm_context"));
    if (!ctx) return nullptr;
    hotools::spring_vrm_context_reset_state(ctx);
    Py_RETURN_NONE;
}

// spring_vrm_update_dynamic(capsule,
//     current_heads, current_pose_matrices, current_pose_quaternions,
//     parent_pose_quaternions, current_pose_tails,
//     armature_world, armature_world_inv, root_quaternion, root_tail_world, gravity_dir,
//     hit_radii, collided_by_groups,
//     collider_types, collider_groups, collider_centers,
//     collider_segment_a, collider_segment_b, collider_radii) -> None
PyObject* spring_vrm_update_dynamic(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 19;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "spring_vrm_update_dynamic expects %zd arguments", kArgCount);
        return nullptr;
    }

    auto* ctx = static_cast<hotools::SpringVrmContext*>(
        PyCapsule_GetPointer(PyTuple_GET_ITEM(args, 0), "spring_vrm_context"));
    if (!ctx) return nullptr;

    Buffer current_heads, current_pose_matrices, current_pose_quaternions;
    Buffer parent_pose_quaternions, current_pose_tails;
    Buffer armature_world, armature_world_inv, root_quaternion, root_tail_world, gravity_dir;
    Buffer hit_radii, collided_by_groups;
    Buffer collider_types, collider_groups, collider_centers;
    Buffer collider_segment_a, collider_segment_b, collider_radii;

    if (!current_heads.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "current_heads") ||
        !current_pose_matrices.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "current_pose_matrices") ||
        !current_pose_quaternions.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "current_pose_quaternions") ||
        !parent_pose_quaternions.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "parent_pose_quaternions") ||
        !current_pose_tails.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "current_pose_tails") ||
        !armature_world.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "armature_world") ||
        !armature_world_inv.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "armature_world_inv") ||
        !root_quaternion.get(PyTuple_GET_ITEM(args, 8), PyBUF_FORMAT | PyBUF_ND, "root_quaternion") ||
        !root_tail_world.get(PyTuple_GET_ITEM(args, 9), PyBUF_FORMAT | PyBUF_ND, "root_tail_world") ||
        !gravity_dir.get(PyTuple_GET_ITEM(args, 10), PyBUF_FORMAT | PyBUF_ND, "gravity_dir") ||
        !hit_radii.get(PyTuple_GET_ITEM(args, 11), PyBUF_FORMAT | PyBUF_ND, "hit_radii") ||
        !collided_by_groups.get(PyTuple_GET_ITEM(args, 12), PyBUF_FORMAT | PyBUF_ND, "collided_by_groups") ||
        !collider_types.get(PyTuple_GET_ITEM(args, 13), PyBUF_FORMAT | PyBUF_ND, "collider_types") ||
        !collider_groups.get(PyTuple_GET_ITEM(args, 14), PyBUF_FORMAT | PyBUF_ND, "collider_groups") ||
        !collider_centers.get(PyTuple_GET_ITEM(args, 15), PyBUF_FORMAT | PyBUF_ND, "collider_centers") ||
        !collider_segment_a.get(PyTuple_GET_ITEM(args, 16), PyBUF_FORMAT | PyBUF_ND, "collider_segment_a") ||
        !collider_segment_b.get(PyTuple_GET_ITEM(args, 17), PyBUF_FORMAT | PyBUF_ND, "collider_segment_b") ||
        !collider_radii.get(PyTuple_GET_ITEM(args, 18), PyBUF_FORMAT | PyBUF_ND, "collider_radii")) {
        return nullptr;
    }

    const Py_ssize_t bone_count = static_cast<Py_ssize_t>(ctx->bone_count);
    if (!expect_flat_float32(current_heads, "current_heads", bone_count * 3) ||
        !expect_flat_float32(current_pose_matrices, "current_pose_matrices", bone_count * 16) ||
        !expect_flat_float32(current_pose_quaternions, "current_pose_quaternions", bone_count * 4) ||
        !expect_flat_float32(parent_pose_quaternions, "parent_pose_quaternions", bone_count * 4) ||
        !expect_flat_float32(current_pose_tails, "current_pose_tails", bone_count * 3) ||
        !expect_flat_float32(armature_world, "armature_world", 16) ||
        !expect_flat_float32(armature_world_inv, "armature_world_inv", 16) ||
        !expect_flat_float32(root_quaternion, "root_quaternion", 4) ||
        !expect_flat_float32(root_tail_world, "root_tail_world", 3) ||
        !expect_flat_float32(gravity_dir, "gravity_dir", 3) ||
        !expect_flat_float32(hit_radii, "hit_radii", bone_count) ||
        !expect_flat_int32(collided_by_groups, "collided_by_groups", bone_count) ||
        !hotools::py::expect_int32(collider_types, "collider_types") ||
        !hotools::py::expect_int32(collider_groups, "collider_groups") ||
        !hotools::py::expect_float32(collider_centers, "collider_centers") ||
        !hotools::py::expect_float32(collider_segment_a, "collider_segment_a") ||
        !hotools::py::expect_float32(collider_segment_b, "collider_segment_b") ||
        !hotools::py::expect_float32(collider_radii, "collider_radii")) {
        return nullptr;
    }

    Py_ssize_t collider_count = 0;
    if (!hotools::py::expect_1d_array(collider_types, "collider_types", -1)) {
        return nullptr;
    }
    collider_count = collider_types.view.shape[0];
    if (!hotools::py::expect_1d_array(collider_groups, "collider_groups", collider_count) ||
        !hotools::py::expect_1d_array(collider_centers, "collider_centers", collider_count * 3) ||
        !hotools::py::expect_1d_array(collider_segment_a, "collider_segment_a", collider_count * 3) ||
        !hotools::py::expect_1d_array(collider_segment_b, "collider_segment_b", collider_count * 3) ||
        !hotools::py::expect_1d_array(collider_radii, "collider_radii", collider_count)) {
        return nullptr;
    }

    hotools::spring_vrm_context_update_dynamic(
        ctx,
        float_ptr(current_heads),
        float_ptr(current_pose_matrices),
        float_ptr(current_pose_quaternions),
        float_ptr(parent_pose_quaternions),
        float_ptr(current_pose_tails),
        float_ptr(armature_world),
        float_ptr(armature_world_inv),
        float_ptr(root_quaternion),
        float_ptr(root_tail_world),
        float_ptr(gravity_dir),
        float_ptr(hit_radii),
        int32_ptr(collided_by_groups),
        int32_ptr(collider_types),
        int32_ptr(collider_groups),
        float_ptr(collider_centers),
        float_ptr(collider_segment_a),
        float_ptr(collider_segment_b),
        float_ptr(collider_radii),
        static_cast<std::int64_t>(collider_count));

    Py_RETURN_NONE;
}

// spring_vrm_step(capsule, dt, substeps, stiffness, drag, gravity_power) -> None
PyObject* spring_vrm_step(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 6) {
        PyErr_SetString(PyExc_TypeError, "spring_vrm_step expects 6 arguments");
        return nullptr;
    }
    auto* ctx = static_cast<hotools::SpringVrmContext*>(
        PyCapsule_GetPointer(PyTuple_GET_ITEM(args, 0), "spring_vrm_context"));
    if (!ctx) return nullptr;

    const double dt            = as_double(PyTuple_GET_ITEM(args, 1), "dt");
    if (PyErr_Occurred()) return nullptr;
    const long substeps        = as_long(PyTuple_GET_ITEM(args, 2), "substeps");
    if (PyErr_Occurred()) return nullptr;
    const double stiffness     = as_double(PyTuple_GET_ITEM(args, 3), "stiffness_force");
    if (PyErr_Occurred()) return nullptr;
    const double drag          = as_double(PyTuple_GET_ITEM(args, 4), "drag_force");
    if (PyErr_Occurred()) return nullptr;
    const double gravity_power = as_double(PyTuple_GET_ITEM(args, 5), "gravity_power");
    if (PyErr_Occurred()) return nullptr;

    hotools::spring_vrm_context_step(
        ctx,
        static_cast<float>(dt),
        static_cast<int>(substeps),
        static_cast<float>(stiffness),
        static_cast<float>(drag),
        static_cast<float>(gravity_power));

    Py_RETURN_NONE;
}

// spring_vrm_read_results(capsule, out_matrices, out_quaternions) -> None
// out_matrices:    (N, 16) float32 writable
// out_quaternions: (N,  4) float32 writable
PyObject* spring_vrm_read_results(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 3) {
        PyErr_SetString(PyExc_TypeError, "spring_vrm_read_results expects 3 arguments");
        return nullptr;
    }
    auto* ctx = static_cast<hotools::SpringVrmContext*>(
        PyCapsule_GetPointer(PyTuple_GET_ITEM(args, 0), "spring_vrm_context"));
    if (!ctx) return nullptr;

    Buffer out_matrices, out_quaternions;
    if (!out_matrices.get(PyTuple_GET_ITEM(args, 1), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "out_matrices") ||
        !out_quaternions.get(PyTuple_GET_ITEM(args, 2), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "out_quaternions")) {
        return nullptr;
    }

    const Py_ssize_t bone_count = static_cast<Py_ssize_t>(ctx->bone_count);
    if (!expect_flat_float32(out_matrices, "out_matrices", bone_count * 16) ||
        !expect_flat_float32(out_quaternions, "out_quaternions", bone_count * 4)) {
        return nullptr;
    }

    hotools::spring_vrm_context_read_results(
        ctx,
        float_ptr(out_matrices),
        float_ptr(out_quaternions));

    Py_RETURN_NONE;
}

// spring_vrm_read_debug(capsule,
//     out_current_heads, out_current_tails, out_prev_tails, out_current_pose_tails,
//     out_hit_radii, out_collided_by_groups,
//     out_collider_types, out_collider_groups, out_collider_centers,
//     out_collider_segment_a, out_collider_segment_b, out_collider_radii) -> None
PyObject* spring_vrm_read_debug(PyObject*, PyObject* args) {
    constexpr Py_ssize_t kArgCount = 13;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "spring_vrm_read_debug expects %zd arguments", kArgCount);
        return nullptr;
    }
    auto* ctx = static_cast<hotools::SpringVrmContext*>(
        PyCapsule_GetPointer(PyTuple_GET_ITEM(args, 0), "spring_vrm_context"));
    if (!ctx) return nullptr;

    Buffer current_heads, current_tails, prev_tails, current_pose_tails;
    Buffer hit_radii, collided_by_groups;
    Buffer collider_types, collider_groups, collider_centers;
    Buffer collider_segment_a, collider_segment_b, collider_radii;

    if (!current_heads.get(PyTuple_GET_ITEM(args, 1), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "out_current_heads") ||
        !current_tails.get(PyTuple_GET_ITEM(args, 2), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "out_current_tails") ||
        !prev_tails.get(PyTuple_GET_ITEM(args, 3), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "out_prev_tails") ||
        !current_pose_tails.get(PyTuple_GET_ITEM(args, 4), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "out_current_pose_tails") ||
        !hit_radii.get(PyTuple_GET_ITEM(args, 5), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "out_hit_radii") ||
        !collided_by_groups.get(PyTuple_GET_ITEM(args, 6), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "out_collided_by_groups") ||
        !collider_types.get(PyTuple_GET_ITEM(args, 7), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "out_collider_types") ||
        !collider_groups.get(PyTuple_GET_ITEM(args, 8), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "out_collider_groups") ||
        !collider_centers.get(PyTuple_GET_ITEM(args, 9), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "out_collider_centers") ||
        !collider_segment_a.get(PyTuple_GET_ITEM(args, 10), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "out_collider_segment_a") ||
        !collider_segment_b.get(PyTuple_GET_ITEM(args, 11), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "out_collider_segment_b") ||
        !collider_radii.get(PyTuple_GET_ITEM(args, 12), PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "out_collider_radii")) {
        return nullptr;
    }

    const Py_ssize_t bone_count = static_cast<Py_ssize_t>(ctx->bone_count);
    const Py_ssize_t collider_count = static_cast<Py_ssize_t>(ctx->collider_count);
    if (!expect_flat_float32(current_heads, "out_current_heads", bone_count * 3) ||
        !expect_flat_float32(current_tails, "out_current_tails", bone_count * 3) ||
        !expect_flat_float32(prev_tails, "out_prev_tails", bone_count * 3) ||
        !expect_flat_float32(current_pose_tails, "out_current_pose_tails", bone_count * 3) ||
        !expect_flat_float32(hit_radii, "out_hit_radii", bone_count) ||
        !expect_flat_int32(collided_by_groups, "out_collided_by_groups", bone_count) ||
        !expect_flat_int32(collider_types, "out_collider_types", collider_count) ||
        !expect_flat_int32(collider_groups, "out_collider_groups", collider_count) ||
        !expect_flat_float32(collider_centers, "out_collider_centers", collider_count * 3) ||
        !expect_flat_float32(collider_segment_a, "out_collider_segment_a", collider_count * 3) ||
        !expect_flat_float32(collider_segment_b, "out_collider_segment_b", collider_count * 3) ||
        !expect_flat_float32(collider_radii, "out_collider_radii", collider_count)) {
        return nullptr;
    }

    hotools::spring_vrm_context_read_debug(
        ctx,
        float_ptr(current_heads),
        float_ptr(current_tails),
        float_ptr(prev_tails),
        float_ptr(current_pose_tails),
        float_ptr(hit_radii),
        int32_ptr(collided_by_groups),
        int32_ptr(collider_types),
        int32_ptr(collider_groups),
        float_ptr(collider_centers),
        float_ptr(collider_segment_a),
        float_ptr(collider_segment_b),
        float_ptr(collider_radii));

    Py_RETURN_NONE;
}
