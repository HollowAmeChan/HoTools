"""Independent corrective rotation math. Quaternions use x, y, z, w order."""
import math

ANGLE_EPSILON = 1e-5


def normalize_quaternion(values):
    values = tuple(float(value) for value in values)
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        raise ValueError("姿态四元数必须包含四个有限数值")
    length = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(length) or length < 1e-12:
        raise ValueError("姿态四元数不能为零")
    return tuple(value / length for value in values)


def euler_xyz_quaternion(euler):
    x, y, z = (float(value) * 0.5 for value in euler)
    if not all(math.isfinite(value) for value in (x, y, z)):
        raise ValueError("姿态旋转必须为有限数值")
    cx, cy, cz = math.cos(x), math.cos(y), math.cos(z)
    sx, sy, sz = math.sin(x), math.sin(y), math.sin(z)
    return normalize_quaternion((
        sx * cy * cz - cx * sy * sz,
        cx * sy * cz + sx * cy * sz,
        cx * cy * sz - sx * sy * cz,
        cx * cy * cz + sx * sy * sz,
    ))


def quaternion_angle(a, b):
    """Shortest SO(3) angle between normalized quaternions; q and -q agree."""
    dot = min(1.0, abs(sum(x * y for x, y in zip(a, b))))
    return 2.0 * math.atan2(math.sqrt(max(0.0, 1.0 - dot * dot)), dot)


IDENTITY = (0.0, 0.0, 0.0, 1.0)


def smoothstep(value):
    t = min(1.0, max(0.0, value))
    return t * t * (3.0 - 2.0 * t)


def pose_weight(current, pose, radius, weight=1.0, neutral_angle=None, current_neutral=None):
    distance = quaternion_angle(current, pose)
    if distance >= radius:
        return 0.0
    c = neutral_angle if neutral_angle is not None else quaternion_angle(pose, IDENTITY)
    if c < ANGLE_EPSILON:
        raise ValueError("修型姿态不能与基准姿态相同")
    b = current_neutral if current_neutral is not None else quaternion_angle(current, IDENTITY)
    neutral = smoothstep((b + c - distance) / (2.0 * c))
    return weight * smoothstep(1.0 - distance / radius) * neutral
