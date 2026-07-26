"""Tests for projection-folder filename discovery without requiring Blender."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "addon" / "skin_and_bones_forge" / "projection" / "source_files.py"
)
SPEC = importlib.util.spec_from_file_location("sbf_source_files", MODULE_PATH)
SOURCE_FILES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCE_FILES)


class ProjectionSourceFileTests(unittest.TestCase):
    def test_finds_four_views_and_ignores_source_and_non_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            expected = {}
            for name in ("front", "back", "left", "right"):
                expected[name] = folder / f"{name}_projection.PNG"
                expected[name].touch()
            (folder / "character_source_2k.png").touch()
            (folder / "manifest.txt").touch()

            self.assertEqual(
                SOURCE_FILES.find_cardinal_view_images(folder),
                expected,
            )

    def test_rejects_missing_view_without_guessing(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for name in ("front", "back", "left"):
                (folder / f"character-{name}.jpg").touch()

            with self.assertRaisesRegex(ValueError, "missing: right"):
                SOURCE_FILES.find_cardinal_view_images(folder)

    def test_rejects_duplicate_view_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for name in ("front", "back", "left", "right"):
                (folder / f"{name}_projection.png").touch()
            (folder / "character.front.webp").touch()

            with self.assertRaisesRegex(ValueError, "multiple matches: front"):
                SOURCE_FILES.find_cardinal_view_images(folder)

    def test_view_key_must_be_a_separate_filename_token(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for name in ("front", "back", "left", "right"):
                (folder / f"{name}_projection.png").touch()
            (folder / "leftover_source.png").touch()

            found = SOURCE_FILES.find_cardinal_view_images(folder)
            self.assertEqual(found["left"].name, "left_projection.png")


if __name__ == "__main__":
    unittest.main()
