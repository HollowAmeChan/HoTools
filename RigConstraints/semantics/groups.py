"""Validate a declaration against its actual source facts, without repairs."""

from ..registry import load_registry


def definition(kind, version=1):
    return next((d for d in load_registry()["semanticDefinitions"]
                 if d["type"] == kind and d["version"] == version), None)


def inspect_group(group, document):
    """Return (resolved sources, reasons). A broken declaration stays broken."""
    reasons, sources = [], []
    d = definition(group.get("semanticType"), group.get("semanticVersion"))
    if d is None:
        return [], ["未支持的语义类型或版本"]
    if d.get("generatorIds") and group.get("generatorId") not in d["generatorIds"]:
        reasons.append("生成来源不符合语义契约")
    if d.get("acceptedEvidence") and group.get("evidence") not in d["acceptedEvidence"]:
        reasons.append("登记来源不符合语义契约")
    spec = d.get("members", ())
    members = group.get("members", ())
    if len(members) != len(spec):
        reasons.append("成员数量与语义契约不符")
    by_id = {s["sourceId"]: s for s in document["sources"]}
    ids = group.get("memberSourceIds", ())
    for index, expected in enumerate(spec):
        member = members[index] if index < len(members) else {}
        sid = ids[index] if index < len(ids) else ""
        source = by_id.get(sid)
        if source is None:
            reasons.append("缺少成员约束：" + (member.get("constraintName") or expected["role"]))
            continue
        sources.append(source)
        c = source["constraint"]
        if source["ownerBone"] != group["ownerBone"] or source["ownerKind"] != "BONE":
            reasons.append("成员不属于登记骨骼")
        if c["constraintType"] != expected["constraintType"] or member.get("constraintType") != expected["constraintType"]:
            reasons.append("成员类型不符：" + c["name"])
        if member.get("role") != expected["role"] or member.get("order") != index:
            reasons.append("成员角色或登记顺序不符：" + c["name"])
    if len({s["sourceId"] for s in sources}) != len(sources):
        reasons.append("同一约束被重复登记")
    if len(sources) == len(spec) and len(sources) > 1:
        positions = [s["constraint"]["stackIndex"] for s in sources]
        if positions != list(range(positions[0], positions[0] + len(positions))):
            reasons.append("组合成员必须按契约相邻且有序")
    for name in group.get("sourceBones", ()):
        if name not in {b["boneName"] for b in document.get("sourceContext", {}).get("bones", ())}:
            reasons.append("关联骨缺失：" + name)
    if not reasons and group["semanticType"] == "AIM":
        reasons += _aim_reasons(sources, group, document)
    if not reasons and group["semanticType"] == "TWIST":
        if len({(s["constraint"]["targetObjectName"], s["constraint"]["targetBoneName"]) for s in sources}) != 1:
            reasons.append("Twist 旋转与伸展目标不一致")
    if not reasons and group["semanticType"] == "MCH":
        if group.get("sourceBones") != [sources[0]["constraint"]["targetBoneName"]]:
            reasons.append("MCH 来源声明与约束目标不一致")
    return sources, list(dict.fromkeys(reasons))


def _aim_reasons(sources, group, document):
    a, u = [s["constraint"] for s in sources]
    targets = [a["targetBoneName"], u["targetBoneName"]]
    reasons = []
    if group.get("sourceBones") != targets:
        reasons.append("Aim 角色目标与登记不一致")
    if len(set(targets + [group["ownerBone"]])) != 3:
        reasons.append("Aim owner/target/up 必须互异")
    for c in (a, u):
        p = c["parameters"]
        if c["targetObjectName"] != document["armatureName"]:
            reasons.append("Aim v1 要求当前骨架目标")
        if p.get("owner_space") != "WORLD" or p.get("target_space") != "WORLD":
            reasons.append("Aim v1 要求 WORLD→WORLD")
        if p.get("influence") != 1 or p.get("head_tail", 0) != 0 or p.get("use_bbone_shape", False):
            reasons.append("Aim v1 成员影响度/目标点设置不符")
    ap, up = a["parameters"], u["parameters"]
    aa, ua = ap.get("track_axis", ""), up.get("track_axis", "")
    if not aa or not ua or aa[-1:] == ua[-1:] or up.get("lock_axis") != "LOCK_" + aa[-1:]:
        reasons.append("Aim 轴组合不符")
    if ap.get("mute", False) != up.get("mute", False):
        reasons.append("Aim 两成员静音状态不一致")
    return reasons


def source_reference_reasons(source, document):
    """Validate resolvable ordinary bone targets; external facts stay intact."""
    c = source["constraint"]
    type_record = next((r for r in load_registry()["constraintTypes"]
                        if r["type"] == c["constraintType"]), {})
    reasons = []
    if type_record.get("targetRequired") and not c.get("targetObjectName"):
        reasons.append("约束目标对象缺失")
    context = document.get("sourceContext", {})
    if source.get("captureStage") == "EXPORT_GENERATED":
        context = document.get("bindings", {}).get("bindingContext", context)
    bone_names = {b["boneName"] for b in context.get("bones", ())}
    target = c.get("targetBoneName")
    if c.get("targetObjectName") == document["armatureName"] and target and target not in bone_names:
        reasons.append("目标骨缺失：" + target)
    if c["constraintType"] == "ARMATURE":
        targets = c.get("references", {}).get("targets", ())
        if not targets:
            reasons.append("Armature 来源列表为空")
        for row in targets:
            p = row.get("properties", {})
            if not p.get("target"):
                reasons.append("Armature 来源对象缺失")
            elif p["target"].get("name") == document["armatureName"] and p.get("subtarget") not in bone_names:
                reasons.append("Armature 来源骨缺失：" + p.get("subtarget", ""))
    reasons += _excluded_dependency_reasons(source, document)
    return list(dict.fromkeys(reasons))


def _excluded_dependency_reasons(source, document):
    """Observe the ordinary-export boundary without opening excluded stacks."""
    excluded = set(document.get("excludedOwners", ()))
    if not excluded:
        return []
    armature = document["armatureName"]
    reasons = []

    def inspect(constraint, owner, context, excluded_names, stage):
        parents = {b["boneName"]: b.get("parentBone", "") for b in context.get("bones", ())}
        dependencies = []
        if source["ownerKind"] == "BONE":
            dependencies.append(("所属骨", owner))
        if constraint.get("targetObjectName") == armature:
            dependencies.append(("目标骨", constraint.get("targetBoneName", "")))
        if constraint.get("constraintType") == "ARMATURE":
            for row in constraint.get("references", {}).get("targets", ()):
                p = row.get("properties", {})
                if (p.get("target") or {}).get("name") == armature:
                    dependencies.append(("Armature 来源骨", p.get("subtarget", "")))
        for role, name in dependencies:
            current, visited = name, set()
            while current:
                if current in visited:
                    reasons.append("{}{}父链循环，无法检查已排除的大型 HoAux 骨边界".format(stage, role))
                    break
                if current in excluded_names:
                    reasons.append("{}{}依赖已排除的大型 HoAux 骨：{}；其约束栈不在本轮普通约束导出中".format(stage, role, current))
                    break
                visited.add(current)
                if current not in parents:
                    reasons.append("{}{}依赖边界不完整，无法检查已排除的大型 HoAux 骨：{}".format(stage, role, current))
                    break
                current = parents[current]

    overlay = document.get("bindings")
    generated = source.get("captureStage") == "EXPORT_GENERATED" and overlay
    inspect(source["constraint"], source["ownerBone"], overlay.get("bindingContext", {}) if generated else document.get("sourceContext", {}), excluded, "生成源" if generated else "作者态")
    if overlay:
        final_excluded = excluded | {row["exportBone"] for row in overlay.get("boneMap", ())
                                     if row["sourceBone"] in excluded}
        change = next((row for row in overlay.get("constraintMap", ()) if row["sourceId"] == source["sourceId"]), {})
        constraint = dict(source["constraint"])
        constraint.update({key: change[key] for key in ("targetObjectName", "targetBoneName", "references") if key in change})
        inspect(constraint, change.get("ownerBone", source["ownerBone"]), overlay.get("bindingContext", {}), final_excluded, "最终绑定")
    return reasons
