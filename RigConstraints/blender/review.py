"""Explicit read-only reviews; no handlers, persistent snapshots or auto repair."""

from datetime import datetime

_cache = {}


def _key(value):
    pointer = getattr(value, "as_pointer", None)
    return pointer() if callable(pointer) else id(value)


def invalidate(value):
    """Accept an Object or shared Armature datablock, including deleted owners."""
    key = _key(value)
    shared_data = getattr(value, "data", None)
    data_key = _key(shared_data) if shared_data is not None else key
    for object_key, report in list(_cache.items()):
        if key == object_key or data_key == report["dataKey"]:
            del _cache[object_key]


def clear_cache():
    _cache.clear()


def cached(armature):
    return _cache.get(_key(armature))


def scan(armature):
    from ..source import capture_armature
    from ..semantics import translate
    doc = translate(capture_armature(armature))
    by_id = {s["sourceId"]: s for s in doc["sources"]}
    known = []
    for semantic in doc["semantics"]:
        known.append({"ownerBone": semantic["ownerBone"], "label": semantic["semanticType"],
            "message": " + ".join(by_id[s]["constraint"]["name"] for s in semantic["sourceIds"]),
            "sourceIds": list(semantic["sourceIds"]), "semanticId": semantic["semanticId"]})
    broken = [d for d in doc["diagnostics"] if d["status"] == "BROKEN"]
    unknown = [d for d in doc["diagnostics"] if d["status"] == "UNKNOWN"]
    report = {"dataKey": _key(armature.data), "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "known": known, "broken": broken, "unknown": unknown, "document": doc,
        "excludedCount": len(doc["excludedOwners"]), "mchPlans": doc["mchPlans"]}
    _cache[_key(armature)] = report
    return report
