"""Validation for the editable fitted-skeleton preview."""

from __future__ import annotations

import math

from mathutils import Vector

from ..constants import RIG_ARMATURE_MODIFIER, RIG_CONTRACT_PROPERTY
from .analysis import topology_snapshot
from .fitting import bone_endpoint_map
from .hands import hand_metrics
from .landmarks import confidence_summary


def _finite_vector(vector):
    return all(math.isfinite(float(value)) for value in vector)


def _diff(before, after, key):
    return before.get(key) == after.get(key)


def _expected_binding_state_change(target, before, after, production_names):
    """Accept only binding-owned group/modifier changes after an earlier bind."""

    if not target.get("sbf_bound", False):
        return False
    production_names = set(production_names)
    before_groups = [
        name for name in before.get("vertex_groups", [])
        if name not in production_names
    ]
    after_groups = [
        name for name in after.get("vertex_groups", [])
        if name not in production_names
    ]
    before_modifiers = [
        name for name in before.get("armature_modifiers", [])
        if name != RIG_ARMATURE_MODIFIER
    ]
    after_modifiers = [
        name for name in after.get("armature_modifiers", [])
        if name != RIG_ARMATURE_MODIFIER
    ]
    return before_groups == after_groups and before_modifiers == after_modifiers


def validate_fitted_rig(target, canonical, fitted, contract, analysis, landmarks):
    errors = []
    warnings = []
    production_names = [bone["name"] for bone in contract["bones"]]
    fitted_names = [bone.name for bone in fitted.data.bones]
    production_parents = {
        bone["name"]: bone["parent"] for bone in contract["bones"]
    }
    production_deform = {
        bone["name"]: bone["deform"] for bone in contract["bones"]
    }
    fitted_parents = {
        bone.name: bone.parent.name if bone.parent else None
        for bone in fitted.data.bones
    }
    missing = [name for name in production_names if name not in fitted_names]
    extra = [name for name in fitted_names if name not in production_names]
    hierarchy_mismatches = [
        name
        for name in production_names
        if name in fitted_parents
        and fitted_parents[name] != production_parents[name]
    ]
    deform_mismatches = [
        name
        for name in production_names
        if name in fitted.data.bones
        and bool(fitted.data.bones[name].use_deform) != production_deform[name]
    ]
    fingerprint_match = (
        fitted.get(RIG_CONTRACT_PROPERTY) == contract["fingerprint"]
    )
    if not fingerprint_match:
        errors.append("Fitted preview production fingerprint metadata is missing or stale.")
    if missing or extra:
        errors.append("Fitted preview bones do not match the simplified profile.")
    if hierarchy_mismatches:
        errors.append("Fitted preview hierarchy differs from the production contract.")
    if deform_mismatches:
        errors.append("Fitted preview deform flags differ from the production contract.")

    removed = set(contract.get("removed_bones", []))
    retained_removed = sorted(removed.intersection(fitted_names))
    if retained_removed:
        errors.append(
            "Fitted preview retained excluded finger bones: "
            + ", ".join(retained_removed)
        )
    source_records = contract.get("source_bones", [])
    source_names = [bone["name"] for bone in source_records]
    actual_source_names = [bone.name for bone in canonical.data.bones]
    source_parents = {
        bone["name"]: bone["parent"] for bone in source_records
    }
    source_deform = {
        bone["name"]: bool(bone["deform"]) for bone in source_records
    }
    source_unchanged = (
        actual_source_names == source_names
        and all(
            (bone.parent.name if bone.parent else None)
            == source_parents.get(bone.name)
            and bool(bone.use_deform) == source_deform.get(bone.name)
            for bone in canonical.data.bones
        )
    )
    if not source_unchanged:
        errors.append("The full canonical source rig changed during simplified fitting.")

    height = float(analysis["world_height"])
    non_finite = []
    zero_length = []
    short = []
    world_points = []
    for bone in fitted.data.bones:
        head = fitted.matrix_world @ bone.head_local
        tail = fitted.matrix_world @ bone.tail_local
        world_points.extend((head, tail))
        if not _finite_vector(head) or not _finite_vector(tail):
            non_finite.append(bone.name)
        if bone.length <= 1e-7:
            zero_length.append(bone.name)
        elif bone.length < height * 0.0005:
            short.append(bone.name)
    if non_finite:
        errors.append(f"Non-finite bones: {', '.join(non_finite)}")
    if zero_length:
        errors.append(f"Zero-length bones: {', '.join(zero_length)}")
    if short:
        warnings.append(f"Implausibly short bones: {', '.join(short)}")

    lateral = Vector(analysis["lateral_axis_world"])
    center = Vector(analysis["centerline_world"])
    inverted = []
    for base in ("shoulder", "elbow", "wrist", "hip", "knee", "ankle"):
        left = Vector(landmarks[f"{base}_left"]["world"])
        right = Vector(landmarks[f"{base}_right"]["world"])
        if (left - right).dot(lateral) <= 0.0:
            inverted.append(base)
    if inverted:
        errors.append(f"Left/right inversion: {', '.join(inverted)}")

    center_bones = ("body", "body_top0", "body_top1", "body_top2", "neck", "head")
    drifts = {}
    for name in center_bones:
        bone = fitted.data.bones.get(name)
        if bone is None:
            continue
        midpoint = fitted.matrix_world @ ((bone.head_local + bone.tail_local) * 0.5)
        drift = abs((midpoint - center).dot(lateral))
        drifts[name] = round(drift, 6)
    excessive_drift = {
        name: drift for name, drift in drifts.items() if drift > height * 0.035
    }
    if excessive_drift:
        warnings.append("Centerline drift exceeds 3.5% of height.")

    expected = bone_endpoint_map(landmarks)
    residuals = {}
    for name, (head_expected, tail_expected) in expected.items():
        bone = fitted.data.bones.get(name)
        if bone is None:
            continue
        head = fitted.matrix_world @ bone.head_local
        tail = fitted.matrix_world @ bone.tail_local
        residuals[name] = round(
            max((head - head_expected).length, (tail - tail_expected).length),
            7,
        )
    max_residual = max(residuals.values(), default=float("inf"))
    if max_residual > max(1e-5, height * 0.002):
        errors.append(
            f"Landmark fitting residual {max_residual:.6f} m exceeds tolerance."
        )

    hand_validation = hand_metrics(fitted, height)
    if hand_validation["invalid_pose_bones"]:
        errors.append(
            "Invalid hand pose transforms: "
            + ", ".join(hand_validation["invalid_pose_bones"])
        )
    warnings.extend(hand_validation["warnings"])
    hand_bound_errors = []
    for side in ("left", "right"):
        hand = fitted.data.bones.get(f"arm_{side}_hand")
        if hand is None:
            continue
        head = fitted.matrix_world @ hand.head_local
        tail = fitted.matrix_world @ hand.tail_local
        wrist = Vector(landmarks[f"wrist_{side}"]["world"])
        hand_target = Vector(landmarks[f"hand_{side}"]["world"])
        if max((head - wrist).length, (tail - hand_target).length) > height * 0.025:
            hand_bound_errors.append(side)
    if hand_bound_errors:
        errors.append(
            "Singular fitted hand bones exceed target-hand bounds: "
            + ", ".join(hand_bound_errors)
        )

    before = analysis["topology_snapshot"]
    after = topology_snapshot(target)
    topology_unchanged = all(
        _diff(before, after, key)
        for key in ("vertices", "edges", "polygons", "loops", "polygon_vertices")
    )
    vertex_order_unchanged = _diff(before, after, "vertex_positions")
    uv_unchanged = _diff(before, after, "uv_layers")
    materials_unchanged = _diff(before, after, "materials")
    groups_unchanged = _diff(before, after, "vertex_groups")
    modifiers_unchanged = _diff(before, after, "armature_modifiers")
    expected_binding_change = _expected_binding_state_change(
        target,
        before,
        after,
        production_names + contract.get("removed_bones", []),
    )
    if not topology_unchanged:
        errors.append("Production target topology changed.")
    if not vertex_order_unchanged:
        errors.append("Production target vertex positions/order changed.")
    if not uv_unchanged:
        errors.append("Production target UV data changed.")
    if not materials_unchanged:
        errors.append("Production target material slots changed.")
    if not groups_unchanged and not expected_binding_change:
        errors.append("Production target vertex groups changed.")
    if not modifiers_unchanged and not expected_binding_change:
        errors.append("Production target armature modifiers changed.")

    confidence = confidence_summary(landmarks)
    if confidence["low_count"]:
        warnings.append(
            "Low-confidence landmarks: " + ", ".join(confidence["low_landmarks"])
        )

    if errors:
        status = "FAILED"
    elif warnings:
        status = "NEEDS_ARTIST_CORRECTION"
    else:
        status = "READY_FOR_BINDING"
    minimum = [
        min(point[index] for point in world_points) for index in range(3)
    ]
    maximum = [
        max(point[index] for point in world_points) for index in range(3)
    ]
    return {
        "status": status,
        "profile_id": contract.get("profile_id"),
        "source_canonical_fingerprint": contract.get("source_fingerprint"),
        "production_fingerprint": contract["fingerprint"],
        "production_fingerprint_match": fingerprint_match,
        "source_canonical_unchanged": source_unchanged,
        "original_bone_count": len(source_records),
        "original_deform_bone_count": sum(source_deform.values()),
        "removed_finger_bone_count": len(removed),
        "removed_finger_bones": contract.get("removed_bones", []),
        "remaining_production_bone_count": len(production_names),
        "exact_bone_name_match": production_names == fitted_names,
        "hierarchy_match": not hierarchy_mismatches,
        "missing_bones": missing,
        "extra_bones": extra,
        "deform_flag_mismatches": deform_mismatches,
        "non_finite_bones": non_finite,
        "zero_length_bones": zero_length,
        "implausibly_short_bones": short,
        "left_right_inversion": inverted,
        "centerline_drift": drifts,
        "landmark_residuals": residuals,
        "maximum_landmark_residual": max_residual,
        "landmark_confidence": confidence,
        "hand_validation": hand_validation,
        "hand_bounds_match": not hand_bound_errors,
        "target_height": height,
        "fitted_armature_world_bounds": {
            "minimum": [round(value, 6) for value in minimum],
            "maximum": [round(value, 6) for value in maximum],
        },
        "topology_unchanged": topology_unchanged,
        "vertex_order_unchanged": vertex_order_unchanged,
        "uv_unchanged": uv_unchanged,
        "materials_unchanged": materials_unchanged,
        "vertex_groups_unchanged": groups_unchanged,
        "armature_modifiers_unchanged": modifiers_unchanged,
        "expected_binding_state_change": expected_binding_change,
        "errors": errors,
        "warnings": warnings,
    }
