# Testing and release validation

## Fast reference test

From PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File tests/reference/run_reference_test.ps1 `
  -Blender E:\Blender\blender.exe `
  -Size 1024
```

This is the fast structural regression. It validates:

- Target discovery and all four projection views.
- Nonzero view ownership after occlusion rejection.
- Live body and head shader-control updates without rebuilding projection UVs.
- Four-point Front and two-point true-profile landmark calibration.
- Head-only correction with unchanged body transforms.
- Idempotent facial-calibration reapply.
- Bake completion and requested texture dimensions.
- Original vertex/polygon counts in the Blender output.
- Byte-for-byte-equivalent original UV coordinates plus `SBF_BaseColorUV`.
- Explicit baked base-color binding to the clean UV.
- Normal image assignment.
- Temporary-data cleanup.
- Packed base color.
- Roughness `1.0` and normal strength `0.25`.
- Blender output reopen.
- GLB export and GLB re-import, including base-color UV-set selection.

## Release-quality Folsom test

```powershell
powershell -ExecutionPolicy Bypass -File tests/reference/run_reference_test.ps1 `
  -Blender E:\Blender\blender.exe `
  -Size 4096 `
  -RenderProofs
```

Inspect every image under `build/reference_test_4096/proof_renders`. Automated
structural checks cannot decide whether a face is recognizable or clothing
looks coherent.

## Static checks

```powershell
python -m compileall -q addon scripts
python scripts/validate_addon.py
python -m unittest discover -s tests -p "test_*.py"
python scripts/build_release.py
```

The release ZIP must contain a single top-level `skin_and_bones_forge/`
package and no `__pycache__` or fixture assets.

Every push to `main` runs these static checks on GitHub Actions and uploads
`Skin_and_Bones_Forge_v0.6.4` as a 30-day workflow artifact.

To exercise texture projection and baking on the exact-welded production mesh,
run the Blender harness directly with `--prepare-spar3d`. The ordinary wrapper
retains its historical no-intake baseline.

The local-only intake matrix is driven by
`scripts/run_spar3d_intake_fixture_test.py`. Pass each raw GLB with a repeated
`--fixture` argument; the harness checks exact-weld proof, normalization,
protected-source integrity, idempotence, rollback, restore, target validation,
and rigging component analysis without copying the ignored assets into Git.

## Local Bones fixture test

The proprietary rig and target are not committed. When they are available,
run the Blender 5.1.2 regression directly:

```powershell
E:\Blender\blender.exe `
  "D:\Blender\Blends\baked animation rigged test model.blend" `
  --background --python scripts\run_rig_fixture_test.py -- `
  --target "D:\AI aRt\Models\skinandbones\retexturedfolsomsavage.glb" `
  --reference-glb "D:\AI aRt\Models\skinandbones\baked animation rigged test model.glb" `
  --addon addon `
  --forge-repo "E:\DeVForge\dreadstone_animation_forge"
```

This checks deterministic animation-neutral fingerprinting, state restore,
target analysis, exact names/hierarchy, preview replacement, saved correction
reapply, and byte-stable protected topology/vertex positions/UVs/material
slots. It also proves deterministic `DSB_SIMPLE_HANDS_V1` generation, exact
36-bone descendant exclusion, both retained hand bones and parents, donor
finger-weight merging, no removed deform groups, and unchanged source
Actions/NLA. Production coverage includes forced transaction rollback,
idempotent rebinding, all 21 production deform groups, one Armature modifier,
zero unweighted or non-normalized vertices, four maximum influences,
component/proxy cleanup, 14 pose tests, five filtered production Actions,
clean GLB reimport with no removed channels, and Dreadstone Animation Forge's
actual analyzer and required hand mapping.

The same fixture applies `RELAXED`, `OPEN_MAGIC`, and `GRIP_SHAFT` as finite,
distinct whole-hand alignments and verifies the optional shape-key names remain
reserved rather than required.

The legacy Skin texture-bake harness requires the local assets documented in
`reference_assets/README.md`. Do not claim complete Skin regression coverage
when those ignored fixtures are absent.

## Second-character gate

Before 1.0.0, run the same workflow on at least one unrelated SPAR3D human:

- Different body proportions and clothing.
- A different import orientation to exercise axis controls.
- Four standardized cardinal sources produced independently of Folsom.

The second-character result must require settings changes only, never add-on
source edits. No second SPAR3D fixture is included in the v1 handoff, so this
gate remains an external release requirement.
