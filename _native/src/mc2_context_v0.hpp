#pragma once

#include <Python.h>

namespace hotools {

PyObject* mc2_context_v0_create(PyObject*, PyObject* args);
PyObject* mc2_context_v0_inspect(PyObject*, PyObject* args);
PyObject* mc2_context_v0_update_proxy_static(PyObject*, PyObject* args);
PyObject* mc2_context_v0_update_baseline_static(PyObject*, PyObject* args);
PyObject* mc2_context_v0_update_bone_static(PyObject*, PyObject* args);
PyObject* mc2_context_v0_update_distance_static(PyObject*, PyObject* args);
PyObject* mc2_context_v0_update_bending_static(PyObject*, PyObject* args);
PyObject* mc2_context_v0_update_center_static(PyObject*, PyObject* args);
PyObject* mc2_context_v0_update_center_dynamic(PyObject*, PyObject* args);
PyObject* mc2_context_v0_update_step_interpolation(PyObject*, PyObject* args);
PyObject* mc2_context_v0_update_team_options(PyObject*, PyObject* args);
PyObject* mc2_context_v0_apply_center_frame_shift(PyObject*, PyObject* args);
PyObject* mc2_context_v0_apply_center_negative_scale_teleport(PyObject*, PyObject* args);
PyObject* mc2_context_v0_update_parameters(PyObject*, PyObject* args);
PyObject* mc2_context_v0_update_dynamic(PyObject*, PyObject* args);
PyObject* mc2_context_v0_reset(PyObject*, PyObject* args);
PyObject* mc2_context_v0_step(PyObject*, PyObject* args);
PyObject* mc2_context_v0_read(PyObject*, PyObject* args);
PyObject* mc2_context_v0_read_step_basic(PyObject*, PyObject* args);
PyObject* mc2_context_v0_read_center_step(PyObject*, PyObject* args);
PyObject* mc2_context_v0_free(PyObject*, PyObject* args);
PyObject* mc2_context_v0_stats(PyObject*, PyObject* args);

}  // namespace hotools
