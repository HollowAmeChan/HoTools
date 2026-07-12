#pragma once

#include <Python.h>

namespace hotools {

PyObject* mc2_context_v0_create(PyObject*, PyObject* args);
PyObject* mc2_context_v0_inspect(PyObject*, PyObject* args);
PyObject* mc2_context_v0_update_parameters(PyObject*, PyObject* args);
PyObject* mc2_context_v0_update_dynamic(PyObject*, PyObject* args);
PyObject* mc2_context_v0_reset(PyObject*, PyObject* args);
PyObject* mc2_context_v0_step(PyObject*, PyObject* args);
PyObject* mc2_context_v0_read(PyObject*, PyObject* args);
PyObject* mc2_context_v0_free(PyObject*, PyObject* args);
PyObject* mc2_context_v0_stats(PyObject*, PyObject* args);

}  // namespace hotools
