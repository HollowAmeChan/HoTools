"""Ordinary Aux/Aim/MCH authoring metadata without a boneProperty dependency.

Actual constraint parameters remain on Blender constraints. Persistent groups
only record the declaration, roles and owner-local references. The legacy view
is read-only and never repairs missing or renamed constraints.
"""

from hashlib import sha256


from ..registry import load_registry

_MEMBER_SPECS = {
    row["type"]: tuple((member["constraintType"], member["role"])
                       for member in row["members"])
    for row in load_registry()["semanticDefinitions"] if row["version"] == 1
}
_AUX_SEMANTICS = {
    "TWIST": "TWIST", "FAN": "FAN", "FAN_SINGLE": "FAN",
    "FAN_SIDE": "FAN", "MCH": "MCH", "AIM": "AIM", "COPY_R": "COPY_ROTATION",
}
_OWNED_AUX_TYPES = frozenset({"TWIST", "FAN", "FAN_SINGLE", "FAN_SIDE", "MCH"})


def _data_bone(pose_bone):
    direct = getattr(pose_bone, "bone", None)
    if direct is not None:
        return direct
    bones = getattr(getattr(getattr(pose_bone, "id_data", None), "data", None), "bones", None)
    getter = getattr(bones, "get", None)
    return getter(pose_bone.name) if callable(getter) else None


def _props(data_bone):
    return getattr(data_bone, "hotools_boneprops", None)


def _aux(data_bone):
    return getattr(_props(data_bone), "auxBone", None)


def _groups(data_bone):
    return getattr(_props(data_bone), "constraintGroups", None)


def _invalidate(armature):
    if armature is None:
        return
    try:
        from . import review
    except ImportError:
        return
    callback = getattr(review, "invalidate", None)
    if callable(callback):
        callback(armature)


def _group_id(semantic_type, generator_id):
    key = semantic_type + "\0" + generator_id
    return "g_" + sha256(key.encode("utf-8")).hexdigest()[:24]


def _aux_type(data_bone):
    aux = _aux(data_bone)
    return str(getattr(aux, "auxType", "") or "").strip().upper()


def _generator_id(aux_type):
    return "hotools.aux." + aux_type.lower()


def register_group(pose_bone, semantic_type, constraints, *, generator_id="", semantic_version=1, roles=None, owns_bone=False):
    """Commit all members of one declaration, updating the same generator group.

    A generator can distinguish multiple groups of the same semantic type on a
    bone with different generator_id values. Minimal legacy PropertyGroups keep
    working: without constraintGroups this is an intentional no-op.
    """
    data_bone = _data_bone(pose_bone)
    groups = _groups(data_bone)
    if groups is None:
        return None
    semantic_type = str(semantic_type or "").strip().upper()
    if not semantic_type or not isinstance(semantic_version, int) or semantic_version < 1:
        raise ValueError("Constraint groups need a semantic type and positive version")
    constraints = list(constraints)
    if not constraints:
        raise ValueError("A constraint group needs at least one member")
    if any(not str(getattr(c, "name", "") or "") for c in constraints):
        raise ValueError("Constraint group members need owner-local names")
    if len({c.name for c in constraints}) != len(constraints):
        raise ValueError("A constraint group cannot repeat a member")
    spec = _MEMBER_SPECS.get(semantic_type, ())
    if roles is None:
        if tuple(str(c.type) for c in constraints) == tuple(t for t, _ in spec):
            roles = [role for _, role in spec]
        else:
            roles = ["member"] * len(constraints)
    roles = list(roles)
    if len(roles) != len(constraints):
        raise ValueError("Provide one role per constraint group member")
    generator_id = str(generator_id or _generator_id(_aux_type(data_bone) or semantic_type))
    group_id = _group_id(semantic_type, generator_id)
    group = next((g for g in groups if g.groupId == group_id), None)
    if group is None:
        group = groups.add()
    group.groupId = group_id
    group.semanticType = semantic_type
    group.semanticVersion = semantic_version
    group.generatorId = generator_id
    group.evidence = "GENERATED"
    group.ownsBone = bool(owns_bone)
    group.members.clear()
    for index, (constraint, role) in enumerate(zip(constraints, roles)):
        member = group.members.add()
        member.constraintName = str(constraint.name)
        member.constraintType = str(constraint.type)
        member.role = str(role)
        member.order = index
    _invalidate(getattr(pose_bone, "id_data", None))
    return group_id


def clear_groups(data_bone):
    """Clear ordinary declarations only; never touch the large HoAux system."""
    groups = _groups(data_bone)
    if groups is not None:
        groups.clear()
    _invalidate(getattr(data_bone, "id_data", None))


def _clear_legacy_aux(data_bone):
    aux = _aux(data_bone)
    if aux is None:
        return
    aux.sourceBones.clear()
    aux.constraintNames.clear()
    aux.auxType = "NONE"
    aux.isAuxBone = False
    if hasattr(aux, "aimVersion"):
        aux.aimVersion = 1


def reset_aux_info(data_bone):
    """Remove ordinary Aux identity and declarations while preserving the bone."""
    clear_groups(data_bone)
    _clear_legacy_aux(data_bone)


def unregister_group(data_bone, semantic_type, *, generator_id=""):
    """Unregister exactly one generator declaration; never delete constraints.

    The old Aux identity is a shadow of the same default generator and is cleared
    only for that matching declaration, avoiding read-only legacy resurrection.
    Other new groups and large HoAux metadata are preserved.
    """
    semantic_type = str(semantic_type or "").strip().upper()
    aux_type = _aux_type(data_bone)
    generator_id = str(generator_id or _generator_id(aux_type or semantic_type))
    group_id = _group_id(semantic_type, generator_id)
    groups = _groups(data_bone)
    removed = 0
    if groups is not None:
        for index in reversed(range(len(groups))):
            if groups[index].groupId == group_id:
                groups.remove(index)
                removed += 1
    if _AUX_SEMANTICS.get(aux_type) == semantic_type and _generator_id(aux_type) == generator_id:
        _clear_legacy_aux(data_bone)
    _invalidate(getattr(data_bone, "id_data", None))
    return removed


def owns_aux_bone(data_bone, *, pose_bone=None):
    """Return whether an ordinary generator owns this bone, not just constraints."""
    aux_type = _aux_type(data_bone)
    # Explicitly adopted owners remain protected even if a malformed declaration
    # claims ownership. They were never created by these authoring tools.
    if aux_type in {"COPY_R", "AIM"}:
        return False
    groups = iter_groups(data_bone, pose_bone=pose_bone)
    if groups:
        return any(group.get("ownsBone", False) for group in groups)
    return aux_type in _OWNED_AUX_TYPES


def prepare_aux_detach(pose_bone):
    """Preflight a constraint-only Aux removal without changing authoring data."""
    data_bone = _data_bone(pose_bone)
    aux_type = _aux_type(data_bone)
    semantic_type = _AUX_SEMANTICS.get(aux_type)
    generator_id = _generator_id(aux_type)
    candidates = [g for g in iter_groups(data_bone, pose_bone=pose_bone)
                  if g["semanticType"] == semantic_type and g["generatorId"] == generator_id]
    if len(candidates) != 1:
        raise ValueError(f"{pose_bone.name} 的 {aux_type} 登记缺失或重复，保留原骨及约束")
    group = candidates[0]
    if group["groupId"] != _group_id(semantic_type, generator_id):
        raise ValueError(f"{pose_bone.name} 的 {aux_type} 登记身份失配，保留原骨及约束")
    spec = _MEMBER_SPECS.get(semantic_type)
    members = group["members"]
    if group["semanticVersion"] != 1 or spec is None or len(members) != len(spec):
        raise ValueError(f"{pose_bone.name} 的 {aux_type} 登记版本或成员无效，保留原骨及约束")
    names = []
    for index, ((expected_type, role), member) in enumerate(zip(spec, members)):
        name = member["constraintName"]
        actual = pose_bone.constraints.get(name) if name else None
        if (not name or name in names or member["constraintType"] != expected_type or
                member["role"] != role or member["order"] != index or
                actual is None or actual.type != expected_type):
            raise ValueError(f"{pose_bone.name} 的已登记约束 {name or '<缺失>'} 缺失或类型失配，保留原骨及约束")
        names.append(name)
    return group


def detach_aux_group(pose_bone, group):
    """Remove only preflighted owner-local members and that generator's metadata."""
    current = prepare_aux_detach(pose_bone)
    if current != group:
        raise ValueError(f"{pose_bone.name} 的登记已变化，请重新检查后移除")
    for member in group["members"]:
        pose_bone.constraints.remove(pose_bone.constraints[member["constraintName"]])
    unregister_group(_data_bone(pose_bone), group["semanticType"], generator_id=group["generatorId"])
    return len(group["members"])


def _member_view(member):
    return {
        "constraintName": str(member.constraintName),
        "constraintType": str(member.constraintType),
        "role": str(member.role),
        "order": int(member.order),
    }


def _legacy_group(data_bone, pose_bone=None):
    aux = _aux(data_bone)
    aux_type = _aux_type(data_bone)
    semantic_type = _AUX_SEMANTICS.get(aux_type)
    if not getattr(aux, "isAuxBone", False) or semantic_type is None:
        return None
    names = [str(ref.name) for ref in getattr(aux, "constraintNames", ()) if str(ref.name)]
    # Fan pin bones legitimately have Aux identity without generated constraints.
    if not names:
        return None
    spec = _MEMBER_SPECS[semantic_type]
    stack = getattr(pose_bone, "constraints", None) if pose_bone is not None else None
    members = []
    used = set()
    for index, (expected_type, role) in enumerate(spec):
        name = ""
        if stack is not None:
            for registered in names:
                if registered in used:
                    continue
                constraint = stack.get(registered)
                if constraint is not None and constraint.type == expected_type:
                    name = registered
                    break
            if not name:
                # Preserve unresolved names as evidence. A same-named, wrong-type
                # constraint must also remain visible to structural validation.
                name = next((n for n in names if n not in used and stack.get(n) is None), "")
                if not name and len(names) == len(spec):
                    name = next((n for n in names if n not in used), "")
        elif len(names) <= len(spec):
            name = names[index] if index < len(names) else ""
        if name:
            used.add(name)
        members.append({"constraintName": name, "constraintType": expected_type, "role": role, "order": index})
    # Without owner context an extended legacy Aim list cannot be safely paired.
    # Keep each reference; callers can resolve it with their specific PoseBone.
    if stack is None and len(names) > len(spec):
        first_extra = len(members)
        members.extend({"constraintName": n, "constraintType": "", "role": "unresolved", "order": first_extra + i} for i, n in enumerate(names))
    generator_id = _generator_id(aux_type)
    return {
        "groupId": _group_id(semantic_type, generator_id),
        "semanticType": semantic_type,
        "semanticVersion": int(getattr(aux, "aimVersion", 1)) if semantic_type == "AIM" else 1,
        "generatorId": generator_id,
        "members": members,
        "evidence": "LEGACY",
        "ownsBone": aux_type in _OWNED_AUX_TYPES,
    }


def iter_groups(data_bone, *, pose_bone=None):
    """Return fresh standard dictionaries, adapting old metadata without writes.

    Optional owner context disambiguates legacy Aim records that also registered
    independent position constraints. Never search other objects for a PoseBone.
    """
    groups = _groups(data_bone)
    if groups is not None and len(groups):
        return [{
            "groupId": str(group.groupId),
            "semanticType": str(group.semanticType),
            "semanticVersion": int(group.semanticVersion),
            "generatorId": str(group.generatorId),
            "members": [_member_view(member) for member in group.members],
            "evidence": str(group.evidence or "GENERATED"),
            "ownsBone": bool(group.ownsBone),
        } for group in groups]
    legacy = _legacy_group(data_bone, pose_bone)
    return [legacy] if legacy is not None else []


def _register_aux_constraint(pose_bone, constraint):
    """Legacy partial registration: update the name index, never a group."""
    aux = _aux(_data_bone(pose_bone))
    name = str(getattr(constraint, "name", "") or "")
    if aux is None or not name:
        return
    if all(ref.name != name for ref in aux.constraintNames):
        aux.constraintNames.add().name = name
    _invalidate(getattr(pose_bone, "id_data", None))


def _find_registered_aux_constraint(pose_bone, constraint_type):
    aux = _aux(_data_bone(pose_bone))
    if aux is None:
        return None
    names = {ref.name for ref in aux.constraintNames if ref.name}
    return next((c for c in getattr(pose_bone, "constraints", ()) if c.name in names and c.type == constraint_type), None)


def _ensure_aux_constraint_name_available(pose_bone, constraint_name, constraint_type):
    if pose_bone is None:
        return
    aux = _aux(_data_bone(pose_bone))
    names = {ref.name for ref in getattr(aux, "constraintNames", ()) if ref.name}
    for constraint in getattr(pose_bone, "constraints", ()):
        if constraint.name != constraint_name:
            continue
        if constraint_name not in names:
            raise RuntimeError(
                f"骨架 {getattr(getattr(pose_bone, 'id_data', None), 'name', '<未知>')} 的骨骼 {pose_bone.name} "
                f"已有未登记约束 {constraint_name}，无法创建 {constraint_type}；请先改名或删除冲突约束。"
            )
        if constraint.type != constraint_type:
            raise RuntimeError(
                f"骨骼 {pose_bone.name} 已登记约束 {constraint_name} 类型为 {constraint.type}，与需要的 {constraint_type} 不一致。"
            )


def _replace_aux_constraints(pose_bone, constraints):
    """Replace legacy names and commit a complete known ordinary semantic group."""
    data_bone = _data_bone(pose_bone)
    aux = _aux(data_bone)
    if aux is None:
        return
    constraints = list(constraints)
    aux.constraintNames.clear()
    for constraint in constraints:
        _register_aux_constraint(pose_bone, constraint)
    aux_type = _aux_type(data_bone)
    semantic_type = _AUX_SEMANTICS.get(aux_type)
    if not getattr(aux, "isAuxBone", False) or semantic_type is None:
        return
    spec = _MEMBER_SPECS[semantic_type]
    # Aim's owned list can also contain independent Copy Location constraints.
    selected = [c for c in constraints if c.type in {t for t, _ in spec}]
    generator_id = _generator_id(aux_type)
    groups = _groups(data_bone)
    if groups is not None:
        for index in reversed(range(len(groups))):
            if groups[index].groupId == _group_id(semantic_type, generator_id):
                groups.remove(index)
    if tuple(c.type for c in selected) == tuple(t for t, _ in spec):
        register_group(pose_bone, semantic_type, selected, generator_id=generator_id,
                       semantic_version=int(getattr(aux, "aimVersion", 1)) if semantic_type == "AIM" else 1,
                       roles=[role for _, role in spec], owns_bone=aux_type in _OWNED_AUX_TYPES)
    _invalidate(getattr(pose_bone, "id_data", None))
