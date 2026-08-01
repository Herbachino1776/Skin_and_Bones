"""Blender integration for cleaned and pose-aligned projection sources."""

from __future__ import annotations

import hashlib
import json

import bpy
import numpy
from mathutils import Vector

from ..constants import (
    BODY_PART_ATTRIBUTE_PREFIX,
    BODY_PART_ID_ATTRIBUTE,
    SOURCE_CLEAN_PREFIX,
    SOURCE_CONFIDENCE_PREFIX,
    SOURCE_DIAGNOSTIC_PREFIX,
    SOURCE_OWNER_PROPERTY,
    SOURCE_STATE_PROPERTY,
    SOURCE_WARP_PREFIX,
    TEMPORARY_PROPERTY,
    VIEW_NAMES,
)
from ..rigging.analysis import analyze_target
from ..rigging.landmarks import (
    apply_saved_corrections,
    estimate_projection_landmarks,
)
from .alignment import _alpha_bounds
from .body_alignment import (
    BODY_LANDMARK_NAMES,
    BODY_PARTS,
    body_part_ownership,
    normalize_landmark_metadata,
    pose_mismatch,
    warp_part_pixels,
)
from .core import view_directions, world_bounds
from .source_doctor import process_source_plate_pixels, validate_cleaned_pixels


WARP_ATLAS_SCHEMA = 2
WARP_ATLAS_GUTTER = 2
WARP_ATLAS_MAX_SIZE = 16384


def _stable_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _image_rgba(image):
    width, height = map(int, image.size)
    if width <= 0 or height <= 0:
        raise ValueError(f"Image '{image.name}' has no pixel data.")
    channels = int(image.channels)
    source = numpy.empty(width * height * channels, dtype=numpy.float32)
    image.pixels.foreach_get(source)
    source = source.reshape((height, width, channels))
    if channels == 4:
        return source.copy()
    rgba = numpy.ones((height, width, 4), dtype=numpy.float32)
    rgba[:, :, : min(3, channels)] = source[:, :, : min(3, channels)]
    return rgba


def _copy_color_intent(source, destination):
    try:
        destination.colorspace_settings.name = source.colorspace_settings.name
    except (AttributeError, TypeError):
        pass
    destination.alpha_mode = source.alpha_mode


def _owned_image(name, width, height, source, kind, *, temporary=False):
    image = bpy.data.images.get(name)
    if image is not None:
        if not image.get(SOURCE_OWNER_PROPERTY, False):
            raise RuntimeError(
                f"Image '{name}' already exists but is not owned by Skin & Bones."
            )
        if tuple(image.size) != (width, height):
            bpy.data.images.remove(image, do_unlink=True)
            image = None
    if image is None:
        image = bpy.data.images.new(
            name,
            width=width,
            height=height,
            alpha=True,
            float_buffer=False,
        )
    image[SOURCE_OWNER_PROPERTY] = True
    image["sbf_source_kind"] = kind
    image[TEMPORARY_PROPERTY] = bool(temporary)
    _copy_color_intent(source, image)
    return image


def _doctor_parameters(settings):
    return {
        "trusted_mask_erosion": round(float(settings.trusted_mask_erosion), 6),
        "rgb_extension_distance": round(float(settings.rgb_extension_distance), 6),
        "despill_strength": round(float(settings.despill_strength), 6),
        "silhouette_confidence_width": round(
            float(settings.silhouette_confidence_width), 6
        ),
    }


def doctor_fingerprint(settings, view_name, image, pixels=None):
    pixels = _image_rgba(image) if pixels is None else pixels
    return _digest(
        {
            "schema": 1,
            "view": view_name,
            "source": image.name,
            "filepath": image.filepath,
            "size": list(map(int, image.size)),
            "colorspace": image.colorspace_settings.name,
            "alpha_mode": image.alpha_mode,
            "pixel_sha256": hashlib.sha256(
                numpy.asarray(pixels, dtype=numpy.float32).tobytes()
            ).hexdigest(),
            "parameters": _doctor_parameters(settings),
        }
    )


def invalidate_source_alignment(settings, reason, *, cleaned=False):
    """Invalidate derived state without deleting artist or source datablocks."""

    settings.source_doctor_state = "STALE"
    settings.source_preview_ready = False
    settings.source_alignment_status = reason
    settings.preview_source_fingerprint = ""
    for name in VIEW_NAMES:
        view = getattr(settings, name)
        view.warp_fingerprint = ""
        view.warp_images_json = ""
        view.pose_mismatch_status = "NOT_RUN"
        view.pose_mismatch_details_json = ""
        if cleaned:
            view.cleaned_fingerprint = ""


def _diagnostic_pixels(cleaned, mask):
    diagnostic = cleaned.copy()
    if mask is not None:
        diagnostic[mask, :3] = (1.0, 0.0, 0.12)
        diagnostic[mask, 3] = 1.0
    return diagnostic


def process_source_plate(settings, view_name, *, force=False):
    view = getattr(settings, view_name)
    original = view.image
    if original is None:
        raise ValueError(f"{view_name.replace('_', ' ').title()} has no source image.")
    width, height = map(int, original.size)
    source_pixels = _image_rgba(original)
    fingerprint = doctor_fingerprint(
        settings, view_name, original, source_pixels
    )
    existing = view.cleaned_image
    if (
        not force
        and existing is not None
        and view.cleaned_fingerprint == fingerprint
        and existing.get(SOURCE_OWNER_PROPERTY, False)
    ):
        validate_cleaned_source(view, view_name)
        return existing, json.loads(view.source_doctor_metrics_json or "{}"), False

    original_alpha = source_pixels[:, :, 3].copy()
    result = process_source_plate_pixels(
        source_pixels,
        width,
        height,
        **_doctor_parameters(settings),
    )
    validate_cleaned_pixels(result, width, height)
    if not numpy.array_equal(result["pixels"][:, :, 3], original_alpha):
        raise RuntimeError("Source Plate Doctor changed the original alpha values.")

    clean = _owned_image(
        f"{SOURCE_CLEAN_PREFIX}{view_name.upper()}",
        width,
        height,
        original,
        "CLEANED_SOURCE",
    )
    clean.pixels.foreach_set(result["pixels"].reshape(-1))
    clean["sbf_original_image"] = original.name
    clean["sbf_doctor_fingerprint"] = fingerprint
    clean["sbf_doctor_metrics"] = _stable_json(result["diagnostics"])
    clean.update()

    diagnostic = _owned_image(
        f"{SOURCE_DIAGNOSTIC_PREFIX}{view_name.upper()}",
        width,
        height,
        original,
        "EDGE_CONTAMINATION",
    )
    diagnostic_pixels = _diagnostic_pixels(
        result["pixels"], result.get("contamination_mask")
    )
    diagnostic.pixels.foreach_set(diagnostic_pixels.reshape(-1))
    diagnostic["sbf_original_image"] = original.name
    diagnostic.update()

    confidence = _owned_image(
        f"{SOURCE_CONFIDENCE_PREFIX}{view_name.upper()}",
        width,
        height,
        original,
        "SOURCE_CONFIDENCE",
    )
    confidence_values = numpy.asarray(result["confidence"], dtype=numpy.float32)
    confidence_pixels = numpy.ones((height, width, 4), dtype=numpy.float32)
    confidence_pixels[:, :, :3] = confidence_values[:, :, None]
    confidence.pixels.foreach_set(confidence_pixels.reshape(-1))
    confidence["sbf_original_image"] = original.name
    confidence["sbf_doctor_fingerprint"] = fingerprint
    confidence.update()

    view.cleaned_image = clean
    view.source_confidence_image = confidence
    view.cleaned_fingerprint = fingerprint
    view.cleaned_original_name = original.name
    view.source_doctor_metrics_json = _stable_json(result["diagnostics"])
    view.warp_fingerprint = ""
    view.warp_images_json = ""
    settings.source_doctor_state = "READY"
    settings.source_preview_ready = False
    return clean, result["diagnostics"], True


def process_all_source_plates(settings, *, force=False):
    results = {}
    for name in VIEW_NAMES:
        view = getattr(settings, name)
        if view.enabled and view.image is not None:
            try:
                _clean, diagnostics, changed = process_source_plate(
                    settings, name, force=force
                )
            except (RuntimeError, ValueError) as exc:
                raise ValueError(f"{name}: {exc}") from exc
            results[name] = {**diagnostics, "changed": changed}
    if not results:
        raise ValueError("No enabled source images are loaded.")
    settings.source_doctor_state = "READY"
    return results


def validate_cleaned_source(view, view_name):
    original = view.image
    clean = view.cleaned_image
    if original is None:
        raise ValueError(f"{view_name} is missing its original source.")
    if clean is None or clean.name not in bpy.data.images:
        raise ValueError(f"{view_name} is missing its cleaned source.")
    if not clean.get(SOURCE_OWNER_PROPERTY, False):
        raise ValueError(f"{view_name} cleaned source is not owned by Skin & Bones.")
    if tuple(clean.size) != tuple(original.size):
        raise ValueError(f"{view_name} owned-image size mismatch.")
    confidence = view.source_confidence_image
    if (
        confidence is None
        or not confidence.get(SOURCE_OWNER_PROPERTY, False)
        or tuple(confidence.size) != tuple(original.size)
        or confidence.get("sbf_doctor_fingerprint", "") != view.cleaned_fingerprint
    ):
        raise ValueError(f"{view_name} is missing its valid source confidence band.")
    if clean.get("sbf_original_image", "") != original.name:
        raise ValueError(f"{view_name} cleaned source belongs to a different original.")
    if view.cleaned_fingerprint != clean.get("sbf_doctor_fingerprint", ""):
        raise ValueError(f"{view_name} cleaned source state is stale.")
    return clean


def _image_bounds(image, settings):
    bounds, _head, _black = _alpha_bounds(
        image,
        threshold=0.02,
        head_threshold=settings.head_threshold,
    )
    return bounds


def _image_initialized_landmarks(view_name, clean, bounds):
    """Estimate joint chains from deterministic silhouette cross-sections."""

    pixels = _image_rgba(clean)
    alpha = pixels[:, :, 3]
    visible = alpha > 0.02
    if float(visible.mean()) > 0.95:
        border = numpy.concatenate(
            (pixels[0, :, :3], pixels[-1, :, :3], pixels[:, 0, :3], pixels[:, -1, :3]),
            axis=0,
        )
        background = numpy.median(border, axis=0)
        visible &= numpy.linalg.norm(pixels[:, :, :3] - background, axis=2) > 0.025
    height, width = visible.shape
    minimum_x, minimum_y, maximum_x, maximum_y = bounds
    center_x = (minimum_x + maximum_x) * 0.5

    def row_values(fraction):
        normalized_y = minimum_y + fraction * (maximum_y - minimum_y)
        row = max(0, min(height - 1, int(round(normalized_y * (height - 1)))))
        radius = max(1, int(round(height * 0.006)))
        rows = visible[max(0, row - radius) : min(height, row + radius + 1)]
        _ys, xs = numpy.nonzero(rows)
        if not len(xs):
            return numpy.asarray([center_x], dtype=numpy.float64), normalized_y
        return xs.astype(numpy.float64) / max(width - 1, 1), normalized_y

    def extreme(fraction, side):
        xs, y = row_values(fraction)
        quantile = 0.92 if side == "screen_right" else 0.08
        return (float(numpy.quantile(xs, quantile)), y)

    def leg_center(fraction, side):
        xs, y = row_values(fraction)
        half = xs[xs >= center_x] if side == "screen_right" else xs[xs <= center_x]
        if not len(half):
            half = xs
        return (float(numpy.median(half)), y)

    if view_name in {"left", "right"}:
        visible_side = view_name
        hidden_side = "right" if view_name == "left" else "left"
        points = {
            "head_top": (float(numpy.median(row_values(0.995)[0])), row_values(0.995)[1]),
            "chin": (float(numpy.median(row_values(0.815)[0])), row_values(0.815)[1]),
        }
        for base, fraction in (
            ("shoulder", 0.775), ("elbow", 0.655), ("wrist", 0.535),
            ("hand", 0.505), ("hip", 0.505), ("knee", 0.285),
            ("ankle", 0.065), ("toe", 0.020),
        ):
            xs, y = row_values(fraction)
            points[f"{base}_{visible_side}"] = (float(numpy.median(xs)), y)
        metadata = {
            "points": points,
            "skipped": [
                name for name in BODY_LANDMARK_NAMES
                if name.endswith(f"_{hidden_side}")
            ],
        }
        return normalize_landmark_metadata(metadata, view_name)

    anatomical_left_screen = "screen_left" if view_name == "back" else "screen_right"
    anatomical_right_screen = "screen_right" if view_name == "back" else "screen_left"
    top_xs, top_y = row_values(0.995)
    chin_xs, chin_y = row_values(0.815)
    points = {
        "head_top": (float(numpy.median(top_xs)), top_y),
        "chin": (float(numpy.median(chin_xs)), chin_y),
    }
    for base, fraction in (
        ("shoulder", 0.775), ("elbow", 0.655),
        ("wrist", 0.535), ("hand", 0.505),
    ):
        points[f"{base}_left"] = extreme(fraction, anatomical_left_screen)
        points[f"{base}_right"] = extreme(fraction, anatomical_right_screen)
    for base, fraction in (
        ("hip", 0.505), ("knee", 0.285),
        ("ankle", 0.065), ("toe", 0.020),
    ):
        points[f"{base}_left"] = leg_center(fraction, anatomical_left_screen)
        points[f"{base}_right"] = leg_center(fraction, anatomical_right_screen)
    return normalize_landmark_metadata({"points": points, "skipped": []}, view_name)


def auto_initialize_body_landmarks(settings, view_name=None, context=None):
    names = (view_name,) if view_name else VIEW_NAMES
    initialized = []
    for name in names:
        view = getattr(settings, name)
        if not view.enabled or view.image is None:
            continue
        clean = validate_cleaned_source(view, name)
        bounds = _image_bounds(clean, settings)
        metadata = _image_initialized_landmarks(name, clean, bounds)
        view.body_landmarks_json = _stable_json(metadata)
        view.body_landmarks_valid = True
        view.body_landmark_image_name = view.image.name
        view.warp_fingerprint = ""
        view.warp_images_json = ""
        initialized.append(name)
    if not initialized:
        raise ValueError("No cleaned source images are available for body landmarks.")
    settings.source_preview_ready = False
    settings.source_alignment_status = "Body landmarks changed; regenerate warped sources."
    return initialized


def body_landmarks(view, view_name):
    if not view.body_landmarks_json:
        raise ValueError(f"{view_name} has no body landmarks.")
    try:
        metadata = json.loads(view.body_landmarks_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{view_name} body landmark metadata is invalid.") from exc
    if view.image is None or view.body_landmark_image_name != view.image.name:
        raise ValueError(f"{view_name} body landmarks belong to a different image.")
    return normalize_landmark_metadata(metadata, view_name)


def reset_body_landmarks(settings, view_name=None):
    names = (view_name,) if view_name else VIEW_NAMES
    for name in names:
        view = getattr(settings, name)
        view.body_landmarks_json = ""
        view.body_landmarks_valid = False
        view.body_landmark_image_name = ""
        view.warp_fingerprint = ""
        view.warp_images_json = ""
        view.pose_mismatch_status = "NOT_RUN"
        view.pose_mismatch_details_json = ""
    settings.source_preview_ready = False
    settings.source_alignment_status = "Body landmarks reset."


def _view_transform(view, point, *, head=False):
    sign_x = -1.0 if view.flip_x else 1.0
    sign_y = -1.0 if view.flip_y else 1.0
    scale = max(float(view.scale), 1.0e-6)
    scale_x = scale * max(float(view.horizontal_scale), 1.0e-6)
    x = sign_x * (point[0] - 0.5) / scale_x + 0.5 + view.offset_x
    y = sign_y * (point[1] - 0.5) / scale + 0.5 + view.offset_y
    if head:
        head_scale = max(float(view.head_scale), 1.0e-6)
        head_scale_x = head_scale * max(float(view.head_horizontal_scale), 1.0e-6)
        x = (x - 0.5) / head_scale_x + 0.5 + view.head_offset_x
        y = (y - 0.5) / head_scale + 0.5 + view.head_offset_y
    return (max(0.0, min(1.0, x)), max(0.0, min(1.0, y)))


def mesh_body_landmarks(context, settings, view_name, analysis=None, landmarks=None):
    target = settings.target_object
    if target is None or target.type != "MESH":
        raise ValueError("Choose a production target mesh before body alignment.")
    analysis = analysis or analyze_target(
        context, target, settings.forward_axis, settings.up_axis
    )
    landmarks = landmarks or apply_saved_corrections(
        target, estimate_projection_landmarks(context, target, analysis)
    )
    directions = view_directions(settings)
    bounds = world_bounds(target, directions)
    up = directions["up"]
    horizontal = up.cross(directions[view_name]).normalized()
    ortho_scale = bounds["up_span"] / max(settings.framing_ratio, 1.0e-6)

    def project(world, *, head=False):
        point = Vector(world)
        camera_uv = (
            0.5 + (point.dot(horizontal) - bounds["center"].dot(horizontal)) / ortho_scale,
            0.5 + (point.dot(up) - bounds["center"].dot(up)) / ortho_scale,
        )
        return _view_transform(getattr(settings, view_name), camera_uv, head=head)

    height = float(analysis["world_height"])
    head_center = Vector(landmarks["head_center"]["world"])
    chin = head_center - up * height * 0.080
    mapping = {
        "head_top": project(landmarks["head_top"]["world"], head=True),
        "chin": project(chin, head=True),
    }
    for source_name, target_name in (
        ("shoulder_left", "shoulder_left"),
        ("shoulder_right", "shoulder_right"),
        ("elbow_left", "elbow_left"),
        ("elbow_right", "elbow_right"),
        ("wrist_left", "wrist_left"),
        ("wrist_right", "wrist_right"),
        ("hand_left", "hand_left"),
        ("hand_right", "hand_right"),
        ("hip_left", "hip_left"),
        ("hip_right", "hip_right"),
        ("knee_left", "knee_left"),
        ("knee_right", "knee_right"),
        ("ankle_left", "ankle_left"),
        ("ankle_right", "ankle_right"),
        ("toe_left", "toe_left"),
        ("toe_right", "toe_right"),
    ):
        mapping[target_name] = project(landmarks[source_name]["world"])
    return {"points": mapping, "skipped": []}, analysis, landmarks


def _warp_owned_image_names(view):
    try:
        payload = json.loads(view.warp_images_json or "{}")
    except (AttributeError, json.JSONDecodeError):
        return ()
    if payload.get("schema") == WARP_ATLAS_SCHEMA:
        return (payload.get("atlas", ""),)
    # Version 1.1 stored one full-size image name per body part.
    return tuple(value for value in payload.values() if isinstance(value, str))


def _remove_view_warps(view):
    for name in _warp_owned_image_names(view):
        image = bpy.data.images.get(name)
        if image is not None and image.get(SOURCE_OWNER_PROPERTY, False):
            bpy.data.images.remove(image, do_unlink=True)
    view.warp_images_json = ""
    view.warp_fingerprint = ""


def _next_power_of_two(value):
    result = 1
    while result < max(1, int(value)):
        result *= 2
    return result


def _pack_warp_crops(crops):
    """Pack native-resolution transparent crops into one GPU-safe atlas."""

    gutter = WARP_ATLAS_GUTTER
    rectangles = {
        part: (int(crop.shape[1]) + gutter * 2, int(crop.shape[0]) + gutter * 2)
        for part, crop in crops.items()
    }
    minimum_width = _next_power_of_two(
        max(width for width, _height in rectangles.values())
    )
    candidates = []
    atlas_width = minimum_width
    ordered = sorted(
        BODY_PARTS,
        key=lambda part: (
            -rectangles[part][1],
            -rectangles[part][0],
            BODY_PARTS.index(part),
        ),
    )
    while atlas_width <= WARP_ATLAS_MAX_SIZE:
        x = y = row_height = 0
        positions = {}
        valid = True
        for part in ordered:
            width, height = rectangles[part]
            if width > atlas_width:
                valid = False
                break
            if x and x + width > atlas_width:
                y += row_height
                x = 0
                row_height = 0
            positions[part] = (x + gutter, y + gutter)
            x += width
            row_height = max(row_height, height)
        required_height = y + row_height
        atlas_height = _next_power_of_two(required_height)
        if valid and atlas_height <= WARP_ATLAS_MAX_SIZE:
            area = atlas_width * atlas_height
            aspect_penalty = abs(
                atlas_width.bit_length() - atlas_height.bit_length()
            )
            candidates.append(
                (area, aspect_penalty, atlas_width, atlas_height, positions)
            )
        atlas_width *= 2
    if not candidates:
        raise RuntimeError(
            "Body-part warp atlas exceeds Blender's safe 16K texture limit."
        )
    _area, _aspect, width, height, positions = min(candidates)
    return width, height, positions


def _build_warp_atlas(part_pixels, source_width, source_height):
    crops = {}
    source_bounds = {}
    for part in BODY_PARTS:
        pixels = part_pixels[part]
        visible_y, visible_x = numpy.nonzero(pixels[:, :, 3] > 1.0e-8)
        if len(visible_x):
            minimum_x = max(0, int(visible_x.min()) - 1)
            maximum_x = min(source_width - 1, int(visible_x.max()) + 1)
            minimum_y = max(0, int(visible_y.min()) - 1)
            maximum_y = min(source_height - 1, int(visible_y.max()) + 1)
            crop = pixels[
                minimum_y : maximum_y + 1,
                minimum_x : maximum_x + 1,
            ].copy()
        else:
            minimum_x = maximum_x = minimum_y = maximum_y = 0
            crop = numpy.zeros((1, 1, 4), dtype=numpy.float32)
        crops[part] = crop
        source_bounds[part] = (minimum_x, minimum_y, maximum_x, maximum_y)

    atlas_width, atlas_height, positions = _pack_warp_crops(crops)
    atlas = numpy.zeros((atlas_height, atlas_width, 4), dtype=numpy.float32)
    parts = {}
    for part in BODY_PARTS:
        crop = crops[part]
        atlas_x, atlas_y = positions[part]
        crop_height, crop_width = crop.shape[:2]
        atlas[
            atlas_y : atlas_y + crop_height,
            atlas_x : atlas_x + crop_width,
        ] = crop
        parts[part] = {
            "source_bounds": list(source_bounds[part]),
            "atlas_origin": [atlas_x, atlas_y],
            "crop_size": [crop_width, crop_height],
        }
    return atlas, parts


def generate_warped_sources(context, settings, view_name=None):
    target = settings.target_object
    analysis = analyze_target(
        context, target, settings.forward_axis, settings.up_axis
    )
    mesh_landmarks = apply_saved_corrections(
        target, estimate_projection_landmarks(context, target, analysis)
    )
    names = (view_name,) if view_name else VIEW_NAMES
    results = {}
    severe = []
    prepared = []
    for name in names:
        view = getattr(settings, name)
        if not view.enabled or view.image is None:
            continue
        clean = validate_cleaned_source(view, name)
        source = body_landmarks(view, name)
        target_metadata, _analysis, _mesh = mesh_body_landmarks(
            context, settings, name, analysis, mesh_landmarks
        )
        # Hidden profile-side target points must be excluded exactly like the source.
        for skipped in source["skipped"]:
            target_metadata["points"].pop(skipped, None)
            target_metadata["skipped"].append(skipped)
        mismatch = pose_mismatch(source, target_metadata)
        view.pose_mismatch_status = mismatch["status"]
        view.pose_mismatch_worst_part = mismatch["worst_part"]
        view.pose_mismatch_error = mismatch["error"]
        view.pose_mismatch_details_json = _stable_json(mismatch["parts"])
        severe.extend(
            f"{name}:{part}={details['error']:.3f}"
            for part, details in mismatch["parts"].items()
            if details["status"] == "SEVERE"
        )
        prepared.append((name, view, clean, source, target_metadata, mismatch))
    if severe:
        settings.source_pose_state = "SOURCE_POSE_REVIEW_REQUIRED"
        settings.source_alignment_status = "Severe pose contradiction: " + ", ".join(severe)
        raise RuntimeError(
            "SOURCE_POSE_REVIEW_REQUIRED: " + ", ".join(severe)
        )

    for name, view, clean, source, target_metadata, mismatch in prepared:
        clean_pixels = _image_rgba(clean)
        confidence_pixels = _image_rgba(view.source_confidence_image)[:, :, 0]
        clean_pixels[:, :, 3] *= confidence_pixels
        width, height = map(int, clean.size)
        fingerprint = _digest(
            {
                "schema": WARP_ATLAS_SCHEMA,
                "clean": view.cleaned_fingerprint,
                "source_landmarks": source,
                "target_landmarks": target_metadata,
                "feather": round(float(settings.warp_joint_feather), 6),
            }
        )
        existing_image, _existing_metadata = get_warped_atlas(view, require=False)
        if view.warp_fingerprint == fingerprint and existing_image is not None:
            results[name] = mismatch
            continue
        _remove_view_warps(view)
        part_pixels = {}
        for part in BODY_PARTS:
            pixels = warp_part_pixels(
                clean_pixels,
                width,
                height,
                source,
                target_metadata,
                part,
                feather=settings.warp_joint_feather,
            )
            if not numpy.isfinite(pixels).all():
                raise RuntimeError(f"{name} {part} warp contains non-finite pixels.")
            part_pixels[part] = pixels
        atlas_pixels, parts = _build_warp_atlas(part_pixels, width, height)
        atlas_visible_fraction = float((atlas_pixels[:, :, 3] > 1.0e-8).mean())
        if atlas_visible_fraction <= 0.0:
            raise RuntimeError(
                f"{name} body-part warp is transparent; projection preview cancelled."
            )
        atlas_height, atlas_width = atlas_pixels.shape[:2]
        image = _owned_image(
            f"{SOURCE_WARP_PREFIX}{name.upper()}_ATLAS",
            atlas_width,
            atlas_height,
            clean,
            "WARP_ATLAS",
            temporary=True,
        )
        image.pixels.foreach_set(atlas_pixels.reshape(-1))
        image["sbf_source_view"] = name
        image["sbf_warp_fingerprint"] = fingerprint
        image["sbf_warp_atlas_schema"] = WARP_ATLAS_SCHEMA
        image.update()
        view.warp_images_json = _stable_json(
            {
                "schema": WARP_ATLAS_SCHEMA,
                "atlas": image.name,
                "source_size": [width, height],
                "atlas_size": [atlas_width, atlas_height],
                "visible_fraction": round(atlas_visible_fraction, 8),
                "parts": parts,
            }
        )
        view.warp_fingerprint = fingerprint
        results[name] = mismatch
    if not results:
        raise ValueError("No body-aligned source views were generated.")
    settings.source_pose_state = "READY"
    settings.source_preview_ready = False
    worst_view = max(
        results,
        key=lambda name: (
            {"HIDDEN": -1, "ACCEPTABLE": 0, "MODERATE": 1, "SEVERE": 2}[results[name]["status"]],
            results[name]["error"],
            name,
        ),
    )
    settings.source_alignment_status = (
        f"Warped {len(results)} views; worst {worst_view} "
        f"{results[worst_view]['worst_part']} {results[worst_view]['status'].lower()} "
        f"({results[worst_view]['error']:.4f} -> 0.0000)."
    )
    return results


def get_warped_atlas(view, *, require=True):
    try:
        metadata = json.loads(view.warp_images_json or "{}")
    except json.JSONDecodeError as exc:
        if require:
            raise ValueError("Warped source metadata is invalid.") from exc
        return None, {}
    if metadata.get("schema") != WARP_ATLAS_SCHEMA:
        if require:
            raise ValueError(
                "Warped source uses a legacy over-limit preview layout; refresh it."
            )
        return None, {}
    image = bpy.data.images.get(metadata.get("atlas", ""))
    if image is None:
        if require:
            raise ValueError("Missing projection-only body-part warp atlas.")
        return None, {}
    valid = (
        image.get(SOURCE_OWNER_PROPERTY, False)
        and image.get("sbf_source_kind", "") == "WARP_ATLAS"
        and image.get("sbf_warp_fingerprint", "") == view.warp_fingerprint
        and image.get("sbf_warp_atlas_schema", 0) == WARP_ATLAS_SCHEMA
        and tuple(image.size) == tuple(metadata.get("atlas_size", ()))
        and view.cleaned_image is not None
        and tuple(view.cleaned_image.size)
        == tuple(metadata.get("source_size", ()))
        and set(metadata.get("parts", {})) == set(BODY_PARTS)
        and float(metadata.get("visible_fraction", 0.0)) > 0.0
        and image.has_data
    )
    if not valid:
        if require:
            raise ValueError("Warped source atlas ownership or dimensions are stale.")
        return None, {}
    return image, metadata


def get_warped_images(view, *, require=True):
    """Compatibility view of the atlas as seven strictly owned regions."""

    image, metadata = get_warped_atlas(view, require=require)
    if image is None:
        return {}
    return {part: image for part in metadata["parts"]}


def processed_source_payload(settings, *, require_warp=True):
    views = {}
    for name in VIEW_NAMES:
        view = getattr(settings, name)
        if not view.enabled or view.image is None:
            continue
        clean = validate_cleaned_source(view, name)
        item = {
            "original": view.image.name,
            "cleaned": clean.name,
            "cleaned_fingerprint": view.cleaned_fingerprint,
            "confidence": view.source_confidence_image.name,
            "alignment": {
                "flip_x": bool(view.flip_x),
                "flip_y": bool(view.flip_y),
                "scale": round(float(view.scale), 7),
                "horizontal_scale": round(float(view.horizontal_scale), 7),
                "offset_x": round(float(view.offset_x), 7),
                "offset_y": round(float(view.offset_y), 7),
                "head_scale": round(float(view.head_scale), 7),
                "head_horizontal_scale": round(float(view.head_horizontal_scale), 7),
                "head_offset_x": round(float(view.head_offset_x), 7),
                "head_offset_y": round(float(view.head_offset_y), 7),
            },
        }
        if require_warp:
            image, metadata = get_warped_atlas(view)
            item["warp_atlas"] = {
                "image": image.name,
                "atlas_size": metadata["atlas_size"],
                "source_size": metadata["source_size"],
                "visible_fraction": metadata["visible_fraction"],
                "parts": metadata["parts"],
            }
            item["warp_fingerprint"] = view.warp_fingerprint
        views[name] = item
    if not views:
        raise ValueError("No enabled processed sources are available.")
    return {"schema": WARP_ATLAS_SCHEMA, "views": views}


def processed_source_fingerprint(settings, *, require_warp=True):
    return _digest(processed_source_payload(settings, require_warp=require_warp))


def stamp_preview_source_state(material, settings):
    fingerprint = processed_source_fingerprint(settings)
    material[SOURCE_STATE_PROPERTY] = fingerprint
    material["sbf_processed_source_payload"] = _stable_json(
        processed_source_payload(settings)
    )
    settings.preview_source_fingerprint = fingerprint
    settings.source_preview_ready = True
    return fingerprint


def validate_preview_source_parity(material, settings):
    current = processed_source_fingerprint(settings)
    preview = material.get(SOURCE_STATE_PROPERTY, "")
    if not preview or preview != current or settings.preview_source_fingerprint != current:
        raise RuntimeError(
            "Processed source state changed after preview; refresh before final bake."
        )
    expected = processed_source_payload(settings)["views"]
    nodes = material.node_tree.nodes if material.node_tree else ()
    for view_name, item in expected.items():
        image_name = item["warp_atlas"]["image"]
        for node_name in (
            f"SBF_WarpAtlas_{view_name}",
            f"SBF_WarpAtlasSafe_{view_name}",
        ):
            node = nodes.get(node_name)
            if node is None or node.image is None or node.image.name != image_name:
                raise RuntimeError(
                    "Preview and final bake do not use the same body-part warp atlas."
                )
            if not node.image.has_data:
                raise RuntimeError(
                    "Projection atlas pixel data is unavailable; refresh the preview before baking."
                )
    texture_nodes = [node for node in nodes if node.bl_idname == "ShaderNodeTexImage"]
    if len(texture_nodes) > 13 or any(node.image is None for node in texture_nodes):
        raise RuntimeError(
            "Projection preview exceeds the production GPU texture budget; refresh it."
        )
    shader_attributes = {
        node.attribute_name
        for node in nodes
        if node.bl_idname == "ShaderNodeAttribute" and node.attribute_name
    }
    shader_attributes.update(
        node.uv_map
        for node in nodes
        if node.bl_idname == "ShaderNodeUVMap" and node.uv_map
    )
    if len(shader_attributes) > 12:
        raise RuntimeError(
            "Projection preview exceeds Blender's production attribute budget; refresh it."
        )
    return True


def create_body_part_attributes(context, target, settings):
    """Create one compact semantic owner ID without editing geometry."""

    analysis = analyze_target(context, target, settings.forward_axis, settings.up_axis)
    landmarks = apply_saved_corrections(
        target, estimate_projection_landmarks(context, target, analysis)
    )
    up = Vector(analysis["up_axis_world"])
    lateral = Vector(analysis["lateral_axis_world"])
    center = Vector(analysis["centerline_world"])
    ground = float(analysis["ground"])
    height = max(float(analysis["world_height"]), 1.0e-8)

    def normalized(world):
        point = Vector(world)
        return (
            0.5 + (point - center).dot(lateral) / height,
            (point.dot(up) - ground) / height,
        )

    landmark_points = {
        name: normalized(item["world"])
        for name, item in landmarks.items()
        if name in {
            "shoulder_left", "shoulder_right", "elbow_left", "elbow_right",
            "wrist_left", "wrist_right", "hand_left", "hand_right",
            "hip_left", "hip_right", "knee_left", "knee_right",
            "ankle_left", "ankle_right", "toe_left", "toe_right",
        }
    }
    owners = []
    for vertex in target.data.vertices:
        world = target.matrix_world @ vertex.co
        owners.append(body_part_ownership(normalized(world), landmark_points))
    polygon_owners = {}
    for polygon in target.data.polygons:
        candidates = [owners[index] for index in polygon.vertices]
        polygon_owners[polygon.index] = min(
            BODY_PARTS,
            key=lambda part: (-candidates.count(part), BODY_PARTS.index(part)),
        )
    for existing in list(target.data.attributes):
        if existing.name.startswith(BODY_PART_ATTRIBUTE_PREFIX):
            target.data.attributes.remove(existing)
    attribute = target.data.attributes.new(
        name=BODY_PART_ID_ATTRIBUTE,
        type="FLOAT",
        domain="CORNER",
    )
    for polygon in target.data.polygons:
        value = float(BODY_PARTS.index(polygon_owners[polygon.index]))
        for loop_index in polygon.loop_indices:
            attribute.data[loop_index].value = value
    target.data["sbf_body_part_ownership"] = _stable_json(
        {
            part: sum(owner == part for owner in polygon_owners.values())
            for part in BODY_PARTS
        }
    )
    return attribute


def cleanup_warped_sources(settings):
    for name in VIEW_NAMES:
        _remove_view_warps(getattr(settings, name))
    settings.source_preview_ready = False
    settings.preview_source_fingerprint = ""


def restore_original_source(settings, view_name):
    view = getattr(settings, view_name)
    _remove_view_warps(view)
    for image in (
        view.cleaned_image,
        view.source_confidence_image,
        bpy.data.images.get(f"{SOURCE_DIAGNOSTIC_PREFIX}{view_name.upper()}"),
    ):
        if image is not None and image.get(SOURCE_OWNER_PROPERTY, False):
            bpy.data.images.remove(image, do_unlink=True)
    view.cleaned_image = None
    view.source_confidence_image = None
    view.cleaned_fingerprint = ""
    view.cleaned_original_name = ""
    view.source_doctor_metrics_json = ""
    settings.source_doctor_state = "STALE"
    settings.source_preview_ready = False
    settings.source_alignment_status = f"{view_name.title()} restored to its untouched original."


def contamination_metrics(settings):
    result = {}
    for name in VIEW_NAMES:
        view = getattr(settings, name)
        if view.source_doctor_metrics_json:
            try:
                result[name] = json.loads(view.source_doctor_metrics_json)
            except json.JSONDecodeError:
                pass
    return result
