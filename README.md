# Skin & Bones Forge

Skin & Bones Forge is a Blender 5.1.2 add-on for rebuilding the base-color
texture of a SPAR3D human mesh and building a validated production rig from
the canonical Animate Anything humanoid skeleton.

Version 0.6.0 implements one-click SPAR3D production-mesh intake, the Folsom
visual workflow, and production **Bones**:

- Import a raw SPAR3D GLB, weld only exactly coincident seam vertices, prove
  loop UV/corner-normal/material preservation, and normalize a protected clean
  production copy to 1.50 m without remeshing or changing its silhouette.
- Preserve the target geometry, original UV map, material slot, and normal map.
- Create axis-aware orthographic projection cameras and temporary camera UVs.
- Prefer front/back identity detail on the upper body and head.
- Reject arm, hand, and other foreground pixels on surfaces hidden behind them.
- Calibrate eyes and mouth corners in a zoomable Image Editor without altering
  the clean source plates.
- Use an identity-safe confidence blend instead of stacking several full faces
  or switching photographs on hard polygon boundaries.
- Auto-fit source silhouettes and update image alignment controls live.
- Pad valid source edges to prevent pale scalp, jaw, and shoulder holes.
- Preview the material before committing in a compact, collapsible workflow.
- Bake a 1024-8192 pixel atlas into a clean base-color UV (4096 by default)
  while the normal and other PBR maps stay explicitly bound to the original UV.
- Restore roughness and normal strength with adjustable defaults of 1.0 and 0.25.
- Remove all temporary data, save a new `.blend`, export a new GLB, and emit
  optional processing manifests and verification renders.
- Fingerprint all 57 canonical rest bones while inventorying—but excluding—
  Actions and NLA from the fingerprint.
- Analyze evaluated target geometry, topology, materials, UVs, connected
  components, symmetry, and 26 confidence-scored humanoid landmarks.
- Fit an exact-name, exact-hierarchy armature duplicate to target proportions.
- Expose 16 persistent artist-correction handles and validate that fitting
  leaves topology, vertex order, UVs, materials, groups, and modifiers intact.
- Derive the versioned `DSB_SIMPLE_HANDS_V1` production profile from the full
  immutable 57-bone source contract. It retains both canonical hand bones and
  excludes all 36 verified finger descendants, leaving 21 production bones.
- Merge removed finger donor weights into the matching retained hand group and
  generate owned, deterministic production Action copies with only removed
  finger channels filtered out.
- Bind fragmented production meshes through barycentric canonical-donor
  transfer, connected-component classification, a fitted bone-segment proxy
  fallback, deterministic cleanup, and four-influence normalization.
- Roll back failed binds, prevent duplicate deform groups/modifiers, and emit a
  machine-readable weight/component report.
- Run 63 isolated-bone stress checks and every frame of all five canonical
  Actions using non-destructive Blender 5 Action-slot adaptation.
- Finalize a clean 21-bone production hierarchy, export a skinned GLB with five
  filtered production Actions, validate a clean reimport, and call Dreadstone
  Animation Forge's actual rig analyzer in an isolated Blender process.

## Install

1. Use the release archive `Skin_and_Bones_Forge_v0.6.0.zip`.
2. In Blender 5.1.2, open **Edit > Preferences > Add-ons**.
3. Choose **Install from Disk**, select the ZIP, and enable **Skin & Bones Forge**.
4. In the 3D Viewport, open the sidebar with `N` and select
   **Skin & Bones Forge**.

Do not unpack the release ZIP before installing it. The archive contains the
required top-level `skin_and_bones_forge` module.

## Quick workflow

1. Click **Import + Prepare SPAR3D Character** and choose the raw GLB.
2. Confirm **READY FOR SKIN**, then click **Validate Character**.
3. Load the four matching source images.
4. Click **One-Click Best Preview**. This applies the exact tested preset,
   auto-fits the loaded silhouettes, and builds the preview.
   The two 45-degree views are optional.
5. If a face needs correction, expand Front, choose **Place Face Points...**,
   and mark both eye centers and mouth corners. Calibrate each other source
   independently. A true profile needs only its visible eye and matching mouth
   corner; press `S` to skip each hidden point.
6. Inspect the face, head-orbit views, hands, torso, and thighs. Image,
   flip, scale, offset, alpha, and weight controls update live. Click
   **Refresh Preview** after changing fit, ownership, or occlusion settings.
7. Choose the texture size and output path, then click **Bake Final Texture**.
8. Use **Render Verification Set**, **Save New Base Asset**, and
   **Export New GLB**.

For Bones, open/import the production target alongside the canonical rig,
choose both objects, then use **Bones — Automatic Humanoid Rig** in order:
**Analyze Canonical Rig**, **Analyze Target Humanoid**, **Generate Landmark
Preview**, **Fit Skeleton Preview**, and **Validate Fitted Skeleton**. Move
cyan handles and use **Refit From Corrections** when validation requests artist
correction. Then choose the binding method and continue through **Bind
Production Character**, weight validation, pose tests, canonical Action tests,
finalization, rigged GLB export, clean reimport, and Animation Forge
acceptance. See [the rigging workflow](docs/rigging_workflow.md).

The source `.blend` is not overwritten unless **Allow Source Overwrite** is
explicitly enabled. See [the complete workflow](docs/workflow.md) and
[troubleshooting guide](docs/troubleshooting.md).

All output paths default under `E:\Skin_And_Bones_Exports`, separated into
`Textures`, `Blender`, `GLB`, `Rigged_GLB`, `Proof_Renders`, and `Reports`.

## Reference validation

The repository includes a Blender-driven Folsom regression harness:

```powershell
powershell -ExecutionPolicy Bypass -File tests/reference/run_reference_test.ps1 `
  -Blender E:\Blender\blender.exe `
  -Size 4096 `
  -RenderProofs
```

It loads the original fixture, runs the add-on without editing source code,
bakes and packs the atlas, saves a clean Blender copy, exports a GLB, reopens
the Blender output, reimports the GLB, and checks the geometry/material
contract. Large fixture files are intentionally ignored by Git; see
[reference asset setup](reference_assets/README.md).

## Repository layout

```text
addon/skin_and_bones_forge/   Installable add-on module
scripts/                      Build, install, inspect, and regression helpers
tests/reference/              Blender 5.1.2 reference test wrapper
docs/                         Artist and technical documentation
reference_assets/             Local-only Folsom regression fixtures
proof_renders/                Local-only reference proof images
```

Build the versioned installable archive with:

```powershell
python scripts/build_release.py
```

The ZIP and SHA-256 checksum are written to `dist/`.

## Automatic GitHub ZIP

Every push to `main` runs
[Validate and build](https://github.com/Herbachino1776/Skin_and_Bones/actions/workflows/validate.yml).
The successful run exposes `Skin_and_Bones_Forge_v0.6.0` under **Artifacts**
for 30 days. Download the artifact, extract its one contained installable ZIP,
and drop that ZIP into Blender using **Install from Disk**.

## Scope

Version 0.6.0 completes the simplified-hand production contract and permanent
production-rigging slice. Optional hand shape-key authoring, animation polish,
gore/damage authoring, batch processing, Rigify, paintable masks, and depth-map
visibility remain downstream milestones.

Skin & Bones Forge is licensed under GPL-3.0-or-later.
