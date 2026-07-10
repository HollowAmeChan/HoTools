"""共享碰撞组、mask 与预览颜色。"""

COLLISION_GROUP_COUNT = 16
ALL_COLLISION_GROUPS_MASK = (1 << COLLISION_GROUP_COUNT) - 1
COLLISION_GROUP_COLORS = (
    (0.10, 0.63, 1.00, 0.86),
    (1.00, 0.45, 0.25, 0.86),
    (0.35, 0.90, 0.35, 0.86),
    (1.00, 0.82, 0.18, 0.86),
    (0.78, 0.48, 1.00, 0.86),
    (0.12, 0.92, 0.82, 0.86),
    (1.00, 0.35, 0.62, 0.86),
    (0.62, 0.88, 0.18, 0.86),
    (0.30, 0.48, 1.00, 0.86),
    (1.00, 0.60, 0.12, 0.86),
    (0.20, 0.78, 0.55, 0.86),
    (0.92, 0.38, 1.00, 0.86),
    (0.88, 0.75, 0.55, 0.86),
    (0.52, 0.72, 0.95, 0.86),
    (0.95, 0.52, 0.52, 0.86),
    (0.78, 0.78, 0.78, 0.86),
)


def set_collision_group_bit(mask: int, group: int, value: bool) -> int:
    bit = 1 << (int(group) - 1)
    return int(mask) | bit if value else int(mask) & ~bit


def collision_group_bit(mask: int, group: int) -> bool:
    return bool(int(mask) & (1 << (int(group) - 1)))


def collision_group_color(group: int):
    index = min(max(int(group), 1), COLLISION_GROUP_COUNT) - 1
    return COLLISION_GROUP_COLORS[index]


__all__ = [
    "ALL_COLLISION_GROUPS_MASK",
    "COLLISION_GROUP_COLORS",
    "COLLISION_GROUP_COUNT",
    "collision_group_bit",
    "collision_group_color",
    "set_collision_group_bit",
]
