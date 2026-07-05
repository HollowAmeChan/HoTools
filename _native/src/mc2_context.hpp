#pragma once

#include <nanobind/nanobind.h>

namespace nb = nanobind;

namespace hotools {

// register_mc2_context_class 在 mc2_context.cpp 中实现，
// 由 hotools_native.cpp 的 NB_MODULE 调用。
void register_mc2_context_class(nb::module_& m);

}  // namespace hotools
