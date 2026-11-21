"""Translate declared groups and admitted direct facts, retaining every source."""

from copy import deepcopy
from ..codec import fingerprint
from ..registry import load_registry, implementations_for
from .groups import inspect_group, source_reference_reasons


def translate(document):
    doc = deepcopy(document)
    doc["semantics"], doc["implementationBindings"], doc["diagnostics"] = [], [], []
    sources = {s["sourceId"]: s for s in doc["sources"]}
    declarations = doc.get("declarations", ())
    declared, consumed = set(), set()
    memberships = {}
    group_counts, generator_counts = {}, {}
    for group in declarations:
        key = (group["ownerBone"], group["groupId"])
        group_counts[key] = group_counts.get(key, 0) + 1
        generator = (group["ownerBone"], group["semanticType"], group.get("generatorId", ""))
        generator_counts[generator] = generator_counts.get(generator, 0) + 1
        for sid in group.get("memberSourceIds", ()):
            if sid:
                memberships.setdefault(sid, []).append(group)
                declared.add(sid)
    for group in declarations:
        resolved, reasons = inspect_group(group, doc)
        if not group.get("groupId") or group_counts[(group["ownerBone"], group["groupId"])] > 1:
            reasons.append("语义组 ID 缺失或重复")
        if generator_counts[(group["ownerBone"], group["semanticType"], group.get("generatorId", ""))] > 1:
            reasons.append("同一生成来源的语义组重复")
        for s in resolved:
            reasons += source_reference_reasons(s, doc)
            if len(memberships[s["sourceId"]]) > 1:
                reasons.append("同一约束被多个语义组认领")
        if reasons:
            doc["diagnostics"].append({"status": "BROKEN", "ownerBone": group["ownerBone"],
                "groupId": group["groupId"], "label": group["semanticType"], "sourceIds": group.get("memberSourceIds", []),
                "message": "；".join(dict.fromkeys(reasons))})
            continue
        parameters = {"sourceBones": group.get("sourceBones", []), "auxType": group.get("auxType", ""),
                      "groupId": group["groupId"], "generatorId": group.get("generatorId", ""),
                      "ownsBone": group.get("ownsBone", False)}
        if group["semanticType"] == "AIM":
            a, u = [s["constraint"] for s in resolved]
            parameters.update(targetBone=a["targetBoneName"], upBone=u["targetBoneName"],
                aimAxis=a["parameters"]["track_axis"], upAxis=u["parameters"]["track_axis"],
                upMode="OBJECT_POSITION", muted=a["parameters"].get("mute", False))
        kind = group["semanticType"]
        rule = "group.copy_r" if kind == "COPY_ROTATION" else "group." + kind.lower()
        _add(doc, kind, group["ownerBone"], [s["sourceId"] for s in resolved],
             rule, group.get("evidence", "LEGACY"), parameters)
        consumed.update(s["sourceId"] for s in resolved)
    catalog = {r["type"]: r for r in load_registry()["constraintTypes"]}
    for sid, source in sources.items():
        if sid in consumed or sid in declared:
            continue
        c, owner = source["constraint"], source["ownerBone"]
        problems = source_reference_reasons(source, doc)
        if problems:
            doc["diagnostics"].append({"status": "BROKEN", "ownerBone": owner, "label": c["name"], "sourceIds": [sid], "message": "；".join(problems)})
            continue
        row = catalog.get(c["constraintType"], {})
        # copyR is authored in the Aux tool. Raw manually-added Copy Rotation
        # remains a source fact; it is never adopted or repaired on export.
        if (source["ownerKind"] == "BONE" and row.get("translationStatus") == "DIRECT"
                and c["constraintType"] != "COPY_ROTATION"):
            _add(doc, c["constraintType"], owner, [sid], "direct." + c["constraintType"].lower(), "RAW_TYPE", {})
        else:
            doc["diagnostics"].append({"status": "UNKNOWN", "ownerBone": owner, "label": c["name"], "sourceIds": [sid],
                "message": "未登记 copyR；请使用 Ho 基础辅助骨 copyR 入口" if c["constraintType"] == "COPY_ROTATION" else "尚无适用的语义翻译"})
    doc["inputFingerprint"] = fingerprint(doc)
    return doc


def _add(doc, kind, owner, source_ids, rule, evidence, parameters):
    sid = "s" + str(len(doc["semantics"]))
    doc["semantics"].append({"semanticId": sid, "semanticType": kind, "semanticVersion": 1,
        "ownerBone": owner, "sourceIds": source_ids, "ruleId": rule, "ruleVersion": 1,
        "evidence": evidence, "parameters": parameters})
    for implementation in implementations_for(kind):
        doc["implementationBindings"].append({"semanticId": sid, "backendId": implementation["backendId"],
            "implementationId": implementation["id"], "contractVersion": implementation["contractVersion"],
            "selection": "CANDIDATE", "fallbackPolicy": "ALLOW_LEGACY" if implementation["fidelity"] == "LEGACY" else "EXACT_ONLY"})
