"""Static contract checks for the Bones vertical slice."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "addon" / "skin_and_bones_forge"
RIGGING = PACKAGE / "rigging"


class RiggingStaticTests(unittest.TestCase):
    def test_modular_rigging_package_is_complete(self):
        required = {
            "__init__.py",
            "contract.py",
            "deformation.py",
            "analysis.py",
            "landmarks.py",
            "fitting.py",
            "validation.py",
            "profile.py",
            "hands.py",
            "weights.py",
            "poses.py",
            "production.py",
            "compatibility.py",
            "acceptance_runner.py",
            "reimport_runner.py",
        }
        self.assertEqual(required, {path.name for path in RIGGING.glob("*.py")})
        for path in RIGGING.glob("*.py"):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_fingerprint_excludes_animation_inventory(self):
        tree = ast.parse(
            (RIGGING / "contract.py").read_text(encoding="utf-8")
        )
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "fingerprint_payload"
        )
        source = ast.unparse(function)
        self.assertIn("bones", source)
        self.assertNotIn("animation_inventory", source)
        self.assertNotIn("filepath", source)

    def test_required_rigging_operators_exist(self):
        source = (
            PACKAGE / "operators" / "rigging.py"
        ).read_text(encoding="utf-8")
        for identifier in (
            "sbf.analyze_canonical_rig",
            "sbf.write_rig_report",
            "sbf.analyze_target_humanoid",
            "sbf.generate_rig_landmarks",
            "sbf.fit_skeleton_preview",
            "sbf.refit_from_corrections",
            "sbf.reset_rig_landmarks",
            "sbf.validate_fitted_skeleton",
            "sbf.clean_rig_preview",
            "sbf.apply_hand_pose",
            "sbf.bind_production_character",
            "sbf.validate_production_weights",
            "sbf.run_pose_torture_tests",
            "sbf.test_canonical_actions",
            "sbf.finalize_production_rig",
            "sbf.export_rigged_glb",
            "sbf.validate_clean_reimport",
            "sbf.run_animation_forge_acceptance",
            "sbf.clean_temporary_rigging_data",
        ):
            self.assertIn(identifier, source)

    def test_binding_is_donor_first_and_transactional(self):
        source = (RIGGING / "weights.py").read_text(encoding="utf-8")
        self.assertIn("NEAREST_DONOR_FACE_BARYCENTRIC", source)
        self.assertIn("create_aligned_donor", source)
        self.assertIn("classify_components", source)
        self.assertIn("clean_weighting_temporary_data", source)
        self.assertIn("except Exception:", source)
        self.assertIn("_restore_vertex_groups", source)
        self.assertNotIn("parent_set", source)

    def test_animation_forge_uses_actual_analyzer_operator(self):
        source = (RIGGING / "acceptance_runner.py").read_text(encoding="utf-8")
        self.assertIn("bpy.ops.daf.analyze()", source)
        self.assertIn("module.map_bones", source)
        self.assertIn("module.detect_animate_anything_profile", source)

    def test_animation_forge_generates_and_scans_real_drafts(self):
        source = (RIGGING / "acceptance_runner.py").read_text(encoding="utf-8")
        self.assertIn("bpy.ops.daf.walk()", source)
        self.assertIn("bpy.ops.daf.hurt_left()", source)
        self.assertIn("scan_action_deformation", source)

    def test_weight_repair_uses_fitted_bone_distance_not_hard_bins(self):
        source = (RIGGING / "weights.py").read_text(encoding="utf-8")
        self.assertIn("_spatially_plausible", source)
        self.assertIn("low_confidence_spatially_preserved", source)
        tree = ast.parse(source)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "clean_weights"
        )
        clean_source = ast.unparse(function)
        self.assertNotIn("_region_allowed", clean_source)

    def test_deformation_gate_uses_edges_and_palette_continuity(self):
        deformation = (RIGGING / "deformation.py").read_text(encoding="utf-8")
        weights = (RIGGING / "weights.py").read_text(encoding="utf-8")
        self.assertIn("maximum_edge_stretch_ratio", deformation)
        self.assertIn("blocking_separated_components", deformation)
        self.assertIn("palette_reconciliation_iterations", weights)
        self.assertIn("maximum_edge_weight_delta_after", weights)

    def test_export_defaults_use_the_e_drive_delivery_tree(self):
        constants = (PACKAGE / "constants.py").read_text(encoding="utf-8")
        properties = (PACKAGE / "properties.py").read_text(encoding="utf-8")
        self.assertIn(r'EXPORT_ROOT = r"E:\Skin_And_Bones_Exports"', constants)
        for directory in (
            "Textures",
            "Blender",
            "GLB",
            "Rigged_GLB",
            "Proof_Renders",
            "Reports",
        ):
            self.assertIn(directory, constants)
        self.assertNotIn("C:\\\\", constants + properties)

    def test_simplified_hand_profile_is_hierarchy_derived(self):
        profile = (RIGGING / "profile.py").read_text(encoding="utf-8")
        fitting = (RIGGING / "fitting.py").read_text(encoding="utf-8")
        weights = (RIGGING / "weights.py").read_text(encoding="utf-8")
        poses = (RIGGING / "poses.py").read_text(encoding="utf-8")
        hands = (RIGGING / "hands.py").read_text(encoding="utf-8")
        landmarks = (RIGGING / "landmarks.py").read_text(encoding="utf-8")
        self.assertIn("DSB_SIMPLE_HANDS_V1", profile)
        self.assertIn("identify_finger_descendants", profile)
        self.assertIn("_descendants", profile)
        self.assertIn("removed_to_hand", weights)
        self.assertIn("donor_hand_weight_merge", weights)
        self.assertIn("removed_finger_channels", poses)
        self.assertIn("sbf_production_action", poses)
        self.assertIn('contract.get("removed_bones"', fitting)
        for pose in ("RELAXED", "OPEN_MAGIC", "GRIP_SHAFT"):
            self.assertIn(pose, hands)
        for shape_key in ("DSB_HAND_OPEN_MAGIC", "DSB_HAND_GRIP_SHAFT"):
            self.assertIn(shape_key, hands)
        for finger in ("index", "middle", "ring", "little", "thumb"):
            self.assertNotIn(f'"{finger}_left"', landmarks)
            self.assertNotIn(f'"{finger}_right"', landmarks)


if __name__ == "__main__":
    unittest.main()
