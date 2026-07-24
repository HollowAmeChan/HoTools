import sys
import unittest
from pathlib import Path


HOAUX_DIR = Path(__file__).resolve().parents[2]
if str(HOAUX_DIR) not in sys.path:
    sys.path.insert(0, str(HOAUX_DIR))

from ir.model import HoAuxSourceIR, ResourceEdge, ResourceRecord
from ir.parser import HoAuxIRParseError, parse_json
from ir.writer import to_dict, to_json


class HoAuxCodecTests(unittest.TestCase):
    def test_round_trip_preserves_unresolved_resources(self):
        source = HoAuxSourceIR(
            rig_id="rig-a",
            armature_name="Armature",
            resources=[
                ResourceRecord(
                    resource_key="bone-a",
                    resource_kind="BONE",
                    owns=["constraint-a"],
                    payload={"name": "DEF_Test_L"},
                ),
                ResourceRecord(
                    resource_key="constraint-a",
                    resource_kind="CONSTRAINT",
                    status="UNRESOLVED",
                    uses=[ResourceEdge("TARGETS", "missing-bone")],
                    payload={"type": "COPY_ROTATION", "influence": 0.5},
                ),
            ],
        )

        encoded = to_json(source)
        decoded = parse_json(encoded)

        self.assertEqual(to_dict(decoded), to_dict(source))

    def test_rejects_unknown_schema_version(self):
        source = HoAuxSourceIR(rig_id="rig-a", armature_name="Armature")
        data = to_dict(source)
        data["schemaVersion"] = 999
        import json

        with self.assertRaises(HoAuxIRParseError):
            parse_json(json.dumps(data))


if __name__ == "__main__":
    unittest.main(argv=[__file__])
