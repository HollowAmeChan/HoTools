# Ordinary Rig Constraint coverage

Generated from `registry/registry.v1.json`; regenerate with `python -m RigConstraints.registry --write`.

The table registers capabilities; it is not a claim that all parameters of a Blender type are executable.

## Catalog progress

- Blender baseline: 4.5.8, 5.2.0.
- Constraint types: 29; direct semantics: 2; group-only members: 5; UnknownSemantic: 22.
- Semantic definitions: 7; implementation contracts: 23; implemented legacy/current paths: 23; planned: 0.
- Full-type completion, parameter-domain completion and real SDK validation are deliberately not conflated.

copyR requires explicit generated/adopted ownership metadata. A manually authored raw Copy Rotation remains a source fact and is not guessed into copyR; v2/v3 retain their compatibility interpretation.

## Three parallel columns

| Blender source type | Blender versions | Admitted owners | Semantic translation | Unity implementation references |
| --- | --- | --- | --- | --- |
| `CAMERA_SOLVER` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `FOLLOW_TRACK` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `OBJECT_SOLVER` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `COPY_LOCATION` | 4.5.8, 5.2.0 | OBJECT, BONE | COPY_LOCATION | standard.copy_location.world@1<br>hoaux.copy_location.world@1<br>vrc.copy_location.world@1 |
| `COPY_ROTATION` | 4.5.8, 5.2.0 | OBJECT, BONE | COPY_ROTATION, TWIST, FAN (explicit copyR registration required) | standard.copy_rotation.world@1<br>standard.twist.legacy@1<br>standard.fan.legacy@1<br>hoaux.copy_rotation.world@1<br>hoaux.twist.legacy@1<br>hoaux.fan.legacy@1<br>vrc.copy_rotation.world@1<br>vrc.twist.legacy@1<br>vrc.fan.legacy@1<br>hoaux.copy_rotation.local@1<br>hoaux.copy_rotation.owner_orient@1 |
| `COPY_SCALE` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `COPY_TRANSFORMS` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `LIMIT_DISTANCE` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `LIMIT_LOCATION` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `LIMIT_ROTATION` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `LIMIT_SCALE` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `MAINTAIN_VOLUME` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `TRANSFORM` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `TRANSFORM_CACHE` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `CLAMP_TO` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `DAMPED_TRACK` | 4.5.8, 5.2.0 | OBJECT, BONE | AIM (registered group only) | standard.aim.object_position@1<br>hoaux.aim.object_position@1<br>vrc.aim.object_position@1 |
| `IK` | 4.5.8, 5.2.0 | BONE | UnknownSemantic | None |
| `LOCKED_TRACK` | 4.5.8, 5.2.0 | OBJECT, BONE | AIM (registered group only) | standard.aim.object_position@1<br>hoaux.aim.object_position@1<br>vrc.aim.object_position@1 |
| `SPLINE_IK` | 4.5.8, 5.2.0 | BONE | UnknownSemantic | None |
| `STRETCH_TO` | 4.5.8, 5.2.0 | OBJECT, BONE | TWIST (registered group only) | standard.twist.legacy@1<br>hoaux.twist.legacy@1<br>vrc.twist.legacy@1 |
| `TRACK_TO` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `ACTION` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `ARMATURE` | 4.5.8, 5.2.0 | OBJECT, BONE | ARMATURE | standard.armature.linear@1<br>hoaux.armature.linear@1<br>vrc.armature.linear@1 |
| `CHILD_OF` | 4.5.8, 5.2.0 | OBJECT, BONE | MCH (registered group only) | standard.mch.parent@1<br>hoaux.mch.parent@1<br>vrc.mch.parent@1 |
| `FLOOR` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `FOLLOW_PATH` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `GEOMETRY_ATTRIBUTE` | 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `PIVOT` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |
| `SHRINKWRAP` | 4.5.8, 5.2.0 | OBJECT, BONE | UnknownSemantic | None |

## Ordered semantic member contracts

The scanner reads these member specs from the registry; it must not maintain a second hardcoded signature table.

| Semantic | Ordered source type / role | Rule | Writes |
| --- | --- | --- | --- |
| COPY_LOCATION@1 | COPY_LOCATION / location | direct.copy_location | POSITION |
| COPY_ROTATION@1 | COPY_ROTATION / rotation | group.copy_r | ROTATION |
| ARMATURE@1 | ARMATURE / armature | direct.armature | POSITION, ROTATION, SCALE |
| MCH@1 | CHILD_OF / parent | group.mch | POSITION, ROTATION |
| TWIST@1 | COPY_ROTATION / rotation, STRETCH_TO / stretch | group.twist | POSITION, ROTATION, SCALE |
| FAN@1 | COPY_ROTATION / rotation | group.fan | ROTATION |
| AIM@1 | DAMPED_TRACK / aim, LOCKED_TRACK / up | group.aim | ROTATION |

## Versioned implementation contracts

Exact/conditional/approximate is a contract declaration. Verification evidence is a separate column.

| Implementation | Semantic | Backend | Availability | Fidelity | Verification | Test suite |
| --- | --- | --- | --- | --- | --- | --- |
| `standard.copy_location.world@1` | COPY_LOCATION@1 | Standard | IMPLEMENTED | EXACT | TESTED | constraint-ir-v3-regression |
| `standard.copy_rotation.world@1` | COPY_ROTATION@1 | Standard | IMPLEMENTED | CONDITIONAL | TESTED | constraint-ir-v3-regression |
| `standard.armature.linear@1` | ARMATURE@1 | Standard | IMPLEMENTED | APPROXIMATE | TESTED | constraint-ir-v3-regression |
| `standard.mch.parent@1` | MCH@1 | Standard | IMPLEMENTED | CONDITIONAL | LEGACY_EVIDENCE | legacy-aux-regression |
| `standard.twist.legacy@1` | TWIST@1 | Standard | IMPLEMENTED | LEGACY | LEGACY_EVIDENCE | legacy-aux-regression |
| `standard.fan.legacy@1` | FAN@1 | Standard | IMPLEMENTED | LEGACY | LEGACY_EVIDENCE | legacy-aux-regression |
| `standard.aim.object_position@1` | AIM@1 | Standard | IMPLEMENTED | EXACT | TESTED | constraint-ir-v3-regression |
| `hoaux.copy_location.world@1` | COPY_LOCATION@1 | HoAux | IMPLEMENTED | EXACT | TESTED | constraint-ir-v3-regression |
| `hoaux.copy_rotation.world@1` | COPY_ROTATION@1 | HoAux | IMPLEMENTED | EXACT | TESTED | constraint-ir-v3-regression |
| `hoaux.armature.linear@1` | ARMATURE@1 | HoAux | IMPLEMENTED | CONDITIONAL | TESTED | constraint-ir-v3-regression |
| `hoaux.mch.parent@1` | MCH@1 | HoAux | IMPLEMENTED | CONDITIONAL | LEGACY_EVIDENCE | legacy-aux-regression |
| `hoaux.twist.legacy@1` | TWIST@1 | HoAux | IMPLEMENTED | LEGACY | LEGACY_EVIDENCE | legacy-aux-regression |
| `hoaux.fan.legacy@1` | FAN@1 | HoAux | IMPLEMENTED | LEGACY | LEGACY_EVIDENCE | legacy-aux-regression |
| `hoaux.aim.object_position@1` | AIM@1 | HoAux | IMPLEMENTED | EXACT | TESTED | constraint-ir-v3-regression |
| `vrc.copy_location.world@1` | COPY_LOCATION@1 | Vrc | IMPLEMENTED | EXACT | SHIM_ONLY | constraint-ir-v3-regression |
| `vrc.copy_rotation.world@1` | COPY_ROTATION@1 | Vrc | IMPLEMENTED | CONDITIONAL | SHIM_ONLY | constraint-ir-v3-regression |
| `vrc.armature.linear@1` | ARMATURE@1 | Vrc | IMPLEMENTED | APPROXIMATE | SHIM_ONLY | constraint-ir-v3-regression |
| `vrc.mch.parent@1` | MCH@1 | Vrc | IMPLEMENTED | CONDITIONAL | SHIM_ONLY | legacy-aux-regression |
| `vrc.twist.legacy@1` | TWIST@1 | Vrc | IMPLEMENTED | LEGACY | SHIM_ONLY | legacy-aux-regression |
| `vrc.fan.legacy@1` | FAN@1 | Vrc | IMPLEMENTED | LEGACY | SHIM_ONLY | legacy-aux-regression |
| `vrc.aim.object_position@1` | AIM@1 | Vrc | IMPLEMENTED | EXACT | SHIM_ONLY | constraint-ir-v3-regression |
| `hoaux.copy_rotation.local@1` | COPY_ROTATION@1 | HoAux | IMPLEMENTED | EXACT | TESTED | copy-rotation-local-fbx-golden |
| `hoaux.copy_rotation.owner_orient@1` | COPY_ROTATION@1 | HoAux | IMPLEMENTED | EXACT | TESTED | copy-rotation-local-fbx-golden |

## Registered test matrix

Export the machine-readable contract/suite join with `python -m RigConstraints.registry --matrix`.

Axes describe existing suites, not an automatically proven Cartesian product. Contract-specific verification and VRC SHIM_ONLY limits remain authoritative.

| Suite | Runners | Observed axes |
| --- | --- | --- |
| constraint-ir-v3-regression | HoTools: `tests/export_wtd_ir_v3_fixture.py`<br>HoUnityTools: `Tests~/ConstraintIRV3/Run.ps1` | backend: HoAux, Standard, Vrc shim<br>channels: Copy Location, Copy Rotation, Armature, Aim<br>lifecycle: runtime, repeat evaluation, prefab, merge<br>limits: VRC real SDK/client untested; native approximations retain per-contract limits |
| legacy-aux-regression | HoTools: `tests/test_blender_aux_constraint_ownership.py`<br>HoTools: `tests/test_blender_fbx_mch_local_rotation.py`<br>HoTools: `tests/test_blender_hofbx_v4.py`<br>HoUnityTools: `Tests~/ConstraintIRV3/Run.ps1`<br>HoUnityTools: `Tests~/ConstraintIRV4/RunImport.ps1` | blender: 4.5.8, 5.2.0<br>semantics: MCH, Twist, Fan<br>lifecycle: ownership, source preservation, v3 compatibility, v4 assembly, reimport, undo<br>limits: legacy behavior is not full-domain numerical equivalence |
| copy-rotation-local-fbx-golden | HoTools: `tests/export_copyr_v4_fixture.py`<br>HoUnityTools: `Tests~/ConstraintIRV4/Run-local.ps1` | blender: 4.5.8, 5.2.0<br>spaces: WORLD to WORLD, LOCAL to LOCAL, LOCAL_OWNER_ORIENT to LOCAL<br>influence: 0, 0.3, 0.5, 1<br>bones: different rest axes, left/right, dynamic owner and target parents, reflected per-bone bases, ordered stacks<br>routes: Raw, MCH, serialized prefab, missing-reference recovery, merge<br>frames: first, repeat<br>rigRoot: positive uniform TRS, zero rejected, odd negative rejected, even negative rejected, nonuniform rejected, ancestor shear rejected, valid recovery<br>tolerance: position 1e-4 m, rotation 0.1 deg, scale 1e-4<br>limits: single-owner UI creates one copyR; explicit stack fixtures test IR/runtime separately |

## Evidence and boundaries

- Blender 4.5.8/5.2.0 RNA Constraint.type enums and object/pose constraint_add operators; 2026-11-21.
- Operator-admitted owner domains, not proof every object subtype or parameter combination evaluates.
- Source facts and unknown fields remain intact even when no semantic or implementation exists.
- Candidate contracts are not permission to execute. Validate conditions, binding context and host capabilities first.
- Local and Owner Orientation Copy Rotation availability follows each registered numerical acceptance record; only its stated input domain is certified.
- VRC SHIM_ONLY evidence covers API/serialization paths, not real SDK/client numerical equivalence.
- LEGACY/LEGACY_EVIDENCE preserves existing behavior and does not certify all Blender parameter combinations.
- Standard non-half rotation influence and native Armature mapping retain their explicit interpolation/rigid-approximation limits.
- Blender 5.2.0 adds GEOMETRY_ATTRIBUTE; cataloged with per-type version applicability and still UnknownSemantic.

## Public pure-Python API

- `model.new_document(armature_name, blender_version='', capture_stage='AUTHORING')` creates a mutable v4 dictionary with no fabricated final FBX binding overlay.
- `codec.dumps(document, indent=2)` validates, refreshes inputFingerprint in a copy and preserves unknown fields; it never mutates the caller.
- `codec.loads(text, verify_fingerprint=True)` rejects malformed v4, duplicate JSON keys, non-finite numbers and stale fingerprints. It preserves unknown source/semantic types and extension fields.
- `codec.fingerprint(document)` hashes compact sorted UTF-8 JSON with ensure_ascii=False, sort_keys=True, separators=(',', ':') and no numeric rounding. Only root exportTime and inputFingerprint are excluded; arrays retain order.
- `validation.schema.validate_document(document)` returns dictionaries containing code, path and message. It validates structure/references without scanning a scene or selecting a backend implementation.
- `registry.load_registry()` returns a fresh parsed copy. `registry.registry_manifest()` returns id, version and SHA256 of the authority JSON's actual UTF-8 file bytes, including whitespace/newline.
- `registry.find_implementation(id, version)` uses an exact pair and returns None on mismatch. `registry.implementations_for(semantic_type, backend=None)` includes planned entries and does not grant execution permission.
- `python -m RigConstraints.registry --check` verifies this generated document has not drifted.

Registry conditions are declarative data. ownerSpaces/targetSpaces are independent; copyRotation.spacePairs are ordered target/source space first, owner space second. Every current implementation requires BONE owners; OBJECT facts remain representable without being executable.

Fingerprint golden canonical payload:

`{"a":1.0,"nested":{"exportTime":"kept"},"z":"裙子"}`

Its SHA256 is `2b7c80faa177b85a2f10a7e8e4dcc27c7ea18a8d0a487e50c46172dbc96d27e1`. The registry file hash follows a separate raw-byte rule.
