"""Static contract checks for the Bones vertical slice."""

from __future__ import annotations

import ast
from collections import defaultdict
import math
import re
from types import SimpleNamespace
import unittest
from pathlib import Path

try:
    import numpy as np
except ModuleNotFoundError:
    np = None


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "addon" / "skin_and_bones_forge"
RIGGING = PACKAGE / "rigging"


class RiggingStaticTests(unittest.TestCase):
    @unittest.skipUnless(np is not None, "Blender NumPy runtime required")
    def test_dense_weight_regularization_matches_reference_rules(self):
        source = (RIGGING / "weights.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name
            in {
                "_limit_and_normalize_rows",
                "_accumulate_edge_values",
                "_regularize_dense_weights",
            }
        ]
        namespace = {"np": np}
        exec(
            compile(
                ast.Module(body=functions, type_ignores=[]),
                str(RIGGING / "weights.py"),
                "exec",
            ),
            namespace,
        )

        values = np.asarray(
            [
                (0.70, 0.30, 0.00, 0.00),
                (0.60, 0.25, 0.15, 0.00),
                (0.10, 0.50, 0.40, 0.00),
                (0.00, 0.20, 0.55, 0.25),
                (0.00, 0.00, 0.65, 0.35),
                (0.25, 0.25, 0.25, 0.25),
            ],
            dtype=np.float64,
        )
        edges = np.asarray(
            ((0, 1), (1, 2), (2, 3), (3, 4), (1, 5), (3, 5)),
            dtype=np.int64,
        )
        palette_edges = edges[[0, 1, 2, 4, 5]]
        smoothing_allowed = np.ones(values.shape, dtype=bool)
        smoothing_allowed[2, 0] = False
        smoothing_allowed[3, 0] = False
        palette_allowed = np.ones(values.shape, dtype=bool)
        palette_allowed[3:, 0] = False
        tiny_vertices = np.asarray((False, False, False, False, True, False))

        def limit_rows(rows, limit):
            result = np.zeros_like(rows)
            for index, row in enumerate(rows):
                ranked = sorted(
                    enumerate(row), key=lambda item: (-item[1], item[0])
                )[:limit]
                total = sum(value for _column, value in ranked)
                if total > 0.0:
                    for column, value in ranked:
                        result[index, column] = value / total
            return result

        reference = values.copy()
        adjacency = [[] for _row in reference]
        for first, second in edges:
            adjacency[int(first)].append(int(second))
            adjacency[int(second)].append(int(first))
        for _iteration in range(3):
            updated = reference.copy()
            for index, neighbors in enumerate(adjacency):
                if not neighbors or tiny_vertices[index]:
                    continue
                combined = reference[index] * 0.35
                combined += sum(reference[item] for item in neighbors) * (
                    0.65 / len(neighbors)
                )
                combined[~smoothing_allowed[index]] = 0.0
                combined[combined < 1.0e-4] = 0.0
                total = float(np.sum(combined))
                if total > 0.0:
                    updated[index] = combined / total
            reference = updated
        reference = limit_rows(reference, 3)
        palette_executed = 0
        for _iteration in range(5):
            proposals = [[] for _row in reference]
            for first, second in palette_edges:
                first = int(first)
                second = int(second)
                if np.sum(np.abs(reference[first] - reference[second])) <= 0.08:
                    continue
                common = limit_rows(
                    ((reference[first] + reference[second]) * 0.5)[None, :],
                    3,
                )[0]
                proposals[first].append(common)
                proposals[second].append(common)
            if not any(proposals):
                break
            reconciled = reference.copy()
            for index, items in enumerate(proposals):
                if not items:
                    continue
                combined = reference[index] * 0.25
                factor = 0.75 / len(items)
                for item in items:
                    combined += np.where(
                        palette_allowed[index], item * factor, 0.0
                    )
                reconciled[index] = limit_rows(combined[None, :], 3)[0]
            reference = reconciled
            palette_executed += 1

        actual, smoothing_executed, actual_palette_executed = namespace[
            "_regularize_dense_weights"
        ](
            values,
            edges,
            palette_edges,
            smoothing_allowed,
            palette_allowed,
            tiny_vertices,
            3,
            3,
            0.65,
            1.0e-4,
            5,
            0.08,
        )

        np.testing.assert_allclose(actual, reference, atol=1.0e-12, rtol=0.0)
        self.assertEqual(3, smoothing_executed)
        self.assertEqual(palette_executed, actual_palette_executed)

    def test_modular_rigging_package_is_complete(self):
        required = {
            "__init__.py",
            "contract.py",
            "canonical.py",
            "deformation.py",
            "glb_skin.py",
            "analysis.py",
            "landmark_math.py",
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
            "sbf.load_canonical_rig",
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
            "sbf.convert_legacy_yminus",
            "sbf.clean_temporary_rigging_data",
        ):
            self.assertIn(identifier, source)

    def test_canonical_action_inventory_is_scoped_to_the_armature(self):
        tree = ast.parse(
            (RIGGING / "contract.py").read_text(encoding="utf-8")
        )
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_action_inventory"
        )
        source = ast.unparse(function)
        self.assertIn("animation.nla_tracks", source)
        self.assertNotIn("bpy.data.actions", source)

    def test_binding_is_proxy_heat_first_and_transactional(self):
        source = (RIGGING / "weights.py").read_text(encoding="utf-8")
        self.assertIn("NEAREST_DONOR_FACE_BARYCENTRIC", source)
        self.assertIn("create_aligned_donor", source)
        self.assertIn("create_voxel_heat_proxy", source)
        self.assertIn("BLENDER_AUTOMATIC_WEIGHTS_ON_VOXEL_PROXY", source)
        self.assertIn("smooth_surface_weights", source)
        self.assertIn("attenuate_remote_limb_weights", source)
        self.assertIn("classify_components", source)
        self.assertIn("clean_weighting_temporary_data", source)
        self.assertIn("except Exception:", source)
        self.assertIn("_restore_vertex_groups", source)
        tree = ast.parse(source)
        binder = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "bind_production_character"
        )
        self.assertNotIn("parent_set", ast.unparse(binder))

    def test_universal_auto_skin_is_the_one_click_default(self):
        properties = (PACKAGE / "properties.py").read_text(encoding="utf-8")
        operators = (PACKAGE / "operators" / "rigging.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('default="VOXEL_HEAT_PROXY"', properties)
        self.assertIn('mode="VOXEL_HEAT_PROXY"', operators)
        weights = (RIGGING / "weights.py").read_text(encoding="utf-8")
        self.assertIn("VOXEL_HEAT_NOISE_THRESHOLD = 0.002", weights)
        self.assertIn("max(float(threshold), VOXEL_HEAT_NOISE_THRESHOLD)", weights)
        self.assertIn("remove_spatially_impossible_weights", weights)
        self.assertIn("_regularize_weight_continuity", weights)
        self.assertIn("smoothing_iterations=0", weights)
        self.assertIn("palette_iterations=128", weights)
        self.assertIn("palette_edge_limit=0.015", weights)
        self.assertIn("strict_plausible or bridge_plausible", weights)

    def test_voxel_heat_repairs_only_small_fully_unweighted_components(self):
        source = (RIGGING / "weights.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in {
                "_component_indices",
                "_repairable_unweighted_components",
            }
        ]
        namespace = {"defaultdict": defaultdict}
        exec(
            compile(
                ast.Module(body=functions, type_ignores=[]),
                str(RIGGING / "weights.py"),
                "exec",
            ),
            namespace,
        )
        mesh = SimpleNamespace(
            vertices=[None] * 10,
            edges=[
                SimpleNamespace(vertices=edge)
                for edge in (
                    (0, 1),
                    (2, 3),
                    (3, 4),
                    (4, 5),
                    (6, 7),
                    (7, 8),
                    (8, 9),
                )
            ],
        )
        weights = [
            {},
            {},
            {"body": 1.0},
            {},
            {"body": 1.0},
            {},
            {},
            {},
            {},
            {},
        ]

        repairable = namespace["_repairable_unweighted_components"](
            mesh,
            weights,
            max_vertices=2,
        )

        self.assertEqual([[0, 1]], repairable)

    def test_hand_fit_uses_forearm_corridor_and_editable_landmarks(self):
        landmarks = (RIGGING / "landmarks.py").read_text(encoding="utf-8")
        operators = (PACKAGE / "operators" / "rigging.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def _hand_endpoint", landmarks)
        self.assertIn("palm center validated by side-confined", landmarks)
        self.assertIn('"hand_left",\n    "hand_right",\n    "hip_left"', landmarks)
        self.assertIn("_rest_surface_points(obj)", landmarks)
        self.assertIn("refresh_hand_landmarks", operators)
        self.assertIn("_invalidate_binding_results(settings, target)", operators)

    def test_landmark_profile_targets_standard_high_a_pose(self):
        source = (RIGGING / "landmarks.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        assignments = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id
            in {"HIGH_A_HEIGHT_FRACTIONS", "HIGH_A_HAND_OFFSET"}
        }
        self.assertEqual(assignments["HIGH_A_HEIGHT_FRACTIONS"]["wrist"], 0.608)
        self.assertEqual(assignments["HIGH_A_HEIGHT_FRACTIONS"]["elbow"], 0.690)
        self.assertLess(assignments["HIGH_A_HAND_OFFSET"]["up"], 0.0)
        self.assertIn("isolated outer-arm center", source)

    def test_fitted_validation_allows_only_owned_post_bind_state(self):
        source = (RIGGING / "validation.py").read_text(encoding="utf-8")
        self.assertIn("def _expected_binding_state_change", source)
        self.assertIn('target.get("sbf_bound", False)', source)
        self.assertIn("RIG_ARMATURE_MODIFIER", source)
        self.assertIn("and not expected_binding_change", source)

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

    def test_animation_forge_accepts_rest_only_canonical_delivery(self):
        source = (RIGGING / "acceptance_runner.py").read_text(encoding="utf-8")
        self.assertIn("filtered_actions_accepted = not unresolved_action_bones", source)
        self.assertIn('"source_actions_optional": True', source)
        self.assertNotIn(
            "filtered_actions_accepted = bool(action_inventory)", source
        )

    def test_canonical_actions_deduplicate_blender_numeric_suffixes(self):
        source = (RIGGING / "poses.py").read_text(encoding="utf-8")
        self.assertIn("def canonical_source_actions", source)
        self.assertIn(r'(?:\.\d{3})+$', source)
        self.assertIn("actions, missing_actions = canonical_source_actions", source)
        self.assertIn("def canonical_expected_action_names", source)
        production = (RIGGING / "production.py").read_text(encoding="utf-8")
        self.assertIn(
            "expected_action_names = canonical_expected_action_names(contract)",
            production,
        )
        self.assertIn(
            "imported_action_names == expected_action_names",
            production,
        )
        tree = ast.parse(source)
        functions = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in {
                "_semantic_action_name",
                "canonical_expected_action_names",
                "production_action_semantic_name",
            }
        ]
        namespace = {
            "re": re,
            "PRODUCTION_TRACK_PREFIX": "SBF_ProductionTrack_",
            "PRODUCTION_ACTION_PREFIX": "SBF_Production_",
        }
        exec(
            compile(ast.Module(body=functions, type_ignores=[]), str(RIGGING / "poses.py"), "exec"),
            namespace,
        )
        contract = {
            "animation_inventory": {
                "actions": [
                    {"name": "Walk"},
                    {"name": "Walk.001"},
                    {"name": "Death"},
                    {"name": "Attack_A"},
                    {"name": "Attack_B"},
                    {"name": "Cast"},
                    {"name": "Idle"},
                    {"name": "Hurt"},
                ]
            }
        }
        self.assertEqual(
            ["Attack_A", "Attack_B", "Cast", "Death", "Hurt", "Idle", "Walk"],
            namespace["canonical_expected_action_names"](contract),
        )
        self.assertEqual(
            "Attack_A",
            namespace["production_action_semantic_name"](
                "SBF_ProductionTrack_Attack_A.001"
            ),
        )

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

    def test_root_is_retained_but_cannot_anchor_surface_weights(self):
        source = (RIGGING / "weights.py").read_text(encoding="utf-8")
        self.assertIn('NON_SURFACE_DEFORM_BONES = frozenset({"root"})', source)
        self.assertIn("def remove_root_surface_weights", source)
        self.assertIn('"prohibited_surface_weight_vertices"', source)
        self.assertIn("deform_names - NON_SURFACE_DEFORM_BONES", source)

    def test_scene_targets_and_bilateral_pelvis_bridges_are_guarded(self):
        operators = (PACKAGE / "operators" / "rigging.py").read_text(
            encoding="utf-8"
        )
        weights = (RIGGING / "weights.py").read_text(encoding="utf-8")
        poses = (RIGGING / "poses.py").read_text(encoding="utf-8")
        deformation = (RIGGING / "deformation.py").read_text(encoding="utf-8")
        self.assertIn("target.name not in context.view_layer.objects", operators)
        self.assertIn("def stabilize_bilateral_leg_bridges", weights)
        self.assertIn("bilateral_leg_bridge_feathered_vertices", weights)
        self.assertIn("meaningful_deformation", poses)
        self.assertIn("relative_displacements", deformation)

    def test_deformation_gate_uses_edges_and_palette_continuity(self):
        deformation = (RIGGING / "deformation.py").read_text(encoding="utf-8")
        weights = (RIGGING / "weights.py").read_text(encoding="utf-8")
        self.assertIn("maximum_edge_stretch_ratio", deformation)
        self.assertIn("maximum_coincident_seam_separation", deformation)
        self.assertIn("blocking_separated_components", deformation)
        self.assertIn("DEFAULT_EDGE_DEFORMED_LENGTH_RATIO = 0.04", deformation)
        self.assertIn('item["deformed_length"]', deformation)
        self.assertIn('height * edge_deformed_length_limit', deformation)
        self.assertIn("palette_reconciliation_iterations", weights)
        self.assertIn("maximum_edge_weight_delta_after", weights)

    def test_rigged_export_repairs_and_reimport_blocks_split_seam_weights(self):
        production = (RIGGING / "production.py").read_text(encoding="utf-8")
        self.assertIn("repair_glb_skin_weights", production)
        self.assertIn("audit_glb_skin_weights", production)
        self.assertIn('seam_weight_report["coincident_seam_weights_match"]', production)

    def test_final_weight_cleanup_matches_validator_threshold(self):
        source = (RIGGING / "weights.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_canonicalize_final_weights"
        )
        namespace = {
            "math": math,
            "DEFAULT_WEIGHT_THRESHOLD": 1.0e-4,
            "DEFAULT_INFLUENCE_LIMIT": 4,
            "WEIGHT_TOLERANCE": 1.0e-4,
        }
        isolated = ast.Module(body=[function], type_ignores=[])
        exec(compile(isolated, str(RIGGING / "weights.py"), "exec"), namespace)
        canonicalize = namespace["_canonicalize_final_weights"]

        failing_weights = [
            {"body": 0.99984, "neck": 0.00008, "root": 0.00008}
            for _index in range(25)
        ]
        cleaned, stats = canonicalize(failing_weights, 0.0001, 4)

        self.assertEqual([{"body": 1.0}] * 25, cleaned)
        self.assertEqual(50, stats["final_threshold_pruned_influences"])
        self.assertEqual(25, stats["final_threshold_pruned_vertices"])
        self.assertEqual(25, stats["final_renormalized_vertices"])

        bind = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "bind_production_character"
        )
        bind_source = ast.unparse(bind)
        self.assertLess(
            bind_source.index("_ensure_deform_group_coverage"),
            bind_source.index("_canonicalize_final_weights"),
        )

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
