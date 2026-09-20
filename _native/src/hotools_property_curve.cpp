#include <Python.h>

#include <nanobind/nanobind.h>

#include "hotools_property_curve.hpp"

namespace nb = nanobind;

namespace {

nb::object steal_or_throw(PyObject* result) {
    if (result == nullptr) {
        throw nb::python_error();
    }
    return nb::steal<nb::object>(result);
}

}  // namespace

// hotools_native 的原生入口：只承载 PropertyCurve 的采样内核。
//
// PropertyCurve 是 HoTools 父仓的贮藏内容（核心资源），物理世界
// （MC2 / Field / XPBD / SpringVRM / RigidWriteback）只是它的调用方。
// 物理世界的原生实现位于 OmniNode/PhysicsWorld/native/，编译为独立模块
// hotools_physics（另有 hotools_jolt），详见该目录 README。
// 两侧不共享任何 nanobind 类型，只通过 Python 对象边界交互。
NB_MODULE(hotools_native, module) {
    module.doc() = "Native acceleration backend for HoTools PropertyCurve (sampler kernels).";

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
}
