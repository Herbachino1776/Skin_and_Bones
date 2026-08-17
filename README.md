# Skin & Bones Forge

Skin & Bones Forge is a Blender 5.1.2 add-on for rebuilding the base-color
texture of a SPAR3D human mesh and building a validated production rig from
the bundled Townsman-derived Y+ canonical humanoid skeleton.

Version 2.2.2 implements one-click SPAR3D production-mesh intake, the Folsom
visual workflow, production **Bones**, non-destructive texture repair,
shared-body Appearance Variant Families, and a surgical mirrored single-plate
weapon texture baker:

- Finish mass-produced weapon GLBs from one already-background-removed RGBA
  plate without entering the humanoid source/landmark workflow. Select the
  weapon mesh, load the plate, auto-fit its alpha silhouette, choose the local
  projection-depth axis and source side, mirror the plate onto the opposite
  side, fine-tune scale/width/offset/rotation/edge wrap live, then EMIT-bake
  and bind the result through the weapon's existing UV while preserving normal
  and other PBR material data. Broad front/back faces now reach full projection
  strength in one bake; Edge Wrap feathers only the rounded/perpendicular
  transition instead of requiring repeated bake buildup.
- Author one protected production mesh, canonical 21-bone rig, hierarchy,
  scale, UV contract, and weight set once, then keep multiple independently
  sourced, baked, repaired, approved, and exported appearances on that body.
- Switch active variants in the sidebar without duplicating the mesh or rig;
  the production material immediately binds the selected variant's final image.
- Fingerprint topology, vertex order, UVs, production rig/rest hierarchy,
  weights, transforms, axes, and stable production-mesh identity. Technical
  changes stale every affected approval instead of silently reusing it.
- Export active or all approved variants as distinct rigged GLBs with a compact
  versioned family handoff in glTF extras and the sibling rigging manifest.

- Import a raw SPAR3D GLB, weld only exactly coincident seam vertices, prove
  loop UV/corner-normal/material preservation, and normalize a protected clean
  production copy to 1.50 m without remeshing or changing its silhouette.
- Preserve the target geometry, original UV map, material slot, and normal map.
- Auto-skin through a temporary voxel heat proxy, transfer four-influence
  weights back to the untouched mesh, suppress hand-to-leg contact drag, and
  reconcile adjacent pelvis palettes for stable collapse animation.
- Retain the canonical root bone for hierarchy and root motion while forbidding
  direct root weights from anchoring visible character surfaces.
- Create axis-aware orthographic projection cameras and temporary camera UVs.
- Clean every source non-destructively into `SBF_CLEAN_SOURCE_*`, removing
  partial-alpha background spill and extending foreground RGB under transparency.
- Store 18 labeled image-space body landmarks per view, isolate projected arm
  joints from torso/clothing cross-sections, explicitly skip hidden profile
  sides, and block only genuine `SOURCE_POSE_REVIEW_REQUIRED` contradictions.
- Fit the first rig-landmark preview to the standardized `SBF_HIGH_A_V1` pose
  instead of reproducing the old canonical arms-down wrist and hand positions.
- Keep each processed projection plate continuous while using labeled body
  landmarks for per-part pose preflight. Sparse diagnostic triangles never
  become the visible head, torso, or limb texture.
- Prefer front/back identity detail on the upper body and head.
- Reject arm, hand, and other foreground pixels on surfaces hidden behind them.
- Calibrate eyes and mouth corners in a zoomable Image Editor without altering
  the clean source plates.
- Use an identity-safe confidence blend instead of stacking several full faces
  or switching photographs on hard polygon boundaries.
- Auto-fit source silhouettes and update image alignment controls live.
- Despill source edges and confidence-gate their silhouettes before projection.
- Preview the material before committing in a compact, collapsible workflow.
- Bake a 1024-8192 pixel atlas into a clean base-color UV (4096 by default),
  automatically replacing fragmented polygon-island layouts with a semantic
  view-space atlas while normal and other PBR maps stay on the original UV.
- Preserve the raw bake as `SBF_BaseColor_Baked`, paint Clone/Heal changes into
  owned correction and mask layers, and bind the composited
  `SBF_BaseColor_Final` for preview, packing, PNG output, and GLB delivery.
- Clone through surface tangent space across rotated UV islands, Heal with
  deterministic frequency separation, Smart Fill only explicit masks from
  semantic/material-safe donors, and harmonize paired geometric UV seam bands.
- Classify projection fallback and repair provenance per atlas texel, expose
  unresolved/seam diagnostics, and block delivery when the configured safe
  unresolved threshold or known diagnostic colors remain.
- Restore roughness and normal strength with adjustable defaults of 1.0 and 0.25.
- Remove all temporary data, save a new `.blend`, export a new GLB, and emit
  optional processing manifests and verification renders.
- Load the armature-only `SBF_HUMANOID_YPLUS_V1` template from the installed
  add-on, verify all 21 rest bones against its manifest, and reuse the one
  tagged template instead of importing an external rig GLB.
- Treat Blender +Y as character forward, +Z as up, +X as anatomical right,
  and stamp that versioned coordinate contract on the rig and mesh.
- Analyze evaluated target geometry, topology, materials, UVs, connected
  components, symmetry, and 26 confidence-scored humanoid landmarks.
- Fit an exact-name, exact-hierarchy armature duplicate to target proportions.
- Expose 16 persistent artist-correction handles and validate that fitting
  leaves topology, vertex order, UVs, materials, groups, and modifiers intact.
- Use the versioned `DSB_SIMPLE_HANDS_V1` 21-bone production profile directly.
  Legacy 57-bone sources can still derive it by excluding the 36 verified
  finger descendants.
- Merge removed finger donor weights into the matching retained hand group and
  generate owned, deterministic production Action copies with only removed
  finger channels filtered out.
- Bind fragmented production meshes through barycentric canonical-donor
  transfer, connected-component classification, a fitted bone-segment proxy
  fallback, deterministic cleanup, and four-influence normalization.
- Roll back failed binds, prevent duplicate deform groups/modifiers, and emit a
  machine-readable weight/component report.
- Run 63 isolated-bone stress checks. The bundled rest template intentionally
  contains no Actions or NLA; animation-library generation remains an
  Animation Forge responsibility.
- Finalize a clean 21-bone production hierarchy, export a skinned GLB with
  version/axis metadata, validate a clean reimport, and call Dreadstone
  Animation Forge's actual rig analyzer in an isolated Blender process.

## Install

1. Use the release archive `Skin_and_Bones_Forge_v2.2.2.zip`.
2. In Blender 5.1.2, open **Edit > Preferences > Add-ons**.
3. Choose **Install from Disk**, select the ZIP, and enable **Skin & Bones Forge**.
4. In the 3D Viewport, open the sidebar with `N` and select
   **Skin & Bones Forge**.

Do not unpack the release ZIP before installing it. The archive contains the
required top-level `skin_and_bones_forge` module.

## Quick workflow

1. Click **Import + Prepare SPAR3D Character** and choose the raw GLB.
2. Confirm **READY FOR SKIN**, then click **Validate Character**.
3. Click **Select Character Perspective Folder** to load the four matching
   `front`, `back`, `left`, and `right` images from their filenames. The picker
   starts in `D:\AI aRt\Skin and Bones Projection packs`.
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
8. Expand **SKIN 4. Texture Repair Studio**. You may paint
   `SBF_BaseColor_Final` with Blender's native Clone brush (leave Correction
   Layer enabled at 1.0), use the add-on repair tools, then click
   **SAVE BLENDER PAINT + COMMIT**. Save/export also captures native paint.
9. Use **Render Verification Set**, **Save New Base Asset**, and
   **Export New GLB**.

## Mirrored single-plate weapon workflow

This path assumes the upstream weapon-production pipeline has already produced
both the weapon GLB and a transparent/background-removed RGBA projection image.
It does not run Source Doctor, character landmarks, rigging, or body semantics.

1. Import/open the weapon GLB normally and select the mesh to texture.
2. Expand **WEAPON — Single-Plate Bake** and click **Use Selected Weapon Mesh**.
3. Click **Load Weapon Projection Plate** and choose the transparent plate.
4. Leave **Projection Depth** on Local Y for the common X/Z weapon silhouette,
   or switch to Local X/Z if that particular generated asset is oriented
   differently. Choose which side receives the unmirrored source.
5. Keep **Mirror Opposite Side** enabled and click **Auto Fit Plate** followed by
   **Create / Refresh Weapon Preview**.
6. Fine-tune Scale, Width Fit, Horizontal/Vertical offset, Rotation, Flip X/Y,
   Edge Wrap, Alpha Cut, and Projection Strength. These controls update the
   existing preview live. At Projection Strength 1.0, broad faces are opaque
   source color in one pass; Edge Wrap changes only the feather around edges.
7. Choose bake size/output and click **BAKE + BIND TEXTURE**. The resulting PNG
   is baked through the weapon's existing UV and becomes its Principled base
   color; normal/roughness/other PBR bindings remain intact.

To create alternate people on the same completed body, finish and finalize the
production Bones rig, expand **Appearance Variants**, and click **CREATE FAMILY
FROM CURRENT APPEARANCE**. Use **Add Variant** for a fresh source selection or
**Duplicate Settings** to retain useful calibration while clearing bake,
repair, and approval. Bake and repair each appearance normally, click
**APPROVE VARIANT**, then use **EXPORT ACTIVE** or **EXPORT APPROVED**. The
variant exporter writes rigged GLBs under `Rigged_GLB\Appearance_Variants`.
Legacy files and the original single-character workflow remain optional and
unchanged until a family is explicitly created. See the
[appearance-family handoff contract](docs/appearance_variant_handoff.md).

For Bones, select the production target and follow **BONES 1-4** in order. The
packaged canonical rig loads automatically; **Load Bundled Canonical Rig** is
available for explicit verification. Continue with **Analyze Canonical Rig**,
**Analyze Target Humanoid**, **Generate Landmark
Preview**, **Fit Skeleton Preview**, and **Validate Fitted Skeleton**. Move
cyan handles—including the two whole-hand endpoints—and use **Refit From
Corrections** when validation requests artist correction. Do not rotate fitted
rest bones directly in Edit Mode. Then continue through **Bind
Production Character**, weight validation, pose tests, canonical Action tests,
finalization, rigged GLB export, clean reimport, and Animation Forge
acceptance. See [the rigging workflow](docs/rigging_workflow.md) and the
[canonical humanoid handoff contract](docs/canonical_humanoid_contract.md).

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
The successful run exposes `Skin_and_Bones_Forge_v2.2.2` under **Artifacts**
for 30 days. Download the artifact, extract its one contained installable ZIP,
and drop that ZIP into Blender using **Install from Disk**.

## Scope

Version 2.2.2 keeps the isolated mirrored single-plate weapon finishing path
from 2.2.1 but changes its coverage policy so full-strength broad faces are
complete in one bake while rounded/perpendicular edges remain feathered. The
weapon path owns only projection fit, preview, base-color bake, and material
binding on an already-prepared mesh; it does not own weapon generation,
rigging, collision, gameplay calibration, or source background removal.
Appearance variants continue to own only source, calibration, bake, repair,
diagnostics, approval, and export identity; they do not own mesh, rig, weights,
Actions, damage, or other PBR authoring. Optional hand shape-key authoring,
animation polish, gore/damage authoring, Rigify, and runtime game editing remain
downstream milestones.

Skin & Bones Forge is licensed under GPL-3.0-or-later.