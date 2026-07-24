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


class SBF_PT_output(_SBF_PT_section, Panel):
    bl_label = "5. Bake Material"
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


class SBF_PT_delivery(_SBF_PT_section, Panel):
    bl_label = "6. Delivery & Verification"
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


PANEL_CLASSES = (
    SBF_PT_main,
    SBF_PT_target,
    SBF_PT_sources,
    SBF_PT_preview,
    SBF_PT_head_protection,
    SBF_PT_blending,
    SBF_PT_occlusion,
    SBF_PT_output,
    SBF_PT_delivery,
)
