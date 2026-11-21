"""Keep authoring facts immutable while binding final exported constraints.

Constraint identity is owner kind, owner name and owner-local name plus an
explicit type check. Stack positions are outputs of matching, never a fallback
identity. No object/bone/constraint is modified by this module.
"""

from copy import deepcopy

from ..codec import fingerprint
from ..semantics import translate
from ..source import capture_armature


def _identity(source):
    return source["ownerKind"], source["ownerBone"], source["constraint"]["name"]


def _index_sources(sources, label):
    result = {}
    for source in sources:
        key = _identity(source)
        if key in result:
            raise ValueError("{}约束身份重复：{} / {}".format(label, key[1], key[2]))
        result[key] = source
    return result


def _mapping(source_id, final):
    constraint = final["constraint"]
    return {
        "sourceId": source_id,
        "ownerKind": final["ownerKind"],
        "ownerBone": final["ownerBone"],
        "constraintName": constraint["name"],
        "constraintType": constraint["constraintType"],
        "stackIndex": constraint["stackIndex"],
        "targetObjectName": constraint["targetObjectName"],
        "targetBoneName": constraint["targetBoneName"],
        "references": deepcopy(constraint["references"]),
    }


def build_export_document(authoring_document, armature, *, mch_map=None):
    """Bind an AUTHORING snapshot to the final armature without rewriting facts.

    Only registered MCH members belonging to this preprocessing map may appear
    as new EXPORT_GENERATED facts. Unexpected additions, missing original names,
    or same-name type changes abort instead of reattaching by stack position.
    """
    if authoring_document.get("captureStage") != "AUTHORING":
        raise ValueError("导出绑定需要预处理前的 AUTHORING 快照")
    if authoring_document.get("armatureName") != getattr(armature, "name", None):
        raise ValueError("作者快照与最终骨架身份不一致")
    document = deepcopy(authoring_document)
    final = capture_armature(armature, capture_stage="POSTPROCESS")
    original = _index_sources(document["sources"], "作者态")
    final_sources = _index_sources(final["sources"], "最终导出")
    source_bones = {row["boneName"] for row in document.get("sourceContext", {}).get("bones", ())}
    final_bones = {row["boneName"] for row in final["sourceContext"].get("bones", ())}
    mch_map = dict(mch_map or {})
    if len(set(mch_map.values())) != len(mch_map):
        raise ValueError("MCH 骨映射必须一一对应")
    for source, exported in mch_map.items():
        if (not isinstance(source, str) or not isinstance(exported, str) or
                not source or not exported or source == exported or
                source not in source_bones or exported not in final_bones):
            raise ValueError("MCH 骨映射与作者态／最终绑定不一致：{} → {}".format(source, exported))

    constraint_map = []
    final_to_source = {}
    for key, source in original.items():
        matched = final_sources.get(key)
        if matched is None:
            raise ValueError("导出中原始约束缺失或改名：{} / {}；不按栈位置猜测".format(key[1], key[2]))
        if matched["constraint"]["constraintType"] != source["constraint"]["constraintType"]:
            raise ValueError("导出中同名约束类型改变：{} / {}".format(key[1], key[2]))
        final_to_source[matched["sourceId"]] = source["sourceId"]
        constraint_map.append(_mapping(source["sourceId"], matched))

    unmatched = [source for source in final["sources"] if _identity(source) not in original]
    unmatched_ids = {source["sourceId"] for source in unmatched}
    generated_owners = set(mch_map.values())
    generated_groups = []
    approved_ids = set()
    declared_mch_owners = set()
    for group in final.get("declarations", ()):
        if group["ownerBone"] not in generated_owners or group["semanticType"] != "MCH":
            continue
        if group["ownerBone"] in declared_mch_owners:
            raise ValueError("最终 MCH 语义登记重复：" + group["ownerBone"])
        declared_mch_owners.add(group["ownerBone"])
        member_ids = group.get("memberSourceIds", ())
        # Existing authoring MCH records are already represented; never append a
        # second copy of an authored member merely because its bone is mapped.
        if member_ids and all(sid in final_to_source for sid in member_ids):
            continue
        if (len(member_ids) != 1 or not member_ids[0] or
                member_ids[0] not in unmatched_ids or member_ids[0] in approved_ids):
            raise ValueError("最终 MCH 登记缺失、重复或混合作者态成员：" + group["ownerBone"])
        member = next(source for source in unmatched if source["sourceId"] == member_ids[0])
        constraint = member["constraint"]
        origin = next(name for name, exported in mch_map.items() if exported == group["ownerBone"])
        if (member["ownerKind"] != "BONE" or constraint["constraintType"] != "CHILD_OF" or
                constraint["targetObjectName"] != final["armatureName"] or
                constraint["targetBoneName"] != origin or group.get("sourceBones") != [origin]):
            raise ValueError("最终 MCH 绑定不匹配生成骨映射：" + group["ownerBone"])
        approved_ids.add(member_ids[0])
        generated_groups.append(group)
    if declared_mch_owners != generated_owners:
        missing = sorted(generated_owners - declared_mch_owners)
        raise ValueError("最终 MCH 骨缺少完整语义登记：" + ", ".join(missing))
    if unmatched_ids != approved_ids:
        unexpected = next(source for source in unmatched if source["sourceId"] not in approved_ids)
        raise ValueError("导出中出现未声明的新约束：{} / {}；仅接受已登记的生成 MCH".format(
            unexpected["ownerBone"], unexpected["constraint"]["name"]))

    existing_ids = {source["sourceId"] for source in document["sources"]}
    next_id = len(existing_ids)
    for source in unmatched:
        while "c" + str(next_id) in existing_ids:
            next_id += 1
        generated = deepcopy(source)
        generated["sourceId"] = "c" + str(next_id)
        generated["captureStage"] = "EXPORT_GENERATED"
        next_id += 1
        existing_ids.add(generated["sourceId"])
        final_to_source[source["sourceId"]] = generated["sourceId"]
        document["sources"].append(generated)
        constraint_map.append(_mapping(generated["sourceId"], source))

    declarations = document.setdefault("declarations", [])
    for group in generated_groups:
        transplanted = deepcopy(group)
        transplanted["captureStage"] = "EXPORT_GENERATED"
        transplanted["memberSourceIds"] = [final_to_source[sid] for sid in group["memberSourceIds"]]
        declarations.append(transplanted)

    final_context = deepcopy(final["sourceContext"])
    final_context["fbxBoneAxes"] = "Y_X"
    document["bindings"] = {
        "captureStage": "POSTPROCESS",
        "boneMap": [{"sourceBone": source, "exportBone": mch_map[source]} for source in sorted(mch_map)],
        "constraintMap": constraint_map,
        "bindingContext": final_context,
    }
    document = translate(document)
    generated_source_ids = {final_to_source[sid] for sid in approved_ids}
    for diagnostic in document["diagnostics"]:
        if diagnostic["status"] == "BROKEN" and generated_source_ids.intersection(diagnostic.get("sourceIds", ())):
            raise ValueError("生成 MCH 语义无效：" + diagnostic["message"])
    document["inputFingerprint"] = fingerprint(document)
    return document


def refresh_final_context(document, armature):
    """Refresh matrices after object correction, without re-reading removed facts.

    Constraint cleanup precedes object correction in HoFBX. Consumer analysis
    therefore keeps the earlier conservative full-matrix requirement rather
    than deciding a source became position-only just because consumers vanished.
    """
    from Exporter.ConstraintIRExporter import ConstraintIRExporter
    result = deepcopy(document)
    prior = {b["boneName"]: b for b in result["bindings"]["bindingContext"]["bones"]}
    context = ConstraintIRExporter._binding_context(armature, list(armature.data.bones))
    context["fbxBoneAxes"] = "Y_X"
    for bone in context["bones"]:
        old = prior.get(bone["boneName"])
        if old is not None:
            bone["positionOnly"] = old.get("positionOnly", False) and bone["positionOnly"]
            bone["hasPoseAnimation"] = old.get("hasPoseAnimation", False) or bone["hasPoseAnimation"]
    result["bindings"]["bindingContext"] = context
    result["inputFingerprint"] = fingerprint(result)
    return result
