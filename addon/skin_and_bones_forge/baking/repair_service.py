"""Blender image, mesh, and delivery integration for Texture Repair Studio."""

from __future__ import annotations

import json
import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

from ..constants import (
    BASE_COLOR_UV_NAME,
    BODY_PART_ATTRIBUTE_PREFIX,
    REPAIR_BAKED_IMAGE,
    REPAIR_CLASSIFICATION_IMAGE,
    REPAIR_CORRECTION_IMAGE,
    REPAIR_DIAGNOSTIC_IMAGE,
    REPAIR_DONOR_MASK_IMAGE,
    REPAIR_FINAL_IMAGE,
    REPAIR_FINGERPRINT_PROPERTY,
    REPAIR_FORBIDDEN_MASK_IMAGE,
    REPAIR_MASK_IMAGE,
    REPAIR_OWNER_PROPERTY,
    REPAIR_PREVIEW_MATERIAL_PROPERTY,
    REPAIR_PREVIEW_PREFIX,
    REPAIR_PREVIEW_SLOT_PROPERTY,
    REPAIR_ROLE_PROPERTY,
    REPAIR_TARGET_MASK_IMAGE,
    TEMPORARY_PROPERTY,
    VIEW_NAMES,
    WEIGHT_ATTRIBUTE_PREFIX,
)
from ..projection.body_alignment import BODY_PARTS
from .texture_repair import (
    CLASSIFICATION_NAMES,
    SEAM_HEAL,
    SMART_FILL,
    UNRESOLVED,
    OPPOSITE_PARTS,
    apply_surface_stroke,
    classification_rgba,
    composite_corrections,
    detect_unresolved,
    detect_uv_seam_pairs,
    harmonize_seam_bands,
    image_fingerprint,
    initial_classification,
    known_diagnostic_mask,
    map_tangent_clone_offsets,
    normalized_distance_from_mask,
    repair_fingerprint,
    repair_state_is_compatible,
    seam_error,
    smart_fill_masked,
)


REPAIR_IMAGE_NAMES = (
    REPAIR_BAKED_IMAGE,
    REPAIR_CORRECTION_IMAGE,
    REPAIR_MASK_IMAGE,
    REPAIR_FINAL_IMAGE,
    REPAIR_CLASSIFICATION_IMAGE,
)

_ATLAS_CACHE = {}


def _stable_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _image_pixels(image):
    width, height = (int(image.size[0]), int(image.size[1]))
    values = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(values)
    return values.reshape(height, width, 4)


def _set_image_pixels(image, values):
    pixels = np.asarray(values, dtype=np.float32)
    expected = (int(image.size[1]), int(image.size[0]), 4)
    if pixels.shape != expected:
        raise ValueError(
            f"Image '{image.name}' expects {expected}, received {pixels.shape}."
        )
    image.pixels.foreach_set(pixels.reshape(-1))
    image.update()


def _remove_owned_image(image):
    if image is not None and image.get(REPAIR_OWNER_PROPERTY, False):
        bpy.data.images.remove(image, do_unlink=True)


def _is_owned_repair_preview(material):
    return bool(
        material is not None
        and material.name.startswith(REPAIR_PREVIEW_PREFIX)
        and material.get(REPAIR_OWNER_PROPERTY, False)
    )


def _restore_production_material(info):
    """Leave any temporary preview and bind the validated production material."""

    target = info.obj
    slot = int(info.material_slot)
    if not 0 <= slot < len(target.material_slots):
        slot = int(target.get(REPAIR_PREVIEW_SLOT_PROPERTY, -1))
    if not 0 <= slot < len(target.material_slots):
        raise RuntimeError("The production material slot is no longer available.")

    current = target.material_slots[slot].material
    stored_name = target.get(REPAIR_PREVIEW_MATERIAL_PROPERTY, "")
    stored = bpy.data.materials.get(stored_name) if stored_name else None
    target.material_slots[slot].material = info.material

    for material in {current, stored}:
        if _is_owned_repair_preview(material) and material.users == 0:
            bpy.data.materials.remove(material)
    for key in (
        REPAIR_PREVIEW_SLOT_PROPERTY,
        REPAIR_PREVIEW_MATERIAL_PROPERTY,
    ):
        if key in target:
            del target[key]
    return info.material


def validate_repair_name_availability():
    for name in REPAIR_IMAGE_NAMES:
        image = bpy.data.images.get(name)
        if image is not None and not image.get(REPAIR_OWNER_PROPERTY, False):
            raise RuntimeError(
                f"Image name '{name}' is already used by artist data. Rename it "
                "before starting Texture Repair Studio."
            )


def _new_owned_image(name, width, height, role, fingerprint, *, data=False):
    image = bpy.data.images.new(
        name,
        width=int(width),
        height=int(height),
        alpha=True,
        float_buffer=False,
    )
    image.colorspace_settings.name = "Non-Color" if data else "sRGB"
    image.alpha_mode = "STRAIGHT"
    image[REPAIR_OWNER_PROPERTY] = True
    image[REPAIR_ROLE_PROPERTY] = role
    image[REPAIR_FINGERPRINT_PROPERTY] = fingerprint
    return image


def _owned_layer(name, width, height, role, fingerprint, *, data=False, reuse=True):
    image = bpy.data.images.get(name)
    compatible = (
        image is not None
        and image.get(REPAIR_OWNER_PROPERTY, False)
        and image.get(REPAIR_ROLE_PROPERTY, "") == role
        and image.get(REPAIR_FINGERPRINT_PROPERTY, "") == fingerprint
        and tuple(image.size) == (int(width), int(height))
    )
    if compatible and reuse:
        return image, True
    _remove_owned_image(image)
    return _new_owned_image(
        name, width, height, role, fingerprint, data=data
    ), False


def _mesh_repair_fingerprint(mesh, uv_name, size):
    uv_layer = mesh.uv_layers.get(uv_name)
    if uv_layer is None:
        raise RuntimeError(f"Production base-color UV '{uv_name}' is missing.")
    return repair_fingerprint(
        (tuple(vertex.co) for vertex in mesh.vertices),
        (tuple(polygon.vertices) for polygon in mesh.polygons),
        (tuple(item.uv) for item in uv_layer.data),
        size,
        uv_name,
    )


def current_repair_fingerprint(target):
    uv_name = target.get("sbf_repair_uv", "")
    size = json.loads(target.get("sbf_repair_size", "[0,0]"))
    if not uv_name or min(size) <= 0:
        return ""
    return _mesh_repair_fingerprint(target.data, uv_name, size)


def ensure_repair_compatible(info, settings):
    stored = info.obj.get(REPAIR_FINGERPRINT_PROPERTY, "")
    current = current_repair_fingerprint(info.obj)
    if not repair_state_is_compatible(stored, current):
        settings.repair_state = "STALE"
        settings.repair_status = (
            "Texture repairs are stale after a topology, UV, or atlas change. "
            "Re-bake before preview, repair, or delivery."
        )
        raise RuntimeError(settings.repair_status)
    return current


def _polygon_metadata(mesh):
    parts = []
    confidence = []
    for polygon in mesh.polygons:
        owner = -1
        if polygon.loop_indices:
            loop_index = polygon.loop_indices[0]
            for part_index, part in enumerate(BODY_PARTS):
                attribute = mesh.attributes.get(
                    f"{BODY_PART_ATTRIBUTE_PREFIX}{part}"
                )
                if (
                    attribute is not None
                    and attribute.data[loop_index].value > 0.5
                ):
                    owner = part_index
                    break
        parts.append(owner)
        weights = []
        for loop_index in polygon.loop_indices:
            total = 0.0
            for view_name in VIEW_NAMES:
                attribute = mesh.attributes.get(
                    f"{WEIGHT_ATTRIBUTE_PREFIX}{view_name}"
                )
                if attribute is not None:
                    total += max(0.0, float(attribute.data[loop_index].value))
            weights.append(min(1.0, total))
        confidence.append(round(sum(weights) / max(len(weights), 1), 6))
    return parts, confidence


def _mesh_seam_pairs(mesh, uv_name):
    uv_layer = mesh.uv_layers[uv_name]
    faces = []
    face_uvs = []
    for polygon in mesh.polygons:
        faces.append(tuple(polygon.vertices))
        face_uvs.append(
            tuple(tuple(uv_layer.data[index].uv) for index in polygon.loop_indices)
        )
    return detect_uv_seam_pairs(faces, face_uvs)


def _rasterize_atlas(target, fingerprint):
    mesh = target.data
    width, height = json.loads(target["sbf_repair_size"])
    uv_name = target["sbf_repair_uv"]
    uv_layer = mesh.uv_layers.get(uv_name)
    if uv_layer is None:
        raise RuntimeError(f"Repair UV '{uv_name}' no longer exists.")
    parts = json.loads(target.get("sbf_repair_polygon_parts", "[]"))
    confidence_by_face = json.loads(
        target.get("sbf_repair_polygon_confidence", "[]")
    )
    if len(parts) != len(mesh.polygons):
        parts = [-1] * len(mesh.polygons)
    if len(confidence_by_face) != len(mesh.polygons):
        confidence_by_face = [1.0] * len(mesh.polygons)

    coverage = np.zeros((height, width), dtype=bool)
    semantic = np.full((height, width), -1, dtype=np.int8)
    material = np.full((height, width), -1, dtype=np.int16)
    face_index = np.full((height, width), -1, dtype=np.int32)
    confidence = np.zeros((height, width), dtype=np.float32)
    mesh.calc_loop_triangles()
    for triangle in mesh.loop_triangles:
        polygon_index = int(triangle.polygon_index)
        coordinates = np.asarray(
            [tuple(uv_layer.data[index].uv) for index in triangle.loops],
            dtype=np.float64,
        )
        coordinates[:, 0] *= max(width - 1, 1)
        coordinates[:, 1] *= max(height - 1, 1)
        x0 = max(0, int(math.floor(float(np.min(coordinates[:, 0])))))
        x1 = min(width, int(math.ceil(float(np.max(coordinates[:, 0])))) + 1)
        y0 = max(0, int(math.floor(float(np.min(coordinates[:, 1])))))
        y1 = min(height, int(math.ceil(float(np.max(coordinates[:, 1])))) + 1)
        if x0 >= x1 or y0 >= y1:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        ax, ay = coordinates[0]
        bx, by = coordinates[1]
        cx, cy = coordinates[2]
        denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(float(denominator)) <= 1.0e-12:
            continue
        first = ((by - cy) * (xx - cx) + (cx - bx) * (yy - cy)) / denominator
        second = ((cy - ay) * (xx - cx) + (ax - cx) * (yy - cy)) / denominator
        third = 1.0 - first - second
        inside = (first >= -1.0e-6) & (second >= -1.0e-6) & (third >= -1.0e-6)
        if not np.any(inside):
            continue
        patch_coverage = coverage[y0:y1, x0:x1]
        patch_coverage[inside] = True
        semantic[y0:y1, x0:x1][inside] = int(parts[polygon_index])
        material[y0:y1, x0:x1][inside] = int(
            mesh.polygons[polygon_index].material_index
        )
        face_index[y0:y1, x0:x1][inside] = polygon_index
        confidence[y0:y1, x0:x1][inside] = float(
            confidence_by_face[polygon_index]
        )
    return {
        "fingerprint": fingerprint,
        "coverage": coverage,
        "semantic": semantic,
        "material": material,
        "face": face_index,
        "confidence": confidence,
    }


def atlas_data(target):
    fingerprint = current_repair_fingerprint(target)
    stored = target.get(REPAIR_FINGERPRINT_PROPERTY, "")
    if not repair_state_is_compatible(stored, fingerprint):
        raise RuntimeError(
            "Texture repairs are stale because topology, the production base-color "
            "UV, or atlas size changed. Re-bake to create compatible layers."
        )
    key = target.as_pointer()
    cached = _ATLAS_CACHE.get(key)
    if cached is None or cached["fingerprint"] != fingerprint:
        cached = _rasterize_atlas(target, fingerprint)
        _ATLAS_CACHE[key] = cached
    return cached


def repair_images(target, *, require=True):
    fingerprint = target.get(REPAIR_FINGERPRINT_PROPERTY, "")
    result = {}
    for role, name in (
        ("baked", REPAIR_BAKED_IMAGE),
        ("corrections", REPAIR_CORRECTION_IMAGE),
        ("mask", REPAIR_MASK_IMAGE),
        ("final", REPAIR_FINAL_IMAGE),
        ("classification", REPAIR_CLASSIFICATION_IMAGE),
    ):
        image = bpy.data.images.get(name)
        valid = (
            image is not None
            and image.get(REPAIR_OWNER_PROPERTY, False)
            and image.get(REPAIR_ROLE_PROPERTY, "") == role
            and image.get(REPAIR_FINGERPRINT_PROPERTY, "") == fingerprint
        )
        if require and not valid:
            raise RuntimeError(
                f"Texture Repair Studio image '{name}' is missing or stale. Re-bake."
            )
        result[role] = image if valid else None
    return result


def _mask_layer(name, target, role):
    width, height = json.loads(target["sbf_repair_size"])
    fingerprint = target[REPAIR_FINGERPRINT_PROPERTY]
    image, reused = _owned_layer(
        name, width, height, role, fingerprint, data=True, reuse=True
    )
    if not reused:
        pixels = np.zeros((height, width, 4), dtype=np.float32)
        pixels[:, :, 3] = 1.0
        _set_image_pixels(image, pixels)
    return image


def begin_repair_session(
    context,
    info,
    settings,
    baked_image,
    output_path,
    bake_uv_name,
):
    """Adopt a successful raw bake and create/reuse compatible repair layers."""

    validate_repair_name_availability()
    target = info.obj
    width, height = int(baked_image.size[0]), int(baked_image.size[1])
    fingerprint = _mesh_repair_fingerprint(
        info.mesh, bake_uv_name, (width, height)
    )
    previous = bpy.data.images.get(REPAIR_CORRECTION_IMAGE)
    preserved = bool(
        previous is not None
        and previous.get(REPAIR_OWNER_PROPERTY, False)
        and repair_state_is_compatible(
            previous.get(REPAIR_FINGERPRINT_PROPERTY, ""), fingerprint
        )
        and tuple(previous.size) == (width, height)
    )

    old_baked = bpy.data.images.get(REPAIR_BAKED_IMAGE)
    if old_baked is not baked_image:
        _remove_owned_image(old_baked)
    baked_image.name = REPAIR_BAKED_IMAGE
    baked_image[REPAIR_OWNER_PROPERTY] = True
    baked_image[REPAIR_ROLE_PROPERTY] = "baked"
    baked_image[REPAIR_FINGERPRINT_PROPERTY] = fingerprint
    baked_pixels = _image_pixels(baked_image)
    baked_image["sbf_pixel_fingerprint"] = image_fingerprint(baked_pixels)

    corrections, reused_corrections = _owned_layer(
        REPAIR_CORRECTION_IMAGE,
        width,
        height,
        "corrections",
        fingerprint,
        reuse=True,
    )
    mask, reused_mask = _owned_layer(
        REPAIR_MASK_IMAGE,
        width,
        height,
        "mask",
        fingerprint,
        data=True,
        reuse=True,
    )
    final, _reused_final = _owned_layer(
        REPAIR_FINAL_IMAGE,
        width,
        height,
        "final",
        fingerprint,
        reuse=False,
    )
    classification, reused_classification = _owned_layer(
        REPAIR_CLASSIFICATION_IMAGE,
        width,
        height,
        "classification",
        fingerprint,
        data=True,
        reuse=True,
    )
    if not reused_corrections:
        values = np.zeros((height, width, 4), dtype=np.float32)
        values[:, :, 3] = 1.0
        _set_image_pixels(corrections, values)
    if not reused_mask:
        values = np.zeros((height, width, 4), dtype=np.float32)
        values[:, :, 3] = 1.0
        _set_image_pixels(mask, values)

    polygon_parts, polygon_confidence = _polygon_metadata(info.mesh)
    seam_pairs = _mesh_seam_pairs(info.mesh, bake_uv_name)
    target[REPAIR_FINGERPRINT_PROPERTY] = fingerprint
    target["sbf_repair_uv"] = bake_uv_name
    target["sbf_repair_size"] = _stable_json([width, height])
    target["sbf_repair_polygon_parts"] = _stable_json(polygon_parts)
    target["sbf_repair_polygon_confidence"] = _stable_json(polygon_confidence)
    target["sbf_repair_seam_pairs"] = _stable_json(seam_pairs)
    target["sbf_repair_source_fingerprint"] = baked_image[
        "sbf_pixel_fingerprint"
    ]
    target["sbf_repair_schema"] = "skin-and-bones-texture-repair-v1"
    _ATLAS_CACHE.pop(target.as_pointer(), None)
    atlas = atlas_data(target)
    unresolved = detect_unresolved(
        baked_pixels, atlas["coverage"], atlas["confidence"]
    )
    if not reused_classification or not preserved:
        classes = initial_classification(
            atlas["coverage"], atlas["confidence"], unresolved
        )
        _set_image_pixels(classification, classification_rgba(classes))
        classification["sbf_classification_values"] = _stable_json(
            {str(key): value for key, value in CLASSIFICATION_NAMES.items()}
        )

    raw_path = Path(output_path).with_name(
        f"{Path(output_path).stem}.baked{Path(output_path).suffix or '.png'}"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    baked_image.filepath_raw = str(raw_path)
    baked_image.file_format = "PNG"
    baked_image.save()
    settings.last_raw_baked_image = baked_image
    settings.last_baked_image = final
    settings.repair_correction_image = corrections
    settings.repair_mask_image = mask
    settings.repair_final_image = final
    settings.repair_classification_image = classification
    settings.repair_state = "READY"
    settings.repair_status = (
        "Compatible correction layer preserved across re-bake."
        if preserved
        else "New non-destructive correction layer is ready."
    )
    commit_final_base_color(info, settings, output_path=output_path)
    return {
        "baked": baked_image,
        "corrections": corrections,
        "mask": mask,
        "final": final,
        "classification": classification,
        "fingerprint": fingerprint,
        "preserved": preserved,
        "unresolved": int(np.count_nonzero(unresolved)),
        "seams": len(seam_pairs),
        "raw_path": raw_path,
    }


def _classification_values(image):
    colors = _image_pixels(image)
    result = np.zeros(colors.shape[:2], dtype=np.uint8)
    from .texture_repair import CLASSIFICATION_COLORS

    for value, color in CLASSIFICATION_COLORS.items():
        match = np.max(
            np.abs(colors[:, :, :3] - np.asarray(color[:3], dtype=np.float32)),
            axis=2,
        ) <= 0.01
        result[match] = value
    return result


def commit_final_base_color(info, settings, *, output_path=None):
    _restore_production_material(info)
    images = repair_images(info.obj)
    baked = _image_pixels(images["baked"])
    corrections = _image_pixels(images["corrections"])
    mask = _image_pixels(images["mask"])[:, :, 0]
    final = composite_corrections(
        baked,
        corrections,
        mask,
        enabled=settings.repair_enabled,
        opacity=settings.repair_opacity,
    )
    _set_image_pixels(images["final"], final)
    atlas = atlas_data(info.obj)
    unresolved = detect_unresolved(final, atlas["coverage"], atlas["confidence"])
    classes = _classification_values(images["classification"])
    classes[(classes == UNRESOLVED) & ~unresolved] = (
        1  # DIRECT_PROJECTION is safe after a repair fills the pixel.
    )
    classes[unresolved] = UNRESOLVED
    _set_image_pixels(images["classification"], classification_rgba(classes))
    diagnostic = known_diagnostic_mask(final, atlas["coverage"])
    metrics = {
        "schema": "skin-and-bones-texture-repair-v1",
        "fingerprint": info.obj[REPAIR_FINGERPRINT_PROPERTY],
        "source_fingerprint": info.obj.get("sbf_repair_source_fingerprint", ""),
        "correction_pixels": int(np.count_nonzero(mask > 1.0e-6)),
        "correction_coverage": round(
            float(np.count_nonzero(mask > 1.0e-6))
            / max(int(np.count_nonzero(atlas["coverage"])), 1),
            8,
        ),
        "unresolved": int(np.count_nonzero(unresolved)),
        "diagnostic_pixels": int(np.count_nonzero(diagnostic)),
        "seam_before": float(settings.repair_seam_error_before),
        "seam_after": float(settings.repair_seam_error_after),
    }
    info.obj["sbf_repair_metrics"] = _stable_json(metrics)
    settings.repair_unresolved_count = metrics["unresolved"]
    settings.repair_correction_count = metrics["correction_pixels"]
    settings.repair_status = (
        f"Final composite ready: {metrics['correction_pixels']:,} corrected, "
        f"{metrics['unresolved']:,} unresolved."
    )
    path = Path(
        bpy.path.abspath(str(output_path or settings.output_image_path))
    ).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    images["final"].filepath_raw = str(path)
    images["final"].file_format = "PNG"
    images["final"].save()
    if settings.pack_baked_image:
        for role in ("baked", "corrections", "mask", "final", "classification"):
            images[role].pack()
    info.base_color_node.image = images["final"]
    info.obj["sbf_base_color_image"] = images["final"].name
    info.obj["sbf_base_color_path"] = str(path)
    settings.last_baked_image = images["final"]
    settings.last_raw_baked_image = images["baked"]
    return images["final"], path, metrics


def validate_repair_for_delivery(info, settings):
    final, _path, metrics = commit_final_base_color(info, settings)
    if final.name != REPAIR_FINAL_IMAGE or info.base_color_node.image != final:
        raise RuntimeError(
            "Delivery is blocked because the production material does not use "
            "SBF_BaseColor_Final."
        )
    threshold = int(settings.repair_unresolved_threshold)
    if metrics["unresolved"] > threshold:
        raise RuntimeError(
            f"Delivery blocked: {metrics['unresolved']:,} unresolved texture pixels "
            f"exceed the safe threshold of {threshold:,}."
        )
    if metrics["diagnostic_pixels"]:
        raise RuntimeError(
            f"Delivery blocked: {metrics['diagnostic_pixels']:,} known diagnostic "
            "color pixels remain in the final base color."
        )
    return metrics


def set_clone_source(settings, sample):
    settings.repair_clone_source_json = _stable_json(sample)
    settings.repair_source_status = (
        f"Source set on {sample.get('part_name', 'surface')} at "
        f"UV {sample['uv'][0]:.4f}, {sample['uv'][1]:.4f}."
    )


def clone_source(settings):
    if not settings.repair_clone_source_json:
        raise RuntimeError("Click SET SOURCE on the target surface first.")
    return json.loads(settings.repair_clone_source_json)


def _stroke_layers(info):
    images = repair_images(info.obj)
    return (
        images,
        _image_pixels(images["baked"]),
        _image_pixels(images["corrections"]),
        _image_pixels(images["mask"])[:, :, 0],
        _classification_values(images["classification"]),
    )


def apply_repair_strokes(info, settings, source, targets):
    images, baked, corrections, mask, classes = _stroke_layers(info)
    atlas = atlas_data(info.obj)
    source_part = int(source.get("part", -1))
    source_material = int(source.get("material", -1))
    donor_allowed = atlas["coverage"].copy()
    if settings.repair_restrict_part:
        donor_allowed &= atlas["semantic"] == source_part
    if settings.repair_restrict_material:
        donor_allowed &= atlas["material"] == source_material
    changed = 0
    rejected = 0
    first_target = targets[0] if targets else None
    for target in targets:
        target_part = int(target.get("part", -1))
        target_material = int(target.get("material", -1))
        permitted_target_parts = {source_part}
        if settings.repair_symmetry and source_part in OPPOSITE_PARTS:
            permitted_target_parts.add(int(OPPOSITE_PARTS[source_part]))
        if (
            settings.repair_restrict_part
            and target_part not in permitted_target_parts
        ):
            rejected += 1
            continue
        if settings.repair_restrict_material and target_material != source_material:
            rejected += 1
            continue
        target_allowed = atlas["coverage"].copy()
        if settings.repair_restrict_part:
            target_allowed &= atlas["semantic"] == target_part
        if settings.repair_restrict_material:
            target_allowed &= atlas["material"] == target_material
        source_uv = source["uv"]
        if settings.repair_clone_aligned and first_target is not None:
            delta = np.asarray(target["uv"]) - np.asarray(first_target["uv"])
            source_uv = map_tangent_clone_offsets(
                delta[None, :],
                source["uv"],
                source["basis"],
                first_target["basis"],
            )[0].tolist()
        result = apply_surface_stroke(
            baked,
            corrections,
            mask,
            classes,
            source_uv=source_uv,
            target_uv=target["uv"],
            source_tangent_to_uv=source["basis"],
            target_tangent_to_uv=target["basis"],
            radius=settings.repair_brush_size,
            hardness=1.0 - settings.repair_softness,
            opacity=settings.repair_strength,
            mode=settings.repair_mode,
            source_scale=settings.repair_source_scale,
            source_rotation=settings.repair_source_rotation,
            detail_preservation=settings.repair_detail_preservation,
            low_frequency_radius=settings.repair_frequency_radius,
            donor_allowed=donor_allowed,
            target_allowed=target_allowed,
        )
        changed += result.changed_pixels
        rejected += result.rejected_pixels
    _set_image_pixels(images["corrections"], corrections)
    mask_rgba = np.repeat(mask[:, :, None], 4, axis=2)
    mask_rgba[:, :, 3] = 1.0
    _set_image_pixels(images["mask"], mask_rgba)
    _set_image_pixels(images["classification"], classification_rgba(classes))
    commit_final_base_color(info, settings)
    settings.repair_status = (
        f"{settings.repair_mode.title()} stroke: {changed:,} pixels changed, "
        f"{rejected:,} restricted."
    )
    return {"changed": changed, "rejected": rejected}


def _selected_face_mask(info):
    atlas = atlas_data(info.obj)
    selected = np.asarray(
        [polygon.select for polygon in info.mesh.polygons], dtype=bool
    )
    face_map = atlas["face"]
    valid = face_map >= 0
    result = np.zeros(face_map.shape, dtype=bool)
    result[valid] = selected[face_map[valid]]
    return result


def _image_mask(image):
    return _image_pixels(image)[:, :, 0] >= 0.5


def smart_fill(info, settings):
    images, baked, corrections, mask, classes = _stroke_layers(info)
    current = composite_corrections(
        baked,
        corrections,
        mask,
        enabled=settings.repair_enabled,
        opacity=settings.repair_opacity,
    )
    atlas = atlas_data(info.obj)
    source = settings.repair_smart_fill_target
    if source == "SELECTED_FACES":
        target_mask = _selected_face_mask(info)
    elif source == "ARTIST_MASK":
        target_mask = _image_mask(
            _mask_layer(
                REPAIR_TARGET_MASK_IMAGE, info.obj, "smart_fill_target_mask"
            )
        )
    elif source == "UNRESOLVED":
        target_mask = detect_unresolved(
            current, atlas["coverage"], atlas["confidence"]
        )
    else:
        raise RuntimeError(f"Unknown Smart Fill target: {source}")
    forbidden_image = _mask_layer(
        REPAIR_FORBIDDEN_MASK_IMAGE, info.obj, "forbidden_source_mask"
    )
    donor_image = _mask_layer(
        REPAIR_DONOR_MASK_IMAGE, info.obj, "artist_donor_mask"
    )
    settings.repair_target_mask_image = _mask_layer(
        REPAIR_TARGET_MASK_IMAGE, info.obj, "smart_fill_target_mask"
    )
    settings.repair_donor_mask_image = donor_image
    settings.repair_forbidden_mask_image = forbidden_image
    forbidden = _image_mask(forbidden_image)
    artist_donor = _image_mask(donor_image)
    donor = (
        atlas["coverage"]
        & ~target_mask
        & ~forbidden
        & (
            (atlas["confidence"] >= settings.repair_min_donor_confidence)
            | artist_donor
        )
    )
    result = smart_fill_masked(
        current,
        target_mask,
        donor,
        atlas["semantic"],
        atlas["material"],
        source_policy=settings.repair_source_policy,
        artist_donor_mask=artist_donor,
        forbidden_mask=forbidden,
        confidence=atlas["confidence"],
        contamination_distance=normalized_distance_from_mask(forbidden),
        max_candidates=settings.repair_patch_candidates,
        max_pixels=settings.repair_smart_fill_pixel_limit,
    )
    filled = result["filled_mask"]
    corrections[filled] = result["image"][filled]
    mask[filled] = 1.0
    classes[filled] = SMART_FILL
    classes[target_mask & ~filled] = UNRESOLVED
    _set_image_pixels(images["corrections"], corrections)
    mask_rgba = np.repeat(mask[:, :, None], 4, axis=2)
    mask_rgba[:, :, 3] = 1.0
    _set_image_pixels(images["mask"], mask_rgba)
    _set_image_pixels(images["classification"], classification_rgba(classes))
    commit_final_base_color(info, settings)
    metrics = {
        key: int(result[key])
        for key in ("requested", "filled", "unresolved", "rejected")
    }
    info.obj["sbf_repair_smart_fill_metrics"] = _stable_json(metrics)
    settings.repair_status = (
        f"Smart Fill: {metrics['filled']:,} filled, "
        f"{metrics['unresolved']:,} unresolved, {metrics['rejected']:,} rejected."
    )
    return metrics


def _stored_seam_pairs(target):
    return json.loads(target.get("sbf_repair_seam_pairs", "[]"))


def detect_color_seams(info, settings):
    images = repair_images(info.obj)
    current = _image_pixels(images["final"])
    pairs = _stored_seam_pairs(info.obj)
    errors = [seam_error(current, [pair]) for pair in pairs]
    selected = [
        index
        for index, error in enumerate(errors)
        if error >= settings.repair_seam_detection_threshold
    ]
    settings.repair_selected_seams_json = _stable_json(selected)
    before = float(np.mean([errors[index] for index in selected])) if selected else 0.0
    settings.repair_seam_error_before = before
    settings.repair_seam_error_after = before
    settings.repair_detected_seam_count = len(selected)
    info.obj["sbf_repair_seam_errors"] = _stable_json(errors)
    settings.repair_status = (
        f"Detected {len(selected):,} color seams from {len(pairs):,} paired UV edges; "
        f"mean error {before:.5f}."
    )
    return {"pairs": len(pairs), "selected": len(selected), "error": before}


def heal_seams(info, settings, *, all_safe=False):
    images, baked, corrections, mask, classes = _stroke_layers(info)
    current = composite_corrections(
        baked,
        corrections,
        mask,
        enabled=settings.repair_enabled,
        opacity=settings.repair_opacity,
    )
    pairs = _stored_seam_pairs(info.obj)
    if all_safe:
        selected = list(range(len(pairs)))
    else:
        selected = json.loads(settings.repair_selected_seams_json or "[]")
    chosen = [pairs[index] for index in selected if 0 <= index < len(pairs)]
    if not chosen:
        raise RuntimeError("Detect or select color seams before healing.")
    atlas = atlas_data(info.obj)
    result = harmonize_seam_bands(
        current,
        chosen,
        seam_width=settings.repair_seam_width,
        max_correction=settings.repair_seam_max_correction,
        confidence=atlas["confidence"],
    )
    repaired = result["repair_mask"]
    corrections[repaired] = result["image"][repaired]
    mask[repaired] = 1.0
    classes[repaired] = SEAM_HEAL
    _set_image_pixels(images["corrections"], corrections)
    mask_rgba = np.repeat(mask[:, :, None], 4, axis=2)
    mask_rgba[:, :, 3] = 1.0
    _set_image_pixels(images["mask"], mask_rgba)
    _set_image_pixels(images["classification"], classification_rgba(classes))
    commit_final_base_color(info, settings)
    settings.repair_seam_error_before = result["before_error"]
    settings.repair_seam_error_after = result["after_error"]
    metrics = {
        "before": result["before_error"],
        "after": result["after_error"],
        "safe": result["safe_pairs"],
        "unsafe": result["unsafe_pairs"],
        "pixels": int(np.count_nonzero(repaired)),
    }
    info.obj["sbf_repair_seam_metrics"] = _stable_json(metrics)
    settings.repair_status = (
        f"Seam Heal: {metrics['safe']} safe, {metrics['unsafe']} manual; "
        f"error {metrics['before']:.5f} -> {metrics['after']:.5f}."
    )
    return metrics


def clear_repairs(info, settings, *, selected=False):
    images, _baked, corrections, mask, classes = _stroke_layers(info)
    region = _selected_face_mask(info) if selected else np.ones(mask.shape, dtype=bool)
    changed = int(np.count_nonzero((mask > 1.0e-6) & region))
    corrections[region] = (0.0, 0.0, 0.0, 1.0)
    mask[region] = 0.0
    atlas = atlas_data(info.obj)
    baked = _image_pixels(images["baked"])
    unresolved = detect_unresolved(
        baked, atlas["coverage"], atlas["confidence"]
    )
    reset = initial_classification(
        atlas["coverage"], atlas["confidence"], unresolved
    )
    classes[region] = reset[region]
    _set_image_pixels(images["corrections"], corrections)
    mask_rgba = np.repeat(mask[:, :, None], 4, axis=2)
    mask_rgba[:, :, 3] = 1.0
    _set_image_pixels(images["mask"], mask_rgba)
    _set_image_pixels(images["classification"], classification_rgba(classes))
    commit_final_base_color(info, settings)
    settings.repair_status = f"Cleared {changed:,} corrected pixels."
    return changed


def _diagnostic_image(target, values):
    height, width = values.shape[:2]
    fingerprint = target[REPAIR_FINGERPRINT_PROPERTY]
    image, _reused = _owned_layer(
        REPAIR_DIAGNOSTIC_IMAGE,
        width,
        height,
        "diagnostic",
        fingerprint,
        reuse=True,
    )
    _set_image_pixels(image, values)
    return image


def _seam_heatmap(target, final):
    values = final.copy()
    pairs = _stored_seam_pairs(target)
    height, width = values.shape[:2]
    for pair in pairs:
        error = seam_error(final, [pair])
        color = np.asarray((min(1.0, error * 4.0), max(0.0, 1.0 - error * 4.0), 0.0))
        for edge in (pair["uv_a"], pair["uv_b"]):
            start = np.asarray(edge[0])
            end = np.asarray(edge[1])
            count = max(
                2,
                int(
                    math.ceil(
                        math.hypot(
                            (end[0] - start[0]) * width,
                            (end[1] - start[1]) * height,
                        )
                    )
                ),
            )
            for amount in np.linspace(0.0, 1.0, count):
                uv = start * (1.0 - amount) + end * amount
                x = int(np.clip(round(uv[0] * (width - 1)), 0, width - 1))
                y = int(np.clip(round(uv[1] * (height - 1)), 0, height - 1))
                values[
                    max(0, y - 1) : min(height, y + 2),
                    max(0, x - 1) : min(width, x + 2),
                    :3,
                ] = color
    return values


def clear_repair_preview(info):
    _restore_production_material(info)


def show_repair_preview(context, info, settings):
    ensure_repair_compatible(info, settings)
    images = repair_images(info.obj)
    final = _image_pixels(images["final"])
    display = settings.repair_display
    if display == "FINAL":
        clear_repair_preview(info)
        info.base_color_node.image = images["final"]
        return images["final"]
    if display == "BEFORE":
        display_image = images["baked"]
    elif display == "CORRECTION_MASK":
        display_image = images["mask"]
    elif display == "CLASSIFICATION":
        display_image = images["classification"]
    elif display == "SOURCE_CONTAMINATION":
        atlas = atlas_data(info.obj)
        overlay = final.copy()
        low_confidence = atlas["coverage"] & (atlas["confidence"] < 0.20)
        overlay[low_confidence, :3] = (1.0, 0.0, 0.65)
        display_image = _diagnostic_image(info.obj, overlay)
    elif display == "TARGET_MASK":
        display_image = _mask_layer(
            REPAIR_TARGET_MASK_IMAGE, info.obj, "smart_fill_target_mask"
        )
        settings.repair_target_mask_image = display_image
    elif display == "DONOR_MASK":
        display_image = _mask_layer(
            REPAIR_DONOR_MASK_IMAGE, info.obj, "artist_donor_mask"
        )
        settings.repair_donor_mask_image = display_image
    elif display == "FORBIDDEN_MASK":
        display_image = _mask_layer(
            REPAIR_FORBIDDEN_MASK_IMAGE, info.obj, "forbidden_source_mask"
        )
        settings.repair_forbidden_mask_image = display_image
    elif display == "UNRESOLVED":
        atlas = atlas_data(info.obj)
        overlay = final.copy()
        unresolved = detect_unresolved(final, atlas["coverage"], atlas["confidence"])
        overlay[unresolved, :3] = (1.0, 0.0, 0.1)
        display_image = _diagnostic_image(info.obj, overlay)
    elif display == "SEAM_HEATMAP":
        display_image = _diagnostic_image(
            info.obj, _seam_heatmap(info.obj, final)
        )
    elif display == "UNLIT_FINAL":
        display_image = images["final"]
    else:
        display_image = _diagnostic_image(info.obj, final)

    clear_repair_preview(info)
    material = bpy.data.materials.new(f"{REPAIR_PREVIEW_PREFIX}{info.obj.name}")
    material.use_nodes = True
    material[REPAIR_OWNER_PROPERTY] = True
    material[TEMPORARY_PROPERTY] = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = display_image
    uv = nodes.new("ShaderNodeUVMap")
    uv.uv_map = info.obj.get("sbf_repair_uv", BASE_COLOR_UV_NAME)
    links.new(uv.outputs["UV"], texture.inputs["Vector"])
    links.new(texture.outputs["Color"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    target = info.obj
    target[REPAIR_PREVIEW_SLOT_PROPERTY] = info.material_slot
    target[REPAIR_PREVIEW_MATERIAL_PROPERTY] = material.name
    target.material_slots[info.material_slot].material = material
    return display_image


def surface_sample_from_hit(target, polygon_index, world_location, uv_name):
    """Resolve a ray-cast hit to production UV and a tangent-to-UV basis."""

    mesh = target.data
    mesh.calc_loop_triangles()
    local_point = target.matrix_world.inverted() @ Vector(world_location)
    candidates = [
        triangle
        for triangle in mesh.loop_triangles
        if triangle.polygon_index == int(polygon_index)
    ]
    if not candidates:
        raise RuntimeError("The clicked polygon has no render triangle.")
    triangle = min(
        candidates,
        key=lambda item: (
            sum(
                (mesh.vertices[index].co - local_point).length
                for index in item.vertices
            )
        ),
    )
    points = [mesh.vertices[index].co.copy() for index in triangle.vertices]
    first_edge = points[1] - points[0]
    second_edge = points[2] - points[0]
    normal = first_edge.cross(second_edge)
    if normal.length <= 1.0e-10:
        raise RuntimeError("The clicked surface triangle is degenerate.")
    normal.normalize()
    tangent = first_edge.normalized()
    bitangent = normal.cross(tangent).normalized()
    edge_matrix = np.asarray(
        (
            (first_edge.dot(tangent), first_edge.dot(bitangent)),
            (second_edge.dot(tangent), second_edge.dot(bitangent)),
        ),
        dtype=np.float64,
    )
    uv_layer = mesh.uv_layers.get(uv_name)
    if uv_layer is None:
        raise RuntimeError(f"Production base-color UV '{uv_name}' is missing.")
    uv_points = np.asarray(
        [tuple(uv_layer.data[index].uv) for index in triangle.loops],
        dtype=np.float64,
    )
    uv_edges = np.asarray(
        (uv_points[1] - uv_points[0], uv_points[2] - uv_points[0])
    )
    basis = (np.linalg.inv(edge_matrix) @ uv_edges).T
    local_edges = np.asarray(
        (
            (points[1] - points[0]).dot(tangent),
            (points[1] - points[0]).dot(bitangent),
            (points[2] - points[0]).dot(tangent),
            (points[2] - points[0]).dot(bitangent),
        ),
        dtype=np.float64,
    ).reshape(2, 2)
    local_delta = np.asarray(
        (
            (local_point - points[0]).dot(tangent),
            (local_point - points[0]).dot(bitangent),
        )
    )
    bary_tail = np.linalg.solve(local_edges.T, local_delta)
    barycentric = np.asarray(
        (1.0 - bary_tail.sum(), bary_tail[0], bary_tail[1])
    )
    uv_value = barycentric @ uv_points
    polygon_parts = json.loads(target.get("sbf_repair_polygon_parts", "[]"))
    part = polygon_parts[int(polygon_index)] if polygon_parts else -1
    return {
        "uv": [float(uv_value[0]), float(uv_value[1])],
        "basis": [float(value) for value in basis.reshape(-1)],
        "polygon": int(polygon_index),
        "part": int(part),
        "part_name": (
            BODY_PARTS[int(part)]
            if 0 <= int(part) < len(BODY_PARTS)
            else "unknown"
        ),
        "material": int(mesh.polygons[int(polygon_index)].material_index),
        "world": [float(value) for value in world_location],
    }


def clear_runtime_cache():
    _ATLAS_CACHE.clear()
