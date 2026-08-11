"""Persistent appearance-variant families."""

from .model import (
    FAMILY_SCHEMA,
    HANDOFF_SCHEMA,
    TECHNICAL_BODY_SCHEMA,
    appearance_handoff_record,
    approval_is_current,
    bake_uv_adoption_allowed,
    stable_fingerprint,
    variant_export_name,
    variant_image_name,
)

__all__ = (
    "FAMILY_SCHEMA",
    "HANDOFF_SCHEMA",
    "TECHNICAL_BODY_SCHEMA",
    "appearance_handoff_record",
    "approval_is_current",
    "bake_uv_adoption_allowed",
    "stable_fingerprint",
    "variant_export_name",
    "variant_image_name",
)
