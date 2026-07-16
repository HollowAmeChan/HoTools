#include "mc2_static_build.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <map>
#include <limits>
#include <set>
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

struct Vec4 {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
    double w = 1.0;
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

Vec3 add(const Vec3& left, const Vec3& right) {
    return {left.x + right.x, left.y + right.y, left.z + right.z};
}

Vec3 scale(const Vec3& value, double factor) {
    return {value.x * factor, value.y * factor, value.z * factor};
}

Vec3 load_position(const double* positions, std::int32_t index) {
    const auto offset = static_cast<std::size_t>(index) * 3;
    return {positions[offset], positions[offset + 1], positions[offset + 2]};
}

Vec3 load_vec3(const double* values, std::size_t index) {
    const auto offset = index * 3;
    return {values[offset], values[offset + 1], values[offset + 2]};
}

void store_vec3(std::vector<double>& values, std::size_t index, const Vec3& value) {
    const auto offset = index * 3;
    values[offset] = value.x;
    values[offset + 1] = value.y;
    values[offset + 2] = value.z;
}

Vec4 normalize(const Vec4& value, const char* name) {
    const double magnitude = std::sqrt(
        value.x * value.x + value.y * value.y + value.z * value.z + value.w * value.w
    );
    if (!(magnitude > kZeroEpsilon) || !std::isfinite(magnitude)) {
        throw std::invalid_argument(std::string(name) + " must be non-zero");
    }
    return {value.x / magnitude, value.y / magnitude, value.z / magnitude, value.w / magnitude};
}

Vec4 matrix_to_quaternion(
    double m00, double m01, double m02,
    double m10, double m11, double m12,
    double m20, double m21, double m22
) {
    Vec4 quaternion;
    const double trace = m00 + m11 + m22;
    if (trace > 0.0) {
        const double value = std::sqrt(trace + 1.0) * 2.0;
        quaternion = {(m21 - m12) / value, (m02 - m20) / value, (m10 - m01) / value, 0.25 * value};
    } else if (m00 > m11 && m00 > m22) {
        const double value = std::sqrt(1.0 + m00 - m11 - m22) * 2.0;
        quaternion = {0.25 * value, (m01 + m10) / value, (m02 + m20) / value, (m21 - m12) / value};
    } else if (m11 > m22) {
        const double value = std::sqrt(1.0 + m11 - m00 - m22) * 2.0;
        quaternion = {(m01 + m10) / value, 0.25 * value, (m12 + m21) / value, (m02 - m20) / value};
    } else {
        const double value = std::sqrt(1.0 + m22 - m00 - m11) * 2.0;
        quaternion = {(m02 + m20) / value, (m12 + m21) / value, 0.25 * value, (m10 - m01) / value};
    }
    return normalize(quaternion, "bind pose quaternion");
}

Vec4 orientation_quaternion(const Vec3& normal, const Vec3& tangent) {
    const Vec3 forward = normalize(tangent, "orientation tangent");
    const Vec3 up = normalize(normal, "orientation normal");
    const Vec3 right = normalize(cross(up, forward), "orientation right");
    const Vec3 corrected_up = cross(forward, right);
    return matrix_to_quaternion(
        right.x, corrected_up.x, forward.x,
        right.y, corrected_up.y, forward.y,
        right.z, corrected_up.z, forward.z
    );
}

Vec4 quaternion_conjugate(const Vec4& value) {
    return {-value.x, -value.y, -value.z, value.w};
}

Vec4 quaternion_multiply(const Vec4& first, const Vec4& second) {
    return {
        first.w * second.x + first.x * second.w + first.y * second.z - first.z * second.y,
        first.w * second.y - first.x * second.z + first.y * second.w + first.z * second.x,
        first.w * second.z + first.x * second.y - first.y * second.x + first.z * second.w,
        first.w * second.w - first.x * second.x - first.y * second.y - first.z * second.z,
    };
}

Vec3 rotate_by_inverse(const Vec4& rotation, const Vec3& value) {
    const Vec4 pure {value.x, value.y, value.z, 0.0};
    const Vec4 result = quaternion_multiply(
        quaternion_multiply(quaternion_conjugate(rotation), pure),
        rotation
    );
    return {result.x, result.y, result.z};
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

Vec3 triangle_tangent(
    const double* positions,
    const double* uvs,
    const Triangle& triangle
) {
    const Vec3 first = load_position(positions, triangle[0]);
    const Vec3 dist_ba = subtract(load_position(positions, triangle[1]), first);
    const Vec3 dist_ca = subtract(load_position(positions, triangle[2]), first);
    const auto first_uv = static_cast<std::size_t>(triangle[0]) * 2;
    const auto second_uv = static_cast<std::size_t>(triangle[1]) * 2;
    const auto third_uv = static_cast<std::size_t>(triangle[2]) * 2;
    const double uv_ba_x = uvs[second_uv] - uvs[first_uv];
    const double uv_ba_y = uvs[second_uv + 1] - uvs[first_uv + 1];
    const double uv_ca_x = uvs[third_uv] - uvs[first_uv];
    const double uv_ca_y = uvs[third_uv + 1] - uvs[first_uv + 1];
    double area = uv_ba_x * uv_ca_y - uv_ba_y * uv_ca_x;
    if (area == 0.0) area = 1.0;
    const Vec3 tangent = scale(
        {
            dist_ba.x * uv_ca_y - dist_ca.x * uv_ba_y,
            dist_ba.y * uv_ca_y - dist_ca.y * uv_ba_y,
            dist_ba.z * uv_ca_y - dist_ca.z * uv_ba_y,
        },
        -1.0 / area
    );
    const double magnitude = length(tangent);
    if (!(magnitude > kZeroEpsilon)) return {};
    if (!std::isfinite(magnitude)) {
        throw std::invalid_argument("triangle tangent must be finite");
    }
    return scale(tangent, 1.0 / magnitude);
}

std::int32_t narrow_index(std::size_t value, const char* name) {
    if (value > static_cast<std::size_t>(std::numeric_limits<std::int32_t>::max())) {
        throw std::overflow_error(std::string(name) + " exceeds int32");
    }
    return static_cast<std::int32_t>(value);
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

Mc2MeshFinalProxyDerived mc2_build_mesh_final_proxy_derived(
    const double* positions,
    const double* local_normals,
    const double* local_tangents,
    const double* uvs,
    const std::uint8_t* vertex_attributes,
    std::size_t vertex_count,
    const std::int32_t* triangles,
    const double* triangle_normals,
    std::size_t triangle_count,
    const std::int32_t* lines,
    std::size_t line_count
) {
    if (positions == nullptr || local_normals == nullptr || local_tangents == nullptr ||
        uvs == nullptr || vertex_attributes == nullptr ||
        (triangle_count > 0 && (triangles == nullptr || triangle_normals == nullptr)) ||
        (line_count > 0 && lines == nullptr)) {
        throw std::invalid_argument("MC2 final proxy derived buffers cannot be null");
    }
    Mc2MeshFinalProxyDerived result;
    result.local_normals.assign(local_normals, local_normals + vertex_count * 3);
    result.local_tangents.assign(local_tangents, local_tangents + vertex_count * 3);
    result.vertex_attributes.assign(vertex_attributes, vertex_attributes + vertex_count);

    std::vector<Triangle> triangle_values(triangle_count);
    std::vector<Vec3> normal_values(triangle_count);
    std::vector<Vec3> tangent_values(triangle_count);
    std::vector<std::vector<std::size_t>> vertex_triangles(vertex_count);
    std::set<Edge> edge_values;
    std::vector<std::vector<std::int32_t>> adjacency(vertex_count);
    auto add_neighbor = [&adjacency](std::int32_t vertex, std::int32_t neighbor) {
        auto& values = adjacency[static_cast<std::size_t>(vertex)];
        if (std::find(values.begin(), values.end(), neighbor) == values.end()) {
            values.push_back(neighbor);
        }
    };

    for (std::size_t index = 0; index < triangle_count; ++index) {
        const Triangle triangle {
            triangles[index * 3], triangles[index * 3 + 1], triangles[index * 3 + 2],
        };
        for (const auto vertex : triangle) {
            if (vertex < 0 || static_cast<std::size_t>(vertex) >= vertex_count) {
                throw std::invalid_argument("triangles contains an out-of-range vertex index");
            }
            auto& records = vertex_triangles[static_cast<std::size_t>(vertex)];
            if (records.size() < 7) records.push_back(index);
        }
        triangle_values[index] = triangle;
        normal_values[index] = load_vec3(triangle_normals, index);
        tangent_values[index] = triangle_tangent(positions, uvs, triangle);
        for (const auto& edge : triangle_edges(triangle)) edge_values.insert(edge);
        add_neighbor(triangle[0], triangle[1]);
        add_neighbor(triangle[0], triangle[2]);
        add_neighbor(triangle[1], triangle[0]);
        add_neighbor(triangle[1], triangle[2]);
        add_neighbor(triangle[2], triangle[0]);
        add_neighbor(triangle[2], triangle[1]);
    }
    for (std::size_t index = 0; index < line_count; ++index) {
        const std::int32_t first = lines[index * 2];
        const std::int32_t second = lines[index * 2 + 1];
        if (first < 0 || second < 0 ||
            static_cast<std::size_t>(first) >= vertex_count ||
            static_cast<std::size_t>(second) >= vertex_count) {
            throw std::invalid_argument("lines contains an out-of-range vertex index");
        }
        edge_values.insert(canonical_edge(first, second));
        add_neighbor(first, second);
        add_neighbor(second, first);
    }

    result.edges.reserve(edge_values.size() * 2);
    for (const auto& edge : edge_values) {
        result.edges.push_back(edge.first);
        result.edges.push_back(edge.second);
    }
    result.vertex_to_vertex_ranges.reserve(vertex_count * 2);
    for (const auto& values : adjacency) {
        result.vertex_to_vertex_ranges.push_back(
            narrow_index(result.vertex_to_vertex_data.size(), "vertex adjacency")
        );
        result.vertex_to_vertex_ranges.push_back(narrow_index(values.size(), "vertex adjacency"));
        result.vertex_to_vertex_data.insert(
            result.vertex_to_vertex_data.end(),
            values.rbegin(),
            values.rend()
        );
    }

    result.vertex_to_triangle_ranges.reserve(vertex_count * 2);
    for (std::size_t vertex = 0; vertex < vertex_count; ++vertex) {
        const auto& records = vertex_triangles[vertex];
        result.vertex_to_triangle_ranges.push_back(
            narrow_index(result.vertex_to_triangle_data.size() / 2, "vertex triangle records")
        );
        result.vertex_to_triangle_ranges.push_back(
            narrow_index(records.size(), "vertex triangle records")
        );
        if (records.empty()) continue;
        result.vertex_attributes[vertex] |= static_cast<std::uint8_t>(0x80u);
        Vec3 final_normal;
        Vec3 final_tangent;
        for (const auto triangle_index : records) {
            final_normal = add(final_normal, normal_values[triangle_index]);
            final_tangent = add(final_tangent, tangent_values[triangle_index]);
        }
        auto choose_direction = [&records](
            const std::vector<Vec3>& values,
            Vec3 sum,
            const char* name
        ) {
            if (length(sum) >= 0.5) return normalize(sum, name);
            double best_distance = -1.0;
            Vec3 best;
            for (const auto base_index : records) {
                Vec3 candidate;
                const Vec3 base = values[base_index];
                for (const auto other_index : records) {
                    if (other_index == base_index) continue;
                    const Vec3 other = values[other_index];
                    candidate = add(candidate, scale(other, dot(base, other) >= 0.0 ? 1.0 : -1.0));
                }
                const double distance = dot(candidate, candidate);
                if (distance > best_distance) {
                    best_distance = distance;
                    best = base;
                }
            }
            return best;
        };
        final_normal = choose_direction(normal_values, final_normal, "final vertex normal");
        final_tangent = choose_direction(tangent_values, final_tangent, "final vertex tangent");
        for (const auto triangle_index : records) {
            std::int32_t flip = 0;
            if (dot(final_normal, normal_values[triangle_index]) < 0.0) flip |= 0x1;
            if (dot(final_tangent, tangent_values[triangle_index]) < 0.0) flip |= 0x2;
            result.vertex_to_triangle_data.push_back(flip);
            result.vertex_to_triangle_data.push_back(
                narrow_index(triangle_index, "triangle index")
            );
        }

        Vec3 output_normal;
        Vec3 output_tangent;
        const auto record_start = static_cast<std::size_t>(
            result.vertex_to_triangle_ranges[vertex * 2]
        );
        for (std::size_t record_offset = 0; record_offset < records.size(); ++record_offset) {
            const auto triangle_index = records[record_offset];
            const auto data_offset = (record_start + record_offset) * 2;
            const auto flip = result.vertex_to_triangle_data[data_offset];
            output_normal = add(
                output_normal,
                scale(normal_values[triangle_index], (flip & 0x1) == 0 ? 1.0 : -1.0)
            );
            output_tangent = add(
                output_tangent,
                scale(tangent_values[triangle_index], (flip & 0x2) == 0 ? 1.0 : -1.0)
            );
        }
        output_normal = normalize(output_normal, "local normal");
        output_tangent = normalize(cross(output_normal, output_tangent), "local tangent");
        store_vec3(result.local_normals, vertex, output_normal);
        store_vec3(result.local_tangents, vertex, output_tangent);
    }

    result.bind_positions.resize(vertex_count * 3);
    result.bind_rotations.resize(vertex_count * 4);
    for (std::size_t vertex = 0; vertex < vertex_count; ++vertex) {
        const Vec3 position = load_vec3(positions, vertex);
        store_vec3(result.bind_positions, vertex, negate(position));
        const Vec4 rotation = orientation_quaternion(
            load_vec3(result.local_normals.data(), vertex),
            load_vec3(result.local_tangents.data(), vertex)
        );
        const auto offset = vertex * 4;
        result.bind_rotations[offset] = -rotation.x;
        result.bind_rotations[offset + 1] = -rotation.y;
        result.bind_rotations[offset + 2] = -rotation.z;
        result.bind_rotations[offset + 3] = rotation.w;
    }
    return result;
}

Mc2BaselinePoseDepthDerived mc2_build_baseline_pose_depth_derived(
    const double* positions,
    const double* local_normals,
    const double* local_tangents,
    const std::uint8_t* vertex_attributes,
    const std::int32_t* parent_indices,
    std::size_t vertex_count,
    const std::int32_t* baseline_data,
    std::size_t baseline_data_count
) {
    if (positions == nullptr || local_normals == nullptr || local_tangents == nullptr ||
        vertex_attributes == nullptr || parent_indices == nullptr ||
        (baseline_data_count > 0 && baseline_data == nullptr)) {
        throw std::invalid_argument("MC2 baseline pose/depth buffers cannot be null");
    }
    constexpr std::uint8_t kMove = 0x02u;
    constexpr std::uint8_t kZeroDistance = 0x20u;
    constexpr double kZeroDistanceEpsilon = 1.0e-8;
    auto is_move = [](std::uint8_t value) { return (value & kMove) != 0u; };
    Mc2BaselinePoseDepthDerived result;
    result.vertex_attributes.assign(vertex_attributes, vertex_attributes + vertex_count);
    result.root_indices.assign(vertex_count, -1);
    result.depths.assign(vertex_count, 0.0);
    result.vertex_local_positions.assign(vertex_count * 3, 0.0);
    result.vertex_local_rotations.assign(vertex_count * 4, 0.0);
    std::vector<Vec4> orientations(vertex_count);
    std::vector<bool> orientation_ready(vertex_count, false);
    auto get_orientation = [&](std::size_t vertex) {
        if (!orientation_ready[vertex]) {
            orientations[vertex] = orientation_quaternion(
                load_vec3(local_normals, vertex),
                load_vec3(local_tangents, vertex)
            );
            orientation_ready[vertex] = true;
        }
        return orientations[vertex];
    };
    for (std::size_t data_index = 0; data_index < baseline_data_count; ++data_index) {
        const auto vertex_value = baseline_data[data_index];
        if (vertex_value < 0 || static_cast<std::size_t>(vertex_value) >= vertex_count) {
            throw std::invalid_argument("baseline_data contains an out-of-range vertex index");
        }
        const auto vertex = static_cast<std::size_t>(vertex_value);
        const auto parent_value = parent_indices[vertex];
        if (parent_value < 0) {
            result.vertex_local_rotations[vertex * 4 + 3] = 1.0;
            continue;
        }
        if (static_cast<std::size_t>(parent_value) >= vertex_count) {
            throw std::invalid_argument("parent_indices contains an out-of-range vertex index");
        }
        const auto parent = static_cast<std::size_t>(parent_value);
        const Vec4 parent_rotation = get_orientation(parent);
        const Vec4 vertex_rotation = get_orientation(vertex);
        const Vec3 local_position = rotate_by_inverse(
            parent_rotation,
            subtract(load_vec3(positions, vertex), load_vec3(positions, parent))
        );
        store_vec3(result.vertex_local_positions, vertex, local_position);
        const Vec4 local_rotation = normalize(
            quaternion_multiply(quaternion_conjugate(parent_rotation), vertex_rotation),
            "vertex local rotation"
        );
        const auto offset = vertex * 4;
        result.vertex_local_rotations[offset] = local_rotation.x;
        result.vertex_local_rotations[offset + 1] = local_rotation.y;
        result.vertex_local_rotations[offset + 2] = local_rotation.z;
        result.vertex_local_rotations[offset + 3] = local_rotation.w;
        if (length(local_position) < kZeroDistanceEpsilon) {
            result.vertex_attributes[vertex] |= kZeroDistance;
        }
    }
    std::vector<double> lengths(vertex_count, 0.0);
    double max_length = 0.0;
    for (std::size_t vertex = 0; vertex < vertex_count; ++vertex) {
        if (!is_move(result.vertex_attributes[vertex])) continue;
        auto current = vertex;
        auto parent_value = parent_indices[current];
        std::size_t guard = 0;
        while (parent_value >= 0) {
            if (static_cast<std::size_t>(parent_value) >= vertex_count || ++guard > vertex_count) {
                throw std::invalid_argument("parent_indices contains an invalid chain");
            }
            const auto parent = static_cast<std::size_t>(parent_value);
            lengths[vertex] += length(
                subtract(load_vec3(positions, current), load_vec3(positions, parent))
            );
            result.root_indices[vertex] = parent_value;
            if (!is_move(result.vertex_attributes[parent])) break;
            current = parent;
            parent_value = parent_indices[current];
        }
        max_length = std::max(max_length, lengths[vertex]);
    }
    if (max_length > kZeroDistanceEpsilon) {
        for (std::size_t vertex = 0; vertex < vertex_count; ++vertex) {
            result.depths[vertex] = std::clamp(lengths[vertex] / max_length, 0.0, 1.0);
        }
    }
    return result;
}

Mc2MeshBaselineDerived mc2_build_mesh_baseline_derived(
    const double* positions,
    const double* local_normals,
    const double* local_tangents,
    const std::uint8_t* vertex_attributes,
    std::size_t vertex_count,
    const std::int32_t* edges,
    std::size_t edge_count
) {
    if (positions == nullptr || local_normals == nullptr || local_tangents == nullptr ||
        vertex_attributes == nullptr || (edge_count > 0 && edges == nullptr)) {
        throw std::invalid_argument("MC2 baseline derived buffers cannot be null");
    }
    constexpr std::uint8_t kFixed = 0x01u;
    constexpr std::uint8_t kMove = 0x02u;
    constexpr std::uint8_t kTriangle = 0x80u;
    constexpr std::uint8_t kIncludeLine = 0x01u;
    auto is_fixed = [](std::uint8_t value) { return (value & kFixed) != 0u; };
    auto is_move = [](std::uint8_t value) { return (value & kMove) != 0u; };
    auto is_invalid = [](std::uint8_t value) {
        return (value & static_cast<std::uint8_t>(kFixed | kMove)) == 0u;
    };

    Mc2MeshBaselineDerived result;
    result.vertex_attributes.assign(vertex_attributes, vertex_attributes + vertex_count);
    result.parent_indices.assign(vertex_count, -1);
    std::vector<std::vector<std::int32_t>> adjacency(vertex_count);
    for (std::size_t index = 0; index < edge_count; ++index) {
        const std::int32_t first = edges[index * 2];
        const std::int32_t second = edges[index * 2 + 1];
        if (first < 0 || second < 0 ||
            static_cast<std::size_t>(first) >= vertex_count ||
            static_cast<std::size_t>(second) >= vertex_count || first == second) {
            throw std::invalid_argument("baseline edges contains an invalid vertex index");
        }
        adjacency[static_cast<std::size_t>(first)].push_back(second);
        adjacency[static_cast<std::size_t>(second)].push_back(first);
    }
    for (auto& neighbors : adjacency) {
        std::sort(neighbors.begin(), neighbors.end());
        neighbors.erase(std::unique(neighbors.begin(), neighbors.end()), neighbors.end());
    }

    std::vector<std::vector<std::int32_t>> children(vertex_count);
    std::vector<std::int32_t> marks(vertex_count, 0);
    std::vector<std::pair<std::int32_t, double>> frontier;
    for (std::size_t vertex = 0; vertex < vertex_count; ++vertex) {
        if (is_fixed(result.vertex_attributes[vertex])) {
            frontier.emplace_back(static_cast<std::int32_t>(vertex), 0.0);
        }
    }
    while (!frontier.empty()) {
        for (const auto& [vertex_value, frontier_distance] : frontier) {
            static_cast<void>(frontier_distance);
            const auto vertex = static_cast<std::size_t>(vertex_value);
            if (!is_move(result.vertex_attributes[vertex])) continue;
            std::int32_t best_parent = -1;
            double best_cost = -1.0;
            for (const auto target_value : adjacency[vertex]) {
                const auto target = static_cast<std::size_t>(target_value);
                if (marks[target] == 0) continue;
                double cost = 0.0;
                if (!is_move(result.vertex_attributes[target])) {
                    cost = length(subtract(load_vec3(positions, vertex), load_vec3(positions, target)));
                } else {
                    const std::int32_t grandparent_value = result.parent_indices[target];
                    if (grandparent_value < 0) continue;
                    const auto grandparent = static_cast<std::size_t>(grandparent_value);
                    const Vec3 first = subtract(load_vec3(positions, target), load_vec3(positions, vertex));
                    const Vec3 second = subtract(load_vec3(positions, grandparent), load_vec3(positions, target));
                    const double denominator = length(first) * length(second);
                    if (!(denominator > 0.0)) continue;
                    cost = std::acos(std::clamp(dot(first, second) / denominator, -1.0, 1.0));
                }
                if (best_parent < 0 || cost < best_cost) {
                    best_parent = target_value;
                    best_cost = cost;
                }
            }
            if (best_parent >= 0) {
                result.parent_indices[vertex] = best_parent;
                marks[vertex] = 1;
            }
        }
        for (const auto& [vertex_value, frontier_distance] : frontier) {
            static_cast<void>(frontier_distance);
            const auto vertex = static_cast<std::size_t>(vertex_value);
            marks[vertex] = 2;
            const auto parent = result.parent_indices[vertex];
            if (parent >= 0) {
                children[static_cast<std::size_t>(parent)].push_back(vertex_value);
            }
        }
        std::map<std::int32_t, double> candidate_distances;
        for (const auto& [vertex_value, frontier_distance] : frontier) {
            static_cast<void>(frontier_distance);
            const auto vertex = static_cast<std::size_t>(vertex_value);
            for (const auto target_value : adjacency[vertex]) {
                const auto target = static_cast<std::size_t>(target_value);
                if (is_invalid(result.vertex_attributes[target]) || marks[target] != 0) continue;
                const double distance = length(
                    subtract(load_vec3(positions, vertex), load_vec3(positions, target))
                );
                const auto found = candidate_distances.find(target_value);
                if (found == candidate_distances.end() || distance < found->second) {
                    candidate_distances[target_value] = distance;
                }
            }
        }
        frontier.assign(candidate_distances.begin(), candidate_distances.end());
        std::sort(frontier.begin(), frontier.end(), [](const auto& left, const auto& right) {
            if (left.second != right.second) return left.second < right.second;
            return left.first < right.first;
        });
    }

    result.child_ranges.reserve(vertex_count * 2);
    for (auto& values : children) {
        std::sort(values.begin(), values.end());
        result.child_ranges.push_back(narrow_index(result.child_data.size(), "child data"));
        result.child_ranges.push_back(narrow_index(values.size(), "child data"));
        result.child_data.insert(result.child_data.end(), values.begin(), values.end());
    }

    for (std::size_t root = 0; root < vertex_count; ++root) {
        if (!is_fixed(result.vertex_attributes[root]) || children[root].empty()) continue;
        const auto start = result.baseline_data.size();
        std::uint8_t line_flag = 0;
        std::vector<std::int32_t> stack {static_cast<std::int32_t>(root)};
        while (!stack.empty()) {
            const std::int32_t vertex_value = stack.back();
            stack.pop_back();
            const auto vertex = static_cast<std::size_t>(vertex_value);
            result.baseline_data.push_back(vertex_value);
            if ((result.vertex_attributes[vertex] & kTriangle) == 0u) line_flag |= kIncludeLine;
            const auto& values = children[vertex];
            stack.insert(stack.end(), values.rbegin(), values.rend());
        }
        result.baseline_flags.push_back(line_flag);
        result.baseline_ranges.push_back(narrow_index(start, "baseline data"));
        result.baseline_ranges.push_back(
            narrow_index(result.baseline_data.size() - start, "baseline data")
        );
    }

    auto pose_depth = mc2_build_baseline_pose_depth_derived(
        positions,
        local_normals,
        local_tangents,
        result.vertex_attributes.data(),
        result.parent_indices.data(),
        vertex_count,
        result.baseline_data.data(),
        result.baseline_data.size()
    );
    result.vertex_attributes = std::move(pose_depth.vertex_attributes);
    result.root_indices = std::move(pose_depth.root_indices);
    result.depths = std::move(pose_depth.depths);
    result.vertex_local_positions = std::move(pose_depth.vertex_local_positions);
    result.vertex_local_rotations = std::move(pose_depth.vertex_local_rotations);
    return result;
}

}  // namespace hotools
