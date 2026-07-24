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
- Bake completion and requested texture dimensions.
- Original vertex/polygon counts in the Blender output.
- Original UV layer names.
- Normal image assignment.
- Temporary-data cleanup.
- Packed base color.
- Roughness `1.0` and normal strength `0.25`.
- Blender output reopen.
- GLB export and GLB re-import.

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
python scripts/build_release.py
```

The release ZIP must contain a single top-level `skin_and_bones_forge/`
package and no `__pycache__` or fixture assets.

## Second-character gate

Before 1.0.0, run the same workflow on at least one unrelated SPAR3D human:

- Different body proportions and clothing.
- A different import orientation to exercise axis controls.
- Four sources produced independently of Folsom.

The second-character result must require settings changes only, never add-on
source edits. No second SPAR3D fixture is included in the v1 handoff, so this
gate remains an external release requirement.
