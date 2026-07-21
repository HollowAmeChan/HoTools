#include <Python.h>

#include <nanobind/nanobind.h>

#include "hotools_property_curve.hpp"
#include "mc2_bindings.hpp"

PyObject* spring_vrm_create_context(PyObject*, PyObject*);
PyObject* free_spring_vrm_context(PyObject*, PyObject*);
PyObject* spring_vrm_reset_state(PyObject*, PyObject*);
PyObject* spring_vrm_update_dynamic(PyObject*, PyObject*);
PyObject* spring_vrm_step(PyObject*, PyObject*);
PyObject* spring_vrm_read_results(PyObject*, PyObject*);
PyObject* spring_vrm_read_debug(PyObject*, PyObject*);

namespace nb = nanobind;

namespace {

nb::object steal_or_throw(PyObject* result) {
    if (result == nullptr) {
        throw nb::python_error();
    }
    return nb::steal<nb::object>(result);
}

void call_python_entry(PyObject* (*function)(PyObject*, PyObject*), nb::args args) {
    PyObject* result = function(nullptr, args.ptr());
    if (result == nullptr) {
        throw nb::python_error();
    }
    Py_DECREF(result);
}

}  // namespace

NB_MODULE(hotools_native, module) {
    module.doc() = "Native acceleration backend for HoTools (nanobind module shell).";

    module.def(
        "compile_property_float_curve",
        [](nb::object payload) {
            return steal_or_throw(hotools::compile_property_float_curve_object(payload.ptr()));
        },
        nb::arg("payload"),
        "Compile a float curve payload into a native capsule."
    );
    module.def(
        "compile_property_color_curve",
        [](nb::object payload) {
            return steal_or_throw(hotools::compile_property_color_curve_object(payload.ptr()));
        },
        nb::arg("payload"),
        "Compile a color curve payload into a native capsule."
    );
    module.def(
        "sample_property_float_curve",
        [](nb::object curve, double position, nb::object extend) {
            return steal_or_throw(hotools::sample_property_float_curve_object(
                curve.ptr(), position, extend.ptr()
            ));
        },
        nb::arg("curve"),
        nb::arg("position"),
        nb::arg("extend").none(),
        "Sample a native float curve or payload at one position."
    );
    module.def(
        "sample_property_color_curve",
        [](nb::object curve, double position, nb::object extend) {
            return steal_or_throw(hotools::sample_property_color_curve_object(
                curve.ptr(), position, extend.ptr()
            ));
        },
        nb::arg("curve"),
        nb::arg("position"),
        nb::arg("extend").none(),
        "Sample a native color curve or payload at one position."
    );
    module.def(
        "sample_property_float_curve_many",
        [](nb::object curve, int count, nb::object extend) {
            return steal_or_throw(hotools::sample_property_float_curve_many_object(
                curve.ptr(), count, extend.ptr()
            ));
        },
        nb::arg("curve"),
        nb::arg("count"),
        nb::arg("extend").none(),
        "Sample a native float curve or payload at evenly spaced positions."
    );
    module.def(
        "sample_property_color_curve_many",
        [](nb::object curve, int count, nb::object extend) {
            return steal_or_throw(hotools::sample_property_color_curve_many_object(
                curve.ptr(), count, extend.ptr()
            ));
        },
        nb::arg("curve"),
        nb::arg("count"),
        nb::arg("extend").none(),
        "Sample a native color curve or payload at evenly spaced positions."
    );
    module.def(
        "sample_property_float_curve_positions",
        [](nb::object curve, nb::object positions, nb::object extend) {
            return steal_or_throw(hotools::sample_property_float_curve_positions_object(
                curve.ptr(), positions.ptr(), extend.ptr()
            ));
        },
        nb::arg("curve"),
        nb::arg("positions"),
        nb::arg("extend").none(),
        "Sample a native float curve or payload at explicit positions."
    );
    module.def(
        "sample_property_color_curve_positions",
        [](nb::object curve, nb::object positions, nb::object extend) {
            return steal_or_throw(hotools::sample_property_color_curve_positions_object(
                curve.ptr(), positions.ptr(), extend.ptr()
            ));
        },
        nb::arg("curve"),
        nb::arg("positions"),
        nb::arg("extend").none(),
        "Sample a native color curve or payload at explicit positions."
    );

    module.def(
        "spring_vrm_create_context",
        [](nb::args args) {
            return steal_or_throw(spring_vrm_create_context(nullptr, args.ptr()));
        },
        "Create a VRM SpringBone context (dual-call API)."
    );
    module.def(
        "free_spring_vrm_context",
        [](nb::args args) { call_python_entry(free_spring_vrm_context, args); },
        "Release a VRM SpringBone context. Repeated calls are safe."
    );
    module.def(
        "spring_vrm_reset_state",
        [](nb::args args) { call_python_entry(spring_vrm_reset_state, args); },
        "Reset tail state to current pose tails."
    );
    module.def(
        "spring_vrm_update_dynamic",
        [](nb::args args) { call_python_entry(spring_vrm_update_dynamic, args); },
        "Upload per-frame pose and collider arrays."
    );
    module.def(
        "spring_vrm_step",
        [](nb::args args) { call_python_entry(spring_vrm_step, args); },
        "Step spring bone simulation."
    );
    module.def(
        "spring_vrm_read_results",
        [](nb::args args) { call_python_entry(spring_vrm_read_results, args); },
        "Copy result matrices/quaternions into pre-allocated output buffers."
    );
    module.def(
        "spring_vrm_read_debug",
        [](nb::args args) { call_python_entry(spring_vrm_read_debug, args); },
        "Copy SpringBone context debug/state arrays into pre-allocated output buffers."
    );

    hotools::bind_mc2(module);
    hotools::bind_mc2_domain_cpu(module);
}
