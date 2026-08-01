"""Pure projection-landmark clustering regressions."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "addon" / "skin_and_bones_forge" / "rigging" / "landmark_math.py"
SPEC = importlib.util.spec_from_file_location("sbf_landmark_math", MODULE)
LANDMARK_MATH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LANDMARK_MATH)


class LandmarkMathTests(unittest.TestCase):
    def test_isolates_arm_band_outside_dense_torso_band(self):
        torso = [0.002 * index for index in range(96)]
        arm = [0.34 + 0.001 * index for index in range(48)]
        values = torso + arm
        indices = LANDMARK_MATH.isolated_outer_cluster_indices(
            values,
            minimum_gap=0.02,
        )
        self.assertEqual(set(indices), set(range(len(torso), len(values))))

    def test_rejects_a_continuous_slice_without_an_isolated_limb(self):
        values = [0.002 * index for index in range(144)]
        self.assertEqual(
            LANDMARK_MATH.isolated_outer_cluster_indices(
                values,
                minimum_gap=0.02,
            ),
            (),
        )

    def test_rejects_non_finite_input(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            LANDMARK_MATH.isolated_outer_cluster_indices(
                [0.1, float("nan")] * 10,
                minimum_gap=0.02,
            )


if __name__ == "__main__":
    unittest.main()
