/**
 * jolt_rigid.cpp — Jolt Physics nanobind 绑定
 *
 * 暴露给 Python 的模块名：hotools_jolt
 * 主要类型：JoltWorld — 管理一个 Jolt PhysicsSystem 实例
 *
 * 设计原则（对应 HoTools Phase 5 要求）：
 * - JoltWorld 实例只挂在 world.backend_resources["rigid_solver"]，不做全局单例。
 * - body_id / constraint_id 只保存在 rigid solver slot，不写回 Blender 对象。
 * - 公开 API 使用 HoTools 语义（body_type / shape_type），不暴露 Jolt 内部类型名。
 * - dispose 顺序：先 remove 所有 constraints，再 remove 所有 bodies，最后销毁 world。
 */

// Jolt 必须在任何 STL 之前被包含
#include <Jolt/Jolt.h>

JPH_SUPPRESS_WARNINGS

#include <Jolt/RegisterTypes.h>
#include <Jolt/Core/Factory.h>
#include <Jolt/Core/TempAllocator.h>
#include <Jolt/Core/JobSystemSingleThreaded.h>
#include <Jolt/Physics/PhysicsSettings.h>
#include <Jolt/Physics/PhysicsSystem.h>
#include <Jolt/Physics/Body/BodyCreationSettings.h>
#include <Jolt/Physics/Body/BodyInterface.h>
#include <Jolt/Physics/Collision/Shape/BoxShape.h>
#include <Jolt/Physics/Collision/Shape/SphereShape.h>
#include <Jolt/Physics/Collision/Shape/CapsuleShape.h>
#include <Jolt/Physics/Collision/Shape/CylinderShape.h>
#include <Jolt/Physics/Collision/Shape/TaperedCapsuleShape.h>
#include <Jolt/Physics/Collision/Shape/TaperedCylinderShape.h>
#include <Jolt/Physics/Collision/Shape/PlaneShape.h>
#include <Jolt/Physics/Collision/Shape/RotatedTranslatedShape.h>
#include <Jolt/Physics/Collision/CollisionGroup.h>
#include <Jolt/Geometry/Plane.h>
#include <Jolt/Physics/Constraints/FixedConstraint.h>
#include <Jolt/Physics/Constraints/HingeConstraint.h>
#include <Jolt/Physics/Constraints/SliderConstraint.h>
#include <Jolt/Physics/Constraints/ConeConstraint.h>
#include <Jolt/Physics/Constraints/PointConstraint.h>
#include <Jolt/Physics/Constraints/DistanceConstraint.h>

#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>
#include <nanobind/stl/array.h>
#include <nanobind/stl/unordered_map.h>

#include <array>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#ifdef _WIN32
#  define WIN32_LEAN_AND_MEAN
#  include <windows.h>
#endif

namespace nb = nanobind;
using namespace JPH;

// ---------------------------------------------------------------------------
// Jolt 全局初始化（lock-free，规避 tbbmalloc_proxy 干扰 MSVCP CRT mutex）
// ---------------------------------------------------------------------------

// 用原子状态替代 std::once_flag，完全避免 MSVCP140 的 Mtx_trylock 路径
// 0 = 未初始化  1 = 初始化中  2 = 已完成
static std::atomic<int> g_jolt_init_state{0};

static void ensure_jolt_initialized() {
    if (g_jolt_init_state.load(std::memory_order_acquire) == 2)
        return;
    int expected = 0;
    if (g_jolt_init_state.compare_exchange_strong(
            expected, 1, std::memory_order_acq_rel)) {
        // 赢得初始化权
        RegisterDefaultAllocator();
        Factory::sInstance = new Factory();
        RegisterTypes();
        g_jolt_init_state.store(2, std::memory_order_release);
    } else {
        // 另一个线程正在初始化，自旋等待（单进程内极少发生）
        while (g_jolt_init_state.load(std::memory_order_acquire) < 2) {}
    }
}

// ---------------------------------------------------------------------------
// 物理层设置（2 层：静止 / 运动中）
// ---------------------------------------------------------------------------

namespace HoLayers {
    static constexpr ObjectLayer NON_MOVING = 0;
    static constexpr ObjectLayer MOVING     = 1;
    static constexpr uint32_t    NUM_LAYERS = 2;
}

namespace HoBPLayers {
    static constexpr BroadPhaseLayer NON_MOVING{0};
    static constexpr BroadPhaseLayer MOVING{1};
    static constexpr uint32_t        NUM_LAYERS = 2;
}

class HoBPLayerInterface final : public BroadPhaseLayerInterface {
public:
    HoBPLayerInterface() {
        mObjToBP[HoLayers::NON_MOVING] = HoBPLayers::NON_MOVING;
        mObjToBP[HoLayers::MOVING]     = HoBPLayers::MOVING;
    }
    uint GetNumBroadPhaseLayers() const override {
        return HoBPLayers::NUM_LAYERS;
    }
    BroadPhaseLayer GetBroadPhaseLayer(ObjectLayer layer) const override {
        return mObjToBP[layer];
    }
#if defined(JPH_EXTERNAL_PROFILE) || defined(JPH_PROFILE_ENABLED)
    const char* GetBroadPhaseLayerName(BroadPhaseLayer layer) const override {
        return (layer == HoBPLayers::NON_MOVING) ? "NON_MOVING" : "MOVING";
    }
#endif
private:
    BroadPhaseLayer mObjToBP[HoLayers::NUM_LAYERS];
};

class HoObjVsBPFilter final : public ObjectVsBroadPhaseLayerFilter {
public:
    bool ShouldCollide(ObjectLayer obj, BroadPhaseLayer bp) const override {
        if (obj == HoLayers::NON_MOVING)
            return bp == HoBPLayers::MOVING;
        return true; // MOVING collides with everything
    }
};

class HoObjLayerFilter final : public ObjectLayerPairFilter {
public:
    bool ShouldCollide(ObjectLayer a, ObjectLayer b) const override {
        if (a == HoLayers::NON_MOVING && b == HoLayers::NON_MOVING)
            return false; // 静态-静态不碰
        return true;
    }
};

// ---------------------------------------------------------------------------
// 辅助：Python tuple → Jolt Vec3 / Quat
// ---------------------------------------------------------------------------

class HoCollisionGroupFilter final : public GroupFilter {
    JPH_DECLARE_SERIALIZABLE_VIRTUAL(JPH_EXPORT, HoCollisionGroupFilter)

public:
    bool CanCollide(const CollisionGroup& a, const CollisionGroup& b) const override {
        uint32_t group_a = a.GetGroupID();
        uint32_t group_b = b.GetGroupID();
        uint32_t filter_id_a = (a.GetSubGroupID() >> 16u) & 0xffffu;
        uint32_t filter_id_b = (b.GetSubGroupID() >> 16u) & 0xffffu;
        if (filter_id_a != 0u && filter_id_b != 0u &&
            mDisabledPairs.find(pair_key(filter_id_a, filter_id_b)) != mDisabledPairs.end())
            return false;

        if (group_a < 1u || group_a > 16u || group_b < 1u || group_b > 16u)
            return true;

        uint32_t mask_a = a.GetSubGroupID() & 0xffffu;
        uint32_t mask_b = b.GetSubGroupID() & 0xffffu;
        uint32_t bit_a = 1u << (group_a - 1u);
        uint32_t bit_b = 1u << (group_b - 1u);
        return (mask_a & bit_b) != 0u && (mask_b & bit_a) != 0u;
    }

    void DisablePair(uint32_t filter_id_a, uint32_t filter_id_b) {
        if (filter_id_a == 0u || filter_id_b == 0u || filter_id_a == filter_id_b)
            return;
        mDisabledPairs.insert(pair_key(filter_id_a, filter_id_b));
    }

    void EnablePair(uint32_t filter_id_a, uint32_t filter_id_b) {
        if (filter_id_a == 0u || filter_id_b == 0u || filter_id_a == filter_id_b)
            return;
        mDisabledPairs.erase(pair_key(filter_id_a, filter_id_b));
    }

    void ClearPairs() {
        mDisabledPairs.clear();
    }

private:
    static uint64_t pair_key(uint32_t a, uint32_t b) {
        uint32_t lo = (std::min)(a, b);
        uint32_t hi = (std::max)(a, b);
        return (static_cast<uint64_t>(lo) << 32u) | static_cast<uint64_t>(hi);
    }

    std::unordered_set<uint64_t> mDisabledPairs;
};

JPH_IMPLEMENT_SERIALIZABLE_VIRTUAL(HoCollisionGroupFilter)
{
    JPH_ADD_BASE_CLASS(HoCollisionGroupFilter, GroupFilter)
}

static RVec3 to_vec3(const std::array<float, 3>& v) {
    return RVec3(v[0], v[1], v[2]);
}

static Quat to_quat(const std::array<float, 4>& q) {
    // 传入顺序 (w, x, y, z)
    return Quat(q[1], q[2], q[3], q[0]);
}

static std::array<float, 3> from_vec3(RVec3 v) {
    return {static_cast<float>(v.GetX()),
            static_cast<float>(v.GetY()),
            static_cast<float>(v.GetZ())};
}

static std::array<float, 4> from_quat(Quat q) {
    // 返回顺序 (w, x, y, z)
    return {q.GetW(), q.GetX(), q.GetY(), q.GetZ()};
}

// ---------------------------------------------------------------------------
// JoltWorld — 封装单个 Jolt PhysicsSystem
// ---------------------------------------------------------------------------

struct BodyRecord {
    BodyID  id;
    EMotionType motion_type;
    uint32_t filter_id;
};

struct ConstraintRecord {
    Ref<TwoBodyConstraint> constraint;
    uint32_t body_a_handle;
    uint32_t body_b_handle;
    bool disable_collisions;
    bool collision_pair_disabled;
    std::string constraint_type;
};

class JoltWorld {
public:
    explicit JoltWorld(uint32_t max_bodies = 2048,
                       uint32_t max_body_pairs = 4096,
                       uint32_t max_contact_constraints = 2048)
    {
        // ensure_jolt_initialized() 已在模块加载时调用，此处为保险再调一次（幂等）
        ensure_jolt_initialized();
        mGroupFilter = new HoCollisionGroupFilter();
        mTempAllocator = std::make_unique<TempAllocatorImpl>(8 * 1024 * 1024);
        mJobSystem     = std::make_unique<JobSystemSingleThreaded>(cMaxPhysicsJobs);
        mPhysicsSystem = std::make_unique<PhysicsSystem>();
        mPhysicsSystem->Init(
            max_bodies, 0,
            max_body_pairs,
            max_contact_constraints,
            mBPLayerInterface,
            mObjVsBPFilter,
            mObjLayerFilter
        );
        // Blender 使用 Z-up 坐标系，重力沿 -Z 轴
        mPhysicsSystem->SetGravity(Vec3(0.f, 0.f, -9.81f));
    }

    ~JoltWorld() { clear(); }

    // ---- Body management -----------------------------------------------

    uint32_t add_body(
        const std::string&        body_type_str,
        float                     mass,
        float                     friction,
        float                     restitution,
        const std::array<float,3>& position,
        const std::array<float,4>& rotation_wxyz,   // (w,x,y,z)
        const std::string&        shape_type_str,
        float                     shape_radius,      // SPHERE / CAPSULE
        float                     shape_half_height, // CAPSULE
        const std::array<float,3>& shape_half_extents, // BOX
        uint32_t                  collision_group,
        uint32_t                  collided_by_groups,
        const std::array<float,3>& shape_offset,
        const std::array<float,4>& shape_rotation_wxyz,
        const std::array<float,3>& linear_velocity,
        const std::array<float,3>& angular_velocity,
        float                     linear_damping,
        float                     angular_damping,
        float                     gravity_factor,
        bool                      allow_sleeping,
        const std::string&        motion_quality_str,
        float                     max_linear_velocity,
        float                     max_angular_velocity,
        bool                      is_sensor,
        uint32_t                  allowed_dofs_bits,
        bool                      collide_kinematic_vs_non_dynamic,
        float                     shape_plane_half_extent,
        float                     shape_top_radius,
        float                     shape_bottom_radius,
        float                     shape_convex_radius
    )
    {
        // 形状
        Ref<Shape> shape;
        const bool is_plane = shape_type_str == "PLANE";
        if (shape_type_str == "SPHERE") {
            shape = new SphereShape(shape_radius);
        } else if (shape_type_str == "CAPSULE") {
            shape = new CapsuleShape(shape_half_height, shape_radius);
        } else if (shape_type_str == "CYLINDER") {
            float radius = (std::max)(shape_radius, 0.001f);
            float convex_radius = std::clamp(shape_convex_radius, 0.0f, radius);
            shape = new CylinderShape(shape_half_height, radius, convex_radius);
        } else if (shape_type_str == "TAPERED_CAPSULE") {
            TaperedCapsuleShapeSettings settings(
                (std::max)(shape_half_height, 0.0f),
                (std::max)(shape_top_radius, 0.001f),
                (std::max)(shape_bottom_radius, 0.001f)
            );
            Shape::ShapeResult result = settings.Create();
            if (result.HasError())
                throw std::runtime_error(std::string("Jolt TaperedCapsuleShape failed: ") + result.GetError().c_str());
            shape = result.Get();
        } else if (shape_type_str == "TAPERED_CYLINDER") {
            float top_radius = (std::max)(shape_top_radius, 0.001f);
            float bottom_radius = (std::max)(shape_bottom_radius, 0.001f);
            float convex_radius = std::clamp(shape_convex_radius, 0.0f, (std::min)(top_radius, bottom_radius));
            TaperedCylinderShapeSettings settings(
                (std::max)(shape_half_height, 0.001f),
                top_radius,
                bottom_radius,
                convex_radius
            );
            Shape::ShapeResult result = settings.Create();
            if (result.HasError())
                throw std::runtime_error(std::string("Jolt TaperedCylinderShape failed: ") + result.GetError().c_str());
            shape = result.Get();
        } else if (is_plane) {
            float half_extent = (std::max)(std::abs(shape_plane_half_extent), 1.0f);
            shape = new PlaneShape(Plane(Vec3(0.0f, 0.0f, 1.0f), 0.0f), nullptr, half_extent);
        } else { // BOX (default)
            shape = new BoxShape(Vec3(shape_half_extents[0],
                                     shape_half_extents[1],
                                     shape_half_extents[2]));
        }
        if (shape_offset[0] != 0.f || shape_offset[1] != 0.f || shape_offset[2] != 0.f ||
            shape_rotation_wxyz[0] != 1.f || shape_rotation_wxyz[1] != 0.f ||
            shape_rotation_wxyz[2] != 0.f || shape_rotation_wxyz[3] != 0.f) {
            shape = new RotatedTranslatedShape(
                Vec3(shape_offset[0], shape_offset[1], shape_offset[2]),
                to_quat(shape_rotation_wxyz),
                shape
            );
        }

        // 运动类型
        EMotionType motion = EMotionType::Dynamic;
        ObjectLayer layer  = HoLayers::MOVING;
        if (body_type_str == "STATIC" || is_plane) {
            motion = EMotionType::Static;
            layer  = HoLayers::NON_MOVING;
        } else if (body_type_str == "KINEMATIC") {
            motion = EMotionType::Kinematic;
        }

        BodyCreationSettings settings(
            shape,
            to_vec3(position),
            to_quat(rotation_wxyz),
            motion,
            layer
        );
        settings.mFriction = friction;
        settings.mRestitution = restitution;
        uint32_t primary_group = (std::min)((std::max)(collision_group, 1u), 16u);
        uint32_t filter_id = allocate_filter_id();
        settings.mCollisionGroup.SetGroupFilter(mGroupFilter);
        settings.mCollisionGroup.SetGroupID(primary_group);
        settings.mCollisionGroup.SetSubGroupID(
            ((filter_id & 0xffffu) << 16u) | (collided_by_groups & 0xffffu)
        );
        settings.mLinearVelocity = Vec3(linear_velocity[0], linear_velocity[1], linear_velocity[2]);
        settings.mAngularVelocity = Vec3(angular_velocity[0], angular_velocity[1], angular_velocity[2]);
        settings.mLinearDamping = std::clamp(linear_damping, 0.0f, 1.0f);
        settings.mAngularDamping = std::clamp(angular_damping, 0.0f, 1.0f);
        settings.mGravityFactor = gravity_factor;
        settings.mAllowSleeping = allow_sleeping;
        settings.mMotionQuality = (
            motion_quality_str == "LINEAR_CAST" || motion_quality_str == "CCD"
        ) ? EMotionQuality::LinearCast : EMotionQuality::Discrete;
        settings.mMaxLinearVelocity = (std::max)(0.0f, max_linear_velocity);
        settings.mMaxAngularVelocity = (std::max)(0.0f, max_angular_velocity);
        settings.mIsSensor = is_sensor;
        settings.mCollideKinematicVsNonDynamic = collide_kinematic_vs_non_dynamic;
        uint32_t allowed_mask = allowed_dofs_bits & 0x3fu;
        settings.mAllowedDOFs = allowed_mask != 0u
            ? static_cast<EAllowedDOFs>(allowed_mask)
            : EAllowedDOFs::All;
        if (motion == EMotionType::Dynamic && mass > 0.f) {
            settings.mOverrideMassProperties = EOverrideMassProperties::CalculateInertia;
            settings.mMassPropertiesOverride.mMass = mass;
        }

        BodyInterface& bi = mPhysicsSystem->GetBodyInterface();
        Body* body = bi.CreateBody(settings);
        if (!body)
            throw std::runtime_error("Jolt CreateBody failed（超出 max_bodies？）");

        bi.AddBody(body->GetID(), EActivation::Activate);

        uint32_t handle = mNextHandle++;
        mBodies[handle] = {body->GetID(), motion, filter_id};
        return handle;
    }

    void remove_body(uint32_t handle) {
        auto it = mBodies.find(handle);
        if (it == mBodies.end()) return;
        remove_constraints_for_body(handle);
        BodyInterface& bi = mPhysicsSystem->GetBodyInterface();
        bi.RemoveBody(it->second.id);
        bi.DestroyBody(it->second.id);
        mBodies.erase(it);
    }

    // 运动学 body 每帧由动画驱动
    void set_kinematic_transform(
        uint32_t                  handle,
        const std::array<float,3>& position,
        const std::array<float,4>& rotation_wxyz,
        float                     dt
    ) {
        auto it = mBodies.find(handle);
        if (it == mBodies.end()) return;
        mPhysicsSystem->GetBodyInterface().MoveKinematic(
            it->second.id, to_vec3(position), to_quat(rotation_wxyz), dt);
    }

    bool set_body_velocity(
        uint32_t                  handle,
        const std::array<float,3>& linear_velocity,
        const std::array<float,3>& angular_velocity
    ) {
        auto it = mBodies.find(handle);
        if (it == mBodies.end() || it->second.motion_type == EMotionType::Static)
            return false;
        mPhysicsSystem->GetBodyInterface().SetLinearAndAngularVelocity(
            it->second.id,
            Vec3(linear_velocity[0], linear_velocity[1], linear_velocity[2]),
            Vec3(angular_velocity[0], angular_velocity[1], angular_velocity[2])
        );
        return true;
    }

    bool add_body_force(
        uint32_t                  handle,
        const std::array<float,3>& force,
        const std::array<float,3>& torque
    ) {
        auto it = mBodies.find(handle);
        if (it == mBodies.end() || it->second.motion_type != EMotionType::Dynamic)
            return false;
        mPhysicsSystem->GetBodyInterface().AddForceAndTorque(
            it->second.id,
            Vec3(force[0], force[1], force[2]),
            Vec3(torque[0], torque[1], torque[2]),
            EActivation::Activate
        );
        return true;
    }

    bool add_body_impulse(
        uint32_t                  handle,
        const std::array<float,3>& impulse,
        const std::array<float,3>& angular_impulse
    ) {
        auto it = mBodies.find(handle);
        if (it == mBodies.end() || it->second.motion_type != EMotionType::Dynamic)
            return false;
        BodyInterface& bi = mPhysicsSystem->GetBodyInterface();
        bi.AddImpulse(it->second.id, Vec3(impulse[0], impulse[1], impulse[2]));
        bi.AddAngularImpulse(
            it->second.id,
            Vec3(angular_impulse[0], angular_impulse[1], angular_impulse[2])
        );
        return true;
    }

    bool set_body_gravity_factor(uint32_t handle, float gravity_factor) {
        auto it = mBodies.find(handle);
        if (it == mBodies.end() || it->second.motion_type == EMotionType::Static)
            return false;
        mPhysicsSystem->GetBodyInterface().SetGravityFactor(it->second.id, gravity_factor);
        return true;
    }

    bool set_body_material_response(uint32_t handle, float friction, float restitution) {
        auto it = mBodies.find(handle);
        if (it == mBodies.end())
            return false;
        BodyInterface& bi = mPhysicsSystem->GetBodyInterface();
        bi.SetFriction(it->second.id, std::clamp(friction, 0.0f, 1.0f));
        bi.SetRestitution(it->second.id, std::clamp(restitution, 0.0f, 1.0f));
        return true;
    }

    bool set_body_motion_quality(uint32_t handle, const std::string& motion_quality_str) {
        auto it = mBodies.find(handle);
        if (it == mBodies.end() || it->second.motion_type == EMotionType::Static)
            return false;
        EMotionQuality quality = (
            motion_quality_str == "LINEAR_CAST" || motion_quality_str == "CCD"
        ) ? EMotionQuality::LinearCast : EMotionQuality::Discrete;
        mPhysicsSystem->GetBodyInterface().SetMotionQuality(it->second.id, quality);
        return true;
    }

    bool activate_body(uint32_t handle, bool active) {
        auto it = mBodies.find(handle);
        if (it == mBodies.end() || it->second.motion_type == EMotionType::Static)
            return false;
        BodyInterface& bi = mPhysicsSystem->GetBodyInterface();
        if (active)
            bi.ActivateBody(it->second.id);
        else
            bi.DeactivateBody(it->second.id);
        return true;
    }

    std::tuple<std::array<float,3>, std::array<float,4>>
    get_body_transform(uint32_t handle) const {
        auto it = mBodies.find(handle);
        if (it == mBodies.end())
            return {{0,0,0}, {1,0,0,0}};
        RVec3 pos; Quat rot;
        mPhysicsSystem->GetBodyInterface().GetPositionAndRotation(
            it->second.id, pos, rot);
        return {from_vec3(pos), from_quat(rot)};
    }

    std::tuple<
        std::array<float,3>,
        std::array<float,4>,
        std::array<float,3>,
        std::array<float,3>,
        bool,
        bool>
    get_body_state(uint32_t handle) const {
        auto it = mBodies.find(handle);
        if (it == mBodies.end())
            return {{0,0,0}, {1,0,0,0}, {0,0,0}, {0,0,0}, false, false};

        auto& lif = mPhysicsSystem->GetBodyLockInterface();
        BodyLockRead lock(lif, it->second.id);
        if (!lock.Succeeded())
            return {{0,0,0}, {1,0,0,0}, {0,0,0}, {0,0,0}, false, false};

        const Body& body = lock.GetBody();
        Vec3 linear_velocity = body.GetLinearVelocity();
        Vec3 angular_velocity = body.GetAngularVelocity();
        bool active = body.IsActive();
        bool sleeping = body.GetMotionType() == EMotionType::Dynamic && !active;
        return {
            from_vec3(body.GetPosition()),
            from_quat(body.GetRotation()),
            {linear_velocity.GetX(), linear_velocity.GetY(), linear_velocity.GetZ()},
            {angular_velocity.GetX(), angular_velocity.GetY(), angular_velocity.GetZ()},
            active,
            sleeping
        };
    }

    // ---- Constraint management -----------------------------------------

    uint32_t add_constraint(
        const std::string&        constraint_type_str,
        uint32_t                  body_a_handle,
        uint32_t                  body_b_handle,
        const std::array<float,3>& anchor_pos,
        const std::array<float,4>& anchor_rot_wxyz,   // (w,x,y,z)
        uint32_t                  constraint_priority,
        uint32_t                  solver_velocity_steps,
        uint32_t                  solver_position_steps,
        float                     draw_constraint_size,
        bool                      limit_enabled,
        float                     angular_limit_min,
        float                     angular_limit_max,
        float                     linear_limit_min,
        float                     linear_limit_max,
        float                     limit_spring_frequency,
        float                     limit_spring_damping,
        float                     max_friction_torque,
        float                     max_friction_force,
        const std::string&        motor_state_str,
        float                     motor_frequency,
        float                     motor_damping,
        float                     motor_force_limit,
        float                     motor_torque_limit,
        float                     motor_target_angular_velocity,
        float                     motor_target_angle,
        float                     motor_target_velocity,
        float                     motor_target_position,
        float                     cone_half_angle,
        bool                      disable_collisions,
        float                     distance_min,
        float                     distance_max
    ) {
        RVec3 pos = to_vec3(anchor_pos);
        Quat  rot = to_quat(anchor_rot_wxyz);

        // 持锁直到约束创建完成，防止 Body 引用在 Create() 前失效。
        // sFixedToWorld 是静态哨兵体，不通过 PhysicsSystem lock 管理。
        auto& lif = mPhysicsSystem->GetBodyLockInterface();

        std::unique_ptr<BodyLockRead> lock_a;
        std::unique_ptr<BodyLockRead> lock_b;
        const Body* body_a_ptr = nullptr;
        const Body* body_b_ptr = nullptr;

        if (body_a_handle == UINT32_MAX) {
            body_a_ptr = &Body::sFixedToWorld;
        } else {
            lock_a = std::make_unique<BodyLockRead>(lif, lookup_body_id(body_a_handle));
            if (!lock_a->Succeeded())
                throw std::runtime_error("无法锁定 Body A");
            body_a_ptr = &lock_a->GetBody();
        }

        if (body_b_handle == UINT32_MAX) {
            body_b_ptr = &Body::sFixedToWorld;
        } else {
            lock_b = std::make_unique<BodyLockRead>(lif, lookup_body_id(body_b_handle));
            if (!lock_b->Succeeded())
                throw std::runtime_error("无法锁定 Body B");
            body_b_ptr = &lock_b->GetBody();
        }

        // Jolt Create() 取 Body&（非 const），而 BodyLockRead / sFixedToWorld 均为 const Body&。
        // 单线程模式下约束创建发生在 step() 之外，Body 内存地址稳定，const_cast 安全。
        Body& body_a = const_cast<Body&>(*body_a_ptr);
        Body& body_b = const_cast<Body&>(*body_b_ptr);

        Ref<TwoBodyConstraint> c;
        auto apply_common = [&](auto& s) {
            s.mConstraintPriority = constraint_priority;
            s.mNumVelocityStepsOverride = (std::min)(solver_velocity_steps, uint32_t{255});
            s.mNumPositionStepsOverride = (std::min)(solver_position_steps, uint32_t{255});
            s.mDrawConstraintSize = (std::max)(0.0f, draw_constraint_size);
        };
        auto apply_limit_spring = [&](SpringSettings& spring) {
            spring = SpringSettings(
                ESpringMode::FrequencyAndDamping,
                (std::max)(0.0f, limit_spring_frequency),
                (std::max)(0.0f, limit_spring_damping)
            );
        };
        auto apply_motor_settings = [&](MotorSettings& motor) {
            motor.mSpringSettings = SpringSettings(
                ESpringMode::FrequencyAndDamping,
                (std::max)(0.0f, motor_frequency),
                (std::max)(0.0f, motor_damping)
            );
            if (motor_force_limit > 0.0f)
                motor.SetForceLimit(motor_force_limit);
            if (motor_torque_limit > 0.0f)
                motor.SetTorqueLimit(motor_torque_limit);
        };

        if (constraint_type_str == "FIXED") {
            FixedConstraintSettings s;
            apply_common(s);
            s.mAutoDetectPoint = false;
            s.mPoint1 = s.mPoint2 = pos;
            s.mAxisX1 = s.mAxisX2 = rot.RotateAxisX();
            s.mAxisY1 = s.mAxisY2 = rot.RotateAxisY();
            c = static_cast<TwoBodyConstraint*>(s.Create(body_a, body_b));
        } else if (constraint_type_str == "HINGE") {
            HingeConstraintSettings s;
            apply_common(s);
            s.mPoint1 = s.mPoint2 = pos;
            s.mHingeAxis1 = s.mHingeAxis2 = rot.RotateAxisZ();
            s.mNormalAxis1 = s.mNormalAxis2 = rot.RotateAxisX();
            if (limit_enabled) {
                float min_angle = std::clamp(angular_limit_min, -JPH_PI, 0.0f);
                float max_angle = std::clamp(angular_limit_max, 0.0f, JPH_PI);
                if (min_angle >= max_angle) {
                    max_angle = (std::min)(JPH_PI, min_angle + 1.0e-4f);
                    if (min_angle >= max_angle)
                        min_angle = max_angle - 1.0e-4f;
                }
                s.mLimitsMin = min_angle;
                s.mLimitsMax = max_angle;
                apply_limit_spring(s.mLimitsSpringSettings);
            }
            s.mMaxFrictionTorque = (std::max)(0.0f, max_friction_torque);
            apply_motor_settings(s.mMotorSettings);
            HingeConstraint* hinge = static_cast<HingeConstraint*>(s.Create(body_a, body_b));
            if (motor_state_str == "VELOCITY") {
                hinge->SetMotorState(EMotorState::Velocity);
                hinge->SetTargetAngularVelocity(motor_target_angular_velocity);
            } else if (motor_state_str == "POSITION") {
                hinge->SetMotorState(EMotorState::Position);
                hinge->SetTargetAngle(motor_target_angle);
            }
            c = static_cast<TwoBodyConstraint*>(hinge);
        } else if (constraint_type_str == "SLIDER") {
            SliderConstraintSettings s;
            apply_common(s);
            s.mAutoDetectPoint = false;
            s.mPoint1 = s.mPoint2 = pos;
            s.mSliderAxis1 = s.mSliderAxis2 = rot.RotateAxisZ();
            s.mNormalAxis1 = s.mNormalAxis2 = rot.RotateAxisX();
            if (limit_enabled) {
                float min_pos = linear_limit_min;
                float max_pos = linear_limit_max;
                if (min_pos > max_pos)
                    std::swap(min_pos, max_pos);
                if (min_pos == max_pos) {
                    max_pos = min_pos + 1.0e-4f;
                }
                s.mLimitsMin = min_pos;
                s.mLimitsMax = max_pos;
                apply_limit_spring(s.mLimitsSpringSettings);
            }
            s.mMaxFrictionForce = (std::max)(0.0f, max_friction_force);
            apply_motor_settings(s.mMotorSettings);
            SliderConstraint* slider = static_cast<SliderConstraint*>(s.Create(body_a, body_b));
            if (motor_state_str == "VELOCITY") {
                slider->SetMotorState(EMotorState::Velocity);
                slider->SetTargetVelocity(motor_target_velocity);
            } else if (motor_state_str == "POSITION") {
                slider->SetMotorState(EMotorState::Position);
                slider->SetTargetPosition(motor_target_position);
            }
            c = static_cast<TwoBodyConstraint*>(slider);
        } else if (constraint_type_str == "CONE") {
            ConeConstraintSettings s;
            apply_common(s);
            s.mPoint1 = s.mPoint2 = pos;
            s.mTwistAxis1 = s.mTwistAxis2 = rot.RotateAxisZ();
            s.mHalfConeAngle = std::clamp(cone_half_angle, 0.0f, JPH_PI);
            c = static_cast<TwoBodyConstraint*>(s.Create(body_a, body_b));
        } else if (constraint_type_str == "POINT") {
            PointConstraintSettings s;
            apply_common(s);
            s.mPoint1 = s.mPoint2 = pos;
            c = static_cast<TwoBodyConstraint*>(s.Create(body_a, body_b));
        } else if (constraint_type_str == "DISTANCE") {
            DistanceConstraintSettings s;
            apply_common(s);
            s.mPoint1 = s.mPoint2 = pos;
            s.mMinDistance = (std::max)(0.0f, (std::min)(distance_min, distance_max));
            s.mMaxDistance = (std::max)(s.mMinDistance, (std::max)(distance_min, distance_max));
            apply_limit_spring(s.mLimitsSpringSettings);
            c = static_cast<TwoBodyConstraint*>(s.Create(body_a, body_b));
        } else {
            throw std::invalid_argument("不支持的约束类型: " + constraint_type_str);
        }
        // lock_a / lock_b 在此析构，释放读锁

        mPhysicsSystem->AddConstraint(c);
        if (disable_collisions)
            disable_collision_pair(body_a_handle, body_b_handle);
        uint32_t handle = mNextHandle++;
        mConstraints[handle] = {
            c,
            body_a_handle,
            body_b_handle,
            disable_collisions,
            disable_collisions,
            constraint_type_str,
        };
        return handle;
    }

    std::tuple<
        std::string,
        bool,
        std::string,
        float,
        std::array<float,3>,
        std::array<float,3>,
        float,
        float>
    get_constraint_state(uint32_t handle) const {
        auto it = mConstraints.find(handle);
        if (it == mConstraints.end())
            return {"", false, "none", 0.0f, {0,0,0}, {0,0,0}, 0.0f, 0.0f};

        const ConstraintRecord& record = it->second;
        TwoBodyConstraint* base = record.constraint.GetPtr();
        std::string current_value_kind = "none";
        float current_value = 0.0f;
        std::array<float,3> lambda_position = {0.0f, 0.0f, 0.0f};
        std::array<float,3> lambda_rotation = {0.0f, 0.0f, 0.0f};
        float lambda_limit = 0.0f;
        float lambda_motor = 0.0f;

        if (record.constraint_type == "FIXED") {
            auto* constraint = static_cast<FixedConstraint*>(base);
            Vec3 p = constraint->GetTotalLambdaPosition();
            Vec3 r = constraint->GetTotalLambdaRotation();
            lambda_position = {p.GetX(), p.GetY(), p.GetZ()};
            lambda_rotation = {r.GetX(), r.GetY(), r.GetZ()};
        } else if (record.constraint_type == "HINGE") {
            auto* constraint = static_cast<HingeConstraint*>(base);
            current_value_kind = "angle";
            current_value = constraint->GetCurrentAngle();
            Vec3 p = constraint->GetTotalLambdaPosition();
            Vector<2> r = constraint->GetTotalLambdaRotation();
            lambda_position = {p.GetX(), p.GetY(), p.GetZ()};
            lambda_rotation = {r[0], r[1], 0.0f};
            lambda_limit = constraint->GetTotalLambdaRotationLimits();
            lambda_motor = constraint->GetTotalLambdaMotor();
        } else if (record.constraint_type == "SLIDER") {
            auto* constraint = static_cast<SliderConstraint*>(base);
            current_value_kind = "position";
            current_value = constraint->GetCurrentPosition();
            Vector<2> p = constraint->GetTotalLambdaPosition();
            Vec3 r = constraint->GetTotalLambdaRotation();
            lambda_position = {p[0], p[1], 0.0f};
            lambda_rotation = {r.GetX(), r.GetY(), r.GetZ()};
            lambda_limit = constraint->GetTotalLambdaPositionLimits();
            lambda_motor = constraint->GetTotalLambdaMotor();
        } else if (record.constraint_type == "CONE") {
            auto* constraint = static_cast<ConeConstraint*>(base);
            Vec3 p = constraint->GetTotalLambdaPosition();
            lambda_position = {p.GetX(), p.GetY(), p.GetZ()};
            lambda_rotation = {0.0f, 0.0f, constraint->GetTotalLambdaRotation()};
        } else if (record.constraint_type == "POINT") {
            auto* constraint = static_cast<PointConstraint*>(base);
            Vec3 p = constraint->GetTotalLambdaPosition();
            lambda_position = {p.GetX(), p.GetY(), p.GetZ()};
        } else if (record.constraint_type == "DISTANCE") {
            auto* constraint = static_cast<DistanceConstraint*>(base);
            current_value_kind = "distance";
            RVec3 point1 = constraint->GetBody1()->GetCenterOfMassTransform()
                * constraint->GetConstraintToBody1Matrix().GetTranslation();
            RVec3 point2 = constraint->GetBody2()->GetCenterOfMassTransform()
                * constraint->GetConstraintToBody2Matrix().GetTranslation();
            current_value = static_cast<float>((point2 - point1).Length());
            lambda_position = {constraint->GetTotalLambdaPosition(), 0.0f, 0.0f};
        }

        return {
            record.constraint_type,
            base->GetEnabled(),
            current_value_kind,
            current_value,
            lambda_position,
            lambda_rotation,
            lambda_limit,
            lambda_motor,
        };
    }

    bool set_constraint_enabled(uint32_t handle, bool enabled) {
        auto it = mConstraints.find(handle);
        if (it == mConstraints.end())
            return false;
        ConstraintRecord& record = it->second;
        if (record.disable_collisions) {
            if (enabled && !record.collision_pair_disabled) {
                disable_collision_pair(record.body_a_handle, record.body_b_handle);
                record.collision_pair_disabled = true;
            } else if (!enabled && record.collision_pair_disabled) {
                enable_collision_pair(record.body_a_handle, record.body_b_handle);
                record.collision_pair_disabled = false;
            }
        }
        record.constraint->SetEnabled(enabled);
        return true;
    }

    void remove_constraint(uint32_t handle) {
        auto it = mConstraints.find(handle);
        if (it == mConstraints.end()) return;
        if (it->second.collision_pair_disabled)
            enable_collision_pair(it->second.body_a_handle, it->second.body_b_handle);
        mPhysicsSystem->RemoveConstraint(it->second.constraint);
        mConstraints.erase(it);
    }

    // ---- Simulation step -----------------------------------------------

    float step(float dt, int substeps) {
        auto t0 = std::chrono::high_resolution_clock::now();
        mPhysicsSystem->Update(dt, substeps, mTempAllocator.get(), mJobSystem.get());
        auto t1 = std::chrono::high_resolution_clock::now();
        return std::chrono::duration<float, std::milli>(t1 - t0).count();
    }

    // ---- Info ------------------------------------------------------

    uint32_t body_count()       const { return static_cast<uint32_t>(mBodies.size()); }
    uint32_t constraint_count() const { return static_cast<uint32_t>(mConstraints.size()); }

    void set_gravity(const std::array<float,3>& g) {
        mPhysicsSystem->SetGravity(Vec3(g[0], g[1], g[2]));
    }

    void clear() {
        // 顺序：先移除约束（约束持有 Body 引用），再销毁刚体
        for (auto& [h, c] : mConstraints)
            mPhysicsSystem->RemoveConstraint(c.constraint);
        mConstraints.clear();
        mDisabledPairRefCounts.clear();
        mGroupFilter->ClearPairs();

        BodyInterface& bi = mPhysicsSystem->GetBodyInterface();
        for (auto& [h, r] : mBodies) {
            bi.RemoveBody(r.id);
            bi.DestroyBody(r.id);
        }
        mBodies.clear();
    }

private:
    BodyID lookup_body_id(uint32_t handle) const {
        auto it = mBodies.find(handle);
        if (it == mBodies.end())
            throw std::runtime_error("无效的 body handle");
        return it->second.id;
    }

    uint32_t allocate_filter_id() {
        uint32_t id = mNextFilterId++ & 0xffffu;
        if (id == 0u)
            id = mNextFilterId++ & 0xffffu;
        return id == 0u ? 1u : id;
    }

    static uint64_t pair_key(uint32_t a, uint32_t b) {
        uint32_t lo = (std::min)(a, b);
        uint32_t hi = (std::max)(a, b);
        return (static_cast<uint64_t>(lo) << 32u) | static_cast<uint64_t>(hi);
    }

    uint32_t filter_id_for_body_handle(uint32_t handle) const {
        auto it = mBodies.find(handle);
        return it == mBodies.end() ? 0u : it->second.filter_id;
    }

    void disable_collision_pair(uint32_t body_a_handle, uint32_t body_b_handle) {
        if (body_a_handle == UINT32_MAX || body_b_handle == UINT32_MAX)
            return;
        uint32_t id_a = filter_id_for_body_handle(body_a_handle);
        uint32_t id_b = filter_id_for_body_handle(body_b_handle);
        if (id_a == 0u || id_b == 0u || id_a == id_b)
            return;
        uint64_t key = pair_key(id_a, id_b);
        uint32_t& refs = mDisabledPairRefCounts[key];
        refs += 1u;
        if (refs == 1u)
            mGroupFilter->DisablePair(id_a, id_b);
    }

    void enable_collision_pair(uint32_t body_a_handle, uint32_t body_b_handle) {
        if (body_a_handle == UINT32_MAX || body_b_handle == UINT32_MAX)
            return;
        uint32_t id_a = filter_id_for_body_handle(body_a_handle);
        uint32_t id_b = filter_id_for_body_handle(body_b_handle);
        if (id_a == 0u || id_b == 0u || id_a == id_b)
            return;
        uint64_t key = pair_key(id_a, id_b);
        auto it = mDisabledPairRefCounts.find(key);
        if (it == mDisabledPairRefCounts.end())
            return;
        if (it->second > 1u) {
            it->second -= 1u;
            return;
        }
        mDisabledPairRefCounts.erase(it);
        mGroupFilter->EnablePair(id_a, id_b);
    }

    void remove_constraints_for_body(uint32_t body_handle) {
        std::vector<uint32_t> to_remove;
        for (const auto& [h, c] : mConstraints) {
            if (c.body_a_handle == body_handle || c.body_b_handle == body_handle)
                to_remove.push_back(h);
        }
        for (uint32_t h : to_remove)
            remove_constraint(h);
    }

    HoBPLayerInterface  mBPLayerInterface;
    HoObjVsBPFilter     mObjVsBPFilter;
    HoObjLayerFilter    mObjLayerFilter;
    Ref<HoCollisionGroupFilter> mGroupFilter;

    std::unique_ptr<TempAllocatorImpl>        mTempAllocator;
    std::unique_ptr<JobSystemSingleThreaded>  mJobSystem;
    std::unique_ptr<PhysicsSystem>            mPhysicsSystem;

    std::unordered_map<uint32_t, BodyRecord> mBodies;
    std::unordered_map<uint32_t, ConstraintRecord> mConstraints;
    std::unordered_map<uint64_t, uint32_t> mDisabledPairRefCounts;
    uint32_t mNextFilterId = 1;
    uint32_t mNextHandle = 1; // 0 保留为 invalid
};

// ---------------------------------------------------------------------------
// nanobind 模块
// ---------------------------------------------------------------------------

NB_MODULE(hotools_jolt, m) {
    m.doc() = "HoTools Jolt Physics binding（nanobind）";

    // tbbmalloc_proxy compatibility warmup: force Win32 thread primitives to initialize
    // before any Jolt call, ensuring CRITICAL_SECTION/SRWLOCK state is valid.
#ifdef _WIN32
    {
        CRITICAL_SECTION cs;
        InitializeCriticalSection(&cs);
        EnterCriticalSection(&cs);
        LeaveCriticalSection(&cs);
        DeleteCriticalSection(&cs);
    }
#endif

    // Initialize Jolt eagerly at module import time (not lazily in JoltWorld constructor)
    ensure_jolt_initialized();

    nb::class_<JoltWorld>(m, "JoltWorld")
        .def(nb::init<uint32_t, uint32_t, uint32_t>(),
             nb::arg("max_bodies")              = 2048,
             nb::arg("max_body_pairs")          = 4096,
             nb::arg("max_contact_constraints") = 2048,
             "创建 Jolt PhysicsSystem 实例。")

        // body
        .def("add_body", &JoltWorld::add_body,
             nb::arg("body_type"),
             nb::arg("mass"),
             nb::arg("friction"),
             nb::arg("restitution"),
             nb::arg("position"),
             nb::arg("rotation_wxyz"),
             nb::arg("shape_type"),
             nb::arg("shape_radius")       = 0.5f,
             nb::arg("shape_half_height")  = 0.5f,
             nb::arg("shape_half_extents") = std::array<float,3>{0.5f, 0.5f, 0.5f},
             nb::arg("collision_group")     = 1u,
             nb::arg("collided_by_groups")  = 0xffffu,
             nb::arg("shape_offset")       = std::array<float,3>{0.0f, 0.0f, 0.0f},
             nb::arg("shape_rotation_wxyz") = std::array<float,4>{1.0f, 0.0f, 0.0f, 0.0f},
             nb::arg("linear_velocity")    = std::array<float,3>{0.0f, 0.0f, 0.0f},
             nb::arg("angular_velocity")   = std::array<float,3>{0.0f, 0.0f, 0.0f},
             nb::arg("linear_damping")     = 0.05f,
             nb::arg("angular_damping")    = 0.05f,
             nb::arg("gravity_factor")     = 1.0f,
             nb::arg("allow_sleeping")     = true,
             nb::arg("motion_quality")     = "DISCRETE",
             nb::arg("max_linear_velocity") = 500.0f,
             nb::arg("max_angular_velocity") = 47.1239f,
             nb::arg("is_sensor")          = false,
             nb::arg("allowed_dofs")       = 0x3fu,
             nb::arg("collide_kinematic_vs_non_dynamic") = false,
             nb::arg("shape_plane_half_extent") = 10.0f,
             nb::arg("shape_top_radius") = 0.5f,
             nb::arg("shape_bottom_radius") = 0.3f,
             nb::arg("shape_convex_radius") = 0.05f,
             "注册刚体，返回 handle（uint32）。")

        .def("remove_body", &JoltWorld::remove_body,
             nb::arg("handle"),
             "从世界中移除并销毁刚体。")

        .def("set_kinematic_transform", &JoltWorld::set_kinematic_transform,
             nb::arg("handle"),
             nb::arg("position"),
             nb::arg("rotation_wxyz"),
             nb::arg("dt"),
             "每帧驱动运动学刚体位置/旋转（由 Blender 动画提供）。")

        .def("set_body_velocity", &JoltWorld::set_body_velocity,
             nb::arg("handle"),
             nb::arg("linear_velocity"),
             nb::arg("angular_velocity") = std::array<float,3>{0.0f, 0.0f, 0.0f},
             "设置非静态刚体线速度和角速度；无效或静态刚体返回 False。")

        .def("add_body_force", &JoltWorld::add_body_force,
             nb::arg("handle"),
             nb::arg("force"),
             nb::arg("torque") = std::array<float,3>{0.0f, 0.0f, 0.0f},
             "给动态刚体添加本步 force/torque；无效或非动态刚体返回 False。")

        .def("add_body_impulse", &JoltWorld::add_body_impulse,
             nb::arg("handle"),
             nb::arg("impulse"),
             nb::arg("angular_impulse") = std::array<float,3>{0.0f, 0.0f, 0.0f},
             "给动态刚体添加 impulse/angular impulse；无效或非动态刚体返回 False。")

        .def("set_body_gravity_factor", &JoltWorld::set_body_gravity_factor,
             nb::arg("handle"),
             nb::arg("gravity_factor"),
             "设置非静态刚体重力倍率；无效或静态刚体返回 False。")

        .def("set_body_material_response", &JoltWorld::set_body_material_response,
             nb::arg("handle"),
             nb::arg("friction"),
             nb::arg("restitution"),
             "设置刚体摩擦/弹性响应；无效刚体返回 False。")

        .def("set_body_motion_quality", &JoltWorld::set_body_motion_quality,
             nb::arg("handle"),
             nb::arg("motion_quality"),
             "设置非静态刚体 CCD/Discrete 质量；无效或静态刚体返回 False。")

        .def("activate_body", &JoltWorld::activate_body,
             nb::arg("handle"),
             nb::arg("active") = true,
             "激活或休眠非静态刚体；无效或静态刚体返回 False。")

        .def("get_body_transform", &JoltWorld::get_body_transform,
             nb::arg("handle"),
             "返回 (position, rotation_wxyz) 元组，用于写回 Blender 对象变换。")

        .def("get_body_state", &JoltWorld::get_body_state,
             nb::arg("handle"),
             "返回 (position, rotation_wxyz, linear_velocity, angular_velocity, active, sleeping)。")

        // constraint
        .def("add_constraint", &JoltWorld::add_constraint,
             nb::arg("constraint_type"),
             nb::arg("body_a_handle"),
             nb::arg("body_b_handle"),
             nb::arg("anchor_pos"),
             nb::arg("anchor_rot_wxyz"),
             nb::arg("constraint_priority") = 0u,
             nb::arg("solver_velocity_steps") = 0u,
             nb::arg("solver_position_steps") = 0u,
             nb::arg("draw_constraint_size") = 1.0f,
             nb::arg("limit_enabled") = false,
             nb::arg("angular_limit_min") = -JPH_PI,
             nb::arg("angular_limit_max") = JPH_PI,
             nb::arg("linear_limit_min") = -1.0f,
             nb::arg("linear_limit_max") = 1.0f,
             nb::arg("limit_spring_frequency") = 0.0f,
             nb::arg("limit_spring_damping") = 0.0f,
             nb::arg("max_friction_torque") = 0.0f,
             nb::arg("max_friction_force") = 0.0f,
             nb::arg("motor_state") = "OFF",
             nb::arg("motor_frequency") = 2.0f,
             nb::arg("motor_damping") = 1.0f,
             nb::arg("motor_force_limit") = 0.0f,
             nb::arg("motor_torque_limit") = 0.0f,
             nb::arg("motor_target_angular_velocity") = 0.0f,
             nb::arg("motor_target_angle") = 0.0f,
             nb::arg("motor_target_velocity") = 0.0f,
             nb::arg("motor_target_position") = 0.0f,
             nb::arg("cone_half_angle") = 0.0f,
             nb::arg("disable_collisions") = false,
             nb::arg("distance_min") = 0.0f,
             nb::arg("distance_max") = 1.0f,
             "注册约束（FIXED/HINGE/SLIDER/CONE/POINT/DISTANCE），返回 handle。\n"
             "body_a_handle 或 body_b_handle 传 0xFFFFFFFF 表示固定到世界。")

        .def("remove_constraint", &JoltWorld::remove_constraint,
             nb::arg("handle"),
             "移除约束。")

        .def("get_constraint_state", &JoltWorld::get_constraint_state,
             nb::arg("handle"),
             "返回约束类型、启用状态、当前值和上一物理步的 lambda 快照。")

        .def("set_constraint_enabled", &JoltWorld::set_constraint_enabled,
             nb::arg("handle"),
             nb::arg("enabled"),
             "启用或禁用约束；用于短期禁用和断裂策略。")

        // step
        .def("step", &JoltWorld::step,
             nb::arg("dt"),
             nb::arg("substeps") = 1,
             "执行一帧物理模拟，返回耗时（毫秒，float）。")

        // info
        .def_prop_ro("body_count",       &JoltWorld::body_count)
        .def_prop_ro("constraint_count", &JoltWorld::constraint_count)
        .def("set_gravity",              &JoltWorld::set_gravity,
             nb::arg("gravity"),
             "设置重力向量，默认 (0, 0, -9.81)（Blender Z-up）。")

        .def("clear", &JoltWorld::clear,
             "移除所有刚体和约束（dispose 时调用）。");

    // 常量：无效 handle
    m.attr("INVALID_HANDLE") = nb::int_(0u);
    m.attr("WORLD_HANDLE")   = nb::int_(0xFFFFFFFFu);
}
