"""Clean extracted-release smoke test for registration and canonical loading."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import zipfile

import bpy


argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
parser = argparse.ArgumentParser()
parser.add_argument("--zip", type=Path, required=True)
parser.add_argument("--install-dir", type=Path, required=True)
parser.add_argument("--report", type=Path, required=True)
args = parser.parse_args(argv)

args.install_dir.mkdir(parents=True, exist_ok=False)
with zipfile.ZipFile(args.zip.resolve()) as archive:
    archive.extractall(args.install_dir)
for module_name in list(sys.modules):
    if module_name == "skin_and_bones_forge" or module_name.startswith(
        "skin_and_bones_forge."
    ):
        del sys.modules[module_name]
sys.path.insert(0, str(args.install_dir.resolve()))
import skin_and_bones_forge  # noqa: E402


skin_and_bones_forge.register()
try:
    result = bpy.ops.sbf.load_canonical_rig()
    armature = bpy.context.scene.sbf_settings.canonical_armature
    if "FINISHED" not in result or armature is None:
        raise RuntimeError("Installed release could not load its canonical rig.")
    report = {
        "status": "CLEAN_INSTALL_CANONICAL_PASSED",
        "addon_version": list(skin_and_bones_forge.bl_info["version"]),
        "armature": armature.name,
        "bone_count": len(armature.data.bones),
        "rig_version": armature.get("sbf_canonical_rig_version", ""),
        "forward_axis": armature.get("sbf_forward_axis", ""),
        "up_axis": armature.get("sbf_up_axis", ""),
        "installed_package": str(
            args.install_dir.resolve() / "skin_and_bones_forge"
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("SBF_CLEAN_INSTALL_CANONICAL")
    print(json.dumps(report, indent=2, sort_keys=True))
finally:
    skin_and_bones_forge.unregister()
