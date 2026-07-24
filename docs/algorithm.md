# Projection and bake algorithm

## Coordinate frame and cameras

The user selects forward and up axes. With normalized forward vector `f` and
up vector `u`, character-right is:

```text
r = normalize(cross(f, u))
```

The four outward view directions are `f`, `-f`, `-r`, and `r`. Every
orthographic camera looks at the world-space mesh bounding-box center. Its
default scale is:

```text
ortho_scale = character_height / 0.90
```

The scene is temporarily evaluated with a square render aspect before
calling `world_to_camera_view`, so camera UVs are predictable regardless of
the artist's render settings.

## Temporary data

The add-on creates:

- `SBF_ProjectionCamera_front/back/left/right`
- `SBF_PROJ_front/back/left/right`
- `SBF_WEIGHT_front/back/left/right`
- `SBF_Preview_<object>`

The original material slot and active UV name are recorded on the target and
restored during cleanup.

## Identity-priority weights

For a world-space corner point `p`, normal `n`, and view direction `d`:

```text
directional = max(0, dot(n, d))
```

Height is normalized along the chosen up axis. Front/back biases default to
`3` below 0.58 height, `10` from 0.58 to 0.75, and `40` above 0.75. Side bias
defaults to `1`.

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

This release intentionally uses ray casting. Projection-resolution depth
maps are planned for 0.2.0.

## Shader blend and fallback

For every source:

```text
alpha_weight = source_alpha * geometric_weight * alpha_threshold_mask
weighted_color = source_color * alpha_weight
```

The normalized result is:

```text
sum(weighted_color) / max(sum(alpha_weight), 0.0001)
```

When total coverage is at or below the default `0.01` fallback threshold, the
original SPAR3D base color is used. This avoids black gaps and does not invent
texture behind genuine source occlusions.

## Production bake

The temporary preview emission is baked with Cycles into a new image using
the original production UV. On success, only the base-color image is replaced.
The production material, normal image, material slot, hierarchy, transforms,
geometry, and UV layout remain intact.
