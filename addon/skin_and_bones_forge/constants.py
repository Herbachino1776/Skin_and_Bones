"""Shared constants for Skin & Bones Forge."""

ADDON_NAME = "Skin & Bones Forge"
ADDON_MODULE = "skin_and_bones_forge"
ADDON_VERSION = (1, 2, 0)
ADDON_VERSION_STRING = ".".join(str(part) for part in ADDON_VERSION)

EXPORT_ROOT = r"E:\Skin_And_Bones_Exports"
EXPORT_TEXTURE_DIR = rf"{EXPORT_ROOT}\Textures"
EXPORT_BLEND_DIR = rf"{EXPORT_ROOT}\Blender"
EXPORT_GLB_DIR = rf"{EXPORT_ROOT}\GLB"
EXPORT_RIGGED_GLB_DIR = rf"{EXPORT_ROOT}\Rigged_GLB"
EXPORT_PROOF_DIR = rf"{EXPORT_ROOT}\Proof_Renders"
EXPORT_REPORT_DIR = rf"{EXPORT_ROOT}\Reports"
DEFAULT_PROJECTION_PACKS_DIR = r"D:\AI aRt\Skin and Bones Projection packs"

CARDINAL_VIEW_NAMES = ("front", "back", "left", "right")
DIAGONAL_VIEW_NAMES = ("front_left", "front_right")
VIEW_NAMES = (
    "front",
    "front_left",
    "front_right",
    "left",
    "right",
    "back",
)
VIEW_LABELS = {
    "front": "Front",
    "back": "Back",
    "left": "Character Left",
    "right": "Character Right",
    "front_left": "Front 45 deg - Character Left",
    "front_right": "Front 45 deg - Character Right",
}
FACIAL_LANDMARK_NAMES = (
    "eye_image_left",
    "eye_image_right",
    "mouth_image_left",
    "mouth_image_right",
)
FACIAL_LANDMARK_LABELS = (
    "Image-left eye center",
    "Image-right eye center",
    "Image-left mouth corner",
    "Image-right mouth corner",
)

TEMP_PREFIX = "SBF_"
TEMP_COLLECTION = "SBF_Temporary"
PROJECTION_CAMERA_PREFIX = "SBF_ProjectionCamera_"
PROJECTION_UV_PREFIX = "SBF_PROJ_"
BASE_COLOR_UV_NAME = "SBF_BaseColorUV"
WEIGHT_ATTRIBUTE_PREFIX = "SBF_WEIGHT_"
PREVIEW_MATERIAL_PREFIX = "SBF_Preview_"
VERIFY_PREFIX = "SBF_Verify_"
SOURCE_CLEAN_PREFIX = "SBF_CLEAN_SOURCE_"
SOURCE_WARP_PREFIX = "SBF_WARP_SOURCE_"
SOURCE_DIAGNOSTIC_PREFIX = "SBF_EDGE_CONTAMINATION_"
SOURCE_CONFIDENCE_PREFIX = "SBF_SOURCE_CONFIDENCE_"
SOURCE_OWNER_PROPERTY = "sbf_source_doctor_owned"
SOURCE_STATE_PROPERTY = "sbf_processed_source_state"
BODY_PART_ATTRIBUTE_PREFIX = f"{WEIGHT_ATTRIBUTE_PREFIX}part_"

REPAIR_BAKED_IMAGE = "SBF_BaseColor_Baked"
REPAIR_CORRECTION_IMAGE = "SBF_Texture_Corrections"
REPAIR_MASK_IMAGE = "SBF_Texture_Correction_Mask"
REPAIR_FINAL_IMAGE = "SBF_BaseColor_Final"
REPAIR_CLASSIFICATION_IMAGE = "SBF_Texture_Classification"
REPAIR_TARGET_MASK_IMAGE = "SBF_Texture_Repair_TargetMask"
REPAIR_DONOR_MASK_IMAGE = "SBF_Texture_Repair_DonorMask"
REPAIR_FORBIDDEN_MASK_IMAGE = "SBF_Texture_ForbiddenSourceMask"
REPAIR_DIAGNOSTIC_IMAGE = "SBF_Texture_Repair_Diagnostic"
REPAIR_OWNER_PROPERTY = "sbf_texture_repair_owned"
REPAIR_FINGERPRINT_PROPERTY = "sbf_texture_repair_fingerprint"
REPAIR_ROLE_PROPERTY = "sbf_texture_repair_role"
REPAIR_PREVIEW_PREFIX = "SBF_Preview_TextureRepair_"

TEMPORARY_PROPERTY = "sbf_temporary"
ORIGINAL_MATERIAL_PROPERTY = "sbf_original_material"
ORIGINAL_SLOT_PROPERTY = "sbf_original_slot"
ORIGINAL_UV_PROPERTY = "sbf_original_uv"

PROCESSING_PRESET = "SPAR3D Human - Identity Priority / Occlusion Safe"

RIG_PREVIEW_COLLECTION = "SBF_RigPreview"
RIG_PREVIEW_ARMATURE = "SBF_FittedSkeletonPreview"
RIG_LANDMARK_PREFIX = "SBF_Landmark_"
RIG_OWNER_PROPERTY = "sbf_rig_owner"
RIG_TARGET_PROPERTY = "sbf_rig_target"
RIG_CONTRACT_PROPERTY = "sbf_canonical_fingerprint"
RIG_ANALYSIS_PROPERTY = "sbf_rig_analysis"
RIG_CORRECTIONS_PROPERTY = "sbf_landmark_corrections"
RIG_TOPOLOGY_PROPERTY = "sbf_rig_topology_snapshot"
RIG_PRODUCTION_ARMATURE = "SBF_ProductionRig"
RIG_TEMP_COLLECTION = "SBF_RiggingTemporary"
RIG_DONOR_OBJECT = "SBF_CanonicalWeightDonor"
RIG_PROXY_OBJECT = "SBF_WeightFallbackProxy"
RIG_ARMATURE_MODIFIER = "SBF_ProductionArmature"
RIG_WEIGHT_REPORT_PROPERTY = "sbf_weight_report"
RIG_PRODUCTION_PROPERTY = "sbf_production_rig"
