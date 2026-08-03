#include "mesh_xpbd_bindings.hpp"

#include "hotools_mesh_xpbd.hpp"

#include <nanobind/ndarray.h>

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace nb = nanobind;

namespace hotools {
namespace {

using cf32_1d = nb::ndarray<const float, nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using cf32_2d = nb::ndarray<const float, nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using ci32_1d = nb::ndarray<const std::int32_t, nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using ci32_2d = nb::ndarray<const std::int32_t, nb::ndim<2>, nb::c_contig, nb::device::cpu>;

void require_float3_rows(cf32_2d values, const char* name) {
    if (values.shape(1) != 3) {
        throw nb::value_error((std::string(name) + " must have shape [N,3]").c_str());
    }
}

std::vector<float> copy_float_1d(cf32_1d values) {
    return std::vector<float>(values.data(), values.data() + values.shape(0));
}

std::vector<float> copy_float_2d(cf32_2d values) {
    require_float3_rows(values, "float3 array");
    const std::size_t count = static_cast<std::size_t>(values.shape(0) * 3);
    return std::vector<float>(values.data(), values.data() + count);
}

std::vector<std::int32_t> copy_index_pairs(ci32_2d values) {
    if (values.shape(1) != 2) {
        throw nb::value_error("constraint indices must have shape [N,2]");
    }
    const std::size_t count = static_cast<std::size_t>(values.shape(0) * 2);
    return std::vector<std::int32_t>(values.data(), values.data() + count);
}

template<typename T>
nb::ndarray<nb::numpy, T> owned_array_2d(
    const std::vector<T>& source,
    std::size_t rows,
    std::size_t columns
) {
    auto* owner_data = new std::vector<T>(source);
    nb::capsule owner(owner_data, [](void* pointer) noexcept {
        delete static_cast<std::vector<T>*>(pointer);
    });
    return nb::ndarray<nb::numpy, T>(
        owner_data->data(), {rows, columns}, owner
    );
}

nb::ndarray<nb::numpy, float> read_positions(mesh_xpbd::Context& context) {
    const auto& values = context.positions();
    return owned_array_2d(values, values.size() / 3, 3);
}

mesh_xpbd::ColliderView collider_view(
    ci32_1d types,
    ci32_1d group_bits,
    cf32_2d centers,
    cf32_2d segment_a,
    cf32_2d segment_b,
    cf32_1d radii
) {
    const std::size_t count = static_cast<std::size_t>(types.shape(0));
    require_float3_rows(centers, "collider_centers");
    require_float3_rows(segment_a, "collider_segment_a");
    require_float3_rows(segment_b, "collider_segment_b");
    if (static_cast<std::size_t>(group_bits.shape(0)) != count ||
        static_cast<std::size_t>(centers.shape(0)) != count ||
        static_cast<std::size_t>(segment_a.shape(0)) != count ||
        static_cast<std::size_t>(segment_b.shape(0)) != count ||
        static_cast<std::size_t>(radii.shape(0)) != count) {
        throw nb::value_error("collider arrays must have the same row count");
    }
    return {
        count,
        types.data(),
        group_bits.data(),
        centers.data(),
        segment_a.data(),
        segment_b.data(),
        radii.data(),
    };
}

}  // namespace

void bind_mesh_xpbd(nb::module_& module) {
    nb::class_<mesh_xpbd::Context>(module, "MeshXpbdContextV1")
        .def("update_reference", [](
            mesh_xpbd::Context& context,
            cf32_2d rest_positions,
            cf32_1d inverse_masses,
            cf32_1d collision_radii
        ) {
            require_float3_rows(rest_positions, "rest_positions");
            context.update_reference(
                copy_float_2d(rest_positions),
                copy_float_1d(inverse_masses),
                copy_float_1d(collision_radii)
            );
        },
        nb::arg("rest_positions").noconvert(),
        nb::arg("inverse_masses").noconvert(),
        nb::arg("collision_radii").noconvert())
        .def("update_pin_targets", [](
            mesh_xpbd::Context& context,
            cf32_2d pin_positions
        ) {
            require_float3_rows(pin_positions, "pin_positions");
            context.update_pin_targets(copy_float_2d(pin_positions));
        }, nb::arg("pin_positions").noconvert())
        .def("update_parameters", &mesh_xpbd::Context::update_parameters,
            nb::arg("damping"), nb::arg("stretch_compliance"),
            nb::arg("bend_compliance"), nb::arg("iterations"))
        .def("reset", [](mesh_xpbd::Context& context, cf32_2d positions) {
            require_float3_rows(positions, "positions");
            context.reset(copy_float_2d(positions));
        }, nb::arg("positions").noconvert())
        .def("step", [](
            mesh_xpbd::Context& context,
            float delta_time,
            std::int32_t substeps,
            cf32_1d gravity_direction,
            float gravity_power,
            ci32_1d collider_types,
            ci32_1d collider_group_bits,
            cf32_2d collider_centers,
            cf32_2d collider_segment_a,
            cf32_2d collider_segment_b,
            cf32_1d collider_radii,
            std::uint32_t collided_by_groups
        ) {
            if (gravity_direction.shape(0) != 3) {
                throw nb::value_error("gravity_direction must have shape [3]");
            }
            const auto colliders = collider_view(
                collider_types, collider_group_bits, collider_centers,
                collider_segment_a, collider_segment_b, collider_radii
            );
            context.step(
                delta_time,
                substeps,
                {
                    gravity_direction(0),
                    gravity_direction(1),
                    gravity_direction(2),
                },
                gravity_power,
                colliders,
                collided_by_groups
            );
            return read_positions(context);
        },
        nb::arg("delta_time"), nb::arg("substeps"),
        nb::arg("gravity_direction").noconvert(), nb::arg("gravity_power"),
        nb::arg("collider_types").noconvert(),
        nb::arg("collider_group_bits").noconvert(),
        nb::arg("collider_centers").noconvert(),
        nb::arg("collider_segment_a").noconvert(),
        nb::arg("collider_segment_b").noconvert(),
        nb::arg("collider_radii").noconvert(),
        nb::arg("collided_by_groups"))
        .def("read_positions", &read_positions)
        .def("stats", [](mesh_xpbd::Context& context) {
            const auto& stats = context.stats();
            nb::dict result;
            result["schema_version"] = mesh_xpbd::kSchemaVersion;
            result["step_count"] = stats.step_count;
            result["reset_count"] = stats.reset_count;
            result["parameter_update_count"] = stats.parameter_update_count;
            result["reference_update_count"] = stats.reference_update_count;
            result["pin_target_update_count"] = stats.pin_target_update_count;
            result["last_contact_count"] = stats.last_contact_count;
            result["particle_count"] = stats.particle_count;
            result["stretch_constraint_count"] = stats.stretch_constraint_count;
            result["bend_constraint_count"] = stats.bend_constraint_count;
            return result;
        })
        .def("dispose", &mesh_xpbd::Context::dispose)
        .def_prop_ro("disposed", &mesh_xpbd::Context::disposed);

    module.def(
        "mesh_xpbd_create_context_v1",
        [](cf32_2d rest_positions,
           cf32_1d inverse_masses,
           ci32_2d stretch_indices,
           ci32_2d bend_indices,
           cf32_1d collision_radii,
           float damping,
           float stretch_compliance,
           float bend_compliance,
           std::int32_t iterations) {
            require_float3_rows(rest_positions, "rest_positions");
            return new mesh_xpbd::Context(
                copy_float_2d(rest_positions),
                copy_float_1d(inverse_masses),
                copy_index_pairs(stretch_indices),
                copy_index_pairs(bend_indices),
                copy_float_1d(collision_radii),
                damping,
                stretch_compliance,
                bend_compliance,
                iterations
            );
        },
        nb::rv_policy::take_ownership,
        nb::arg("rest_positions").noconvert(),
        nb::arg("inverse_masses").noconvert(),
        nb::arg("stretch_indices").noconvert(),
        nb::arg("bend_indices").noconvert(),
        nb::arg("collision_radii").noconvert(),
        nb::arg("damping"),
        nb::arg("stretch_compliance"),
        nb::arg("bend_compliance"),
        nb::arg("iterations"),
        "Create a strict XPBD mesh context with owned native state."
    );
}

}  // namespace hotools
