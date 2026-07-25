"""Print rig/mesh facts for a .blend or imported GLB.

Run inside Blender.  Pass ``--glb PATH`` to clear the scene and import a GLB.
This is intentionally read-only and is useful when preparing local rig fixtures.
"""

from __future__ import annotations

import argparse
import json
import sys

import bpy
from mathutils import Vector


def _args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--glb")
    return parser.parse_args(argv)


def _rounded(values):
    return [round(float(value), 6) for value in values]


def _mesh_summary(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
        minimum = Vector((min(point[i] for point in points) for i in range(3)))
        maximum = Vector((max(point[i] for point in points) for i in range(3)))
    finally:
        evaluated.to_mesh_clear()
    return {
        "name": obj.name,
        "data": obj.data.name,
        "parent": obj.parent.name if obj.parent else None,
        "vertices": len(obj.data.vertices),
        "edges": len(obj.data.edges),
        "polygons": len(obj.data.polygons),
        "loops": len(obj.data.loops),
        "bounds_min": _rounded(minimum),
        "bounds_max": _rounded(maximum),
        "world_height_z": round(maximum.z - minimum.z, 6),
        "uv_layers": [layer.name for layer in obj.data.uv_layers],
        "materials": [
            slot.material.name if slot.material else None for slot in obj.material_slots
        ],
        "vertex_groups": [group.name for group in obj.vertex_groups],
        "modifiers": [
            {
                "name": modifier.name,
                "type": modifier.type,
                "object": (
                    modifier.object.name
                    if hasattr(modifier, "object") and modifier.object
                    else None
                ),
            }
            for modifier in obj.modifiers
        ],
    }


def _armature_summary(obj):
    actions = []
    for action in bpy.data.actions:
        actions.append(
            {
                "name": action.name,
                "frame_range": _rounded(action.frame_range),
                "slots": len(action.slots),
            }
        )
    nla = []
    if obj.animation_data:
        for track in obj.animation_data.nla_tracks:
            nla.append(
                {
                    "name": track.name,
                    "mute": track.mute,
                    "strips": [
                        {"name": strip.name, "action": strip.action.name if strip.action else None}
                        for strip in track.strips
                    ],
                }
            )
    return {
        "name": obj.name,
        "data": obj.data.name,
        "parent": obj.parent.name if obj.parent else None,
        "pose_position": obj.data.pose_position,
        "display_type": obj.display_type,
        "matrix_world": [_rounded(row) for row in obj.matrix_world],
        "bones": [
            {
                "name": bone.name,
                "parent": bone.parent.name if bone.parent else None,
                "deform": bone.use_deform,
                "connected": bone.use_connect,
                "head": _rounded(bone.head_local),
                "tail": _rounded(bone.tail_local),
                "roll": round(float(bone.matrix_local.to_3x3().to_euler("XYZ").y), 6),
                "length": round(float(bone.length), 6),
            }
            for bone in obj.data.bones
        ],
        "active_action": (
            obj.animation_data.action.name
            if obj.animation_data and obj.animation_data.action
            else None
        ),
        "actions": actions,
        "nla": nla,
    }


args = _args()
if args.glb:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=args.glb)

summary = {
    "blender": bpy.app.version_string,
    "filepath": bpy.data.filepath,
    "objects": [
        {
            "name": obj.name,
            "type": obj.type,
            "parent": obj.parent.name if obj.parent else None,
            "scale": _rounded(obj.scale),
        }
        for obj in bpy.data.objects
    ],
    "meshes": [_mesh_summary(obj) for obj in bpy.data.objects if obj.type == "MESH"],
    "armatures": [
        _armature_summary(obj) for obj in bpy.data.objects if obj.type == "ARMATURE"
    ],
}
print("SBF_RIG_ASSET_JSON_BEGIN")
print(json.dumps(summary, indent=2, sort_keys=True))
print("SBF_RIG_ASSET_JSON_END")
