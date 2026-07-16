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
- `bone_connection_*.json`: real BoneCloth `RenderSetupData` imports covering
  Line, Automatic, Sequential loop/non-loop, branch, residual-line, and the
  strict 120-degree triangle boundary.
- `bone_static_*.json`: real Bone Line `ImportFrom()` followed by resolved
  attributes and `ConvertProxyMesh()`, recording final proxy/finalizer arrays,
  transform baseline, normal adjustment, and vertex-to-transform rotations.
- `bone_rotation_line_*.json` and `bone_rotation_triangle_*.json`: isolated
  source jobs freezing the positive-scale Bone display-rotation and
  world-to-parent-local output stages.
- `particle_step_*.json`: direct reflective calls to
  `SimulationStepUpdateParticles()`. One case disables inertia, wind,
  collision, and external force while locking velocity stabilization, damping,
  gravity, fixed-particle pose tracking, and scratch clearing order. The
  Center-inertia case disables all forces and freezes depth interpolation,
  position/velocity-reference shift, velocity rotation, and step-basic pose.
  Two baseline cases freeze parent-first step-basic reconstruction under
  positive scale and an X-axis negative-scale transition.
  The complete-frame case executes two source-ordered no-collision substeps
  with Center inertia, prediction, Distance, Bending/Sum, the second Distance
  pass, particle post, and Team post so the second step consumes committed
  velocity from the first.
- `tether_runtime_*.json`: direct reflective call to fixed source
  `TetherConstraint.SolverConstraint()`, freezing compression/stretch
  projection, Fixed/missing-root gates, and velocity-reference attenuation.
- `angle_runtime_*.json`: direct reflective call to fixed source
  `AngleConstraint.SolverConstraint()`, freezing Restoration plus Limit across
  two baseline chains, Fixed roots, gravity falloff, velocity attenuation, and
  scratch clear.
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
  translation/rotation cancellation with world inertia disabled. The fourth
  freezes anchor cancellation followed by world inertia and both speed limits.
  The fifth isolates the persistent movement-smoothing velocity update and its
  position cancellation. The sixth isolates the extra world-inertia shift and
  moving-speed normalization caused by a positive time scale below one. The
  seventh keeps component inertia while deriving the current Center frame from
  a Fixed particle pose. The eighth freezes zero-time-scale full cancellation
  and zero moving speed without a simulation step. The ninth executes the
  scheduler jobs and freezes update/skip counts plus multi-step interpolation.
  The tenth freezes configured Keep teleport detection before smoothing and its
  100% frame shift. The eleventh freezes configured Reset teleport detection,
  zero frame shift, Center history replacement, and smoothing reset. The
  twelfth combines Keep with an X-axis scale-sign transition and freezes
  negative-matrix then frame-shift ordering. The thirteenth combines Reset with
  the same transition and proves particle reset takes precedence over the
  negative-scale matrix. The fourteenth freezes the X-axis component scale-sign
  transition by itself, both negative-scale TRS delta matrices, and the resulting
  Center and particle-history transforms before inertia shift.

Generated `Library`, `Temp`, logs, and nonessential ProjectSettings are ignored.
`Packages/packages-lock.json` is committed after a successful run so the
resolved Unity package environment remains explicit.
