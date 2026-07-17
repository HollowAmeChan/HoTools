#pragma once

#include <Python.h>

#include "mc2_context_internal.hpp"
#include "python_buffer_utils.hpp"

namespace hotools::mc2_internal {

Mc2ContextV0* context_from(PyObject* object);
bool ensure_live(Mc2ContextV0* context);
bool dict_float(PyObject* dict, const char* key, float value);
bool expect_2d(
    const py::Buffer& buffer,
    const char* name,
    Py_ssize_t rows,
    Py_ssize_t columns
);
bool build_bone_output(Mc2ContextV0& context);

}  // namespace hotools::mc2_internal
