"""Shared constants for Skin & Bones Forge."""

ADDON_NAME = "Skin & Bones Forge"
ADDON_MODULE = "skin_and_bones_forge"
ADDON_VERSION = (0, 1, 0)
ADDON_VERSION_STRING = ".".join(str(part) for part in ADDON_VERSION)

VIEW_NAMES = ("front", "back", "left", "right")
VIEW_LABELS = {
    "front": "Front",
    "back": "Back",
    "left": "Character Left",
    "right": "Character Right",
}

TEMP_PREFIX = "SBF_"
TEMP_COLLECTION = "SBF_Temporary"
PROJECTION_CAMERA_PREFIX = "SBF_ProjectionCamera_"
PROJECTION_UV_PREFIX = "SBF_PROJ_"
WEIGHT_ATTRIBUTE_PREFIX = "SBF_WEIGHT_"
PREVIEW_MATERIAL_PREFIX = "SBF_Preview_"
VERIFY_PREFIX = "SBF_Verify_"

TEMPORARY_PROPERTY = "sbf_temporary"
ORIGINAL_MATERIAL_PROPERTY = "sbf_original_material"
ORIGINAL_SLOT_PROPERTY = "sbf_original_slot"
ORIGINAL_UV_PROPERTY = "sbf_original_uv"

PROCESSING_PRESET = "SPAR3D Human - Identity Priority / Occlusion Safe"
