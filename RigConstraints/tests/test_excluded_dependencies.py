"""Ordinary constraints retain facts but cannot consume omitted HoAux stacks."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from RigConstraints.model import new_document
from RigConstraints.semantics import translate


def fixture(kind="COPY_LOCATION", target="Excluded"):
    doc = new_document("Rig", "4.5.8")
    doc["excludedOwners"] = ["Excluded"]
    doc["sourceContext"] = {"bones": [{"boneName": name, "parentBone": ""}
                                    for name in ("Owner", "Target", "Excluded", "Mapped")]}
    doc["sources"] = [{"sourceId": "c0", "ownerKind": "BONE", "ownerBone": "Owner",
        "captureStage": "AUTHORING", "constraint": {"name": "ordinary", "stackIndex": 0,
        "constraintType": kind, "targetObjectName": "Rig", "targetBoneName": target,
        "parameters": {"owner_space": "WORLD", "target_space": "WORLD", "influence": 1}, "references": {}}}]
    if kind == "COPY_ROTATION":
        doc["declarations"] = [{"ownerBone": "Owner", "groupId": "copy_r", "semanticType": kind,
            "semanticVersion": 1, "generatorId": "hotools.aux.copy_r", "evidence": "GENERATED",
            "auxType": "COPY_R", "sourceBones": [target], "memberSourceIds": ["c0"],
            "members": [{"constraintName": "ordinary", "constraintType": kind, "role": "rotation", "order": 0}]}]
    if kind == "ARMATURE":
        c = doc["sources"][0]["constraint"]
        c["targetObjectName"], c["targetBoneName"] = "", ""
        c["references"]["targets"] = [{"properties": {"target": {"name": "Rig"}, "subtarget": target, "weight": 1}}]
    return doc


class ExcludedDependencyTests(unittest.TestCase):
    def assert_blocked(self, doc):
        before = deepcopy(doc)
        result = translate(doc)
        self.assertEqual(before, doc)
        self.assertEqual(before["sources"], result["sources"])
        self.assertFalse(result["semantics"])
        self.assertTrue(any(d["status"] == "BROKEN" and "已排除的大型 HoAux 骨" in d["message"]
                            for d in result["diagnostics"]), result["diagnostics"])

    def test_direct_and_collection_targets_are_blocked_without_losing_facts(self):
        for kind in ("COPY_LOCATION", "COPY_ROTATION", "ARMATURE"):
            with self.subTest(kind=kind):
                self.assert_blocked(fixture(kind))

    def test_unrelated_exclusion_keeps_all_supported_semantics(self):
        for kind in ("COPY_LOCATION", "COPY_ROTATION", "ARMATURE"):
            with self.subTest(kind=kind):
                result = translate(fixture(kind, "Target"))
                self.assertEqual(1, len(result["semantics"]))
                self.assertFalse(result["diagnostics"])

    def test_target_ancestor_and_owner_ancestor_are_dependencies(self):
        for index in (0, 1):
            with self.subTest(bone=index):
                doc = fixture(target="Target")
                doc["sourceContext"]["bones"][index]["parentBone"] = "Excluded"
                self.assert_blocked(doc)

    def test_external_same_name_does_not_cross_the_current_armature_boundary(self):
        doc = fixture()
        doc["sources"][0]["constraint"]["targetObjectName"] = "OtherRig"
        result = translate(doc)
        self.assertEqual(1, len(result["semantics"]))
        self.assertFalse(result["diagnostics"])

    def test_final_overlay_cannot_hide_an_authoring_dependency(self):
        doc = fixture()
        doc["bindings"] = {"constraintMap": [{"sourceId": "c0", "targetBoneName": "Target"}],
                           "boneMap": [], "bindingContext": doc["sourceContext"]}
        self.assert_blocked(doc)

    def test_final_overlay_introduced_dependency_is_blocked(self):
        for kind in ("COPY_LOCATION", "ARMATURE"):
            with self.subTest(kind=kind):
                doc = fixture(kind, "Target")
                change = {"sourceId": "c0"}
                if kind == "ARMATURE":
                    change["references"] = fixture(kind)["sources"][0]["constraint"]["references"]
                else:
                    change["targetBoneName"] = "Excluded"
                doc["bindings"] = {"constraintMap": [change], "boneMap": [], "bindingContext": doc["sourceContext"]}
                self.assert_blocked(doc)

    def test_mapped_exclusion_and_final_parent_dependencies_are_blocked(self):
        doc = fixture(target="Target")
        doc["bindings"] = {"constraintMap": [{"sourceId": "c0", "targetBoneName": "Mapped"}],
            "boneMap": [{"sourceBone": "Excluded", "exportBone": "Mapped"}], "bindingContext": doc["sourceContext"]}
        self.assert_blocked(doc)
        doc["bindings"]["boneMap"] = []
        doc["bindings"]["bindingContext"] = deepcopy(doc["sourceContext"])
        doc["bindings"]["bindingContext"]["bones"][3]["parentBone"] = "Excluded"
        self.assert_blocked(doc)

    def test_missing_authoring_graph_fails_closed_but_generated_source_uses_final_graph(self):
        doc = fixture(target="Target")
        doc["sourceContext"]["bones"][0]["parentBone"] = "Owner"
        self.assert_blocked(doc)
        doc["sourceContext"]["bones"][0]["parentBone"] = ""
        context = doc.pop("sourceContext")
        self.assert_blocked(doc)
        doc["sources"][0]["captureStage"] = "EXPORT_GENERATED"
        doc["bindings"] = {"constraintMap": [], "boneMap": [], "bindingContext": context}
        self.assertEqual(1, len(translate(doc)["semantics"]))


if __name__ == "__main__":
    unittest.main()
