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
Unity. The exporter writes the following fixture groups into the HoTools MC2 fixture
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
- `distance_runtime_*.json`: direct reflective calls to the fixed source
  `DistanceConstraint.SolverConstraint()` internal entry. The first cases
  isolate mixed nonzero/zero record ordering and record final next/velocity
  positions without running the abandoned Unity host.
- `bending_*.json`: direct `TriangleBendingConstraint.CreateData()` ordered
  quads, rest angle/volume values, and sign/volume markers. Raw Pack64 and
  source-generated write arrays remain diagnostic fields; the latter are not
  promoted into the host/native contract because the fixed runtime never
  registers or consumes them.
- `bending_runtime_*.json`: direct reflective calls to fixed source
  `SolverConstraint()` and `SumConstraint()`, recording fixed-point scratch
  counts/components, averaged positions, unconditional scratch clear, Fixed
  particle behavior, and negative-scale consumption.
- `particle_step_*.json`: direct reflective calls to
  `SimulationStepUpdateParticles()`. One case disables inertia, wind,
  collision, and external force while locking velocity stabilization, damping,
  gravity, fixed-particle pose tracking, and scratch clearing order. The
  Center-inertia case disables all forces and freezes depth interpolation,
  position/velocity-reference shift, velocity rotation, and step-basic pose.
- `center_step_*.json`: direct reflective calls to
  `TeamManager.SimulationStepTeamUpdate()`, freezing frame interpolation,
  local movement/rotation inertia limits, inertia vector/rotation, angular
  velocity, scale ratio, gravity falloff, velocity stabilization, and blend
  weight with wind disabled.
- `center_frame_shift_*.json`: direct reflective calls to
  `TeamManager.SimulationCalcCenterAndInertiaAndWind()`. The first case isolates
  positive-scale `worldInertia` translation/rotation shift with fixed points,
  anchor, smoothing, limits, teleport, synchronization, culling, skip, and
  stabilization disabled. The second case applies movement and rotation speed
  limits after the same world-inertia shift. The third case isolates anchor
  translation/rotation cancellation with world inertia disabled.

Generated `Library`, `Temp`, logs, and nonessential ProjectSettings are ignored.
`Packages/packages-lock.json` is committed after a successful run so the
resolved Unity package environment remains explicit.
