# Artist workflow

## Prepare the character

Open the SPAR3D `.blend` or import its GLB. Keep a source copy. The add-on
works in memory and writes to new output paths by default, but source control
is still good production hygiene.

Select the primary production mesh. Version 0.1.0 expects:

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

Assign front, back, character-left, and character-right RGBA images. Each
image should depict the same identity, outfit, hairstyle, proportions, pose,
lighting, camera height, and framing.

Best results come from:

- A mild A-pose with arms separated from the torso.
- Hands separated from the thighs.
- Slightly separated legs.
- Neutral, even light and a transparent background.
- 2048–4096 pixels of useful character height for a 4K bake.

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

Scale values above `1.0` enlarge the source subject in the projection.

## Preview and refine

Load the identity-priority preset and click **Create Projection Preview**.
This operation creates temporary orthographic cameras, `SBF_PROJ_*` UV maps,
and `SBF_WEIGHT_*` corner attributes, then assigns a temporary emission
preview material.

Inspect:

- Front and three-quarter facial identity.
- Eyes, nose, mouth, beard, and hairline for doubling.
- Shoulders and the hair crown for collaging.
- Torso and thighs behind the arms for phantom hands.
- Silhouettes for pale/white bands.
- Under-arm regions for honest fallback to the original atlas.

Change settings and click **Refresh Preview**. The add-on always rebuilds its
temporary state from the production material.

## Bake

Choose an atlas size, output PNG, margin, roughness, normal strength, and
packing state. Click **Bake Final Texture**.

The bake:

1. Uses the preview material as an EMIT source.
2. Bakes into the original production UV map.
3. Saves the PNG.
4. Optionally packs it.
5. Replaces only the production base-color image.
6. Preserves the normal image.
7. Applies the chosen roughness and normal strength.
8. Removes projection cameras, UVs, weights, and the preview material.

The default 4096 bake uses Cycles CPU, one sample, and a 24-pixel margin.

## Verify and deliver

**Render Verification Set** writes:

- Front, back, left, and right
- Face close-up
- Left and right three-quarter
- Lower front
- Lower three-quarter

Use these views to catch identity ghosting and through-projection. Then use
**Save New Base Asset** and **Export New GLB**. If enabled, a sibling
`.sbf.json` file records the add-on version, UV, material, texture size, and
output settings.

The clean output contains no temporary projection data and remains a
boneless base asset for a separate rigging project.
