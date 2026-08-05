"""Blender runtime regression for bundled rig loading and Y+ idempotence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix


def _args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--addon", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args(argv)


args = _args()
bpy.ops.wm.read_factory_settings(use_empty=True)
sys.path.insert(0, str(args.addon.resolve()))
import skin_and_bones_forge  # noqa: E402
from skin_and_bones_forge.constants import (  # noqa: E402
    CANONICAL_ASSET_PROPERTY,
    CANONICAL_FORWARD_PROPERTY,
    CANONICAL_RIG_VERSION,
    CANONICAL_RIG_VERSION_PROPERTY,
)
from skin_and_bones_forge.rigging import (  # noqa: E402
    analyze_canonical_rig,
    convert_legacy_character_yminus,
    ensure_unrigged_target_yplus,
)


skin_and_bones_forge.register()
try:
    settings = bpy.context.scene.sbf_settings
    first = bpy.ops.sbf.load_canonical_rig()
    first_object = settings.canonical_armature
    first_data = first_object.data
    first_contract = analyze_canonical_rig(bpy.context, first_object)
    second = bpy.ops.sbf.load_canonical_rig()
    templates = [
        obj
        for obj in bpy.data.objects
        if obj.type == "ARMATURE" and obj.get(CANONICAL_ASSET_PROPERTY, False)
    ]
    if "FINISHED" not in first or "FINISHED" not in second:
        raise RuntimeError("Bundled canonical rig operator did not finish.")
    if len(templates) != 1 or templates[0] is not first_object:
        raise RuntimeError("Repeated loading created a duplicate canonical rig.")
    if settings.canonical_armature.data is not first_data:
        raise RuntimeError("Repeated loading replaced the canonical armature data.")

    mesh_data = bpy.data.meshes.new("SBF_Test_YMinus_Data")
    mesh_data.from_pydata(
        [(0.0, -1.0, 0.0), (-0.2, 0.0, 0.0), (0.2, 0.0, 0.0)],
        [],
        [(0, 1, 2)],
    )
    target = bpy.data.objects.new("SBF_Test_YMinus", mesh_data)
    bpy.context.scene.collection.objects.link(target)
    target.location.x = 0.25
    normalization = ensure_unrigged_target_yplus(
        bpy.context, target, "-Y", "+Z"
    )
    first_positions = [vertex.co.copy() for vertex in target.data.vertices]
    repeat_normalization = ensure_unrigged_target_yplus(
        bpy.context, target, "+Y", "+Z"
    )
    second_positions = [vertex.co.copy() for vertex in target.data.vertices]
    if (
        not normalization["rotated"]
        or not normalization["object_transform_applied"]
        or repeat_normalization["rotated"]
    ):
        raise RuntimeError("Unrigged target orientation was not applied exactly once.")
    if first_positions != second_positions or first_positions[0].y < 0.999999:
        raise RuntimeError("Unrigged -Y target did not become stable +Y geometry.")
    if target.matrix_world != Matrix.Identity(4):
        raise RuntimeError("Unrigged target object transform was not applied.")

    legacy = first_object.copy()
    legacy.data = first_object.data.copy()
    legacy.name = "SBF_Test_LegacyRig"
    legacy.data.name = "SBF_Test_LegacyRig_Data"
    legacy[CANONICAL_ASSET_PROPERTY] = False
    legacy.data[CANONICAL_ASSET_PROPERTY] = False
    legacy[CANONICAL_FORWARD_PROPERTY] = "-Y"
    legacy.data[CANONICAL_FORWARD_PROPERTY] = "-Y"
    legacy["sbf_orientation_state"] = "LEGACY_Y_MINUS"
    legacy.data["sbf_orientation_state"] = "LEGACY_Y_MINUS"
    legacy.matrix_world = Matrix.Identity(4)
    bpy.context.scene.collection.objects.link(legacy)
    legacy_mesh_data = bpy.data.meshes.new("SBF_Test_LegacyMesh_Data")
    legacy_mesh_data.from_pydata(
        [(0.0, -1.0, 0.0), (-0.2, 0.0, 0.0), (0.2, 0.0, 0.0)],
        [],
        [(0, 1, 2)],
    )
    legacy_mesh = bpy.data.objects.new("SBF_Test_LegacyMesh", legacy_mesh_data)
    bpy.context.scene.collection.objects.link(legacy_mesh)
    modifier = legacy_mesh.modifiers.new("Armature", "ARMATURE")
    modifier.object = legacy
    migration = convert_legacy_character_yminus(
        bpy.context, legacy, legacy_mesh
    )
    migrated_positions = [vertex.co.copy() for vertex in legacy_mesh.data.vertices]
    repeated_migration = convert_legacy_character_yminus(
        bpy.context, legacy, legacy_mesh
    )
    if not migration["rotated"] or repeated_migration["rotated"]:
        raise RuntimeError("Legacy character migration was not idempotent.")
    if migrated_positions[0].y < 0.999999:
        raise RuntimeError("Legacy character did not migrate to +Y.")
    if legacy.get(CANONICAL_RIG_VERSION_PROPERTY) != CANONICAL_RIG_VERSION:
        raise RuntimeError("Migrated legacy rig lacks version metadata.")

    report = {
        "status": "CANONICAL_ASSET_RUNTIME_PASSED",
        "template_count_after_repeat": len(templates),
        "fingerprint": first_contract["fingerprint"],
        "bone_count": len(first_contract["bones"]),
        "forward_axis": first_contract["forward_axis"],
        "up_axis": first_contract["up_axis"],
        "action_count": len(first_contract["animation_inventory"]["actions"]),
        "reference_mesh_count": len(first_contract["reference_meshes"]),
        "unrigged_normalization": normalization,
        "unrigged_repeat": repeat_normalization,
        "legacy_migration": migration,
        "legacy_repeat": repeated_migration,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("SBF_CANONICAL_ASSET_RUNTIME")
    print(json.dumps(report, indent=2, sort_keys=True))
finally:
    skin_and_bones_forge.unregister()
