// hotools_physics.native — 物理世界原生扩展（nanobind 模块入口）
//
// 归属：HoTools-Omninode-Physics / PhysicsWorld/native
// 由 _native/src/hotools_native.cpp 的物理部分拆分而来（2026 分仓）。
//
// 模块名刻意不复用 hotools_native：父仓 HoTools 的 hotools_native 只提供
// PropertyCurve 采样内核。两者同名时只能依赖 sys.path 顺序才能加载正确，
// 且失败表现为“符号缺失”这种难查的静默降级，故物理侧使用独立模块名。
//
// 两侧不共享任何 nanobind 类型，只通过 Python 对象边界交互。

#include <Python.h>

#include <nanobind/nanobind.h>

#include "field_runtime_bindings.hpp"
#include "mc2_bindings.hpp"
#include "mesh_xpbd_bindings.hpp"
#include "rigid_writeback.hpp"

// spring_bone_vrm 仍是手写 C-API 入口（非 nanobind 绑定），这里只做转发。
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

NB_MODULE(hotools_physics, module) {
    module.doc() = "Native acceleration backend for the HoTools OmniNode physics world.";

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

    hotools::bind_field_runtime(module);
    hotools::bind_mc2(module);
    hotools::bind_mc2_domain_cpu(module);
    hotools::bind_mesh_xpbd(module);
    hotools::bind_rigid_writeback(module);
}
