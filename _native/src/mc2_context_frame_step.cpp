#include "mc2_api.hpp"

#include "mc2_context_internal.hpp"
#include "mc2_context_helpers.hpp"
#include "python_buffer_utils.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>

namespace hotools {

using namespace mc2_internal;
using namespace py;

PyObject* mc2_context_v0_update_center_dynamic(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 14) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_center_dynamic expects 14 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->center_static_ready || !context->parameters_ready) {
        PyErr_SetString(PyExc_RuntimeError, "Center dynamic requires Center static and parameters");
        return nullptr;
    }
    Buffer old_frame_position, frame_position, old_frame_rotation, frame_rotation;
    Buffer old_frame_scale, frame_scale, old_world_position, old_world_rotation;
    Buffer initial_scale, negative_scale_direction;
    if (!old_frame_position.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "center_old_frame_world_position") ||
        !frame_position.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "center_frame_world_position") ||
        !old_frame_rotation.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "center_old_frame_world_rotation") ||
        !frame_rotation.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "center_frame_world_rotation") ||
        !old_frame_scale.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "center_old_frame_world_scale") ||
        !frame_scale.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "center_frame_world_scale") ||
        !old_world_position.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "center_old_world_position") ||
        !old_world_rotation.get(PyTuple_GET_ITEM(args, 8), PyBUF_FORMAT | PyBUF_ND, "center_old_world_rotation") ||
        !initial_scale.get(PyTuple_GET_ITEM(args, 9), PyBUF_FORMAT | PyBUF_ND, "center_initial_scale") ||
        !negative_scale_direction.get(PyTuple_GET_ITEM(args, 10), PyBUF_FORMAT | PyBUF_ND, "center_negative_scale_direction")) {
        return nullptr;
    }
    Buffer* vectors3[] = {
        &old_frame_position, &frame_position, &old_frame_scale, &frame_scale,
        &old_world_position, &initial_scale, &negative_scale_direction,
    };
    const char* vector3_names[] = {
        "center_old_frame_world_position", "center_frame_world_position",
        "center_old_frame_world_scale", "center_frame_world_scale",
        "center_old_world_position", "center_initial_scale",
        "center_negative_scale_direction",
    };
    for (std::size_t index = 0; index < 7; ++index) {
        if (!expect_float32(*vectors3[index], vector3_names[index]) ||
            !expect_1d_array(*vectors3[index], vector3_names[index], 3) ||
            !finite_floats(*vectors3[index], vector3_names[index])) {
            return nullptr;
        }
    }
    Buffer* quaternions[] = {&old_frame_rotation, &frame_rotation, &old_world_rotation};
    const char* quaternion_names[] = {
        "center_old_frame_world_rotation", "center_frame_world_rotation",
        "center_old_world_rotation",
    };
    for (std::size_t index = 0; index < 3; ++index) {
        if (!expect_float32(*quaternions[index], quaternion_names[index]) ||
            !expect_1d_array(*quaternions[index], quaternion_names[index], 4) ||
            !finite_floats(*quaternions[index], quaternion_names[index])) {
            return nullptr;
        }
        const auto* values = static_cast<const float*>(quaternions[index]->view.buf);
        float length_squared = 0.0f;
        for (std::size_t component = 0; component < 4; ++component) {
            length_squared += values[component] * values[component];
        }
        if (std::fabs(length_squared - 1.0f) > 2.0e-5f) {
            PyErr_Format(PyExc_ValueError, "%s must contain a unit quaternion", quaternion_names[index]);
            return nullptr;
        }
    }
    const double distance_weight = as_double(PyTuple_GET_ITEM(args, 11), "center_distance_weight");
    const double frame_interpolation = as_double(
        PyTuple_GET_ITEM(args, 12), "center_frame_interpolation"
    );
    const double velocity_weight = as_double(
        PyTuple_GET_ITEM(args, 13), "center_velocity_weight"
    );
    if (PyErr_Occurred()) return nullptr;
    if (!std::isfinite(distance_weight) || distance_weight < 0.0 || distance_weight > 1.0 ||
        !std::isfinite(frame_interpolation) || frame_interpolation < 0.0 || frame_interpolation > 1.0 ||
        !std::isfinite(velocity_weight) || velocity_weight < 0.0 || velocity_weight > 1.0) {
        PyErr_SetString(PyExc_ValueError, "Center dynamic weights must be in 0..1");
        return nullptr;
    }
    const auto* initial_scale_values = static_cast<const float*>(initial_scale.view.buf);
    const auto* negative_values = static_cast<const float*>(negative_scale_direction.view.buf);
    for (std::size_t component = 0; component < 3; ++component) {
        if (std::fabs(initial_scale_values[component]) <= kMc2Epsilon) {
            PyErr_SetString(PyExc_ValueError, "center_initial_scale cannot contain zero");
            return nullptr;
        }
        if (negative_values[component] != -1.0f && negative_values[component] != 1.0f) {
            PyErr_SetString(PyExc_ValueError, "center_negative_scale_direction must contain only -1 or 1");
            return nullptr;
        }
    }
    auto copy3 = [](const Buffer& source, std::array<float, 3>& target) {
        const auto* values = static_cast<const float*>(source.view.buf);
        std::copy(values, values + 3, target.begin());
    };
    auto copy4 = [](const Buffer& source, std::array<float, 4>& target) {
        const auto* values = static_cast<const float*>(source.view.buf);
        std::copy(values, values + 4, target.begin());
    };
    copy3(old_frame_position, context->center_old_frame_world_position);
    copy3(frame_position, context->center_frame_world_position);
    copy4(old_frame_rotation, context->center_old_frame_world_rotation);
    copy4(frame_rotation, context->center_frame_world_rotation);
    copy3(old_frame_scale, context->center_old_frame_world_scale);
    copy3(frame_scale, context->center_frame_world_scale);
    copy3(old_world_position, context->center_old_world_position);
    copy4(old_world_rotation, context->center_old_world_rotation);
    copy3(initial_scale, context->center_initial_scale);
    copy3(negative_scale_direction, context->center_negative_scale_direction);
    context->center_distance_weight = static_cast<float>(distance_weight);
    context->frame_interpolation = static_cast<float>(frame_interpolation);
    context->velocity_weight = static_cast<float>(velocity_weight);
    context->center_dynamic_ready = true;
    context->center_frame_ready = true;
    context->center_result_ready = false;
    ++context->center_dynamic_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_step_interpolation(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_update_step_interpolation expects 2 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->center_frame_ready) {
        PyErr_SetString(
            PyExc_RuntimeError,
            "Step interpolation requires a complete Center frame update"
        );
        return nullptr;
    }
    const double frame_interpolation = as_double(
        PyTuple_GET_ITEM(args, 1), "frame_interpolation"
    );
    if (PyErr_Occurred()) return nullptr;
    if (!std::isfinite(frame_interpolation) ||
        frame_interpolation < 0.0 || frame_interpolation > 1.0) {
        PyErr_SetString(PyExc_ValueError, "frame_interpolation must be in 0..1");
        return nullptr;
    }
    context->frame_interpolation = static_cast<float>(frame_interpolation);
    context->center_dynamic_ready = true;
    context->center_result_ready = false;
    ++context->step_interpolation_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_update_team_options(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_team_options expects 2 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const double animation_pose_ratio = as_double(
        PyTuple_GET_ITEM(args, 1), "animation_pose_ratio"
    );
    if (PyErr_Occurred()) return nullptr;
    if (!std::isfinite(animation_pose_ratio) ||
        animation_pose_ratio < 0.0 || animation_pose_ratio > 1.0) {
        PyErr_SetString(PyExc_ValueError, "animation_pose_ratio must be in 0..1");
        return nullptr;
    }
    context->animation_pose_ratio = static_cast<float>(animation_pose_ratio);
    ++context->team_options_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_apply_center_frame_shift(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_apply_center_frame_shift expects 4 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto count = static_cast<std::size_t>(context->vertex_count);
    if (!context->initialized || context->state_positions.size() != count * 3 ||
        context->state_rotations.size() != count * 4 ||
        context->state_velocities.size() != count * 3 ||
        context->velocity_reference_positions.size() != count * 3) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 particle state is not initialized for Center frame shift");
        return nullptr;
    }
    Buffer pivot, shift_vector, shift_rotation;
    if (!pivot.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "center_shift_pivot") ||
        !shift_vector.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "center_shift_vector") ||
        !shift_rotation.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "center_shift_rotation")) {
        return nullptr;
    }
    if (!expect_float32(pivot, "center_shift_pivot") ||
        !expect_1d_array(pivot, "center_shift_pivot", 3) ||
        !finite_floats(pivot, "center_shift_pivot") ||
        !expect_float32(shift_vector, "center_shift_vector") ||
        !expect_1d_array(shift_vector, "center_shift_vector", 3) ||
        !finite_floats(shift_vector, "center_shift_vector") ||
        !expect_float32(shift_rotation, "center_shift_rotation") ||
        !expect_1d_array(shift_rotation, "center_shift_rotation", 4) ||
        !finite_floats(shift_rotation, "center_shift_rotation")) {
        return nullptr;
    }
    const auto* rotation = static_cast<const float*>(shift_rotation.view.buf);
    float rotation_length_squared = 0.0f;
    for (std::size_t component = 0; component < 4; ++component) {
        rotation_length_squared += rotation[component] * rotation[component];
    }
    if (std::fabs(rotation_length_squared - 1.0f) > 2.0e-5f) {
        PyErr_SetString(PyExc_ValueError, "center_shift_rotation must contain a unit quaternion");
        return nullptr;
    }
    const auto* pivot_values = static_cast<const float*>(pivot.view.buf);
    const auto* shift_values = static_cast<const float*>(shift_vector.view.buf);
    const std::array<float, 4> shift_quaternion {
        rotation[0], rotation[1], rotation[2], rotation[3]
    };
    for (std::size_t vertex = 0; vertex < count; ++vertex) {
        const auto offset = vertex * 3;
        const auto rotation_offset = vertex * 4;
        float local_position[3] {
            context->state_positions[offset + 0] - pivot_values[0],
            context->state_positions[offset + 1] - pivot_values[1],
            context->state_positions[offset + 2] - pivot_values[2],
        };
        float rotated_position[3] {};
        rotate_vector_xyzw(rotation, local_position, rotated_position);
        for (std::size_t component = 0; component < 3; ++component) {
            context->state_positions[offset + component] =
                pivot_values[component] + rotated_position[component] + shift_values[component];
        }
        float local_reference[3] {
            context->velocity_reference_positions[offset + 0] - pivot_values[0],
            context->velocity_reference_positions[offset + 1] - pivot_values[1],
            context->velocity_reference_positions[offset + 2] - pivot_values[2],
        };
        float rotated_reference[3] {};
        rotate_vector_xyzw(rotation, local_reference, rotated_reference);
        for (std::size_t component = 0; component < 3; ++component) {
            context->velocity_reference_positions[offset + component] =
                pivot_values[component] + rotated_reference[component] + shift_values[component];
        }
        float rotated_velocity[3] {};
        rotate_vector_xyzw(
            rotation,
            context->state_velocities.data() + offset,
            rotated_velocity
        );
        std::copy_n(rotated_velocity, 3, context->state_velocities.data() + offset);
        const std::array<float, 4> state_rotation {
            context->state_rotations[rotation_offset + 0],
            context->state_rotations[rotation_offset + 1],
            context->state_rotations[rotation_offset + 2],
            context->state_rotations[rotation_offset + 3],
        };
        auto shifted_rotation = quaternion_multiply(shift_quaternion, state_rotation);
        normalize_quaternion(shifted_rotation);
        std::copy(
            shifted_rotation.begin(), shifted_rotation.end(),
            context->state_rotations.begin() + static_cast<std::ptrdiff_t>(rotation_offset)
        );
    }
    ++context->center_frame_shift_count;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_apply_center_negative_scale_teleport(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_apply_center_negative_scale_teleport expects 2 arguments"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto count = static_cast<std::size_t>(context->vertex_count);
    if (!context->initialized || context->state_positions.size() != count * 3 ||
        context->state_rotations.size() != count * 4 ||
        context->state_velocities.size() != count * 3 ||
        context->velocity_reference_positions.size() != count * 3) {
        PyErr_SetString(
            PyExc_RuntimeError,
            "MC2 V0 particle state is not initialized for negative-scale teleport"
        );
        return nullptr;
    }
    Buffer matrix;
    if (!matrix.get(
            PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND,
            "center_negative_scale_matrix"
        ) ||
        !expect_float32(matrix, "center_negative_scale_matrix") ||
        !expect_2d(matrix, "center_negative_scale_matrix", 4, 4) ||
        !finite_floats(matrix, "center_negative_scale_matrix")) {
        return nullptr;
    }
    const auto* values = static_cast<const float*>(matrix.view.buf);
    for (std::size_t vertex = 0; vertex < count; ++vertex) {
        const auto offset = vertex * 3;
        const auto rotation_offset = vertex * 4;
        const Vec3 position {
            context->state_positions[offset + 0],
            context->state_positions[offset + 1],
            context->state_positions[offset + 2],
        };
        const Vec3 reference {
            context->velocity_reference_positions[offset + 0],
            context->velocity_reference_positions[offset + 1],
            context->velocity_reference_positions[offset + 2],
        };
        const Vec3 velocity {
            context->state_velocities[offset + 0],
            context->state_velocities[offset + 1],
            context->state_velocities[offset + 2],
        };
        const Vec3 transformed_position = transform_point_matrix(values, position);
        const Vec3 transformed_reference = transform_point_matrix(values, reference);
        const Vec3 transformed_velocity = transform_vector_matrix(values, velocity);
        const std::array<float, 4> rotation {
            context->state_rotations[rotation_offset + 0],
            context->state_rotations[rotation_offset + 1],
            context->state_rotations[rotation_offset + 2],
            context->state_rotations[rotation_offset + 3],
        };
        const auto transformed_rotation = transform_rotation_matrix(values, rotation);
        const Vec3 vectors[] = {
            transformed_position, transformed_reference, transformed_velocity
        };
        float* outputs[] = {
            context->state_positions.data() + offset,
            context->velocity_reference_positions.data() + offset,
            context->state_velocities.data() + offset,
        };
        for (std::size_t index = 0; index < 3; ++index) {
            outputs[index][0] = vectors[index].x;
            outputs[index][1] = vectors[index].y;
            outputs[index][2] = vectors[index].z;
        }
        std::copy(
            transformed_rotation.begin(), transformed_rotation.end(),
            context->state_rotations.begin() + static_cast<std::ptrdiff_t>(rotation_offset)
        );
    }
    ++context->center_negative_scale_teleport_count;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_apply_task_teleport(PyObject*, PyObject* args) {
    const auto argument_count = PyTuple_GET_SIZE(args);
    if (argument_count != 1) {
        PyErr_SetString(
            PyExc_TypeError,
            "mc2_context_v0_apply_task_teleport expects 1 argument"
        );
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const auto count = static_cast<std::size_t>(context->vertex_count);
    if (!context->parameters_ready || !context->dynamic_ready || !context->initialized ||
        context->float_values.size() != static_cast<std::size_t>(kFloatCount) ||
        context->int_values.size() != static_cast<std::size_t>(kIntCount) ||
        context->old_dynamic_positions.size() != count * 3 ||
        context->dynamic_positions.size() != count * 3 ||
        context->old_dynamic_rotations.size() != count * 4 ||
        context->dynamic_rotations.size() != count * 4 ||
        context->state_positions.size() != count * 3 ||
        context->state_rotations.size() != count * 4 ||
        context->state_velocities.size() != count * 3 ||
        context->velocity_reference_positions.size() != count * 3) {
        PyErr_SetString(
            PyExc_RuntimeError,
            "particle teleport requires initialized parameters, dynamic bases, and state"
        );
        return nullptr;
    }

    {
    const auto set_tuple3 = [](PyObject* dict, const char* key,
                               const std::array<float, 3>& value) {
        PyObject* tuple = Py_BuildValue(
            "(fff)", value[0], value[1], value[2]
        );
        if (tuple == nullptr) return false;
        const bool ok = PyDict_SetItemString(dict, key, tuple) == 0;
        Py_DECREF(tuple);
        return ok;
    };
    const auto set_tuple4 = [](PyObject* dict, const char* key,
                               const std::array<float, 4>& value) {
        PyObject* tuple = Py_BuildValue(
            "(ffff)", value[0], value[1], value[2], value[3]
        );
        if (tuple == nullptr) return false;
        const bool ok = PyDict_SetItemString(dict, key, tuple) == 0;
        Py_DECREF(tuple);
        return ok;
    };
    const auto build_task_result = [&]() -> PyObject* {
        PyObject* result = PyDict_New();
        if (result == nullptr) return nullptr;
        const bool triggered = context->particle_teleport_trigger_count > 0;
        if (!dict_i64(result, "mode", context->particle_teleport_mode) ||
            !dict_i64(result, "trigger_count", triggered ? context->vertex_count : 0) ||
            !dict_i64(result, "particle_count", context->vertex_count) ||
            !dict_bool(result, "applied", triggered) ||
            !dict_string(
                result,
                "reference_kind",
                context->particle_teleport_reference_kind == 1
                    ? "first_fixed"
                    : "object_origin"
            ) ||
            !dict_i64(
                result,
                "reference_index",
                context->particle_teleport_reference_index
            ) ||
            !set_tuple3(
                result,
                "old_reference_position",
                context->particle_teleport_old_reference_position
            ) ||
            !set_tuple3(
                result,
                "reference_position",
                context->particle_teleport_reference_position
            ) ||
            !set_tuple4(
                result,
                "old_reference_rotation_xyzw",
                context->particle_teleport_old_reference_rotation
            ) ||
            !set_tuple4(
                result,
                "reference_rotation_xyzw",
                context->particle_teleport_reference_rotation
            ) ||
            !dict_float(
                result,
                "measured_distance",
                context->particle_teleport_max_distance
            ) ||
            !dict_float(
                result,
                "distance_threshold",
                context->particle_teleport_distance_threshold
            ) ||
            !dict_float(
                result,
                "measured_rotation_degrees",
                context->particle_teleport_max_rotation_degrees
            ) ||
            !dict_float(
                result,
                "rotation_threshold_degrees",
                context->particle_teleport_rotation_threshold_degrees
            )) {
            Py_DECREF(result);
            return nullptr;
        }
        return result;
    };

    if (context->particle_teleport_evaluation_revision == context->dynamic_revision) {
        return build_task_result();
    }

    constexpr std::size_t kTeleportDistance = 22;
    constexpr std::size_t kTeleportRotation = 23;
    constexpr std::size_t kTeleportMode = 2;
    constexpr float kRadiansToDegrees = 57.295779513082320876f;
    const auto mode = context->int_values[kTeleportMode];
    const float distance_threshold = std::max(
        context->float_values[kTeleportDistance] * std::fabs(context->scale_ratio),
        0.0f
    );
    const float rotation_threshold = std::max(
        context->float_values[kTeleportRotation],
        0.0f
    );

    const auto display_position = [&](const std::vector<float>& values,
                                      std::size_t vertex,
                                      const std::array<float, 3>& pose_position,
                                      const std::array<float, 4>& pose_rotation,
                                      const std::array<float, 3>& pose_scale) {
        const Vec3 raw = load_vector3(values, vertex);
        if (context->setup_kind != 0 || !context->component_pose_ready) {
            return raw;
        }
        const auto reference_inverse = quaternion_inverse(
            context->component_reference_rotation
        );
        Vec3 local = rotate_vector(reference_inverse, Vec3 {
            raw.x - context->component_reference_position[0],
            raw.y - context->component_reference_position[1],
            raw.z - context->component_reference_position[2],
        });
        local.x *= pose_scale[0] / context->component_reference_scale[0];
        local.y *= pose_scale[1] / context->component_reference_scale[1];
        local.z *= pose_scale[2] / context->component_reference_scale[2];
        const Vec3 rotated = rotate_vector(pose_rotation, local);
        return Vec3 {
            pose_position[0] + rotated.x,
            pose_position[1] + rotated.y,
            pose_position[2] + rotated.z,
        };
    };
    const auto display_rotation = [&](const std::vector<float>& values,
                                      std::size_t vertex,
                                      const std::array<float, 4>& pose_rotation) {
        auto value = load_quaternion(values, vertex);
        if (context->setup_kind == 0 && context->component_pose_ready) {
            value = quaternion_multiply(
                quaternion_multiply(
                    pose_rotation,
                    quaternion_inverse(context->component_reference_rotation)
                ),
                value
            );
            normalize_quaternion(value);
        }
        return value;
    };

    Vec3 old_reference {};
    Vec3 current_reference {};
    std::array<float, 4> old_reference_rotation {0.0f, 0.0f, 0.0f, 1.0f};
    std::array<float, 4> current_reference_rotation {0.0f, 0.0f, 0.0f, 1.0f};
    context->particle_teleport_reference_kind = 0;
    context->particle_teleport_reference_index = -1;
    if (!context->center_fixed_indices.empty()) {
        const auto raw_index = context->center_fixed_indices.front();
        if (raw_index < 0 || static_cast<std::size_t>(raw_index) >= count) {
            PyErr_SetString(
                PyExc_RuntimeError,
                "MC2 task teleport Fixed reference is outside the particle range"
            );
            return nullptr;
        }
        const auto index = static_cast<std::size_t>(raw_index);
        old_reference = display_position(
            context->old_dynamic_positions,
            index,
            context->old_component_position,
            context->old_component_rotation,
            context->old_component_scale
        );
        current_reference = display_position(
            context->dynamic_positions,
            index,
            context->component_position,
            context->component_rotation,
            context->component_scale
        );
        old_reference_rotation = display_rotation(
            context->old_dynamic_rotations,
            index,
            context->old_component_rotation
        );
        current_reference_rotation = display_rotation(
            context->dynamic_rotations,
            index,
            context->component_rotation
        );
        context->particle_teleport_reference_kind = 1;
        context->particle_teleport_reference_index = raw_index;
    } else {
        if (!context->component_pose_ready) {
            PyErr_SetString(
                PyExc_RuntimeError,
                "MC2 task teleport object-origin reference is unavailable"
            );
            return nullptr;
        }
        old_reference = Vec3 {
            context->old_component_position[0],
            context->old_component_position[1],
            context->old_component_position[2],
        };
        current_reference = Vec3 {
            context->component_position[0],
            context->component_position[1],
            context->component_position[2],
        };
        old_reference_rotation = context->old_component_rotation;
        current_reference_rotation = context->component_rotation;
    }

    const Vec3 reference_delta {
        current_reference.x - old_reference.x,
        current_reference.y - old_reference.y,
        current_reference.z - old_reference.z,
    };
    const float measured_distance = length(reference_delta);
    const float quaternion_dot = std::clamp(std::fabs(
        old_reference_rotation[0] * current_reference_rotation[0] +
        old_reference_rotation[1] * current_reference_rotation[1] +
        old_reference_rotation[2] * current_reference_rotation[2] +
        old_reference_rotation[3] * current_reference_rotation[3]
    ), 0.0f, 1.0f);
    const float measured_rotation =
        2.0f * std::acos(quaternion_dot) * kRadiansToDegrees;
    const bool triggered = mode != 0 && (
        (measured_distance > kMc2Epsilon && measured_distance >= distance_threshold) ||
        (measured_rotation > kMc2Epsilon && measured_rotation >= rotation_threshold)
    );

    context->particle_teleport_evaluation_revision = context->dynamic_revision;
    context->particle_teleport_mode = mode;
    context->particle_teleport_trigger_count = triggered ? 1 : 0;
    context->particle_teleport_max_distance = measured_distance;
    context->particle_teleport_max_rotation_degrees = measured_rotation;
    context->particle_teleport_distance_threshold = distance_threshold;
    context->particle_teleport_rotation_threshold_degrees = rotation_threshold;
    context->particle_teleport_old_reference_position = {
        old_reference.x, old_reference.y, old_reference.z
    };
    context->particle_teleport_reference_position = {
        current_reference.x, current_reference.y, current_reference.z
    };
    context->particle_teleport_old_reference_rotation = old_reference_rotation;
    context->particle_teleport_reference_rotation = current_reference_rotation;

    if (triggered && mode == 2) {
        auto delta_rotation = quaternion_multiply(
            current_reference_rotation,
            quaternion_inverse(old_reference_rotation)
        );
        normalize_quaternion(delta_rotation);
        const auto transform_positions = [&](std::vector<float>& values) {
            if (values.size() != count * 3) return;
            for (std::size_t vertex = 0; vertex < count; ++vertex) {
                const Vec3 value = load_vector3(values, vertex);
                const Vec3 rotated = rotate_vector(delta_rotation, Vec3 {
                    value.x - old_reference.x,
                    value.y - old_reference.y,
                    value.z - old_reference.z,
                });
                const auto offset = vertex * 3;
                values[offset + 0] = current_reference.x + rotated.x;
                values[offset + 1] = current_reference.y + rotated.y;
                values[offset + 2] = current_reference.z + rotated.z;
            }
        };
        const auto transform_rotations = [&](std::vector<float>& values) {
            if (values.size() != count * 4) return;
            for (std::size_t vertex = 0; vertex < count; ++vertex) {
                auto value = quaternion_multiply(
                    delta_rotation,
                    load_quaternion(values, vertex)
                );
                normalize_quaternion(value);
                store_quaternion(values, vertex, value);
            }
        };
        const auto rotate_vectors = [&](std::vector<float>& values) {
            if (values.size() != count * 3) return;
            for (std::size_t vertex = 0; vertex < count; ++vertex) {
                const auto offset = vertex * 3;
                const Vec3 value = rotate_vector(
                    delta_rotation,
                    load_vector3(values, vertex)
                );
                values[offset + 0] = value.x;
                values[offset + 1] = value.y;
                values[offset + 2] = value.z;
            }
        };
        transform_positions(context->state_positions);
        transform_positions(context->velocity_reference_positions);
        transform_positions(context->step_basic_positions);
        transform_positions(context->animated_base_positions);
        transform_rotations(context->state_rotations);
        transform_rotations(context->step_basic_rotations);
        transform_rotations(context->animated_base_rotations);
        rotate_vectors(context->state_velocities);
        rotate_vectors(context->particle_real_velocities);
        rotate_vectors(context->particle_collision_normals);
        std::fill(context->particle_friction.begin(), context->particle_friction.end(), 0.0f);
        std::fill(
            context->particle_static_friction.begin(),
            context->particle_static_friction.end(),
            0.0f
        );
    }
    if (triggered) {
        ++context->particle_teleport_apply_count;
        context->bone_output_positions.clear();
        context->bone_output_rotations.clear();
        context->self_contact_keys.clear();
        context->self_intersect_records.clear();
        context->self_particle_intersect_flags.assign(count, static_cast<std::uint8_t>(0));
        context->self_intersect_detection_ready = false;
        context->self_intersect_flags_ready = false;
        for (auto& flag : context->self_primitive_flags) {
            flag &= ~kSelfIntersectMask;
        }
        context->self_contact_candidates.clear();
        clear_self_collision_contacts(*context);
        context->self_primitive_dynamic_ready = false;
        context->self_grid_dynamic_ready = false;
        context->self_candidate_ready = false;
    }
    return build_task_result();
    }

}

PyObject* mc2_context_v0_update_parameters(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_parameters expects 4 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    Buffer floats, ints, curves;
    if (!floats.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "float_values") ||
        !ints.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "int_values") ||
        !curves.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "curve_values")) {
        return nullptr;
    }
    if (!expect_float32(floats, "float_values") ||
        !expect_1d_array(floats, "float_values", kFloatCount) ||
        !expect_int32(ints, "int_values") ||
        !expect_1d_array(ints, "int_values", kIntCount) ||
        !validate_parameter_ints(ints) ||
        !expect_float32(curves, "curve_values") ||
        !expect_2d(curves, "curve_values", kCurveRows, kCurveColumns) ||
        !finite_floats(floats, "float_values") ||
        !finite_floats(curves, "curve_values")) {
        return nullptr;
    }
    auto next_floats = copy_values<float>(floats);
    auto next_ints = copy_values<std::int32_t>(ints);
    auto next_curves = copy_values<float>(curves);
    context->float_values.swap(next_floats);
    context->int_values.swap(next_ints);
    context->curve_values.swap(next_curves);
    context->parameters_ready = true;
    ++context->parameter_revision;
    Py_RETURN_NONE;
}

void commit_dynamic_values(
    Mc2ContextV0& context,
    long frame,
    long generation,
    std::vector<float>&& positions,
    std::vector<float>&& rotations,
    float velocity_weight,
    float gravity_ratio,
    float scale_ratio,
    float negative_scale_sign,
    float frame_interpolation
) {
    if (context.dynamic_ready) {
        context.old_dynamic_positions = context.dynamic_positions;
        context.old_dynamic_rotations = context.dynamic_rotations;
    } else {
        context.old_dynamic_positions = positions;
        context.old_dynamic_rotations = rotations;
    }
    context.dynamic_positions = std::move(positions);
    context.dynamic_rotations = std::move(rotations);
    context.frame = frame;
    context.generation = generation;
    context.velocity_weight = velocity_weight;
    context.gravity_ratio = gravity_ratio;
    context.scale_ratio = scale_ratio;
    context.negative_scale_sign = negative_scale_sign;
    context.frame_interpolation = frame_interpolation;
    context.center_dynamic_ready = false;
    context.center_frame_ready = false;
    context.center_result_ready = false;
    context.dynamic_ready = true;
    context.bone_output_positions.clear();
    context.bone_output_rotations.clear();
    ++context.dynamic_revision;
}

void commit_component_pose(
    Mc2ContextV0& context,
    const float* position,
    const float* rotation,
    const float* scale
) {
    if (context.component_pose_ready) {
        context.old_component_position = context.component_position;
        context.old_component_rotation = context.component_rotation;
        context.old_component_scale = context.component_scale;
    } else {
        std::copy_n(position, 3, context.old_component_position.begin());
        std::copy_n(rotation, 4, context.old_component_rotation.begin());
        std::copy_n(scale, 3, context.old_component_scale.begin());
        std::copy_n(position, 3, context.component_reference_position.begin());
        std::copy_n(rotation, 4, context.component_reference_rotation.begin());
        std::copy_n(scale, 3, context.component_reference_scale.begin());
    }
    std::copy_n(position, 3, context.component_position.begin());
    std::copy_n(rotation, 4, context.component_rotation.begin());
    std::copy_n(scale, 3, context.component_scale.begin());
    context.component_pose_ready = true;
}

PyObject* build_raw_center_pose(
    Mc2ContextV0& context,
    const float* component_position,
    const float* component_rotation,
    const float* component_scale
) {
    Vec3 position {
        component_position[0], component_position[1], component_position[2]
    };
    std::array<float, 4> rotation {
        component_rotation[0], component_rotation[1],
        component_rotation[2], component_rotation[3]
    };
    const bool has_negative_scale =
        component_scale[0] < 0.0f || component_scale[1] < 0.0f || component_scale[2] < 0.0f;
    if (!context.center_fixed_indices.empty()) {
        if (context.bone_vertex_bind_pose_rotations.size() !=
            static_cast<std::size_t>(context.vertex_count) * 4) {
            PyErr_SetString(PyExc_RuntimeError, "raw Center producer has no bind rotations");
            return nullptr;
        }
        position = {};
        Vec3 normal_sum {};
        Vec3 tangent_sum {};
        for (const auto raw_index : context.center_fixed_indices) {
            if (raw_index < 0 || raw_index >= context.vertex_count) {
                PyErr_SetString(PyExc_RuntimeError, "raw Center fixed index is invalid");
                return nullptr;
            }
            const auto index = static_cast<std::size_t>(raw_index);
            position = add(position, load_vector3(context.dynamic_positions, index));
            auto frame_rotation = load_quaternion(context.dynamic_rotations, index);
            if (has_negative_scale) {
                const Vec3 normal = rotate_vector(frame_rotation, {0.0f, 1.0f, 0.0f});
                const Vec3 tangent = rotate_vector(frame_rotation, {0.0f, 0.0f, 1.0f});
                frame_rotation = quaternion_from_forward_up(
                    mul(tangent, -1.0f), mul(normal, -1.0f)
                );
            }
            auto corrected = quaternion_multiply(
                frame_rotation,
                load_quaternion(context.bone_vertex_bind_pose_rotations, index)
            );
            normalize_quaternion(corrected);
            normal_sum = add(normal_sum, rotate_vector(corrected, {0.0f, 1.0f, 0.0f}));
            tangent_sum = add(tangent_sum, rotate_vector(corrected, {0.0f, 0.0f, 1.0f}));
        }
        position = mul(
            position,
            1.0f / static_cast<float>(context.center_fixed_indices.size())
        );
        if (component_scale[0] < 0.0f || component_scale[2] < 0.0f) {
            normal_sum = mul(normal_sum, -1.0f);
        }
        if (component_scale[0] < 0.0f || component_scale[1] < 0.0f) {
            tangent_sum = mul(tangent_sum, -1.0f);
        }
        if (length(normal_sum) <= kMc2Epsilon || length(tangent_sum) <= kMc2Epsilon) {
            PyErr_SetString(PyExc_ValueError, "raw Center orientation is degenerate");
            return nullptr;
        }
        rotation = quaternion_from_forward_up(tangent_sum, normal_sum);
    }
    return Py_BuildValue(
        "(ffffffffff)",
        position.x, position.y, position.z,
        rotation[0], rotation[1], rotation[2], rotation[3],
        component_scale[0], component_scale[1], component_scale[2]
    );
}

bool parse_raw_dynamic_scalars(
    PyObject* args,
    int first_scalar,
    float& velocity_weight,
    float& gravity_ratio,
    float& scale_ratio,
    float& negative_scale_sign,
    float& frame_interpolation
) {
    const double velocity = as_double(PyTuple_GET_ITEM(args, first_scalar), "velocity_weight");
    const double gravity = as_double(PyTuple_GET_ITEM(args, first_scalar + 1), "gravity_ratio");
    const double scale = as_double(PyTuple_GET_ITEM(args, first_scalar + 2), "scale_ratio");
    const double negative = as_double(PyTuple_GET_ITEM(args, first_scalar + 3), "negative_scale_sign");
    const double interpolation = as_double(PyTuple_GET_ITEM(args, first_scalar + 4), "frame_interpolation");
    if (PyErr_Occurred()) return false;
    if (!std::isfinite(velocity) || velocity < 0.0 || velocity > 1.0 ||
        !std::isfinite(gravity) || gravity < 0.0 || gravity > 1.0 ||
        !std::isfinite(scale) || scale <= 0.0 ||
        (negative != -1.0 && negative != 1.0) ||
        !std::isfinite(interpolation) || interpolation < 0.0 || interpolation > 1.0) {
        PyErr_SetString(PyExc_ValueError, "MC2 raw dynamic scalar is out of range");
        return false;
    }
    velocity_weight = static_cast<float>(velocity);
    gravity_ratio = static_cast<float>(gravity);
    scale_ratio = static_cast<float>(scale);
    negative_scale_sign = static_cast<float>(negative);
    frame_interpolation = static_cast<float>(interpolation);
    return true;
}

bool validate_component_pose(
    Buffer& position,
    Buffer& rotation,
    Buffer& scale
) {
    if (!expect_float32(position, "component_position") ||
        !expect_1d_array(position, "component_position", 3) ||
        !expect_float32(rotation, "component_rotation_xyzw") ||
        !expect_1d_array(rotation, "component_rotation_xyzw", 4) ||
        !expect_float32(scale, "component_scale") ||
        !expect_1d_array(scale, "component_scale", 3) ||
        !finite_floats(position, "component_position") ||
        !finite_floats(rotation, "component_rotation_xyzw") ||
        !finite_floats(scale, "component_scale")) {
        return false;
    }
    const auto* rotation_values = static_cast<const float*>(rotation.view.buf);
    const double rotation_length_squared =
        static_cast<double>(rotation_values[0]) * rotation_values[0] +
        static_cast<double>(rotation_values[1]) * rotation_values[1] +
        static_cast<double>(rotation_values[2]) * rotation_values[2] +
        static_cast<double>(rotation_values[3]) * rotation_values[3];
    if (!std::isfinite(rotation_length_squared) ||
        std::abs(rotation_length_squared - 1.0) > 2.0e-5) {
        PyErr_SetString(PyExc_ValueError, "component_rotation_xyzw must be a unit quaternion");
        return false;
    }
    const auto* scale_values = static_cast<const float*>(scale.view.buf);
    if (std::abs(scale_values[0]) <= kMc2Epsilon ||
        std::abs(scale_values[1]) <= kMc2Epsilon ||
        std::abs(scale_values[2]) <= kMc2Epsilon) {
        PyErr_SetString(PyExc_ValueError, "component_scale cannot contain zero");
        return false;
    }
    return true;
}

PyObject* mc2_context_v0_update_mesh_dynamic_raw(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 12) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_mesh_dynamic_raw expects 12 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->parameters_ready || !context->proxy_static_ready) {
        PyErr_SetString(PyExc_RuntimeError, "raw Mesh dynamic requires parameters and proxy static");
        return nullptr;
    }
    const long frame = as_long(PyTuple_GET_ITEM(args, 1), "frame");
    const long generation = as_long(PyTuple_GET_ITEM(args, 2), "generation");
    if (PyErr_Occurred()) return nullptr;
    Buffer positions, component_position, component_rotation, component_scale;
    if (!positions.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "world_positions") ||
        !component_position.get(PyTuple_GET_ITEM(args, 9), PyBUF_FORMAT | PyBUF_ND, "component_position") ||
        !component_rotation.get(PyTuple_GET_ITEM(args, 10), PyBUF_FORMAT | PyBUF_ND, "component_rotation_xyzw") ||
        !component_scale.get(PyTuple_GET_ITEM(args, 11), PyBUF_FORMAT | PyBUF_ND, "component_scale")) {
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->vertex_count);
    if (!expect_float32(positions, "world_positions") ||
        !expect_2d(positions, "world_positions", count, 3) ||
        !finite_floats(positions, "world_positions") ||
        !validate_component_pose(component_position, component_rotation, component_scale)) {
        return nullptr;
    }
    float velocity_weight, gravity_ratio, scale_ratio, negative_scale_sign, frame_interpolation;
    if (!parse_raw_dynamic_scalars(
        args, 4, velocity_weight, gravity_ratio, scale_ratio,
        negative_scale_sign, frame_interpolation
    )) return nullptr;
    auto next_positions = copy_values<float>(positions);
    std::vector<float> next_rotations(static_cast<std::size_t>(context->vertex_count) * 4, 0.0f);
    for (std::size_t vertex = 0; vertex < static_cast<std::size_t>(context->vertex_count); ++vertex) {
        next_rotations[vertex * 4 + 3] = 1.0f;
    }
    if (!apply_bone_triangle_output(*context, next_positions, next_rotations, false)) {
        PyErr_SetString(PyExc_RuntimeError, "raw Mesh frame orientation producer failed");
        return nullptr;
    }
    commit_dynamic_values(
        *context, frame, generation, std::move(next_positions), std::move(next_rotations),
        velocity_weight, gravity_ratio, scale_ratio, negative_scale_sign, frame_interpolation
    );
    commit_component_pose(
        *context,
        static_cast<const float*>(component_position.view.buf),
        static_cast<const float*>(component_rotation.view.buf),
        static_cast<const float*>(component_scale.view.buf)
    );
    return build_raw_center_pose(
        *context,
        static_cast<const float*>(component_position.view.buf),
        static_cast<const float*>(component_rotation.view.buf),
        static_cast<const float*>(component_scale.view.buf)
    );
}

PyObject* mc2_context_v0_update_bone_dynamic_raw(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 13) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_bone_dynamic_raw expects 13 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->parameters_ready || !context->bone_static_ready) {
        PyErr_SetString(PyExc_RuntimeError, "raw Bone dynamic requires parameters and Bone static");
        return nullptr;
    }
    const long frame = as_long(PyTuple_GET_ITEM(args, 1), "frame");
    const long generation = as_long(PyTuple_GET_ITEM(args, 2), "generation");
    if (PyErr_Occurred()) return nullptr;
    Buffer positions, matrices, component_position, component_rotation, component_scale;
    if (!positions.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "world_positions") ||
        !matrices.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "pose_matrices") ||
        !component_position.get(PyTuple_GET_ITEM(args, 10), PyBUF_FORMAT | PyBUF_ND, "component_position") ||
        !component_rotation.get(PyTuple_GET_ITEM(args, 11), PyBUF_FORMAT | PyBUF_ND, "component_rotation_xyzw") ||
        !component_scale.get(PyTuple_GET_ITEM(args, 12), PyBUF_FORMAT | PyBUF_ND, "component_scale")) {
        return nullptr;
    }
    const auto count = static_cast<Py_ssize_t>(context->vertex_count);
    if (context->bone_vertex_to_transform_rotations.size() !=
        static_cast<std::size_t>(context->vertex_count) * 4) {
        PyErr_SetString(
            PyExc_RuntimeError,
            "raw Bone dynamic requires vertex-to-transform rotations"
        );
        return nullptr;
    }
    if (!expect_float32(positions, "world_positions") ||
        !expect_2d(positions, "world_positions", count, 3) ||
        !expect_float32(matrices, "pose_matrices") || matrices.view.ndim != 3 ||
        matrices.view.shape[0] != count || matrices.view.shape[1] != 3 || matrices.view.shape[2] != 3 ||
        !finite_floats(positions, "world_positions") ||
        !finite_floats(matrices, "pose_matrices") ||
        !validate_component_pose(component_position, component_rotation, component_scale)) {
        return nullptr;
    }
    float velocity_weight, gravity_ratio, scale_ratio, negative_scale_sign, frame_interpolation;
    if (!parse_raw_dynamic_scalars(
        args, 5, velocity_weight, gravity_ratio, scale_ratio,
        negative_scale_sign, frame_interpolation
    )) return nullptr;
    auto next_positions = copy_values<float>(positions);
    std::vector<float> next_rotations(static_cast<std::size_t>(context->vertex_count) * 4);
    const auto* matrix_values = static_cast<const float*>(matrices.view.buf);
    const auto* component_rotation_values = static_cast<const float*>(component_rotation.view.buf);
    const std::array<float, 4> component_quaternion {
        component_rotation_values[0], component_rotation_values[1],
        component_rotation_values[2], component_rotation_values[3]
    };
    for (std::size_t vertex = 0; vertex < static_cast<std::size_t>(context->vertex_count); ++vertex) {
        const float* matrix = matrix_values + vertex * 9;
        Vec3 x {matrix[0], matrix[3], matrix[6]};
        Vec3 y {matrix[1], matrix[4], matrix[7]};
        Vec3 z {matrix[2], matrix[5], matrix[8]};
        const float x_length = length(x), y_length = length(y), z_length = length(z);
        if (x_length <= kMc2Epsilon || y_length <= kMc2Epsilon || z_length <= kMc2Epsilon) {
            PyErr_SetString(PyExc_ValueError, "raw Bone pose matrix contains zero scale");
            return nullptr;
        }
        x = mul(x, 1.0f / x_length);
        y = mul(y, 1.0f / y_length);
        z = mul(z, 1.0f / z_length);
        const float determinant = dot(cross(x, y), z);
        if (std::abs(dot(x, y)) > 1.0e-4f || std::abs(dot(x, z)) > 1.0e-4f ||
            std::abs(dot(y, z)) > 1.0e-4f || std::abs(determinant - 1.0f) > 1.0e-4f) {
            PyErr_SetString(PyExc_ValueError, "raw Bone pose matrix must be proper and shear-free");
            return nullptr;
        }
        const auto transform_rotation = quaternion_multiply(
            component_quaternion,
            quaternion_from_forward_up(z, y)
        );
        const auto vertex_to_transform = load_quaternion(
            context->bone_vertex_to_transform_rotations,
            vertex
        );
        const std::array<float, 4> transform_to_vertex {
            -vertex_to_transform[0],
            -vertex_to_transform[1],
            -vertex_to_transform[2],
            vertex_to_transform[3],
        };
        auto proxy_rotation = quaternion_multiply(
            transform_rotation,
            transform_to_vertex
        );
        normalize_quaternion(proxy_rotation);
        store_quaternion(next_rotations, vertex, proxy_rotation);
    }
    commit_dynamic_values(
        *context, frame, generation, std::move(next_positions), std::move(next_rotations),
        velocity_weight, gravity_ratio, scale_ratio, negative_scale_sign, frame_interpolation
    );
    commit_component_pose(
        *context,
        static_cast<const float*>(component_position.view.buf),
        component_rotation_values,
        static_cast<const float*>(component_scale.view.buf)
    );
    return build_raw_center_pose(
        *context,
        static_cast<const float*>(component_position.view.buf),
        component_rotation_values,
        static_cast<const float*>(component_scale.view.buf)
    );
}

PyObject* mc2_context_v0_update_dynamic(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 10) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_dynamic expects 10 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->parameters_ready) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 parameters have not been uploaded");
        return nullptr;
    }
    const long frame = as_long(PyTuple_GET_ITEM(args, 1), "frame");
    const long generation = as_long(PyTuple_GET_ITEM(args, 2), "generation");
    const double velocity_weight = as_double(PyTuple_GET_ITEM(args, 5), "velocity_weight");
    const double gravity_ratio = as_double(PyTuple_GET_ITEM(args, 6), "gravity_ratio");
    const double scale_ratio = as_double(PyTuple_GET_ITEM(args, 7), "scale_ratio");
    const double negative_scale_sign = as_double(
        PyTuple_GET_ITEM(args, 8), "negative_scale_sign"
    );
    const double frame_interpolation = as_double(
        PyTuple_GET_ITEM(args, 9), "frame_interpolation"
    );
    if (PyErr_Occurred()) return nullptr;
    if (!std::isfinite(velocity_weight) || velocity_weight < 0.0 || velocity_weight > 1.0 ||
        !std::isfinite(gravity_ratio) || gravity_ratio < 0.0 || gravity_ratio > 1.0 ||
        !std::isfinite(scale_ratio) || scale_ratio <= 0.0 ||
        (negative_scale_sign != -1.0 && negative_scale_sign != 1.0) ||
        !std::isfinite(frame_interpolation) ||
        frame_interpolation < 0.0 || frame_interpolation > 1.0) {
        PyErr_SetString(PyExc_ValueError, "MC2 dynamic scalar is out of range");
        return nullptr;
    }
    Buffer positions, rotations;
    if (!positions.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "world_positions") ||
        !rotations.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "world_rotations_xyzw")) {
        return nullptr;
    }
    const Py_ssize_t count = static_cast<Py_ssize_t>(context->vertex_count);
    if (!expect_float32(positions, "world_positions") ||
        !expect_2d(positions, "world_positions", count, 3) ||
        !expect_float32(rotations, "world_rotations_xyzw") ||
        !expect_2d(rotations, "world_rotations_xyzw", count, 4) ||
        !finite_floats(positions, "world_positions") ||
        !finite_floats(rotations, "world_rotations_xyzw") ||
        !validate_quaternions(rotations, "world_rotations_xyzw")) {
        return nullptr;
    }
    auto next_positions = copy_values<float>(positions);
    auto next_rotations = copy_values<float>(rotations);
    if (context->dynamic_ready) {
        context->old_dynamic_positions = context->dynamic_positions;
        context->old_dynamic_rotations = context->dynamic_rotations;
    } else {
        context->old_dynamic_positions = next_positions;
        context->old_dynamic_rotations = next_rotations;
    }
    context->dynamic_positions.swap(next_positions);
    context->dynamic_rotations.swap(next_rotations);
    context->frame = frame;
    context->generation = generation;
    context->velocity_weight = static_cast<float>(velocity_weight);
    context->gravity_ratio = static_cast<float>(gravity_ratio);
    context->scale_ratio = static_cast<float>(scale_ratio);
    context->negative_scale_sign = static_cast<float>(negative_scale_sign);
    context->frame_interpolation = static_cast<float>(frame_interpolation);
    context->center_dynamic_ready = false;
    context->center_frame_ready = false;
    context->center_result_ready = false;
    context->dynamic_ready = true;
    context->bone_output_positions.clear();
    context->bone_output_rotations.clear();
    ++context->dynamic_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_derive_center_pose_raw(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 4) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_derive_center_pose_raw expects 4 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->center_static_ready || !context->dynamic_ready) {
        PyErr_SetString(PyExc_RuntimeError, "raw Center pose requires static and dynamic data");
        return nullptr;
    }
    Buffer position, rotation, scale;
    if (!position.get(PyTuple_GET_ITEM(args, 1), PyBUF_FORMAT | PyBUF_ND, "component_position") ||
        !rotation.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "component_rotation") ||
        !scale.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "component_scale")) {
        return nullptr;
    }
    if (!expect_float32(position, "component_position") ||
        !expect_1d_array(position, "component_position", 3) ||
        !finite_floats(position, "component_position") ||
        !expect_float32(rotation, "component_rotation") ||
        !expect_2d(rotation, "component_rotation", 1, 4) ||
        !finite_floats(rotation, "component_rotation") ||
        !validate_quaternions(rotation, "component_rotation") ||
        !expect_float32(scale, "component_scale") ||
        !expect_1d_array(scale, "component_scale", 3) ||
        !finite_floats(scale, "component_scale")) {
        return nullptr;
    }
    const auto* scale_values = static_cast<const float*>(scale.view.buf);
    if (std::abs(scale_values[0]) <= kMc2Epsilon ||
        std::abs(scale_values[1]) <= kMc2Epsilon ||
        std::abs(scale_values[2]) <= kMc2Epsilon) {
        PyErr_SetString(PyExc_ValueError, "component_scale cannot contain zero");
        return nullptr;
    }
    commit_component_pose(
        *context,
        static_cast<const float*>(position.view.buf),
        static_cast<const float*>(rotation.view.buf),
        scale_values
    );
    return build_raw_center_pose(
        *context,
        static_cast<const float*>(position.view.buf),
        static_cast<const float*>(rotation.view.buf),
        scale_values
    );
}

PyObject* mc2_context_v0_update_colliders(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 11) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_update_colliders expects 11 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const long mask = as_long(PyTuple_GET_ITEM(args, 1), "collided_by_groups");
    if (PyErr_Occurred()) return nullptr;
    if (mask < 0 || mask > 0xFFFF) {
        PyErr_SetString(PyExc_ValueError, "collided_by_groups must be in 0..65535");
        return nullptr;
    }

    Buffer types, groups, centers, segment_a, segment_b;
    Buffer old_centers, old_segment_a, old_segment_b, radii;
    if (!types.get(PyTuple_GET_ITEM(args, 2), PyBUF_FORMAT | PyBUF_ND, "collider_types") ||
        !groups.get(PyTuple_GET_ITEM(args, 3), PyBUF_FORMAT | PyBUF_ND, "collider_group_bits") ||
        !centers.get(PyTuple_GET_ITEM(args, 4), PyBUF_FORMAT | PyBUF_ND, "collider_centers") ||
        !segment_a.get(PyTuple_GET_ITEM(args, 5), PyBUF_FORMAT | PyBUF_ND, "collider_segment_a") ||
        !segment_b.get(PyTuple_GET_ITEM(args, 6), PyBUF_FORMAT | PyBUF_ND, "collider_segment_b") ||
        !old_centers.get(PyTuple_GET_ITEM(args, 7), PyBUF_FORMAT | PyBUF_ND, "collider_old_centers") ||
        !old_segment_a.get(PyTuple_GET_ITEM(args, 8), PyBUF_FORMAT | PyBUF_ND, "collider_old_segment_a") ||
        !old_segment_b.get(PyTuple_GET_ITEM(args, 9), PyBUF_FORMAT | PyBUF_ND, "collider_old_segment_b") ||
        !radii.get(PyTuple_GET_ITEM(args, 10), PyBUF_FORMAT | PyBUF_ND, "collider_radii")) {
        return nullptr;
    }
    if (!expect_int32_scalar_array(types, "collider_types")) return nullptr;
    const Py_ssize_t count = types.view.shape[0];
    if (!expect_int32_scalar_array(groups, "collider_group_bits") || groups.view.shape[0] != count ||
        !expect_float32(centers, "collider_centers") || !expect_2d(centers, "collider_centers", count, 3) ||
        !expect_float32(segment_a, "collider_segment_a") || !expect_2d(segment_a, "collider_segment_a", count, 3) ||
        !expect_float32(segment_b, "collider_segment_b") || !expect_2d(segment_b, "collider_segment_b", count, 3) ||
        !expect_float32(old_centers, "collider_old_centers") || !expect_2d(old_centers, "collider_old_centers", count, 3) ||
        !expect_float32(old_segment_a, "collider_old_segment_a") || !expect_2d(old_segment_a, "collider_old_segment_a", count, 3) ||
        !expect_float32(old_segment_b, "collider_old_segment_b") || !expect_2d(old_segment_b, "collider_old_segment_b", count, 3) ||
        !expect_float32(radii, "collider_radii") || radii.view.ndim != 1 || radii.view.shape[0] != count ||
        !finite_floats(centers, "collider_centers") ||
        !finite_floats(segment_a, "collider_segment_a") ||
        !finite_floats(segment_b, "collider_segment_b") ||
        !finite_floats(old_centers, "collider_old_centers") ||
        !finite_floats(old_segment_a, "collider_old_segment_a") ||
        !finite_floats(old_segment_b, "collider_old_segment_b") ||
        !finite_floats(radii, "collider_radii")) {
        return nullptr;
    }
    const auto* type_values = static_cast<const std::int32_t*>(types.view.buf);
    const auto* group_values = static_cast<const std::int32_t*>(groups.view.buf);
    for (Py_ssize_t index = 0; index < count; ++index) {
        if (type_values[index] < 0 || type_values[index] > 3) {
            PyErr_SetString(PyExc_ValueError, "collider type must be in 0..3");
            return nullptr;
        }
        const auto group = group_values[index];
        if (group <= 0 || group > 0x8000 || (group & (group - 1)) != 0) {
            PyErr_SetString(PyExc_ValueError, "collider group bit must be one bit in 1..32768");
            return nullptr;
        }
    }

    context->collided_by_groups = static_cast<std::int32_t>(mask);
    context->collider_types = copy_values<std::int32_t>(types);
    context->collider_group_bits = copy_values<std::int32_t>(groups);
    context->collider_centers = copy_values<float>(centers);
    context->collider_segment_a = copy_values<float>(segment_a);
    context->collider_segment_b = copy_values<float>(segment_b);
    context->collider_old_centers = copy_values<float>(old_centers);
    context->collider_old_segment_a = copy_values<float>(old_segment_a);
    context->collider_old_segment_b = copy_values<float>(old_segment_b);
    context->collider_radii = copy_values<float>(radii);
    ++context->collider_revision;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_reset(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 1) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_reset expects 1 argument");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    if (!context->dynamic_ready) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 dynamic frame has not been uploaded");
        return nullptr;
    }
    context->state_positions = context->dynamic_positions;
    context->state_rotations = context->dynamic_rotations;
    context->old_dynamic_positions = context->dynamic_positions;
    context->old_dynamic_rotations = context->dynamic_rotations;
    if (context->component_pose_ready) {
        context->old_component_position = context->component_position;
        context->old_component_rotation = context->component_rotation;
        context->old_component_scale = context->component_scale;
    }
    context->state_velocities.assign(
        static_cast<std::size_t>(context->vertex_count) * 3,
        0.0f
    );
    context->velocity_reference_positions = context->dynamic_positions;
    context->particle_friction.assign(static_cast<std::size_t>(context->vertex_count), 0.0f);
    context->particle_static_friction.assign(static_cast<std::size_t>(context->vertex_count), 0.0f);
    context->particle_collision_normals.assign(static_cast<std::size_t>(context->vertex_count) * 3, 0.0f);
    context->particle_real_velocities.assign(static_cast<std::size_t>(context->vertex_count) * 3, 0.0f);
    context->step_basic_positions = context->dynamic_positions;
    context->step_basic_rotations = context->dynamic_rotations;
    context->center_dynamic_ready = false;
    context->center_frame_ready = false;
    context->center_result_ready = false;
    context->bone_output_positions.clear();
    context->bone_output_rotations.clear();
    context->self_contact_keys.clear();
    context->self_intersect_records.clear();
    context->self_particle_intersect_flags.assign(
        static_cast<std::size_t>(context->vertex_count),
        static_cast<std::uint8_t>(0)
    );
    context->self_intersect_detection_ready = false;
    context->self_intersect_flags_ready = false;
    for (auto& flag : context->self_primitive_flags) {
        flag &= ~kSelfIntersectMask;
    }
    context->self_contact_candidates.clear();
    clear_self_collision_contacts(*context);
    context->self_primitive_dynamic_ready = false;
    context->self_grid_dynamic_ready = false;
    context->self_candidate_ready = false;
    context->self_point_grid_count = 0;
    context->self_edge_grid_count = 0;
    context->self_triangle_grid_count = 0;
    context->self_max_primitive_size = 0.0f;
    context->self_grid_size = 0.0f;
    context->initialized = true;
    ++context->reset_count;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_set_tether_enabled(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_set_tether_enabled expects 2 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const int enabled = PyObject_IsTrue(PyTuple_GET_ITEM(args, 1));
    if (enabled < 0) return nullptr;
    context->tether_enabled = enabled != 0;
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_set_setup_kind(PyObject*, PyObject* args) {
    if (PyTuple_GET_SIZE(args) != 2) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_set_setup_kind expects 2 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const long setup_kind = as_long(PyTuple_GET_ITEM(args, 1), "setup_kind");
    if (PyErr_Occurred()) return nullptr;
    if (setup_kind < 0 || setup_kind > 2) {
        PyErr_SetString(PyExc_ValueError, "setup_kind must be in 0..2");
        return nullptr;
    }
    if (context->proxy_static_ready || context->baseline_static_ready || context->initialized) {
        PyErr_SetString(PyExc_RuntimeError, "setup_kind is immutable after context initialization");
        return nullptr;
    }
    context->setup_kind = static_cast<std::int32_t>(setup_kind);
    Py_RETURN_NONE;
}

PyObject* mc2_context_v0_step(PyObject*, PyObject* args) {
    const Py_ssize_t argument_count = PyTuple_GET_SIZE(args);
    if (argument_count != 4 && argument_count != 5 && argument_count != 6) {
        PyErr_SetString(PyExc_TypeError, "mc2_context_v0_step expects 4, 5, or 6 arguments");
        return nullptr;
    }
    auto* context = context_from(PyTuple_GET_ITEM(args, 0));
    if (!ensure_live(context)) return nullptr;
    const double dt = as_double(PyTuple_GET_ITEM(args, 1), "dt");
    const double simulation_power_y = as_double(
        PyTuple_GET_ITEM(args, 2),
        "simulation_power_y"
    );
    const double simulation_power_z = as_double(
        PyTuple_GET_ITEM(args, 3),
        "simulation_power_z"
    );
    const double simulation_power_w = argument_count >= 5
        ? as_double(PyTuple_GET_ITEM(args, 4), "simulation_power_w")
        : 1.0;
    const int final_substep_value = argument_count == 6
        ? PyObject_IsTrue(PyTuple_GET_ITEM(args, 5))
        : 1;
    if (final_substep_value < 0) return nullptr;
    const bool is_final_substep = final_substep_value != 0;
    if (PyErr_Occurred()) return nullptr;
    if (!std::isfinite(dt) || dt < 0.0 ||
        !std::isfinite(simulation_power_y) || simulation_power_y < 0.0 ||
        !std::isfinite(simulation_power_z) || simulation_power_z < 0.0 ||
        !std::isfinite(simulation_power_w) || simulation_power_w < 0.0) {
        PyErr_SetString(PyExc_ValueError, "dt and simulation powers must be finite and non-negative");
        return nullptr;
    }
    if (!context->parameters_ready || !context->dynamic_ready || !context->initialized) {
        PyErr_SetString(PyExc_RuntimeError, "MC2 V0 context is not ready to step");
        return nullptr;
    }
    if (dt <= kMc2Epsilon) Py_RETURN_NONE;
    Mc2ContextStepStateV0 state;
    if (!begin_mc2_context_step(
            *context,
            static_cast<float>(dt),
            static_cast<float>(simulation_power_y),
            static_cast<float>(simulation_power_z),
            static_cast<float>(simulation_power_w),
            state)) {
        return nullptr;
    }
    finish_mc2_context_step(state, static_cast<float>(dt), is_final_substep);
    Py_RETURN_NONE;
}

}  // namespace hotools
