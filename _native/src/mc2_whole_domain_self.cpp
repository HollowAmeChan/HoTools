#include "mc2_whole_domain_self.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <vector>

namespace hotools {
namespace {

constexpr float kMc2Epsilon = 0.00000001f;
constexpr std::uint32_t kSelfFix0 = 0x04000000u;
constexpr std::uint32_t kSelfAllFix = 0x20000000u;
constexpr std::uint32_t kSelfIgnore = 0x40000000u;
constexpr std::int32_t kSelfIgnoreGrid = 1000000;

struct Vec3 {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

Vec3 add(Vec3 a, Vec3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
Vec3 sub(Vec3 a, Vec3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
Vec3 mul(Vec3 a, float value) { return {a.x * value, a.y * value, a.z * value}; }
float dot(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
Vec3 cross(Vec3 a, Vec3 b) {
    return {
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
    };
}
float length_squared(Vec3 value) { return dot(value, value); }
float length(Vec3 value) { return std::sqrt(length_squared(value)); }
Vec3 normalize(Vec3 value) {
    const float size = length(value);
    return size > kMc2Epsilon ? mul(value, 1.0f / size) : Vec3 {};
}
float saturate(float value) {
    return std::max(0.0f, std::min(1.0f, value));
}

std::uint16_t float_to_half_bits(float value) {
    std::uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof(bits));
    const std::uint32_t sign = (bits >> 16u) & 0x8000u;
    const std::uint32_t exponent = (bits >> 23u) & 0xffu;
    const std::uint32_t mantissa = bits & 0x7fffffu;
    if (exponent == 0xffu) {
        return static_cast<std::uint16_t>(
            sign | 0x7c00u | (mantissa != 0u ? 0x0200u : 0u)
        );
    }
    const int half_exponent = static_cast<int>(exponent) - 127 + 15;
    if (half_exponent >= 31) return static_cast<std::uint16_t>(sign | 0x7c00u);
    if (half_exponent <= 0) {
        if (half_exponent < -10) return static_cast<std::uint16_t>(sign);
        const std::uint32_t full_mantissa = mantissa | 0x800000u;
        const int shift = 14 - half_exponent;
        std::uint32_t half_mantissa = full_mantissa >> shift;
        const std::uint32_t remainder_mask = (std::uint32_t {1} << shift) - 1u;
        const std::uint32_t remainder = full_mantissa & remainder_mask;
        const std::uint32_t halfway = std::uint32_t {1} << (shift - 1);
        if (remainder > halfway ||
            (remainder == halfway && (half_mantissa & 1u) != 0u)) {
            ++half_mantissa;
        }
        return static_cast<std::uint16_t>(sign | half_mantissa);
    }
    std::uint32_t rounded_mantissa = mantissa >> 13u;
    const std::uint32_t remainder = mantissa & 0x1fffu;
    if (remainder > 0x1000u ||
        (remainder == 0x1000u && (rounded_mantissa & 1u) != 0u)) {
        ++rounded_mantissa;
    }
    std::uint32_t rounded_exponent = static_cast<std::uint32_t>(half_exponent);
    if (rounded_mantissa == 0x0400u) {
        rounded_mantissa = 0;
        ++rounded_exponent;
        if (rounded_exponent >= 31u) {
            return static_cast<std::uint16_t>(sign | 0x7c00u);
        }
    }
    return static_cast<std::uint16_t>(
        sign | (rounded_exponent << 10u) | rounded_mantissa
    );
}

float half_bits_to_float(std::uint16_t value) {
    const std::uint32_t sign = static_cast<std::uint32_t>(value & 0x8000u) << 16u;
    std::uint32_t exponent = (value >> 10u) & 0x1fu;
    std::uint32_t mantissa = value & 0x03ffu;
    std::uint32_t bits = 0;
    if (exponent == 0u) {
        if (mantissa == 0u) {
            bits = sign;
        } else {
            int normal_exponent = -14;
            while ((mantissa & 0x0400u) == 0u) {
                mantissa <<= 1u;
                --normal_exponent;
            }
            mantissa &= 0x03ffu;
            bits = sign |
                (static_cast<std::uint32_t>(normal_exponent + 127) << 23u) |
                (mantissa << 13u);
        }
    } else if (exponent == 31u) {
        bits = sign | 0x7f800000u | (mantissa << 13u);
    } else {
        const auto float_exponent = static_cast<std::uint32_t>(
            static_cast<int>(exponent) - 15 + 127
        );
        bits = sign | (float_exponent << 23u) | (mantissa << 13u);
    }
    float result = 0.0f;
    std::memcpy(&result, &bits, sizeof(result));
    return result;
}

float quantize_half(float value) {
    return half_bits_to_float(float_to_half_bits(value));
}

Vec3 load_vector3(const std::vector<float>& values, std::size_t vertex) {
    const auto offset = vertex * 3;
    return {values[offset + 0], values[offset + 1], values[offset + 2]};
}

std::uint64_t self_particle_pair_key(std::int32_t first, std::int32_t second) {
    const auto first_value = static_cast<std::uint32_t>(first);
    const auto second_value = static_cast<std::uint32_t>(second);
    const auto lower = first_value < second_value ? first_value : second_value;
    const auto upper = first_value < second_value ? second_value : first_value;
    return (static_cast<std::uint64_t>(lower) << 32u) |
        static_cast<std::uint64_t>(upper);
}

enum class NoopTimingStage {
    SelfSolvePrepare,
    SelfSolveRound1,
    SelfSolveRound2,
    SelfSolveRound3,
    SelfSolveRound4,
};

class NoopTimingScope {
public:
    NoopTimingScope(void*, NoopTimingStage) {}
};

struct WholeDomainSelfState {
    std::int64_t vertex_count = 0;
    std::int64_t frame = 0;
    std::int64_t generation = 0;
    bool self_collision_static_ready = false;
    bool self_primitive_dynamic_ready = false;
    bool self_grid_dynamic_ready = false;
    bool self_candidate_ready = false;
    bool self_contact_ready = false;
    bool self_contact_debug_requested = false;
    bool self_contact_debug_ready = false;
    bool self_owner_same_partition_enabled = false;
    std::int64_t self_grid_update_count = 0;
    std::int64_t self_candidate_update_count = 0;
    std::int64_t self_contact_build_count = 0;
    std::int64_t self_contact_update_count = 0;
    std::int64_t self_contact_solver_iteration_count = 0;
    std::int64_t self_contact_sum_count = 0;
    std::vector<float> state_positions;
    std::vector<float> velocity_reference_positions;
    std::vector<float> debug_self_contact_corrections;
    std::vector<std::uint32_t> self_primitive_flags;
    std::vector<std::int32_t> self_particle_indices;
    std::vector<float> self_primitive_depths;
    std::vector<std::uint64_t> self_topology_neighbor_keys;
    std::vector<float> self_primitive_inverse_masses;
    std::vector<float> self_primitive_aabb_min;
    std::vector<float> self_primitive_aabb_max;
    std::vector<float> self_primitive_thickness;
    std::vector<std::int32_t> self_primitive_owner_indices;
    std::vector<std::int32_t> self_owner_primary_group_bits;
    std::vector<std::int32_t> self_owner_collided_by_groups;
    std::vector<std::int32_t> self_primitive_grids;
    std::vector<std::int32_t> self_grid_hashes;
    std::vector<std::int32_t> self_grid_starts;
    std::vector<std::int32_t> self_grid_counts;
    std::vector<std::int32_t> self_contact_candidates;
    std::vector<std::int32_t> self_contact_primitive_indices;
    std::vector<std::int32_t> self_contact_types;
    std::vector<std::uint8_t> self_contact_enabled;
    std::vector<float> self_contact_thickness;
    std::vector<float> self_contact_s;
    std::vector<float> self_contact_t;
    std::vector<float> self_contact_normals;
    std::vector<std::int32_t> self_intersect_records;
    std::int64_t self_point_primitive_count = 0;
    std::int64_t self_edge_primitive_count = 0;
    std::int64_t self_triangle_primitive_count = 0;
    std::int64_t self_point_grid_count = 0;
    std::int64_t self_edge_grid_count = 0;
    std::int64_t self_triangle_grid_count = 0;
    std::int64_t self_primitive_frame = 0;
    std::int64_t self_primitive_generation = 0;
    float self_max_primitive_size = 0.0f;
    float self_grid_size = 0.0f;
    std::vector<std::uint64_t> self_contact_keys;
};

std::int32_t self_grid_hash(std::int32_t x, std::int32_t y, std::int32_t z) {
    const std::uint32_t hash =
        static_cast<std::uint32_t>(x) * 0x4C7F6DD1u +
        static_cast<std::uint32_t>(y) * 0x4822A3E9u +
        static_cast<std::uint32_t>(z) * 0xAAC3C25Du +
        0xD21D0945u;
    std::int32_t result = 0;
    static_assert(sizeof(result) == sizeof(hash));
    std::memcpy(&result, &hash, sizeof(result));
    return result;
}

template <typename T>
void reorder_self_primitive_chunk(
    std::vector<T>& values,
    std::size_t start,
    std::size_t count,
    std::size_t stride,
    const std::vector<std::size_t>& order
) {
    std::vector<T> reordered(count * stride);
    for (std::size_t destination = 0; destination < count; ++destination) {
        const auto source = order[destination];
        std::copy_n(
            values.data() + source * stride,
            stride,
            reordered.data() + destination * stride
        );
    }
    std::copy(
        reordered.begin(),
        reordered.end(),
        values.begin() + static_cast<std::ptrdiff_t>(start * stride)
    );
}

bool self_owner_pair_allowed(
    const WholeDomainSelfState& context,
    std::size_t primitive0,
    std::size_t primitive1
) {
    if (context.self_primitive_owner_indices.empty()) return true;
    if (primitive0 >= context.self_primitive_owner_indices.size() ||
        primitive1 >= context.self_primitive_owner_indices.size()) {
        return false;
    }
    const auto owner0 = context.self_primitive_owner_indices[primitive0];
    const auto owner1 = context.self_primitive_owner_indices[primitive1];
    if (owner0 < 0 || owner1 < 0) return false;
    if (owner0 == owner1) return context.self_owner_same_partition_enabled;
    const auto owner_count = context.self_owner_primary_group_bits.size();
    if (static_cast<std::size_t>(owner0) >= owner_count ||
        static_cast<std::size_t>(owner1) >= owner_count ||
        context.self_owner_collided_by_groups.size() != owner_count) {
        return false;
    }
    const auto mask0 = context.self_owner_collided_by_groups[owner0];
    const auto mask1 = context.self_owner_collided_by_groups[owner1];
    const bool allows0 = mask0 == 0 ||
        (mask0 & context.self_owner_primary_group_bits[owner1]) != 0;
    const bool allows1 = mask1 == 0 ||
        (mask1 & context.self_owner_primary_group_bits[owner0]) != 0;
    return allows0 && allows1;
}

bool update_self_collision_grid(WholeDomainSelfState& context) {
    const auto primitive_count = context.self_primitive_flags.size();
    context.self_contact_candidates.clear();
    context.self_candidate_ready = false;
    context.self_primitive_grids.assign(
        primitive_count * 3,
        kSelfIgnoreGrid
    );
    context.self_grid_hashes.assign(primitive_count, 0);
    context.self_grid_starts.assign(primitive_count, 0);
    context.self_grid_counts.assign(primitive_count, 0);
    context.self_point_grid_count = 0;
    context.self_edge_grid_count = 0;
    context.self_triangle_grid_count = 0;
    if (context.self_grid_size <= kMc2Epsilon) {
        context.self_grid_dynamic_ready = false;
        return false;
    }

    const std::array<std::size_t, 3> starts {
        0,
        static_cast<std::size_t>(context.self_point_primitive_count),
        static_cast<std::size_t>(
            context.self_point_primitive_count + context.self_edge_primitive_count
        ),
    };
    const std::array<std::size_t, 3> counts {
        static_cast<std::size_t>(context.self_point_primitive_count),
        static_cast<std::size_t>(context.self_edge_primitive_count),
        static_cast<std::size_t>(context.self_triangle_primitive_count),
    };
    std::array<std::int64_t*, 3> grid_count_outputs {
        &context.self_point_grid_count,
        &context.self_edge_grid_count,
        &context.self_triangle_grid_count,
    };

    for (std::size_t kind = 0; kind < 3; ++kind) {
        const auto start = starts[kind];
        const auto count = counts[kind];
        if (count == 0) continue;
        for (std::size_t local = 0; local < count; ++local) {
            const auto primitive = start + local;
            if ((context.self_primitive_flags[primitive] & kSelfIgnore) != 0u) continue;
            for (std::size_t component = 0; component < 3; ++component) {
                const auto offset = primitive * 3 + component;
                const float center = (
                    context.self_primitive_aabb_min[offset] +
                    context.self_primitive_aabb_max[offset]
                ) * 0.5f;
                context.self_primitive_grids[offset] = static_cast<std::int32_t>(
                    std::floor(center / context.self_grid_size)
                );
            }
        }

        std::vector<std::size_t> order(count);
        for (std::size_t local = 0; local < count; ++local) order[local] = start + local;
        std::stable_sort(order.begin(), order.end(), [&](std::size_t left, std::size_t right) {
            for (std::size_t component = 0; component < 3; ++component) {
                const auto left_value = context.self_primitive_grids[left * 3 + component];
                const auto right_value = context.self_primitive_grids[right * 3 + component];
                if (left_value != right_value) return left_value < right_value;
            }
            return false;
        });
        reorder_self_primitive_chunk(context.self_primitive_flags, start, count, 1, order);
        reorder_self_primitive_chunk(context.self_particle_indices, start, count, 3, order);
        reorder_self_primitive_chunk(context.self_primitive_depths, start, count, 1, order);
        reorder_self_primitive_chunk(context.self_primitive_inverse_masses, start, count, 3, order);
        reorder_self_primitive_chunk(context.self_primitive_aabb_min, start, count, 3, order);
        reorder_self_primitive_chunk(context.self_primitive_aabb_max, start, count, 3, order);
        reorder_self_primitive_chunk(context.self_primitive_thickness, start, count, 1, order);
        if (context.self_primitive_owner_indices.size() == primitive_count) {
            reorder_self_primitive_chunk(
                context.self_primitive_owner_indices,
                start,
                count,
                1,
                order
            );
        }
        reorder_self_primitive_chunk(context.self_primitive_grids, start, count, 3, order);

        struct GridRun {
            std::int32_t hash;
            std::int32_t start;
            std::int32_t count;
        };
        std::vector<GridRun> runs;
        std::size_t run_start = start;
        for (std::size_t local = 1; local <= count; ++local) {
            bool same_grid = false;
            if (local < count) {
                same_grid = true;
                for (std::size_t component = 0; component < 3; ++component) {
                    if (context.self_primitive_grids[(start + local) * 3 + component] !=
                        context.self_primitive_grids[run_start * 3 + component]) {
                        same_grid = false;
                        break;
                    }
                }
            }
            if (same_grid) continue;
            const auto x = context.self_primitive_grids[run_start * 3];
            const auto y = context.self_primitive_grids[run_start * 3 + 1];
            const auto z = context.self_primitive_grids[run_start * 3 + 2];
            runs.push_back(GridRun {
                self_grid_hash(x, y, z),
                static_cast<std::int32_t>(run_start),
                static_cast<std::int32_t>(start + local - run_start),
            });
            run_start = start + local;
        }
        std::stable_sort(runs.begin(), runs.end(), [](const GridRun& left, const GridRun& right) {
            return left.hash < right.hash;
        });
        for (std::size_t run = 0; run < runs.size(); ++run) {
            context.self_grid_hashes[start + run] = runs[run].hash;
            context.self_grid_starts[start + run] = runs[run].start;
            context.self_grid_counts[start + run] = runs[run].count;
        }
        *grid_count_outputs[kind] = static_cast<std::int64_t>(runs.size());
    }
    context.self_grid_dynamic_ready = true;
    ++context.self_grid_update_count;
    return true;
}

bool self_primitives_are_topology_neighbors(
    const WholeDomainSelfState& context,
    std::size_t left,
    std::size_t right
) {
    const auto left_kind = static_cast<std::size_t>(
        (context.self_primitive_flags[left] >> 24u) & 0x03u
    );
    const auto right_kind = static_cast<std::size_t>(
        (context.self_primitive_flags[right] >> 24u) & 0x03u
    );
    for (std::size_t left_axis = 0; left_axis <= left_kind; ++left_axis) {
        const auto particle = context.self_particle_indices[left * 3 + left_axis];
        for (std::size_t right_axis = 0; right_axis <= right_kind; ++right_axis) {
            const auto target = context.self_particle_indices[right * 3 + right_axis];
            if (particle == target) return true;
            const auto key = self_particle_pair_key(particle, target);
            if (std::binary_search(
                    context.self_topology_neighbor_keys.begin(),
                    context.self_topology_neighbor_keys.end(),
                    key)) {
                return true;
            }
        }
    }
    return false;
}

bool self_aabbs_overlap(
    const WholeDomainSelfState& context,
    std::size_t left,
    std::size_t right
) {
    for (std::size_t component = 0; component < 3; ++component) {
        if (context.self_primitive_aabb_max[left * 3 + component] <
                context.self_primitive_aabb_min[right * 3 + component] ||
            context.self_primitive_aabb_min[left * 3 + component] >
                context.self_primitive_aabb_max[right * 3 + component]) {
            return false;
        }
    }
    return true;
}

std::int64_t self_binary_search_grid_hash(
    const WholeDomainSelfState& context,
    std::size_t start,
    std::size_t length,
    std::int32_t value
) {
    std::size_t offset = 0;
    for (std::size_t remaining = length; remaining != 0; remaining >>= 1) {
        const auto index = offset + (remaining >> 1);
        const auto current = context.self_grid_hashes[start + index];
        if (value == current) return static_cast<std::int64_t>(index);
        if (value > current) {
            offset = index + 1;
            --remaining;
        }
    }
    return -1;
}

void detect_self_collision_intersections(WholeDomainSelfState& context) {
    context.self_intersect_records.clear();
    if (!context.self_contact_debug_requested ||
        !context.self_grid_dynamic_ready ||
        context.self_edge_primitive_count <= 0 ||
        context.self_triangle_primitive_count <= 0 ||
        context.self_max_primitive_size <= kMc2Epsilon ||
        context.self_grid_size <= kMc2Epsilon) {
        return;
    }

    struct IntersectRecord {
        std::array<std::int32_t, 5> particles {};
    };
    std::vector<IntersectRecord> records;
    const auto edge_start = static_cast<std::size_t>(
        context.self_point_primitive_count
    );
    const auto edge_count = static_cast<std::size_t>(
        context.self_edge_primitive_count
    );
    const auto triangle_start = static_cast<std::size_t>(
        context.self_point_primitive_count + context.self_edge_primitive_count
    );
    const auto triangle_grid_count = static_cast<std::size_t>(
        context.self_triangle_grid_count
    );
    const auto frame_phase = static_cast<std::size_t>(
        (context.frame % 2 + 2) % 2
    );
    for (std::size_t edge = edge_start; edge < edge_start + edge_count; ++edge) {
        if ((edge % 2) != frame_phase) continue;
        const auto edge_flags = context.self_primitive_flags[edge];
        if ((edge_flags & kSelfIgnore) != 0u) continue;
        std::array<std::int32_t, 3> start_grid {};
        std::array<std::int32_t, 3> end_grid {};
        const float padding = context.self_max_primitive_size * 0.5f;
        for (std::size_t component = 0; component < 3; ++component) {
            start_grid[component] = static_cast<std::int32_t>(std::floor(
                (context.self_primitive_aabb_min[edge * 3 + component] - padding) /
                context.self_grid_size
            ));
            end_grid[component] = static_cast<std::int32_t>(std::floor(
                (context.self_primitive_aabb_max[edge * 3 + component] + padding) /
                context.self_grid_size
            ));
        }
        for (std::int64_t z = start_grid[2]; z <= end_grid[2]; ++z) {
            for (std::int64_t y = start_grid[1]; y <= end_grid[1]; ++y) {
                for (std::int64_t x = start_grid[0]; x <= end_grid[0]; ++x) {
                    const auto hash = self_grid_hash(
                        static_cast<std::int32_t>(x),
                        static_cast<std::int32_t>(y),
                        static_cast<std::int32_t>(z)
                    );
                    const auto run_index = self_binary_search_grid_hash(
                        context,
                        triangle_start,
                        triangle_grid_count,
                        hash
                    );
                    if (run_index < 0) continue;
                    const auto buffer_index = triangle_start +
                        static_cast<std::size_t>(run_index);
                    const auto run_start = static_cast<std::size_t>(
                        context.self_grid_starts[buffer_index]
                    );
                    const auto run_end = run_start + static_cast<std::size_t>(
                        context.self_grid_counts[buffer_index]
                    );
                    for (std::size_t triangle = run_start;
                         triangle < run_end;
                         ++triangle) {
                        const auto triangle_flags =
                            context.self_primitive_flags[triangle];
                        if (!self_owner_pair_allowed(context, edge, triangle) ||
                            !self_aabbs_overlap(context, edge, triangle) ||
                            (triangle_flags & kSelfIgnore) != 0u ||
                            ((edge_flags & kSelfAllFix) != 0u &&
                             (triangle_flags & kSelfAllFix) != 0u) ||
                            self_primitives_are_topology_neighbors(
                                context, edge, triangle
                            )) {
                            continue;
                        }
                        records.push_back(IntersectRecord {{
                            context.self_particle_indices[edge * 3],
                            context.self_particle_indices[edge * 3 + 1],
                            context.self_particle_indices[triangle * 3],
                            context.self_particle_indices[triangle * 3 + 1],
                            context.self_particle_indices[triangle * 3 + 2],
                        }});
                    }
                }
            }
        }
    }
    std::sort(records.begin(), records.end(), [](const auto& left, const auto& right) {
        return left.particles < right.particles;
    });
    records.erase(
        std::unique(records.begin(), records.end(), [](const auto& left, const auto& right) {
            return left.particles == right.particles;
        }),
        records.end()
    );
    context.self_intersect_records.reserve(records.size() * 5);
    for (const auto& record : records) {
        context.self_intersect_records.insert(
            context.self_intersect_records.end(),
            record.particles.begin(),
            record.particles.end()
        );
    }
}

void confirm_self_collision_intersections(WholeDomainSelfState& context) {
    const auto record_count = context.self_intersect_records.size() / 5;
    std::vector<std::int32_t> confirmed;
    confirmed.reserve(context.self_intersect_records.size());
    for (std::size_t record = 0; record < record_count; ++record) {
        const auto* particles = context.self_intersect_records.data() + record * 5;
        Vec3 p = load_vector3(
            context.state_positions, static_cast<std::size_t>(particles[0])
        );
        const Vec3 q = load_vector3(
            context.state_positions, static_cast<std::size_t>(particles[1])
        );
        const Vec3 a = load_vector3(
            context.state_positions, static_cast<std::size_t>(particles[2])
        );
        const Vec3 b = load_vector3(
            context.state_positions, static_cast<std::size_t>(particles[3])
        );
        const Vec3 c = load_vector3(
            context.state_positions, static_cast<std::size_t>(particles[4])
        );
        Vec3 qp = sub(p, q);
        const Vec3 ac = sub(c, a);
        const Vec3 ab = sub(b, a);
        const Vec3 normal = cross(ab, ac);
        float denominator = dot(qp, normal);
        if (std::abs(denominator) < kMc2Epsilon) continue;
        if (denominator < 0.0f) {
            p = q;
            qp = mul(qp, -1.0f);
            denominator = -denominator;
        }
        const Vec3 ap = sub(p, a);
        const float distance = dot(ap, normal);
        if (distance < 0.0f || distance > denominator) continue;
        const Vec3 cross_value = cross(qp, ap);
        const float v = dot(ac, cross_value);
        if (v < 0.0f || v > denominator) continue;
        const float w = -dot(ab, cross_value);
        if (w < 0.0f || v + w > denominator) continue;
        confirmed.insert(confirmed.end(), particles, particles + 5);
    }
    context.self_intersect_records.swap(confirmed);
}

void update_self_collision_candidates(WholeDomainSelfState& context) {
    context.self_contact_candidates.clear();
    context.self_candidate_ready = false;
    if (!context.self_grid_dynamic_ready) return;

    struct Candidate {
        std::int32_t primitive0;
        std::int32_t primitive1;
        std::int32_t type;
    };
    std::vector<Candidate> candidates;
    const auto point_start = std::size_t {0};
    const auto edge_start = static_cast<std::size_t>(context.self_point_primitive_count);
    const auto triangle_start = static_cast<std::size_t>(
        context.self_point_primitive_count + context.self_edge_primitive_count
    );

    auto detect = [&](std::size_t my_start,
                      std::size_t my_count,
                      std::size_t target_start,
                      std::size_t target_count,
                      std::size_t target_grid_count,
                      std::int32_t contact_type,
                      bool duplicate_detection) {
        if (my_count == 0 || target_count == 0 || target_grid_count == 0) return;
        for (std::size_t primitive = my_start; primitive < my_start + my_count; ++primitive) {
            const auto flag = context.self_primitive_flags[primitive];
            if ((flag & kSelfIgnore) != 0u) continue;
            std::array<std::int32_t, 3> start_grid {};
            std::array<std::int32_t, 3> end_grid {};
            for (std::size_t component = 0; component < 3; ++component) {
                const float padding = context.self_max_primitive_size * 0.5f;
                start_grid[component] = static_cast<std::int32_t>(std::floor(
                    (context.self_primitive_aabb_min[primitive * 3 + component] - padding) /
                    context.self_grid_size
                ));
                end_grid[component] = static_cast<std::int32_t>(std::floor(
                    (context.self_primitive_aabb_max[primitive * 3 + component] + padding) /
                    context.self_grid_size
                ));
            }
            for (std::int64_t z = start_grid[2]; z <= end_grid[2]; ++z) {
                for (std::int64_t y = start_grid[1]; y <= end_grid[1]; ++y) {
                    for (std::int64_t x = start_grid[0]; x <= end_grid[0]; ++x) {
                        const auto hash = self_grid_hash(
                            static_cast<std::int32_t>(x),
                            static_cast<std::int32_t>(y),
                            static_cast<std::int32_t>(z)
                        );
                        const auto run_index = self_binary_search_grid_hash(
                            context,
                            target_start,
                            target_grid_count,
                            hash
                        );
                        if (run_index < 0) continue;
                        const auto buffer_index = target_start + static_cast<std::size_t>(run_index);
                        const auto run_start = static_cast<std::size_t>(
                            context.self_grid_starts[buffer_index]
                        );
                        const auto run_end = run_start + static_cast<std::size_t>(
                            context.self_grid_counts[buffer_index]
                        );
                        if (duplicate_detection && run_end < primitive) continue;
                        auto target = duplicate_detection
                            ? std::max(run_start, primitive)
                            : run_start;
                        for (; target < run_end; ++target) {
                            if (duplicate_detection && primitive == target) continue;
                            const auto target_flag = context.self_primitive_flags[target];
                            if (!self_owner_pair_allowed(context, primitive, target) ||
                                !self_aabbs_overlap(context, primitive, target) ||
                                (target_flag & kSelfIgnore) != 0u ||
                                ((flag & kSelfAllFix) != 0u &&
                                 (target_flag & kSelfAllFix) != 0u) ||
                                self_primitives_are_topology_neighbors(
                                    context,
                                    primitive,
                                    target
                                )) {
                                continue;
                            }
                            candidates.push_back(Candidate {
                                static_cast<std::int32_t>(primitive),
                                static_cast<std::int32_t>(target),
                                contact_type,
                            });
                        }
                    }
                }
            }
        }
    };

    detect(
        edge_start,
        static_cast<std::size_t>(context.self_edge_primitive_count),
        edge_start,
        static_cast<std::size_t>(context.self_edge_primitive_count),
        static_cast<std::size_t>(context.self_edge_grid_count),
        0,
        true
    );
    detect(
        point_start,
        static_cast<std::size_t>(context.self_point_primitive_count),
        triangle_start,
        static_cast<std::size_t>(context.self_triangle_primitive_count),
        static_cast<std::size_t>(context.self_triangle_grid_count),
        1,
        false
    );
    std::sort(candidates.begin(), candidates.end(), [](const Candidate& left, const Candidate& right) {
        if (left.type != right.type) return left.type < right.type;
        if (left.primitive0 != right.primitive0) return left.primitive0 < right.primitive0;
        return left.primitive1 < right.primitive1;
    });
    candidates.erase(
        std::unique(candidates.begin(), candidates.end(), [](const Candidate& left, const Candidate& right) {
            return left.type == right.type &&
                left.primitive0 == right.primitive0 &&
                left.primitive1 == right.primitive1;
        }),
        candidates.end()
    );
    context.self_contact_candidates.reserve(candidates.size() * 3);
    for (const auto& candidate : candidates) {
        context.self_contact_candidates.push_back(candidate.primitive0);
        context.self_contact_candidates.push_back(candidate.primitive1);
        context.self_contact_candidates.push_back(candidate.type);
    }
    context.self_candidate_ready = true;
    ++context.self_candidate_update_count;
}

struct SelfContactValue {
    std::int32_t primitive0 = 0;
    std::int32_t primitive1 = 0;
    std::int32_t type = 0;
    std::uint8_t enabled = 0;
    float thickness = 0.0f;
    float s = 0.0f;
    float t = 0.0f;
    Vec3 normal {};
};

float closest_segment_segment(
    Vec3 p1,
    Vec3 q1,
    Vec3 p2,
    Vec3 q2,
    float& s,
    float& t,
    Vec3& c1,
    Vec3& c2
) {
    const Vec3 d1 = sub(q1, p1);
    const Vec3 d2 = sub(q2, p2);
    const Vec3 r = sub(p1, p2);
    const float a = dot(d1, d1);
    const float e = dot(d2, d2);
    const float f = dot(d2, r);
    if (a <= 1.0e-8f && e <= 1.0e-8f) {
        s = t = 0.0f;
        c1 = p1;
        c2 = p2;
        return length_squared(sub(c1, c2));
    }
    if (a <= 1.0e-8f) {
        s = 0.0f;
        t = saturate(f / e);
    } else {
        const float c = dot(d1, r);
        if (e <= 1.0e-8f) {
            t = 0.0f;
            s = saturate(-c / a);
        } else {
            const float b = dot(d1, d2);
            const float denominator = a * e - b * b;
            s = denominator != 0.0f
                ? saturate((b * f - c * e) / denominator)
                : 0.0f;
            t = (b * s + f) / e;
            if (t < 0.0f) {
                t = 0.0f;
                s = saturate(-c / a);
            } else if (t > 1.0f) {
                t = 1.0f;
                s = saturate((b - c) / a);
            }
        }
    }
    c1 = add(p1, mul(d1, s));
    c2 = add(p2, mul(d2, t));
    return length_squared(sub(c1, c2));
}

Vec3 closest_point_triangle(
    Vec3 point,
    Vec3 a,
    Vec3 b,
    Vec3 c,
    Vec3& uvw
) {
    uvw = {};
    const Vec3 ab = sub(b, a);
    const Vec3 ac = sub(c, a);
    const Vec3 ap = sub(point, a);
    const float d1 = dot(ab, ap);
    const float d2 = dot(ac, ap);
    if (d1 <= 0.0f && d2 <= 0.0f) {
        uvw.x = 1.0f;
        return a;
    }
    const Vec3 bp = sub(point, b);
    const float d3 = dot(ab, bp);
    const float d4 = dot(ac, bp);
    if (d3 >= 0.0f && d4 <= d3) {
        uvw.y = 1.0f;
        return b;
    }
    const float vc = d1 * d4 - d3 * d2;
    if (vc <= 0.0f && d1 >= 0.0f && d3 <= 0.0f) {
        const float v = d1 / (d1 - d3);
        uvw = {1.0f - v, v, 0.0f};
        return add(a, mul(ab, v));
    }
    const Vec3 cp = sub(point, c);
    const float d5 = dot(ab, cp);
    const float d6 = dot(ac, cp);
    if (d6 >= 0.0f && d5 <= d6) {
        uvw.z = 1.0f;
        return c;
    }
    const float vb = d5 * d2 - d1 * d6;
    if (vb <= 0.0f && d2 >= 0.0f && d6 <= 0.0f) {
        const float w = d2 / (d2 - d6);
        uvw = {1.0f - w, 0.0f, w};
        return add(a, mul(ac, w));
    }
    const float va = d3 * d6 - d5 * d4;
    if (va <= 0.0f && (d4 - d3) >= 0.0f && (d5 - d6) >= 0.0f) {
        const float denominator = (d4 - d3) + (d5 - d6);
        const float w = (d4 - d3) / denominator;
        uvw = {0.0f, 1.0f - w, w};
        return add(b, mul(sub(c, b), w));
    }
    const float denominator = 1.0f / (va + vb + vc);
    const float v = vb * denominator;
    const float w = vc * denominator;
    uvw = {1.0f - v - w, v, w};
    return add(add(a, mul(ab, v)), mul(ac, w));
}

bool update_self_contact_value(
    const WholeDomainSelfState& context,
    const std::vector<float>& old_positions,
    bool first,
    SelfContactValue& contact
) {
    contact.enabled = 0;
    const auto primitive0 = static_cast<std::size_t>(contact.primitive0);
    const auto primitive1 = static_cast<std::size_t>(contact.primitive1);
    const float threshold = contact.thickness * 3.0f;
    auto particle = [&](std::size_t primitive, std::size_t axis) {
        return static_cast<std::size_t>(context.self_particle_indices[primitive * 3 + axis]);
    };
    if (contact.type == 0) {
        const auto a0 = particle(primitive0, 0);
        const auto a1 = particle(primitive0, 1);
        const auto b0 = particle(primitive1, 0);
        const auto b1 = particle(primitive1, 1);
        const Vec3 next_a0 = load_vector3(context.state_positions, a0);
        const Vec3 next_a1 = load_vector3(context.state_positions, a1);
        const Vec3 next_b0 = load_vector3(context.state_positions, b0);
        const Vec3 next_b1 = load_vector3(context.state_positions, b1);
        const Vec3 old_a0 = load_vector3(old_positions, a0);
        const Vec3 old_a1 = load_vector3(old_positions, a1);
        const Vec3 old_b0 = load_vector3(old_positions, b0);
        const Vec3 old_b1 = load_vector3(old_positions, b1);
        float s = 0.0f, t = 0.0f;
        Vec3 closest_a {}, closest_b {};
        const float closest_length = std::sqrt(closest_segment_segment(
            old_a0, old_a1, old_b0, old_b1, s, t, closest_a, closest_b
        ));
        if (closest_length < 1.0e-9f) return false;
        const Vec3 normal = mul(sub(closest_a, closest_b), 1.0f / closest_length);
        const Vec3 displacement_a = add(
            mul(sub(next_a0, old_a0), 1.0f - s),
            mul(sub(next_a1, old_a1), s)
        );
        const Vec3 displacement_b = add(
            mul(sub(next_b0, old_b0), 1.0f - t),
            mul(sub(next_b1, old_b1), t)
        );
        const float predicted_length = closest_length +
            dot(normal, displacement_a) - dot(normal, displacement_b);
        if (predicted_length > threshold) return false;
        contact.enabled = 1;
        contact.s = quantize_half(s);
        contact.t = quantize_half(t);
        contact.normal = {
            quantize_half(normal.x),
            quantize_half(normal.y),
            quantize_half(normal.z),
        };
        return true;
    }
    if (contact.type == 1) {
        const auto point_index = particle(primitive0, 0);
        const auto b0 = particle(primitive1, 0);
        const auto b1 = particle(primitive1, 1);
        const auto b2 = particle(primitive1, 2);
        const Vec3 next_point = load_vector3(context.state_positions, point_index);
        const Vec3 old_point = load_vector3(old_positions, point_index);
        const Vec3 next_b0 = load_vector3(context.state_positions, b0);
        const Vec3 next_b1 = load_vector3(context.state_positions, b1);
        const Vec3 next_b2 = load_vector3(context.state_positions, b2);
        const Vec3 old_b0 = load_vector3(old_positions, b0);
        const Vec3 old_b1 = load_vector3(old_positions, b1);
        const Vec3 old_b2 = load_vector3(old_positions, b2);
        const Vec3 point_displacement = sub(next_point, old_point);
        const Vec3 displacement_b0 = sub(next_b0, old_b0);
        const Vec3 displacement_b1 = sub(next_b1, old_b1);
        const Vec3 displacement_b2 = sub(next_b2, old_b2);
        Vec3 uvw {};
        const Vec3 closest = closest_point_triangle(
            old_point, old_b0, old_b1, old_b2, uvw
        );
        const Vec3 triangle_displacement = add(
            add(mul(displacement_b0, uvw.x), mul(displacement_b1, uvw.y)),
            mul(displacement_b2, uvw.z)
        );
        const Vec3 closest_vector = sub(closest, old_point);
        const float closest_length = length(closest_vector);
        if (closest_length <= kMc2Epsilon) return false;
        Vec3 normal = mul(closest_vector, 1.0f / closest_length);
        const float predicted_length = closest_length -
            dot(normal, point_displacement) + dot(normal, triangle_displacement);
        if (predicted_length >= threshold) return false;
        float sign = contact.s;
        if (first) {
            const Vec3 triangle_normal = normalize(cross(
                sub(old_b1, old_b0),
                sub(old_b2, old_b0)
            ));
            normal = normalize(sub(old_point, closest));
            const float direction = dot(triangle_normal, normal);
            if (std::abs(direction) < 0.5f) return false;
            sign = direction > 0.0f ? 1.0f : -1.0f;
        }
        contact.s = quantize_half(sign);
        contact.enabled = 1;
        return true;
    }
    return false;
}

void clear_self_collision_contacts(WholeDomainSelfState& context) {
    context.self_contact_keys.clear();
    context.self_contact_primitive_indices.clear();
    context.self_contact_types.clear();
    context.self_contact_enabled.clear();
    context.self_contact_thickness.clear();
    context.self_contact_s.clear();
    context.self_contact_t.clear();
    context.self_contact_normals.clear();
    context.self_contact_debug_ready = false;
    context.debug_self_contact_corrections.clear();
    context.self_contact_ready = false;
}

void append_self_contact(WholeDomainSelfState& context, const SelfContactValue& contact) {
    context.self_contact_primitive_indices.push_back(contact.primitive0);
    context.self_contact_primitive_indices.push_back(contact.primitive1);
    context.self_contact_types.push_back(contact.type);
    context.self_contact_enabled.push_back(contact.enabled);
    context.self_contact_thickness.push_back(contact.thickness);
    context.self_contact_s.push_back(contact.s);
    context.self_contact_t.push_back(contact.t);
    context.self_contact_normals.push_back(contact.normal.x);
    context.self_contact_normals.push_back(contact.normal.y);
    context.self_contact_normals.push_back(contact.normal.z);
    const auto key =
        (static_cast<std::uint64_t>(contact.type) << 62u) |
        (static_cast<std::uint64_t>(static_cast<std::uint32_t>(contact.primitive0)) << 31u) |
        static_cast<std::uint32_t>(contact.primitive1);
    context.self_contact_keys.push_back(key);
}

void build_self_collision_contacts(
    WholeDomainSelfState& context,
    const std::vector<float>& old_positions
) {
    clear_self_collision_contacts(context);
    const auto candidate_count = context.self_contact_candidates.size() / 3;
    for (std::size_t candidate = 0; candidate < candidate_count; ++candidate) {
        const auto primitive0 = context.self_contact_candidates[candidate * 3];
        const auto primitive1 = context.self_contact_candidates[candidate * 3 + 1];
        SelfContactValue contact;
        contact.primitive0 = primitive0;
        contact.primitive1 = primitive1;
        contact.type = context.self_contact_candidates[candidate * 3 + 2];
        contact.thickness = quantize_half(
            context.self_primitive_thickness[primitive0] +
            context.self_primitive_thickness[primitive1]
        );
        if (update_self_contact_value(context, old_positions, true, contact)) {
            append_self_contact(context, contact);
        }
    }
    context.self_contact_ready = true;
    ++context.self_contact_build_count;
}

void update_self_collision_contacts(
    WholeDomainSelfState& context,
    const std::vector<float>& old_positions
) {
    if (!context.self_contact_ready) return;
    const auto count = context.self_contact_types.size();
    for (std::size_t index = 0; index < count; ++index) {
        SelfContactValue contact;
        contact.primitive0 = context.self_contact_primitive_indices[index * 2];
        contact.primitive1 = context.self_contact_primitive_indices[index * 2 + 1];
        contact.type = context.self_contact_types[index];
        contact.enabled = context.self_contact_enabled[index];
        contact.thickness = context.self_contact_thickness[index];
        contact.s = context.self_contact_s[index];
        contact.t = context.self_contact_t[index];
        contact.normal = {
            context.self_contact_normals[index * 3],
            context.self_contact_normals[index * 3 + 1],
            context.self_contact_normals[index * 3 + 2],
        };
        update_self_contact_value(context, old_positions, false, contact);
        context.self_contact_enabled[index] = contact.enabled;
        context.self_contact_s[index] = contact.s;
        context.self_contact_t[index] = contact.t;
        context.self_contact_normals[index * 3] = contact.normal.x;
        context.self_contact_normals[index * 3 + 1] = contact.normal.y;
        context.self_contact_normals[index * 3 + 2] = contact.normal.z;
    }
    ++context.self_contact_update_count;
}

void add_wrapped_int32(std::int32_t& destination, std::int32_t value) {
    const std::uint32_t sum =
        static_cast<std::uint32_t>(destination) + static_cast<std::uint32_t>(value);
    std::memcpy(&destination, &sum, sizeof(destination));
}

void solve_self_collision_contacts(
    WholeDomainSelfState& context,
    void* timing
) {
    if (!context.self_contact_ready) return;
    const auto vertex_count = static_cast<std::size_t>(context.vertex_count);
    const auto contact_count = context.self_contact_types.size();
    const bool capture_debug = context.self_contact_debug_requested;
    std::vector<std::int32_t> counts;
    std::vector<std::int32_t> sums;
    {
        NoopTimingScope stage(
            timing, NoopTimingStage::SelfSolvePrepare
        );
        context.self_contact_debug_ready = false;
        if (capture_debug) {
            context.debug_self_contact_corrections.assign(
                contact_count * 2 * 3, 0.0f
            );
        } else {
            context.debug_self_contact_corrections.clear();
        }
        counts.assign(vertex_count, 0);
        sums.assign(vertex_count * 3, 0);
    }
    struct DebugContribution {
        std::size_t contact;
        std::size_t side;
        std::size_t vertex;
        std::array<std::int32_t, 3> fixed;
    };
    std::vector<DebugContribution> debug_contributions;
    auto accumulate = [&](
        std::size_t vertex,
        Vec3 correction,
        std::size_t contact,
        std::size_t side
    ) {
        ++counts[vertex];
        const std::array<float, 3> values {correction.x, correction.y, correction.z};
        if (capture_debug) {
            DebugContribution debug {contact, side, vertex, {}};
            for (std::size_t component = 0; component < 3; ++component) {
                const auto fixed = static_cast<std::int32_t>(
                    values[component] * 1000000.0f
                );
                add_wrapped_int32(sums[vertex * 3 + component], fixed);
                debug.fixed[component] = fixed;
            }
            debug_contributions.push_back(debug);
            return;
        }
        for (std::size_t component = 0; component < 3; ++component) {
            const auto fixed = static_cast<std::int32_t>(values[component] * 1000000.0f);
            add_wrapped_int32(sums[vertex * 3 + component], fixed);
        }
    };
    auto particle = [&](std::size_t primitive, std::size_t axis) {
        return static_cast<std::size_t>(context.self_particle_indices[primitive * 3 + axis]);
    };
    auto inverse_mass = [&](std::size_t primitive, std::size_t axis) {
        return context.self_primitive_inverse_masses[primitive * 3 + axis];
    };
    auto can_write = [&](std::size_t primitive, std::size_t axis) {
        const auto blocked = (kSelfFix0 | 0x00000001u) << axis;
        return (context.self_primitive_flags[primitive] & blocked) == 0u;
    };

    constexpr int kSolverIterations = 4;
    constexpr std::array<NoopTimingStage, kSolverIterations>
        kIterationStages {
            NoopTimingStage::SelfSolveRound1,
            NoopTimingStage::SelfSolveRound2,
            NoopTimingStage::SelfSolveRound3,
            NoopTimingStage::SelfSolveRound4,
        };
    for (int iteration = 0; iteration < kSolverIterations; ++iteration) {
        NoopTimingScope stage(timing, kIterationStages[iteration]);
        for (std::size_t contact = 0; contact < contact_count; ++contact) {
            if (context.self_contact_enabled[contact] == 0) continue;
            const auto primitive0 = static_cast<std::size_t>(
                context.self_contact_primitive_indices[contact * 2]
            );
            const auto primitive1 = static_cast<std::size_t>(
                context.self_contact_primitive_indices[contact * 2 + 1]
            );
            const float thickness = context.self_contact_thickness[contact];
            if (context.self_contact_types[contact] == 0) {
                const auto a0 = particle(primitive0, 0);
                const auto a1 = particle(primitive0, 1);
                const auto b0 = particle(primitive1, 0);
                const auto b1 = particle(primitive1, 1);
                const float s = context.self_contact_s[contact];
                const float t = context.self_contact_t[contact];
                const Vec3 normal {
                    context.self_contact_normals[contact * 3],
                    context.self_contact_normals[contact * 3 + 1],
                    context.self_contact_normals[contact * 3 + 2],
                };
                const Vec3 a = add(
                    mul(load_vector3(context.state_positions, a0), 1.0f - s),
                    mul(load_vector3(context.state_positions, a1), s)
                );
                const Vec3 b = add(
                    mul(load_vector3(context.state_positions, b0), 1.0f - t),
                    mul(load_vector3(context.state_positions, b1), t)
                );
                const float projected_length = dot(normal, sub(a, b));
                if (projected_length > thickness) continue;
                const float weight_a0 = 1.0f - s;
                const float weight_a1 = s;
                const float weight_b0 = 1.0f - t;
                const float weight_b1 = t;
                const float inv_a0 = inverse_mass(primitive0, 0);
                const float inv_a1 = inverse_mass(primitive0, 1);
                const float inv_b0 = inverse_mass(primitive1, 0);
                const float inv_b1 = inverse_mass(primitive1, 1);
                const float denominator =
                    inv_a0 * weight_a0 * weight_a0 +
                    inv_a1 * weight_a1 * weight_a1 +
                    inv_b0 * weight_b0 * weight_b0 +
                    inv_b1 * weight_b1 * weight_b1;
                if (denominator == 0.0f) continue;
                const float scale = (thickness - projected_length) / denominator;
                const Vec3 correction_a0 = mul(normal, scale * inv_a0 * weight_a0);
                const Vec3 correction_a1 = mul(normal, scale * inv_a1 * weight_a1);
                const Vec3 correction_b0 = mul(normal, -scale * inv_b0 * weight_b0);
                const Vec3 correction_b1 = mul(normal, -scale * inv_b1 * weight_b1);
                if (can_write(primitive0, 0)) accumulate(a0, correction_a0, contact, 0);
                if (can_write(primitive0, 1)) accumulate(a1, correction_a1, contact, 0);
                if (can_write(primitive1, 0)) accumulate(b0, correction_b0, contact, 1);
                if (can_write(primitive1, 1)) accumulate(b1, correction_b1, contact, 1);
            } else if (context.self_contact_types[contact] == 1) {
                const auto point_index = particle(primitive0, 0);
                const auto b0 = particle(primitive1, 0);
                const auto b1 = particle(primitive1, 1);
                const auto b2 = particle(primitive1, 2);
                const Vec3 position_b0 = load_vector3(context.state_positions, b0);
                const Vec3 position_b1 = load_vector3(context.state_positions, b1);
                const Vec3 position_b2 = load_vector3(context.state_positions, b2);
                const Vec3 point_position = load_vector3(context.state_positions, point_index);
                const Vec3 triangle_normal = normalize(cross(
                    sub(position_b1, position_b0),
                    sub(position_b2, position_b0)
                ));
                Vec3 uvw {};
                closest_point_triangle(
                    point_position,
                    position_b0,
                    position_b1,
                    position_b2,
                    uvw
                );
                const Vec3 normal = mul(triangle_normal, context.self_contact_s[contact]);
                const float distance = dot(normal, sub(point_position, position_b0));
                if (distance >= thickness) continue;
                const float inv_point = inverse_mass(primitive0, 0);
                const float inv_b0 = inverse_mass(primitive1, 0);
                const float inv_b1 = inverse_mass(primitive1, 1);
                const float inv_b2 = inverse_mass(primitive1, 2);
                const float denominator =
                    inv_point +
                    inv_b0 * uvw.x * uvw.x +
                    inv_b1 * uvw.y * uvw.y +
                    inv_b2 * uvw.z * uvw.z;
                if (denominator == 0.0f) continue;
                const float scale = (distance - thickness) / denominator;
                const Vec3 correction = mul(normal, -scale * inv_point);
                const Vec3 correction_b0 = mul(normal, scale * inv_b0 * uvw.x);
                const Vec3 correction_b1 = mul(normal, scale * inv_b1 * uvw.y);
                const Vec3 correction_b2 = mul(normal, scale * inv_b2 * uvw.z);
                if (can_write(primitive0, 0)) accumulate(point_index, correction, contact, 0);
                if (can_write(primitive1, 0)) accumulate(b0, correction_b0, contact, 1);
                if (can_write(primitive1, 1)) accumulate(b1, correction_b1, contact, 1);
                if (can_write(primitive1, 2)) accumulate(b2, correction_b2, contact, 1);
            }
        }
        if (capture_debug) {
            for (const auto& contribution : debug_contributions) {
                const auto count = counts[contribution.vertex];
                if (count <= 0) continue;
                const auto start = (contribution.contact * 2 + contribution.side) * 3;
                for (std::size_t component = 0; component < 3; ++component) {
                    context.debug_self_contact_corrections[start + component] +=
                        static_cast<float>(contribution.fixed[component]) /
                        static_cast<float>(count) * 0.000001f;
                }
            }
            debug_contributions.clear();
        }
        for (std::size_t vertex = 0; vertex < vertex_count; ++vertex) {
            const auto count = counts[vertex];
            if (count > 0) {
                for (std::size_t component = 0; component < 3; ++component) {
                    const float correction =
                        static_cast<float>(sums[vertex * 3 + component]) /
                        static_cast<float>(count) * 0.000001f;
                    context.state_positions[vertex * 3 + component] += correction;
                }
            }
        }
        std::fill(counts.begin(), counts.end(), 0);
        std::fill(sums.begin(), sums.end(), 0);
        ++context.self_contact_solver_iteration_count;
        ++context.self_contact_sum_count;
    }
    context.self_contact_debug_ready = capture_debug;
}


}  // namespace

struct Mc2WholeDomainSelfEngine::Impl {
    WholeDomainSelfState state;
    Mc2WholeDomainSelfDebugSnapshot debug_snapshot;
    bool debug_snapshot_ready = false;
};

Mc2WholeDomainSelfEngine::Mc2WholeDomainSelfEngine()
    : impl_(std::make_unique<Impl>()) {}

Mc2WholeDomainSelfEngine::~Mc2WholeDomainSelfEngine() = default;

void Mc2WholeDomainSelfEngine::configure(
    std::size_t vertex_count,
    const std::int32_t* points,
    std::size_t point_count,
    const std::int32_t* edges,
    std::size_t edge_count,
    const std::int32_t* triangles,
    std::size_t triangle_count,
    const std::uint32_t* particle_partition_indices,
    const std::uint32_t* particle_attribute_flags,
    const std::uint32_t* partition_self_collision_modes,
    const std::uint32_t* partition_collision_groups,
    const std::uint32_t* partition_collision_masks,
    std::size_t partition_count
) {
    auto& state = impl_->state;
    state = WholeDomainSelfState {};
    impl_->debug_snapshot = Mc2WholeDomainSelfDebugSnapshot {};
    impl_->debug_snapshot_ready = false;
    state.vertex_count = static_cast<std::int64_t>(vertex_count);
    state.self_point_primitive_count = static_cast<std::int64_t>(point_count);
    state.self_edge_primitive_count = static_cast<std::int64_t>(edge_count);
    state.self_triangle_primitive_count = static_cast<std::int64_t>(triangle_count);
    state.self_owner_same_partition_enabled = true;
    state.self_primitive_flags.reserve(point_count + edge_count + triangle_count);
    state.self_particle_indices.reserve((point_count + edge_count + triangle_count) * 3);
    state.self_primitive_depths.assign(point_count + edge_count + triangle_count, 0.0f);
    state.self_primitive_owner_indices.reserve(point_count + edge_count + triangle_count);
    auto append_primitive = [&](std::uint32_t kind, const std::int32_t* indices) {
        const auto axis_count = static_cast<std::size_t>(kind + 1u);
        std::uint32_t flags = kind << 24u;
        std::int32_t owner = -1;
        std::size_t fixed_count = 0;
        for (std::size_t axis = 0; axis < 3; ++axis) {
            const auto vertex = indices[axis];
            state.self_particle_indices.push_back(vertex);
            if (axis >= axis_count) continue;
            if (owner < 0) {
                owner = static_cast<std::int32_t>(particle_partition_indices[vertex]);
            }
            if ((particle_attribute_flags[vertex] & 0x02u) == 0u) {
                flags |= kSelfFix0 << axis;
                ++fixed_count;
            }
        }
        if (fixed_count == axis_count) flags |= kSelfAllFix;
        if (owner < 0 || partition_self_collision_modes[owner] != 2u) {
            flags |= kSelfIgnore;
        }
        state.self_primitive_flags.push_back(flags);
        state.self_primitive_owner_indices.push_back(owner);
    };
    for (std::size_t index = 0; index < point_count; ++index) {
        const std::int32_t indices[3] = {points[index], -1, -1};
        append_primitive(0u, indices);
    }
    for (std::size_t index = 0; index < edge_count; ++index) {
        const std::int32_t indices[3] = {
            edges[index * 2], edges[index * 2 + 1], -1,
        };
        append_primitive(1u, indices);
    }
    for (std::size_t index = 0; index < triangle_count; ++index) {
        const std::int32_t indices[3] = {
            triangles[index * 3],
            triangles[index * 3 + 1],
            triangles[index * 3 + 2],
        };
        append_primitive(2u, indices);
    }
    state.self_owner_primary_group_bits.assign(partition_count, 0);
    state.self_owner_collided_by_groups.assign(partition_count, 0);
    for (std::size_t partition = 0; partition < partition_count; ++partition) {
        state.self_owner_primary_group_bits[partition] =
            static_cast<std::int32_t>(partition_collision_groups[partition]);
        state.self_owner_collided_by_groups[partition] =
            static_cast<std::int32_t>(partition_collision_masks[partition]);
    }
    state.self_topology_neighbor_keys.reserve(edge_count);
    for (std::size_t edge = 0; edge < edge_count; ++edge) {
        const auto first = edges[edge * 2];
        const auto second = edges[edge * 2 + 1];
        if (first != second) {
            state.self_topology_neighbor_keys.push_back(
                self_particle_pair_key(first, second)
            );
        }
    }
    std::sort(
        state.self_topology_neighbor_keys.begin(),
        state.self_topology_neighbor_keys.end()
    );
    state.self_topology_neighbor_keys.erase(
        std::unique(
            state.self_topology_neighbor_keys.begin(),
            state.self_topology_neighbor_keys.end()
        ),
        state.self_topology_neighbor_keys.end()
    );
    const auto primitive_count = point_count + edge_count + triangle_count;
    state.self_primitive_inverse_masses.assign(primitive_count * 3, 0.0f);
    state.self_primitive_aabb_min.assign(primitive_count * 3, 0.0f);
    state.self_primitive_aabb_max.assign(primitive_count * 3, 0.0f);
    state.self_primitive_thickness.assign(primitive_count, 0.0f);
    state.self_primitive_grids.assign(primitive_count * 3, kSelfIgnoreGrid);
    state.self_grid_hashes.assign(primitive_count, 0);
    state.self_grid_starts.assign(primitive_count, 0);
    state.self_grid_counts.assign(primitive_count, 0);
    state.self_collision_static_ready = true;
    clear_self_collision_contacts(state);
}

void Mc2WholeDomainSelfEngine::solve(
    float* positions,
    const float* old_positions,
    const float* particle_thickness,
    const float* particle_friction,
    const float* particle_cloth_mass,
    std::int64_t frame,
    std::int64_t generation,
    std::int64_t& candidate_count,
    std::int64_t& contact_count
) {
    auto& state = impl_->state;
    const auto vertex_count = static_cast<std::size_t>(state.vertex_count);
    const auto primitive_count = state.self_primitive_flags.size();
    state.frame = frame;
    state.generation = generation;
    state.state_positions.assign(positions, positions + vertex_count * 3);
    state.velocity_reference_positions.assign(
        old_positions, old_positions + vertex_count * 3
    );
    float edge_max_size = 0.0f;
    float fallback_max_size = 0.0f;
    for (std::size_t primitive = 0; primitive < primitive_count; ++primitive) {
        const auto kind = (state.self_primitive_flags[primitive] >> 24u) & 0x03u;
        const auto axis_count = static_cast<std::size_t>(kind + 1u);
        float minimum[3] {
            std::numeric_limits<float>::max(),
            std::numeric_limits<float>::max(),
            std::numeric_limits<float>::max(),
        };
        float maximum[3] {
            std::numeric_limits<float>::lowest(),
            std::numeric_limits<float>::lowest(),
            std::numeric_limits<float>::lowest(),
        };
        float thickness = 0.0f;
        for (std::size_t axis = 0; axis < axis_count; ++axis) {
            const auto vertex = static_cast<std::size_t>(
                state.self_particle_indices[primitive * 3 + axis]
            );
            const auto position_offset = vertex * 3;
            const bool fixed =
                (state.self_primitive_flags[primitive] & (kSelfFix0 << axis)) != 0u;
            float mass = fixed ? 100.0f : 1.0f + particle_friction[vertex] * 10.0f;
            mass += particle_cloth_mass[vertex] * 50.0f;
            state.self_primitive_inverse_masses[primitive * 3 + axis] = 1.0f / mass;
            thickness += std::max(particle_thickness[vertex], 0.0f);
            for (std::size_t component = 0; component < 3; ++component) {
                minimum[component] = std::min({
                    minimum[component],
                    state.state_positions[position_offset + component],
                    state.velocity_reference_positions[position_offset + component],
                });
                maximum[component] = std::max({
                    maximum[component],
                    state.state_positions[position_offset + component],
                    state.velocity_reference_positions[position_offset + component],
                });
            }
        }
        thickness /= static_cast<float>(axis_count);
        state.self_primitive_thickness[primitive] = thickness;
        for (std::size_t component = 0; component < 3; ++component) {
            state.self_primitive_aabb_min[primitive * 3 + component] =
                minimum[component] - thickness;
            state.self_primitive_aabb_max[primitive * 3 + component] =
                maximum[component] + thickness;
        }
        const float primitive_size = std::max({
            maximum[0] - minimum[0],
            maximum[1] - minimum[1],
            maximum[2] - minimum[2],
        });
        fallback_max_size = std::max(fallback_max_size, primitive_size);
        if (kind == 1u) edge_max_size = std::max(edge_max_size, primitive_size);
    }
    if (edge_max_size <= kMc2Epsilon) edge_max_size = fallback_max_size;
    state.self_max_primitive_size = edge_max_size;
    state.self_grid_size = edge_max_size * 3.0f;
    state.self_primitive_frame = frame;
    state.self_primitive_generation = generation;
    state.self_primitive_dynamic_ready = true;
    update_self_collision_grid(state);
    detect_self_collision_intersections(state);
    update_self_collision_candidates(state);
    build_self_collision_contacts(state, state.velocity_reference_positions);
    solve_self_collision_contacts(state, nullptr);
    if (state.self_contact_debug_requested) {
        confirm_self_collision_intersections(state);
    }
    if (state.self_contact_debug_requested && state.self_contact_debug_ready) {
        auto& snapshot = impl_->debug_snapshot;
        snapshot.frame = state.frame;
        snapshot.generation = state.generation;
        snapshot.point_primitive_count = state.self_point_primitive_count;
        snapshot.edge_primitive_count = state.self_edge_primitive_count;
        snapshot.triangle_primitive_count = state.self_triangle_primitive_count;
        snapshot.point_grid_count = state.self_point_grid_count;
        snapshot.edge_grid_count = state.self_edge_grid_count;
        snapshot.triangle_grid_count = state.self_triangle_grid_count;
        snapshot.max_primitive_size = state.self_max_primitive_size;
        snapshot.grid_size = state.self_grid_size;
        snapshot.primitive_flags = state.self_primitive_flags;
        snapshot.particle_indices = state.self_particle_indices;
        snapshot.primitive_depths = state.self_primitive_depths;
        snapshot.inverse_masses = state.self_primitive_inverse_masses;
        snapshot.aabb_min = state.self_primitive_aabb_min;
        snapshot.aabb_max = state.self_primitive_aabb_max;
        snapshot.thickness = state.self_primitive_thickness;
        snapshot.owner_indices = state.self_primitive_owner_indices;
        snapshot.owner_group_bits = state.self_owner_primary_group_bits;
        snapshot.owner_collision_masks = state.self_owner_collided_by_groups;
        snapshot.primitive_grids = state.self_primitive_grids;
        snapshot.grid_hashes = state.self_grid_hashes;
        snapshot.grid_starts = state.self_grid_starts;
        snapshot.grid_counts = state.self_grid_counts;
        snapshot.candidates = state.self_contact_candidates;
        snapshot.contact_indices = state.self_contact_primitive_indices;
        snapshot.contact_types = state.self_contact_types;
        snapshot.contact_enabled = state.self_contact_enabled;
        snapshot.contact_thickness = state.self_contact_thickness;
        snapshot.contact_s = state.self_contact_s;
        snapshot.contact_t = state.self_contact_t;
        snapshot.contact_normals = state.self_contact_normals;
        snapshot.contact_corrections = state.debug_self_contact_corrections;
        snapshot.intersect_records = state.self_intersect_records;
        impl_->debug_snapshot_ready = true;
    }
    state.self_contact_debug_requested = false;
    candidate_count = static_cast<std::int64_t>(
        state.self_contact_candidates.size() / 3
    );
    contact_count = static_cast<std::int64_t>(state.self_contact_types.size());
    std::copy(state.state_positions.begin(), state.state_positions.end(), positions);
}

void Mc2WholeDomainSelfEngine::request_debug_capture() {
    impl_->state.self_contact_debug_requested = true;
    impl_->debug_snapshot_ready = false;
}

void Mc2WholeDomainSelfEngine::clear_debug_capture() noexcept {
    impl_->state.self_contact_debug_requested = false;
    impl_->state.self_contact_debug_ready = false;
    impl_->state.debug_self_contact_corrections.clear();
    impl_->state.self_intersect_records.clear();
    impl_->debug_snapshot = Mc2WholeDomainSelfDebugSnapshot {};
    impl_->debug_snapshot_ready = false;
}

bool Mc2WholeDomainSelfEngine::debug_capture_ready() const noexcept {
    return impl_->debug_snapshot_ready;
}

const Mc2WholeDomainSelfDebugSnapshot&
Mc2WholeDomainSelfEngine::debug_snapshot() const noexcept {
    return impl_->debug_snapshot;
}

}  // namespace hotools
