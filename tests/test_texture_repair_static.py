"""Static integration checks for Texture Repair Studio."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "addon" / "skin_and_bones_forge"


class TextureRepairStaticTests(unittest.TestCase):
    def test_owned_layer_contract_is_exact(self):
        constants = (PACKAGE / "constants.py").read_text(encoding="utf-8")
        for name in (
            "SBF_BaseColor_Baked",
            "SBF_Texture_Corrections",
            "SBF_Texture_Correction_Mask",
            "SBF_BaseColor_Final",
        ):
            self.assertIn(name, constants)

    def test_bake_extends_existing_pipeline(self):
        source = (PACKAGE / "baking" / "core.py").read_text(encoding="utf-8")
        self.assertIn("begin_repair_session", source)
        self.assertIn("_bind_production_texture_uvs", source)
        self.assertIn("cleanup_temporary_data", source)
        self.assertNotIn("info.base_color_node.image = baked_image", source)

    def test_delivery_cannot_bypass_final_composite(self):
        source = (PACKAGE / "export" / "core.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls_by_function = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                calls_by_function[node.name] = {
                    child.func.id
                    for child in ast.walk(node)
                    if isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                }
        self.assertIn(
            "validate_repair_for_delivery",
            calls_by_function["save_blend_copy"],
        )
        self.assertIn("validate_repair_for_delivery", calls_by_function["export_glb"])

    def test_ui_and_operators_are_registered(self):
        operators = (PACKAGE / "operators" / "__init__.py").read_text(
            encoding="utf-8"
        )
        panel = (PACKAGE / "panels" / "main_panel.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("TEXTURE_REPAIR_OPERATOR_CLASSES", operators)
        self.assertIn("SKIN 4. Texture Repair Studio", panel)
        self.assertIn("COMMIT FINAL BASE COLOR", panel)
        self.assertIn("Advanced Texture Repair", panel)

    def test_algorithms_do_not_import_blender(self):
        source = (PACKAGE / "baking" / "texture_repair.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertNotIn("bpy", imported)

    def test_repair_preview_uses_dedicated_ownership_state(self):
        service = (PACKAGE / "baking" / "repair_service.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("_restore_production_material(info)", service)
        self.assertIn("REPAIR_PREVIEW_SLOT_PROPERTY", service)
        self.assertNotIn("target[ORIGINAL_MATERIAL_PROPERTY]", service)
        self.assertNotIn("target[ORIGINAL_SLOT_PROPERTY]", service)


if __name__ == "__main__":
    unittest.main()
