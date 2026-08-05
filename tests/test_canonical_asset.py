"""Packaged canonical-rig and Y+ handoff contract tests."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "addon" / "skin_and_bones_forge"
ASSET = PACKAGE / "assets" / "canonical_humanoid_yplus_v1.blend"
MANIFEST = PACKAGE / "assets" / "canonical_humanoid_yplus_v1.contract.json"


class CanonicalAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_asset_is_armature_only_yplus_contract(self):
        payload = self.manifest
        self.assertEqual("SBF_HUMANOID_YPLUS_V1", payload["rig_version"])
        self.assertEqual("+Y", payload["forward_axis"])
        self.assertEqual("+Z", payload["up_axis"])
        self.assertEqual("root", payload["root_bone"])
        self.assertEqual(1.0, payload["unit_scale_meters"])
        self.assertEqual(21, payload["bone_count"])
        self.assertEqual(21, payload["deform_bone_count"])
        self.assertEqual(0, payload["animation_count"])
        self.assertEqual(0, payload["reference_mesh_count"])

    def test_asset_checksum_and_portability(self):
        binary = ASSET.read_bytes()
        self.assertEqual(
            self.manifest["asset_sha256"], hashlib.sha256(binary).hexdigest()
        )
        self.assertNotIn(b"D:\\Blender", binary)
        self.assertNotIn(b"Townsman,blend.blend", binary)

    def test_rest_geometry_encodes_yplus_and_anatomical_sides(self):
        bones = {
            bone["name"]: bone for bone in self.manifest["contract"]["bones"]
        }
        for side in ("left", "right"):
            foot = bones[f"leg_{side}_foot"]
            self.assertGreater(foot["tail"][1], foot["head"][1])
        self.assertGreater(
            bones["leg_right_top"]["head"][0],
            bones["leg_left_top"]["head"][0],
        )
        self.assertIsNone(bones["root"]["parent"])
        self.assertGreater(bones["root"]["tail"][2], bones["root"]["head"][2])

    def test_packaging_preflight_has_clear_missing_asset_failure(self):
        source = (ROOT / "scripts" / "build_release.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("Canonical rig packaging failed; missing:", source)
        self.assertIn("asset checksum differs from manifest", source)


if __name__ == "__main__":
    unittest.main()
