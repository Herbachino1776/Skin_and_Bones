"""Capture deformation evidence from the unmodified failing Blender fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy


def _arguments():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--mesh", default="geometry_0")
    parser.add_argument("--armature", default="SBF_ProductionRig")
    parser.add_argument("--action", default="DSB_DRAFT_Walk")
    return parser.parse_args(argv)


args = _arguments()
addon = str((Path.cwd() / "addon").resolve())
if addon not in sys.path:
    sys.path.insert(0, addon)
for module_name in list(sys.modules):
    if module_name == "skin_and_bones_forge" or module_name.startswith(
        "skin_and_bones_forge."
    ):
        del sys.modules[module_name]

from skin_and_bones_forge.rigging.deformation import (  # noqa: E402
    audit_bind_space,
    scan_action_deformation,
)


mesh = bpy.data.objects.get(args.mesh)
armature = bpy.data.objects.get(args.armature)
action = bpy.data.actions.get(args.action)
if mesh is None or mesh.type != "MESH":
    raise RuntimeError(f"Baseline mesh was not found: {args.mesh}")
if armature is None or armature.type != "ARMATURE":
    raise RuntimeError(f"Baseline armature was not found: {args.armature}")
if action is None:
    raise RuntimeError(f"Baseline Action was not found: {args.action}")

animation = armature.animation_data
report = {
    "status": "BASELINE_CAPTURED",
    "source_blend": str(Path(bpy.data.filepath).resolve()),
    "blender": bpy.app.version_string,
    "mesh": mesh.name,
    "armature": armature.name,
    "action": action.name,
    "active_object": (
        bpy.context.view_layer.objects.active.name
        if bpy.context.view_layer.objects.active
        else None
    ),
    "selected_objects": sorted(obj.name for obj in bpy.context.selected_objects),
    "active_action": (
        animation.action.name if animation and animation.action else None
    ),
    "nla_tracks": [
        {
            "name": track.name,
            "mute": bool(track.mute),
            "solo": bool(track.is_solo),
            "strips": [
                strip.action.name if strip.action else None
                for strip in track.strips
            ],
        }
        for track in (animation.nla_tracks if animation else [])
    ],
    "bind_space": audit_bind_space(bpy.context, mesh, armature),
    "deformation": scan_action_deformation(
        bpy.context,
        mesh,
        armature,
        action,
    ),
}
args.report.parent.mkdir(parents=True, exist_ok=True)
args.report.write_text(
    json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(
    "SBF_BASELINE_RESULT",
    json.dumps(
        {
            "status": report["deformation"]["status"],
            "first_unsafe_frame": report["deformation"]["first_unsafe_frame"],
            "worst_frame": report["deformation"]["worst_frame"],
            "maximum_edge_stretch_ratio": report["deformation"][
                "maximum_edge_stretch_ratio"
            ],
            "maximum_bounds_ratio": report["deformation"][
                "maximum_bounds_ratio"
            ],
            "report": str(args.report.resolve()),
        },
        sort_keys=True,
    ),
)
