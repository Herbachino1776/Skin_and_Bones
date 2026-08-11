"""Blender runtime for shared-body appearance variant families."""

from __future__ import annotations

from array import array
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import uuid

import bpy
from bpy.app.handlers import persistent

from ..constants import (
    ADDON_VERSION_STRING,
    BASE_COLOR_UV_NAME,
    REPAIR_BAKED_IMAGE,
    REPAIR_CLASSIFICATION_IMAGE,
    REPAIR_CORRECTION_IMAGE,
    REPAIR_FINAL_IMAGE,
    REPAIR_FINGERPRINT_PROPERTY,
    REPAIR_FORBIDDEN_MASK_IMAGE,
    REPAIR_MASK_IMAGE,
    REPAIR_OWNER_PROPERTY,
    REPAIR_TARGET_MASK_IMAGE,
    REPAIR_DONOR_MASK_IMAGE,
    RIG_PRODUCTION_PROPERTY,
    RIG_WEIGHT_REPORT_PROPERTY,
    SOURCE_CLEAN_PREFIX,
    SOURCE_CONFIDENCE_PREFIX,
    SOURCE_DIAGNOSTIC_PREFIX,
    SOURCE_OWNER_PROPERTY,
    VIEW_NAMES,
)
from .model import (
    FAMILY_SCHEMA,
    FAMILY_SCHEMA_VERSION,
    TECHNICAL_BODY_SCHEMA,
    TECHNICAL_BODY_SCHEMA_VERSION,
    appearance_handoff_record,
    bake_uv_adoption_allowed,
    stable_fingerprint,
    stable_json,
    technical_body_fingerprint,
    variant_export_name,
    variant_image_name,
)


VIEW_STATE_FIELDS = (
    "enabled",
    "expanded",
    "flip_x",
    "flip_y",
    "scale",
    "horizontal_scale",
    "offset_x",
    "offset_y",
    "head_scale",
    "head_horizontal_scale",
    "head_offset_x",
    "head_offset_y",
    "eye_image_left",
    "eye_image_right",
    "mouth_image_left",
    "mouth_image_right",
    "facial_landmarks_set",
    "facial_landmarks_skipped",
    "facial_calibration_valid",
    "landmark_image_name",
    "cleaned_fingerprint",
    "cleaned_original_name",
    "source_doctor_metrics_json",
    "body_landmarks_json",
    "body_landmarks_valid",
    "body_landmark_image_name",
    "warp_images_json",
    "warp_fingerprint",
    "pose_mismatch_status",
    "pose_mismatch_worst_part",
    "pose_mismatch_error",
    "pose_mismatch_details_json",
    "auto_head_scale",
    "auto_head_horizontal_scale",
    "auto_head_offset_x",
    "auto_head_offset_y",
    "alpha_threshold",
    "key_black_background",
    "black_key_threshold",
    "weight",
    "occlusion",
)

APPEARANCE_STATE_FIELDS = (
    "framing_ratio",
    "show_projection_cameras",
    "live_preview",
    "auto_fit_source_images",
    "source_doctor_view",
    "trusted_mask_erosion",
    "rgb_extension_distance",
    "despill_strength",
    "silhouette_confidence_width",
    "warp_joint_feather",
    "show_edge_contamination",
    "show_cleaned_source",
    "show_pose_mismatch",
    "source_doctor_state",
    "source_pose_state",
    "source_alignment_status",
    "source_preview_ready",
    "preview_source_fingerprint",
    "directional_exponent",
    "minimum_weight",
    "lower_front_back_bias",
    "upper_front_back_bias",
    "head_front_back_bias",
    "head_identity_lock",
    "head_blend_sharpness",
    "source_edge_padding",
    "head_lock_transition",
    "side_bias",
    "upper_threshold",
    "head_threshold",
    "top_surface_coverage",
    "fallback_threshold",
    "occlusion_protection",
    "visibility_method",
    "visibility_samples",
    "depth_tolerance_factor",
    "occlusion_feather",
    "texture_size",
    "bake_margin",
    "generate_bake_uv",
    "repair_enabled",
    "repair_opacity",
    "repair_mode",
    "repair_brush_size",
    "repair_softness",
    "repair_strength",
    "repair_spacing",
    "repair_detail_preservation",
    "repair_source_scale",
    "repair_source_rotation",
    "repair_clone_aligned",
    "repair_restrict_part",
    "repair_restrict_material",
    "repair_symmetry",
    "repair_frequency_radius",
    "repair_smart_fill_target",
    "repair_source_policy",
    "repair_min_donor_confidence",
    "repair_patch_candidates",
    "repair_smart_fill_pixel_limit",
    "repair_seam_width",
    "repair_seam_max_correction",
    "repair_seam_detection_threshold",
    "repair_unresolved_threshold",
    "repair_display",
    "repair_state",
    "repair_status",
    "repair_source_status",
    "repair_clone_source_json",
    "repair_selected_seams_json",
    "repair_unresolved_count",
    "repair_correction_count",
    "repair_detected_seam_count",
    "repair_seam_error_before",
    "repair_seam_error_after",
)

VARIANT_IMAGE_FIELDS = (
    "baked_image",
    "correction_image",
    "mask_image",
    "final_image",
    "classification_image",
    "target_mask_image",
    "donor_mask_image",
    "forbidden_mask_image",
)

SETTINGS_IMAGE_FIELDS = {
    "baked_image": "last_raw_baked_image",
    "correction_image": "repair_correction_image",
    "mask_image": "repair_mask_image",
    "final_image": "repair_final_image",
    "classification_image": "repair_classification_image",
    "target_mask_image": "repair_target_mask_image",
    "donor_mask_image": "repair_donor_mask_image",
    "forbidden_mask_image": "repair_forbidden_mask_image",
}

IMAGE_BASE_NAMES = {
    "baked_image": REPAIR_BAKED_IMAGE,
    "correction_image": REPAIR_CORRECTION_IMAGE,
    "mask_image": REPAIR_MASK_IMAGE,
    "final_image": REPAIR_FINAL_IMAGE,
    "classification_image": REPAIR_CLASSIFICATION_IMAGE,
    "target_mask_image": REPAIR_TARGET_MASK_IMAGE,
    "donor_mask_image": REPAIR_DONOR_MASK_IMAGE,
    "forbidden_mask_image": REPAIR_FORBIDDEN_MASK_IMAGE,
}

TARGET_APPEARANCE_PROPERTIES = (
    REPAIR_FINGERPRINT_PROPERTY,
    "sbf_repair_uv",
    "sbf_repair_size",
    "sbf_repair_polygon_parts",
    "sbf_repair_polygon_confidence",
    "sbf_repair_seam_pairs",
    "sbf_repair_source_fingerprint",
    "sbf_repair_schema",
    "sbf_repair_metrics",
    "sbf_base_color_image",
    "sbf_base_color_path",
)


def _json_value(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return list(value)
    except TypeError:
        return str(value)


def _property_snapshot(owner, fields):
    return {name: _json_value(getattr(owner, name)) for name in fields}


def _restore_properties(owner, payload, fields):
    for name in fields:
        if name not in payload:
            continue
        try:
            setattr(owner, name, payload[name])
        except (AttributeError, TypeError, ValueError):
            continue


def _hash_uv(layer):
    digest = hashlib.sha256()
    for item in layer.data:
        digest.update(struct.pack("<2f", float(item.uv.x), float(item.uv.y)))
    return digest.hexdigest()


def _mesh_record(target):
    mesh = target.data
    positions = hashlib.sha256()
    for vertex in mesh.vertices:
        positions.update(
            struct.pack("<3f", *(float(value) for value in vertex.co))
        )
    topology = hashlib.sha256()
    for polygon in mesh.polygons:
        topology.update(struct.pack("<II", len(polygon.vertices), polygon.index))
        for index in polygon.vertices:
            topology.update(struct.pack("<I", int(index)))
    uv_contract = []
    base_color_uv = None
    for layer in mesh.uv_layers:
        item = {
            "name": layer.name,
            "loop_sha256": _hash_uv(layer),
        }
        if layer.name == BASE_COLOR_UV_NAME:
            base_color_uv = item
        else:
            uv_contract.append(item)
    return {
        "mesh_id": target.get("sbf_production_mesh_id", ""),
        "mesh_name": mesh.name,
        "object_name_at_creation": target.get(
            "sbf_production_mesh_original_name", target.name
        ),
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "polygons": len(mesh.polygons),
        "loops": len(mesh.loops),
        "positions_sha256": positions.hexdigest(),
        "topology_sha256": topology.hexdigest(),
        "uv_contract": uv_contract,
        "base_color_uv": base_color_uv,
    }


def _production_armature(target):
    candidates = []
    if target.parent is not None and target.parent.type == "ARMATURE":
        candidates.append(target.parent)
    for modifier in target.modifiers:
        if modifier.type == "ARMATURE" and modifier.object is not None:
            if modifier.object not in candidates:
                candidates.append(modifier.object)
    candidates = [
        item for item in candidates if item.get(RIG_PRODUCTION_PROPERTY, False)
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            "Finalize exactly one production rig before creating a variant family."
        )
    return candidates[0]


def _armature_record(armature):
    bones = []
    rest = hashlib.sha256()
    for bone in armature.data.bones:
        values = [float(value) for row in bone.matrix_local for value in row]
        for value in values:
            rest.update(struct.pack("<d", value))
        bones.append(
            {
                "name": bone.name,
                "parent": bone.parent.name if bone.parent else None,
                "deform": bool(bone.use_deform),
            }
        )
    return {
        "object": armature.name,
        "canonical_fingerprint": armature.get(
            "sbf_canonical_fingerprint", ""
        ),
        "canonical_rig_version": armature.get(
            "sbf_canonical_rig_version", ""
        ),
        "canonical_contract_version": armature.get(
            "sbf_rig_contract_version", 0
        ),
        "production_profile": armature.get("sbf_production_profile", ""),
        "production_fingerprint": armature.get(
            "sbf_production_fingerprint", ""
        ),
        "bones": bones,
        "rest_sha256": rest.hexdigest(),
    }


def _weight_record(target, armature):
    bone_names = {bone.name for bone in armature.data.bones if bone.use_deform}
    index_names = {
        group.index: group.name
        for group in target.vertex_groups
        if group.name in bone_names
    }
    digest = hashlib.sha256()
    for vertex in target.data.vertices:
        digest.update(struct.pack("<I", vertex.index))
        values = sorted(
            (
                index_names[item.group],
                float(item.weight),
            )
            for item in vertex.groups
            if item.group in index_names and float(item.weight) > 0.0
        )
        digest.update(struct.pack("<I", len(values)))
        for name, weight in values:
            encoded = name.encode("utf-8")
            digest.update(struct.pack("<I", len(encoded)))
            digest.update(encoded)
            digest.update(struct.pack("<d", weight))
    try:
        report = json.loads(target.get(RIG_WEIGHT_REPORT_PROPERTY, "{}") or "{}")
    except (TypeError, json.JSONDecodeError):
        report = {}
    return {
        "sha256": digest.hexdigest(),
        "report_status": report.get("status", ""),
        "influence_limit": report.get("influence_limit"),
        "unweighted_vertices": report.get("unweighted_vertices"),
    }


def technical_body_record(target, settings, *, create_identity=False):
    """Fingerprint every shared technical invariant without image state."""

    if create_identity and not target.get("sbf_production_mesh_id", ""):
        target["sbf_production_mesh_id"] = uuid.uuid4().hex
        target["sbf_production_mesh_original_name"] = target.name
    if not target.get("sbf_production_mesh_id", ""):
        raise RuntimeError("The production mesh has no stable family identity.")
    armature = _production_armature(target)
    armature_record = _armature_record(armature)
    if not armature_record["production_fingerprint"]:
        raise RuntimeError("The finalized production rig fingerprint is missing.")
    record = {
        "schema": TECHNICAL_BODY_SCHEMA,
        "schema_version": TECHNICAL_BODY_SCHEMA_VERSION,
        "mesh": _mesh_record(target),
        "rig": armature_record,
        "weights": _weight_record(target, armature),
        "coordinate_contract": {
            "forward_axis": settings.forward_axis,
            "up_axis": settings.up_axis,
            "matrix_world": [
                round(float(value), 9)
                for row in target.matrix_world
                for value in row
            ],
            "scale": [round(float(value), 9) for value in target.scale],
        },
    }
    record["fingerprint"] = technical_body_fingerprint(record)
    return record


def active_variant(settings):
    variants = settings.appearance_variants
    index = int(settings.active_variant_index)
    if not settings.appearance_family_id or not 0 <= index < len(variants):
        return None
    return variants[index]


def variant_by_id(settings, variant_id):
    for item in settings.appearance_variants:
        if item.variant_id == variant_id:
            return item
    return None


def image_name_for_settings(settings, base_name):
    variant = active_variant(settings)
    if variant is None:
        return base_name
    return variant_image_name(
        settings.appearance_family_id, variant.variant_id, base_name
    )


def stamp_image_owner(settings, image):
    variant = active_variant(settings)
    if variant is None or image is None:
        return image
    image["sbf_appearance_family_id"] = settings.appearance_family_id
    image["sbf_appearance_variant_id"] = variant.variant_id
    return image


def _ensure_view_states(variant):
    existing = {item.view_name: item for item in variant.views}
    for name in VIEW_NAMES:
        if name not in existing:
            item = variant.views.add()
            item.view_name = name


def _variant_view(variant, name):
    _ensure_view_states(variant)
    for item in variant.views:
        if item.view_name == name:
            return item
    raise RuntimeError(f"Variant view state '{name}' could not be created.")


def _target_state(target):
    if target is None:
        return {}
    return {
        name: _json_value(target[name])
        for name in TARGET_APPEARANCE_PROPERTIES
        if name in target
    }


def _restore_target_state(target, payload):
    if target is None:
        return
    for name in TARGET_APPEARANCE_PROPERTIES:
        if name in target and name not in payload:
            del target[name]
    for name, value in payload.items():
        target[name] = value


def sync_variant_from_settings(settings, variant=None):
    variant = variant or active_variant(settings)
    if variant is None:
        return None
    variant.state_json = stable_json(
        _property_snapshot(settings, APPEARANCE_STATE_FIELDS)
    )
    for name in VIEW_NAMES:
        source = getattr(settings, name)
        stored = _variant_view(variant, name)
        stored.state_json = stable_json(
            _property_snapshot(source, VIEW_STATE_FIELDS)
        )
        stored.source_image = source.image
        stored.cleaned_image = source.cleaned_image
        stored.confidence_image = source.source_confidence_image
    for variant_field, settings_field in SETTINGS_IMAGE_FIELDS.items():
        setattr(variant, variant_field, getattr(settings, settings_field))
    target = settings.target_object
    variant.target_state_json = stable_json(_target_state(target))
    variant.bake_state = "READY" if variant.final_image else "NOT_BAKED"
    variant.repair_state = (
        "CLEAN"
        if (
            settings.repair_state == "READY"
            and settings.repair_unresolved_count
            <= settings.repair_unresolved_threshold
        )
        else "NEEDS_REVIEW"
    )
    variant.diagnostics_json = stable_json(
        {
            "source_doctor_state": settings.source_doctor_state,
            "source_pose_state": settings.source_pose_state,
            "repair_state": settings.repair_state,
            "repair_unresolved_count": settings.repair_unresolved_count,
            "repair_correction_count": settings.repair_correction_count,
            "repair_detected_seam_count": settings.repair_detected_seam_count,
        }
    )
    if (
        variant.final_image is not None
        and target is not None
        and not variant.bake_output_path
    ):
        variant.bake_output_path = target.get("sbf_base_color_path", "")
    if variant.final_image is not None:
        settings.last_baked_image = variant.final_image
    return variant


def _bind_variant_texture(settings, variant):
    material = settings.production_material
    if material is None or material.node_tree is None:
        return
    node = material.node_tree.nodes.get(settings.base_color_node)
    if node is None or node.bl_idname != "ShaderNodeTexImage":
        node = next(
            (
                item
                for item in material.node_tree.nodes
                if item.bl_idname == "ShaderNodeTexImage"
            ),
            None,
        )
    if node is None:
        return
    node.image = variant.final_image
    target = settings.target_object
    if target is not None:
        if variant.final_image is None:
            for key in ("sbf_base_color_image", "sbf_base_color_path"):
                if key in target:
                    del target[key]
        else:
            target["sbf_base_color_image"] = variant.final_image.name
            target["sbf_base_color_path"] = variant.bake_output_path


def restore_variant_to_settings(settings, variant):
    settings.appearance_syncing = True
    try:
        try:
            state = json.loads(variant.state_json or "{}")
        except json.JSONDecodeError:
            state = {}
        _restore_properties(settings, state, APPEARANCE_STATE_FIELDS)
        for name in VIEW_NAMES:
            stored = _variant_view(variant, name)
            view = getattr(settings, name)
            try:
                view_state = json.loads(stored.state_json or "{}")
            except json.JSONDecodeError:
                view_state = {}
            _restore_properties(view, view_state, VIEW_STATE_FIELDS)
            view.image = stored.source_image
            view.cleaned_image = stored.cleaned_image
            view.source_confidence_image = stored.confidence_image
        for variant_field, settings_field in SETTINGS_IMAGE_FIELDS.items():
            setattr(settings, settings_field, getattr(variant, variant_field))
        settings.last_baked_image = variant.final_image
        try:
            target_state = json.loads(variant.target_state_json or "{}")
        except json.JSONDecodeError:
            target_state = {}
        _restore_target_state(settings.target_object, target_state)
        settings.appearance_loaded_variant_id = variant.variant_id
    finally:
        settings.appearance_syncing = False
    _bind_variant_texture(settings, variant)
    return variant


def _cleanup_live_projection(context, settings, previous):
    if context is None or settings.target_object is None:
        return
    try:
        from ..projection import cleanup_temporary_data
        from ..projection.source_processing import cleanup_warped_sources

        cleanup_temporary_data(
            context, settings.target_object, settings.production_material
        )
        cleanup_warped_sources(settings)
        sync_variant_from_settings(settings, previous)
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return


def switch_active_variant(scene, context=None):
    settings = scene.sbf_settings
    if settings.appearance_syncing:
        return None
    destination = active_variant(settings)
    if destination is None:
        return None
    previous = variant_by_id(
        settings, settings.appearance_loaded_variant_id
    )
    if previous is not None and previous != destination:
        sync_variant_from_settings(settings, previous)
        _cleanup_live_projection(context or bpy.context, settings, previous)
    restore_variant_to_settings(settings, destination)
    validate_family_compatibility(settings)
    settings.status_message = (
        f"Active appearance: {destination.display_name}. Shared body unchanged."
    )
    return destination


def _new_variant(settings, display_name):
    variant = settings.appearance_variants.add()
    variant.variant_id = uuid.uuid4().hex
    variant.display_name = display_name
    variant.export_name = variant_export_name(display_name)
    variant.approval_state = "UNAPPROVED"
    variant.technical_state = "VALID"
    variant.bake_state = "NOT_BAKED"
    variant.repair_state = "CLEAN"
    variant.dirty = True
    variant.revision = 1
    _ensure_view_states(variant)
    return variant


def _copy_variant_authoring(source, destination, *, include_sources):
    destination.state_json = source.state_json
    for name in VIEW_NAMES:
        original = _variant_view(source, name)
        copy = _variant_view(destination, name)
        copy.state_json = original.state_json
        copy.source_image = original.source_image if include_sources else None
        copy.cleaned_image = None
        copy.confidence_image = None
        try:
            state = json.loads(copy.state_json or "{}")
        except json.JSONDecodeError:
            state = {}
        for key in (
            "cleaned_fingerprint",
            "cleaned_original_name",
            "source_doctor_metrics_json",
            "body_landmarks_json",
            "body_landmark_image_name",
            "warp_images_json",
            "warp_fingerprint",
            "pose_mismatch_details_json",
        ):
            state[key] = ""
        state["body_landmarks_valid"] = False
        state["pose_mismatch_status"] = "NOT_RUN"
        if not include_sources:
            state["landmark_image_name"] = ""
            state["facial_calibration_valid"] = False
            state["facial_landmarks_set"] = [False] * 4
            state["facial_landmarks_skipped"] = [False] * 4
        copy.state_json = stable_json(state)
    try:
        state = json.loads(destination.state_json or "{}")
    except json.JSONDecodeError:
        state = {}
    state.update(
        {
            "source_doctor_state": "STALE",
            "source_pose_state": "NOT_RUN",
            "source_alignment_status": "Process source plates before preview.",
            "source_preview_ready": False,
            "preview_source_fingerprint": "",
            "repair_state": "NOT_READY",
            "repair_status": "Bake a base-color atlas to begin repair.",
            "repair_source_status": "No surface source set.",
            "repair_clone_source_json": "",
            "repair_selected_seams_json": "[]",
            "repair_unresolved_count": 0,
            "repair_correction_count": 0,
            "repair_detected_seam_count": 0,
            "repair_seam_error_before": 0.0,
            "repair_seam_error_after": 0.0,
        }
    )
    destination.state_json = stable_json(state)
    destination.target_state_json = "{}"


def claim_active_variant_images(settings):
    variant = active_variant(settings)
    if variant is None:
        return
    for field in VARIANT_IMAGE_FIELDS:
        image = getattr(variant, field)
        if image is None or not image.get(REPAIR_OWNER_PROPERTY, False):
            continue
        desired = variant_image_name(
            settings.appearance_family_id,
            variant.variant_id,
            IMAGE_BASE_NAMES[field],
        )
        image.name = desired
        stamp_image_owner(settings, image)
    for view in variant.views:
        for image, base_name in (
            (view.cleaned_image, f"{SOURCE_CLEAN_PREFIX}{view.view_name.upper()}"),
            (
                view.confidence_image,
                f"{SOURCE_CONFIDENCE_PREFIX}{view.view_name.upper()}",
            ),
        ):
            if image is None or not image.get(SOURCE_OWNER_PROPERTY, False):
                continue
            image.name = variant_image_name(
                settings.appearance_family_id, variant.variant_id, base_name
            )
            stamp_image_owner(settings, image)
        diagnostic = bpy.data.images.get(
            f"{SOURCE_DIAGNOSTIC_PREFIX}{view.view_name.upper()}"
        )
        if diagnostic is not None and diagnostic.get(SOURCE_OWNER_PROPERTY, False):
            diagnostic.name = variant_image_name(
                settings.appearance_family_id,
                variant.variant_id,
                f"{SOURCE_DIAGNOSTIC_PREFIX}{view.view_name.upper()}",
            )
            stamp_image_owner(settings, diagnostic)
    _bind_variant_texture(settings, variant)


def create_family(settings, target, display_name=""):
    if settings.appearance_family_id:
        raise RuntimeError("This scene already has an appearance variant family.")
    record = technical_body_record(target, settings, create_identity=True)
    settings.appearance_syncing = True
    try:
        settings.appearance_family_id = uuid.uuid4().hex
        settings.appearance_family_name = display_name.strip() or target.name
        settings.appearance_family_schema = FAMILY_SCHEMA_VERSION
        settings.appearance_technical_body_json = stable_json(record)
        settings.appearance_technical_body_fingerprint = record["fingerprint"]
        settings.appearance_family_status = "VALID"
        settings.appearance_variants.clear()
        initial = _new_variant(settings, "Appearance 1")
        initial.export_name = variant_export_name(
            f"{settings.appearance_family_name}_{initial.display_name}"
        )
        settings.active_variant_index = 0
        settings.appearance_loaded_variant_id = initial.variant_id
    finally:
        settings.appearance_syncing = False
    target["sbf_appearance_family_id"] = settings.appearance_family_id
    sync_variant_from_settings(settings, initial)
    claim_active_variant_images(settings)
    validate_family_compatibility(settings)
    return initial


def add_variant(settings, *, duplicate=False, display_name=""):
    source = active_variant(settings)
    if source is None:
        raise RuntimeError("Create an appearance variant family first.")
    if not validate_family_compatibility(settings):
        raise RuntimeError(
            "Resolve the stale shared technical body before adding an appearance."
        )
    sync_variant_from_settings(settings, source)
    label = display_name.strip() or f"Appearance {len(settings.appearance_variants) + 1}"
    settings.appearance_syncing = True
    try:
        variant = _new_variant(settings, label)
        variant.export_name = variant_export_name(
            f"{settings.appearance_family_name}_{label}"
        )
        _copy_variant_authoring(
            source, variant, include_sources=bool(duplicate)
        )
        settings.active_variant_index = len(settings.appearance_variants) - 1
    finally:
        settings.appearance_syncing = False
    restore_variant_to_settings(settings, variant)
    return variant


def mark_active_variant_dirty(settings, reason="Appearance changed"):
    if settings.appearance_syncing:
        return None
    variant = active_variant(settings)
    if variant is None:
        return None
    variant.revision = max(1, int(variant.revision) + 1)
    variant.dirty = True
    variant.dirty_reason = str(reason)
    variant.approval_state = "DIRTY"
    return variant


def validate_family_compatibility(settings):
    if not settings.appearance_family_id or settings.target_object is None:
        settings.appearance_family_status = "NONE"
        return False
    try:
        current = technical_body_record(settings.target_object, settings)
    except RuntimeError:
        current = None
    valid = bool(
        current
        and current["fingerprint"]
        == settings.appearance_technical_body_fingerprint
    )
    settings.appearance_family_status = "VALID" if valid else "STALE"
    for variant in settings.appearance_variants:
        variant.technical_state = "VALID" if valid else "STALE"
        if not valid and variant.approval_state == "APPROVED":
            variant.approval_state = "STALE"
        elif (
            valid
            and variant.approval_state == "STALE"
            and variant.approval_fingerprint
            and variant.approved_revision == variant.revision
            and not variant.dirty
        ):
            variant.approval_state = "APPROVED"
    return valid


def adopt_initial_bake_uv(settings):
    if not settings.appearance_family_id:
        return False
    if any(item.approval_state == "APPROVED" for item in settings.appearance_variants):
        return validate_family_compatibility(settings)
    previous = json.loads(settings.appearance_technical_body_json or "{}")
    current = technical_body_record(settings.target_object, settings)
    if current["fingerprint"] == settings.appearance_technical_body_fingerprint:
        return True
    if not bake_uv_adoption_allowed(previous, current):
        validate_family_compatibility(settings)
        return False
    settings.appearance_technical_body_json = stable_json(current)
    settings.appearance_technical_body_fingerprint = current["fingerprint"]
    settings.appearance_family_status = "VALID"
    for variant in settings.appearance_variants:
        variant.technical_state = "VALID"
    return True


def _pixel_fingerprint(image):
    if image is None or not image.has_data:
        return ""
    values = array("f", [0.0]) * len(image.pixels)
    image.pixels.foreach_get(values)
    return hashlib.sha256(values.tobytes()).hexdigest()


def appearance_content_fingerprint(settings, variant=None):
    variant = sync_variant_from_settings(settings, variant)
    if variant is None:
        return ""
    views = []
    for item in variant.views:
        source = item.source_image
        views.append(
            {
                "view": item.view_name,
                "state": json.loads(item.state_json or "{}"),
                "source": (
                    {
                        "name": source.name,
                        "filepath": source.filepath,
                        "size": list(source.size),
                        "pixels": _pixel_fingerprint(source),
                    }
                    if source is not None
                    else None
                ),
            }
        )
    images = {
        field: _pixel_fingerprint(getattr(variant, field))
        for field in VARIANT_IMAGE_FIELDS
    }
    return stable_fingerprint(
        {
            "schema": FAMILY_SCHEMA,
            "variant_id": variant.variant_id,
            "revision": int(variant.revision),
            "state": json.loads(variant.state_json or "{}"),
            "views": views,
            "images": images,
            "target_state": json.loads(variant.target_state_json or "{}"),
        }
    )


def approve_active_variant(context):
    settings = context.scene.sbf_settings
    variant = active_variant(settings)
    if variant is None:
        raise RuntimeError("Create an appearance variant family first.")
    if not validate_family_compatibility(settings):
        raise RuntimeError(
            "Approval blocked: the shared technical body no longer matches the family."
        )
    if variant.final_image is None:
        raise RuntimeError("Bake and repair this appearance before approval.")
    from ..baking.repair_service import validate_repair_for_delivery
    from ..validation import validate_target

    info = validate_target(context, settings)
    validate_repair_for_delivery(info, settings)
    sync_variant_from_settings(settings, variant)
    variant.dirty = False
    variant.dirty_reason = ""
    variant.approved_revision = variant.revision
    variant.approval_fingerprint = appearance_content_fingerprint(
        settings, variant
    )
    variant.approved_at_utc = datetime.now(timezone.utc).isoformat()
    variant.approval_state = "APPROVED"
    return variant


def unapprove_active_variant(settings):
    variant = active_variant(settings)
    if variant is None:
        raise RuntimeError("No active appearance variant exists.")
    variant.approval_state = "UNAPPROVED"
    variant.dirty = True
    variant.dirty_reason = "Artist removed approval"
    return variant


def validate_active_variant_for_export(settings):
    variant = active_variant(settings)
    if variant is None:
        raise RuntimeError("No active appearance variant exists.")
    if not validate_family_compatibility(settings):
        raise RuntimeError("Export blocked: shared technical body is incompatible.")
    if (
        variant.approval_state != "APPROVED"
        or variant.dirty
        or variant.approved_revision != variant.revision
    ):
        raise RuntimeError(
            f"Export blocked: '{variant.display_name}' is not currently approved."
        )
    current = appearance_content_fingerprint(settings, variant)
    if current != variant.approval_fingerprint:
        mark_active_variant_dirty(settings, "Appearance changed after approval")
        sync_variant_from_settings(settings, variant)
        raise RuntimeError(
            "Export blocked: appearance pixels or settings changed after approval."
        )
    return variant


def handoff_for_variant(settings, variant):
    return appearance_handoff_record(
        family_id=settings.appearance_family_id,
        family_display_name=settings.appearance_family_name,
        variant_id=variant.variant_id,
        variant_display_name=variant.display_name,
        export_identity=variant.export_name,
        technical_body_fingerprint_value=(
            settings.appearance_technical_body_fingerprint
        ),
        appearance_revision=variant.revision,
        approved_revision=variant.approved_revision,
        approval_fingerprint=variant.approval_fingerprint,
        approved_at_utc=variant.approved_at_utc,
        addon_version=ADDON_VERSION_STRING,
    )


def variant_texture_path(settings, base_path=None):
    variant = active_variant(settings)
    value = base_path or settings.output_image_path
    path = Path(bpy.path.abspath(str(value))).resolve()
    if variant is None:
        return path
    suffix = path.suffix or ".png"
    return path.with_name(f"{variant.export_name}_base_color{suffix}")


def variant_glb_path(settings, variant):
    directory = Path(
        bpy.path.abspath(settings.appearance_export_directory)
    ).resolve()
    return directory / f"{variant.export_name}.glb"


def delete_variant(settings, index):
    if len(settings.appearance_variants) <= 1:
        raise RuntimeError(
            "A variant family must retain one appearance; add another before deleting."
        )
    if not 0 <= index < len(settings.appearance_variants):
        raise RuntimeError("The selected appearance variant no longer exists.")
    doomed = settings.appearance_variants[index]
    if doomed.variant_id == settings.appearance_loaded_variant_id:
        sync_variant_from_settings(settings, doomed)
        _cleanup_live_projection(bpy.context, settings, doomed)
    images = [getattr(doomed, field) for field in VARIANT_IMAGE_FIELDS]
    for view in doomed.views:
        images.extend((view.cleaned_image, view.confidence_image))
    variant_id = doomed.variant_id
    settings.appearance_syncing = True
    try:
        settings.appearance_variants.remove(index)
        settings.active_variant_index = min(
            index, len(settings.appearance_variants) - 1
        )
        settings.appearance_loaded_variant_id = ""
    finally:
        settings.appearance_syncing = False
    for image in images:
        if (
            image is not None
            and image.get("sbf_appearance_family_id", "")
            == settings.appearance_family_id
            and image.get("sbf_appearance_variant_id", "") == variant_id
            and (
                image.get(REPAIR_OWNER_PROPERTY, False)
                or image.get(SOURCE_OWNER_PROPERTY, False)
            )
        ):
            bpy.data.images.remove(image, do_unlink=True)
    restore_variant_to_settings(settings, active_variant(settings))
    return variant_id


def rename_active_variant(settings, display_name):
    variant = active_variant(settings)
    if variant is None:
        raise RuntimeError("No active appearance variant exists.")
    name = display_name.strip()
    if not name:
        raise RuntimeError("Appearance display name cannot be empty.")
    variant.display_name = name
    variant.export_name = variant_export_name(
        f"{settings.appearance_family_name}_{name}"
    )
    mark_active_variant_dirty(settings, "Appearance identity renamed")
    return variant


def pack_family_images(settings):
    for variant in settings.appearance_variants:
        for field in VARIANT_IMAGE_FIELDS:
            image = getattr(variant, field)
            if (
                image is not None
                and image.has_data
                and image.get(REPAIR_OWNER_PROPERTY, False)
                and image.packed_file is None
            ):
                try:
                    image.pack()
                except RuntimeError:
                    pass


@persistent
def _save_pre(_unused):
    for scene in bpy.data.scenes:
        settings = getattr(scene, "sbf_settings", None)
        if settings is None or not settings.appearance_family_id:
            continue
        sync_variant_from_settings(settings)
        pack_family_images(settings)


@persistent
def _load_post(_unused):
    for scene in bpy.data.scenes:
        settings = getattr(scene, "sbf_settings", None)
        if settings is None or not settings.appearance_family_id:
            continue
        if len(settings.appearance_variants):
            settings.active_variant_index = min(
                max(int(settings.active_variant_index), 0),
                len(settings.appearance_variants) - 1,
            )
            restore_variant_to_settings(settings, active_variant(settings))
            validate_family_compatibility(settings)


def register_handlers():
    if _save_pre not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_save_pre)
    if _load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post)


def unregister_handlers():
    if _save_pre in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(_save_pre)
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
