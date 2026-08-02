"""Pure body-landmark, warp mapping, ownership, and preflight tests."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "addon" / "skin_and_bones_forge" / "projection" / "body_alignment.py"
SPEC = importlib.util.spec_from_file_location("sbf_body_alignment", MODULE)
BODY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BODY)


class BodyAlignmentTests(unittest.TestCase):
    def test_landmark_overlay_labels_names_and_orients_anatomical_right(self):
        self.assertEqual(
            BODY.body_landmark_display_label("shoulder_right"),
            "4. Right shoulder",
        )
        self.assertEqual(
            BODY.body_landmark_display_label("hand_right"),
            "10. Right hand center",
        )
        self.assertEqual(
            BODY.body_landmark_orientation_hint("front"),
            "Front view: character RIGHT is image LEFT",
        )
        self.assertEqual(
            BODY.body_landmark_orientation_hint("back"),
            "Back view: character RIGHT is image RIGHT",
        )
        self.assertEqual(BODY.body_landmark_orientation_hint("left"), "")
        with self.assertRaisesRegex(ValueError, "Unknown body landmark"):
            BODY.body_landmark_display_label("third_elbow")

    def test_landmark_normalization_clamps_and_rejects_unknowns(self):
        result = BODY.normalize_landmark_metadata(
            {"points": {"head_top": (-0.2, 1.2)}, "skipped": []}
        )
        self.assertEqual(result["points"]["head_top"], (0.0, 1.0))
        with self.assertRaisesRegex(ValueError, "Unknown"):
            BODY.normalize_landmark_metadata(
                {"points": {"third_elbow": (0.5, 0.5)}, "skipped": []}
            )

    def test_profile_explicitly_skips_hidden_side(self):
        profile = BODY.auto_initialize_landmarks("left")
        hidden = {name for name in BODY.BODY_LANDMARK_NAMES if name.endswith("_right")}
        self.assertTrue(hidden.issubset(set(profile["skipped"])))
        broken = {"points": dict(profile["points"]), "skipped": []}
        with self.assertRaisesRegex(ValueError, "explicitly skip"):
            BODY.normalize_landmark_metadata(broken, "left")

    def test_piecewise_affine_mapping_is_bounded(self):
        source = [((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))]
        target = [((0.0, 0.0), (2.0, 0.0), (0.0, 2.0))]
        self.assertEqual(BODY.piecewise_affine_map((0.5, 0.5), source, target), (0.25, 0.25))
        self.assertIsNone(BODY.piecewise_affine_map((1.8, 1.8), source, target))

    def test_body_part_ownership_prevents_crossing(self):
        landmarks = BODY.auto_initialize_landmarks("front")["points"]
        self.assertEqual(BODY.body_part_ownership(landmarks["hand_left"], landmarks), "left_arm")
        self.assertEqual(BODY.body_part_ownership(landmarks["hand_right"], landmarks), "right_arm")
        self.assertEqual(BODY.body_part_ownership((0.5, 0.68), landmarks), "torso")
        self.assertEqual(BODY.body_part_ownership(landmarks["knee_left"], landmarks), "left_leg")
        self.assertNotEqual(BODY.body_part_ownership(landmarks["hand_left"], landmarks), "right_leg")

    def test_mismatch_classification_and_warp_improvement(self):
        source = BODY.auto_initialize_landmarks("front")
        target = {"points": dict(source["points"]), "skipped": []}
        target["points"]["wrist_left"] = (
            source["points"]["wrist_left"][0] - 0.25,
            source["points"]["wrist_left"][1] + 0.22,
        )
        before = BODY.pose_mismatch(source, target)
        self.assertEqual(before["status"], "SEVERE")
        after = BODY.pose_mismatch(target, target)
        self.assertEqual(after["status"], "ACCEPTABLE")
        self.assertGreater(before["error"], after["error"])
        self.assertEqual(BODY.classify_mismatch(0.25), "MODERATE")

    def test_symmetric_hanging_arms_from_visual_fixture_are_acceptable(self):
        source = {
            "points": {
                "shoulder_left": (0.373, 0.757),
                "elbow_left": (0.334, 0.643),
                "wrist_left": (0.292, 0.532),
                "hand_left": (0.287, 0.484),
                "shoulder_right": (0.627, 0.757),
                "elbow_right": (0.661, 0.643),
                "wrist_right": (0.711, 0.532),
                "hand_right": (0.728, 0.484),
            }
        }
        target = {
            "points": {
                "shoulder_left": (0.378561, 0.757507),
                "elbow_left": (0.338825, 0.645886),
                "wrist_left": (0.293406, 0.534265),
                "hand_left": (0.287116, 0.478455),
                "shoulder_right": (0.629151, 0.757507),
                "elbow_right": (0.664073, 0.645886),
                "wrist_right": (0.708614, 0.534265),
                "hand_right": (0.713983, 0.478455),
            }
        }
        mismatch = BODY.pose_mismatch(source, target)
        self.assertEqual(mismatch["parts"]["left_arm"]["status"], "ACCEPTABLE")
        self.assertEqual(mismatch["parts"]["right_arm"]["status"], "ACCEPTABLE")
        self.assertLess(mismatch["parts"]["left_arm"]["error"], 0.12)
        self.assertLess(mismatch["parts"]["right_arm"]["error"], 0.12)

    def test_high_a_back_hands_must_continue_forearms_not_fold_to_pelvis(self):
        source = {
            "points": {
                "shoulder_left": (0.418, 0.768),
                "elbow_left": (0.287, 0.656),
                "wrist_left": (0.183, 0.571),
                "hand_left": (0.157, 0.544),
                "shoulder_right": (0.598, 0.772),
                "elbow_right": (0.723, 0.658),
                "wrist_right": (0.809, 0.579),
                "hand_right": (0.845, 0.552),
            }
        }
        folded_target = {
            "points": {
                "shoulder_left": (0.346971, 0.747500),
                "elbow_left": (0.226828, 0.639500),
                "wrist_left": (0.122596, 0.531500),
                "hand_left": (0.417935, 0.489249),
                "shoulder_right": (0.653665, 0.747500),
                "elbow_right": (0.771026, 0.639500),
                "wrist_right": (0.875414, 0.531500),
                "hand_right": (0.585258, 0.493158),
            }
        }
        continued_target = {
            "points": {
                **folded_target["points"],
                "hand_left": (0.090621, 0.498369),
                "hand_right": (0.907180, 0.498635),
            }
        }

        folded = BODY.pose_mismatch(source, folded_target)["parts"]
        continued = BODY.pose_mismatch(source, continued_target)["parts"]

        self.assertEqual(folded["left_arm"]["status"], "SEVERE")
        self.assertEqual(folded["right_arm"]["status"], "SEVERE")
        self.assertEqual(continued["left_arm"]["status"], "ACCEPTABLE")
        self.assertEqual(continued["right_arm"]["status"], "ACCEPTABLE")
        self.assertLess(continued["left_arm"]["error"], 0.07)
        self.assertLess(continued["right_arm"]["error"], 0.07)

    @unittest.skipIf(BODY._np is None, "NumPy runtime is unavailable")
    def test_bounded_raster_write_reaches_the_destination_image(self):
        landmarks = BODY.auto_initialize_landmarks("front")
        pixels = BODY._np.ones((64, 64, 4), dtype=BODY._np.float32)
        warped = BODY.warp_part_pixels(
            pixels,
            64,
            64,
            landmarks,
            landmarks,
            "head",
            feather=0.08,
        )
        visible = warped[:, :, 3] > 0.0
        self.assertTrue(visible.any())
        self.assertFalse(visible.all())
        self.assertGreater(float(warped[:, :, 3].max()), 0.9)

    @unittest.skipIf(BODY._np is None, "NumPy runtime is unavailable")
    def test_continuous_source_keeps_base_and_only_overlays_moderate_limbs(self):
        base = BODY._np.zeros((8, 8, 4), dtype=BODY._np.float32)
        base[:, :, 0] = 0.25
        base[:, :, 3] = 1.0
        moderate_arm = BODY._np.zeros_like(base)
        moderate_arm[2:6, 2:6, 1] = 1.0
        moderate_arm[2:6, 2:6, 3] = 0.5
        ignored_head = BODY._np.zeros_like(base)
        ignored_head[:, :, 2] = 1.0
        ignored_head[:, :, 3] = 1.0
        result, applied = BODY.compose_continuous_source(
            base,
            {"left_arm": moderate_arm, "head": ignored_head},
            {
                "left_arm": {"status": "MODERATE"},
                "head": {"status": "MODERATE"},
            },
        )
        self.assertEqual(applied, ("left_arm",))
        self.assertTrue(BODY._np.allclose(result[0, 0], base[0, 0]))
        self.assertAlmostEqual(float(result[3, 3, 0]), 0.125, places=6)
        self.assertAlmostEqual(float(result[3, 3, 1]), 0.5, places=6)
        self.assertAlmostEqual(float(result[:, :, 3].min()), 1.0, places=6)

        untouched, applied = BODY.compose_continuous_source(
            base,
            {"left_arm": moderate_arm},
            {"left_arm": {"status": "ACCEPTABLE"}},
        )
        self.assertEqual(applied, ())
        self.assertTrue(BODY._np.array_equal(untouched, base))

    def test_processed_state_invalidation_is_stable(self):
        payload = {"source": "front", "doctor": {"despill": 0.85}, "landmarks": [0.4, 0.8]}
        token = BODY.processed_state_token(payload)
        self.assertFalse(BODY.processed_state_is_stale(token, payload))
        changed = {**payload, "doctor": {"despill": 0.90}}
        self.assertTrue(BODY.processed_state_is_stale(token, changed))
        self.assertEqual(token, BODY.processed_state_token(payload))


if __name__ == "__main__":
    unittest.main()
