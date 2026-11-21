"""Fail visibly when the live Blender constraint domain outgrows the catalog."""

from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from RigConstraints.registry import load_registry

data = load_registry()
version = ".".join(str(v) for v in bpy.app.version)
live = {item.identifier for item in bpy.types.Constraint.bl_rna.properties["type"].enum_items if item.identifier}
known = {row["type"] for row in data["constraintTypes"]}
assert not live - known, "New Blender constraint types need catalog rows: " + ", ".join(sorted(live - known))
if version in data["blenderCatalogVersions"]:
    expected = {row["type"] for row in data["constraintTypes"] if version in row["blenderVersions"]}
    assert live == expected, (live - expected, expected - live)
for row in data["constraintTypes"]:
    assert row["semanticTypes"] or row["translationStatus"] == "UNKNOWN"
print("CONSTRAINT_CATALOG_OK", version, len(live))
