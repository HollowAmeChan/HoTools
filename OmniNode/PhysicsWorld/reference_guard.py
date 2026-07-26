"""PhysicsWorld 对 OmniNode 持久引用门禁协议的适配。"""

from __future__ import annotations

from ..OmniReferenceGuard import (
    is_bpy_reference_valid,
    resolve_bpy_object_reference,
)


def _pointer(value, name: str) -> int:
    try:
        if isinstance(value, dict):
            return int(value.get(name, 0) or 0)
        return int(getattr(value, name, 0) or 0)
    except Exception:
        return 0


def _current_reference(value, name: str):
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _set_reference(value, name: str, reference) -> bool:
    try:
        if isinstance(value, dict):
            previous = value.get(name)
            value[name] = reference
        else:
            previous = getattr(value, name, None)
            setattr(value, name, reference)
        return previous is not reference
    except Exception:
        return False


def _declares_armature_reference(value) -> bool:
    names = ("armature", "armature_ptr", "armature_data_ptr")
    if isinstance(value, dict):
        return any(name in value for name in names)
    return any(hasattr(value, name) for name in names)


def _reference_matches(reference, object_pointer: int, data_pointer: int) -> bool:
    if not is_bpy_reference_valid(reference):
        return False
    if object_pointer <= 0:
        return True
    try:
        if int(reference.as_pointer()) != object_pointer:
            return False
        if data_pointer <= 0:
            return True
        data = getattr(reference, "data", None)
        return data is not None and int(data.as_pointer()) == data_pointer
    except Exception:
        return False


def _refresh_armature(value) -> int:
    if not _declares_armature_reference(value):
        return 0
    current = _current_reference(value, "armature")
    object_pointer = _pointer(value, "armature_ptr")
    data_pointer = _pointer(value, "armature_data_ptr")
    if _reference_matches(current, object_pointer, data_pointer):
        return 0

    fresh = resolve_bpy_object_reference(
        object_pointer,
        data_pointer,
        object_type="ARMATURE",
    )
    return 1 if _set_reference(value, "armature", fresh) else 0


def _refresh_slot(slot) -> int:
    data = getattr(slot, "data", None)
    spec = data.get("spec") if isinstance(data, dict) else None
    if spec is None:
        return 0

    changed = _refresh_armature(spec)
    for chain in tuple(getattr(spec, "chains", ()) or ()):
        changed += _refresh_armature(chain)
    return changed


def _refresh_implicit_object(entry: dict) -> int:
    changed = _refresh_armature(entry)
    payload = entry.get("payload")
    if isinstance(payload, dict):
        changed += _refresh_armature(payload)
    return changed


def refresh_physics_world_references(world, reason: str = "unknown") -> int:
    """刷新一个 PhysicsWorldCache 内全部已声明身份的 Armature 引用。"""
    changed = 0
    solver_slots = getattr(world, "solver_slots", None)
    if isinstance(solver_slots, dict):
        for slot in tuple(solver_slots.values()):
            changed += _refresh_slot(slot)

    implicit_objects = getattr(world, "implicit_objects", None)
    if isinstance(implicit_objects, list):
        for entry in tuple(implicit_objects):
            if isinstance(entry, dict):
                changed += _refresh_implicit_object(entry)
    return changed
