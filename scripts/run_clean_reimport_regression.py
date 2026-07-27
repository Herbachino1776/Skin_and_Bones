"""Validate an exported rigged GLB from a configured production .blend."""

import json
import os
from pathlib import Path
import sys

import bpy


addon = str((Path.cwd() / "addon").resolve())
existing = sys.modules.get("skin_and_bones_forge")
if existing is not None and hasattr(existing, "unregister"):
    existing.unregister()
for module_name in list(sys.modules):
    if module_name == "skin_and_bones_forge" or module_name.startswith(
        "skin_and_bones_forge."
    ):
        del sys.modules[module_name]
sys.path.insert(0, addon)

import skin_and_bones_forge  # noqa: E402
from skin_and_bones_forge.rigging.production import (  # noqa: E402
    validate_clean_reimport,
)


skin_and_bones_forge.register()
settings = bpy.context.scene.sbf_settings
contract = json.loads(settings.rig_production_contract_json)
glb = os.environ.get("SBF_RIGGED_GLB", settings.rigged_export_glb_path)
report = validate_clean_reimport(
    bpy.context,
    glb,
    contract,
    settings.target_height,
)
print("SBF_CLEAN_REIMPORT_REGRESSION", json.dumps(report, sort_keys=True))
assert report["status"] == "CLEAN_REIMPORT_PASSED", report
