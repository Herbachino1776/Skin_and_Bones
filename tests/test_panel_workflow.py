"""Static contracts for the workflow-first sidebar organization."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = ROOT / "addon" / "skin_and_bones_forge" / "panels" / "main_panel.py"


def _assignment(class_node, name):
    for node in class_node.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    return None


def _calls(class_node, method):
    values = set()
    for node in ast.walk(class_node):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == method
            and node.args
        ):
            argument = node.args[0] if method == "operator" else node.args[1]
            if isinstance(argument, ast.Constant):
                values.add(argument.value)
    return values


class PanelWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PANEL_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.classes = {
            node.name: node
            for node in cls.tree.body
            if isinstance(node, ast.ClassDef) and node.name.startswith("SBF_PT_")
        }

    def test_primary_stages_have_explicit_workflow_order(self):
        expected = (
            ("SBF_PT_spar3d_intake", "0. Character Setup", 0),
            ("SBF_PT_sources", "SKIN 1. Source Images", 1),
            ("SBF_PT_preview", "SKIN 2. Align & Preview", 2),
            ("SBF_PT_output", "SKIN 3. Bake Texture", 3),
            ("SBF_PT_texture_repair", "SKIN 4. Texture Repair Studio", 4),
            ("SBF_PT_delivery", "SKIN 5. Base Asset Delivery", 5),
            ("SBF_PT_bones", "BONES 1. Build & Fit Skeleton", 6),
            ("SBF_PT_bone_binding", "BONES 2. Bind & Validate Weights", 7),
            ("SBF_PT_bone_tests", "BONES 3. Test & Finalize Rig", 8),
            ("SBF_PT_bone_delivery", "BONES 4. Export & Compatibility", 9),
        )
        for name, label, order in expected:
            panel = self.classes[name]
            self.assertEqual(label, _assignment(panel, "bl_label"))
            self.assertEqual(order, _assignment(panel, "bl_order"))
            if order:
                self.assertEqual({"DEFAULT_CLOSED"}, _assignment(panel, "bl_options"))

    def test_advanced_controls_are_nested_with_their_stage(self):
        expected_parents = {
            "SBF_PT_target": "SBF_PT_spar3d_intake",
            "SBF_PT_spar3d_intake_advanced": "SBF_PT_spar3d_intake",
            "SBF_PT_source_doctor": "SBF_PT_preview",
            "SBF_PT_source_doctor_advanced": "SBF_PT_preview",
            "SBF_PT_head_protection": "SBF_PT_preview",
            "SBF_PT_blending": "SBF_PT_preview",
            "SBF_PT_occlusion": "SBF_PT_preview",
            "SBF_PT_bake_advanced": "SBF_PT_output",
            "SBF_PT_texture_repair_advanced": "SBF_PT_texture_repair",
            "SBF_PT_bone_binding_advanced": "SBF_PT_bone_binding",
        }
        for name, parent in expected_parents.items():
            panel = self.classes[name]
            self.assertEqual(parent, _assignment(panel, "bl_parent_id"))
            self.assertEqual({"DEFAULT_CLOSED"}, _assignment(panel, "bl_options"))

    def test_recommended_actions_are_in_their_proper_stage(self):
        self.assertNotIn("sbf.best_preview", _calls(self.classes["SBF_PT_main"], "operator"))
        self.assertIn("sbf.best_preview", _calls(self.classes["SBF_PT_preview"], "operator"))
        self.assertIn("sbf.bake_final", _calls(self.classes["SBF_PT_output"], "operator"))
        self.assertIn("sbf.bind_production_character", _calls(self.classes["SBF_PT_bone_binding"], "operator"))
        self.assertIn("sbf.finalize_production_rig", _calls(self.classes["SBF_PT_bone_tests"], "operator"))
        self.assertIn("sbf.export_rigged_glb", _calls(self.classes["SBF_PT_bone_delivery"], "operator"))

    def test_customization_controls_remain_available(self):
        all_operators = _calls(self.tree, "operator")
        all_properties = _calls(self.tree, "prop")
        required_operators = {
            "sbf.preview_exact_weld",
            "sbf.calibrate_face_landmarks",
            "sbf.place_body_landmarks",
            "sbf.show_source_doctor_image",
            "sbf.texture_smart_fill",
            "sbf.texture_heal_seams",
            "sbf.run_pose_torture_tests",
            "sbf.test_canonical_actions",
            "sbf.run_animation_forge_acceptance",
        }
        required_properties = {
            "forward_axis",
            "up_axis",
            "head_blend_sharpness",
            "directional_exponent",
            "visibility_method",
            "trusted_mask_erosion",
            "generate_bake_uv",
            "repair_source_rotation",
            "repair_min_donor_confidence",
            "repair_seam_detection_threshold",
            "rig_weight_threshold",
            "rig_influence_limit",
            "rig_export_actions",
        }
        self.assertTrue(required_operators <= all_operators)
        self.assertTrue(required_properties <= all_properties)


if __name__ == "__main__":
    unittest.main()
