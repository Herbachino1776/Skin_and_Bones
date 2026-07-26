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

## The canonical rig looks huge in armature space

The supplied Animate Anything rig is normalized by uniformly scaled parent
empties. Do not apply those transforms. Bones reads the exact rest data from
the armature and measures visible reference height from evaluated mesh
world-space bounds; object dimensions and `DSB_SIZE_ROOT_*` names are not used
as scale authority.

## Animation changes the canonical report

Action and NLA names are inventory fields, so their inventory can differ after
an artist adds animation. The canonical fingerprint must remain unchanged
while Actions play because it is derived only from ordered rest bones,
hierarchy, flags, heads/tails, rolls, and quantized rest matrices. If it does
change, confirm the armature rest data itself was not edited.

## Validation requests landmark correction

This is expected for uncertain elbows, hands, heels, toes, or fragmented
SPAR3D topology. Move the cyan handles in Object mode, click **Refit From
Corrections**, and validate again. Corrections are serialized on the target
mesh and survive preview cleanup and file reload. **Reset Landmark
Corrections** removes the saved overrides and regenerates automatic handles.

## A whole-hand bone points into the leg

Click **Fit Skeleton Preview** again. Whole-hand endpoints are detected by
continuing each forearm into a side-confined palm corridor, so the retained
hand bones cannot use a thigh-height surface slice. If a palm still needs
adjustment, move its cyan hand handle and click **Refit From Corrections**.
Do not rotate the bone itself in Armature Edit Mode: that changes its local rest
roll, which can make the pose test look better while correctly causing the
canonical Action compatibility gate to fail. Revalidate, rebind, then rerun
the pose and canonical Action tests.

## Bone-heat risk is high

The warning is advisory during preview fitting. **Bind Production Character**
uses **Universal Voxel Auto-Skin**: Blender bone heat runs on an owned temporary
voxel proxy and the weights are transferred to the unchanged production mesh.
Do not remesh or retopologize the production target to silence the warning.

When a relaxed hand physically touches the thigh or robe, the prepared surface
can contain contact edges between the two anatomical branches. The binder
tapers whole-hand influence out of the lower leg branch to stop the leg-fan
artifact. Pose torture tests can still report a contact-seam stretch because a
single connected edge cannot move as both hand and leg without topology
separation; the binder does not silently split the accepted production mesh.

## Production weights need review

Open the machine-readable weight report from the target's `sbf_weight_report`
custom property. A binding is not pose-ready if it has unweighted,
non-normalized, invalid, non-deform, over-limit, missing, or empty deform
groups. Re-run binding after changing the method or tiny-weight threshold;
repeated binding replaces owned groups and the owned Armature modifier.

Version 1.0.0 retains the canonical `root` bone but forbids it from directly
weighting production-surface vertices. Root-motion Actions and hierarchy remain
intact because child bones inherit root transforms. Any transferred root weight
is redistributed before final normalization, preventing pelvis or groin cloth
from remaining near the origin while the body collapses.

## Canonical Actions explode on the fitted rig

Do not apply the original source Actions directly to the identity-space fitted
armature. The canonical fixture stores pose translations in its scaled source
rest space. **Test Canonical Actions** creates temporary adapted copies and
scales only location channels by each fitted/source rest-bone length ratio.
**Finalize Production Rig** creates the five owned export Actions without
editing the originals.

If only pelvis or robe vertices fan outward during a collapse, re-run **Bind
Production Character** with version 0.6.7 or later. The binder now reconciles
abrupt four-influence palette changes across short production-mesh edges after
voxel transfer. Do not repair this by moving hand bones, splitting the mesh, or
assigning the affected region rigidly to root; those approaches introduce new
rest-orientation or deformation seams.

Version 0.6.8 also prevents millimeter-scale rest edges from failing solely on
a large ratio during an otherwise coherent collapse. An edge is blocking only
when it exceeds both the 4.5x stretch ratio and 4% of character height after
deformation. Large pelvis fans remain blocking; short, visually coherent robe
or shoulder folds do not.

## Animation Forge rejects the GLB

First run **Validate Clean Reimport**. Then verify **Animation Forge
Repository** points at the package directory containing its `__init__.py`.
Acceptance runs a factory-clean Blender subprocess and calls the real
`daf.analyze` operator; review the sibling `.animation_forge.json` report for
the mapping, missing roles, operator result, and process output.

## Finger bones appear in the production preview or export

Re-run **Analyze Canonical Rig**, then rebuild the preview. The
`DSB_SIMPLE_HANDS_V1` profile must report 36 removed finger descendants and 21
remaining production bones for the supplied canonical fixture. Do not hide or
collapse finger bones to satisfy an old fingerprint: the full 57-bone
fingerprint describes the immutable source, while the separate production
fingerprint describes the simplified output.

If a singular hand needs an open-palm or closed-grip silhouette, that requires
future mesh deformation (for example the reserved `DSB_HAND_OPEN_MAGIC` or
`DSB_HAND_GRIP_SHAFT` shape keys), not per-finger bones in this profile.
