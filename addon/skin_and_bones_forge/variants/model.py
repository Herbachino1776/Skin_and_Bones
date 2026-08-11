"""Pure appearance-family identity, naming, and handoff helpers."""

from __future__ import annotations

import hashlib
import json
import re


FAMILY_SCHEMA = "skin-and-bones-appearance-family-v1"
FAMILY_SCHEMA_VERSION = 1
TECHNICAL_BODY_SCHEMA = "skin-and-bones-technical-body-v1"
TECHNICAL_BODY_SCHEMA_VERSION = 1
HANDOFF_SCHEMA = "skin-and-bones-appearance-family-handoff-v1"
HANDOFF_SCHEMA_VERSION = 1


def stable_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def stable_fingerprint(value):
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def safe_identifier(value, fallback="appearance"):
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value).strip())
    cleaned = cleaned.strip("_-").lower()
    return cleaned or fallback


def variant_image_name(family_id, variant_id, base_name):
    """Return a short, stable Blender image name without global collisions."""

    suffix = str(base_name)
    if suffix.startswith("SBF_"):
        suffix = suffix[4:]
    family = hashlib.sha256(str(family_id).encode("utf-8")).hexdigest()[:8]
    variant = hashlib.sha256(str(variant_id).encode("utf-8")).hexdigest()[:8]
    return f"SBF_{family}_{variant}_{suffix}"


def variant_export_name(display_name, fallback="appearance"):
    return safe_identifier(display_name, fallback)


def technical_body_fingerprint(record):
    payload = dict(record)
    payload.pop("fingerprint", None)
    return stable_fingerprint(payload)


def bake_uv_adoption_allowed(previous, current):
    """Allow the first SBF base-color UV to become part of an unapproved family."""

    old = json.loads(stable_json(previous))
    new = json.loads(stable_json(current))
    old.pop("fingerprint", None)
    new.pop("fingerprint", None)
    old_uv = old.get("mesh", {}).pop("base_color_uv", None)
    new_uv = new.get("mesh", {}).pop("base_color_uv", None)
    return old == new and old_uv is None and bool(new_uv)


def approval_is_current(variant):
    return bool(
        variant.get("approval_state") == "APPROVED"
        and not variant.get("dirty", True)
        and int(variant.get("approved_revision", -1))
        == int(variant.get("revision", 0))
        and variant.get("technical_state") == "VALID"
        and variant.get("approval_fingerprint")
    )


def appearance_handoff_record(
    *,
    family_id,
    family_display_name,
    variant_id,
    variant_display_name,
    export_identity,
    technical_body_fingerprint_value,
    appearance_revision,
    approved_revision,
    approval_fingerprint,
    approved_at_utc,
    addon_version,
):
    return {
        "schema": HANDOFF_SCHEMA,
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "family_schema": FAMILY_SCHEMA,
        "family_schema_version": FAMILY_SCHEMA_VERSION,
        "family_id": family_id,
        "family_display_name": family_display_name,
        "variant_id": variant_id,
        "variant_display_name": variant_display_name,
        "export_identity": export_identity,
        "technical_body_schema": TECHNICAL_BODY_SCHEMA,
        "technical_body_schema_version": TECHNICAL_BODY_SCHEMA_VERSION,
        "technical_body_fingerprint": technical_body_fingerprint_value,
        "appearance_revision": int(appearance_revision),
        "approval": {
            "state": "APPROVED",
            "approved_revision": int(approved_revision),
            "appearance_fingerprint": approval_fingerprint,
            "approved_at_utc": approved_at_utc,
            "addon_version": addon_version,
        },
    }
