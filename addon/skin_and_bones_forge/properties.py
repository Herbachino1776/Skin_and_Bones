"""Blender properties exposed by the add-on."""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    BoolVectorProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Image, Material, Object, PropertyGroup

from .constants import (
    EXPORT_BLEND_DIR,
    EXPORT_GLB_DIR,
    EXPORT_PROOF_DIR,
    EXPORT_REPORT_DIR,
    EXPORT_RIGGED_GLB_DIR,
    EXPORT_TEXTURE_DIR,
    VIEW_LABELS,
    VIEW_NAMES,
)


AXIS_ITEMS = (
    ("+X", "+X", "Positive X"),
    ("-X", "-X", "Negative X"),
    ("+Y", "+Y", "Positive Y"),
    ("-Y", "-Y", "Negative Y"),
    ("+Z", "+Z", "Positive Z"),
    ("-Z", "-Z", "Negative Z"),
)

SOURCE_VIEW_ITEMS = tuple(
    (name, VIEW_LABELS[name], f"Edit {VIEW_LABELS[name]} body landmarks")
    for name in VIEW_NAMES
)


def _mesh_object_poll(_self, obj):
    return obj is not None and obj.type == "MESH"


def _armature_object_poll(_self, obj):
    return obj is not None and obj.type == "ARMATURE"


def _update_view_preview(view, context):
    """Push inexpensive source-view edits into an existing preview material."""

    if context is None or context.scene is None:
        return
    settings = getattr(context.scene, "sbf_settings", None)
    if settings is None or not settings.live_preview:
        return
    try:
        from .projection.material import update_preview_view_controls

        update_preview_view_controls(settings, changed_view=view)
    except (AttributeError, ReferenceError, RuntimeError):
        # Property updates must remain safe while Blender registers/unregisters
        # classes or while temporary preview data is being cleaned up.
        return


def _update_view_image(view, context):
    if (
        view.image is not None
        and view.landmark_image_name
        and view.landmark_image_name != view.image.name
    ):
        view.facial_landmarks_set = (False, False, False, False)
        view.facial_landmarks_skipped = (False, False, False, False)
        view.facial_calibration_valid = False
        view.landmark_image_name = ""
    if view.image is None or (
        view.cleaned_original_name and view.cleaned_original_name != view.image.name
    ):
        view.cleaned_image = None
        view.source_confidence_image = None
        view.cleaned_fingerprint = ""
        view.cleaned_original_name = ""
        view.source_doctor_metrics_json = ""
        view.body_landmarks_json = ""
        view.body_landmarks_valid = False
        view.body_landmark_image_name = ""
        view.warp_images_json = ""
        view.warp_fingerprint = ""
        view.pose_mismatch_status = "NOT_RUN"
        view.pose_mismatch_details_json = ""
        if context is not None and context.scene is not None:
            settings = getattr(context.scene, "sbf_settings", None)
            if settings is not None:
                settings.source_doctor_state = "STALE"
                settings.source_preview_ready = False
                settings.preview_source_fingerprint = ""
    if context is not None and context.scene is not None and view.image is not None:
        settings = getattr(context.scene, "sbf_settings", None)
        if settings is not None and settings.auto_fit_source_images:
            try:
                from .projection.alignment import auto_fit_view_image

                auto_fit_view_image(settings, changed_view=view)
            except (AttributeError, ReferenceError, RuntimeError, ValueError):
                pass
    _update_view_preview(view, context)


def _update_all_preview_views(_settings, context):
    if context is None or context.scene is None:
        return
    settings = getattr(context.scene, "sbf_settings", None)
    if settings is None or not settings.live_preview:
        return
    try:
        from .projection.material import update_preview_view_controls

        update_preview_view_controls(settings)
    except (AttributeError, ReferenceError, RuntimeError):
        return


def _invalidate_doctor_settings(_settings, context):
    if context is None or context.scene is None:
        return
    settings = getattr(context.scene, "sbf_settings", None)
    if settings is None:
        return
    try:
        from .projection.source_processing import invalidate_source_alignment

        invalidate_source_alignment(
            settings,
            "Source Doctor settings changed; process plates and regenerate warps.",
            cleaned=True,
        )
    except (AttributeError, ReferenceError, RuntimeError):
        return


def _update_repair_composite(_settings, context):
    if context is None or context.scene is None:
        return
    settings = getattr(context.scene, "sbf_settings", None)
    if settings is None or settings.repair_state != "READY":
        return
    try:
        from .baking.repair_service import (
            commit_final_base_color,
            show_repair_preview,
        )
        from .validation import validate_target

        info = validate_target(context, settings)
        commit_final_base_color(info, settings)
        show_repair_preview(context, info, settings)
    except (AttributeError, ReferenceError, RuntimeError, ValueError, OSError):
        return


def _update_repair_display(_settings, context):
    if context is None or context.scene is None:
        return
    settings = getattr(context.scene, "sbf_settings", None)
    if settings is None or settings.repair_state != "READY":
        return
    try:
        from .baking.repair_service import show_repair_preview
        from .validation import validate_target

        show_repair_preview(context, validate_target(context, settings), settings)
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return


class SBFViewSettings(PropertyGroup):
    image: PointerProperty(
        name="Image",
        description="RGBA projection image for this character view",
        type=Image,
        update=_update_view_image,
    )
    enabled: BoolProperty(
        name="Enabled",
        default=True,
        update=_update_view_preview,
    )
    expanded: BoolProperty(name="Expanded", default=False)
    flip_x: BoolProperty(
        name="Flip X",
        default=False,
        update=_update_view_preview,
    )
    flip_y: BoolProperty(
        name="Flip Y",
        default=False,
        update=_update_view_preview,
    )
    scale: FloatProperty(
        name="Scale",
        description="Scale the source around its center",
        default=1.0,
        min=0.1,
        max=5.0,
        soft_min=0.5,
        soft_max=2.0,
        update=_update_view_preview,
    )
    horizontal_scale: FloatProperty(
        name="Horizontal Fit",
        description=(
            "Independent horizontal source fit used to match the mesh silhouette"
        ),
        default=1.0,
        min=0.1,
        max=5.0,
        soft_min=0.5,
        soft_max=2.0,
        update=_update_view_preview,
    )
    offset_x: FloatProperty(
        name="Horizontal",
        default=0.0,
        min=-2.0,
        max=2.0,
        soft_min=-0.25,
        soft_max=0.25,
        update=_update_view_preview,
    )
    offset_y: FloatProperty(
        name="Vertical",
        default=0.0,
        min=-2.0,
        max=2.0,
        soft_min=-0.25,
        soft_max=0.25,
        update=_update_view_preview,
    )
    head_scale: FloatProperty(
        name="Head Scale",
        description="Additional live scale applied only inside the head region",
        default=1.0,
        min=0.25,
        max=4.0,
        soft_min=0.75,
        soft_max=1.5,
        update=_update_view_preview,
    )
    head_horizontal_scale: FloatProperty(
        name="Head Horizontal Fit",
        description=(
            "Independent horizontal fit for aligning eyes, nose, ears, "
            "and silhouette landmarks"
        ),
        default=1.0,
        min=0.25,
        max=4.0,
        soft_min=0.75,
        soft_max=1.5,
        update=_update_view_preview,
    )
    head_offset_x: FloatProperty(
        name="Head Horizontal",
        default=0.0,
        min=-1.0,
        max=1.0,
        soft_min=-0.15,
        soft_max=0.15,
        update=_update_view_preview,
    )
    head_offset_y: FloatProperty(
        name="Head Vertical",
        default=0.0,
        min=-1.0,
        max=1.0,
        soft_min=-0.15,
        soft_max=0.15,
        update=_update_view_preview,
    )
    eye_image_left: FloatVectorProperty(
        name="Image-Left Eye",
        description="Normalized image position of the eye on the left of the image",
        size=2,
        default=(0.40, 0.75),
        min=0.0,
        max=1.0,
    )
    eye_image_right: FloatVectorProperty(
        name="Image-Right Eye",
        description="Normalized image position of the eye on the right of the image",
        size=2,
        default=(0.60, 0.75),
        min=0.0,
        max=1.0,
    )
    mouth_image_left: FloatVectorProperty(
        name="Image-Left Mouth",
        description="Normalized image position of the mouth corner on the left",
        size=2,
        default=(0.44, 0.65),
        min=0.0,
        max=1.0,
    )
    mouth_image_right: FloatVectorProperty(
        name="Image-Right Mouth",
        description="Normalized image position of the mouth corner on the right",
        size=2,
        default=(0.56, 0.65),
        min=0.0,
        max=1.0,
    )
    facial_landmarks_set: BoolVectorProperty(
        name="Facial Landmarks Set",
        size=4,
        default=(False, False, False, False),
        options={"HIDDEN"},
    )
    facial_landmarks_skipped: BoolVectorProperty(
        name="Facial Landmarks Skipped",
        size=4,
        default=(False, False, False, False),
        options={"HIDDEN"},
    )
    facial_calibration_valid: BoolProperty(
        name="Facial Calibration Ready",
        default=False,
        options={"HIDDEN"},
    )
    landmark_image_name: StringProperty(default="", options={"HIDDEN"})
    cleaned_image: PointerProperty(
        name="Cleaned Source",
        description="Owned non-destructive Source Plate Doctor result",
        type=Image,
        options={"HIDDEN"},
    )
    source_confidence_image: PointerProperty(
        name="Source Confidence",
        description="Owned lower-confidence silhouette-band image",
        type=Image,
        options={"HIDDEN"},
    )
    cleaned_fingerprint: StringProperty(default="", options={"HIDDEN"})
    cleaned_original_name: StringProperty(default="", options={"HIDDEN"})
    source_doctor_metrics_json: StringProperty(default="", options={"HIDDEN"})
    body_landmarks_json: StringProperty(default="", options={"HIDDEN"})
    body_landmarks_valid: BoolProperty(default=False, options={"HIDDEN"})
    body_landmark_image_name: StringProperty(default="", options={"HIDDEN"})
    warp_images_json: StringProperty(default="", options={"HIDDEN"})
    warp_fingerprint: StringProperty(default="", options={"HIDDEN"})
    pose_mismatch_status: EnumProperty(
        name="Pose Mismatch",
        items=(
            ("NOT_RUN", "Not Run", "Pose preflight has not run"),
            ("HIDDEN", "Hidden", "This body part is explicitly hidden"),
            ("ACCEPTABLE", "Acceptable", "Source pose is close to the mesh"),
            ("MODERATE", "Moderate", "Bounded warping can align this pose"),
            ("SEVERE", "Severe", "Artist source-pose review is required"),
        ),
        default="NOT_RUN",
    )
    pose_mismatch_worst_part: StringProperty(default="", options={"HIDDEN"})
    pose_mismatch_error: FloatProperty(default=0.0, options={"HIDDEN"})
    pose_mismatch_details_json: StringProperty(default="", options={"HIDDEN"})
    auto_head_scale: FloatProperty(default=1.0, options={"HIDDEN"})
    auto_head_horizontal_scale: FloatProperty(
        default=1.0,
        options={"HIDDEN"},
    )
    auto_head_offset_x: FloatProperty(default=0.0, options={"HIDDEN"})
    auto_head_offset_y: FloatProperty(default=0.0, options={"HIDDEN"})
    alpha_threshold: FloatProperty(
        name="Alpha Threshold",
        default=0.01,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=_update_view_preview,
    )
    key_black_background: BoolProperty(
        name="Key Black Background",
        description=(
            "Treat a solid black image background as transparent; auto-fit "
            "enables this when needed"
        ),
        default=False,
        update=_update_view_preview,
    )
    black_key_threshold: FloatProperty(
        name="Black Key Threshold",
        default=0.01,
        min=0.0,
        max=0.25,
        soft_max=0.05,
        precision=3,
        update=_update_view_preview,
    )
    weight: FloatProperty(
        name="Overall Weight",
        default=1.0,
        min=0.0,
        max=10.0,
        soft_max=2.0,
        update=_update_view_preview,
    )
    occlusion: BoolProperty(name="Occlusion", default=True)


class SBFSettings(PropertyGroup):
    intake_target_height: FloatProperty(
        name="Target Height",
        description="Normalized production-character height in meters",
        default=1.50,
        min=0.10,
        max=20.0,
        precision=3,
        unit="LENGTH",
    )
    intake_preserve_raw: BoolProperty(
        name="Preserve Raw Source",
        description=(
            "Keep the untouched imported hierarchy in a protected hidden collection"
        ),
        default=True,
    )
    intake_readiness: EnumProperty(
        name="Readiness",
        items=(
            ("NOT_RUN", "Not Run", "SPAR3D intake has not run"),
            ("READY_FOR_SKIN", "Ready for Skin", "All preparation checks passed"),
            (
                "NEEDS_GEOMETRY_REVIEW",
                "Needs Geometry Review",
                "Exact welding succeeded but the surface needs review",
            ),
            (
                "ORIENTATION_REVIEW_REQUIRED",
                "Orientation Review Required",
                "The imported vertical orientation is not confident",
            ),
            ("FAILED", "Failed", "Preparation failed and was rolled back"),
        ),
        default="NOT_RUN",
    )
    intake_status_summary: StringProperty(
        name="Intake Summary",
        default="No SPAR3D character has been prepared.",
    )
    intake_validation_summary: StringProperty(
        name="Validation Summary",
        default="Readiness has not been evaluated.",
    )
    intake_recommended_action: StringProperty(
        name="Recommended Next Action",
        default="Import and prepare a raw SPAR3D character.",
    )
    intake_source_path: StringProperty(default="", options={"HIDDEN"})
    intake_report_json: StringProperty(default="", options={"HIDDEN"})
    intake_test_failure_stage: StringProperty(default="", options={"HIDDEN"})

    target_object: PointerProperty(
        name="Target Mesh",
        description="SPAR3D mesh to process",
        type=Object,
        poll=_mesh_object_poll,
    )
    production_material: PointerProperty(
        name="Production Material",
        type=Material,
    )
    target_uv: StringProperty(name="Target UV", default="")
    base_color_node: StringProperty(name="Base Color Node", default="")
    normal_map_node: StringProperty(name="Normal Map Node", default="")

    forward_axis: EnumProperty(
        name="Forward Axis",
        description="Outward direction of the character's front",
        items=AXIS_ITEMS,
        default="+Y",
    )
    up_axis: EnumProperty(
        name="Up Axis",
        items=AXIS_ITEMS,
        default="+Z",
    )

    front: PointerProperty(type=SBFViewSettings)
    front_left: PointerProperty(type=SBFViewSettings)
    front_right: PointerProperty(type=SBFViewSettings)
    back: PointerProperty(type=SBFViewSettings)
    left: PointerProperty(type=SBFViewSettings)
    right: PointerProperty(type=SBFViewSettings)

    framing_ratio: FloatProperty(
        name="Framing Ratio",
        description="Fraction of the square projection frame occupied by the character",
        default=0.90,
        min=0.25,
        max=1.25,
    )
    show_projection_cameras: BoolProperty(
        name="Show Projection Cameras",
        default=False,
    )
    live_preview: BoolProperty(
        name="Live Alignment Preview",
        description=(
            "Update image, flip, scale, offset, alpha, and overall weight "
            "controls immediately after a projection preview exists"
        ),
        default=True,
        update=_update_all_preview_views,
    )
    auto_fit_source_images: BoolProperty(
        name="Auto-Fit Loaded Images",
        description=(
            "Center and scale each newly loaded source from its alpha silhouette"
        ),
        default=True,
    )
    source_doctor_view: EnumProperty(
        name="Source View",
        items=SOURCE_VIEW_ITEMS,
        default="front",
    )
    trusted_mask_erosion: FloatProperty(
        name="Trusted Mask Erosion",
        description="2K-reference pixels removed from the trusted silhouette edge",
        default=1.5,
        min=0.0,
        max=16.0,
        precision=1,
        update=_invalidate_doctor_settings,
    )
    rgb_extension_distance: FloatProperty(
        name="RGB Extension Distance",
        description="2K-reference pixels of foreground RGB extended under transparency",
        default=12.0,
        min=0.0,
        max=128.0,
        precision=1,
        update=_invalidate_doctor_settings,
    )
    despill_strength: FloatProperty(
        name="Despill Strength",
        description="Remove detected green, pink, gray, or monochrome edge spill",
        default=0.85,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=_invalidate_doctor_settings,
    )
    silhouette_confidence_width: FloatProperty(
        name="Silhouette Confidence Width",
        description="2K-reference pixel width marked as lower projection confidence",
        default=8.0,
        min=0.0,
        max=64.0,
        precision=1,
        update=_invalidate_doctor_settings,
    )
    warp_joint_feather: FloatProperty(
        name="Joint Feather",
        description="Bounded feather inside per-part warp triangles",
        default=0.08,
        min=0.0,
        max=0.25,
        subtype="FACTOR",
        update=_invalidate_doctor_settings,
    )
    show_edge_contamination: BoolProperty(
        name="Show Edge Contamination",
        default=False,
    )
    show_cleaned_source: BoolProperty(
        name="Show Cleaned Source",
        default=False,
    )
    show_pose_mismatch: BoolProperty(
        name="Show Pose Mismatch",
        default=False,
    )
    source_doctor_state: EnumProperty(
        name="Plate Doctor",
        items=(
            ("NOT_RUN", "Not Run", "Source plates have not been processed"),
            ("STALE", "Stale", "Settings or source state changed"),
            ("READY", "Ready", "All enabled source plates are cleaned"),
            ("FAILED", "Failed", "Source processing failed"),
        ),
        default="NOT_RUN",
    )
    source_pose_state: StringProperty(
        name="Pose Preflight",
        default="NOT_RUN",
    )
    source_alignment_status: StringProperty(
        name="Source Alignment Status",
        default="Process source plates before preview.",
    )
    source_preview_ready: BoolProperty(default=False, options={"HIDDEN"})
    preview_source_fingerprint: StringProperty(default="", options={"HIDDEN"})

    directional_exponent: FloatProperty(
        name="Directional Exponent",
        default=4.0,
        min=0.25,
        max=16.0,
    )
    minimum_weight: FloatProperty(
        name="Minimum Weight",
        default=0.001,
        min=0.0,
        max=0.1,
        precision=4,
    )
    lower_front_back_bias: FloatProperty(
        name="Lower Front/Back",
        default=3.0,
        min=0.0,
        max=100.0,
    )
    upper_front_back_bias: FloatProperty(
        name="Upper Front/Back",
        default=10.0,
        min=0.0,
        max=100.0,
    )
    head_front_back_bias: FloatProperty(
        name="Head Front/Back",
        default=1.25,
        min=0.0,
        max=200.0,
    )
    head_identity_lock: BoolProperty(
        name="Identity-Safe Head Blend",
        description=(
            "Use a strongly confidence-weighted blend for the head so adjacent "
            "aligned sources transition without duplicate faces or hard seams"
        ),
        default=True,
    )
    head_blend_sharpness: FloatProperty(
        name="Head Blend Sharpness",
        description=(
            "Higher values narrow the transition between the strongest aligned "
            "head sources; lower values soften source seams"
        ),
        default=3.0,
        min=1.0,
        max=12.0,
        soft_max=6.0,
        update=_update_all_preview_views,
    )
    source_edge_padding: FloatProperty(
        name="Source Edge Padding",
        description=(
            "Fill small scalp, jaw, and shoulder projection gaps from a nearby "
            "valid sample inside each aligned source silhouette"
        ),
        default=0.05,
        min=0.0,
        max=0.20,
        soft_max=0.10,
        subtype="FACTOR",
        update=_update_all_preview_views,
    )
    head_lock_transition: FloatProperty(
        name="Neck Transition",
        description="Vertical feather between body blending and head ownership",
        default=0.025,
        min=0.0,
        max=0.2,
        soft_max=0.08,
        precision=3,
    )
    side_bias: FloatProperty(
        name="Side Bias",
        default=1.0,
        min=0.0,
        max=20.0,
    )
    upper_threshold: FloatProperty(
        name="Upper Threshold",
        default=0.58,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    head_threshold: FloatProperty(
        name="Head Threshold",
        default=0.80,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    top_surface_coverage: FloatProperty(
        name="Top Coverage",
        default=0.90,
        min=0.0,
        max=2.0,
    )
    fallback_threshold: FloatProperty(
        name="Fallback Threshold",
        default=0.01,
        min=0.0,
        max=1.0,
        precision=3,
    )

    occlusion_protection: BoolProperty(
        name="Occlusion Protection",
        description="Reject source views when the target point is not the first surface hit",
        default=True,
    )
    visibility_method: EnumProperty(
        name="Visibility Method",
        items=(
            (
                "RAY_CAST",
                "Ray Cast",
                "Check first-surface visibility at polygon centers and vertices",
            ),
        ),
        default="RAY_CAST",
    )
    visibility_samples: EnumProperty(
        name="Visibility Samples",
        items=(
            ("VERTEX", "Vertices", "Check loop vertices"),
            (
                "CENTER_VERTEX",
                "Centers + Vertices",
                "Conservatively require polygon center and vertex visibility",
            ),
        ),
        default="CENTER_VERTEX",
    )
    depth_tolerance_factor: FloatProperty(
        name="Depth Tolerance",
        description="First-hit tolerance relative to character height",
        default=0.003,
        min=0.00001,
        max=0.05,
        precision=5,
    )
    occlusion_feather: FloatProperty(
        name="Occlusion Feather",
        description="Soft transition beyond the strict depth tolerance",
        default=0.25,
        min=0.0,
        max=4.0,
    )

    texture_size: EnumProperty(
        name="Texture Size",
        items=(
            ("1024", "1024", "1024 x 1024"),
            ("2048", "2048", "2048 x 2048"),
            ("4096", "4096", "4096 x 4096"),
            ("8192", "8192", "8192 x 8192"),
        ),
        default="4096",
    )
    bake_margin: IntProperty(name="Bake Margin", default=24, min=0, max=256)
    generate_bake_uv: BoolProperty(
        name="Clean Base-Color UV",
        description=(
            "Generate a dedicated connected UV atlas for the baked base color "
            "while keeping the original UV assigned to normal and other maps"
        ),
        default=True,
    )
    roughness: FloatProperty(
        name="Roughness",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    normal_strength: FloatProperty(
        name="Normal Strength",
        default=0.25,
        min=0.0,
        max=5.0,
    )
    smooth_shading: BoolProperty(name="Smooth Shading", default=True)
    pack_baked_image: BoolProperty(name="Pack Baked Image", default=True)
    output_image_path: StringProperty(
        name="Base Color Path",
        subtype="FILE_PATH",
        default=rf"{EXPORT_TEXTURE_DIR}\rebuilt_base_color.png",
    )
    save_blend_path: StringProperty(
        name="New Blender File",
        subtype="FILE_PATH",
        default=rf"{EXPORT_BLEND_DIR}\character_sbf.blend",
    )
    export_glb_path: StringProperty(
        name="New GLB",
        subtype="FILE_PATH",
        default=rf"{EXPORT_GLB_DIR}\character_sbf.glb",
    )
    proof_render_dir: StringProperty(
        name="Proof Render Folder",
        subtype="DIR_PATH",
        default=EXPORT_PROOF_DIR + "\\",
    )
    proof_resolution: IntProperty(
        name="Proof Resolution",
        default=1024,
        min=128,
        max=4096,
    )
    write_manifest: BoolProperty(name="Write Processing Manifest", default=True)
    allow_source_overwrite: BoolProperty(
        name="Allow Source Overwrite",
        description="Permit output paths to replace the currently open Blender file",
        default=False,
    )
    last_baked_image: PointerProperty(name="Last Baked Image", type=Image)
    last_raw_baked_image: PointerProperty(name="Original Baked Image", type=Image)
    repair_correction_image: PointerProperty(
        name="Texture Corrections", type=Image
    )
    repair_mask_image: PointerProperty(name="Correction Mask", type=Image)
    repair_final_image: PointerProperty(name="Final Base Color", type=Image)
    repair_classification_image: PointerProperty(
        name="Source Classification", type=Image
    )
    repair_target_mask_image: PointerProperty(
        name="Smart Fill Target Mask", type=Image
    )
    repair_donor_mask_image: PointerProperty(
        name="Artist Donor Mask", type=Image
    )
    repair_forbidden_mask_image: PointerProperty(
        name="Forbidden Source Mask", type=Image
    )
    repair_enabled: BoolProperty(
        name="Enable Correction Layer",
        default=True,
        update=_update_repair_composite,
    )
    repair_opacity: FloatProperty(
        name="Correction Opacity",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=_update_repair_composite,
    )
    repair_mode: EnumProperty(
        name="Repair Mode",
        items=(
            (
                "CLONE",
                "Clone",
                "Copy surface detail through production UV tangent space",
            ),
            (
                "HEAL",
                "Heal",
                "Adapt copied detail to target low-frequency color",
            ),
            (
                "SMART_FILL",
                "Smart Fill",
                "Fill only the explicit atlas repair mask",
            ),
            (
                "SEAM_HEAL",
                "Seam Heal",
                "Harmonize paired geometric UV seam bands",
            ),
        ),
        default="CLONE",
    )
    repair_brush_size: FloatProperty(
        name="Size",
        description="Brush radius in atlas pixels",
        default=32.0,
        min=1.0,
        max=512.0,
        soft_max=128.0,
    )
    repair_softness: FloatProperty(
        name="Softness",
        default=0.55,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    repair_strength: FloatProperty(
        name="Strength",
        default=0.85,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    repair_spacing: FloatProperty(
        name="Spacing",
        description="Viewport brush spacing as a fraction of brush diameter",
        default=0.20,
        min=0.02,
        max=1.0,
        subtype="FACTOR",
    )
    repair_detail_preservation: FloatProperty(
        name="Detail Preservation",
        default=0.85,
        min=0.0,
        max=1.5,
        soft_max=1.0,
        subtype="FACTOR",
    )
    repair_source_scale: FloatProperty(
        name="Source Scale", default=1.0, min=0.1, max=5.0
    )
    repair_source_rotation: FloatProperty(
        name="Source Rotation",
        default=0.0,
        min=-3.14159265,
        max=3.14159265,
        subtype="ANGLE",
    )
    repair_clone_aligned: BoolProperty(
        name="Aligned Source",
        description="Advance the source anchor with the target stroke",
        default=True,
    )
    repair_restrict_part: BoolProperty(
        name="Restrict to Semantic Part", default=True
    )
    repair_restrict_material: BoolProperty(
        name="Restrict to Material", default=True
    )
    repair_symmetry: BoolProperty(
        name="Left / Right Symmetry",
        description="Also apply to the anatomically opposite surface when available",
        default=False,
    )
    repair_frequency_radius: IntProperty(
        name="Frequency Radius", default=4, min=1, max=64
    )
    repair_smart_fill_target: EnumProperty(
        name="Fill Target",
        items=(
            (
                "UNRESOLVED",
                "Detected Unresolved",
                "Use only detected unresolved texels",
            ),
            (
                "SELECTED_FACES",
                "Selected Faces",
                "Convert selected faces to an atlas mask",
            ),
            ("ARTIST_MASK", "Artist-Painted Mask", "Use the owned target mask image"),
        ),
        default="UNRESOLVED",
    )
    repair_source_policy: EnumProperty(
        name="Donor Policy",
        items=(
            ("SAME_PART", "Same Part", "Use the same semantic part and material"),
            (
                "OPPOSITE_SYMMETRIC_PART",
                "Opposite Symmetric Part",
                "Use the opposite limb with the same material",
            ),
            (
                "SAME_MATERIAL",
                "Same Material",
                "Use the same material within the same or opposite body part",
            ),
            (
                "ARTIST_PAINTED_DONOR_MASK",
                "Artist-Painted Donor Mask",
                "Use only the artist donor mask and matching material",
            ),
            (
                "COMBINED_SAFE_SOURCES",
                "Combined Safe Sources",
                "Use same/opposite part or artist donors within the same material",
            ),
        ),
        default="COMBINED_SAFE_SOURCES",
    )
    repair_min_donor_confidence: FloatProperty(
        name="Minimum Donor Confidence",
        default=0.20,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    repair_patch_candidates: IntProperty(
        name="Patch Candidates", default=96, min=8, max=512
    )
    repair_smart_fill_pixel_limit: IntProperty(
        name="Smart Fill Pixel Limit",
        default=250000,
        min=1,
        max=4000000,
    )
    repair_seam_width: IntProperty(
        name="Seam Width", default=4, min=1, max=64
    )
    repair_seam_max_correction: FloatProperty(
        name="Maximum Accepted Correction",
        default=0.35,
        min=0.001,
        max=1.732,
        precision=3,
    )
    repair_seam_detection_threshold: FloatProperty(
        name="Seam Detection Threshold",
        default=0.045,
        min=0.001,
        max=1.732,
        precision=3,
    )
    repair_unresolved_threshold: IntProperty(
        name="Safe Unresolved Threshold",
        description="Maximum unresolved atlas pixels allowed for delivery",
        default=0,
        min=0,
        max=10000000,
    )
    repair_display: EnumProperty(
        name="Inspection",
        items=(
            ("FINAL", "After", "Live final composite"),
            ("BEFORE", "Before", "Original non-destructive bake"),
            ("UNRESOLVED", "Unresolved", "Unresolved/uncovered texel overlay"),
            ("SEAM_HEATMAP", "Seam Heatmap", "Measured base-color seam overlay"),
            ("CORRECTION_MASK", "Correction Mask", "Correction blend mask"),
            ("CLASSIFICATION", "Classification", "Per-texel source classification"),
            (
                "SOURCE_CONTAMINATION",
                "Source Contamination",
                "Source Doctor and low-confidence projection overlay",
            ),
            ("TARGET_MASK", "Target Mask", "Artist-painted Smart Fill target mask"),
            ("DONOR_MASK", "Donor Mask", "Artist-painted safe donor mask"),
            ("FORBIDDEN_MASK", "Forbidden Mask", "Explicit forbidden-source mask"),
            ("UNLIT_FINAL", "Unlit Final", "Unlit final base-color inspection"),
        ),
        default="FINAL",
        update=_update_repair_display,
    )
    repair_state: EnumProperty(
        name="Texture Repair",
        items=(
            ("NOT_READY", "Not Ready", "Bake a base-color atlas first"),
            ("READY", "Ready", "Owned compatible repair layers are ready"),
            ("STALE", "Stale", "Topology, UV, or atlas size changed"),
            ("FAILED", "Failed", "Repair operation failed and rolled back"),
        ),
        default="NOT_READY",
    )
    repair_status: StringProperty(
        name="Repair Status", default="Bake a base-color atlas to begin repair."
    )
    repair_source_status: StringProperty(
        name="Clone Source", default="No surface source set."
    )
    repair_clone_source_json: StringProperty(default="", options={"HIDDEN"})
    repair_selected_seams_json: StringProperty(default="[]", options={"HIDDEN"})
    repair_unresolved_count: IntProperty(name="Unresolved", default=0)
    repair_correction_count: IntProperty(name="Corrected", default=0)
    repair_detected_seam_count: IntProperty(name="Detected Seams", default=0)
    repair_seam_error_before: FloatProperty(name="Seam Error Before", default=0.0)
    repair_seam_error_after: FloatProperty(name="Seam Error After", default=0.0)
    status_message: StringProperty(name="Status", default="Ready")

    canonical_armature: PointerProperty(
        name="Canonical Rig Source",
        description="Known-good Animate Anything armature in the current file",
        type=Object,
        poll=_armature_object_poll,
    )
    canonical_report_path: StringProperty(
        name="Rig Report",
        subtype="FILE_PATH",
        default=rf"{EXPORT_REPORT_DIR}\canonical_rig_report.json",
    )
    canonical_contract_json: StringProperty(default="", options={"HIDDEN"})
    canonical_fingerprint: StringProperty(
        name="Canonical Fingerprint",
        default="Not analyzed",
    )
    target_analysis_json: StringProperty(default="", options={"HIDDEN"})
    target_height: FloatProperty(
        name="Target Height",
        default=0.0,
        precision=4,
        unit="LENGTH",
    )
    landmark_confidence_summary: StringProperty(
        name="Landmark Confidence",
        default="Not analyzed",
    )
    rig_validation_state: EnumProperty(
        name="Rig Validation",
        items=(
            ("NOT_RUN", "Not Run", "No fitted-rig validation has run"),
            ("READY_FOR_BINDING", "Ready for Binding", "Skeleton checks passed"),
            (
                "NEEDS_ARTIST_CORRECTION",
                "Needs Artist Correction",
                "Preview is structurally valid but uncertain landmarks need review",
            ),
            ("FAILED", "Failed", "Blocking fitted-rig validation errors"),
        ),
        default="NOT_RUN",
    )
    rig_blocking_warnings: StringProperty(default="", options={"HIDDEN"})
    rig_validation_json: StringProperty(default="", options={"HIDDEN"})
    rig_production_profile: StringProperty(
        name="Simplified Production Profile",
        default="DSB_SIMPLE_HANDS_V1",
    )
    rig_production_contract_json: StringProperty(
        default="", options={"HIDDEN"}
    )
    rig_production_fingerprint: StringProperty(
        name="Production Fingerprint",
        default="Not generated",
    )
    rig_full_bone_count: IntProperty(name="Full Canonical Bones", default=0)
    rig_full_deform_bone_count: IntProperty(
        name="Full Canonical Deform Bones", default=0
    )
    rig_removed_finger_bone_count: IntProperty(
        name="Removed Finger Bones", default=0
    )
    rig_production_bone_count: IntProperty(
        name="Production Bones", default=0
    )
    rig_filtered_action_count: IntProperty(
        name="Filtered Actions", default=0
    )
    rig_removed_finger_channel_count: IntProperty(
        name="Removed Finger Channels", default=0
    )
    rig_hand_pose: EnumProperty(
        name="Whole-Hand Alignment",
        items=(
            ("RELAXED", "Relaxed", "Neutral singular hand-bone alignment"),
            (
                "OPEN_MAGIC",
                "Open Magic Direction",
                "Aim the whole hand for casting; does not articulate fingers",
            ),
            (
                "GRIP_SHAFT",
                "Grip Shaft Alignment",
                "Align the whole hand to a shaft; does not articulate fingers",
            ),
        ),
        default="RELAXED",
    )
    rig_binding_method: EnumProperty(
        name="Binding Method",
        items=(
            (
                "VOXEL_HEAT_PROXY",
                "Universal Voxel Auto-Skin",
                "Bone-heat a temporary watertight proxy and transfer weights "
                "back to the unchanged production mesh",
            ),
            (
                "CANONICAL_TRANSFER_WITH_PROXY_FALLBACK",
                "Canonical + Proxy Fallback",
                "Transfer canonical donor weights and repair low-confidence vertices",
            ),
            (
                "CANONICAL_TRANSFER",
                "Canonical Transfer",
                "Canonical surface transfer with fallback only for unweighted vertices",
            ),
            (
                "AUTOMATIC_WEIGHTS_DIAGNOSTIC",
                "Automatic Diagnostic",
                "Diagnostic anatomical proxy weights; not the production default",
            ),
        ),
        default="VOXEL_HEAT_PROXY",
    )
    rig_weight_threshold: FloatProperty(
        name="Tiny Weight Threshold",
        default=0.0001,
        min=0.0,
        max=0.05,
        precision=5,
    )
    rig_influence_limit: IntProperty(
        name="Maximum Influences",
        default=4,
        min=1,
        max=8,
    )
    rig_force_binding_failure: BoolProperty(
        default=False,
        options={"HIDDEN"},
    )
    rig_weight_status: EnumProperty(
        name="Weight Status",
        items=(
            ("NOT_RUN", "Not Run", "Production binding has not run"),
            (
                "READY_FOR_ANIMATION_TEST",
                "Ready for Animation Test",
                "Weights and bind-space checks passed",
            ),
            ("NEEDS_REBIND", "Needs Rebind", "Binding matrices or rig changed"),
            ("NEEDS_WEIGHT_REVIEW", "Needs Weight Review", "Review weight warnings"),
            ("FAILED", "Failed", "Production weights failed"),
        ),
        default="NOT_RUN",
    )
    rig_weight_report_json: StringProperty(default="", options={"HIDDEN"})
    rig_unweighted_count: IntProperty(name="Unweighted", default=0)
    rig_maximum_influences: IntProperty(name="Maximum Influences", default=0)
    rig_donor_confidence: FloatProperty(
        name="Donor Confidence",
        default=0.0,
        subtype="FACTOR",
    )
    rig_proxy_fallback_count: IntProperty(name="Proxy Fallback", default=0)
    rig_pose_test_status: StringProperty(
        name="Pose Tests",
        default="NOT_RUN",
    )
    rig_pose_test_json: StringProperty(default="", options={"HIDDEN"})
    rig_action_test_status: StringProperty(
        name="Canonical Actions",
        default="NOT_RUN",
    )
    rig_action_test_json: StringProperty(default="", options={"HIDDEN"})
    rigged_export_glb_path: StringProperty(
        name="Rigged GLB",
        subtype="FILE_PATH",
        default=rf"{EXPORT_RIGGED_GLB_DIR}\character_sbf_rigged.glb",
    )
    rig_export_actions: BoolProperty(
        name="Export Filtered Actions",
        default=True,
    )
    rig_export_status: StringProperty(name="Rigged Export", default="NOT_RUN")
    rig_reimport_status: StringProperty(name="Clean Reimport", default="NOT_RUN")
    rig_reimport_json: StringProperty(default="", options={"HIDDEN"})
    animation_forge_repository: StringProperty(
        name="Animation Forge Repository",
        subtype="DIR_PATH",
        default="E:\\DeVForge\\dreadstone_animation_forge",
    )
    rig_animation_forge_status: StringProperty(
        name="Animation Forge",
        default="NOT_RUN",
    )
    rig_animation_forge_json: StringProperty(default="", options={"HIDDEN"})
    rig_recommended_action: StringProperty(
        name="Next Action",
        default="Analyze the canonical rig.",
    )


PROPERTY_CLASSES = (SBFViewSettings, SBFSettings)


def register():
    for cls in PROPERTY_CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.sbf_settings = PointerProperty(type=SBFSettings)


def unregister():
    if hasattr(bpy.types.Scene, "sbf_settings"):
        del bpy.types.Scene.sbf_settings
    for cls in reversed(PROPERTY_CLASSES):
        bpy.utils.unregister_class(cls)
