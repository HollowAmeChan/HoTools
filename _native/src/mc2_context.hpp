#pragma once

#include <Python.h>

namespace hotools {

PyObject* create_meshcloth_mc2_context_object(long vertex_count,
                                              long distance_count,
                                              long bend_count,
                                              long collider_radius_count);
PyObject* update_meshcloth_mc2_context_static_object(PyObject* context_object,
                                                     long vertex_count,
                                                     long distance_count,
                                                     long bend_count,
                                                     long collider_radius_count);
PyObject* update_meshcloth_mc2_context_static_arrays(PyObject*, PyObject* args);
PyObject* update_meshcloth_mc2_context_params_object(PyObject* context_object, long param_slot_count);
PyObject* update_meshcloth_mc2_context_param_arrays(PyObject*, PyObject* args);
PyObject* meshcloth_mc2_context_info_object(PyObject* context_object);
PyObject* free_meshcloth_mc2_context_object(PyObject* context_object);
PyObject* solve_meshcloth_mc2_context(PyObject*, PyObject* args);
PyObject* solve_meshcloth_mc2_context_cached_params(PyObject*, PyObject* args);

}  // namespace hotools
