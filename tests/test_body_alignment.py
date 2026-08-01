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

    def test_processed_state_invalidation_is_stable(self):
        payload = {"source": "front", "doctor": {"despill": 0.85}, "landmarks": [0.4, 0.8]}
        token = BODY.processed_state_token(payload)
        self.assertFalse(BODY.processed_state_is_stale(token, payload))
        changed = {**payload, "doctor": {"despill": 0.90}}
        self.assertTrue(BODY.processed_state_is_stale(token, changed))
        self.assertEqual(token, BODY.processed_state_token(payload))


if __name__ == "__main__":
    unittest.main()
