#include "mc2_static_build.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace hotools {
namespace {

constexpr double kZeroEpsilon = 1.0e-12;
constexpr double kSameSurfaceAngleDegrees = 80.0;
constexpr double kRadiansToDegrees = 57.2957795130823208768;

struct Vec3 {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

Vec3 subtract(const Vec3& left, const Vec3& right) {
    return {left.x - right.x, left.y - right.y, left.z - right.z};
}

Vec3 cross(const Vec3& left, const Vec3& right) {
    return {
        left.y * right.z - left.z * right.y,
        left.z * right.x - left.x * right.z,
        left.x * right.y - left.y * right.x,
    };
}

double dot(const Vec3& left, const Vec3& right) {
    return left.x * right.x + left.y * right.y + left.z * right.z;
}

double length(const Vec3& value) {
    return std::sqrt(dot(value, value));
}

Vec3 normalize(const Vec3& value, const char* name) {
    const double magnitude = length(value);
    if (!(magnitude > kZeroEpsilon) || !std::isfinite(magnitude)) {
        throw std::invalid_argument(std::string(name) + " must be non-zero");
    }
    return {value.x / magnitude, value.y / magnitude, value.z / magnitude};
}

Vec3 negate(const Vec3& value) {
    return {-value.x, -value.y, -value.z};
}

Vec3 load_position(const double* positions, std::int32_t index) {
    const auto offset = static_cast<std::size_t>(index) * 3;
    return {positions[offset], positions[offset + 1], positions[offset + 2]};
}

using Triangle = std::array<std::int32_t, 3>;
using Edge = std::pair<std::int32_t, std::int32_t>;

Edge canonical_edge(std::int32_t first, std::int32_t second) {
    if (first == second) {
        throw std::invalid_argument("MC2 proxy edge cannot be a self edge");
    }
    return first < second ? Edge(first, second) : Edge(second, first);
}

std::array<Edge, 3> triangle_edges(const Triangle& triangle) {
    return {
        canonical_edge(triangle[0], triangle[1]),
        canonical_edge(triangle[1], triangle[2]),
        canonical_edge(triangle[2], triangle[0]),
    };
}

std::int32_t remaining_vertex(const Triangle& triangle, const Edge& edge) {
    for (const auto vertex : triangle) {
        if (vertex != edge.first && vertex != edge.second) return vertex;
    }
    throw std::invalid_argument("triangle does not contain a remaining vertex for edge");
}

Triangle flipped(const Triangle& triangle) {
    return {triangle[0], triangle[2], triangle[1]};
}

Vec3 triangle_normal(const double* positions, const Triangle& triangle) {
    const Vec3 first = load_position(positions, triangle[0]);
    const Vec3 second = load_position(positions, triangle[1]);
    const Vec3 third = load_position(positions, triangle[2]);
    return normalize(cross(subtract(second, first), subtract(third, first)), "triangle normal");
}

double vector_angle(const Vec3& first, const Vec3& second) {
    const double denominator = length(first) * length(second);
    if (!(denominator > kZeroEpsilon)) {
        throw std::invalid_argument("triangle angle vector must be non-zero");
    }
    const double cosine = std::clamp(dot(first, second) / denominator, -1.0, 1.0);
    return std::acos(cosine);
}

double two_triangle_angle(
    const double* positions,
    const Triangle& first,
    const Triangle& second,
    const Edge& edge
) {
    const Vec3 edge_start = load_position(positions, edge.first);
    const Vec3 va = subtract(load_position(positions, edge.second), edge_start);
    const Vec3 vb = subtract(load_position(positions, remaining_vertex(first, edge)), edge_start);
    const Vec3 vc = subtract(load_position(positions, remaining_vertex(second, edge)), edge_start);
    return vector_angle(cross(va, vb), cross(vc, va)) * kRadiansToDegrees;
}

bool two_triangle_open(
    const double* positions,
    const Triangle& second,
    const Edge& edge,
    const Vec3& first_normal
) {
    const Vec3 direction = normalize(
        subtract(
            load_position(positions, remaining_vertex(second, edge)),
            load_position(positions, edge.first)
        ),
        "triangle open direction"
    );
    return dot(first_normal, direction) <= 0.0;
}

}  // namespace

void mc2_optimize_triangle_direction(
    const double* positions,
    std::size_t vertex_count,
    std::int32_t* triangles,
    std::size_t triangle_count,
    double* triangle_normals
) {
    if (positions == nullptr || triangles == nullptr || triangle_normals == nullptr) {
        throw std::invalid_argument("MC2 triangle direction buffers cannot be null");
    }
    std::vector<Triangle> final_triangles(triangle_count);
    std::vector<Vec3> normals(triangle_count);
    std::map<Edge, std::vector<std::size_t>> edge_to_triangles;
    for (std::size_t index = 0; index < triangle_count; ++index) {
        Triangle triangle {
            triangles[index * 3],
            triangles[index * 3 + 1],
            triangles[index * 3 + 2],
        };
        for (const auto vertex : triangle) {
            if (vertex < 0 || static_cast<std::size_t>(vertex) >= vertex_count) {
                throw std::invalid_argument("triangles contains an out-of-range vertex index");
            }
        }
        final_triangles[index] = triangle;
        normals[index] = triangle_normal(positions, triangle);
        for (const auto& edge : triangle_edges(triangle)) {
            auto& values = edge_to_triangles[edge];
            if (std::find(values.begin(), values.end(), index) == values.end()) {
                values.push_back(index);
            }
        }
    }

    std::vector<bool> used(triangle_count, false);
    for (std::size_t start = 0; start < triangle_count; ++start) {
        if (used[start]) continue;
        used[start] = true;
        std::vector<std::size_t> queue {start};
        std::size_t queue_cursor = 0;
        std::vector<std::size_t> layer;
        std::int64_t open_count = 0;
        std::int64_t close_count = 0;
        while (queue_cursor < queue.size()) {
            const std::size_t triangle_index = queue[queue_cursor++];
            const Vec3 normal = normals[triangle_index];
            const Triangle triangle = final_triangles[triangle_index];
            layer.push_back(triangle_index);
            for (const auto& edge : triangle_edges(triangle)) {
                const auto found = edge_to_triangles.find(edge);
                if (found == edge_to_triangles.end()) continue;
                for (const auto other_index : found->second) {
                    if (used[other_index]) continue;
                    Triangle other = final_triangles[other_index];
                    Vec3 other_normal = normals[other_index];
                    if (two_triangle_angle(positions, triangle, other, edge) >
                        kSameSurfaceAngleDegrees) {
                        continue;
                    }
                    if (dot(normal, other_normal) < 0.0) {
                        other = flipped(other);
                        final_triangles[other_index] = other;
                        other_normal = negate(other_normal);
                        normals[other_index] = other_normal;
                    }
                    if (two_triangle_open(positions, other, edge, normal)) {
                        ++open_count;
                    } else {
                        ++close_count;
                    }
                    used[other_index] = true;
                    queue.push_back(other_index);
                }
            }
        }
        if (close_count > open_count) {
            for (const auto triangle_index : layer) {
                final_triangles[triangle_index] = flipped(final_triangles[triangle_index]);
                normals[triangle_index] = negate(normals[triangle_index]);
            }
        }
    }

    for (std::size_t index = 0; index < triangle_count; ++index) {
        triangles[index * 3] = final_triangles[index][0];
        triangles[index * 3 + 1] = final_triangles[index][1];
        triangles[index * 3 + 2] = final_triangles[index][2];
        triangle_normals[index * 3] = normals[index].x;
        triangle_normals[index * 3 + 1] = normals[index].y;
        triangle_normals[index * 3 + 2] = normals[index].z;
    }
}

}  // namespace hotools
