"""Read-only access to the one authoritative ordinary-rig registry.

Unity distributes this exact JSON file. Its manifest is a SHA256 of the actual
file bytes, including whitespace and the final newline, not reserialized JSON.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("registry.v1.json")


def _read_authority():
    raw = REGISTRY_PATH.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    _validate_registry(data)
    return data, hashlib.sha256(raw).hexdigest()


def _validate_registry(data):
    if not isinstance(data, dict) or data.get("id") != "hotools.rig-constraints.registry" or type(data.get("version")) is not int:
        raise ValueError("invalid ordinary-rig registry identity")
    if data["version"] < 1:
        raise ValueError("invalid registry version")
    for key in ("constraintTypes", "semanticDefinitions", "implementations"):
        if not isinstance(data.get(key), list):
            raise ValueError("registry requires an array: " + key)
    types, semantics, identities = set(), set(), set()
    for row in data["constraintTypes"]:
        if not isinstance(row, dict) or not isinstance(row.get("type"), str) or not row["type"]:
            raise ValueError("invalid constraint type record")
        if row["type"] in types:
            raise ValueError("duplicate registry constraint type")
        types.add(row["type"])
        if not isinstance(row.get("ownerKinds"), list) or not row["ownerKinds"] or any(value not in ("OBJECT", "BONE") for value in row["ownerKinds"]):
            raise ValueError("invalid owner kinds")
        if not isinstance(row.get("semanticTypes"), list) or row.get("translationStatus") not in ("DIRECT", "GROUP_ONLY", "UNKNOWN"):
            raise ValueError("invalid type semantic catalog")
        if not isinstance(row.get("blenderVersions"), list) or not row["blenderVersions"] or any(value not in data.get("blenderCatalogVersions", ()) for value in row["blenderVersions"]):
            raise ValueError("constraint type must declare observed Blender versions")
    for row in data["semanticDefinitions"]:
        if not isinstance(row, dict) or not isinstance(row.get("type"), str) or type(row.get("version")) is not int or row["version"] < 1:
            raise ValueError("invalid semantic definition")
        identity = (row["type"], row["version"])
        if identity in semantics:
            raise ValueError("duplicate semantic definition")
        semantics.add(identity)
        if not isinstance(row.get("sourceConstraintTypes"), list) or any(value not in types for value in row["sourceConstraintTypes"]):
            raise ValueError("semantic definition references an unknown source type")
        members = row.get("members")
        if not isinstance(members, list) or not members:
            raise ValueError("semantic definition needs ordered member specifications")
        roles = set()
        for member in members:
            if not isinstance(member, dict) or member.get("constraintType") not in types or not isinstance(member.get("role"), str) or not member["role"]:
                raise ValueError("invalid semantic member specification")
            if member["role"] in roles:
                raise ValueError("duplicate semantic member role")
            roles.add(member["role"])
        if [member["constraintType"] for member in members] != row["sourceConstraintTypes"]:
            raise ValueError("semantic members and source type signature disagree")
    for row in data["constraintTypes"]:
        if any(not any(identity[0] == value for identity in semantics) for value in row["semanticTypes"]):
            raise ValueError("type catalog references an unknown semantic definition")
    for row in data["implementations"]:
        required = ("id", "contractVersion", "semanticType", "semanticVersion", "backendId", "conditions", "availability", "fidelity", "verification", "artifacts", "testSuites")
        if not isinstance(row, dict) or any(key not in row for key in required):
            raise ValueError("implementation is missing required fields")
        if not isinstance(row["id"], str) or not row["id"] or "@" in row["id"] or type(row["contractVersion"]) is not int or row["contractVersion"] < 1:
            raise ValueError("invalid implementation identity")
        identity = (row["id"], row["contractVersion"])
        if identity in identities:
            raise ValueError("duplicate implementation contract")
        identities.add(identity)
        if row["backendId"] not in ("Standard", "HoAux", "Vrc") or not row["id"].startswith(row["backendId"].lower() + "."):
            raise ValueError("implementation backend mismatch")
        if type(row["semanticVersion"]) is not int or (row["semanticType"], row["semanticVersion"]) not in semantics:
            raise ValueError("implementation references an unknown semantic version")
        if not isinstance(row["conditions"], dict) or not isinstance(row["verification"], dict):
            raise ValueError("implementation conditions/verification must be objects")
        if row["availability"] not in ("IMPLEMENTED", "PLANNED", "DISABLED"):
            raise ValueError("unknown implementation availability")
        if row["fidelity"] not in ("EXACT", "CONDITIONAL", "APPROXIMATE", "LEGACY", "UNSPECIFIED"):
            raise ValueError("unknown implementation fidelity")
        if row["verification"].get("status") not in ("TESTED", "LEGACY_EVIDENCE", "SHIM_ONLY", "UNTESTED", "FAILED"):
            raise ValueError("unknown verification status")
        if row["availability"] == "PLANNED" and row["verification"].get("status") == "TESTED":
            raise ValueError("a planned implementation cannot be marked tested")
        for key in ("artifacts", "testSuites"):
            if not isinstance(row[key], list) or any(not isinstance(value, str) for value in row[key]):
                raise ValueError("implementation list is invalid: " + key)


def load_registry():
    """Return a fresh dictionary; callers cannot mutate a shared registry."""
    return _read_authority()[0]


def registry_manifest():
    data, digest = _read_authority()
    return {"id": data["id"], "version": data["version"], "sha256": digest}


def find_implementation(id, version):
    """Return one exact identity/version or None; never choose a fallback."""
    if not isinstance(id, str) or type(version) is not int:
        return None
    return next((deepcopy(row) for row in load_registry()["implementations"]
                 if row["id"] == id and row["contractVersion"] == version), None)


def implementations_for(semantic_type, backend=None):
    """List catalog candidates, including planned entries, without selection."""
    return [row for row in load_registry()["implementations"]
            if row["semanticType"] == semantic_type and (backend is None or row["backendId"] == backend)]


def generate_coverage(registry=None):
    """Render the checked-in coverage document from authority data only."""
    data = load_registry() if registry is None else registry
    _validate_registry(data)
    rows = data["constraintTypes"]
    implementations = data["implementations"]
    direct = sum(row["translationStatus"] == "DIRECT" for row in rows)
    grouped = sum(row["translationStatus"] == "GROUP_ONLY" for row in rows)
    unknown = sum(row["translationStatus"] == "UNKNOWN" for row in rows)
    implemented = sum(row["availability"] == "IMPLEMENTED" for row in implementations)
    planned = sum(row["availability"] == "PLANNED" for row in implementations)
    lines = [
        "# Ordinary Rig Constraint coverage", "",
        "Generated from `registry/registry.v1.json`; regenerate with `python -m RigConstraints.registry --write`.", "",
        "The table registers capabilities; it is not a claim that all parameters of a Blender type are executable.", "",
        "## Catalog progress", "",
        "- Blender baseline: {}.".format(", ".join(data["blenderCatalogVersions"])),
        "- Constraint types: {}; direct semantics: {}; group-only members: {}; UnknownSemantic: {}.".format(len(rows), direct, grouped, unknown),
        "- Semantic definitions: {}; implementation contracts: {}; implemented legacy/current paths: {}; planned: {}.".format(len(data["semanticDefinitions"]), len(implementations), implemented, planned),
        "- Full-type completion, parameter-domain completion and real SDK validation are deliberately not conflated.", "",
        "copyR requires explicit generated/adopted ownership metadata. A manually authored raw Copy Rotation remains a source fact and is not guessed into copyR; v2/v3 retain their compatibility interpretation.", "",
        "## Three parallel columns", "",
        "| Blender source type | Blender versions | Admitted owners | Semantic translation | Unity implementation references |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        semantic_names = row["semanticTypes"]
        translation = ", ".join(semantic_names) if semantic_names else "UnknownSemantic"
        if row.get("registrationRequired"):
            translation += " (explicit copyR registration required)"
        elif row["translationStatus"] == "GROUP_ONLY":
            translation += " (registered group only)"
        references = [item["id"] + "@" + str(item["contractVersion"]) for item in implementations if item["semanticType"] in semantic_names]
        lines.append("| `{}` | {} | {} | {} | {} |".format(row["type"], ", ".join(row["blenderVersions"]), ", ".join(row["ownerKinds"]), translation, "<br>".join(references) or "None"))
    lines += ["", "## Ordered semantic member contracts", "",
              "The scanner reads these member specs from the registry; it must not maintain a second hardcoded signature table.", "",
              "| Semantic | Ordered source type / role | Rule | Writes |",
              "| --- | --- | --- | --- |"]
    for row in data["semanticDefinitions"]:
        members = ", ".join("{} / {}".format(member["constraintType"], member["role"]) for member in row["members"])
        lines.append("| {}@{} | {} | {} | {} |".format(row["type"], row["version"], members, ", ".join(row["ruleIds"]), ", ".join(row["writeChannels"])))
    lines += ["", "## Versioned implementation contracts", "",
              "Exact/conditional/approximate is a contract declaration. Verification evidence is a separate column.", "",
              "| Implementation | Semantic | Backend | Availability | Fidelity | Verification | Test suite |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in implementations:
        lines.append("| `{}@{}` | {}@{} | {} | {} | {} | {} | {} |".format(
            row["id"], row["contractVersion"], row["semanticType"], row["semanticVersion"], row["backendId"],
            row["availability"], row["fidelity"], row["verification"]["status"], ", ".join(row["testSuites"])))
    lines += ["", "## Evidence and boundaries", "",
              "- " + data["catalogEvidence"]["baseline"],
              "- " + data["catalogEvidence"]["ownerKindsMeaning"],
              "- Source facts and unknown fields remain intact even when no semantic or implementation exists.",
              "- Candidate contracts are not permission to execute. Validate conditions, binding context and host capabilities first.",
              "- Local and Owner Orientation Copy Rotation contracts remain PLANNED until Unity numerical acceptance passes.",
              "- VRC SHIM_ONLY evidence covers API/serialization paths, not real SDK/client numerical equivalence.",
              "- LEGACY/LEGACY_EVIDENCE preserves existing behavior and does not certify all Blender parameter combinations.",
              "- Standard non-half rotation influence and native Armature mapping retain their explicit interpolation/rigid-approximation limits."]
    for version, difference in data["catalogEvidence"].get("additionalObservedVersions", {}).items():
        lines.append("- Blender {} adds {}; cataloged with per-type version applicability and still UnknownSemantic.".format(version, ", ".join(difference.get("addedTypes", [])) or "no new types"))
    lines += ["", "## Public pure-Python API", "",
              "- `model.new_document(armature_name, blender_version='', capture_stage='AUTHORING')` creates a mutable v4 dictionary with no fabricated final FBX binding overlay.",
              "- `codec.dumps(document, indent=2)` validates, refreshes inputFingerprint in a copy and preserves unknown fields; it never mutates the caller.",
              "- `codec.loads(text, verify_fingerprint=True)` rejects malformed v4, duplicate JSON keys, non-finite numbers and stale fingerprints. It preserves unknown source/semantic types and extension fields.",
              "- `codec.fingerprint(document)` hashes compact sorted UTF-8 JSON with ensure_ascii=False, sort_keys=True, separators=(',', ':') and no numeric rounding. Only root exportTime and inputFingerprint are excluded; arrays retain order.",
              "- `validation.schema.validate_document(document)` returns dictionaries containing code, path and message. It validates structure/references without scanning a scene or selecting a backend implementation.",
              "- `registry.load_registry()` returns a fresh parsed copy. `registry.registry_manifest()` returns id, version and SHA256 of the authority JSON's actual UTF-8 file bytes, including whitespace/newline.",
              "- `registry.find_implementation(id, version)` uses an exact pair and returns None on mismatch. `registry.implementations_for(semantic_type, backend=None)` includes planned entries and does not grant execution permission.",
              "- `python -m RigConstraints.registry --check` verifies this generated document has not drifted.", "",
              "Registry conditions are declarative data. ownerSpaces/targetSpaces are independent; copyRotation.spacePairs are ordered target/source space first, owner space second. Every current implementation requires BONE owners; OBJECT facts remain representable without being executable.",
              "", "Fingerprint golden canonical payload:", "",
              '`{"a":1.0,"nested":{"exportTime":"kept"},"z":"裙子"}`',
              "", "Its SHA256 is `" + hashlib.sha256('{"a":1.0,"nested":{"exportTime":"kept"},"z":"裙子"}'.encode("utf-8")).hexdigest() + "`. The registry file hash follows a separate raw-byte rule."]
    return "\n".join(lines) + "\n"


__all__ = ["REGISTRY_PATH", "load_registry", "registry_manifest", "find_implementation", "implementations_for", "generate_coverage"]
