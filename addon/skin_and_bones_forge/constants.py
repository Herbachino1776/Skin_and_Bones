"""Shared constants for Skin & Bones Forge."""

ADDON_NAME = "Skin & Bones Forge"
ADDON_MODULE = "skin_and_bones_forge"
ADDON_VERSION = (0, 2, 1)
ADDON_VERSION_STRING = ".".join(str(part) for part in ADDON_VERSION)

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

TEMPORARY_PROPERTY = "sbf_temporary"
ORIGINAL_MATERIAL_PROPERTY = "sbf_original_material"
ORIGINAL_SLOT_PROPERTY = "sbf_original_slot"
ORIGINAL_UV_PROPERTY = "sbf_original_uv"

PROCESSING_PRESET = "SPAR3D Human - Identity Priority / Occlusion Safe"
