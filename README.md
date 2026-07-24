# Skin & Bones Forge

Skin & Bones Forge is a Blender 5.1.2 add-on for rebuilding the base-color
texture of a SPAR3D human mesh from matching front, back, character-left, and
character-right images, with optional front-left and front-right 45-degree
plates.

Version 0.2.0 implements the Folsom reference workflow as an adjustable,
non-destructive pipeline:

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

## Install

1. Use the release archive `Skin_and_Bones_Forge_v0.2.0.zip`.
2. In Blender 5.1.2, open **Edit > Preferences > Add-ons**.
3. Choose **Install from Disk**, select the ZIP, and enable **Skin & Bones Forge**.
4. In the 3D Viewport, open the sidebar with `N` and select
   **Skin & Bones Forge**.

Do not unpack the release ZIP before installing it. The archive contains the
required top-level `skin_and_bones_forge` module.

## Quick workflow

1. Open or import the SPAR3D character.
2. Select its production mesh and click **Validate Character**.
3. Load the **SPAR3D Human - Identity Priority / Occlusion Safe** preset.
4. Assign matching front, back, character-left, and character-right images.
   The two 45-degree views are optional.
5. Expand Front, choose **Place Face Points...**, and mark both eye centers
   and mouth corners. Calibrate each other source independently; press `S` to
   skip one hidden profile landmark.
6. Click **Create Projection Preview**.
7. Inspect the face, head-orbit views, hands, torso, and thighs. Image,
   flip, scale, offset, alpha, and weight controls update live. Click
   **Refresh Preview** after changing fit, ownership, or occlusion settings.
8. Choose the texture size and output path, then click **Bake Final Texture**.
9. Use **Render Verification Set**, **Save New Base Asset**, and
   **Export New GLB**.

The source `.blend` is not overwritten unless **Allow Source Overwrite** is
explicitly enabled. See [the complete workflow](docs/workflow.md) and
[troubleshooting guide](docs/troubleshooting.md).

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
The successful run exposes `Skin_and_Bones_Forge_v0.2.0` under **Artifacts**
for 30 days. Download the artifact, extract its one contained installable ZIP,
and drop that ZIP into Blender using **Install from Disk**.

## Scope

The 0.2.x line is deliberately limited to visual finishing. Rigging,
animation, gore, paintable masks, and depth-map visibility are downstream
milestones. The current release uses the proven conservative ray-cast
visibility method.

Skin & Bones Forge is licensed under GPL-3.0-or-later.
