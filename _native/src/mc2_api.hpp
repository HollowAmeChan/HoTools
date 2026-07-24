#pragma once

#include <Python.h>

namespace hotools {

PyObject* mc2_mesh_frame_orientations_v1(PyObject*, PyObject* args);
PyObject* mc2_bone_frame_orientations_v1(PyObject*, PyObject* args);
PyObject* mc2_mesh_static_fingerprint_v1(PyObject*, PyObject* args);
PyObject* mc2_bone_static_fingerprint_v1(PyObject*, PyObject* args);

}  // namespace hotools
