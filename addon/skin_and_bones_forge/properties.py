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
)


AXIS_ITEMS = (
    ("+X", "+X", "Positive X"),
    ("-X", "-X", "Negative X"),
    ("+Y", "+Y", "Positive Y"),
    ("-Y", "-Y", "Negative Y"),
    ("+Z", "+Z", "Positive Z"),
    ("-Z", "-Z", "Negative Z"),
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
        default="CANONICAL_TRANSFER_WITH_PROXY_FALLBACK",
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
