"""Export Townsman with the Y+ contract and validate a clean GLB reimport."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy


def _args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--addon", type=Path, required=True)
    parser.add_argument("--glb", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args(argv)


args = _args()
existing = sys.modules.get("skin_and_bones_forge")
if existing is not None and hasattr(existing, "unregister"):
    try:
        existing.unregister()
    except RuntimeError:
        pass
for module_name in list(sys.modules):
    if module_name == "skin_and_bones_forge" or module_name.startswith(
        "skin_and_bones_forge."
    ):
        del sys.modules[module_name]
sys.path.insert(0, str(args.addon.resolve()))
import skin_and_bones_forge  # noqa: E402
from skin_and_bones_forge.rigging import (  # noqa: E402
    apply_canonical_metadata,
    derive_simplified_contract,
    ensure_canonical_rig,
    export_rigged_glb,
    validate_clean_reimport,
)
from skin_and_bones_forge.rigging.contract import (  # noqa: E402
    analyze_canonical_rig,
)


skin_and_bones_forge.register()
try:
    target = bpy.data.objects.get("SBF_CLEAN_CHARACTER")
    armature = bpy.data.objects.get("SBF_ProductionRig")
    if target is None or armature is None:
        raise RuntimeError("Townsman production character was not found.")
    settings = bpy.context.scene.sbf_settings
    settings.target_object = target
    settings.canonical_contract_json = ""
    settings.rig_production_contract_json = ""
    canonical = ensure_canonical_rig(bpy.context, settings)
    full_contract = analyze_canonical_rig(bpy.context, canonical)
    contract = derive_simplified_contract(full_contract)
    settings.canonical_fingerprint = full_contract["fingerprint"]
    settings.rig_production_fingerprint = contract["fingerprint"]
    settings.rig_production_profile = contract["profile_id"]
    settings.rig_export_actions = False
    settings.target_height = 1.5
    settings.rigged_export_glb_path = str(args.glb.resolve())
    if armature.animation_data is not None:
        armature.animation_data_clear()
    for pose_bone in armature.pose.bones:
        pose_bone.matrix_basis.identity()
    armature.data.pose_position = "REST"
    apply_canonical_metadata(armature, target=target)
    armature["sbf_production_profile"] = contract["profile_id"]
    armature["sbf_production_fingerprint"] = contract["fingerprint"]
    armature["sbf_canonical_fingerprint"] = contract["source_fingerprint"]
    target["sbf_production_profile"] = contract["profile_id"]
    target["sbf_production_fingerprint"] = contract["fingerprint"]
    bpy.context.view_layer.update()
    output, manifest = export_rigged_glb(
        bpy.context, target, armature, contract, settings
    )
    reimport = validate_clean_reimport(
        bpy.context, output, contract, settings.target_height
    )
    if reimport["status"] != "CLEAN_REIMPORT_PASSED":
        raise RuntimeError(
            "Townsman Y+ GLB clean reimport failed: "
            + json.dumps(reimport, sort_keys=True)
        )
    report = {
        "status": "TOWNSMAN_CANONICAL_ROUNDTRIP_PASSED",
        "glb": str(output),
        "manifest": str(manifest),
        "canonical_fingerprint": full_contract["fingerprint"],
        "production_fingerprint": contract["fingerprint"],
        "rig_version": armature.get("sbf_canonical_rig_version", ""),
        "forward_axis": armature.get("sbf_forward_axis", ""),
        "up_axis": armature.get("sbf_up_axis", ""),
        "reimport": reimport,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("SBF_TOWNSMAN_CANONICAL_ROUNDTRIP")
    print(json.dumps(report, indent=2, sort_keys=True))
finally:
    skin_and_bones_forge.unregister()
