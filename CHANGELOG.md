# Changelog

All notable changes follow semantic versioning.

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
