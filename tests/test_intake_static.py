"""Static contracts for the SPAR3D intake vertical slice."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "addon" / "skin_and_bones_forge"
INTAKE = PACKAGE / "intake"


class IntakeStaticTests(unittest.TestCase):
    def test_intake_package_is_complete_and_compiles(self):
        required = {"__init__.py", "analysis.py", "weld.py", "core.py"}
        self.assertEqual(required, {path.name for path in INTAKE.glob("*.py")})
        for path in INTAKE.glob("*.py"):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_primary_operators_and_first_panel_exist(self):
        operators = (PACKAGE / "operators" / "intake.py").read_text(encoding="utf-8")
        panel = (PACKAGE / "panels" / "main_panel.py").read_text(encoding="utf-8")
        for identifier in (
            "sbf.import_and_prepare_spar3d",
            "sbf.prepare_selected_spar3d",
            "sbf.analyze_spar3d",
            "sbf.preview_exact_weld",
            "sbf.write_intake_report",
            "sbf.compare_raw_clean",
            "sbf.restore_raw_spar3d",
            "sbf.remove_raw_spar3d",
        ):
            self.assertIn(identifier, operators)
        self.assertIn('bl_label = "0. SPAR3D Intake & Mesh Prep"', panel)
        classes = ast.parse(panel)
        tuple_assignment = next(
            node
            for node in classes.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "PANEL_CLASSES" for target in node.targets)
        )
        values = [item.id for item in tuple_assignment.value.elts]
        self.assertLess(values.index("SBF_PT_spar3d_intake"), values.index("SBF_PT_target"))

    def test_weld_is_exact_and_does_not_use_approximate_mesh_operations(self):
        source = (INTAKE / "weld.py").read_text(encoding="utf-8")
        self.assertIn("canonical_by_position", source)
        self.assertIn("source_to_canonical", source)
        self.assertIn('"approximate_merge_performed": False', source)
        for prohibited in (
            "remove_doubles",
            "merge_by_distance",
            "voxel_remesh",
            "quadriflow_remesh",
            "decimate",
            "limited_dissolve",
            "holes_fill",
        ):
            self.assertNotIn(prohibited, source)

    def test_corner_and_material_proof_is_mandatory(self):
        source = (INTAKE / "weld.py").read_text(encoding="utf-8")
        for proof in (
            "material_assignments_preserved",
            "uv_values_preserved",
            "uv_seam_discontinuities_preserved",
            "corner_normals_preserved",
            "surface_area_world_preserved",
            "signed_volume_world_preserved",
            "world_bounds_preserved",
        ):
            self.assertIn(proof, source)

    def test_transaction_and_ownership_contracts_exist(self):
        source = (INTAKE / "core.py").read_text(encoding="utf-8")
        for contract in (
            "_inventory",
            "_rollback_new_data",
            "SceneState",
            "SBF_SOURCE_RAW_PROTECTED",
            "SBF_CLEAN_CHARACTER",
            "sbf_raw_geometry_fingerprint",
            "READY_FOR_SKIN",
            "NEEDS_GEOMETRY_REVIEW",
            "ORIENTATION_REVIEW_REQUIRED",
        ):
            self.assertIn(contract, source)


if __name__ == "__main__":
    unittest.main()
