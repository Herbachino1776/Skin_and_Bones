# Canonical humanoid and Animation Forge handoff contract

## Authority and identification

Skin & Bones Forge 2.2.0 packages the armature-only Blender asset
`skin_and_bones_forge/assets/canonical_humanoid_yplus_v1.blend` and the sibling
`canonical_humanoid_yplus_v1.contract.json`. The asset contains exactly one
armature named `SBF_CanonicalHumanoid_YPlus_V1`, 21 deform bones, no mesh, no
materials, no Actions, and no NLA. Its rig identifier is
`SBF_HUMANOID_YPLUS_V1`.

Generated armatures, meshes, GLB extras, and `.sbf.json` manifests expose:

| Property | Current value |
| --- | --- |
| `sbf_canonical_rig_version` | `SBF_HUMANOID_YPLUS_V1` |
| `sbf_rig_contract_version` | `1` |
| `sbf_forward_axis` | `+Y` |
| `sbf_up_axis` | `+Z` |
| `sbf_root_bone` | `root` |
| `sbf_unit_scale_meters` | `1.0` |
| `sbf_orientation_revision` | `1` |
| `sbf_orientation_state` | `CANONICAL_Y_PLUS` |
| `sbf_bone_mapping` | JSON semantic-to-bone mapping below |

Consumers must prefer this explicit metadata. Do not infer facing from mesh
bounds, a pose, filenames, or an external canonical GLB.

## Coordinate and transform contract

In Blender native coordinates:

- character forward is world **+Y**;
- up and grounding are world **+Z**, with feet grounded at `Z = 0`;
- anatomical right is world **+X** and anatomical left is world **-X**;
- one Blender unit is one meter;
- armature and production mesh object matrices are identity after preparation;
- scales are positive `(1, 1, 1)` with no mesh-only correction, negative scale,
  object-level 180-degree yaw, or hidden corrective parent.

Blender's Y-up glTF exporter maps local `(X, Y, Z)` to glTF `(X, Z, -Y)`.
Therefore canonical forward is glTF **-Z**, up is glTF **+Y**, and right remains
glTF **+X**. A GLB imported back into Blender must again face Blender +Y. Never
apply another 180-degree correction after recognizing the current rig version.

The top-level `root` bone has no parent and carries hierarchy/root motion. It is
retained as a deform bone for contract compatibility, but Skin & Bones removes
direct `root` weights from visible production vertices; child bones inherit
root motion. The asset manifest is authoritative for exact heads, tails, rolls,
rest matrices, flags, and hierarchy. Fitted character bone lengths/positions
change to landmarks, while names, parent relationships, deform flags, local
orientation policy, version, and coordinate basis remain fixed.

## Semantic bone mapping

| Semantic role | Bone |
| --- | --- |
| root | `root` |
| pelvis/hips | `body` |
| lower spine | `body_top0` |
| middle spine | `body_top1` |
| chest/upper spine | `body_top2` |
| neck | `neck` |
| head | `head` |
| left shoulder / upper arm / lower arm / hand | `shoulder_left` / `arm_left_top` / `arm_left_bot` / `arm_left_hand` |
| right shoulder / upper arm / lower arm / hand | `shoulder_right` / `arm_right_top` / `arm_right_bot` / `arm_right_hand` |
| left upper leg / lower leg / foot | `leg_left_top` / `leg_left_bot` / `leg_left_foot` |
| right upper leg / lower leg / foot | `leg_right_top` / `leg_right_bot` / `leg_right_foot` |

There are no finger bones, toe descendants, IK controls, or hidden compatibility
bones in this profile. Animation Forge should consume `sbf_bone_mapping` first
and may use the table as the fixed fallback for this rig version.

## New character and legacy behavior

For a new unrigged target, Skin & Bones uses the artist-declared source forward
and up axes to transform mesh and shape-key coordinates into +Y/+Z once. It then
sets explicit orientation metadata. Re-running the operation sees
`CANONICAL_Y_PLUS` and does not rotate again.

A rig is legacy only when it has explicit `-Y`/`LEGACY_Y_MINUS` metadata or
matches the known 57-bone Animate Anything schema-1 rest fingerprint. Unknown
rigs are never guessed or rotated automatically. **Convert Legacy Y- Character**
rotates a verified static armature rest basis and all bound mesh/shape-key data
by 180 degrees around Z, writes a migration report, and becomes a no-op on
repeat. It refuses rigs with Actions or NLA because rewriting animation-library
data here would be unsafe. Animation Forge must provide any animation-aware
legacy migration.

## Exact Animation Forge responsibilities

Animation Forge should make these separate updates without modifying Skin &
Bones' canonical asset:

1. **Rig selection:** accept `sbf_canonical_rig_version ==
   SBF_HUMANOID_YPLUS_V1`; use `sbf_bone_mapping`; do not require an external
   canonical GLB.
2. **Animation direction:** generate forward/root motion along Blender +Y
   (glTF -Z), rightward motion along +X, and do not apply the old Y- yaw fix.
   If a legacy `-Y` rig is detected, migrate/reject it exactly once before
   authoring Actions.
3. **Death grounding:** calculate grounding in Blender Z with the desired floor
   at `Z = 0` (glTF Y = 0), drive the top-level `root`, and keep the armature
   and mesh coherent. Do not bake a mesh-only vertical or yaw correction.
4. **Humanoid idle and retargeting:** map hips to `body`, spine through
   `body_top0..2`, and limbs through the named left/right chains. Retarget
   rotations against this rig version's local rest matrices/fingerprint, while
   leaving Skin & Bones' rest pose unchanged.
5. **Animation library:** author idle, walk, hurt, death, grounding, transition,
   and direction-specific Actions in Animation Forge. Zero Actions in a clean
   Skin & Bones delivery is intentional and valid.
