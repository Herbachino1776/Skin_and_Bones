"""Pure and static regressions for appearance variant families."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = (
    ROOT
    / "addon"
    / "skin_and_bones_forge"
    / "variants"
    / "model.py"
)
SPEC = importlib.util.spec_from_file_location("sbf_variant_model", MODEL_PATH)
MODEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODEL)


class AppearanceVariantModelTests(unittest.TestCase):
    def test_internal_image_names_are_stable_and_variant_distinct(self):
        first = MODEL.variant_image_name(
            "family-123456789", "variant-a-123456", "SBF_BaseColor_Final"
        )
        second = MODEL.variant_image_name(
            "family-123456789", "variant-b-123456", "SBF_BaseColor_Final"
        )
        self.assertEqual(first, MODEL.variant_image_name(
            "family-123456789", "variant-a-123456", "SBF_BaseColor_Final"
        ))
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("SBF_"))

    def test_only_first_base_color_uv_addition_is_adoptable(self):
        previous = {
            "schema": MODEL.TECHNICAL_BODY_SCHEMA,
            "mesh": {"topology": "same", "base_color_uv": None},
            "rig": {"fingerprint": "rig"},
        }
        current = json.loads(json.dumps(previous))
        current["mesh"]["base_color_uv"] = {
            "name": "SBF_BaseColorUV",
            "loop_sha256": "uv",
        }
        self.assertTrue(MODEL.bake_uv_adoption_allowed(previous, current))
        current["rig"]["fingerprint"] = "changed"
        self.assertFalse(MODEL.bake_uv_adoption_allowed(previous, current))

    def test_handoff_is_small_versioned_and_family_linked(self):
        record = MODEL.appearance_handoff_record(
            family_id="family-id",
            family_display_name="Bandit",
            variant_id="variant-id",
            variant_display_name="Sooted",
            export_identity="bandit_sooted",
            technical_body_fingerprint_value="technical-sha",
            appearance_revision=7,
            approved_revision=7,
            approval_fingerprint="appearance-sha",
            approved_at_utc="2026-08-11T00:00:00+00:00",
            addon_version="2.2.0",
        )
        self.assertEqual(record["schema"], MODEL.HANDOFF_SCHEMA)
        self.assertEqual(record["family_id"], "family-id")
        self.assertEqual(record["variant_id"], "variant-id")
        self.assertEqual(record["technical_body_fingerprint"], "technical-sha")
        self.assertEqual(record["approval"]["approved_revision"], 7)
        self.assertLess(len(json.dumps(record)), 1500)

    def test_approval_requires_exact_revision_and_valid_body(self):
        approved = {
            "approval_state": "APPROVED",
            "dirty": False,
            "revision": 4,
            "approved_revision": 4,
            "technical_state": "VALID",
            "approval_fingerprint": "sha",
        }
        self.assertTrue(MODEL.approval_is_current(approved))
        for key, value in (
            ("dirty", True),
            ("approved_revision", 3),
            ("technical_state", "STALE"),
        ):
            changed = dict(approved)
            changed[key] = value
            self.assertFalse(MODEL.approval_is_current(changed))


class AppearanceVariantStaticTests(unittest.TestCase):
    def test_blender_storage_uses_stable_ids_and_no_object_copies(self):
        properties = (
            ROOT / "addon" / "skin_and_bones_forge" / "properties.py"
        ).read_text(encoding="utf-8")
        runtime = (
            ROOT
            / "addon"
            / "skin_and_bones_forge"
            / "variants"
            / "runtime.py"
        ).read_text(encoding="utf-8")
        variant_properties = properties.split(
            "class SBFAppearanceVariant", 1
        )[1].split("class SBFSettings", 1)[0]
        self.assertIn("variant_id: StringProperty", properties)
        self.assertIn("appearance_variants: CollectionProperty", properties)
        self.assertNotIn("mesh: PointerProperty", variant_properties)
        self.assertNotIn("armature: PointerProperty", variant_properties)
        self.assertIn("technical_body_record", runtime)
        self.assertIn("_weight_record", runtime)

    def test_export_contains_versioned_handoff_extras(self):
        production = (
            ROOT
            / "addon"
            / "skin_and_bones_forge"
            / "rigging"
            / "production.py"
        ).read_text(encoding="utf-8")
        operators = (
            ROOT
            / "addon"
            / "skin_and_bones_forge"
            / "operators"
            / "variants.py"
        ).read_text(encoding="utf-8")
        self.assertIn("sbf_appearance_family_handoff", production)
        self.assertIn("appearance_handoff=handoff_for_variant", operators)
        self.assertIn("sbf.export_approved_appearances", operators)


if __name__ == "__main__":
    unittest.main()
