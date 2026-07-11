# MC2 Unity Oracle

Minimal batch-only Unity project for exporting Tier A arrays from the fixed
MagicaCloth2 source checkout. It is not a simulation host and does not use the
abandoned `HoClothUnity` project.

MagicaCloth2 is commercial source. This project may only reference an existing
local checkout through `Packages/manifest.json`. Never copy or vendor the MC2
package into this repository. The project `.gitignore` explicitly excludes the
common embedded-package and Assets copy locations as a second guard.

Pinned inputs:

- Unity Editor: `6000.3.15f1`
- MagicaCloth2: `2.18.1`
- Source commit: `418f89ff31a45bb4b2336641ad5907a1110eabea`
- Source checkout default: `D:\Unity_Fork\MagicaCloth2`

Run `run.ps1`. The script rejects a different MC2 commit before launching
Unity. The exporter writes three fixture groups into the HoTools MC2 fixture
directory:

- `mesh_baseline_*.json`: final-proxy-stage `VirtualMesh` inputs followed by
  the original private baseline methods invoked by reflection.
- `mesh_proxy_*.json`: direct `ConvertProxyMesh()` source output for final
  triangle winding, edge union, attributes, normals/tangents, bind poses, and
  decoded vertex-to-triangle flip records.
- `distance_*.json`: direct `DistanceConstraint.CreateData()` raw packed
  indices, expanded per-vertex ranges, targets, and signed rest distances.
  These fixtures preserve raw hash-map order for diagnostics and define a
  separate canonical static-membership comparison; they do not use the old
  HoTools solver as an oracle.

Generated `Library`, `Temp`, logs, and nonessential ProjectSettings are ignored.
`Packages/packages-lock.json` is committed after a successful run so the
resolved Unity package environment remains explicit.
