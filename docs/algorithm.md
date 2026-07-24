# Projection and bake algorithm

## Coordinate frame and cameras

The user selects forward and up axes. With normalized forward vector `f` and
up vector `u`, character-right is:

```text
r = normalize(cross(f, u))
```

The cardinal outward view directions are `f`, `-f`, `-r`, and `r`. Optional
front-left and front-right directions are:

```text
normalize(f - r)
normalize(f + r)
```

Every orthographic camera looks at the world-space mesh bounding-box center.
Its default scale is:

```text
ortho_scale = character_height / 0.90
```

The scene is temporarily evaluated with a square render aspect before
calling `world_to_camera_view`, so camera UVs are predictable regardless of
the artist's render settings.

## Temporary data

The add-on creates:

- `SBF_ProjectionCamera_<view>` for four cardinal and two optional diagonal views
- `SBF_PROJ_<view>`
- `SBF_WEIGHT_<view>`
- `SBF_WEIGHT_head_mask`
- `SBF_Preview_<object>`

The original material slot and active UV name are recorded on the target and
restored during cleanup.

## Identity-priority weights

For a world-space corner point `p`, normal `n`, and view direction `d`:

```text
directional = max(0, dot(n, d))
```

Height is normalized along the chosen up axis. Front/back/diagonal biases
default to `3` below 0.58 height, `10` from 0.58 to 0.80, and `1.25` above
0.80. Side bias defaults to `1`. The head uses a later confidence step instead
of an extreme directional bias.

Top-facing surfaces receive positional front/back coverage:

```text
front_position = normalized coordinate along forward
hemisphere = front_position                  # front
hemisphere = 1 - front_position              # back
top_coverage = abs(dot(n, up)) * hemisphere * 0.90
directional = max(directional, top_coverage)
```

The geometric view weight is:

```text
(minimum_weight + bias * directional^exponent)
    * visibility
    * per_view_weight
```

Defaults are minimum `0.001` and exponent `4`.

SPAR3D may store several vertices at the same physical boundary point with
different fragment normals. For projection ownership only, the add-on
averages normals at positions within one millionth of the character size.
This removes triangular source changes without editing the mesh normals used
for shading or export.

## Occlusion rejection

For each enabled view, a ray begins outside the mesh at:

```text
origin = p + d * ray_distance
direction = -d
```

The point is visible only when the first hit belongs to the target and is
within `character_height * depth_tolerance` of `p`. The conservative default
checks both vertices and polygon centers. A corner receives the view only
when both tests pass.

The optional feather linearly fades near the tolerance boundary. Occluded
surfaces receive zero weight for that view. This prevents opaque arms and
hands in a side source from being stamped onto the torso or thigh behind
them.

Horizontal rays are tangent to the crown and underside of the jaw. In the
head mask only, top/bottom-facing coverage receives a conservative,
alpha-gated visibility fallback. This prevents the old atlas from appearing
as a white cap or jaw patch without opening hidden torso surfaces.

This release intentionally uses ray casting. Projection-resolution depth maps
remain a future optimization.

## Silhouette and facial alignment

Auto-fit measures each source silhouette and applies body scale, independent
horizontal fit, and offset. It then fits the upper head silhouette into a
separate live head transform.

Four user landmarks provide the missing internal facial frame:

```text
image-left eye center
image-right eye center
image-left mouth corner
image-right mouth corner
```

Front defines the reference eye-to-mouth scale and facial center relative to
its head bounds. Each other source receives a head-only similarity correction.
A profile may omit one hidden point; three points still correct center and
vertical scale. The body transform is never modified, and reapplying starts
from the stored auto-fit transform rather than accumulating edits.

## Shader blend and fallback

For every source, the regular body confidence is:

```text
alpha_weight = source_alpha * geometric_weight * alpha_threshold_mask
weighted_color = source_color * alpha_weight
```

The normalized result is:

```text
sum(weighted_color) / max(sum(alpha_weight), 0.0001)
```

Inside `SBF_WEIGHT_head_mask`, each source confidence is sharpened before
normalization:

```text
head_confidence = alpha_weight ^ head_blend_sharpness
head_color =
    sum(source_color * head_confidence)
    / max(sum(head_confidence), 0.0001)
```

The default sharpness is `3`. This produces a narrow transition among aligned
neighbors without blending several complete faces or cutting on polygon
boundaries.

Opaque black source backgrounds are keyed. If a projected point narrowly
misses the keyed silhouette, a second sample contracted toward the image
center supplies nearby valid edge color. The default source-edge padding is
`0.05`; it is used only when the primary sample is invalid.

When total coverage is at or below the default `0.01` fallback threshold, the
original SPAR3D base color is used. This avoids black gaps and does not invent
texture behind genuine source occlusions.

## Production bake

SPAR3D can duplicate exact boundary vertices across hundreds of fragments.
Baking into its original atlas therefore turns the result into tiny
low-resolution triangle islands. By default, the add-on:

1. Copies the mesh to a temporary unwrap object.
2. Welds only vertices within `0.000001` Blender units on that copy.
3. Generates broad Smart Project charts on the welded copy.
4. Transfers the UVs back by original polygon and loop correspondence.
5. Deletes the temporary object without changing production geometry.

The temporary preview emission is baked with Cycles into a new image using
`SBF_BaseColorUV`. The baked base-color node is explicitly bound to that UV.
Unconfigured normal and other PBR image nodes are explicitly bound to the
unchanged original UV. The material slot, hierarchy, transforms, vertices,
polygons, original UV coordinates, and normal image remain intact.
