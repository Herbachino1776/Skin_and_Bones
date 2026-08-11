# Appearance Variant Family handoff

Skin & Bones Forge 2.2.0 exports each approved appearance as an ordinary
canonical rigged GLB plus one compact identity record. Dreadstone Animation
Forge may use the record to recognize several visual assets as the same
technical character. It must not infer animation or damage inheritance rules
that are not present in its own versioned contracts.

## Compatibility proof

One `family_id` is valid only while the stored technical-body SHA-256 matches
the current authoring body. The fingerprint schema is
`skin-and-bones-technical-body-v1` (`schema_version: 1`) and covers:

- the stable production-mesh ID;
- ordered local vertex coordinates, vertex count, edge/loop/polygon counts,
  ordered polygon vertex indices, and polygon order;
- every non-bake production UV name and ordered loop UV value, plus the
  `SBF_BaseColorUV` contract once the first bake creates it;
- the canonical fingerprint, canonical rig/contract versions, production
  profile, production fingerprint, ordered bone names/parents/deform flags,
  and ordered rest matrices;
- ordered normalized deform weights by vertex and bone name, plus the stored
  weight-validation status;
- target object world transform/scale and the declared +Y/+Z (or explicitly
  configured) coordinate axes.

Adding `SBF_BaseColorUV` during the first unapproved family bake is the only
automatic fingerprint adoption. It is accepted only when every other technical
field is byte-equivalent. Any later incompatible technical change marks all
variant approvals stale.

For two exports whose `family_id` and `technical_body_fingerprint` both match,
a downstream tool may safely assume identical mesh topology and vertex order,
production rig/rest hierarchy, production profile, bind weights, UV contract,
scale, and coordinate contract. It may share animation/damage authoring by its
own policy. It must treat base-color pixels, source projections, repair layers,
approval revision, variant display name, and export identity as
appearance-specific.

## GLB record

The glTF exporter writes `export_extras=true`. Both the character mesh node and
the armature node receive these scalar extras during export:

- `sbf_appearance_family_id`
- `sbf_appearance_variant_id`
- `sbf_technical_body_fingerprint`
- `sbf_appearance_family_handoff`

`sbf_appearance_family_handoff` is a compact JSON string with this exact shape:

```json
{
  "schema": "skin-and-bones-appearance-family-handoff-v1",
  "schema_version": 1,
  "family_schema": "skin-and-bones-appearance-family-v1",
  "family_schema_version": 1,
  "family_id": "stable UUID hex",
  "family_display_name": "Bandit Humanoid 01",
  "variant_id": "stable UUID hex",
  "variant_display_name": "Sooted",
  "export_identity": "bandit_humanoid_01_sooted",
  "technical_body_schema": "skin-and-bones-technical-body-v1",
  "technical_body_schema_version": 1,
  "technical_body_fingerprint": "SHA-256 hex",
  "appearance_revision": 7,
  "approval": {
    "state": "APPROVED",
    "approved_revision": 7,
    "appearance_fingerprint": "SHA-256 hex",
    "approved_at_utc": "RFC 3339 timestamp",
    "addon_version": "2.2.0"
  }
}
```

The sibling `<asset>.glb.sbf.json` rigging manifest contains the same object at
top-level key `appearance_family`, alongside the existing canonical rig,
weight, reimport, and Animation Forge acceptance fields. Projection-session
landmarks, source paths, caches, masks, and image pixels are deliberately not
included in the GLB handoff.

## Consumer algorithm

1. Read the mesh or armature extras. JSON-decode
   `sbf_appearance_family_handoff` and require the handoff/schema versions above.
2. Verify the scalar family/variant/fingerprint extras equal the decoded values.
3. Group assets only when both `family_id` and
   `technical_body_fingerprint` match.
4. Use `variant_id` as portable appearance identity and `export_identity` as
   the human/file-facing key. Do not use Blender object or image names as IDs.
5. Require `approval.state == "APPROVED"` and
   `approval.approved_revision == appearance_revision` for production ingest.
6. Keep animation, Damage Keys, Progressive Damage Sites, offensive Actions,
   and runtime timing under Animation Forge ownership. This record proves
   technical compatibility only; it does not implement inheritance.

If the handoff is absent, treat the GLB as a legacy standalone character. If
the family matches but the technical fingerprint differs, treat it as a
different/incompatible technical body and require explicit artist migration.
