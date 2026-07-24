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

Adjust that view's **Scale**. Values above `1.0` enlarge the source subject.
Use offsets to align the face, shoulders, hips, and feet. Source images with
inconsistent camera height or body proportions cannot be fully corrected by
a single scale.

## Face details double in three-quarter views

- Confirm the front/back images show the same identity as the profiles.
- Increase **Head Front/Back** or **Upper Front/Back**.
- Increase **Directional Exponent** to narrow directional influence.
- Reduce the offending side view's overall weight.

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
- Reduce the alpha threshold.
- Refine scale/offset alignment.
- Keep smooth view blending; do not force one view over an entire polygon.

## The preview did not update

Click **Refresh Preview** after changing source transforms or blending
settings. If the file was interrupted during an operation, run
**Clean Temporary Data** and create the preview again.

## Bake fails

- Ensure the target is selectable and in Object mode.
- Confirm Cycles is available.
- Use a smaller texture for diagnosis.
- Check that the output folder is writable.
- Avoid 8192 bakes on machines without enough memory.

## The normal map changed or disappeared

The add-on only changes the base-color image. A missing normal after GLB
export usually means the original material did not have a connected Normal
Map node. Re-run validation and address its warning before baking.

## Save is refused

The save path matches the source file. Choose a new path. Source overwrite is
blocked unless **Allow Source Overwrite** is explicitly enabled.
