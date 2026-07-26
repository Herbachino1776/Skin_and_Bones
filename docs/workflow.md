# Artist workflow

## Prepare the character

Open the SPAR3D `.blend` or import its GLB. Keep a source copy. The add-on
works in memory and writes to new output paths by default, but source control
is still good production hygiene.

Start with **0. SPAR3D Intake & Mesh Prep**. Version 0.6.5 imports the raw GLB,
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
click **Validate Character**. The add-on fills the detected production
material, UV, base-color node, and normal-map node.

## Prepare the sources

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

After loading the sources, click **One-Click Best Preview**. It applies the
same identity-priority preset used by the visual acceptance harness, auto-fits
every loaded silhouette, reapplies saved facial landmarks, and creates the
preview. The operation creates temporary orthographic cameras, `SBF_PROJ_*`
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

Choose an atlas size, output PNG, margin, roughness, normal strength, and
packing state. Keep **Clean Base-Color UV** enabled for SPAR3D output, then
click **Bake Final Texture**.

The bake:

1. Uses the preview material as an EMIT source.
2. Builds `SBF_BaseColorUV` from a temporary exact-welded copy so fragmented
   SPAR3D surfaces do not turn into tiny triangle islands.
3. Copies that UV back without changing the production vertices or polygons.
4. Bakes and saves the PNG.
5. Explicitly binds the baked base color to `SBF_BaseColorUV`.
6. Keeps the original UV and binds unconfigured normal/PBR image nodes to it.
7. Optionally packs the image and applies roughness and normal strength.
8. Removes projection cameras, projection UVs, weights, and preview material.

The default 4096 bake uses Cycles CPU, one sample, a 24-pixel margin, and the
clean base-color UV. Disable that option only for a mesh whose original UV is
already a deliberate, connected production atlas.

## Verify and deliver

**Render Verification Set** writes:

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

Version 0.6.5 fits, binds, tests, and exports the production rig. Keep the
canonical rig and production target in the same file, expand **Bones —
Automatic Humanoid Rig**, and follow the focused workflow in
[rigging_workflow.md](rigging_workflow.md). Preview objects live in the owned
`SBF_RigPreview` collection; donor/proxy data live only in
`SBF_RiggingTemporary`. Production binding intentionally adds the exact 57
deform groups, one Armature modifier, and safe armature parenting while
preserving protected geometry, vertex order, UVs, materials, and textures.
