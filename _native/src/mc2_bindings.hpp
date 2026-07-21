#pragma once

#include <nanobind/nanobind.h>

namespace hotools {

void bind_mc2(nanobind::module_& module);
void bind_mc2_domain_cpu(nanobind::module_& module);

}  // namespace hotools
