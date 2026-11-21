"""Non-mutating structural validation for v4, not scene/capability validation."""

from datetime import datetime
import math
import re

from ..model import BACKENDS, CAPTURE_STAGES, EVIDENCE_KINDS, SCHEMA, SCHEMA_VERSION

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def validate_document(document):
    """Return JSON diagnostics (code/path/message), preserving all input data.

    Unrecognized source types, semantic types and implementation IDs are valid
    facts. The planner, not this structural reader, decides their capability.
    Candidate realizations may overlap; locked executions must not consume a
    source twice on the same backend.
    """
    errors = []

    def report(code, path, message):
        errors.append({"code": code, "path": path, "message": message})

    def obj(value, path):
        if not isinstance(value, dict):
            report("INVALID_STRUCTURE", path, "expected an object")
            return False
        return True

    def field(container, key, expected, path, *, nonempty=False, minimum=None,
              choices=None, optional=False):
        location = path + "." + key
        if key not in container:
            if not optional:
                report("MISSING_FIELD", location, "required field is missing")
            return None
        value = container[key]
        valid = isinstance(value, expected)
        if expected is int:
            valid = type(value) is int
        if not valid:
            report("INVALID_STRUCTURE", location, "expected " + expected.__name__)
            return None
        if nonempty and not value:
            report("INVALID_VALUE", location, "must not be empty")
        if minimum is not None and value < minimum:
            report("INVALID_VALUE", location, "must be >= " + str(minimum))
        if choices is not None and value not in choices:
            report("INVALID_VALUE", location, "value is not permitted by v4")
        return value

    def json_value(value, path, ancestors):
        if value is None or type(value) in (str, bool, int):
            if isinstance(value, str):
                try:
                    value.encode("utf-8")
                except UnicodeError:
                    report("INVALID_JSON", path, "string is not valid UTF-8")
            return
        if type(value) is float:
            if not math.isfinite(value):
                report("INVALID_JSON", path, "non-finite number")
            return
        if not isinstance(value, (dict, list)):
            report("INVALID_JSON", path, "value is not a JSON primitive/object/array")
            return
        if id(value) in ancestors:
            report("INVALID_JSON", path, "cyclic Python container")
            return
        seen = ancestors | {id(value)}
        items = value.items() if isinstance(value, dict) else enumerate(value)
        for key, child in items:
            if isinstance(value, dict) and not isinstance(key, str):
                report("INVALID_JSON", path, "object keys must be strings")
                continue
            json_value(child, path + "." + str(key), seen)

    json_value(document, "$", set())
    if not obj(document, "$"):
        return errors
    schema = field(document, "schema", str, "$")
    version = field(document, "schemaVersion", int, "$")
    if schema is not None and schema != SCHEMA:
        report("UNSUPPORTED_SCHEMA", "$.schema", "not the rig-constraint schema")
    if version is not None and version != SCHEMA_VERSION:
        report("UNSUPPORTED_VERSION", "$.schemaVersion", "expected schemaVersion 4")
    field(document, "armatureName", str, "$", nonempty=True)
    field(document, "blenderVersion", str, "$")
    field(document, "captureStage", str, "$", choices=CAPTURE_STAGES)
    timestamp = field(document, "exportTime", str, "$")
    if timestamp is not None:
        try:
            if not timestamp.endswith("Z") or datetime.fromisoformat(timestamp[:-1] + "+00:00").utcoffset().total_seconds() != 0:
                raise ValueError()
        except (ValueError, AttributeError):
            report("INVALID_VALUE", "$.exportTime", "expected RFC3339 UTC ending in Z")
    input_hash = field(document, "inputFingerprint", str, "$")
    if input_hash is not None and not _SHA256.fullmatch(input_hash):
        report("INVALID_VALUE", "$.inputFingerprint", "expected lowercase SHA256 hex")
    manifest = field(document, "registry", dict, "$")
    if manifest is not None:
        field(manifest, "id", str, "$.registry", nonempty=True)
        field(manifest, "version", int, "$.registry", minimum=1)
        digest = field(manifest, "sha256", str, "$.registry")
        if digest is not None and not _SHA256.fullmatch(digest):
            report("INVALID_VALUE", "$.registry.sha256", "expected lowercase SHA256 hex")
    field(document, "sourceContext", dict, "$", optional=True)
    sources = field(document, "sources", list, "$") or []
    semantics = field(document, "semantics", list, "$") or []
    implementations = field(document, "implementationBindings", list, "$") or []
    source_ids, source_slots, semantic_ids = set(), set(), set()
    semantic_sources = {}

    for index, source in enumerate(sources):
        path = "$.sources[{}]".format(index)
        if not obj(source, path):
            continue
        source_id = field(source, "sourceId", str, path, nonempty=True)
        owner = field(source, "ownerBone", str, path, nonempty=True)
        owner_kind = field(source, "ownerKind", str, path, choices=("BONE", "OBJECT"))
        stage = field(source, "captureStage", str, path, choices=CAPTURE_STAGES)
        if source_id is not None:
            if source_id in source_ids:
                report("DUPLICATE_ID", path + ".sourceId", "duplicate sourceId")
            source_ids.add(source_id)
        constraint = field(source, "constraint", dict, path)
        if constraint is None:
            continue
        cpath = path + ".constraint"
        stack = field(constraint, "stackIndex", int, cpath, minimum=0)
        field(constraint, "name", str, cpath)
        field(constraint, "constraintType", str, cpath, nonempty=True)
        field(constraint, "targetObjectName", str, cpath)
        field(constraint, "targetBoneName", str, cpath)
        field(constraint, "parameters", dict, cpath)
        field(constraint, "references", dict, cpath)
        slot = (owner_kind, owner, stage, stack)
        if None not in slot:
            if slot in source_slots:
                report("DUPLICATE_SOURCE", cpath + ".stackIndex", "duplicate owner/stage/stack slot")
            source_slots.add(slot)

    for index, semantic in enumerate(semantics):
        path = "$.semantics[{}]".format(index)
        if not obj(semantic, path):
            continue
        semantic_id = field(semantic, "semanticId", str, path, nonempty=True)
        if semantic_id is not None:
            if semantic_id in semantic_ids:
                report("DUPLICATE_ID", path + ".semanticId", "duplicate semanticId")
            semantic_ids.add(semantic_id)
        field(semantic, "semanticType", str, path, nonempty=True)
        field(semantic, "semanticVersion", int, path, minimum=1)
        field(semantic, "ownerBone", str, path, nonempty=True)
        field(semantic, "ruleId", str, path, nonempty=True)
        field(semantic, "ruleVersion", int, path, minimum=1)
        field(semantic, "evidence", str, path, choices=EVIDENCE_KINDS)
        field(semantic, "parameters", dict, path)
        references = field(semantic, "sourceIds", list, path, nonempty=True) or []
        unique = set()
        for position, reference in enumerate(references):
            rpath = path + ".sourceIds[{}]".format(position)
            if not isinstance(reference, str) or not reference:
                report("INVALID_STRUCTURE", rpath, "expected a nonempty sourceId")
                continue
            if reference in unique:
                report("DUPLICATE_REFERENCE", rpath, "source referenced twice by one semantic")
            unique.add(reference)
            if reference not in source_ids:
                report("DANGLING_REFERENCE", rpath, "sourceId does not exist")
        if semantic_id is not None:
            semantic_sources[semantic_id] = unique

    identities, locked, consumed = set(), set(), {}
    for index, implementation in enumerate(implementations):
        path = "$.implementationBindings[{}]".format(index)
        if not obj(implementation, path):
            continue
        semantic_id = field(implementation, "semanticId", str, path, nonempty=True)
        backend = field(implementation, "backendId", str, path, choices=BACKENDS)
        implementation_id = field(implementation, "implementationId", str, path, nonempty=True)
        contract = field(implementation, "contractVersion", int, path, minimum=1)
        selection = field(implementation, "selection", str, path, choices=("CANDIDATE", "LOCKED"))
        field(implementation, "fallbackPolicy", str, path, nonempty=True)
        if semantic_id is not None and semantic_id not in semantic_ids:
            report("DANGLING_REFERENCE", path + ".semanticId", "semanticId does not exist")
        identity = (semantic_id, backend, implementation_id, contract)
        if None not in identity:
            if identity in identities:
                report("DUPLICATE_BINDING", path, "duplicate implementation binding")
            identities.add(identity)
        if selection == "LOCKED" and semantic_id is not None and backend is not None:
            pair = (semantic_id, backend)
            if pair in locked:
                report("MULTIPLE_LOCKED", path, "at most one locked implementation per semantic/backend")
            locked.add(pair)
            for source_id in semantic_sources.get(semantic_id, ()):
                key = (backend, source_id)
                if key in consumed and consumed[key] != semantic_id:
                    report("OVERLAPPING_EXECUTION", path, "locked semantics consume the same source")
                consumed[key] = semantic_id

    overlay = field(document, "bindings", dict, "$", optional=True)
    if overlay is not None:
        field(overlay, "captureStage", str, "$.bindings", choices=("POSTPROCESS",))
        field(overlay, "bindingContext", dict, "$.bindings")
        bone_map = field(overlay, "boneMap", list, "$.bindings") or []
        constraint_map = field(overlay, "constraintMap", list, "$.bindings") or []
        seen_bones, seen_constraints = set(), set()
        for index, mapping in enumerate(bone_map):
            path = "$.bindings.boneMap[{}]".format(index)
            if not obj(mapping, path):
                continue
            source_bone = field(mapping, "sourceBone", str, path, nonempty=True)
            field(mapping, "exportBone", str, path, nonempty=True)
            if source_bone is not None:
                if source_bone in seen_bones:
                    report("DUPLICATE_BINDING", path, "duplicate sourceBone mapping")
                seen_bones.add(source_bone)
        for index, mapping in enumerate(constraint_map):
            path = "$.bindings.constraintMap[{}]".format(index)
            if not obj(mapping, path):
                continue
            source_id = field(mapping, "sourceId", str, path, nonempty=True)
            if source_id is not None:
                if source_id not in source_ids:
                    report("DANGLING_REFERENCE", path + ".sourceId", "sourceId does not exist")
                if source_id in seen_constraints:
                    report("DUPLICATE_BINDING", path, "duplicate source constraint mapping")
                seen_constraints.add(source_id)
            for key in ("ownerBone", "targetObjectName", "targetBoneName"):
                field(mapping, key, str, path, optional=True)
            field(mapping, "stackIndex", int, path, minimum=0, optional=True)
            field(mapping, "references", dict, path, optional=True)
    return errors
