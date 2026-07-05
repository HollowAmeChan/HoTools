#pragma once

#include <Python.h>

namespace hotools {

PyObject* create_meshcloth_mc2_context(PyObject*, PyObject* args);
PyObject* update_meshcloth_mc2_context_static(PyObject*, PyObject* args);
PyObject* update_meshcloth_mc2_context_static_arrays(PyObject*, PyObject* args);
PyObject* update_meshcloth_mc2_context_params(PyObject*, PyObject* args);
PyObject* update_meshcloth_mc2_context_param_arrays(PyObject*, PyObject* args);
PyObject* meshcloth_mc2_context_info(PyObject*, PyObject* args);
PyObject* free_meshcloth_mc2_context(PyObject*, PyObject* args);
PyObject* solve_meshcloth_mc2_context(PyObject*, PyObject* args);
PyObject* solve_meshcloth_mc2_context_cached_params(PyObject*, PyObject* args);

}  // namespace hotools
