#pragma once

#include <Python.h>

namespace hotools {

PyObject* compile_property_float_curve(PyObject* self, PyObject* args);
PyObject* compile_property_color_curve(PyObject* self, PyObject* args);
PyObject* sample_property_float_curve(PyObject* self, PyObject* args);
PyObject* sample_property_color_curve(PyObject* self, PyObject* args);
PyObject* sample_property_float_curve_many(PyObject* self, PyObject* args);
PyObject* sample_property_color_curve_many(PyObject* self, PyObject* args);
PyObject* sample_property_float_curve_positions(PyObject* self, PyObject* args);
PyObject* sample_property_color_curve_positions(PyObject* self, PyObject* args);

}  // namespace hotools
