"""Pure-standard-library acceptance for v4 source/semantic/contract data."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ADDON_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ADDON_ROOT))

from RigConstraints import codec, model, registry
from RigConstraints.validation.schema import validate_document


def source(source_id="c0", owner="Owner", stack=0):
    return {
        "sourceId": source_id, "ownerBone": owner, "ownerKind": "BONE",
        "captureStage": "AUTHORING",
        "constraint": {
            "stackIndex": stack, "name": "Copy Rotation", "constraintType": "COPY_ROTATION",
            "targetObjectName": "Rig", "targetBoneName": "Target",
            "parameters": {"owner_space": "WORLD", "target_space": "WORLD", "influence": .3},
            "references": {},
        },
    }


def semantic(semantic_id="s0", source_ids=None):
    return {
        "semanticId": semantic_id, "semanticType": "COPY_ROTATION", "semanticVersion": 1,
        "ownerBone": "Owner", "sourceIds": ["c0"] if source_ids is None else source_ids,
        "ruleId": "direct.copy_rotation", "ruleVersion": 1,
        "evidence": "RAW_TYPE", "parameters": {},
    }


def binding(semantic_id="s0", implementation_id="hoaux.copy_rotation.world", selection="CANDIDATE"):
    return {
        "semanticId": semantic_id, "backendId": "HoAux", "implementationId": implementation_id,
        "contractVersion": 1, "selection": selection, "fallbackPolicy": "EXACT_ONLY",
    }


def example():
    document = model.new_document("Rig", "4.5.8")
    document["sources"] = [source()]
    document["semantics"] = [semantic()]
    document["implementationBindings"] = [binding()]
    return document


class CodecTests(unittest.TestCase):
    def assert_code(self, document, code):
        diagnostics = validate_document(document)
        self.assertTrue(any(item["code"] == code for item in diagnostics), diagnostics)
        self.assertTrue(all(set(item) == {"code", "path", "message"} for item in diagnostics))

    def test_empty_authoring_snapshot_is_valid_and_has_no_final_bindings(self):
        document = model.new_document("裙子", "4.5.8")
        self.assertEqual([], validate_document(document))
        self.assertNotIn("bindings", document)
        self.assertEqual(document, codec.loads(codec.dumps(document)))

    def test_lossless_unknown_fields_and_types_at_every_layer(self):
        document = example()
        document["futureTop"] = {"名字": [True, None, -3, .125, "é/裙子"]}
        document["sources"][0]["futureSource"] = {"nested": "kept"}
        raw = document["sources"][0]["constraint"]
        raw["constraintType"] = "FUTURE_BLENDER_TYPE"
        raw["parameters"]["futureParameter"] = {"values": [1, 1.0, .03]}
        raw["references"]["futureCollection"] = [{"target": "外部骨架"}]
        raw["futureRaw"] = {"rnaExtension": "kept"}
        document["semantics"][0]["futureSemantic"] = [1, 2]
        document["implementationBindings"][0]["futurePlan"] = {"why": "kept"}
        document["semantics"][0]["semanticType"] = "FUTURE_SEMANTIC"
        document["implementationBindings"][0]["implementationId"] = "future.contract"
        before = deepcopy(document)
        actual = codec.loads(codec.dumps(document))
        self.assertEqual(before, document, "serialization must not mutate the caller")
        actual.pop("inputFingerprint")
        before.pop("inputFingerprint")
        self.assertEqual(before, actual)

    def test_unknown_source_without_any_semantic_is_valid(self):
        document = model.new_document("Rig")
        document["sources"] = [source()]
        document["sources"][0]["constraint"]["constraintType"] = "NOT_IMPLEMENTED"
        self.assertEqual([], validate_document(document))

    def test_fingerprint_excludes_only_root_volatile_fields(self):
        a = {"z": "裙子", "a": 1.0, "nested": {"exportTime": "kept"}, "exportTime": "ignored", "inputFingerprint": "ignored"}
        canonical = '{"a":1.0,"nested":{"exportTime":"kept"},"z":"裙子"}'
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self.assertEqual(expected, codec.fingerprint(a))
        b = {"nested": {"exportTime": "kept"}, "a": 1.0, "z": "裙子", "exportTime": "changed"}
        self.assertEqual(codec.fingerprint(a), codec.fingerprint(b))
        b["nested"]["exportTime"] = "changed"
        self.assertNotEqual(codec.fingerprint(a), codec.fingerprint(b))
        self.assertNotEqual(codec.fingerprint({"a": 1}), codec.fingerprint({"a": 1.0}))
        self.assertNotEqual(codec.fingerprint({"a": [1, 2]}), codec.fingerprint({"a": [2, 1]}))

    def test_input_tampering_is_detected_and_writer_refreshes_copy(self):
        text = codec.dumps(example())
        document = json.loads(text)
        document["sources"][0]["constraint"]["parameters"]["influence"] = .5
        with self.assertRaisesRegex(ValueError, "inputFingerprint"):
            codec.loads(json.dumps(document))
        self.assertEqual(.5, codec.loads(codec.dumps(document))["sources"][0]["constraint"]["parameters"]["influence"])

    def test_duplicate_json_keys_and_nonfinite_values_are_rejected(self):
        for value in ('{"schema":1,"schema":2}', '{"number":NaN}', '{"number":Infinity}'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                codec.loads(value)
        document = example()
        document["future"] = float("nan")
        self.assert_code(document, "INVALID_JSON")
        with self.assertRaises(ValueError):
            codec.dumps(document)

    def test_required_structure_and_future_schema_are_rejected(self):
        for key in ("sources", "semantics", "registry", "inputFingerprint"):
            document = example()
            del document[key]
            self.assert_code(document, "MISSING_FIELD")
        document = example()
        document["schemaVersion"] = 5
        self.assert_code(document, "UNSUPPORTED_VERSION")
        document["schemaVersion"] = True
        self.assert_code(document, "INVALID_STRUCTURE")
        document = example()
        document["sources"][0]["constraint"]["stackIndex"] = True
        self.assert_code(document, "INVALID_STRUCTURE")

    def test_bad_references_and_duplicate_identities_are_reported(self):
        document = example()
        document["semantics"][0]["sourceIds"] = ["missing"]
        self.assert_code(document, "DANGLING_REFERENCE")
        document = example()
        document["implementationBindings"][0]["semanticId"] = "missing"
        self.assert_code(document, "DANGLING_REFERENCE")
        document = example()
        document["sources"].append(deepcopy(document["sources"][0]))
        self.assert_code(document, "DUPLICATE_ID")
        self.assert_code(document, "DUPLICATE_SOURCE")
        document = example()
        document["semantics"].append(deepcopy(document["semantics"][0]))
        self.assert_code(document, "DUPLICATE_ID")
        document = example()
        document["implementationBindings"].append(deepcopy(document["implementationBindings"][0]))
        self.assert_code(document, "DUPLICATE_BINDING")

    def test_locked_realizations_are_exclusive_but_candidates_are_not(self):
        document = example()
        document["implementationBindings"].append(binding(implementation_id="hoaux.copy_rotation.local"))
        self.assertEqual([], validate_document(document))
        for item in document["implementationBindings"]:
            item["selection"] = "LOCKED"
        self.assert_code(document, "MULTIPLE_LOCKED")
        document = example()
        document["semantics"].append(semantic("s1"))
        document["implementationBindings"] = [binding(selection="LOCKED"), binding("s1", selection="LOCKED")]
        self.assert_code(document, "OVERLAPPING_EXECUTION")

    def test_binding_overlay_preserves_authoring_facts(self):
        document = example()
        document["bindings"] = {
            "captureStage": "POSTPROCESS", "boneMap": [{"sourceBone": "Target", "exportBone": "MCH_Target"}],
            "constraintMap": [{"sourceId": "c0", "targetBoneName": "MCH_Target", "references": {"futureFinalReference": "kept"}}],
            "bindingContext": {"futureContext": [1, 2]}, "futureOverlay": {"kept": True},
        }
        actual = codec.loads(codec.dumps(document))
        self.assertEqual("Target", actual["sources"][0]["constraint"]["targetBoneName"])
        self.assertEqual("MCH_Target", actual["bindings"]["constraintMap"][0]["targetBoneName"])
        document["bindings"]["constraintMap"][0]["sourceId"] = "missing"
        self.assert_code(document, "DANGLING_REFERENCE")

    def test_python_non_json_values_are_diagnostics_not_mutations(self):
        for invalid in (object(), (1, 2), {1: "bad key"}, float("inf")):
            document = example()
            document["future"] = invalid
            self.assert_code(document, "INVALID_JSON")


class RegistryTests(unittest.TestCase):
    def test_ordered_member_specs_are_authoritative_for_all_semantics(self):
        semantics = {row["type"]: row for row in registry.load_registry()["semanticDefinitions"]}
        for row in semantics.values():
            self.assertEqual(row["sourceConstraintTypes"], [member["constraintType"] for member in row["members"]])
        self.assertEqual([{"constraintType": "DAMPED_TRACK", "role": "aim"}, {"constraintType": "LOCKED_TRACK", "role": "up"}], semantics["AIM"]["members"])
        self.assertEqual(["rotation", "stretch"], [member["role"] for member in semantics["TWIST"]["members"]])

    def test_manifest_hashes_the_actual_authority_bytes(self):
        raw = registry.REGISTRY_PATH.read_bytes()
        expected = hashlib.sha256(raw).hexdigest()
        self.assertEqual(expected, registry.registry_manifest()["sha256"])
        self.assertEqual("hotools.rig-constraints.registry", registry.registry_manifest()["id"])

    def test_versioned_catalog_covers_observed_rna_domains(self):
        data = registry.load_registry()
        rows = {row["type"]: row for row in data["constraintTypes"]}
        self.assertEqual(29, len(rows))
        self.assertEqual(28, sum("4.5.8" in row["blenderVersions"] for row in rows.values()))
        self.assertEqual(29, sum("5.2.0" in row["blenderVersions"] for row in rows.values()))
        self.assertEqual(["BONE"], rows["IK"]["ownerKinds"])
        self.assertEqual(["BONE"], rows["SPLINE_IK"]["ownerKinds"])
        self.assertEqual("5.2", rows["GEOMETRY_ATTRIBUTE"]["since"])
        self.assertEqual("UNKNOWN", rows["GEOMETRY_ATTRIBUTE"]["translationStatus"])
        self.assertEqual("GROUP_ONLY", rows["DAMPED_TRACK"]["translationStatus"])
        self.assertEqual("GROUP_ONLY", rows["COPY_ROTATION"]["translationStatus"])
        self.assertTrue(rows["COPY_ROTATION"]["registrationRequired"])
        rotation = next(row for row in data["semanticDefinitions"] if row["type"] == "COPY_ROTATION")
        self.assertEqual(["group.copy_r"], rotation["ruleIds"])
        self.assertNotIn("RAW_TYPE", rotation["acceptedEvidence"])

    def test_exact_contract_lookup_never_falls_back(self):
        implementation = registry.find_implementation("hoaux.copy_rotation.world", 1)
        self.assertEqual("HoAux", implementation["backendId"])
        self.assertIsNone(registry.find_implementation("hoaux.copy_rotation.world", 2))
        self.assertIsNone(registry.find_implementation("future.implementation", 1))
        self.assertIsNone(registry.find_implementation("hoaux.copy_rotation.world", True))
        implementation["conditions"]["ownerSpaces"] = ["BROKEN"]
        self.assertEqual(["WORLD"], registry.find_implementation("hoaux.copy_rotation.world", 1)["conditions"]["ownerSpaces"])

    def test_local_is_planned_and_vrc_evidence_is_not_numerical_equivalence(self):
        choices = registry.implementations_for("COPY_ROTATION", "HoAux")
        self.assertEqual(3, len(choices))
        self.assertEqual(2, sum(row["availability"] == "PLANNED" for row in choices))
        for suffix in ("local", "owner_orient"):
            item = registry.find_implementation("hoaux.copy_rotation." + suffix, 1)
            self.assertEqual("PLANNED", item["availability"])
            self.assertEqual("UNTESTED", item["verification"]["status"])
        for item in registry.load_registry()["implementations"]:
            if item["backendId"] == "Vrc":
                self.assertEqual("SHIM_ONLY", item["verification"]["status"])

    def test_registry_and_generated_coverage_do_not_drift(self):
        path = ADDON_ROOT / "RigConstraints" / "docs" / "COVERAGE.md"
        self.assertEqual(registry.generate_coverage(), path.read_text(encoding="utf-8"))
        self.assertEqual(23, len(registry.load_registry()["implementations"]))


if __name__ == "__main__":
    unittest.main()
