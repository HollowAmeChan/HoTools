#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include <igl/copyleft/cgal/outer_hull.h>

#include <Eigen/Core>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <unordered_map>
#include <utility>
#include <vector>

namespace nb = nanobind;

namespace {

using VertexInput = nb::ndarray<const double, nb::numpy, nb::shape<-1, 3>,
                                nb::c_contig, nb::device::cpu>;
using TriangleInput = nb::ndarray<const std::int32_t, nb::numpy,
                                  nb::shape<-1, 3>, nb::c_contig,
                                  nb::device::cpu>;
using IndexInput = nb::ndarray<const std::int32_t, nb::numpy, nb::shape<-1>,
                               nb::c_contig, nb::device::cpu>;

using MatrixXdR = Eigen::Matrix<double, Eigen::Dynamic, 3, Eigen::RowMajor>;
using MatrixXiR = Eigen::Matrix<int, Eigen::Dynamic, 3, Eigen::RowMajor>;
static_assert(sizeof(int) == sizeof(std::int32_t));

struct CoordinateKey {
    std::array<std::uint64_t, 3> bits{};

    bool operator==(const CoordinateKey& other) const noexcept {
        return bits == other.bits;
    }
};

struct CoordinateHash {
    std::size_t operator()(const CoordinateKey& key) const noexcept {
        std::size_t seed = 0;
        for (const std::uint64_t value : key.bits) {
            seed ^= std::hash<std::uint64_t>{}(value) +
                    0x9e3779b97f4a7c15ULL + (seed << 6U) + (seed >> 2U);
        }
        return seed;
    }
};

std::uint64_t coordinate_bits(double value) {
    if (value == 0.0) {
        value = 0.0;  // Canonicalize negative zero.
    }
    std::uint64_t bits = 0;
    static_assert(sizeof(bits) == sizeof(value));
    std::memcpy(&bits, &value, sizeof(bits));
    return bits;
}

CoordinateKey coordinate_key(double x, double y, double z) {
    return {{coordinate_bits(x), coordinate_bits(y), coordinate_bits(z)}};
}

template <typename T>
struct ArrayStorage {
    explicit ArrayStorage(std::vector<T>&& source) : values(std::move(source)) {}
    std::vector<T> values;
    T empty_value{};
};

template <typename T>
nb::ndarray<nb::numpy, T> make_numpy(
    std::vector<T>&& values,
    std::initializer_list<std::size_t> shape
) {
    auto* storage = new ArrayStorage<T>(std::move(values));
    T* data = storage->values.empty() ? &storage->empty_value
                                      : storage->values.data();
    nb::capsule owner(storage, [](void* pointer) noexcept {
        delete static_cast<ArrayStorage<T>*>(pointer);
    });
    return nb::ndarray<nb::numpy, T>(data, shape, owner);
}

void validate_inputs(
    const VertexInput& vertices,
    const TriangleInput& triangles,
    const IndexInput& triangle_polygons,
    const IndexInput& polygon_vertices,
    const IndexInput& polygon_offsets
) {
    const std::size_t vertex_count = vertices.shape(0);
    const std::size_t triangle_count = triangles.shape(0);
    if (triangle_polygons.shape(0) != triangle_count) {
        throw std::invalid_argument(
            "triangle_polygons must contain one polygon index per triangle"
        );
    }
    if (polygon_offsets.shape(0) == 0 || polygon_offsets(0) != 0) {
        throw std::invalid_argument("polygon_offsets must start with zero");
    }
    const std::int32_t final_offset =
        polygon_offsets(polygon_offsets.shape(0) - 1);
    if (final_offset < 0 || static_cast<std::size_t>(final_offset) !=
                                polygon_vertices.shape(0)) {
        throw std::invalid_argument(
            "the last polygon offset must equal polygon_vertices.size"
        );
    }

    for (std::size_t i = 0; i < vertex_count; ++i) {
        for (std::size_t axis = 0; axis < 3; ++axis) {
            if (!std::isfinite(vertices(i, axis))) {
                throw std::invalid_argument("vertices must contain finite coordinates");
            }
        }
    }
    for (std::size_t i = 0; i < triangle_count; ++i) {
        for (std::size_t corner = 0; corner < 3; ++corner) {
            const std::int32_t index = triangles(i, corner);
            if (index < 0 || static_cast<std::size_t>(index) >= vertex_count) {
                throw std::invalid_argument("triangle vertex index is out of range");
            }
        }
    }

    const std::size_t polygon_count = polygon_offsets.shape(0) - 1;
    for (std::size_t p = 0; p < polygon_count; ++p) {
        const std::int32_t begin = polygon_offsets(p);
        const std::int32_t end = polygon_offsets(p + 1);
        if (begin < 0 || end < begin || end - begin < 3) {
            throw std::invalid_argument("each polygon must have at least three vertices");
        }
        for (std::int32_t i = begin; i < end; ++i) {
            const std::int32_t index = polygon_vertices(static_cast<std::size_t>(i));
            if (index < 0 || static_cast<std::size_t>(index) >= vertex_count) {
                throw std::invalid_argument("polygon vertex index is out of range");
            }
        }
    }
    for (std::size_t i = 0; i < triangle_count; ++i) {
        const std::int32_t polygon = triangle_polygons(i);
        if (polygon < 0 || static_cast<std::size_t>(polygon) >= polygon_count) {
            throw std::invalid_argument("triangle polygon index is out of range");
        }
    }
}

nb::dict outer_hull(
    const VertexInput& vertices,
    const TriangleInput& triangles,
    const IndexInput& triangle_polygons,
    const IndexInput& polygon_vertices,
    const IndexInput& polygon_offsets
) {
    validate_inputs(
        vertices, triangles, triangle_polygons, polygon_vertices, polygon_offsets
    );

    const Eigen::Index vertex_count = static_cast<Eigen::Index>(vertices.shape(0));
    const Eigen::Index triangle_count = static_cast<Eigen::Index>(triangles.shape(0));
    const std::size_t polygon_count = polygon_offsets.shape(0) - 1;

    Eigen::Map<const MatrixXdR> input_vertices(
        vertices.data(), vertex_count, 3
    );
    Eigen::Map<const MatrixXiR> input_triangles(
        reinterpret_cast<const int*>(triangles.data()), triangle_count, 3
    );

    MatrixXdR hull_vertices;
    MatrixXiR hull_triangles;
    Eigen::VectorXi source_triangles;
    Eigen::VectorXi flipped;
    if (triangle_count != 0) {
        nb::gil_scoped_release release;
        igl::copyleft::cgal::outer_hull(
            input_vertices,
            input_triangles,
            hull_vertices,
            hull_triangles,
            source_triangles,
            flipped
        );
    } else {
        hull_vertices.resize(0, 3);
        hull_triangles.resize(0, 3);
    }

    const std::size_t hull_face_count =
        static_cast<std::size_t>(hull_triangles.rows());
    std::unordered_map<CoordinateKey, std::int32_t, CoordinateHash>
        hull_vertex_by_coordinate;
    hull_vertex_by_coordinate.reserve(
        static_cast<std::size_t>(hull_vertices.rows()) * 2U + 1U
    );
    for (Eigen::Index i = 0; i < hull_vertices.rows(); ++i) {
        hull_vertex_by_coordinate.emplace(
            coordinate_key(
                hull_vertices(i, 0), hull_vertices(i, 1), hull_vertices(i, 2)
            ),
            static_cast<std::int32_t>(i)
        );
    }

    std::vector<std::int32_t> input_to_hull(
        static_cast<std::size_t>(vertex_count), -1
    );
    for (Eigen::Index i = 0; i < vertex_count; ++i) {
        const auto found = hull_vertex_by_coordinate.find(
            coordinate_key(
                input_vertices(i, 0), input_vertices(i, 1), input_vertices(i, 2)
            )
        );
        if (found != hull_vertex_by_coordinate.end()) {
            input_to_hull[static_cast<std::size_t>(i)] = found->second;
        }
    }

    std::vector<std::int32_t> output_count(
        static_cast<std::size_t>(triangle_count), 0
    );
    std::vector<std::int32_t> output_face(
        static_cast<std::size_t>(triangle_count), -1
    );
    std::vector<std::vector<std::int32_t>> polygon_triangles(polygon_count);
    for (Eigen::Index t = 0; t < triangle_count; ++t) {
        polygon_triangles[static_cast<std::size_t>(triangle_polygons(t))]
            .push_back(static_cast<std::int32_t>(t));
    }
    for (std::size_t f = 0; f < hull_face_count; ++f) {
        const int source = source_triangles(static_cast<Eigen::Index>(f));
        if (source < 0 || source >= triangle_count) {
            throw std::runtime_error("outer_hull returned an invalid source face");
        }
        ++output_count[static_cast<std::size_t>(source)];
        output_face[static_cast<std::size_t>(source)] =
            static_cast<std::int32_t>(f);
    }

    std::vector<bool> restored(polygon_count, false);
    std::vector<bool> skip_hull_face(hull_face_count, false);
    std::vector<bool> restore_reversed(polygon_count, false);
    std::size_t restored_polygon_count = 0;

    for (std::size_t p = 0; p < polygon_count; ++p) {
        const std::int32_t begin = polygon_offsets(p);
        const std::int32_t end = polygon_offsets(p + 1);
        const std::size_t corner_count = static_cast<std::size_t>(end - begin);
        const auto& source_faces = polygon_triangles[p];
        if (source_faces.size() != corner_count - 2U) {
            continue;
        }

        bool can_restore = true;
        int common_flip = -1;
        for (std::int32_t i = begin; i < end; ++i) {
            if (input_to_hull[static_cast<std::size_t>(polygon_vertices(i))] < 0) {
                can_restore = false;
                break;
            }
        }

        for (const std::int32_t source : source_faces) {
            if (!can_restore || output_count[static_cast<std::size_t>(source)] != 1) {
                can_restore = false;
                break;
            }
            const std::int32_t face = output_face[static_cast<std::size_t>(source)];
            std::array<std::int32_t, 3> expected{};
            std::array<std::int32_t, 3> actual{};
            for (std::size_t c = 0; c < 3; ++c) {
                expected[c] = input_to_hull[static_cast<std::size_t>(
                    input_triangles(source, static_cast<Eigen::Index>(c))
                )];
                actual[c] = hull_triangles(face, static_cast<Eigen::Index>(c));
            }
            std::sort(expected.begin(), expected.end());
            std::sort(actual.begin(), actual.end());
            if (expected != actual || expected.front() < 0) {
                can_restore = false;
                break;
            }
            const int face_flip = flipped(face) != 0 ? 1 : 0;
            if (common_flip < 0) {
                common_flip = face_flip;
            } else if (common_flip != face_flip) {
                can_restore = false;
                break;
            }
        }

        if (!can_restore) {
            continue;
        }
        restored[p] = true;
        restore_reversed[p] = common_flip == 1;
        ++restored_polygon_count;
        for (const std::int32_t source : source_faces) {
            skip_hull_face[static_cast<std::size_t>(
                output_face[static_cast<std::size_t>(source)]
            )] = true;
        }
    }

    std::vector<std::int32_t> face_vertices;
    std::vector<std::int32_t> face_offsets;
    std::vector<std::int32_t> face_sources;
    std::vector<std::int32_t> face_source_triangles;
    face_offsets.reserve(restored_polygon_count + hull_face_count + 1U);
    face_sources.reserve(restored_polygon_count + hull_face_count);
    face_source_triangles.reserve(restored_polygon_count + hull_face_count);
    face_offsets.push_back(0);

    for (std::size_t p = 0; p < polygon_count; ++p) {
        if (!restored[p]) {
            continue;
        }
        const std::int32_t begin = polygon_offsets(p);
        const std::int32_t end = polygon_offsets(p + 1);
        if (!restore_reversed[p]) {
            for (std::int32_t i = begin; i < end; ++i) {
                face_vertices.push_back(input_to_hull[static_cast<std::size_t>(
                    polygon_vertices(i)
                )]);
            }
        } else {
            for (std::int32_t i = end; i > begin; --i) {
                face_vertices.push_back(input_to_hull[static_cast<std::size_t>(
                    polygon_vertices(i - 1)
                )]);
            }
        }
        face_sources.push_back(static_cast<std::int32_t>(p));
        face_source_triangles.push_back(-1);
        face_offsets.push_back(static_cast<std::int32_t>(face_vertices.size()));
    }

    std::size_t seam_triangle_count = 0;
    for (std::size_t f = 0; f < hull_face_count; ++f) {
        if (skip_hull_face[f]) {
            continue;
        }
        for (Eigen::Index c = 0; c < 3; ++c) {
            face_vertices.push_back(
                hull_triangles(static_cast<Eigen::Index>(f), c)
            );
        }
        const int source_triangle = source_triangles(static_cast<Eigen::Index>(f));
        face_sources.push_back(triangle_polygons(
            static_cast<std::size_t>(source_triangle)
        ));
        face_source_triangles.push_back(source_triangle);
        face_offsets.push_back(static_cast<std::int32_t>(face_vertices.size()));
        ++seam_triangle_count;
    }

    std::vector<double> output_vertices;
    if (hull_vertices.size() != 0) {
        output_vertices.assign(
            hull_vertices.data(), hull_vertices.data() + hull_vertices.size()
        );
    }

    const std::size_t face_vertex_count = face_vertices.size();
    const std::size_t face_offset_count = face_offsets.size();
    const std::size_t face_source_count = face_sources.size();
    const std::size_t face_source_triangle_count = face_source_triangles.size();

    nb::dict result;
    result["vertices"] = make_numpy<double>(
        std::move(output_vertices),
        {static_cast<std::size_t>(hull_vertices.rows()), 3U}
    );
    result["face_vertices"] = make_numpy<std::int32_t>(
        std::move(face_vertices), {face_vertex_count}
    );
    result["face_offsets"] = make_numpy<std::int32_t>(
        std::move(face_offsets), {face_offset_count}
    );
    result["face_sources"] = make_numpy<std::int32_t>(
        std::move(face_sources), {face_source_count}
    );
    result["face_source_triangles"] = make_numpy<std::int32_t>(
        std::move(face_source_triangles), {face_source_triangle_count}
    );
    result["restored_polygons"] = restored_polygon_count;
    result["seam_triangles"] = seam_triangle_count;
    return result;
}

}  // namespace

NB_MODULE(hotools_boolean, module) {
    module.doc() =
        "Exact self-union/outer-hull reconstruction for HoTools (CGAL/libigl).";
    module.def(
        "outer_hull",
        &outer_hull,
        nb::arg("vertices").noconvert(),
        nb::arg("triangles").noconvert(),
        nb::arg("triangle_polygons").noconvert(),
        nb::arg("polygon_vertices").noconvert(),
        nb::arg("polygon_offsets").noconvert(),
        "Remove internal cells and cavities while preserving untouched polygons."
    );
}
