"""MC2 Python 后端的常量与 cache schema 标识。"""

MC2_CACHE_KIND = "MESH_PHYSICS_MC2"
MC2_SOLVER_VERSION = 3

MC2_ATTR_INVALID = 1 << 0
MC2_ATTR_FIXED = 1 << 1
MC2_ATTR_MOVE = 1 << 2
MC2_ATTR_MOTION = 1 << 3

MC2_DISTANCE_TYPE_STRUCTURAL = 1
MC2_DISTANCE_TYPE_BEND_DISTANCE_APPROX = 16
MC2_BEND_KIND_DISTANCE_APPROX = "distance_approx"

MC2_CURVE_READY_PARAMETERS = {
    "distance_stiffness",
    "bend_stiffness",
    "radius",
    "max_distance",
    "tether_compression",
    "tether_stretch",
    "motion_stiffness",
    "backstop_radius",
    "backstop_distance",
    "collider_friction",
    "angle_restoration_stiffness",
    "angle_limit",
    "damping",
}


class MC2SystemConstants:
    """与 MC2 Define.System 对齐的求解常量。"""

    EPSILON = 0.000001
    FRICTION_MASS = 3.0
    DEPTH_MASS = 5.0
    TETHER_COMPRESSION_LIMIT = 0.4
    TETHER_STRETCH_LIMIT = 0.03
    TETHER_STIFFNESS_WIDTH = 0.3
    TETHER_COMPRESSION_STIFFNESS = 1.0
    TETHER_STRETCH_STIFFNESS = 1.0
    TETHER_COMPRESSION_VELOCITY_ATTENUATION = 0.7
    TETHER_STRETCH_VELOCITY_ATTENUATION = 0.7
    MOTION_VELOCITY_ATTENUATION = 0.95
    COLLIDER_COLLISION_DYNAMIC_FRICTION_RATIO = 1.0
    COLLIDER_COLLISION_STATIC_FRICTION_RATIO = 1.0
