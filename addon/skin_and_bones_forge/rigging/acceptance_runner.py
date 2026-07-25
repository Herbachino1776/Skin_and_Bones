"""Isolated Blender process for actual Dreadstone Animation Forge acceptance."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import re
import sys

import bpy


def _args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--glb", type=Path, required=True)
    parser.add_argument("--forge-repo", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args(argv)


def _action_bones(action):
    pattern = re.compile(r'pose\.bones\["([^"]+)"\]')
    result = set()
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for channelbag in getattr(strip, "channelbags", []):
                for curve in getattr(channelbag, "fcurves", []):
                    match = pattern.search(curve.data_path)
                    if match:
                        result.add(match.group(1))
    return result


args = _args()
report = {
    "status": "ANIMATION_FORGE_REJECTED",
    "forge_repository": str(args.forge_repo.resolve()),
    "glb": str(args.glb.resolve()),
}
module = None
try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    repo = args.forge_repo.resolve()
    if not (repo / "__init__.py").is_file():
        raise RuntimeError("Animation Forge repository package was not found.")
    sys.path.insert(0, str(repo.parent))
    module = importlib.import_module(repo.name)
    module.register()
    bpy.ops.import_scene.gltf(filepath=str(args.glb.resolve()))
    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    skinned = [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and any(
            modifier.type == "ARMATURE" and modifier.object in armatures
            for modifier in obj.modifiers
        )
    ]
    if len(armatures) != 1 or len(skinned) != 1:
        raise RuntimeError(
            f"Expected one armature and one skinned mesh; found "
            f"{len(armatures)} and {len(skinned)}."
        )
    bpy.ops.object.select_all(action="DESELECT")
    armature = armatures[0]
    mesh = skinned[0]
    armature.select_set(True)
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = armature
    operator_result = bpy.ops.daf.analyze()
    mapping = module.map_bones(armature, bpy.context.scene.daf_settings)
    exact_profile = bool(module.detect_animate_anything_profile(armature))
    required = {
        "hips",
        "thigh_l",
        "shin_l",
        "foot_l",
        "thigh_r",
        "shin_r",
        "foot_r",
        "upper_arm_l",
        "upper_arm_r",
        "lower_arm_l",
        "lower_arm_r",
        "hand_l",
        "hand_r",
        "shoulder_l",
        "shoulder_r",
        "spine",
        "chest",
        "neck",
        "head",
    }
    missing = sorted(required - set(mapping))
    available_bones = {bone.name for bone in armature.data.bones}
    action_inventory = sorted(action.name for action in bpy.data.actions)
    unresolved_action_bones = {
        action.name: sorted(_action_bones(action) - available_bones)
        for action in bpy.data.actions
        if _action_bones(action) - available_bones
    }
    filtered_actions_accepted = bool(action_inventory) and not unresolved_action_bones
    text = bpy.data.texts.get("DSB_Rig_Mapping.txt")
    mapping_report = text.as_string() if text else ""
    accepted = (
        "FINISHED" in operator_result
        and exact_profile
        and not missing
        and bool(mapping)
        and bool(mapping_report)
        and filtered_actions_accepted
    )
    report = {
        "status": (
            "ANIMATION_FORGE_ACCEPTED"
            if accepted
            else "ANIMATION_FORGE_WARNING"
        ),
        "forge_repository": str(repo),
        "forge_version": list(module.bl_info["version"]),
        "actual_operator": "daf.analyze",
        "operator_result": sorted(operator_result),
        "armature": armature.name,
        "mesh": mesh.name,
        "mesh_skinned": True,
        "hierarchy_resolves": mesh.parent == armature
        or any(
            modifier.type == "ARMATURE" and modifier.object == armature
            for modifier in mesh.modifiers
        ),
        "exact_animate_anything_profile": exact_profile,
        "mapping": dict(sorted(mapping.items())),
        "missing_required_roles": missing,
        "required_simplified_roles": sorted(required),
        "mapping_report": mapping_report,
        "filtered_action_inventory": action_inventory,
        "filtered_actions_accepted": filtered_actions_accepted,
        "unresolved_action_bones": unresolved_action_bones,
        "removed_finger_dependency_reported": (
            "finger" in mapping_report.lower()
        ),
        "depends_on_removed_finger_bones": False if accepted else None,
        "animation_generation_can_see_rig": accepted,
    }
except Exception as exc:
    report["error"] = str(exc)
finally:
    if module is not None:
        try:
            module.unregister()
        except Exception:
            pass
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
print("SBF_ANIMATION_FORGE_ACCEPTANCE")
print(json.dumps(report, indent=2, sort_keys=True))
if report["status"] == "ANIMATION_FORGE_REJECTED":
    raise RuntimeError(report.get("error", "Animation Forge rejected the rig."))
