# Artist workflow

## Prepare the character

Open the SPAR3D `.blend` or import its GLB. Keep a source copy. The add-on
works in memory and writes to new output paths by default, but source control
is still good production hygiene.

Start with **0. Character Setup**. Version 2.0.0 imports the raw GLB,
selects the plausible production mesh, exact-welds duplicated seam positions,
preserves face-corner UVs and normals, and normalizes the clean target to 1.50 m.
The downstream target contract expects:

- A real mesh with renderable polygons.
- An existing production UV map.
- A node-based material assigned to the mesh.
- A base-color image node connected to Principled Base Color or labeled
  `BASE COLOR`.
- Preferably, a normal texture connected through a Normal Map node.

Open **3D Viewport > Sidebar > Skin & Bones Forge**, set **Target Mesh**, and
click **Validate Character** in the same stage. **Target Contract &
Orientation** keeps the detected material, UV, and axis overrides nearby but
collapsed until they are needed.

The sidebar follows the production sequence and keeps later stages collapsed:

- **SKIN 1-5** moves from source images through alignment, bake, repair, and
  boneless base-asset delivery.
- **BONES 1-4** moves from skeleton fitting through binding, deformation tests,
  and rigged compatibility export.
- Advanced diagnostics and tuning stay nested under the stage they affect.

## Prepare the sources

Open **SKIN 1. Source Images**, click **Select Character Perspective Folder**,
and choose a character folder.
The browser opens at `D:\AI aRt\Skin and Bones Projection packs`. The add-on
loads exactly one image whose filename contains each separate view key:
`front`, `back`, `left`, and `right`. Other files, including the source image,
manifest, and mesh, are ignored. Missing or duplicate view matches cancel the
operation without replacing the currently assigned images.

Expand each source header, click **Open Image from Disk...**, and select the
front, back, character-left, or character-right image. Optional front-left and
front-right 45-degree cards improve coverage when those plates are genuinely
matched. The **Loaded** field is Blender's selector for images already present
in the current `.blend`.
**Auto-Fit Loaded Images** centers and scales a newly loaded subject from its
alpha silhouette. Each image should depict the same identity, outfit,
hairstyle, proportions, pose, lighting, camera height, and framing.

Best results come from:

- A mild A-pose with arms separated from the torso.
- Hands separated from the thighs.
- Slightly separated legs.
- Neutral, even light and a transparent background.
- A transparent background is preferred; solid black backgrounds can use
  **Key Black Background**.
- 2048-4096 pixels of useful character height for a 4K bake.

The left/right labels refer to the character's sides, not the viewer's.

## Run Source Alignment Doctor

Open **SKIN 2. Align & Preview**, then expand **Manual Source Processing &
Landmarks** before final bake:

1. Click **PROCESS ALL SOURCE PLATES**. The original image datablocks and PNGs
   remain untouched; the add-on creates owned `SBF_CLEAN_SOURCE_<VIEW>` images.
2. Click **AUTO INITIALIZE BODY LANDMARKS**. The deterministic silhouette pass
   initializes head, shoulder, elbow, wrist, hand, hip, knee, ankle, and foot
   anchors. Profile views explicitly skip the hidden anatomical side.
3. Choose a source and use **PLACE BODY LANDMARKS** when the automatic points
   need correction. Every cyan point is labeled with its number and anatomical
   name. Front view states that character right is image left; back view states
   that character right is image right. The Image Editor supports wheel zoom,
   middle-mouse pan, Backspace undo, `S` skip-hidden, Enter accept, and Escape
   cancel.
4. Click **PREPARE CONTINUOUS SOURCES**. Pose preflight still evaluates head,
   torso, both arms/hands, pelvis, and both legs/feet independently, but each
   view remains one continuous cleaned plate for preview and bake.
5. Click **REFRESH BEST PREVIEW**.

The pose preflight reports acceptable, moderate, or severe mismatch per view
and lists every moderate or severe part. Target elbow, wrist, and hand anchors
come from the isolated outer-arm silhouette band rather than torso or clothing
vertices at the same height. Moderate mismatch remains available for artist
review without forcing sparse affine patches into the texture. Severe
articulated contradiction stops with
`SOURCE_POSE_REVIEW_REQUIRED`; correct the landmarks or supply a pose-compatible
plate rather than forcing the bake.

Use **SHOW EDGE CONTAMINATION** and **SHOW CLEANED SOURCE** under **Advanced
Source Processing** to inspect cleanup. Doctor pixel distances are scaled from a
2K reference. **RESTORE ORIGINAL SOURCE** removes only owned cleaned/warped
data and returns that view to its untouched original pointer.

## Orient and align

The default reference orientation is:

- Character front outward: `+Y`
- Character up: `+Z`

Change **Forward Axis** and **Up Axis** for differently oriented imports.
They must be perpendicular.

Start with a framing ratio of `0.90`. Per-view controls then provide:

- Flip X/Y
- Scale around the center
- Horizontal/vertical offset
- Alpha threshold
- Overall view weight
- Per-view occlusion enable
- Head-only scale, horizontal fit, and offset
- Interactive facial landmarks

Scale values above `1.0` enlarge the source subject in the projection.

## Calibrate the face

Facial calibration is stored as metadata and never paints dots into the clean
source image.

1. Expand **Front** and choose **Place Face Points...**.
2. The source opens in a zoomed Image Editor. Place the image-left eye center,
   image-right eye center, image-left mouth corner, and image-right mouth
   corner.
3. Use the mouse wheel to zoom, middle mouse to pan, Backspace to undo, and
   `R` to reset. Press Enter to make Front the reference.
4. Repeat for each side or optional 45-degree source. On a true left/right
   profile, place the visible eye center and matching mouth corner, and press
   `S` to skip both hidden points. Diagonal sources should use three or four.

Each view is corrected independently. Applying a right-side calibration does
not alter body fit or the already-calibrated left side. **Reapply** is
idempotent and starts from the saved silhouette auto-fit.

## Preview and refine

In **SKIN 2. Align & Preview**, click **One-Click Best Preview** after loading
the sources. It applies the
same identity-priority preset used by the visual acceptance harness, auto-fits
every loaded silhouette, processes missing cleaned sources, initializes missing
body landmarks, creates bounded body warps, reapplies saved facial landmarks,
and creates the preview. The operation creates temporary orthographic cameras, `SBF_PROJ_*`
UV maps, and `SBF_WEIGHT_*` corner attributes, then assigns a temporary
emission preview material.

The source image, flip, scale, offset, alpha threshold, black key, enable
state, and overall weight controls update the existing material immediately
when **Live Alignment Preview** is enabled. Camera fit, head ownership, and
occlusion settings still require **Refresh Preview** because they rebuild
geometry attributes or ray visibility.

**Identity-Safe Head Blend** is enabled by the preset. It strongly favors the
best aligned source while allowing a narrow confidence transition to its
neighbor. This avoids both failure modes: several complete faces blended at
once, and hard polygon-shaped cuts between photographs. **Head Blend
Sharpness**, **Source Edge Padding**, and the neck transition are adjustable
under **Head Identity Protection**.

Inspect:

- Front and three-quarter facial identity.
- Eyes, nose, mouth, beard, and hairline for doubling.
- Shoulders and the hair crown for collaging.
- Torso and thighs behind the arms for phantom hands.
- Silhouettes for pale/white bands.
- Under-arm regions for honest fallback to the original atlas.

Use live source controls for alignment. Click **Refresh Preview** only after
changing fit, ownership, blending, or occlusion settings. The add-on rebuilds
temporary state from the production material.

## Bake

Open **SKIN 3. Bake Texture**, choose an atlas size and output PNG, then click
**Bake Final Texture**. Margin, roughness, normal strength, packing state, and
**Clean Base-Color UV** remain under **Advanced Bake & Material Settings**.
Keep **Clean Base-Color UV** enabled for SPAR3D output.

The bake:

1. Uses the preview material as an EMIT source.
2. Verifies that preview and bake fingerprints reference exactly the same
   cleaned and per-part warped images; stale state blocks the bake.
3. Builds `SBF_BaseColorUV` from a temporary exact-welded copy so fragmented
   SPAR3D surfaces do not turn into tiny triangle islands.
4. Copies that UV back without changing the production vertices or polygons.
5. Bakes and saves the PNG.
6. Explicitly binds the baked base color to `SBF_BaseColorUV`.
7. Keeps the original UV and binds unconfigured normal/PBR image nodes to it.
8. Optionally packs the image and applies roughness and normal strength.
9. Removes projection cameras, projection UVs, weights, warped caches, and the
   preview material while retaining reusable cleaned sources.

The default 4096 bake uses Cycles CPU, one sample, a 24-pixel margin, and the
clean base-color UV. Disable that option only for a mesh whose original UV is
already a deliberate, connected production atlas.

## Repair the baked base color

The bake now starts **SKIN 4. Texture Repair Studio** at the active atlas size. It
keeps four owned layers:

- `SBF_BaseColor_Baked`: the unchanged projection result, also saved beside the
  requested output as `*.baked.png`;
- `SBF_Texture_Corrections`: replacement RGB produced by repair tools;
- `SBF_Texture_Correction_Mask`: the non-destructive blend amount;
- `SBF_BaseColor_Final`: `mix(Baked, Corrections, CorrectionMask)` and the only
  image bound for final PNG, packed Blender data, and GLB export.

Topology, polygon/vertex order, `SBF_BaseColorUV`, and atlas size are
fingerprinted. A compatible re-bake preserves the correction and mask layers;
changing any fingerprinted contract clears stale corrections. Preview refreshes
do not remove them. Normal and other PBR images remain on the original UV.

For **Clone** or **Heal**, click **SET SOURCE** in the 3D Viewport, then drag
with **APPLY / PAINT REPAIR**. Clone maps source and target through their local
surface tangent bases, so rotated UV islands do not rotate the copied detail.
Heal keeps source high-frequency detail while adapting to target color. Size,
Softness, Strength, and Detail Preservation are the normal controls; source
scale/rotation, spacing, aligned/fixed behavior, semantic/material restrictions,
and optional anatomical symmetry are under **Advanced Texture Repair**. Escape
or right-click cancels before any pixels are written.

**SMART FILL MASK** runs only on detected unresolved pixels, selected faces
converted to an atlas mask, or the owned artist target mask. The default
**Combined Safe Sources** policy requires the same material and a matching or
opposite semantic part (or an explicitly painted donor). The forbidden-source
mask always wins. Fill advances from the boundary inward and reports requested,
filled, unresolved, and rejected counts. Split a mask if it exceeds the
configured bounded pixel limit.

For seam work, click **DETECT COLOR SEAMS**. The add-on pairs UV-separated
corners only when their faces share a real mesh edge, measures base-color
discontinuity, and selects seams above the detection threshold. **HEAL SELECTED
SEAMS** handles the current list; **HEAL ALL SAFE SEAMS** leaves corrections
above the maximum accepted amount for manual Clone/Heal. Only narrow paired UV
bands receive low-frequency harmonization; fine detail remains and repaired RGB
extends just beyond island borders.

Use **Show Unresolved**, **Show Seam Heatmap**, Before/After, Correction Mask,
Classification, and **Unlit Final** for inspection. Diagnostic preview materials
are temporary; **CLEAR REPAIR PREVIEW** restores the production material without
deleting corrections. **CLEAR SELECTED REGION** and **CLEAR ALL** change only
owned repair layers. Blender's native Clone brush may edit
`SBF_BaseColor_Final` directly while Correction Layer is enabled at 1.0. Click
**SAVE BLENDER PAINT + COMMIT** before verification; changed pixels are moved
into the persistent correction and mask layers. Save and GLB export perform
the same capture, recomposite, and validation automatically, and block when
unresolved pixels exceed **Safe Unresolved Threshold** or known diagnostic
colors remain.

## Verify and deliver

Open **SKIN 5. Base Asset Delivery**. **Render Verification Set** writes:

- Front, back, left, and right
- Face close-up
- Left and right head close-ups at 30, 45, 60, and 90 degrees
- Left and right three-quarter
- Lower front
- Lower three-quarter

Use these views to catch identity ghosting and through-projection. Then use
**Save New Base Asset** and **Export New GLB**. If enabled, a sibling
`.sbf.json` file records the add-on version, UV, material, texture size, and
output settings.

The clean output contains no temporary projection data and remains a
boneless base asset for a separate rigging project.

## Build the production Bones rig

Version 2.1.0 fits, binds, tests, and exports the production rig. Select the
production target; the canonical Y+ template loads from the add-on automatically.
Then follow **BONES 1-4**
and the focused workflow in
[rigging_workflow.md](rigging_workflow.md). Preview objects live in the owned
`SBF_RigPreview` collection; donor/proxy data live only in
`SBF_RiggingTemporary`. Production binding intentionally adds the exact 21
deform groups, one Armature modifier, and safe armature parenting while
preserving protected geometry, vertex order, UVs, materials, and textures.
