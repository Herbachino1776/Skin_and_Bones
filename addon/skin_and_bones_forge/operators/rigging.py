"""Operators for the Bones automatic humanoid rig vertical slice."""

from __future__ import annotations

from contextlib import AbstractContextManager
import json

import bpy
from bpy.types import Operator
from mathutils import Vector

from ..constants import (
    CANONICAL_FORWARD_AXIS,
    CANONICAL_UP_AXIS,
    RIG_ANALYSIS_PROPERTY,
    RIG_OWNER_PROPERTY,
    RIG_PREVIEW_ARMATURE,
)
from ..rigging import (
    analyze_canonical_rig,
    analyze_target,
    apply_canonical_metadata,
    audit_bind_space,
    audit_production_weights,
    audit_rest_orientation,
    apply_hand_pose,
    apply_saved_corrections,
    bind_production_character,
    clean_rig_preview,
    clean_owned_production_actions,
    clean_weighting_temporary_data,
    confidence_summary,
    convert_legacy_character_yminus,
    create_landmark_preview,
    derive_simplified_contract,
    estimate_landmarks,
    ensure_canonical_rig,
    ensure_unrigged_target_yplus,
    export_rigged_glb,
    fit_skeleton_preview,
    finalize_production_rig,
    landmark_objects,
    load_weight_report,
    production_armature,
    refresh_hand_landmarks,
    refresh_rigging_manifest,
    reset_corrections,
    run_animation_forge_acceptance,
    run_isolated_bone_forensics,
    run_pose_torture_tests,
    save_corrections,
    test_canonical_actions,
    validate_clean_reimport,
    validate_fitted_rig,
    write_contract_report,
)


class _OperationState(AbstractContextManager):
    """Preserve the artist's interaction state around an operator."""

    MODE_MAP = {
        "EDIT_MESH": "EDIT",
        "EDIT_ARMATURE": "EDIT",
        "EDIT_CURVE": "EDIT",
        "EDIT_SURFACE": "EDIT",
        "EDIT_TEXT": "EDIT",
        "EDIT_METABALL": "EDIT",
        "POSE": "POSE",
        "SCULPT": "SCULPT",
        "PAINT_WEIGHT": "WEIGHT_PAINT",
        "PAINT_VERTEX": "VERTEX_PAINT",
        "PAINT_TEXTURE": "TEXTURE_PAINT",
    }

    def __init__(self, context):
        self.context = context
        active = context.view_layer.objects.active
        self.active_name = active.name if active is not None else None
        self.selected_names = [obj.name for obj in context.selected_objects]
        self.mode = context.mode
        self.frame = context.scene.frame_current
        self.cursor = context.scene.cursor.location.copy()

    def __enter__(self):
        if self.context.object is not None and self.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        return self

    def __exit__(self, exc_type, exc, traceback):
        scene = self.context.scene
        scene.frame_set(self.frame)
        scene.cursor.location = self.cursor
        for obj in list(self.context.selected_objects):
            obj.select_set(False)
        for name in self.selected_names:
            obj = bpy.data.objects.get(name)
            if obj is not None and name in self.context.view_layer.objects:
                obj.select_set(True)
        active = bpy.data.objects.get(self.active_name) if self.active_name else None
        if active is not None and active.name in self.context.view_layer.objects:
            self.context.view_layer.objects.active = active
            restore_mode = self.MODE_MAP.get(self.mode)
            if restore_mode:
                try:
                    bpy.ops.object.mode_set(mode=restore_mode)
                except RuntimeError:
                    pass
        return False


def _settings(context):
    return context.scene.sbf_settings


def _target(context, settings):
    target = settings.target_object
    if target is None:
        active = context.view_layer.objects.active
        if active is not None and active.type == "MESH":
            target = active
    if target is None or target.type != "MESH":
        raise ValueError("Choose a production Target Mesh.")
    if target.name not in context.view_layer.objects:
        # Blender can preserve a PointerProperty to an object after that object
        # has been unlinked from every scene collection.  Such an orphan still
        # accepts vertex groups and modifiers, but the dependency graph never
        # evaluates them.  Recover the unique visible intake twin when one
        # exists (for example after an artist duplicates/replaces the clean
        # object) instead of spending minutes binding a no-op target.
        identity_keys = (
            "sbf_intake_token",
            "sbf_normalized_geometry_fingerprint",
        )
        candidates = [
            obj
            for obj in context.view_layer.objects
            if obj.type == "MESH"
            and obj != target
            and all(target.get(key) and obj.get(key) == target.get(key)
                    for key in identity_keys)
        ]
        if len(candidates) > 1:
            raise ValueError(
                f"Target Mesh '{target.name}' is not in the active scene. "
                "Choose the intended visible production mesh; multiple intake "
                "copies have the same identity."
            )
        # The stored pointer is the authoritative processed topology and may
        # already carry artist corrections or a completed bind.  Swap it back
        # into the scene in place of a unique glTF/reimport duplicate instead
        # of silently changing the production target to split topology.
        if candidates:
            duplicate = candidates[0]
            collections = list(duplicate.users_collection)
            for collection in collections:
                collection.objects.unlink(duplicate)
        else:
            collections = [context.scene.collection]
        for collection in collections:
            if target.name not in collection.objects:
                collection.objects.link(target)
        target.hide_viewport = False
        try:
            target.hide_set(False)
        except RuntimeError:
            pass
        context.view_layer.update()
        if target.name not in context.view_layer.objects:
            raise ValueError(
                f"Target Mesh '{target.name}' could not be restored to the "
                "active scene; choose a visible production mesh."
            )
    settings.target_object = target
    return target


def _canonical(context, settings):
    return ensure_canonical_rig(context, settings)


def _contract(context, settings):
    armature = _canonical(context, settings)
    if settings.canonical_contract_json:
        try:
            contract = json.loads(settings.canonical_contract_json)
            if (
                contract.get("armature_data") == armature.data.name
                and contract.get("fingerprint") == settings.canonical_fingerprint
            ):
                return contract
        except json.JSONDecodeError:
            pass
    contract = analyze_canonical_rig(context, armature)
    settings.canonical_contract_json = json.dumps(
        contract, sort_keys=True, separators=(",", ":")
    )
    settings.canonical_fingerprint = contract["fingerprint"]
    return contract


def _production_contract(context, settings):
    full = _contract(context, settings)
    if settings.rig_production_contract_json:
        try:
            contract = json.loads(settings.rig_production_contract_json)
            if (
                contract.get("source_fingerprint") == full["fingerprint"]
                and contract.get("profile_id") == "DSB_SIMPLE_HANDS_V1"
                and contract.get("fingerprint")
                == settings.rig_production_fingerprint
            ):
                return contract
        except json.JSONDecodeError:
            pass
    contract = derive_simplified_contract(full)
    settings.rig_production_contract_json = json.dumps(
        contract, sort_keys=True, separators=(",", ":")
    )
    settings.rig_production_profile = contract["profile_id"]
    settings.rig_production_fingerprint = contract["fingerprint"]
    settings.rig_full_bone_count = contract["source_bone_count"]
    settings.rig_full_deform_bone_count = contract[
        "source_deform_bone_count"
    ]
    settings.rig_removed_finger_bone_count = len(contract["removed_bones"])
    settings.rig_production_bone_count = contract["production_bone_count"]
    return contract


def _bound_armatures(target):
    result = {
        modifier.object
        for modifier in target.modifiers
        if modifier.type == "ARMATURE" and modifier.object is not None
    }
    if target.parent is not None and target.parent.type == "ARMATURE":
        result.add(target.parent)
    return result


def _identity_object_transform(obj, tolerance=1.0e-7):
    return all(
        abs(
            float(
                obj.matrix_world[row][column]
                - (1.0 if row == column else 0.0)
            )
        )
        <= tolerance
        for row in range(4)
        for column in range(4)
    )


def _prepare_target_orientation(context, settings, target):
    """Normalize new meshes or adopt an already-proven persisted Y+ analysis."""

    bound = _bound_armatures(target)
    persisted = target.get(RIG_ANALYSIS_PROPERTY, settings.target_analysis_json)
    if bound and persisted:
        try:
            payload = json.loads(persisted)
            analysis = payload.get("analysis", payload)
        except (TypeError, json.JSONDecodeError):
            analysis = {}
        if (
            analysis.get("target_data") == target.data.name
            and analysis.get("forward_axis") == CANONICAL_FORWARD_AXIS
            and analysis.get("up_axis") == CANONICAL_UP_AXIS
            and len(bound) == 1
            and all(
                _identity_object_transform(obj)
                for obj in [target, *bound]
            )
        ):
            apply_canonical_metadata(next(iter(bound)), target=target)
            settings.forward_axis = CANONICAL_FORWARD_AXIS
            settings.up_axis = CANONICAL_UP_AXIS
            return {"status": "ADOPTED_PERSISTED_YPLUS", "rotated": False}
    result = ensure_unrigged_target_yplus(
        context, target, settings.forward_axis, settings.up_axis
    )
    settings.forward_axis = CANONICAL_FORWARD_AXIS
    settings.up_axis = CANONICAL_UP_AXIS
    return result


def _analyze(context, settings, target):
    _prepare_target_orientation(context, settings, target)
    analysis = analyze_target(
        context, target, settings.forward_axis, settings.up_axis
    )
    landmarks = estimate_landmarks(context, target, analysis)
    apply_saved_corrections(target, landmarks)
    refresh_hand_landmarks(context, target, analysis, landmarks)
    payload = {"analysis": analysis, "landmarks": landmarks}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    settings.target_analysis_json = encoded
    settings.target_height = analysis["world_height"]
    target[RIG_ANALYSIS_PROPERTY] = encoded
    confidence = confidence_summary(landmarks)
    settings.landmark_confidence_summary = (
        f"mean {confidence['mean']:.2f}, min {confidence['minimum']:.2f}, "
        f"{confidence['low_count']} low"
    )
    return analysis, landmarks


def _analysis(context, settings, target, refresh=False):
    orientation = _prepare_target_orientation(context, settings, target)
    refresh = refresh or bool(orientation.get("rotated"))
    if not refresh and settings.target_analysis_json:
        try:
            payload = json.loads(settings.target_analysis_json)
            if payload["analysis"]["target_data"] == target.data.name:
                landmarks = apply_saved_corrections(
                    target, payload["landmarks"]
                )
                refresh_hand_landmarks(
                    context, target, payload["analysis"], landmarks
                )
                return payload["analysis"], landmarks
        except (KeyError, TypeError, json.JSONDecodeError):
            pass
    return _analyze(context, settings, target)


def _fitted(target):
    production = production_armature(target)
    if production is not None:
        return production
    fitted = bpy.data.objects.get(RIG_PREVIEW_ARMATURE)
    if (
        fitted is None
        or fitted.type != "ARMATURE"
        or fitted.get(RIG_OWNER_PROPERTY) != "AUTOMATIC_HUMANOID_RIG_PREVIEW"
        or fitted.get("sbf_rig_target") != target.data.name
    ):
        raise ValueError("Fit a Skeleton Preview for this target first.")
    return fitted


def _fail(operator, settings, exc):
    message = str(exc)
    settings.status_message = f"Rigging error: {message}"
    settings.rig_blocking_warnings = message
    operator.report({"ERROR"}, message)
    return {"CANCELLED"}


def _store_weight_report(settings, report):
    settings.rig_weight_report_json = json.dumps(
        report, sort_keys=True, separators=(",", ":")
    )
    settings.rig_weight_status = report["status"]
    settings.rig_unweighted_count = report["unweighted_vertices"]
    settings.rig_maximum_influences = report["maximum_influences"]
    settings.rig_donor_confidence = report["donor_transfer_confidence"]["mean"]
    settings.rig_proxy_fallback_count = report["proxy_fallback_vertex_count"]


def _invalidate_binding_results(settings, target):
    """Mark an earlier bind and all deformation tests stale after a refit."""

    if target.get("sbf_bound", False):
        settings.rig_weight_status = "NEEDS_REBIND"
    settings.rig_pose_test_status = "NOT_RUN"
    settings.rig_action_test_status = "NOT_RUN"
    settings.rig_pose_test_json = ""
    settings.rig_action_test_json = ""


def _load_json(value, label):
    try:
        return json.loads(value) if value else {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} report is invalid; rerun that test.") from exc


class SBF_OT_load_canonical_rig(Operator):
    bl_idname = "sbf.load_canonical_rig"
    bl_label = "Load Bundled Canonical Rig"
    bl_description = (
        "Append or reuse the verified Y+ canonical humanoid packaged with "
        "Skin & Bones Forge"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                armature = ensure_canonical_rig(context, settings)
                contract = _contract(context, settings)
                production = _production_contract(context, settings)
            settings.rig_recommended_action = "Analyze the target humanoid."
            settings.status_message = (
                f"Bundled canonical rig ready: {armature.name}; "
                f"{len(contract['bones'])} bones; "
                f"{production['profile_id']}."
            )
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_analyze_canonical_rig(Operator):
    bl_idname = "sbf.analyze_canonical_rig"
    bl_label = "Analyze Canonical Rig"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                contract = analyze_canonical_rig(
                    context, _canonical(context, settings)
                )
            settings.canonical_contract_json = json.dumps(
                contract, sort_keys=True, separators=(",", ":")
            )
            settings.canonical_fingerprint = contract["fingerprint"]
            production = _production_contract(context, settings)
            settings.rig_recommended_action = "Analyze the target humanoid."
            settings.status_message = (
                f"Canonical rig: {len(contract['bones'])} bones, fingerprint "
                f"{contract['fingerprint'][:12]}...; "
                f"{production['profile_id']}: "
                f"{production['production_bone_count']} bones."
            )
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (RuntimeError, ValueError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_write_rig_report(Operator):
    bl_idname = "sbf.write_rig_report"
    bl_label = "Write Rig Report"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                contract = _contract(context, settings)
                path = write_contract_report(
                    contract, settings.canonical_report_path
                )
            settings.status_message = f"Wrote canonical rig report: {path}"
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (OSError, RuntimeError, ValueError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_analyze_target_humanoid(Operator):
    bl_idname = "sbf.analyze_target_humanoid"
    bl_label = "Analyze Target Humanoid"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                target = _target(context, settings)
                analysis, landmarks = _analyze(context, settings, target)
            confidence = confidence_summary(landmarks)
            settings.rig_recommended_action = "Generate and inspect landmark preview."
            settings.status_message = (
                f"Target {analysis['world_height']:.4f} m; "
                f"{analysis['connected_components']} components; "
                f"{confidence['low_count']} low-confidence landmarks."
            )
            self.report(
                {"WARNING"} if analysis["warnings"] else {"INFO"},
                settings.status_message,
            )
            return {"FINISHED"}
        except (RuntimeError, ValueError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_generate_rig_landmarks(Operator):
    bl_idname = "sbf.generate_rig_landmarks"
    bl_label = "Generate Landmark Preview"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                target = _target(context, settings)
                _analysis_data, landmarks = _analysis(
                    context, settings, target, refresh=True
                )
                handles = create_landmark_preview(
                    context.scene, target, landmarks, replace=True
                )
            settings.rig_recommended_action = (
                "Move uncertain cyan handles, or fit the skeleton preview."
            )
            settings.status_message = f"Created {len(handles)} editable landmarks."
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (RuntimeError, ValueError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_fit_skeleton_preview(Operator):
    bl_idname = "sbf.fit_skeleton_preview"
    bl_label = "Fit Skeleton Preview"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                target = _target(context, settings)
                source = _canonical(context, settings)
                contract = _production_contract(context, settings)
                _analysis_data, landmarks = _analysis(context, settings, target)
                if not landmark_objects(target):
                    create_landmark_preview(
                        context.scene, target, landmarks, replace=True
                    )
                fitted = fit_skeleton_preview(
                    context,
                    source,
                    target,
                    contract,
                    landmarks,
                )
                settings.rig_hand_pose = "RELAXED"
                _invalidate_binding_results(settings, target)
            settings.rig_validation_state = "NOT_RUN"
            settings.rig_recommended_action = (
                "Inspect handles and skeleton, then validate the fitted skeleton."
            )
            settings.status_message = (
                f"Fitted editable preview '{fitted.name}' with "
                f"{len(fitted.data.bones)} {contract['profile_id']} bones; "
                f"{len(contract['removed_bones'])} finger bones excluded."
            )
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (RuntimeError, ValueError, KeyError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_refit_from_corrections(Operator):
    bl_idname = "sbf.refit_from_corrections"
    bl_label = "Refit From Corrections"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                target = _target(context, settings)
                handles = landmark_objects(target)
                if not handles:
                    raise ValueError("Generate Landmark Preview before refitting.")
                save_corrections(
                    target,
                    {name: handle.matrix_world.translation for name, handle in handles.items()},
                )
                analysis, landmarks = _analyze(context, settings, target)
                source = _canonical(context, settings)
                contract = _production_contract(context, settings)
                fitted = fit_skeleton_preview(
                    context,
                    source,
                    target,
                    contract,
                    landmarks,
                )
                settings.rig_hand_pose = "RELAXED"
                _invalidate_binding_results(settings, target)
                settings.target_analysis_json = json.dumps(
                    {"analysis": analysis, "landmarks": landmarks},
                    sort_keys=True,
                    separators=(",", ":"),
                )
            settings.rig_validation_state = "NOT_RUN"
            settings.rig_recommended_action = "Validate the corrected skeleton."
            settings.status_message = (
                f"Saved corrections and refitted "
                f"{len(fitted.data.bones)} simplified production bones."
            )
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (RuntimeError, ValueError, KeyError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_reset_rig_landmarks(Operator):
    bl_idname = "sbf.reset_rig_landmarks"
    bl_label = "Reset Landmark Corrections"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                target = _target(context, settings)
                reset_corrections(target)
                _analysis_data, landmarks = _analyze(context, settings, target)
                create_landmark_preview(
                    context.scene, target, landmarks, replace=True
                )
            settings.rig_validation_state = "NOT_RUN"
            settings.rig_recommended_action = "Inspect automatic landmarks and refit."
            settings.status_message = "Reset all landmark corrections to automatic detection."
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (RuntimeError, ValueError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_apply_hand_pose(Operator):
    bl_idname = "sbf.apply_hand_pose"
    bl_label = "Apply Hand Pose"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                target = _target(context, settings)
                fitted = _fitted(target)
                pose_name = apply_hand_pose(fitted, settings.rig_hand_pose)
                context.view_layer.update()
            settings.rig_validation_state = "NOT_RUN"
            settings.status_message = (
                f"Applied owned functional hand pose: {pose_name}."
            )
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (RuntimeError, ValueError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_validate_fitted_skeleton(Operator):
    bl_idname = "sbf.validate_fitted_skeleton"
    bl_label = "Validate Fitted Skeleton"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                target = _target(context, settings)
                source = _canonical(context, settings)
                contract = _production_contract(context, settings)
                analysis, landmarks = _analysis(context, settings, target)
                result = validate_fitted_rig(
                    target,
                    source,
                    _fitted(target),
                    contract,
                    analysis,
                    landmarks,
                )
            settings.rig_validation_state = result["status"]
            settings.rig_validation_json = json.dumps(
                result, sort_keys=True, separators=(",", ":")
            )
            messages = result["errors"] + result["warnings"]
            settings.rig_blocking_warnings = " | ".join(messages)
            if result["status"] == "READY_FOR_BINDING":
                settings.rig_recommended_action = (
                    "Skeleton fitting is proven; proceed to the weighting milestone."
                )
            elif result["status"] == "NEEDS_ARTIST_CORRECTION":
                settings.rig_recommended_action = (
                    "Move low-confidence handles, refit, and validate again."
                )
            else:
                settings.rig_recommended_action = (
                    "Resolve blocking validation errors before binding."
                )
            settings.status_message = (
                f"Rig validation: {result['status']} "
                f"(max residual {result['maximum_landmark_residual']:.6f} m)."
            )
            self.report(
                {"ERROR"}
                if result["status"] == "FAILED"
                else {"WARNING"}
                if result["status"] == "NEEDS_ARTIST_CORRECTION"
                else {"INFO"},
                settings.status_message,
            )
            return {"CANCELLED"} if result["status"] == "FAILED" else {"FINISHED"}
        except (RuntimeError, ValueError, KeyError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_clean_rig_preview(Operator):
    bl_idname = "sbf.clean_rig_preview"
    bl_label = "Clean Rig Preview"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                removed = clean_rig_preview(context.scene)
            settings.rig_validation_state = "NOT_RUN"
            settings.rig_recommended_action = "Generate landmarks or fit a new preview."
            settings.status_message = f"Removed {removed} owned rig-preview objects."
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except RuntimeError as exc:
            return _fail(self, settings, exc)


class SBF_OT_bind_production_character(Operator):
    bl_idname = "sbf.bind_production_character"
    bl_label = "Bind Production Character"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                target = _target(context, settings)
                source = _canonical(context, settings)
                contract = _production_contract(context, settings)
                analysis, landmarks = _analysis(context, settings, target)
                fitted = _fitted(target)
                if not target.get("sbf_bound", False):
                    fitted_report = validate_fitted_rig(
                        target, source, fitted, contract, analysis, landmarks
                    )
                    if fitted_report["status"] == "FAILED":
                        raise RuntimeError(
                            "Fitted skeleton has blocking validation errors."
                        )
                report = bind_production_character(
                    context,
                    target,
                    source,
                    fitted,
                    contract,
                    analysis,
                    mode="VOXEL_HEAT_PROXY",
                    threshold=settings.rig_weight_threshold,
                    influence_limit=settings.rig_influence_limit,
                    force_failure=settings.rig_force_binding_failure,
                )
                # Existing .blend files may persist the legacy donor mode.
                # Record the method only after the transactional bind succeeds.
                settings.rig_binding_method = "VOXEL_HEAT_PROXY"
            _store_weight_report(settings, report)
            settings.rig_pose_test_status = "NOT_RUN"
            settings.rig_action_test_status = "NOT_RUN"
            settings.rig_recommended_action = (
                "Validate production weights."
                if report["status"] != "FAILED"
                else "Resolve production weighting errors."
            )
            settings.status_message = (
                f"Binding: {report['status']}; "
                f"{report['unweighted_vertices']} unweighted; "
                f"max {report['maximum_influences']} influences."
            )
            self.report(
                {"INFO"}
                if report["status"] == "READY_FOR_ANIMATION_TEST"
                else {"WARNING"},
                settings.status_message,
            )
            return {"FINISHED"}
        except (RuntimeError, ValueError, KeyError) as exc:
            settings.rig_weight_status = "FAILED"
            return _fail(self, settings, exc)


class SBF_OT_validate_production_weights(Operator):
    bl_idname = "sbf.validate_production_weights"
    bl_label = "Validate Production Weights"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                target = _target(context, settings)
                fitted = _fitted(target)
                analysis, _landmarks = _analysis(context, settings, target)
                prior = load_weight_report(target)
                if prior is None:
                    raise ValueError("Bind the production character first.")
                report = audit_production_weights(
                    target,
                    fitted,
                    analysis,
                    prior,
                    threshold=settings.rig_weight_threshold,
                    influence_limit=settings.rig_influence_limit,
                )
            _store_weight_report(settings, report)
            settings.rig_recommended_action = (
                "Run pose torture tests."
                if report["status"] == "READY_FOR_ANIMATION_TEST"
                else "Review the weight report before pose testing."
            )
            settings.status_message = (
                f"Weights: {report['status']}; "
                f"{report['weighted_vertices']}/{report['total_vertices']} weighted."
            )
            self.report(
                {"INFO"}
                if report["status"] == "READY_FOR_ANIMATION_TEST"
                else {"WARNING"},
                settings.status_message,
            )
            return {"FINISHED"}
        except (RuntimeError, ValueError, KeyError) as exc:
            settings.rig_weight_status = "FAILED"
            return _fail(self, settings, exc)


class SBF_OT_run_pose_torture_tests(Operator):
    bl_idname = "sbf.run_pose_torture_tests"
    bl_label = "Run Pose Torture Tests"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                target = _target(context, settings)
                armature = _fitted(target)
                report = run_pose_torture_tests(
                    context, target, armature, settings.target_height
                )
                analysis, _landmarks = _analysis(context, settings, target)
                isolated = run_isolated_bone_forensics(
                    context, target, armature, analysis
                )
                report["isolated_bone_forensics"] = isolated
                if isolated["status"] != "READY_FOR_ANIMATION_TEST":
                    report["status"] = "POSE_TESTS_FAILED"
            settings.rig_pose_test_json = json.dumps(
                report, sort_keys=True, separators=(",", ":")
            )
            settings.rig_pose_test_status = report["status"]
            settings.rig_recommended_action = (
                "Test the canonical Actions."
                if report["status"] == "POSE_TESTS_PASSED"
                else "Review failed pose deformation checks."
            )
            settings.status_message = f"Pose testing: {report['status']}."
            self.report(
                {"INFO"} if report["status"] == "POSE_TESTS_PASSED" else {"ERROR"},
                settings.status_message,
            )
            return {"FINISHED"} if report["status"] == "POSE_TESTS_PASSED" else {"CANCELLED"}
        except (RuntimeError, ValueError, KeyError) as exc:
            settings.rig_pose_test_status = "POSE_TESTS_FAILED"
            return _fail(self, settings, exc)


class SBF_OT_test_canonical_actions(Operator):
    bl_idname = "sbf.test_canonical_actions"
    bl_label = "Test Canonical Actions"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                target = _target(context, settings)
                armature = _fitted(target)
                source = _canonical(context, settings)
                contract = _production_contract(context, settings)
                analysis, _landmarks = _analysis(context, settings, target)
                weight_report = load_weight_report(target)
                bind_audit = audit_bind_space(context, target, armature)
                rest_audit = audit_rest_orientation(
                    source, armature, contract, analysis
                )
                pose_report = _load_json(
                    settings.rig_pose_test_json, "Pose test"
                )
                if weight_report is None:
                    settings.rig_weight_status = "NEEDS_WEIGHT_REVIEW"
                    raise RuntimeError(
                        "Animation gate blocked: bind and validate weights first."
                    )
                if bind_audit["status"] != "READY_FOR_ANIMATION_TEST":
                    settings.rig_weight_status = "NEEDS_REBIND"
                    raise RuntimeError(
                        "Animation gate blocked: mesh/armature bind space is stale."
                    )
                if rest_audit["status"] != "READY_FOR_ANIMATION_TEST":
                    settings.rig_weight_status = "NEEDS_REBIND"
                    raise RuntimeError(
                        "Animation gate blocked: fitted rest orientation is incompatible."
                    )
                if weight_report["status"] != "READY_FOR_ANIMATION_TEST":
                    settings.rig_weight_status = "NEEDS_WEIGHT_REVIEW"
                    raise RuntimeError(
                        "Animation gate blocked: production weights are not ready."
                    )
                if (
                    pose_report.get("status") != "POSE_TESTS_PASSED"
                    or pose_report.get("isolated_bone_forensics", {}).get(
                        "status"
                    )
                    != "READY_FOR_ANIMATION_TEST"
                ):
                    raise RuntimeError(
                        "Animation gate blocked: isolated-bone forensics must pass."
                    )
                report = test_canonical_actions(
                    context,
                    target,
                    armature,
                    contract,
                    settings.target_height,
                )
                report["pre_animation_gate"] = {
                    "status": "READY_FOR_ANIMATION_TEST",
                    "bind_space": bind_audit,
                    "rest_orientation": rest_audit,
                    "weights": weight_report["status"],
                    "isolated_bones": pose_report[
                        "isolated_bone_forensics"
                    ]["status"],
                }
            settings.rig_action_test_json = json.dumps(
                report, sort_keys=True, separators=(",", ":")
            )
            settings.rig_action_test_status = report["status"]
            settings.rig_filtered_action_count = report.get(
                "filtered_action_count", 0
            )
            settings.rig_removed_finger_channel_count = report.get(
                "removed_finger_channel_count", 0
            )
            settings.rig_recommended_action = (
                "Finalize the production rig."
                if report["status"]
                in {
                    "CANONICAL_ACTIONS_PASSED",
                    "CANONICAL_ACTIONS_NOT_BUNDLED",
                }
                else "Resolve canonical Action compatibility failures."
            )
            settings.status_message = f"Canonical Actions: {report['status']}."
            self.report(
                {"INFO"}
                if report["status"]
                in {
                    "CANONICAL_ACTIONS_PASSED",
                    "CANONICAL_ACTIONS_NOT_BUNDLED",
                }
                else {"ERROR"},
                settings.status_message,
            )
            return (
                {"FINISHED"}
                if report["status"]
                in {
                    "CANONICAL_ACTIONS_PASSED",
                    "CANONICAL_ACTIONS_NOT_BUNDLED",
                }
                else {"CANCELLED"}
            )
        except (RuntimeError, ValueError, KeyError) as exc:
            settings.rig_action_test_status = "CANONICAL_ACTIONS_FAILED"
            return _fail(self, settings, exc)


class SBF_OT_finalize_production_rig(Operator):
    bl_idname = "sbf.finalize_production_rig"
    bl_label = "Finalize Production Rig"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                target = _target(context, settings)
                armature = finalize_production_rig(
                    target,
                    _fitted(target),
                    _production_contract(context, settings),
                    _load_json(settings.rig_pose_test_json, "Pose test"),
                    _load_json(settings.rig_action_test_json, "Canonical Action"),
                )
            settings.rig_recommended_action = "Export the validated rigged GLB."
            settings.status_message = f"Finalized production rig '{armature.name}'."
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (RuntimeError, ValueError, KeyError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_export_rigged_glb(Operator):
    bl_idname = "sbf.export_rigged_glb"
    bl_label = "Export Rigged GLB"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                target = _target(context, settings)
                armature = production_armature(target)
                if armature is None or not armature.get("sbf_production_rig", False):
                    raise ValueError("Finalize the production rig before export.")
                output, manifest = export_rigged_glb(
                    context,
                    target,
                    armature,
                    _production_contract(context, settings),
                    settings,
                )
            settings.rig_export_status = "EXPORTED"
            settings.rig_recommended_action = "Validate the GLB by clean reimport."
            settings.status_message = f"Exported {output}; manifest {manifest.name}."
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            settings.rig_export_status = "EXPORT_FAILED"
            return _fail(self, settings, exc)


class SBF_OT_validate_clean_reimport(Operator):
    bl_idname = "sbf.validate_clean_reimport"
    bl_label = "Validate Clean Reimport"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                target = _target(context, settings)
                contract = _production_contract(context, settings)
                report = validate_clean_reimport(
                    context,
                    bpy.path.abspath(settings.rigged_export_glb_path),
                    contract,
                    settings.target_height,
                )
            settings.rig_reimport_json = json.dumps(
                report, sort_keys=True, separators=(",", ":")
            )
            settings.rig_reimport_status = report["status"]
            armature = production_armature(target)
            if armature is not None:
                refresh_rigging_manifest(
                    settings.rigged_export_glb_path,
                    target,
                    armature,
                    contract,
                    settings,
                )
            settings.rig_recommended_action = (
                "Run Animation Forge acceptance."
                if report["status"] == "CLEAN_REIMPORT_PASSED"
                else "Resolve GLB reimport differences."
            )
            settings.status_message = f"Clean reimport: {report['status']}."
            self.report(
                {"INFO"} if report["status"] == "CLEAN_REIMPORT_PASSED" else {"ERROR"},
                settings.status_message,
            )
            return (
                {"FINISHED"}
                if report["status"] == "CLEAN_REIMPORT_PASSED"
                else {"CANCELLED"}
            )
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            settings.rig_reimport_status = "CLEAN_REIMPORT_FAILED"
            return _fail(self, settings, exc)


class SBF_OT_run_animation_forge_acceptance(Operator):
    bl_idname = "sbf.run_animation_forge_acceptance"
    bl_label = "Run Animation Forge Acceptance"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            report, path = run_animation_forge_acceptance(
                settings.rigged_export_glb_path,
                settings.animation_forge_repository,
            )
            settings.rig_animation_forge_json = json.dumps(
                report, sort_keys=True, separators=(",", ":")
            )
            settings.rig_animation_forge_status = report["status"]
            target = _target(context, settings)
            armature = production_armature(target)
            if armature is not None:
                refresh_rigging_manifest(
                    settings.rigged_export_glb_path,
                    target,
                    armature,
                    _production_contract(context, settings),
                    settings,
                )
            settings.rig_recommended_action = (
                "Production rig milestone accepted."
                if report["status"] == "ANIMATION_FORGE_ACCEPTED"
                else "Review the Animation Forge acceptance report."
            )
            settings.status_message = (
                f"Animation Forge: {report['status']} ({path.name})."
            )
            self.report(
                {"INFO"}
                if report["status"] == "ANIMATION_FORGE_ACCEPTED"
                else {"WARNING"},
                settings.status_message,
            )
            return (
                {"FINISHED"}
                if report["status"] != "ANIMATION_FORGE_REJECTED"
                else {"CANCELLED"}
            )
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            settings.rig_animation_forge_status = "ANIMATION_FORGE_REJECTED"
            return _fail(self, settings, exc)


class SBF_OT_convert_legacy_yminus(Operator):
    bl_idname = "sbf.convert_legacy_yminus"
    bl_label = "Convert Legacy Y- Character"
    bl_description = (
        "Permanently rotate a verified static legacy Y- armature and every "
        "bound mesh into the Y+ canonical basis; animated rigs are refused"
    )
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, _event):
        return context.window_manager.invoke_confirm(
            self,
            event=None,
            title="Convert Legacy Y- Character?",
            message=(
                "This changes armature rest data and bound mesh coordinates. "
                "Save a copy first. Rigs with Actions or NLA are refused."
            ),
            confirm_text="Convert Once",
            icon="ERROR",
        )

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                target = _target(context, settings)
                armatures = _bound_armatures(target)
                if len(armatures) != 1:
                    raise ValueError(
                        "Choose a target bound to exactly one legacy armature."
                    )
                report = convert_legacy_character_yminus(
                    context, next(iter(armatures)), target
                )
            settings.rig_legacy_conversion_json = json.dumps(
                report, sort_keys=True, separators=(",", ":")
            )
            settings.forward_axis = CANONICAL_FORWARD_AXIS
            settings.up_axis = CANONICAL_UP_AXIS
            settings.target_analysis_json = ""
            settings.rig_recommended_action = (
                "Re-analyze the converted Y+ target and validate the rig."
            )
            settings.status_message = (
                "Legacy orientation: " + report["status"]
            )
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (RuntimeError, ValueError, KeyError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_clean_temporary_rigging_data(Operator):
    bl_idname = "sbf.clean_temporary_rigging_data"
    bl_label = "Clean Temporary Rigging Data"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            with _OperationState(context):
                removed = clean_weighting_temporary_data()
                removed.extend(
                    clean_owned_production_actions(
                        production_armature(
                            settings.target_object
                            if settings.target_object is not None
                            else None
                        )
                    )
                )
                for action in list(bpy.data.actions):
                    if action.get("sbf_temporary_pose_test", False):
                        removed.append(action.name)
                        bpy.data.actions.remove(action, do_unlink=True)
            settings.status_message = (
                f"Removed {len(removed)} owned temporary rigging items."
            )
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except RuntimeError as exc:
            return _fail(self, settings, exc)


RIGGING_OPERATOR_CLASSES = (
    SBF_OT_load_canonical_rig,
    SBF_OT_analyze_canonical_rig,
    SBF_OT_write_rig_report,
    SBF_OT_analyze_target_humanoid,
    SBF_OT_generate_rig_landmarks,
    SBF_OT_fit_skeleton_preview,
    SBF_OT_refit_from_corrections,
    SBF_OT_reset_rig_landmarks,
    SBF_OT_apply_hand_pose,
    SBF_OT_validate_fitted_skeleton,
    SBF_OT_clean_rig_preview,
    SBF_OT_bind_production_character,
    SBF_OT_validate_production_weights,
    SBF_OT_run_pose_torture_tests,
    SBF_OT_test_canonical_actions,
    SBF_OT_finalize_production_rig,
    SBF_OT_export_rigged_glb,
    SBF_OT_validate_clean_reimport,
    SBF_OT_run_animation_forge_acceptance,
    SBF_OT_convert_legacy_yminus,
    SBF_OT_clean_temporary_rigging_data,
)
