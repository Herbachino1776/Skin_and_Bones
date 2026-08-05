"""Build a deterministic installable Blender add-on ZIP."""

from __future__ import annotations

import ast
import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "addon" / "skin_and_bones_forge"
DIST = ROOT / "dist"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
CANONICAL_ASSET = PACKAGE / "assets" / "canonical_humanoid_yplus_v1.blend"
CANONICAL_MANIFEST = (
    PACKAGE / "assets" / "canonical_humanoid_yplus_v1.contract.json"
)


def _validate_canonical_asset():
    missing = [
        path.name
        for path in (CANONICAL_ASSET, CANONICAL_MANIFEST)
        if not path.is_file()
    ]
    if missing:
        raise RuntimeError(
            "Canonical rig packaging failed; missing: " + ", ".join(missing)
        )
    manifest = json.loads(CANONICAL_MANIFEST.read_text(encoding="utf-8"))
    digest = hashlib.sha256(CANONICAL_ASSET.read_bytes()).hexdigest()
    if digest != manifest.get("asset_sha256"):
        raise RuntimeError(
            "Canonical rig packaging failed; asset checksum differs from manifest."
        )
    if (
        manifest.get("rig_version") != "SBF_HUMANOID_YPLUS_V1"
        or manifest.get("forward_axis") != "+Y"
        or manifest.get("up_axis") != "+Z"
    ):
        raise RuntimeError(
            "Canonical rig packaging failed; version or axis contract is invalid."
        )


def _addon_version():
    tree = ast.parse((PACKAGE / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "bl_info"
                for target in node.targets
            ):
                bl_info = ast.literal_eval(node.value)
                return ".".join(str(part) for part in bl_info["version"])
    raise RuntimeError("Could not read literal bl_info version from add-on package.")


VERSION = _addon_version()
OUTPUT = DIST / f"Skin_and_Bones_Forge_v{VERSION}.zip"

_validate_canonical_asset()
DIST.mkdir(parents=True, exist_ok=True)
for pattern in ("Skin_and_Bones_Forge_v*.zip", "skin_and_bones_forge-*.zip"):
    for old_output in DIST.glob(pattern):
        old_output.unlink()
        checksum = old_output.with_suffix(old_output.suffix + ".sha256")
        if checksum.exists():
            checksum.unlink()

with zipfile.ZipFile(
    OUTPUT,
    "w",
    compression=zipfile.ZIP_DEFLATED,
    compresslevel=9,
) as archive:
    for path in sorted(PACKAGE.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        archive_name = path.relative_to(PACKAGE.parent).as_posix()
        info = zipfile.ZipInfo(archive_name, date_time=FIXED_ZIP_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        archive.writestr(
            info,
            path.read_bytes(),
            compress_type=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        )

digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
checksum = OUTPUT.with_suffix(OUTPUT.suffix + ".sha256")
checksum.write_text(f"{digest}  {OUTPUT.name}\n", encoding="ascii")
print(f"Built: {OUTPUT}")
print(f"SHA256: {digest}")
