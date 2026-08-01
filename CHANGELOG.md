# Changelog

All notable changes follow semantic versioning.

## 1.1.0 - 2026-07-31

### Added

- Non-destructive Source Plate Doctor with trusted-mask erosion, deterministic
  despill, transparent hidden-RGB repair/extension, contamination diagnostics,
  validation, owned cleanup, and idempotent source fingerprints.
- Per-view 18-point body-landmark metadata and Image Editor placement matching
  the facial-landmark zoom, pan, undo, skip-hidden, accept, and cancel workflow.
- Seven bounded piecewise-affine body-part source images, pose-consistency
  preflight, and strict one-owner-per-polygon anatomical projection guards.
- Preview/final-bake processed-source parity validation and compact Source
  Alignment Doctor UI with advanced diagnostics.

### Changed

- `One-Click Best Preview` now runs the complete cleaned-source, body-alignment,
  bounded-warp, ownership, confidence/occlusion, preview, and bake-ready flow.

## 0.6.1 - 2026-07-25

### Fixed

- Replaced the unavailable `MOD_WELD` panel icon with Blender 5.1.2's valid
  `AUTOMERGE_ON` icon so both SPAR3D intake panels draw without a Python error.

## 0.6.0 - 2026-07-25

### Added

- One-click raw SPAR3D GLB import, target resolution, exact-position seam weld,
  proof-driven cleanup, transform/height normalization, and automatic pipeline
  target assignment.
- Protected raw-source and clean-character collections with explicit ownership,
  deterministic fingerprints, machine-readable intake reports, restore/removal
  controls, idempotent replacement, and transactional rollback.
- Complete raw topology, attribute, material, texture, manifold, winding,
  component, duplicate-position, and diagnostic near-position analysis.
- Blender 5.1.2 fixture-matrix coverage for UV/corner-normal preservation,
  watertightness, normalization, target validation, rigging analysis, rollback,
  restore, idempotence, and release registration.

### Changed

- The sidebar now begins with **0. SPAR3D Intake & Mesh Prep**, followed by the
  unchanged texture workflow, Bones, and delivery stages.
- Version advanced to 0.6.0.

## 0.5.1 - 2026-07-25

### Added

- Reusable all-frame deformation forensics with direct mesh-edge strain,
  component, bounds, non-finite, and isolated-bone evidence.
- Blocking bind/rest/weight/isolated-bone preflight for canonical Actions and
  real Animation Forge walk/hurt acceptance, including clean GLB reimport.
- Deterministic continuity and four-influence palette repair for fragmented
  scans whose touching hand/thigh surfaces otherwise form anchored fans.
- Default `E:\Skin_And_Bones_Exports` delivery tree for Blender, GLB, rigged
  GLB, texture, proof-render, and machine-report outputs.

### Fixed

- Removed coarse anatomy-bin cleanup that reassigned neighboring vertices to
  incompatible arm, leg, torso, and root transforms.
- Corrected false-positive disconnected-component separation during coherent
  collapse animation while retaining blocking edge/bounds explosion checks.
- Canonical Action compatibility now evaluates every frame and reports the
  first unsafe frame and exact vertices, edges, components, and weights.

## 0.5.0 - 2026-07-25

### Added

- Versioned `DSB_SIMPLE_HANDS_V1` production contract derived
  deterministically from the immutable full canonical source contract.
- Hierarchy- and naming-verified exclusion of all 36 thumb/finger descendants,
  retaining the exact 21 unrelated body, limb, wrist, and hand bones.
- Transactional canonical-donor simplification that merges removed finger
  weights into the matching retained hand, normalizes them, and deletes the
  temporary donor after transfer.
- Owned deterministic filtered Action copies, per-channel removal reports,
  idempotent replacement, and cleanup support without editing source Actions.
- Simplified-contract, donor-merge, Action-filter, GLB round-trip, and actual
  Dreadstone Animation Forge regression coverage in Blender 5.1.2.

### Changed

- Fitted previews, weighting, finalization, export, and validation now use one
  singular deforming hand bone per side; finger articulation is intentionally
  outside this production profile.
- The Bones UI distinguishes the Full Canonical Contract from the Simplified
  Production Profile and reports removed/remaining bones and filtered channels.
- `RELAXED`, `OPEN_MAGIC`, and `GRIP_SHAFT` are whole-hand alignment presets.
  Optional `DSB_HAND_OPEN_MAGIC` and `DSB_HAND_GRIP_SHAFT` shape-key names are
  reserved but not required or authored.

## 0.4.0 - 2026-07-25

### Added

- Transactional production binding with canonical donor preparation,
  nearest-face barycentric transfer, classification of every disconnected
  target component, fitted bone-segment proxy fallback, deterministic cleanup,
  complete rollback, and idempotent rebinding.
- Machine-readable weight acceptance covering normalization, unweighted and
  invalid vertices, influence limits, deform-group coverage, side
  contamination, component repairs, regional summaries, and hand/foot usage.
- Fourteen owned pose-torture tests plus five canonical Action compatibility
  fixtures with Blender 5 Action-slot handling and non-destructive
  rest-proportion translation adaptation.
- Production-rig finalization, five-Action NLA export, rigging manifest,
  clean-GLB reimport validation, and isolated acceptance through Dreadstone
  Animation Forge's actual `daf.analyze` operator.
- Blender 5.1.2 regression coverage for forced rollback, repeat binding,
  permanent weights, state restoration, export/reimport, Animation Forge, and
  release-ZIP registration.

### Changed

- The Bones panel now continues from fitted-skeleton validation through
  binding, deformation tests, finalization, delivery, and compatibility
  acceptance.
- Version advanced to 0.4.0. Hand-pose aesthetics remain explicitly deferred;
  canonical hand/finger structure and nonempty deform coverage are enforced.

## 0.3.1 - 2026-07-24

### Added

- Owned `RELAXED`, `OPEN_MAGIC`, and `GRIP_SHAFT` functional hand presets,
  with `RELAXED` applied automatically to every fitted preview.
- Numerical validation for hand span versus palm width, finger spread, fitted
  hand bounds versus target height, left/right asymmetry, and finite pose
  transforms.

### Changed

- Palm-local finger fitting now uses a conservative `0.50` scale multiplier,
  compresses lateral spread to `0.50`, reduces thumb flare, and keeps the
  canonical names, hierarchy, deform flags, and animation-facing channels.
- The Blender rig fixture now exercises all three hand poses and rejects
  oversized, splayed, asymmetric, or invalid fitted hands.

## 0.3.0 - 2026-07-24

### Added

- Canonical rest-skeleton reports and deterministic SHA-256 fingerprints,
  including hierarchy, deform/connect flags, rest matrices, local axes,
  transforms, reference mesh relationships, vertex groups, Actions, and NLA.
- Evaluated world-space SPAR3D analysis with topology/material/UV inventory,
  symmetry, connected components, bone-heat warnings, and 26 confidence-scored
  humanoid landmarks.
- An owned, idempotent fitted armature preview that retains the canonical 57
  bone names, hierarchy, deform flags, and roll conventions while fitting
  independent body and limb proportions.
- Sixteen editable landmark handles with deterministic correction persistence,
  correction reapply/reset, preview refit, cleanup, and three-state validation.
- Blender 5.1.2 rig-fixture regression coverage using local proprietary assets.

### Changed

- Add-on version advanced to 0.3.0 and the sidebar now includes
  **Bones — Automatic Humanoid Rig**.

### Scope

- Permanent target parenting, armature modifiers, vertex groups, weights,
  animation retargeting, and rigged export remain intentionally excluded.

## 0.2.1 - 2026-07-24

### Added

- **One-Click Best Preview** applies the exact visual-acceptance preset,
  auto-fits every loaded source, reapplies saved facial calibration, and
  creates the projection preview in one action.

### Changed

- True left and right profile calibration now accepts the two landmarks that
  are physically visible: one eye center and its matching mouth corner.
- Profile calibration guidance explicitly explains how to skip the two hidden
  points.

### Fixed

- Removed the incorrect three-point minimum that prevented valid total-profile
  source calibration.

## 0.2.0 - 2026-07-23

### Added

- Live preview updates for source image, flip, scale, offset, alpha threshold,
  black-background keying, enable state, and overall weight controls.
- Alpha-silhouette source auto-fit with bulk 4K pixel analysis.
- Zoomable per-source facial landmark calibration for eye centers and mouth
  corners, including three-point support for a hidden profile landmark.
- Optional front-left and front-right 45-degree source slots and projection
  cameras while retaining the four-cardinal workflow.
- Identity-safe confidence blending in the head region, with adjustable
  sharpness and no hard per-polygon source cuts.
- Source-edge padding and tangent-surface fallback for scalp, jaw, and shoulder
  coverage without exposing pale remnants of the old atlas.
- Lateral head isolation so raised shoulders do not enter the identity lock.
- Eight close head-orbit verification angles at 30, 45, 60, and 90 degrees.
- Collapsible workflow panels and individually collapsible source-view cards.
- A dedicated clean base-color UV bake path that temporarily welds exact
  SPAR3D fragment duplicates for unwrapping, then copies the atlas back
  without changing production geometry or the original UV.

### Changed

- Projection transforms now live in preview shader nodes instead of baked
  camera UVs, avoiding expensive ray-cast rebuilds during alignment.
- The SPAR3D preset enables head protection, live alignment, and silhouette
  edge padding by default.
- The Folsom regression now isolates repository code from any user-installed
  add-on and asserts live shader updates, head-only landmark correction,
  three-point profile calibration, body-transform isolation, and idempotent
  calibration reapply.

### Fixed

- Removed the multi-face/four-ear blend produced by overlapping uncalibrated
  cardinal photographs.
- Removed the large stretched or pale source-boundary patches seen around the
  side of the head and shoulders.
- Removed the post-bake triangle mosaic caused by SPAR3D's fragmented original
  UV atlas while retaining that UV for the normal and other PBR textures.
- Smoothed projection ownership across exact duplicate fragment positions
  without changing the production mesh normals.

## 0.1.1 - 2026-07-23

### Fixed

- Added an explicit **Open Image from Disk...** file browser to every front,
  back, character-left, and character-right source slot.
- Kept the existing image datablock selector as a clearly labeled **Loaded**
  field for reusing images already present in the Blender file.
- Exercised disk image loading through the Blender Folsom regression.

## 0.1.0 - 2026-07-23

### Added

- Installable Blender 5.1.2 add-on and 3D Viewport sidebar workflow.
- Target, material, base-color, normal-map, and production-UV validation.
- Four configurable RGBA projection views with axis controls, per-view
  transforms, alpha thresholds, weights, and occlusion toggles.
- Orthographic camera fitting and temporary camera-projection UV maps.
- Height-aware front/back identity priority and top-surface coverage.
- Conservative polygon-center plus vertex first-surface ray visibility.
- Non-destructive projection preview with original-atlas fallback.
- 1024, 2048, 4096, and 8192 EMIT bake targets.
- Adjustable roughness, normal strength, smoothing, image packing, and margin.
- Temporary-data cleanup, save-copy, GLB export, and JSON processing manifests.
- Nine-view verification renderer.
- Folsom Blender/GLB regression and output-inspection scripts.
- Versioned release ZIP builder and documentation.
- Deterministic GitHub Actions packaging on every `main` push, with the
  installable ZIP retained as a downloadable workflow artifact for 30 days.
