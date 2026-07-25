"""Validate a prepared SPAR3D target through fitted-skeleton preview."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy


argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
parser = argparse.ArgumentParser()
target_group = parser.add_mutually_exclusive_group(required=True)
target_group.add_argument("--target", type=Path)
target_group.add_argument("--target-blend", type=Path)
parser.add_argument("--addon", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args(argv)

addon_path = str(args.addon.resolve())
if addon_path not in sys.path:
    sys.path.insert(0, addon_path)

existing_addon = sys.modules.get("skin_and_bones_forge")
if existing_addon is not None and hasattr(existing_addon, "unregister"):
    try:
        existing_addon.unregister()
    except RuntimeError:
        pass
for module_name in list(sys.modules):
    if module_name == "skin_and_bones_forge" or module_name.startswith(
        "skin_and_bones_forge."
    ):
        del sys.modules[module_name]

import skin_and_bones_forge  # noqa: E402
from skin_and_bones_forge.constants import RIG_PREVIEW_COLLECTION  # noqa: E402
from skin_and_bones_forge.rigging.analysis import topology_snapshot  # noqa: E402


def finished(result, name):
    if "FINISHED" not in result:
        raise AssertionError(f"{name} failed: {result}")


canonical = next(
    (obj for obj in bpy.data.objects if obj.type == "ARMATURE"), None
)
if canonical is None:
    raise AssertionError("The opened canonical fixture contains no armature.")

if args.target_blend:
    with bpy.data.libraries.load(
        str(args.target_blend.resolve()), link=False
    ) as (source_data, destination_data):
        candidates = [
            name
            for name in source_data.objects
            if name == "SBF_CLEAN_CHARACTER"
            or name.startswith("SBF_CLEAN_CHARACTER_")
        ]
        destination_data.objects = candidates[:1]
    targets = [obj for obj in destination_data.objects if obj is not None]
    for obj in targets:
        bpy.context.scene.collection.objects.link(obj)
else:
    before = {obj.as_pointer() for obj in bpy.data.objects}
    finished(
        bpy.ops.import_scene.gltf(filepath=str(args.target.resolve())),
        "prepared target import",
    )
    targets = [
        obj
        for obj in bpy.data.objects
        if obj.as_pointer() not in before and obj.type == "MESH"
    ]
if len(targets) != 1:
    raise AssertionError(f"Expected one prepared target mesh, found {len(targets)}.")
target = targets[0]
target_before = topology_snapshot(target)

skin_and_bones_forge.register()
try:
    settings = bpy.context.scene.sbf_settings
    settings.canonical_armature = canonical
    settings.target_object = target
    settings.forward_axis = "+Y"
    settings.up_axis = "+Z"
    finished(bpy.ops.sbf.analyze_canonical_rig(), "canonical analysis")
    finished(bpy.ops.sbf.analyze_target_humanoid(), "rigging geometry analysis")
    target_analysis = json.loads(settings.target_analysis_json)["analysis"]
    if target_analysis["connected_components"] != 1:
        raise AssertionError(
            "Prepared target still reports fragmented rigging geometry."
        )
    finished(bpy.ops.sbf.generate_rig_landmarks(), "landmark preview")
    finished(bpy.ops.sbf.fit_skeleton_preview(), "fitted skeleton preview")
    finished(bpy.ops.sbf.validate_fitted_skeleton(), "fitted skeleton validation")
    collection = bpy.data.collections.get(RIG_PREVIEW_COLLECTION)
    fitted = next(
        (obj for obj in collection.objects if obj.type == "ARMATURE"), None
    ) if collection else None
    if fitted is None:
        raise AssertionError("Fitted skeleton preview was not created.")
    if topology_snapshot(target) != target_before:
        raise AssertionError("Fitted skeleton workflow changed protected target topology.")
    result = {
        "status": "PASS",
        "blender_version": bpy.app.version_string,
        "target": target.name,
        "vertices": len(target.data.vertices),
        "polygons": len(target.data.polygons),
        "rigging_connected_components": target_analysis["connected_components"],
        "bone_heat_risk": target_analysis["bone_heat_risk"],
        "fitted_bones": len(fitted.data.bones),
        "fitted_validation_state": settings.rig_validation_state,
        "target_topology_unchanged": True,
    }
finally:
    if hasattr(bpy.types.Scene, "sbf_settings"):
        skin_and_bones_forge.unregister()

args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("SBF_SPAR3D_DOWNSTREAM_RIG_OK")
print(json.dumps(result, indent=2, sort_keys=True))
