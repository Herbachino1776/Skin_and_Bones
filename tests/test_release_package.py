"""Pure-Python release packaging tests."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build_release.py"
OUTPUT = ROOT / "dist" / "Skin_and_Bones_Forge_v0.6.8.zip"


class ReleasePackageTests(unittest.TestCase):
    def _build(self):
        subprocess.run(
            [sys.executable, str(BUILD_SCRIPT)],
            cwd=ROOT,
            check=True,
        )
        self.assertTrue(OUTPUT.is_file())
        return hashlib.sha256(OUTPUT.read_bytes()).hexdigest()

    def test_release_zip_is_deterministic_and_installable(self):
        first_hash = self._build()
        second_hash = self._build()
        self.assertEqual(first_hash, second_hash)

        with zipfile.ZipFile(OUTPUT) as archive:
            names = archive.namelist()
            self.assertIsNone(archive.testzip())
            self.assertIn("skin_and_bones_forge/__init__.py", names)
            self.assertTrue(
                all(name.startswith("skin_and_bones_forge/") for name in names)
            )
            self.assertFalse(any("__pycache__" in name for name in names))
            self.assertFalse(any(name.endswith((".pyc", ".pyo")) for name in names))


if __name__ == "__main__":
    unittest.main()
