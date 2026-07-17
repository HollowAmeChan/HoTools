#include "mc2_api.hpp"

#include "mc2_context_internal.hpp"
#include "mc2_context_helpers.hpp"

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace hotools {

using namespace mc2_internal;
using namespace py;

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

PyObject* mc2_context_v0_read_self_collision_primitives(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 5) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_self_collision_primitives expects 5 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->self_primitive_dynamic_ready) {
        PyErr_SetString(PyExc_RuntimeError, "self-collision primitive dynamics are not ready");
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->self_primitive_flags.size());
    Buffer inverse_masses, aabb_min, aabb_max, thickness;
    if (!inverse_masses.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_inverse_masses"
        ) ||
        !aabb_min.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_aabb_min"
        ) ||
        !aabb_max.get(
            PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_aabb_max"
        ) ||
        !thickness.get(
            PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_thickness"
        )) {
        return nullptr;
    }
    if (!expect_float32(inverse_masses, "out_self_inverse_masses") ||
        !expect_2d(inverse_masses, "out_self_inverse_masses", count, 3) ||
        !expect_float32(aabb_min, "out_self_aabb_min") ||
        !expect_2d(aabb_min, "out_self_aabb_min", count, 3) ||
        !expect_float32(aabb_max, "out_self_aabb_max") ||
        !expect_2d(aabb_max, "out_self_aabb_max", count, 3) ||
        !expect_float32(thickness, "out_self_thickness") ||
        !expect_1d_array(thickness, "out_self_thickness", count)) {
        return nullptr;
    }
    std::memcpy(
        inverse_masses.view.buf,
        context->self_primitive_inverse_masses.data(),
        context->self_primitive_inverse_masses.size() * sizeof(float)
    );
    std::memcpy(
        aabb_min.view.buf,
        context->self_primitive_aabb_min.data(),
        context->self_primitive_aabb_min.size() * sizeof(float)
    );
    std::memcpy(
        aabb_max.view.buf,
        context->self_primitive_aabb_max.data(),
        context->self_primitive_aabb_max.size() * sizeof(float)
    );
    std::memcpy(
        thickness.view.buf,
        context->self_primitive_thickness.data(),
        context->self_primitive_thickness.size() * sizeof(float)
    );
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_self_collision_grid(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 6) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_self_collision_grid expects 6 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->self_grid_dynamic_ready) {
        PyErr_SetString(PyExc_RuntimeError, "self-collision grid is not ready");
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->self_primitive_flags.size());
    Buffer particle_indices, grids, hashes, starts, counts;
    if (!particle_indices.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_particle_indices"
        ) ||
        !grids.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_primitive_grids"
        ) ||
        !hashes.get(
            PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_grid_hashes"
        ) ||
        !starts.get(
            PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_grid_starts"
        ) ||
        !counts.get(
            PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_grid_counts"
        )) {
        return nullptr;
    }
    if (!expect_int32(particle_indices, "out_self_particle_indices") ||
        !expect_2d(particle_indices, "out_self_particle_indices", count, 3) ||
        !expect_int32(grids, "out_self_primitive_grids") ||
        !expect_2d(grids, "out_self_primitive_grids", count, 3) ||
        !expect_int32(hashes, "out_self_grid_hashes") ||
        !expect_1d_array(hashes, "out_self_grid_hashes", count) ||
        !expect_int32(starts, "out_self_grid_starts") ||
        !expect_1d_array(starts, "out_self_grid_starts", count) ||
        !expect_int32(counts, "out_self_grid_counts") ||
        !expect_1d_array(counts, "out_self_grid_counts", count)) {
        return nullptr;
    }
    std::memcpy(
        particle_indices.view.buf,
        context->self_particle_indices.data(),
        context->self_particle_indices.size() * sizeof(std::int32_t)
    );
    std::memcpy(
        grids.view.buf,
        context->self_primitive_grids.data(),
        context->self_primitive_grids.size() * sizeof(std::int32_t)
    );
    std::memcpy(
        hashes.view.buf,
        context->self_grid_hashes.data(),
        context->self_grid_hashes.size() * sizeof(std::int32_t)
    );
    std::memcpy(
        starts.view.buf,
        context->self_grid_starts.data(),
        context->self_grid_starts.size() * sizeof(std::int32_t)
    );
    std::memcpy(
        counts.view.buf,
        context->self_grid_counts.data(),
        context->self_grid_counts.size() * sizeof(std::int32_t)
    );
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_self_collision_candidates(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_self_collision_candidates expects 2 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->self_candidate_ready) {
        PyErr_SetString(PyExc_RuntimeError, "self-collision candidates are not ready");
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->self_contact_candidates.size() / 3);
    Buffer candidates;
    if (!candidates.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_candidates"
        )) {
        return nullptr;
    }
    if (!expect_int32(candidates, "out_self_contact_candidates") ||
        !expect_2d(candidates, "out_self_contact_candidates", count, 3)) {
        return nullptr;
    }
    std::memcpy(
        candidates.view.buf,
        context->self_contact_candidates.data(),
        context->self_contact_candidates.size() * sizeof(std::int32_t)
    );
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_self_collision_contacts(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 8) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_self_collision_contacts expects 8 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->self_contact_ready) {
        PyErr_SetString(PyExc_RuntimeError, "self-collision contacts are not ready");
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->self_contact_types.size());
    Buffer indices, types, enabled, thickness, s, t, normals;
    if (!indices.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_indices"
        ) ||
        !types.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_types"
        ) ||
        !enabled.get(
            PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_enabled"
        ) ||
        !thickness.get(
            PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_thickness"
        ) ||
        !s.get(
            PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_s"
        ) ||
        !t.get(
            PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_t"
        ) ||
        !normals.get(
            PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_normals"
        )) {
        return nullptr;
    }
    if (!expect_int32(indices, "out_self_contact_indices") ||
        !expect_2d(indices, "out_self_contact_indices", count, 2) ||
        !expect_int32(types, "out_self_contact_types") ||
        !expect_1d_array(types, "out_self_contact_types", count) ||
        !expect_uint8_scalar_array(enabled, "out_self_contact_enabled") ||
        !expect_1d_array(enabled, "out_self_contact_enabled", count) ||
        !expect_float32(thickness, "out_self_contact_thickness") ||
        !expect_1d_array(thickness, "out_self_contact_thickness", count) ||
        !expect_float32(s, "out_self_contact_s") ||
        !expect_1d_array(s, "out_self_contact_s", count) ||
        !expect_float32(t, "out_self_contact_t") ||
        !expect_1d_array(t, "out_self_contact_t", count) ||
        !expect_float32(normals, "out_self_contact_normals") ||
        !expect_2d(normals, "out_self_contact_normals", count, 3)) {
        return nullptr;
    }
    std::memcpy(indices.view.buf, context->self_contact_primitive_indices.data(),
                context->self_contact_primitive_indices.size() * sizeof(std::int32_t));
    std::memcpy(types.view.buf, context->self_contact_types.data(),
                context->self_contact_types.size() * sizeof(std::int32_t));
    std::memcpy(enabled.view.buf, context->self_contact_enabled.data(),
                context->self_contact_enabled.size() * sizeof(std::uint8_t));
    std::memcpy(thickness.view.buf, context->self_contact_thickness.data(),
                context->self_contact_thickness.size() * sizeof(float));
    std::memcpy(s.view.buf, context->self_contact_s.data(),
                context->self_contact_s.size() * sizeof(float));
    std::memcpy(t.view.buf, context->self_contact_t.data(),
                context->self_contact_t.size() * sizeof(float));
    std::memcpy(normals.view.buf, context->self_contact_normals.data(),
                context->self_contact_normals.size() * sizeof(float));
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_self_collision_intersections(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_self_collision_intersections expects 4 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->self_intersect_detection_ready && !context->self_intersect_flags_ready) {
        PyErr_SetString(PyExc_RuntimeError, "self-collision intersections are not ready");
        return nullptr;
    }
    const auto record_count = static_cast<Py_ssize_t>(
        context->self_intersect_records.size() / 5
    );
    const auto vertex_count = static_cast<Py_ssize_t>(context->vertex_count);
    const auto primitive_count = static_cast<Py_ssize_t>(context->self_primitive_flags.size());
    Buffer records, particle_flags, primitive_flags;
    if (!records.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_intersect_records"
        ) ||
        !particle_flags.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_particle_intersect_flags"
        ) ||
        !primitive_flags.get(
            PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_primitive_flags"
        )) {
        return nullptr;
    }
    if (!expect_int32(records, "out_self_intersect_records") ||
        !expect_2d(records, "out_self_intersect_records", record_count, 5) ||
        !expect_uint8_scalar_array(particle_flags, "out_self_particle_intersect_flags") ||
        !expect_1d_array(
            particle_flags,
            "out_self_particle_intersect_flags",
            vertex_count
        ) ||
        !expect_uint32_scalar_array(primitive_flags, "out_self_primitive_flags") ||
        !expect_1d_array(primitive_flags, "out_self_primitive_flags", primitive_count)) {
        return nullptr;
    }
    std::memcpy(
        records.view.buf,
        context->self_intersect_records.data(),
        context->self_intersect_records.size() * sizeof(std::int32_t)
    );
    std::memcpy(
        particle_flags.view.buf,
        context->self_particle_intersect_flags.data(),
        context->self_particle_intersect_flags.size() * sizeof(std::uint8_t)
    );
    std::memcpy(
        primitive_flags.view.buf,
        context->self_primitive_flags.data(),
        context->self_primitive_flags.size() * sizeof(std::uint32_t)
    );
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_bone_output(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 3) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_read_bone_output expects 3 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!build_bone_output(*context)) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 Bone output state is incomplete");
        return nullptr;
    }
    Buffer positions, rotations;
    if (!positions.get(
            PyTuple_GET_ITEM(args, 1),
            PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_bone_positions") ||
        !rotations.get(
            PyTuple_GET_ITEM(args, 2),
            PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_bone_rotations")) {
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->vertex_count);
    if (!expect_float32(positions, "out_bone_positions") ||
        !expect_2d(positions, "out_bone_positions", count, 3) ||
        !expect_float32(rotations, "out_bone_rotations") ||
        !expect_2d(rotations, "out_bone_rotations", count, 4)) {
        return nullptr;
    }
    std::memcpy(
        positions.view.buf,
        context->bone_output_positions.data(),
        context->bone_output_positions.size() * sizeof(float)
    );
    std::memcpy(
        rotations.view.buf,
        context->bone_output_rotations.data(),
        context->bone_output_rotations.size() * sizeof(float)
    );
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_step_basic(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 3) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_read_step_basic expects 3 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto count = static_cast<std::size_t>(context->vertex_count);
    if (context->step_basic_positions.size() != count * 3 ||
        context->step_basic_rotations.size() != count * 4) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 step-basic pose is not ready");
        return nullptr;
    }
    Buffer positions, rotations;
    if (!positions.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_step_basic_positions"
        ) ||
        !rotations.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_step_basic_rotations"
        )) {
        return nullptr;
    }
    const Py_ssize_t vertex_count = static_cast<Py_ssize_t>(context->vertex_count);
    if (!expect_float32(positions, "out_step_basic_positions") ||
        !expect_2d(positions, "out_step_basic_positions", vertex_count, 3) ||
        !expect_float32(rotations, "out_step_basic_rotations") ||
        !expect_2d(rotations, "out_step_basic_rotations", vertex_count, 4)) {
        return nullptr;
    }
    std::memcpy(
        positions.view.buf,
        context->step_basic_positions.data(),
        context->step_basic_positions.size() * sizeof(float)
    );
    std::memcpy(
        rotations.view.buf,
        context->step_basic_rotations.data(),
        context->step_basic_rotations.size() * sizeof(float)
    );
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_center_step(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 8) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_read_center_step expects 8 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->center_result_ready) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 Center step result is not ready");
        return nullptr;
    }
    Buffer now_position, now_rotation, step_vector, step_rotation;
    Buffer inertia_vector, inertia_rotation, rotation_axis;
    Buffer* outputs[] = {
        &now_position, &now_rotation, &step_vector, &step_rotation,
        &inertia_vector, &inertia_rotation, &rotation_axis,
    };
    const char* names[] = {
        "out_center_now_world_position", "out_center_now_world_rotation",
        "out_center_step_vector", "out_center_step_rotation",
        "out_center_inertia_vector", "out_center_inertia_rotation",
        "out_center_rotation_axis",
    };
    const Py_ssize_t widths[] = {3, 4, 3, 4, 3, 4, 3};
    for (std::size_t index = 0; index < 7; ++index) {
        if (!outputs[index]->get(
                PyTuple_GET_ITEM(args, static_cast<Py_ssize_t>(index + 1)),
                PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
                names[index]) ||
            !expect_float32(*outputs[index], names[index]) ||
            !expect_1d_array(*outputs[index], names[index], widths[index])) {
            return nullptr;
        }
    }
    const float* values[] = {
        context->center_now_world_position.data(),
        context->center_now_world_rotation.data(),
        context->center_step_vector.data(),
        context->center_step_rotation.data(),
        context->center_inertia_vector.data(),
        context->center_inertia_rotation.data(),
        context->center_rotation_axis.data(),
    };
    for (std::size_t index = 0; index < 7; ++index) {
        std::memcpy(
            outputs[index]->view.buf,
            values[index],
            static_cast<std::size_t>(widths[index]) * sizeof(float)
        );
    }
    PyObject* result = PyDict_New();
    if (result == nullptr) return nullptr;
    if (!dict_float(result, "frame_interpolation", context->frame_interpolation) ||
        !dict_float(result, "step_move_inertia_ratio", context->center_step_move_inertia_ratio) ||
        !dict_float(result, "step_rotation_inertia_ratio", context->center_step_rotation_inertia_ratio) ||
        !dict_float(result, "angular_velocity", context->center_angular_velocity) ||
        !dict_float(result, "scale_ratio", context->scale_ratio) ||
        !dict_float(result, "gravity_dot", context->center_gravity_dot) ||
        !dict_float(result, "gravity_ratio", context->gravity_ratio) ||
        !dict_float(result, "velocity_weight", context->velocity_weight) ||
        !dict_float(result, "blend_weight", context->center_blend_weight)) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}

}  // namespace hotools
