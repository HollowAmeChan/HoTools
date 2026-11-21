"""Validate a pair only when an author explicitly adopts it as Aim."""

from ..source.context import _bone_get


def inspect_aim_pair(armature, owner, names=None):
    """Describe one strict rotation-only pair, without modifying ownership."""
    stack = list(getattr(owner, "constraints", ()))
    selected = [(i, c) for i, c in enumerate(stack)
                if (names is None or c.name in names) and c.type in {"DAMPED_TRACK", "LOCKED_TRACK"}]
    if len(selected) != 2 or selected[1][0] != selected[0][0] + 1:
        return None
    pair = [c for _, c in selected]
    if [c.type for c in pair] != ["DAMPED_TRACK", "LOCKED_TRACK"]:
        return None
    sources = [str(getattr(c, "subtarget", "")) for c in pair]
    if len(set(sources)) != 2 or owner.name in sources:
        return None
    if any(not (getattr(c, "target", None) == armature and bool(getattr(c, "subtarget", ""))) or _bone_get(armature.data.bones, c.subtarget) is None for c in pair):
        return None
    if any(getattr(c, "influence", 0) != 1.0 or getattr(c, "owner_space", "") != "WORLD" or getattr(c, "target_space", "") != "WORLD" or getattr(c, "head_tail", 0) != 0 or getattr(c, "use_bbone_shape", False) for c in pair):
        return None
    if len({bool(getattr(c, "mute", False)) for c in pair}) != 1:
        return None
    damped, locked = pair
    aim_axis, up_axis = getattr(damped, "track_axis", ""), getattr(locked, "track_axis", "")
    axes = {"TRACK_X", "TRACK_Y", "TRACK_Z", "TRACK_NEGATIVE_X", "TRACK_NEGATIVE_Y", "TRACK_NEGATIVE_Z"}
    if aim_axis not in axes or up_axis not in axes or aim_axis[-1] == up_axis[-1] or getattr(locked, "lock_axis", "") != "LOCK_" + aim_axis[-1]:
        return None
    return {"selected": selected, "sources": sources, "aim_axis": aim_axis, "up_axis": up_axis,
            "muted": bool(getattr(damped, "mute", False))}
