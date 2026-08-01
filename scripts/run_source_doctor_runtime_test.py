"""Blender 5.1.2 runtime regression for non-destructive source cleanup."""

from __future__ import annotations

from array import array
import hashlib
import json
from pathlib import Path
import sys

import bpy


repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root / "addon"))

import skin_and_bones_forge  # noqa: E402
from skin_and_bones_forge.constants import VIEW_NAMES  # noqa: E402
from skin_and_bones_forge.projection.source_processing import (  # noqa: E402
    process_source_plate,
    restore_original_source,
    validate_cleaned_source,
)


def fingerprint(image):
    values = array("f", [0.0]) * (image.size[0] * image.size[1] * image.channels)
    image.pixels.foreach_get(values)
    return hashlib.sha256(values.tobytes()).hexdigest()


skin_and_bones_forge.register()
try:
    settings = bpy.context.scene.sbf_settings
    for name in VIEW_NAMES:
        getattr(settings, name).enabled = name == "front"
    width = height = 64
    background = (0.1, 1.0, 0.25)
    foreground = (0.62, 0.31, 0.20)
    pixels = []
    for y in range(height):
        for x in range(width):
            inside = 18 <= x <= 45 and 8 <= y <= 55
            edge = inside and (x in {18, 45} or y in {8, 55})
            if edge:
                alpha = 0.45
                color = tuple(
                    background[channel] * 0.96 + foreground[channel] * 0.04
                    for channel in range(3)
                )
            elif inside:
                alpha = 1.0
                color = foreground
            else:
                alpha = 0.0
                color = background
            pixels.extend((*color, alpha))
    original = bpy.data.images.new(
        "SBF_Runtime_Original",
        width=width,
        height=height,
        alpha=True,
        float_buffer=False,
    )
    original.pixels.foreach_set(pixels)
    original.update()
    original_before = fingerprint(original)
    settings.front.image = original
    settings.trusted_mask_erosion = 32.0
    settings.rgb_extension_distance = 320.0
    settings.silhouette_confidence_width = 160.0
    settings.despill_strength = 1.0

    clean, metrics, changed = process_source_plate(settings, "front", force=True)
    if not changed or clean == original:
        raise RuntimeError("Source Doctor did not create a separate owned image")
    if fingerprint(original) != original_before:
        raise RuntimeError("Source Doctor modified the original image")
    if metrics["strong_matches_after"] != 0:
        raise RuntimeError("Strong background-matching edge pixels survived cleanup")
    if metrics["contamination_after"] >= metrics["contamination_before"]:
        raise RuntimeError("Synthetic green contamination was not measurably reduced")
    clean_fingerprint = fingerprint(clean)
    reused, reused_metrics, changed = process_source_plate(
        settings, "front", force=False
    )
    if changed or reused != clean or fingerprint(reused) != clean_fingerprint:
        raise RuntimeError("Repeated source processing was not idempotent")
    if reused_metrics != metrics:
        raise RuntimeError("Reused Source Doctor metrics changed")

    clean.scale(32, 32)
    try:
        validate_cleaned_source(settings.front, "front")
    except ValueError as exc:
        if "size mismatch" not in str(exc):
            raise
    else:
        raise RuntimeError("Owned-image size mismatch was not rejected")
    process_source_plate(settings, "front", force=True)

    unrelated = bpy.data.images.new("Artist_Unrelated_Image", 4, 4)
    restore_original_source(settings, "front")
    if original.name not in bpy.data.images or fingerprint(original) != original_before:
        raise RuntimeError("Restore Original removed or changed the source")
    if unrelated.name not in bpy.data.images:
        raise RuntimeError("Restore Original removed an unowned image")
    if settings.front.cleaned_image is not None:
        raise RuntimeError("Restore Original retained the owned cleaned pointer")

    print("SBF_SOURCE_DOCTOR_RUNTIME_RESULT")
    print(
        json.dumps(
            {
                "status": "PASS",
                "blender_version": bpy.app.version_string,
                "contamination_before": metrics["contamination_before"],
                "contamination_after": metrics["contamination_after"],
                "strong_matches_before": metrics["strong_matches_before"],
                "strong_matches_after": metrics["strong_matches_after"],
                "original_unchanged": True,
                "idempotent": True,
                "size_mismatch_rejected": True,
                "owned_cleanup_only": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
finally:
    skin_and_bones_forge.unregister()
