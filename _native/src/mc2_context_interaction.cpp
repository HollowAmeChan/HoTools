#include "mc2_api.hpp"

#include "mc2_context_internal.hpp"
#include "mc2_context_helpers.hpp"

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>

namespace hotools {

using namespace mc2_internal;
using namespace py;

// World-owned interaction ABI; per-slot state remains in Mc2ContextV0.
PyObject* mc2_interaction_v0_create(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 1) {
        PyErr_SetString(PyExc_TypeError, "mc2_interaction_v0_create expects 1 argument");
        return nullptr;
    }
    const long schema = as_long(PyTuple_GET_ITEM(args, 0), "schema_version");
    if (PyErr_Occurred()) return nullptr;
    if (schema != kSchemaVersion) {
        PyErr_SetString(PyExc_ValueError, "unsupported MC2 interaction schema version");
        return nullptr;
    }
    auto* interaction = new Mc2InteractionV0();
    PyObject* capsule = PyCapsule_New(
        interaction,
        kInteractionCapsuleName,
        destroy_interaction
    );
    if (capsule == nullptr) {
        delete interaction;
        return nullptr;
    }
    return capsule;
}

PyObject* mc2_interaction_v0_inspect(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 1) {
        PyErr_SetString(PyExc_TypeError, "mc2_interaction_v0_inspect expects 1 argument");
        return nullptr;
    }
    auto* interaction = interaction_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(interaction)) return nullptr;
    const auto& aggregate = interaction->aggregate;
    const std::int64_t estimated_bytes = static_cast<std::int64_t>(
        aggregate.state_positions.size() * sizeof(float) +
        interaction->old_positions.size() * sizeof(float) +
        aggregate.self_primitive_flags.size() * sizeof(std::uint32_t) +
        aggregate.self_particle_indices.size() * sizeof(std::int32_t) +
        aggregate.self_primitive_depths.size() * sizeof(float) +
        aggregate.self_primitive_inverse_masses.size() * sizeof(float) +
        aggregate.self_primitive_aabb_min.size() * sizeof(float) +
        aggregate.self_primitive_aabb_max.size() * sizeof(float) +
        aggregate.self_primitive_thickness.size() * sizeof(float) +
        aggregate.self_primitive_owner_indices.size() * sizeof(std::int32_t) +
        aggregate.self_primitive_grids.size() * sizeof(std::int32_t) +
        aggregate.self_grid_hashes.size() * sizeof(std::int32_t) +
        aggregate.self_grid_starts.size() * sizeof(std::int32_t) +
        aggregate.self_grid_counts.size() * sizeof(std::int32_t) +
        aggregate.self_contact_candidates.size() * sizeof(std::int32_t) +
        aggregate.self_contact_primitive_indices.size() * sizeof(std::int32_t) +
        aggregate.self_contact_types.size() * sizeof(std::int32_t) +
        aggregate.self_contact_enabled.size() * sizeof(std::uint8_t) +
        aggregate.self_contact_thickness.size() * sizeof(float) +
        aggregate.self_contact_s.size() * sizeof(float) +
        aggregate.self_contact_t.size() * sizeof(float) +
        aggregate.self_contact_normals.size() * sizeof(float) +
        aggregate.self_intersect_records.size() * sizeof(std::int32_t) +
        aggregate.self_particle_intersect_flags.size() * sizeof(std::uint8_t)
    );
    PyObject* result = PyDict_New();
    if (result == nullptr) return nullptr;
    if (!dict_string(result, "schema", "mc2_interaction_v0") ||
        !dict_i64(result, "schema_version", kSchemaVersion) ||
        !dict_i64(result, "scope_revision", interaction->scope_revision) ||
        !dict_i64(result, "step_count", interaction->step_count) ||
        !dict_i64(
            result,
            "participant_count",
            static_cast<std::int64_t>(interaction->participants.size())
        ) ||
        !dict_i64(result, "pair_count", interaction->pair_count) ||
        !dict_i64(result, "vertex_count", interaction->aggregate.vertex_count) ||
        !dict_i64(
            result,
            "point_primitive_count",
            aggregate.self_point_primitive_count
        ) ||
        !dict_i64(
            result,
            "edge_primitive_count",
            aggregate.self_edge_primitive_count
        ) ||
        !dict_i64(
            result,
            "triangle_primitive_count",
            aggregate.self_triangle_primitive_count
        ) ||
        !dict_i64(
            result,
            "primitive_count",
            static_cast<std::int64_t>(
                interaction->aggregate.self_primitive_flags.size()
            )
        ) ||
        !dict_i64(result, "candidate_count", interaction->candidate_count) ||
        !dict_i64(result, "contact_count", interaction->contact_count) ||
        !dict_i64(
            result,
            "grid_count",
            aggregate.self_point_grid_count +
                aggregate.self_edge_grid_count +
                aggregate.self_triangle_grid_count
        ) ||
        !dict_i64(result, "estimated_bytes", estimated_bytes) ||
        !dict_float(result, "max_primitive_size", aggregate.self_max_primitive_size) ||
        !dict_float(result, "grid_size", aggregate.self_grid_size) ||
        !dict_i64(
            result,
            "intersect_record_count",
            interaction->intersect_record_count
        ) ||
        !dict_bool(result, "released", interaction->released)) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}

PyObject* mc2_interaction_v0_step_group(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 9) {
        PyErr_SetString(PyExc_TypeError, "mc2_interaction_v0_step_group expects 9 arguments");
        return nullptr;
    }
    auto* interaction = interaction_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(interaction)) return nullptr;
    PyObject* context_sequence = PySequence_Fast(
        PyTuple_GET_ITEM(args, 1), "contexts must be a sequence"
    );
    PyObject* group_sequence = PySequence_Fast(
        PyTuple_GET_ITEM(args, 2), "primary_group_bits must be a sequence"
    );
    PyObject* mask_sequence = PySequence_Fast(
        PyTuple_GET_ITEM(args, 3), "collided_by_groups must be a sequence"
    );
    if (context_sequence == nullptr || group_sequence == nullptr || mask_sequence == nullptr) {
        Py_XDECREF(context_sequence);
        Py_XDECREF(group_sequence);
        Py_XDECREF(mask_sequence);
        return nullptr;
    }
    const auto count = PySequence_Fast_GET_SIZE(context_sequence);
    if (PySequence_Fast_GET_SIZE(group_sequence) != count ||
        PySequence_Fast_GET_SIZE(mask_sequence) != count) {
        Py_DECREF(context_sequence);
        Py_DECREF(group_sequence);
        Py_DECREF(mask_sequence);
        PyErr_SetString(PyExc_ValueError, "interaction metadata length mismatch");
        return nullptr;
    }
    const double dt = as_double(PyTuple_GET_ITEM(args, 4), "dt");
    const double simulation_power_y = as_double(
        PyTuple_GET_ITEM(args, 5), "simulation_power_y"
    );
    const double simulation_power_z = as_double(
        PyTuple_GET_ITEM(args, 6), "simulation_power_z"
    );
    const double simulation_power_w = as_double(
        PyTuple_GET_ITEM(args, 7), "simulation_power_w"
    );
    const int final_substep_value = PyObject_IsTrue(PyTuple_GET_ITEM(args, 8));
    if (PyErr_Occurred() || final_substep_value < 0 ||
        !std::isfinite(dt) || dt < 0.0 ||
        !std::isfinite(simulation_power_y) || simulation_power_y < 0.0 ||
        !std::isfinite(simulation_power_z) || simulation_power_z < 0.0 ||
        !std::isfinite(simulation_power_w) || simulation_power_w < 0.0) {
        Py_DECREF(context_sequence);
        Py_DECREF(group_sequence);
        Py_DECREF(mask_sequence);
        if (!PyErr_Occurred()) {
            PyErr_SetString(
                PyExc_ValueError,
                "dt and simulation powers must be finite and non-negative"
            );
        }
        return nullptr;
    }
    if (dt <= kMc2Epsilon) {
        Py_DECREF(context_sequence);
        Py_DECREF(group_sequence);
        Py_DECREF(mask_sequence);
        Py_RETURN_NONE;
    }

    std::vector<Mc2ContextV0*> contexts;
    std::vector<std::int32_t> primary_group_bits;
    std::vector<std::int32_t> collided_by_groups;
    std::vector<std::uintptr_t> scope_identity;
    contexts.reserve(static_cast<std::size_t>(count));
    primary_group_bits.reserve(static_cast<std::size_t>(count));
    collided_by_groups.reserve(static_cast<std::size_t>(count));
    for (Py_ssize_t index = 0; index < count; ++index) {
        auto* context = context_from(PySequence_Fast_GET_ITEM(context_sequence, index));
        if (!ensure_live(context)) {
            Py_DECREF(context_sequence);
            Py_DECREF(group_sequence);
            Py_DECREF(mask_sequence);
            return nullptr;
        }
        if (!context->parameters_ready || !context->dynamic_ready || !context->initialized) {
            Py_DECREF(context_sequence);
            Py_DECREF(group_sequence);
            Py_DECREF(mask_sequence);
            PyErr_SetString(PyExc_RuntimeError, "MC2 V0 context is not ready to step");
            return nullptr;
        }
        const long group_bit = as_long(
            PySequence_Fast_GET_ITEM(group_sequence, index),
            "primary_group_bit"
        );
        const long mask = as_long(
            PySequence_Fast_GET_ITEM(mask_sequence, index),
            "collided_by_groups"
        );
        if (PyErr_Occurred() || group_bit <= 0 || group_bit > 0x8000 ||
            (group_bit & (group_bit - 1)) != 0 || mask < 0 || mask > 0xFFFF) {
            Py_DECREF(context_sequence);
            Py_DECREF(group_sequence);
            Py_DECREF(mask_sequence);
            if (!PyErr_Occurred()) {
                PyErr_SetString(PyExc_ValueError, "invalid MC2 interaction group metadata");
            }
            return nullptr;
        }
        contexts.push_back(context);
        primary_group_bits.push_back(static_cast<std::int32_t>(group_bit));
        collided_by_groups.push_back(static_cast<std::int32_t>(mask));
        const bool interactive = context->setup_kind == 0 &&
            context->int_values.size() == static_cast<std::size_t>(kIntCount) &&
            context->int_values[kSelfCollisionSyncMode] != 0;
        if (interactive) {
            scope_identity.push_back(reinterpret_cast<std::uintptr_t>(context));
            scope_identity.push_back(static_cast<std::uintptr_t>(group_bit));
            scope_identity.push_back(static_cast<std::uintptr_t>(mask));
        }
    }
    Py_DECREF(context_sequence);
    Py_DECREF(group_sequence);
    Py_DECREF(mask_sequence);

    const bool same_scope = interaction_scope_matches(*interaction, scope_identity);
    if (same_scope && !interaction->participants.empty() &&
        interaction->aggregate.self_grid_dynamic_ready) {
        interaction->aggregate.frame = interaction->participants.front().context->frame;
        interaction->aggregate.generation =
            interaction->participants.front().context->generation;
        detect_self_collision_intersections_once(interaction->aggregate);
    }

    std::vector<Mc2ContextStepStateV0> states(contexts.size());
    for (std::size_t index = 0; index < contexts.size(); ++index) {
        if (!begin_mc2_context_step(
                *contexts[index],
                static_cast<float>(dt),
                static_cast<float>(simulation_power_y),
                static_cast<float>(simulation_power_z),
                static_cast<float>(simulation_power_w),
                states[index])) {
            return nullptr;
        }
    }

    interaction->participants.clear();
    for (std::size_t index = 0; index < contexts.size(); ++index) {
        auto* context = contexts[index];
        const bool interactive = context->setup_kind == 0 &&
            context->int_values.size() == static_cast<std::size_t>(kIntCount) &&
            context->int_values[kSelfCollisionSyncMode] != 0 &&
            context->self_primitive_dynamic_ready;
        if (!interactive) continue;
        interaction->participants.push_back(Mc2InteractionParticipantV0 {
            context,
            primary_group_bits[index],
            collided_by_groups[index],
            0,
            index,
        });
    }
    interaction->pair_count = 0;
    for (std::size_t left = 0; left < interaction->participants.size(); ++left) {
        for (std::size_t right = left + 1; right < interaction->participants.size(); ++right) {
            const auto& a = interaction->participants[left];
            const auto& b = interaction->participants[right];
            const bool allows_a = a.collided_by_groups == 0 ||
                (a.collided_by_groups & b.primary_group_bit) != 0;
            const bool allows_b = b.collided_by_groups == 0 ||
                (b.collided_by_groups & a.primary_group_bit) != 0;
            if (allows_a && allows_b) ++interaction->pair_count;
        }
    }
    if (interaction->participants.size() >= 2) {
        build_and_solve_interaction(*interaction, states);
    } else {
        interaction->candidate_count = 0;
        interaction->contact_count = 0;
        interaction->intersect_record_count = 0;
    }

    const bool is_final_substep = final_substep_value != 0;
    for (auto& state : states) {
        finish_mc2_context_step(state, static_cast<float>(dt), is_final_substep);
    }
    if (is_final_substep && interaction->participants.size() >= 2) {
        finish_interaction_intersections(*interaction);
    }
    ++interaction->step_count;
    Py_RETURN_NONE;
}

PyObject* mc2_interaction_v0_read_debug(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 13) {
        PyErr_SetString(PyExc_TypeError, "mc2_interaction_v0_read_debug expects 13 arguments");
        return nullptr;
    }
    auto* interaction = interaction_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(interaction)) return nullptr;
    auto& aggregate = interaction->aggregate;
    if (!aggregate.self_primitive_dynamic_ready) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 interaction debug state is not ready");
        return nullptr;
    }
    const long flags = PyLong_AsLong(PyTuple_GET_ITEM(args, 1));
    if (flags == -1 && PyErr_Occurred()) return nullptr;
    constexpr long kDebugGrid = 1l << 1l;
    constexpr long kDebugCandidates = 1l << 2l;
    constexpr long kDebugContacts = 1l << 3l;
    const auto vertex_count = static_cast<Py_ssize_t>(aggregate.vertex_count);
    const auto primitive_count = static_cast<Py_ssize_t>(
        aggregate.self_primitive_flags.size()
    );
    const auto candidate_count = static_cast<Py_ssize_t>(
        aggregate.self_contact_candidates.size() / 3
    );
    const auto contact_count = static_cast<Py_ssize_t>(
        aggregate.self_contact_types.size()
    );
    const auto intersect_count = static_cast<Py_ssize_t>(
        aggregate.self_intersect_records.size() / 5
    );
    const auto grid_count = (flags & kDebugGrid) != 0 ? primitive_count : 0;
    const auto requested_candidate_count = (flags & kDebugCandidates) != 0
        ? candidate_count : 0;
    const auto requested_contact_count = (flags & kDebugContacts) != 0
        ? contact_count : 0;
    const auto requested_intersect_count = (flags & kDebugContacts) != 0
        ? intersect_count : 0;
    Buffer positions, particle_indices, owner_indices, grids, candidates;
    Buffer contact_indices, contact_types, contact_enabled, contact_thickness;
    Buffer contact_normals, intersect_records;
    Buffer* buffers[] = {
        &positions, &particle_indices, &owner_indices, &grids, &candidates,
        &contact_indices, &contact_types, &contact_enabled, &contact_thickness,
        &contact_normals, &intersect_records,
    };
    const char* names[] = {
        "out_positions", "out_particle_indices", "out_owner_indices",
        "out_grids", "out_candidates", "out_contact_indices",
        "out_contact_types", "out_contact_enabled", "out_contact_thickness",
        "out_contact_normals", "out_intersect_records",
    };
    for (std::size_t index = 0; index < 11; ++index) {
        if (!buffers[index]->get(
                PyTuple_GET_ITEM(args, static_cast<Py_ssize_t>(index + 2)),
                PyBUF_FORMAT | PyBUF_ND | PyBUF_WRITABLE,
                names[index])) {
            return nullptr;
        }
    }
    if (!expect_float32(positions, names[0]) ||
        !expect_2d(positions, names[0], vertex_count, 3) ||
        !expect_int32(particle_indices, names[1]) ||
        !expect_2d(particle_indices, names[1], primitive_count, 3) ||
        !expect_int32(owner_indices, names[2]) ||
        !expect_1d_array(owner_indices, names[2], primitive_count) ||
        !expect_int32(grids, names[3]) ||
        !expect_2d(grids, names[3], grid_count, 3) ||
        !expect_int32(candidates, names[4]) ||
        !expect_2d(candidates, names[4], requested_candidate_count, 3) ||
        !expect_int32(contact_indices, names[5]) ||
        !expect_2d(contact_indices, names[5], requested_contact_count, 2) ||
        !expect_int32(contact_types, names[6]) ||
        !expect_1d_array(contact_types, names[6], requested_contact_count) ||
        !expect_uint8_scalar_array(contact_enabled, names[7]) ||
        !expect_1d_array(contact_enabled, names[7], requested_contact_count) ||
        !expect_float32(contact_thickness, names[8]) ||
        !expect_1d_array(contact_thickness, names[8], requested_contact_count) ||
        !expect_float32(contact_normals, names[9]) ||
        !expect_2d(contact_normals, names[9], requested_contact_count, 3) ||
        !expect_int32(intersect_records, names[10]) ||
        !expect_2d(intersect_records, names[10], requested_intersect_count, 5)) {
        return nullptr;
    }
    auto copy = [](Buffer& output, const auto& source) {
        if (source.empty()) return;
        std::memcpy(output.view.buf, source.data(), source.size() * sizeof(source[0]));
    };
    copy(positions, aggregate.state_positions);
    copy(particle_indices, aggregate.self_particle_indices);
    copy(owner_indices, aggregate.self_primitive_owner_indices);
    if ((flags & kDebugGrid) != 0) copy(grids, aggregate.self_primitive_grids);
    if ((flags & kDebugCandidates) != 0) {
        copy(candidates, aggregate.self_contact_candidates);
    }
    if ((flags & kDebugContacts) != 0) {
        copy(contact_indices, aggregate.self_contact_primitive_indices);
        copy(contact_types, aggregate.self_contact_types);
        copy(contact_enabled, aggregate.self_contact_enabled);
        copy(contact_thickness, aggregate.self_contact_thickness);
        copy(contact_normals, aggregate.self_contact_normals);
        copy(intersect_records, aggregate.self_intersect_records);
    }
    Py_RETURN_NONE;
}

PyObject* mc2_interaction_v0_free(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 1) {
        PyErr_SetString(PyExc_TypeError, "mc2_interaction_v0_free expects 1 argument");
        return nullptr;
    }
    auto* interaction = interaction_from(PyTuple_GET_ITEM(args, 0));
    if (interaction == nullptr) return nullptr;
    release_interaction(*interaction);
    Py_RETURN_NONE;
}

}  // namespace hotools
