# Bones automatic humanoid rig workflow

## Prepare

Use Blender 5.1.2. Keep the known-good Animate Anything armature, its reference
mesh, parent scale hierarchy, Actions, and NLA intact. Import the retextured
SPAR3D GLB into the same working file. Set the production mesh as **Target
Mesh** and the known-good armature as **Canonical Rig Source**.

The source `.blend` remains the rest-skeleton authority. The exported rigged
GLB is useful for external GLB compatibility inspection but does not override
rest heads, tails, matrices, hierarchy, or bone names.

## Analyze

1. Click **Analyze Canonical Rig**. The fingerprint covers stable rest data;
   Actions and NLA are inventoried but excluded. Use **Write Rig Report** for
   the JSON-compatible full report.
2. Confirm the existing Forward and Up axes describe the target, then click
   **Analyze Target Humanoid**.
3. Review target height, connected-component/bone-heat warnings, and landmark
   confidence. A warning is not silently promoted to a confident result.

## Preview and correct

1. Click **Generate Landmark Preview** to create 18 cyan editable handles in
   `SBF_RigPreview`.
2. Click **Fit Skeleton Preview**. The add-on duplicates the armature object
   and data, removes animation/constraints from the duplicate, derives
   `DSB_SIMPLE_HANDS_V1`, excludes verified finger descendants, fits the 21
   remaining bone endpoints, and displays it in front. Exact retained names,
   hierarchy, and deform flags remain intact.
3. Move uncertain handles in Object mode. Click **Refit From Corrections** to
   serialize their world positions on the target and rebuild the preview.
4. Use **Reset Landmark Corrections** to discard saved overrides and return to
   deterministic automatic landmarks.

The two whole-hand handles continue the elbow-to-wrist direction into each
palm. Correct these cyan handles and refit; do not rotate fitted rest bones in
Edit Mode. Direct rest-bone edits cannot preserve the canonical local roll used
by rotation Actions and are intentionally blocked by the animation gate.

## Simplified production hands

The full canonical rig remains immutable and retains all 57 bones. The
versioned production profile retains `arm_left_hand` and `arm_right_hand`,
attached to their canonical forearm parents, while excluding all 36 verified
thumb/finger descendants. No finger landmarks or hidden compatibility bones
are created.

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

Click **Bind Production Character** to run **Universal Voxel Auto-Skin**. The
operation voxelizes a temporary world-space copy, runs Blender automatic bone
heat on that watertight proxy, transfers the proxy weights back to the original
production vertices, and deletes the proxy. The production surface itself is
never remeshed. A topology-aware limb-contact taper prevents a lowered hand
from dragging the nearby thigh or robe when the arm is raised.

Cleanup removes invalid, tiny, non-deform, opposite-side, and anatomically
impossible influences; smooths transfer only across real production edges;
repairs structurally empty deform groups; limits vertices to four influences;
and normalizes again. The target's
topology, vertex order, UVs, materials, textures, and source Actions are not
changed. Failure restores the original target parent, transforms, modifiers,
groups, metadata, selection, mode, frame, and animation state.

Use **Validate Production Weights** to refresh the machine-readable report.
`READY_FOR_ANIMATION_TEST` requires zero unweighted or non-normalized vertices,
zero invalid/non-deform weights, no vertices over the configured limit, all 21
production deform groups populated, no removed finger groups, and exactly one
owned Armature modifier.

## Test and finalize

Run **Run Pose Torture Tests** followed by **Test Canonical Actions**. The first
operation evaluates every retained production bone around all three local axes
and removes its owned test Action. The second evaluates every frame of all five
canonical fixtures through Blender 5 Action slots.
Owned copies remove only channels targeting excluded finger bones, then scale
remaining pose-bone location channels by fitted/source rest length. Frame
ranges, markers, interpolation, non-finger channels, source Actions, and source
NLA tracks remain unchanged.

When both pass, use **Finalize Production Rig**. This removes landmark/preview
helpers, names the armature `SBF_ProductionRig`, creates five owned
production-compatible Actions/NLA tracks, and retains rigging metadata.

## Export and compatibility acceptance

All output fields default under `E:\Skin_And_Bones_Exports`: `Textures`,
`Blender`, `GLB`, `Rigged_GLB`, `Proof_Renders`, and `Reports`. Directories are
created when an export is written; changing a field remains supported.

Set **Rigged GLB**, leave **Export Filtered Actions** enabled when desired,
and click **Export Rigged GLB**. The adjacent `.sbf.json` manifest records the
fingerprint, binding/component statistics, pose/Action results, delivery
results, and the deferred hand-aesthetics warning.

Then run **Validate Clean Reimport**. It verifies the exact simplified bone
list and hierarchy, 21 deform bones, no removed finger Action channels, one
skinned mesh and Armature relationship, materials/textures, both UV maps, five
Actions, height/bounds, and meaningful finite deformation.

Finally set the local Dreadstone Animation Forge package directory and run
**Run Animation Forge Acceptance**. The add-on launches a factory-clean Blender
5.1.2 process, imports the GLB, loads Animation Forge without modifying it, and
calls its actual `daf.analyze`, `daf.walk`, and `daf.hurt_left` operators.
`ANIMATION_FORGE_ACCEPTED` requires the Animate Anything body/limb profile, a
skinned mesh, resolved hierarchy, required body/arm/forearm/hand mappings,
accepted filtered Actions, the real mapping report, and safe all-frame walk
and hurt deformation. Finger equality is intentionally not required.

**Clean Temporary Rigging Data** removes only owned donor, proxy, and temporary
test data. It does not delete the finalized production rig.
