# Bones automatic humanoid rig workflow

## Prepare

Use Blender 5.1.2 and set the production mesh as **Target Mesh**. Skin & Bones
loads `assets/canonical_humanoid_yplus_v1.blend` automatically from the
installed add-on. No external canonical GLB, source `.blend`, or absolute local
path is required. **Load Bundled Canonical Rig** explicitly appends the same
armature-only template for verification and reuses it on repeated execution.

The packaged asset and sibling contract manifest are the rest-skeleton
authority. They contain the Townsman-derived 21-bone armature, no character
mesh, and no Actions/NLA. See
[canonical_humanoid_contract.md](canonical_humanoid_contract.md).

## Analyze

Open **BONES 1. Build & Fit Skeleton**.

1. Click **Analyze Canonical Rig**. It loads and verifies the bundled asset if
   necessary. The fingerprint covers versioned axes and stable rest data. Use
   **Write Rig Report** for the JSON-compatible full report.
2. Confirm the existing Forward and Up axes describe the target, then click
   **Analyze Target Humanoid**.
3. Review target height, connected-component/bone-heat warnings, and landmark
   confidence. A warning is not silently promoted to a confident result.

## Preview and correct

1. Click **Generate Landmark Preview** to create 18 cyan editable handles in
   `SBF_RigPreview`.
2. Click **Fit Skeleton Preview**. The add-on duplicates the armature object
   and data, removes animation from the duplicate, uses
   `DSB_SIMPLE_HANDS_V1`, fits all 21 bone endpoints, and displays it in front.
   Exact retained names,
   hierarchy, and deform flags remain intact.
3. Move uncertain handles in Object mode. Click **Refit From Corrections** to
   serialize their world positions on the target and rebuild the preview.
4. Use **Reset Landmark Corrections** to discard saved overrides and return to
   deterministic automatic landmarks.

The automatic arm chain uses the versioned `SBF_HIGH_A_V1` production pose:
outer-arm cross-sections locate elbows and wrists, and a normalized palm offset
places each whole-hand handle. Correct uncertain cyan handles and refit; do not
rotate fitted rest bones in Edit Mode. Direct rest-bone edits cannot preserve
the canonical local roll used by rotation Actions and are intentionally blocked
by the animation gate.

## Simplified production hands

The canonical asset is already the final 21-bone profile. It retains
`arm_left_hand` and `arm_right_hand` attached to their forearm parents and has
no finger descendants or hidden compatibility bones. The older 57-bone source
derivation remains readable for legacy projects but is not packaged or needed.

`RELAXED` is the default whole-hand alignment. `OPEN_MAGIC` and `GRIP_SHAFT`
aim the singular hand bones for casting direction and weapon-shaft alignment;
they do not articulate fingers. The optional future shape-key names
`DSB_HAND_OPEN_MAGIC` and `DSB_HAND_GRIP_SHAFT` are reserved but not required
or authored in this milestone.

## Validate the fit

Click **Validate Fitted Skeleton**. `READY_FOR_BINDING` means all current
checks passed. `NEEDS_ARTIST_CORRECTION` means the rig is structurally valid
but warnings or low-confidence landmarks require review. `FAILED` is blocking
and identifies contract, transform, residual, or target-mutation errors.
After repairing an already-bound character, the validator permits only the
expected Skin & Bones deform groups and owned Armature modifier from that old
bind. It still marks weights stale and requires **Bind Production Character**
again before pose or Action tests.

**Clean Rig Preview** removes only owned handles and fitted armatures. Saved
corrections stay on the target so regenerated handles can reapply them.

## Bind production weights

Open **BONES 2. Bind & Validate Weights**. The normal path keeps its two primary
actions prominent; **Advanced Binding Settings** retains the weight threshold
and influence-limit overrides.

Click **Bind Production Character** to run **Universal Voxel Auto-Skin**. The
operation voxelizes a temporary world-space copy, runs Blender automatic bone
heat on that watertight proxy, transfers the proxy weights back to the original
production vertices, and deletes the proxy. The production surface itself is
never remeshed. A topology-aware limb-contact taper prevents a lowered hand
from dragging the nearby thigh or robe when the arm is raised. A final
topology-only palette reconciliation keeps adjacent pelvis and robe vertices
on compatible four-bone palettes so collapse Actions cannot fan open a seam.

Cleanup removes invalid, tiny, non-deform, opposite-side, and anatomically
impossible influences; smooths transfer only across real production edges;
redistributes direct root influence to compatible body or limb bones; repairs
other structurally empty deform groups; limits vertices to four influences;
and normalizes again. The reconciliation intentionally prioritizes deformation
quality over a quick bind and may take about one to two minutes on a detailed
character. The target's
topology, vertex order, UVs, materials, textures, and source Actions are not
changed. Failure restores the original target parent, transforms, modifiers,
groups, metadata, selection, mode, frame, and animation state.

Use **Validate Production Weights** to refresh the machine-readable report.
`READY_FOR_ANIMATION_TEST` requires zero unweighted or non-normalized vertices,
zero invalid/non-deform weights, no vertices over the configured limit, all 20
surface-deforming groups populated, an empty `root` surface group, no removed
finger groups, and exactly one owned Armature modifier. The retained `root`
bone still drives hierarchy and root motion through its children.

## Test and finalize

Open **BONES 3. Test & Finalize Rig**.

Run **Run Pose Torture Tests** followed by **Test Canonical Actions**. The first
operation evaluates every retained production bone around all three local axes
and removes its owned test Action. The second records
`CANONICAL_ACTIONS_NOT_BUNDLED` for this rest-only asset; that is an accepted
finalization state, not a skipped structural test. Animation Forge owns idle,
walk, hurt, and death Action generation.

When both pass, use **Finalize Production Rig**. This removes landmark/preview
helpers, names the armature `SBF_ProductionRig`, and retains the versioned
rig/axis/bone-map metadata. It does not create an animation library.

## Export and compatibility acceptance

Open **BONES 4. Export & Compatibility**.

All output fields default under `E:\Skin_And_Bones_Exports`: `Textures`,
`Blender`, `GLB`, `Rigged_GLB`, `Proof_Renders`, and `Reports`. Directories are
created when an export is written; changing a field remains supported.

Set **Rigged GLB**, enable **Export Filtered Actions** only when the working
character already has intentionally authored Actions,
and click **Export Rigged GLB**. The adjacent `.sbf.json` manifest records the
fingerprint, binding/component statistics, pose/Action results, delivery
results, and the deferred hand-aesthetics warning. Export also restores the
authoritative source weights onto every UV/normal-split GLB vertex and blocks
if even one exported position cannot be mapped safely.

Then run **Validate Clean Reimport**. It verifies the exact simplified bone
list and hierarchy, 21 deform bones, +Y foot/root geometry, versioned axis
metadata, one skinned mesh and Armature relationship, materials/textures, UV
maps, height/bounds, identical weights at coincident split seams, and finite
isolated-bone deformation. Zero Actions is correct for a rest-only delivery.

For an existing static Y- project, **Convert Legacy Y- Character** rotates the
armature rest data and all bound mesh/shape-key coordinates exactly once and
adds current metadata. It refuses unknown rigs and any rig with Actions/NLA;
animated legacy migration belongs in Animation Forge.

Finally set the local Dreadstone Animation Forge package directory and run
**Run Animation Forge Acceptance**. The add-on launches a factory-clean Blender
5.1.2 process, imports the GLB, loads Animation Forge without modifying it, and
calls its actual `daf.analyze`, `daf.walk`, and `daf.hurt_left` operators.
`ANIMATION_FORGE_ACCEPTED` requires the Animate Anything body/limb profile, a
skinned mesh, resolved hierarchy, required body/arm/forearm/hand mappings,
the real mapping report, and safe all-frame walk and hurt deformation. A
rest-only zero-Action delivery is valid; if source Actions are present, every
channel must resolve on the production rig. Finger equality is intentionally
not required.

**Clean Temporary Rigging Data** removes only owned donor, proxy, and temporary
test data. It does not delete the finalized production rig.
