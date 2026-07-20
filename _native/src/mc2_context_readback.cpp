#include "mc2_api.hpp"

#include "mc2_context_internal.hpp"
#include "mc2_context_helpers.hpp"

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>

namespace hotools {

using namespace mc2_internal;
using namespace py;

namespace {

void build_angle_limit_debug(
    const Mc2ContextV0& context,
    float* targets,
    float* vectors,
    std::uint8_t* valid
) {
    const auto count = static_cast<std::size_t>(context.vertex_count);
    if (context.baseline_parents.size() != count ||
        context.baseline_ranges.size() % 2 != 0 ||
        context.step_basic_positions.size() != count * 3 ||
        context.step_basic_rotations.size() != count * 4 ||
        context.state_positions.size() != count * 3 ||
        context.proxy_attributes.size() != count) {
        return;
    }
    std::vector<float> work_rotations = context.step_basic_rotations;
    std::vector<Vec3> local_positions(count);
    std::vector<std::array<float, 4>> local_rotations(
        count, {0.0f, 0.0f, 0.0f, 1.0f}
    );
    const auto line_count = context.baseline_ranges.size() / 2;
    for (std::size_t line = 0; line < line_count; ++line) {
        const auto start = context.baseline_ranges[line * 2];
        const auto line_size = context.baseline_ranges[line * 2 + 1];
        if (start < 0 || line_size <= 1 ||
            static_cast<std::size_t>(start + line_size) > context.baseline_data.size()) {
            continue;
        }
        for (std::int32_t local = 1; local < line_size; ++local) {
            const auto raw_child = context.baseline_data[static_cast<std::size_t>(start + local)];
            if (raw_child < 0 || static_cast<std::size_t>(raw_child) >= count) continue;
            const auto child = static_cast<std::size_t>(raw_child);
            const auto raw_parent = context.baseline_parents[child];
            if (raw_parent < 0 || static_cast<std::size_t>(raw_parent) >= count) continue;
            const auto parent = static_cast<std::size_t>(raw_parent);
            const Vec3 base {
                context.step_basic_positions[child * 3 + 0] -
                    context.step_basic_positions[parent * 3 + 0],
                context.step_basic_positions[child * 3 + 1] -
                    context.step_basic_positions[parent * 3 + 1],
                context.step_basic_positions[child * 3 + 2] -
                    context.step_basic_positions[parent * 3 + 2],
            };
            const float base_length = length(base);
            if (base_length <= kMc2Epsilon) continue;
            const auto parent_step_inverse = quaternion_inverse(
                load_quaternion(context.step_basic_rotations, parent)
            );
            local_positions[child] = rotate_vector(
                parent_step_inverse, mul(base, 1.0f / base_length)
            );
            local_rotations[child] = quaternion_multiply(
                parent_step_inverse,
                load_quaternion(context.step_basic_rotations, child)
            );
        }
        for (std::int32_t local = 1; local < line_size; ++local) {
            const auto raw_child = context.baseline_data[static_cast<std::size_t>(start + local)];
            if (raw_child < 0 || static_cast<std::size_t>(raw_child) >= count) continue;
            const auto child = static_cast<std::size_t>(raw_child);
            const auto raw_parent = context.baseline_parents[child];
            if (raw_parent < 0 || static_cast<std::size_t>(raw_parent) >= count ||
                !is_move(context.proxy_attributes[child])) {
                continue;
            }
            const auto parent = static_cast<std::size_t>(raw_parent);
            const auto parent_rotation = load_quaternion(work_rotations, parent);
            const Vec3 target_direction = rotate_vector(
                parent_rotation, local_positions[child]
            );
            const Vec3 current {
                context.state_positions[child * 3 + 0] -
                    context.state_positions[parent * 3 + 0],
                context.state_positions[child * 3 + 1] -
                    context.state_positions[parent * 3 + 1],
                context.state_positions[child * 3 + 2] -
                    context.state_positions[parent * 3 + 2],
            };
            const float target_length = length(target_direction);
            const float current_length = length(current);
            if (target_length <= kMc2Epsilon || current_length <= kMc2Epsilon) continue;
            const Vec3 target_vector = mul(
                target_direction, current_length / target_length
            );
            const auto offset = child * 3;
            vectors[offset + 0] = target_vector.x;
            vectors[offset + 1] = target_vector.y;
            vectors[offset + 2] = target_vector.z;
            targets[offset + 0] = context.state_positions[parent * 3 + 0] + target_vector.x;
            targets[offset + 1] = context.state_positions[parent * 3 + 1] + target_vector.y;
            targets[offset + 2] = context.state_positions[parent * 3 + 2] + target_vector.z;
            valid[child] = 1;

            const auto base_rotation = quaternion_multiply(
                parent_rotation, local_rotations[child]
            );
            store_quaternion(
                work_rotations,
                child,
                quaternion_multiply(
                    quaternion_from_to(target_direction, current),
                    base_rotation
                )
            );
        }
    }
}

}  // namespace

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
    std::memcpy(inverse_masses.view.buf, context->self_primitive_inverse_masses.data(),
                context->self_primitive_inverse_masses.size() * sizeof(float));
    std::memcpy(aabb_min.view.buf, context->self_primitive_aabb_min.data(),
                context->self_primitive_aabb_min.size() * sizeof(float));
    std::memcpy(aabb_max.view.buf, context->self_primitive_aabb_max.data(),
                context->self_primitive_aabb_max.size() * sizeof(float));
    std::memcpy(thickness.view.buf, context->self_primitive_thickness.data(),
                context->self_primitive_thickness.size() * sizeof(float));
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_debug_self_indices(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_debug_self_indices expects 2 arguments"
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
    Buffer indices;
    if (!indices.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_particle_indices"
        )) {
        return nullptr;
    }
    if (!expect_int32(indices, "out_self_particle_indices") ||
        !expect_2d(indices, "out_self_particle_indices", count, 3)) {
        return nullptr;
    }
    std::memcpy(
        indices.view.buf,
        context->self_particle_indices.data(),
        context->self_particle_indices.size() * sizeof(std::int32_t)
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
    Buffer* outputs[] = {&particle_indices, &grids, &hashes, &starts, &counts};
    const char* names[] = {
        "out_self_particle_indices", "out_self_primitive_grids",
        "out_self_grid_hashes", "out_self_grid_starts", "out_self_grid_counts",
    };
    for (std::size_t index = 0; index < 5; ++index) {
        if (!outputs[index]->get(
                PyTuple_GET_ITEM(args, static_cast<Py_ssize_t>(index + 1)),
                PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE, names[index])) {
            return nullptr;
        }
    }
    if (!expect_int32(particle_indices, names[0]) ||
        !expect_2d(particle_indices, names[0], count, 3) ||
        !expect_int32(grids, names[1]) ||
        !expect_2d(grids, names[1], count, 3) ||
        !expect_int32(hashes, names[2]) ||
        !expect_1d_array(hashes, names[2], count) ||
        !expect_int32(starts, names[3]) ||
        !expect_1d_array(starts, names[3], count) ||
        !expect_int32(counts, names[4]) ||
        !expect_1d_array(counts, names[4], count)) {
        return nullptr;
    }
    std::memcpy(particle_indices.view.buf, context->self_particle_indices.data(),
                context->self_particle_indices.size() * sizeof(std::int32_t));
    std::memcpy(grids.view.buf, context->self_primitive_grids.data(),
                context->self_primitive_grids.size() * sizeof(std::int32_t));
    std::memcpy(hashes.view.buf, context->self_grid_hashes.data(),
                context->self_grid_hashes.size() * sizeof(std::int32_t));
    std::memcpy(starts.view.buf, context->self_grid_starts.data(),
                context->self_grid_starts.size() * sizeof(std::int32_t));
    std::memcpy(counts.view.buf, context->self_grid_counts.data(),
                context->self_grid_counts.size() * sizeof(std::int32_t));
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_debug_self_grid(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 5) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_debug_self_grid expects 5 arguments"
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
    Buffer grids, hashes, starts, counts;
    if (!grids.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_primitive_grids"
        ) ||
        !hashes.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_grid_hashes"
        ) ||
        !starts.get(
            PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_grid_starts"
        ) ||
        !counts.get(
            PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_grid_counts"
        )) {
        return nullptr;
    }
    if (!expect_int32(grids, "out_self_primitive_grids") ||
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

PyObject* mc2_context_v0_read_debug_self_candidates(PyObject* self, PyObject* args) {
    return mc2_context_v0_read_self_collision_candidates(self, args);
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
    Buffer* outputs[] = {&indices, &types, &enabled, &thickness, &s, &t, &normals};
    const char* names[] = {
        "out_self_contact_indices", "out_self_contact_types",
        "out_self_contact_enabled", "out_self_contact_thickness",
        "out_self_contact_s", "out_self_contact_t", "out_self_contact_normals",
    };
    for (std::size_t index = 0; index < 7; ++index) {
        if (!outputs[index]->get(
                PyTuple_GET_ITEM(args, static_cast<Py_ssize_t>(index + 1)),
                PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE, names[index])) {
            return nullptr;
        }
    }
    if (!expect_int32(indices, names[0]) ||
        !expect_2d(indices, names[0], count, 2) ||
        !expect_int32(types, names[1]) ||
        !expect_1d_array(types, names[1], count) ||
        !expect_uint8_scalar_array(enabled, names[2]) ||
        !expect_1d_array(enabled, names[2], count) ||
        !expect_float32(thickness, names[3]) ||
        !expect_1d_array(thickness, names[3], count) ||
        !expect_float32(s, names[4]) ||
        !expect_1d_array(s, names[4], count) ||
        !expect_float32(t, names[5]) ||
        !expect_1d_array(t, names[5], count) ||
        !expect_float32(normals, names[6]) ||
        !expect_2d(normals, names[6], count, 3)) {
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

PyObject* mc2_context_v0_read_debug_self_contacts(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 7) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_debug_self_contacts expects 7 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->self_contact_ready || !context->self_contact_debug_ready) {
        PyErr_SetString(PyExc_RuntimeError, "self-collision contact debug is not ready");
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->self_contact_types.size());
    Buffer indices, types, enabled, thickness, normals, corrections;
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
        !normals.get(
            PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_normals"
        ) ||
        !corrections.get(
            PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_contact_corrections"
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
        !expect_float32(normals, "out_self_contact_normals") ||
        !expect_2d(normals, "out_self_contact_normals", count, 3) ||
        !expect_float32(corrections, "out_self_contact_corrections") ||
        !expect_3d(corrections, "out_self_contact_corrections", count, 2, 3)) {
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
    std::memcpy(normals.view.buf, context->self_contact_normals.data(),
                context->self_contact_normals.size() * sizeof(float));
    std::memcpy(corrections.view.buf, context->debug_self_contact_corrections.data(),
                context->debug_self_contact_corrections.size() * sizeof(float));
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
        !expect_1d_array(particle_flags, "out_self_particle_intersect_flags", vertex_count) ||
        !expect_uint32_scalar_array(primitive_flags, "out_self_primitive_flags") ||
        !expect_1d_array(primitive_flags, "out_self_primitive_flags", primitive_count)) {
        return nullptr;
    }
    std::memcpy(records.view.buf, context->self_intersect_records.data(),
                context->self_intersect_records.size() * sizeof(std::int32_t));
    std::memcpy(particle_flags.view.buf, context->self_particle_intersect_flags.data(),
                context->self_particle_intersect_flags.size() * sizeof(std::uint8_t));
    std::memcpy(primitive_flags.view.buf, context->self_primitive_flags.data(),
                context->self_primitive_flags.size() * sizeof(std::uint32_t));
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_debug_self_intersections(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_debug_self_intersections expects 2 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->self_intersect_flags_ready) {
        PyErr_SetString(PyExc_RuntimeError, "final self-collision intersections are not ready");
        return nullptr;
    }
    const auto record_count = static_cast<Py_ssize_t>(
        context->self_intersect_records.size() / 5
    );
    Buffer records;
    if (!records.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_self_intersect_records"
        )) {
        return nullptr;
    }
    if (!expect_int32(records, "out_self_intersect_records") ||
        !expect_2d(records, "out_self_intersect_records", record_count, 5)) {
        return nullptr;
    }
    std::memcpy(
        records.view.buf,
        context->self_intersect_records.data(),
        context->self_intersect_records.size() * sizeof(std::int32_t)
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

PyObject* mc2_context_v0_read_debug_motion_base(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 3) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_read_debug_motion_base expects 3 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto count = static_cast<std::size_t>(context->vertex_count);
    if (!context->initialized ||
        context->animated_base_positions.size() != count * 3 ||
        context->animated_base_rotations.size() != count * 4) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 debug Motion Base state is not ready");
        return nullptr;
    }
    Buffer positions, rotations;
    if (!positions.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_motion_base_positions"
        ) ||
        !rotations.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_motion_base_rotations"
        )) {
        return nullptr;
    }
    const auto vertex_count = static_cast<Py_ssize_t>(context->vertex_count);
    if (!expect_float32(positions, "out_motion_base_positions") ||
        !expect_2d(positions, "out_motion_base_positions", vertex_count, 3) ||
        !expect_float32(rotations, "out_motion_base_rotations") ||
        !expect_2d(rotations, "out_motion_base_rotations", vertex_count, 4)) {
        return nullptr;
    }
    std::memcpy(
        positions.view.buf, context->animated_base_positions.data(),
        context->animated_base_positions.size() * sizeof(float)
    );
    std::memcpy(
        rotations.view.buf, context->animated_base_rotations.data(),
        context->animated_base_rotations.size() * sizeof(float)
    );
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_debug_baseline(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_debug_baseline expects 4 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto count = static_cast<std::size_t>(context->vertex_count);
    if (context->baseline_parents.size() != count ||
        context->baseline_roots.size() != count ||
        context->baseline_depths.size() != count) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 debug baseline state is not ready");
        return nullptr;
    }
    Buffer parents, roots, depths;
    if (!parents.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_baseline_parents"
        ) ||
        !roots.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_baseline_roots"
        ) ||
        !depths.get(
            PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_baseline_depths"
        )) {
        return nullptr;
    }
    const auto vertex_count = static_cast<Py_ssize_t>(context->vertex_count);
    if (!expect_int32(parents, "out_baseline_parents") ||
        !expect_1d_array(parents, "out_baseline_parents", vertex_count) ||
        !expect_int32(roots, "out_baseline_roots") ||
        !expect_1d_array(roots, "out_baseline_roots", vertex_count) ||
        !expect_float32(depths, "out_baseline_depths") ||
        !expect_1d_array(depths, "out_baseline_depths", vertex_count)) {
        return nullptr;
    }
    std::memcpy(
        parents.view.buf,
        context->baseline_parents.data(),
        context->baseline_parents.size() * sizeof(std::int32_t)
    );
    std::memcpy(
        roots.view.buf,
        context->baseline_roots.data(),
        context->baseline_roots.size() * sizeof(std::int32_t)
    );
    std::memcpy(
        depths.view.buf,
        context->baseline_depths.data(),
        context->baseline_depths.size() * sizeof(float)
    );
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_debug_angle_restoration(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_debug_angle_restoration expects 4 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto count = static_cast<std::size_t>(context->vertex_count);
    if (!context->initialized ||
        context->step_basic_positions.size() != count * 3 ||
        context->state_positions.size() != count * 3 ||
        context->baseline_parents.size() != count ||
        context->proxy_attributes.size() != count) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 debug Angle Restoration state is not ready");
        return nullptr;
    }
    Buffer target_buffer, vector_buffer, valid_buffer;
    if (!target_buffer.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_angle_restoration_targets"
        ) ||
        !vector_buffer.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_angle_restoration_vectors"
        ) ||
        !valid_buffer.get(
            PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_angle_restoration_valid"
        )) {
        return nullptr;
    }
    const auto vertex_count = static_cast<Py_ssize_t>(context->vertex_count);
    if (!expect_float32(target_buffer, "out_angle_restoration_targets") ||
        !expect_2d(target_buffer, "out_angle_restoration_targets", vertex_count, 3) ||
        !expect_float32(vector_buffer, "out_angle_restoration_vectors") ||
        !expect_2d(vector_buffer, "out_angle_restoration_vectors", vertex_count, 3) ||
        !expect_uint8_scalar_array(valid_buffer, "out_angle_restoration_valid") ||
        !expect_1d_array(valid_buffer, "out_angle_restoration_valid", vertex_count)) {
        return nullptr;
    }
    auto* targets = static_cast<float*>(target_buffer.view.buf);
    auto* vectors = static_cast<float*>(vector_buffer.view.buf);
    auto* valid = static_cast<std::uint8_t*>(valid_buffer.view.buf);
    for (std::size_t vertex = 0; vertex < count; ++vertex) {
        const auto offset = vertex * 3;
        targets[offset + 0] = context->step_basic_positions[offset + 0];
        targets[offset + 1] = context->step_basic_positions[offset + 1];
        targets[offset + 2] = context->step_basic_positions[offset + 2];
        vectors[offset + 0] = 0.0f;
        vectors[offset + 1] = 0.0f;
        vectors[offset + 2] = 0.0f;
        valid[vertex] = 0;
        const auto parent = context->baseline_parents[vertex];
        if (parent < 0 || static_cast<std::size_t>(parent) >= count ||
            !is_move(context->proxy_attributes[vertex])) {
            continue;
        }
        const auto parent_offset = static_cast<std::size_t>(parent) * 3;
        vectors[offset + 0] = context->step_basic_positions[offset + 0] -
            context->step_basic_positions[parent_offset + 0];
        vectors[offset + 1] = context->step_basic_positions[offset + 1] -
            context->step_basic_positions[parent_offset + 1];
        vectors[offset + 2] = context->step_basic_positions[offset + 2] -
            context->step_basic_positions[parent_offset + 2];
        targets[offset + 0] = context->state_positions[parent_offset + 0] + vectors[offset + 0];
        targets[offset + 1] = context->state_positions[parent_offset + 1] + vectors[offset + 1];
        targets[offset + 2] = context->state_positions[parent_offset + 2] + vectors[offset + 2];
        valid[vertex] = 1;
    }
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_debug_angle_limit(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_debug_angle_limit expects 4 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto count = static_cast<std::size_t>(context->vertex_count);
    if (!context->initialized ||
        context->step_basic_positions.size() != count * 3 ||
        context->step_basic_rotations.size() != count * 4 ||
        context->state_positions.size() != count * 3) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 debug Angle Limit state is not ready");
        return nullptr;
    }
    Buffer target_buffer, vector_buffer, valid_buffer;
    if (!target_buffer.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_angle_limit_targets"
        ) ||
        !vector_buffer.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_angle_limit_vectors"
        ) ||
        !valid_buffer.get(
            PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_angle_limit_valid"
        )) {
        return nullptr;
    }
    const auto vertex_count = static_cast<Py_ssize_t>(context->vertex_count);
    if (!expect_float32(target_buffer, "out_angle_limit_targets") ||
        !expect_2d(target_buffer, "out_angle_limit_targets", vertex_count, 3) ||
        !expect_float32(vector_buffer, "out_angle_limit_vectors") ||
        !expect_2d(vector_buffer, "out_angle_limit_vectors", vertex_count, 3) ||
        !expect_uint8_scalar_array(valid_buffer, "out_angle_limit_valid") ||
        !expect_1d_array(valid_buffer, "out_angle_limit_valid", vertex_count)) {
        return nullptr;
    }
    auto* targets = static_cast<float*>(target_buffer.view.buf);
    auto* vectors = static_cast<float*>(vector_buffer.view.buf);
    auto* valid = static_cast<std::uint8_t*>(valid_buffer.view.buf);
    for (std::size_t vertex = 0; vertex < count; ++vertex) {
        const auto offset = vertex * 3;
        targets[offset + 0] = context->state_positions[offset + 0];
        targets[offset + 1] = context->state_positions[offset + 1];
        targets[offset + 2] = context->state_positions[offset + 2];
        vectors[offset + 0] = 0.0f;
        vectors[offset + 1] = 0.0f;
        vectors[offset + 2] = 0.0f;
        valid[vertex] = 0;
    }
    build_angle_limit_debug(*context, targets, vectors, valid);
    Py_RETURN_NONE;
}
PyObject* mc2_context_v0_read_debug_dynamics(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 3) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_debug_dynamics expects 3 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto count = static_cast<std::size_t>(context->vertex_count);
    if (!context->initialized ||
        context->state_velocities.size() != count * 3 ||
        context->particle_real_velocities.size() != count * 3) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 debug dynamics are not ready");
        return nullptr;
    }
    Buffer velocities, real_velocities;
    if (!velocities.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_state_velocities"
        ) ||
        !real_velocities.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_real_velocities"
        )) {
        return nullptr;
    }
    const auto vertex_count = static_cast<Py_ssize_t>(context->vertex_count);
    if (!expect_float32(velocities, "out_state_velocities") ||
        !expect_2d(velocities, "out_state_velocities", vertex_count, 3) ||
        !expect_float32(real_velocities, "out_real_velocities") ||
        !expect_2d(real_velocities, "out_real_velocities", vertex_count, 3)) {
        return nullptr;
    }
    std::memcpy(
        velocities.view.buf,
        context->state_velocities.data(),
        context->state_velocities.size() * sizeof(float)
    );
    std::memcpy(
        real_velocities.view.buf,
        context->particle_real_velocities.data(),
        context->particle_real_velocities.size() * sizeof(float)
    );
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_debug_distance_tether(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 5) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_debug_distance_tether expects 5 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto vertex_count = static_cast<std::size_t>(context->vertex_count);
    const auto record_count = context->distance_targets.size();
    if (!context->initialized ||
        context->baseline_roots.size() != vertex_count ||
        context->distance_ranges.size() != vertex_count * 2 ||
        context->distance_rest_signed.size() != record_count) {
        PyErr_SetString(
            PyExc_RuntimeError,
            "MC2 V0 debug distance/tether state is not ready"
        );
        return nullptr;
    }
    Buffer roots, ranges, targets, rests;
    if (!roots.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_baseline_roots"
        ) ||
        !ranges.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_distance_ranges"
        ) ||
        !targets.get(
            PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_distance_targets"
        ) ||
        !rests.get(
            PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_distance_rest_signed"
        )) {
        return nullptr;
    }
    const auto vertices = static_cast<Py_ssize_t>(vertex_count);
    const auto records = static_cast<Py_ssize_t>(record_count);
    if (!expect_int32(roots, "out_baseline_roots") ||
        !expect_1d_array(roots, "out_baseline_roots", vertices) ||
        !expect_int32(ranges, "out_distance_ranges") ||
        !expect_2d(ranges, "out_distance_ranges", vertices, 2) ||
        !expect_int32(targets, "out_distance_targets") ||
        !expect_1d_array(targets, "out_distance_targets", records) ||
        !expect_float32(rests, "out_distance_rest_signed") ||
        !expect_1d_array(rests, "out_distance_rest_signed", records)) {
        return nullptr;
    }
    std::memcpy(
        roots.view.buf,
        context->baseline_roots.data(),
        context->baseline_roots.size() * sizeof(std::int32_t)
    );
    std::memcpy(
        ranges.view.buf,
        context->distance_ranges.data(),
        context->distance_ranges.size() * sizeof(std::int32_t)
    );
    if (record_count > 0) {
        std::memcpy(
            targets.view.buf,
            context->distance_targets.data(),
            context->distance_targets.size() * sizeof(std::int32_t)
        );
        std::memcpy(
            rests.view.buf,
            context->distance_rest_signed.data(),
            context->distance_rest_signed.size() * sizeof(float)
        );
    }
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_debug_bending(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_debug_bending expects 4 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto record_count = context->bending_rest_angle_or_volume.size();
    if (!context->initialized ||
        context->bending_quads.size() != record_count * 4 ||
        context->bending_sign_or_volume.size() != record_count) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 debug bending state is not ready");
        return nullptr;
    }
    Buffer quads, rests, markers;
    if (!quads.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_bending_quads"
        ) ||
        !rests.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_bending_rests"
        ) ||
        !markers.get(
            PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_bending_markers"
        )) {
        return nullptr;
    }
    const auto records = static_cast<Py_ssize_t>(record_count);
    if (!expect_int32(quads, "out_bending_quads") ||
        !expect_2d(quads, "out_bending_quads", records, 4) ||
        !expect_float32(rests, "out_bending_rests") ||
        !expect_1d_array(rests, "out_bending_rests", records) ||
        !expect_int32(markers, "out_bending_markers") ||
        !expect_1d_array(markers, "out_bending_markers", records)) {
        return nullptr;
    }
    if (record_count > 0) {
        std::memcpy(
            quads.view.buf,
            context->bending_quads.data(),
            context->bending_quads.size() * sizeof(std::int32_t)
        );
        std::memcpy(
            rests.view.buf,
            context->bending_rest_angle_or_volume.data(),
            context->bending_rest_angle_or_volume.size() * sizeof(float)
        );
        auto* marker_values = static_cast<std::int32_t*>(markers.view.buf);
        for (std::size_t index = 0; index < record_count; ++index) {
            marker_values[index] = static_cast<std::int32_t>(
                context->bending_sign_or_volume[index]
            );
        }
    }
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_debug_constraint_results(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 3) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_debug_constraint_results expects 3 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto vertex_count = static_cast<std::size_t>(context->vertex_count);
    const auto row_count = debug_constraint_pass_count(
        context->debug_constraint_ready_mask
    ) * vertex_count;
    const auto value_count = row_count * 3;
    if (context->debug_constraint_request_mask == 0 ||
        context->debug_constraint_ready_mask == 0 ||
        context->debug_constraint_ready_mask != context->debug_constraint_request_mask ||
        context->debug_constraint_origins.size() != value_count ||
        context->debug_constraint_corrections.size() != value_count) {
        PyErr_SetString(
            PyExc_RuntimeError,
            "MC2 constraint debug was not requested or is not ready"
        );
        return nullptr;
    }
    Buffer origins, corrections;
    if (!origins.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_constraint_origins"
        ) ||
        !corrections.get(
            PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
            "out_constraint_corrections"
        )) {
        return nullptr;
    }
    const auto rows = static_cast<Py_ssize_t>(row_count);
    if (!expect_float32(origins, "out_constraint_origins") ||
        !expect_2d(origins, "out_constraint_origins", rows, 3) ||
        !expect_float32(corrections, "out_constraint_corrections") ||
        !expect_2d(corrections, "out_constraint_corrections", rows, 3)) {
        return nullptr;
    }
    if (value_count > 0) {
        std::memcpy(
            origins.view.buf,
            context->debug_constraint_origins.data(),
            value_count * sizeof(float)
        );
        std::memcpy(
            corrections.view.buf,
            context->debug_constraint_corrections.data(),
            value_count * sizeof(float)
        );
    }
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_debug_distance_results(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 6) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_debug_distance_results expects 6 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto record_count = context->distance_targets.size();
    const auto row_count = record_count * 2;
    const auto vector_value_count = row_count * 3;
    if ((context->debug_constraint_request_mask & kDebugConstraintDistance) == 0 ||
        !context->debug_distance_record_ready ||
        context->debug_distance_record_origins.size() != vector_value_count ||
        context->debug_distance_record_corrections.size() != vector_value_count ||
        context->debug_distance_record_lengths.size() != row_count ||
        context->debug_distance_record_rests.size() != row_count ||
        context->debug_distance_record_valid.size() != row_count) {
        PyErr_SetString(
            PyExc_RuntimeError,
            "MC2 distance record debug was not requested or is not ready"
        );
        return nullptr;
    }
    Buffer origins, corrections, lengths, rests, valid;
    Buffer* buffers[] = {&origins, &corrections, &lengths, &rests, &valid};
    const char* names[] = {
        "out_distance_record_origins",
        "out_distance_record_corrections",
        "out_distance_record_lengths",
        "out_distance_record_rests",
        "out_distance_record_valid",
    };
    for (std::size_t index = 0; index < 5; ++index) {
        if (!buffers[index]->get(
                PyTuple_GET_ITEM(args, static_cast<Py_ssize_t>(index + 1)),
                PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
                names[index]
            )) {
            return nullptr;
        }
    }
    const auto rows = static_cast<Py_ssize_t>(row_count);
    const auto records = static_cast<Py_ssize_t>(record_count);
    if (!expect_float32(origins, names[0]) ||
        !expect_2d(origins, names[0], rows, 3) ||
        !expect_float32(corrections, names[1]) ||
        !expect_2d(corrections, names[1], rows, 3) ||
        !expect_float32(lengths, names[2]) ||
        !expect_2d(lengths, names[2], 2, records) ||
        !expect_float32(rests, names[3]) ||
        !expect_2d(rests, names[3], 2, records) ||
        !expect_uint8_scalar_array(valid, names[4]) ||
        !expect_1d_array(valid, names[4], rows)) {
        return nullptr;
    }
    if (vector_value_count > 0) {
        std::memcpy(
            origins.view.buf,
            context->debug_distance_record_origins.data(),
            vector_value_count * sizeof(float)
        );
        std::memcpy(
            corrections.view.buf,
            context->debug_distance_record_corrections.data(),
            vector_value_count * sizeof(float)
        );
    }
    if (row_count > 0) {
        std::memcpy(
            lengths.view.buf,
            context->debug_distance_record_lengths.data(),
            row_count * sizeof(float)
        );
        std::memcpy(
            rests.view.buf,
            context->debug_distance_record_rests.data(),
            row_count * sizeof(float)
        );
        std::memcpy(
            valid.view.buf,
            context->debug_distance_record_valid.data(),
            row_count * sizeof(std::uint8_t)
        );
    }
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_debug_bending_results(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_debug_bending_results expects 4 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto record_count = context->bending_rest_angle_or_volume.size();
    const auto row_count = record_count * 4;
    const auto vector_value_count = row_count * 3;
    if ((context->debug_constraint_request_mask & kDebugConstraintBending) == 0 ||
        !context->debug_bending_record_ready ||
        context->debug_bending_record_origins.size() != vector_value_count ||
        context->debug_bending_record_corrections.size() != vector_value_count ||
        context->debug_bending_record_valid.size() != record_count) {
        PyErr_SetString(
            PyExc_RuntimeError,
            "MC2 bending record debug was not requested or is not ready"
        );
        return nullptr;
    }
    Buffer origins, corrections, valid;
    Buffer* buffers[] = {&origins, &corrections, &valid};
    const char* names[] = {
        "out_bending_record_origins",
        "out_bending_record_corrections",
        "out_bending_record_valid",
    };
    for (std::size_t index = 0; index < 3; ++index) {
        if (!buffers[index]->get(
                PyTuple_GET_ITEM(args, static_cast<Py_ssize_t>(index + 1)),
                PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
                names[index]
            )) {
            return nullptr;
        }
    }
    const auto rows = static_cast<Py_ssize_t>(row_count);
    const auto records = static_cast<Py_ssize_t>(record_count);
    if (!expect_float32(origins, names[0]) ||
        !expect_2d(origins, names[0], rows, 3) ||
        !expect_float32(corrections, names[1]) ||
        !expect_2d(corrections, names[1], rows, 3) ||
        !expect_uint8_scalar_array(valid, names[2]) ||
        !expect_1d_array(valid, names[2], records)) {
        return nullptr;
    }
    if (vector_value_count > 0) {
        std::memcpy(
            origins.view.buf,
            context->debug_bending_record_origins.data(),
            vector_value_count * sizeof(float)
        );
        std::memcpy(
            corrections.view.buf,
            context->debug_bending_record_corrections.data(),
            vector_value_count * sizeof(float)
        );
    }
    if (record_count > 0) {
        std::memcpy(
            valid.view.buf,
            context->debug_bending_record_valid.data(),
            record_count * sizeof(std::uint8_t)
        );
    }
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_debug_motion_results(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_debug_motion_results expects 4 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto record_count = static_cast<std::size_t>(context->vertex_count) * 2;
    const auto vector_value_count = record_count * 3;
    if ((context->debug_constraint_request_mask & kDebugConstraintMotion) == 0 ||
        !context->debug_motion_record_ready ||
        context->debug_motion_record_origins.size() != vector_value_count ||
        context->debug_motion_record_corrections.size() != vector_value_count ||
        context->debug_motion_record_valid.size() != record_count) {
        PyErr_SetString(
            PyExc_RuntimeError,
            "MC2 motion record debug was not requested or is not ready"
        );
        return nullptr;
    }
    Buffer origins, corrections, valid;
    Buffer* buffers[] = {&origins, &corrections, &valid};
    const char* names[] = {
        "out_motion_record_origins",
        "out_motion_record_corrections",
        "out_motion_record_valid",
    };
    for (std::size_t index = 0; index < 3; ++index) {
        if (!buffers[index]->get(
                PyTuple_GET_ITEM(args, static_cast<Py_ssize_t>(index + 1)),
                PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
                names[index]
            )) {
            return nullptr;
        }
    }
    const auto records = static_cast<Py_ssize_t>(record_count);
    if (!expect_float32(origins, names[0]) ||
        !expect_2d(origins, names[0], records, 3) ||
        !expect_float32(corrections, names[1]) ||
        !expect_2d(corrections, names[1], records, 3) ||
        !expect_uint8_scalar_array(valid, names[2]) ||
        !expect_1d_array(valid, names[2], records)) {
        return nullptr;
    }
    if (vector_value_count > 0) {
        std::memcpy(
            origins.view.buf,
            context->debug_motion_record_origins.data(),
            vector_value_count * sizeof(float)
        );
        std::memcpy(
            corrections.view.buf,
            context->debug_motion_record_corrections.data(),
            vector_value_count * sizeof(float)
        );
    }
    if (record_count > 0) {
        std::memcpy(
            valid.view.buf,
            context->debug_motion_record_valid.data(),
            record_count * sizeof(std::uint8_t)
        );
    }
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_debug_angle_results(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 8) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_debug_angle_results expects 8 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto record_count = context->baseline_data.size() *
        static_cast<std::size_t>(kMc2AngleIterationCount) * 2;
    const auto vector_value_count = record_count * 2 * 3;
    if ((context->debug_constraint_request_mask & kDebugConstraintAngle) == 0 ||
        !context->debug_angle_record_ready ||
        context->debug_angle_record_origins.size() != vector_value_count ||
        context->debug_angle_record_corrections.size() != vector_value_count ||
        context->debug_angle_record_currents.size() != record_count ||
        context->debug_angle_record_limits.size() != record_count ||
        context->debug_angle_record_children.size() != record_count ||
        context->debug_angle_record_parents.size() != record_count ||
        context->debug_angle_record_valid.size() != record_count) {
        PyErr_SetString(
            PyExc_RuntimeError,
            "MC2 angle record debug was not requested or is not ready"
        );
        return nullptr;
    }
    Buffer origins, corrections, currents, limits, children, parents, valid;
    Buffer* buffers[] = {
        &origins, &corrections, &currents, &limits, &children, &parents, &valid
    };
    const char* names[] = {
        "out_angle_record_origins",
        "out_angle_record_corrections",
        "out_angle_record_currents",
        "out_angle_record_limits",
        "out_angle_record_children",
        "out_angle_record_parents",
        "out_angle_record_valid",
    };
    for (std::size_t index = 0; index < 7; ++index) {
        if (!buffers[index]->get(
                PyTuple_GET_ITEM(args, static_cast<Py_ssize_t>(index + 1)),
                PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
                names[index]
            )) {
            return nullptr;
        }
    }
    const auto records = static_cast<Py_ssize_t>(record_count);
    if (!expect_float32(origins, names[0]) ||
        !expect_2d(origins, names[0], records * 2, 3) ||
        !expect_float32(corrections, names[1]) ||
        !expect_2d(corrections, names[1], records * 2, 3) ||
        !expect_float32(currents, names[2]) ||
        !expect_1d_array(currents, names[2], records) ||
        !expect_float32(limits, names[3]) ||
        !expect_1d_array(limits, names[3], records) ||
        !expect_int32(children, names[4]) ||
        !expect_1d_array(children, names[4], records) ||
        !expect_int32(parents, names[5]) ||
        !expect_1d_array(parents, names[5], records) ||
        !expect_uint8_scalar_array(valid, names[6]) ||
        !expect_1d_array(valid, names[6], records)) {
        return nullptr;
    }
    if (vector_value_count > 0) {
        std::memcpy(origins.view.buf, context->debug_angle_record_origins.data(),
                    vector_value_count * sizeof(float));
        std::memcpy(corrections.view.buf, context->debug_angle_record_corrections.data(),
                    vector_value_count * sizeof(float));
    }
    if (record_count > 0) {
        std::memcpy(currents.view.buf, context->debug_angle_record_currents.data(),
                    record_count * sizeof(float));
        std::memcpy(limits.view.buf, context->debug_angle_record_limits.data(),
                    record_count * sizeof(float));
        std::memcpy(children.view.buf, context->debug_angle_record_children.data(),
                    record_count * sizeof(std::int32_t));
        std::memcpy(parents.view.buf, context->debug_angle_record_parents.data(),
                    record_count * sizeof(std::int32_t));
        std::memcpy(valid.view.buf, context->debug_angle_record_valid.data(),
                    record_count * sizeof(std::uint8_t));
    }
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_read_debug_external_contacts(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 7) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_read_debug_external_contacts expects 7 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->external_contact_debug_requested ||
        !context->external_contact_debug_ready) {
        PyErr_SetString(
            PyExc_RuntimeError,
            "MC2 external contact debug was not requested or is not ready"
        );
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(
        context->external_contact_debug_records.size()
    );
    Buffer primitive_kinds, primitive_indices, collider_indices;
    Buffer positions, normals, corrections;
    Buffer* integer_buffers[] = {
        &primitive_kinds, &primitive_indices, &collider_indices
    };
    const char* integer_names[] = {
        "out_primitive_kinds", "out_primitive_indices", "out_collider_indices"
    };
    for (std::size_t index = 0; index < 3; ++index) {
        if (!integer_buffers[index]->get(
                PyTuple_GET_ITEM(args, static_cast<Py_ssize_t>(index + 1)),
                PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
                integer_names[index]
            ) ||
            !expect_int32(*integer_buffers[index], integer_names[index]) ||
            !expect_1d_array(*integer_buffers[index], integer_names[index], count)) {
            return nullptr;
        }
    }
    Buffer* vector_buffers[] = {&positions, &normals, &corrections};
    const char* vector_names[] = {
        "out_positions", "out_normals", "out_corrections"
    };
    for (std::size_t index = 0; index < 3; ++index) {
        if (!vector_buffers[index]->get(
                PyTuple_GET_ITEM(args, static_cast<Py_ssize_t>(index + 4)),
                PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
                vector_names[index]
            ) ||
            !expect_float32(*vector_buffers[index], vector_names[index]) ||
            !expect_2d(*vector_buffers[index], vector_names[index], count, 3)) {
            return nullptr;
        }
    }
    auto* kinds = static_cast<std::int32_t*>(primitive_kinds.view.buf);
    auto* primitives = static_cast<std::int32_t*>(primitive_indices.view.buf);
    auto* colliders = static_cast<std::int32_t*>(collider_indices.view.buf);
    auto* position_values = static_cast<float*>(positions.view.buf);
    auto* normal_values = static_cast<float*>(normals.view.buf);
    auto* correction_values = static_cast<float*>(corrections.view.buf);
    for (std::size_t index = 0; index < context->external_contact_debug_records.size(); ++index) {
        const auto& record = context->external_contact_debug_records[index];
        kinds[index] = record.primitive_kind;
        primitives[index] = record.primitive_index;
        colliders[index] = record.collider_index;
        for (std::size_t component = 0; component < 3; ++component) {
            position_values[index * 3 + component] = record.position[component];
            normal_values[index * 3 + component] = record.normal[component];
            correction_values[index * 3 + component] = record.correction[component];
        }
    }
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
