#pragma once

#include <Python.h>

namespace hotools {

PyObject* compile_property_float_curve_object(PyObject* payload);
PyObject* compile_property_color_curve_object(PyObject* payload);
PyObject* sample_property_float_curve_object(PyObject* curve_object, double position, PyObject* extend_object);
PyObject* sample_property_color_curve_object(PyObject* curve_object, double position, PyObject* extend_object);
PyObject* sample_property_float_curve_many_object(PyObject* curve_object, int sample_count, PyObject* extend_object);
PyObject* sample_property_color_curve_many_object(PyObject* curve_object, int sample_count, PyObject* extend_object);
PyObject* sample_property_float_curve_positions_object(PyObject* curve_object, PyObject* positions_object, PyObject* extend_object);
PyObject* sample_property_color_curve_positions_object(PyObject* curve_object, PyObject* positions_object, PyObject* extend_object);

PyObject* compile_property_float_curve(PyObject* self, PyObject* args);
PyObject* compile_property_color_curve(PyObject* self, PyObject* args);
PyObject* sample_property_float_curve(PyObject* self, PyObject* args);
PyObject* sample_property_color_curve(PyObject* self, PyObject* args);
PyObject* sample_property_float_curve_many(PyObject* self, PyObject* args);
PyObject* sample_property_color_curve_many(PyObject* self, PyObject* args);
PyObject* sample_property_float_curve_positions(PyObject* self, PyObject* args);
PyObject* sample_property_color_curve_positions(PyObject* self, PyObject* args);

}  // namespace hotools
