# Troubleshooting

## Validation cannot find the base color

Connect the production Image Texture node directly or indirectly to
Principled **Base Color**, or set its label to `BASE COLOR`. If several
unlabeled image nodes exist, the add-on will not guess.

## The projection is rotated or shows the wrong side

Set **Forward Axis** to the direction that points outward from the character's
face and **Up Axis** to the top of the head. Use per-view Flip X only when the
source itself is mirrored.

## The character is too large or small in a source

Try **Auto-Fit Source Images** first. It centers and scales all enabled images
from their visible alpha silhouettes.

Adjust that view's **Scale**. Values above `1.0` enlarge the source subject.
Use offsets to align the face, shoulders, hips, and feet. Source images with
inconsistent camera height or body proportions cannot be fully corrected by
a single scale.

## Face details double in three-quarter views

- Confirm every image shows the same identity, expression, pose, camera
  height, and focal treatment.
- Use **Place Face Points...** on Front first, then calibrate the affected side
  independently. A true profile can use three visible points.
- Keep **Identity-Safe Head Blend** enabled.
- Raise **Head Blend Sharpness** if two already-calibrated sources still overlap
  too broadly; lower it if the boundary becomes too abrupt.
- **Head Blend Sharpness** updates live; click **Refresh Preview** after
  changing the head threshold.
- Raise **Head Threshold** if raised shoulders enter the protected region.

If one side is good and the other is not, do not change a global axis or the
good side. The likely cause is a source-specific pose, framing, or facial
center difference. Recalibrate only the failing source.

## A hand or arm appears on the torso or thigh

- Keep **Occlusion Protection** and per-view occlusion enabled.
- Use **Centers + Vertices** sampling.
- Lower depth tolerance if a hidden point is being accepted.
- Do not use alpha as a substitute for visibility; a foreground limb pixel is
  opaque.

## Dark or old-texture patches appear under an arm

This is honest fallback: no enabled camera sees that surface first. Improve
the source pose by separating arms and hands from the body. Optional
three-quarter sources and paintable masks are planned for a later milestone.

## White or pale silhouette bands appear

- Verify that the source has correct straight alpha.
- For an opaque black background, enable **Key Black Background** or rerun
  **Auto-Fit Source Images** so it is detected automatically.
- Reduce the alpha threshold.
- Refine scale/offset alignment.
- Keep **Source Edge Padding** near its preset value so nearby valid hair,
  skin, or clothing fills small silhouette misses.
- Keep the confidence blend enabled; hard per-polygon view switching creates
  visible triangular cuts.

## The preview did not update

Ensure **Live Alignment Preview** is enabled. Image, flip, scale, offset,
alpha, black-key, enable, weight, and head transform controls update
immediately after a preview exists. Click **Refresh Preview** after changing
framing, confidence sharpness, advanced geometric blending, or occlusion. If an operation was
interrupted, run **Clean Temporary Data** and create the preview again.

## Bake fails

- Ensure the target is selectable and in Object mode.
- Confirm Cycles is available.
- Use a smaller texture for diagnosis.
- Check that the output folder is writable.
- Avoid 8192 bakes on machines without enough memory.

## The preview is clean but the baked result has triangle patches

Keep **Clean Base-Color UV** enabled. SPAR3D meshes can contain hundreds of
exactly separated fragments, and their original atlas gives those fragments
too little bake resolution. The clean UV is generated without changing the
production vertices or polygons; the original UV remains assigned to the
normal and other PBR maps.

## The normal map changed or disappeared

The add-on only changes the base-color image. A missing normal after GLB
export usually means the original material did not have a connected Normal
Map node. Re-run validation and address its warning before baking.

## Save is refused

The save path matches the source file. Choose a new path. Source overwrite is
blocked unless **Allow Source Overwrite** is explicitly enabled.
