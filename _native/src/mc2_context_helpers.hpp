#pragma once

#include <Python.h>

#include "mc2_context_internal.hpp"
#include "python_buffer_utils.hpp"

namespace hotools::mc2_internal {

inline constexpr const char* kInteractionCapsuleName =
    "hotools_native.MC2InteractionV0";
inline constexpr long kSchemaVersion = 0;
inline constexpr Py_ssize_t kIntCount = 11;
inline constexpr Py_ssize_t kSelfCollisionSyncMode = 10;
inline constexpr float kMc2Epsilon = 0.00000001f;

Mc2ContextV0* context_from(PyObject* object);
Mc2InteractionV0* interaction_from(PyObject* object);
bool ensure_live(Mc2ContextV0* context);
bool ensure_live(Mc2InteractionV0* interaction);
void destroy_interaction(PyObject* capsule);
void release_interaction(Mc2InteractionV0& interaction);
bool dict_i64(PyObject* dict, const char* key, std::int64_t value);
bool dict_bool(PyObject* dict, const char* key, bool value);
bool dict_float(PyObject* dict, const char* key, float value);
bool dict_string(PyObject* dict, const char* key, const char* value);
bool expect_2d(
    const py::Buffer& buffer,
    const char* name,
    Py_ssize_t rows,
    Py_ssize_t columns
);
bool build_bone_output(Mc2ContextV0& context);
bool interaction_scope_matches(
    Mc2InteractionV0& interaction,
    const std::vector<std::uintptr_t>& scope_identity
);
void detect_self_collision_intersections_once(Mc2ContextV0& context);
bool begin_mc2_context_step(
    Mc2ContextV0& context,
    float dt,
    float simulation_power_y,
    float simulation_power_z,
    float simulation_power_w,
    Mc2ContextStepStateV0& state
);
void finish_mc2_context_step(
    Mc2ContextStepStateV0& state,
    float dt,
    bool is_final_substep
);
bool build_and_solve_interaction(
    Mc2InteractionV0& interaction,
    const std::vector<Mc2ContextStepStateV0>& states
);
void finish_interaction_intersections(Mc2InteractionV0& interaction);

}  // namespace hotools::mc2_internal
