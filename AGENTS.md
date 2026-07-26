# AGENTS.md — Skin & Bones Forge Repository Contract

This file governs all work in this repository. Read it completely before editing code, running tests, changing assets, or writing a plan.

## 1. Mandatory task startup

At the start of every task:

1. Read this `AGENTS.md`.
2. Run `git status --short` and do not overwrite unrelated user work.
3. Read the latest relevant code, tests, and documentation before proposing changes.
4. Inspect recent commits when the task may overlap recent work.
5. Identify the smallest complete vertical slice that solves the requested problem.
6. Begin implementation. Do not spend the task producing a large speculative architecture essay.

Direct user instructions override this file. More deeply nested `AGENTS.md` files override this file only inside their own directory trees.

## 2. Project mission

Skin & Bones Forge is a Blender **5.1.2** add-on that turns SPAR3D humanoid assets into production-ready Dreadstone Black characters by providing:

- SPAR3D mesh intake and validation;
- multi-view texture projection and baking;
- canonical humanoid skeleton analysis and fitting;
- deterministic production skinning;
- animation compatibility checks;
- rigged GLB export and clean-reimport validation;
- Dreadstone Animation Forge acceptance.

The add-on must remain usable by an artist through clear, ordered, mostly one-click workflow stages.

## 3. Current source of truth

Before changing behavior, read the relevant files:

- `README.md`
- `docs/workflow.md`
- `docs/rigging_workflow.md`
- `docs/troubleshooting.md`
- `addon/skin_and_bones_forge/constants.py`
- `addon/skin_and_bones_forge/properties.py`
- `addon/skin_and_bones_forge/operators/`
- `addon/skin_and_bones_forge/panels/`
- `addon/skin_and_bones_forge/projection/`
- `addon/skin_and_bones_forge/baking/`
- `addon/skin_and_bones_forge/export/`
- `addon/skin_and_bones_forge/validation/`
- `addon/skin_and_bones_forge/rigging/`
- `tests/`
- `scripts/validate_addon.py`
- `scripts/build_release.py`

Do not trust an old task prompt over the current repository. Confirm names, versions, paths, operators, properties, and contracts from the checked-out code.

## 4. Non-negotiable production contracts

### 4.1 Blender and packaging

- Supported Blender version: **5.1.2**.
- The installable ZIP must contain the top-level `skin_and_bones_forge` package.
- Operator IDs use the `sbf.` namespace.
- Registration and unregistration must remain symmetrical.
- A release is not complete until the built ZIP passes integrity and registration checks.

### 4.2 Canonical rig authority

- The known-good Animate Anything source `.blend` is the canonical rest-skeleton authority.
- The canonical source armature, reference mesh, parent-scale hierarchy, Actions, and NLA are immutable fixtures.
- Never apply transforms, rename bones, edit rest bones, overwrite Actions, or destructively clean the canonical source.
- The canonical contract contains 57 rest bones.
- Canonical fingerprints cover stable rest data and exclude Actions/NLA from the hash while inventorying them separately.
- Exact names and hierarchy are necessary but not sufficient: local rest orientation, roll, axes, and matrices must remain animation-compatible.

### 4.3 Production rig profile

The current production profile is `DSB_SIMPLE_HANDS_V1` unless the user explicitly authorizes a contract change.

- Retain both canonical hand bones.
- Exclude the verified 36 finger descendants.
- Final production skeleton: 21 retained bones.
- Do not silently reintroduce hidden finger bones.
- Do not change the profile because a pose looks unattractive.
- Hand aesthetics are secondary to structural correctness unless the task specifically targets hands.

Any intentional profile change requires:

- a versioned profile;
- migration-aware validation;
- updated Action filtering;
- updated export/reimport checks;
- updated Animation Forge acceptance;
- updated tests and documentation.

### 4.4 Character-space left and right

Left and right always mean the character’s anatomical left and right, never the viewer’s screen sides.

For a front-facing character:

- character-left appears on viewer-right;
- character-right appears on viewer-left.

Use the target’s declared forward/up axes to derive the lateral axis. Validate side assignment independently through landmarks, bone positions, vertex-group centroids, and isolated motion. A detected inversion is blocking.

### 4.5 Target asset preservation

After a production target is accepted, preserve unless the task explicitly authorizes otherwise:

- topology;
- vertex order;
- polygon order where relied upon;
- UV maps and loop UV values;
- material slots and per-face material indices;
- textures and image relationships;
- custom/split normals;
- vertex colors and generic attributes;
- shape keys;
- production object identity where required.

Do not remesh, decimate, boolean-union, dissolve, weld, or reorder an accepted production target as a side effect of rigging, baking, export, or validation.

The only planned exception is the dedicated **pre-bake SPAR3D Intake & Mesh Prep** stage. Its accepted cleaned result becomes the new authoritative base topology before texture baking, weights, shape keys, gore, or animation data exist.

### 4.6 Texture contract

- Preserve the original production UV and normal-map relationship.
- Base-color reprojection/baking may use a dedicated clean UV.
- Do not silently move normal or other PBR maps to the baked base-color UV.
- Temporary cameras, UVs, images, materials, and nodes must be owned, traceable, and removable.
- Failed bake or preview operations must restore scene and material state.
- A rigging change must not regress the Skin workflow.

### 4.7 Binding contract

Production binding must be deterministic and transactional.

Required final conditions:

- exactly one intended Armature modifier;
- Vertex Groups enabled;
- Bone Envelopes disabled;
- zero unweighted vertices;
- finite, non-negative weights;
- normalized sums within documented tolerance;
- no weights on non-deform bones;
- no more than four meaningful influences per vertex;
- no anatomically impossible dominant influences;
- no stale groups from a previous fit;
- no catastrophic deformation under isolated poses or accepted Actions.

Fragmented SPAR3D meshes must not be handled by blind bone heat as the sole production strategy. Prefer canonical donor transfer, component-aware validation/repair, and a temporary proxy fallback when needed.

If fitted bones, rest matrices, object transforms, parenting, or the production profile change, invalidate stale binding, Action-test, export, and acceptance results.

### 4.8 Animation compatibility

- Never rewrite canonical source Actions to hide a bad rig.
- Create clearly owned production-compatible Action copies.
- Filter only channels excluded by the versioned production profile.
- Preserve source frame ranges, markers, interpolation, and non-excluded channels.
- Canonical Action tests must evaluate actual deformation, not only channel-name existence.
- Dreadstone Animation Forge acceptance must call the real analyzer/operator where technically possible. Do not fake acceptance with a parallel name check.
- A visible exploding, tearing, remote, or severely stretching mesh is a failure even when an operator returns `FINISHED`.

## 5. SPAR3D Intake & Mesh Prep rules

When implementing or modifying the pre-bake intake stage:

- Preserve an untouched, protected raw source copy.
- Work on a Skin & Bones-owned production copy.
- Analyze before modifying.
- Prefer exact-position welding for SPAR3D seam-split vertices.
- Preserve face-corner UVs, material indices, corner/split normals, sharp boundaries, colors, and generic attributes.
- Do not use broad Merge by Distance as the automatic default.
- Do not voxel remesh, quad remesh, decimate, smooth, fill all holes, or boolean-union the production surface automatically.
- Remove only proven loose or degenerate elements and report each category.
- Validate before/after face count, area, volume, bounds, components, boundaries, manifoldness, winding, UVs, normals, and materials.
- Normalize the unrigged clean copy only after geometry validation.
- Default target height is 1.50 m unless current settings or the user specify otherwise.
- Apply transforms only while the clean character is unrigged.
- Ground feet at `Z = 0`, center laterally, and preserve the configured forward direction.
- On success, assign the clean object as the Skin & Bones target.
- On failure, remove only owned data and restore the previous scene state.

## 6. Blender implementation rules

### 6.1 State safety

Every nontrivial operator must preserve or intentionally restore relevant state:

- active object;
- selection;
- mode;
- current frame;
- pose/rest position;
- active Action;
- NLA state;
- parent and `matrix_parent_inverse`;
- object transforms;
- visibility and collections;
- material assignments;
- render engine/settings when changed;
- temporary data.

Use `try/finally` around stateful operations. A failed operation must not leave the scene half-mutated.

### 6.2 Data ownership

All temporary or generated data must have unambiguous Skin & Bones ownership through naming and/or custom properties.

Owned data includes temporary:

- objects;
- collections;
- meshes;
- armatures;
- Actions;
- NLA tracks;
- materials;
- images;
- UV layers;
- vertex groups;
- modifiers;
- reports.

Cleanup operators must delete only owned data. Never use broad name patterns that could remove artist data.

### 6.3 Coordinate spaces

Never mix local, object, armature, evaluated, and world space implicitly.

For every geometric or rigging computation, make the space explicit in variable names or nearby comments. Transform once, at a documented boundary. Avoid double-applying parent scale or object matrices.

Binding must prove that the mesh and armature are using the same rest/bind space.

### 6.4 Blender API discipline

- Prefer direct data API operations over context-sensitive `bpy.ops` where practical.
- When an operator is required, establish and restore its context explicitly.
- Use the evaluated dependency graph for evaluated geometry.
- Always pair `to_mesh()` with `to_mesh_clear()`.
- Avoid relying on viewport state for correctness.
- Avoid global scene searches when owned references or explicit arguments are available.
- Keep operations deterministic: stable sorting, stable naming, stable fingerprints, and no dependence on selection order unless documented.
- Make repeated execution idempotent. Do not accumulate duplicate helpers, modifiers, groups, Actions, images, or collections.

### 6.5 Error handling

- Fail loudly with a specific, actionable reason.
- Do not convert blocking errors into warnings to force pipeline progress.
- Do not catch broad exceptions without rollback and reporting.
- Do not silently choose among ambiguous meshes, armatures, materials, or Actions.
- Use explicit statuses such as `READY_*`, `NEEDS_*`, and `FAILED`.
- Persist machine-readable reports for complex analysis and validation.

## 7. Code organization

Keep modules focused. Add behavior to the appropriate package rather than expanding a single catch-all file.

Current major boundaries:

- `projection/`: cameras, projections, fitting, masks, preview materials;
- `baking/`: atlas baking and texture output;
- `export/`: save/export and delivery validation;
- `validation/`: target and material contracts;
- `rigging/contract.py`: canonical rest contract and fingerprinting;
- `rigging/analysis.py`: target/canonical analysis;
- `rigging/landmarks.py`: humanoid landmarks and correction handles;
- `rigging/fitting.py`: fitted skeleton construction;
- `rigging/validation.py`: fitted-rig validation;
- `rigging/profile.py`: versioned production-bone profile;
- `rigging/hands.py`: simplified-hand behavior;
- `rigging/weights.py`: donor transfer, fallback, cleanup, and weight validation;
- `rigging/poses.py`: isolated and torture-pose tests;
- `rigging/production.py`: finalization and production hierarchy;
- `rigging/compatibility.py`: Action/export/Animation Forge compatibility;
- `operators/`: thin Blender operator orchestration;
- `panels/`: ordered artist workflow UI;
- `properties.py`: persistent settings and status;
- `constants.py`: stable versioned constants.

If the checked-out tree differs, follow the current tree rather than this summary and update this file when the architecture intentionally changes.

Business logic belongs in testable core modules. Operators should validate context, call core functions, report results, and restore state. Panels should not contain business logic.

## 8. Change discipline

- Solve the requested problem, not adjacent hypothetical problems.
- Make the smallest coherent change that fully fixes the defect.
- Do not rewrite working systems without evidence.
- Do not modify Dreadstone Animation Forge unless the task explicitly includes that repository and the defect is proven there.
- Do not modify large binary fixtures.
- Do not commit generated `.blend`, GLB, render, cache, or reference assets unless explicitly requested.
- Do not add dependencies without a demonstrated need.
- Do not weaken an existing invariant because a fixture fails.
- Do not “fix” deformation by deleting components, hiding geometry, clamping vertices, or assigning all failures to root.
- Do not use fake or mocked acceptance when the actual Blender path is available.
- Do not make unrelated formatting changes.
- Do not amend or rewrite existing commits unless explicitly requested.

## 9. Required investigation for deformation bugs

For mesh explosions, severe stretching, or failed canonical Actions, inspect evidence before changing algorithms:

1. Reproduce in the supplied `.blend` or GLB.
2. Find the first failing Action and frame.
3. Compare mesh/armature local and world matrices.
4. Check parent, `matrix_parent_inverse`, modifier target, modifier count, Vertex Groups, and Bone Envelopes.
5. Compare retained bone names, hierarchy, roll, axes, and rest matrices with the canonical source.
6. Identify the worst displaced vertices and connected components.
7. Print their complete weights and dominant bones.
8. Run isolated pelvis, spine, arm, forearm, thigh, shin, hand, and foot tests.
9. Determine whether the cause is fitting, bind space, weights, Action mapping, or multiple defects.
10. Fix the root cause and add a regression that fails on the old behavior.

Do not declare success from a rest-pose screenshot.

## 10. Testing requirements

Run the narrowest relevant test during development, then the required repository checks before completion.

### 10.1 Always run

```bash
python scripts/validate_addon.py
python -m unittest discover -s tests -p "test_*.py"
python scripts/build_release.py
```

Also test the generated ZIP for integrity.

### 10.2 Blender runtime tests

Changes to Blender behavior require Blender **5.1.2** runtime validation.

Run the relevant fixture/harness for every changed subsystem. Examples include:

- target validation;
- projection preview;
- final bake;
- fitted skeleton generation;
- binding and rollback;
- weight validation;
- isolated/torture poses;
- canonical Actions;
- rigged GLB export;
- clean GLB reimport;
- Animation Forge analysis.

For the full Folsom reference workflow when fixtures are available:

```powershell
powershell -ExecutionPolicy Bypass -File tests/reference/run_reference_test.ps1 `
  -Blender E:\Blender\blender.exe `
  -Size 4096 `
  -RenderProofs
```

Use the actual Blender path in the environment.

If a required large fixture or external add-on is unavailable:

- run everything that is available;
- state exactly what was not run and why;
- do not claim full regression success.

### 10.3 Test quality

Tests must verify outcomes, not implementation strings alone.

For geometry/rigging work, assert numerical invariants such as:

- object and mesh counts;
- topology/vertex fingerprint where required;
- component and manifold statistics;
- UV/material preservation;
- exact bone list and hierarchy;
- bind-matrix consistency;
- weight normalization and influence limits;
- maximum deformation/bounds expansion;
- Action-channel resolution;
- export/reimport equivalence;
- actual Animation Forge analyzer result.

A script completing without exception is not enough.

## 11. Version and release synchronization

When a task changes the add-on version, update every current version authority, including at least:

- `addon/skin_and_bones_forge/__init__.py`
- `addon/skin_and_bones_forge/constants.py`
- `pyproject.toml`
- `scripts/validate_addon.py`
- README release filenames/text
- version-sensitive tests or manifests

Search the repository for the previous version and verify no unintended stale references remain.

Build output belongs in `dist/`. Report the ZIP path and SHA-256. Do not hand-assemble the release archive when `scripts/build_release.py` is available.

## 12. Documentation rules

Update documentation when artist workflow, buttons, settings, statuses, requirements, or output contracts change.

Keep documentation operational:

- exact button names;
- exact order;
- explicit blocking states;
- recovery steps;
- no promises for unimplemented features.

Do not replace implementation with documentation. Do not write several new planning documents when an existing workflow document should be updated.

## 13. Completion standard

A task is complete only when:

- the requested behavior is implemented;
- the original failure is reproduced or otherwise evidenced;
- the fix is tested in the correct environment;
- existing source assets remain unchanged;
- temporary data is cleaned;
- static tests pass;
- relevant Blender runtime tests pass;
- the release ZIP builds;
- remaining failures or unavailable fixtures are disclosed.

Final reports should be concise and contain:

1. root cause or implemented capability;
2. changed files;
3. important invariants preserved;
4. tests actually run and exact results;
5. tests not run and why;
6. release ZIP path and SHA-256 when requested;
7. commit SHA when requested;
8. remaining blockers or non-blocking debt.

Do not include a long diary of exploration.

## 14. Hard prohibitions

Never:

- claim a test passed when it was not run;
- claim an Animation Forge acceptance pass without calling its real path;
- modify canonical source assets in place;
- overwrite the user’s source `.blend`;
- destructively apply transforms to an already-rigged character;
- silently change canonical or production bone contracts;
- confuse viewer-left with anatomical left;
- keep stale weights after changing fit/rest transforms;
- leave Bone Envelopes enabled on the production Armature modifier;
- leave unweighted vertices;
- hide or delete exploding geometry to pass validation;
- broadly weld or remesh an accepted production target;
- remove UV seams or average corner normals during SPAR3D cleanup;
- leave temporary Actions, donors, proxies, objects, or collections behind;
- weaken validation to make a broken asset appear ready;
- spend the task on unrelated refactors or speculative prose.

## 15. Codex task behavior

For every Codex task in this repository:

- read this file before acting;
- inspect current code before relying on prompt assumptions;
- code first;
- use supplied fixtures;
- continue through implementation and testing;
- stop only for a genuine missing fixture, unavailable external dependency, permission failure, or irreducible ambiguity;
- report blockers precisely rather than guessing;
- keep the final response short and evidence-based.
