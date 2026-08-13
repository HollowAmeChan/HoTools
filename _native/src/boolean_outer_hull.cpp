#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include <igl/copyleft/cgal/outer_hull.h>
#include <igl/copyleft/cgal/mesh_boolean.h>

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/boost/graph/helpers.h>
#include <CGAL/Polygon_mesh_processing/border.h>
#include <CGAL/Polygon_mesh_processing/manifoldness.h>
#include <CGAL/Polygon_mesh_processing/orientation.h>
#include <CGAL/Polygon_mesh_processing/orient_polygon_soup.h>
#include <CGAL/Polygon_mesh_processing/polygon_soup_to_polygon_mesh.h>
#include <CGAL/Polygon_mesh_processing/repair.h>
#include <CGAL/Polygon_mesh_processing/repair_polygon_soup.h>
#include <CGAL/Polygon_mesh_processing/repair_self_intersections.h>
#include <CGAL/Polygon_mesh_processing/self_intersections.h>
#include <CGAL/Polygon_mesh_processing/triangulate_faces.h>
#include <CGAL/Polygon_mesh_processing/triangulate_hole.h>

#include <Eigen/Core>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iterator>
#include <queue>
#include <string>
#include <stdexcept>
#include <unordered_set>
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

using RepairKernel = CGAL::Exact_predicates_inexact_constructions_kernel;
using RepairPoint = RepairKernel::Point_3;
using RepairMesh = CGAL::Surface_mesh<RepairPoint>;
namespace PMP = CGAL::Polygon_mesh_processing;

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
        value = 0.0;  // 统一负零表示。
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

nb::dict boolean_mesh(
    const VertexInput& vertices_a,
    const TriangleInput& faces_a,
    const VertexInput& vertices_b,
    const TriangleInput& faces_b,
    const std::int32_t operation
) {
    if (operation < 0 || operation > 2) {
        throw std::invalid_argument("布尔运算类型必须为 0（交集）、1（并集）或 2（差集）");
    }
    Eigen::Map<const MatrixXdR> va(vertices_a.data(), vertices_a.shape(0), 3);
    Eigen::Map<const MatrixXiR> fa(reinterpret_cast<const int*>(faces_a.data()), faces_a.shape(0), 3);
    Eigen::Map<const MatrixXdR> vb(vertices_b.data(), vertices_b.shape(0), 3);
    Eigen::Map<const MatrixXiR> fb(reinterpret_cast<const int*>(faces_b.data()), faces_b.shape(0), 3);

    auto validate_solid = [](const MatrixXdR& vertices, const MatrixXiR& faces, const char* name) {
        RepairMesh mesh;
        std::vector<RepairMesh::Vertex_index> vertex_map;
        vertex_map.reserve(static_cast<std::size_t>(vertices.rows()));
        for (Eigen::Index i = 0; i < vertices.rows(); ++i) {
            vertex_map.push_back(mesh.add_vertex(RepairPoint(vertices(i, 0), vertices(i, 1), vertices(i, 2))));
        }
        for (Eigen::Index i = 0; i < faces.rows(); ++i) {
            const auto face = mesh.add_face(
                vertex_map[static_cast<std::size_t>(faces(i, 0))],
                vertex_map[static_cast<std::size_t>(faces(i, 1))],
                vertex_map[static_cast<std::size_t>(faces(i, 2))]
            );
            if (face == RepairMesh::null_face()) {
                throw std::runtime_error(std::string(name) + " 不是有效的边流形网格");
            }
        }
        std::vector<RepairMesh::Halfedge_index> non_manifold;
        PMP::non_manifold_vertices(mesh, std::back_inserter(non_manifold));
        if (!CGAL::is_closed(mesh) || !non_manifold.empty()) {
            throw std::runtime_error(std::string(name) + " 必须是封闭流形网格，请先运行自动优化");
        }
        // 自交网格不满足 is_outward_oriented 的前置条件，只在可检查时验证朝向。
        if (!PMP::does_self_intersect(mesh) && !PMP::is_outward_oriented(mesh)) {
            throw std::runtime_error(std::string(name) + " 面朝向不一致，请先运行自动优化");
        }
    };
    validate_solid(MatrixXdR(va), MatrixXiR(fa), "活动物体");
    validate_solid(MatrixXdR(vb), MatrixXiR(fb), "非活动物体");
    MatrixXdR vc;
    MatrixXiR fc;
    Eigen::VectorXi j;
    const auto type = operation == 0
        ? igl::MESH_BOOLEAN_TYPE_INTERSECT
        : operation == 1
            ? igl::MESH_BOOLEAN_TYPE_UNION
            : igl::MESH_BOOLEAN_TYPE_MINUS;
    {
        nb::gil_scoped_release release;
        const bool valid = igl::copyleft::cgal::mesh_boolean(va, fa, vb, fb, type, vc, fc, j);
        if (!valid) {
            throw std::runtime_error("CGAL 无法为输入网格建立稳定的 winding number 场");
        }
    }
    std::vector<double> out_vertices(vc.data(), vc.data() + vc.size());
    std::vector<std::int32_t> out_faces(
        reinterpret_cast<const std::int32_t*>(fc.data()),
        reinterpret_cast<const std::int32_t*>(fc.data()) + fc.size()
    );
    nb::dict result;
    result["vertices"] = make_numpy<double>(std::move(out_vertices), {static_cast<std::size_t>(vc.rows()), 3U});
    result["faces"] = make_numpy<std::int32_t>(std::move(out_faces), {static_cast<std::size_t>(fc.rows()), 3U});
    return result;
}

nb::dict auto_optimize_mesh(
    const VertexInput& vertices,
    const IndexInput& polygon_vertices,
    const IndexInput& polygon_offsets
) {
    if (polygon_offsets.shape(0) == 0 || polygon_offsets(0) != 0) {
        throw std::invalid_argument("多边形偏移必须从零开始");
    }
    std::vector<RepairPoint> points;
    points.reserve(vertices.shape(0));
    for (std::size_t i = 0; i < vertices.shape(0); ++i) {
        points.emplace_back(vertices(i, 0), vertices(i, 1), vertices(i, 2));
    }
    std::vector<std::vector<std::size_t>> polygons;
    polygons.reserve(polygon_offsets.shape(0) - 1U);
    for (std::size_t p = 0; p + 1U < polygon_offsets.shape(0); ++p) {
        const std::int32_t begin = polygon_offsets(p);
        const std::int32_t end = polygon_offsets(p + 1U);
        if (begin < 0 || end < begin || end - begin < 3) {
            continue;
        }
        std::vector<std::size_t> polygon;
        polygon.reserve(static_cast<std::size_t>(end - begin));
        for (std::int32_t i = begin; i < end; ++i) {
            const std::int32_t index = polygon_vertices(static_cast<std::size_t>(i));
            if (index < 0 || static_cast<std::size_t>(index) >= points.size()) {
                throw std::invalid_argument("多边形顶点索引超出范围");
            }
            polygon.push_back(static_cast<std::size_t>(index));
        }
        polygons.push_back(std::move(polygon));
    }

    PMP::merge_duplicate_points_in_polygon_soup(points, polygons);
    PMP::orient_polygon_soup(points, polygons);

    RepairMesh mesh;
    PMP::polygon_soup_to_polygon_mesh(points, polygons, mesh);

    // 每次只处理一个边界并重新扫描，避免拓扑修改后继续使用失效的半边句柄。
    auto fill_holes = [](RepairMesh& target) {
        std::size_t filled = 0;
        for (;;) {
            std::vector<RepairMesh::Halfedge_index> borders;
            PMP::extract_boundary_cycles(target, std::back_inserter(borders));
            if (borders.empty()) {
                break;
            }
            bool progress = false;
            for (const auto border : borders) {
                std::vector<RepairMesh::Face_index> patch_faces;
                PMP::triangulate_hole(
                    target,
                    border,
                    CGAL::parameters::face_output_iterator(std::back_inserter(patch_faces))
                );
                if (!patch_faces.empty()) {
                    ++filled;
                    progress = true;
                    break;
                }
            }
            if (!progress) {
                break;
            }
        }
        return filled;
    };

    // 先封闭边界，再把网格三角化后检测并排除自交。
    std::size_t filled_holes = fill_holes(mesh);
    PMP::triangulate_faces(mesh);
    const bool had_self_intersections = PMP::does_self_intersect(mesh);
    bool self_intersections_fixed = true;
    if (had_self_intersections) {
        // 猴头耳部等复杂区域可能无法在保持原属的前提下展开，允许 CGAL
        // 拆分必要的非流形顶点，并增加局部修复迭代次数。
        self_intersections_fixed = PMP::experimental::remove_self_intersections(
            mesh,
            CGAL::parameters::preserve_genus(false)
                .number_of_iterations(20)
                .use_smoothing(true)
        );
    }

    // 排除自交可能重新产生边界，因此再次封洞并以最终结果复查。
    filled_holes += fill_holes(mesh);
    const bool remaining_self_intersections = PMP::does_self_intersect(mesh);
    const bool repair_attempt_succeeded = self_intersections_fixed;
    // remove_self_intersections 的返回值表示本轮过程是否全部完成，最终状态以
    // 重新检测为准；部分修复后没有残留自交时仍然是可用结果。
    self_intersections_fixed = !remaining_self_intersections;

    std::vector<RepairMesh::Halfedge_index> non_manifold;
    PMP::non_manifold_vertices(mesh, std::back_inserter(non_manifold));
    const bool closed = CGAL::is_closed(mesh);
    const bool manifold = non_manifold.empty();
    if (closed && manifold && !remaining_self_intersections) {
        PMP::orient_to_bound_a_volume(mesh);
    }

    std::vector<double> output_vertices;
    output_vertices.reserve(mesh.number_of_vertices() * 3U);
    std::unordered_map<std::size_t, std::int32_t> vertex_ids;
    for (const auto vertex : mesh.vertices()) {
        const RepairPoint& point = mesh.point(vertex);
        vertex_ids.emplace(vertex.idx(), static_cast<std::int32_t>(vertex_ids.size()));
        output_vertices.push_back(point.x());
        output_vertices.push_back(point.y());
        output_vertices.push_back(point.z());
    }
    std::vector<std::int32_t> output_faces;
    output_faces.reserve(mesh.number_of_faces() * 3U);
    for (const auto face : mesh.faces()) {
        std::vector<std::int32_t> face_vertices;
        for (const auto vertex : CGAL::vertices_around_face(halfedge(face, mesh), mesh)) {
            face_vertices.push_back(vertex_ids.at(vertex.idx()));
        }
        if (face_vertices.size() == 3U) {
            output_faces.insert(output_faces.end(), face_vertices.begin(), face_vertices.end());
        }
    }

    const std::size_t output_vertex_count = output_vertices.size() / 3U;
    const std::size_t output_face_count = output_faces.size() / 3U;
    nb::dict result;
    result["vertices"] = make_numpy<double>(std::move(output_vertices), {output_vertex_count, 3U});
    result["faces"] = make_numpy<std::int32_t>(std::move(output_faces), {output_face_count, 3U});
    result["had_self_intersections"] = had_self_intersections;
    result["self_intersections_fixed"] = self_intersections_fixed;
    result["repair_attempt_succeeded"] = repair_attempt_succeeded;
    result["filled_holes"] = filled_holes;
    result["closed"] = closed;
    result["manifold"] = manifold;
    result["non_manifold_vertices"] = non_manifold.size();
    return result;
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
        "HoTools 的 CGAL/libigl 精确布尔运算模块。";
    module.def(
        "boolean",
        &boolean_mesh,
        nb::arg("vertices_a").noconvert(),
        nb::arg("faces_a").noconvert(),
        nb::arg("vertices_b").noconvert(),
        nb::arg("faces_b").noconvert(),
        nb::arg("operation").noconvert(),
        "执行交集、并集或差集布尔运算。"
    );
    module.def(
        "auto_optimize",
        &auto_optimize_mesh,
        nb::arg("vertices").noconvert(),
        nb::arg("polygon_vertices").noconvert(),
        nb::arg("polygon_offsets").noconvert(),
        "自动优化网格并返回封闭和流形检查结果。"
    );
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
