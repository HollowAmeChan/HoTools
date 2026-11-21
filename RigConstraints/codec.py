"""Standard-library JSON codec and deterministic input fingerprints.

The registry manifest hashes the authority file's *actual UTF-8 bytes* instead;
that intentionally differs from this input-document canonicalization.
"""

from copy import deepcopy
import hashlib
import json


def _reject_constant(value):
    raise ValueError("non-finite JSON number: " + value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _validate(document):
    from .validation.schema import validate_document
    diagnostics = validate_document(document)
    if diagnostics:
        first = diagnostics[0]
        raise ValueError("{code} at {path}: {message}".format(**first))


def fingerprint(document):
    """SHA256 of sorted, compact UTF-8 JSON, excluding two root-only keys.

    Array order, extension fields, Unicode and the distinction between integer
    and floating-point JSON numbers are retained. No numeric rounding occurs.
    Nested fields called exportTime/inputFingerprint are meaningful payload.
    """
    if not isinstance(document, dict):
        raise ValueError("document must be an object")
    payload = {key: value for key, value in document.items()
               if key not in ("exportTime", "inputFingerprint")}
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, UnicodeError) as error:
        raise ValueError("document is not JSON-compatible") from error
    return hashlib.sha256(encoded).hexdigest()


def dumps(document, *, indent=2):
    """Validate and serialize a copy, refreshing its inputFingerprint.

    The caller's mutable authoring dictionary is never modified. Every unknown
    JSON field is retained. This function does not select an implementation.
    """
    value = deepcopy(document)
    if not isinstance(value, dict):
        raise ValueError("document must be an object")
    value["inputFingerprint"] = fingerprint(value)
    _validate(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      allow_nan=False, indent=indent)


def loads(value, *, verify_fingerprint=True):
    """Parse v4 losslessly; malformed structure and stale input hashes fail."""
    try:
        document = json.loads(value, object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
    except (TypeError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid JSON document") from error
    _validate(document)
    if verify_fingerprint and document["inputFingerprint"] != fingerprint(document):
        raise ValueError("inputFingerprint does not match document inputs")
    return document
