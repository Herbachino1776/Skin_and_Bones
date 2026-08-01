"""Pure tests for Texture Repair Studio algorithms."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

try:
    import numpy as np
except ModuleNotFoundError:  # Blender 5.1.2 bundles NumPy; host Python may not.
    np = None


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "addon"
    / "skin_and_bones_forge"
    / "baking"
    / "texture_repair.py"
)
if np is not None:
    SPEC = importlib.util.spec_from_file_location("sbf_texture_repair", MODULE_PATH)
    REPAIR = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = REPAIR
    SPEC.loader.exec_module(REPAIR)
else:
    REPAIR = None


@unittest.skipIf(np is None, "NumPy tests run in the supported Blender runtime")
class TextureRepairTests(unittest.TestCase):
    def rgba(self, height=16, width=16, color=(0.2, 0.3, 0.4, 1.0)):
        image = np.empty((height, width, 4), dtype=np.float32)
        image[:] = color
        return image

    def test_correction_composite_preserves_bake_and_alpha(self):
        baked = self.rgba(color=(0.1, 0.2, 0.3, 0.75))
        correction = self.rgba(color=(0.9, 0.6, 0.1, 0.1))
        mask = np.full((16, 16), 0.5, dtype=np.float32)
        original = baked.copy()
        result = REPAIR.composite_corrections(
            baked, correction, mask, opacity=0.5
        )
        np.testing.assert_array_equal(baked, original)
        np.testing.assert_allclose(result[0, 0, :3], (0.3, 0.3, 0.25))
        self.assertAlmostEqual(float(result[0, 0, 3]), 0.75)
        disabled = REPAIR.composite_corrections(
            baked, correction, mask, enabled=False
        )
        np.testing.assert_allclose(disabled, baked)

    def test_fingerprint_invalidates_uv_topology_and_size(self):
        vertices = ((0, 0, 0), (1, 0, 0), (0, 1, 0))
        polygons = ((0, 1, 2),)
        uvs = ((0, 0), (1, 0), (0, 1))
        original = REPAIR.repair_fingerprint(
            vertices, polygons, uvs, (2048, 2048), "SBF_BaseColorUV"
        )
        same = REPAIR.repair_fingerprint(
            vertices, polygons, uvs, (2048, 2048), "SBF_BaseColorUV"
        )
        changed_uv = REPAIR.repair_fingerprint(
            vertices,
            polygons,
            ((0, 0), (0.9, 0), (0, 1)),
            (2048, 2048),
            "SBF_BaseColorUV",
        )
        changed_topology = REPAIR.repair_fingerprint(
            vertices, ((0, 2, 1),), uvs, (2048, 2048), "SBF_BaseColorUV"
        )
        changed_size = REPAIR.repair_fingerprint(
            vertices, polygons, uvs, (4096, 4096), "SBF_BaseColorUV"
        )
        self.assertTrue(REPAIR.repair_state_is_compatible(original, same))
        self.assertEqual(len({original, changed_uv, changed_topology, changed_size}), 4)

    def test_tangent_clone_mapping_handles_rotated_uv_islands(self):
        offsets = np.array(((0.1, 0.0), (0.0, 0.2)), dtype=np.float64)
        source_basis = ((0.0, -1.0), (1.0, 0.0))
        target_basis = ((1.0, 0.0), (0.0, 1.0))
        mapped = REPAIR.map_tangent_clone_offsets(
            offsets,
            (0.5, 0.5),
            source_basis,
            target_basis,
        )
        np.testing.assert_allclose(mapped[0], (0.5, 0.6), atol=1.0e-8)
        np.testing.assert_allclose(mapped[1], (0.3, 0.5), atol=1.0e-8)

    def test_clone_stroke_writes_only_non_destructive_layers(self):
        baked = self.rgba(32, 32)
        baked[:, :, 0] = np.linspace(0.0, 1.0, 32)[None, :]
        before = baked.copy()
        correction = np.zeros_like(baked)
        mask = np.zeros((32, 32), dtype=np.float32)
        classes = np.zeros((32, 32), dtype=np.uint8)
        result = REPAIR.apply_surface_stroke(
            baked,
            correction,
            mask,
            classes,
            source_uv=(0.75, 0.5),
            target_uv=(0.25, 0.5),
            source_tangent_to_uv=((0.0, -1.0), (1.0, 0.0)),
            target_tangent_to_uv=((1.0, 0.0), (0.0, 1.0)),
            radius=5,
            hardness=0.5,
            opacity=1.0,
            mode="CLONE",
        )
        np.testing.assert_array_equal(baked, before)
        self.assertGreater(result.changed_pixels, 0)
        self.assertGreater(float(mask[16, 8]), 0.99)
        self.assertEqual(int(classes[16, 8]), REPAIR.CLONE)
        self.assertGreater(float(correction[16, 8, 0]), 0.70)

    def test_heal_frequency_separation_adapts_color_and_keeps_detail(self):
        yy, xx = np.mgrid[:32, :32]
        checker = ((xx + yy) % 2).astype(np.float32) * 0.16 - 0.08
        source = self.rgba(32, 32, (0.25, 0.25, 0.25, 1.0))
        target = self.rgba(32, 32, (0.72, 0.46, 0.32, 1.0))
        source[:, :, :3] += checker[:, :, None]
        healed = REPAIR.frequency_separated_heal(
            source, target, detail_preservation=1.0, low_frequency_radius=3
        )
        np.testing.assert_allclose(
            healed[:, :, :3].mean(axis=(0, 1)),
            target[:, :, :3].mean(axis=(0, 1)),
            atol=0.015,
        )
        self.assertGreater(float(healed[:, :, 0].std()), 0.06)

    def _smart_fill_fixture(self):
        image = self.rgba(12, 18, (0.3, 0.3, 0.3, 1.0))
        semantics = np.full((12, 18), -1, dtype=np.int16)
        materials = np.full((12, 18), -1, dtype=np.int16)
        donor = np.zeros((12, 18), dtype=bool)
        target = np.zeros((12, 18), dtype=bool)
        # Unrelated hand donor: tempting boundary color but semantically invalid.
        semantics[1:5, 1:5] = 2
        materials[1:5, 1:5] = 0
        image[1:5, 1:5, :3] = (1.0, 0.1, 0.1)
        donor[1:5, 1:5] = True
        # Opposite leg donor: the only allowed combined-safe source.
        semantics[7:11, 1:5] = 6
        materials[7:11, 1:5] = 0
        image[7:11, 1:5, :3] = (0.1, 0.2, 0.9)
        donor[7:11, 1:5] = True
        semantics[4:9, 11:16] = 5
        materials[4:9, 11:16] = 0
        target[5:8, 12:15] = True
        image[target, :3] = 1.0
        return image, target, donor, semantics, materials

    def test_smart_fill_is_deterministic_and_restricts_donors(self):
        fixture = self._smart_fill_fixture()
        first = REPAIR.smart_fill_masked(*fixture, max_candidates=32)
        second = REPAIR.smart_fill_masked(*fixture, max_candidates=32)
        np.testing.assert_array_equal(first["image"], second["image"])
        self.assertEqual(first["filled"], 9)
        self.assertEqual(first["unresolved"], 0)
        filled_colors = first["image"][fixture[1], :3]
        self.assertTrue(np.all(filled_colors[:, 2] > 0.8))
        self.assertTrue(np.all(filled_colors[:, 0] < 0.2))

    def test_same_material_policy_still_rejects_unrelated_hand(self):
        fixture = self._smart_fill_fixture()
        result = REPAIR.smart_fill_masked(
            *fixture,
            source_policy="SAME_MATERIAL",
            max_candidates=32,
        )
        filled_colors = result["image"][fixture[1], :3]
        self.assertEqual(result["filled"], 9)
        self.assertTrue(np.all(filled_colors[:, 2] > 0.8))
        self.assertTrue(np.all(filled_colors[:, 0] < 0.2))

    def test_forbidden_mask_can_leave_smart_fill_unresolved(self):
        image, target, donor, semantics, materials = self._smart_fill_fixture()
        result = REPAIR.smart_fill_masked(
            image,
            target,
            donor,
            semantics,
            materials,
            forbidden_mask=donor,
        )
        self.assertEqual(result["filled"], 0)
        self.assertEqual(result["unresolved"], 9)
        self.assertGreaterEqual(result["rejected"], 1)

    def test_forbidden_distance_increases_away_from_contamination(self):
        forbidden = np.zeros((7, 7), dtype=bool)
        forbidden[3, 3] = True
        distance = REPAIR.normalized_distance_from_mask(
            forbidden, max_distance=4
        )
        self.assertEqual(float(distance[3, 3]), 0.0)
        self.assertLess(float(distance[3, 4]), float(distance[3, 6]))
        self.assertEqual(float(distance[0, 0]), 1.0)

    def test_smart_fill_advances_from_boundary_to_center(self):
        image = self.rgba(9, 9, (0.15, 0.55, 0.25, 1.0))
        target = np.zeros((9, 9), dtype=bool)
        target[2:7, 2:7] = True
        image[target, :3] = 1.0
        semantic = np.zeros((9, 9), dtype=np.int16)
        material = np.zeros((9, 9), dtype=np.int16)
        donor = ~target
        result = REPAIR.smart_fill_masked(
            image,
            target,
            donor,
            semantic,
            material,
            source_policy="SAME_PART",
        )
        self.assertEqual(result["filled"], 25)
        self.assertEqual(result["unresolved"], 0)
        np.testing.assert_allclose(result["image"][4, 4, :3], (0.15, 0.55, 0.25))

    def test_seam_pair_detection_uses_shared_geometry(self):
        faces = ((0, 1, 2), (1, 0, 3), (4, 5, 6))
        face_uvs = (
            ((0.1, 0.1), (0.4, 0.1), (0.2, 0.4)),
            ((0.8, 0.8), (0.6, 0.8), (0.7, 0.5)),
            ((0.0, 0.0), (0.1, 0.0), (0.0, 0.1)),
        )
        pairs = REPAIR.detect_uv_seam_pairs(faces, face_uvs)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["edge"], (0, 1))
        self.assertEqual(pairs[0]["faces"], (0, 1))

    def test_seam_harmonization_reduces_error_without_broad_blur(self):
        image = self.rgba(64, 64, (0.2, 0.2, 0.2, 1.0))
        image[:, 40:, :3] = (0.8, 0.65, 0.5)
        # High-frequency detail proves the function applies a color delta rather
        # than replacing both regions with a generic blurred image.
        image[::2, :, 0] += 0.04
        pair = {
            "edge": (0, 1),
            "faces": (0, 1),
            "uv_a": ((0.25, 0.2), (0.25, 0.8)),
            "uv_b": ((0.75, 0.2), (0.75, 0.8)),
            "separation": 0.5,
        }
        before = REPAIR.seam_error(image, [pair])
        result = REPAIR.harmonize_seam_bands(
            image, [pair], seam_width=3, max_correction=1.0
        )
        self.assertLess(result["after_error"], before * 0.35)
        np.testing.assert_array_equal(result["image"][:, 31:34], image[:, 31:34])
        self.assertAlmostEqual(
            float(result["image"][20, 16, 0] - result["image"][21, 16, 0]),
            float(image[20, 16, 0] - image[21, 16, 0]),
            places=5,
        )

    def test_source_classification_and_unresolved_detection(self):
        image = self.rgba(4, 4, (0.5, 0.4, 0.3, 1.0))
        coverage = np.ones((4, 4), dtype=bool)
        confidence = np.ones((4, 4), dtype=np.float32)
        confidence[1, 1] = 0.0
        image[1, 1, :3] = 1.0
        unresolved = REPAIR.detect_unresolved(image, coverage, confidence)
        classes = REPAIR.initial_classification(coverage, confidence, unresolved)
        self.assertTrue(unresolved[1, 1])
        self.assertEqual(int(classes[1, 1]), REPAIR.UNRESOLVED)
        self.assertEqual(int(classes[0, 0]), REPAIR.DIRECT_PROJECTION)
        rgba = REPAIR.classification_rgba(classes)
        np.testing.assert_allclose(
            rgba[1, 1], REPAIR.CLASSIFICATION_COLORS[REPAIR.UNRESOLVED]
        )


if __name__ == "__main__":
    unittest.main(argv=[__file__])
