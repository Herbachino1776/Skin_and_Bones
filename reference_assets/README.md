# Local reference fixtures

The large Folsom assets are intentionally excluded from Git. Restore them
from `Skin_and_Bones_Forge_Handoff_V1.zip` so this directory contains:

```text
folsomsavage_original.blend
folsomsavage_retextured_v7.blend
folsomsavage_retextured_v7.glb
folsomsavage_rebuilt_base_color_4096_v7.png
folsom_bandit_1_source_4k.png
projection_views/
  front_projection.png
  back_projection.png
  left_projection.png
  right_projection.png
```

The regression harness resolves these paths relative to the repository and
does not depend on the original Dread Stone Black workspace.

Do not commit these binaries without an intentional Git LFS or release-asset
policy.
