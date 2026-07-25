"""Generate real Dreadstone Animation Forge drafts for a supplied rigged GLB.

This runner is intentionally read-only with respect to the input GLB.  It is
designed to be followed by another Blender ``--python`` diagnostic in the same
process, or used alone to capture operator/mapping evidence.
"""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys

import bpy


def _arguments():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--glb", type=Path, required=True)
    parser.add_argument("--forge-repo", type=Path, required=True)
    parser.add_argument("--additional-draft", choices=("NONE", "HURT"), default="HURT")
    return parser.parse_args(argv)


args = _arguments()
bpy.ops.wm.read_factory_settings(use_empty=True)
repository = args.forge_repo.resolve()
if not (repository / "__init__.py").is_file():
    raise RuntimeError(f"Animation Forge package was not found: {repository}")

sys.path.insert(0, str(repository.parent))
forge = importlib.import_module(repository.name)
forge.register()

bpy.ops.import_scene.gltf(filepath=str(args.glb.resolve()))
armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
meshes = [
    obj
    for obj in bpy.data.objects
    if obj.type == "MESH"
    and any(
        modifier.type == "ARMATURE" and modifier.object in armatures
        for modifier in obj.modifiers
    )
]
if len(armatures) != 1 or len(meshes) != 1:
    raise RuntimeError(
        f"Expected one armature and one skinned mesh; found "
        f"{len(armatures)} armatures and {len(meshes)} meshes."
    )

armature = armatures[0]
mesh = meshes[0]
bpy.ops.object.select_all(action="DESELECT")
armature.select_set(True)
mesh.select_set(True)
bpy.context.view_layer.objects.active = armature

analysis_result = bpy.ops.daf.analyze()
mapping = forge.map_bones(armature, bpy.context.scene.daf_settings)
walk_result = bpy.ops.daf.walk()
additional_result = None
if args.additional_draft == "HURT":
    additional_result = bpy.ops.daf.hurt_left()
    # Leave the walk active for a chained deformation scanner.
    armature.animation_data.action = bpy.data.actions[forge.DRAFT_ACTION_NAMES["WALK"]]

mapping_text = bpy.data.texts.get("DSB_Rig_Mapping.txt")
report = {
    "status": "GENERATED",
    "blender": bpy.app.version_string,
    "forge_version": list(forge.bl_info["version"]),
    "input_glb": str(args.glb.resolve()),
    "armature": armature.name,
    "mesh": mesh.name,
    "analyze_operator_result": sorted(analysis_result),
    "walk_operator_result": sorted(walk_result),
    "additional_operator": "daf.hurt_left" if additional_result else None,
    "additional_operator_result": (
        sorted(additional_result) if additional_result else None
    ),
    "mapping": dict(sorted(mapping.items())),
    "mapping_report": mapping_text.as_string() if mapping_text else "",
    "active_action": (
        armature.animation_data.action.name
        if armature.animation_data and armature.animation_data.action
        else None
    ),
    "nla_tracks": [
        {
            "name": track.name,
            "mute": bool(track.mute),
            "strips": [
                strip.action.name if strip.action else None for strip in track.strips
            ],
        }
        for track in (armature.animation_data.nla_tracks if armature.animation_data else [])
    ],
    "actions": sorted(action.name for action in bpy.data.actions),
}
print("SBF_ANIMATION_FORGE_GENERATION")
print(json.dumps(report, indent=2, sort_keys=True))
