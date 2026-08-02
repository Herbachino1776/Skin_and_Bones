# Troubleshooting

## Source Plate Doctor or body alignment blocks preview

- `STALE` means a source, Doctor setting, or body landmark changed. Run
  **PROCESS ALL SOURCE PLATES**, **PREPARE CONTINUOUS SOURCES**, then **REFRESH BEST
  PREVIEW**.
- `SOURCE_POSE_REVIEW_REQUIRED` is a deliberate severe-pose gate. Choose the
  reported view, use **PLACE BODY LANDMARKS**, and verify the worst arm/leg
  chain. For `right_arm`, verify Right shoulder, Right elbow, Right wrist, and
  Right hand center. In Front, character right is image left; in Back,
  character right is image right. A genuinely different pose needs a compatible
  source plate.
- Version 2.0.1 could sample a high-A hand at a fixed low body row and mistake
  the trouser edge for the hand, folding both target arm chains inward with
  errors near 1.0. Install 2.0.2 and rerun **PREPARE CONTINUOUS SOURCES**.
- In versions before 2.0.0, a wide torso, belt, or skirt could pull the
  mesh-side wrist estimate inward while the source wrist remained on the arm.
  Nearly symmetric hanging arms could therefore report values around 0.5-0.7,
  with only the marginally worse side displayed. Install 2.0.2, re-run
  **PREPARE CONTINUOUS SOURCES**, and inspect the expanded per-part results.
- A huge face tile, triangular torso/limb patches, or white projection gaps are
  the retired sparse-atlas regression from 2.0.0. Install 2.0.2 and refresh the
  preview; the add-on now rebuilds one continuous source per view.
- A saved blend whose generated cleaned images reopen black is self-healed by
  2.0.2 on the next preview refresh. The original projection PNGs are re-read;
  no manual image deletion is required.
- An owned-image size mismatch indicates stale or artist-resized
  `SBF_CLEAN_SOURCE_*` data. **RESTORE ORIGINAL SOURCE** and process that view
  again; the source PNG is never changed.
- If contamination remains highlighted, increase RGB extension modestly or
  correct the source alpha. Validation refuses partial-alpha pixels that still
  strongly match the detected background.

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
If bone heat misses a very small, fully disconnected voxel island, the binder
rigidly assigns that proxy island to its nearest fitted surface bone and records
the repair in the weight report. Larger islands and partial component failures
remain blocking instead of being hidden by a broad fallback.

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
Production Character** with version 1.0.1 or later. The binder detects connected
center groin/robe bridges that received both left- and right-leg weights, moves
their shared influence to the pelvis/body chain, and feathers the correction
over neighboring topology. Do not repair this by moving hand bones, splitting
the mesh, or assigning the affected region to root; those approaches introduce
new rest-orientation or deformation seams.

## The exported character develops jagged holes during animation

Install 2.0.4 or newer and export the rigged GLB again before Damage Authoring.
Older output could assign different skin weights to coincident vertex copies
created for GLB UV and normal seams. Those copies overlap in rest pose but pull
apart under a walk. **Export Rigged GLB** now rewrites every split copy from the
authoritative welded source weight, and **Validate Clean Reimport** blocks any
weight mismatch or physical seam opening across every exported Action.

Version 0.6.8 also prevents millimeter-scale rest edges from failing solely on
a large ratio during an otherwise coherent collapse. An edge is blocking only
when it exceeds both the 4.5x stretch ratio and 4% of character height after
deformation. Large pelvis fans remain blocking; short, visually coherent robe
or shoulder folds do not.

Version 1.0.1 also repairs a saved Target Mesh pointer that refers to the
authoritative clean object after it was unlinked from the active scene. A
unique visible intake/reimport duplicate is swapped out and the authoritative
processed topology is restored before fitting or binding. Pose and Action
tests reject zero-motion rigs, and collapse/root translation is evaluated
relative to whole-character motion so a coherent fall is not mistaken for an
exploding vertex.

Version 1.1.0 fixes clean-reimport Action inventory validation. The
factory-clean validator derives the expected semantic Action count from the
serialized canonical contract; it no longer expects zero merely because the
original source Action datablocks are intentionally absent from the clean
process.

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

## Texture repairs disappeared after re-bake

Texture Repair Studio preserves corrections only when target vertex/polygon
order, the production base-color UV corners, and atlas dimensions have the same
fingerprint. A topology edit, UV edit, or texture-size change intentionally
creates empty correction layers because stale pixels would land on the wrong
surface. Preview refreshes and compatible re-bakes preserve the layers. Use the
separate `*.baked.png` and saved `.blend` for recovery; do not rename unrelated
artist images to the reserved `SBF_Texture_*` names.

## Blender Clone brush edits disappear on commit, save, or export

Install 2.0.3 or newer, paint the production image named
`SBF_BaseColor_Final`, leave **Correction Layer** enabled with **Opacity 1.0**,
and click **SAVE BLENDER PAINT + COMMIT**. The add-on detects changed pixels and
moves them into its persistent correction/mask layers before recompositing.
Save, GLB export, compatible re-bakes, and later Texture Doctor actions perform
the same capture automatically.

## The whole character turns pink after texture repair

Install 1.2.1 or newer. Version 1.2.0 could leave
`SBF_Preview_<character>` assigned after a repair action even though the
Inspection control said **After**. The final texture and correction layers were
not overwritten, but Blender could display the temporary projection material
or its unloaded generated images as pink. In 1.2.1, **After**, **CLEAR REPAIR
PREVIEW**, every repair commit, save, and export explicitly restores the
validated production material while preserving correction pixels.

## The projection preview turns the whole character pink

Install 1.2.2 or newer, then click **One-Click Best Preview** again. Version
1.2.1's four-cardinal preview requested 57 image samplers and more mesh
attributes than Blender's material limit; Blender 5.1.2 rejected that GPU shader
with **uses too many attributes** and displayed magenta. The same version also
wrote bounded warp pixels through a detached NumPy reshape, leaving those
sources transparent and
causing final bake to reuse the old SPAR3D base color. Version 1.2.2 packs each
view into one native-resolution body-part atlas, uses one compact owner ID, and
blocks final bake when a processed atlas is transparent, stale, or unavailable.

You do not need to rebuild the character or reselect the PNGs. Open the existing
`.blend`, install 1.2.2, click **One-Click Best Preview**, confirm the actual
projection artwork appears, and then click **Bake Final Base Color**.

## Smart Fill reports rejected or unresolved pixels

Smart Fill never expands beyond the explicit target mask. Under the default
**Combined Safe Sources** policy it also requires the same material plus the
same/opposite semantic part or an artist donor. Review the forbidden and donor
masks, lower **Minimum Donor Confidence** only when the source is genuinely
safe, or use Clone/Heal. Do not disable part restrictions simply to let a hand
or face texture fill a thigh, torso, or clothing region.

## Seam Heal leaves seams selected

The measured correction exceeds **Maximum Accepted Correction** or the pair is
ambiguous. This is intentional: Seam Heal only changes narrow bands around real
shared 3D edges whose UV corners are separated. Use the heatmap and unlit final
inspection, then repair unsafe pairs manually with Clone/Heal. Lighting and
normal-map seams are not base-color seam candidates.

## Save or GLB export is blocked after repair

Click **Show Unresolved** and inspect the classification overlay. Delivery
recomposites `SBF_BaseColor_Final` and blocks when unresolved pixels exceed
**Safe Unresolved Threshold**, a known diagnostic color remains, the repair
fingerprint is stale, or the production material does not use the final image.
Repair the remaining mask and click **SAVE BLENDER PAINT + COMMIT**; do not raise the
threshold to hide a visible atlas hole.
