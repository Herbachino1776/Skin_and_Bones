"""3D Viewport sidebar interface."""

from __future__ import annotations

from bpy.types import Panel

from ..constants import VIEW_LABELS, VIEW_NAMES
from ..projection.alignment import minimum_facial_landmarks


def _draw_view(layout, settings, name):
    view = getattr(settings, name)
    box = layout.box()
    header = box.row(align=True)
    header.prop(
        view,
        "expanded",
        text=VIEW_LABELS[name],
        emboss=False,
        icon="TRIA_DOWN" if view.expanded else "TRIA_RIGHT",
    )
    header.prop(view, "enabled", text="")
    header.prop(view, "occlusion", text="", icon="MOD_MASK")
    if not view.expanded:
        image_state = view.image.name if view.image is not None else "No image"
        header.label(text=image_state, icon="IMAGE_DATA")
        return

    open_image = box.operator(
        "sbf.load_view_image",
        text="Open Image from Disk...",
        icon="FILE_FOLDER",
    )
    open_image.view_name = name
    box.prop(view, "image", text="Loaded")
    doctor = box.row(align=True)
    doctor.enabled = view.image is not None
    process = doctor.operator(
        "sbf.process_source_plate",
        text="PROCESS SOURCE",
        icon="MODIFIER",
    )
    process.view_name = name
    if view.cleaned_image is not None:
        doctor.label(text="Clean", icon="CHECKMARK")
    transforms = box.row(align=True)
    transforms.prop(view, "flip_x", text="Flip X")
    transforms.prop(view, "flip_y", text="Flip Y")
    box.prop(view, "scale")
    box.prop(view, "horizontal_scale")
    offsets = box.row(align=True)
    offsets.prop(view, "offset_x")
    offsets.prop(view, "offset_y")
    head = box.box()
    head.label(text="Head Landmark Alignment", icon="PIVOT_CURSOR")
    calibration = head.row(align=True)
    calibration.enabled = view.image is not None
    calibrate = calibration.operator(
        "sbf.calibrate_face_landmarks",
        text="Place Face Points...",
        icon="EYEDROPPER",
    )
    calibrate.view_name = name
    landmark_count = sum(bool(value) for value in view.facial_landmarks_set)
    if landmark_count >= minimum_facial_landmarks(name):
        apply_landmarks = calibration.operator(
            "sbf.apply_face_calibration",
            text="Reapply",
            icon="CHECKMARK",
        )
        apply_landmarks.view_name = name
    state = "Reference" if name == "front" else "Calibrated"
    if view.facial_calibration_valid:
        head.label(
            text=f"{state}: {landmark_count}/4 facial points",
            icon="CHECKMARK",
        )
    elif landmark_count:
        head.label(
            text=f"Saved: {landmark_count}/4 points (calibrate Front first)",
            icon="INFO",
        )
    head.prop(view, "head_scale")
    head.prop(view, "head_horizontal_scale")
    head_offsets = head.row(align=True)
    head_offsets.prop(view, "head_offset_x")
    head_offsets.prop(view, "head_offset_y")
    weights = box.row(align=True)
    weights.prop(view, "alpha_threshold")
    weights.prop(view, "weight")
    keying = box.row(align=True)
    keying.prop(view, "key_black_background")
    threshold = keying.row(align=True)
    threshold.enabled = view.key_black_background
    threshold.prop(view, "black_key_threshold", text="Threshold")


class SBF_PT_main(Panel):
    bl_label = "Skin & Bones Forge"
    bl_idname = "SBF_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Skin & Bones Forge"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_settings
        layout.operator("sbf.load_preset", icon="PRESET")
        layout.operator(
            "sbf.best_preview",
            text="One-Click Best Preview",
            icon="SHADING_RENDERED",
        )
        status = layout.box()
        status.label(text=settings.status_message, icon="INFO")


class _SBF_PT_section:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Skin & Bones Forge"
    bl_parent_id = "SBF_PT_main"


class SBF_PT_spar3d_intake(_SBF_PT_section, Panel):
    bl_label = "0. SPAR3D Intake & Mesh Prep"
    bl_idname = "SBF_PT_spar3d_intake"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_settings
        primary = layout.column(align=True)
        primary.scale_y = 1.15
        primary.operator(
            "sbf.import_and_prepare_spar3d",
            text="IMPORT + PREPARE SPAR3D CHARACTER",
            icon="IMPORT",
        )
        primary.operator(
            "sbf.prepare_selected_spar3d",
            text="PREPARE SELECTED SPAR3D CHARACTER",
            icon="AUTOMERGE_ON",
        )
        options = layout.box()
        options.prop(settings, "intake_target_height")
        options.prop(settings, "intake_preserve_raw", icon="LOCKED")
        status = layout.box()
        icon = {
            "READY_FOR_SKIN": "CHECKMARK",
            "NEEDS_GEOMETRY_REVIEW": "ERROR",
            "ORIENTATION_REVIEW_REQUIRED": "ORIENTATION_GIMBAL",
            "FAILED": "CANCEL",
        }.get(settings.intake_readiness, "QUESTION")
        status.label(
            text=settings.intake_readiness.replace("_", " ").title(),
            icon=icon,
        )
        status.label(text=settings.intake_status_summary)
        status.label(text=settings.intake_validation_summary)
        status.separator()
        status.label(text=settings.intake_recommended_action, icon="LIGHT")


class SBF_PT_spar3d_intake_advanced(_SBF_PT_section, Panel):
    bl_label = "Advanced Intake Diagnostics"
    bl_idname = "SBF_PT_spar3d_intake_advanced"
    bl_parent_id = "SBF_PT_spar3d_intake"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.operator("sbf.analyze_spar3d", icon="VIEWZOOM")
        layout.operator("sbf.preview_exact_weld", icon="AUTOMERGE_ON")
        layout.operator("sbf.write_intake_report", icon="TEXT")
        layout.operator("sbf.compare_raw_clean", icon="ARROW_LEFTRIGHT")
        rollback = layout.box()
        rollback.label(text="Source & Rollback", icon="RECOVER_LAST")
        rollback.operator("sbf.restore_raw_spar3d", icon="LOOP_BACK")
        rollback.operator("sbf.remove_raw_spar3d", icon="TRASH")
        details = layout.box()
        details.label(text="Diagnostic merge thresholds are report-only.")
        details.label(text=context.scene.sbf_settings.intake_validation_summary)


class SBF_PT_target(_SBF_PT_section, Panel):
    bl_label = "1. Target Character"
    bl_idname = "SBF_PT_target"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_settings
        layout.prop(settings, "target_object")
        layout.prop(settings, "production_material")
        layout.prop(settings, "target_uv")
        axes = layout.row(align=True)
        axes.prop(settings, "forward_axis")
        axes.prop(settings, "up_axis")
        layout.operator("sbf.validate", icon="CHECKMARK")


class SBF_PT_sources(_SBF_PT_section, Panel):
    bl_label = "2. Source Views"
    bl_idname = "SBF_PT_sources"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_settings
        load_folder = layout.column(align=True)
        load_folder.scale_y = 1.15
        load_folder.operator(
            "sbf.load_perspective_folder",
            text="Select Character Perspective Folder",
            icon="FILE_FOLDER",
        )
        layout.prop(settings, "auto_fit_source_images")
        layout.operator("sbf.auto_fit_sources", icon="FULLSCREEN_ENTER")
        layout.label(
            text="Expand only the view you are aligning.",
            icon="IMAGE_DATA",
        )
        layout.label(
            text="Calibrate Front first; other views are corrected independently.",
            icon="PIVOT_CURSOR",
        )
        layout.label(
            text="True profiles need only the visible eye + mouth corner.",
            icon="EYEDROPPER",
        )
        layout.label(
            text="45 deg views are optional, but improve intermediate angles.",
            icon="INFO",
        )
        for name in VIEW_NAMES:
            _draw_view(layout, settings, name)


class SBF_PT_preview(_SBF_PT_section, Panel):
    bl_label = "3. Fit & Live Preview"
    bl_idname = "SBF_PT_preview"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_settings
        layout.prop(settings, "framing_ratio")
        layout.prop(settings, "show_projection_cameras")
        layout.prop(settings, "live_preview", icon="HIDE_OFF")
        row = layout.row(align=True)
        row.operator("sbf.create_preview", icon="MATERIAL")
        row.operator("sbf.refresh_preview", icon="FILE_REFRESH")
        hint = layout.column(align=True)
        hint.scale_y = 0.85
        hint.label(text="Image alignment updates live after preview.")
        hint.label(text="Ownership or occlusion changes need Refresh.")


class SBF_PT_head_protection(_SBF_PT_section, Panel):
    bl_label = "4. Head Identity Protection"
    bl_idname = "SBF_PT_head_protection"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_settings
        layout.prop(settings, "head_identity_lock", icon="LOCKED")
        controls = layout.column()
        controls.enabled = settings.head_identity_lock
        controls.prop(settings, "head_threshold")
        controls.prop(settings, "head_blend_sharpness")
        controls.prop(settings, "source_edge_padding")
        controls.prop(settings, "head_lock_transition")
        layout.label(
            text="Prevents double faces and duplicate ears.",
            icon="MOD_MASK",
        )


class SBF_PT_blending(_SBF_PT_section, Panel):
    bl_label = "Advanced Blending"
    bl_idname = "SBF_PT_blending"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_settings
        layout.prop(settings, "directional_exponent")
        layout.prop(settings, "minimum_weight")
        layout.prop(settings, "lower_front_back_bias")
        layout.prop(settings, "upper_front_back_bias")
        layout.prop(settings, "head_front_back_bias")
        layout.prop(settings, "side_bias")
        layout.prop(settings, "upper_threshold")
        layout.prop(settings, "top_surface_coverage")
        layout.prop(settings, "fallback_threshold")


class SBF_PT_occlusion(_SBF_PT_section, Panel):
    bl_label = "Occlusion"
    bl_idname = "SBF_PT_occlusion"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_settings
        layout.prop(settings, "occlusion_protection")
        column = layout.column()
        column.enabled = settings.occlusion_protection
        column.prop(settings, "visibility_method")
        column.prop(settings, "visibility_samples")
        column.prop(settings, "depth_tolerance_factor")
        column.prop(settings, "occlusion_feather")


class SBF_PT_source_doctor(_SBF_PT_section, Panel):
    bl_label = "5. SOURCE ALIGNMENT DOCTOR"
    bl_idname = "SBF_PT_source_doctor"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_settings
        primary = layout.box().column(align=True)
        primary.scale_y = 1.18
        primary.operator(
            "sbf.process_all_source_plates",
            text="PROCESS ALL SOURCE PLATES",
            icon="MODIFIER",
        )
        primary.operator(
            "sbf.auto_body_landmarks",
            text="AUTO INITIALIZE BODY LANDMARKS",
            icon="EMPTY_AXIS",
        )
        selection = primary.row(align=True)
        selection.prop(settings, "source_doctor_view", text="")
        place = selection.operator(
            "sbf.place_body_landmarks",
            text="PLACE BODY LANDMARKS",
            icon="PIVOT_CURSOR",
        )
        place.view_name = settings.source_doctor_view
        primary.operator(
            "sbf.generate_warped_sources",
            text="GENERATE WARPED SOURCES",
            icon="MOD_MESHDEFORM",
        )
        primary.operator(
            "sbf.best_preview",
            text="REFRESH BEST PREVIEW",
            icon="FILE_REFRESH",
        )

        diagnostics = layout.box()
        state_icon = {
            "READY": "CHECKMARK",
            "STALE": "ERROR",
            "FAILED": "CANCEL",
        }.get(settings.source_doctor_state, "QUESTION")
        diagnostics.label(
            text=f"Contamination: {settings.source_doctor_state.replace('_', ' ').title()}",
            icon=state_icon,
        )
        diagnostics.label(text=f"Pose: {settings.source_pose_state}")
        diagnostics.label(text=settings.source_alignment_status, icon="INFO")
        diagnostics.prop(settings, "show_pose_mismatch", icon="ORIENTATION_GIMBAL")
        if settings.show_pose_mismatch:
            for name in VIEW_NAMES:
                view = getattr(settings, name)
                if view.image is None:
                    continue
                diagnostics.label(
                    text=(
                        f"{VIEW_LABELS[name]}: {view.pose_mismatch_status.title()} "
                        f"{view.pose_mismatch_worst_part.replace('_', ' ')} "
                        f"({view.pose_mismatch_error:.4f})"
                    )
                )


class SBF_PT_source_doctor_advanced(_SBF_PT_section, Panel):
    bl_label = "Advanced Source Doctor"
    bl_idname = "SBF_PT_source_doctor_advanced"
    bl_parent_id = "SBF_PT_source_doctor"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_settings
        layout.prop(settings, "trusted_mask_erosion")
        layout.prop(settings, "rgb_extension_distance")
        layout.prop(settings, "despill_strength")
        layout.prop(settings, "silhouette_confidence_width")
        layout.prop(settings, "warp_joint_feather")
        layout.separator()
        layout.prop(settings, "source_doctor_view")
        row = layout.row(align=True)
        show_contamination = row.operator(
            "sbf.show_source_doctor_image",
            text="SHOW EDGE CONTAMINATION",
            icon="ERROR",
        )
        show_contamination.view_name = settings.source_doctor_view
        show_contamination.image_kind = "CONTAMINATION"
        show_clean = row.operator(
            "sbf.show_source_doctor_image",
            text="SHOW CLEANED SOURCE",
            icon="IMAGE_DATA",
        )
        show_clean.view_name = settings.source_doctor_view
        show_clean.image_kind = "CLEANED"
        actions = layout.row(align=True)
        reset = actions.operator(
            "sbf.reset_body_landmarks",
            text="RESET BODY LANDMARKS",
            icon="LOOP_BACK",
        )
        reset.view_name = settings.source_doctor_view
        restore = actions.operator(
            "sbf.restore_original_source",
            text="RESTORE ORIGINAL SOURCE",
            icon="RECOVER_LAST",
        )
        restore.view_name = settings.source_doctor_view


class SBF_PT_output(_SBF_PT_section, Panel):
    bl_label = "6. Bake Material"
    bl_idname = "SBF_PT_output"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_settings
        layout.prop(settings, "texture_size")
        layout.prop(settings, "bake_margin")
        layout.prop(settings, "generate_bake_uv")
        layout.prop(settings, "roughness")
        layout.prop(settings, "normal_strength")
        layout.prop(settings, "smooth_shading")
        layout.prop(settings, "pack_baked_image")
        layout.prop(settings, "output_image_path")
        layout.operator("sbf.bake_final", icon="RENDER_STILL")


class SBF_PT_texture_repair(_SBF_PT_section, Panel):
    bl_label = "7. TEXTURE REPAIR STUDIO"
    bl_idname = "SBF_PT_texture_repair"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_settings
        ready = settings.repair_state == "READY"
        layer = layout.box()
        layer.enabled = ready
        row = layer.row(align=True)
        row.prop(settings, "repair_enabled", text="Correction Layer")
        row.prop(settings, "repair_opacity", text="Opacity")

        tabs = layer.row(align=True)
        tabs.prop_enum(settings, "repair_mode", "CLONE", text="Clone")
        tabs.prop_enum(settings, "repair_mode", "HEAL", text="Heal")
        tabs.prop_enum(settings, "repair_mode", "SMART_FILL", text="Smart Fill")
        tabs.prop_enum(settings, "repair_mode", "SEAM_HEAL", text="Seam Heal")

        if settings.repair_mode in {"CLONE", "HEAL"}:
            source = layer.row()
            source.scale_y = 1.35
            source.operator(
                "sbf.texture_repair_set_source",
                text="SET SOURCE",
                icon="EYEDROPPER",
            )
            paint = layer.row()
            paint.scale_y = 1.55
            paint.operator(
                "sbf.texture_repair_paint",
                text="APPLY / PAINT REPAIR",
                icon="BRUSH_DATA",
            )
        elif settings.repair_mode == "SMART_FILL":
            smart = layer.row()
            smart.scale_y = 1.55
            smart.operator(
                "sbf.texture_smart_fill",
                text="SMART FILL MASK",
                icon="MOD_MASK",
            )
        else:
            seams = layer.row()
            seams.scale_y = 1.55
            heal = seams.operator(
                "sbf.texture_heal_seams",
                text="HEAL SAFE SEAMS",
                icon="UV_SYNC_SELECT",
            )
            heal.all_safe = True

        controls = layer.column(align=True)
        controls.prop(settings, "repair_brush_size")
        controls.prop(settings, "repair_softness")
        controls.prop(settings, "repair_strength")
        if settings.repair_mode == "HEAL":
            controls.prop(settings, "repair_detail_preservation")

        inspection = layer.row(align=True)
        unresolved = inspection.operator(
            "sbf.texture_display",
            text="Show Unresolved",
            icon="ERROR",
            depress=settings.repair_display == "UNRESOLVED",
        )
        unresolved.display = "UNRESOLVED"
        heatmap = inspection.operator(
            "sbf.texture_display",
            text="Show Seam Heatmap",
            icon="UV",
            depress=settings.repair_display == "SEAM_HEATMAP",
        )
        heatmap.display = "SEAM_HEATMAP"
        comparison = layer.row(align=True)
        before = comparison.operator(
            "sbf.texture_display",
            text="Before",
            depress=settings.repair_display == "BEFORE",
        )
        before.display = "BEFORE"
        after = comparison.operator(
            "sbf.texture_display",
            text="After",
            depress=settings.repair_display == "FINAL",
        )
        after.display = "FINAL"

        commit = layer.row()
        commit.scale_y = 1.5
        commit.operator(
            "sbf.texture_commit_final",
            text="COMMIT FINAL BASE COLOR",
            icon="CHECKMARK",
        )
        layer.operator(
            "sbf.texture_clear_preview",
            text="CLEAR REPAIR PREVIEW",
            icon="HIDE_OFF",
        )
        status = layout.box()
        status.label(text=settings.repair_status, icon="INFO")
        status.label(
            text=(
                f"Corrected {settings.repair_correction_count:,} | "
                f"Unresolved {settings.repair_unresolved_count:,} | "
                f"Seams {settings.repair_detected_seam_count:,}"
            )
        )
        status.label(text=settings.repair_source_status)


class SBF_PT_texture_repair_advanced(_SBF_PT_section, Panel):
    bl_label = "Advanced Texture Repair"
    bl_idname = "SBF_PT_texture_repair_advanced"
    bl_parent_id = "SBF_PT_texture_repair"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_settings
        layout.enabled = settings.repair_state == "READY"
        brush = layout.box()
        brush.label(text="Clone / Heal", icon="BRUSH_DATA")
        brush.prop(settings, "repair_spacing")
        brush.prop(settings, "repair_source_scale")
        brush.prop(settings, "repair_source_rotation")
        brush.prop(settings, "repair_clone_aligned")
        brush.prop(settings, "repair_restrict_part")
        brush.prop(settings, "repair_restrict_material")
        brush.prop(settings, "repair_symmetry")
        brush.prop(settings, "repair_frequency_radius")

        smart = layout.box()
        smart.label(text="Masked Smart Fill", icon="MOD_MASK")
        smart.prop(settings, "repair_smart_fill_target")
        smart.prop(settings, "repair_source_policy")
        smart.prop(settings, "repair_min_donor_confidence")
        smart.prop(settings, "repair_patch_candidates")
        smart.prop(settings, "repair_smart_fill_pixel_limit")
        masks = smart.row(align=True)
        target_mask = masks.operator("sbf.texture_display", text="TARGET MASK")
        target_mask.display = "TARGET_MASK"
        donor_mask = masks.operator("sbf.texture_display", text="DONOR MASK")
        donor_mask.display = "DONOR_MASK"
        forbidden_mask = masks.operator(
            "sbf.texture_display", text="FORBIDDEN MASK"
        )
        forbidden_mask.display = "FORBIDDEN_MASK"
        smart.prop(settings, "repair_target_mask_image")
        smart.prop(settings, "repair_donor_mask_image")
        smart.prop(settings, "repair_forbidden_mask_image")

        seams = layout.box()
        seams.label(text="Geometry-Aware Seam Heal", icon="UV")
        seams.prop(settings, "repair_seam_width")
        seams.prop(settings, "repair_seam_detection_threshold")
        seams.prop(settings, "repair_seam_max_correction")
        detect = seams.row()
        detect.scale_y = 1.25
        detect.operator("sbf.texture_detect_seams", text="DETECT COLOR SEAMS")
        actions = seams.row(align=True)
        selected = actions.operator(
            "sbf.texture_heal_seams", text="HEAL SELECTED SEAMS"
        )
        selected.all_safe = False
        safe = actions.operator(
            "sbf.texture_heal_seams", text="HEAL ALL SAFE SEAMS"
        )
        safe.all_safe = True
        seams.label(
            text=(
                f"Seam error {settings.repair_seam_error_before:.5f} -> "
                f"{settings.repair_seam_error_after:.5f}"
            )
        )

        diagnostics = layout.box()
        diagnostics.label(text="Diagnostics / Layer Safety", icon="IMAGE_DATA")
        diagnostics.prop(settings, "repair_display")
        diagnostics.prop(settings, "repair_unresolved_threshold")
        diagnostics.prop(settings, "repair_correction_image")
        diagnostics.prop(settings, "repair_mask_image")
        diagnostics.prop(settings, "repair_classification_image")
        clears = diagnostics.row(align=True)
        selected_clear = clears.operator(
            "sbf.texture_clear", text="CLEAR SELECTED REGION"
        )
        selected_clear.selected = True
        all_clear = clears.operator("sbf.texture_clear", text="CLEAR ALL")
        all_clear.selected = False


class SBF_PT_delivery(_SBF_PT_section, Panel):
    bl_label = "9. Delivery & Verification"
    bl_idname = "SBF_PT_delivery"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_settings
        layout.prop(settings, "save_blend_path")
        layout.operator("sbf.save_copy", icon="FILE_BLEND")
        layout.prop(settings, "export_glb_path")
        layout.operator("sbf.export_glb", icon="EXPORT")
        layout.prop(settings, "proof_render_dir")
        layout.prop(settings, "proof_resolution")
        layout.operator("sbf.render_verification", icon="RENDERLAYERS")
        layout.prop(settings, "write_manifest")
        layout.prop(settings, "allow_source_overwrite")
        layout.operator("sbf.cleanup", icon="TRASH")


class SBF_PT_bones(_SBF_PT_section, Panel):
    bl_label = "8. Bones — Automatic Humanoid Rig"
    bl_idname = "SBF_PT_bones"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_settings
        layout.prop(settings, "canonical_armature")
        row = layout.row(align=True)
        row.operator("sbf.analyze_canonical_rig", icon="ARMATURE_DATA")
        row.operator("sbf.write_rig_report", icon="TEXT")
        layout.prop(settings, "canonical_report_path")

        fingerprint = settings.canonical_fingerprint
        if len(fingerprint) > 20:
            fingerprint = f"{fingerprint[:20]}..."
        layout.label(
            text=f"Full Canonical Contract: {fingerprint}", icon="KEY_HLT"
        )
        profile = layout.box()
        profile.label(text="Simplified Production Profile", icon="ARMATURE_DATA")
        profile.label(text=settings.rig_production_profile)
        production_fingerprint = settings.rig_production_fingerprint
        if len(production_fingerprint) > 20:
            production_fingerprint = f"{production_fingerprint[:20]}..."
        profile.label(
            text=f"Fingerprint: {production_fingerprint}", icon="KEY_HLT"
        )
        profile.label(
            text=f"Full canonical bones: {settings.rig_full_bone_count}"
        )
        profile.label(
            text=(
                f"Removed finger bones: "
                f"{settings.rig_removed_finger_bone_count}"
            )
        )
        profile.label(
            text=f"Remaining production bones: {settings.rig_production_bone_count}"
        )

        target = layout.box()
        target.label(text="Target & Landmarks", icon="OUTLINER_OB_MESH")
        target.operator("sbf.analyze_target_humanoid", icon="VIEWZOOM")
        target.operator("sbf.generate_rig_landmarks", icon="EMPTY_AXIS")
        target.label(text=f"Height: {settings.target_height:.4f} m")
        target.label(text=settings.landmark_confidence_summary, icon="INFO")

        fit = layout.box()
        fit.label(text="Editable Skeleton Preview", icon="ARMATURE_DATA")
        hand_fit = fit.box()
        hand_fit.label(text="Singular Deforming Hands", icon="BONE_DATA")
        hand_fit.label(text="One retained hand bone per side")
        hand_fit.label(text="Finger chains are excluded")
        hand_fit.label(text="Optional shape keys reserved; not required")
        fit.operator("sbf.fit_skeleton_preview", icon="MOD_ARMATURE")
        row = fit.row(align=True)
        row.operator("sbf.refit_from_corrections", icon="FILE_REFRESH")
        row.operator("sbf.reset_rig_landmarks", icon="LOOP_BACK")
        hand_pose = fit.row(align=True)
        hand_pose.prop(settings, "rig_hand_pose", text="")
        hand_pose.operator("sbf.apply_hand_pose", text="Align Hand")
        fit.operator("sbf.validate_fitted_skeleton", icon="CHECKMARK")
        fit.operator("sbf.clean_rig_preview", icon="TRASH")

        state_icon = {
            "READY_FOR_BINDING": "CHECKMARK",
            "NEEDS_ARTIST_CORRECTION": "ERROR",
            "FAILED": "CANCEL",
        }.get(settings.rig_validation_state, "QUESTION")
        validation_label = settings.rig_validation_state.replace(
            "_", " "
        ).title()
        layout.label(
            text=f"Validation: {validation_label}",
            icon=state_icon,
        )
        if settings.rig_blocking_warnings:
            warnings = layout.box()
            warnings.alert = settings.rig_validation_state == "FAILED"
            for message in settings.rig_blocking_warnings.split(" | ")[:4]:
                warnings.label(text=message, icon="ERROR")

        binding = layout.box()
        binding.label(text="Production Binding", icon="MOD_ARMATURE")
        binding.label(text="Universal Voxel Auto-Skin", icon="MOD_REMESH")
        advanced = binding.column(align=True)
        advanced.prop(settings, "rig_weight_threshold")
        advanced.prop(settings, "rig_influence_limit")
        binding.operator("sbf.bind_production_character", icon="LINKED")
        binding.operator("sbf.validate_production_weights", icon="CHECKMARK")
        weight_icon = {
            "READY_FOR_ANIMATION_TEST": "CHECKMARK",
            "NEEDS_REBIND": "ERROR",
            "NEEDS_WEIGHT_REVIEW": "ERROR",
            "FAILED": "CANCEL",
        }.get(settings.rig_weight_status, "QUESTION")
        binding.label(
            text=f"Weights: {settings.rig_weight_status.replace('_', ' ').title()}",
            icon=weight_icon,
        )
        stats = binding.grid_flow(columns=2, even_columns=True, align=True)
        stats.label(text=f"Unweighted: {settings.rig_unweighted_count}")
        stats.label(text=f"Max influences: {settings.rig_maximum_influences}")
        stats.label(text=f"Donor confidence: {settings.rig_donor_confidence:.3f}")
        stats.label(text=f"Proxy fallback: {settings.rig_proxy_fallback_count}")

        tests = layout.box()
        tests.label(text="Deformation Acceptance", icon="POSE_HLT")
        tests.operator("sbf.run_pose_torture_tests", icon="PLAY")
        tests.label(text=f"Pose tests: {settings.rig_pose_test_status}")
        tests.operator("sbf.test_canonical_actions", icon="ACTION")
        tests.label(text=f"Canonical Actions: {settings.rig_action_test_status}")
        tests.label(
            text=f"Filtered Actions: {settings.rig_filtered_action_count}"
        )
        tests.label(
            text=(
                f"Removed finger channels: "
                f"{settings.rig_removed_finger_channel_count}"
            )
        )
        tests.operator("sbf.finalize_production_rig", icon="ARMATURE_DATA")

        delivery = layout.box()
        delivery.label(text="Rigged GLB & Compatibility", icon="EXPORT")
        delivery.prop(settings, "rigged_export_glb_path")
        delivery.prop(settings, "rig_export_actions")
        delivery.operator("sbf.export_rigged_glb", icon="EXPORT")
        delivery.label(text=f"Export: {settings.rig_export_status}")
        delivery.operator("sbf.validate_clean_reimport", icon="IMPORT")
        delivery.label(text=f"Reimport: {settings.rig_reimport_status}")
        delivery.prop(settings, "animation_forge_repository")
        delivery.operator(
            "sbf.run_animation_forge_acceptance", icon="PLUGIN"
        )
        delivery.label(
            text=f"Animation Forge: {settings.rig_animation_forge_status}"
        )
        delivery.operator("sbf.clean_temporary_rigging_data", icon="TRASH")
        layout.label(text=settings.rig_recommended_action, icon="LIGHT")


PANEL_CLASSES = (
    SBF_PT_main,
    SBF_PT_spar3d_intake,
    SBF_PT_spar3d_intake_advanced,
    SBF_PT_target,
    SBF_PT_sources,
    SBF_PT_preview,
    SBF_PT_head_protection,
    SBF_PT_blending,
    SBF_PT_occlusion,
    SBF_PT_source_doctor,
    SBF_PT_source_doctor_advanced,
    SBF_PT_output,
    SBF_PT_texture_repair,
    SBF_PT_texture_repair_advanced,
    SBF_PT_bones,
    SBF_PT_delivery,
)
