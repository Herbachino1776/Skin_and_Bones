"""Build the installable legacy add-on ZIP."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "addon" / "skin_and_bones_forge"
DIST = ROOT / "dist"
VERSION = "0.1.0"
OUTPUT = DIST / f"skin_and_bones_forge-{VERSION}.zip"

DIST.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(PACKAGE.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        archive.write(path, path.relative_to(PACKAGE.parent).as_posix())

digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
checksum = OUTPUT.with_suffix(OUTPUT.suffix + ".sha256")
checksum.write_text(f"{digest}  {OUTPUT.name}\n", encoding="ascii")
print(f"Built: {OUTPUT}")
print(f"SHA256: {digest}")
