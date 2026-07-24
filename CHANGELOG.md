# Changelog

All notable changes follow semantic versioning.

## 0.2.0 - 2026-07-23

### Added

- Live preview updates for source image, flip, scale, offset, alpha threshold,
  black-background keying, enable state, and overall weight controls.
- Alpha-silhouette source auto-fit with bulk 4K pixel analysis.
- Zoomable per-source facial landmark calibration for eye centers and mouth
  corners, including three-point support for a hidden profile landmark.
- Optional front-left and front-right 45-degree source slots and projection
  cameras while retaining the four-cardinal workflow.
- Identity-safe confidence blending in the head region, with adjustable
  sharpness and no hard per-polygon source cuts.
- Source-edge padding and tangent-surface fallback for scalp, jaw, and shoulder
  coverage without exposing pale remnants of the old atlas.
- Lateral head isolation so raised shoulders do not enter the identity lock.
- Eight close head-orbit verification angles at 30, 45, 60, and 90 degrees.
- Collapsible workflow panels and individually collapsible source-view cards.
- A dedicated clean base-color UV bake path that temporarily welds exact
  SPAR3D fragment duplicates for unwrapping, then copies the atlas back
  without changing production geometry or the original UV.

### Changed

- Projection transforms now live in preview shader nodes instead of baked
  camera UVs, avoiding expensive ray-cast rebuilds during alignment.
- The SPAR3D preset enables head protection, live alignment, and silhouette
  edge padding by default.
- The Folsom regression now isolates repository code from any user-installed
  add-on and asserts live shader updates, head-only landmark correction,
  three-point profile calibration, body-transform isolation, and idempotent
  calibration reapply.

### Fixed

- Removed the multi-face/four-ear blend produced by overlapping uncalibrated
  cardinal photographs.
- Removed the large stretched or pale source-boundary patches seen around the
  side of the head and shoulders.
- Removed the post-bake triangle mosaic caused by SPAR3D's fragmented original
  UV atlas while retaining that UV for the normal and other PBR textures.
- Smoothed projection ownership across exact duplicate fragment positions
  without changing the production mesh normals.

## 0.1.1 - 2026-07-23

### Fixed

- Added an explicit **Open Image from Disk...** file browser to every front,
  back, character-left, and character-right source slot.
- Kept the existing image datablock selector as a clearly labeled **Loaded**
  field for reusing images already present in the Blender file.
- Exercised disk image loading through the Blender Folsom regression.

## 0.1.0 - 2026-07-23

### Added

- Installable Blender 5.1.2 add-on and 3D Viewport sidebar workflow.
- Target, material, base-color, normal-map, and production-UV validation.
- Four configurable RGBA projection views with axis controls, per-view
  transforms, alpha thresholds, weights, and occlusion toggles.
- Orthographic camera fitting and temporary camera-projection UV maps.
- Height-aware front/back identity priority and top-surface coverage.
- Conservative polygon-center plus vertex first-surface ray visibility.
- Non-destructive projection preview with original-atlas fallback.
- 1024, 2048, 4096, and 8192 EMIT bake targets.
- Adjustable roughness, normal strength, smoothing, image packing, and margin.
- Temporary-data cleanup, save-copy, GLB export, and JSON processing manifests.
- Nine-view verification renderer.
- Folsom Blender/GLB regression and output-inspection scripts.
- Versioned release ZIP builder and documentation.
- Deterministic GitHub Actions packaging on every `main` push, with the
  installable ZIP retained as a downloadable workflow artifact for 30 days.
