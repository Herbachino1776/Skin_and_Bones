"""Deterministic, testable texture-repair algorithms.

The functions in this module deliberately have no Blender dependency.  Blender
image ownership, mesh ray casting, and UI orchestration live in
``repair_service``; this module owns pixel math and UV/tangent contracts.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass

import numpy as np


REPAIR_SCHEMA = "skin-and-bones-texture-repair-v1"

DIRECT_PROJECTION = 1
ORIGINAL_ATLAS_FALLBACK = 2
CLONE = 3
HEAL = 4
SMART_FILL = 5
SEAM_HEAL = 6
UNRESOLVED = 7

CLASSIFICATION_NAMES = {
    DIRECT_PROJECTION: "DIRECT_PROJECTION",
    ORIGINAL_ATLAS_FALLBACK: "ORIGINAL_ATLAS_FALLBACK",
    CLONE: "CLONE",
    HEAL: "HEAL",
    SMART_FILL: "SMART_FILL",
    SEAM_HEAL: "SEAM_HEAL",
    UNRESOLVED: "UNRESOLVED",
}

CLASSIFICATION_COLORS = {
    DIRECT_PROJECTION: (0.10, 0.75, 0.20, 1.0),
    ORIGINAL_ATLAS_FALLBACK: (0.20, 0.45, 1.00, 1.0),
    CLONE: (0.00, 0.90, 1.00, 1.0),
    HEAL: (0.75, 0.25, 1.00, 1.0),
    SMART_FILL: (1.00, 0.65, 0.00, 1.0),
    SEAM_HEAL: (1.00, 0.95, 0.00, 1.0),
    UNRESOLVED: (1.00, 0.00, 0.10, 1.0),
}

OPPOSITE_PARTS = {
    2: 3,  # arm_left / arm_right
    3: 2,
    5: 6,  # leg_left / leg_right
    6: 5,
    "left_arm": "right_arm",
    "right_arm": "left_arm",
    "left_leg": "right_leg",
    "right_leg": "left_leg",
}


def _as_float_image(image):
    values = np.asarray(image, dtype=np.float32)
    if values.ndim != 3 or values.shape[2] not in {1, 3, 4}:
        raise ValueError("Expected an H x W scalar, RGB, or RGBA image.")
    return values


def composite_corrections(
    baked,
    corrections,
    correction_mask,
    *,
    enabled=True,
    opacity=1.0,
):
    """Return ``mix(Baked, Corrections, CorrectionMask)`` without mutation."""

    base = _as_float_image(baked)
    repair = _as_float_image(corrections)
    if base.shape != repair.shape:
        raise ValueError("Baked and correction images must have matching shapes.")
    mask = np.asarray(correction_mask, dtype=np.float32)
    if mask.ndim == 3:
        mask = mask[:, :, 0]
    if mask.shape != base.shape[:2]:
        raise ValueError("Correction mask must match the image dimensions.")
    amount = np.clip(mask, 0.0, 1.0)
    if not enabled:
        amount = np.zeros_like(amount)
    amount = np.clip(amount * float(opacity), 0.0, 1.0)[:, :, None]
    result = base * (1.0 - amount) + repair * amount
    if result.shape[2] == 4:
        # The base atlas owns alpha.  Repairs are an RGB-only production layer.
        result[:, :, 3] = base[:, :, 3]
    return np.clip(result, 0.0, 1.0).astype(np.float32, copy=False)


def repair_fingerprint(vertices, polygons, loop_uvs, atlas_size, uv_name):
    """Hash topology, vertex order, production UV corners, and atlas size."""

    digest = hashlib.sha256()
    digest.update(REPAIR_SCHEMA.encode("ascii"))
    digest.update(str(uv_name).encode("utf-8"))
    digest.update(struct.pack("<II", int(atlas_size[0]), int(atlas_size[1])))
    for vertex in vertices:
        digest.update(struct.pack("<3d", *(float(value) for value in vertex)))
    digest.update(b"\0POLYGONS\0")
    for polygon in polygons:
        values = tuple(int(value) for value in polygon)
        digest.update(struct.pack("<I", len(values)))
        digest.update(struct.pack(f"<{len(values)}I", *values))
    digest.update(b"\0UV\0")
    for uv in loop_uvs:
        digest.update(struct.pack("<2d", float(uv[0]), float(uv[1])))
    return digest.hexdigest()


def repair_state_is_compatible(stored_fingerprint, current_fingerprint):
    return bool(stored_fingerprint) and stored_fingerprint == current_fingerprint


def image_fingerprint(image):
    values = np.asarray(image, dtype=np.float32)
    return hashlib.sha256(values.tobytes(order="C")).hexdigest()


def rotation_matrix(angle_radians):
    cosine = math.cos(float(angle_radians))
    sine = math.sin(float(angle_radians))
    return np.array(((cosine, -sine), (sine, cosine)), dtype=np.float64)


def map_tangent_clone_offsets(
    target_uv_offsets,
    source_uv,
    source_tangent_to_uv,
    target_tangent_to_uv,
    *,
    scale=1.0,
    rotation=0.0,
):
    """Map target UV offsets into a source island through surface tangent space.

    Each 2x2 basis maps a column tangent-space displacement to a UV
    displacement.  Consequently a brush remains oriented on the surface even
    when the source and target UV islands have different rotations.
    """

    offsets = np.asarray(target_uv_offsets, dtype=np.float64)
    if offsets.shape[-1] != 2:
        raise ValueError("UV offsets must end with two coordinates.")
    source_basis = np.asarray(source_tangent_to_uv, dtype=np.float64).reshape(2, 2)
    target_basis = np.asarray(target_tangent_to_uv, dtype=np.float64).reshape(2, 2)
    determinant = float(np.linalg.det(target_basis))
    if abs(determinant) <= 1.0e-12:
        raise ValueError("Target tangent/UV basis is singular.")
    if abs(float(np.linalg.det(source_basis))) <= 1.0e-12:
        raise ValueError("Source tangent/UV basis is singular.")
    local = offsets @ np.linalg.inv(target_basis).T
    local = local @ rotation_matrix(rotation).T
    local *= float(scale)
    mapped = local @ source_basis.T
    return mapped + np.asarray(source_uv, dtype=np.float64)


def bilinear_sample(image, uv):
    pixels = _as_float_image(image)
    coordinates = np.asarray(uv, dtype=np.float64)
    original_shape = coordinates.shape[:-1]
    flat = coordinates.reshape(-1, 2)
    height, width = pixels.shape[:2]
    x = np.clip(flat[:, 0], 0.0, 1.0) * max(width - 1, 1)
    y = np.clip(flat[:, 1], 0.0, 1.0) * max(height - 1, 1)
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    tx = (x - x0)[:, None]
    ty = (y - y0)[:, None]
    top = pixels[y0, x0] * (1.0 - tx) + pixels[y0, x1] * tx
    bottom = pixels[y1, x0] * (1.0 - tx) + pixels[y1, x1] * tx
    result = top * (1.0 - ty) + bottom * ty
    return result.reshape(original_shape + (pixels.shape[2],))


def _box_blur_axis(values, radius, axis):
    if radius <= 0:
        return values.copy()
    pad = [(0, 0)] * values.ndim
    pad[axis] = (radius, radius)
    padded = np.pad(values, pad, mode="edge")
    cumulative = np.cumsum(padded, axis=axis, dtype=np.float64)
    zero_shape = list(cumulative.shape)
    zero_shape[axis] = 1
    cumulative = np.concatenate(
        (np.zeros(zero_shape, dtype=np.float64), cumulative), axis=axis
    )
    width = radius * 2 + 1
    high = [slice(None)] * values.ndim
    low = [slice(None)] * values.ndim
    high[axis] = slice(width, None)
    low[axis] = slice(None, -width)
    return (cumulative[tuple(high)] - cumulative[tuple(low)]) / float(width)


def box_blur(image, radius):
    values = np.asarray(image, dtype=np.float32)
    radius = max(0, int(radius))
    if radius == 0:
        return values.copy()
    horizontal = _box_blur_axis(values, radius, 1)
    return _box_blur_axis(horizontal, radius, 0).astype(np.float32)


def frequency_separated_heal(
    source,
    target,
    *,
    detail_preservation=0.85,
    low_frequency_radius=4,
):
    """Combine source high-frequency detail with target low-frequency color."""

    source_values = _as_float_image(source)
    target_values = _as_float_image(target)
    if source_values.shape != target_values.shape:
        raise ValueError("Heal source and target must have matching shapes.")
    source_low = box_blur(source_values, low_frequency_radius)
    target_low = box_blur(target_values, low_frequency_radius)
    high = source_values - source_low
    result = target_low + high * float(detail_preservation)
    if result.shape[2] == 4:
        result[:, :, 3] = target_values[:, :, 3]
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def brush_falloff(distances, radius, hardness):
    radius = max(float(radius), 1.0e-6)
    hardness = np.clip(float(hardness), 0.0, 1.0)
    inner = radius * hardness
    distances = np.asarray(distances, dtype=np.float32)
    if inner >= radius - 1.0e-6:
        return (distances <= radius).astype(np.float32)
    transition = np.clip((distances - inner) / (radius - inner), 0.0, 1.0)
    smooth = transition * transition * (3.0 - 2.0 * transition)
    return np.where(distances <= inner, 1.0, 1.0 - smooth) * (
        distances <= radius
    )


@dataclass(frozen=True)
class StrokeResult:
    changed_pixels: int
    rejected_pixels: int
    bounds: tuple[int, int, int, int]


def apply_surface_stroke(
    baked,
    corrections,
    correction_mask,
    classification,
    *,
    source_uv,
    target_uv,
    source_tangent_to_uv,
    target_tangent_to_uv,
    radius,
    hardness,
    opacity,
    mode="CLONE",
    source_scale=1.0,
    source_rotation=0.0,
    detail_preservation=0.85,
    low_frequency_radius=4,
    donor_allowed=None,
    target_allowed=None,
):
    """Apply one circular Clone or Heal dab to non-destructive layers."""

    base = _as_float_image(baked)
    repair = _as_float_image(corrections)
    mask = np.asarray(correction_mask, dtype=np.float32)
    classes = np.asarray(classification)
    if mask.ndim == 3:
        mask_values = mask[:, :, 0]
    else:
        mask_values = mask
    height, width = base.shape[:2]
    center_x = float(target_uv[0]) * max(width - 1, 1)
    center_y = float(target_uv[1]) * max(height - 1, 1)
    pixel_radius = max(1.0, float(radius))
    x0 = max(0, int(math.floor(center_x - pixel_radius)))
    x1 = min(width, int(math.ceil(center_x + pixel_radius)) + 1)
    y0 = max(0, int(math.floor(center_y - pixel_radius)))
    y1 = min(height, int(math.ceil(center_y + pixel_radius)) + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    distance = np.hypot(xx - center_x, yy - center_y)
    weight = brush_falloff(distance, pixel_radius, hardness)
    weight *= np.clip(float(opacity), 0.0, 1.0)
    if target_allowed is not None:
        weight *= np.asarray(target_allowed, dtype=bool)[y0:y1, x0:x1]

    offsets = np.stack(
        (
            (xx - center_x) / max(width - 1, 1),
            (yy - center_y) / max(height - 1, 1),
        ),
        axis=-1,
    )
    source_coordinates = map_tangent_clone_offsets(
        offsets,
        source_uv,
        source_tangent_to_uv,
        target_tangent_to_uv,
        scale=source_scale,
        rotation=source_rotation,
    )
    inside_source = (
        (source_coordinates[:, :, 0] >= 0.0)
        & (source_coordinates[:, :, 0] <= 1.0)
        & (source_coordinates[:, :, 1] >= 0.0)
        & (source_coordinates[:, :, 1] <= 1.0)
    )
    if donor_allowed is not None:
        donor = np.asarray(donor_allowed, dtype=np.float32)
        donor_samples = bilinear_sample(
            donor[:, :, None], source_coordinates
        )[:, :, 0]
        inside_source &= donor_samples >= 0.999
    rejected = int(np.count_nonzero((weight > 0.0) & ~inside_source))
    weight *= inside_source
    active = weight > 1.0e-6
    if not np.any(active):
        return StrokeResult(0, rejected, (x0, y0, x1, y1))

    source_samples = bilinear_sample(base, source_coordinates)
    mode = str(mode).upper()
    if mode == "HEAL":
        low_source = box_blur(base, low_frequency_radius)
        low_target = box_blur(base, low_frequency_radius)[y0:y1, x0:x1]
        source_low_samples = bilinear_sample(low_source, source_coordinates)
        desired = low_target + (
            source_samples - source_low_samples
        ) * float(detail_preservation)
        class_value = HEAL
    elif mode == "CLONE":
        desired = source_samples
        class_value = CLONE
    else:
        raise ValueError(f"Unsupported incremental repair mode: {mode}")
    desired = np.clip(desired, 0.0, 1.0)

    old_mask = mask_values[y0:y1, x0:x1]
    base_patch = base[y0:y1, x0:x1]
    repair_patch = repair[y0:y1, x0:x1]
    old_final = base_patch * (1.0 - old_mask[:, :, None]) + repair_patch * (
        old_mask[:, :, None]
    )
    amount = weight[:, :, None]
    new_final = old_final * (1.0 - amount) + desired * amount
    new_mask = 1.0 - (1.0 - old_mask) * (1.0 - weight)
    divisor = np.maximum(new_mask[:, :, None], 1.0e-8)
    new_repair = (new_final - base_patch * (1.0 - new_mask[:, :, None])) / divisor
    repair_patch[active] = np.clip(new_repair[active], 0.0, 1.0)
    if repair.shape[2] == 4:
        repair_patch[:, :, 3][active] = 1.0
    old_mask[active] = new_mask[active]
    classes[y0:y1, x0:x1][active] = class_value
    return StrokeResult(int(np.count_nonzero(active)), rejected, (x0, y0, x1, y1))


def known_diagnostic_mask(image, coverage=None, tolerance=1.0e-4):
    """Find exact pipeline diagnostic colors, not ordinary white clothing."""

    values = _as_float_image(image)
    rgb = values[:, :, :3]
    result = np.zeros(rgb.shape[:2], dtype=bool)
    for color in ((1.0, 0.0, 1.0), (0.0, 1.0, 0.0), (0.0, 1.0, 1.0)):
        result |= np.max(
            np.abs(rgb - np.asarray(color, dtype=np.float32)), axis=2
        ) <= float(tolerance)
    if coverage is not None:
        result &= np.asarray(coverage, dtype=bool)
    return result


def detect_unresolved(image, coverage, direct_confidence=None):
    """Detect honest atlas holes while avoiding bright, genuinely white cloth."""

    values = _as_float_image(image)
    rgb = values[:, :, :3]
    covered = np.asarray(coverage, dtype=bool)
    chroma = np.max(rgb, axis=2) - np.min(rgb, axis=2)
    exact_white = (np.min(rgb, axis=2) >= 0.9995) & (chroma <= 0.0005)
    transparent = values[:, :, 3] <= 0.001 if values.shape[2] == 4 else False
    unresolved = covered & (exact_white | transparent | known_diagnostic_mask(values))
    if direct_confidence is not None:
        confidence = np.asarray(direct_confidence, dtype=np.float32)
        unresolved &= confidence < 0.05
    return unresolved


def initial_classification(coverage, direct_confidence, unresolved=None):
    covered = np.asarray(coverage, dtype=bool)
    confidence = np.asarray(direct_confidence, dtype=np.float32)
    if covered.shape != confidence.shape:
        raise ValueError("Coverage and direct confidence must have matching shapes.")
    result = np.zeros(covered.shape, dtype=np.uint8)
    result[covered & (confidence >= 0.05)] = DIRECT_PROJECTION
    result[covered & (confidence < 0.05)] = ORIGINAL_ATLAS_FALLBACK
    if unresolved is not None:
        result[np.asarray(unresolved, dtype=bool)] = UNRESOLVED
    return result


def classification_rgba(classification, *, alpha_outside=0.0):
    classes = np.asarray(classification, dtype=np.uint8)
    result = np.zeros(classes.shape + (4,), dtype=np.float32)
    result[:, :, 3] = float(alpha_outside)
    for value, color in CLASSIFICATION_COLORS.items():
        result[classes == value] = color
    return result


def _shift(values, dy, dx, fill):
    result = np.full_like(values, fill)
    source_y = slice(max(0, -dy), min(values.shape[0], values.shape[0] - dy))
    source_x = slice(max(0, -dx), min(values.shape[1], values.shape[1] - dx))
    target_y = slice(max(0, dy), min(values.shape[0], values.shape[0] + dy))
    target_x = slice(max(0, dx), min(values.shape[1], values.shape[1] + dx))
    result[target_y, target_x] = values[source_y, source_x]
    return result


def _frontier(remaining):
    remaining = np.asarray(remaining, dtype=bool)
    adjacent_safe = np.zeros_like(remaining)
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        adjacent_safe |= ~_shift(remaining, dy, dx, True)
    return remaining & adjacent_safe


def normalized_distance_from_mask(mask, max_distance=32):
    """Return deterministic 0..1 distance from forbidden/contaminated pixels."""

    source = np.asarray(mask, dtype=bool)
    limit = max(1, int(max_distance))
    distance = np.full(source.shape, limit, dtype=np.float32)
    distance[source] = 0.0
    reached = source.copy()
    frontier = source.copy()
    for step in range(1, limit + 1):
        expanded = np.zeros_like(source)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            expanded |= _shift(frontier, dy, dx, False)
        frontier = expanded & ~reached
        if not np.any(frontier):
            break
        distance[frontier] = float(step)
        reached |= frontier
    return distance / float(limit)


def _neighbor_descriptor(image, remaining):
    rgb = image[:, :, :3]
    total = np.zeros_like(rgb, dtype=np.float32)
    count = np.zeros(remaining.shape, dtype=np.float32)
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        neighbor_remaining = _shift(remaining, dy, dx, True)
        valid = ~neighbor_remaining
        total += _shift(rgb, dy, dx, 0.0) * valid[:, :, None]
        count += valid
    return total / np.maximum(count[:, :, None], 1.0)


def _gradient_descriptor(image):
    luminance = (
        image[:, :, 0] * 0.2126
        + image[:, :, 1] * 0.7152
        + image[:, :, 2] * 0.0722
    )
    gy, gx = np.gradient(luminance.astype(np.float32))
    magnitude = np.hypot(gx, gy)
    angle = np.arctan2(gy, gx)
    return magnitude, angle


def _policy_mask(
    target_semantic,
    target_material,
    donor_semantics,
    donor_materials,
    donor_artist,
    policy,
    opposite_parts,
):
    same_part = donor_semantics == target_semantic
    same_material = donor_materials == target_material
    opposite = opposite_parts.get(target_semantic)
    opposite_part = (
        donor_semantics == opposite
        if opposite is not None
        else np.zeros_like(same_part)
    )
    policy = str(policy).upper()
    if policy == "SAME_PART":
        return same_part & same_material
    if policy == "OPPOSITE_SYMMETRIC_PART":
        return opposite_part & same_material
    if policy == "SAME_MATERIAL":
        # Material slots are frequently shared by all skin.  Never let that
        # turn a hand/arm into an automatic thigh or torso donor.
        return same_material & (same_part | opposite_part)
    if policy == "ARTIST_PAINTED_DONOR_MASK":
        return donor_artist & same_material & (same_part | opposite_part)
    if policy == "COMBINED_SAFE_SOURCES":
        return same_material & (same_part | opposite_part)
    raise ValueError(f"Unknown Smart Fill source policy: {policy}")


def smart_fill_masked(
    image,
    target_mask,
    donor_mask,
    semantic_map,
    material_map,
    *,
    source_policy="COMBINED_SAFE_SOURCES",
    artist_donor_mask=None,
    forbidden_mask=None,
    confidence=None,
    contamination_distance=None,
    opposite_parts=None,
    max_candidates=96,
    max_pixels=250_000,
):
    """Deterministically synthesize only a supplied mask, boundary inward.

    Candidate descriptors combine boundary color, local texture, edge
    orientation, confidence, spatial distance, and distance from contamination.
    Donor pixels are always sampled from the original safe donor set; newly
    filled pixels provide boundary context but never become unrelated donors.
    """

    values = _as_float_image(image).copy()
    target = np.asarray(target_mask, dtype=bool).copy()
    donors = np.asarray(donor_mask, dtype=bool).copy()
    semantics = np.asarray(semantic_map)
    materials = np.asarray(material_map)
    if target.shape != values.shape[:2] or donors.shape != target.shape:
        raise ValueError("Smart Fill masks must match the image dimensions.")
    if semantics.shape != target.shape or materials.shape != target.shape:
        raise ValueError("Semantic/material maps must match the image dimensions.")
    forbidden = (
        np.zeros_like(target)
        if forbidden_mask is None
        else np.asarray(forbidden_mask, dtype=bool)
    )
    artist = (
        np.zeros_like(target)
        if artist_donor_mask is None
        else np.asarray(artist_donor_mask, dtype=bool)
    )
    donor_confidence = (
        np.ones(target.shape, dtype=np.float32)
        if confidence is None
        else np.asarray(confidence, dtype=np.float32)
    )
    safe_distance = (
        np.ones(target.shape, dtype=np.float32)
        if contamination_distance is None
        else np.asarray(contamination_distance, dtype=np.float32)
    )
    donors &= ~target & ~forbidden & (semantics >= 0) & (materials >= 0)
    requested = int(np.count_nonzero(target))
    if requested > int(max_pixels):
        raise ValueError(
            f"Smart Fill mask contains {requested:,} pixels; limit is "
            f"{int(max_pixels):,}. Split it into smaller explicit masks."
        )

    original = values.copy()
    donor_y, donor_x = np.nonzero(donors)
    donor_rgb = original[donor_y, donor_x, :3]
    donor_semantics = semantics[donor_y, donor_x]
    donor_materials = materials[donor_y, donor_x]
    donor_artist = artist[donor_y, donor_x]
    donor_quality = donor_confidence[donor_y, donor_x]
    donor_safe_distance = safe_distance[donor_y, donor_x]
    gradient_magnitude, gradient_angle = _gradient_descriptor(original)
    donor_gradient = gradient_magnitude[donor_y, donor_x]
    donor_angle = gradient_angle[donor_y, donor_x]
    opposite_parts = opposite_parts or OPPOSITE_PARTS

    remaining = target.copy()
    filled_mask = np.zeros_like(target)
    rejected = 0
    height, width = target.shape
    diagonal = max(math.hypot(width, height), 1.0)
    while np.any(remaining):
        frontier = _frontier(remaining)
        if not np.any(frontier):
            break
        boundary_rgb = _neighbor_descriptor(values, remaining)
        frontier_y, frontier_x = np.nonzero(frontier)
        progress = 0
        groups = sorted(
            {
                (semantics[y, x].item(), materials[y, x].item())
                for y, x in zip(frontier_y, frontier_x, strict=True)
            },
            key=lambda item: (str(item[0]), str(item[1])),
        )
        for target_semantic, target_material in groups:
            group = (
                frontier
                & (semantics == target_semantic)
                & (materials == target_material)
            )
            gy, gx = np.nonzero(group)
            permitted = _policy_mask(
                target_semantic,
                target_material,
                donor_semantics,
                donor_materials,
                donor_artist,
                source_policy,
                opposite_parts,
            )
            candidates = np.flatnonzero(permitted)
            if candidates.size == 0:
                rejected += int(gy.size)
                continue
            order = np.lexsort((donor_x[candidates], donor_y[candidates]))
            candidates = candidates[order]
            if candidates.size > int(max_candidates):
                selection = np.linspace(
                    0, candidates.size - 1, int(max_candidates), dtype=np.int64
                )
                candidates = candidates[selection]
            candidate_rgb = donor_rgb[candidates]
            candidate_y = donor_y[candidates]
            candidate_x = donor_x[candidates]
            candidate_gradient = donor_gradient[candidates]
            candidate_angle = donor_angle[candidates]
            candidate_quality = donor_quality[candidates]
            candidate_safe = donor_safe_distance[candidates]
            for start in range(0, gy.size, 1024):
                end = min(start + 1024, gy.size)
                ty = gy[start:end]
                tx = gx[start:end]
                context_rgb = boundary_rgb[ty, tx, :3]
                color_score = np.mean(
                    (context_rgb[:, None, :] - candidate_rgb[None, :, :]) ** 2,
                    axis=2,
                )
                target_gradient = gradient_magnitude[ty, tx]
                target_angle = gradient_angle[ty, tx]
                texture_score = np.abs(
                    target_gradient[:, None] - candidate_gradient[None, :]
                )
                angle_delta = np.abs(
                    np.angle(
                        np.exp(
                            1j
                            * (
                                target_angle[:, None]
                                - candidate_angle[None, :]
                            )
                        )
                    )
                ) / math.pi
                distance_score = np.hypot(
                    ty[:, None] - candidate_y[None, :],
                    tx[:, None] - candidate_x[None, :],
                ) / diagonal
                score = (
                    color_score
                    + texture_score * 0.15
                    + angle_delta * 0.04
                    + distance_score * 0.05
                    + (1.0 - candidate_quality[None, :]) * 0.20
                    + (1.0 - candidate_safe[None, :]) * 0.15
                )
                chosen = candidates[np.argmin(score, axis=1)]
                values[ty, tx, :3] = donor_rgb[chosen]
                if values.shape[2] == 4:
                    values[ty, tx, 3] = 1.0
                remaining[ty, tx] = False
                filled_mask[ty, tx] = True
                progress += int(ty.size)
        if progress == 0:
            break

    return {
        "image": values,
        "filled_mask": filled_mask,
        "filled": int(np.count_nonzero(filled_mask)),
        "unresolved": int(np.count_nonzero(remaining)),
        "rejected": int(rejected),
        "requested": requested,
    }


def detect_uv_seam_pairs(faces, face_uvs, min_separation=1.0e-6):
    """Pair 3D-neighbor face edges whose UV corners are separated."""

    if len(faces) != len(face_uvs):
        raise ValueError("Faces and face UVs must have matching lengths.")
    edge_uses = {}
    for face_index, (vertices, uvs) in enumerate(zip(faces, face_uvs, strict=True)):
        if len(vertices) != len(uvs):
            raise ValueError("Each face must have one UV per vertex corner.")
        for corner, vertex_a in enumerate(vertices):
            vertex_b = vertices[(corner + 1) % len(vertices)]
            key = tuple(sorted((int(vertex_a), int(vertex_b))))
            uv_a = tuple(float(value) for value in uvs[corner])
            uv_b = tuple(float(value) for value in uvs[(corner + 1) % len(uvs)])
            by_vertex = {int(vertex_a): uv_a, int(vertex_b): uv_b}
            edge_uses.setdefault(key, []).append(
                {
                    "face": face_index,
                    "uv": (by_vertex[key[0]], by_vertex[key[1]]),
                }
            )
    pairs = []
    for edge, uses in sorted(edge_uses.items()):
        if len(uses) != 2:
            continue
        first, second = uses
        separation = max(
            math.dist(first["uv"][0], second["uv"][0]),
            math.dist(first["uv"][1], second["uv"][1]),
        )
        if separation <= float(min_separation):
            continue
        pairs.append(
            {
                "edge": edge,
                "faces": (first["face"], second["face"]),
                "uv_a": first["uv"],
                "uv_b": second["uv"],
                "separation": separation,
            }
        )
    return pairs


def _line_samples(edge, width, height):
    start = np.asarray(edge[0], dtype=np.float64)
    end = np.asarray(edge[1], dtype=np.float64)
    length = math.hypot(
        (end[0] - start[0]) * max(width - 1, 1),
        (end[1] - start[1]) * max(height - 1, 1),
    )
    count = max(2, int(math.ceil(length)) + 1)
    amount = np.linspace(0.0, 1.0, count, dtype=np.float64)[:, None]
    return start[None, :] * (1.0 - amount) + end[None, :] * amount


def seam_error(image, seam_pairs):
    values = _as_float_image(image)
    height, width = values.shape[:2]
    errors = []
    for pair in seam_pairs:
        samples_a = _line_samples(pair["uv_a"], width, height)
        samples_b = _line_samples(pair["uv_b"], width, height)
        count = min(len(samples_a), len(samples_b))
        color_a = bilinear_sample(values, samples_a[:count])[:, :3]
        color_b = bilinear_sample(values, samples_b[:count])[:, :3]
        errors.extend(np.linalg.norm(color_a - color_b, axis=1).tolist())
    return float(np.mean(errors)) if errors else 0.0


def harmonize_seam_bands(
    image,
    seam_pairs,
    *,
    seam_width=4,
    max_correction=0.35,
    confidence=None,
):
    """Harmonize only narrow paired UV bands while preserving fine detail."""

    values = _as_float_image(image)
    output = values.copy()
    height, width = values.shape[:2]
    confidence_values = (
        np.ones((height, width), dtype=np.float32)
        if confidence is None
        else np.asarray(confidence, dtype=np.float32)
    )
    low = box_blur(values[:, :, :3], max(1, int(seam_width)))
    delta_sum = np.zeros((height, width, 3), dtype=np.float32)
    weight_sum = np.zeros((height, width), dtype=np.float32)
    repaired_band = np.zeros((height, width), dtype=bool)
    safe_pairs = 0
    unsafe_pairs = 0
    before_errors = []

    for pair in seam_pairs:
        samples_a = _line_samples(pair["uv_a"], width, height)
        samples_b = _line_samples(pair["uv_b"], width, height)
        count = min(len(samples_a), len(samples_b))
        samples_a = samples_a[:count]
        samples_b = samples_b[:count]
        color_a = bilinear_sample(low, samples_a)[:, :3]
        color_b = bilinear_sample(low, samples_b)[:, :3]
        differences = np.linalg.norm(color_a - color_b, axis=1)
        mean_difference = float(np.mean(differences))
        before_errors.append(mean_difference)
        if mean_difference > float(max_correction):
            unsafe_pairs += 1
            continue
        confidence_a = bilinear_sample(
            confidence_values[:, :, None], samples_a
        )[:, 0]
        confidence_b = bilinear_sample(
            confidence_values[:, :, None], samples_b
        )[:, 0]
        # The stronger side moves less.  Equal-confidence pairs meet halfway.
        total_confidence = np.maximum(confidence_a + confidence_b, 1.0e-6)
        move_a = confidence_b / total_confidence
        move_b = confidence_a / total_confidence
        delta_a = (color_b - color_a) * move_a[:, None]
        delta_b = (color_a - color_b) * move_b[:, None]
        radius = max(1, int(seam_width))
        for samples, deltas in ((samples_a, delta_a), (samples_b, delta_b)):
            for uv, delta in zip(samples, deltas, strict=True):
                center_x = uv[0] * max(width - 1, 1)
                center_y = uv[1] * max(height - 1, 1)
                x0 = max(0, int(math.floor(center_x - radius)))
                x1 = min(width, int(math.ceil(center_x + radius)) + 1)
                y0 = max(0, int(math.floor(center_y - radius)))
                y1 = min(height, int(math.ceil(center_y + radius)) + 1)
                yy, xx = np.mgrid[y0:y1, x0:x1]
                distance = np.hypot(xx - center_x, yy - center_y)
                weight = brush_falloff(distance, radius, 0.15)
                delta_sum[y0:y1, x0:x1] += weight[:, :, None] * delta
                weight_sum[y0:y1, x0:x1] += weight
                repaired_band[y0:y1, x0:x1] |= weight > 1.0e-6
        safe_pairs += 1

    active = weight_sum > 1.0e-6
    output[:, :, :3][active] = np.clip(
        values[:, :, :3][active]
        + delta_sum[active] / weight_sum[active, None],
        0.0,
        1.0,
    )
    return {
        "image": output,
        "repair_mask": repaired_band,
        "before_error": (
            float(np.mean(before_errors)) if before_errors else 0.0
        ),
        "after_error": seam_error(output, seam_pairs),
        "safe_pairs": safe_pairs,
        "unsafe_pairs": unsafe_pairs,
    }


def metrics_json(metrics):
    return json.dumps(metrics, sort_keys=True, separators=(",", ":"))
