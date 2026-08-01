"""Pure Source Plate Doctor tests without Blender."""

from __future__ import annotations

import importlib.util
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "addon" / "skin_and_bones_forge" / "projection" / "source_doctor.py"
SPEC = importlib.util.spec_from_file_location("sbf_source_doctor", MODULE)
SOURCE_DOCTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCE_DOCTOR)


def synthetic_plate(width=11, height=11):
    background = (1.0, 0.1, 0.65)
    foreground = (0.55, 0.28, 0.18)
    pixels = []
    for y in range(height):
        for x in range(width):
            if 3 <= x <= 7 and 2 <= y <= 8:
                edge = x in {3, 7} or y in {2, 8}
                if edge:
                    alpha = 0.45
                    color = tuple(background[c] * 0.94 + foreground[c] * 0.06 for c in range(3))
                else:
                    alpha = 1.0
                    color = foreground
            else:
                alpha = 0.0
                color = background
            pixels.extend((*color, alpha))
    return pixels


class SourceDoctorTests(unittest.TestCase):
    def process(self):
        return SOURCE_DOCTOR.process_source_plate_pixels(
            synthetic_plate(),
            11,
            11,
            trusted_mask_erosion=190.0,
            rgb_extension_distance=760.0,
            despill_strength=1.0,
            silhouette_confidence_width=380.0,
        )

    def test_trusted_mask_is_eroded_inside_foreground(self):
        result = self.process()
        trusted = result["trusted_mask"]
        self.assertTrue(trusted[5 * 11 + 5])
        self.assertFalse(trusted[2 * 11 + 3])
        self.assertLess(sum(trusted), result["diagnostics"]["visible_pixels"])
        self.assertEqual(result["confidence"][5 * 11 + 5], 1.0)
        self.assertLess(result["confidence"][2 * 11 + 3], 1.0)

    def test_despill_reduces_background_matching(self):
        metrics = self.process()["diagnostics"]
        self.assertGreater(metrics["contamination_before"], metrics["contamination_after"])
        self.assertGreater(metrics["strong_matches_before"], metrics["strong_matches_after"])

    def test_hidden_rgb_extends_without_changing_alpha(self):
        source = synthetic_plate()
        result = self.process()
        cleaned = result["pixels"]
        adjacent = (5 * 11 + 2) * 4
        self.assertEqual(cleaned[adjacent + 3], 0.0)
        self.assertNotEqual(tuple(cleaned[adjacent : adjacent + 3]), tuple(source[adjacent : adjacent + 3]))
        self.assertEqual(
            [source[index] for index in range(3, len(source), 4)],
            [cleaned[index] for index in range(3, len(cleaned), 4)],
        )

    def test_processing_is_deterministic_and_finite(self):
        first = self.process()
        second = self.process()
        self.assertEqual(first["pixels"], second["pixels"])
        self.assertEqual(first["confidence"], second["confidence"])
        self.assertTrue(all(math.isfinite(value) for value in first["pixels"]))
        self.assertTrue(SOURCE_DOCTOR.validate_cleaned_pixels(first, 11, 11))

    def test_rejects_non_finite_pixels(self):
        pixels = synthetic_plate()
        pixels[0] = math.nan
        with self.assertRaisesRegex(ValueError, "non-finite"):
            SOURCE_DOCTOR.process_source_plate_pixels(pixels, 11, 11)


if __name__ == "__main__":
    unittest.main()
